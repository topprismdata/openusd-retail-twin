#!/usr/bin/env python3
"""标注预算曲线图 (2026-11-21): 给论文用的两张图。

图1: mAP@0.5 vs 真实标注比例 —— 无合成 / +160 张合成两条线, 误差棒 = seed 间标准差。
图2: 逐图配对差值的分布 (直方图 + 胜/负张数), 说明"评测集侧"的差异方向与幅度。

只读已落盘的 json, 不需要 GPU。写: docs/research/benchmark/budget_curve_figure.png
"""
import glob
import json
import os
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
OUT = os.path.join(PUB, "budget_curve_figure.png")

CJK = {"family": ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]}
matplotlib.rcParams["font.sans-serif"] = CJK["family"]
matplotlib.rcParams["axes.unicode_minus"] = False


def load_cells():
    groups = {}
    for f in sorted(glob.glob(os.path.join(BENCH, "budget_real*_synth*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        c = d["dataset"]["cell"]
        groups.setdefault((float(c["real_frac"]), int(c["synth_n"])), []).append(d)
    return groups


def compact_tag(path):
    """paired_image_eval_real0.05_s43.json → '5% (s43)'; real0.02 → '2% (s42)'。"""
    base = os.path.basename(path).replace("paired_image_eval_", "").replace(".json", "")
    seed = "42"
    if "_s" in base:
        base, seed = base.rsplit("_s", 1)
    if base.startswith("gap_real1"):
        # 缺口型对比 (5% 真实 vs 全量真实, 同 seed)
        return f"5%→100% (s{seed})"
    frac = "2%" if "0.02" in base else ("5%" if "0.05" in base else base)
    return f"{frac} (s{seed})"


def main():
    groups = load_cells()
    if not groups:
        raise SystemExit("[FIG] 没有格点 json")

    def stat(frac, synth):
        rs = groups.get((frac, synth), [])
        if not rs:
            return None
        xs = [r["map50"] for r in rs]
        return (statistics.mean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0), len(xs))

    fracs = sorted({f for f, _ in groups}, reverse=True)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13.0, 4.6))

    for synth, color, label in ((0, "#5B8FF9", "无合成"), (200, "#F6BD16", "+160 张合成")):
        xs, ys, es, ns = [], [], [], []
        for fr in fracs:
            s = stat(fr, synth)
            if not s:
                continue
            xs.append(fr * 100)
            ys.append(s[0])
            es.append(s[1])
            ns.append(s[2])
        if xs:
            ax1.errorbar(xs, ys, yerr=es, marker="o", capsize=3, lw=1.8, color=color,
                         label=label)
            # 每个点的 seed 数直接标在点旁 (不同预算点的 seed 数不同, 不能塞进图例);
            # 两条线的标注上下错开, 避免重叠
            dy = 6 if synth == 0 else -14
            for x, y, e, n in zip(xs, ys, es, ns):
                ax1.annotate(f"n={n}", (x, y + e), textcoords="offset points",
                             xytext=(0, dy), ha="center", fontsize=7, color=color)

    ax1.set_xscale("log")
    ax1.set_xticks([2, 5, 100])
    ax1.set_xticklabels(["2%", "5%", "100%"])
    ax1.set_xlabel("真实标注预算 (SKU-110K train 的比例)")
    ax1.set_ylabel("test mAP@0.5")
    ax1.set_title("标注预算曲线: 合成补不回缺口 (误差棒=seed 间标准差)")
    ax1.grid(alpha=0.3)
    ax1.legend(fontsize=9)
    for sp in ("top", "right"):
        ax1.spines[sp].set_visible(False)

    # 图2: 逐图配对差值
    files = sorted(glob.glob(os.path.join(BENCH, "paired_image_eval_*.json")))
    if files:
        labels, diffs, colors, kinds = [], [], [], []
        palette = ["#5B8FF9", "#F6BD16", "#61DDAA", "#F6BD16"]
        GAP_COLOR = "#6DC8EC"       # 缺口型对比 (全量真实 vs 5% 真实)
        for i, f in enumerate(files):
            d = json.load(open(f, encoding="utf-8"))
            is_gap = "gap_real1" in os.path.basename(f)
            labels.append(f"{compact_tag(f)}\n{(d['paired_diff_mean'])*100:+.2f}pp, t={d['paired_t']:.0f}")
            # 逐图差值无法从 json 复原 (只存了汇总) → 用汇总统计画误差棒
            diffs.append(d["paired_diff_mean"] * 100)
            colors.append(GAP_COLOR if is_gap else palette[i % len(palette)])
            kinds.append(is_gap)
        ax2.bar(range(len(diffs)), diffs, color=colors, width=0.5)
        ax2.set_xticks(range(len(diffs)))
        ax2.set_xticklabels(labels, fontsize=6.5)
        ax2.axhline(0, color="#333", lw=1)
        ax2.set_ylabel("逐图 AP@0.5 配对差值 (pp)")
        ax2.set_title("逐图配对 (n=2,936): 缺口稳定, 合成效应随训练 seed 变号")
        ax2.grid(alpha=0.3, axis="y")
        for sp in ("top", "right"):
            ax2.spines[sp].set_visible(False)
        from matplotlib.patches import Patch
        handles = [Patch(color=GAP_COLOR, label="缺口: 全量真实 vs 5% 真实 (同 seed)"),
                   Patch(color=palette[0], label="合成 vs 无合成 (同格点, 同 seed)")]
        ax2.legend(handles=handles, fontsize=7, loc="upper right", framealpha=0.9)

    fig.tight_layout()
    os.makedirs(PUB, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print("->", OUT)


if __name__ == "__main__":
    main()
