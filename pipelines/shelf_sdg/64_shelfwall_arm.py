#!/usr/bin/env python
"""真实货架墙臂 (I-17, 2026-11-25): 按 63 号探针的机制改生成器。

**为什么做这个**: 63 号上下文剥离探针把"真实照片的上下文 (货架纹理/背板/价签/邻居
遮挡/杂乱光照)"定量成 **+22.76 pp** (配对差分, 95% CI [+16.0, +29.5], 3/3 seed 一致)
—— 这是本仓测到的最大单一因子 (密度只有 ~4 pp, 形状先验 10.66 pp)。也就是说: 合成模型
在真实图上失败, 主要不是因为"商品长得不一样", 而是因为**商品周围的一切都不像**。
本臂就是照这条机制改生成器, 看缺口能不能补回一部分。

**改了什么 (环境, 商品不动)**:
  * 层板/背板: 纯色金属 -> 程序化斑驳纹理 (真实货架不是纯色)
  * 前沿: 保留黄价签条 + 加一排白色小价签 (不可读, 只制造"杂乱")
  * 竖向隔板: 每个排面之间立一片薄板 -> 商品被部分遮挡
  * 光照: 每层 LED 能量不均 + 一盏偏暖侧光 (不是均匀棚拍)
  * 货位: 前后/侧向错位 -> 商品不再是一排等距盒子
  * 商品本身: **仍然是白盒** —— 表面 (I-14, -13.2 pp) 与几何 (形状臂, -10.66 pp) 已各自
    被实测否掉, 这里只测"上下文"这一个变量。

**密度同时上调** (bays 1 -> 2, cam_mult 1.0 -> 1.25): 探针的对照组说明**数量**只值
~4 pp, 但"邻居的像素"属于上下文, 要有邻居才谈得上上下文; 顺带把商品的画面占比从
0.0053 调到 ~0.0034 (真实域 0.0030)。所以本臂是**"域重写"臂**(样式 + 密度),
不是严格单变量臂: 假设是"合成域必须在场景结构上整体靠近真实域"。若为正, 再拆单变量
消融 (样式-only / 密度-only) 定位是哪一半起的作用; 若为负, 本仓结论升级为强负结论。

**主比较 = last-vs-last**: 与已发布的 R1 对照臂 (runs_r1_s{seed}) 配对, 权重一律取
last.pt (完全不按 val 挑 epoch), best-vs-best 只作次要参考。

用法:
    python pipelines/shelf_sdg/64_shelfwall_arm.py --stage render
    python pipelines/shelf_sdg/64_shelfwall_arm.py --stage single
    python pipelines/shelf_sdg/64_shelfwall_arm.py --stage train --seeds 43,44,45
    python pipelines/shelf_sdg/64_shelfwall_arm.py --stage all
"""
import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import blender_command  # noqa: E402
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")
RAW = os.path.join(BENCH, "sdg_shelf_wall")     # 原始渲染 (4 类)
POOL = os.path.join(BENCH, "synth_wall")        # 单类化后的训练池
CONTROL_RUNS = "runs_r1_s{seed}"                # 对照臂 (白盒池, 已发布)
LOG = os.path.join(BENCH, "shelfwall_arm.log")
ART = os.path.join(BENCH, "shelfwall_arm.json")

# 与 R1 对照池同族的配方 (同 seed / 同场景留出 / 同训练配方), 变化 = 样式 + 密度
RECIPE = dict(num_images=200, seed=42, val_ratio=0.2, images_per_scene=4,
              split_mode="scene", samples=64,
              cam_mult=1.25, lens=28.0, misalign=0.10, bays=2,
              style="shelfwall", product_texture="none")
# 与已发布 R1 run 一致的训练配置 (见 output/benchmark/runs_r1_s43/train/args.yaml)
TRAIN_CFG = dict(epochs=10, imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)
SEEDS = [43, 44, 45]
TAG = "wall"      # 消融时改 tag -> 池目录/权重目录/产物名都跟着变, 不互相污染

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
if os.environ.get("SDG_RENDER_DEVICE", "").strip().lower() == "cpu":
    ENV["FORCE_CPU_RENDER"] = "1"
else:
    ENV.pop("FORCE_CPU_RENDER", None)
ENV["CYCLES_DEVICE"] = ENV.get("CYCLES_DEVICE", "OPTIX")


