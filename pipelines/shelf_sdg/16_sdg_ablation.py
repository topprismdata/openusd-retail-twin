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
2026-11-21 注 (审计 F6 场景级留出): SDG 生成器现在默认按**场景族**生成 ——
每个场景在 层位/上架 bay/SKU 配比/灯光/相机位姿/错位率 上随机, 场景参数由
(base_seed, scene_idx) 派生, train/val 场景集合不相交。本消融的四个臂**共享同一套
场景随机化分布**, 臂间差异仍只来自臂级参数 (cam_mult/lens/misalign/bays);
但 "bays=N" 现在意为 "N 个 bay 可用, 每个场景随机上架其中一部分", 解读时需按此口径。
"""
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import blender_command  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")

ARMS = {
    "R3-base": dict(num=400, cam_mult=1.0, lens=50, misalign=0.10, bays=1),
    "R3-A12":  dict(num=400, cam_mult=1.6, lens=40, misalign=0.10, bays=1),
    "R3-A3":   dict(num=400, cam_mult=1.0, lens=50, misalign=0.35, bays=1),
    "R3-full": dict(num=400, cam_mult=1.6, lens=40, misalign=0.35, bays=5),
}


def generate(arm):
    cfg = ARMS[arm]
    out = os.path.join(BENCH, f"sdg_{arm}")
    # 2026-11-23: blender_command() 而不是 blender_bin() —— Windows 上本机入口是
    # tools/blender.cmd (bpy pip 模块替身), 直接 exec .cmd 会 WinError 193。
    cmd = blender_command() + ["-b", "-P", os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"), "--",
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


def measure_domain_gap(synth_dir, real_root):
    """实测三个域差距因子 (A1 密度 / A2 尺度 / A3 朝向) 并落盘。

    2026-11-20 (审计: R1 归因不可核验): 原 docstring 声称输出
    output/benchmark/domain_gap_measure.json, 但脚本实际只写 sku110k_<arm>.json ——
    于是"纯合成为何迁移不了"的根因 (密度/尺度/朝向错配) 永远无法核验。
    这里真正把因子测出来: 合成侧来自 SDG 标签, 真实侧来自 SKU-110K 标注 CSV。
    """
    import glob
    import statistics as st

    def synth_stats():
        per_img, areas, aspects = [], [], []
        for lp in sorted(glob.glob(os.path.join(synth_dir, "labels", "*", "*.txt"))):
            n = 0
            for ln in open(lp):
                p = ln.split()
                if len(p) != 5:
                    continue
                n += 1
                bw, bh = float(p[3]), float(p[4])
                areas.append(bw * bh)
                aspects.append(bw / bh if bh else 0.0)
            per_img.append(n)
        return per_img, areas, aspects

    def real_stats():
        import csv
        from collections import defaultdict
        ann = os.path.join(real_root, "annotations", "annotations_test.csv")
        if not os.path.exists(ann):
            return None
        per_img = defaultdict(int)
        areas, aspects = [], []
        with open(ann) as f:
            for row in csv.reader(f):
                if not row or row[0].startswith("image") or len(row) < 5:
                    continue
                per_img[os.path.basename(row[0])] += 1
                try:
                    x1, y1, x2, y2 = (float(v) for v in row[1:5])
                except ValueError:
                    continue
                w, h = abs(x2 - x1), abs(y2 - y1)
                areas.append(w * h)
                aspects.append(w / h if h else 0.0)
        return list(per_img.values()), areas, aspects

    def med(xs):
        return round(float(st.median(xs)), 6) if xs else None

    def p50(xs):
        return med(xs)

    sp, sa, sx = synth_stats()
    rp, ra, rx = real_stats()
    out = {
        "schema": "domain_gap_measure/1",
        "arm": arm_global,
        "synth_dir": synth_dir,
        "real_root": real_root if rp is not None else None,
        "A1_density": {
            "boxes_per_image_synth": round(sum(sp) / len(sp), 2) if sp else None,
            "boxes_per_image_real": round(sum(rp) / len(rp), 2) if rp else None,
            "measured": rp is not None,
        },
        "A2_scale": {
            "box_area_p50_synth": med(sa), "box_area_p50_real": med(ra),
            "measured": rp is not None,
        },
        "A3_orientation": {
            "aspect_p50_synth": p50(sx), "aspect_p50_real": p50(rx),
            "measured": rp is not None,
        },
        "note": ("真实侧需要 SKU110K_ROOT 指向的数据集; 未提供时只出合成侧, "
                 "因子结论不可下 (审计: 归因必须可核验)"),
    }
    return out


def main():
    global arm_global
    arm = sys.argv[sys.argv.index("--arm") + 1] if "--arm" in sys.argv else "R3-base"
    seed = int(sys.argv[sys.argv.index("--seed") + 1]) if "--seed" in sys.argv else 42
    arm_global = arm
    epochs_override = int(sys.argv[sys.argv.index("--epochs") + 1]) if "--epochs" in sys.argv else None
    import importlib.util as ilu
    sp = ilu.spec_from_file_location("b14", os.path.join(BASE, "14_sku110k_baseline.py"))
    m14 = ilu.module_from_spec(sp)
    sp.loader.exec_module(m14)
    from ultralytics import YOLO
    yaml_path = to_single(generate(arm, seed))
    batch, workers = m14.mem_guard()
    # 2026-11-20: device 改自动选择 (原写死 mps, 在 Windows/NVIDIA 上直接不可用);
    # 协议其余项与 14 保持一致, 四臂/各 R3 臂同改, 不做单臂调参。
    proto = {"model": "yolo11n.pt", "imgsz": 640, "epochs": 10, "batch": 4,
             "workers": 2, "cache": False, "seed": seed, "max_det": 1000, "device": "auto"}
    if epochs_override:
        proto["epochs"] = epochs_override
        print(f"[PROTOCOL] epochs 覆盖为 {epochs_override} (已计入 protocol_hash)")
    device = m14.resolve_device()
    # 2026-11-09 协议同步修订: 与 14 一致 (10ep/batch4, 内存止损); R3-full 首跑用了 15/8, 已标注不一致
    model = YOLO(proto["model"])
    model_fp = m14.model_weights_fingerprint(model, proto["model"])
    model.train(data=yaml_path, epochs=proto["epochs"], imgsz=proto["imgsz"],
                batch=batch, seed=proto["seed"], device=device, workers=workers,
                project=os.path.join(BENCH, f"runs_{arm}"), name="train", exist_ok=True)
    ckpt = os.path.join(BENCH, f"runs_{arm}", "train", "weights", "best.pt")
    ev = YOLO(ckpt)
    r = ev.val(data=m14.sku110k_yaml(), split="test", imgsz=proto["imgsz"],
               device=device, max_det=proto["max_det"],
               project=os.path.join(BENCH, f"runs_{arm}"), name="val", exist_ok=True)
    rep = {"arm": arm, "factors": ARMS[arm], "protocol": proto,
           "actual_train_config": {"epochs": proto["epochs"], "batch": batch,
                                    "workers": workers, "device": device},
           "checkpoint": m14.archive_checkpoint(arm, ckpt, "best"),
           "model_weights": model_fp,
           "protocol_manifest": build_manifest(
               proto,
               data={"factors": ARMS[arm], "synth_dir": os.path.join(BENCH, f"synth_single_{arm}")},
               splits=m14.split_fingerprints("r1", synth_dir=os.path.join(BENCH, f"synth_single_{arm}")),
               actual={"epochs": proto["epochs"], "batch": batch, "workers": workers,
                        "device": device},
               deps=runtime_versions(),
               extra={"model_weights": model_fp}),
           "map50": float(r.box.map50), "map50_95": float(r.box.map)}
    write_json(os.path.join(BENCH, f"sku110k_{arm}.json"), rep)

    # 2026-11-20: 真正产出 domain_gap_measure.json (原 docstring 承诺但从未落盘)
    gap = measure_domain_gap(os.path.join(BENCH, f"synth_single_{arm}"), m14.sku110k_root())
    gap["protocol_manifest"] = rep["protocol_manifest"]
    write_json(os.path.join(BENCH, "domain_gap_measure.json"), gap)
    print(f"[ABLATION] {arm} map50={rep['map50']:.4f} map50-95={rep['map50_95']:.4f} "
          f"hash={rep['protocol_manifest']['protocol_hash']}")
    print(f"[ABLATION] 域差距实测 -> domain_gap_measure.json "
          f"(密度 {gap['A1_density']['boxes_per_image_synth']} 框/图, "
          f"真实侧{'已测' if gap['A1_density']['measured'] else '缺数据集, 未测'})")


if __name__ == "__main__":
    main()
