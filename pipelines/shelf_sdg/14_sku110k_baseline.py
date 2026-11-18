#!/usr/bin/env python3
"""P0-1 真实货架基准四臂对照 (reviews/gpt_review_32 P0-1 + gpt_review_35 四臂设计)。

固定协议 (所有臂一致, 禁止单臂调参):
  检测器 YOLO11n · imgsz 640 · epochs 15 · batch 8 · seed 42 · MPS · max_det 1000 (密集货架)
  评测: SKU-110K 官方 test split — mAP@0.5 / mAP@0.5:0.95 / P / R +
        600 张计数指标 (MAE / MAPE / Pearson r)
臂:
  r0 真实数据 (SKU-110K train)          — 强基线能达到什么水平
  r1 仅合成 (本项目 SDG 单类化)          — 合成数据独立真实泛化能力
  r2 真实+合成                           — 合成是否带来增量
  r3 真实+改进SDG (P0-2 落地后)          — 分割/可见性过滤的因果贡献 (占位, 待 P0-2)
输出: output/benchmark/sku110k_<arm>.json (含协议哈希, 负结果也照实写)
用法: python3 14_sku110k_baseline.py --arm r0
"""
import hashlib
import json
import os
import sys
import time

# MPS 内存纪律: 不用 HIGH_WATERMARK_RATIO (语义为 >=1, 设 <1 会 RuntimeError);
# 靠 batch=2/threads=2 + 串行 + mem_guard 控 footprint (2026-11-09 实测 118GB 预留事件后修订)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
SDG = os.path.join(BASE, "output", "sdg_shelf")
SYNTH_SINGLE = os.path.join(BENCH, "synth_single")

PROTOCOL = {
    "model": "yolo11n.pt",
    "imgsz": 640,
    "epochs": 10,      # 2026-11-08 内存止损修订: 15->10, 四臂同改保持协议内部一致
    "batch": 4,        # 内存约束下调 (原 8)
    "workers": 2,
    "cache": False,
    "seed": 42,
    "max_det": 1000,
    "device": "mps",
}


def available_gb():
    """macOS 可用内存 GB (vm_stat free + inactive + speculative + purgeable 近似)。"""
    import subprocess
    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    pg = {}
    for ln in out.splitlines():
        if ":" in ln:
            k, v = ln.split(":")
            try:
                pg[k.strip()] = int(v.strip().rstrip("."))
            except ValueError:
                pass
    import re
    m = re.search(r"page size of (\d+) bytes", out)
    ps = int(m.group(1)) if m else 16384
    free = pg.get("Pages free", 0) + pg.get("Pages inactive", 0) + pg.get("Pages speculative", 0)
    return free * ps / 1e9


def mem_guard(need_gb=18.0):
    """内存硬约束: 不足则降 batch/threads, 再不足拒跑 (不挤占用户系统)。"""
    import torch
    avail = available_gb()
    batch, workers, threads = PROTOCOL["batch"], PROTOCOL["workers"], 4
    if avail < need_gb:
        batch, workers, threads = 2, 1, 2
    if avail < 10.0:
        raise SystemExit(f"[MEM-GUARD] 可用 {avail:.1f}GB < 10GB, 拒跑以保护系统")
    torch.set_num_threads(threads)
    print(f"[MEM-GUARD] avail={avail:.1f}GB batch={batch} workers={workers} threads={threads}")
    return batch, workers


def protocol_hash():
    return hashlib.sha256(json.dumps(PROTOCOL, sort_keys=True).encode()).hexdigest()[:16]


def build_synth_single():
    """SDG 4 类 -> 单类 product (丢弃 OOS gap 框), 输出 YOLO 目录 + yaml。"""
    import shutil
    os.makedirs(SYNTH_SINGLE, exist_ok=True)
    for split in ("train", "val"):
        img_src = os.path.join(SDG, "images", split)
        lab_src = os.path.join(SDG, "labels", split)
        img_dst = os.path.join(SYNTH_SINGLE, "images", split)
        lab_dst = os.path.join(SYNTH_SINGLE, "labels", split)
        os.makedirs(img_dst, exist_ok=True)
        os.makedirs(lab_dst, exist_ok=True)
        if not os.path.isdir(img_src):
            continue
        for f in os.listdir(img_src):
            shutil.copy2(os.path.join(img_src, f), os.path.join(img_dst, f))
            src_txt = os.path.join(lab_src, f.replace(".png", ".txt"))
            dst_txt = os.path.join(lab_dst, f.replace(".png", ".txt"))
            lines = []
            if os.path.exists(src_txt):
                for ln in open(src_txt):
                    p = ln.split()
                    if len(p) == 5 and p[0] != "1":      # 1 = OOS gap, 非商品
                        lines.append("0 " + " ".join(p[1:]))
            with open(dst_txt, "w") as fh:
                fh.write("\n".join(lines) + ("\n" if lines else ""))
    yaml_path = os.path.join(SYNTH_SINGLE, "dataset.yaml")
    with open(yaml_path, "w") as f:
        f.write(f"path: {SYNTH_SINGLE}\ntrain: images/train\nval: images/val\nnc: 1\nnames: [product]\n")
    return yaml_path


