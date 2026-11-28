#!/usr/bin/env python
"""从一个 run 的 results.csv 里抽出**验证 mAP50 的逐轮轨迹** -> 回答"同一份数据多训几轮还有没有收益"。

为什么值得单独抽: 轮数轴的结论如果只靠"训 10 ep 的 run" vs "训 40 ep 的 run"两个独立 run
来比, 就多了一个 run 之间的噪声源 ✓; 而**同一个 40 轮的 run 内部**, 第 10/20/30/40 轮的
验证 mAP50 是同一条轨迹上的四个点 -> 轮数轴的形状(还在涨? 已平? 掉了?)是**run 内**的,
不受 run 间噪声影响 ✓。

用法:
    python pipelines/shelf_sdg/77_epoch_curve.py --runs runs_pf_ctrlc_s{seed} --seeds 43 44 45
输出: 每个 seed 的逐轮 val mAP50 + 在 10/20/30/40 轮处的取值 + 形状判语。
"""
import argparse
import csv
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")


def curve(run_dir):
    p = os.path.join(run_dir, "train", "results.csv")
    if not os.path.isfile(p):
        return None
    out = []
    with open(p, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            ep = row.get("epoch")
            v = row.get("metrics/mAP50(B)")
            v95 = row.get("metrics/mAP50-95(B)")
            if ep is None or not v:
                continue
            out.append((int(float(ep)), float(v), float(v95) if v95 else None))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", required=True, help="run 目录模板 (可用 {seed})")
    ap.add_argument("--seeds", type=int, nargs="*", default=[43])
    ap.add_argument("--marks", type=int, nargs="*", default=[10, 20, 30, 40])
    args = ap.parse_args()

    tpl = args.runs
    per_seed = {}
    for seed in args.seeds:
        run = tpl.format(seed=seed)
        d = os.path.join(BENCH, run)
        c = curve(d)
        if not c:
            print(f"[{run}] 没有 results.csv (还在训? 或目录不存在) -> 跳过 ✓")
            continue
        per_seed[seed] = c
        marks = [m for m in args.marks if any(e == m for e, _, _ in c)]
        pts = ", ".join(f"{m}ep={dict((e, v) for e, v, _ in c)[m]:.4f}" for m in marks)
        print(f"[{run}] {len(c)} 轮 -> {pts}")
        # 形状: 最后 10 轮的均值 vs 前 10 轮的均值 (同一 run 内 -> 不受 run 间噪声影响 ✓)
        if len(c) >= 20:
            head = sum(v for _, v, _ in c[:10]) / 10
            tail = sum(v for _, v, _ in c[-10:]) / 10
            best = max(v for _, v, _ in c)
            print(f"    前 10 轮均值 {head:.4f} / 后 10 轮均值 {tail:.4f} "
                  f"(差 {(tail - head) * 100:+.2f} pp ✓) / 最优单轮 {best:.4f}")
    if not per_seed:
        raise SystemExit("没有可用的 run ✓")

    # 跨 seed 求均值 (逐轮对齐 ✓)
    common = min(len(c) for c in per_seed.values())
    print()
    print("跨 seed 均值的逐轮 val mAP50 (前 40 轮):")
    means = []
    for i in range(common):
        vals = [per_seed[s][i][1] for s in per_seed]
        m = sum(vals) / len(vals)
        means.append(m)
        mark = " <-" if (i + 1) in args.marks else ""
        print(f"  ep {i + 1:2d}: {m:.4f}{mark}")
    if len(means) >= 20:
        best_i = max(range(len(means)), key=lambda i: means[i])
        print(f"  最高点: ep {best_i + 1} ({means[best_i]:.4f}) "
              f"/ 末轮 ep {len(means)} ({means[-1]:.4f}) "
              f"-> 末轮相对最高点 {(means[-1] - means[best_i]) * 100:+.2f} pp ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
