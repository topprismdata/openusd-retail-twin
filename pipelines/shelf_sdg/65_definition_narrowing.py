#!/usr/bin/env python
"""I-19 · "商品定义收窄"的量化诊断 (2026-11-26)。

问题: 纹理臂 (-13.2 pp)、货架墙臂 (-23.3 pp)、上下文臂 (-9.8 pp) 都掉了分, 而它们
改的都不是"商品本身该长什么样"(上下文臂连商品像素都没碰 ✓)。三条臂的共同后果被
62 号诊断过一次: **模型把"商品"的定义收窄了**。这里把它量化:

对真实 test 集, 把模型的检出框与 GT 框按 IoU>=0.5 配对, 然后按 GT 框的
  · 面积占比 (相对图像面积)
  · 宽高比
分桶, 算每个桶里的**召回率**。
如果某个臂的模型**只在"窄条形"的小目标上召回**, 而在宽的/大的目标上几乎不召回,
那就是"定义被收窄"的直接证据 (而不是"整体变弱" —— 整体变弱会让所有桶一起掉)。

用法:
    python pipelines/shelf_sdg/65_definition_narrowing.py
产物:
    output/benchmark/definition_narrowing.json   (数字现算, 不手写)
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
ART = os.path.join(BENCH, "definition_narrowing.json")
IOU = 0.5

MODELS = [
    ("control_R1", os.path.join(BENCH, "runs_r1_s43", "train", "weights", "last.pt")),
    ("shelfwall_I17", os.path.join(BENCH, "runs_wall_s43", "train", "weights", "last.pt")),
    ("ctxwall_I18", os.path.join(BENCH, "runs_ctx_s43", "train", "weights", "last.pt")),
]


def load_real_test(n_max=120):
    """真实 test 集 (图 + GT 框)。SKU-110K 的 test.txt 给出文件名单。

    数据集根由环境变量 `SKU110K_ROOT` 指定 —— 不给默认值: 写死某个人的
    绝对路径, 换台机器就静默指到不存在的目录 (要么读到空, 要么读到别的盘)。"""
    root = os.environ.get("SKU110K_ROOT", "").strip()
    if not root:
        raise SystemExit(
            "[DEF-NARROW] 缺环境变量 SKU110K_ROOT —— 指向 SKU-110K 数据集根目录 "
            "(含 test.txt / images/ / labels/), 例如:\n"
            '    export SKU110K_ROOT="/data/SKU-110K"')
    lst = os.path.join(root, "test.txt")
    names = []
    if os.path.isfile(lst):
        for ln in open(lst, encoding="utf-8"):
            ln = ln.strip()
            if ln:
                names.append(os.path.basename(ln))
    else:
        names = [os.path.basename(p) for p in sorted(glob.glob(os.path.join(root, "images", "*.jpg")))]
    out = []
    for nm in names[:n_max]:
        ip = os.path.join(root, "images", nm)
        lp = os.path.join(root, "labels", nm.rsplit(".", 1)[0] + ".txt")
        if not (os.path.isfile(ip) and os.path.isfile(lp)):
            continue
        gts = []
        for ln in open(lp, encoding="utf-8"):
            p = ln.split()
            if len(p) == 5:
                gts.append((float(p[1]), float(p[2]), float(p[3]), float(p[4])))
        out.append((ip, gts))
    return out


def iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def main():
    from ultralytics import YOLO
    data = load_real_test()
    print(f"[NARROW] 真实 test 取 {len(data)} 张")
    # 面积分桶 (相对图像面积): 真实域的商品很小, 桶按对数分
    AREA_EDGES = [0.0, 0.001, 0.0025, 0.006, 0.015, 1.0]
    ASP_EDGES = [0.0, 0.25, 0.4, 0.6, 1.0, 100.0]
    res = {"schema": "definition_narrowing/1",
           "generated_by": "pipelines/shelf_sdg/65_definition_narrowing.py",
           "iou": IOU, "n_images": len(data),
           "area_edges": AREA_EDGES, "aspect_edges": ASP_EDGES,
           "models": {}}
    from PIL import Image
    for tag, ck in MODELS:
        if not os.path.isfile(ck):
            print(f"[NARROW] 跳过 {tag} (缺权重 {ck})")
            continue
        model = YOLO(ck)
        area_hit = {}
        area_tot = {}
        asp_hit = {}
        asp_tot = {}
        for ip, gts in data:
            W, H = Image.open(ip).size
            r = model.predict(ip, imgsz=640, conf=0.05, device="0", verbose=False)[0]
            dets = []
            for b in r.boxes:
                x0, y0, x1, y1 = b.xyxy[0].tolist()
                dets.append((x0 / W, y0 / H, (x1 - x0) / W, (y1 - y0) / H))
            for (cx, cy, w, h) in gts:
                # GT 是 YOLO 归一化的 (cx, cy, w, h) -> 转成 (x0, y0, x1, y1)
                g = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                hit = any(iou(g, (d[0], d[1], d[0] + d[2], d[1] + d[3])) >= IOU for d in dets)
                ai = next((i for i in range(len(AREA_EDGES) - 1) if AREA_EDGES[i] <= w * h < AREA_EDGES[i + 1]), None)
                ar = w / h if h > 0 else 0
                xi = next((i for i in range(len(ASP_EDGES) - 1) if ASP_EDGES[i] <= ar < ASP_EDGES[i + 1]), None)
                if ai is not None:
                    area_tot[ai] = area_tot.get(ai, 0) + 1
                    area_hit[ai] = area_hit.get(ai, 0) + (1 if hit else 0)
                if xi is not None:
                    asp_tot[xi] = asp_tot.get(xi, 0) + 1
                    asp_hit[xi] = asp_hit.get(xi, 0) + (1 if hit else 0)
        def bucket(hit, tot):
            return {f"{AREA_EDGES[i]:g}-{AREA_EDGES[i+1]:g}" if False else str(i):
                    {"n": tot[i], "recall": round(hit.get(i, 0) / tot[i], 4)}
                    for i in sorted(tot)}
        res["models"][tag] = {
            "by_area": bucket(area_hit, area_tot),
            "by_aspect": bucket(asp_hit, asp_tot),
            "overall_recall": round(sum(area_hit.values()) / max(1, sum(area_tot.values())), 4),
        }
        print(f"[NARROW] {tag}: 总体召回 {res['models'][tag]['overall_recall']:.4f} | "
              f"按面积 {[res['models'][tag]['by_area'][str(i)]['recall'] for i in sorted(area_tot)]}")
    with open(ART, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(f"-> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
