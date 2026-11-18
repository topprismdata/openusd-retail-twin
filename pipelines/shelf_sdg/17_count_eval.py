#!/usr/bin/env python3
"""四臂计数业务指标 (shelf-monitor 口径): 每测试图预测 facings 数 vs 真值数。

真值: /opt/homebrew/datasets/SKU-110K/annotations/annotations_test.csv (image,x1,y1,x2,y2,...)
预测: 各臂 best.pt 在 test 前 600 图 (conf 0.35, max_det 1000)
输出: output/benchmark/count_<arm>.json {mae, mape, pearson_r, n_images}
用法: python3 17_count_eval.py --arm r0
"""
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
ROOT = "/opt/homebrew/datasets/SKU-110K"
N_EVAL = 600
CONF = 0.35


def gt_counts():
    per = defaultdict(int)
    with open(os.path.join(ROOT, "annotations", "annotations_test.csv")) as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("image"):
                continue
            per[os.path.basename(row[0])] += 1
    return per


def main():
    arm = sys.argv[sys.argv.index("--arm") + 1] if "--arm" in sys.argv else "r0"
    from ultralytics import YOLO
    w = os.path.join(BENCH, f"runs_{arm}", "train", "weights", "best.pt")
    if arm == "r0" and not os.path.exists(w):
        w = os.path.join(BENCH, "runs_r0", "train", "weights", "best.pt")
    model = YOLO(w)
    gt = gt_counts()
    names = sorted(gt)[:N_EVAL]
    imgs = [os.path.join(ROOT, "images", n) for n in names]
    preds = model.predict(imgs, conf=CONF, max_det=1000, device="mps", verbose=False)
    pc = [len(p.boxes) for p in preds]
    gc = [gt[n] for n in names]
    pc_a, gc_a = np.asarray(pc, float), np.asarray(gc, float)
    mae = float(np.abs(pc_a - gc_a).mean())
    mape = float((np.abs(pc_a - gc_a) / np.maximum(1, gc_a)).mean() * 100)
    r = float(np.corrcoef(pc_a, gc_a)[0, 1]) if pc_a.std() > 0 and gc_a.std() > 0 else 0.0
    rep = {"arm": arm, "n_images": len(names), "conf": CONF,
           "count_mae": round(mae, 2), "count_mape_pct": round(mape, 2),
           "pearson_r": round(r, 3),
           "mean_pred": round(float(pc_a.mean()), 1), "mean_gt": round(float(gc_a.mean()), 1)}
    json.dump(rep, open(os.path.join(BENCH, f"count_{arm}.json"), "w"), indent=2)
    print(f"[COUNT] {arm} MAE={rep['count_mae']} MAPE={rep['count_mape_pct']}% r={rep['pearson_r']} "
          f"(pred {rep['mean_pred']} vs gt {rep['mean_gt']})")


if __name__ == "__main__":
    main()
