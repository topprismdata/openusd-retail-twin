#!/usr/bin/env python
"""I-28 · 轮数轴的饱和点探针 (2026-11-28)。

**为什么做这个**: I-26 测出 "在真实标注上多训几轮" 是目前**唯一还没被否掉**的方向 ✓
(10->20 ep +3.60 pp ✓, 20->40 ep +2.38 pp ✓, CI 都整段在 0 以上 ✓), 但 40 轮处的
**验证 mAP 仍在涨** (0.7625 -> 0.7886 -> 0.8115 -> 0.8285 ✓) —— 也就是**不知道这个便宜的
杠杆在哪儿饱和** ✓。

**三种可能, 都有决策含义** ✓:
- 80 ep 继续涨 -> 结论: "训练预算这条杠杆还没到头" ✓ -> 真实标注的利用效率是**当前唯一
  有正收益的方向** ✓ (其余可调项全被实测否掉 ✓) -> 该把算力投在这里 ✓。
- 80 ep 与 40 ep 持平 (CI 跨 0) -> 结论: "40 轮是这条杠杆的饱和点" ✓ -> 再加轮数是浪费 ✓。
- 80 ep 掉分 -> 结论: "40 轮之后开始过拟合" ✓ -> 正好解释 I-26 的边际收益递减 ✓。

**探针先跑 1 个 seed** ✓ (约 96 min/seed ✓, 40 轮臂实测 2888 s ✓): 单 seed 的结果**只当
探针** ✓ (不写进结论 ✓) —— 但它足以区分上面三种情况 ✓ (40->80 的效应若是真的 +2 pp 量级,
单 seed 就看得出来 ✓; 若只差 0.3 pp 则需要更多 seed ✓ -> 到时再补 ✓)。

**协议**: 与 ctrl_c (I-26, 40 ep) **除 epochs 外逐项相同** ✓ (同一份真实子集 yaml ✓ /
同一份 test split ✓ / 同一组超参 ✓ / 同一 seed ✓) -> 配对差值 (ctrl_d - ctrl_c) ✓。
**不复用 40 轮的权重继续训** ✓ (那是"warm restart" ✓, 轨迹与"从头训 80 轮"不是一回事 ✓),
所以这是**干净的新臂** ✓, 代价是 2 倍算力 ✓。
"""
import csv
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402  (全仓唯一的 CI 实现 ✓)

BENCH = os.path.join(BASE, "output", "benchmark")
BUDGET_DIR = os.path.join(BENCH, "budget")
REAL_YAML = os.path.join(BUDGET_DIR, "i20_real.yaml")
C26_ART = os.path.join(BENCH, "real_budget_epoch_arm.json")     # ctrl_c (40 ep) ✓
LOG = os.path.join(BENCH, "epoch_saturation_probe.log")
ART = os.path.join(BENCH, "epoch_saturation_probe.json")
RUN_TMPL = os.path.join(BENCH, "runs_pf_ctrld_s{seed}")
CTRL_C_RUN_TMPL = os.path.join(BENCH, "runs_pf_ctrlc_s{seed}")
TRAIN_CFG = dict(imgsz=640, batch=4, workers=2, device="0",
                 pretrained=True, optimizer="auto", close_mosaic=10)
EP = 80          # 轮数轴的下一档 ✓ (ctrl_c = 40 ✓)


