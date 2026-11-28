#!/usr/bin/env python
"""I-19 · "训练时抑制上下文依赖"臂 (2026-11-26)。

为什么做这个臂 (按机制, 不按直觉):
  * I-16 (63 号探针): 真实照片里把**框外像素换成纯色** -> 真实域 mAP50 从 0.2308 涨到
    0.4554 (+22.76 pp, CI [+16.0, +29.5], 3/3 seed)。而同一处理施加到**合成域**上
    几乎无影响 (-0.29 pp) -> **真实照片的上下文是干扰项, 合成域的上下文是有用的**。
  * I-18 (只改上下文臂): 把合成域的上下文做得更像真实 -> 真实域迁移**掉了 10.1 pp**
    (n=5 显著), 机制是"到了真实照片上整体不自信" -> 模型把**合成域的上下文**当成了
    商品定义的一部分。
  => 合起来指向: 问题不在"上下文不够真实", 而在**模型学到的商品定义依赖了合成域的
     上下文**。那就直接测: **训练时让上下文随机消失**, 逼模型只认商品本身。

干预 (单变量, 其余与 R1 对照臂逐项相同):
  * 训练集里 **50% 的图**把框外像素换成**随机纯色** (每通道 40-140, 不用固定色,
    免得模型学成"只在某个底色上找东西"这种新捷径 ✓); 框内像素与标签原样 ✓;
  * **验证集原样** (与对照臂完全一致 ✓ -> best/last 的选法可比 ✓);
  * 图数、像素、商品位置、标签、训练配方 (epochs 10 / batch 4 / imgsz 640 /
    workers 2 / pretrained / optimizer auto / close_mosaic 10) 全部不变 ✓。
  * **图数不变** (160 张 ✓) -> 训练样本数与对照臂相同 ✓ (不引入"数据量"这个混淆 ✓)。

口径: 与已发布的 R1 对照臂 (runs_r1_s{seed}) **同 seed 配对比较**, 主比较 last-vs-last,
seed 43-47 (n=5 —— I-18 的教训: 跨域臂 n=3 统计功效不够 ✓)。

用法:
    python pipelines/shelf_sdg/66_context_suppress_arm.py
产物:
    output/benchmark/context_suppress_arm.json   (数字现算, 不手写)
    output/benchmark/synth_ctxsupp/               (掩膜后的训练池)
"""
import json
import os
import random
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")
SRC_POOL = os.path.join(BENCH, "synth_single")      # R1 对照臂用的池 (原样)
POOL = os.path.join(BENCH, "synth_ctxsupp")          # 掩膜后的池
CONTROL_RUNS = "runs_r1_s{seed}"
LOG = os.path.join(BENCH, "context_suppress_arm.log")
ART = os.path.join(BENCH, "context_suppress_arm.json")
SEEDS = [43, 44, 45, 46, 47]
P_MASK = 0.5          # 训练集里被"剥掉上下文"的图的比例
MIN_SIDE = 4          # 与 63 号探针一致: 太小的框贴进去没意义
TRAIN_CFG = dict(epochs=10, imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)


def log(m):
    line = f"[CTXSUP {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def strip_context(img_path, lbl_path, out_path, bg):
    """框外 -> bg; 框内原样。返回是否真的做了 (太小框的图原样保留)。"""
    from PIL import Image
    img = Image.open(img_path).convert("RGB")
    W, H = img.size
    canvas = Image.new("RGB", (W, H), bg)
    try:
        with open(lbl_path, "r", encoding="utf-8") as fh:
            lines = [ln.strip() for ln in fh if ln.strip()]
    except OSError:
        lines = []
    pasted = 0
    for line in lines:
        p = line.split()
        if len(p) < 5:
            continue
        _, cx, cy, w, h = (float(x) for x in p[:5])
        x0, x1 = max(0, int((cx - w / 2) * W)), min(W, int((cx + w / 2) * W))
        y0, y1 = max(0, int((cy - h / 2) * H)), min(H, int((cy + h / 2) * H))
        if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
            continue
        canvas.paste(img.crop((x0, y0, x1, y1)), (x0, y0))
        pasted += 1
    if pasted == 0:
        shutil.copy2(img_path, out_path)
        return False
    canvas.save(out_path)
    return True


