#!/usr/bin/env python
"""**sim2real 差距: 哪种干预能撼动它** —— 多臂干预探针 (2026-11-24/25)。

出发点 (全部来自本仓已有产物, 见 docs/research/INSIGHT_QUEUE.md)
---------------------------------------------------------------
* 纯合成臂在**自己池的 val** 上 mAP **0.995**, 在**真实 SKU-110K test** 上 **0.244**
  (51 号 `domain_fit_probe` 重测 0.2436, 与已发布 0.2437 一致 -> 评测管线自洽)
  -> 合成域学得会, **~75 pp 全是跨域差距**;
* 真实图砍到 22 框/图只掉 4 pp -> **框数不是主因**;
* 把合成**标签口径**对齐真实 (面积/宽高比) 反而更差 (0.207 vs 0.227) -> **统计量对齐没用**;
* 跨合成池迁移 0.92–0.97 -> 生成器内部参数变化学得动;
* 合成图之间**布局相似度 0.82** (60 个 8 框场景对 59/60 高度相似) -> 多样性可能不足。

所以剩下的都是"外观 / 多样性"类干预。本脚本在**图数固定 (160 张)**、**训练配置固定**
(与已发布 R1 run 逐项一致) 的前提下, 逐个隔离一种干预, 看谁能撼动跨域 mAP:

  arm `control`  : 原池原样 (对照; 复用已发布权重, 用同一套评测流程重评)
  arm `photo`    : 图像空间退化 (噪声/JPEG/模糊/暗角/色偏; 几何与标签不动)
  arm `pasta`    : 傅里叶**振幅**谱按频率加比例高斯扰动 (**相位不动 -> 框仍然有效**)
  arm `mixed3`   : 数据层面换多样性 (三个配方池各 53/53/54; 见 53 号)
  arm `augment+` : 数据不动, 只把 ultralytics 内置增强调大 (hsv/mosaic/mixup)
                    —— 文献所指"增加变化性"的最便宜实现

文献定位与依据
--------------
* PASTA (Chattopadhyay et al., ICCV 2023): 合成图**高频振幅变化**比真实图小
  (纹理变化不足), 在振幅域做扰动可改善 sim2real -> `pasta` 臂;
* arXiv 2610.00030: 合成数据可当**探针**, "controlled, interpretable domain shifts ...
  isolating individual sources of variation", 且这一用途"远未被探索"; 同文指出多篇研究里
  **"增加变化性往往比提升视觉真实度更有效"** -> `mixed3` / `augment+` 与 `photo`/`pasta` 同权重地测;
* ultralytics 8.4.216 的检测分支**没有** RandAugment (`augment` 是测试期 TTA 的 bool,
  RandAugment 只在分类增强里) -> `augment+` 用内置增强表达"变化性", 不假装用了 RandAugment。

产物: output/benchmark/syn2real_interventions.json / .md -> docs/research/benchmark/

用法:
    python pipelines/shelf_sdg/52_photorealism_probe.py --arm photo --seeds 43,44,45
    python pipelines/shelf_sdg/52_photorealism_probe.py --all-arms --seeds 43,44,45
"""
import argparse
import glob
import json
import os
import shutil
import statistics
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
REAL_YAML = os.environ.get("SKU110K_YAML", "SKU-110K.yaml")

SRC_POOL = os.path.join(BENCH, "synth_single")            # R1 配方池 (单类化)
POOLS = {"photo": os.path.join(BENCH, "synth_single_aug"),  # 已由旧脚本建好(退化)
         "pasta": os.path.join(BENCH, "synth_single_pasta"),
         # 2026-11-25: **blur2 / blurR** —— 由 55 号输入探针直接推出的臂。
         #   55 号实测: 合成模型在**模糊后的真实图**上 mAP50 +1.73 pp (σ640=2),
         #   而真实模型几乎无感 (+0.24 pp) -> 合成模型的特征**过度依赖高频边缘结构**,
         #   真实照片的高频细节在误导它。
         #   于是反过来试: 把**合成训练图**也模糊, 让模型别依赖那条通道。
         #   σ 一律以**检测器输入空间 (letterbox 640)** 为准, 源图 σ 按缩放换算
         #   (源 1440 宽 -> letterbox 640, 比例 640/1440=0.444, σ_src = σ640/0.444)。
         "blur2": os.path.join(BENCH, "synth_single_blur2"),
         "blurR": os.path.join(BENCH, "synth_single_blurR"),
         # 2026-11-25: **scene40 / scene160** —— 唯一还没测过的方向 (I-08):
         #   同样 160 张图、同样 160 种图内布局, 只差**场景多样性**。
         "scene40": os.path.join(BENCH, "synth_scene40"),
         "scene160": os.path.join(BENCH, "synth_scene160")}
