#!/usr/bin/env python3
"""P2 代理验收: 在 shelfwise SKUs_on_shelves_PL (CC-BY-4.0, 真实门店货架) 上评我们的模型。

数据在外部盘: 用环境变量 `SKUPL_ROOT` 指向 SKUs_on_shelves_PL 解压后的目录 (COCO 格式)
流程: COCO json -> YOLO 目录 (单类 product, 折叠所有 SKU 类) -> 用 R0/R2 best.pt 评 mAP + 计数指标
产出: output/benchmark/p2_proxy_<arm>.json
用法: export SKUPL_ROOT=/Volumes/<disk>/datasets/SKUs_on_shelves_PL
      python3 20_p2_pl_eval.py --arm r0 [--limit 2000]
"""
import json
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PL = os.environ.get("SKUPL_ROOT", "").strip()
if not PL:
    raise SystemExit(
        "[P2] 缺环境变量 SKUPL_ROOT —— 指向 SKUs_on_shelves_PL 解压后的根目录 "
        "(含 COCO json), 例如:\n"
        '    export SKUPL_ROOT="/Volumes/<disk>/datasets/SKUs_on_shelves_PL"')


def find_coco():
    for root, _d, files in os.walk(PL):
        for f in files:
            if f.endswith(".json") and "coco" in f.lower():
                return os.path.join(root, f)
        for f in files:
            if f == "annotations.json" or f.endswith("_annotations.json"):
                return os.path.join(root, f)
    return None


def coco_to_yolo(coco_path, out_dir, limit):
    coco = json.load(open(coco_path))
    imgs = {i["id"]: i for i in coco["images"]}
    per = {}
    for a in coco["annotations"]:
        if a.get("iscrowd"):
            continue
        per.setdefault(a["image_id"], []).append(a)
    os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "labels"), exist_ok=True)
    n = 0
    for iid, anns in per.items():
        if limit and n >= limit:
            break
        img = imgs[iid]
        w, h = img["width"], img["height"]
        fn = os.path.splitext(os.path.basename(img["file_name"]))[0]
        src = os.path.join(os.path.dirname(coco_path), img["file_name"])
        if not os.path.exists(src):
            cand = os.path.join(PL, "images", os.path.basename(img["file_name"]))
            src = cand if os.path.exists(cand) else None
        if not src:
            continue
        lines = []
        for a in anns:
            x, y, bw, bh = a["bbox"]
            cx, cy = (x + bw / 2) / w, (y + bh / 2) / h
            lines.append(f"0 {cx:.5f} {cy:.5f} {bw / w:.5f} {bh / h:.5f}")
        if not lines:
            continue
        with open(os.path.join(out_dir, "labels", fn + ".txt"), "w") as f:
            f.write("\n".join(lines))
        with open(os.path.join(out_dir, "images", fn + ".txt"), "w") as f:
            f.write(src)          # 路径清单, 评测时按需读图 (不复制 10GB 图)
        n += 1
    return n


def main():
    arm = sys.argv[sys.argv.index("--arm") + 1] if "--arm" in sys.argv else "r0"
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 2000
    coco_path = find_coco()
    if not coco_path:
        raise SystemExit(f"[P2] 未找到 COCO json under {PL} (zip 解压完成?)")
    out = os.path.join(BENCH, "pl_yolo")
    n = coco_to_yolo(coco_path, out, limit)
    print(f"[P2] converted {n} images from {coco_path}")

    from ultralytics import YOLO
    w = os.path.join(BENCH, f"runs_{arm}", "train", "weights", "best.pt")
    model = YOLO(w)
    # 逐图预测 (路径清单), 计 mAP@0.5 近似: 用 gt 框做 IoU0.5 匹配召回/精度 + 计数指标
    import cv2
    preds, gts = [], []
    counts_p, counts_g = [], []
    for lf in sorted(os.listdir(os.path.join(out, "labels"))):
        if not lf.endswith(".txt"):
            continue
        src = open(os.path.join(out, "images", lf)).read().strip()
        gt = np.loadtxt(os.path.join(out, "labels", lf), ndmin=2)[:, 1:5]
        img = cv2.imread(src)
        if img is None:
            continue
        r = model.predict(img, conf=0.35, max_det=1000, verbose=False)[0]
        pb = r.boxes.xyxy.cpu().numpy() if len(r.boxes) else np.zeros((0, 4))
        counts_p.append(len(pb))
        counts_g.append(len(gt))
        # gt 为归一化 cxcywh -> xyxy 像素
        H, W = img.shape[:2]
        gb = []
        for cx, cy, bw, bh in gt:
            gb.append([ (cx - bw / 2) * W, (cy - bh / 2) * H, (cx + bw / 2) * W, (cy + bh / 2) * H ])
        gb = np.asarray(gb).reshape(-1, 4)
        preds.append(pb)
        gts.append(gb)

    def iou_matrix(a, b):
        xa = np.maximum(a[:, None, 0], b[None, :, 0])
        ya = np.maximum(a[:, None, 1], b[None, :, 1])
        xb = np.minimum(a[:, None, 2], b[None, :, 2])
        yb = np.minimum(a[:, None, 3], b[None, :, 3])
        inter = np.clip(xb - xa, 0, None) * np.clip(yb - ya, 0, None)
        aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
        bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
        return inter / np.maximum(1, aa[:, None] + bb[None, :] - inter)

    tp = fp = fn = 0
    for pb, gb in zip(preds, gts):
        if len(pb) and len(gb):
            m = iou_matrix(pb, gb)
            used = set()
            for i in range(len(pb)):
                j = int(np.argmax(m[i])) if m[i].max() >= 0.5 else -1
                if j >= 0 and j not in used:
                    tp += 1
                    used.add(j)
                else:
                    fp += 1
            fn += len(gb) - len(used)
        else:
            fp += len(pb)
            fn += len(gb)
    prec = tp / max(1, tp + fp)
    rec = tp / max(1, tp + fn)
    cp, cg = np.asarray(counts_p, float), np.asarray(counts_g, float)
    rep = {
        "source": "shelfwise-by-form/SKUs_on_shelves_PL (CC-BY-4.0)",
        "arm": arm, "n_images": len(preds),
        "precision@0.5": round(float(prec), 3), "recall@0.5": round(float(rec), 3),
        "f1@0.5": round(2 * prec * rec / max(1e-9, prec + rec), 3),
        "count_mae": round(float(np.abs(cp - cg).mean()), 2),
        "count_mape_pct": round(float((np.abs(cp - cg) / np.maximum(1, cg)).mean() * 100), 2),
        "pearson_r": round(float(np.corrcoef(cp, cg)[0, 1]), 3) if cp.std() > 0 and cg.std() > 0 else 0.0,
    }
    json.dump(rep, open(os.path.join(BENCH, f"p2_proxy_{arm}.json"), "w"), indent=2)
    print("[P2]", json.dumps(rep, ensure_ascii=False))


if __name__ == "__main__":
    main()
