#!/usr/bin/env python
"""把某个臂的产物算成**可以直接贴进 README 的数字** (表格行 + 配对均值 + CI + 判语)。

为什么要有这个脚本: 每次写臂的小节都要手工从产物里抄 3 组数 (每个 seed 的两列、
配对差均值、95% CI) —— 抄错一个数, 闸门 (28 号) 会报红, 但那时已经白写了一遍 ✓。
这里把抄写这件事变成现算 ✓, **但判语与结论由人写** (脚本只给数字与 CI 形态对应的
判语候选 ✓)。

用法:
    python pipelines/shelf_sdg/76_arm_report_numbers.py --artifact real_budget_epoch_arm.json \
        --arm wash --control ctrl_b
    python pipelines/shelf_sdg/76_arm_report_numbers.py --artifact mixstyle_arm.json \
        --arm arm --control control

输出: 每个 seed 一行 "| seed 43 | 对照 | 臂 | Δ (pp) |" 的 markdown 行 +
配对均值与 95% CI + 按 CI 形态给出的判语候选 (与 multi-seed-aggregation-pitfalls §3 一致 ✓)。

判语口径 (与 28 号闸门一致 ✓):
    CI 整段 < 0  -> "显著劣化" (至少劣化 |ci 下端| pp)
    CI 整段 > 0  -> "显著为正" (至少高 ci 下端 pp)
    CI 跨 0      -> "未检出差异" (若真值在 CI 下端, 最多劣化 |ci 下端| pp)
"""
import argparse
import json
import os
import statistics
import sys

MINUS = "\u2212"   # README 用 U+2212 (闸门正则只认它与 +) ✓

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")


def paired_stats(diffs):
    """配对差 -> (n, mean, ci95) —— **走全仓唯一的 ci95_t** ✓ (t 临界值表不许再抄 ✓)。"""
    n = len(diffs)
    mean = sum(diffs) / n
    if n < 2:
        return n, mean, None
    _m, lo, hi = ci95_t(diffs)
    return n, mean, [lo, hi]


def verdict(ci):
    """按 CI 形态给判语候选 (与 skill: multi-seed-aggregation-pitfalls §3 一致 ✓)。"""
    if ci is None:
        return "(n=1, 没有 CI —— 不能给判语 ✓)"
    lo, hi = ci
    if hi < 0:
        return f"CI 整段在 0 以下 = **显著劣化** (至少劣化 {abs(hi):.2f} pp ✓)"
    if lo > 0:
        return f"CI 整段在 0 以上 = **显著为正** (至少高 {lo:.2f} pp ✓)"
    return (f"CI 跨 0 = **未检出差异** (若真值在 CI 下端, 最多劣化 {abs(hi):.2f} pp ✓)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True, help="产物 json 名 (在 output/benchmark/ 下)")
    ap.add_argument("--arm", required=True, help="臂在 per_seed 里的键名 (如 wash / arm_last)")
    ap.add_argument("--control", required=True, help="对照在 per_seed 里的键名 (如 ctrl_b)")
    ap.add_argument("--metric", default="map50", help="per_seed 里要比的指标键 (默认 map50)")
    ap.add_argument("--name", default=None, help="臂在表格里的显示名 (默认用 --arm)")
    args = ap.parse_args()

    p = args.artifact if os.path.isabs(args.artifact) else os.path.join(BENCH, args.artifact)
    if not os.path.isfile(p):
        raise SystemExit(f"缺产物 {p}")
    art = json.load(open(p, encoding="utf-8"))

    per_seed = art.get("per_seed") or {}
    if not per_seed:
        raise SystemExit("产物里没有 per_seed")

    exp = (art.get("design") or {}).get("seeds")
    if exp and len(per_seed) < len(exp):
        print(f"⚠️ 产物只有 {len(per_seed)}/{len(exp)} 个 seed (臂还在跑) "
              f"-> **这些数字还不能进 README** ✓\n")

    arm_name = args.name or args.arm
    diffs, rows = [], []
    for s in sorted(per_seed, key=lambda x: int(x) if str(x).isdigit() else x):
        row = per_seed[s]
        a, c = row.get(args.arm), row.get(args.control)
        if not a or not c:
            continue
        av, cv = a[args.metric], c[args.metric]
        d = (av - cv) * 100.0
        diffs.append(d)
        rows.append(f"| seed {s} | {cv:.4f} | {av:.4f} | {d:+.2f} |".replace("-", MINUS))

    if not rows:
        raise SystemExit(f"没找到能配对的 seed (臂键 {args.arm} / 对照键 {args.control}) ✓")

    n, mean, ci = paired_stats(diffs)
    neg = sum(1 for d in diffs if d < 0)

    print(f"表格行 (对照 → {arm_name}, 指标 {args.metric}):")
    for r in rows:
        print("  " + r)
    print()
    ci_s = (f"[{ci[0]:+.2f}, {ci[1]:+.2f}]".replace("-", MINUS)) if ci else "(无, n=1)"
    print(f"配对: Δ({arm_name}−{args.control}) = {mean:+.2f} pp，"
          f"mean {mean:+.2f}pp，95% CI {ci_s}，n={n}"
          f"（{neg}/{n} seed 为负 ✓）".replace("-", MINUS))
    print(f"判语候选: {verdict(ci)}")
    print()
    print("闸门要匹配的 README 写法 (28 号 6c 项的格式 —— "
          "**Δ 槽位放的是均值** ✓, 与 I-20/I-22 的写法一致):")
    if ci:
        print(f"  Δ({arm_name}−{args.control}) = {mean:+.2f} pp，mean {mean:+.2f}pp，"
              f"95% CI [{ci[0]:+.2f}, {ci[1]:+.2f}]".replace("-", MINUS))
    else:
        print(f"  Δ({arm_name}−{args.control}) = {mean:+.2f} pp，mean {mean:+.2f}pp，"
              f"95% CI [x, y]  ← n=1, 没有 CI, 这一行还不能写进 README ✓".replace("-", MINUS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