BIG_MANIFEST = os.path.join(BENCH, "sdg_bigpool", "split_manifest.json")
BIG_SINGLE = os.path.join(BENCH, "synth_bigpool")          # 大池单类化版
OUT_JSON = os.path.join(BENCH, "syn2real_interventions.json")
CONTROL_RUNS = "runs_r1_s{seed}"                            # 对照臂的已发布权重
ARMS = ("control", "photo", "pasta", "mixed3", "augment+", "blur2", "blurR",
        "scene40", "scene160")
ARM_DESC = {
    "control": "原池原样 (对照)",
    "photo": "图像空间退化 (噪声/JPEG/模糊/暗角/色偏)",
    "pasta": "傅里叶振幅谱扰动 (相位不动)",
    "mixed3": "三池混合 53/53/54 (数据层面多样性)",
    "augment+": "数据不动, 内置增强调大 (变化性)",
    "blur2": "训练图统一模糊 σ640=2 (让模型别依赖高频边缘)",
    "blurR": "训练图随机模糊 σ640∈{0,1,2,4} (学高频不变性)",
    "scene40": "大池 40 场景 × 4 图 = 160 张 (场景少)",
    "scene160": "大池 160 场景 × 1 图 = 160 张 (场景多)",
}
BLUR_SIGMA_640 = 2.0       # 固定臂: 输入空间 σ (对应 55 号探针里涨分最多的那一档)
BLUR_SIGMA_640_SET = (0.0, 1.0, 2.0, 4.0)   # 随机臂的取值集合
# 与已发布 R1 run 一致的训练配置 (见 output/benchmark/runs_r1_s43/train/args.yaml)
TRAIN_CFG = dict(epochs=10, imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)
PASTA_SIGMA = 0.6          # 振幅相对扰动强度 (实测 15% 像素变化, 结构保持)
PASTA_HP_START = 0.15     # 高通权重起点: 归一化半径 < 0.15 的低频不加噪 (保色/亮度)


def log(m):
    print(f"[S2R {time.strftime('%m-%d %H:%M:%S')}] {m}", flush=True)


# ---------------------------------------------------------------- 数据层干预

def _pasta(arr, rng, sigma=PASTA_SIGMA, hp_start=PASTA_HP_START):
    """PASTA 式振幅谱扰动 (逐通道)。

    在**振幅谱**上加噪声: 噪声幅度以**图像自身对比度** (像素标准差) 为基准, 乘以高通
    权重 w(f) (低频权重 0, 高频趋近 1) -> 只在"高频纹理"这一频带上补能量, 不动颜色与
    亮度; **相位保持不变** -> 图像结构不变, 框的位置与大小仍然成立, 所以能直接复用原标签。

    注意: 早期版本用"噪声幅度 ∝ 该频率幅值", 结果高频段幅值极小 -> 扰动量近乎为零
    (实测 0.12% 像素变化); 现在改为绝对幅度基准, σ 由 54 号脚本按**真实图的径向幅值谱**
    标定 (让合成图的高频尾巴追上真实图)。
    """
    import numpy as np
    h, w = arr.shape[:2]
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    r = np.sqrt(fy ** 2 + fx ** 2) / 0.7071
    wgt = np.clip((r - hp_start) / (1.0 - hp_start), 0.0, 1.0)
    scale = float(arr.std()) or 1.0
    noise_amp = sigma * scale
    out = np.empty_like(arr)
    for c in range(arr.shape[2]):
        F = np.fft.fft2(arr[:, :, c])
        amp, ph = np.abs(F), np.angle(F)
        noise = rng.normal(0.0, noise_amp, amp.shape) * wgt
        rec = np.real(np.fft.ifft2((amp + noise) * np.exp(1j * ph)))
        out[:, :, c] = rec
    return np.clip(out, 0, 255)


