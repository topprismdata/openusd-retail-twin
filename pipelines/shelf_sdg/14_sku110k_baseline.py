#!/usr/bin/env python3
"""P0-1 真实货架基准四臂对照 (reviews/gpt_review_32 P0-1 + gpt_review_35 四臂设计)。

固定协议 (所有臂一致, 禁止单臂调参):
  检测器 YOLO11n · imgsz 640 · epochs 10 · batch 4 (mem_guard 可下调) · seed 42 · MPS/CUDA · max_det 1000 (密集货架)
  评测: SKU-110K 官方 test split — mAP@0.5 / mAP@0.5:0.95 / P / R +
        600 张计数指标 (MAE / MAPE / Pearson r)
  2026-11-18 审计修订: 产物新增 dataset.synth_ratio (实际训练集组成) 与
  actual_train_config (实际 epochs/batch), 避免"混合比"与"协议一致性"不可核验。
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
import shutil
import sys
import time

# MPS 内存纪律: 不用 HIGH_WATERMARK_RATIO (语义为 >=1, 设 <1 会 RuntimeError);
# 靠 batch=2/threads=2 + 串行 + mem_guard 控 footprint (2026-11-09 实测 118GB 预留事件后修订)

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import available_memory_gb, torch_device  # noqa: E402
from pipelines.common.protocol import (build_manifest, dir_fingerprint, file_fingerprint,  # noqa: E402
                                       file_sha256, runtime_versions, split_fingerprint, write_json)

BENCH = os.path.join(BASE, "output", "benchmark")
SDG = os.path.join(BASE, "output", "sdg_shelf")
SYNTH_SINGLE = os.path.join(BENCH, "synth_single")

# 2026-11-08 历史协议 (与已发布四臂数字 0.886/0.868/0.133 一一对应): device=mps
PROTOCOL_V1 = {
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
# v2 (2026-11-20): device 改为自动选择, 其余超参与 v1 完全一致 —— 四臂同改, 不做单臂调参。
# 旧哈希仍会随报告一起输出 (protocol_hash_legacy), 以便与历史数字对齐。
PROTOCOL = dict(PROTOCOL_V1, device="auto")


def mem_guard(need_gb=18.0):
    """内存硬约束: 不足则降 batch/threads, 再不足拒跑 (不挤占用户系统)。

    2026-11-20: 内存探测改用 runtime_env.available_memory_gb() (跨平台)。
    原实现直接 exec macOS 的 vm_stat, 在 Windows/Linux 上是 FileNotFoundError。
    """
    import torch
    avail = available_memory_gb()
    batch, workers, threads = PROTOCOL["batch"], PROTOCOL["workers"], 4
    if avail < need_gb:
        batch, workers, threads = 2, 1, 2
    if avail < 10.0:
        raise SystemExit(f"[MEM-GUARD] 可用 {avail:.1f}GB < 10GB, 拒跑以保护系统")
    torch.set_num_threads(threads)
    print(f"[MEM-GUARD] avail={avail:.1f}GB batch={batch} workers={workers} threads={threads}")
    return batch, workers


def resolve_device():
    """实际训练设备。协议声明 auto 时按 cuda > mps > cpu 自动选 (跨平台)。"""
    if PROTOCOL["device"] != "auto":
        return PROTOCOL["device"]
    dev = torch_device()
    print(f"[DEVICE] 协议 device=auto -> 实际 {dev}")
    return dev


def protocol_hash():
    return hashlib.sha256(json.dumps(PROTOCOL, sort_keys=True).encode()).hexdigest()[:16]


def sku110k_root():
    """SKU-110K 根目录: env SKU110K_ROOT > 原仓的 macOS Homebrew 路径。

    2026-11-20: 原代码把路径硬编码成 /opt/homebrew/... , 换机即失效。
    """
    return os.environ.get("SKU110K_ROOT", "/opt/homebrew/datasets/SKU-110K")


def sku110k_yaml():
    """评测集 yaml: env SKU110K_YAML > 默认 "SKU-110K.yaml"。

    2026-11-20: 便于换机/换评测集 (也用于端到端冒烟: 指向一个临时小评测集)。
    """
    return os.environ.get("SKU110K_YAML", "SKU-110K.yaml")


def dataset_composition(arm):
    """记录每个臂实际用了多少图/来自哪里 —— 缺它则"混合比"不可知 (审计 F2)。

    之前四臂 json 只记 protocol 与指标, 不记数据组成, 导致 R2 的合成占比无法还原。
    这里按 arm 统计可数到的图数并标注来源; 外部数据集 (SKU-110K) 的真实规模由
    调用方的 split 文件决定, 这里记录其路径与 split 名单指纹 (若有)。

    2026-11-20: 追加目录内容指纹 (sha256) 与 SDG 划分清单哈希 ——
    这样"数字是用哪份数据跑出来的"可事后核验, 不再只能靠人记。
    """
    import glob

    def n_images(path):
        return len(glob.glob(os.path.join(path, "*.jpg"))) + len(glob.glob(os.path.join(path, "*.png")))

    comp = {"arm": arm, "sources": []}
    if arm == "r0":
        comp["sources"].append({"kind": "real", "split": "train",
                                "yaml": sku110k_yaml(), "root": sku110k_root()})
    elif arm == "r1":
        comp["sources"].append({"kind": "synthetic_only",
                                "path": os.path.join(SYNTH_SINGLE, "images", "train"),
                                "n_images": n_images(os.path.join(SYNTH_SINGLE, "images", "train")),
                                "orig_sdg": os.path.join(SDG, "images", "train"),
                                "n_orig_images": n_images(os.path.join(SDG, "images", "train")),
                                "fingerprint": dir_fingerprint(os.path.join(SYNTH_SINGLE, "images", "train"))})
    elif arm == "r2":
        real_train = os.path.join(BENCH, "real_train_sym", "images")
        synth_train = os.path.join(SYNTH_SINGLE, "images", "train")
        n_real, n_syn = n_images(real_train), n_images(synth_train)
        comp["sources"].append({"kind": "real", "split": "train", "path": real_train,
                                "n_images": n_real, "yaml": sku110k_yaml(),
                                "fingerprint": dir_fingerprint(real_train)})
        comp["sources"].append({"kind": "synthetic", "path": synth_train, "n_images": n_syn,
                                "fingerprint": dir_fingerprint(synth_train)})
        total = n_real + n_syn
        comp["n_total_train"] = total
        comp["synth_ratio"] = (round(n_syn / total, 6) if total else None)
    # 合成集的划分清单 (2026-11-20): 记录 SDG 划分策略与指纹, 泄漏可事后查
    sm = os.path.join(SDG, "split_manifest.json")
    if os.path.exists(sm):
        comp["synth_split_manifest"] = {"path": os.path.relpath(sm, BASE),
                                        "sha256": file_sha256(sm)}
    comp["note"] = ("n_images 为本地可数到的图数; SKU-110K 的 split 定义在仓外, "
                    "真实总量需以 SKU-110K.yaml / <split>.txt 为准 (审计 F4)")
    return comp


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
    """从 SKU-110K 官方 <split>.txt 建链接目录 (拼混合集)。

    2026-11-20: 根目录改为 env SKU110K_ROOT (原代码硬编码 macOS Homebrew 路径);
    符号链接失败 (Windows 无开发者模式) 时退回复制, 不再整臂崩掉。
    """
    root = sku110k_root()
    dst = os.path.join(BENCH, f"real_{split}_sym")
    for sub in ("images", "labels"):
        d = os.path.join(dst, sub)
        os.makedirs(d, exist_ok=True)
    split_file = os.path.join(root, f"{split}.txt")
    if not os.path.exists(split_file):
        raise SystemExit(f"[DATA] 找不到 SKU-110K split 名单: {split_file}\n"
                         f"        用 env SKU110K_ROOT=<数据集根目录> 指定 (当前: {root})")
    names = [l.strip() for l in open(split_file) if l.strip()]
    n_copied = 0
    for n in names:
        stem = os.path.splitext(os.path.basename(n))[0]
        for sub, ext in (("images", ".jpg"), ("labels", ".txt")):
            src = os.path.join(root, sub, stem + ext)
            if not os.path.exists(src):
                src = os.path.join(root, sub, n)
            lk = os.path.join(dst, sub, stem + ext)
            if os.path.exists(src) and not os.path.exists(lk):
                try:
                    os.symlink(src, lk)
                except OSError:
                    shutil.copy2(src, lk)
                    n_copied += 1
    if n_copied:
        print(f"[DATA] {split}: {n_copied} 个文件以复制方式链接 (符号链接不可用)")
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


def model_weights_fingerprint(model, name):
    """模型权重文件的指纹 —— 协议里只写 "yolo11n.pt" 这个名字是不够的:
    同一名字在不同 ultralytics 版本下下载到的字节并不相同。
    """
    p = getattr(model, "ckpt_path", None)
    if not p or not os.path.isfile(p):
        p = os.path.abspath(name)
    return file_fingerprint(p, name=name)


def archive_checkpoint(arm, weights_path, selection):
    """把权重归档到 output/benchmark/weights/<arm>/ 并记录 sha256。

    2026-11-20 审计修复: 之前权重只落在 runs/ (被 .gitignore 排除),
    仓内无从校验"这个数字是用哪份权重跑出来的" —— 复现链断在这里。
    """
    if not weights_path or not os.path.isfile(weights_path):
        return {"selection": selection, "path": None, "sha256": None, "exists": False}
    dst_dir = os.path.join(BENCH, "weights", arm)
    os.makedirs(dst_dir, exist_ok=True)
    dst = os.path.join(dst_dir, os.path.basename(weights_path))
    shutil.copy2(weights_path, dst)
    return {"selection": selection, "path": os.path.relpath(dst, BASE).replace("\\", "/"),
            "sha256": file_sha256(dst), "bytes": os.path.getsize(dst), "exists": True}


def split_fingerprints(arm, synth_dir=None):
    """本臂训练/验证集的文件级指纹 (名称 + 内容)。

    2026-11-20: 指纹覆盖"用了哪些文件 + 文件内容是什么" —— 划分或内容被换掉都会被抓到。
    """
    out = {}
    if arm == "r0":
        root = sku110k_root()
        split_file = os.path.join(root, "train.txt")
        if os.path.exists(split_file):
            names = [l.strip() for l in open(split_file) if l.strip()]
            out["train"] = split_fingerprint(
                [(os.path.basename(n), os.path.join(root, "images", os.path.basename(n)))
                 for n in names])
        else:
            out["train"] = {"n": 0, "note": "SKU-110K split 名单不在本机, 仓内不可核验"}
    elif arm in ("r1", "r2"):
        base = synth_dir or SYNTH_SINGLE
        for split in ("train", "val"):
            d = os.path.join(base, "images", split)
            items = [(f, os.path.join(d, f)) for f in sorted(os.listdir(d))] if os.path.isdir(d) else []
            out[split] = split_fingerprint(items)
    return out


def val_only(weights, arm):
    import torch
    torch.set_num_threads(2)
    from ultralytics import YOLO
    device = resolve_device()
    ev = YOLO(weights)
    m = ev.val(data=sku110k_yaml(), split="test", imgsz=PROTOCOL["imgsz"],
               device=device, max_det=PROTOCOL["max_det"], batch=2,
               project=os.path.join(BENCH, f"runs_{arm}"), name="val", exist_ok=True)
    rep = {"arm": arm, "protocol": PROTOCOL, "protocol_hash": protocol_hash(),
           "epochs_trained": PROTOCOL["epochs"], "map50": float(m.box.map50),
           "map50_95": float(m.box.map), "precision": float(m.box.mp),
           "recall": float(m.box.mr),
           "actual_train_config": {"device": device},
           "checkpoint": archive_checkpoint(arm, weights, "given"),
           "protocol_manifest": build_manifest(
               PROTOCOL,
               data=dataset_composition(arm),
               splits=split_fingerprints(arm),
               actual={"device": device, "mode": "val-only"},
               deps=runtime_versions())}
    write_json(os.path.join(BENCH, f"sku110k_{arm}.json"), rep)
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
    # 2026-11-20: 权重选择可显式指定。默认 best (与历史协议一致);
    # R1 (纯合成) 用合成 val 选 best 会偏乐观, 想避免就传 --select last。
    selection = "best"
    if "--select" in sys.argv:
        selection = sys.argv[sys.argv.index("--select") + 1]
        if selection not in ("best", "last"):
            raise SystemExit("--select 只能是 best 或 last")
    # 2026-11-20: epochs 可显式覆盖 —— 覆盖值会写进 protocol 字典, 因而进 protocol_hash,
    # 不会再出现"实跑 15ep / 协议写 10ep"这种事后才发现的不一致 (审计: R3-full 首跑)。
    if "--epochs" in sys.argv:
        PROTOCOL["epochs"] = int(sys.argv[sys.argv.index("--epochs") + 1])
        print(f"[PROTOCOL] epochs 覆盖为 {PROTOCOL['epochs']} (已计入 protocol_hash)")
    # 2026-11-22: --seed 覆盖训练随机种子 (多种子复跑用)。seed 是协议的一部分,
    # 覆盖后 protocol_hash 随之改变 → 不同 seed 的产物天然可区分。
    if "--seed" in sys.argv:
        PROTOCOL["seed"] = int(sys.argv[sys.argv.index("--seed") + 1])
        print(f"[PROTOCOL] seed 覆盖为 {PROTOCOL['seed']} (已计入 protocol_hash)")
    os.makedirs(BENCH, exist_ok=True)
    from ultralytics import YOLO

    if arm == "r0":
        data = sku110k_yaml()
    elif arm == "r1":
        data = build_synth_single()
    elif arm == "r2":
        build_synth_single()
        data = mixed_yaml(sku110k_yaml(), None)
    else:
        raise SystemExit("r3 待 P0-2 落地")

    # 2026-11-21: --arm-tag 给复跑一个后缀 (敏感性检查), 产物写 runs_<arm>_<tag>/ 与
    # sku110k_<arm>_<tag>.json, **不覆盖**已发布的臂产物; 数据语义仍由 arm 决定。
    arm_tag = ""
    if "--arm-tag" in sys.argv:
        arm_tag = sys.argv[sys.argv.index("--arm-tag") + 1].strip()
    run_id = f"{arm}_{arm_tag}" if arm_tag else arm

    t0 = time.time()
    model = YOLO(PROTOCOL["model"])
    model_fp = model_weights_fingerprint(model, PROTOCOL["model"])
    batch, workers = mem_guard()
    device = resolve_device()
    model.train(data=data, epochs=PROTOCOL["epochs"], imgsz=PROTOCOL["imgsz"],
                batch=batch, seed=PROTOCOL["seed"], device=device,
                workers=workers, cache=PROTOCOL["cache"],
                project=os.path.join(BENCH, f"runs_{run_id}"), name="train", exist_ok=True)
    ckpt = os.path.join(BENCH, f"runs_{run_id}", "train", "weights", f"{selection}.pt")
    ev = YOLO(ckpt)
    metrics = ev.val(data=sku110k_yaml(), split="test", imgsz=PROTOCOL["imgsz"],
                     device=device, max_det=PROTOCOL["max_det"],
                     project=os.path.join(BENCH, f"runs_{run_id}"), name="val", exist_ok=True)
    wall = round(time.time() - t0, 1)
    # 只算一次, 顶层与 manifest 共用同一份 (避免重复哈希/重复拷贝, 也保证两处一致)
    composition = dataset_composition(arm)
    ckpt_info = archive_checkpoint(run_id, ckpt, selection)
    report = {
        "arm": arm,
        "run_id": run_id,
        "dataset": composition,
        # 顶层的 protocol_hash 是**历史口径** (只哈希协议字典), 与已发布四臂一致;
        # 完整口径 (协议+数据+划分+实跑配置+依赖+权重+权重选择) 见 protocol_hash_full。
        "protocol_hash_full": None,   # 下面 manifest 建好后回填
        "actual_train_config": {"epochs": PROTOCOL["epochs"], "batch": batch,
                                 "workers": workers, "device": device},
        "protocol": PROTOCOL,
        "protocol_hash": protocol_hash(),
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
        "precision": float(metrics.box.mp),
        "recall": float(metrics.box.mr),
        "wall_sec": wall,
        "checkpoint": ckpt_info,
        "model_weights": model_fp,
        "protocol_manifest": build_manifest(
            PROTOCOL,
            data=composition,
            splits=split_fingerprints(arm),
            actual={"epochs": PROTOCOL["epochs"], "batch": batch, "workers": workers,
                     "device": device, "wall_sec": wall, "checkpoint_selection": selection},
            deps=runtime_versions(),
            checkpoint=ckpt_info,
            extra={"protocol_v1": PROTOCOL_V1,
                   "model_weights": model_fp,
                   "note": "protocol_hash 覆盖协议+数据+划分+实跑配置+依赖+权重+模型权重文件; "
                           "protocol_hash_legacy 对应 2026-11-08 历史数字"}),
        "note": "counting metrics (MAE/MAPE/Pearson) 见后续 count_eval 步骤",
    }
    report["protocol_hash_full"] = report["protocol_manifest"]["protocol_hash"]
    write_json(os.path.join(BENCH, f"sku110k_{run_id}.json"), report)
    print(f"[BENCH] {run_id} map50={report['map50']:.4f} map50-95={report['map50_95']:.4f} "
          f"P={report['precision']:.3f} R={report['recall']:.3f} wall={report['wall_sec']}s "
          f"hash={report['protocol_manifest']['protocol_hash']}")


if __name__ == "__main__":
    main()
