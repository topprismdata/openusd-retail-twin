#!/usr/bin/env python
"""I-22 · MixStyle（特征级多样化）臂 (2026-11-26)。

为什么做这个臂 (文献 + 本仓自己的负结果共同指向):
  * 本仓实测: **把合成域做得"更像真实"没有用, 反而更差** (I-17 −23.5 pp / I-18 −10.1 pp
    ✓), 而"加更多合成图"也不补缺口 (剂量轴平坦略负 ✓) -> "提高真实感"这条已被否 ✓。
  * 文献 (arXiv 2610.00030, TNO/FOI 综述 §5.1): **"increasing variation ... is often more
    effective for improving synthetic-to-real transfer than increasing visual realism"**
    ✓ —— 其中明确点名**特征级多样化** (MixStyle / pAdaIN / DSU ✓) 与 PASTA ✓。
  * 本仓**从未测过特征级多样化** ✓: 测过的是图像级增强 (augment+ −3.77 ✓)、场景数多样性
    (scene40/scene160 未检出 ✓)、以及"更像真实" (I-17/I-18 ✓) —— 但**特征统计层面的
    扰动**是一个独立的、未测过的旋钮 ✓。

干预 (单变量, 其余与 R1 对照臂逐项相同 ✓):
  * 训练时在 backbone 的前两个 C2f 阶段之后, 对特征图做 **MixStyle** ✓
    (官方实现: 每样本每通道的 mu/sigma 与**打乱后的 batch** 按 Beta(a,a) 采样混合 ✓;
     a=0.1 ✓, 与 MixStyle 检测配置的默认一致 ✓);
  * **只在训练时开** (eval 时关闭 ✓ -> 不改推理路径 ✓);
  * 数据集 = **已发布的 legacy 单类池** (与 R1 对照臂同一份 ✓), 图数/像素/标签/训练配方
    (10 ep / batch 4 / imgsz 640 / workers 2 / pretrained / optimizer auto / close_mosaic 10)
    全部不变 ✓ -> **唯一变量 = 特征统计被扰动** ✓。

口径: 与已发布的 R1 对照臂 (runs_r1_s{seed}) 同 seed 配对, 主比较 last-vs-last,
seed 43-47 (n=5 —— 跨域臂 n=3 统计功效不够 ✓)。

用法:
    python pipelines/shelf_sdg/69_mixstyle_arm.py [--seeds 43 44 45 46 47]
产物:
    output/benchmark/mixstyle_arm.json
"""
import json
import os
import sys
import time

import torch

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")
POOL = os.path.join(BENCH, "synth_single")
LOG = os.path.join(BENCH, "mixstyle_arm.log")
ART = os.path.join(BENCH, "mixstyle_arm.json")
SEEDS = [43, 44, 45, 46, 47]
ALPHA = 0.1
TRAIN_CFG = dict(epochs=10, imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)


def log(m):
    line = f"[MIXSTYLE {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def mixstyle(x, alpha=ALPHA, eps=1e-6):
    """官方 MixStyle: 每样本每通道的 mu/sigma 与打乱后的 batch 混合 ✓。"""
    import torch
    from torch.distributions import Beta
    if x.dim() != 4 or x.size(0) < 2:
        return x
    mu = x.mean(dim=[2, 3], keepdim=True)
    var = x.var(dim=[2, 3], keepdim=True)
    sig = (var + eps).sqrt()
    x_norm = (x - mu) / sig
    lmda = Beta(alpha, alpha).sample((x.size(0), 1, 1, 1)).to(x.device)
    mu_mix = lmda * mu + (1 - lmda) * mu.flip(0)
    sig_mix = lmda * sig + (1 - lmda) * sig.flip(0)
    return x_norm * sig_mix + mu_mix


