#!/usr/bin/env python3
"""形状先验探针 (2026-11-23): 渲染少量图, 标定"世界宽高比 -> 投影宽高比"的系数。

为什么需要探针
--------------
新加的 `--shape-profile real` 是按真实域的形状分布给商品采样长宽, 但**投影宽高比**
不等于世界宽高比 (透视 + 深度面的贡献)。历史数据给出的经验值是
    投影/世界 ≈ 0.3232 / 0.3529 = 0.916  (即 gain ≈ 1.09)
但那是"全同形 + 12% 错位"下的统计, 直接拿来用是猜的 -> 必须渲几张实测。

本脚本:
  1. 用**与 R1 对照集完全相同的配方** (cam1.0/lens28/mis0.10/bays1) 渲 N 张探针图
     (只多一个 --shape-profile real), 于是探针与对照之间**只差形状**;
  2. 量探针的逐图中位宽高比 / 单框面积;
  3. 对照: R1 对照集 (output/sdg_shelf) 与真实域 (real_shape_profile.json);
  4. 输出 output/benchmark/shape_probe.json, 里面有**实测 gain** —— 用它把
     --shape-aspect-gain 标定到"采样分布 = 真实分布"。

只渲 N 张 (默认 4), CPU (Cycles backend=CPU) -> 不占 GPU, 可与训练链并行。
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import blender_command  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
PROBE = os.path.join(BENCH, "sdg_shape_probe")
PROFILE = os.path.join(BENCH, "real_shape_profile.json")

# 与 R1 对照集 (output/sdg_shelf) 完全一致的配方
CONTROL_RECIPE = dict(cam_mult=1.0, lens=28.0, misalign=0.10, bays=1,
                      num_images=200, seed=42, val_ratio=0.2,
                      images_per_scene=4, split_mode="scene", samples=64)


def log(m):
    print(f"[SHAPE-PROBE {time.strftime('%m-%d %H:%M:%S')}] {m}", flush=True)


def render(n_images, gain, threads=6, area_gain=0.782):
    # 2026-11-23: 强制 Cycles 走 CPU —— 渲染器默认挑 OPTIX/GPU, 而 GPU 正在跑 YOLO
    # 训练/计数推理 -> Cycles 排在 GPU 队列里干等 (实测卡了 20 分钟一张图没出)。
    # 2026-11-24: 改成**可配置** —— 强制 CPU 的唯一理由是"GPU 要留给训练"。
    # GPU 空闲时 (比如渲染与训练串行, 或只做渲染) 用 GPU 反而快 2 倍以上
    # (实测 GTX 1050 Ti / OPTIX: 18 s/图 vs CPU 40 s/图)。
    #   SDG_RENDER_DEVICE=cpu  -> 强制 CPU (与 GPU 上有训练任务时同)
    #   SDG_RENDER_DEVICE=gpu  -> 允许 GPU (CYCLES_DEVICE=OPTIX)
    #   不设                    -> 跟随 FORCE_CPU_RENDER (缺省即 GPU)
    env = dict(os.environ)
    dev = os.environ.get("SDG_RENDER_DEVICE", "").strip().lower()
    if dev == "cpu":
        env["FORCE_CPU_RENDER"] = "1"
    else:
        env.pop("FORCE_CPU_RENDER", None)
        env["CYCLES_DEVICE"] = env.get("CYCLES_DEVICE", "OPTIX")
    cmd = blender_command() + ["-b", "-t", str(threads), "-P",
                               os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"),
                               "--",
                               "--num-images", str(n_images),
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
                               "--shape-aspect-gain", str(gain),
                               "--shape-area-gain", str(area_gain),
                               "--out", PROBE]
    log("RUN " + " ".join(cmd[2:]))
    log_path = os.path.join(BENCH, "chain_steps", "shape_probe_render.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8", errors="ignore") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=28800, env=env)
    if r.returncode != 0:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as fh:
            print(fh.read()[-3000:])
        raise SystemExit(f"[SHAPE-PROBE] 渲染失败 (退出码 {r.returncode}); 日志 {log_path}")
    log(f"渲染完成 {(time.time() - t0) / 60:.1f} min (日志 {log_path})")


def measure(label_dir):
    """→ (逐图中位宽高比列表, 单框面积列表)"""
    img_med, box_area, box_ar = [], [], []
    if not os.path.isdir(label_dir):
        return img_med, box_area, box_ar
    for f in sorted(os.listdir(label_dir)):
        if not f.endswith(".txt"):
            continue
        ars, areas = [], []
        with open(os.path.join(label_dir, f), "r", encoding="utf-8") as fh:
            for line in fh:
                p = line.split()
                if len(p) < 5:
                    continue
                w, h = float(p[3]), float(p[4])
                ars.append(w / h if h > 0 else 0.0)
                areas.append(w * h)
        if ars:
            img_med.append(statistics.median(ars))
            box_ar.extend(ars)
            box_area.extend(areas)
    return img_med, box_area, box_ar


def stats(img_med, box_area, box_ar):
    def q(xs, p):
        if not xs:
            return None
        xs = sorted(xs)
        return round(xs[min(len(xs) - 1, max(0, int(round(p * (len(xs) - 1)))))], 5)
    return {
        "n_images": len(img_med), "n_boxes": len(box_ar),
        "per_image_median_aspect": {
            "mean": round(statistics.mean(img_med), 4) if img_med else None,
            "std": round(statistics.pstdev(img_med), 4) if len(img_med) > 1 else None,
            "p10": q(img_med, 0.1), "p50": q(img_med, 0.5), "p90": q(img_med, 0.9)},
        "per_box_aspect": {
            "mean": round(statistics.mean(box_ar), 4) if box_ar else None,
            "p50": q(box_ar, 0.5)},
        "per_box_area": {
            "mean": round(statistics.mean(box_area), 6) if box_area else None,
            "p50": q(box_area, 0.5)},
    }


def fit_mapping():
    """用探针的标注 (记了世界尺寸) 拟合"世界 -> 投影"的换算系数。

    投影受透视影响, **不是常数倍**, 必须实测:
      gain      = median(投影宽高比 / 世界宽高比)   -> 目标投影宽高比 = 目标 / gain
      area_gain = median(投影框面积 / 世界正面面积) -> 目标投影面积   = 目标 * area_gain
    只用 COMPLIANT 框 (近乎正对相机, 旋转框的紧致框会被透视/遮挡改形)。
    """
    ann_dir = os.path.join(PROBE, "annotations")
    lab_dir = os.path.join(PROBE, "labels")
    ratios, area_ratios = [], []
    if not os.path.isdir(ann_dir):
        return None, None
    for f in sorted(os.listdir(ann_dir)):
        if not f.endswith(".json"):
            continue
        split = "train" if os.path.exists(os.path.join(lab_dir, "train", f.replace(".json", ".txt"))) else "val"
        lab = os.path.join(lab_dir, split, f.replace(".json", ".txt"))
        if not os.path.exists(lab):
            continue
        with open(lab, "r", encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        with open(os.path.join(ann_dir, f), "r", encoding="utf-8") as fh:
            meta = json.load(fh)
        anns = meta.get("annotations", [])
        if len(anns) != len(lines):
            continue
        for ln, a in zip(lines, anns):
            p = ln.split()
            if len(p) < 5 or a.get("status") != "COMPLIANT":
                continue
            w, h = float(p[3]), float(p[4])
            if h <= 0 or w <= 0:
                continue
            war = a.get("world_ar")
            ww, wh = a.get("world_w"), a.get("world_h")
            if war and war > 0:
                ratios.append((w / h) / war)
            if ww and wh and ww > 0 and wh > 0:
                area_ratios.append((w * h) / (ww * wh))
    if not ratios:
        return None, None
    ratios.sort()
    area_ratios.sort()
    return (round(ratios[len(ratios) // 2], 4),
            round(area_ratios[len(area_ratios) // 2], 4) if area_ratios else None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", type=int, default=4)
    ap.add_argument("--gain", type=float, default=1.214)
    ap.add_argument("--area-gain", type=float, default=0.782)
    ap.add_argument("--threads", type=int, default=6)
    args = ap.parse_args()

    if not os.path.exists(PROFILE):
        raise SystemExit("[SHAPE-PROBE] 先跑 41_real_shape_profile.py")
    render(args.images, args.gain, args.threads, args.area_gain)

    probe = stats(*measure(os.path.join(PROBE, "labels", "train")))
    probe_all = stats(*measure(os.path.join(PROBE, "labels")))
    ctrl = stats(*measure(os.path.join(BASE, "output", "sdg_shelf", "labels", "train")))
    with open(PROFILE, "r", encoding="utf-8") as fh:
        prof = json.load(fh)
    real = prof["real"]
    gain_fit, area_gain_fit = fit_mapping()

    out = {
        "schema": "shape_probe/2",
        "measured_at": "2026-11-23",
        "probe_recipe": dict(CONTROL_RECIPE, shape_profile="real",
                             shape_aspect_gain=args.gain,
                             shape_area_gain=args.area_gain,
                             n_probe_images=args.images),
        "probe_train": probe,
        "probe_all_splits": probe_all,
        "control_r1_train": ctrl,
        "real_train": {k: real[k] for k in ("n_images", "per_image_median_aspect",
                                            "per_box_aspect", "per_box_area")},
        "gain_used": args.gain,
        "area_gain_used": args.area_gain,
        "gain_fitted": gain_fit,
        "area_gain_fitted": area_gain_fit,
        "gain_note": ("gain_fitted = median(投影宽高比/世界宽高比) (只用 COMPLIANT 框)。"
                      "要用它反推: 目标投影宽高比 = 目标值 / gain_fitted -> 即 --shape-aspect-gain。"
                      "area_gain_fitted = median(投影框面积/世界正面面积) -> --shape-area-gain。"),
    }
    p = os.path.join(BENCH, "shape_probe.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    log(f"探针逐图中位宽高比 mean {probe['per_image_median_aspect']['mean']} "
        f"(p10 {probe['per_image_median_aspect']['p10']}, p50 {probe['per_image_median_aspect']['p50']}, "
        f"p90 {probe['per_image_median_aspect']['p90']}), 单框面积 mean {probe['per_box_area']['mean']}")
    log(f"对照 R1 逐图中位宽高比 mean {ctrl['per_image_median_aspect']['mean']}, "
        f"单框面积 mean {ctrl['per_box_area']['mean']}")
    log(f"真实   逐图中位宽高比 mean {real['per_image_median_aspect']['mean']}, "
        f"单框面积 mean {real['per_box_area']['mean']}")
    log(f"标定: gain_fitted={gain_fit} (用的是 {args.gain}), area_gain_fitted={area_gain_fit} "
        f"(用的是 {args.area_gain})")
    log(f"-> {p}")


if __name__ == "__main__":
    main()
