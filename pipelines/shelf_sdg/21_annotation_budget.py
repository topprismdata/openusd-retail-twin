#!/usr/bin/env python3
"""标注预算对照臂 (审计 F1): 合成数据到底能不能替代真实标注?

为什么需要这个脚本 (审计 F1):
    现有四臂里**没有任何一个臂减少过真实标注量** ——
    R2 = 全量真实 train + 合成追加, 所以 "R2≈R0 ⇒ 合成可替代手工标注" 是无效推论
    (合成占比 ≤5% 时 "R2≈R0" 是构造性必然)。
    要真正回答"替代", 需要一张 **标注预算曲线**: 在真实标注只剩 k 的前提下,
    加 N 张合成能不能把性能补回全量真实基线?

网格:
    (real_frac, synth_n) 每个格点独立训练, **同一个** 真实 test 集评测。

数据组成全部可事后核验:
    - 真实子集: 由 --budget-seed 派生的确定性**随机**抽样 (不是"取前 k 张", 避免顺序偏置),
      名单落 output/benchmark/budget/<cell>_real.txt (每行一个图路径), sha256 进报告;
    - 合成子集: 同法抽 N 张, 名单同样落盘 + 指纹;
    - 评测集: env SKU110K_YAML 指定的真实 test split (与四臂一致, 不变)。

输出:
    output/benchmark/budget_<realfrac>_<synthn>.json   单格点报告
    output/benchmark/budget_curve.json                 整条曲线
    output/benchmark/budget_curve.md                   论文可直接贴的表

用法:
    python pipelines/shelf_sdg/21_annotation_budget.py --fracs 1,0.5,0.25 --synth 0,400
    # 评测集: env SKU110K_YAML=<yaml> (默认 SKU-110K.yaml)
"""
import glob
import hashlib
import json
import os
import random
import sys
import time
from types import SimpleNamespace

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import available_memory_gb, torch_device  # noqa: E402
from pipelines.common.protocol import (build_manifest, file_sha256, runtime_versions,  # noqa: E402
                                       write_json)

BENCH = os.path.join(BASE, "output", "benchmark")
BUDGET_DIR = os.path.join(BENCH, "budget")
SDG = os.path.join(BASE, "output", "sdg_shelf")

PROTOCOL = {
    "model": "yolo11n.pt",
    "imgsz": 640,
    "epochs": 10,
    "batch": 4,
    "workers": 2,
    "cache": False,
    "seed": 42,
    "max_det": 1000,
    "device": "auto",
}
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp")


# --------------------------------------------------------------------------- 工具


def parse_args():
    argv = sys.argv[1:]
    def opt(name, default=None, cast=str):
        if name in argv:
            return cast(argv[argv.index(name) + 1])
        return default
    return SimpleNamespace(
        fracs=[float(x) for x in str(opt("--fracs", "1,0.5,0.25")).split(",") if x.strip()],
        synth=[int(x) for x in str(opt("--synth", "0,400")).split(",") if x.strip()],
        seed=int(opt("--seed", PROTOCOL["seed"])),
        budget_seed=int(opt("--budget-seed", 20261120)),
        epochs=int(opt("--epochs", PROTOCOL["epochs"])),
        select=str(opt("--select", "last")),
        yaml=os.environ.get("SKU110K_YAML", "SKU-110K.yaml"),
        synth_dir=str(opt("--synth-dir", os.path.join(SDG, "images", "train"))),
        # 2026-11-21: 多 seed 复跑时不覆盖既有格点 (run tag 后缀), 便于算方差
        run_tag=str(opt("--run-tag", "")),
        # 2026-11-21: --merge-only 只重算曲线表 (不再训练), 用于链跑完后补跑/刷新
        merge_only=("--merge-only" in argv),
        # 2026-11-25: --strict-protocol 禁止内存守卫静默降 batch (复现/对照类实验必须用)
        strict_protocol=("--strict-protocol" in argv),
        # 2026-11-25: --mem-need-gb 显式给内存守卫阈值 (默认 18 GB)。
        #   18 GB 是**渲大池期间**定的 (Blender 峰值 ~15 GB)。渲完之后机器上只剩
        #   浏览器/系统级进程, batch=4 的训练实测峰值 RSS ~2.5 GB -> 阈值可以下调,
        #   但**必须显式写出来**并记进产物, 不能让"静默降 batch"改掉协议
        #   (batch 4 -> 2 会让 mAP 与已发布数字不可比)。
        mem_need_gb=float(opt("--mem-need-gb", 18.0)),
    )


