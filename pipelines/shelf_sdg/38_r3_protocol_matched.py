#!/usr/bin/env python3
"""R3 域对齐臂的**协议对齐复跑** (2026-11-23)。

为什么需要这个脚本
------------------
已发布四臂里的 R3-full (纯合成 + 域对齐参数: cam_mult1.6 / lens40 / misalign0.35 / bays5)
有三重问题, 使它在仓内**不可复现、不可比较**:

  1. 协议记录与实际训练配置矛盾 (审计 F3): 首跑 15/8 epoch, 产物 json 记 10 epoch;
  2. 它的合成集是**旧划分**那一份 (已被 2026-11-21 的场景级留出集覆盖), 现已不存在;
  3. 它是 **400 图** 的训练集, 而当前协议的 R1 是 **160 图** (场景级留出 train 160/val 40)
     -> 即使重跑, 图数、划分、场景族都不同, 与 R1/R0 不可比。

于是审计里"域对齐不是充分条件" (C7) 这条判决, 实际靠的是一次**不可复现**的运行。

本脚本做的事: 把 R3-full 重做成**与当前协议完全对齐**的臂, 只留一个自变量:

  | 项                | R1 (对照, 已有)          | R3pm (本脚本)              |
  |-------------------|--------------------------|----------------------------|
  | 图像数 / 划分      | 200 图 = 160/40 场景级留出 | 200 图 = 160/40 场景级留出  |
  | base_seed / 抽样   | 42 / val_ratio 0.2       | 42 / val_ratio 0.2         |
  | images_per_scene   | 4                        | 4                          |
  | samples (射线网格) | 64                       | 64                         |
  | 标签语义 / 单类化   | 同一套 (visible-tight + 丢 class1) | 同一套 ✅      |
  | 训练协议           | YOLO11n/640/10ep/batch4/seed | 同上, **多 seed** ✅     |
  | **处理变量**       | cam1.0/lens28/mis0.10/bays1 | cam1.6/lens40/mis0.35/bays5 |

即: **除 SDG 配方外一切相同**, 于是 "R3pm − R1" 就是域对齐这一个因子的效应。

同时落两样东西:
  * 每个 seed 的产物 (与四臂同 schema: protocol / protocol_manifest / dataset / map50 …),
    供 36 号汇总脚本直接纳入;
  * 该合成集自己的域差距实测 (密度/尺度/朝向) —— **"域对齐"这个说法本身要被测量检验**:
    如果配方改了但密度/框面积/朝向三个因子没往真实侧靠, 那 "域对齐" 只是名字。

用法 (需 GPU 空闲):
    python pipelines/shelf_sdg/38_r3_protocol_matched.py --stage render
    python pipelines/shelf_sdg/38_r3_protocol_matched.py --stage train --seeds 42,43,44
    python pipelines/shelf_sdg/38_r3_protocol_matched.py --stage summarize
"""
import argparse
import glob
import json
import os
import re
import statistics as st
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import blender_command  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
SDG_OUT = os.path.join(BENCH, "sdg_R3pm")
SYNTH_OUT = os.path.join(BENCH, "synth_single_R3pm")

# 与当前协议 (output/sdg_shelf/split_manifest.json) 完全一致的部分
PROTO_SPLIT = dict(num_images=200, seed=42, val_ratio=0.2, images_per_scene=4,
                    split_mode="scene", samples=64)
# 唯一的处理变量: 域对齐配方 (R3-full)
TREATMENT = dict(cam_mult=1.6, lens=40.0, misalign=0.35, bays=5)

# 对照臂 (当前协议的 R1) 的同 seed 产物 —— 用于配对比较
CONTROL_ARTIFACTS = {
    42: "sku110k_r1_scenebest.json",   # 同配方同 seed 42 (best.pt 与 last.pt 同值)
    43: "sku110k_r1_s43.json",
    44: "sku110k_r1_s44.json",
    45: "sku110k_r1_s45.json",
    46: "sku110k_r1_s46.json",
    47: "sku110k_r1_s47.json",
}


def log(msg):
    print(f"[R3PM {time_str()}] {msg}", flush=True)


def time_str():
    import time
    return time.strftime("%m-%d %H:%M:%S")