def build_pool():
    """造掩膜池: train 里 50% 的图剥掉上下文; val 原样。"""
    from PIL import Image
    if os.path.isdir(POOL):
        shutil.rmtree(POOL)
    rng = random.Random(20261126)
    stats = {"n_train": 0, "masked": 0, "n_val": 0}
    for split in ("train", "val"):
        si = os.path.join(SRC_POOL, "images", split)
        sl = os.path.join(SRC_POOL, "labels", split)
        di = os.path.join(POOL, "images", split)
        dl = os.path.join(POOL, "labels", split)
        os.makedirs(di, exist_ok=True)
        os.makedirs(dl, exist_ok=True)
        for f in sorted(os.listdir(si)):
            if not f.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            src = os.path.join(si, f)
            lbl = os.path.join(sl, os.path.splitext(f)[0] + ".txt")
            dst = os.path.join(di, f)
            if os.path.isfile(lbl):
                shutil.copy2(lbl, os.path.join(dl, os.path.splitext(f)[0] + ".txt"))
            if split == "val":
                shutil.copy2(src, dst)
                stats["n_val"] += 1
                continue
            stats["n_train"] += 1
            if rng.random() < P_MASK:
                bg = (rng.randint(40, 140), rng.randint(40, 140), rng.randint(40, 140))
                if strip_context(src, lbl, dst, bg):
                    stats["masked"] += 1
                else:
                    shutil.copy2(src, dst)
            else:
                shutil.copy2(src, dst)
    with open(os.path.join(POOL, "dataset.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"path: {POOL}\ntrain: images/train\nval: images/val\n"
                 "nc: 1\nnames: [product]\n")
    log(f"掩膜池: train {stats['n_train']} 张 (剥掉上下文 {stats['masked']} 张, "
        f"比例 {stats['masked']/max(1,stats['n_train']):.2f}) | val {stats['n_val']} 张原样")
    return stats


def _eval(ckpt):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=os.environ.get("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml")),
              split="test", imgsz=640, batch=4, device="0", max_det=1000, workers=2, verbose=False)
    return (float(r.box.map50), float(r.box.map), float(r.box.mp), float(r.box.mr))


def main():
    from ultralytics import YOLO
    stats = build_pool()
    yml = os.path.join(POOL, "dataset.yaml")
    recs = {}
    if os.path.isfile(ART):
        try:
            recs = dict((json.load(open(ART, encoding="utf-8")).get("per_seed") or {}))
        except Exception:
            recs = {}
    for seed in SEEDS:
        run = os.path.join(BENCH, f"runs_ctxsupp_s{seed}")
        ck_last = os.path.join(run, "train", "weights", "last.pt")
        if not os.path.isfile(ck_last):
            model = YOLO("yolo11n.pt")
            model.train(data=yml, seed=seed, project=run, name="train", exist_ok=True,
                        verbose=False, **TRAIN_CFG)
        row = {}
        ctrl = os.path.join(BENCH, CONTROL_RUNS.format(seed=seed), "train", "weights", "last.pt")
        if os.path.isfile(ctrl):
            m50, m95, mp, mr = _eval(ctrl)
            row["control_last"] = {"map50": m50, "map50_95": m95, "precision": mp, "recall": mr}
            log(f"control(last) seed {seed}: 真实 test mAP50 = {m50:.4f}")
        if os.path.isfile(ck_last):
            m50, m95, mp, mr = _eval(ck_last)
            row["arm_last"] = {"map50": m50, "map50_95": m95, "precision": mp, "recall": mr}
            log(f"arm_last seed {seed}: 真实 test mAP50 = {m50:.4f}")
        recs[str(seed)] = row
    rep = {"schema": "context_suppress_arm/1",
           "generated_by": "pipelines/shelf_sdg/66_context_suppress_arm.py",
           "measured_at": time.strftime("%Y-%m-%d"),
           "intervention": {
               "name": "训练集 50% 的图把框外像素换成随机纯色 (框内与标签原样), val 原样",
               "p_mask": P_MASK,
               "bg_range": [40, 140],
               "src_pool": SRC_POOL,
               "pool_stats": stats,
               "train_cfg": TRAIN_CFG,
               "note": ("图数/像素/标签/训练配方与 R1 对照臂逐项相同; "
                        "唯一差别 = 一半训练图的框外上下文被抹掉 ✓"),
           },
           "control": "已发布的 R1 对照臂 (runs_r1_s{seed})",
           "per_seed": recs}
    rep["paired"] = {}
    diffs = []
    for s, row in recs.items():
        if "control_last" in row and "arm_last" in row:
            diffs.append((row["arm_last"]["map50"] - row["control_last"]["map50"]) * 100.0)
    if diffs:
        n = len(diffs)
        mean = sum(diffs) / n
        if n == 1:
            rep["paired"]["arm_last_vs_control_last"] = {"n": n, "mean_pp": round(mean, 4),
                                                         "ci95_pp": None,
                                                         "per_seed_pp": [round(d, 4) for d in diffs]}
        else:
            _m, lo, hi = ci95_t(diffs)
            rep["paired"]["arm_last_vs_control_last"] = {
                "n": n, "mean_pp": round(mean, 4),
                "ci95_pp": [round(lo, 4), round(hi, 4)],
                "per_seed_pp": [round(d, 4) for d in diffs]}
            log(f"配对 arm - control: {mean:+.2f} pp, CI [{lo:+.2f}, {hi:+.2f}]")
    with open(ART, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    log(f"-> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
