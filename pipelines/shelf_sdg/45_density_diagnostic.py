#!/usr/bin/env python
"""密度诊断臂 (2026-11-24): 域差距三因子里**密度**到底有多重要?

背景
----
域差距三因子 (同一套度量, `23_domain_gap_measure.py`):

    因子        真实        合成       差距
    密度(框/图) 147.04      21.83      6.74x   <- 最远
    朝向(宽高比)  1.0544     0.3232     3.26x   <- 已实测: 对齐后变差 10.66pp
    尺度(框面积)  0.0030     0.0053     1.7x    <- 已实测: 对齐后变差 10.66pp

形状臂 (`43_r1shape_arm.py`) 已经实测过**朝 + 尺度**两个因子: 都精确对准真实域之后,
mAP 反而掉了 10.66pp (n=6, CI [-16.48, -4.83])。于是"剩下的差距是不是密度"就成了
唯一的开放问题 —— 但这个判断**是从形状臂的负结果推断出来的, 从来没有直接测过**
(README 原先的机理段落只把密度列为"嫌疑", 并没说它就是主因)。

设计: **在真实数据侧**做密度稀释, 而不是改生成器
---------------------------------------------------------
生成器侧提密度有严重的混淆项: 槽宽 0.08m 而商品宽 0.048m, 一个槽**物理上放不下第二个
同宽商品**; 想把 21.8 提到 147 框/图 (6.74x), 必须同时缩小商品 + 缩紧间距, 于是
**尺度因子和密度因子一起动** —— 那样就分不清是哪个起作用了。

反过来, 在真实数据侧稀释密度是**干净的单因子干预**:
  * 输入仍是真实图像 (内容/视角/光照/分辨率全不变);
  * 只把每张图的**标注框**随机裁掉一部分, 框/图从 147 降到目标值;
  * 框的语义、分布、尺度、朝向全不变 (裁的是框的**数量**, 不是框的**样子**)。
所以 mAP 的变化只能归因于"每图有多少个框"这一个变量。

为什么这个诊断有意义
--------------------
合成集的框是**可见区域紧致框**, 真实框是**整品框** (审计 F7), 两者的"一个框"含义本就
不同; 但即便如此, 若"框/图"这个量本身对 mAP 影响巨大, 那合成侧的 6.74x 密度差距就是
首要嫌疑; 若影响很小, 那差距必然在别处 (成像风格/框语义/图内布局)。

结果 (2026-11-24 实测, 22 框/图 x 3 seed)
------------------------------------------
配对差值 (稀释臂 - 全量真实基线, 同 seed) = **-4.02 pp, 95% CI [-4.52, -3.51]**
(n=3, t=-33.9, sd 0.21)。机制是**漏检**而不是定不准: precision 0.8853 -> 0.8995
(略升), recall 0.8082 -> 0.6964 (**-11.2pp**), mAP50-95 0.5299 -> 0.4849 ——
丢掉 85% 的标注 = 大量真实物体从没被当成正样本, 模型压根没学过它们。

由此得到的结论 (README 已按此改写):
  1. 密度是真实的一个**实质性**因素, 但**不是全部**: 4.02 pp 约为 5% 预算下
     "合成->全量真实"缺口 (9.92 pp) 的 ~41%; 其余 ~59% 仍未定位。
  2. 形状臂的 -10.66 pp **不是**密度污染: 该臂密度只动 1.2 框/图, 按本次斜率
     (0.032 pp/框/图) 只值 0.04 pp。
  3. "合成补不回缺口"有了机制解释: 合成的框密度只有真实的 1/6.7, 加合成图会**拉低**
     训练集的有效框密度而不是拉高 —— 5% 预算加 160 张合成后有效密度 147.04 -> 111.96,
     按斜率预期掉 1.13 pp, 实测是 -0.15 pp (略好, 在噪声内), 确实没有正向补回。

用法:
    python pipelines/shelf_sdg/45_density_diagnostic.py --boxes-per-image 22 --seeds 42,43
    # 每个 (目标框/图, seed) 一份产物, 评测集 = 真实 test (与四臂一致)
    # --boxes-per-image 74 --seeds 42  -> 中间点, 用来检验单调性与线性 (斜率外推)
"""
import argparse
import glob
import hashlib
import json
import os
import random
import shutil
import sys
import time
from types import SimpleNamespace

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.runtime_env import available_memory_gb, torch_device  # noqa: E402
from pipelines.common.protocol import (build_manifest, file_sha256, runtime_versions,  # noqa: E402
                                       write_json)

