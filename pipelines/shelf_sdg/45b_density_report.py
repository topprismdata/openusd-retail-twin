#!/usr/bin/env python
"""密度诊断汇总 (2026-11-24): 把各密度点的产物汇成一张曲线 + 一份 md。

为什么单独一个脚本
----------------
`45_density_diagnostic.py` 负责**跑**每个 (目标框/图, seed) 格点, 每个格点落一份
json; 但"结论"要跨格点看 (配对到全量真实基线、按 seed 配对算差值与 CI、画密度-性能
曲线), 所以汇总单独做 —— 这样重跑任何一个格点都不影响结论的算法, 且结论可以随时重算
(数字不手写)。

输入
----
  output/benchmark/density_dens<K>_s<seed>.json   (45 号的产物)
  output/benchmark/budget_real1_synth0*.json       (全量真实基线: 147 框/图)

输出
----
  output/benchmark/density_curve.json / .md / .png
  docs/research/benchmark/density_curve.md        (给 README 引用)

用法:
    python pipelines/shelf_sdg/45b_density_report.py
"""
import glob
import json
import math
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import T_CRIT_95  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
FIG = os.path.join(BENCH, "density_curve.png")


def _f(x):
    return float(str(x).replace("−", "-"))


def load():
    """读各密度点 + 基线, 返回 (points, base_by_seed)。"""
    base = {}
    for f in sorted(glob.glob(os.path.join(BENCH, "budget_real1_synth0*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        s = (d.get("protocol") or {}).get("seed")
        if s is not None and "map50" in d:
            base[s] = d
    pts = {}
    for f in sorted(glob.glob(os.path.join(BENCH, "density_dens*_s*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        k = round(float((d.get("dataset") or {}).get("boxes_per_image") or 0), 2)
        if not k:
            continue
        pts.setdefault(k, []).append(d)
    return pts, base


def summarize(pts, base):
    """每个密度点: 各 seed 的 mAP50 / 与基线的配对差值 / 均值 / sd / CI。"""
    out = []
    # 基线本身也是一个"密度点" (147 框/图, 差值恒为 0)
    if base:
        bm = statistics.mean(d["map50"] for d in base.values())
        bs = statistics.stdev([d["map50"] for d in base.values()]) if len(base) > 1 else 0.0
        out.append({"boxes_per_image": round(
            (base[list(base)[0]].get("dataset") or {}).get("boxes_per_image") or 147.04, 2),
            "n_seeds": len(base), "map50_mean": bm, "map50_sd": bs,
            "per_seed": {str(s): d["map50"] for s, d in sorted(base.items())},
            "paired_diff_pp": None, "paired_mean_pp": 0.0, "paired_ci": [0.0, 0.0],
            "recall_mean": statistics.mean(d.get("recall", 0.0) for d in base.values()),
            "precision_mean": statistics.mean(d.get("precision", 0.0) for d in base.values()),
            "is_baseline": True})
    for k in sorted(pts):
        recs = pts[k]
        diffs, seeds = [], []
        for d in recs:
            s = (d.get("protocol") or {}).get("seed")
            b = base.get(s)
            if b is None:
                continue
            diffs.append((d["map50"] - b["map50"]) * 100)
            seeds.append(s)
        mean = statistics.mean(diffs) if diffs else None
        ci = [None, None]
        if len(diffs) > 1:
            sd = statistics.stdev(diffs)
            hw = T_CRIT_95.get(len(diffs) - 1, 1.96) * sd / math.sqrt(len(diffs))
            ci = [mean - hw, mean + hw]
        out.append({
            "boxes_per_image": k, "n_seeds": len(recs),
            "map50_mean": statistics.mean(d["map50"] for d in recs),
            "map50_sd": statistics.stdev([d["map50"] for d in recs]) if len(recs) > 1 else 0.0,
            "per_seed": {str((d.get("protocol") or {}).get("seed")): d["map50"] for d in recs},
            "paired_diff_pp": [round(x, 3) for x in diffs],
            "paired_mean_pp": round(mean, 4) if mean is not None else None,
            "paired_ci": [round(x, 4) for x in ci] if ci[0] is not None else None,
            "recall_mean": statistics.mean(d.get("recall", 0.0) for d in recs),
            "precision_mean": statistics.mean(d.get("precision", 0.0) for d in recs),
            "is_baseline": False,
        })
    return out


def make_figure(summary_rows):
    """密度-性能曲线: x = 框/图 (对数), y = mAP@0.5。"""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # 中文字体: 与 31 号同一套 (Windows/macOS/Linux 都能落到一个可用的 CJK 字体)
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
    matplotlib.rcParams["axes.unicode_minus"] = False
    xs = [r["boxes_per_image"] for r in summary_rows]
    ys = [r["map50_mean"] for r in summary_rows]
    es = [r["map50_sd"] for r in summary_rows]
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    ax.errorbar(xs, ys, yerr=es, marker="o", capsize=4, lw=2,
                color="#2f6fb0", label="稀释臂 (真实数据, 只减框的数量)")
    # 合成侧的密度水平 -> 一条参考竖线
    ax.axvline(21.83, ls="--", lw=1.4, color="#888888",
               label="合成侧密度 21.83 框/图")
    ax.set_xscale("log")
    ax.set_xlabel("每图框数 (对数轴)")
    ax.set_ylabel("mAP@0.5 (真实 test)")
    ax.set_title("框密度 -> mAP@0.5 (干预: 只裁框, 图像/框的样子不变)")
    ax.grid(alpha=0.3)
    ax.legend(fontsize=9)
    fig.tight_layout()
    fig.savefig(FIG, dpi=140)
    plt.close(fig)
    return FIG


def linearity_check(rows):
    """单调性 + 线性: 三个密度点齐了才判得了。

    为什么要在脚本里判 (而不是手算写进文档): README 里"密度解释了约四成"这句结论
    依赖**外推**, 而外推靠的是"密度 -> 性能"近似线性。只有两个点时线性无从检验
    (两点连线必过两点); 有了中间点, 就能看它**落在两端点连线的上方还是下方** ->
    关系是凸还是凹, 外推方向是乐观还是保守。

    做法: 在 (log10 框/图, mAP) 平面上用**两端点**连线 (不是最小二乘, 因为端点
    才是外推的锚), 中间点看残差。
    """
    pts = sorted([r for r in rows if r["n_seeds"] >= 1],
                  key=lambda r: r["boxes_per_image"])
    if len(pts) < 3:
        return {"available": False,
                "reason": f"只有 {len(pts)} 个密度点, 线性无从检验 (两点连线必过两点)",
                "n_points": len(pts)}
    lo, hi = pts[0], pts[-1]
    x0, y0 = math.log10(lo["boxes_per_image"]), lo["map50_mean"]
    x1, y1 = math.log10(hi["boxes_per_image"]), hi["map50_mean"]
    mids = []
    for r in pts[1:-1]:
        x = math.log10(r["boxes_per_image"])
        pred = y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        mids.append({"boxes_per_image": r["boxes_per_image"],
                     "n_seeds": r["n_seeds"],
                     "map50_mean": round(r["map50_mean"], 4),
                     "log_linear_pred": round(pred, 4),
                     "residual_pp": round((r["map50_mean"] - pred) * 100, 3)})
    ys = [r["map50_mean"] for r in pts]
    monotone = all(ys[i] <= ys[i + 1] + 1e-12 for i in range(len(ys) - 1))
    # 局部斜率 (pp / 框/图), 用来检验"斜率是不是常数"
    slopes = []
    for a, b in zip(pts, pts[1:]):
        dd = b["boxes_per_image"] - a["boxes_per_image"]
        if dd:
            slopes.append({"from": a["boxes_per_image"], "to": b["boxes_per_image"],
                           "pp_per_box": round((b["map50_mean"] - a["map50_mean"]) * 100 / dd, 5)})
    return {"available": True, "n_points": len(pts),
            "monotone_increasing": monotone,
            "middle_points": mids,
            "local_slopes": slopes,
            "note": ("残差 > 0 = 中间点高于两端点连线 (凹: 掉框的代价在低密度端更大); "
                     "残差 < 0 = 凸 (代价在高密度端更大)。"
                     "线性近似成立 <=> |残差| 小 (相对 CI 宽度)。")}


def main():
    pts, base = load()
    if not pts:
        raise SystemExit("[DENS-REPORT] 没有密度诊断产物 (output/benchmark/density_dens*_s*.json)")
    rows = summarize(pts, base)
    lin = linearity_check(rows)
    rep = {"schema": "density_curve/2",
           "generated_by": "pipelines/shelf_sdg/45b_density_report.py",
           "baseline": "budget_real1_synth0*.json (全量真实, 147.04 框/图)",
           "linearity_check": lin,
           "points": rows}
    os.makedirs(PUB, exist_ok=True)
    for p in (os.path.join(BENCH, "density_curve.json"), os.path.join(PUB, "density_curve.json")):
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)

    lines = ["# 密度-性能曲线 (2026-11-24)", "",
             "干预: **只裁框的数量** (图像像素、框的尺度/朝向/位置分布、评测集、训练协议全不变)。",
             "基线 = 全量真实 (147.04 框/图)。", "",
             "| 框/图 | seed 数 | mAP@0.5 mean ± sd | 配对差值 (pp) mean | 95% CI | recall | precision |",
             "|---:|---:|---|---:|---|---:|---:|"]
    for r in rows:
        ci = r["paired_ci"]
        ci_s = f"[{ci[0]:+.2f}, {ci[1]:+.2f}]" if ci else "—"
        d_s = f"{r['paired_mean_pp']:+.2f}" if r["paired_mean_pp"] is not None else "—"
        lines.append(f"| {r['boxes_per_image']:.2f} | {r['n_seeds']} | "
                     f"{r['map50_mean']:.4f} ± {r['map50_sd']:.4f} | {d_s} | {ci_s} | "
                     f"{r['recall_mean']:.4f} | {r['precision_mean']:.4f} |")
    lines += ["", "逐 seed mAP@0.5:", ""]
    for r in rows:
        lines.append(f"- {r['boxes_per_image']:.2f} 框/图: " +
                     ", ".join(f"seed {k} = {v:.4f}" for k, v in sorted(r["per_seed"].items())))
    lines += ["", "## 单调性与线性 (自动判据)", ""]
    if not lin.get("available"):
        lines.append(f"- 线性检验**做不了**: {lin.get('reason')}")
    else:
        lines.append(f"- 密度升高时 mAP 单调上升: **{'是' if lin['monotone_increasing'] else '否'}**")
        for m in lin["middle_points"]:
            lines.append(f"- 中间点 {m['boxes_per_image']:.2f} 框/图 "
                         f"(n={m['n_seeds']}): 实测 {m['map50_mean']:.4f}, "
                         f"两端点(log轴)连线预测 {m['log_linear_pred']:.4f}, "
                         f"**残差 {m['residual_pp']:+.2f} pp**")
        lines.append("- 局部斜率 (pp / 框/图): " + ", ".join(
            f"{s['from']:.0f}→{s['to']:.0f}: {s['pp_per_box']:+.4f}" for s in lin["local_slopes"]))
        lines.append(f"- 判读: {lin['note']}")
    md = "\n".join(lines) + "\n"
    for p in (os.path.join(BENCH, "density_curve.md"), os.path.join(PUB, "density_curve.md")):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(md)
    make_figure(rows)
    # 图也进发布目录 (24_publish_manifest.py 靠扫目录收录)
    import shutil
    shutil.copy2(FIG, os.path.join(PUB, "density_curve.png"))
    print("->", os.path.join(BENCH, "density_curve.json"))
    print("->", os.path.join(BENCH, "density_curve.md"))
    print("->", os.path.join(PUB, "density_curve.md"))
    print("->", os.path.join(PUB, "density_curve.json"))
    print("->", FIG)
    print("->", os.path.join(PUB, "density_curve.png"))
    for r in rows:
        ci = r["paired_ci"]
        print(f"   {r['boxes_per_image']:7.2f} 框/图  mAP {r['map50_mean']:.4f} "
              f"± {r['map50_sd']:.4f}  配对 {r['paired_mean_pp']} "
              f"CI {ci if ci else '—'}")


if __name__ == "__main__":
    main()