def render():
    """用 Blender 按 R3-full 配方 + 当前协议的划分参数生成合成集。

    2026-11-23: 用 blender_command() 而不是 blender_bin() —— Windows 上本机的
    Blender 入口是 tools/blender.cmd (bpy pip 模块替身), 直接 exec .cmd 会
    WinError 193, blender_command() 统一经 cmd.exe /c 转发。
    """
    out = os.path.join(BENCH, "sdg_R3pm")
    cmd = blender_command() + ["-b", "-P",
                               os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"), "--",
           "--num-images", str(PROTO_SPLIT["num_images"]),
           "--seed", str(PROTO_SPLIT["seed"]),
           "--val-ratio", str(PROTO_SPLIT["val_ratio"]),
           "--images-per-scene", str(PROTO_SPLIT["images_per_scene"]),
           "--split-mode", PROTO_SPLIT["split_mode"],
           "--samples", str(PROTO_SPLIT["samples"]),
           "--cam-mult", str(TREATMENT["cam_mult"]),
           "--lens", str(TREATMENT["lens"]),
           "--misalign", str(TREATMENT["misalign"]),
           "--bays", str(TREATMENT["bays"]),
           "--out", out]
    log("RUN " + " ".join(cmd[2:]))
    log(f"[R3PM] 渲染 {PROTO_SPLIT['num_images']} 图 (bays={TREATMENT['bays']}), "
        f"这一步最慢, 预计数小时")
    # 输出**流式写日志**而不是 capture_output: 渲染要几小时, 全capture 等于全程没日志,
    # 而且末尾要靠 stdout 找错误时已经晚了。
    log_path = os.path.join(BENCH, "chain_steps", "r3pm_render.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="ignore") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=28800)
    if r.returncode != 0:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
            tail = fh.read()[-3000:]
        print(tail)
        raise SystemExit(f"[R3PM] SDG 生成失败 (退出码 {r.returncode}); 日志 {log_path}")
    log(f"渲染完成 (日志 {log_path})")
    return out


def to_single(src):
    """4 类 -> 单类 product (丢 class 1 = OOS gap), 与 14 号 build_synth_single 同逻辑。"""
    import shutil
    dst = SYNTH_OUT
    os.makedirs(dst, exist_ok=True)
    for split in ("train", "val"):
        isrc = os.path.join(src, "images", split)
        lsrc = os.path.join(src, "labels", split)
        idst = os.path.join(dst, "images", split)
        ldst = os.path.join(dst, "labels", split)
        os.makedirs(idst, exist_ok=True)
        os.makedirs(ldst, exist_ok=True)
        if not os.path.isdir(isrc):
            continue
        for f in os.listdir(isrc):
            shutil.copy2(os.path.join(isrc, f), os.path.join(idst, f))
            lines = []
            t = os.path.join(lsrc, f.replace(".png", ".txt"))
            if os.path.exists(t):
                for ln in open(t, encoding="utf-8"):
                    p = ln.split()
                    if len(p) == 5 and p[0] != "1":
                        lines.append("0 " + " ".join(p[1:]))
            with open(os.path.join(ldst, f.replace(".png", ".txt")), "w", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))
    y = os.path.join(dst, "dataset.yaml")
    with open(y, "w", encoding="utf-8") as fh:
        fh.write(f"path: {dst}\ntrain: images/train\nval: images/val\nnc: 1\nnames: [product]\n")
    return y


