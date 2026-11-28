#!/usr/bin/env python3
"""预算臂的 seed 方差分析 (2026-11-21)。

背景: 预算臂每格点只跑了一次, 审计里"统计显著性不可判定"这条限制一直挂着。
本脚本把同一格点的多个训练 seed 汇总成 mean ± std, 并对"加合成 vs 不加合成"做**配对**比较
(同一格点、同一批真实子集, 只换训练 seed), 给出差值的均值、标准差与 t 值。

读: output/benchmark/budget_real*_synth*.json (含 --run-tag 后缀的多次运行)
写: output/benchmark/budget_seed_variance.{md,json}
"""
import glob
import json
import math
import os
import re
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")

TAG_RE = re.compile(r"^budget_real([\d.]+)_synth(\d+)(?:_(.+))?\.json$")
FULL_CELL = (1.0, 0)      # 全量真实格点 (100% 真实标注, 无合成)


def load_cells():
    cells = {}
    for f in sorted(glob.glob(os.path.join(BENCH, "budget_real*_synth*.json"))):
        m = TAG_RE.match(os.path.basename(f))
        if not m:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        c = d["dataset"]["cell"]
        key = (float(c["real_frac"]), int(c["synth_n"]))
        seed = d.get("protocol", {}).get("seed")
        cells.setdefault(key, []).append({
            "seed": seed, "tag": m.group(3) or f"s{seed}",
            "map50": d["map50"], "map50_95": d["map50_95"],
            "precision": d["precision"], "recall": d["recall"],
            "n_real": d["dataset"]["n_real"], "n_synth": d["dataset"]["n_synth"],
            "real_subset_sha256": d["dataset"].get("real_subset_sha256"),
            "synth_subset_sha256": d["dataset"].get("synth_subset_sha256"),
            "protocol_hash": d.get("protocol_hash"),
            "ckpt_sha256": (d.get("checkpoint") or {}).get("sha256"),
        })
    for k in cells:
        cells[k].sort(key=lambda r: (r["seed"] is None, r["seed"]))
    return cells


def mean_std(xs):
    if not xs:
        return None, None
    m = statistics.mean(xs)
    s = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, s


T_CRIT_05 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306}


def paired(cells, frac, synth_a, synth_b):
    """同一格点内, 用同一批训练 seed 配对比较 synth_b 相对 synth_a 的差值。"""
    a = {r["seed"]: r for r in cells.get((frac, synth_a), []) if r["seed"] is not None}
    b = {r["seed"]: r for r in cells.get((frac, synth_b), []) if r["seed"] is not None}
    common = sorted(set(a) & set(b))
    diffs = [(s, b[s]["map50"] - a[s]["map50"], a[s], b[s]) for s in common]
    if not diffs:
        return None
    ds = [d[1] for d in diffs]
    m, sd = mean_std(ds)
    out = {"n_pairs": len(ds), "seeds": [d[0] for d in diffs],
           "diffs_pp": [round(d[1] * 100, 3) for d in diffs],
           "mean_diff_pp": round(m * 100, 3),
           "std_diff_pp": round(sd * 100, 3) if sd is not None else None}
    if len(ds) > 1 and sd > 0:
        df = len(ds) - 1
        t = m / (sd / math.sqrt(len(ds)))
        crit = T_CRIT_05.get(df)
        out["t"] = round(t, 3)
        out["df"] = df
        out["t_crit_0.05"] = crit
        out["p_approx"] = ("<0.05 (双尾)" if crit and abs(t) >= crit
                           else ">0.05 (双尾)" if crit
                           else "n 太小, 只能作方向性判断")
    return out


