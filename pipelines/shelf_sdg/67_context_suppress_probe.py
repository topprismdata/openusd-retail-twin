#!/usr/bin/env python
"""I-19 的机制探针 (2026-11-26) —— 67 号。

问题: I-19 那条臂 (+1.51 pp, CI 跨 0) 到底有没有**真的**让模型变得不依赖上下文?

做法: 复用 63 号探针的同一套处理 (框外像素换成纯色, 框内与标签不动 ✓), 但这次
换**谁来被测**:
  * 对照 R1 的模型 (runs_r1_s{seed}) 在 真实原图 / 真实剥离版 上的差 = **上下文依赖度**
    (63 号测过: 真实域 +22.76 pp ✓);
  * I-19 的模型 (runs_ctxsupp_s{seed}) 在同样两张图上的差 = 它还剩多少上下文依赖。
判据:
  * 若 I-19 模型的 Δ_real **明显小于**对照的 Δ_real -> 干预**起作用了** (模型真的
    学到了"上下文可以忽略") -> 那 +1.5 pp 的迁移收益小, 是因为**上下文的 22.76 pp
    里只有一小部分是"依赖"造成的**, 剩下的是别的机制 ✓;
  * 若 Δ_real 基本不变 -> 干预**没起作用** -> +1.5 pp 只是噪声/巧合 ✓。

产物: output/benchmark/context_suppress_probe.json (数字现算 ✓)
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")
PROBE_DIR = os.path.join(BENCH, "context_probe")
OUT = os.path.join(BENCH, "context_suppress_probe.json")
LOG = os.path.join(BENCH, "context_suppress_probe.log")
SEEDS = [43, 44, 45, 46, 47]
N_IMG = 300          # 63 号用的是 800 张; 这里取前 300 张 (原图与剥离版同序 ✓) -> 5x 快
REAL_DIR = os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K")


def log(m):
    line = f"[CTXPROBE {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def subset_yaml(name, n=N_IMG):
    """从 63 号探针的名单里取前 n 张, 生成 (清单, yaml)。

    原图侧: context_probe/real_subset.txt (指向 SKU-110K 的图 ✓);
    剥离版: context_probe/real_stripped/images/<同名> ✓ —— **按名单顺序**取, 两边一一对应 ✓。
    """
    raw_lst = os.path.join(PROBE_DIR, "real_subset.txt")
    if not os.path.isfile(raw_lst):
        raise SystemExit(f"缺 {raw_lst} —— 先跑 63 号探针")
    with open(raw_lst, encoding="utf-8") as fh:
        raw = [ln.strip() for ln in fh if ln.strip()][:n]
    strip_dir = os.path.join(PROBE_DIR, "real_stripped", "images")
    if not os.path.isdir(strip_dir):
        raise SystemExit(f"缺 {strip_dir} —— 先跑 63 号探针")
    strips = []
    for p in raw:
        s = os.path.join(strip_dir, os.path.basename(p))
        if not os.path.isfile(s):
            raise SystemExit(f"剥离版缺 {s}")
        strips.append(s)
    out = {}
    for key, paths in (("raw", raw), ("stripped", strips)):
        lst = os.path.join(PROBE_DIR, f"ctxsupp_{key}_{n}.txt")
        with open(lst, "w", encoding="utf-8") as fh:
            fh.write("".join(p + "\n" for p in paths))
        yml = os.path.join(PROBE_DIR, f"ctxsupp_{key}_{n}.yaml")
        with open(yml, "w", encoding="utf-8") as fh:
            fh.write(f"path: {REAL_DIR}\ntrain: {lst}\nval: {lst}\ntest: {lst}\n"
                     "nc: 1\nnames: [product]\n")
        out[key] = yml
    return out


def ev(ckpt, yaml):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=yaml, split="test", imgsz=640, batch=4, device="0",
              max_det=1000, workers=2, verbose=False)
    return {"map50": float(r.box.map50), "map50_95": float(r.box.map),
            "precision": float(r.box.mp), "recall": float(r.box.mr),
            "n_images": int(getattr(r, "n_images", 0) or 0)}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", default=SEEDS)
    ap.add_argument("--arm-run", default="runs_ctxsupp_s{seed}",
                    help="臂的权重目录模板 (默认 I-19 的 runs_ctxsupp_s{seed})")
    ap.add_argument("--control-run", default="runs_r1_s{seed}",
                    help="对照的权重目录模板 (默认 R1 对照臂)")
    ap.add_argument("--out", default=OUT, help="产物路径")
    ap.add_argument("--question", default=None,
                    help="覆盖产物里的问题描述 (复用本脚本测别的臂时用 ✓)")
    ap.add_argument("--schema", default="context_suppress_probe/1",
                    help="产物的 schema 名 (复用本脚本测别的臂时用 ✓)")
    args = ap.parse_args()
    out_path = args.out
    raw_yaml = subset_yaml("raw")["raw"]
    strip_yaml = subset_yaml("stripped")["stripped"]
    log(f"子集: {N_IMG} 张 (原图 / 剥离版); 臂目录模板 {args.arm_run}")
    # **断点续跑**: 产物里已有的 (seed, 模型) 结果直接复用 ✓ (评测是确定性的 ✓),
    # 这样补算统计量不必重跑 GPU 评测 ✓。
    prev = {}
    if os.path.isfile(out_path):
        try:
            prev = json.load(open(out_path, encoding="utf-8")).get("models") or {}
        except Exception:
            prev = {}
    rep = {"schema": args.schema,
           "generated_by": "pipelines/shelf_sdg/67_context_suppress_probe.py",
           "measured_at": time.strftime("%Y-%m-%d"),
           "arm_run": args.arm_run,
           "control_run": args.control_run,
           "question": (args.question or
                        "这个臂的模型比对照更依赖上下文吗? (I-19 的干预有没有真的降低上下文依赖?)"),
           "n_images": N_IMG,
           "subset_note": ("取 63 号探针同一份名单的前 300 张 (原图与剥离版同序 ✓); "
                           "对照与臂都在**同一份子集**上评 -> 可配对 ✓"),
           "models": {}}
    for seed in args.seeds:
        for tag, run in (("control", args.control_run.format(seed=seed)),
                         ("arm", args.arm_run.format(seed=seed))):
            ck = os.path.join(BENCH, run, "train", "weights", "last.pt")
            if not os.path.isfile(ck):
                log(f"缺权重 {ck}, 跳过")
                continue
            old = ((prev.get(str(seed)) or {}).get(tag) or {})
            if "raw" in old and "stripped" in old:
                row = old
                log(f"seed {seed} {tag}: 复用已有结果 (raw {row['raw']['map50']:.4f})")
            else:
                row = {"raw": ev(ck, raw_yaml), "stripped": ev(ck, strip_yaml)}
                log(f"seed {seed} {tag}: raw {row['raw']['map50']:.4f} -> 剥离版 "
                    f"{row['stripped']['map50']:.4f}")
            row["delta_real_pp"] = (row["stripped"]["map50"] - row["raw"]["map50"]) * 100
            rep["models"].setdefault(str(seed), {})[tag] = row

    def paired_stats(diffs):
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

    # 三个配对比较:
    #   arm_minus_control_delta_pp : 上下文依赖度的差 (越大 = 越依赖上下文 ✓)
    #   arm_minus_control_raw_pp    : 真实原图上的差 (迁移效果 ✓)
    #   arm_minus_control_stripped_pp: 剥离上下文的真实图上的差 (商品识别本身 ✓)
    buckets = {"delta_pp": [], "raw_pp": [], "stripped_pp": []}
    for s, m in rep["models"].items():
        if "control" in m and "arm" in m:
            buckets["delta_pp"].append(m["arm"]["delta_real_pp"] - m["control"]["delta_real_pp"])
            buckets["raw_pp"].append((m["arm"]["raw"]["map50"] - m["control"]["raw"]["map50"]) * 100)
            buckets["stripped_pp"].append(
                (m["arm"]["stripped"]["map50"] - m["control"]["stripped"]["map50"]) * 100)
    rep["arm_minus_control_delta_pp"] = paired_stats(buckets["delta_pp"])
    rep["arm_minus_control_raw_pp"] = paired_stats(buckets["raw_pp"])
    rep["arm_minus_control_stripped_pp"] = paired_stats(buckets["stripped_pp"])
    # 对照自己的上下文依赖度均值 (用来和 63 号探针的 800 张口径对照 ✓)
    ctrl_delta = [m["control"]["delta_real_pp"] for m in rep["models"].values()
                  if "control" in m]
    if ctrl_delta:
        rep["control_context_dependence_pp"] = {
            "n": len(ctrl_delta),
            "mean_pp": round(sum(ctrl_delta) / len(ctrl_delta), 4),
            "per_seed_pp": [round(v, 4) for v in ctrl_delta]}
    for k, v in (("上下文依赖差", rep["arm_minus_control_delta_pp"]),
                 ("真实原图差", rep["arm_minus_control_raw_pp"]),
                 ("剥离版差", rep["arm_minus_control_stripped_pp"])):
        if v:
            log(f"臂-对照 {k}: {v['mean_pp']:+.2f} pp, CI {v.get('ci95_pp')}")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    log(f"-> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