def train(seeds):
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "b14", os.path.join(BASE, "pipelines/shelf_sdg/14_sku110k_baseline.py"))
    m14 = ilu.module_from_spec(spec)
    spec.loader.exec_module(m14)
    from pipelines.common.protocol import (build_manifest, dir_fingerprint,  # noqa: E402
                                           runtime_versions)
    from ultralytics import YOLO

    yaml_path = to_single(SDG_OUT)
    device = m14.resolve_device()
    for seed in seeds:
        out_json = os.path.join(BENCH, f"sku110k_r3pm_s{seed}.json")
        if os.path.exists(out_json):
            log(f"SKIP r3pm seed={seed} (已存在)")
            continue
        proto = {"model": "yolo11n.pt", "imgsz": 640, "epochs": 10, "batch": 4,
                 "workers": 2, "cache": False, "seed": seed, "max_det": 1000, "device": "auto"}
        # 14 号的 protocol_hash() 用的是它自己的 PROTOCOL 字典 —— 不同步 seed 的话,
        # 三个 seed 的产物会算出**同一个 hash** (都按 seed 42 算) → 哈希就废了。
        m14.PROTOCOL["seed"] = seed
        batch, workers = m14.mem_guard()
        model = YOLO(proto["model"])
        model_fp = m14.model_weights_fingerprint(model, proto["model"])
        run_dir = os.path.join(BENCH, f"runs_R3pm_s{seed}")
        log(f"训练 r3pm seed={seed} (batch={batch} workers={workers} device={device})")
        model.train(data=yaml_path, epochs=proto["epochs"], imgsz=proto["imgsz"],
                    batch=batch, seed=proto["seed"], device=device, workers=workers,
                    project=run_dir, name="train", exist_ok=True)
        ckpt = os.path.join(run_dir, "train", "weights", "best.pt")
        # 归档用**带 seed 的文件名** —— 否则每个 seed 都往 weights/r3pm/best.pt 覆盖,
        # 仓里只剩最后一个 seed 的权重, 与其他 seed 的数字对不上。
        import shutil
        ckpt_tagged = os.path.join(run_dir, "train", "weights", f"best_s{seed}.pt")
        shutil.copy2(ckpt, ckpt_tagged)
        ev = YOLO(ckpt)
        r = ev.val(data=m14.sku110k_yaml(), split="test", imgsz=proto["imgsz"],
                   device=device, max_det=proto["max_det"],
                   project=run_dir, name="val", exist_ok=True)
        rep = {
            "arm": "r3pm",
            "run_id": f"r3pm_s{seed}",
            "dataset": {
                "arm": "r3pm",
                "sources": [{"kind": "synthetic_only",
                             "path": os.path.join(SYNTH_OUT, "images", "train"),
                             "n_images": len(glob.glob(os.path.join(SYNTH_OUT, "images", "train", "*.png"))),
                             "fingerprint": dir_fingerprint(os.path.join(SYNTH_OUT, "images", "train"))}],
                "note": "协议对齐的 R3-full (域对齐配方); 对照臂 = 当前协议的 R1 (同图数同划分同种子)",
            },
            "protocol": proto,
            "protocol_hash": m14.protocol_hash(),
            "actual_train_config": {"epochs": proto["epochs"], "batch": batch,
                                    "workers": workers, "device": device},
            "map50": float(r.box.map50),
            "map50_95": float(r.box.map),
            "precision": float(r.box.mp), "recall": float(r.box.mr),
            "checkpoint": m14.archive_checkpoint("r3pm", ckpt_tagged, "best"),
            "model_weights": model_fp,
            "protocol_manifest": build_manifest(
                proto,
                data={"treatment": TREATMENT, "split_protocol": PROTO_SPLIT,
                      "synth_dir": os.path.relpath(SYNTH_OUT, BASE).replace("\\", "/")},
                splits=m14.split_fingerprints("r1", synth_dir=SYNTH_OUT),
                actual={"epochs": proto["epochs"], "batch": batch, "workers": workers,
                        "device": device},
                deps=runtime_versions(),
                extra={"model_weights": model_fp}),
            "treatment": TREATMENT,
            "split_protocol": PROTO_SPLIT,
        }
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        log(f"r3pm seed={seed}: map50={rep['map50']:.4f} map50_95={rep['map50_95']:.4f}")


def synth_composition(sdg_dir):
    """合成集的目标构成 (状态机占比) + 可见占比 —— 用来解释"为什么更差"。

    class 0=合规 / 1=OOS gap(单类化时丢弃) / 2=朝向错位 / 3=竞品入侵。
    R3-full 配方把 misalign 提到 0.35 → 错位商品占比从 ~10% 涨到 ~36%,
    而错位框在单类化后**仍然算商品** → 训练信号里"倾斜商品"的比重暴涨。
    """
    hist = {}
    vf = []
    n = 0
    for f in sorted(glob.glob(os.path.join(sdg_dir, "annotations", "*.json"))):
        try:
            recs = json.load(open(f, encoding="utf-8")).get("annotations", [])
        except Exception:
            continue
        for r in recs:
            hist[str(r.get("class_id"))] = hist.get(str(r.get("class_id")), 0) + 1
            n += 1
            if r.get("visible_frac") is not None:
                vf.append(r["visible_frac"])
    tot = n or 1
    kept = tot - hist.get("1", 0)
    return {
        "n_objects": n,
        "class_hist": hist,
        "class_share": {k: round(v / tot, 4) for k, v in sorted(hist.items())},
        "kept_objects": kept,
        "misaligned_share_of_kept": round(hist.get("2", 0) / kept, 4) if kept else None,
        "noncompliant_share_of_kept": round((hist.get("2", 0) + hist.get("3", 0)) / kept, 4) if kept else None,
        "mean_visible_frac": round(sum(vf) / len(vf), 4) if vf else None,
        "note": "class 2=朝向错位, class 3=竞品入侵; 两者在单类化后都算 product",
    }


