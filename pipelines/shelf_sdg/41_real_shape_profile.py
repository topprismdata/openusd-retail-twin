#!/usr/bin/env python3
"""真实域的**形状分布**剖析 (2026-11-23): 为"朝向因子"给出可执行的形状先验。

背景
----
域差距的三个因子 (密度 / 尺度 / 朝向) 里, "朝向"这一项此前从没被真正操作过:
生成器里所有商品都是**同一个**箱子 (PACK_W 0.048 x PACK_D 0.044 x PACK_H 0.136),
而 "misalign" 状态只是把它**绕竖轴转 82 度** (面朝错了) —— 这会把它从"宽 48mm"变成
"宽 44mm", 投影宽高比从 0.353 变成 0.324, 所以 R3-full 配方的中位宽高比不升反降
(0.3232 -> 0.3007), 离真实侧更远了。

而真实域 (SKU-110K) 的商品**形状很多样**: 逐图中位宽高比的均值 1.05、p10 0.38、p90 1.92
-> 说明真实的每一张图都有自己的"宽窄构成"(有的货架全是扁盒, 有的全是竖瓶)。
**这意味着朝向因子是可以在生成器里表达的**: 只要让每个商品的投影宽高比按真实分布采样。

本脚本产出那个分布 (真实 train 标签 vs 合成 R1 标签), 作为生成器的形状先验:
  * 逐图中位宽高比的分位数 (决定"每张图的宽窄构成");
  * 图内宽高比的离散度 (决定"同一张图内商品之间的差异");
  * 单框面积分布 (决定尺度因子, 与朝向因子耦合)。

只读标签, 不依赖 GPU。
输出: output/benchmark/real_shape_profile.json
"""
import json
import os
import statistics

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
ROOT = os.environ.get("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))

QS = (0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 0.9, 0.95, 0.99)


def quant(xs, qs=QS):
    xs = sorted(xs)
    if not xs:
        return {}
    out = {}
    for q in qs:
        i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
        out[f"p{int(q * 100)}"] = round(xs[i], 5)
    return out


def shape_stats(per_image_boxes):
    """per_image_boxes: [ [(w, h), ...], ... ] (归一化的 w/h)"""
    img_med, box_ar, box_area, spread = [], [], [], []
    for boxes in per_image_boxes:
        if not boxes:
            continue
        ars = [w / h if h > 0 else 0.0 for w, h in boxes]
        areas = [w * h for w, h in boxes]
        img_med.append(statistics.median(ars))
        box_ar.extend(ars)
        box_area.extend(areas)
        # 图内离散度: 对数宽高比的四分位距 (乘性尺度)
        logs = sorted(math_log(a) for a in ars)
        q1 = logs[int(0.25 * (len(logs) - 1))]
        q3 = logs[int(0.75 * (len(logs) - 1))]
        spread.append(q3 - q1)
    return {
        "n_images": len(img_med), "n_boxes": len(box_ar),
        "per_image_median_aspect": {"mean": round(statistics.mean(img_med), 4),
                                     "std": round(statistics.pstdev(img_med), 4),
                                     **quant(img_med)},
        "per_box_aspect": {"mean": round(statistics.mean(box_ar), 4),
                           "std": round(statistics.pstdev(box_ar), 4),
                           **quant(box_ar)},
        "per_box_area": {"mean": round(statistics.mean(box_area), 6),
                         "std": round(statistics.pstdev(box_area), 6),
                         **quant(box_area)},
        "within_image_log_iqr": {"mean": round(statistics.mean(spread), 4),
                                 "std": round(statistics.pstdev(spread), 4),
                                 **quant(spread)},
    }


def math_log(x):
    import math
    return math.log(max(x, 1e-6))


def read_real_train():
    per_image = []
    split = os.path.join(ROOT, "train.txt")
    stems = []
    if os.path.exists(split):
        with open(split, "r", encoding="utf-8") as fh:
            stems = [s.strip() for s in fh if s.strip()]
    ldir = os.path.join(ROOT, "labels")
    for raw in stems:
        # train.txt 里是 "./images/train_0.jpg" —— 取 basename 再去扩展名
        stem = os.path.splitext(os.path.basename(raw))[0]
        p = os.path.join(ldir, stem + ".txt")
        if not os.path.exists(p):
            continue
        boxes = []
        with open(p, "r", encoding="utf-8") as fh:
            for line in fh:
                q = line.split()
                if len(q) >= 5:
                    boxes.append((float(q[3]), float(q[4])))
        if boxes:
            per_image.append(boxes)
    return per_image


def read_synth(label_dir):
    per_image = []
    if not os.path.isdir(label_dir):
        return per_image
    for f in sorted(os.listdir(label_dir)):
        if not f.endswith(".txt"):
            continue
        boxes = []
        with open(os.path.join(label_dir, f), "r", encoding="utf-8") as fh:
            for line in fh:
                q = line.split()
                if len(q) >= 5:
                    boxes.append((float(q[3]), float(q[4])))
        if boxes:
            per_image.append(boxes)
    return per_image


def main():
    real = read_real_train()
    synth = read_synth(os.path.join(BENCH, "synth_single", "labels", "train"))
    out = {
        "schema": "real_shape_profile/1",
        "measured_at": "2026-11-23",
        "source": "SKU-110K train 标签 (真实域) vs output/benchmark/synth_single (R1 对照)",
        "note": ("宽高比 = 框宽/框高 (归一化坐标); 面积 = 框宽*框高 (归一化, 即占图面积比例)。"
                 "per_image_median_aspect 是 23 号 domain_gap 用的那个统计量 (逐图中位数的均值)。"),
        "real": shape_stats(real),
        "synth_r1": shape_stats(synth),
    }
    p = os.path.join(BENCH, "real_shape_profile.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    r, s = out["real"], out["synth_r1"]
    print(f"[SHAPE] 真实: 逐图中位宽高比 mean {r['per_image_median_aspect']['mean']} "
          f"(p10 {r['per_image_median_aspect']['p10']}, p50 {r['per_image_median_aspect']['p50']}, "
          f"p90 {r['per_image_median_aspect']['p90']}), 单框面积 mean {r['per_box_area']['mean']}")
    print(f"[SHAPE] R1  : 逐图中位宽高比 mean {s['per_image_median_aspect']['mean']} "
          f"(p10 {s['per_image_median_aspect']['p10']}, p50 {s['per_image_median_aspect']['p50']}, "
          f"p90 {s['per_image_median_aspect']['p90']}), 单框面积 mean {s['per_box_area']['mean']}")
    print(f"[SHAPE] -> {p}")


if __name__ == "__main__":
    main()
