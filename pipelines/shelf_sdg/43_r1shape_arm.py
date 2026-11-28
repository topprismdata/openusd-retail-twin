#!/usr/bin/env python3
"""R1 + 形状先验臂 (2026-11-23): 只动"朝向因子"的单因子干预。

为什么有这个臂
--------------
上一轮 (脚本 38) 的结论是"本项目的 SDG 生成器无法正确表达域对齐" —— 那个结论**有一半是错的**,
复盘后发现是我的诊断搞错了:

  * 域差距三因子 = 密度 / 尺度 / 朝向; "域对齐"配方 (R3-full: cam1.6/lens40/mis0.35/bays5)
    调的是**镜头与摆货**, 而"朝向因子"它**根本没碰**;
  * 更关键: 生成器里"朝向"并不是不可表达的 —— 所有商品共用一个箱子
    (PACK_W 0.048 x PACK_H 0.136, 世界宽高比 0.353), 所以投影宽高比被钉在 0.32,
    而真实域逐图中位宽高比均值是 **1.05** (p10 0.38 / p90 1.92);
  * "misalign" 状态只是把箱子**绕竖轴转 82 度** (面朝错了), 投影宽高比从 0.353 变成
    0.324 —— 所以 R3-full 的朝向因子不升反降, **不是"调不动", 是没调**。

于是这里做一个**只差一个变量**的臂: 与 R1 对照集**完全相同的配方**
(cam1.0/lens28/mis0.10/bays1/200 图/场景级留出/seed 42/同一套标签语义/同一训练协议),
只多一个 --shape-profile real: 按真实域的形状分布给每个商品采样长宽与投影面积
(逐图采一个"宽窄构成", 图内加对数正态抖动)。

**⚠️ 2026-11-24 订正**: 原文写"面积保持不变 -> 只动朝向因子" —— **这是错的**, 实际
面积也变了 (--shape-area-gain 0.782), 实测单框面积 0.0053 -> 0.0031 (真实 0.0030)。
所以这个臂动的是**朝向 + 尺度两个因子**(恰好是域差距三因子里的两个), 不是单因子臂。
这不影响它作为"域对齐"实验的有效性 —— 两个因子都是朝真实侧动的, 结论照样成立;
但**"只动一个因子"的措辞必须去掉**, 否则会把一个两因子干预写成单因子实验。
另外, 每图保留框数 21.83 -> 20.63 不是"改了别的变量", 而是几何干预的**下游必然后果**:
商品改宽 -> 遮挡变多 -> 可见度过滤 (vis_frac < 15%) 丢弃的记录变多 (实测 3.98%,
对照臂 0%)。

预测与解读
----------
  * 若朝向/尺度因子真的被操作 (实测: 逐图中位宽高比 0.32 -> 0.79, 单框面积 0.0053 ->
    0.0031, 两者都更接近真实的 1.05 / 0.0030), 而 mAP **没有**改善 -> 说明
    "把朝向+尺度对齐到真实侧"**本身不是**域差距的主因 (之前 R3-full 的失败不能归因于
    "只对齐了两个因子");
  * 若 mAP **改善** -> "域对齐"确实是有效手段, 之前失败是因为配方没操作朝向/尺度。

用法 (需 GPU 空闲; 渲染是 CPU, 可与训练并行):
    python pipelines/shelf_sdg/43_r1shape_arm.py --stage render
    python pipelines/shelf_sdg/43_r1shape_arm.py --stage train --seeds 42,43,44
    python pipelines/shelf_sdg/43_r1shape_arm.py --stage summarize
"""
import argparse
import glob
import json
import os
import re
import shutil
import statistics as st
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import blender_command  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
SDG_OUT = os.path.join(BENCH, "sdg_shape")
SYNTH_OUT = os.path.join(BENCH, "synth_single_shape")

# 与 R1 对照集 (output/sdg_shelf) 完全一致的配方 —— 唯一多出来的是形状先验
CONTROL_RECIPE = dict(num_images=200, seed=42, val_ratio=0.2, images_per_scene=4,
                      split_mode="scene", samples=64,
                      cam_mult=1.0, lens=28.0, misalign=0.10, bays=1)
