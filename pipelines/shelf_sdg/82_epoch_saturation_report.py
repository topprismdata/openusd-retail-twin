#!/usr/bin/env python
"""I-28 · 轮数轴饱和点的**汇总报告** (2026-11-28)。

读 81 号的产物 ✓ -> 出人读得懂的结论 ✓ (曲线 + 平台读数 + 配对差 ✓)。
**数字全部来自产物** ✓ (逐轮轨迹是训练自己写的 results.csv ✓), 不手抄 ✓。

用法: python pipelines/shelf_sdg/82_epoch_saturation_report.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

BENCH = os.path.join(BASE, "output", "benchmark")
ART = os.path.join(BENCH, "epoch_saturation_probe.json")
OUT = os.path.join(BENCH, "epoch_saturation_report.md")


def plateau(traj):
    """末 10 轮均值 / 最好轮次 / 末轮与最好轮之差 ✓ (平台读数 ✓)"""
    if not traj or not traj.get("val_map50"):
        return {}
    v = traj["val_map50"]
    eps = traj["epochs"]
    tail = v[-10:]
    best_i = v.index(max(v))
    return {"epochs_done": traj.get("n_epochs_done"),
            "last10_mean": round(sum(tail) / len(tail), 5),
            "best": round(max(v), 5), "best_epoch": eps[best_i],
            "last_minus_best": round(v[-1] - max(v), 5),
            "last": round(v[-1], 5)}


def main():
    if not os.path.isfile(ART):
        raise SystemExit(f"缺 {ART} —— 先跑 81 号")
    d = json.load(open(ART, encoding="utf-8"))
    lines = ["# I-28 · 轮数轴的饱和点 (真实标注, 5% 预算 411 张)", "",
             f"- 问题: {d.get('question')}",
             f"- 方案: {d['design']['arm_ctrl_d']}",
             f"- 基线: {d['design']['baseline_ctrl_c']}",
             f"- 评测: {d['design']['eval']}", ""]
    rows = []
    for seed, row in sorted((d.get("per_seed") or {}).items()):
        c = (row.get("ctrl_c_last") or {}).get("map50")
        dd = (row.get("ctrl_d_last") or {}).get("map50")
        pc = plateau(row.get("traj_ctrl_c"))
        pd = plateau(row.get("traj_ctrl_d"))
        rows.append((seed, c, dd, pc, pd))
    if not rows:
        raise SystemExit("产物里还没有 seed 结果 (81 号还在跑 ✓)")
    lines += ["| seed | ctrl_c 40 ep (test mAP50) | ctrl_d 80 ep (test mAP50) | Δ pp | 40 ep 末10轮均值 | 80 ep 末10轮均值 | 80 ep 最好轮 |",
              "|---|---|---|---|---|---|---|"]
    for seed, c, dd, pc, pd in rows:
        delta = (dd - c) * 100 if (c is not None and dd is not None) else None
        lines.append(f"| {seed} | {c if c is None else round(c, 4)} | "
                     f"{dd if dd is None else round(dd, 4)} | "
                     f"{'—' if delta is None else f'{delta:+.2f}'} | "
                     f"{pc.get('last10_mean', '—')} | {pd.get('last10_mean', '—')} | "
                     f"{pd.get('best', '—')} (ep {pd.get('best_epoch', '—')}) |")
    lines.append("")
    p = d.get("paired_ctrl_d_vs_ctrl_c")
    if p:
        lines += [f"**配对差 (ctrl_d − ctrl_c)**: {p['mean_pp']:+.2f} pp, "
                  f"95% CI {p['ci95_pp']}, n={p['n']} → **{p['verdict']}**", ""]
    lines += ["## 读法", "",
              "- `80 ep 末10轮均值` 明显高于 `40 ep 末10轮均值` → **这条杠杆还没到头** ✓",
              "- 两者持平 → **40 轮就是饱和点** ✓ (再加算力就是浪费 ✓)",
              "- 80 ep 的 test mAP50 反而更低 → **40 轮之后开始过拟合** ✓",
              "- **单 seed 的结果只是探针** ✓ (区分涨/平/跌 ✓), 结论需要更多 seed ✓",
              "",
              "## 产物", "", f"- {os.path.relpath(ART, BASE)} (逐轮轨迹 + 配对差 ✓)",
              f"- {os.path.relpath(OUT, BASE)} (本报告 ✓)"]
    os.makedirs(BENCH, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"-> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
