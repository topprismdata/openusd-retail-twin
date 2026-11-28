#!/usr/bin/env python
"""上下文剥离探针 (I-16): 真实照片的**上下文**是不是合成模型过不去的那堵墙?

问题
----
I-08/I-11/I-13/I-14/I-04 把"可调项"清空后, 74.66 pp 的跨域缺口只剩**场景结构**没被
直接测过 (合成图 = 三层大箱货架, 真实图 = 密集小商品墙)。直接改生成器要 6-8 机时,
所以先用这个 1 小时的探针估收益。

测量 (只改输入像素, 标签一律不动)
----------------------------------
把图里**每个标注框的区域原样保留**、**框外全部换成纯色背景** -> "上下文剥离版"。
于是:

  * 框的位置/大小/数量/商品像素 全部不变 -> 变量只有"框外那些像素" (货架纹理、
    木纹、灯光、**邻居商品的像素**、邻物造成的遮挡与杂乱);
  * 框的**布局** (数量/尺寸分布) 也保持不变 -> 所以这个探针测的是"视觉上下文",
    不测"布局"; 布局那一半另有证据 (密度 -4 pp、形状臂 -10.66 pp、尺寸已对齐)。

对照组 (差分, 用来扣掉"贴图伪影")
----------------------------------
把同样的处理施加到**留出的合成集** (大池 val 的 560 张, R1 对照模型没见过这些场景):
Δ_synth = 剥离在**合成域**上的效应 (其中包含"把框贴到纯色底上"这个动作本身的效应,
比如边界变锐利、商品更显著)。真实域的 Δ_real 减去它 -> 才是"真实上下文"特有的代价:

  Δ_real  >> Δ_synth -> 真实上下文 (货架/灯光/邻居) 是主要障碍 -> 生成器改造有希望
  Δ_real ≈ Δ_synth -> 上下文不是障碍 -> 缺口在商品本身/布局 -> 生成器改造救不了

用法:
    python pipelines/shelf_sdg/63_context_probe.py [--n-real 800]
"""
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
WORK = os.path.join(BENCH, "context_probe")
OUT_JSON = os.path.join(BENCH, "context_probe.json")
SEEDS = [43, 44, 45]
REAL_DIR = os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K")
REAL_YAML = os.path.join(REAL_DIR, "SKU-110K.yaml")
BIGPOOL = os.path.join(BENCH, "synth_bigpool")
BG = (236, 236, 236)          # 纯色背景: 与合成域的浅灰货架底接近
MIN_SIDE = 4                 # 框的最小边长 (像素), 太小的框贴进去没有意义


def strip_one(args):
    """把一张图的框外像素换成纯色, 框内像素原样保留; 返回写入的路径。"""
    from PIL import Image
    src, lbl, dst_img, dst_lbl = args
    img = Image.open(src).convert("RGB")
    W, H = img.size
    canvas = Image.new("RGB", (W, H), BG)
    try:
        with open(lbl, "r", encoding="utf-8") as fh:
            lines = [l.strip() for l in fh if l.strip()]
    except OSError:
        lines = []
    for line in lines:
        p = line.split()
        if len(p) < 5:
            continue
        _, cx, cy, w, h = (float(x) for x in p[:5])
        x0 = max(0, int((cx - w / 2) * W))
        x1 = min(W, int((cx + w / 2) * W))
        y0 = max(0, int((cy - h / 2) * H))
        y1 = min(H, int((cy + h / 2) * H))
        if x1 - x0 < MIN_SIDE or y1 - y0 < MIN_SIDE:
            continue
        canvas.paste(img.crop((x0, y0, x1, y1)), (x0, y0))
    os.makedirs(os.path.dirname(dst_img), exist_ok=True)
    os.makedirs(os.path.dirname(dst_lbl), exist_ok=True)
    canvas.save(dst_img, quality=95)
    with open(dst_lbl, "w", encoding="utf-8") as fh:
        fh.write("".join(l + "\n" for l in lines))
    return dst_img


def build_stripped(name, items):
    """items = [(src_img, lbl_path, dst_stem)] -> 造一个 images/ + labels/ 的数据集目录。"""
    root = os.path.join(WORK, name)
    imgs = os.path.join(root, "images")
    lbls = os.path.join(root, "labels")
    os.makedirs(imgs, exist_ok=True)
    os.makedirs(lbls, exist_ok=True)
    jobs = []
    for src, lbl, stem in items:
        ext = os.path.splitext(src)[1] or ".jpg"
        jobs.append((src, lbl, os.path.join(imgs, stem + ext),
                     os.path.join(lbls, stem + ".txt")))
    with ProcessPoolExecutor(max_workers=8) as ex:
        for i, _ in enumerate(ex.map(strip_one, jobs), 1):
            if i % 100 == 0:
                print(f"[STRIP {name}] {i}/{len(jobs)}", flush=True)
    yaml_path = os.path.join(root, "dataset.yaml")
    with open(yaml_path, "w", encoding="utf-8") as fh:
        fh.write(f"path: {root}\ntrain: images\nval: images\ntest: images\n"
                 "nc: 1\nnames: [product]\n")
    return yaml_path


