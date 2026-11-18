#!/usr/bin/env python3
"""29c - 扫参对比板: 8 组合网格 + 参数标签
用法: python3 29c_sweep_board.py
产物: output/benchmark/splash_sweep_board.png
"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SW = os.path.join(BASE, "output", "splash_sweep")
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

COMBOS = [
    (2.0, 0.375, 10), (2.0, 0.375, 14), (3.0, 0.340, 10), (3.0, 0.375, 12),
    (3.0, 0.410, 14), (4.0, 0.375, 10), (4.0, 0.410, 16), (3.0, 0.410, 20),
]


def main():
    f_t, f_c = ImageFont.truetype(FONT, 24), ImageFont.truetype(FONT, 16)
    CELL, PAD = 380, 14
    cols, rows = 4, 2
    W = PAD + cols * (CELL + PAD)
    H = 50 + rows * (CELL + 30) + PAD
    canvas = Image.new("RGB", (W, H), (246, 246, 246))
    d = ImageDraw.Draw(canvas)
    d.text((PAD, 12), "对撞射流扫参矩阵 (射速 m/s × 撞高 m × 采样帧) — 判形选优", fill=(25, 25, 25), font=f_t)
    for k, (sp, cz, fr) in enumerate(COMBOS):
        gx = PAD + (k % cols) * (CELL + PAD)
        gy = 50 + (k // cols) * (CELL + 30)
        path = os.path.join(SW, f"sp{sp:.0f}_z{int(cz*1000)}_f{fr}.png")
        if os.path.exists(path):
            im = Image.open(path).convert("RGB")
            im.thumbnail((CELL, CELL))
            canvas.paste(im, (gx + (CELL - im.width) // 2, gy + (CELL - im.height) // 2))
        else:
            d.rectangle([gx, gy, gx + CELL, gy + CELL], fill=(230, 230, 230))
            d.text((gx + 60, gy + CELL // 2), "缺图", fill=(150, 150, 150), font=f_c)
        d.rectangle([gx, gy, gx + CELL, gy + CELL], outline=(200, 204, 200))
        d.text((gx + 6, gy + CELL + 5), f"v={sp}  z={cz:.3f}  f={fr}", fill=(70, 70, 70), font=f_c)
    out = os.path.join(BASE, "output", "benchmark", "splash_sweep_board.png")
    canvas.save(out)
    print(f"[SWEEPBOARD] {out} {canvas.size[0]}x{canvas.size[1]}")


if __name__ == "__main__":
    main()