def patch_mixstyle(model, n_stages=2):
    """把 backbone 的前 n_stages 个 C2f 模块的输出做 MixStyle (仅训练时 ✓)。

    实现: 替换模块的 forward ✓ —— ultralytics 的 C2f.forward 返回一个 tensor ✓,
    所以包一层即可 ✓; **eval 时直接返回原输出** ✓ (推理路径不变 ✓)。
    """
    import torch.nn as nn
    net = model.model.model if hasattr(model, "model") else model.model
    backbone = net.model if hasattr(net, "model") else net
    # YOLO11 的 backbone 块叫 **C3k2** (不是 C2f ✓); 两种都认, 取前 n_stages 个 ✓
    stages = [m for m in backbone if type(m).__name__ in ("C3k2", "C2f")]
    if len(stages) < n_stages:
        raise SystemExit(f"backbone 里只有 {len(stages)} 个 C3k2/C2f, 不足 {n_stages}")
    wrapped = []
    for m in stages[:n_stages]:
        orig = m.forward

        def new_forward(x, _orig=orig, _mod=m):
            out = _orig(x)
            if _mod.training and isinstance(out, torch.Tensor):
                return mixstyle(out)
            return out

        m.forward = new_forward
        wrapped.append(type(m).__name__)
    return wrapped


def _eval(ckpt):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"), split="test",
              imgsz=640, batch=4, device="0", max_det=1000, workers=2, verbose=False)
    return {"map50": float(r.box.map50), "map50_95": float(r.box.map),
            "precision": float(r.box.mp), "recall": float(r.box.mr)}


def main():
    import argparse
    import torch
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", default=SEEDS)
    args = ap.parse_args()
    yml = os.path.join(POOL, "dataset.yaml")
    if not os.path.isfile(yml):
        raise SystemExit(f"缺 {yml}")

    from ultralytics import YOLO
    recs = {}
    if os.path.isfile(ART):
        try:
            recs = dict(json.load(open(ART, encoding="utf-8")).get("per_seed") or {})
        except Exception:
            recs = {}
    for seed in args.seeds:
        row = recs.get(str(seed)) or {}
        run = os.path.join(BENCH, f"runs_mixstyle_s{seed}")
        ck = os.path.join(run, "train", "weights", "last.pt")
        if not os.path.isfile(ck):
            model = YOLO("yolo11n.pt")
            patched = patch_mixstyle(model)
            log(f"seed {seed}: MixStyle 已挂到 {patched}")
            model.train(data=yml, seed=seed, project=run, name="train", exist_ok=True,
                        verbose=False, **TRAIN_CFG)
        row["arm_last"] = _eval(ck)
        log(f"arm seed {seed}: 真实 test mAP50 = {row['arm_last']['map50']:.4f}")
        ctrl = os.path.join(BENCH, f"runs_r1_s{seed}", "train", "weights", "last.pt")
        if os.path.isfile(ctrl):
            row["control_last"] = _eval(ctrl)
            log(f"control seed {seed}: 真实 test mAP50 = {row['control_last']['map50']:.4f}")
        recs[str(seed)] = row

    diffs = []
    for s, row in recs.items():
        if "arm_last" in row and "control_last" in row:
            diffs.append((row["arm_last"]["map50"] - row["control_last"]["map50"]) * 100.0)
    rep = {"schema": "mixstyle_arm/1",
           "generated_by": "pipelines/shelf_sdg/69_mixstyle_arm.py",
           "measured_at": time.strftime("%Y-%m-%d"),
           "question": ("特征级多样化 (MixStyle) 能不能比'更像真实'更有效地补上跨域缺口?"),
           "intervention": {
               "name": "训练时对 backbone 前两个 C2f 的输出做 MixStyle (a=0.1), eval 时关闭",
               "alpha": ALPHA, "stages": 2, "pool": POOL, "train_cfg": TRAIN_CFG,
               "note": ("数据/图数/像素/标签/配方与 R1 对照臂逐项相同 ✓; "
                        "唯一变量 = 训练时的特征统计被扰动 ✓")},
           "control": "已发布的 R1 对照臂 (runs_r1_s{seed})",
           "per_seed": recs}
    if diffs:
        n = len(diffs)
        mean = sum(diffs) / n
        out = {"n": n, "mean_pp": round(mean, 4),
               "per_seed_pp": [round(d, 4) for d in diffs]}
        if n > 1:
            _m, lo, hi = ci95_t(diffs)
            out["ci95_pp"] = [round(lo, 4), round(hi, 4)]
        rep["paired"] = {"arm_last_vs_control_last": out}
        log(f"配对 arm - control: {mean:+.2f} pp, CI {out.get('ci95_pp')}")
    with open(ART, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    log(f"-> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