def domain_gap_of(synth_dir):
    """该合成集自己的域差距因子 (密度/尺度/朝向) —— 检验"域对齐"是否真的往真实侧靠。

    **复用 23 号脚本的度量函数** (`read_labels`/`stats`), 不自己再写一份:
    本脚本原先有一份手抄版, 真实侧用了 CSV 的**像素**面积而合成侧用**归一化**面积,
    两个单位直接相比 —— A2 那一栏是错的 (真实 18300 vs 合成 0.0039)。
    真实侧直接读已发布的 `domain_gap_measure.json` (同一份真实数据, 不必重算 8219 张图)。

    口径: 框面积/宽高比都按**归一化**算 (合成侧本来就是; 真实侧由 23 号统一处理)。
    """
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "b23", os.path.join(BASE, "pipelines/shelf_sdg/23_domain_gap_measure.py"))
    m23 = ilu.module_from_spec(spec)
    spec.loader.exec_module(m23)

    items = m23.read_labels(os.path.join(synth_dir, "labels", "train"),
                             os.path.join(synth_dir, "images", "train"))
    if not items:
        return {"error": f"没有标签: {synth_dir}"}

    def side(it):
        return {
            "n_images": len(it),
            "boxes_per_image": m23.stats([x["n_boxes"] for x in it]),
            "mean_box_area": m23.stats([x["mean_area"] for x in it]),
            "median_aspect_ratio": m23.stats([x["median_ar"] for x in it]),
            "image_res": sorted({(x["W"], x["H"]) for x in it})[:5],
            "total_boxes": sum(x["n_boxes"] for x in it),
        }

    synth = side(items)
    real = {}
    pub = os.path.join(BENCH, "domain_gap_measure.json")
    if not os.path.exists(pub):
        pub = os.path.join(BASE, "docs", "research", "benchmark", "domain_gap_measure.json")
    if os.path.exists(pub):
        try:
            real = json.load(open(pub, encoding="utf-8")).get("real", {})
        except Exception:
            real = {}
    return {"synth_dir": os.path.relpath(synth_dir, BASE).replace("\\", "/"),
            "synth": synth, "real": real,
            "source_note": "合成侧用 23 号脚本的同一套度量; 真实侧取已发布的 domain_gap_measure.json"}


