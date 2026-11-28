#!/usr/bin/env python
"""I-19 机制探针的图 (2026-11-26) —— 72 号。

读的是 67 号的产物 (现算 ✓ 不手写 ✓): 三组配对差的均值与 95% CI ✓
  * 剥离版 (没有上下文的真实照片)  -> 干预是否让"商品识别本身"变强 ✓
  * 真实原图 (有杂乱上下文的真实照片) -> 迁移有没有真的变好 ✓
  * 上下文依赖度 (剥离版 - 原图)     -> 干预是否真的降低了上下文依赖 ✓
输出: docs/research/benchmark/context_suppress_probe.png
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
SRC = os.path.join(BENCH, "context_suppress_probe.json")
OUT = os.path.join(PUB, "context_suppress_probe.png")

ROWS = [
    ("剥离版\n(没有上下文的真实照片)", "arm_minus_control_stripped_pp", "#2f6bf0"),
    ("真实原图\n(有杂乱上下文的真实照片)", "arm_minus_control_raw_pp", "#6aa84f"),
    ("上下文依赖度\n(剥离版 − 原图)", "arm_minus_control_delta_pp", "#e69138"),
]


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    # 中文字体 (仓内统一解析 ✓) —— 不设的话中文会变成方框 ✗
    sys.path.insert(0, BASE)
    from pipelines.common.fonts import find_font_path
    cjk = find_font_path("cjk")
    if cjk:
        font_manager.fontManager.addfont(cjk)
        matplotlib.rcParams["font.family"] = font_manager.FontProperties(fname=cjk).get_name()
        matplotlib.rcParams["axes.unicode_minus"] = False
    else:
        print("[FIG] 没找到 CJK 字体, 标签可能显示为方块 ✗")
    if not os.path.isfile(SRC):
        raise SystemExit(f"缺 {SRC} —— 先跑 67 号探针")
    d = json.load(open(SRC, encoding="utf-8"))
    labels, means, los, his, colors = [], [], [], [], []
    for label, key, color in ROWS:
        v = d.get(key) or {}
        if v.get("mean_pp") is None:
            continue
        ci = v.get("ci95_pp") or [v["mean_pp"], v["mean_pp"]]
        labels.append(label)
        means.append(v["mean_pp"])
        los.append(v["mean_pp"] - ci[0])
        his.append(ci[1] - v["mean_pp"])
        colors.append(color)
    if not labels:
        raise SystemExit("产物里没有可画的配对统计")
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    y = range(len(labels))
    ax.barh(y, means, color=colors, height=0.55)
    ax.errorbar(means, y, xerr=[los, his], fmt="none", ecolor="#202124", capsize=5, lw=1.4)
    ax.axvline(0, color="#202124", lw=1)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=9)
    ax.invert_yaxis()   # 第一行在上 (barh 默认反过来 ✓)
    ax.set_xlabel("臂 − 对照 (mAP50 百分点)", fontsize=10)
    ax.set_title("I-19 机制探针: 干预改了什么、没改什么 (n=%d, 配对 95%% CI)"
                 % (d.get("arm_minus_control_raw_pp", {}).get("n", 0)), fontsize=11)
    ax.grid(axis="x", alpha=0.25, lw=0.6)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    os.makedirs(PUB, exist_ok=True)
    fig.savefig(OUT, dpi=160)
    print(f"-> {OUT}")
    for label, m, lo, hi in zip(labels, means, los, his):
        print(f"   {label.replace(chr(10), ' ')}: {m:+.2f} pp [{m-lo:+.2f}, {m+hi:+.2f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
