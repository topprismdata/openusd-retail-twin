#!/usr/bin/env python3
"""v100 品牌方纯牛奶1L 贴图 atlas (2048x2048, 同经典 UV 契约).
正面: 白底+深蓝弧带+"纯牛奶"大字+品牌logo+三连环徽章+餐饮之选+净含量1L (程序化复刻主图视觉).
背面: 营养成分表(真值277kJ/3.2g/3.8g/4.8g/53mg/100mg)+配料生牛乳+储存条件+条码.
UV: FRONT(60,104,940,1944) BACK(1112,104,1992,1944) SIDE_L(972,104,1010,1944) SIDE_R(1042,104,1080,1944) TOP(60,8,940,72) BOTTOM(1112,8,1992,72)."""
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import os, math

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "assets/textures/carton_1l_albedo.png")
W = H = 2048
BLUE = (20, 55, 130)
DBLUE = (15, 40, 100)
RED = (200, 30, 40)
WHITE = (250, 250, 248)
GOLD = (210, 170, 60)

def font(sz, bold=False):
    paths = ["/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
             "/System/Library/Fonts/Hiragino Sans GB.ttc"]
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, sz, index=0)
            except Exception:
                pass
    return ImageFont.load_default()

def main():
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    # ---- FRONT (60,104)-(940,1944), 880x1840 ----
    fx0, fy0, fx1, fy1 = 60, 104, 940, 1944
    fw, fh = fx1-fx0, fy1-fy0
    # 顶部深蓝弧带
    d.rectangle([fx0, fy0, fx1, fy0+int(fh*0.13)], fill=BLUE)
    # 底部深蓝弧带
    d.rectangle([fx0, fy1-int(fh*0.10), fx1, fy1], fill=BLUE)
    # 品牌 logo (右上): 红字+椭圆
    lx, ly = fx0+int(fw*0.62), fy0+int(fh*0.16)
    d.ellipse([lx-10, ly-10, lx+150, ly+70], outline=BLUE, width=4)
    d.text((lx+18, ly+8), "品牌方", fill=RED, font=font(46))
    d.text((lx-5, ly+78), "虚拟演示产品 · 非在售", fill=(60,60,60), font=font(18))
    # 品牌徽章 (左上, 纯虚构图形: 三连环)
    ox, oy = fx0+int(fw*0.12), fy0+int(fh*0.17)
    rings = [(0,0,BLUE),(36,0,(90,60,160)),(72,0,(40,120,170))]
    for rx, ry, rc in rings:
        d.ellipse([ox+rx, oy+ry, ox+rx+30, oy+ry+30], outline=rc, width=4)
    # "纯牛奶" 大字 (中央, 深蓝, 竖排三字)
    cx = fx0 + fw//2
    chars = "纯牛奶"
    csz = 200
    for i, ch in enumerate(chars):
        cy = fy0 + int(fh*0.30) + i*int(csz*1.05)
        d.text((cx, cy), ch, fill=DBLUE, font=font(csz), anchor="mm")
    # "餐饮之选" 标签
    d.rectangle([cx-90, fy0+int(fh*0.72), cx+90, fy0+int(fh*0.72)+44], fill=DBLUE)
    d.text((cx, fy0+int(fh*0.72)+22), "餐饮之选", fill=WHITE, font=font(28), anchor="mm")
    # 圆形徽章 (右下)
    bx, by = fx0+int(fw*0.72), fy0+int(fh*0.80)
    d.ellipse([bx-70, by-70, bx+70, by+70], fill=GOLD)
    d.ellipse([bx-52, by-52, bx+52, by+52], fill=DBLUE)
    d.text((bx, by-12), "奶香鲜浓", fill=WHITE, font=font(22), anchor="mm")
    d.text((bx, by+16), "奶泡绵密", fill=WHITE, font=font(22), anchor="mm")
    # 净含量 1L (底部)
    d.text((cx, fy1-int(fh*0.045)), "净含量:1L", fill=WHITE, font=font(40), anchor="mm")
    # 3.2g 蛋白卖点 (左下)
    d.text((fx0+int(fw*0.18), fy0+int(fh*0.82)), "3.2g/100mL", fill=BLUE, font=font(30), anchor="mm")
    d.text((fx0+int(fw*0.18), fy0+int(fh*0.82)+36), "优质乳蛋白", fill=(80,80,80), font=font(22), anchor="mm")

    # ---- BACK (1112,104)-(1992,1944) 营养成分表+配料+储存+条码 ----
    bx0, by0, bx1, by1 = 1112, 104, 1992, 1944
    bw, bh = bx1-bx0, by1-by0
    bcx = bx0 + bw//2
    # 标题
    d.text((bcx, by0+80), "营养成分表", fill=(30,30,30), font=font(40), anchor="mm")
    # 表格
    tx0, ty0 = bx0+80, by0+130
    tw, th = bw-160, 560
    d.rectangle([tx0, ty0, tx0+tw, ty0+th], outline=(40,40,40), width=3)
    rows = [("项目","每100mL","NRV%"), ("能量","277kJ","3%"), ("蛋白质","3.2g","5%"),
            ("脂肪","3.8g","6%"), ("碳水化合物","4.8g","2%"), ("钠","53mg","3%"), ("钙","100mg","13%")]
    rh = th // len(rows)
    for i, (a,b,c) in enumerate(rows):
        ry = ty0 + i*rh
        if i > 0:
            d.line([tx0, ry, tx0+tw, ry], fill=(120,120,120), width=1)
        fnt = font(28 if i==0 else 26)
        d.text((tx0+30, ry+rh//2), a, fill=(30,30,30), font=fnt, anchor="lm")
        d.text((tx0+tw//2+40, ry+rh//2), b, fill=(30,30,30), font=fnt, anchor="mm")
        d.text((tx0+tw-50, ry+rh//2), c, fill=(30,30,30), font=fnt, anchor="rm")
    d.line([tx0+tw//2-30, ty0, tx0+tw//2-30, ty0+th], fill=(120,120,120), width=1)
    d.line([tx0+tw-110, ty0, tx0+tw-110, ty0+th], fill=(120,120,120), width=1)
    # 配料/储存
    iy = ty0 + th + 50
    d.text((bx0+90, iy), "配 料：生牛乳", fill=(40,40,40), font=font(28), anchor="lm")
    d.text((bx0+90, iy+50), "产品标准代号：GB 25190", fill=(40,40,40), font=font(26), anchor="lm")
    d.text((bx0+90, iy+100), "贮存条件：未开启前无需冷藏，", fill=(40,40,40), font=font(26), anchor="lm")
    d.text((bx0+90, iy+140), "开启后请贮存于2-6℃并于2日内饮用完毕", fill=(40,40,40), font=font(26), anchor="lm")
    d.text((bx0+90, iy+200), "内蒙古品牌方乳业集团股份有限公司出品", fill=(40,40,40), font=font(26), anchor="lm")
    d.text((bx0+90, iy+245), "消费者服务热线：4008169999", fill=(40,40,40), font=font(26), anchor="lm")
    # 条码 (EAN-13 程序化, 占位系列 6901230*)
    bar_y = by1 - 280
    bar_x = bcx - 200
    rng = np.random.default_rng(11)
    # 简化条码竖条 (视觉真实, 非可扫描)
    x = bar_x
    for i in range(60):
        wbar = int(rng.choice([2,3,4,6]))
        if i % 2 == 0:
            d.rectangle([x, bar_y, x+wbar, bar_y+180], fill=(20,20,20))
        x += wbar + int(rng.choice([2,3,4]))
        if x > bar_x + 400: break
    d.text((bcx, bar_y+200), "6 901230 500123", fill=(30,30,30), font=font(30), anchor="mm")

    # ---- SIDE_L / SIDE_R 窄条: 深蓝竖排"纯牛奶" ----
    for sx0, sx1 in [(972,1010),(1042,1080)]:
        d.rectangle([sx0, 104, sx1, 1944], fill=BLUE)
    # ---- TOP / BOTTOM ----
    d.rectangle([60, 8, 940, 72], fill=WHITE)
    d.rectangle([1112, 8, 1992, 72], fill=WHITE)

    img.save(OUT)
    print("saved", OUT, img.size)
    # 预览
    img.crop((60,104,940,1944)).resize((440,920)).save("/tmp/carton1l_front.png")
    img.crop((1112,104,1992,1944)).resize((440,920)).save("/tmp/carton1l_back.png")

if __name__ == "__main__":
    main()