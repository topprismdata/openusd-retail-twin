#!/usr/bin/env python3
"""30 - 保真验收板: 四视角 + 旋盖细节 + 逐项检查表 (研究重建级诚实清单)
用法: python3 30_qa_board.py
产物: output/benchmark/qa_board.png
"""
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QA = os.path.join(BASE, "output", "qa_four_view")
FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

VIEWS = [("正面 0°", "front"), ("侧面 90°", "side"), ("背面 180°", "back"), ("45°", "deg45")]

# 逐项: (项目, 状态, 说明)  状态: OK / PARTIAL / PLACEHOLDER / UNTESTED
CHECKS = [
    ("盒体几何 (48×44×136mm 八角倒角)", "OK", "程序化参数, 尺寸可追溯"),
    ("DreamCap 旋盖几何", "OK", "直径/高度参数正确"),
    ("品牌字「经典」", "PARTIAL", "位置/配色对齐官方; 字体为手工重建, 非官方字库"),
    ("品名「有机纯牛奶」竖排", "PARTIAL", "排版对齐; 字体重建"),
    ("有机认证图形 (花环/标)", "PARTIAL", "简化重建, 细节与官方有差"),
    ("规格/净含量 250ml", "PLACEHOLDER", "程序化占位, 需官方核准数据"),
    ("侧条品牌竖排信息", "PLACEHOLDER", "当前留白; 真实包装侧条含竖排产品信息, 营养表在背面"),
    ("旋盖滚花/防伪纹理", "PLACEHOLDER", "几何光滑, 纹理未建"),
    ("色差 ΔE vs 官方绿卡", "UNTESTED", "未做分光色差测量; 目测色相在带内"),
    ("授权素材", "MISSING", "当前为研究重建, 商业使用需官方VI授权"),
]
BADGE = {"OK": ("✓ 达标", (26, 107, 69)), "PARTIAL": ("△ 部分对齐", (166, 124, 40)),
         "PLACEHOLDER": ("○ 占位", (140, 90, 30)), "UNTESTED": ("? 待测", (110, 110, 110)),
         "MISSING": ("✗ 需授权", (170, 60, 50))}


def load(path, cell):
    im = Image.open(path).convert("RGB")
    im.thumbnail((cell, cell))
    bg = Image.new("RGB", (cell, cell), (252, 252, 252))
    bg.paste(im, ((cell - im.width) // 2, (cell - im.height) // 2))
    return bg


def main():
    f_t, f_h, f_c, f_b = (ImageFont.truetype(FONT, s) for s in (26, 17, 15, 16))
    CELL, PAD = 340, 16
    cap_cell = 250
    W = PAD + CELL * 4 + PAD * 3 + cap_cell + PAD * 2
    H_TOP = CAP_H = 40 + CELL + 20
    ROW_H = 34
    H = CAP_H + 60 + 8 + len(CHECKS) * ROW_H + 90
    canvas = Image.new("RGB", (W, H), (248, 248, 248))
    d = ImageDraw.Draw(canvas)
    d.text((PAD, 12), "四视角保真验收 · 经典有机 (研究重建级, 非官方认证资产)", fill=(20, 20, 20), font=f_t)
    for k, (nm, key) in enumerate(VIEWS):
        x = PAD + k * (CELL + PAD)
        canvas.paste(load(os.path.join(QA, f"{key}.png"), CELL), (x, 46))
        d.rectangle([x, 46, x + CELL, 46 + CELL], outline=(214, 218, 214))
        d.text((x + 6, 50 + CELL), nm, fill=(90, 90, 90), font=f_b)
    x2 = PAD + CELL * 4 + PAD * 3
    canvas.paste(load(os.path.join(QA, "cap_top.png"), cap_cell), (x2, 46))
    d.rectangle([x2, 46, x2 + cap_cell, 46 + cap_cell], outline=(214, 218, 214))
    d.text((x2 + 6, 50 + cap_cell), "旋盖细节 (俯视)", fill=(90, 90, 90), font=f_b)

    y0 = CAP_H + 78
    d.text((PAD, y0 - 30), "逐项检查清单 (对照官方在售包装目验; 分光色差/字体比对待官方素材)", fill=(60, 60, 60), font=f_h)
    for k, (item, st, note) in enumerate(CHECKS):
        y = y0 + k * ROW_H
        if k % 2 == 0:
            d.rectangle([PAD, y, W - PAD, y + ROW_H - 4], fill=(255, 255, 255))
        label, color = BADGE[st]
        d.text((PAD + 8, y + 5), item, fill=(40, 40, 40), font=f_c)
        d.text((PAD + 400, y + 5), label, fill=color, font=f_c)
        d.text((PAD + 530, y + 5), note, fill=(110, 110, 110), font=f_c)
    y = y0 + len(CHECKS) * ROW_H + 16
    d.text((PAD, y), "结论: 达到「研究重建/技术演示」级保真; 官方认证资产需 VI 授权素材 + 分光色差 + 字库比对后重建。", fill=(140, 60, 40), font=f_b)
    out = os.path.join(BASE, "output", "benchmark", "qa_board.png")
    canvas.save(out)
    print(f"[QABOARD] {out} {canvas.size[0]}x{canvas.size[1]}")


if __name__ == "__main__":
    main()
