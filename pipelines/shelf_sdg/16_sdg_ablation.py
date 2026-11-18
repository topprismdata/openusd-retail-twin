#!/usr/bin/env python3
"""P0-3 合成-真实域差距预注册消融 (output/benchmark/domain_gap_measure.json 三因子)。

因子 (测量自 SKU-110K val vs 我们 SDG val):
  A1 密度: 真实 152 框/图 vs 合成 25  → 相机拉远+广角, 多排多列入视
  A2 尺度: 真实框面积 0.0027 vs 0.0065 → 同 A1 相机参数 (框变小)
  A3 朝向: 真实宽高比 p50 0.55 (混朝向) vs 0.29 (仅立砖) → 提高侧立/倾倒混入概率
预注册臂 (固定协议同 14: YOLO11n/640/15ep/seed42/max_det1000, 评测 SKU-110K test):
  R3-base : 当前 SDG 参数
  R3-A12  : 密度+尺度修正 (cam_dist x2.2, lens 35)
  R3-A3   : 朝向混入 (misalign 10% -> 35%)
  R3-full : A12+A3
判读: 各臂 vs R1(纯合成旧参数) 在真实 test 的 mAP@0.5 增量 = 因子因果贡献。
用法: python3 16_sdg_ablation.py --arm R3-A12   (生成+训练+评测, 需 GPU 空闲)
密度注: 密度因子(25->152框/图)需多联货架墙场景扩展, 单相机因子仅到~30; 该子因子另立 A1b 臂。
"""
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"

ARMS = {
    "R3-base": dict(num=400, cam_mult=1.0, lens=50, misalign=0.10, bays=1),
    "R3-A12":  dict(num=400, cam_mult=1.6, lens=40, misalign=0.10, bays=1),
    "R3-A3":   dict(num=400, cam_mult=1.0, lens=50, misalign=0.35, bays=1),
    "R3-full": dict(num=400, cam_mult=1.6, lens=40, misalign=0.35, bays=5),
}


def generate(arm):
    cfg = ARMS[arm]
    out = os.path.join(BENCH, f"sdg_{arm}")
    cmd = [BLENDER, "-b", "-P", os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"), "--",
           "--num-images", str(cfg["num"]), "--seed", "42",
           "--cam-mult", str(cfg["cam_mult"]), "--lens", str(cfg["lens"]),
           "--misalign", str(cfg["misalign"]), "--bays", str(cfg["bays"]), "--out", out]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit(f"SDG gen failed for {arm}")
    return out


def to_single(src):
    """4 类 -> 单类 product (丢 gap), 复用 14 的转换逻辑。"""
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("b14", os.path.join(BASE, "14_sku110k_baseline.py"))
    m14 = ilu.module_from_spec(spec)
    spec.loader.exec_module(m14)
    import shutil
    dst = os.path.join(BENCH, f"synth_single_{arm_global}")
    os.makedirs(dst, exist_ok=True)
    for split in ("train", "val"):
        isrc = os.path.join(src, "images", split)
        lsrc = os.path.join(src, "labels", split)
        idst = os.path.join(dst, "images", split)
        ldst = os.path.join(dst, "labels", split)
        os.makedirs(idst, exist_ok=True)
        os.makedirs(ldst, exist_ok=True)
        if not os.path.isdir(isrc):
            continue
        for f in os.listdir(isrc):
            shutil.copy2(os.path.join(isrc, f), os.path.join(idst, f))
            lines = []
            t = os.path.join(lsrc, f.replace(".png", ".txt"))
            if os.path.exists(t):
                for ln in open(t):
                    p = ln.split()
                    if len(p) == 5 and p[0] != "1":
                        lines.append("0 " + " ".join(p[1:]))
            open(os.path.join(ldst, f.replace(".png", ".txt")), "w").write(
                "\n".join(lines) + ("\n" if lines else ""))
    y = os.path.join(dst, "dataset.yaml")
    open(y, "w").write(f"path: {dst}\ntrain: images/train\nval: images/val\nnc: 1\nnames: [product]\n")
    return y


arm_global = None


def main():
    global arm_global
    arm = sys.argv[sys.argv.index("--arm") + 1] if "--arm" in sys.argv else "R3-base"
    arm_global = arm
    import importlib.util as ilu
    sp = ilu.spec_from_file_location("b14", os.path.join(BASE, "14_sku110k_baseline.py"))
    m14 = ilu.module_from_spec(sp)
    sp.loader.exec_module(m14)
    from ultralytics import YOLO
    yaml_path = to_single(generate(arm))
    batch, workers = m14.mem_guard()
    proto = {"model": "yolo11n.pt", "imgsz": 640, "epochs": 10, "batch": 4,
             "workers": 2, "cache": False, "seed": 42, "max_det": 1000, "device": "mps"}
    # 2026-11-09 协议同步修订: 与 14 一致 (10ep/batch4, 内存止损); R3-full 首跑用了 15/8, 已标注不一致
    model = YOLO(proto["model"])
    model.train(data=yaml_path, epochs=proto["epochs"], imgsz=proto["imgsz"],
                batch=batch, seed=proto["seed"], device=proto["device"], workers=workers,
                project=os.path.join(BENCH, f"runs_{arm}"), name="train", exist_ok=True)
    ev = YOLO(os.path.join(BENCH, f"runs_{arm}", "train", "weights", "best.pt"))
    r = ev.val(data="SKU-110K.yaml", split="test", imgsz=proto["imgsz"],
               device=proto["device"], max_det=proto["max_det"],
               project=os.path.join(BENCH, f"runs_{arm}"), name="val", exist_ok=True)
    rep = {"arm": arm, "factors": ARMS[arm], "protocol": proto,
           "map50": float(r.box.map50), "map50_95": float(r.box.map)}
    json.dump(rep, open(os.path.join(BENCH, f"sku110k_{arm}.json"), "w"), indent=2)
    print(f"[ABLATION] {arm} map50={rep['map50']:.4f} map50-95={rep['map50_95']:.4f}")


if __name__ == "__main__":
    main()
