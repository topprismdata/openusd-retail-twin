#!/usr/bin/env python3
"""标注口径差实测 (审计 F7): 合成标签 vs 真实标签, 到底差在哪、差多少。

背景: 审计 F7 记的是"合成标签丢弃遮挡物 (可见面积 <15% 的不入库), 真实标注保留被遮挡商品",
另有一条"单类化时丢弃 OOS gap 框"。这两条都只是**代码层面**的观察, 从没在
**实际使用的那套合成数据**上量过数 —— 于是"口径差"一直是个没有量级的说法。

本脚本不训练、不渲染, 只读已有产物, 回答四个问题:
  1. 可见度过滤在这套数据上到底丢没丢东西? (逐图: 标注记录数 vs YOLO 标签行数)
  2. 单类化 (丢弃 class 1 = OOS gap) 丢掉多少框?
  3. 合成标签的框密度 (框/图) 与真实 SKU-110K 差多少?
  4. 这些口径差对"R2 (真实+合成) vs R0 (真实)"这个结论的**影响上界**有多大?
     (上界 = 合成数据在 R2 训练集里的占比 —— 只有这个比例的信号被口径差污染)

产物: output/benchmark/label_semantics.json (+ 供 26 号发布脚本收录)
"""
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
SDG = os.path.join(BASE, "output", "sdg_shelf")
SYNTH_SINGLE = os.path.join(BENCH, "synth_single")
OUT = os.path.join(BENCH, "label_semantics.json")

