#!/usr/bin/env python3
"""域差距度量 (2026-11-21): 把"合成为什么帮不上忙"从推测变成可核验的数字。

审计里 R1 (纯合成 0.133) 的负结果归因一直写着"根因指向训练/真实密度错配, 但该归因因缺
`domain_gap_measure.json` 未落盘而仓内不可核验"。本脚本补上这个文件: 用**标签统计**对比
真实 train 与 SDG 合成 train, 落盘密度/尺寸/覆盖度/冗余度四组量。

不依赖 GPU, 只读标签与图片头信息。
"""
import glob
import json
import os
import random
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "output", "benchmark")

IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp")


def quant(xs, qs=(0.1, 0.5, 0.9)):
    xs = sorted(xs)
    if not xs:
        return {}
    out = {}
    for q in qs:
        i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
        out[f"p{int(q*100)}"] = round(xs[i], 4)
    return out


def stats(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "mean": round(statistics.mean(xs), 4),
            "std": round(statistics.stdev(xs), 4) if len(xs) > 1 else 0.0,
            **quant(xs)}


def read_labels(label_dir, img_dir, stems=None):
    """→ 每图: (n_boxes, 面积占比和, 归一化框宽高比中位数)

    SKU-110K 的布局是扁平的 (labels/<stem>.txt + images/<stem>.jpg), split 由
    train.txt/val.txt/test.txt 给出; 合成集是 images/train + labels/train 两层。
    """
    out = []
    if not os.path.isdir(label_dir):
        return out
    if stems is None:
        stems = sorted(f[:-4] for f in os.listdir(label_dir) if f.endswith(".txt"))
    for stem in stems:
        lf = os.path.join(label_dir, stem + ".txt")
        if not os.path.exists(lf):
            continue
        img = None
        for e in IMG_EXT:
            p = os.path.join(img_dir, stem + e)
            if os.path.exists(p):
                img = p
                break
        if img is None:
            continue
        try:
            from PIL import Image
            with Image.open(img) as im:
                W, H = im.size
        except Exception:
            W = H = 640
        areas, ars = [], []
        with open(lf, encoding="utf-8") as fh:
            for line in fh:
                p = line.split()
                if len(p) < 5:
                    continue
                w, h = float(p[3]), float(p[4])
                areas.append(w * h)
                ars.append(w / h if h > 0 else 0.0)
        out.append({"stem": stem, "n_boxes": len(areas),
                    "area_sum": sum(areas),
                    "mean_area": (sum(areas) / len(areas)) if areas else 0.0,
                    "median_ar": statistics.median(ars) if ars else 0.0,
                    "W": W, "H": H})
    return out


