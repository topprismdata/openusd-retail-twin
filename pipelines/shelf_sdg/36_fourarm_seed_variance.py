#!/usr/bin/env python3
"""已发布四臂的 seed 方差与配对比较 (2026-11-22 晚)。

背景: 四臂 (r0 真实 / r1 纯合成 / r2 真实+合成) 的数字来自 2026-11-08 的单次运行 (seed 42)。
全篇最后一条"单次运行支撑的结论"是:
    "R2 真实+合成 相对 R0 真实: Δ −1.77pp ≤ 2pp, **未检出差异**"
没有方差就说不清这个 −1.77pp 里有多少是训练噪声, 也说不清"未检出差异"是"确实接近"还是
"单次运行的运气"。本脚本把 r0/r2 各三个 seed 汇总成 mean±std, 并对 r2−r0 做**按 seed 配对**
的差值统计 (同一 seed 上两个模型面对同一个评测集)。

读: output/benchmark/sku110k_*.json (含 --arm-tag 后缀的复跑) + 已发布的 seed 42 产物
写: output/benchmark/fourarm_seed_variance.{md,json}
"""
import glob
import json
import math
import os
import re
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")

# 2026-11-23: r3pm = 协议对齐复跑的 R3-full 域对齐臂 (脚本 38), r1shape = 只动朝向因子的
# 形状先验臂 (脚本 43), 与四臂同 schema
TAG_RE = re.compile(r"^sku110k_(r\d+|r3pm|r1shape)(?:_(.+))?\.json$")
SEED_TAG_RE = re.compile(r"^s(\d+)$")
T_CRIT_05 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306}


def _data_fp(d):
    """产物用的数据指纹 (各来源的 sha256 组合) —— 判"是不是同一个实验"的第一要件。"""
    srcs = (d.get("dataset", {}).get("sources") or [])
    return tuple(sorted((s.get("kind"), (s.get("fingerprint") or {}).get("sha256"))
                        for s in srcs))


def _proto_key(d):
    """协议 (去掉 seed —— seed 正是我们要复跑的变量)。"""
    p = dict(d.get("protocol") or {})
    p.pop("seed", None)
    return json.dumps(p, sort_keys=True)


def load_arms():
    """返回 (按 seed 分组的臂, 其它敏感性复跑)。

    **判据是"是不是协议可比的同 seed 复跑", 不是文件名后缀**。
    2026-11-24 修: 原来按后缀 `s<seed>` 判断, 于是 `sku110k_r1_scenebest.json`
    (R1 的 seed 42 运行, 由 38 号脚本生成, 供形状臂/域对齐臂当对照) 被当成"敏感性复跑"
    排除了 —— 但它的协议、数据指纹、权重选择口径与 s43–s47 **完全一致**
    (protocol 相同去掉 seed / train split sha256 同 / 数据 sha256 同 / checkpoint=best),
    只是一个 seed 的合法复跑。后果: 形状臂的配对统计只对上 2 对 (n=2), 而臂自己的
    摘要是 3 对 —— 两处对不上, 且 n=2 的 CI 极窄, 容易读成"显著变差"。

    所以改成按**产物内容**判定:
      * 非历史协议 (protocol.device != mps);
      * 权重选择口径 = best (last 是敏感性复跑, 不能混进 seed 统计);
      * 数据指纹与该臂其它运行一致 (同一次实验);
      * 协议 (去掉 seed) 一致。
    文件名后缀只用于**显示**与去重 (同 arm 同 seed 只留一份, output 优先)。
    """
    arms = {}
    others = []
    for pat in (os.path.join(BENCH, "sku110k_*.json"), os.path.join(PUB, "sku110k_*.json")):
        for f in sorted(glob.glob(pat)):
            m = TAG_RE.match(os.path.basename(f))
            if not m:
                continue
            arm, tag = m.group(1), m.group(2)
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            seed = d.get("protocol", {}).get("seed")
            if seed is None:
                continue
            pm = d.get("protocol_manifest") or {}
            sel = (pm.get("actual") or {}).get("checkpoint_selection")
            legacy = (d.get("protocol", {}).get("device") == "mps")
            rec = {
                "_src": "output" if f.startswith(BENCH) else "pub",
                "arm": arm, "seed": seed, "tag": tag or f"s{seed}",
                "map50": d.get("map50"), "map50_95": d.get("map50_95"),
                "precision": d.get("precision"), "recall": d.get("recall"),
                "protocol_hash": d.get("protocol_hash"),
                "ckpt_sha256": (d.get("checkpoint") or {}).get("sha256"),
                "wall_sec": d.get("wall_sec"),
                "file": os.path.basename(f),
                "ckpt_selection": sel,
                "data_fp": _data_fp(d),
                "proto_key": _proto_key(d),
                # "历史协议" = 2026-11-08 那一版 (protocol.device = mps, 且没有数据指纹)。
                # 它的**合成数据**与现在不同 (旧划分 vs 场景级留出) → 对 r1/r2 不能当成
                # seed 复跑; 只有 r0 (纯真实, 数据没变) 的历史 run 仍可配对。
                "legacy": legacy,
            }
            # 协议可比的 seed 复跑: 非历史协议 + best.pt 口径 + 有数据指纹。
            # `scenelast` (last.pt) 与任何非 best 口径的运行一律算敏感性复跑。
            is_seed_run = (not legacy) and (sel in (None, "best")) and bool(rec["data_fp"])
            if is_seed_run:
                key = (arm, seed)
                # 同一 (arm, seed) 只留一份 (output 版优先: 字段更全)
                if key in arms and arms[key]["_src"] == "output":
                    continue
                arms[key] = rec
            else:
                others.append(rec)
    # 同臂内若数据指纹不一致 -> 那不是同一次实验, 降级成敏感性复跑 (不进 seed 统计)
    for arm, recs in list({a: [r for (aa, _s), r in arms.items() if aa == a]
                            for a in {a for a, _s in arms}}.items()):
        fps = {r["data_fp"] for r in recs}
        protos = {r["proto_key"] for r in recs}
        if len(fps) > 1 or len(protos) > 1:
            # 取众数组合作为"主口径"
            from collections import Counter
            fp_main = Counter(r["data_fp"] for r in recs).most_common(1)[0][0]
            proto_main = Counter(r["proto_key"] for r in recs).most_common(1)[0][0]
            for r in recs:
                if r["data_fp"] != fp_main or r["proto_key"] != proto_main:
                    del arms[(arm, r["seed"])]
                    others.append(r)
    grouped = {}
    for (arm, seed), r in arms.items():
        grouped.setdefault(arm, []).append(r)
    for k in grouped:
        grouped[k].sort(key=lambda r: r["seed"])
    return grouped, others