def summarize(seeds):
    """汇总: R3pm 各 seed + 同 seed 的 R1 对照 + 域差距因子。

    **配对差值与 CI 只在 36 号脚本里算** (四臂/五臂汇总的唯一事实源), 这里只引用,
    避免同一个统计量在两个脚本里各算一遍、日后对不上。

    **汇总必须覆盖磁盘上所有已完成的 seed, 不能只看本次传入的 seeds**:
    40 号链分批跑 (先 42–45 再 46/47), 如果 summarize 只把"本次传入的 seed"写进产物,
    后一次就会把前一次的 seed 覆盖掉 —— 表现为产物里只剩 2 个 seed、mean 变成那 2 个的
    平均 (2026-11-24 实测: 跑了 46/47 后 r3pm_mean 从 0.1435 变成 0.1443, per_seed 只剩
    46/47, 而 README 写的是 6 个 seed 的 mean 0.1435)。所以这里扫全目录, seeds 参数
    只用来决定"要不要强制重算", 不决定"汇总哪些"。
    """
    all_seeds = set(seeds)
    for f in glob.glob(os.path.join(BENCH, "sku110k_r3pm_s*.json")):
        m = re.search(r"_s(\d+)\.json$", os.path.basename(f))
        if m:
            all_seeds.add(int(m.group(1)))
    arms = {}
    for seed in sorted(all_seeds):
        p = os.path.join(BENCH, f"sku110k_r3pm_s{seed}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        arms[seed] = {"r3pm": d["map50"], "r3pm_95": d["map50_95"]}
        c = CONTROL_ARTIFACTS.get(seed)
        if c and os.path.exists(os.path.join(BENCH, c)):
            cd = json.load(open(os.path.join(BENCH, c), encoding="utf-8"))
            arms[seed]["r1"] = cd["map50"]
            arms[seed]["r1_artifact"] = c
    diffs = [(s, v["r3pm"] - v["r1"]) for s, v in arms.items() if "r1" in v]
    out = {
        "schema": "r3_protocol_matched/1",
        "measured_at": "2026-11-23",
        "treatment": TREATMENT,
        "split_protocol": PROTO_SPLIT,
        "control_note": "对照 = 当前协议的 R1 (同 200 图 / 同场景级留出 / 同训练协议 / 同 seed)",
        "per_seed": arms,
        "r3pm_mean": round(st.mean([v["r3pm"] for v in arms.values()]), 4) if arms else None,
        "r3pm_std": round(st.stdev([v["r3pm"] for v in arms.values()]), 4) if len(arms) > 1 else None,
        "r1_mean": round(st.mean([v["r1"] for v in arms.values() if "r1" in v]), 4) if diffs else None,
        "raw_paired_diff_pp": [round(d * 100, 3) for _, d in diffs],
        "paired_diff_pp": None,
        "paired_diff_ci95_pp": None,
        "paired_stats_source": "docs/research/benchmark/fourarm_seed_variance.json (36 号脚本算)",
        "domain_gap_r3pm": domain_gap_of(SYNTH_OUT),
        "domain_gap_r1": domain_gap_of(os.path.join(BENCH, "synth_single")),
        "composition_r3pm": synth_composition(SDG_OUT),
        "composition_r1": synth_composition(os.path.join(BASE, "output", "sdg_shelf")),
    }
    # 引用 36 号的配对结果 (若已跑)
    fsv = os.path.join(BENCH, "fourarm_seed_variance.json")
    if os.path.exists(fsv):
        try:
            j = json.load(open(fsv, encoding="utf-8"))
            for pr in j.get("paired", []):
                if (pr.get("b"), pr.get("a")) == ("r3pm", "r1"):
                    out["paired_diff_pp"] = pr.get("map50_diff_mean_pp")
                    out["paired_diff_ci95_pp"] = pr.get("map50_diff_ci95")
                    out["paired_n"] = pr.get("n_pairs")
        except Exception:
            pass
    # 域差距三因子: R1 (默认配方) vs R3pm (域对齐配方) vs 真实 —— 同一套度量 (23 号脚本)
    def pick(gap, path):
        cur = gap.get("synth", {}) if isinstance(gap, dict) else {}
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        return cur

    def pick_real(path):
        cur = out["domain_gap_r1"].get("real", {})
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        return cur

    out["domain_gap_comparison"] = {
        "boxes_per_image_mean": {
            "r1": pick(out["domain_gap_r1"], ["boxes_per_image", "mean"]),
            "r3pm": pick(out["domain_gap_r3pm"], ["boxes_per_image", "mean"]),
            "real": pick_real(["boxes_per_image", "mean"])},
        "mean_box_area_mean": {
            "r1": pick(out["domain_gap_r1"], ["mean_box_area", "mean"]),
            "r3pm": pick(out["domain_gap_r3pm"], ["mean_box_area", "mean"]),
            "real": pick_real(["mean_box_area", "mean"])},
        "median_aspect_ratio_mean": {
            "r1": pick(out["domain_gap_r1"], ["median_aspect_ratio", "mean"]),
            "r3pm": pick(out["domain_gap_r3pm"], ["median_aspect_ratio", "mean"]),
            "real": pick_real(["median_aspect_ratio", "mean"])},
    }
    p = os.path.join(BENCH, "r3_protocol_matched.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    log(f"汇总 -> {p}")
    for s, v in arms.items():
        log(f"  seed {s}: R3pm {v['r3pm']:.4f}" +
            (f" vs R1 {v['r1']:.4f} (Δ {(v['r3pm'] - v['r1']) * 100:+.2f}pp)" if "r1" in v else ""))
    if out["paired_diff_ci95_pp"]:
        log(f"  配对差值 (引自 36 号汇总) mean {out['paired_diff_pp']:+.2f}pp, "
            f"95% CI {out['paired_diff_ci95_pp']}")
    else:
        log("  配对差值: 先跑 36_fourarm_seed_variance.py 再重跑本脚本的 summarize 阶段")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("render", "train", "summarize", "all"), default="all")
    ap.add_argument("--seeds", default="42,43,44")
    args = ap.parse_args()
    seeds = [int(s) for s in args.seeds.split(",") if s.strip()]
    os.makedirs(os.path.join(BENCH, "chain_steps"), exist_ok=True)
    if args.stage in ("render", "all"):
        render()
    if args.stage in ("train", "all"):
        train(seeds)
    if args.stage in ("summarize", "all"):
        summarize(seeds)


if __name__ == "__main__":
    main()