def load_yaml(path):
    """极简 dataset yaml 解析 (不依赖 PyYAML —— 训练环境里未必装了)。

    支持本仓用到的子集: `key: value` / `key: [a, b]` / 相对 path: 的相对路径。
    """
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.split("#")[0].strip()
            if not line or ":" not in line:
                continue
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                v = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
            out[k] = v
    return out


def resolve_split(y, key):
    """把 yaml 里的 split 路径解析成绝对目录 (相对 path: 基准)。"""
    val = y.get(key)
    if val is None:
        raise SystemExit(f"[DATA] 评测 yaml 缺少 '{key}'")
    if isinstance(val, (list, tuple)):
        val = val[0]
    val = str(val)
    if os.path.isabs(val):
        return val
    root = str(y.get("path", "."))
    return os.path.normpath(os.path.join(root, val))


def pool_fingerprint(d):
    """合成池的身份指纹 (2026-11-24 加)。

    为什么需要: `synth_subset_sha256` 记的是**这一档取的那 N 张**的名单指纹, 而剂量轴
    各档是**嵌套子集** -> 每档名单指纹都不同, 所以它不能用来判断"几个档来自同一个池"。
    剂量轴必须是单变量的 (池不变, 只变剂量), 所以产物要能回答"这批图是从哪个池抽的"。
    这里记池目录本身: 路径 + 图像文件名清单的 sha256 (不含像素, 够识别池的身份)。
    """
    if not d or not os.path.isdir(d):
        return None
    names = sorted(f for f in os.listdir(d)
                   if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")))
    h = hashlib.sha256()
    h.update(os.path.abspath(d).encode("utf-8"))
    for n in names:
        h.update(n.encode("utf-8"))
    return {"path": os.path.abspath(d), "n_images": len(names),
            "names_sha256": h.hexdigest()}


def list_images(d):
    """列出一个 split 的图像。

    支持两种形态 (SKU-110K 两种都有):
      - 目录 (yaml 里 `train: train/images`) → 按扩展名枚举;
      - 名单 txt (yaml 里 `train: train.txt`, 仓内 split 名单就是这种) → 逐行读。
    """
    if os.path.isfile(d) and d.lower().endswith(".txt"):
        root = os.path.dirname(d)
        out = []
        for line in open(d, encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            p = line if os.path.isabs(line) else os.path.join(root, line)
            if not os.path.splitext(p)[1].lower() in IMG_EXT:
                p += ".jpg"
            out.append(os.path.abspath(p))
        return sorted(out)
    if not os.path.isdir(d):
        raise SystemExit(f"[DATA] 目录不存在: {d}")
    files = [os.path.abspath(p) for p in glob.glob(os.path.join(d, "*"))
             if os.path.splitext(p)[1].lower() in IMG_EXT]
    return sorted(files)


def sample_subset(items, n, seed):
    """确定性随机抽样 (不用"取前 n 张" —— 那会让排序偏置混进结果)。"""
    if n is None or n >= len(items):
        return list(items)
    idx = list(range(len(items)))
    random.Random(seed).shuffle(idx)
    picked = sorted(idx[:n])
    return [items[i] for i in picked]


def write_list(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(items) + ("\n" if items else ""))
    return path


def mem_guard(need_gb=18.0, strict=False):
    """内存守卫: 内存不够时**降 batch** 以免 OOM。

    2026-11-25 加 `strict`: 降级 batch **不是无害的** (ultralytics 按 nbs/batch 缩放
    学习率), 一旦降级, 这次跑的数值就**不再与协议同配置**, 不能当证据。
    起因: 复现实验 (噪声底) 在与别的训练并发时被降级 (batch 4 -> 2), mAP 从
    0.7946 变成 0.7705, 差点被当成"重跑噪声"。
    strict=True 时**不静默降级**, 直接拒跑 —— 复现/对照类实验必须用它。
    """
    import torch
    avail = available_memory_gb()
    batch, workers, threads = PROTOCOL["batch"], PROTOCOL["workers"], 4
    if avail < need_gb:
        if strict:
            raise SystemExit(
                f"[MEM-GUARD(strict)] 可用内存 {avail:.1f}GB < {need_gb:.0f}GB, 拒跑: "
                f"降 batch 会让本次结果与协议不同配置 (protocol batch="
                f"{PROTOCOL['batch']}), 不能当证据。请先停掉并发的训练/渲染, "
                f"或显式去掉 --strict-protocol (并自行承担协议漂移)。")
        batch, workers, threads = 2, 1, 2
        print(f"[MEM-GUARD] ⚠️ 可用内存 {avail:.1f}GB < {need_gb:.0f}GB -> "
              f"batch {PROTOCOL['batch']} → {batch}, workers → {workers}。"
              f"本次结果**与协议不同配置**, 不能直接当证据。", flush=True)
    if avail < 10.0:
        raise SystemExit(f"[MEM-GUARD] 可用 {avail:.1f}GB < 10GB, 拒跑")
    torch.set_num_threads(threads)
    return batch, workers


def resolve_device():
    if PROTOCOL["device"] != "auto":
        return PROTOCOL["device"]
    return torch_device()


# --------------------------------------------------------------------------- 主流程


def load_existing_reports():
    """读 output/benchmark/ 下已有的格点 json (含 --run-tag 的多种子复跑)。"""
    import glob
    out = []
    for f in sorted(glob.glob(os.path.join(BENCH, "budget_real*_synth*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if d.get("dataset") and d.get("map50") is not None:
            out.append(d)
    return out


def build_curve(reports, args):
    """曲线表: 以 (real_frac=1, synth=0) 作基线, Δ 为相对基线的百分点差。

    2026-11-21: 同一格点可能有多个 seed 的复跑 (--run-tag) → 按格点聚合,
    报 mean ± std 与 seed 列表, 而不是把复跑当成不同的格点。
    """
    import statistics
    groups = {}
    for r in reports:
        c = r["dataset"]["cell"]
        key = (float(c["real_frac"]), int(c["synth_n"]))
        groups.setdefault(key, []).append(r)

    def agg(rs, k):
        xs = [x[k] for x in rs if x.get(k) is not None]
        if not xs:
            return None, None
        return statistics.mean(xs), (statistics.stdev(xs) if len(xs) > 1 else 0.0)

    base = None
    for key, rs in groups.items():
        if key == (1.0, 0):
            m, _ = agg(rs, "map50")
            base = {"map50": m, "map50_95": agg(rs, "map50_95")[0],
                    "n_real": rs[0]["dataset"]["n_real"]}
    cells = []
    for key in sorted(groups, key=lambda k: (-k[0], k[1])):
        rs = groups[key]
        m50, s50 = agg(rs, "map50")
        m95, s95 = agg(rs, "map50_95")
        cells.append({
            "cell": {"real_frac": key[0], "synth_n": key[1]},
            "n_runs": len(rs),
            "seeds": [r.get("protocol", {}).get("seed") for r in rs],
            "n_real": rs[0]["dataset"]["n_real"], "n_synth": rs[0]["dataset"]["n_synth"],
            "map50": m50, "map50_std": s50, "map50_95": m95, "map50_95_std": s95,
            "precision": agg(rs, "precision")[0], "recall": agg(rs, "recall")[0],
            "delta_map50_pp": (round((m50 - base["map50"]) * 100, 3) if base else None),
            "protocol_hash": rs[0]["protocol_hash"],
            "checkpoint_sha256": rs[0]["checkpoint"]["sha256"],
        })
    return {"schema": "annotation_budget_curve/1",
            "generated_by": "pipelines/shelf_sdg/21_annotation_budget.py",
            "source_yaml": args.yaml, "source_yaml_sha256": file_sha256(args.yaml)
            if os.path.isfile(args.yaml) else None,
            "protocol": dict(PROTOCOL, epochs=args.epochs, seed=args.seed),
            "baseline": base,
            "note": "Δ 为相对基线 (real_frac=1, synth=0) 的百分点差; "
                    "负值 = 少标注 + 合成仍掉的精度。同一格点的多次 seed 复跑已聚合为 mean ± std。",
            "cells": cells}


def write_curve(curve, args):
    write_json(os.path.join(BENCH, "budget_curve.json"), curve)
    lines = ["# 标注预算曲线 (合成能否替代真实标注)", "",
             "| 真实比例 | 真实图数 | 合成图数 | runs | mAP@0.5 | std | mAP@0.5:0.95 | Δ mAP@0.5 (pp) |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for c in curve["cells"]:
        d = f"{c['delta_map50_pp']:+.2f}" if c["delta_map50_pp"] is not None else "—"
        lines.append(f"| {c['cell']['real_frac']:g} | {c['n_real']} | {c['n_synth']} | "
                     f"{c['n_runs']} | {c['map50']:.4f} | {(c['map50_std'] or 0):.4f} | "
                     f"{c['map50_95']:.4f} | {d} |")
    lines += ["", f"- 评测集: `{args.yaml}` 的 test split (与四臂同一份)",
              f"- 真实子集为 seed={args.budget_seed} 的确定性随机抽样, 名单与 sha256 见各格点 json",
              f"- 预算曲线哈希: 每个格点的 `protocol_hash` 已记录 (含真实/合成子集指纹)",
              "- 多种子复跑 (--run-tag) 已按格点聚合为 mean ± std; 逐 seed 明细见 "
              "`budget_seed_variance.md`"]
    with open(os.path.join(BENCH, "budget_curve.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[BUDGET] 曲线 -> {os.path.join(BENCH, 'budget_curve.md')}")


def main():
    args = parse_args()
    os.makedirs(BUDGET_DIR, exist_ok=True)
    if args.merge_only:
        reports = load_existing_reports()
        if not reports:
            raise SystemExit("[BUDGET] --merge-only: 没有找到任何已存在的格点 json")
        write_curve(build_curve(reports, args), args)
        return
    y = load_yaml(args.yaml)
    real_train_dir = resolve_split(y, "train")
    real_val_dir = resolve_split(y, "val")
    real_test_dir = resolve_split(y, "test")
    real_train = list_images(real_train_dir)
    synth_all = list_images(args.synth_dir) if os.path.isdir(args.synth_dir) else []
    print(f"[DATA] 真实 train 可枚举 {len(real_train)} 张 ({real_train_dir})")
    print(f"[DATA] 合成可用 {len(synth_all)} 张 ({args.synth_dir})")
    if not real_train:
        raise SystemExit("[DATA] 真实 train 目录为空")

    nc = y.get("nc", 1)
    names = y.get("names", ["product"])
    device = resolve_device()
    batch, workers = mem_guard(need_gb=args.mem_need_gb, strict=args.strict_protocol)

    cells = []
    for frac in args.fracs:
        for n_syn in args.synth:
            cells.append((frac, n_syn))

    results = []
    for frac, n_syn in cells:
        tag = f"real{frac:g}_synth{n_syn}" + (f"_{args.run_tag}" if args.run_tag else "")
        n_real = max(1, int(round(len(real_train) * frac)))
        real_pick = sample_subset(real_train, n_real, args.budget_seed)
        syn_pick = sample_subset(synth_all, n_syn, args.budget_seed + 1)
        real_list = write_list(os.path.join(BUDGET_DIR, f"{tag}_real.txt"), real_pick)
        syn_list = write_list(os.path.join(BUDGET_DIR, f"{tag}_synth.txt"), syn_pick)

        train_entries = [real_list]
        if syn_pick:
            train_entries.append(syn_list)
        train_yaml = os.path.join(BUDGET_DIR, f"{tag}.yaml")
        with open(train_yaml, "w", encoding="utf-8") as f:
            f.write(f"path: {BASE}\n")
            f.write("train: [" + ", ".join(train_entries) + "]\n")
            f.write(f"val: {real_val_dir}\n")
            f.write(f"test: {real_test_dir}\n")
            f.write(f"nc: {nc}\nnames: {names}\n")

        from ultralytics import YOLO
        model = YOLO(PROTOCOL["model"])
        t0 = time.time()
        model.train(data=train_yaml, epochs=args.epochs, imgsz=PROTOCOL["imgsz"],
                    batch=batch, seed=args.seed, device=device, workers=workers,
                    cache=PROTOCOL["cache"],
                    project=os.path.join(BENCH, f"budget_runs_{tag}"), name="train",
                    exist_ok=True, verbose=False)
        ckpt = os.path.join(BENCH, f"budget_runs_{tag}", "train", "weights", f"{args.select}.pt")
        ev = YOLO(ckpt)
        metrics = ev.val(data=train_yaml, split="test", imgsz=PROTOCOL["imgsz"],
                         device=device, max_det=PROTOCOL["max_det"],
                         project=os.path.join(BENCH, f"budget_runs_{tag}"), name="val",
                         exist_ok=True, verbose=False)
        wall = round(time.time() - t0, 1)

        comp = {
            "cell": {"real_frac": frac, "synth_n": n_syn},
            "n_real": len(real_pick),
            "n_synth": len(syn_pick),
            "real_subset_sha256": file_sha256(real_list),
            "synth_subset_sha256": file_sha256(syn_list) if syn_pick else None,
            # 池身份 (剂量轴单变量性): 同一池的各档必须同这个值。
            # **剂量 0 档也记** (2026-11-24): 0 档没有合成名单, 若不记池身份, 汇总脚本
            # 只能靠"行数最多的池"去猜它属于谁 -> 大池进来后会把老池的锚点抢走, 老池曲线
            # 整条消失 (0 档是配对差值的基准, 丢了就没有配对差值)。
            # 这里记的是"这个格点是对着哪个池准备的", 取没取图由 n_synth 表达。
            "synth_pool": pool_fingerprint(args.synth_dir),
            "budget_seed": args.budget_seed,
            "eval_split": "test",
            "eval_dir": real_test_dir,
            "eval_yaml_sha256": file_sha256(args.yaml) if os.path.isfile(args.yaml) else None,
        }
        protocol = dict(PROTOCOL, epochs=args.epochs, seed=args.seed,
                        real_frac=frac, synth_n=n_syn, budget_seed=args.budget_seed,
                        select=args.select)
        report = {
            "arm": f"budget:{tag}",
            "dataset": comp,
            "actual_train_config": {"epochs": args.epochs, "batch": batch,
                                     "workers": workers, "device": device,
                                     "mem_need_gb": args.mem_need_gb,
                                     "protocol_batch": PROTOCOL["batch"],
                                     "batch_downgraded": batch != PROTOCOL["batch"]},
            "protocol": protocol,
            "map50": float(metrics.box.map50),
            "map50_95": float(metrics.box.map),
            "precision": float(metrics.box.mp),
            "recall": float(metrics.box.mr),
            "wall_sec": wall,
            "checkpoint": {"selection": args.select, "path": ckpt,
                           "sha256": file_sha256(ckpt) if os.path.isfile(ckpt) else None},
            "protocol_manifest": build_manifest(
                protocol, data=comp,
                actual={"epochs": args.epochs, "batch": batch, "workers": workers,
                        "device": device, "wall_sec": wall},
                deps=runtime_versions()),
        }
        report["protocol_hash"] = report["protocol_manifest"]["protocol_hash"]
        write_json(os.path.join(BENCH, f"budget_{tag}.json"), report)
        results.append(report)
        print(f"[BUDGET] real={len(real_pick)} synth={len(syn_pick)} "
              f"map50={report['map50']:.4f} map50-95={report['map50_95']:.4f} "
              f"wall={wall}s hash={report['protocol_hash']}")

    # 曲线: 以 (real_frac=1, synth=0) 若存在则作基线
    write_curve(build_curve(results, args), args)


if __name__ == "__main__":
    main()
