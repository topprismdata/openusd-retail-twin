#!/usr/bin/env python
"""纹理臂**为什么**掉了 13 pp —— 机制诊断 (2026-11-25)。

现象
----
纹理臂 (57 号) 在几何逐帧相同的前提下 (61 号已验证), 跨域 mAP 掉了 **13.2 pp**
(3/3 seed 都是 −11.9 ~ −15.5)。这不是"没效果", 是"效果很大但方向反了" ->
必须查清机制, 否则下一轮还会踩同一个坑。

三个可能, 用两个测量分开
------------------------
1. **模型学成了"找 logo/文字"**: 合成商品上有清晰的小标签 (绿色 logo、中文品名),
   真实域里商品在画面里很小 (单框面积 0.003), 标签根本读不出来 -> 模型学到的线索
   在真实域不成立。预测特征: **recall 崩** (真商品找不到)。
2. **标签变成了误检触发器**: 真实照片里到处是纹理/价签/货架纹理 -> 模型把"有印刷图案
   的区域"当成商品 -> **precision 崩** (乱报)。
3. **贴图把域整体推歪** (色彩/亮度分布变了): 那应该两个指标一起糊, 而且在**自己的
   白盒 val** 上也会掉。

测量
----
A. 真实 test 上的 **precision / recall** (分 1 与 2);
B. **白盒 val (R1 的 40 张)** 上的 mAP (分 3: 掉 = 特征空间整个变了; 不掉 = 只是
   在真实域上不成立);
C. 两张真实 test 图的**预测可视化** (人眼看: 它到底在报什么)。

用法:
    python pipelines/shelf_sdg/62_texture_arm_diagnose.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
SEEDS = [43, 44, 45]
OUT_JSON = os.path.join(BENCH, "texture_arm_diagnosis.json")
VIS_DIR = os.path.join(BENCH, "texture_diagnosis_vis")
REAL_YAML = os.environ.get("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
R1_YAML = os.path.join(BENCH, "synth_single", "dataset.yaml")


def ev(ckpt, yaml, split):
    from ultralytics import YOLO
    m = YOLO(ckpt)
    r = m.val(data=yaml, split=split, imgsz=640, batch=4, device="0",
              max_det=1000, workers=2, verbose=False)
    return {"map50": float(r.box.map50), "map50_95": float(r.box.map),
            "precision": float(r.box.mp), "recall": float(r.box.mr),
            "n_images": int(getattr(r, "n_images", 0) or 0)}


def visualize(ckpt, tag, n=3):
    """把真实 test 的**几张**图跑出带框的 PNG (人眼看它在报什么)。

    注意: 只跑 n 张 —— 之前写成对整个 test 集 (2,935 张) predict+save, 一个模型就要
    存 2,935 个 PNG, 六个模型 1.7 万个文件, 又慢又占盘 (可视化只是给人看的, 不需要全量)。
    """
    try:
        from ultralytics import YOLO
        img_dir = os.path.join(os.path.dirname(REAL_YAML), "images")
        picks = []
        for f in sorted(os.listdir(img_dir)):
            if f.startswith("test_") and f.lower().endswith((".jpg", ".png")):
                picks.append(os.path.join(img_dir, f))
            if len(picks) >= n:
                break
        m = YOLO(ckpt)
        d = os.path.join(VIS_DIR, tag)
        os.makedirs(d, exist_ok=True)
        m.predict(source=picks, imgsz=640, device="0", max_det=300, conf=0.25,
                  save=True, save_dir=d, verbose=False, stream=False)
        return sorted(os.listdir(d))
    except Exception as e:
        return [f"<可视化失败: {type(e).__name__}: {e}>"]


def main():
    rep = {"schema": "texture_arm_diagnosis/1",
           "generated_by": "pipelines/shelf_sdg/62_texture_arm_diagnose.py",
           "measured_at": "2026-11-25",
           "question": ("纹理臂掉 13 pp 是'模型学成找 logo'(recall 崩)、"
                        "'标签变成误检触发器'(precision 崩), 还是'贴图把域整体推歪'?"),
           "per_seed": {}, "visualizations": {}}
    for s in SEEDS:
        row = {}
        cks = {
            "control_last": os.path.join(BENCH, f"runs_r1_s{s}", "train", "weights", "last.pt"),
            "texture_last": os.path.join(BENCH, f"runs_tex_s{s}", "train", "weights", "last.pt"),
        }
        for tag, ck in cks.items():
            if not os.path.isfile(ck):
                row[tag] = {"error": "权重缺失"}
                continue
            row[tag] = {"real_test": ev(ck, REAL_YAML, "test")}
            if os.path.isfile(R1_YAML):
                row[tag]["whitebox_val"] = ev(ck, R1_YAML, "val")
        rep["per_seed"][str(s)] = row
        for tag in ("control_last", "texture_last"):
            ck = cks.get(tag)
            if ck and os.path.isfile(ck):
                rep["visualizations"][f"{tag}_s{s}"] = visualize(ck, f"{tag}_s{s}")
    # ---- 汇总 (配对) ----
    def paired(field):
        d = []
        for s in SEEDS:
            row = rep["per_seed"].get(str(s), {})
            a = (row.get("control_last") or {}).get(field) or {}
            b = (row.get("texture_last") or {}).get(field) or {}
            if "map50" in a and "map50" in b:
                d.append((b["map50"] - a["map50"]) * 100)
                d.append(None)
        return d
    summ = {}
    for field in ("real_test", "whitebox_val"):
        ds = []
        for s in SEEDS:
            row = rep["per_seed"].get(str(s), {})
            a = (row.get("control_last") or {}).get(field) or {}
            b = (row.get("texture_last") or {}).get(field) or {}
            if "map50" in a and "map50" in b:
                ds.append({"delta_map50_pp": round((b["map50"] - a["map50"]) * 100, 3),
                           "delta_precision_pp": round((b["precision"] - a["precision"]) * 100, 3),
                           "delta_recall_pp": round((b["recall"] - a["recall"]) * 100, 3),
                           "ctrl": {k: round(v, 4) for k, v in a.items() if isinstance(v, float)},
                           "tex": {k: round(v, 4) for k, v in b.items() if isinstance(v, float)}})
        summ[field] = ds
    rep["summary"] = summ
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    for field, ds in summ.items():
        if not ds:
            continue
        dm = sum(d["delta_map50_pp"] for d in ds) / len(ds)
        dp = sum(d["delta_precision_pp"] for d in ds) / len(ds)
        dr = sum(d["delta_recall_pp"] for d in ds) / len(ds)
        print(f"[{field}] ΔmAP50 {dm:+.2f} pp | ΔP {dp:+.2f} pp | ΔR {dr:+.2f} pp (n={len(ds)})")
    print(f"[产物] {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
