#!/usr/bin/env python3
"""27 - GPT 验收矩阵拼板: 3 SKU × 3 创意方向 (splash/yogurt/breakfast)
用法: python3 27_creative_matrix.py
产物: output/benchmark/creative_matrix.png
"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CM = os.path.join(BASE, "output", "creative_matrix")
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

SCENES = [("牛奶飞溅 Hero", "splash"), ("酸奶微距", "yogurt"), ("早餐叙事", "breakfast")]
SKUS = [("经典款", "demo_classic"), ("经典有机", "demo_organic"), ("希腊酸奶原味", "demo_yogurt_original")]

CELL, PAD, CAP = 300, 18, 92


def load_fit(path, cell):
    if not os.path.exists(path):
        im = Image.new("RGB", (cell, cell), (240, 240, 240))
        ImageDraw.Draw(im).text((cell // 2 - 26, cell // 2), "待出图", fill=(170, 170, 170),
                                font=ImageFont.truetype(FONT, 18))
        return im
    im = Image.open(path).convert("RGB")
    im.thumbnail((cell - 8, cell - 8))
    bg = Image.new("RGB", (cell, cell), (252, 252, 252))
    bg.paste(im, ((cell - im.width) // 2, (cell - im.height) // 2))
    return bg


def main():
    f_t, f_h, f_c = (ImageFont.truetype(FONT, s) for s in (26, 18, 17))
    W = CAP + (CELL + PAD) * 3 + PAD
    H = CAP + CAP + (CELL + PAD + 30) * 3 + PAD
    canvas = Image.new("RGB", (W, H), (248, 248, 248))
    d = ImageDraw.Draw(canvas)
    d.text((PAD, 14), "最小验证矩阵 · 3 SKU × 3 创意方向 (同一 OpenUSD 母本)", fill=(30, 30, 30), font=f_t)
    for r, (sname, skey) in enumerate(SCENES):
        y = CAP + CAP + r * (CELL + PAD + 30)
        d.text((PAD, y + CELL // 2 - 10), sname, fill=(60, 60, 60), font=f_h)
        for c, (kn, sku) in enumerate(SKUS):
            x = CAP + c * (CELL + PAD)
            canvas.paste(load_fit(os.path.join(CM, f"{skey}_{sku}.png"), CELL), (x, y))
            d.rectangle([x, y, x + CELL, y + CELL], outline=(214, 218, 214))
            d.text((x + 6, y + CELL + 4), kn, fill=(90, 90, 90), font=f_c)
    out = os.path.join(BASE, "output", "benchmark", "creative_matrix.png")
    canvas.save(out)
    print(f"[CM] {out} {canvas.size[0]}x{canvas.size[1]}")


if __name__ == "__main__":
    main()