def symlink_real(split):
    """从 SKU-110K 官方 <split>.txt 建符号链接目录 (零拷贝拼混合集)。"""
    root = "/opt/homebrew/datasets/SKU-110K"
    dst = os.path.join(BENCH, f"real_{split}_sym")
    for sub in ("images", "labels"):
        d = os.path.join(dst, sub)
        os.makedirs(d, exist_ok=True)
    names = [l.strip() for l in open(os.path.join(root, f"{split}.txt")) if l.strip()]
    for n in names:
        stem = os.path.splitext(os.path.basename(n))[0]
        for sub, ext in (("images", ".jpg"), ("labels", ".txt")):
            src = os.path.join(root, sub, stem + ext)
            if not os.path.exists(src):
                src = os.path.join(root, sub, n)
            lk = os.path.join(dst, sub, stem + ext)
            if os.path.exists(src) and not os.path.exists(lk):
                os.symlink(src, lk)
    return dst


def mixed_yaml(real_yaml, synth_yaml):
    rtr = symlink_real("train")
    rval = symlink_real("val")
    p = os.path.join(BENCH, "mixed.yaml")
    with open(p, "w") as f:
        f.write(f"path: {BASE}\n"
                f"train: [{os.path.join(rtr, 'images')}, {os.path.join(SYNTH_SINGLE, 'images', 'train')}]\n"
                f"val: {os.path.join(rval, 'images')}\nnc: 1\nnames: [product]\n")
    return p


def val_only(weights, arm):
    import torch
    torch.set_num_threads(2)
    from ultralytics import YOLO
    ev = YOLO(weights)
    m = ev.val(data="SKU-110K.yaml", split="test", imgsz=PROTOCOL["imgsz"],
               device=PROTOCOL["device"], max_det=PROTOCOL["max_det"], batch=2,
               project=os.path.join(BENCH, f"runs_{arm}"), name="val", exist_ok=True)
    rep = {"arm": arm, "protocol": PROTOCOL, "protocol_hash": protocol_hash(),
           "epochs_trained": PROTOCOL["epochs"], "map50": float(m.box.map50),
           "map50_95": float(m.box.map), "precision": float(m.box.mp),
           "recall": float(m.box.mr)}
    json.dump(rep, open(os.path.join(BENCH, f"sku110k_{arm}.json"), "w"), indent=2)
    print(f"[BENCH] {arm} map50={rep['map50']:.4f} map50-95={rep['map50_95']:.4f}")


def main():
    if "--resume" in sys.argv:
        arm = sys.argv[sys.argv.index("--resume") + 1]
        lowmem = "--lowmem" in sys.argv
        import torch
        torch.set_num_threads(2 if lowmem else 4)
        from ultralytics import YOLO
        m = YOLO(os.path.join(BENCH, f"runs_{arm}", "train", "weights", "last.pt"))
        m.train(resume=True, batch=2 if lowmem else PROTOCOL["batch"],
                workers=1 if lowmem else PROTOCOL["workers"])
        return
    if "--val-only" in sys.argv:
        w = sys.argv[sys.argv.index("--val-only") + 1]
        arm = sys.argv[sys.argv.index("--arm") + 1] if "--arm" in sys.argv else "r0"
        val_only(w, arm)
        return
    arm = "r0"
    if "--arm" in sys.argv:
        arm = sys.argv[sys.argv.index("--arm") + 1]
    os.makedirs(BENCH, exist_ok=True)
    from ultralytics import YOLO

    if arm == "r0":
        data = "SKU-110K.yaml"
    elif arm == "r1":
        data = build_synth_single()
    elif arm == "r2":
        build_synth_single()
        data = mixed_yaml("SKU-110K.yaml", None)
    else:
        raise SystemExit("r3 待 P0-2 落地")

    t0 = time.time()
    model = YOLO(PROTOCOL["model"])
    batch, workers = mem_guard()
    model.train(data=data, epochs=PROTOCOL["epochs"], imgsz=PROTOCOL["imgsz"],
                batch=batch, seed=PROTOCOL["seed"], device=PROTOCOL["device"],
                workers=workers, cache=PROTOCOL["cache"],
                project=os.path.join(BENCH, f"runs_{arm}"), name="train", exist_ok=True)
    best = os.path.join(BENCH, f"runs_{arm}", "train", "weights", "best.pt")
    ev = YOLO(best)
    metrics = ev.val(data="SKU-110K.yaml", split="test", imgsz=PROTOCOL["imgsz"],
                     device=PROTOCOL["device"], max_det=PROTOCOL["max_det"],
                     project=os.path.join(BENCH, f"runs_{arm}"), name="val", exist_ok=True)
    report = {
        "arm": arm,
        "protocol": PROTOCOL,
        "protocol_hash": protocol_hash(),
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
        "precision": float(metrics.box.mp),
        "recall": float(metrics.box.mr),
        "wall_sec": round(time.time() - t0, 1),
        "note": "counting metrics (MAE/MAPE/Pearson) 见后续 count_eval 步骤",
    }
    with open(os.path.join(BENCH, f"sku110k_{arm}.json"), "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[BENCH] {arm} map50={report['map50']:.4f} map50-95={report['map50_95']:.4f} "
          f"P={report['precision']:.3f} R={report['recall']:.3f} wall={report['wall_sec']}s")


if __name__ == "__main__":
    main()
