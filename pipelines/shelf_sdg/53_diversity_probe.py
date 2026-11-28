#!/usr/bin/env python
"""**多样性剂量探针**: 数量固定, 只变"有多少种分布" (2026-11-24)。

问题 (由 I-01 的结果逼出来的)
---------------------------
51 号实测: 纯合成臂在**自己池的 val** 上 mAP **0.995** (域内几乎完美拟合), 到真实 test
只有 **0.227** -> 合成数据完全可学, 77 pp 全是**跨域**差距; 且跨池 (同生成器不同配方)
也能到 0.92–0.97, 说明生成器内部参数变化学得动。

域内能拟合到 0.995, 意味着模型**背得下**这批数据 (160 张、一个货架模板,
layout_similarity 0.82 vs 真实 0.70)。于是关键问题不是"加多少张", 而是
**"加多少种分布"**:

  * 剂量轴 (已发布的 40/80/160 + 在跑的大池 2240) 只加**数量**, 分布不变;
  * 本探针只加**多样性**: 同样 160 张, 但来自 3 个不同配方的池。

对照设计 (数量相同, 只变多样性)
------------------------------
* 臂 `single_r1`: 一个池 (R1) 的 160 张 -> **复用已有权重** (runs_r1_s*), 不重训;
* 臂 `mixed3`: 三个池 (R1 / 形状 / R3pm) 各取 53/53/54 张 = 160 张 -> 重训。

两臂图数相同、协议相同 (yolo11n / 640 / 10 ep / batch 4 / 同一评测集与选模口径),
唯一差别是**分布数**。混合臂的选模 val 也是**混合的** (三个池各 13/13/14), 免得选模
偏向某一个池。

判据
----
* 混合臂跨域 mAP 显著高于单池臂 -> 合成数据的瓶颈是**多样性**, 不是数量 ->
  论文建议从"加合成没用"改成"**加合成要加多样性**", 也解释了为什么纯数量剂量轴是平的;
* 两者都在噪声内 -> 分布混合不管用, 差距只能靠**外观真实度** (照片退化 / 纹理 / 场景类型)
  去啃 —— 那就如实写进"局限与下一步"。

产物: output/benchmark/diversity_probe.json / .md (26 号发布到 docs/research/benchmark/)

用法:
    python pipelines/shelf_sdg/53_diversity_probe.py --seeds 42,43,44
"""
import argparse
import glob
import json
import os
import random
import shutil
import statistics
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
WORK = os.path.join(BENCH, "diversity")

POOLS = [
    ("r1", os.path.join(BENCH, "synth_single")),
    ("shape", os.path.join(BENCH, "synth_single_shape")),
    ("r3pm", os.path.join(BENCH, "synth_single_R3pm")),
]
TOTAL_TRAIN = 160          # 与单池臂的图数完全相同
TOTAL_VAL = 40             # 混合选模 val 的总张数


def log(m):
    print(f"[DIV {time.strftime('%m-%d %H:%M:%S')}] {m}", flush=True)


def _sample(items, n, seed):
    idx = list(range(len(items)))
    random.Random(seed).shuffle(idx)
    return [items[i] for i in sorted(idx[:n])]