def mean_std(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    m = statistics.mean(xs)
    s = statistics.stdev(xs) if len(xs) > 1 else 0.0
    return m, s


def paired(arms, a_arm, b_arm, matched_only=True):
    """b_arm − a_arm, 按训练 seed 配对 (同一 seed 上两个模型比同一个评测集)。

    matched_only=True 时只取**协议可比**的运行 (排除 2026-11-08 的历史协议产物):
    r1/r2 的合成数据在那之后换过 (旧划分 → 场景级留出), 历史 run 不是 seed 复跑。
    """
    def pick(arm):
        rs = arms.get(arm, [])
        if matched_only:
            rs = [r for r in rs if not r.get("legacy")]
        return {r["seed"]: r for r in rs}
    a = pick(a_arm)
    b = pick(b_arm)
    common = sorted(set(a) & set(b))
    if not common:
        return None
    rows = []
    for s in common:
        rows.append({
            "seed": s,
            "map50_diff_pp": round((b[s]["map50"] - a[s]["map50"]) * 100, 3),
            "map50_95_diff_pp": round((b[s]["map50_95"] - a[s]["map50_95"]) * 100, 3),
        })
    out = {"a": a_arm, "b": b_arm, "n_pairs": len(rows), "rows": rows,
           "seeds": common}
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
                half = crit * sd / math.sqrt(len(ds))
                out[f"{base}_diff_ci95"] = [round(m - half, 3), round(m + half, 3)]
    return out


def legacy_seeds(arms, a_arm, b_arm):
    """两个臂里都存在历史协议 run 的 seed (那些配对不能算协议可比的 seed 复跑)。"""
    def seeds(arm):
        return {r["seed"] for r in arms.get(arm, []) if r.get("legacy")}
    return seeds(a_arm) & seeds(b_arm)


def main():
    arms, others = load_arms()
    if not arms:
        raise SystemExit("[4ARM] 没找到任何四臂产物")
    lines = ["# 已发布四臂的 seed 方差 (SKU-110K test; 数据与协议不变, 只变训练 seed)", "",
             "**协议可比性**: 2026-11-08 那版四臂是 macOS/MPS 跑的 (`protocol.device = mps`, 没有数据指纹);",
             "其中 **r1/r2 的合成数据**在那之后换过 (旧划分 → 场景级留出), 所以那两个臂的历史 run",
             "**不是 seed 复跑**, 不能进配对统计; **r0 只有真实数据 (数据没变)**, 历史 run 仍可比。",
             "",
             "| 臂 | 含义 | runs (协议可比) | seeds | mAP@0.5 mean | std | mAP@0.5:0.95 mean | std |",
             "|---|---|---:|---|---:|---:|---:|---:|"]
    meaning = {"r0": "真实基线", "r1": "纯合成", "r2": "真实+合成", "r3": "真实+改进 SDG",
               "r3pm": "纯合成 + 域对齐配方 (协议对齐复跑, 2026-11-23)",
               "r1shape": "纯合成 + 形状先验 (朝向+尺度两因子, 2026-11-23/24)"}
    summary = {}
    for arm in sorted(arms):
        runs = arms[arm]
        matched = [r for r in runs if not r.get("legacy")]
        legacy = [r for r in runs if r.get("legacy")]
        use = matched or runs          # 没有可比复跑时退回全部 (至少把数报出来)
        m50, s50 = mean_std([r["map50"] for r in use])
        m95, s95 = mean_std([r["map50_95"] for r in use])
        seeds = ", ".join(str(r["seed"]) for r in use)
        lines.append(f"| {arm} | {meaning.get(arm, '—')} | {len(use)} | {seeds} | "
                     f"{m50:.4f} | {(s50 or 0):.4f} | {m95:.4f} | {(s95 or 0):.4f} |")
        summary[arm] = {"n": len(use), "seeds": [r["seed"] for r in use],
                        "map50_mean": m50, "map50_std": s50,
                        "map50_95_mean": m95, "map50_95_std": s95,
                        "n_legacy_excluded": len(legacy),
                        "runs": [{k: v for k, v in r.items() if k != "_src"} for r in use]}
    pairs = []
    # r3pm (域对齐配方) 的对照臂是 r1 (同图数/同划分/同协议, 只差 SDG 配方);
    # r1shape (形状先验, 只动朝向因子) 的对照臂同样是 r1
    for a, b in (("r0", "r2"), ("r0", "r1"), ("r1", "r3pm"), ("r1", "r1shape")):
        p = paired(arms, a, b)
        if p:
            pairs.append(p)
    if pairs:
        lines += ["", "## 配对比较 (同一 seed 上两个模型比同一个评测集, 只用协议可比的运行)", "",
                  "| 对比 | n 对 | mAP@0.5 差值 (pp, 逐 seed) | mean | std | 95% CI | t | p |",
                  "|---|---:|---|---:|---:|---|---:|---|"]
        for p in pairs:
            ci = p.get("map50_diff_ci95")
            ci_txt = f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "—"
            lines.append(f"| {p['b']} − {p['a']} | {p['n_pairs']} | "
                         f"{', '.join(f'{r['map50_diff_pp']:+.2f}' for r in p['rows'])} | "
                         f"{p.get('map50_diff_mean_pp', 0):+.2f} | "
                         f"{('%.2f' % p['map50_diff_std_pp']) if p.get('map50_diff_std_pp') is not None else '—'} | "
                         f"{ci_txt} | {p.get('map50_diff_t', '—')} | {p.get('map50_diff_p', '—')} |")
            # "未检出差异"必须同时说清**能排除多大的效应** —— 否则等于什么都没排除
            if ci:
                if ci[1] < 0:
                    p["min_degradation_pp"] = round(abs(ci[1]), 3)
                    verdict = (f"CI 全部在 0 以下 → 劣化**显著**, 95% 置信下**至少**劣化 "
                               f"{abs(ci[1]):.2f} pp")
                elif ci[0] > 0:
                    # CI 整段在 0 以上 = 差值**显著为正** (不是"未检出差异")。
                    # 2026-11-24 修: 原来只判 ci[1] < 0, 于是 [+0.05, +0.26] 这种
                    # 明明不含 0 的 CI 也被写成"CI 跨 0 → 未检出差异" —— 判语与统计量矛盾。
                    p["min_improvement_pp"] = round(ci[0], 3)
                    verdict = (f"CI 全部在 0 以上 → 差值**显著为正** (95% 置信下至少高 "
                               f"{ci[0]:.2f} pp); 方向与幅度都要照实写, 不能说成'未检出差异'")
                else:
                    p["max_excludable_degradation_pp"] = round(abs(ci[1]), 3)
                    verdict = (f"CI 跨 0 → '未检出差异'是数据支持的 (不是单次运行的运气); "
                               f"**若差值为真, 95% 置信下最多劣化 {abs(ci[1]):.2f} pp**")
                lines.append(f"> **{p['b']} 相对 {p['a']}**: 配对差值均值 "
                             f"{p['map50_diff_mean_pp']:+.2f} pp, 95% CI [{ci[0]:+.2f}, {ci[1]:+.2f}] pp → {verdict}")
    # 历史协议 (2026-11-08) 的那一对: 单列, 因为它不是协议可比的 seed 复跑
    legacy_pairs = []
    for a, b in (("r0", "r2"), ("r0", "r1")):
        p = paired(arms, a, b, matched_only=False)
        if not p:
            continue
        legacy_only = [r for r in p["rows"] if r["seed"] in legacy_seeds(arms, a, b)]
        if legacy_only:
            p["rows"] = legacy_only
            p["n_pairs"] = len(legacy_only)
            legacy_pairs.append(p)
    if legacy_pairs:
        lines += ["", "## 历史协议 (2026-11-08, macOS/MPS) 的那一对 —— 不是协议可比的 seed 复跑", "",
                  "| 对比 | seed | mAP@0.5 差值 (pp) | 备注 |",
                  "|---|---:|---:|---|"]
        for p in legacy_pairs:
            for r in p["rows"]:
                lines.append(f"| {p['b']} − {p['a']} | {r['seed']} | {r['map50_diff_pp']:+.2f} | "
                             f"旧合成划分 + macOS/MPS; **与当前协议的复跑不可直接配对** |")
    if others:
        lines += ["", "## 敏感性复跑 (不计入 seed 统计: 数据或权重选择口径与规范臂不同)", "",
                  "| 臂 | 后缀 | seed | mAP@0.5 | mAP@0.5:0.95 | 文件 |",
                  "|---|---|---:|---:|---:|---|"]
        for r in sorted(others, key=lambda r: (r["arm"], r["tag"])):
            lines.append(f"| {r['arm']} | {r['tag']} | {r['seed']} | {r['map50']:.4f} | "
                         f"{r['map50_95']:.4f} | `{r['file']}` |")
    lines += ["", "## 读法与边界",
              "- **本表的 n 与口径是唯一事实源**: 其它脚本 (38 号域对齐臂 / 43 号形状臂) 一律从这里"
              "引用配对差值与 CI, 不自己另算一遍; 闸门 28 号也只与本表对账, 不硬编码期望值。",
              "- 复跑 (seed 43/44) 的数据、协议 (10 ep / 640 / batch 4 / max_det 1000)、"
              "权重选择口径 (best.pt) 全部与 2026-11-08 那版一致, 只换训练 seed → 差值里只剩训练随机性。",
              "- **R2 − R0 就是'向全真实训练集追加 160 张合成图'这个操作的效应**; 配对 CI 跨 0 → "
              "'未检出差异'是数据支持的结论 (而不是单次运行的运气), 但 CI 的宽度同时告诉我们"
              "这个结论**能排除多大的效应**。",
              "- **历史协议 (2026-11-08) 的那一对不能当 seed 复跑**: 那一版的 r1/r2 用的是旧合成划分"
              "(2026-11-21 换成场景级留出), 且跑在 macOS/MPS 上 → 它与当前协议的复跑**不是同一个实验**。"
              "证据: 纯合成臂 r1 在旧协议下是 0.1330, 换合成划分后是 0.2265 / 0.2437 / 0.2532。"
              "所以 README 里那个 'Δ = −1.77pp' 只能当**历史协议的观测值**引用, 不能当当前协议的效应量。",
              "- 训练非逐字节可复现 (同配置两次权重 sha256 不同), 单 seed 差值本身就有运行噪声。",
              "- r1 (纯合成) 只有 160 张合成图, 方差天然比另外两臂大; 它的负结论是"
              "'跨域纯合成不可用', 不因 seed 改变方向。"]
    md = "\n".join(lines) + "\n"
    open(os.path.join(BENCH, "fourarm_seed_variance.md"), "w", encoding="utf-8").write(md)
    json.dump({"schema": "fourarm_seed_variance/1",
               "generated_by": "pipelines/shelf_sdg/36_fourarm_seed_variance.py",
               "groups": summary, "paired": pairs},
              open(os.path.join(BENCH, "fourarm_seed_variance.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print(md)
    print("->", os.path.join(BENCH, "fourarm_seed_variance.md"))


if __name__ == "__main__":
    main()