def _photo_degrade(arr, rng):
    """图像空间退化 (传感器噪声 / JPEG / 轻微模糊 / 暗角 / 色偏)。

    几何与标签**不动** -> 干预是单变量, 框仍然有效。
    """
    from PIL import Image, ImageEnhance, ImageFilter
    import numpy as np
    h, w = arr.shape[:2]
    p = {"jpeg_q": int(rng.integers(55, 95)),
         "noise_sigma": float(rng.uniform(0.0, 8.0) / 255.0),
         "blur_radius": float(rng.uniform(0.0, 1.2)),
         "brightness": float(rng.uniform(0.88, 1.12)),
         "contrast": float(rng.uniform(0.88, 1.12)),
         "saturation": float(rng.uniform(0.85, 1.15)),
         "vignette": float(rng.uniform(0.0, 0.35))}
    if p["vignette"] > 0:
        yy, xx = np.mgrid[0:h, 0:w]
        cx, cy = w / 2.0, h / 2.0
        r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / 1.4142
        mask = (1.0 - p["vignette"] * np.clip(r, 0, 1) ** 2)[..., None]
        arr = np.clip(arr * mask, 0, 255)
    im = Image.fromarray(arr.astype(np.uint8))
    if p["blur_radius"] > 0.01:
        im = im.filter(ImageFilter.GaussianBlur(p["blur_radius"]))
    im = ImageEnhance.Brightness(im).enhance(p["brightness"])
    im = ImageEnhance.Contrast(im).enhance(p["contrast"])
    im = ImageEnhance.Color(im).enhance(p["saturation"])
    arr = np.asarray(im, dtype=np.float32)
    if p["noise_sigma"] > 0:
        arr = arr + rng.normal(0, p["noise_sigma"] * 255, arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    im = Image.fromarray(arr)
    import io
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=p["jpeg_q"])
    buf.seek(0)
    out = np.asarray(Image.open(buf).convert("RGB"), dtype=np.float32)
    return out, p


def _blur_train(arr, rng, mode):
    """把训练图按**检测器输入空间**的 σ 模糊 (几何与标签不动)。

    σ 的口径必须是**模型看到的那 640×640**, 不是源图像素: 源图 1440 宽 ->
    letterbox 640 的缩放是 640/1440=0.444, 所以源图 σ = σ640 / 0.444 = σ640×2.25。
    否则"σ=2"在两个空间里指的不是同一个模糊量。
    """
    import cv2
    import numpy as np
    h, w = arr.shape[:2]
    scale = 640.0 / float(max(w, h))          # letterbox 缩放 (短边贴边, 长边缩)
    if mode == "blurR":
        sigma640 = float(rng.choice(BLUR_SIGMA_640_SET))
    else:
        sigma640 = BLUR_SIGMA_640
    sigma_src = sigma640 / scale               # 换算到源图像素
    if sigma_src <= 0.01:
        return arr.copy(), {"mode": mode, "sigma640": sigma640, "sigma_src": 0.0}
    k = int(2 * round(3 * sigma_src) + 1)      # 3σ 半径的核
    out = cv2.GaussianBlur(arr, (k, k), sigma_src, borderType=cv2.BORDER_REPLICATE)
    return out, {"mode": mode, "sigma640": sigma640, "sigma_src": round(sigma_src, 3),
                 "src_wh": [w, h], "letterbox_scale": round(scale, 4)}


