#!/usr/bin/env python3
"""合并多个 SDG 实例的产出 (2026-11-21): 为"合成剂量"实验准备一个更大的合成池。

为什么要合并: 剂量-反应实验需要比现有 160 张更多的合成图, 但渲染是串行的 (CPU)。
并行跑多个实例 (不同 --seed) 后合并, 可以把合成池扩到 2 倍而不用等 2 倍时间。

三个必须处理的坑:
1. **文件名冲突**: 每个实例都产出 img_000.png → 合并时加实例前缀 (s101_img_000.png);
   YOLO 的标签文件名必须跟着改, 否则 ultralytics 找不到标签。
2. **内容重复**: 不同 seed 理论上不会产出同一张图, 但必须**实测**证明 ——
   这里对每张图算 sha256, 跨实例重复的会被挑出来 (重复会虚增"剂量"的统计效力)。
3. **划分台账**: 合并后的 split_manifest.json 要逐图记录来源实例与 base_seed,
   并重新核验场景级留出 (train/val 场景集合不相交) 是否仍然成立。

用法:
  python pipelines/shelf_sdg/30_merge_sdg_sets.py --src <dir1> <dir2> --out <dir>
"""
import argparse
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import file_sha256, write_json  # noqa: E402


def prefix_of(src_dir):
    """从目录名里取实例前缀 (sdg_dose_s101 -> s101)。"""
    name = os.path.basename(os.path.normpath(src_dir))
    if "_s" in name:
        return name.rsplit("_s", 1)[1]
    return name


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", nargs="+", required=True, help="各实例的 SDG 输出目录")
    ap.add_argument("--out", required=True, help="合并后的 SDG 目录")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    for sub in ("images/train", "images/val", "labels/train", "labels/val", "annotations"):
        os.makedirs(os.path.join(out, sub), exist_ok=True)

    entries = []
    seen_sha = {}          # 内容 sha256 -> 首次出现的 "实例/图名"
    duplicates = []
    inst_stats = []
    for src in args.src:
        src = os.path.abspath(src)
        pre = prefix_of(src)
        man_path = os.path.join(src, "split_manifest.json")
        if not os.path.exists(man_path):
            raise SystemExit(f"[MERGE] 缺少 split_manifest: {man_path}")
        man = json.load(open(man_path, encoding="utf-8"))
        n_here = 0
        for e in man.get("images", []):
            split = e.get("split")
            if split not in ("train", "val"):
                continue
            src_img = os.path.join(src, "images", split, e["image"])
            if not os.path.exists(src_img):
                continue
            sha = file_sha256(src_img)
            if sha in seen_sha:
                duplicates.append({"image": f"{pre}_{e['image']}", "same_as": seen_sha[sha],
                                   "sha256": sha})
                continue
            seen_sha[sha] = f"{pre}/{e['image']}"
            stem = e["image"].rsplit(".", 1)[0]
            new_stem = f"{pre}_{stem}"
            shutil.copy2(src_img, os.path.join(out, "images", split, new_stem + ".png"))
            lab = os.path.join(src, "labels", split, stem + ".txt")
            if os.path.exists(lab):
                shutil.copy2(lab, os.path.join(out, "labels", split, new_stem + ".txt"))
            ann = os.path.join(src, "annotations", stem + ".json")
            if os.path.exists(ann):
                shutil.copy2(ann, os.path.join(out, "annotations", new_stem + ".json"))
            entries.append({
                "image": new_stem + ".png",
                "split": split,
                "source_instance": pre,
                "source_image": e["image"],
                "source_base_seed": man.get("base_seed"),
                "scene_id": e.get("scene_id") or (e.get("profile") or {}).get("scene_id"),
                "content_sha256": sha,
            })
            n_here += 1
        inst_stats.append({"instance": pre, "dir": src, "base_seed": man.get("base_seed"),
                           "copied": n_here, "split_mode": man.get("split_mode"),
                           "scene_level_holdout": man.get("scene_level_holdout")})

    train_scenes = {e["scene_id"] for e in entries if e["split"] == "train" and e.get("scene_id")}
    val_scenes = {e["scene_id"] for e in entries if e["split"] == "val" and e.get("scene_id")}
    overlap = sorted(train_scenes & val_scenes)

    man = {
        "schema": "sdg_split_manifest/3-merged",
        "generated_by": "pipelines/shelf_sdg/30_merge_sdg_sets.py",
        "merged_from": inst_stats,
        "n_train": sum(1 for e in entries if e["split"] == "train"),
        "n_val": sum(1 for e in entries if e["split"] == "val"),
        "train_scene_ids": sorted(train_scenes),
        "val_scene_ids": sorted(val_scenes),
        "scene_overlap": bool(overlap),
        "scene_level_holdout": not overlap,
        "duplicate_images_across_instances": duplicates,
        "n_unique_content_sha256": len(seen_sha),
        "split_policy": ("多实例合并: 每个实例内部是场景级留出; 实例之间靠不同 base_seed "
                         "产生不同场景参数, 合并后重新核验 train/val 场景集合仍不相交"),
        "images": entries,
    }
    write_json(os.path.join(out, "split_manifest.json"), man)
    print(f"[MERGE] {len(entries)} 张 (train {man['n_train']} / val {man['n_val']}) -> {out}")
    print(f"[MERGE] 场景重叠: {len(overlap)} (train∩val) | 跨实例内容重复: {len(duplicates)}")
    if overlap:
        raise SystemExit("[MERGE] 场景重叠, 合并后的划分不再满足场景级留出")
    if duplicates:
        raise SystemExit("[MERGE] 存在跨实例重复图, 剂量统计会被虚增")


if __name__ == "__main__":
    main()