GAIN = 1.214         # 由 42 号探针逐框拟合: gain_fit = median(投影宽高比/世界宽高比) = 0.8234
AREA_GAIN = 0.782    # 由 42 号探针逐框拟合: area_gain_fit = median(投影框面积/世界正面面积) = 0.7824
MAX_WIDTH = 0.14     # 商品世界宽度上限 (槽位间距 0.08; 放宽以容纳真实域的宽尾)


def log(msg):
    print(f"[R1SH {time_str()}] {msg}", flush=True)


def time_str():
    import time
    return time.strftime("%m-%d %H:%M:%S")


def render(threads=4):
    # 2026-11-23: 强制 Cycles 走 CPU (GPU 要留给 YOLO 训练; 否则渲染排在 GPU 队列里干等)。
    # 线程数默认压到 4: 渲染与 YOLO 训练同时跑时, 渲染会把 12 核吃满 -> 训练的数据加载
    # 被饿死 (实测 r3pm 训练被拖成 50 分钟)。留一半核给训练。
    # 2026-11-24: 强制 CPU 改成**可配置** (SDG_RENDER_DEVICE=cpu|gpu) —— 强制 CPU 的唯一
    # 理由是"GPU 要留给训练"; GPU 空闲时用 OPTIX 快 2 倍以上 (实测 18 s/图 vs 40 s/图)。
    env = dict(os.environ)
    dev = os.environ.get("SDG_RENDER_DEVICE", "").strip().lower()
    if dev == "cpu":
        env["FORCE_CPU_RENDER"] = "1"
    else:
        env.pop("FORCE_CPU_RENDER", None)
        env["CYCLES_DEVICE"] = env.get("CYCLES_DEVICE", "OPTIX")
    cmd = blender_command() + ["-b", "-t", str(threads), "-P",
                               os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"), "--",
           "--num-images", str(CONTROL_RECIPE["num_images"]),
           "--seed", str(CONTROL_RECIPE["seed"]),
           "--val-ratio", str(CONTROL_RECIPE["val_ratio"]),
           "--images-per-scene", str(CONTROL_RECIPE["images_per_scene"]),
           "--split-mode", CONTROL_RECIPE["split_mode"],
           "--samples", str(CONTROL_RECIPE["samples"]),
           "--cam-mult", str(CONTROL_RECIPE["cam_mult"]),
           "--lens", str(CONTROL_RECIPE["lens"]),
           "--misalign", str(CONTROL_RECIPE["misalign"]),
           "--bays", str(CONTROL_RECIPE["bays"]),
           "--shape-profile", "real",
           "--shape-aspect-gain", str(GAIN),
           "--shape-area-gain", str(AREA_GAIN),
           "--shape-max-width", str(MAX_WIDTH),
           "--out", SDG_OUT]
    log("RUN " + " ".join(cmd[2:]))
    log_path = os.path.join(BENCH, "chain_steps", "r1shape_render.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8", errors="ignore") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=28800, env=env)
    if r.returncode != 0:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
            print(fh.read()[-3000:])
        raise SystemExit(f"[R1SH] SDG 生成失败 (退出码 {r.returncode}); 日志 {log_path}")
    log(f"渲染完成 (日志 {log_path})")
    return SDG_OUT


