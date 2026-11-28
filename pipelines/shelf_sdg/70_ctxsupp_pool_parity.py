#!/usr/bin/env python
"""I-19 掩膜池的**单变量性核对** (2026-11-26) —— 70 号。

I-19 的整条结论建立在"唯一变量 = 一半训练图的框外上下文被抹掉"上 ✓, 所以这条前提
必须**逐张可核** ✓, 而不是靠脚本作者自证 ✓。本脚本对 **每一张**训练图核对四件事:
  1. **标签逐字节相同** (框/类没动 ✓);
  2. **图片尺寸相同** (几何没动 ✓);
  3. **框内像素逐像素等于原图** (商品本身没动 ✓);
  4. **框外像素是单一纯色** (上下文被抹成纯色 ✓ —— 且**只有被抹的那些图**满足 ✓)。
另外核对 **val 集逐字节等于原图** ✓ (验证集必须是原件 ✓)。

产物: output/benchmark/ctxsupp_pool_parity.json (现算 ✓)
"""
import hashlib
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
SRC = os.path.join(BENCH, "synth_single")
POOL = os.path.join(BENCH, "synth_ctxsupp")
OUT = os.path.join(BENCH, "ctxsupp_pool_parity.json")
MIN_SIDE = 4


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def boxes(lbl, w, h):
    out = []
    try:
        with open(lbl, encoding="utf-8") as fh:
            for line in fh:
                p = line.split()
                if len(p) < 5:
                    continue
                _, cx, cy, bw, bh = (float(v) for v in p[:5])
                x0, x1 = max(0, int((cx - bw / 2) * w)), min(w, int((cx + bw / 2) * w))
                y0, y1 = max(0, int((cy - bh / 2) * h)), min(h, int((cy + bh / 2) * h))
                if x1 - x0 >= MIN_SIDE and y1 - y0 >= MIN_SIDE:
                    out.append((x0, y0, x1, y1))
    except OSError:
        pass
    return out


def main():
    from PIL import Image
    import numpy as np
    res = {"schema": "ctxsupp_pool_parity/1",
           "generated_by": "pipelines/shelf_sdg/70_ctxsupp_pool_parity.py",
           "src_pool": SRC, "pool": POOL, "splits": {}}
    problems = []
    for split in ("train", "val"):
        si = os.path.join(SRC, "images", split)
        di = os.path.join(POOL, "images", split)
        n = 0
        masked = 0
        stats = {"n": 0, "label_identical": 0, "size_identical": 0, "inside_identical": 0,
                 "outside_flat": 0, "flat_checked": 0, "byte_identical_to_src": 0}
        for f in sorted(os.listdir(si)):
            if not f.lower().endswith((".png", ".jpg", ".jpeg")):
                continue
            n += 1
            stats["n"] += 1
            src, dst = os.path.join(si, f), os.path.join(di, f)
            if not os.path.isfile(dst):
                problems.append(f"{split}/{f}: 池里缺这张")
                continue
            stem = os.path.splitext(f)[0]
            l_src = os.path.join(SRC, "labels", split, stem + ".txt")
            l_dst = os.path.join(POOL, "labels", split, stem + ".txt")
            if os.path.isfile(l_src) and os.path.isfile(l_dst):
                if sha(l_src) == sha(l_dst):
                    stats["label_identical"] += 1
                else:
                    problems.append(f"{split}/{f}: 标签被改了")
            a = Image.open(src).convert("RGB")
            b = Image.open(dst).convert("RGB")
            if a.size == b.size:
                stats["size_identical"] += 1
            else:
                problems.append(f"{split}/{f}: 尺寸变了 {a.size} -> {b.size}")
                continue
            arr_a = np.asarray(a).astype(np.int16)
            arr_b = np.asarray(b).astype(np.int16)
            if split == "val":
                if sha(src) == sha(dst):
                    stats["byte_identical_to_src"] += 1
                else:
                    problems.append(f"val/{f}: 验证集必须与原图逐字节相同")
                continue
            w, h = a.size
            mask = np.ones((h, w), dtype=bool)
            for (x0, y0, x1, y1) in boxes(l_src, w, h):
                mask[y0:y1, x0:x1] = False
            if not mask.any():
                continue
            outside = arr_b[mask]
            # 纯色判定: 只比"是否处处等于第一个像素" —— **不用 np.unique** ✓
            # (np.unique 要排序, 200 张大图上慢到跑不完 ✗ -> 这里改成等值比较 ✓)
            flat = bool(np.all(outside == outside[0]))
            if flat:
                stats["outside_flat"] += 1
                stats["flat_checked"] += 1
                masked += 1
                # 框内必须逐像素等于原图
                if np.array_equal(arr_a[~mask], arr_b[~mask]):
                    stats["inside_identical"] += 1
                else:
                    problems.append(f"train/{f}: 框内像素被改了")
            else:
                # 没被抹的图: 必须与原图逐像素相同
                if np.array_equal(arr_a, arr_b):
                    stats["inside_identical"] += 1
                    stats["byte_identical_to_src"] += 1
                else:
                    problems.append(f"train/{f}: 既不是纯色背景, 也不等于原图")
        res["splits"][split] = stats
    res["n_masked_detected"] = res["splits"].get("train", {}).get("outside_flat", 0)
    res["problems"] = problems
    res["ok"] = not problems
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    print(json.dumps({k: res[k] for k in ("splits", "n_masked_detected", "ok")},
                     ensure_ascii=False, indent=2))
    if problems:
        print(f"[PARITY] ❌ {len(problems)} 处问题:")
        for p in problems[:20]:
            print("   -", p)
    else:
        print(f"[PARITY] ✅ 掩膜池单变量性核对通过 -> {OUT}")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