def log(m):
    line = f"[WALL {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def render():
    """渲真实货架墙的池。已渲完则跳过 (可续跑)。"""
    n_done = len(glob.glob(os.path.join(RAW, "images", "train", "*.png"))) + \
        len(glob.glob(os.path.join(RAW, "images", "val", "*.png")))
    if n_done >= RECIPE["num_images"]:
        log(f"货架墙池已存在 ({n_done} 张), 跳过渲染")
        return True
    cmd = blender_command() + [
        "-b", "-P", os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"), "--",
        "--num-images", str(RECIPE["num_images"]),
        "--seed", str(RECIPE["seed"]),
        "--val-ratio", str(RECIPE["val_ratio"]),
        "--images-per-scene", str(RECIPE["images_per_scene"]),
        "--split-mode", RECIPE["split_mode"],
        "--samples", str(RECIPE["samples"]),
        "--cam-mult", str(RECIPE["cam_mult"]),
        "--lens", str(RECIPE["lens"]),
        "--misalign", str(RECIPE["misalign"]),
        "--bays", str(RECIPE["bays"]),
        "--style", RECIPE["style"],
        "--product-texture", RECIPE["product_texture"],
        "--out", RAW]
    log("RUN " + " ".join(cmd[1:]))
    t0 = time.time()
    with open(os.path.join(BENCH, f"shelfwall_render_{TAG}.log"), "w", encoding="utf-8",
              errors="ignore") as fh:
        r = subprocess.run(cmd, env=ENV, cwd=BASE, stdout=fh, stderr=subprocess.STDOUT)
    log(f"渲染结束 (退出码 {r.returncode}, {(time.time()-t0)/60:.1f} min)")
    return r.returncode == 0


def to_single():
    """4 类 -> 单类 (丢 class 1 = OOS gap), 与 14/43/57 号同逻辑。"""
    for split in ("train", "val"):
        isrc = os.path.join(RAW, "images", split)
        lsrc = os.path.join(RAW, "labels", split)
        idst = os.path.join(POOL, "images", split)
        ldst = os.path.join(POOL, "labels", split)
        os.makedirs(idst, exist_ok=True)
        os.makedirs(ldst, exist_ok=True)
        if not os.path.isdir(isrc):
            continue
        for f in sorted(os.listdir(isrc)):
            if not f.lower().endswith(".png"):
                continue
            shutil.copy2(os.path.join(isrc, f), os.path.join(idst, f))
            t = os.path.join(lsrc, f.replace(".png", ".txt"))
            lines = []
            if os.path.exists(t):
                for ln in open(t, encoding="utf-8"):
                    p = ln.split()
                    if len(p) == 5 and p[0] != "1":
                        lines.append("0 " + " ".join(p[1:]))
            with open(os.path.join(ldst, f.replace(".png", ".txt")), "w",
                      encoding="utf-8") as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))
    with open(os.path.join(POOL, "dataset.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"path: {POOL}\ntrain: images/train\nval: images/val\n"
                 "nc: 1\nnames: [product]\n")
    n = len(glob.glob(os.path.join(POOL, "images", "train", "*.png")))
    log(f"单类化完成: {POOL} train={n}")
    return n


def _eval(ckpt):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=ENV["SKU110K_YAML"], split="test", imgsz=640, batch=4, device="0",
              max_det=1000, workers=2, verbose=False)
    return (float(r.box.map50), float(r.box.map), float(r.box.mp), float(r.box.mr))


