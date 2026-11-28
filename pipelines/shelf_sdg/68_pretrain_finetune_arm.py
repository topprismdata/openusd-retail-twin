#!/usr/bin/env python
"""I-20 ·「合成预训练 + 真实标注微调」的分工臂 (2026-11-26)。

为什么做这个臂 (按机制, 不按直觉):
  * I-16 (63 号探针): 真实照片的上下文是**干扰项** (去掉它 +22.76 pp ✓), 而合成域里
    上下文**有用** (去掉它 −0.29 pp ✓) -> 模型在合成域学到的"什么是商品"**依赖合成域
    的上下文** ✓, 到真实照片上这个依赖失效 ✗。
  * 前面所有臂 (I-17 整域重写 / I-18 只改上下文 / I-19 训练时抑制上下文依赖) 都是
    "让合成数据**直接**参与真实域训练" ✗ -> 都被否掉了或幅度不够 ✓。
  * 剩下唯一与机制一致、且没被否掉的用法 = **换分工**: 合成数据只做**预训练**
    (提供商品形状/尺度的先验 ✓), 真实标注做**微调** (让模型适应真实域 ✓, 并在有真实
    照片的阶段里自己学会忽略上下文 ✓)。

臂与两个对照 (三者都用同一份真实子集、同一套配方 ✓):
  * arm    : yolo11n -> 合成池预训练 10 ep -> 真实子集微调 10 ep -> 评测 last.pt
  * ctrl_a : yolo11n -> 只在真实子集上训 10 ep (与臂的**真实曝光**相同 ✓)
  * ctrl_b : yolo11n -> 只在真实子集上训 20 ep -> **总步数比臂更多**
    (臂 = 10x40 + 10x103 = 1430 步 ✓; ctrl_b = 20x103 = 2060 步 ✓) -> 它是**更严格的**
    对照 ✓: 臂若赢过它, 就不是"臂只是多训了步数" ✓。
    两个对照分别堵住"臂只是多看了真实数据"(ctrl_a ✓)与"臂只是多训了步数"(ctrl_b ✓)。

口径: 真实子集 = 5% 预算的 411 张 (与 21 号预算臂**同一份名单** ✓, budget_seed
20261120 ✓); 合成池 = 已发布的 legacy 单类池 (160 张 ✓, 不重渲 ✓); 评测 = SKU-110K
的 test split ✓ (与所有臂同一份 ✓); 主比较 = last-vs-last ✓, 逐 seed 配对 ✓。

用法:
    python pipelines/shelf_sdg/68_pretrain_finetune_arm.py [--seeds 43 44 45]
产物:
    output/benchmark/pretrain_finetune_arm.json
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")
BUDGET_DIR = os.path.join(BENCH, "budget")
SYNTH_POOL = os.path.join(BENCH, "synth_single")          # 已发布的 legacy 单类池
REAL_LIST = os.path.join(BUDGET_DIR, "real0.05_synth0_real.txt")   # 5% 预算的真实名单 ✓
LOG = os.path.join(BENCH, "pretrain_finetune_arm.log")
ART = os.path.join(BENCH, "pretrain_finetune_arm.json")
SEEDS = [43, 44, 45]
REAL_FRAC = 0.05
TRAIN_CFG = dict(imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)
PRETRAIN_EP = 10
FINETUNE_EP = 10
CTRL_A_EP = 10
CTRL_B_EP = 20


def log(m):
    line = f"[PF {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def write_yaml(path, train_entries, val_dir, test_dir):
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"path: {BASE}\n")
        f.write("train: [" + ", ".join(train_entries) + "]\n")
        f.write(f"val: {val_dir}\n")
        f.write(f"test: {test_dir}\n")
        f.write("nc: 1\nnames: [product]\n")
    return path


EVAL_CACHE = os.path.join(BENCH, "pf_arm_eval_cache.json")


def _cache_load():
    try:
        return json.load(open(EVAL_CACHE, encoding="utf-8"))
    except Exception:
        return {}


def _cache_save(d):
    with open(EVAL_CACHE, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)


def _eval_cached(ckpt, yaml, key):
    """评测并缓存 ✓ —— 断点续跑时不必重跑 GPU 评测 ✓。"""
    c = _cache_load()
    if key in c:
        return c[key]
    r = _eval(ckpt, yaml)
    c[key] = r
    _cache_save(c)
    return r


def _eval(ckpt, yaml):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=yaml, split="test", imgsz=640, batch=4, device="0",
              max_det=1000, workers=2, verbose=False)
    return {"map50": float(r.box.map50), "map50_95": float(r.box.map),
            "precision": float(r.box.mp), "recall": float(r.box.mr)}


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="*", default=SEEDS)
    args = ap.parse_args()

    if not os.path.isfile(REAL_LIST):
        raise SystemExit(f"缺 {REAL_LIST} —— 先跑 21 号预算臂生成 5% 真实名单")
    # 真实子集的 yaml: 训练清单 = 5% 名单, val/test = 真实 val/test 目录 (与预算臂同)
    ref_yaml = os.path.join(BUDGET_DIR, "real0.05_synth0.yaml")
    if not os.path.isfile(ref_yaml):
        raise SystemExit(f"缺 {ref_yaml}")
    ref = open(ref_yaml, encoding="utf-8").read()
    val_dir = [ln.split(":", 1)[1].strip() for ln in ref.splitlines() if ln.startswith("val:")][0]
    test_dir = [ln.split(":", 1)[1].strip() for ln in ref.splitlines() if ln.startswith("test:")][0]
    real_yaml = write_yaml(os.path.join(BUDGET_DIR, "i20_real.yaml"), [REAL_LIST], val_dir, test_dir)
    synth_yaml = os.path.join(SYNTH_POOL, "dataset.yaml")
    if not os.path.isfile(synth_yaml):
        raise SystemExit(f"缺 {synth_yaml}")
    log(f"真实子集 {sum(1 for _ in open(REAL_LIST, encoding='utf-8'))} 张 | 合成池 {SYNTH_POOL}")

    from ultralytics import YOLO
    recs = {}
    if os.path.isfile(ART):
        try:
            recs = dict(json.load(open(ART, encoding="utf-8")).get("per_seed") or {})
        except Exception:
            recs = {}
    def paired(a_key, b_key):
        diffs = []
        for s, row in recs.items():
            if a_key in row and b_key in row:
                diffs.append((row[a_key]["map50"] - row[b_key]["map50"]) * 100.0)
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

    def _write(recs_):
        """写产物 ✓ —— **每个 seed 跑完就写一次** ✓ (中途被杀不丢 ✓)。"""
        rep_ = {"schema": "pretrain_finetune_arm/1",
                "generated_by": "pipelines/shelf_sdg/68_pretrain_finetune_arm.py",
                "measured_at": time.strftime("%Y-%m-%d"),
                "question": "合成数据当预训练、真实标注做微调, 能不能比只用真实标注更好?",
                "design": {
                    "arm": f"yolo11n -> 合成池 {PRETRAIN_EP} ep -> 真实子集 {FINETUNE_EP} ep",
                    "ctrl_a": f"yolo11n -> 只在真实子集上训 {CTRL_A_EP} ep (与臂的真实曝光相同)",
                    "ctrl_b": (f"yolo11n -> 只在真实子集上训 {CTRL_B_EP} ep "
                               f"(总步数比臂更多: 臂 1430 步 vs ctrl_b {CTRL_B_EP}x103 步 -> 更严格的对照)"),
                    "real_subset": REAL_LIST, "real_frac": REAL_FRAC,
                    "synth_pool": SYNTH_POOL, "train_cfg": TRAIN_CFG,
                    "eval": "SKU-110K test split (与所有臂同一份), last-vs-last",
                    "seeds": args.seeds},
                "per_seed": recs_}
        rep_["paired"] = {
            "arm_vs_ctrl_a": paired("arm_last", "ctrl_a_last"),
            "arm_vs_ctrl_b": paired("arm_last", "ctrl_b_last"),
            # **ctrl_b vs ctrl_a** = **真实标注的训练预算轴** (10 ep -> 20 ep) ✓
            # (README 里引用的那个数字就是这条 → 它必须由产物给出 ✓,
            #  不能手写或口头拼 ✓)
            "ctrl_b_vs_ctrl_a": paired("ctrl_b_last", "ctrl_a_last"),
        }
        # **P/R 分解** —— 用产物自己的数字判断"损害是怎么发生的" ✓:
        # 全部指标同步下降 = "整体变差" (与 I-17 的定义收窄、I-18 的整体保守不同✓);
        # 只降 recall = "定位减少" (模型不敢报→ 与 I-18 同类✓); 只降 precision = "报错了" ✓。
        for a_key, b_key, tag in (("arm_last", "ctrl_a_last", "arm_vs_ctrl_a"),
                                  ("arm_last", "ctrl_b_last", "arm_vs_ctrl_b")):
            decomp = {}
            for metric in ("map50", "map50_95", "precision", "recall"):
                diffs = []
                for _s, row in recs_.items():
                    if a_key in row and b_key in row:
                        diffs.append((row[a_key][metric] - row[b_key][metric]) * 100.0)
                if diffs:
                    decomp[metric] = {"n": len(diffs),
                                      "mean_pp": round(sum(diffs) / len(diffs), 4),
                                      "per_seed_pp": [round(d, 4) for d in diffs]}
            if decomp:
                rep_["paired"][tag + "_pr_decomposition"] = decomp
        with open(ART, "w", encoding="utf-8") as fh:
            json.dump(rep_, fh, ensure_ascii=False, indent=2)
        return rep_

    for seed in args.seeds:
        row = recs.get(str(seed)) or {}
        # --- 臂: 合成预训练 -> 真实微调 ---
        pre_run = os.path.join(BENCH, f"runs_pf_pre_s{seed}")
        pre_ck = os.path.join(pre_run, "train", "weights", "last.pt")
        if not os.path.isfile(pre_ck):
            YOLO("yolo11n.pt").train(data=synth_yaml, epochs=PRETRAIN_EP, seed=seed,
                                     project=pre_run, name="train", exist_ok=True,
                                     verbose=False, **TRAIN_CFG)
        ft_run = os.path.join(BENCH, f"runs_pf_ft_s{seed}")
        ft_ck = os.path.join(ft_run, "train", "weights", "last.pt")
        if not os.path.isfile(ft_ck):
            YOLO(pre_ck).train(data=real_yaml, epochs=FINETUNE_EP, seed=seed,
                               project=ft_run, name="train", exist_ok=True,
                               verbose=False, **TRAIN_CFG)
        row["arm_last"] = _eval_cached(ft_ck, real_yaml, f"s{seed}_arm")
        log(f"arm seed {seed}: 真实 test mAP50 = {row['arm_last']['map50']:.4f}")
        # --- 对照 A: 只在真实子集上训 10 ep (与臂的真实曝光相同) ---
        a_run = os.path.join(BENCH, f"runs_pf_ctrla_s{seed}")
        a_ck = os.path.join(a_run, "train", "weights", "last.pt")
        if not os.path.isfile(a_ck):
            YOLO("yolo11n.pt").train(data=real_yaml, epochs=CTRL_A_EP, seed=seed,
                                     project=a_run, name="train", exist_ok=True,
                                     verbose=False, **TRAIN_CFG)
        row["ctrl_a_last"] = _eval_cached(a_ck, real_yaml, f"s{seed}_ctrl_a")
        log(f"ctrl_a seed {seed}: 真实 test mAP50 = {row['ctrl_a_last']['map50']:.4f}")
        # --- 对照 B: 只在真实子集上训 20 ep (总步数比臂更多 -> 更严格的对照) ---
        b_run = os.path.join(BENCH, f"runs_pf_ctrlb_s{seed}")
        b_ck = os.path.join(b_run, "train", "weights", "last.pt")
        if not os.path.isfile(b_ck):
            YOLO("yolo11n.pt").train(data=real_yaml, epochs=CTRL_B_EP, seed=seed,
                                     project=b_run, name="train", exist_ok=True,
                                     verbose=False, **TRAIN_CFG)
        row["ctrl_b_last"] = _eval_cached(b_ck, real_yaml, f"s{seed}_ctrl_b")
        log(f"ctrl_b seed {seed}: 真实 test mAP50 = {row['ctrl_b_last']['map50']:.4f}")
        recs[str(seed)] = row
        _write(recs)          # 每个 seed 跑完就落盘 ✓ (中途被杀不丢 ✓)

    rep = _write(recs)
    for k, v in rep["paired"].items():
        if v:
            log(f"{k}: {v['mean_pp']:+.2f} pp, CI {v.get('ci95_pp')}")
    log(f"-> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
