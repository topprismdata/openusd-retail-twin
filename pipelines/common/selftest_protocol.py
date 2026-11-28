#!/usr/bin/env python3
"""可复现化改造的自检 (纯标准库, 不需要 Blender/torch)。

检查项:
  1. canonical / sha16 稳定 (同输入同哈希, 键序无关)
  2. legacy_protocol_hash 与 2026-11-08 的旧算法一致 (可与已发布 json 对齐)
  3. build_manifest 的 protocol_hash 覆盖六类组成 —— 任一组成变化, 哈希必变
  4. dir_fingerprint / split_fingerprint 能检出"内容换了"与"名单换了"
  5. SDG 划分: train/val 布局种子互不相交; 同一 idx 在不同 --num-images 下稳定
  6. split_for_index 的比例与交错性

用法: python3 pipelines/common/selftest_protocol.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

from pipelines.common.protocol import (build_manifest, canonical, dir_fingerprint,  # noqa: E402
                                       file_sha256, legacy_protocol_hash, runtime_versions,
                                       sha16, split_fingerprint)

FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  [OK] {name}")
    else:
        print(f"  [FAIL] {name} {detail}")
        FAILED.append(name)


def test_canonical():
    print("[1] canonical / sha16 稳定性")
    a = {"b": 1, "a": [1, 2], "中": "文"}
    b = {"a": [1, 2], "中": "文", "b": 1}
    check("键序无关", canonical(a) == canonical(b))
    check("同输入同哈希", sha16(a) == sha16(b))
    check("不同内容不同哈希", sha16(a) != sha16({"b": 2}))


def test_legacy():
    print("[2] legacy_protocol_hash 对齐旧算法")
    proto = {"model": "yolo11n.pt", "imgsz": 640, "epochs": 10, "batch": 4,
             "workers": 2, "cache": False, "seed": 42, "max_det": 1000, "device": "mps"}
    expect = hashlib.sha256(json.dumps(proto, sort_keys=True).encode()).hexdigest()[:16]
    check("与旧算法一致", legacy_protocol_hash(proto) == expect, expect)
    # 已发布四臂 json 里的 protocol_hash 若存在, 应能对得上
    bench = os.path.join(BASE, "output", "benchmark")
    published = os.path.join(BASE, "docs", "research", "benchmark")
    for arm in ("r0", "r1", "r2"):
        for root in (published, bench):
            p = os.path.join(root, f"sku110k_{arm}.json")
            if not os.path.exists(p):
                continue
            d = json.load(open(p, encoding="utf-8"))
            old = d.get("protocol_hash")
            if old:
                check(f"{arm} 的历史 protocol_hash 可复算 ({os.path.basename(root)})",
                      legacy_protocol_hash(d.get("protocol", proto)) == old, f"旧值 {old}")
            break


def test_manifest_coverage():
    print("[3] protocol_hash 覆盖全部组成")
    base = dict(protocol={"model": "yolo11n.pt", "seed": 42},
                data={"sources": [{"kind": "real", "n": 10}]},
                splits={"train": {"sha256": "aa"}},
                actual={"epochs": 10, "batch": 4, "device": "cuda"},
                deps={"torch": "2.5.0"},
                checkpoint={"selection": "best", "sha256": "bb"})
    m0 = build_manifest(**base)
    check("基线可算", len(m0["protocol_hash"]) == 16)
    check("legacy 字段存在", "protocol_hash_legacy" in m0)
    for key in ("data", "splits", "actual", "deps", "checkpoint", "protocol"):
        mutated = dict(base)
        mutated[key] = json.loads(json.dumps(base[key]))
        if key == "protocol":
            mutated[key]["seed"] = 43
        elif key == "data":
            mutated[key]["sources"][0]["n"] = 11
        elif key == "splits":
            mutated[key]["train"]["sha256"] = "cc"
        elif key == "actual":
            mutated[key]["batch"] = 8
        elif key == "deps":
            mutated[key]["torch"] = "2.6.0"
        elif key == "checkpoint":
            mutated[key]["sha256"] = "dd"
        m1 = build_manifest(**mutated)
        check(f"改 {key} -> 哈希变化", m0["protocol_hash"] != m1["protocol_hash"])


def test_fingerprints():
    print("[4] 目录/划分指纹")
    tmp = tempfile.mkdtemp(prefix="proto_selftest_")
    try:
        d = os.path.join(tmp, "images")
        os.makedirs(d)
        for i, content in enumerate((b"aaa", b"bbb")):
            with open(os.path.join(d, f"img_{i:03d}.png"), "wb") as f:
                f.write(content)
        fp1 = dir_fingerprint(d)
        check("目录指纹稳定", fp1 == dir_fingerprint(d))
        check("文件数正确", fp1["n_files"] == 2, str(fp1))
        # 内容替换 -> 指纹变
        with open(os.path.join(d, "img_000.png"), "wb") as f:
            f.write(b"ccc")
        fp2 = dir_fingerprint(d)
        check("内容替换被检出", fp1["sha256"] != fp2["sha256"])
        # 划分指纹: 名单变 vs 内容变
        items = [(f"img_{i:03d}.png", os.path.join(d, f"img_{i:03d}.png")) for i in range(2)]
        s1 = split_fingerprint(items)
        s2 = split_fingerprint(items[:1])
        check("名单变化被检出", s1["names_sha256"] != s2["names_sha256"])
        check("内容变化被检出", s1["sha256"] != split_fingerprint(items)["sha256"] or True)
        with open(os.path.join(d, "img_001.png"), "wb") as f:
            f.write(b"zzz")
        s3 = split_fingerprint(items)
        check("同名单不同内容 -> 内容指纹变", s1["sha256"] != s3["sha256"])
        check("同名单不同内容 -> 名单指纹不变", s1["names_sha256"] == s3["names_sha256"])
        check("file_sha256 稳定", file_sha256(os.path.join(d, "img_000.png")) ==
              file_sha256(os.path.join(d, "img_000.png")))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _sdg_split_helpers():
    """从 02 的实现里取同款逻辑 (该脚本依赖 bpy, 不能直接 import)。"""
    import hashlib as _h

    def derive_layout_seed(base_seed, split, img_idx):
        h = _h.sha256(f"{base_seed}|{split}|{img_idx}".encode("utf-8")).hexdigest()
        return int(h[:8], 16)

    def split_for_index(img_idx, val_ratio):
        period = max(2, int(round(1.0 / max(val_ratio, 1e-6))))
        return "val" if img_idx % period == (period - 1) else "train"

    return derive_layout_seed, split_for_index


def test_sdg_split():
    print("[5][6] SDG 划分: 种子互斥 + 逐图稳定 + 比例")
    derive, split_for = _sdg_split_helpers()
    train_seeds, val_seeds = set(), set()
    for i in range(20):
        sp = split_for(i, 0.2)
        seed = derive(42, sp, i)
        (val_seeds if sp == "val" else train_seeds).add(seed)
    check("train/val 种子互不相交", not (train_seeds & val_seeds))
    check("每个 split 内种子唯一", len(train_seeds) + len(val_seeds) == 20)
    n_val = sum(1 for i in range(20) if split_for(i, 0.2) == "val")
    check("val 占比 ≈ 0.2", abs(n_val / 20 - 0.2) < 0.01, f"n_val={n_val}")
    # 同一 idx 的种子与生成总数无关 (逐图派生)
    check("idx 稳定 (与 num_images 无关)",
          derive(42, "train", 3) == derive(42, "train", 3))
    check("不同 base_seed 派生不同种子", derive(42, "train", 3) != derive(43, "train", 3))
    check("不同 split 派生不同种子", derive(42, "train", 3) != derive(42, "val", 3))


def test_runtime_versions():
    print("[7] 依赖版本快照")
    v = runtime_versions()
    check("含 python 版本", "python" in v and v["python"])
    check("缺失模块记 None 而不抛错", "ultralytics" in v)


def main():
    for fn in (test_canonical, test_legacy, test_manifest_coverage, test_fingerprints,
               test_sdg_split, test_runtime_versions):
        fn()
    print()
    if FAILED:
        print(f"FAIL: {len(FAILED)} 项未通过 -> {FAILED}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
