#!/usr/bin/env python3
"""计数指标的置信度阈值敏感性 (2026-11-22): 把"单点 0.35 不稳健"变成可看的图。

背景: 计数类指标 (MAE / MAPE) 依赖检测阈值 —— ultralytics 在 NMS **之前**做 conf 过滤,
阈值调高, 低分框先被滤掉 (不再参与抑制), 计数随之变化。本脚本把两个臂在 5 个阈值上的
MAE / MAPE / Pearson r 画成图 + 表, 结论由数字决定, 不手写。

输入: output/benchmark/count_<arm>.json 的 conf_sweep 字段 (由 17_count_eval.py --conf-sweep 产生)
输出: output/benchmark/count_threshold_sweep.md / .png (发布到 docs/research/benchmark/)
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")

ARMS = [("real1", "全量真实 10 ep"), ("real0.05", "5% 真实 10 ep")]
ARMS = [(a, t) for a, t in ARMS if os.path.exists(os.path.join(BENCH, f"count_{a}.json"))]


def load(arm):
    d = json.load(open(os.path.join(BENCH, f"count_{arm}.json"), encoding="utf-8"))
    return d, d.get("conf_sweep", [])


def main():
    data = {}
    for arm, title in ARMS:
        d, sw = load(arm)
        if len(sw) < 2:                      # 没扫过阈值的臂不参与 (旧产物可能没有 sweep)
            continue
        data[arm] = (d, sw, title)
    if not data:
        raise SystemExit("[SWEEP] 没有带 conf_sweep 的计数产物 (先跑 17_count_eval.py --conf-sweep)")
    lines = ["# 计数指标的置信度阈值敏感性 (2026-11-22)", "",
             "同一份 600 张固定抽样 (种子 20261120), 只改检测置信阈值; "
             "**每个阈值都是在该阈值下直接推理后数框** "
             "(ultralytics 在 NMS 前做 conf 过滤, 阈值语义与\"先推理再过滤\"不等价)。", ""]
    ref = next(iter(data.values()))[1]
    head = "| 臂 | 指标 | " + " | ".join(f"conf={s['conf']}" for s in ref) + " |"
    lines.append(head)
    lines.append("|---|---|" + "---:|" * len(ref))
    for arm, (_, sw, title) in data.items():
        for key, label, fmt in (("count_mae", "count MAE (框/图)", "{:.2f}"),
                                ("count_mape_pct", "count MAPE", "{:.2f}%"),
                                ("pearson_r", "Pearson r", "{:.3f}")):
            vals = " | ".join(fmt.format(s[key]) for s in sw)
            lines.append(f"| {title} | {label} | {vals} |")
    lines.append("")

    # 判读: MAE 的极差倍数
    for arm, (_, sw, title) in data.items():
        maes = [s["count_mae"] for s in sw]
        best = min(sw, key=lambda s: s["count_mae"])
        lines.append(f"- **{title}**: MAE 在 conf {sw[0]['conf']}→{sw[-1]['conf']} 区间从 "
                     f"{maes[0]:.2f} 变到 {maes[-1]:.2f} (极差 **{max(maes) / max(min(maes), 1e-9):.1f}×**), "
                     f"最优点在 conf={best['conf']} (MAE {best['count_mae']:.2f}) → "
                     f"**计数指标必须报出所用阈值, 单点数字不可脱离阈值谈**。")
    lines += ["", "**边界**: 单模型、单次抽样 (n=600)、未跨训练 seed 复现; "
              "真值是标注框数, 不等于货架上的实际商品数 (遮挡/密集堆叠会让标注框数本身偏少)。"]

    md = os.path.join(BENCH, "count_threshold_sweep.md")
    with open(md, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("->", md)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        matplotlib.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
        for arm, (_, sw, title) in data.items():
            x = [s["conf"] for s in sw]
            axes[0].plot(x, [s["count_mae"] for s in sw], "o-", label=title)
            axes[1].plot(x, [s["pearson_r"] for s in sw], "o-", label=title)
        axes[0].set_xlabel("检测置信阈值"); axes[0].set_ylabel("count MAE (框/图)")
        axes[0].set_title("计数误差随阈值变化")
        axes[1].set_xlabel("检测置信阈值"); axes[1].set_ylabel("Pearson r")
        axes[1].set_title("计数相关性随阈值变化")
        for ax in axes:
            ax.grid(alpha=0.3); ax.legend(fontsize=9)
        fig.suptitle("计数指标对置信阈值敏感: 单点 0.35 不能代表这个指标")
        fig.tight_layout()
        png = os.path.join(BENCH, "count_threshold_sweep.png")
        fig.savefig(png, dpi=150)
        print("->", png)
    except Exception as e:                                   # 画图失败不阻断数字产物
        print("[WARN] 出图失败 (数字产物已写):", e)


if __name__ == "__main__":
    main()
