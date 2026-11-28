#!/usr/bin/env python3
"""参照 vs 候选 同框对比板 (验收取证用)。

纪律:
  - **不改任何图像内容**: 只做等高缩放 + 拼接 + 标签; 品牌印刷是硬约束资产, 禁止重绘。
  - 盲评模式 (--blind): 左右随机但**确定性**打乱, 标签只写 A/B, 不泄露哪张是参照;
    映射写 sidecar json 供事后对账 (评审看不到)。
  - 同框对比只证明"风格差距缩小", 不替代外部盲评裁定。

用法:
  python3 compare_board.py --ref assets/reference/lifestyle_highkey_ref.png \
      --cand output/commercial/repro_lifestyle_v1.png --out output/commercial/board_v1.png [--blind]
"""
import argparse
import json
import os
import random

import numpy as np
from PIL import Image, ImageDraw


def build(ref_path, cand_path, out_path, blind=False, height=760, seed=7, left=None,
          key_dir=None):
    ref = Image.open(ref_path).convert("RGB")
    cand = Image.open(cand_path).convert("RGB")

    def fit(im):
        w = int(round(im.width * height / im.height))
        return im.resize((w, height), Image.LANCZOS)

    a, b = fit(ref), fit(cand)
    order = ["ref", "cand"]
    if left:
        # 位置偏倚控制必须**显式指定左右**: 靠 seed 碰运气实测失效
        # (seed 7 与 seed 3 都产出 left=cand → "交换位置复评板"根本没交换, 是假对照)。
        if left not in ("ref", "cand"):
            raise SystemExit("--left 只能是 ref 或 cand")
        order = [left, "cand" if left == "ref" else "ref"]
    elif blind and random.Random(seed).random() < 0.5:
        order = ["cand", "ref"]
    imgs = {"ref": a, "cand": b}
    left, right = imgs[order[0]], imgs[order[1]]
    pad, lab = 24, 44
    W = left.width + right.width + pad * 3
    H = height + pad * 2 + lab
    board = Image.new("RGB", (W, H), (250, 250, 250))
    board.paste(left, (pad, pad + lab))
    board.paste(right, (pad * 2 + left.width, pad + lab))
    d = ImageDraw.Draw(board)
    names = ("A", "B") if blind else ("REFERENCE", "CANDIDATE")
    for txt, x, w in ((names[0], pad, left.width), (names[1], pad * 2 + left.width, right.width)):
        d.text((x + w // 2 - 4 * len(txt), pad + 14), txt, fill=(20, 20, 20))
    board.save(out_path)
    meta = {"left": order[0], "right": order[1], "blind": blind, "seed": seed,
            "ref": ref_path, "cand": cand_path,
            "ref_size": list(ref.size), "cand_size": list(cand.size)}
    # 2026-11-23 (审计 F10): 盲评板的"哪边是哪边"是答案钥匙, **不能和板放在同一个
    # 目录** —— 评审者打开目录就看到了位置答案, 盲评当场失效。默认写到 <板名>_key/。
    key_dir = key_dir or (os.path.splitext(out_path)[0] + "_key")
    os.makedirs(key_dir, exist_ok=True)
    map_path = os.path.join(key_dir, os.path.basename(os.path.splitext(out_path)[0]) + "_map.json")
    with open(map_path, "w") as fh:
        json.dump(meta, fh, indent=1)
    # 对账: 板内两图与源图逐像素一致性(缩放后) — 证明未被重绘
    ok = True
    for im, key in ((left, order[0]), (right, order[1])):
        src = imgs[key]
        if not np.array_equal(np.asarray(im), np.asarray(src)):
            ok = False
    print("[BOARD] %s  %dx%d  left=%s right=%s  像素保真=%s"
          % (out_path, W, H, order[0], order[1], ok))
    if not ok:
        raise SystemExit("对比板像素与源图不一致, 拒绝交付")
    return meta


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ref", required=True)
    p.add_argument("--cand", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--blind", action="store_true")
    p.add_argument("--height", type=int, default=760)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--left", choices=("ref", "cand"), default=None,
                   help="显式指定左图(位置偏倚对照必须用它, 不靠seed)")
    p.add_argument("--key-dir", default=None,
                   help="答案钥匙目录 (默认 <板名>_key/; **不要指到评审者可见的目录**)")
    a = p.parse_args()
    build(a.ref, a.cand, a.out, a.blind, a.height, a.seed, a.left, a.key_dir)


if __name__ == "__main__":
    main()