def to_single(src):
    """4 类 -> 单类 product (丢 class 1 = OOS gap), 与 14/38 号同逻辑。"""
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
        out_json = os.path.join(BENCH, f"sku110k_r1shape_s{seed}.json")
        if os.path.exists(out_json):
            log(f"SKIP r1shape seed={seed} (已存在)")
            continue
        proto = {"model": "yolo11n.pt", "imgsz": 640, "epochs": 10, "batch": 4,
                 "workers": 2, "cache": False, "seed": seed, "max_det": 1000, "device": "auto"}
        m14.PROTOCOL["seed"] = seed
        batch, workers = m14.mem_guard()
        model = YOLO(proto["model"])
        model_fp = m14.model_weights_fingerprint(model, proto["model"])
        run_dir = os.path.join(BENCH, f"runs_r1shape_s{seed}")
        log(f"训练 r1shape seed={seed} (batch={batch} workers={workers} device={device})")
        model.train(data=yaml_path, epochs=proto["epochs"], imgsz=proto["imgsz"],
                    batch=batch, seed=proto["seed"], device=device, workers=workers,
                    project=run_dir, name="train", exist_ok=True)
        ckpt = os.path.join(run_dir, "train", "weights", "best.pt")
        ckpt_tagged = os.path.join(run_dir, "train", "weights", f"best_s{seed}.pt")
        shutil.copy2(ckpt, ckpt_tagged)
        ev = YOLO(ckpt)
        r = ev.val(data=m14.sku110k_yaml(), split="test", imgsz=proto["imgsz"],
                   device=device, max_det=proto["max_det"],
                   project=run_dir, name="val", exist_ok=True)
        rep = {
            "arm": "r1shape",
            "run_id": f"r1shape_s{seed}",
            "dataset": {
                "arm": "r1shape",
                "sources": [{"kind": "synthetic_only",
                             "path": os.path.join(SYNTH_OUT, "images", "train"),
                             "n_images": len(glob.glob(os.path.join(SYNTH_OUT, "images", "train", "*.png"))),
                             "fingerprint": dir_fingerprint(os.path.join(SYNTH_OUT, "images", "train"))}],
                "note": "R1 对照配方 + 形状先验 (朝向与尺度两个因子都按真实域分布重采样; 密度是几何干预的下游涌现量, 见 visible_frac 过滤); 对照臂 = 同配方无形状先验的 R1",
            },
            "protocol": proto,
            "protocol_hash": m14.protocol_hash(),
            "actual_train_config": {"epochs": proto["epochs"], "batch": batch,
                                    "workers": workers, "device": device},
            "map50": float(r.box.map50),
            "map50_95": float(r.box.map),
            "precision": float(r.box.mp), "recall": float(r.box.mr),
            "checkpoint": m14.archive_checkpoint("r1shape", ckpt_tagged, "best"),
            "model_weights": model_fp,
            "protocol_manifest": build_manifest(
                proto,
                data={"treatment": {"shape_profile": "real", "shape_aspect_gain": GAIN,
                          "shape_area_gain": AREA_GAIN, "shape_max_width": MAX_WIDTH},
                      "split_protocol": CONTROL_RECIPE,
                      "synth_dir": os.path.relpath(SYNTH_OUT, BASE).replace("\\", "/")},
                splits=m14.split_fingerprints("r1", synth_dir=SYNTH_OUT),
                actual={"epochs": proto["epochs"], "batch": batch, "workers": workers,
                        "device": device},
                deps=runtime_versions(),
                extra={"model_weights": model_fp}),
            "treatment": {"shape_profile": "real", "shape_aspect_gain": GAIN,
                          "shape_area_gain": AREA_GAIN, "shape_max_width": MAX_WIDTH},
            "split_protocol": CONTROL_RECIPE,
        }
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        log(f"r1shape seed={seed}: map50={rep['map50']:.4f} map50_95={rep['map50_95']:.4f}")


