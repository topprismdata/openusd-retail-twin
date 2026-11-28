#!/usr/bin/env python
"""I-26 ·「真实标注怎么用」的两条尾巴臂 (2026-11-27)。

I-20 的结果 (3 seed ✓): 合成预训练 + 真实微调 (分工臂) 比**真实曝光相同**的纯真实
对照**低 2.01 pp** (CI [-3.41, -0.60] ✓, 3/3 seed 全负 ✓) -> "分工路线"被否 ✓。
这条负结果留下两个必须答的问题, 本脚本同时测:

  A. **合成先验能不能被更多真实轮数洗掉** (arm_wash)
     arm_wash = yolo11n -> 合成池预训练 10 ep -> **真实子集 20 ep** (复用 I-20 已
     训好的预训练权重 ✓, 不重训 ✓)
     对照 = ctrl_b = 只在真实子集上训 20 ep (真实曝光**逐项相同** ✓, 总步数还少
     400 步 ✓ -> 更严格的对照 ✓)
     * arm_wash >= ctrl_b -> 合成先验在**足量真实预算**下是无害的 (甚至有用 ✓)
       -> I-20 的负结果只是"真实预算不够洗掉它" ✓ (该改的是微调轮数, 不是路线 ✓)
     * arm_wash <  ctrl_b -> 合成预训练**永久**把商品定义带偏 ✓ -> 分工路线彻底封死 ✓

  B. **真实标注的训练轮数轴** (ctrl_c)
     ctrl_c = 只在真实子集上训 **40 ep** (与 ctrl_b 的 20 ep 同一条轴 ✓)
     -> 411 张真实图能靠"多训"补回多少缺口 ✓ (这是**最便宜**的一条杠杆 ✓)
     -> 参照: 5% 真实 10 ep = 0.7946 ✓ / 20 ep = 0.8199 ✓ / 全量真实 10 ep = 0.8862 ✓

口径 (逐项与 I-20 相同 ✓): 真实子集 = 5% 预算的 411 张 (同一份名单 ✓); 训练配方 =
imgsz 640 / batch 4 / workers 2 / pretrained / optimizer auto / close_mosaic 10 ✓;
评测 = SKU-110K test split (与所有臂同一份 ✓); **last-vs-last** ✓; 逐 seed 配对 ✓。

用法:
    python pipelines/shelf_sdg/73_real_budget_epoch_arm.py --arms wash ctrl_c --seeds 43 44 45
产物:
    output/benchmark/real_budget_epoch_arm.json
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
REAL_YAML = os.path.join(BUDGET_DIR, "i20_real.yaml")     # I-20 生成的真实子集 yaml ✓
PRE_DIR = "runs_pf_pre_s{seed}"                           # I-20 的合成预训练权重 ✓
LOG = os.path.join(BENCH, "real_budget_epoch_arm.log")
ART = os.path.join(BENCH, "real_budget_epoch_arm.json")
PF_ART = os.path.join(BENCH, "pretrain_finetune_arm.json")   # ctrl_b 的数字从这取 ✓
SEEDS = [43, 44, 45]
TRAIN_CFG = dict(imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)
WASH_EP = 20      # arm_wash 的真实微调轮数 = ctrl_b 的真实轮数 ✓
CTRL_C_EP = 40    # ctrl_c 的真实轮数 (轮数轴的下一档 ✓)


def log(m):
    line = f"[RBE {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def paired(a_key, b_key, recs):
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


EVAL_CACHE = os.path.join(BENCH, "rbe_arm_eval_cache.json")


def _cache_load():
    try:
        return json.load(open(EVAL_CACHE, encoding="utf-8"))
    except Exception:
        return {}


def _cache_save(c):
    with open(EVAL_CACHE, "w", encoding="utf-8") as fh:
        json.dump(c, fh, ensure_ascii=False, indent=2)


def _eval_cached(ckpt, yaml, key):
    """评测并缓存 ✓ —— 断点续跑时不必重跑 GPU 评测 ✓
    (每个模型的评测要 3~5 min ✓, 中途被杀重跑很紵 ✓)"""
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
    ap.add_argument("--arms", nargs="*", default=["wash", "ctrl_c"])
    ap.add_argument("--seeds", type=int, nargs="*", default=SEEDS)
    args = ap.parse_args()

    if not os.path.isfile(REAL_YAML):
        raise SystemExit(f"缺 {REAL_YAML} —— 先跑 68 号生成真实子集 yaml")
    # ctrl_b 的数字: 复用 I-20 的产物 (权重与 yaml 都同一份 ✓), 不重评 ✓
    ctrl_b = {}
    if os.path.isfile(PF_ART):
        for s, row in (json.load(open(PF_ART, encoding="utf-8")).get("per_seed") or {}).items():
            if row.get("ctrl_b_last"):
                ctrl_b[s] = row["ctrl_b_last"]

    from ultralytics import YOLO
    recs = {}
    if os.path.isfile(ART):
        try:
            recs = dict(json.load(open(ART, encoding="utf-8")).get("per_seed") or {})
        except Exception:
            recs = {}

    def _write():
        rep = {"schema": "real_budget_epoch_arm/1",
               "generated_by": "pipelines/shelf_sdg/73_real_budget_epoch_arm.py",
               "measured_at": time.strftime("%Y-%m-%d"),
               "question": ("合成先验能否被更多真实轮数洗掉? 真实标注的训练轮数轴能补回多少缺口?"),
               "design": {
                   "arm_wash": (f"yolo11n -> 合成池预训练 10 ep -> 真实子集 {WASH_EP} ep "
                                f"(复用 I-20 的预训练权重 ✓)"),
                   "ctrl_b": f"yolo11n -> 只在真实子集上训 20 ep (真实曝光与 arm_wash 相同 ✓, 数字取自 I-20 产物 ✓)",
                   "ctrl_c": f"yolo11n -> 只在真实子集上训 {CTRL_C_EP} ep (轮数轴的下一档 ✓)",
                   "real_subset": os.path.join(BUDGET_DIR, "real0.05_synth0_real.txt"),
                   "real_frac": 0.05, "train_cfg": TRAIN_CFG,
                   "eval": "SKU-110K test split (与所有臂同一份), last-vs-last",
                   "seeds": args.seeds},
               "per_seed": recs}
        rep["paired"] = {
            "wash_vs_ctrl_b": paired("wash_last", "ctrl_b_last", recs),
            "ctrl_c_vs_ctrl_b": paired("ctrl_c_last", "ctrl_b_last", recs),
        }
        with open(ART, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        return rep

    for seed in args.seeds:
        row = recs.get(str(seed)) or {}
        if "ctrl_b_last" not in row and str(seed) in ctrl_b:
            row["ctrl_b_last"] = ctrl_b[str(seed)]

        if "wash" in args.arms:
            pre_ck = os.path.join(BENCH, PRE_DIR.format(seed=seed), "train", "weights", "last.pt")
            if not os.path.isfile(pre_ck):
                raise SystemExit(f"缺预训练权重 {pre_ck} —— 先跑 68 号 (I-20)")
            run = os.path.join(BENCH, f"runs_pf_wash_s{seed}")
            ck = os.path.join(run, "train", "weights", "last.pt")
            if not os.path.isfile(ck):
                YOLO(pre_ck).train(data=REAL_YAML, epochs=WASH_EP, seed=seed,
                                   project=run, name="train", exist_ok=True,
                                   verbose=False, **TRAIN_CFG)
            row["wash_last"] = _eval_cached(ck, REAL_YAML, f"s{seed}_wash")
            log(f"arm_wash seed {seed}: 真实 test mAP50 = {row['wash_last']['map50']:.4f}")

        if "ctrl_c" in args.arms:
            run = os.path.join(BENCH, f"runs_pf_ctrlc_s{seed}")
            ck = os.path.join(run, "train", "weights", "last.pt")
            if not os.path.isfile(ck):
                YOLO("yolo11n.pt").train(data=REAL_YAML, epochs=CTRL_C_EP, seed=seed,
                                         project=run, name="train", exist_ok=True,
                                         verbose=False, **TRAIN_CFG)
            row["ctrl_c_last"] = _eval_cached(ck, REAL_YAML, f"s{seed}_ctrl_c")
            log(f"ctrl_c seed {seed}: 真实 test mAP50 = {row['ctrl_c_last']['map50']:.4f}")

        recs[str(seed)] = row
        _write()          # 每个 seed 跑完就落盘 ✓ (中途被杀不丢 ✓)

    rep = _write()
    for k, v in rep["paired"].items():
        if v:
            log(f"{k}: {v['mean_pp']:+.2f} pp, CI {v.get('ci95_pp')}")
    log(f"-> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
