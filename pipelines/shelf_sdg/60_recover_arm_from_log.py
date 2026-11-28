#!/usr/bin/env python
"""从臂运行的**自己的日志**恢复产物 (2026-11-25)。

坑 (与 51b_domain_fit_log_parse.py 同源)
--------------------------------------
`52_photorealism_probe.py` 在**所有臂跑完之后**才写产物。blurR 臂在准备训练池时
崩了 (常量名拼错), 于是已经跑完的 blur2 三个 seed 的结果**只存在于日志里**, 产物里
没有这一臂 -> 报告里要引用这些数时, 只能手抄日志 (数字脱离产物 = 少一个真相源)。

做法: 解析日志里"评测脚本自己打印"的那一行, 按**同一 schema** 还原该臂的统计量,
并用 `52_photorealism_probe.summarize()` 现算 mean/sd/配对差/95% CI —— 统计口径与
正常跑出来的完全一致 (同一份代码), 不手写任何数。产物里同时记下"这一臂是从日志
恢复的"以及来源日志路径, 便于事后核对。

不重跑实验: 已完成的训练结果就是日志里的那几个数, 重跑只会多烧 GPU。

用法:
    python pipelines/shelf_sdg/60_recover_arm_from_log.py \
        --log output/benchmark/syn2real_blur_arms.log --arms blur2
"""
import argparse
import importlib
import json
import os
import re
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
# 52 号的文件名以数字开头, `import` 语句用不了 -> importlib (模块名本身允许数字开头)
arm52 = importlib.import_module("pipelines.shelf_sdg.52_photorealism_probe")

BENCH = os.path.join(BASE, "output", "benchmark")
OUT_JSON = os.path.join(BENCH, "syn2real_interventions.json")

LINE_RE = re.compile(r"\] (?P<arm>\S+) seed (?P<seed>\d+): .*?mAP50 = (?P<v>[0-9.]+)")


def parse_log(path):
    """从日志里取出每个臂的 per-seed mAP50。"""
    out = {}
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = LINE_RE.search(line)
            if not m:
                continue
            arm, seed, v = m.group("arm"), int(m.group("seed")), float(m.group("v"))
            out.setdefault(arm, {})[str(seed)] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True, help="臂运行的日志")
    ap.add_argument("--arms", default="", help="逗号分隔; 缺省 = 日志里所有臂")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    per_arm = parse_log(args.log)
    want = [a.strip() for a in args.arms.split(",") if a.strip()] or list(per_arm)
    if "control" not in per_arm:
        print("[跳过] 日志里没有 control 臂 -> 无法做配对统计")
        return 1

    ctrl_recs = [{"seed": int(s), "map50": v}
                 for s, v in sorted(per_arm["control"].items(), key=lambda kv: int(kv[0]))]

    rep = json.load(open(OUT_JSON, encoding="utf-8"))
    results = rep.setdefault("results", {})

    for arm in want:
        if arm == "control" or arm not in per_arm:
            continue
        recs = [{"seed": int(s), "map50": v}
                for s, v in sorted(per_arm[arm].items(), key=lambda kv: int(kv[0]))]
        v = arm52.summarize(arm, recs, ctrl_recs)
        if v is None:
            continue
        v["recovered_from_log"] = os.path.relpath(args.log, BASE).replace("\\", "/")
        v["provenance"] = ("从该臂运行自己的日志还原 (产物在写之前崩了); "
                           "统计量由 52 号 summarize() 现算, 与正常跑出来同口径")
        old = results.get(arm)
        results[arm] = arm52.merge_arm(old, v) if old else v
        print(f"[恢复] {arm}: n={v['n']} mean={v['mean']} "
              f"配对Δ={v.get('paired_mean_pp')} pp CI={v.get('paired_ci95_pp')}")
        if old:
            print(f"        (与产物里已有的 {arm} 按 seed 并集合并)")

    if args.dry_run:
        print("[dry-run] 未写盘")
        return 0

    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    # .md 用**同一份**渲染逻辑重建 (52 号的 render_md), 否则 .json 与 .md 会各说各话
    md = arm52.render_md(rep)
    md_path = os.path.join(BENCH, "syn2real_interventions.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(md)
    pub = os.path.join(BASE, "docs", "research", "benchmark")
    os.makedirs(pub, exist_ok=True)

    shutil.copy2(OUT_JSON, os.path.join(pub, "syn2real_interventions.json"))
    shutil.copy2(md_path, os.path.join(pub, "syn2real_interventions.md"))
    print(f"[写入] {OUT_JSON} (+ 重建 .md)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