def summarize(seeds):
    """各 seed 结果 + 域差距三因子 (与 R1 对照逐项对比) + 配对统计 (引自 36 号)。

    **汇总扫全目录, 不只看本次传入的 seeds** —— 否则分批跑 (42–44 / 45–47) 时,
    后一次会把前一次的 seed 从产物里覆盖掉 (与 38 号脚本同一个坑, 2026-11-24 修)。
    """
    all_seeds = set(seeds)
    for f in glob.glob(os.path.join(BENCH, "sku110k_r1shape_s*.json")):
        m = re.search(r"_s(\d+)\.json$", os.path.basename(f))
        if m:
            all_seeds.add(int(m.group(1)))
    arms = {}
    for seed in sorted(all_seeds):
        p = os.path.join(BENCH, f"sku110k_r1shape_s{seed}.json")
        if not os.path.exists(p):
            continue
        d = json.load(open(p, encoding="utf-8"))
        arms[seed] = {"r1shape": d["map50"], "r1shape_95": d["map50_95"]}
        c = CONTROL_ARTIFACTS.get(seed)
        if c and os.path.exists(os.path.join(BENCH, c)):
            cd = json.load(open(os.path.join(BENCH, c), encoding="utf-8"))
            arms[seed]["r1"] = cd["map50"]
            arms[seed]["r1_artifact"] = c
    diffs = [(s, v["r1shape"] - v["r1"]) for s, v in arms.items() if "r1" in v]

    # 域差距三因子: 复用 23 号脚本的同一套度量 (真实侧读已发布产物)
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "b23", os.path.join(BASE, "pipelines/shelf_sdg/23_domain_gap_measure.py"))
    m23 = ilu.module_from_spec(spec)
    spec.loader.exec_module(m23)

    def gap_of(synth_dir):
        """该合成集自己的域差距因子 —— 真实侧取已发布的 domain_gap_measure.json。

        注意键名: 已发布产物的真实侧是 `boxes_per_image` / `mean_box_area` /
        `median_aspect_ratio`, 而合成侧我用的是 `boxes_per_image_mean` (带 _mean 后缀)。
        两边**必须归一到同一套键名**, 否则"与真实侧的距离"算不出来 (闸门第 9 组会误报)。
        """
        real = {}
        pub = os.path.join(BENCH, "domain_gap_measure.json")
        if not os.path.exists(pub):
            pub = os.path.join(BASE, "docs", "research", "benchmark", "domain_gap_measure.json")
        if os.path.exists(pub):
            try:
                raw = json.load(open(pub, encoding="utf-8")).get("real", {})
            except Exception:
                raw = {}
            real = {"boxes_per_image_mean": raw.get("boxes_per_image", {}),
                    "mean_box_area": raw.get("mean_box_area", {}),
                    "median_aspect_ratio": raw.get("median_aspect_ratio", {})}
        items = m23.read_labels(os.path.join(synth_dir, "labels", "train"),
                                os.path.join(synth_dir, "images", "train"))
        boxes = [it["n_boxes"] for it in items]
        areas = [it["mean_area"] for it in items]
        ars = [it["median_ar"] for it in items]
        return {"synth": {"boxes_per_image_mean": m23.stats(boxes),
                           "mean_box_area": m23.stats(areas),
                           "median_aspect_ratio": m23.stats(ars)},
                "real": real}

    g_shape = gap_of(SYNTH_OUT)
    # 对照要用**单类化后**的 R1 集 (output/benchmark/synth_single) —— 与形状臂同一口径。
    # 直接拿 output/sdg_shelf (4 类, 26 框/图) 比会多出 OOS gap 框, 密度差 4 框/图,
    # 会被误读成"形状干预改了密度"。
    g_ctrl = gap_of(os.path.join(BENCH, "synth_single"))

    out = {
        "schema": "r1shape_arm/1",
        "measured_at": "2026-11-24",
        "treatment": {"shape_profile": "real", "shape_aspect_gain": GAIN,
                          "shape_area_gain": AREA_GAIN, "shape_max_width": MAX_WIDTH},
        "control_note": "对照 = R1 (同配方同划分同协议同 seed, 只是没有形状先验)",
        "treatment_scope": {
            "factors_moved": ["朝向(投影宽高比)", "尺度(投影面积)"],
            "factors_not_moved": ["密度(框/图)", "视角", "光照", "SKU 配比", "错位率"],
            "note": "干预**同时动了朝向与尺度两个因子** (2026-11-24 订正: 原文写"
                    "'面积保持不变 -> 只动朝向因子' 是错的)。两个因子都朝真实侧动了: "
                    "中位宽高比 0.3196->0.7934 (真实 1.0544), 单框面积 0.0053->0.0031 (真实 0.0030)。",
            "density_is_emergent": "每图保留框 21.83->20.63 **不是干预旋钮**, 而是几何干预的"
                                   "下游必然后果: 商品改宽 -> 遮挡变多 -> 可见度过滤 "
                                   "(vis_frac<15%) 丢弃率从对照臂 0% 升到 3.98%。",
        },
        "per_seed": arms,
        "r1shape_mean": round(st.mean([v["r1shape"] for v in arms.values()]), 4) if arms else None,
        "r1shape_std": round(st.stdev([v["r1shape"] for v in arms.values()]), 4) if len(arms) > 1 else None,
        "r1_mean": round(st.mean([v["r1"] for v in arms.values() if "r1" in v]), 4) if diffs else None,
        "raw_paired_diff_pp": [round(d * 100, 3) for _, d in diffs],
        "paired_diff_pp": None,
        "paired_diff_ci95_pp": None,
        "paired_stats_source": "docs/research/benchmark/fourarm_seed_variance.json (36 号脚本算)",
        "domain_gap_r1shape": g_shape,
        "domain_gap_r1": g_ctrl,
    }
    fsv = os.path.join(BENCH, "fourarm_seed_variance.json")
    if os.path.exists(fsv):
        try:
            j = json.load(open(fsv, encoding="utf-8"))
            for pr in j.get("paired", []):
                if (pr.get("b"), pr.get("a")) == ("r1shape", "r1"):
                    out["paired_diff_pp"] = pr.get("map50_diff_mean_pp")
                    out["paired_diff_ci95_pp"] = pr.get("map50_diff_ci95")
                    out["paired_n"] = pr.get("n_pairs")
        except Exception:
            pass

    def pick(g, path):
        cur = (g.get("synth") or {})
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        return cur

    def pick_real(g, path):
        cur = g.get("real") or {}
        for k in path:
            cur = (cur or {}).get(k) if isinstance(cur, dict) else None
        return cur

    out["factor_comparison"] = {
        "boxes_per_image_mean": {"r1": pick(g_ctrl, ["boxes_per_image_mean", "mean"]),
                                 "r1shape": pick(g_shape, ["boxes_per_image_mean", "mean"]),
                                 "real": pick_real(g_shape, ["boxes_per_image_mean", "mean"])},
        "mean_box_area_mean": {"r1": pick(g_ctrl, ["mean_box_area", "mean"]),
                                "r1shape": pick(g_shape, ["mean_box_area", "mean"]),
                                "real": pick_real(g_shape, ["mean_box_area", "mean"])},
        "median_aspect_ratio_mean": {"r1": pick(g_ctrl, ["median_aspect_ratio", "mean"]),
                                     "r1shape": pick(g_shape, ["median_aspect_ratio", "mean"]),
                                     "real": pick_real(g_shape, ["median_aspect_ratio", "mean"])},
    }
    p = os.path.join(BENCH, "r1shape_arm.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    log(f"汇总 -> {p}")
    for s, v in arms.items():
        log(f"  seed {s}: R1shape {v['r1shape']:.4f}" +
            (f" vs R1 {v['r1']:.4f} (Δ {(v['r1shape'] - v['r1']) * 100:+.2f}pp)" if "r1" in v else ""))
    if out["paired_diff_ci95_pp"]:
        log(f"  配对差值 (引自 36 号汇总) mean {out['paired_diff_pp']:+.2f}pp, "
            f"95% CI {out['paired_diff_ci95_pp']}")
    else:
        log("  配对差值: 先跑 36_fourarm_seed_variance.py 再重跑本脚本的 summarize 阶段")
    return out


# R1 对照臂的同 seed 产物
CONTROL_ARTIFACTS = {
    42: "sku110k_r1_scenebest.json",
    43: "sku110k_r1_s43.json",
    44: "sku110k_r1_s44.json",
    45: "sku110k_r1_s45.json",
    46: "sku110k_r1_s46.json",
    47: "sku110k_r1_s47.json",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("render", "train", "summarize", "all"), default="all")
    ap.add_argument("--seeds", default="42,43,44")
    ap.add_argument("--threads", type=int, default=4, help="Cycles 线程数 (渲染与训练并跑时要压低)")
    args = ap.parse_args()
    seeds = [int(s) for s in str(args.seeds).split(",") if str(s).strip()]
    if args.stage in ("render", "all"):
        render(threads=args.threads)
    if args.stage in ("train", "all"):
        train(seeds)
    if args.stage in ("summarize", "all"):
        summarize(seeds)


if __name__ == "__main__":
    main()
