#!/usr/bin/env python3
"""逐图配对评测 (2026-11-21, 审计行动 8: 让显著性可判定)。

动机: 训练侧的 seed 方差只是噪声的一部分; 真正的检验对象是**评测集** —— 同一个 test 集上,
两个模型 (加合成 vs 不加合成) 到底差多少, 能不能与逐图波动区分开。做法:
对两个模型**逐图**算 AP@0.5 (101 点插值, 与 COCO eval 同口径), 再做配对统计
(逐图差值的均值/标准差/t 值 + 胜/负张数)。

这比"多跑几个 seed"检验力高得多: n = 评测图数 (2,935), 而不是 n = 3~5。

用法:
  python3 25_paired_image_eval.py --weights-a A.pt --weights-b B.pt --label-a "无合成" --label-b "+160 合成"

写: output/benchmark/paired_image_eval_<tag>.{json,md}
"""
import argparse
import json
import os

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "output", "benchmark")
IMG_EXT = (".jpg", ".jpeg", ".png")


# ------------------------------------------------------------------ GT / IO


def load_test_gt(root, split="test"):
    """→ {stem: [ (x1,y1,x2,y2) pixels ]}

    归一化标签 → 像素坐标必须用**每张图自己的分辨率** (SKU-110K 是混合分辨率:
    480×640 / 720×1280 / 1152×1920), 否则 IoU 全错。
    """
    from PIL import Image
    label_dir = os.path.join(root, "labels")
    stems = []
    split_file = os.path.join(root, f"{split}.txt")
    if os.path.exists(split_file):
        with open(split_file, encoding="utf-8") as f:
            for ln in f:
                if not ln.strip():
                    continue
                base = ln.strip().split()[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                for e in IMG_EXT:
                    if base.lower().endswith(e):
                        base = base[:-len(e)]
                        break
                stems.append(base)
    else:
        stems = [f[:-4] for f in os.listdir(label_dir) if f.startswith(split + "_")]
    gt = {}
    for stem in stems:
        ip = image_path(root, stem)
        if ip is None:
            continue
        try:
            with Image.open(ip) as im:
                W, H = im.size
        except Exception:
            continue
        p = os.path.join(label_dir, stem + ".txt")
        boxes = []
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                for ln in f:
                    q = ln.split()
                    if len(q) < 5:
                        continue
                    cx, cy, w, h = map(float, q[1:5])
                    boxes.append([(cx - w / 2) * W, (cy - h / 2) * H,
                                  (cx + w / 2) * W, (cy + h / 2) * H])
        gt[stem] = boxes
    return gt


def image_path(root, stem):
    for e in IMG_EXT:
        p = os.path.join(root, "images", stem + e)
        if os.path.exists(p):
            return p
    return None


# ------------------------------------------------------------------ AP


def iou_matrix(a, b):
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    area_a = (a[:, 2] - a[:, 0]).clip(0) * (a[:, 3] - a[:, 1]).clip(0)
    area_b = (b[:, 2] - b[:, 0]).clip(0) * (b[:, 3] - b[:, 1]).clip(0)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = (rb - lt).clip(0)
    inter = wh[..., 0] * wh[..., 1]
    union = area_a[:, None] + area_b[None, :] - inter
    return np.where(union > 0, inter / np.maximum(union, 1e-9), 0.0)


def _greedy_match(boxes, gts, iou_thr=0.5):
    """按 score 降序贪心匹配 (每个 GT 最多命中一次) → tp 布尔数组 (按传入顺序)。"""
    n_pred, n_gt = len(boxes), len(gts)
    if n_pred == 0:
        return np.zeros(0, dtype=bool)
    if n_gt == 0:
        return np.zeros(n_pred, dtype=bool)
    ious = iou_matrix(boxes, gts)
    used = np.zeros(n_gt, dtype=bool)
    tp = np.zeros(n_pred, dtype=bool)
    for i in range(n_pred):
        cand = ious[i].copy()
        cand[used] = -1.0
        j = int(np.argmax(cand))
        if cand[j] > iou_thr:
            used[j] = True
            tp[i] = True
    return tp


def ap_101(boxes, scores, gts, iou_thr=0.5):
    """单图 AP@0.5 (101 点插值, 与 COCO eval 同口径)。"""
    n_gt = len(gts)
    if n_gt == 0:
        return None
    if len(boxes) == 0:
        return 0.0
    order = np.argsort(-np.asarray(scores))
    boxes = np.asarray(boxes, dtype=float)[order]
    tp = _greedy_match(boxes, gts, iou_thr)
    return _pr_to_ap(np.cumsum(tp.astype(float)), np.cumsum((~tp).astype(float)), n_gt)


def _pr_to_ap(ctp, cfp, n_gt):
    rec = ctp / max(n_gt, 1)
    prec = ctp / np.maximum(ctp + cfp, 1e-9)
    mpre = np.concatenate([[0.0], prec, [0.0]])
    mrec = np.concatenate([[0.0], rec, [1.0]])
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    thresholds = np.linspace(0, 1, 101)
    aps = []
    for t in thresholds:
        idx = np.where(mrec >= t)[0]
        aps.append(mpre[idx[0]] if len(idx) else 0.0)
    return float(np.mean(aps))


def pooled_ap(per_image, gt, stems, iou_thr=0.5):
    """数据集级 AP@0.5 (所有图的所有检测按置信度全局排序后统一匹配) —— 与 ultralytics
    报告的 mAP@0.5 同一口径, 用于**校验**本脚本的逐图 AP 实现没有算错。

    贪心匹配的等价实现: 每张图内部按全局分数顺序处理该图的检测 (图间互不影响),
    最后把所有 (分数, tp) 汇总按分数降序累加 —— 与全局贪心一致。
    """
    all_sc, all_tp = [], []
    for s in stems:
        boxes, scores = per_image.get(s, ([], []))
        if not boxes:
            continue
        order = np.argsort(-np.asarray(scores, dtype=float))
        b = np.asarray(boxes, dtype=float)[order]
        sc = np.asarray(scores, dtype=float)[order]
        tp = _greedy_match(b, gt.get(s, []), iou_thr)
        all_sc.append(sc)
        all_tp.append(tp.astype(float))
    if not all_sc:
        return 0.0
    sc = np.concatenate(all_sc)
    tp = np.concatenate(all_tp)
    order = np.argsort(-sc)
    tp = tp[order]
    n_gt_total = sum(len(gt[s]) for s in stems)
    return _pr_to_ap(np.cumsum(tp), np.cumsum(1.0 - tp), n_gt_total)


# ------------------------------------------------------------------ 推理


def predict_per_image(model, root, stems, batch=16, conf=0.001, iou=0.7, max_det=1000,
                      chunk=500, yaml=None, split="test", project=None, name="val"):
    """逐图检测框。

    2026-11-21: 改用 **ultralytics 的 val + save_json** 而不是 `predict(list_of_paths)`:
    - predict 收到路径列表会 `autocast_list` **一次性把几千张图读进内存** (GB 级),
      并且遇到那张截断的 test 图直接抛 OSError 整个调用失败 (实测: 32 分钟白跑);
    - val 走 DataLoader (多进程加载 + 磁盘流式), 会像已发布的评测一样跳过坏图,
      并额外导出 COCO 格式的逐图检测 (image_id + bbox + score) —— 这正是逐图 AP 需要的。

    仍保留 predict 路径作为无 yaml 时的回退 (只适合小样本冒烟)。
    """
    if yaml:
        return _predict_via_val(model, yaml, split, project, name)
    paths = [image_path(root, s) for s in stems]
    keep = [(s, p) for s, p in zip(stems, paths) if p]
    out = {}
    for start in range(0, len(keep), chunk):
        part = keep[start:start + chunk]
        res = model.predict(source=[p for _, p in part], batch=batch, conf=conf, iou=iou,
                            max_det=max_det, stream=True, verbose=False, device=0)
        for (stem, _), r in zip(part, res):
            b = r.boxes
            if b is None or len(b) == 0:
                out[stem] = ([], [])
                continue
            xyxy = b.xyxy.cpu().numpy()
            sc = b.conf.cpu().numpy()
            out[stem] = (xyxy.tolist(), sc.tolist())
        print(f"[PAIRED]   推理进度 {min(start+chunk, len(keep))}/{len(keep)}", flush=True)
    return out


def _predict_via_val(model, yaml, split, project, name):
    """val(save_json=True) → 逐图检测 {stem: (boxes_xyxy, scores)}。"""
    import glob
    project = project or os.path.join(OUT, "_paired_val")
    model.val(data=yaml, split=split, imgsz=640, device=0, max_det=1000,
              project=project, name=name, exist_ok=True, save_json=True,
              verbose=False)
    js = sorted(glob.glob(os.path.join(project, name, "*.json")))
    if not js:
        raise RuntimeError(f"[PAIRED] val 没有导出 json (目录 {os.path.join(project, name)})")
    dets = {}
    with open(js[0], encoding="utf-8") as f:
        for rec in json.load(f):
            stem = str(rec["image_id"])
            x, y, w, h = rec["bbox"]
            dets.setdefault(stem, ([], []))
            dets[stem][0].append([x, y, x + w, y + h])
            dets[stem][1].append(float(rec["score"]))
    print(f"[PAIRED]   导出 {len(dets)} 张图的检测 (来自 {os.path.basename(js[0])})", flush=True)
    return dets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights-a", required=True)
    ap.add_argument("--weights-b", required=True)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    ap.add_argument("--tag", default="")
    ap.add_argument("--root", default=os.environ.get("SKU110K_ROOT", ""))
    ap.add_argument("--split", default="test")
    ap.add_argument("--limit", type=int, default=0, help="只取前 N 张 (冒烟用; 0=全部)")
    ap.add_argument("--yaml", default=os.environ.get("SKU110K_YAML", ""),
                    help="评测 yaml (给了就走 val+save_json 路径, 推荐)")
    args = ap.parse_args()
    root = args.root.strip()
    if not root:
        raise SystemExit(
            "[PAIRED] 缺数据集根 —— 用 --root 或环境变量 SKU110K_ROOT 指定 "
            "(含 images/ 与 labels/), 例如:\n"
            '            export SKU110K_ROOT="/data/SKU-110K"')
    tag = args.tag or f"{args.label_a.replace(' ', '_')}_vs_{args.label_b.replace(' ', '_')}"

    gt = load_test_gt(root, args.split)
    stems = [s for s in sorted(gt) if image_path(root, s)]
    if args.limit:
        stems = stems[:args.limit]
    print(f"[PAIRED] test 图 {len(stems)} 张, GT 框 {sum(len(gt[s]) for s in stems)}")

    from ultralytics import YOLO
    per = {}
    for w, lab in ((args.weights_a, args.label_a), (args.weights_b, args.label_b)):
        print(f"[PAIRED] 推理 {lab}: {w}")
        model = YOLO(w)
        dets = predict_per_image(model, root, stems,
                                  yaml=(args.yaml or None),
                                  project=os.path.join(OUT, "_paired_val"),
                                  name="val_" + lab.replace(" ", "_").replace("+", "plus"))
        # 只保留在 stems 里的图 (val 会跳过坏图 → 那些图没有检测结果)
        per[lab] = {s: dets.get(s, ([], [])) for s in stems}

    aps = {}
    pooled = {}
    for lab in per:
        vals = []
        for s in stems:
            boxes, scores = per[lab][s]
            a = ap_101(boxes, scores, gt[s])
            if a is not None:
                vals.append(a)
        aps[lab] = np.asarray(vals)
        pooled[lab] = pooled_ap(per[lab], gt, stems)
        print(f"[PAIRED] {lab}: 逐图 AP@0.5 均值 {aps[lab].mean():.4f} "
              f"(n={len(aps[lab])}, std {aps[lab].std(ddof=1):.4f}); "
              f"数据集级 pooled AP@0.5 = {pooled[lab]:.4f} (应≈ultralytics 的 mAP@0.5)")

    a, b = aps[args.label_a], aps[args.label_b]
    n = min(len(a), len(b))
    d = b[:n] - a[:n]
    mean_d = float(d.mean())
    sd = float(d.std(ddof=1)) if n > 1 else 0.0
    t = mean_d / (sd / np.sqrt(n)) if sd > 0 else None
    win = int((d > 0).sum())
    loss = int((d < 0).sum())
    tie = n - win - loss
    res = {
        "schema": "paired_image_eval/1",
        "generated_by": "pipelines/shelf_sdg/25_paired_image_eval.py",
        "n_images": n, "split": args.split,
        "weights": {args.label_a: args.weights_a, args.label_b: args.weights_b},
        "per_image_ap50_mean": {args.label_a: float(a.mean()), args.label_b: float(b.mean())},
        "per_image_ap50_std": {args.label_a: float(a.std(ddof=1)), args.label_b: float(b.std(ddof=1))},
        "pooled_ap50": {args.label_a: pooled[args.label_a], args.label_b: pooled[args.label_b]},
        "pooled_ap50_note": "pooled AP@0.5 与 ultralytics 报告的 mAP@0.5 同口径, 用于校验本脚本实现; "
                            "逐图 AP 的均值**不等于**数据集级 mAP (聚合方式不同: 每图等权 vs 按检测数加权), "
                            "只有配对差值用于推断。",
        "paired_diff_mean": mean_d,
        "paired_diff_std": sd,
        "paired_t": t,
        "images_b_better": win, "images_worse": loss, "images_tied": tie,
        "note": "逐图 AP@0.5 (101 点插值); 配对 t 值按 n=图数 计算。差值的符号: 正= B 更好。"
                "这是评测集侧的检验 (n=图数), 与训练 seed 方差是两个独立的噪声源。",
    }
    os.makedirs(OUT, exist_ok=True)
    pj = os.path.join(OUT, f"paired_image_eval_{tag}.json")
    json.dump(res, open(pj, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    md = [f"# 逐图配对评测: {args.label_a} vs {args.label_b}", "",
          "| 项 | 值 |", "|---|---:|",
          f"| 评测图数 n | {n} |",
          f"| {args.label_a} 逐图 AP@0.5 均值 | {a.mean():.4f} |",
          f"| {args.label_b} 逐图 AP@0.5 均值 | {b.mean():.4f} |",
          f"| 配对差值 (B−A) 均值 | {mean_d*100:+.4f} pp |",
          f"| 配对差值 标准差 | {sd*100:.4f} pp |",
          f"| 配对 t | {('%.3f' % t) if t is not None else '—'} |",
          f"| B 更好的图数 | {win} |",
          f"| B 更差的图数 | {loss} |",
          f"| 持平 | {tie} |",
          f"| 数据集级 pooled AP@0.5 ({args.label_a}) | {pooled[args.label_a]:.4f} |",
          f"| 数据集级 pooled AP@0.5 ({args.label_b}) | {pooled[args.label_b]:.4f} |", "",
          res["note"]]
    pm = os.path.join(OUT, f"paired_image_eval_{tag}.md")
    open(pm, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("\n".join(md))
    print("->", pj)


if __name__ == "__main__":
    main()
