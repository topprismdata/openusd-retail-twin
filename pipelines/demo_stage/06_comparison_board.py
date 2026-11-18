#!/usr/bin/env python3
"""真实电商图 vs 程序化渲染 同框对比板
用法: python3 06_comparison_board.py
输出: output/comparison_board.png (4 格: 电商白底 / 天猫 KV × 真实 | 本方案)
"""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REF = os.path.join(BASE, "references")
OUT = os.path.join(BASE, "output")

CELL = 880          # 单元格图像边长
GAP = 28            # 间距
LABEL_H = 88        # 标签条高
W = CELL * 2 + GAP * 3
H = (LABEL_H + CELL) * 2 + GAP * 3 + 72

FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
]


def font(sz, idx=0):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, sz, index=idx)
            except OSError:
                continue
    return ImageFont.load_default()


def fit(img, box):
    w, h = img.size
    s = max(box / w, box / h)
    img = img.resize((round(w * s), round(h * s)), Image.LANCZOS)
    x = (img.width - box) // 2
    y = (img.height - box) // 2
    return img.crop((x, y, x + box, y + box))


def cell_img(path):
    return fit(Image.open(path).convert("RGB"), CELL)


def draw_label(d, x, y, text, sub, accent):
    d.rectangle([x, y, x + CELL, y + LABEL_H - 10], fill=(24, 26, 24))
    d.rectangle([x, y, x + 14, y + LABEL_H - 10], fill=accent)
    d.text((x + 34, y + 16), text, fill=(255, 255, 255), font=font(44))
    d.text((x + 34, y + 62), sub, fill=(190, 195, 190), font=font(26))


board = Image.new("RGB", (W, H), (240, 240, 238))
d = ImageDraw.Draw(board)

pairs = [
    ("真实参照", "电商在售主图 · 官方旗舰店 (2026-11 抓取)", (16, 98, 56),
     os.path.join(REF, "jd_s5.jpg")),
    ("本方案渲染", "OpenUSD + Blender Cycles · 全离线程序化生成 (同款牛皮纸装)", (198, 88, 40),
     os.path.join(OUT, "multi_platform", "01_JD_WhiteBG_800x800_classic.png")),
    ("真实参照", "天猫官方 KV · 品牌方发布素材", (16, 98, 56),
     os.path.join(REF, "ref3.jpg")),
    ("本方案渲染", "同版式复刻 · 翡翠绿幕 + 双 SKU 组合", (198, 88, 40),
     os.path.join(OUT, "multi_platform", "02_Tmall_Hero_1x1_1600x1600.png")),
]

y = GAP
for row in range(2):
    x = GAP
    for col in range(2):
        label, sub, accent, path = pairs[row * 2 + col]
        d.rectangle([x, y, x + CELL, y + LABEL_H - 10], fill=(24, 26, 24))
        d.rectangle([x, y, x + 14, y + LABEL_H - 10], fill=accent)
        d.text((x + 34, y + 12), label, fill=(255, 255, 255), font=font(42))
        d.text((x + 34, y + 58), sub, fill=(190, 195, 190), font=font(25))
        board.paste(cell_img(path), (x, y + LABEL_H))
        x += CELL + GAP
    y += LABEL_H + CELL + GAP

d.text((GAP, H - 52), "生成: 2026-11-06 · openusd-retail-twin · 全程序化生产 (无实物拍摄) — 贴图为设计演示, 非品牌官方资产",
       fill=(110, 112, 110), font=font(24))

dst = os.path.join(OUT, "comparison_board.png")
board.save(dst)
print(f"[Done] {dst} ({W}x{H})")
