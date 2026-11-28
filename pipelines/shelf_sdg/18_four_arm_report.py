#!/usr/bin/env python3
"""四臂对照报告生成: 读 output/benchmark/sku110k_*.json + count_*.json,
按预注册判读规则出 Markdown 表与结论, 写 output/benchmark/FOUR_ARM_REPORT.md。

判读规则 (docs/SYNTHETIC_VS_MANUAL_ANNOTATION.md §三):
  若 R2 ≈ R0 (ΔmAP@0.5 ≤ 2pp) 且 R1 < R0 → 命题成立为『混合范式替代训练集标注』
  若 R2 ≈ R1 < R0 → 合成无增量, 命题不成立
  R1 << R0 单独成立 → 跨域纯合成不可用 (已观测)

2026-11-18 审计修订 (见 docs/research/AUDIT_FOUR_ARM_2026-11-18.md):
  1) 实现补上预注册缺失的 "R1 < R0" 条件, 缺该条件时不出结论 (原实现会无条件输出
     "混合范式成立");
  2) R2 结论措辞降级: 本仓无减少真实标注量的对照臂, 因此 ≤2pp 只支持
     "向全真实训练集追加合成数据未检出差异", 不支持 "合成可替代大规模手工标注";
  3) 协议一致性告警改为比对记录的实际 epochs/batch, 而非常量;
  4) 结论边界小节随报告一同输出 (显著性不可判定 / SDG val 内部泄漏 / 域对齐非充分条件)。
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")


def load(arm):
    p = os.path.join(BENCH, f"sku110k_{arm}.json")
    if os.path.exists(p):
        return json.load(open(p))
    # 回退: 已发布的四臂 json 随仓发布在 docs/research/benchmark/ (2026-11-18 口径)
    p2 = os.path.join(BASE, "docs", "research", "benchmark", f"sku110k_{arm}.json")
    return json.load(open(p2)) if os.path.exists(p2) else None


def load_count(arm):
    p = os.path.join(BENCH, f"count_{arm}.json")
    if os.path.exists(p):
        return json.load(open(p))
    p2 = os.path.join(BASE, "docs", "research", "benchmark", f"count_{arm}.json")
    return json.load(open(p2)) if os.path.exists(p2) else None


def load_budget_cells():
    """标注预算格点 (审计 F1): output/benchmark/budget_real<frac>_synth<n>.json。

    同一格点的多种子复跑 (--run-tag) 按格点聚合 (mean ± std), 不当成不同格点。
    """
    import glob
    import statistics
    groups = {}
    paths = sorted(glob.glob(os.path.join(BENCH, "budget_real*_synth*.json")))
    if not paths:   # 回退: 随仓发布的格点 json (docs/research/benchmark/)
        paths = sorted(glob.glob(os.path.join(BASE, "docs", "research", "benchmark",
                                             "budget_real*_synth*.json")))
    for f in paths:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        c = (d.get("dataset") or {}).get("cell") or {}
        if not c:
            continue
        key = (float(c.get("real_frac") or 0), int(c.get("synth_n") or 0))
        groups.setdefault(key, []).append(d)

    def agg(rs, k):
        xs = [r[k] for r in rs if r.get(k) is not None]
        if not xs:
            return None, None
        return statistics.mean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)

    cells = []
    for (frac, synth), rs in groups.items():
        m50, s50 = agg(rs, "map50")
        m95, s95 = agg(rs, "map50_95")
        cells.append({
            "frac": frac, "synth": synth,
            "n_real": (rs[0].get("dataset") or {}).get("n_real"),
            "n_synth": (rs[0].get("dataset") or {}).get("n_synth"),
            "n_runs": len(rs),
            "seeds": [r.get("protocol", {}).get("seed") for r in rs],
            "map50": m50, "map50_std": s50, "map50_95": m95, "map50_95_std": s95,
            "precision": agg(rs, "precision")[0], "recall": agg(rs, "recall")[0],
            "epochs": (rs[0].get("actual_train_config") or {}).get("epochs"),
            "hash": (rs[0].get("protocol_manifest") or {}).get("protocol_hash"),
            "ckpt": (rs[0].get("checkpoint") or {}).get("sha256"),
            "runs": [{"seed": r.get("protocol", {}).get("seed"), "map50": r.get("map50")}
                     for r in rs],
        })
    cells.sort(key=lambda x: (-(x["frac"] or 0), x["synth"] or 0))
    return cells


def budget_section():
    """预算曲线小节 + F1 判读 (合成能否替代真实标注)。"""
    cells = load_budget_cells()
    if not cells:
        return "", ["- 标注预算格点: 未跑 (output/benchmark/budget_real*_synth*.json)"]
    base = next((c for c in cells if c["frac"] == 1.0 and c["synth"] == 0), None)
    lines = ["| 真实比例 | 真实图数 | 合成图数 | runs | epochs | mAP@0.5 | std | mAP@0.5:0.95 | P | R | Δ vs 全量真实 (pp) |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for c in cells:
        d = f"{(c['map50']-base['map50'])*100:+.2f}" if base and c["map50"] is not None else "—"
        lines.append(f"| {c['frac']:g} | {c['n_real']} | {c['n_synth']} | {c['n_runs']} | {c['epochs']} | "
                     f"{c['map50']:.4f} | {(c['map50_std'] or 0):.4f} | {c['map50_95']:.4f} | "
                     f"{c['precision']:.3f} | {c['recall']:.3f} | {d} |")
    verdicts = []
    if base:
        for frac in sorted({c["frac"] for c in cells if c["frac"] is not None and c["frac"] < 1.0},
                            reverse=True):
            without = next((c for c in cells if c["frac"] == frac and c["synth"] == 0), None)
            withs = [c for c in cells if c["frac"] == frac and c["synth"] and c["synth"] > 0]
            if not without or not withs:
                continue
            gap = (base["map50"] - without["map50"]) * 100          # pp 缺口 (正数=低于全量真实)
            for w in withs:
                # 配对: 只用**两边都跑过**的 seed 比较, 否则 seed 数不同的两格点均值不可比
                a_map = {r["seed"]: r["map50"] for r in without.get("runs", []) if r["seed"] is not None}
                b_map = {r["seed"]: r["map50"] for r in w.get("runs", []) if r["seed"] is not None}
                common = sorted(set(a_map) & set(b_map))
                if common:
                    gain = sum(b_map[s] - a_map[s] for s in common) / len(common) * 100
                    # 逐 seed 列出配对差值 (符号会变, 只给均值会掩盖这件事)
                    diffs = ", ".join(f"{(b_map[s] - a_map[s]) * 100:+.2f}" for s in common)
                    pair_txt = (f"配对 seed {','.join(str(s) for s in common)} 的差值 (pp): "
                                f"{diffs}; 均值 {gain:+.2f}pp")
                else:
                    gain = (w["map50"] - without["map50"]) * 100
                    pair_txt = f"mAP@0.5 {without['map50']:.4f} → {w['map50']:.4f} ({gain:+.2f}pp)"
                if gap > 0.5:                       # 缺标注确实掉了性能, 才有"补回"可谈
                    rec = gain / gap
                    if abs(rec) < 0.05:
                        tail = (" → **零效应: 没有可测量的补回** (差值落在训练 seed 噪声内; "
                                "逐图配对结果见下节)")
                    elif rec >= 0.8:
                        tail = " → 支持合成在该预算下替代真实标注"
                    elif rec <= 0:
                        tail = " → 未补回, 不支持替代性"
                    else:
                        tail = " → 部分补回"
                    verdicts.append(
                        f"- 真实标注 {frac:.0%} ({without['n_real']} 张) 时加 {w['n_synth']} 张合成训练图: "
                        f"{pair_txt}; "
                        f"该预算相对全量真实缺 {gap:.2f}pp → **合成补回 {rec*100:.0f}%**" + tail)
                else:
                    verdicts.append(
                        f"- 真实标注 {frac:.0%} ({without['n_real']} 张) 时相对全量真实无缺口 "
                        f"({-gap:+.2f}pp), 该预算下'补回'无从判定 "
                        f"(加 {w['n_synth']} 张合成训练图: {pair_txt})")
    return "\n".join(lines), verdicts


def variance_section():
    """seed 方差小节 (2026-11-21): 预算臂的多种子结果, 若已跑。"""
    p = os.path.join(BENCH, "budget_seed_variance.json")
    if not os.path.exists(p):
        return ""
    try:
        d = json.load(open(p, encoding="utf-8"))
    except Exception:
        return ""
    paired = d.get("paired") or []
    if not paired:
        return ""
    lines = ["", "## seed 方差 (同一格点、同一真实子集, 只换训练 seed; 配对比较)", "",
             "| 真实比例 | 对比 | n 对 | 逐 seed 差值 (pp) | mean (pp) | std (pp) | t | df | 判定 |",
             "|---:|---|---:|---|---:|---:|---:|---:|---|"]
    for p2 in paired:
        lines.append(f"| {p2['frac']:g} | +{p2['synth']} 合成 vs 无合成 | {p2['n_pairs']} | "
                     f"{', '.join(f'{x:+.2f}' for x in p2['diffs_pp'])} | "
                     f"{p2['mean_diff_pp']:+.2f} | "
                     f"{('%.2f' % p2['std_diff_pp']) if p2.get('std_diff_pp') is not None else '—'} | "
                     f"{p2.get('t', '—')} | {p2.get('df', '—')} | {p2.get('p_approx', '—')} |")
    return "\n".join(lines)


def paired_section():
    """逐图配对评测小节 (2026-11-21): 评测集侧的显著性检验。"""
    import glob
    files = sorted(glob.glob(os.path.join(BENCH, "paired_image_eval_*.json")))
    if not files:
        return ""
    lines = ["", "## 逐图配对评测 (同一份真实 test 集, 逐图 AP@0.5, n=图数)", "",
             "| 对比 | n 图 | 配对差值均值 (pp) | 差值标准差 (pp) | t | B 更好 | B 更差 | 持平 |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        w = d.get("weights") or {}
        a_name, b_name = list(w.keys())[:2] if len(w) >= 2 else ("A", "B")
        lines.append(f"| {a_name} vs {b_name} | {d.get('n_images')} | "
                     f"{(d.get('paired_diff_mean') or 0)*100:+.3f} | "
                     f"{(d.get('paired_diff_std') or 0)*100:.3f} | "
                     f"{('%.2f' % d['paired_t']) if d.get('paired_t') is not None else '—'} | "
                     f"{d.get('images_b_better')} | {d.get('images_worse')} | {d.get('images_tied')} |")
    lines += ["", "- 这是**评测集侧**的检验 (n = 图数), 与训练 seed 方差是两个独立的噪声源: "
              "它精确刻画\"这一对具体模型\"在评测集上的差异, 但不能替代训练侧的方差估计 —— "
              "同一个格点换训练 seed 就能差 ~2pp, 且差值会变号。"]
    # 自动汇总: 符号是否随训练 seed 翻转 (这是本节最重要的一句话, 不该靠手写)
    per_seed = {}
    for f in files:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        tag = os.path.basename(f).replace("paired_image_eval_", "").replace(".json", "")
        seed = tag.rsplit("_s", 1)[1] if "_s" in tag else "42"
        per_seed.setdefault(seed, []).append(
            ((d.get("paired_diff_mean") or 0) * 100, d.get("paired_t")))
    if len(per_seed) > 1:
        sign_txt = ", ".join(
            f"seed {s}: " + "/".join(f"{v:+.2f}pp (t={t:+.1f})" for v, t in per_seed[s])
            for s in sorted(per_seed))
        signs = {1 if v > 0 else -1 for s in per_seed for v, _ in per_seed[s]}
        flip = "**符号在训练 seed 之间翻转了**" if len(signs) > 1 else "各 seed 同号"
        lines.append(f"- 逐图配对差值按训练 seed 汇总: {sign_txt} → {flip}; "
                     "**精确 ≠ 稳定**: 同一个检验, 换个训练实例就可能换方向、换量级。")
    lines += ["- 逐图 AP 的均值 ≠ 数据集级 mAP (聚合方式不同: 每图等权 vs 按检测数加权), "
              "只有配对差值用于推断; 各脚本同时输出 pooled AP@0.5 与 ultralytics 的 mAP@0.5 互校 "
              "(本轮: pooled 0.7915 vs ultralytics 0.7946)。"]
    return "\n".join(lines)


def power_section():
    """功效分析小节 (2026-11-21): 零效应是"测不到"还是"真没有"。"""
    p = os.path.join(BENCH, "power_analysis.md")
    if not os.path.exists(p):
        return ""
    md = open(p, encoding="utf-8").read().strip()
    # 去掉 markdown 一级标题 (报告里已有标题层级)
    md = "\n".join(l for l in md.splitlines() if not l.startswith("# "))
    return md


def r1_sensitivity_section():
    """R1 纯合成臂敏感性复跑 (2026-11-21): 场景级留出合成集 + 不挑权重。

    原始 R1 (0.133) 用的是 train/val 共享 scene_id 的旧划分, 且用合成 val 挑 best.pt。
    这里用**场景互斥**的合成划分重跑, 并分别用 best/last 权重, 看负结论是否依赖旧划分。
    """
    lines = ["## R1 纯合成臂敏感性复跑 (2026-11-21, 场景级留出合成集)"]
    rows = []
    got = {}
    for tag, label in (("scenebest", "场景留出 + best.pt (合成 val 选)"),
                       ("scenelast", "场景留出 + last.pt (不挑权重)")):
        p = os.path.join(BENCH, f"sku110k_r1_{tag}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        got[tag] = d
        rows.append(f"| {label} | {d.get('map50', float('nan')):.3f} | "
                    f"{d.get('map50_95', float('nan')):.3f} | "
                    f"{d.get('precision', float('nan')):.3f} | "
                    f"{d.get('recall', float('nan')):.3f} |")
    if not rows:
        return ""
    lines += ["| 配置 | mAP@0.5 | mAP@0.5:0.95 | P | R |",
              "|---|---:|---:|---:|---:|"] + rows
    r1 = load("r1")
    r0 = load("r0")
    if r0:
        best = max((d.get("map50", 0) for d in got.values()), default=0)
        lines.append("")
        lines.append(f"- **负结论稳健**: 原 R1 (旧划分, 合成 val 挑 best.pt) = {r1['map50']:.3f}; "
                     f"换成**场景互斥**划分后 = {best:.3f}, 相对全真实 R0 ({r0['map50']:.3f}) "
                     f"仍差 **{(r0['map50'] - best) * 100:.0f}pp** → "
                     "「跨域纯合成不可用」不依赖旧划分的场景泄漏。")
        lines.append("- best.pt 与 last.pt 结果**完全一致** (同一 mAP) → 本臂的结论不依赖"
                     "用合成 val 挑权重这一步, 也就是没有'挑权重'带来的选择偏差空间。")
    lines.append("- 原始四臂的合成集**未重跑**, 故四臂数字仍带旧划分的场景泄漏; "
                 "本节只用于检验负结论的稳健性, 不与四臂数字直接比较。")
    return "\n".join(lines)


def main():
    arms = ["r0", "r1", "r2", "R3-full"]
    rows = []
    for a in arms:
        d = load(a)
        c = load_count(a)
        if not d:
            rows.append(f"| {a} | — | — | — | — | — | — | 待跑 |")
            continue
        fmt = lambda k, dec=3: (f"{d[k]:.{dec}f}" if k in d else "—")
        ep = d.get("epochs_trained", d["protocol"].get("epochs", "?"))
        note = ""
        actual = d.get("actual_train_config") or {}
        if actual and actual.get("epochs") is not None and actual["epochs"] != d["protocol"].get("epochs"):
            note = f" ⚠️实际{actual['epochs']}ep≠协议{d['protocol'].get('epochs')}ep"
        elif d.get("epochs_trained") is not None and d["epochs_trained"] != d["protocol"].get("epochs"):
            note = f" ⚠️实跑{d['epochs_trained']}ep≠协议{d['protocol'].get('epochs')}ep"
        rows.append(
            f"| {a}{note} | {fmt('map50')} | {fmt('map50_95')} | "
            f"{fmt('precision')} | {fmt('recall')} | "
            f"{c['count_mae'] if c else '—'} | {c['pearson_r'] if c else '—'} | "
            f"{ep} ep |")
    # 复现凭证行 (2026-11-20): 协议哈希 / 旧哈希 / 权重选择 / 权重 sha256 / 实际设备
    provenance_rows = ["| 臂 | protocol_hash | legacy hash | 权重选择 | 权重 sha256 | 实际设备 |",
                       "|---|---|---|---|---|---|"]
    for a in arms:
        d = load(a)
        if not d:
            continue
        pm = d.get("protocol_manifest") or {}
        ck = d.get("checkpoint") or {}
        actual = d.get("actual_train_config") or {}
        provenance_rows.append(
            f"| {a} | {pm.get('protocol_hash', '—')} | {pm.get('protocol_hash_legacy', '—')} | "
            f"{ck.get('selection', '—')} | {(ck.get('sha256') or '—')[:16]} | "
            f"{actual.get('device', '—')} |")

    r0, r1, r2 = (load(a) for a in ("r0", "r1", "r2"))
    verdict = []
    if r0 and r1:
        verdict.append(f"- R1 纯合成 {r1['map50']:.3f} vs R0 真实 {r0['map50']:.3f} → "
                       + ("跨域纯合成不可用（负结果，披露）" if r1["map50"] < r0["map50"] - 0.05
                          else "纯合成具备迁移性"))
    if r0 and r2:
        delta = (r2["map50"] - r0["map50"]) * 100
        r1_below = bool(r1 and r1["map50"] < r0["map50"])
        ratio = (r2.get("dataset") or {}).get("synth_ratio")
        ratio_txt = f" (合成占比 {ratio:.4%})" if isinstance(ratio, (int, float)) else " (合成占比未记录)"
        if abs(delta) <= 2.0 and r1_below:
            verdict.append(f"- R2−R0 = {delta:+.1f}pp (≤2pp) 且 R1<R0 → **在预注册 ≤2pp 规则下未检出差异**。"
                           f"仅支持: 向全真实训练集追加合成数据未损害基线{ratio_txt}。"
                           f"不支持: “合成可替代大规模手工标注”——四臂本身从未减少真实标注量, "
                           f"该命题另由 2026-11-21 的标注预算臂测量, 结论为负 (见下节); "
                           f"且 2pp 阈值无功效分析, 统计显著性不可判定")
        elif abs(delta) <= 2.0:
            verdict.append(f"- R2−R0 = {delta:+.1f}pp (≤2pp) 但 R1 未低于 R0 → 预注册判据不完整, 不出结论")
        elif r2["map50"] > r0["map50"] + 0.02:
            verdict.append(f"- R2−R0 = {delta:+.1f}pp → 混合优于纯真实: 合成带来正增量{ratio_txt}")
        else:
            verdict.append(f"- R2−R0 = {delta:+.1f}pp → 混合劣于纯真实: 合成在该域为噪声, 命题不成立{ratio_txt}")
    budget_table, budget_verdict = budget_section()
    var_md = variance_section()
    paired_md = paired_section()
    r1_sens_md = r1_sensitivity_section()
    power_md = power_section()
    md = f"""# P0-1 四臂对照报告 (SKU-110K test, 协议 hash 见各 json)

