# 32_topprism_yogurt_label.py — 虚拟品牌 Topprism 酸奶杯标 (GitHub 展示用)
# 品牌: 棱镜极智能 / Topprism (公司自有品牌, 虚拟演示产品, 非在售)
# 设计语言: 白底 + 蓝紫渐变三角棱镜 logo (GitHub org avatar 同源) + 光谱色散条
import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter
W, H = 2048, 560   # 杯侧展开 (杯面实比 ~3.66:1)
BLUE, PURPLE, CYAN = (47, 107, 240), (139, 60, 240), (0, 144, 240)
INK = (24, 28, 38)

def lerp(a, b, t):
    return tuple(int(a[i] + (b[i]-a[i])*t) for i in range(3))

def grad_tri(draw_size, thick=26):
    """渐变描边三角棱镜 (圆角) — 与 org avatar 同构; 2x 超采样抗锯齿"""
    SS = 2
    im = Image.new("RGBA", (draw_size[0]*SS, draw_size[1]*SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    w, h = im.size
    cx, cy = w/2, h/2 + h*0.06
    s = min(w, h)*0.36
    pts = [(cx, cy - s*0.90), (cx - s*0.82, cy + s*0.55), (cx + s*0.82, cy + s*0.55)]
    def seg_grad(p0, p1, c0, c1, steps=128):
        for i in range(steps):
            t0, t1 = i/steps, (i+1.6)/steps
            a = (p0[0]+(p1[0]-p0[0])*t0, p0[1]+(p1[1]-p0[1])*t0)
            b = (p0[0]+(p1[0]-p0[0])*t1, p0[1]+(p1[1]-p0[1])*t1)
            d.line([a, b], fill=lerp(c0, c1, (t0+t1)/2) + (255,), width=thick*SS)
    seg_grad(pts[0], pts[1], CYAN, PURPLE)
    seg_grad(pts[1], pts[2], PURPLE, BLUE)
    seg_grad(pts[2], pts[0], BLUE, CYAN)
    im = im.resize(draw_size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    return im

def font(sz, bold=True):
    cands = [("/System/Library/Fonts/PingFang.ttc", 0 if bold else 1),
             ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
             ("/System/Library/Fonts/STHeiti Light.ttc", 0)]
    for path, idx in cands:
        try:
            return ImageFont.truetype(path, sz, index=idx)
        except Exception:
            continue
    try:
        return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", sz)
    except Exception:
        return ImageFont.load_default()

# ---------- 杯侧标签 ----------
img = Image.new("RGB", (W, H), (252, 252, 253))
d = ImageDraw.Draw(img)
# 顶部品牌带 (蓝紫渐变横带)
for x in range(W):
    t = x / W
    d.line([(x, 0), (x, 80)], fill=lerp(BLUE, PURPLE, t))
d.text((W/2, 74), "T O P P R I S M", font=font(68), fill=(255, 255, 255), anchor="mm")
# 棱镜 logo
logo = grad_tri((250, 250))
img.paste(logo, (int(W/2)-125, 92), logo)
# 品名
d.text((W/2, 388), "希腊式酸奶", font=font(62), fill=INK, anchor="mm")
d.text((W/2, 446), "蓝莓 籽粒型 · 冷藏 · 160g", font=font(30), fill=(90, 96, 112), anchor="mm")
# 光谱色散条 (棱镜色散母题)
sx, sy, sw, sh = 524, 478, 1000, 9
spec = [(0,144,240),(47,107,240),(90,60,235),(139,60,240),(190,45,190),(225,60,120)]
for i in range(sw):
    t = i / sw
    c = spec[min(int(t*(len(spec)-1)*2), len(spec)-2)]
    c2 = spec[min(int(t*(len(spec)-1)*2)+1, len(spec)-1)]
    tt = (t*(len(spec)-1)*2) % 1
    d.line([(sx+i, sy), (sx+i, sy+sh)], fill=lerp(c, c2, tt))
# 底部信息
d.text((W/2, 524), "虚拟演示产品 · 非销售品 · TOPPRISM DATA", font=font(19), fill=(150, 155, 165), anchor="mm")
# 伪条码 (虚构数字)
bx, by = W-330, 452
for i in range(52):
    bw = 2 if i % 3 else 4
    d.rectangle([bx + i*4, by, bx + i*4 + bw, by + 56], fill=INK if i % 2 else (40, 44, 56))
d.text((bx+38, by+68), "6 9 0 1 2 3  4 5 6 7 8", font=font(17), fill=INK, anchor="mm")
img.save("output/github_topprism/cup_label.png")
print("label ok")

# ---------- 铝箔盖 ----------
LID = 1024
lid = Image.new("RGB", (LID, LID), (210, 212, 218))
dl = ImageDraw.Draw(lid)
# 拉丝银
for y in range(LID):
    v = 200 + int(28 * math.sin(y*0.35) ) + int(18 * ((y*7919) % 13) / 13)
    dl.line([(0, y), (LID, y)], fill=(v, v+2, v+6))
dl.ellipse([LID/2-240, LID/2-320, LID/2+240, LID/2+200], fill=(250, 250, 251))
logo2 = grad_tri((320, 320), thick=34)
lid.paste(logo2, (LID//2-160, LID//2-290), logo2)
dl.text((LID/2, LID/2+40), "T O P P R I S M", font=font(44), fill=(70, 74, 88), anchor="mm")
dl.text((LID/2, LID/2+100), "希腊式酸奶 · 撕开即食", font=font(30), fill=(110, 114, 126), anchor="mm")
dl.text((LID/2, LID-56), "△ 虚拟演示产品 · 非销售品", font=font(18), fill=(140, 144, 154), anchor="mm")
lid.save("output/github_topprism/lid_texture.png")
print("lid ok")