def layout_redundancy(items, max_pairs=4000, seed=42):
    """布局冗余度代理: 归一化框集合 (按面积降序) 的平均成对 IoU。
    越高 = 图像之间的布局越雷同 → 有效样本量越低。"""
    if len(items) < 2:
        return {"n_images": len(items), "mean_pair_iou": None}
    rng = random.Random(seed)
    sigs = []
    for it in items:
        # 用 (n_boxes, mean_area, area_sum, median_ar) 做粗签名做代理, 避免读像素
        sigs.append((it["n_boxes"], it["mean_area"], it["area_sum"], it["median_ar"]))
    ious = []
    n = len(sigs)
    pairs = min(max_pairs, n * (n - 1) // 2)
    for _ in range(pairs):
        i, j = rng.randrange(n), rng.randrange(n)
        if i == j:
            continue
        a, b = sigs[i], sigs[j]
        # 逐维 min/max 相似度 (0..1), 取平均作为布局相似度代理
        sims = []
        for x, y in zip(a, b):
            m = max(abs(x), abs(y))
            sims.append(1.0 - (abs(x - y) / m) if m > 0 else 1.0)
        ious.append(sum(sims) / len(sims))
    return {"n_images": n, "n_pairs_sampled": len(ious),
            "mean_layout_similarity": round(statistics.mean(ious), 4),
            "std": round(statistics.stdev(ious), 4) if len(ious) > 1 else 0.0}


def break_even(real_mean_boxes, synth_mean_boxes, sec_per_image, cells):
    """框质量等效: 要让合成在"框数"上顶替某个预算的真实标注, 需要多少张合成图 + 多少机时。

    只是一阶估算 (假设框数是唯一瓶颈、且更多合成不会更差) —— 用来给"这次只跑了 160 张"
    这个事实定个量级, 不作为结论。
    """
    out = []
    for c in cells:
        n_real = c["n_real"]
        real_mass = n_real * real_mean_boxes
        need = real_mass / max(synth_mean_boxes, 1e-9)
        out.append({
            "real_frac": c["real_frac"], "n_real": n_real,
            "real_box_mass": round(real_mass),
            "synth_images_for_equal_box_mass": round(need),
            "render_hours_at_measured_rate": round(need * sec_per_image / 3600.0, 2),
            "synth_images_actually_used": c["n_synth"],
            "ratio_used_over_needed": round(c["n_synth"] / need, 4) if need else None,
        })
    return out


def main():
    sku = os.environ.get("SKU110K_ROOT", "").strip()
    if not sku:
        raise SystemExit(
            "[DOMAIN-GAP] 缺环境变量 SKU110K_ROOT —— 指向 SKU-110K 数据集根目录, 例如:\n"
            '    export SKU110K_ROOT="/data/SKU-110K"')
    real_lbl = os.path.join(sku, "labels")
    real_img = os.path.join(sku, "images")
    split_file = os.path.join(sku, "train.txt")
    stems = None
    if os.path.exists(split_file):
        with open(split_file, encoding="utf-8") as f:
            stems = []
            for ln in f:
                if not ln.strip():
                    continue
                base = ln.strip().split()[0].rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
                for e in IMG_EXT:
                    if base.lower().endswith(e):
                        base = base[:-len(e)]
                        break
                stems.append(base)
    syn_root = os.path.join(BASE, "output", "benchmark", "synth_single")
    syn_lbl = os.path.join(syn_root, "labels", "train")
    syn_img = os.path.join(syn_root, "images", "train")

    real = read_labels(real_lbl, real_img, stems)
    synth = read_labels(syn_lbl, syn_img)
    if not real or not synth:
        raise SystemExit(f"[GAP] 标签缺失: real={len(real)} synth={len(synth)}")

    def side(items):
        return {
            "n_images": len(items),
            "boxes_per_image": stats([it["n_boxes"] for it in items]),
            "area_sum_per_image": stats([it["area_sum"] for it in items]),
            "mean_box_area": stats([it["mean_area"] for it in items]),
            "median_aspect_ratio": stats([it["median_ar"] for it in items]),
            "image_res": sorted({(it["W"], it["H"]) for it in items})[:5],
            "total_boxes": sum(it["n_boxes"] for it in items),
            "layout_similarity": layout_redundancy(items),
        }

    r, s = side(real), side(synth)
    gaps = {
        "boxes_per_image_ratio_synth_over_real":
            round(s["boxes_per_image"]["mean"] / max(r["boxes_per_image"]["mean"], 1e-9), 4),
        "mean_box_area_ratio_synth_over_real":
            round(s["mean_box_area"]["mean"] / max(r["mean_box_area"]["mean"], 1e-9), 4),
        "area_sum_ratio_synth_over_real":
            round(s["area_sum_per_image"]["mean"] / max(r["area_sum_per_image"]["mean"], 1e-9), 4),
        "layout_similarity_gap_synth_minus_real":
            round(s["layout_similarity"]["mean_layout_similarity"]
                  - r["layout_similarity"]["mean_layout_similarity"], 4),
    }
    # 渲染吞吐 (实测, 来自 SDG split_manifest) + 预算格点 → 框质量等效的机时估算
    thr = {}
    man = os.path.join(BASE, "output", "sdg_shelf", "split_manifest.json")
    if os.path.exists(man):
        try:
            thr = json.load(open(man, encoding="utf-8")).get("throughput") or {}
        except Exception:
            thr = {}
    sec_per_image = float(thr.get("sec_per_image") or 0.0)
    cells = []
    seen = set()
    for f in sorted(glob.glob(os.path.join(BASE, "output", "benchmark", "budget_real*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        c = d["dataset"]["cell"]
        key = (c["real_frac"], d["dataset"]["n_synth"])
        if key in seen:      # 多种子复跑的同一格点只算一次
            continue
        seen.add(key)
        cells.append({"real_frac": c["real_frac"], "n_real": d["dataset"]["n_real"],
                      "n_synth": d["dataset"]["n_synth"]})
    be = break_even(r["boxes_per_image"]["mean"], s["boxes_per_image"]["mean"],
                    sec_per_image, cells) if (cells and sec_per_image) else []

    out = {
        "schema": "domain_gap_measure/1",
        "generated_by": "pipelines/shelf_sdg/23_domain_gap_measure.py",
        "note": "标签统计口径: YOLO 归一化框; area_sum = 单图所有框面积占比之和; "
                "layout_similarity = (n_boxes, mean_area, area_sum, median_ar) 签名的成对相似度均值 "
                "(越高=布局越雷同, 有效样本量越低)",
        "real": r, "synth": s, "gaps": gaps,
        "synth_render_throughput_measured": thr,
        "break_even_box_mass_equivalent": be,
        "limits": [
            "标签统计只说明**分布形状**的差距, 不等于特征空间的距离; 特征级差距需另测 (未做)",
            "合成集只有一套货架模板的参数化变体, 与真实 SKU-110K 的门店实拍不是同一生成过程",
            "layout_similarity 是签名的代理量, 不是像素/特征距离",
            "break_even 是一阶估算 (假设框数是唯一瓶颈): 更多合成是否反而更差**未测**, "
            "本文件只用于给量级, 不作为'加大合成就能替代'的依据",
        ],
    }
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "domain_gap_measure.json")
    json.dump(out, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(json.dumps({"real_boxes_per_image": r["boxes_per_image"]["mean"],
                      "synth_boxes_per_image": s["boxes_per_image"]["mean"],
                      "gaps": gaps,
                      "break_even": be}, ensure_ascii=False, indent=2))
    print("->", p)


if __name__ == "__main__":
    main()
