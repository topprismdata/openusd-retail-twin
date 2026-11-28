#!/usr/bin/env python
"""把产物里由 t 临界值算出来的 95% CI **按全仓唯一口径重算一遍** (2026-11-27)。

背景: 9 个臂脚本各自抄了一份 t 表 ``{2: 12.7062, 3: 4.3027, 4: 3.1824, 5: 2.7764}``
并按 ``n-1`` 查 —— 那张表的键**整体偏移了 1** (键 2 装的是 df=1 的值), 于是实际用的
是 df = n-2 -> n=3 的 CI 宽了约 3 倍 -> 6 条已发布判语从"显著"被压成"未检出差异"。
仓里的规范表 :data:`pipelines.common.protocol.T_CRIT_95` 是按 df 索引的, 配对 t 的
自由度是 df = n-1 -> **规范口径 = 现在的重算口径** ✓。

这个脚本只做一件事: **从产物里已存的 per-seed 差值重算 ci95_pp / mean_pp** ✓
- 不碰任何训练结果 (权重、mAP 都在产物里, 原样保留 ✓)
- 不引入新数据 ✓
- 重算后的产物**能由自己存的 per-seed 值复现** ✓ (闸门 28 号的核对方式 ✓)

用法:
    python pipelines/shelf_sdg/80_recompute_ci_artifacts.py            # 只报 (dry-run)
    python pipelines/shelf_sdg/80_recompute_ci_artifacts.py --apply    # 真的改写产物
产物:
    output/benchmark/ci_migration_2026-11-27.json   (改了哪些、为什么 ✓)
"""
import argparse
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
REC = os.path.join(BENCH, "ci_migration_2026-11-27.json")


def walk(node, path=""):
    """产出所有带 per_seed_pp + ci95_pp 的 dict 及其路径 ✓。"""
    if isinstance(node, dict):
        if isinstance(node.get("per_seed_pp"), list) and "ci95_pp" in node:
            yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def verdict(ci):
    if not ci or len(ci) != 2:
        return "no_ci"
    if ci[1] < 0:
        return "sig_worse"
    if ci[0] > 0:
        return "sig_better"
    return "not_detected"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真的改写产物 (默认只报 ✓)")
    args = ap.parse_args()

    changes = []
    for f in sorted(glob.glob(os.path.join(BENCH, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        touched = False
        for path, node in list(walk(d)):
            vals = [float(x) for x in node["per_seed_pp"]]
            mean, lo, hi = ci95_t(vals)
            if lo is None:
                continue
            new_ci = [round(lo, 4), round(hi, 4)]
            old_ci = node.get("ci95_pp")
            old_mean = node.get("mean_pp")
            same_ci = (isinstance(old_ci, list) and len(old_ci) == 2
                       and abs(old_ci[0] - new_ci[0]) < 5e-4 and abs(old_ci[1] - new_ci[1]) < 5e-4)
            same_mean = old_mean is None or abs(float(old_mean) - mean) < 5e-4
            if same_ci and same_mean:
                continue
            changes.append({
                "artifact": os.path.basename(f),
                "path": path,
                "n": len(vals),
                "mean_pp_old": old_mean,
                "mean_pp_new": round(mean, 4),
                "ci_old": old_ci,
                "ci_new": new_ci,
                "verdict_old": verdict(old_ci),
                "verdict_new": verdict(new_ci),
                "verdict_flipped": verdict(old_ci) != verdict(new_ci),
            })
            if args.apply:
                node["ci95_pp"] = new_ci
                if "mean_pp" in node:
                    node["mean_pp"] = round(mean, 4)
            touched = True
        if touched and args.apply:
            with open(f, "w", encoding="utf-8") as fh:
                json.dump(d, fh, ensure_ascii=False, indent=2)

    flips = [c for c in changes if c["verdict_flipped"]]
    rec = {
        "schema": "ci_migration/1",
        "generated_by": "pipelines/shelf_sdg/80_recompute_ci_artifacts.py",
        "measured_at": "2026-11-27",
        "why": ("9 个臂脚本抄的 t 表键整体偏移 1 -> 实际 df = n-2 -> n=3 的 CI 宽约 3 倍 "
                "-> 6 条判语被压成\"未检出差异\"; 仓里的规范表 T_CRIT_95 按 df 索引, "
                "配对 t 的 df = n-1 -> 本次按规范口径重算 ✓"),
        "canonical": "pipelines.common.protocol.ci95_t (T_CRIT_95.get(n-1), df = n-1)",
        "applied": bool(args.apply),
        "n_changed_entries": len(changes),
        "n_verdict_flips": len(flips),
        "changes": changes,
        "caveat": ("历史 .log 里打印的旧 CI 是当时跑出来的**宽口径**值, 属于运行记录, "
                   "不改写 ✓; 产物与 README 里的数字以本次重算为准 ✓"),
    }
    if not changes and os.path.isfile(REC):
        # 产物已是规范口径 -> **不要用空记录覆盖掉上一次的实际改动清单** ✓
        old_rec = json.load(open(REC, encoding="utf-8"))
        if old_rec.get("n_changed_entries"):
            print("\u4ea7\u7269\u5df2\u662f\u89c4\u8303\u53e3\u5f84 ✓ (\u4e0a\u4e00\u6b21\u7684\u6539\u52a8\u6e05\u5355\u4fdd\u7559\u5728\u4ea7\u7269\u91cc ✓)")
            print(f"\u8bb0\u5f55: {REC}")
            return 0

    with open(REC, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=2)

    print(f"{'已改写' if args.apply else '仅报告 (dry-run)'}: {len(changes)} 条 CI 需要重算, "
          f"其中 {len(flips)} 条判语翻转 ✓")
    for c in changes:
        flag = "**判语翻转**" if c["verdict_flipped"] else ""
        print(f"  {c['artifact']:32s} {c['path']:44s} n={c['n']} "
              f"CI {c['ci_old']} ({c['verdict_old']}) -> {c['ci_new']} ({c['verdict_new']}) {flag}")
    print(f"记录: {REC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