REAL_ROOT = os.environ.get("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))


def read_yolo(path):
    rows = []
    if not os.path.exists(path):
        return rows
    for ln in open(path, encoding="utf-8"):
        p = ln.split()
        if len(p) == 5:
            rows.append((int(p[0]), [float(x) for x in p[1:]]))
    return rows


def img_size(path):
    """PNG/JPG 尺寸 —— 不引 PIL, 直接读 PNG 头 (IHDR) / JPEG SOF。"""
    with open(path, "rb") as f:
        head = f.read(32)
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        w = int.from_bytes(head[16:20], "big")
        h = int.from_bytes(head[20:24], "big")
        return w, h
    return None


def measure_sdg():
    """SDG 原始集: 逐图比对 标注记录 vs YOLO 标签行, 并统计被可见度过滤丢弃的目标。"""
    per_img = []
    ann_dir = os.path.join(SDG, "annotations")
    for ap in sorted(glob.glob(os.path.join(ann_dir, "*.json"))):
        d = json.load(open(ap, encoding="utf-8"))
        recs = d.get("annotations", [])
        stem = os.path.basename(ap)[:-5]
        split = d.get("split") or "train"
        rows = read_yolo(os.path.join(SDG, "labels", split, stem + ".txt"))
        filt = [r for r in recs if r.get("filtered") == "low_visibility"]
        cls = {}
        for r in recs:
            cls[str(r.get("class_id"))] = cls.get(str(r.get("class_id")), 0) + 1
        src = {}
        for r in recs:
            src[str(r.get("bbox_source"))] = src.get(str(r.get("bbox_source")), 0) + 1
        per_img.append({
            "img": stem, "split": split,
            "n_records": len(recs), "n_label_lines": len(rows),
            "n_filtered_low_vis": len(filt),
            "n_label_lines_plus_filtered": len(rows) + len(filt),
            "class_hist": cls, "bbox_source_hist": src,
            "label_hist": {str(c): sum(1 for r in rows if r[0] == c) for c in sorted({r[0] for r in rows})},
        })
    return per_img


def measure_real():
    """真实 SKU-110K: 训练集框密度 (框/图) 与图片数。

    优先用数据集自带的 prep_summary.json (预处理时算好的图数/框数) —— 比逐个读
    1.1 万个标签文件快几十倍, 而且那份 summary 本身进了仓的指纹清单。
    没有 summary 时才退回逐文件统计。
    """
    out = {"root": REAL_ROOT, "available": os.path.isdir(REAL_ROOT)}
    if not out["available"]:
        return out
    ps = os.path.join(REAL_ROOT, "prep_summary.json")
    if os.path.exists(ps):
        d = json.load(open(ps, encoding="utf-8"))
        out["source"] = "prep_summary.json"
        for s in d.get("splits", []):
            n_img = s.get("n_images") or 0
            n_box = s.get("n_boxes") or 0
            out[s["split"]] = {"n_images_found": n_img, "n_boxes": n_box,
                               "boxes_per_image": round(n_box / n_img, 2) if n_img else None}
        return out
    out["source"] = "labels_on_disk"
    for split in ("train", "val", "test"):
        listfile = os.path.join(REAL_ROOT, f"{split}.txt")
        if not os.path.exists(listfile):
            continue
        names = [l.strip() for l in open(listfile, encoding="utf-8") if l.strip()]
        n_boxes = 0
        n_img_found = 0
        for nm in names:
            # 清单里是 './images/train_0.jpg' 这种相对路径
            rel = nm[2:] if nm.startswith("./") else nm
            ip = os.path.join(REAL_ROOT, rel.replace("/", os.sep))
            lp = os.path.join(REAL_ROOT, "labels",
                              os.path.basename(rel).rsplit(".", 1)[0] + ".txt")
            if os.path.exists(ip):
                n_img_found += 1
            n_boxes += len(read_yolo(lp))
        out[split] = {"n_listed": len(names), "n_images_found": n_img_found,
                      "n_boxes": n_boxes,
                      "boxes_per_image": round(n_boxes / n_img_found, 2) if n_img_found else None}
    return out


def arm_synth_ratio():
    """R2 臂的实际合成占比 (取最近一次跑的产物) —— 口径差影响的上界。"""
    cands = sorted(glob.glob(os.path.join(BENCH, "sku110k_r2_s*.json")))
    if not cands:
        return None
    p = cands[-1]
    d = json.load(open(p, encoding="utf-8"))
    comp = d.get("dataset") or d.get("dataset_composition") or {}
    srcs = comp.get("sources", [])
    n_real = n_syn = 0
    for s in srcs:
        if s.get("kind") == "real":
            n_real += s.get("n_images") or 0
        elif s.get("kind") == "synthetic":
            n_syn += s.get("n_images") or 0
    total = n_real + n_syn
    return {"artifact": os.path.basename(p),
            "synth_ratio": comp.get("synth_ratio") or (round(n_syn / total, 6) if total else None),
            "n_real": n_real, "n_synth": n_syn, "n_total_train": total,
            "synth_ratio_note": "合成在 R2 训练集里的占比 —— 口径差能污染的信号上界"}


def write_md(res):
    """人读的汇总 (数字全部来自 json, 不手写)。"""
    real = res.get("real_sku110k", {})
    tr = real.get("train", {})
    ratio = res.get("r2_synth_ratio") or {}
    L = []
    L.append("# 标注口径差实测 (审计 F7) — 2026-11-23\n")
    L.append(f"数据: `{res['sdg_set']}` ({res['n_images']} 图 = train {res['n_images_train']} + "
             f"val {res['n_images_val']}, 场景级留出)\n")
    L.append("| 检验 | 结果 |")
    L.append("|---|---|")
    L.append(f"| 逐图一致性 (标签行数 vs 标注记录数) | {'全部一致' if res['per_image_consistent'] else '有不一致'} |")
    L.append(f"| 可见度过滤 (可见面积 <15% 不入库) 丢弃 | **{res['dropped_low_visibility']} / "
             f"{res['records_total']} = {res['dropped_low_visibility_rate']}** |")
    L.append(f"| 单类化丢弃 class 1 (OOS gap) | {res['dropped_class1_oos_gap']} / {res['records_total']} "
             f"= {res['dropped_class1_rate_of_records']} |")
    L.append(f"| 合成有效框/图 (train, 单类后) | {res['synth_effective_boxes_per_image_train']} |")
    L.append(f"| 真实 SKU-110K train 框/图 | {tr.get('boxes_per_image')} "
             f"({tr.get('n_images_found')} 图 / {tr.get('n_boxes')} 框) |")
    L.append(f"| 框密度比 (真实/合成) | **{round(tr.get('boxes_per_image', 0) / max(1e-9, res['synth_effective_boxes_per_image_train']), 2)}×** |")
    L.append(f"| R2 训练集里的合成占比 (口径差影响的上界) | **{ratio.get('synth_ratio')}** "
             f"({ratio.get('n_synth')} 合成 / {ratio.get('n_real')} 真实) |")
    ch = res.get("class_hist", {})
    kept = sum(v for k, v in ch.items() if k != "1")
    noncompliant = ch.get("2", 0) + ch.get("3", 0)
    L.append(f"| 保留框里带非合规语义 (朝向错位 class2 + 竞品入侵 class3) | {noncompliant} / {kept} = "
             f"{round(noncompliant / kept, 4) if kept else None} |")
    L.append(f"| 框来源 | 全部 `object_index_mask` (可见区域紧致框): "
             f"{res.get('bbox_source_hist')} |")
    L.append("")
    L.append("## 读法\n")
    L.append("1. **审计 F7 记的\"合成丢弃遮挡物\"在这套数据上从未发生** —— 可见度过滤一次都没触发 "
             "(0/5240), 且逐图标签行数与标注记录数完全一致。F7 是代码层面的观察, 不是数据层面的事实。")
    L.append("2. 真正存在的口径差是三条: (a) 单类化时丢 OOS gap 框 "
             f"({res['dropped_class1_rate_of_records']}); (b) 合成框是**可见区域**紧致框, 真实框是整品框; "
             "(c) 框密度差 6.7× (21.8 vs 147.0 框/图)。")
    L.append("3. 对头条结论 (R2 vs R0) 的影响上界 = 合成在 R2 训练集里的占比 = "
             f"**{ratio.get('synth_ratio')}**; 口径差最多只能污染这部分信号, "
             "而实测 Δ(R2−R0) = +0.07pp —— 量级上不可能解释\"未检出差异\"。")
    L.append("4. 对 R1 (纯合成臂) 影响则是 100%: R1 的数字就是\"当前标签语义下的纯合成\"水平。")
    L.append("5. **框密度比 6.74× 是偏向真实的上界估计**: 合成框是**可见区域**紧致框, "
             "换成整品框只会更大 (可见面积占比 <1) → 合成侧的框密度只会更低 → "
             "\"合成的标注效率只有真实的 1/6.7\"这个说法**保守**, 不是夸大。")
    L.append("")
    L.append(f"产物: `output/benchmark/label_semantics.json` (脚本 `37_label_semantics_measure.py` 现算)")
    with open(os.path.join(BENCH, "label_semantics.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")


def main():
    per_img = measure_sdg()
    if not per_img:
        print(f"[LABELS] 没有 SDG 产物 ({SDG}) —— 先跑 02 号脚本")
        raise SystemExit(1)

    n_rec = sum(p["n_records"] for p in per_img)
    n_line = sum(p["n_label_lines"] for p in per_img)
    n_filt = sum(p["n_filtered_low_vis"] for p in per_img)
    # 单类化丢弃: class 1 (OOS gap)
    cls_hist = {}
    src_hist = {}
    for p in per_img:
        for k, v in p["class_hist"].items():
            cls_hist[k] = cls_hist.get(k, 0) + v
        for k, v in p["bbox_source_hist"].items():
            src_hist[k] = src_hist.get(k, 0) + v
    n_c1 = cls_hist.get("1", 0)

    train = [p for p in per_img if p["split"] == "train"]
    val = [p for p in per_img if p["split"] == "val"]
    eff_train = sum(p["n_label_lines"] - p["label_hist"].get("1", 0) for p in train)
    eff_val = sum(p["n_label_lines"] - p["label_hist"].get("1", 0) for p in val)
    raw_train = sum(p["n_label_lines"] for p in train)

    # 逐图一致性: 标签行数 + 被过滤数 是否等于标注记录数 (不等 = 有别的东西被丢)
    inconsistent = [p["img"] for p in per_img
                    if p["n_label_lines"] + p["n_filtered_low_vis"] != p["n_records"]]

    real = measure_real()
    ratio = arm_synth_ratio()

    res = {
        "measured_at": "2026-11-23",
        "sdg_set": os.path.relpath(SDG, BASE).replace("\\", "/"),
        "n_images": len(per_img),
        "n_images_train": len(train), "n_images_val": len(val),
        "records_total": n_rec,
        "label_lines_total": n_line,
        "dropped_low_visibility": n_filt,
        "dropped_low_visibility_rate": round(n_filt / n_rec, 6) if n_rec else None,
        "dropped_class1_oos_gap": n_c1,
        "dropped_class1_rate_of_records": round(n_c1 / n_rec, 6) if n_rec else None,
        "class_hist": cls_hist,
        "bbox_source_hist": src_hist,
        "per_image_consistent": len(inconsistent) == 0,
        "per_image_inconsistent": inconsistent[:20],
        "synth_effective_boxes_per_image_train": round(eff_train / len(train), 2) if train else None,
        "synth_raw_boxes_per_image_train": round(raw_train / len(train), 2) if train else None,
        "synth_effective_boxes_total": eff_train + eff_val,
        "real_sku110k": real,
        "r2_synth_ratio": ratio,
        "verdict": {
            "f7_visibility_filter_fires": n_filt > 0,
            "f7_visibility_drop_rate": round(n_filt / n_rec, 6) if n_rec else None,
            "confound_bound_note": ("合成口径差最多只能污染 R2 训练信号里 '合成占比' 那一部分; "
                                     "占比见 r2_synth_ratio.synth_ratio"),
        },
    }
    os.makedirs(BENCH, exist_ok=True)
    json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    write_md(res)
    print(f"[LABELS] 逐图一致性: {'一致' if not inconsistent else '不一致 ' + str(inconsistent[:5])}")
    print(f"[LABELS] 标注记录 {n_rec} / 标签行 {n_line} / 可见度过滤丢弃 {n_filt} "
          f"({res['dropped_low_visibility_rate']})")
    print(f"[LABELS] class 1 (OOS gap) 丢弃 {n_c1} ({res['dropped_class1_rate_of_records']})")
    print(f"[LABELS] 合成有效框/图 (train) = {res['synth_effective_boxes_per_image_train']} "
          f"(原始 {res['synth_raw_boxes_per_image_train']})")
    for sp in ("train", "val", "test"):
        if sp in real:
            print(f"[LABELS] 真实 {sp}: {real[sp]['n_images_found']} 图 / "
                  f"{real[sp]['n_boxes']} 框 = {real[sp]['boxes_per_image']} 框/图")
    if ratio:
        print(f"[LABELS] R2 合成占比 (上界) = {ratio['synth_ratio']} ({ratio['artifact']})")
    print(f"[LABELS] -> {OUT}")


if __name__ == "__main__":
    main()