def _scene_pool(mode):
    """多样性臂的池: **同样 160 张图, 只变场景数**。

    大池每场景 4 张图, 图内布局种子 = f(base_seed, scene_idx, img_idx) -> 每个
    (场景, 图) 组合的布局都不同。所以:
      scene40  = 40 个场景 x 4 张 = 160 张 (160 种布局, **40** 种场景)
      scene160 = 160 个场景 x 1 张 = 160 张 (160 种布局, **160** 种场景)
    图数与布局多样性都一样 -> 只差**场景多样性** (货架几何/SKU 配比/灯光/相机位姿/
    错位率)。两臂的 val 都用 R1 池的 40 张 val (与对照臂一致) -> best.pt 的挑选口径
    相同, 否则又多一个隐藏变量。
    """
    import shutil
    n_scenes = 40 if mode == "scene40" else 160
    per_scene = 4 if mode == "scene40" else 1
    dst = POOLS[mode]
    man = json.load(open(BIG_MANIFEST, encoding="utf-8"))
    scenes = [s for s in man["scenes"] if s.get("split") == "train"]
    scenes.sort(key=lambda s: s["scene_index"])
    if len(scenes) < n_scenes:
        raise SystemExit(f"[POOL] 大池 train 场景只有 {len(scenes)} 个, 不够 {n_scenes}")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(os.path.join(dst, "images", "train"), exist_ok=True)
    os.makedirs(os.path.join(dst, "labels", "train"), exist_ok=True)
    picked, n_img = [], 0
    for s in scenes[:n_scenes]:
        names = sorted(s["images"])[:per_scene]
        for nm in names:
            shutil.copy2(os.path.join(BIG_SINGLE, "images", "train", nm),
                         os.path.join(dst, "images", "train", nm))
            shutil.copy2(os.path.join(BIG_SINGLE, "labels", "train",
                                       nm.replace(".png", ".txt")),
                         os.path.join(dst, "labels", "train",
                                      nm.replace(".png", ".txt")))
            picked.append({"image": nm, "scene_id": s["scene_id"],
                           "scene_index": s["scene_index"]})
            n_img += 1
    # val 用 R1 池的 40 张 (与对照臂同一批图 -> best.pt 挑选口径一致)
    with open(os.path.join(dst, "dataset.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"path: {dst}\ntrain: images/train\n"
                 f"val: {os.path.join(SRC_POOL, 'images', 'val')}\n"
                 "nc: 1\nnames: [product]\n")
    meta = {"mode": mode, "src_pool": BIG_SINGLE, "pool": dst,
            "n_scenes": n_scenes, "images_per_scene": per_scene, "n_images": n_img,
            "n_layouts": n_img, "val": os.path.join(SRC_POOL, "images", "val"),
            "scene_ids": sorted({p["scene_id"] for p in picked}),
            "note": ("图数与图内布局多样性都相同, 只差场景多样性; 两臂 val 与对照臂一致。")}
    with open(os.path.join(BENCH, f"syn2real_{mode}_meta.json"), "w",
              encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    log(f"{mode} 池 -> {dst} ({n_img} 张, {n_scenes} 个场景, 每场景 {per_scene} 张)")
    return dst


def prepare_pool(mode, seed=20261124, sigma=None):
    """生成干预后的池 (几何与标签原样复制, 只动像素)。"""
    import numpy as np
    from PIL import Image
    if sigma is None:
        sigma = PASTA_SIGMA
        meta_path = os.path.join(BENCH, "syn2real_pasta_calib.json")
        if os.path.exists(meta_path):
            try:
                sigma = float(json.load(open(meta_path, encoding="utf-8"))["sigma"])
                log(f"采用 54 号标定的 PASTA sigma = {sigma}")
            except Exception:
                pass
    dst = POOLS[mode]
    have = len(glob.glob(os.path.join(dst, "images", "train", "*.png")))
    meta_path = os.path.join(BENCH, f"syn2real_{mode}_meta.json")
    if have >= 160 and os.path.exists(meta_path):
        try:
            meta = json.load(open(meta_path, encoding="utf-8"))
            if meta.get("verified_mean_abs_diff", 0) > 0.05:
                log(f"{mode} 池已存在 ({have} 张, 已核验与源图有差异 "
                    f"{meta['verified_mean_abs_diff']:.2f}), 复用")
                return dst
        except Exception:
            pass
    if os.path.isdir(dst):
        shutil.rmtree(dst)          # 旧池可能是"退化没生效"的坏池 (见 meta 的核验项)
    os.makedirs(dst, exist_ok=True)
    rng = np.random.default_rng(seed)
    params = []
    diffs = []
    for split in ("train", "val"):
        src_i = os.path.join(SRC_POOL, "images", split)
        src_l = os.path.join(SRC_POOL, "labels", split)
        dst_i = os.path.join(dst, "images", split)
        dst_l = os.path.join(dst, "labels", split)
        os.makedirs(dst_i, exist_ok=True)
        os.makedirs(dst_l, exist_ok=True)
        if not os.path.isdir(src_i):
            continue
        for f in sorted(os.listdir(src_i)):
            if not f.lower().endswith(".png"):
                continue
            shutil.copy2(os.path.join(src_l, f.replace(".png", ".txt")),
                         os.path.join(dst_l, f.replace(".png", ".txt")))
            src = np.asarray(Image.open(os.path.join(src_i, f)).convert("RGB"),
                             dtype=np.float32)
            if mode == "photo":
                out, p = _photo_degrade(src, rng)
            elif mode in ("blur2", "blurR"):
                out, p = _blur_train(src, rng, mode)
            else:
                out = _pasta(src, rng, sigma=sigma)
                p = {"mode": mode, "sigma": sigma}
            diffs.append(float(np.abs(out - src).mean()))
            Image.fromarray(out.astype(np.uint8)).save(os.path.join(dst_i, f))
            params.append(p)
    with open(os.path.join(dst, "dataset.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"path: {dst}\ntrain: images/train\nval: images/val\n"
                 f"nc: 1\nnames: [product]\n")
    mad = float(np.mean(diffs)) if diffs else 0.0
    meta = {"mode": mode, "src_pool": SRC_POOL, "pool": dst, "seed": seed,
            "n_images": len(params), "sigma": sigma, "hp_start": PASTA_HP_START,
            "verified_mean_abs_diff": round(mad, 4),
            "param_summary": ({"sigma640_hist": {str(k): sum(1 for p in params
                                                        if p.get("sigma640") == k)
                                                  for k in sorted({p.get("sigma640")
                                                                   for p in params})},
                               "note": "σ 以 letterbox 640 输入空间为准; "
                                       "sigma_src = sigma640 / letterbox_scale"}
                              if mode in ("blur2", "blurR") else None),
            "note": ("几何与标签原样复制, 只动像素 -> 干预是单变量, 框仍有效。"
                     "verified_mean_abs_diff = 干预后与源图的平均像素差; "
                     "**若为 0 说明干预没生效** (2026-11-25 就踩到过一个"
                     "'退化池与源图逐像素相同'的坏池, 会把该臂变成对照臂的复制品)。")}
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    log(f"{mode} 池 -> {dst} ({len(params)} 张, 平均像素差 {mad:.3f})")
    if mad <= 0.05:
        raise SystemExit(f"[POOL] {mode} 干预**没有生效** (平均像素差 {mad:.4f}) —— "
                         f"若继续跑, 该臂等于对照臂, 会得到假阴性。已中止。")
    return dst


# ---------------------------------------------------------------- 训练与评测

def train_eval(arm, seeds, data_yaml, extra_hyp=None, control=False):
    from ultralytics import YOLO
    out = []
    for seed in seeds:
        if control:
            ckpt = os.path.join(BENCH, CONTROL_RUNS.format(seed=seed),
                                "train", "weights", "best.pt")
            if not os.path.isfile(ckpt):
                log(f"对照权重缺失 (runs_r1_s{seed}), 跳过该 seed")
                continue
        else:
            run = os.path.join(BENCH, f"runs_s2r_{arm.replace('+','p')}_s{seed}")
            ckpt = os.path.join(run, "train", "weights", "best.pt")
            if not os.path.isfile(ckpt):
                hyp = dict(TRAIN_CFG)
                if extra_hyp:
                    hyp.update(extra_hyp)
                model = YOLO("yolo11n.pt")
                model.train(data=data_yaml, seed=seed, project=run, name="train",
                            exist_ok=True, verbose=False, **hyp)
        m = YOLO(ckpt)
        r = m.val(data=REAL_YAML, split="test", imgsz=640, batch=4, device="0",
                  max_det=1000, workers=2, verbose=False)
        out.append({"seed": seed, "map50": float(r.box.map50),
                    "map50_95": float(r.box.map)})
        log(f"{arm} seed {seed}: 真实 test mAP50 = {out[-1]['map50']:.4f}")
    return out


def _t975(n):
    """95% 双侧 t 分位数 (df = n-1)。小样本用 z=1.96 会**低估** CI 宽度。

    仓里已有教训 (multi-seed-aggregation-pitfalls): n=3 的配对差值用 1.96 会把
    CI 算窄, 判语("显著")就会和统计量打架。这里按 df 查表, n>=30 用 1.96。
    """
    table = {1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706, 6: 2.4469, 7: 2.3646,
             8: 2.3060, 9: 2.2622, 10: 2.2281, 11: 2.2010, 12: 2.1788,
             13: 2.1604, 14: 2.1448, 15: 2.1314, 16: 2.1199, 17: 2.1098,
             18: 2.1009, 19: 2.0930, 20: 2.0860, 25: 2.0600, 30: 2.0423}
    df = max(1, n - 1)
    if df in table:
        return table[df]
    if df < 30:
        ks = sorted(table)
        lo = max(k for k in ks if k <= df)
        hi = min(k for k in ks if k >= df)
        return table[lo] + (table[hi] - table[lo]) * (df - lo) / (hi - lo)
    return 1.96


def _stats(vals):
    n = len(vals)
    mean = statistics.mean(vals)
    sd = statistics.stdev(vals) if n > 1 else 0.0
    hw = _t975(n) * sd / (n ** 0.5) if n > 1 else 0.0
    return {"mean": round(mean, 4), "sd": round(sd, 4), "n": n,
            "ci95": [round(mean - hw, 4), round(mean + hw, 4)]}


def summarize(arm, recs, control=None):
    if not recs:
        return None
    v = [r["map50"] for r in recs]
    s = {"mean": round(statistics.mean(v), 4),
         "sd": round(statistics.stdev(v), 4) if len(v) > 1 else 0.0,
         "n": len(v),
         "per_seed": {str(r["seed"]): r["map50"] for r in recs}}
    if control:
        cm = {c["seed"]: c["map50"] for c in control}
        diffs = [r["map50"] - cm[r["seed"]] for r in recs if r["seed"] in cm]
        if len(diffs) >= 2:
            mean = statistics.mean(diffs)
            sd = statistics.stdev(diffs)
            hw = _t975(len(diffs)) * sd / (len(diffs) ** 0.5)
            s["paired_diff_pp"] = [round(x * 100, 3) for x in diffs]
            s["paired_mean_pp"] = round(mean * 100, 3)
            s["paired_ci95_pp"] = [round((mean - hw) * 100, 3),
                                   round((mean + hw) * 100, 3)]
            s["paired_significant"] = bool(s["paired_ci95_pp"][0] > 0 or
                                           s["paired_ci95_pp"][1] < 0)
    return s


def merge_arm(old, new):
    """把新的臂结果并进旧的 (按 seed 取并集, 重算统计量)。

    坑 (multi-seed-aggregation-pitfalls): 直接 `old = new` 会**覆盖**之前跑的 seed ——
    分两次跑同一臂 (比如先 43,44,45 后补 46) 时, 第一次的 seed 会消失, n 变小、
    CI 变窄, 而报告上还看不出少了 seed。这里按 seed 并集重算。
    """
    if not old:
        return new
    if not new:
        return old
    per = dict(old.get("per_seed") or {})
    per.update(new.get("per_seed") or {})
    seeds = sorted(per, key=lambda s: int(s))
    vals = [per[s] for s in seeds]
    out = {"mean": round(statistics.mean(vals), 4),
           "sd": round(statistics.stdev(vals), 4) if len(vals) > 1 else 0.0,
           "n": len(vals), "per_seed": per}
    for k in ("paired_diff_pp", "paired_mean_pp", "paired_ci95_pp",
              "paired_significant"):
        if new.get(k) is not None:
            out[k] = new[k]
    return out


def render_md(rep):
    """把产物渲染成 markdown 表 (闸门 [15] 逐臂核对的对象)。

    抽成函数是为了让 60 号 (从日志恢复某一臂) 能用**同一份**渲染逻辑重建 .md ——
    否则恢复出来的数字只在 .json 里, .md 与 .json 会各说各话。
    """
    lines = ["# sim2real 干预探针 (2026-11-25)", "",
             "图数固定 160 张, 训练配置与已发布 R1 run 一致, 逐个隔离一种干预。", "",
             "| 干预 | 真实 test mAP@0.5 (mean ± sd) | n | 配对差值 vs 对照 (pp) | 95% CI | 显著 |",
             "|---|---|---:|---:|---|:--:|"]
    for arm in ARMS:
        v = rep["results"].get(arm)
        if not v:
            continue
        pd = v.get("paired_mean_pp")
        ci = v.get("paired_ci95_pp")
        lines.append(
            f"| {arm} ({ARM_DESC.get(arm, '')}) | {v['mean']:.4f} ± {v['sd']:.4f} | {v['n']} | "
            f"{('%+.2f' % pd) if pd is not None else '—'} | "
            f"{('[%+.2f, %+.2f]' % (ci[0], ci[1])) if ci else '—'} | "
            f"{'是' if v.get('paired_significant') else '否'} |")
    lines += ["", "**读法**: 配对差值 95% CI 整段 > 0 -> 该干预有效; 跨 0 -> 无效。",
              "对照臂 = 原池 (同评测流程重评, 与已发布数字一致)。",
              "依据: PASTA (ICCV 2023) / arXiv 2610.00030。"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", default="photo",
                    choices=("photo", "pasta", "mixed3", "augment+", "control",
                             "blur2", "blurR", "scene40", "scene160"))
    ap.add_argument("--seeds", default="43,44,45")
    ap.add_argument("--all-arms", action="store_true",
                    help="一次跑完 photo/pasta/mixed3/augment+ (对照臂自动带上)")
    ap.add_argument("--arms", default="",
                    help="逗号分隔的臂名列表 (优先于 --arm/--all-arms)")
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]

    ctrl_recs = train_eval("control", seeds, None, control=True)
    results = {"control": summarize("control", ctrl_recs)}

    if args.arms:
        arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    elif args.all_arms:
        arms = ["photo", "pasta", "mixed3", "augment+"]
    else:
        arms = [args.arm]
    for arm in arms:
        if arm == "augment+":
            yml = os.path.join(SRC_POOL, "dataset.yaml")
            hyp = {"hsv_h": 0.05, "hsv_s": 1.0, "hsv_v": 0.7,
                   "mosaic": 1.0, "mixup": 0.2, "scale": 0.5, "degrees": 10.0}
            recs = train_eval(arm, seeds, yml, extra_hyp=hyp)
        elif arm == "mixed3":
            # 选权重的 val 集必须与对照臂**完全一致** (R1 池的 40 张 val), 否则
            # "best.pt 是按哪批图选的" 就是一个额外变量, 配对比较就不成立。
            # 53 号生成的 mixed3.yaml 把 val 也混成了三池 (40 张), 那样这一臂的
            # best.pt 与对照臂的 best.pt 是在**不同 val** 上选出来的 -> 这里改写一份。
            src = os.path.join(BENCH, "diversity", "mixed3.yaml")
            with open(src, encoding="utf-8") as fh:
                txt = fh.read()
            train_line = next(l for l in txt.splitlines() if l.startswith("train:"))
            yml = os.path.join(BENCH, "diversity", "mixed3_sameval.yaml")
            with open(yml, "w", encoding="utf-8") as fh:
                fh.write(train_line + "\n")
                fh.write(f"val: {os.path.join(SRC_POOL, 'images', 'val')}\n")
                fh.write("nc: 1\nnames: [product]\n")
            log(f"mixed3 的 val 改为与对照臂一致的 R1 池 val (40 张) -> {yml}")
            recs = train_eval(arm, seeds, yml)
        elif arm in ("scene40", "scene160"):
            pool = _scene_pool(arm)
            recs = train_eval(arm, seeds, os.path.join(pool, "dataset.yaml"))
        else:
            pool = prepare_pool(arm)
            recs = train_eval(arm, seeds, os.path.join(pool, "dataset.yaml"))
        results[arm] = summarize(arm, recs, ctrl_recs)

    rep = {"schema": "syn2real_interventions/1",
           "generated_by": "pipelines/shelf_sdg/52_photorealism_probe.py",
           "measured_at": "2026-11-25",
           "question": ("图数固定 160 张, 训练配置与已发布 R1 run 一致, "
                        "逐个隔离一种干预 -> 哪一种能撼动跨域 mAP?"),
           "literature": ("PASTA (ICCV 2023): 合成图高频振幅变化不足 -> 振幅域扰动可改善 "
                          "sim2real; arXiv 2610.00030: 合成数据可作探针隔离单一因素, "
                          "且'增加变化性常比提升视觉真实度更有效'"),
           "arms": ARM_DESC, "train_cfg": TRAIN_CFG, "seeds": seeds,
           "results": {}}
    prev = {}
    if os.path.exists(OUT_JSON):
        try:
            prev = json.load(open(OUT_JSON, encoding="utf-8")).get("results", {})
        except Exception:
            prev = {}
    for k, v in results.items():
        if v is None:
            continue
        prev[k] = merge_arm(prev.get(k), v)     # 按 seed 并集, 不覆盖旧 seed
    rep["results"] = prev
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    os.makedirs(PUB, exist_ok=True)
    shutil.copy2(OUT_JSON, os.path.join(PUB, "syn2real_interventions.json"))

    md = render_md(rep)
    with open(os.path.join(BENCH, "syn2real_interventions.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    shutil.copy2(os.path.join(BENCH, "syn2real_interventions.md"),
                 os.path.join(PUB, "syn2real_interventions.md"))
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
