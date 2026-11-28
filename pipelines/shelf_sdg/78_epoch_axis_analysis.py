#!/usr/bin/env python
"""轮数轴的**run 内**轨迹分析: 同一份 411 张真实图, 多训几轮到底还有没有收益?

为什么要有这个产物
------------------
轮数轴如果只靠"训 10 ep 的 run" vs "训 40 ep 的 run"两个**独立 run** 来比, 就多了一个
run 间噪声源 (换个 seed / 换个初始化, 差 1-2 pp 很常见 ✓)。而**同一个 40 轮的 run 内部**,
第 10/20/30/40 轮的验证 mAP50 是**同一条轨迹**上的四个点 -> 轮数轴的形状
(还在涨? 已平? 掉了?)是 run 内的, 不受 run 间噪声影响 ✓。

它同时回答第二个问题: **合成预训练留下的伤, 会不会被更多真实轮数洗掉?** ->
把"合成预训练 → 真实 N ep"与"纯真实 N ep"两条轨迹在**同一个 epoch、同一份 val** 上对齐比较 ✓
(这两条曲线的差 = 该 epoch 上的污染量 ✓)。

口径 (全部逐项相同 ✓): 数据 = i20_real.yaml (411 张真实子集 ✓); val = 同一份 val 划分 ✓;
指标 = 验证集 mAP50 (不是 test —— test 只用于最终配对结论 ✓)。

用法:
    python pipelines/shelf_sdg/78_epoch_axis_analysis.py
产物:
    output/benchmark/epoch_axis_curve.json
"""
import csv
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
OUT = os.path.join(BENCH, "epoch_axis_curve.json")
SEEDS = [43, 44, 45]

# 每族: (显示名, run 目录模板, 该族的真实轮数, 是不是"带合成预训练"的那条)
FAMILIES = [
    ("ctrl_a(纯真实 10ep)", "runs_pf_ctrla_s{seed}", 10, False),
    ("ctrl_b(纯真实 20ep)", "runs_pf_ctrlb_s{seed}", 20, False),
    ("ctrl_c(纯真实 40ep)", "runs_pf_ctrlc_s{seed}", 40, False),
    ("分工臂(合成预训练→真实 10ep)", "runs_pf_ft_s{seed}", 10, True),
    ("arm_wash(合成预训练→真实 20ep)", "runs_pf_wash_s{seed}", 20, True),
]
MARKS = [5, 10, 15, 20, 30, 40]


def read_curve(run_dir):
    p = os.path.join(BENCH, run_dir, "train", "results.csv")
    if not os.path.isfile(p):
        return None
    out = {}
    with open(p, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not row.get("epoch") or not row.get("metrics/mAP50(B)"):
                continue
            out[int(float(row["epoch"]))] = float(row["metrics/mAP50(B)"])
    return out or None


def main():
    families = {}
    for name, tpl, epochs, synth in FAMILIES:
        per_seed = {}
        for s in SEEDS:
            c = read_curve(tpl.format(seed=s))
            if c:
                per_seed[str(s)] = c
        if not per_seed:
            print(f"[{name}] 没有可用的 results.csv -> 跳过 ✓")
            continue
        families[name] = {"run_template": tpl, "real_epochs": epochs,
                          "synth_pretrained": synth, "per_seed_val_map50": per_seed}

    if not families:
        raise SystemExit("没有可用的 run ✓")

    # 跨 seed 均值轨迹 (逐轮对齐 ✓)
    for name, f in families.items():
        ps = f["per_seed_val_map50"]
        n_ep = min(len(c) for c in ps.values())
        traj = []
        for i in range(1, n_ep + 1):
            vals = [c[i] for c in ps.values() if i in c]
            traj.append(round(sum(vals) / len(vals), 6))
        f["mean_val_map50_by_epoch"] = traj
        # **每一轮上到底有几个 seed 参与了均值** (有的族可能还没跑完 -> n 不一样 ✓)
        # 不记这个就会把 "2 个 seed 的均值" 写成 "3 个 seed 的均值" 的样子 ✓
        f["n_seeds_by_epoch"] = [sum(1 for c in ps.values() if i in c) for i in range(1, n_ep + 1)]
        f["n_seeds"] = len(ps)

    # 污染量: 同一 epoch 上 "带合成预训练" 与 "纯真实" 的差 (配对, 逐 seed 再求均值 ✓)
    gaps = {}
    for synth_name, plain_name in (("分工臂(合成预训练→真实 10ep)", "ctrl_a(纯真实 10ep)"),
                                    ("arm_wash(合成预训练→真实 20ep)", "ctrl_b(纯真实 20ep)")):
        if synth_name not in families or plain_name not in families:
            continue
        a, b = families[synth_name]["per_seed_val_map50"], families[plain_name]["per_seed_val_map50"]
        per_ep = {}
        for ep in sorted(set.intersection(*[set(c) for c in a.values()]) &
                         set.intersection(*[set(c) for c in b.values()])):
            diffs = []
            for s in a:
                if s in b and ep in a[s] and ep in b[s]:
                    diffs.append((a[s][ep] - b[s][ep]) * 100.0)
            if diffs:
                # **每一轮上的配对数也要记** (有的 seed 还在训 -> n 不一样 ✓)
                per_ep[str(ep)] = {"mean_pp": round(sum(diffs) / len(diffs), 4),
                                   "n": len(diffs)}
        gaps[f"{synth_name} − {plain_name}"] = per_ep

    art = {
        "schema": "epoch_axis_curve/1",
        "generated_by": "pipelines/shelf_sdg/78_epoch_axis_analysis.py",
        "question": ("同一份 411 张真实图, 训练轮数加大的收益曲线是什么形状? "
                     "还在涨 / 已平 / 掉了? 以及合成预训练留下的伤会不会被更多真实轮数洗掉?"),
        "metric": "验证集 mAP50 (同一份 val 划分; test 只用于最终配对结论 ✓)",
        "data": "output/benchmark/budget/i20_real.yaml (411 张真实子集 ✓)",
        "seeds": SEEDS,
        "families": families,
        "synth_contamination_by_epoch_pp": gaps,
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=2)

    # 打印可直接贴进 README 的表 ✓
    print("轮数轴 (跨 seed 均值的**验证集** mAP50, 目标 n=%d ✓):" % len(SEEDS))
    hdr = "| 轮数 | " + " | ".join(families[n]["run_template"] for n in families) + " |"
    print(hdr)
    print("|---" * (len(families) + 1) + "|")
    for ep in MARKS:
        cells = []
        for n, f in families.items():
            tr = f["mean_val_map50_by_epoch"]
            ns = (f.get("n_seeds_by_epoch") or [])
            nn = ns[ep - 1] if ep <= len(ns) else 0
            if ep <= len(tr):
                cells.append(f"{tr[ep - 1]:.4f}" + (f" (n={nn})" if nn != len(SEEDS) else ""))
            else:
                cells.append("—")
        print(f"| {ep} ep | " + " | ".join(cells) + " |")
    print()
    print("合成预训练的污染量 (同一 epoch 上的配对差, pp):")
    for k, v in gaps.items():
        pts = ", ".join(f"{e}ep {d['mean_pp']:+.2f}(n={d['n']})" for e, d in v.items())
        print(f"  {k}: {pts}")
    print()
    print(f"产物: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