def train(seeds):
    """训练货架墙臂 + 评测 (对照 last x 臂 last/best)。"""
    from ultralytics import YOLO
    import ultralytics
    # 多 seed 汇总的坑 (skill: multi-seed-aggregation-pitfalls §1):
    # 分批跑时后一次不能把前一次的 seed 覆盖掉 -> 先读旧产物再合并 ✓
    recs = {}
    if os.path.isfile(ART):
        try:
            _old = json.load(open(ART, encoding="utf-8"))
            recs = dict(_old.get("per_seed") or {})
        except Exception:
            recs = {}
    # 协议指纹: 记下**实际**训练配置, 便于以后核对"同一实验的各格点同协议"
    protocol = dict(TRAIN_CFG)
    protocol["ultralytics"] = ultralytics.__version__
    protocol["control_runs"] = CONTROL_RUNS
    protocol["control_args_fingerprint"] = {}
    for seed in seeds:
        a = os.path.join(BENCH, CONTROL_RUNS.format(seed=seed), "train", "args.yaml")
        if os.path.isfile(a):
            try:
                txt = open(a, encoding="utf-8").read()
                want = ["epochs:", "batch:", "imgsz:", "workers:", "device:", "optimizer:",
                        "close_mosaic:", "pretrained:", "amp:", "deterministic:", "cache:"]
                protocol["control_args_fingerprint"][str(seed)] = {
                    k: next((ln.strip() for ln in txt.splitlines() if ln.startswith(k)), None)
                    for k in want}
            except Exception:
                pass
    yml = os.path.join(POOL, "dataset.yaml")
    for seed in seeds:
        run = os.path.join(BENCH, f"runs_{TAG}_s{seed}")
        ck_best = os.path.join(run, "train", "weights", "best.pt")
        ck_last = os.path.join(run, "train", "weights", "last.pt")
        if not os.path.isfile(ck_last):
            model = YOLO("yolo11n.pt")
            model.train(data=yml, seed=seed, project=run, name="train", exist_ok=True,
                        verbose=False, **TRAIN_CFG)
        row = {}
        ctrl_last = os.path.join(BENCH, CONTROL_RUNS.format(seed=seed),
                                  "train", "weights", "last.pt")
        if os.path.isfile(ctrl_last):
            m50, m95, mp, mr = _eval(ctrl_last)
            row["control_last"] = {"map50": m50, "map50_95": m95, "precision": mp, "recall": mr}
            log(f"control(last) seed {seed}: 真实 test mAP50 = {m50:.4f}")
        for tag, ck in (("wall_best", ck_best), ("wall_last", ck_last)):
            if not os.path.isfile(ck):
                continue
            m50, m95, mp, mr = _eval(ck)
            row[tag] = {"map50": m50, "map50_95": m95, "precision": mp, "recall": mr}
            log(f"{tag} seed {seed}: 真实 test mAP50 = {m50:.4f}")
        recs[str(seed)] = row
    rep = {"schema": "shelfwall_arm/1",
           "generated_by": "pipelines/shelf_sdg/64_shelfwall_arm.py",
           "measured_at": time.strftime("%Y-%m-%d"),
           "recipe": RECIPE,
           "protocol": protocol,
           "control": "已发布的 R1 对照臂 (runs_r1_s{seed}, 白盒池 legacy 配方)",
           "per_seed": recs}
    rep["paired"] = {}
    for a, b in (("control_last", "wall_last"), ("control_last", "wall_best")):
        diffs = []
        for s, row in recs.items():
            if a in row and b in row:
                diffs.append((row[b]["map50"] - row[a]["map50"]) * 100.0)
        if not diffs:
            continue
        n = len(diffs)
        mean = sum(diffs) / n
        if n == 1:
            rep["paired"][f"{b}_vs_{a}"] = {"n": n, "mean_pp": round(mean, 4),
                                           "ci95_pp": None,
                                           "per_seed_pp": [round(d, 4) for d in diffs]}
            continue
        _m, lo, hi = ci95_t(diffs)
        rep["paired"][f"{b}_vs_{a}"] = {
            "n": n, "mean_pp": round(mean, 4),
            "ci95_pp": [round(lo, 4), round(hi, 4)],
            "per_seed_pp": [round(d, 4) for d in diffs]}
        log(f"配对 {b} - {a}: {mean:+.2f} pp, CI [{lo:+.2f}, {hi:+.2f}]")
    # 池的统计量 (密度/面积), 便于核对"密度真的上去了"
    stats = {"n_boxes_per_image": [], "n_images": 0}
    for split in ("train", "val"):
        d = os.path.join(POOL, "labels", split)
        if not os.path.isdir(d):
            continue
        files = glob.glob(os.path.join(d, "*.txt"))
        for f in files:
            with open(f, encoding="utf-8") as fh:
                stats["n_boxes_per_image"].append(sum(1 for _ in fh))
        stats["n_images"] += len(files)
    if stats["n_boxes_per_image"]:
        vals = sorted(stats["n_boxes_per_image"])
        stats["mean_boxes_per_image"] = round(sum(vals) / len(vals), 2)
        stats["median_boxes_per_image"] = vals[len(vals) // 2]
    rep["pool_stats"] = stats
    with open(ART, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    log(f"-> {ART}")
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("render", "single", "train", "all"), default="all")
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    # 消融用的配方覆盖 (默认 = 上面的 RECIPE, 即"真实货架墙"臂本身):
    #   --style legacy --bays 1 --cam-mult 1.0  -> 只改样式 (密度不动)
    #   --style legacy --bays 2 --cam-mult 1.25 -> 只改密度 (样式不动)
    # 目录名随配方变, 免得不同臂的池/权重混在一起。
    ap.add_argument("--style", default=RECIPE["style"])
    ap.add_argument("--bays", type=int, default=RECIPE["bays"])
    ap.add_argument("--cam-mult", type=float, default=RECIPE["cam_mult"])
    ap.add_argument("--tag", default="wall")
    a = ap.parse_args()
    RECIPE["style"] = a.style
    RECIPE["bays"] = a.bays
    RECIPE["cam_mult"] = a.cam_mult
    globals()["TAG"] = a.tag
    if a.tag != "wall":
        globals()["RAW"] = os.path.join(BENCH, f"sdg_shelf_{a.tag}")
        globals()["POOL"] = os.path.join(BENCH, f"synth_{a.tag}")
        globals()["LOG"] = os.path.join(BENCH, f"shelfwall_arm_{a.tag}.log")
        globals()["ART"] = os.path.join(BENCH, f"shelfwall_arm_{a.tag}.json")
    seeds = [int(x) for x in a.seeds.split(",") if x.strip()]
    if a.stage in ("render", "all"):
        if not render():
            raise SystemExit("[WALL] 渲染失败")
    if a.stage in ("single", "all"):
        to_single()
    if a.stage in ("train", "all"):
        train(seeds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