def log(m):
    line = f"[ESP {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def trajectory(run_dir):
    """从 results.csv 抽 **逐轮验证 mAP 轨迹** ✓ (数字是训练自己写的 ✓, 不是手抄 ✓)"""
    f = os.path.join(run_dir, "train", "results.csv")
    if not os.path.isfile(f):
        return None
    eps, val_map, losses = [], [], []
    with open(f, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            e = row.get("epoch")
            m = row.get("metrics/mAP50(B)")
            if e is None or m in (None, ""):
                continue
            eps.append(int(float(e)) + 1)
            val_map.append(float(m))
            losses.append(float(row.get("train/box_loss") or 0.0))
    out = {"epochs": eps, "val_map50": val_map, "train_box_loss": losses,
           "n_epochs_done": len(eps)}
    # **平台的量化** ✓: 末 10 轮的平均验证 mAP + 最好轮次 ✓
    #   -> "还在涨" vs "已经平了" 可以直接读数 ✓ (不用肉眼看曲线 ✓)
    if val_map:
        tail = val_map[-10:]
        out["val_map50_last10_mean"] = round(sum(tail) / len(tail), 5)
        out["val_map50_best"] = max(val_map)
        out["val_map50_best_epoch"] = eps[val_map.index(max(val_map))]
        out["val_map50_last_minus_best"] = round(val_map[-1] - max(val_map), 5)
    return out


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
    ap.add_argument("--seeds", type=int, nargs="*", default=[43])
    ap.add_argument("--epochs", type=int, default=EP)
    args = ap.parse_args()

    if not os.path.isfile(REAL_YAML):
        raise SystemExit(f"缺 {REAL_YAML} —— 先跑 68 号生成真实子集 yaml")
    ctrl_c = {}
    if os.path.isfile(C26_ART):
        for s, row in (json.load(open(C26_ART, encoding="utf-8")).get("per_seed") or {}).items():
            if row.get("ctrl_c_last"):
                ctrl_c[s] = row["ctrl_c_last"]
    if not ctrl_c:
        raise SystemExit("缺 I-26 产物 (ctrl_c 40 ep 的基线数字) —— 先跑 73 号")

    from ultralytics import YOLO
    recs = {}
    if os.path.isfile(ART):
        try:
            recs = dict(json.load(open(ART, encoding="utf-8")).get("per_seed") or {})
        except Exception:
            recs = {}

    def _write():
        rep = {"schema": "epoch_saturation_probe/1",
               "generated_by": "pipelines/shelf_sdg/81_epoch_saturation_probe.py",
               "measured_at": time.strftime("%Y-%m-%d"),
               "question": "真实标注的训练轮数轴在 40 ep 之后还在涨吗 (便宜的杠杆在哪儿饱和)?",
               "design": {
                   "arm_ctrl_d": f"yolo11n -> 只在真实子集上训 {args.epochs} ep (与 ctrl_c 除 epochs 外逐项相同 ✓)",
                   "baseline_ctrl_c": "yolo11n -> 只在真实子集上训 40 ep (I-26 产物 ✓, 同一份 test split ✓)",
                   "real_subset": os.path.join(BUDGET_DIR, "real0.05_synth0_real.txt"),
                   "real_frac": 0.05, "train_cfg": TRAIN_CFG, "epochs": args.epochs,
                   "eval": "SKU-110K test split (与所有臂同一份), last-vs-last",
                   "seeds": args.seeds,
                   "probe_note": ("单 seed 的结果是**探针** ✓ (用来区分涨/平/跌三种情况 ✓), "
                                  "不作为结论 ✓; 需要成结论时再补 seed ✓")},
               "per_seed": recs}
        diffs = []
        for s, row in sorted(recs.items()):
            if row.get("ctrl_d_last") and ctrl_c.get(s):
                diffs.append((row["ctrl_d_last"]["map50"] - ctrl_c[s]["map50"]) * 100.0)
        if diffs:
            mean, lo, hi = ci95_t(diffs)
            rep["paired_ctrl_d_vs_ctrl_c"] = {
                "n": len(diffs), "mean_pp": round(mean, 4),
                "per_seed_pp": [round(d, 4) for d in diffs],
                "ci95_pp": [round(lo, 4), round(hi, 4)],
                "ci_excludes_zero": bool(lo > 0 or hi < 0),
                "verdict": ("显著为正" if lo > 0 else "显著为负" if hi < 0 else "未检出差异")}
        with open(ART, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        return rep

    for seed in args.seeds:
        row = recs.get(str(seed)) or {}
        if "ctrl_c_last" not in row and str(seed) in ctrl_c:
            row["ctrl_c_last"] = ctrl_c[str(seed)]
        run = RUN_TMPL.format(seed=seed)
        ck = os.path.join(run, "train", "weights", "last.pt")
        last = os.path.join(run, "train", "weights", "last.pt")
        res = os.path.join(run, "train", "results.csv")
        done = 0
        if os.path.isfile(res):
            with open(res, encoding="utf-8") as fh:
                done = max(0, sum(1 for _ in fh) - 1)
        if not os.path.isfile(ck) or done < args.epochs:
            if os.path.isfile(last) and 0 < done < args.epochs:
                # **断点续训** ✓ (一轮 ~96 min ✓, 被杀就重来太贵 ✓)
                log(f"ctrl_d seed {seed}: 续训 (已跑 {done}/{args.epochs} ep)")
                YOLO(last).train(resume=True, verbose=False)
            else:
                log(f"ctrl_d seed {seed}: 开训 {args.epochs} ep (预计 ~{args.epochs * 72 // 60} min)")
                YOLO("yolo11n.pt").train(data=REAL_YAML, epochs=args.epochs, seed=seed,
                                         project=run, name="train", exist_ok=True,
                                         verbose=False, **TRAIN_CFG)
        row["ctrl_d_last"] = _eval(ck, REAL_YAML)
        row["traj_ctrl_d"] = trajectory(run)
        row["traj_ctrl_c"] = trajectory(CTRL_C_RUN_TMPL.format(seed=seed))
        row["actual_train_config"] = {
            "epochs_requested": args.epochs,
            "epochs_done": (row["traj_ctrl_d"] or {}).get("n_epochs_done"),
            "data": REAL_YAML, "seed": seed, **TRAIN_CFG}
        base = ctrl_c.get(str(seed)) or {}
        if base:
            log(f"ctrl_d seed {seed}: test mAP50 = {row['ctrl_d_last']['map50']:.4f} "
                f"(ctrl_c 40ep = {base['map50']:.4f}, "
                f"Δ = {(row['ctrl_d_last']['map50'] - base['map50']) * 100:+.2f} pp)")
        recs[str(seed)] = row
        _write()          # 每个 seed 跑完就落盘 ✓ (中途被杀不丢 ✓)

    rep = _write()
    log(f"-> {ART}")
    if "paired_ctrl_d_vs_ctrl_c" in rep:
        p = rep["paired_ctrl_d_vs_ctrl_c"]
        log(f"ctrl_d vs ctrl_c: {p['mean_pp']:+.2f} pp, CI {p.get('ci95_pp')}, {p.get('verdict')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
