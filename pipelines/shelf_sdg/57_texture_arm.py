#!/usr/bin/env python
"""纹理臂 (2026-11-25): 把"合成商品是无纹理白盒"这条实测缺口直接做成一个实验。

**为什么做这个**: 前面几轮把缺口定位到"跨域外观" (74.66 pp), 并用频谱分解 + 三个
干预臂证明它**不是**框的统计量、**不是**照片颗粒、**不是**增强/多样性。最后剩下
"商品长什么样" 这条, 而它的根因在本仓里是**一行代码**: 渲染器的
`create_material_for_sku()` 会去 `assets/textures/{sku}_albedo.png` 找每个 SKU 的
包装贴图, 但研究池渲染时**那些贴图不在工作区** -> 所有商品静默退回默认白材质。
贴图生成器 `pipelines/bootstrap/00_bootstrap_textures.py` 一直都在 (主视觉/营养表/
EAN-13 条码/侧面色条/烫金), 只是没跑过。

**设计 (单变量)**: 与 R1 对照池**完全同一配方、同一 seed、同一场景布局**
(num_images=200 / seed 42 / scene 留出 / 4 图每场景 / samples 64 / cam 1.0 / lens 28 /
misalign 0.10 / bays 1), 唯一变化 = 商品材质 (白 -> 印刷包装)。布局种子由
(base_seed, scene_idx, img_idx) 派生, 与材质无关 -> 场景/光照/相机/框全部逐帧一致,
**只有商品表面像素不同**。

**主比较 = last-vs-last**: R1 已发布权重是 best.pt (按 R1 池的 40 张白盒 val 选的)。
如果纹理臂也用 best.pt, 选权重的集合虽然相同、但那是"白盒域" -> 对纹理臂不友好
(它在自己域里的最好 epoch 未必在白盒域里最好) -> 这个隐藏变量会污染结论。
所以主比较用 **last.pt** (完全无挑选), best-vs-best 作为次要参考一起报出来。

用法:
    python pipelines/shelf_sdg/57_texture_arm.py --stage render   # 渲 200 张 (带贴图)
    python pipelines/shelf_sdg/57_texture_arm.py --stage single   # 单类化 (丢 class 1)
    python pipelines/shelf_sdg/57_texture_arm.py --stage train --seeds 43,44,45
    python pipelines/shelf_sdg/57_texture_arm.py --stage all
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
RAW = os.path.join(BENCH, "sdg_shelf_tex")     # 带贴图的原始渲染 (4 类)
POOL = os.path.join(BENCH, "synth_tex")        # 单类化后的训练池
CONTROL_RUNS = "runs_r1_s{seed}"               # 对照臂 (白盒池) 的已发布 run
LOG = os.path.join(BENCH, "texture_arm.log")
ART = os.path.join(BENCH, "texture_arm.json")

# 与 R1 对照池 (output/sdg_shelf) 完全一致的配方 —— 唯一变化是商品材质
RECIPE = dict(num_images=200, seed=42, val_ratio=0.2, images_per_scene=4,
              split_mode="scene", samples=64,
              cam_mult=1.0, lens=28.0, misalign=0.10, bays=1)
# 与已发布 R1 run 一致的训练配置 (见 output/benchmark/runs_r1_s43/train/args.yaml)
TRAIN_CFG = dict(epochs=10, imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)
SEEDS = [43, 44, 45]

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
if os.environ.get("SDG_RENDER_DEVICE", "").strip().lower() == "cpu":
    ENV["FORCE_CPU_RENDER"] = "1"
else:
    ENV.pop("FORCE_CPU_RENDER", None)
ENV["CYCLES_DEVICE"] = ENV.get("CYCLES_DEVICE", "OPTIX")


def log(m):
    line = f"[TEX {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def render():
    """渲带贴图的池 (GPU)。已渲完则跳过 (可续跑)。"""
    n_done = len(glob.glob(os.path.join(RAW, "images", "train", "*.png"))) + \
        len(glob.glob(os.path.join(RAW, "images", "val", "*.png")))
    if n_done >= RECIPE["num_images"]:
        log(f"带贴图的池已存在 ({n_done} 张), 跳过渲染")
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
        "--out", RAW]
    log("RUN " + " ".join(cmd[1:]))
    t0 = time.time()
    with open(os.path.join(BENCH, "texture_render.log"), "w", encoding="utf-8",
              errors="ignore") as fh:
        r = subprocess.run(cmd, env=ENV, cwd=BASE, stdout=fh, stderr=subprocess.STDOUT)
    log(f"渲染结束 (退出码 {r.returncode}, {(time.time()-t0)/60:.1f} min)")
    return r.returncode == 0


def to_single():
    """4 类 -> 单类 (丢 class 1 = OOS gap), 与 14/43 号同逻辑。

    val 指向 **R1 池的 40 张 val** (与对照臂同一批图) -> best.pt 的挑选口径与对照臂一致。
    """
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
    r1_val = os.path.join(BENCH, "synth_single", "images", "val")
    with open(os.path.join(POOL, "dataset.yaml"), "w", encoding="utf-8") as fh:
        fh.write(f"path: {POOL}\ntrain: images/train\nval: {r1_val}\n"
                 "nc: 1\nnames: [product]\n")
    n = len(glob.glob(os.path.join(POOL, "images", "train", "*.png")))
    log(f"单类化完成: {POOL} train={n} (val 指向 R1 池的 40 张)")
    return n


def _eval(ckpt):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=ENV["SKU110K_YAML"], split="test", imgsz=640, batch=4, device="0",
              max_det=1000, workers=2, verbose=False)
    # 2026-11-25: 记 precision / recall —— 只看 mAP 看不出"贴图让模型**多认**了还是
    # **少认**了真实商品, 而这决定了下一步该修商品表面还是修背景/杂乱。
    return (float(r.box.map50), float(r.box.map),
            float(r.box.mp), float(r.box.mr))


def train(seeds):
    """训练纹理臂 + 评测四组权重 (对照/纹理 x last/best)。"""
    from ultralytics import YOLO
    recs = {}
    yml = os.path.join(POOL, "dataset.yaml")
    for seed in seeds:
        run = os.path.join(BENCH, f"runs_tex_s{seed}")
        ck_best = os.path.join(run, "train", "weights", "best.pt")
        ck_last = os.path.join(run, "train", "weights", "last.pt")
        if not os.path.isfile(ck_last):
            model = YOLO("yolo11n.pt")
            model.train(data=yml, seed=seed, project=run, name="train", exist_ok=True,
                        verbose=False, **TRAIN_CFG)
        row = {}
        # 对照臂 (白盒池) 的 last.pt —— 主比较的基线
        ctrl_last = os.path.join(BENCH, CONTROL_RUNS.format(seed=seed),
                                  "train", "weights", "last.pt")
        if os.path.isfile(ctrl_last):
            m50, m95, mp, mr = _eval(ctrl_last)
            row["control_last"] = {"map50": m50, "map50_95": m95,
                                   "precision": mp, "recall": mr}
            log(f"control(last) seed {seed}: 真实 test mAP50 = {m50:.4f}")
        for tag, ck in (("texture_best", ck_best), ("texture_last", ck_last)):
            if not os.path.isfile(ck):
                continue
            m50, m95, mp, mr = _eval(ck)
            row[tag] = {"map50": m50, "map50_95": m95,
                        "precision": mp, "recall": mr}
            log(f"{tag} seed {seed}: 真实 test mAP50 = {m50:.4f}")
        recs[str(seed)] = row
    # ---- 汇总: 配对差值 (同 seed) ----
    def _paired(a, b):
        diffs = []
        for s, row in recs.items():
            if a in row and b in row:
                diffs.append((row[b]["map50"] - row[a]["map50"]) * 100.0)
        if not diffs:
            return None
        n = len(diffs)
        mean = sum(diffs) / n
        if n == 1:
            return {"n": n, "mean_pp": round(mean, 4), "ci95_pp": None,
                    "per_seed_pp": [round(d, 4) for d in diffs]}
        _m, lo, hi = ci95_t(diffs)
        return {"n": n, "mean_pp": round(mean, 4),
                "ci95_pp": [round(lo, 4), round(hi, 4)],
                "per_seed_pp": [round(d, 4) for d in diffs]}

    art = {"schema": "texture_arm/1",
           "generated_by": "pipelines/shelf_sdg/57_texture_arm.py",
           "measured_at": time.strftime("%Y-%m-%d"),
           "question": ("同一配方/同 seed/同场景布局, 只把商品表面从无纹理白盒换成"
                        "程序化印刷包装 -> 跨域 mAP 会动吗?"),
           "recipe": RECIPE, "train_cfg": TRAIN_CFG, "seeds": seeds,
           "pool": POOL, "per_seed": recs, "paired": {}}
    for a, b in (("control_last", "texture_last"), ("control_last", "texture_best")):
        p = _paired(a, b)
        if p:
            art["paired"][f"{b}_minus_{a}"] = p
    with open(ART, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=2)
    log(f"产物 -> {ART}")
    return art


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=("render", "single", "train", "all"), default="all")
    ap.add_argument("--seeds", default=",".join(str(s) for s in SEEDS))
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    if args.stage in ("render", "all"):
        if not render():
            raise SystemExit("[TEX] 渲染失败")
    if args.stage in ("single", "all"):
        to_single()
    if args.stage in ("train", "all"):
        train(seeds)
    log("=== 纹理臂结束 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