def build_mixed(seed=20261124):
    """写混合名单 + yaml (不拷图: yaml 里直接列图片路径清单)。"""
    os.makedirs(WORK, exist_ok=True)
    per_train = [53, 53, 54]
    per_val = [13, 13, 14]
    train_lists, val_lists = [], []
    for (name, pool), ntr, nva in zip(POOLS, per_train, per_val):
        for split, n, sink in (("train", ntr, train_lists), ("val", nva, val_lists)):
            d = os.path.join(pool, "images", split)
            imgs = sorted(glob.glob(os.path.join(d, "*.png")))
            if not imgs:
                raise SystemExit(f"[DIV] 池 {name} 没有 {split} 图: {d}")
            picked = _sample(imgs, n, seed + hash((name, split)) % 10000)
            lp = os.path.join(WORK, f"mix_{name}_{split}.txt")
            with open(lp, "w", encoding="utf-8") as fh:
                fh.write("\n".join(picked) + "\n")
            sink.append(lp)
    yaml_path = os.path.join(WORK, "mixed3.yaml")
    with open(yaml_path, "w", encoding="utf-8") as fh:
        fh.write(f"path: {BASE}\n")
        fh.write("train: [" + ", ".join(train_lists) + "]\n")
        fh.write("val: [" + ", ".join(val_lists) + "]\n")
        fh.write("nc: 1\nnames: [product]\n")
    # 混合臂的标签统计 (与单池臂对照时要说清差别)
    stats = {}
    for (name, pool), lp in zip(POOLS, train_lists):
        n_boxes = 0
        n_imgs = 0
        for line in open(lp, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            n_imgs += 1
            lt = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(lp))), "")
            lab = line.replace(os.sep + "images" + os.sep, os.sep + "labels" + os.sep)
            lab = os.path.splitext(lab)[0] + ".txt"
            if os.path.exists(lab):
                n_boxes += sum(1 for x in open(lab, encoding="utf-8") if x.strip())
        stats[name] = {"n_images": n_imgs, "n_boxes": n_boxes,
                       "boxes_per_image": round(n_boxes / max(1, n_imgs), 2)}
    meta = {"pools": [p[0] for p in POOLS], "per_pool_train": per_train,
            "per_pool_val": per_val, "yaml": yaml_path,
            "list_files": {"train": train_lists, "val": val_lists},
            "label_stats": stats, "seed": seed}
    with open(os.path.join(BENCH, "diversity_mix_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    log(f"混合池 yaml -> {yaml_path}; 各池 {stats}")
    return yaml_path, meta


def _labels_stats(pools_meta=None):
    return pools_meta or {}


def train_and_eval(yaml_path, seeds, arm, control_runs=None):
    """训练 (或复用对照臂权重) 并在真实 test 上评测。"""
    from ultralytics import YOLO
    real_yaml = os.environ.get("SKU110K_YAML", "SKU-110K.yaml")
    device = "cuda:0"
    out = []
    for seed in seeds:
        if control_runs:
            ckpt = os.path.join(BENCH, control_runs.format(seed=seed),
                                "train", "weights", "best.pt")
            if not os.path.isfile(ckpt):
                log(f"对照权重缺失, 跳过 seed {seed}: {ckpt}")
                continue
        else:
            run = os.path.join(BENCH, f"runs_diversity_s{seed}")
            ckpt = os.path.join(run, "train", "weights", "best.pt")
            if not os.path.isfile(ckpt):
                model = YOLO("yolo11n.pt")
                model.train(data=yaml_path, epochs=10, imgsz=640, batch=4, seed=seed,
                            device=device, workers=2, cache=False,
                            project=run, name="train", exist_ok=True, verbose=False)
        m = YOLO(ckpt)
        r = m.val(data=real_yaml, split="test", imgsz=640, batch=4, device=device,
                  max_det=1000, workers=2, verbose=False)
        out.append({"seed": seed, "map50": float(r.box.map50),
                    "map50_95": float(r.box.map),
                    "checkpoint": os.path.relpath(ckpt, BASE).replace("\\", "/")})
        log(f"{arm} seed {seed}: 真实 test mAP50 = {out[-1]['map50']:.4f}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="42,43,44")
    ap.add_argument("--stage", choices=("mix", "train", "all"), default="all")
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    yaml_path, meta = (None, None)
    if args.stage in ("mix", "all"):
        yaml_path, meta = build_mixed()
    else:
        yaml_path = os.path.join(WORK, "mixed3.yaml")
        mp = os.path.join(BENCH, "diversity_mix_meta.json")
        meta = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}
    if args.stage in ("train", "all"):
        mixed = train_and_eval(yaml_path, seeds, "mixed3")
        # 对照: 单池臂 (R1 配方) 的已有权重, 用**同一套评测流程**重评 (不是抄发布数字)
        control = train_and_eval(None, seeds, "single_r1",
                                 control_runs="runs_r1_s{seed}")
        def agg(recs):
            if not recs:
                return None
            v = [r["map50"] for r in recs]
            return {"mean": round(statistics.mean(v), 4),
                    "sd": round(statistics.stdev(v), 4) if len(v) > 1 else 0.0,
                    "n": len(v), "per_seed": {str(r["seed"]): r["map50"] for r in recs}}
        rep = {"schema": "diversity_probe/1",
               "generated_by": "pipelines/shelf_sdg/53_diversity_probe.py",
               "measured_at": "2026-11-24",
               "question": ("数量固定 (160 张), 单池 vs 三池混合 -> 合成数据的瓶颈是"
                            "数量还是多样性?"),
               "design": {"total_train_images": TOTAL_TRAIN,
                          "pools": [p[0] for p in POOLS],
                          "mix": meta.get("label_stats")},
               "single_r1": agg(control),
               "mixed3": agg(mixed)}
        a, b = rep["single_r1"], rep["mixed3"]
        if a and b:
            diffs = [b["per_seed"][s] - a["per_seed"][s]
                     for s in b["per_seed"] if s in a["per_seed"]]
            rep["paired_diff_pp"] = [round(x * 100, 3) for x in diffs]
            if len(diffs) > 1:
                mean = statistics.mean(diffs)
                sd = statistics.stdev(diffs)
                hw = 1.96 * sd / (len(diffs) ** 0.5)
                rep["paired_mean_pp"] = round(mean * 100, 3)
                rep["paired_ci95_pp"] = [round((mean - hw) * 100, 3),
                                         round((mean + hw) * 100, 3)]
        with open(os.path.join(BENCH, "diversity_probe.json"), "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        os.makedirs(PUB, exist_ok=True)
        shutil.copy2(os.path.join(BENCH, "diversity_probe.json"),
                     os.path.join(PUB, "diversity_probe.json"))
        lines = ["# 多样性剂量探针 (2026-11-24)", "",
                 f"同样 {TOTAL_TRAIN} 张训练图, 一个池 vs 三个池混合。", "",
                 "| 臂 | 真实 test mAP@0.5 (mean ± sd) | n |", "|---|---|---:|"]
        for k, label in (("single_r1", "单池 (R1, 160 张)"),
                         ("mixed3", "三池混合 (53+53+54)")):
            v = rep.get(k)
            lines.append(f"| {label} | {v['mean']:.4f} ± {v['sd']:.4f} | {v['n']} |"
                         if v else f"| {label} | — | 0 |")
        if "paired_mean_pp" in rep:
            ci = rep["paired_ci95_pp"]
            lines += ["", f"配对差值 (混合 − 单池): **{rep['paired_mean_pp']:+.2f} pp**, "
                      f"95% CI [{ci[0]:+.2f}, {ci[1]:+.2f}] (n={len(diffs)})",
                      "", "**读法**: CI 整段 > 0 -> 瓶颈是**多样性**不是数量; 跨 0 -> "
                      "分布混合没用, 差距只能靠外观真实度。"]
        with open(os.path.join(BENCH, "diversity_probe.md"), "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        shutil.copy2(os.path.join(BENCH, "diversity_probe.md"),
                     os.path.join(PUB, "diversity_probe.md"))
        print("\n" + "\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