BENCH = os.path.join(BASE, "output", "benchmark")
DENS_DIR = os.path.join(BENCH, "density")
PROTOCOL = {"model": "yolo11n.pt", "imgsz": 640, "epochs": 10, "batch": 4,
            "workers": 2, "cache": False, "seed": 42, "max_det": 1000, "device": "auto"}


def log(msg):
    line = f"[DENS {time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)


def sku_root():
    return os.environ.get("SKU110K_ROOT", "/opt/homebrew/datasets/SKU-110K")


def sku_yaml():
    return os.environ.get("SKU110K_YAML", "SKU-110K.yaml")


def read_labels(path):
    """YOLO 标签文件 -> [(cls, cx, cy, w, h), ...]"""
    out = []
    if not os.path.exists(path):
        return out
    for line in open(path, encoding="utf-8"):
        p = line.split()
        if len(p) >= 5:
            out.append((p[0], p[1], p[2], p[3], p[4]))
    return out


def build_diluted_dataset(boxes_per_image, seed, tag):
    """构造"框密度被稀释到 boxes_per_image"的真实训练集。

    **图像一律复制/链接原图** (像素完全不变), 只重写 labels/ 下的框文件:
    每张图随机保留 min(原框数, boxes_per_image) 个框 (固定 rng 种子 -> 可复现)。
    框的**样子**不变 (尺度/朝向/位置分布都不动), 只有**数量**变 —— 单因子干预。
    """
    root = sku_root()
    train_file = os.path.join(root, "train.txt")
    names = [l.strip() for l in open(train_file, encoding="utf-8") if l.strip()]
    dst = os.path.join(DENS_DIR, tag)
    for sub in ("images", "labels"):
        d = os.path.join(dst, sub)
        os.makedirs(d, exist_ok=True)
        # 清掉上一次残留
        for f in os.listdir(d):
            fp = os.path.join(d, f)
            if os.path.isfile(fp):
                os.remove(fp)

    rng = random.Random(seed)
    kept_total = orig_total = 0
    n_imgs = 0
    n_link_fail = 0
    list_path = os.path.join(DENS_DIR, f"{tag}_train.txt")
    entries = []
    for n in names:
        stem = os.path.splitext(os.path.basename(n))[0]
        img_src = os.path.join(root, "images", stem + ".jpg")
        lbl_src = os.path.join(root, "labels", stem + ".txt")
        if not os.path.exists(img_src):
            img_src = os.path.join(root, "images", n)
        if not (os.path.exists(img_src) and os.path.exists(lbl_src)):
            continue
        rows = read_labels(lbl_src)
        orig_total += len(rows)
        keep = rows
        if len(rows) > boxes_per_image:
            keep = rng.sample(rows, boxes_per_image)
        kept_total += len(keep)
        img_dst = os.path.join(dst, "images", stem + ".jpg")
        lbl_dst = os.path.join(dst, "labels", stem + ".txt")
        # 链接优先 (省磁盘); Windows 无开发者模式时 symlink 抛 OSError -> 复制。
        # 复制 8219 张 jpg 很慢, 所以这里**只在必要时复制**, 且失败要记数 (不能静默丢图:
        # 丢一张就等于训练集少一张, 数据组成对不上却没人知道)。
        if not os.path.exists(img_dst):
            linked = False
            try:
                os.symlink(img_src, img_dst)
                linked = True
            except OSError:
                pass
            if not linked:
                try:
                    shutil.copy2(img_src, img_dst)
                except Exception as e:
                    n_link_fail += 1
                    if n_link_fail <= 3:
                        log(f"链接/复制失败 ({type(e).__name__}: {e}) -> {img_src}")
                    continue
        with open(lbl_dst, "w", encoding="utf-8") as fh:
            for c, cx, cy, w, h in keep:
                fh.write(f"{c} {cx} {cy} {w} {h}\n")
        entries.append(img_dst)
        n_imgs += 1
    with open(list_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(entries))
    if n_link_fail:
        log(f"警告: {n_link_fail} 张图链接/复制失败 (已跳过) —— 训练集比 train.txt 少这些")
    return {
        "dir": dst, "list": list_path, "n_images": n_imgs,
        "n_link_fail": n_link_fail,
        "boxes_kept": kept_total, "boxes_original": orig_total,
        "boxes_per_image": (kept_total / n_imgs) if n_imgs else None,
        "keep_ratio": (kept_total / orig_total) if orig_total else None,
        "list_sha256": file_sha256(list_path),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boxes-per-image", type=int, default=22,
                    help="每图保留的框数上限 (真实侧本来 ~147; 合成侧 21.8)")
    ap.add_argument("--seeds", default="42,43")
    ap.add_argument("--epochs", type=int, default=10)
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]

    import torch
    from ultralytics import YOLO

    os.makedirs(DENS_DIR, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    batch, workers = (4, 2)
    # 2026-11-25: 密度诊断的三个点必须**同协议**才是一条曲线。机器上并发跑别的
    #   训练时可用内存会掉到 18 GB 以下 -> 14 号的守卫会**静默降 batch 4 -> 2**,
    #   于是 dens74 的 seed 43/44 会变成 batch=2, 而 dens22/dens74_s42 是 batch=4
    #   -> 曲线里混进协议漂移。这里把阈值显式降到 10 GB (batch=4 单跑实测峰值
    #   RSS ~2.5 GB) 并**保持 batch=4**: 内存不够就报错, 不改协议。
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location(
            "m14", os.path.join(BASE, "pipelines/shelf_sdg/14_sku110k_baseline.py"))
        m14 = ilu.module_from_spec(spec)
        spec.loader.exec_module(m14)
        avail = m14.available_memory_gb()
        if avail < 10.0:
            raise SystemExit(f"[MEM-GUARD] 可用 {avail:.1f}GB < 10GB, 拒跑")
        batch, workers = 4, 2
        import torch
        torch.set_num_threads(4)
        print(f"[MEM-GUARD] avail={avail:.1f}GB batch=4 workers=2 (协议固定, 不降级)")
    except SystemExit:
        raise
    except Exception as e:
        log(f"mem_guard 不可用 ({type(e).__name__}: {e}), 用默认 batch={batch}")

    y = os.path.join(sku_root(), "SKU-110K.yaml")
    root_yaml = sku_yaml()
    # 本仓两个 python 都没装 pyyaml, 而 ultralytics 自带 yaml 解析 (它依赖 pyyaml 或
    # 用自己的 loader) —— 用它读, 读不到就退回默认值 (nc=1/names=[product], 与
    # SKU-110K 一致)。
    ydata = {"nc": 1, "names": ["product"]}
    root_obj = None
    for cand in (root_yaml, y):
        cpath = cand if os.path.isabs(cand) else os.path.join(sku_root(), cand)
        if not os.path.exists(cpath):
            continue
        try:
            from ultralytics.utils import YAML
            _y = YAML.load(cpath)
        except Exception as e:
            log(f"读 yaml 失败 ({cpath}: {type(e).__name__}: {e})")
            continue
        if isinstance(_y, dict) and _y.get("names"):
            ydata = _y
            root_obj = _y
            log(f"根 yaml: {cpath}")
            break

    # 评测集必须用**真实 split** (与 21 号 / 四臂一致), 不能手搓目录名:
    # SKU-110K 的图片是**扁平**命名的 (images/val_0.jpg), 并没有 images/val/ 目录 ->
    # 手搓出来的路径 ultralytics 找不到, 训练在数据检查那一步就直接失败
    # (2026-11-24 实测: "images not found, missing path ...\SKU-110K\val")。
    # 这里复用 21 号的 resolve_split (同一套约定, 别再各写一套)。
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "m21", os.path.join(BASE, "pipelines/shelf_sdg/21_annotation_budget.py"))
    m21 = ilu.module_from_spec(spec)
    spec.loader.exec_module(m21)
    if root_obj is not None:
        val_dir = m21.resolve_split(root_obj, "val")
        test_dir = m21.resolve_split(root_obj, "test")
    else:
        val_dir = os.path.join(sku_root(), "val.txt")
        test_dir = os.path.join(sku_root(), "test.txt")
    for _k, _v in (("val", val_dir), ("test", test_dir)):
        if not os.path.exists(_v):
            raise SystemExit(f"[DENS] 评测集 {_k} 不存在: {_v} "
                             f"(SKU110K_ROOT={sku_root()}) —— 先确认数据根目录再跑")

    for seed in seeds:
        tag = f"dens{args.boxes_per_image}_s{seed}"
        out_json = os.path.join(BENCH, f"density_{tag}.json")
        if os.path.exists(out_json):
            log(f"SKIP {tag} (已存在)")
            continue
        info = build_diluted_dataset(args.boxes_per_image, seed, tag)
        log(f"{tag}: {info['n_images']} 图, 框/图 {info['boxes_original'] / max(info['n_images'],1):.1f} "
            f"-> {info['boxes_per_image']:.1f} (保留 {info['keep_ratio']:.1%})")

        yaml_path = os.path.join(DENS_DIR, f"{tag}.yaml")
        with open(yaml_path, "w", encoding="utf-8") as fh:
            fh.write(f"path: {BASE}\n")
            fh.write(f"train: {info['list']}\n")
            fh.write(f"val: {val_dir}\n")
            fh.write(f"test: {test_dir}\n")
            fh.write(f"nc: {ydata.get('nc', 1)}\nnames: {ydata.get('names', ['product'])}\n")

        proto = dict(PROTOCOL, seed=seed)
        model = YOLO(proto["model"])
        run_dir = os.path.join(BENCH, f"density_runs_{tag}")
        log(f"训练 {tag} (batch={batch} workers={workers} device={device})")
        t0 = time.time()
        model.train(data=yaml_path, epochs=args.epochs, imgsz=proto["imgsz"],
                    batch=batch, seed=seed, device=device, workers=workers,
                    cache=proto["cache"], project=run_dir, name="train",
                    exist_ok=True, verbose=False)
        wall = round(time.time() - t0, 1)
        ckpt = os.path.join(run_dir, "train", "weights", "best.pt")
        ev = YOLO(ckpt)
        r = ev.val(data=yaml_path, split="test", imgsz=proto["imgsz"],
                   device=device, max_det=proto["max_det"],
                   project=run_dir, name="val", exist_ok=True, verbose=False)
        rep = {
            "schema": "density_diagnostic/1",
            "measured_at": "2026-11-24",
            "treatment": {
                "what": "真实训练集的**框密度**被稀释 (每图只保留 K 个框)",
                "boxes_per_image_target": args.boxes_per_image,
                "what_is_unchanged": ["图像像素", "框的尺度/朝向/位置分布", "评测集", "训练协议"],
                "why_real_side": ("生成器侧提密度无法单因子: 槽宽 0.08m 放不下第二个 0.048m 的商品, "
                                  "要提密度必须同时缩商品 -> 尺度因子被一起改动; "
                                  "在真实侧稀释则只动'框的数量'这一个变量"),
            },
            "dataset": {
                "arm": "density_diagnostic",
                "n_images": info["n_images"],
                "boxes_kept": info["boxes_kept"],
                "boxes_original": info["boxes_original"],
                "boxes_per_image": round(info["boxes_per_image"], 4),
                "keep_ratio": round(info["keep_ratio"], 6),
                "train_list_sha256": info["list_sha256"],
            },
            "protocol": proto,
            "protocol_hash": None,
            "actual_train_config": {"epochs": args.epochs, "batch": batch,
                                    "workers": workers, "device": device,
                                    "wall_sec": wall},
            "map50": float(r.box.map50),
            "map50_95": float(r.box.map),
            "precision": float(r.box.mp),
            "recall": float(r.box.mr),
            "checkpoint": {"selection": "best", "path": os.path.relpath(ckpt, BASE),
                           "sha256": file_sha256(ckpt), "exists": os.path.exists(ckpt)},
            "protocol_manifest": build_manifest(
                proto,
                data={"treatment": {"boxes_per_image": args.boxes_per_image}},
                splits={"train": {"n": info["n_images"],
                                  "sha256": info["list_sha256"]}},
                actual={"epochs": args.epochs, "batch": batch, "workers": workers,
                        "device": device, "wall_sec": wall},
                deps=runtime_versions()),
        }
        with open(out_json, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        log(f"{tag}: map50={rep['map50']:.4f} map50_95={rep['map50_95']:.4f} "
            f"({wall/60:.1f} min)")
    log("=== 密度诊断完成 ===")


if __name__ == "__main__":
    main()