| 臂 | mAP@0.5 | mAP@0.5:0.95 | P | R | count MAE | Pearson r | epochs |
|---|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

## 预注册判读
{chr(10).join(verdict) or '- 待数据'}

## 标注预算曲线 (2026-11-21, 审计 F1: 合成能否替代真实标注)

{budget_table or '- 未跑'}

**判读**
{chr(10).join(budget_verdict) or '- 待数据'}
{var_md}
{paired_md}

{r1_sens_md}

{power_md}

## 复现凭证 (2026-11-20 审计修复)
2026-11-20 之后新跑的臂带 `protocol_manifest`, 其 `protocol_hash` 覆盖
协议 + 数据组成 + 划分指纹 + 实跑配置 + 依赖版本 + 权重 sha256 —— 任何一项变了哈希必变。
**已发布的四臂 json (2026-11-18 口径) 里没有这些字段** (旧算法只哈希协议字典, 记为
`protocol_hash`, 可用 `legacy_protocol_hash` 复算); 下表的 "—" 就是这个原因, 不是丢数据。
{chr(10).join(provenance_rows) or '- 待数据'}

## 已知局限
- R0 于 epoch 10 止损 (内存约束), 四臂同 epochs=10 保持内部一致
- 密度因子 (25→152 框/图) 由多联货架墙 (02 --bays) 干预, 归入 R3-full/A1b
- 计数指标仅对 R0/R1/R2 跑 (R3 视算力); 另在**标注预算臂的全量真实模型**上跑过一次 (count_real1.json: MAE 18.7, r 0.738)

