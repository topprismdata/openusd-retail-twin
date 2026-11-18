#!/usr/bin/env python3
"""25 - 变体矩阵墙: SKU 轴一键换标 (N 款白底) + 平台轴一键裂变 (1 款→4 平台)
用法: python3 25_matrix_wall.py
产物: output/benchmark/matrix_wall.png
"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MP = os.path.join(BASE, "output", "multi_platform")
ORG = os.path.join(MP, "demo_organic")
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

SKUS = [
    ("经典款", "01_JD_WhiteBG_800x800_demo_classic.png"),
    ("经典娟姗", "01_JD_WhiteBG_800x800_demo_jersey.png"),
    ("经典马年", "01_JD_WhiteBG_800x800_demo_cny.png"),
    ("经典低脂", "01_JD_WhiteBG_800x800_demo_lowfat.png"),
    ("经典梦想38", "01_JD_WhiteBG_800x800_demo_dream38.png"),
    ("经典草原", "01_JD_WhiteBG_800x800_demo_meadow.png"),
    ("希腊酸奶原味", "01_JD_WhiteBG_800x800_demo_yogurt_original.png"),
    ("希腊酸奶金装", "01_JD_WhiteBG_800x800_demo_yogurt_gold.png"),
]
PLATFORMS = [
    ("电商白底 800px", os.path.join(ORG, "01_JD_WhiteBG_800x800.png")),
    ("天猫场景 1:1", os.path.join(ORG, "02_Tmall_Hero_1x1_1600x1600.png")),
    ("抖音 9:16", os.path.join(ORG, "03_Douyin_Feed_9x16_1080x1920.png")),
    ("小红书 3:4", os.path.join(ORG, "04_Xiaohongshu_Note_3x4_1242x1660.png")),
]

CELL, PAD, CAP = 300, 18, 56


def load_fit(path, cell):
    if not os.path.exists(path):
        im = Image.new("RGB", (cell, cell), (238, 240, 238))
        d = ImageDraw.Draw(im)
        d.text((cell // 2 - 30, cell // 2 - 10), "一键可出", fill=(170, 170, 170), font=ImageFont.truetype(FONT, 20))
        return im
    im = Image.open(path).convert("RGB")
    im.thumbnail((cell - 8, cell - 8))
    bg = Image.new("RGB", (cell, cell), (255, 255, 255))
    bg.paste(im, ((cell - im.width) // 2, (cell - im.height) // 2))
    return bg


def main():
    f_t, f_l, f_c = ImageFont.truetype(FONT, 30), ImageFont.truetype(FONT, 20), ImageFont.truetype(FONT, 18)
    # 布局: 左右双面板
    sku_cols, sku_rows = 4, 2
    plat_cols, plat_rows = 2, 2
    panel_pad = 26
    W = panel_pad + sku_cols * (CELL + PAD) + panel_pad + plat_cols * (CELL + PAD) + panel_pad
    H = CAP + panel_pad + sku_rows * (CELL + PAD + 34) + panel_pad

    canvas = Image.new("RGB", (W, H), (248, 248, 248))
    d = ImageDraw.Draw(canvas)
    d.text((panel_pad, 16), "变体矩阵墙 · 同一 OpenUSD 母本一键裂变 (L4 规模化敏捷): SKU 轴换标 × 平台轴构图", fill=(30, 30, 30), font=f_t)

    # 面板 A: SKU 轴
    ax, ay = panel_pad, CAP + panel_pad
    d.text((ax, ay - 4), "SKU 轴 · 一键换标 (8 款, 电商白底)", fill=(60, 60, 60), font=f_l)
    for k, (nm, fn) in enumerate(SKUS):
        gx = ax + (k % sku_cols) * (CELL + PAD)
        gy = ay + 30 + (k // sku_cols) * (CELL + PAD + 34)
        canvas.paste(load_fit(os.path.join(MP, fn), CELL), (gx, gy))
        d.rectangle([gx, gy, gx + CELL, gy + CELL], outline=(214, 218, 214), width=1)
        d.text((gx + 6, gy + CELL + 4), nm, fill=(90, 90, 90), font=f_c)

    # 面板 B: 平台轴
    bx = panel_pad + sku_cols * (CELL + PAD) + panel_pad
    by = ay
    d.text((bx, by - 4), "平台轴 · 一键裂变 (经典有机 → 4 平台构图)", fill=(60, 60, 60), font=f_l)
    for k, (nm, p) in enumerate(PLATFORMS):
        gx = bx + (k % plat_cols) * (CELL + PAD)
        gy = by + 30 + (k // plat_cols) * (CELL + PAD + 34)
        canvas.paste(load_fit(p, CELL), (gx, gy))
        d.rectangle([gx, gy, gx + CELL, gy + CELL], outline=(214, 218, 214), width=1)
        d.text((gx + 6, gy + CELL + 4), nm, fill=(90, 90, 90), font=f_c)

    out = os.path.join(BASE, "output", "benchmark", "matrix_wall.png")
    canvas.save(out)
    print(f"[WALL] {out} {canvas.size[0]}x{canvas.size[1]}")


if __name__ == "__main__":
    main()
