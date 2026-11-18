#!/usr/bin/env python3
"""37_zoo_board.py — 开源资产动物园对照板 (renders -> grid board + standalone HTML 骨架)"""
import os, json
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(HERE, "output/zoo")
man = json.load(open(os.path.join(OUT, "zoo_manifest.json")))

CELL, PAD, BAR = 460, 14, 44
cols = 4
rows = (len(man) + cols - 1) // cols
W = PAD + cols * (CELL + PAD)
H = PAD + BAR + rows * (CELL + 34 + PAD) + 30
board = Image.new("RGB", (W, H), (248, 249, 250))
d = ImageDraw.Draw(board)
def _font(sz):
    for path, idx in (("/System/Library/Fonts/PingFang.ttc", 0),
                      ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
                      ("/System/Library/Fonts/STHeiti Light.ttc", 0)):
        try:
            return ImageFont.truetype(path, sz, index=idx)
        except Exception:
            continue
    return ImageFont.load_default()
f_h = _font(30)
f_c = _font(24)
d.text((PAD, 12), "开源零售资产动物园 · Sketchfab CC × Topprism 徽章化 (CC-BY/CC0, 2026-11-18)", fill=(26, 28, 38), font=f_h)
for i, a in enumerate(man):
    p = os.path.join(OUT, a["key"] + ".png")
    if not os.path.exists(p):
        continue
    im = Image.open(p).convert("RGB").resize((CELL, CELL), Image.LANCZOS)
    x = PAD + (i % cols) * (CELL + PAD)
    y = PAD + BAR + (i // cols) * (CELL + 34 + PAD)
    board.paste(im, (x, y))
    d.rectangle([x, y, x+CELL, y+CELL], outline=(210, 213, 218), width=1)
    lic = "CC0" if "CC0" in a.get("license", "") else "CC-BY"
    # 角标 TOPPRISM 徽章 (白底渐变三角+字标)
    bs = int(CELL * 0.13)
    bx, by = x + CELL - int(bs*2.05), y + CELL - bs - 6
    d.rounded_rectangle([bx, by, bx+int(bs*2.05), by+bs], radius=int(bs*0.14), fill=(255,255,255), outline=(210,213,218))
    cx, cy = bx+int(bs*0.52), by+bs//2
    pts = [(cx, cy-int(bs*0.30)), (cx-int(bs*0.26), cy+int(bs*0.17)), (cx+int(bs*0.26), cy+int(bs*0.17))]
    for i in range(3):
        d.line([pts[i], pts[(i+1) % 3]], fill=[(47,107,240),(139,60,240),(0,144,240)][i], width=max(2, bs//13))
    d.text((bx+int(bs*0.95), by+bs//2), "TOPPRISM", font=f_c, fill=(24,28,38), anchor="lm")
    d.text((x+4, y+CELL+4), f"{a['display']} · {lic} · TOPPRISM", fill=(70, 74, 84), font=f_c)
board.save(os.path.join(OUT, "zoo_board.png"))
print("board", board.size, "->", os.path.join(OUT, "zoo_board.png"))