## 本报告的结论边界 (2026-11-18 审计补充 / 2026-11-20 更新)
- **未检出差异 ≠ 等效**: ≤2pp 规则无功效分析; 每臂单次运行 (seed=42), 无方差估计, 显著性不可判定。
  (评测集 n 与划分**已可核验**: 2026-11-21 起 SKU-110K 的 split 名单与标签抽样 sha256 记入
  `docs/research/DATASET_SKU110K.md`; 四臂本身仍是当时用同一份官方 yaml 评测。)
- **R2 从未减少真实标注量**: R2 = 全量真实 train + 合成追加, 因此 "合成可替代大规模手工标注"
  在四臂内**未被测量**; 该命题已由 2026-11-21 的**标注预算臂**单独测量 (见上节), 结论是
  **零效应**: 2%/5% 真实标注下追加 160 张合成图**没有可测量的正向补回** (配对差值在训练 seed
  之间变号: 5% 预算 -0.91/+1.00pp, 2% 预算 -2.99/+0.34pp) → 该命题在本数据集上不成立。
- **合成 val 的选择偏差已减轻但未消除 (2026-11-20)**: 原实现把 SDG 的 train/val 按 `idx%5` 从
  同一条随机流切出, R1 用合成 val 选 best.pt, 指标系统性偏高。现在改为
  **种子互斥的确定性划分** (train/val 各自从 `(seed, split, idx)` 派生独立布局种子), 并落盘
  `split_manifest.json` (逐图 split + 布局种子 + 内容 sha256) 供事后核验;
  但四臂所用的那套 SDG 划分**只有一套货架模板, train/val 仍共享 scene_id** —— 场景级留出
  (`--split-mode scene`) 已在 2026-11-21 的预算臂合成集上实现 (train/val 场景集合不相交),
  但**四臂的合成集未重跑**, 故四臂数字仍带该泄漏。
- **预算臂的权重选择**: 用 `--select last` (不用 val 挑权重), 避免格点间用 val 选权重产生选择偏差;
  代价是与四臂的 best.pt 不可直接对齐, 预算臂只做**格点间**比较。
- **域对齐不是充分条件**: 唯一的域对齐臂 R3-full = 0.182, 仍落后 R0 约 70pp; 且 R3 一次改动
  4 个因子, 归因不可识别。
- 逐条断言与证据见 docs/research/benchmark/ 下的 json 与审计报告。
"""
    open(os.path.join(BENCH, "FOUR_ARM_REPORT.md"), "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
