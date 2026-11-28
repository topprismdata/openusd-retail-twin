#!/usr/bin/env python
"""从 68 号脚本的日志恢复 I-20 的产物 (2026-11-26) —— 71 号。

为什么需要: 68 号把结果攒在内存里、**跑完 3 个 seed 才写产物** ✗ -> 中途被杀/磁盘满/
会话结束就全丢 ✓。仓里已有同样的做法 (51b `51b_domain_fit_log_parse.py` ✓: 从探针自己
的日志按同一 schema 还原产物 ✓, 数字是脚本输出的搬运 ✓ 不是手写 ✓) -> 这里沿用同一套路 ✓。

日志格式 (68 号的 log() 打印 ✓):
    [PF 11-26 22:38:26] arm seed 43: 真实 test mAP50 = 0.7555
    [PF 11-26 22:41:00] ctrl_a seed 43: 真实 test mAP50 = 0.7931
    [PF 11-26 22:50:00] ctrl_b seed 43: 真实 test mAP50 = 0.8002

用法:
    python pipelines/shelf_sdg/71_recover_pf_arm.py          # 打印 + 写产物
"""
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")
LOG = os.path.join(BENCH, "pretrain_finetune_arm.log")
ART = os.path.join(BENCH, "pretrain_finetune_arm.json")
LINE_RE = re.compile(r"\[PF [^\]]+\] (arm|ctrl_a|ctrl_b) seed (\d+): 真实 test mAP50 = ([0-9.]+)")


def paired(diffs):
    if not diffs:
        return None
    n = len(diffs)
    mean = sum(diffs) / n
    out = {"n": n, "mean_pp": round(mean, 4),
           "per_seed_pp": [round(d, 4) for d in diffs]}
    if n > 1:
        _m, lo, hi = ci95_t(diffs)
        out["ci95_pp"] = [round(lo, 4), round(hi, 4)]
    return out


def main():
    if not os.path.isfile(LOG):
        raise SystemExit(f"缺日志 {LOG}")
    recs = {}
    with open(LOG, encoding="utf-8") as fh:
        for line in fh:
            m = LINE_RE.search(line)
            if not m:
                continue
            tag, seed, val = m.group(1), m.group(2), float(m.group(3))
            recs.setdefault(seed, {})[f"{tag}_last"] = {"map50": val}
    for s, row in recs.items():
        print("seed", s, {k: v["map50"] for k, v in row.items()})
    arm_a = [(row["arm_last"]["map50"] - row["ctrl_a_last"]["map50"]) * 100
             for row in recs.values() if "arm_last" in row and "ctrl_a_last" in row]
    arm_b = [(row["arm_last"]["map50"] - row["ctrl_b_last"]["map50"]) * 100
             for row in recs.values() if "arm_last" in row and "ctrl_b_last" in row]
    rep = {"schema": "pretrain_finetune_arm/1",
           "generated_by": "pipelines/shelf_sdg/71_recover_pf_arm.py (从 68 号日志还原)",
           "recovered_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "note": ("**从 68 号的日志还原** ✓ (数字是脚本输出的搬运 ✓ 不是手写 ✓); "
                    "只有 mAP50 (日志没记 P/R ✓) —— 若 68 号已写产物, 以它为准 ✓"),
           "per_seed": recs,
           "paired": {"arm_vs_ctrl_a": paired(arm_a), "arm_vs_ctrl_b": paired(arm_b)}}
    print(json.dumps(rep["paired"], ensure_ascii=False, indent=2))
    with open(ART, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print(f"-> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
