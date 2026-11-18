#!/usr/bin/env python3
"""23 - organic 样板六视角复评板: 上排=GPT协议六视角, 下排=真实参照|AI直出|修复前(评审时白化版)|修复后"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MP = os.path.join(BASE, "output", "multi_platform", "demo_organic")
CELL_W, CELL_H, BAR_H, PAD = 300, 400, 30, 6


def font(sz):
    try:
        return ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", sz)
    except Exception:
        return ImageFont.load_default()


def cell(board, x0, y0, path, label, missing="缺失"):
    d = ImageDraw.Draw(board)
    d.rectangle([x0, y0, x0 + CELL_W, y0 + BAR_H], fill=(38, 66, 108))
    d.text((x0 + 6, y0 + 6), label, fill=(255, 255, 255), font=font(13))
    cy = y0 + BAR_H
    d.rectangle([x0, cy, x0 + CELL_W, cy + CELL_H], fill=(255, 255, 255), outline=(210, 210, 210))
    if path and os.path.exists(path):
        im = Image.open(path).convert("RGB")
        im.thumbnail((CELL_W - 8, CELL_H - 8))
        board.paste(im, (x0 + (CELL_W - im.width) // 2, cy + (CELL_H - im.height) // 2))
    else:
        d.text((x0 + 14, cy + CELL_H // 2 - 8), missing, fill=(160, 160, 160), font=font(13))


def main():
    views = [
        ("01_JD_WhiteBG_800x800.png", "正面 0°"),
        ("06_Hero_45deg_1600x1600.png", "左前 45°"),
        ("09_Side_90deg_800x800.png", "左侧 90°"),
        ("05_Back_Nutrition_1600x1600.png", "背面 180°"),
        ("10_Top_Cap_800x800.png", "顶视/盖口"),
        ("02_Tmall_Hero_1x1_1600x1600.png", "天猫主图 3/4"),
    ]
    n_cols = max(len(views), 4)
    W = n_cols * CELL_W + (n_cols + 1) * PAD
    H = PAD + BAR_H + (CELL_H + BAR_H + PAD) * 2 + 40
    board = Image.new("RGB", (W, H), (246, 247, 249))
    d = ImageDraw.Draw(board)
    d.text((PAD, PAD), "经典有机 demo_organic 样板复评板 (2026-11-09 白化整改后)", fill=(20, 20, 20), font=font(20))

    y0 = PAD + BAR_H + 8
    for i, (f, label) in enumerate(views):
        cell(board, PAD + i * (CELL_W + PAD), y0, os.path.join(MP, f), f"六视角{i+1}: {label}")
    d.text((PAD, y0 + CELL_H + BAR_H + 2), "上排: 六视角(修复后)  下排: 左→右 真实参照 | GPT AI直出 | 修复前(GPT评2.7白化版) | 修复后白底", fill=(80, 80, 80), font=font(13))

    y1 = y0 + CELL_H + BAR_H + PAD + 18
    row = [
        (os.path.join(BASE, "references", "dt_m_main.jpg"), "真实参照 (电商在售)"),
        (os.path.join(BASE, "references", "ai_gen", "ai_gen_demo_organic.png"), "GPT AI 直出"),
        (os.path.join(BASE, "output", "blind_eval", "before_fix.png"), "修复前 (评审时)"),
        (os.path.join(MP, "01_JD_WhiteBG_800x800.png"), "修复后白底 (本次送审)"),
    ]
    for i, (p, label) in enumerate(row):
        cell(board, PAD + i * (CELL_W + PAD), y1, p, label, missing="未入库")

    out = os.path.join(BASE, "output", "multi_platform", "demo_organic", "six_view_review.png")
    board.save(out)
    print(f"[BOARD6] {out} {board.size[0]}x{board.size[1]}")


if __name__ == "__main__":
    main()