def real_subset(n):
    """从真实 test.txt 里取前 n 张 (固定顺序 -> 可复现)。"""
    items, listing = [], []
    with open(os.path.join(REAL_DIR, "test.txt"), "r", encoding="utf-8") as fh:
        lines = [l.strip() for l in fh if l.strip()]
    for line in lines:
        rel = line.replace("\\", "/").lstrip("./")
        img = os.path.join(REAL_DIR, rel.replace("/", os.sep))
        if not os.path.isfile(img):
            continue
        stem = os.path.splitext(os.path.basename(img))[0]
        lbl = os.path.join(REAL_DIR, "labels", stem + ".txt")
        if not os.path.isfile(lbl):
            continue
        items.append((img, lbl, stem))
        listing.append(img)
        if len(items) >= n:
            break
    lst = os.path.join(WORK, "real_subset.txt")
    os.makedirs(WORK, exist_ok=True)
    with open(lst, "w", encoding="utf-8") as fh:
        fh.write("".join(p + "\n" for p in listing))
    yaml_path = os.path.join(WORK, "real_subset.yaml")
    with open(yaml_path, "w", encoding="utf-8") as fh:
        fh.write(f"path: {REAL_DIR}\ntrain: {lst}\nval: {lst}\ntest: {lst}\n"
                 "nc: 1\nnames: [product]\n")
    return items, yaml_path


def synth_val_items():
    """大池 val 的 560 张 (R1 对照模型训练时没见过这些场景) -> 合成域的对照组。"""
    img_dir = os.path.join(BIGPOOL, "images", "val")
    lbl_dir = os.path.join(BIGPOOL, "labels", "val")
    items = []
    for f in sorted(os.listdir(img_dir)):
        stem = os.path.splitext(f)[0]
        lbl = os.path.join(lbl_dir, stem + ".txt")
        if not os.path.isfile(lbl):
            continue
        items.append((os.path.join(img_dir, f), lbl, stem))
    return items


def ev(ckpt, yaml, split):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=yaml, split=split, imgsz=640, batch=4, device="0",
              max_det=1000, workers=2, verbose=False)
    return {"map50": float(r.box.map50), "map50_95": float(r.box.map),
            "precision": float(r.box.mp), "recall": float(r.box.mr),
            "n_images": int(getattr(r, "n_images", 0) or 0)}


def main():
    n_real = 800
    if "--n-real" in sys.argv:
        n_real = int(sys.argv[sys.argv.index("--n-real") + 1])
    os.makedirs(WORK, exist_ok=True)
    print(f"[CONTEXT] 造真实子集 ({n_real} 张) …", flush=True)
    real_items, real_yaml = real_subset(n_real)
    print(f"[CONTEXT] 造真实剥离版 …", flush=True)
    real_strip_yaml = build_stripped("real_stripped", real_items)
    print(f"[CONTEXT] 造合成对照组 (大池 val) …", flush=True)
    syn_items = synth_val_items()
    syn_strip_yaml = build_stripped("synth_stripped", syn_items)
    syn_yaml = os.path.join(BIGPOOL, "dataset.yaml")

    rep = {"schema": "context_probe/1",
           "generated_by": "pipelines/shelf_sdg/63_context_probe.py",
           "measured_at": "2026-11-25",
           "question": ("真实照片的上下文 (货架/灯光/邻居) 是不是合成模型过不去的那堵墙?"),
           "design": ("只改框外像素 (框内像素与标签一律不动); 对照组 = 同一处理施加到"
                      "留出的合成集 (大池 val), 用差分扣掉'贴到纯色底'这个动作本身的效应"),
           "n_real": len(real_items), "n_synth": len(syn_items),
           "per_seed": {}}
    for s in SEEDS:
        ck = os.path.join(BENCH, f"runs_r1_s{s}", "train", "weights", "last.pt")
        if not os.path.isfile(ck):
            print(f"[CONTEXT] 缺权重 {ck}, 跳过")
            continue
        row = {}
        print(f"[CONTEXT] seed {s}: 真实原图 …", flush=True)
        row["real"] = ev(ck, real_yaml, "test")
        print(f"[CONTEXT] seed {s}: 真实剥离版 …", flush=True)
        row["real_stripped"] = ev(ck, real_strip_yaml, "test")
        print(f"[CONTEXT] seed {s}: 合成留出集 …", flush=True)
        row["synth_heldout"] = ev(ck, syn_yaml, "val")
        print(f"[CONTEXT] seed {s}: 合成留出集剥离版 …", flush=True)
        row["synth_heldout_stripped"] = ev(ck, syn_strip_yaml, "val")
        row["delta_real_pp"] = (row["real_stripped"]["map50"] - row["real"]["map50"]) * 100
        row["delta_synth_pp"] = (row["synth_heldout_stripped"]["map50"]
                                 - row["synth_heldout"]["map50"]) * 100
        row["did_pp"] = row["delta_real_pp"] - row["delta_synth_pp"]
        rep["per_seed"][str(s)] = row
        print(f"[CONTEXT] seed {s}: Δ_real {row['delta_real_pp']:+.2f} pp, "
              f"Δ_synth {row['delta_synth_pp']:+.2f} pp, 差分 {row['did_pp']:+.2f} pp",
              flush=True)
    if rep["per_seed"]:
        rows = list(rep["per_seed"].values())
        rep["mean"] = {k: sum(r[k] for r in rows) / len(rows)
                       for k in ("delta_real_pp", "delta_synth_pp", "did_pp")}
        n = len(rows)
        if n > 1:
            import statistics
            sd = statistics.stdev(r["did_pp"] for r in rows)
            t = 4.303  # df=2, 95%
            m = rep["mean"]["did_pp"]
            rep["did_ci95"] = [m - t * sd / (n ** 0.5), m + t * sd / (n ** 0.5)]
        print(f"[CONTEXT] 平均差分 {rep['mean']['did_pp']:+.2f} pp")
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print(f"[CONTEXT] → {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