def paired_vs_full(cells, frac, synth):
    """跨格点配对: (frac, synth) 相对**全量真实** (1.0, 0) 的差值, 按训练 seed 配对。

    数据子集本身不同 (5% vs 100% 真实), 这里配对的是**训练随机性**:
    同一个 seed 上两个模型面对同一个评测集, 差值里只剩"这次训练抽到了什么"和
    "标注量差多少"两部分 —— 前者是噪声 (要估的), 后者是信号 (要报的)。
    """
    full = {r["seed"]: r for r in cells.get(FULL_CELL, []) if r["seed"] is not None}
    other = {r["seed"]: r for r in cells.get((frac, synth), []) if r["seed"] is not None}
    common = sorted(set(full) & set(other))
    if not common:
        return None
    rows = []
    for s in common:
        rows.append({
            "seed": s,
            "map50_diff_pp": round((other[s]["map50"] - full[s]["map50"]) * 100, 3),
            "map50_95_diff_pp": round((other[s]["map50_95"] - full[s]["map50_95"]) * 100, 3),
            "map50_other": other[s]["map50"], "map50_full": full[s]["map50"],
            "map50_95_other": other[s]["map50_95"], "map50_95_full": full[s]["map50_95"],
        })
    out = {"frac": frac, "synth": synth, "n_pairs": len(rows), "rows": rows}
    for key, base in (("map50_diff_pp", "map50"), ("map50_95_diff_pp", "map50_95")):
        ds = [r[key] for r in rows]
        m, sd = mean_std(ds)
        out[f"{base}_diff_mean_pp"] = round(m, 3)
        out[f"{base}_diff_std_pp"] = round(sd, 3) if sd is not None else None
        if len(ds) > 1 and sd and sd > 0:
            df = len(ds) - 1
            t = m / (sd / math.sqrt(len(ds)))
            crit = T_CRIT_05.get(df)
            out[f"{base}_diff_t"] = round(t, 3)
            out[f"{base}_diff_df"] = df
            out[f"{base}_diff_p"] = ("<0.05 (双尾)" if crit and abs(t) >= crit
                                     else ">0.05 (双尾)" if crit else "n 太小")
            if crit:
                # t 临界值 → 差值均值的 95% CI
                half = crit * sd / math.sqrt(len(ds))
                out[f"{base}_diff_ci95"] = [round(m - half, 3), round(m + half, 3)]
    return out


COUNT_TAG_RE = re.compile(r"^count_real([\d.]+)(?:_s(\d+))?\.json$")


def load_counts():
    """计数指标的跨 seed 汇总 (600 张固定抽样, 名单 sha256 相同才可比)。"""
    groups = {}
    for f in sorted(glob.glob(os.path.join(BENCH, "count_real*.json"))):
        m = COUNT_TAG_RE.match(os.path.basename(f))
        if not m:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        frac = float(m.group(1))
        seed = int(m.group(2)) if m.group(2) else 42
        groups.setdefault(frac, []).append({
            "seed": seed,
            "conf": d.get("conf"),
            "count_mae": d.get("count_mae"),
            "count_mape_pct": d.get("count_mape_pct"),
            "pearson_r": d.get("pearson_r"),
            "mean_pred": d.get("mean_pred"),
            "mean_gt": d.get("mean_gt"),
            "sample_sha256": (d.get("sample") or {}).get("names_sha256"),
            "weights_sha256": (d.get("weights") or {}).get("sha256"),
            "file": os.path.basename(f),
        })
    for k in groups:
        groups[k].sort(key=lambda r: r["seed"])
    return groups


def main():
    cells = load_cells()
    if not cells:
        raise SystemExit("[VAR] 没找到任何格点 json")
    lines = ["# 预算臂 seed 方差 (SKU-110K test, 真实子集固定, 只变训练 seed)", "",
             "| 真实比例 | 合成图数 | runs | seeds | mAP@0.5 mean | std | mAP@0.5:0.95 mean | std | 真实子集 sha256 |",
             "|---:|---:|---:|---|---:|---:|---:|---:|---|"]
    summary = {}
    for (frac, synth), runs in sorted(cells.items(), key=lambda kv: (-kv[0][0], kv[0][1])):
        m50, s50 = mean_std([r["map50"] for r in runs])
        m95, s95 = mean_std([r["map50_95"] for r in runs])
        seeds = ", ".join(str(r["seed"]) for r in runs)
        sha = {r.get("real_subset_sha256") for r in runs if r.get("real_subset_sha256")}
        sha_txt = ("一致 ✓" if len(sha) == 1 else
                   ("—" if not sha else f"**不一致 ({len(sha)} 个)**"))
        lines.append(f"| {frac:g} | {synth} | {len(runs)} | {seeds} | "
                     f"{m50:.4f} | {(s50 if s50 is not None else 0):.4f} | "
                     f"{m95:.4f} | {(s95 if s95 is not None else 0):.4f} | {sha_txt} |")
        summary[f"{frac:g}/{synth}"] = {"n": len(runs), "seeds": [r["seed"] for r in runs],
                                        "map50_mean": m50, "map50_std": s50,
                                        "map50_95_mean": m95, "map50_95_std": s95,
                                        "real_subset_sha256": sorted(sha)}
    # 配对比较: 加合成 vs 不加合成
    fracs = sorted({f for f, _ in cells}, reverse=True)
    pairs = []
    lines += ["", "## 配对比较 (同一格点、同一真实子集, 只换训练 seed)", "",
              "| 真实比例 | 对比 | n 对 | 差值 (pp, 逐 seed) | mean (pp) | std (pp) | t | p (近似) |",
              "|---:|---|---:|---|---:|---:|---:|---|"]
    for frac in fracs:
        synths = sorted({s for f, s in cells if f == frac})
        if len(synths) < 2:
            continue
        for sb in synths[1:]:
            p = paired(cells, frac, 0, sb)
            if not p:
                continue
            pairs.append({"frac": frac, "synth": sb, **p})
            lines.append(f"| {frac:g} | +{sb} 合成 vs 无合成 | {p['n_pairs']} | "
                         f"{', '.join(f'{d:+.2f}' for d in p['diffs_pp'])} | "
                         f"{p['mean_diff_pp']:+.2f} | "
                         f"{('%.2f' % p['std_diff_pp']) if p.get('std_diff_pp') is not None else '—'} | "
                         f"{p.get('t', '—')} | {p.get('p_approx', '—')} |")
    n_pairs_max = max([p["n_pairs"] for p in pairs], default=0)
    # 跨格点配对: 相对全量真实的缺口 (按 seed 配对)
    gaps = []
    full_runs = cells.get(FULL_CELL, [])
    n_full = len([r for r in full_runs if r["seed"] is not None])
    if n_full >= 2:
        lines += ["", "## 相对全量真实的缺口 (跨格点, 按训练 seed 配对)", "",
                  "同一 seed 上, 目标格点与**全量真实** (frac=1) 各训一个模型, 在同一个 SKU-110K test 上评测;",
                  "配对消去的是「这次训练抽到了什么」, 剩下的是标注量差带来的**缺口**及其 seed 噪声。",
                  "", "| 格点 | n 对 | mAP@0.5 差值 (pp, 逐 seed) | mean | std | 95% CI | t | p | "
                  "mAP@0.5:0.95 差值 mean (pp) |",
                  "|---|---:|---|---:|---:|---|---:|---|---:|"]
        for (frac, synth), runs in sorted(cells.items(), key=lambda kv: (-kv[0][0], kv[0][1])):
            if (frac, synth) == FULL_CELL:
                continue
            g = paired_vs_full(cells, frac, synth)
            if not g:
                continue
            gaps.append(g)
            ci = g.get("map50_diff_ci95")
            ci_txt = (f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "—")
            lines.append(f"| {frac:g} 真实 +{synth} 合成 | {g['n_pairs']} | "
                         f"{', '.join(f'{r['map50_diff_pp']:+.2f}' for r in g['rows'])} | "
                         f"{g.get('map50_diff_mean_pp', 0):+.2f} | "
                         f"{('%.2f' % g['map50_diff_std_pp']) if g.get('map50_diff_std_pp') is not None else '—'} | "
                         f"{ci_txt} | {g.get('map50_diff_t', '—')} | {g.get('map50_diff_p', '—')} | "
                         f"{g.get('map50_95_diff_mean_pp', 0):+.2f} |")
    # 计数指标的跨 seed 汇总
    counts = load_counts()
    count_summary = {}
    if counts:
        lines += ["", "## 计数指标的跨 seed 波动 (600 张固定抽样, 同一份名单)", "",
                  "| 真实比例 | runs | seeds | count MAE mean | std | MAPE mean | r mean | 抽样名单 sha |",
                  "|---:|---:|---|---:|---:|---:|---:|---|"]
        for frac, runs in sorted(counts.items(), key=lambda kv: -kv[0]):
            m_mae, s_mae = mean_std([r["count_mae"] for r in runs if r["count_mae"] is not None])
            m_mape, _ = mean_std([r["count_mape_pct"] for r in runs if r["count_mape_pct"] is not None])
            m_r, _ = mean_std([r["pearson_r"] for r in runs if r["pearson_r"] is not None])
            sha = {r["sample_sha256"] for r in runs if r["sample_sha256"]}
            sha_txt = ("一致 ✓" if len(sha) == 1 else ("—" if not sha else f"**不一致 ({len(sha)} 个)**"))
            lines.append(f"| {frac:g} | {len(runs)} | "
                         f"{', '.join(str(r['seed']) for r in runs)} | "
                         f"{(m_mae if m_mae is not None else 0):.2f} | "
                         f"{(s_mae if s_mae is not None else 0):.2f} | "
                         f"{(m_mape if m_mape is not None else 0):.2f}% | "
                         f"{(m_r if m_r is not None else 0):.3f} | {sha_txt} |")
            count_summary[f"{frac:g}"] = {
                "n": len(runs), "seeds": [r["seed"] for r in runs],
                "count_mae_mean": m_mae, "count_mae_std": s_mae,
                "count_mape_mean": m_mape, "pearson_r_mean": m_r,
                "runs": runs,
            }
        # 计数指标的缺口: 相对全量真实, 按 seed 配对
        full_counts = {r["seed"]: r for r in counts.get(1.0, [])}
        if len(full_counts) >= 2:
            lines += ["", "### 计数指标的缺口 (相对全量真实, 按 seed 配对)", "",
                      "| 真实比例 | n 对 | count MAE 差值 (逐 seed) | mean | 95% CI | r 差值 mean |",
                      "|---:|---:|---|---:|---|---:|"]
            for frac, runs in sorted(counts.items(), key=lambda kv: -kv[0]):
                if frac == 1.0:
                    continue
                other = {r["seed"]: r for r in runs}
                common = sorted(set(full_counts) & set(other))
                if not common:
                    continue
                ds = [other[s]["count_mae"] - full_counts[s]["count_mae"] for s in common]
                rs = [other[s]["pearson_r"] - full_counts[s]["pearson_r"] for s in common]
                m, sd = mean_std(ds)
                ci = "—"
                if len(ds) > 1 and sd and sd > 0:
                    crit = T_CRIT_05.get(len(ds) - 1)
                    if crit:
                        half = crit * sd / math.sqrt(len(ds))
                        ci = f"[{m - half:+.2f}, {m + half:+.2f}]"
                mr, _ = mean_std(rs)
                lines.append(f"| {frac:g} | {len(ds)} | "
                             f"{', '.join(f'{d:+.2f}' for d in ds)} | {m:+.2f} | {ci} | "
                             f"{(mr if mr is not None else 0):+.3f} |")
                count_summary.setdefault(f"{frac:g}", {})["gap_vs_full"] = {
                    "n_pairs": len(ds), "seeds": common,
                    "count_mae_diffs": [round(d, 2) for d in ds],
                    "count_mae_mean_diff": round(m, 3),
                    "count_mae_std_diff": round(sd, 3) if sd is not None else None,
                    "count_mae_ci95": ci,
                    "pearson_r_mean_diff": round(mr, 4) if mr is not None else None,
                }
    lines += ["", "## 读法与边界",
              "- 真实/合成子集用**同一个** `--budget-seed 20261120` 抽样, 所以差异只来自训练随机性 (数据划分、"
              "评测集、协议都不变); 这让「加合成 vs 不加合成」成为**配对**比较, 方差可以直接估。",
              f"- 每格点最多 {n_pairs_max} 个 seed → 配对 t 检验 df={max(n_pairs_max-1,0)}; "
              f"双尾 5% 临界值见 `t_crit_0.05` 列。"
              + ("n 仍然偏小, 结论按方向性表述, 不做正式显著性声明。" if n_pairs_max < 5
                 else "n=5 时 df=4, 可给出 5% 水平的双尾判定 (仍限于单次运行、单一数据集)。"),
              f"- 全量真实格点 (frac=1) 现在有 **{n_full} 次运行**"
              + ("(多种子), 它自己的方差已可直接估; 「相对全量真实的缺口」按 seed 配对给出 CI。"
                 if n_full >= 2 else
                 ", 它的**方差未知**; 因此'相对全量真实的缺口'这一列的不确定度大于格点内的比较, "
                 "不能用格点内方差去套它。"),
              "- 训练非逐字节可复现 (同配置两次权重 sha256 不同), 单 seed 差值本身就有运行噪声 —— "
              "这正是本表要量的东西。",
              "- 计数指标那一表只在**同一份 600 张名单**内可比 (名单 sha256 一致才放行); "
              "不同阈值下的数字不能混用 (见 count_threshold_sweep.md)。"]
    md = "\n".join(lines) + "\n"
    open(os.path.join(BENCH, "budget_seed_variance.md"), "w", encoding="utf-8").write(md)
    json.dump({"schema": "budget_seed_variance/2",
               "generated_by": "pipelines/shelf_sdg/22_budget_seed_variance.py",
               "groups": summary, "paired": pairs,
               "vs_full_real": gaps, "count_metrics": count_summary,
               "full_real_runs": n_full},
              open(os.path.join(BENCH, "budget_seed_variance.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(md)
    print("->", os.path.join(BENCH, "budget_seed_variance.md"))


if __name__ == "__main__":
    main()
