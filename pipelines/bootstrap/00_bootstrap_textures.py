#!/usr/bin/env python3
"""
00 - 零依赖零售包装 PBR 材质资产自举生成器 (Zero-Asset Texture Bootstrapper)

生成 (2048x2048 UV atlas, 与 01/02 脚本中的 UV_REGIONS 契约严格对齐):
  1. {sku}_albedo.png (sRGB)       正/背面主视觉 + 营养成分表 + EAN-13 条码 + 侧条
  2. {sku}_orm.png (Non-Color)     R=AO, G=Roughness, B=Metallic (烫金区域像素级同步)
  3. tetrapak_common_normal.png    利乐钻八角折痕 + 封合压线 (全 SKU 通用)

UV atlas 契约 (px, y-down; UV v = 1 - y/2048):
  FRONT  x[60,980]   y[100,1950]   -> 盒正面 (-Y 面)
  BACK   x[1060,1980] y[100,1950]  -> 盒背面 (+Y 面)
  SIDE_L x[984,1022] y[100,1950]   -> 盒左侧面 (-X)
  SIDE_R x[1024,1062] y[100,1950]  -> 盒右侧面 (+X)
  TOP    x[60,980]   y[10,92]      -> 盒顶 (+Z, 喷码区)
  BOTTOM x[1060,1980] y[10,92]     -> 盒底 (-Z)

运行: python3 00_bootstrap_textures.py   (约 2 秒, 仅需 pillow+numpy)
"""
import os
import sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
from pipelines.common.fonts import load_font as _load_font  # noqa: E402

OUTPUT_DIR = os.path.join(BASE_DIR, "assets", "textures")
os.makedirs(OUTPUT_DIR, exist_ok=True)

W, H = 2048, 2048

# ---- UV 区域契约 (与 01/02 脚本一致) ----
# R2 规范 atlas: 岛间 >=32px 间隙 (2x gutter), 零重叠 (Khronos §UV + 审计 R2)
FRONT = (60, 104, 940, 1944)
BACK = (1112, 104, 1992, 1944)
SIDE_L = (972, 104, 1010, 1944)
SIDE_R = (1042, 104, 1080, 1944)
TOP = (60, 8, 940, 72)
BOTTOM = (1112, 8, 1992, 72)

SKU_PROFILES = {
    "demo_yogurt_original": {
        "bg_color": (250, 251, 253),       # 酸奶系列白盒 (爱琴海白墙)
        "accent_color": (26, 78, 150),     # 深爱琴蓝 (正面色带/大字)
        "gold_color": (198, 30, 40),       # 通用块大字色位 -> 酸奶系列红标色
        "base_roughness": 70,              # 光面淋膜纸盒 (~0.28)
        "sides_color": (250, 251, 253),
        "protein": "3.2", "energy": "394", "fat": "3.4", "carb": "12.0",
        "title": "希腊酸奶(演示)",
        "subtitle": "希腊品质 常温保存",
        "barcode": "6901230518888",
        "net": "205 g",
        "amx_gold": False,
    },
    "demo_yogurt_gold": {
        "bg_color": (252, 250, 244),       # 金装: 暖白
        "accent_color": (24, 70, 140),     # 深爱琴蓝
        "gold_color": (196, 150, 60),      # 金装金
        "base_roughness": 70,
        "sides_color": (252, 250, 244),
        "protein": "3.3", "energy": "400", "fat": "3.5", "carb": "12.0",
        "title": "希腊酸奶金装(演示)",
        "subtitle": "金装 希腊品质",
        "barcode": "6901230519999",
        "net": "205 g",
        "amx_gold": True,
    },
    "demo_yogurt_gift": {
        "bg_color": (250, 251, 253),       # 礼盒: 圣托里尼白
        "accent_color": (26, 78, 150),     # 爱琴海蓝
        "gold_color": (196, 150, 60),      # 礼盒金饰线
        "base_roughness": 70,
        "sides_color": (250, 251, 253),
        "protein": "3.2", "energy": "394", "fat": "3.4", "carb": "12.0",
        "title": "希腊酸奶礼盒(演示)",
        "subtitle": "希腊品质 常温保存",
        "barcode": "6901230517777",
        "net": "205 g x 12",
        "amx_gold": True,
    },
    "demo_classic": {
        "bg_color": (136, 114, 78),        # 电商在售: 牛皮纸低碳环保装 (再加深暖, 对齐参照 mid-brown)
        "accent_color": (16, 98, 56),      # 经典绿
        "gold_color": (212, 175, 55),      # 经典烫金
        "base_roughness": 215,             # 牛皮纸哑光 (~0.84, GPT P1-4: 0.82-0.90)
        "sides_color": (136, 114, 78),
        "protein": "3.6", "energy": "309", "fat": "4.4", "carb": "5.0",
        "title": "经典纯牛奶",
        "subtitle": "3.6g/100mL 优质乳蛋白",
        "barcode": "6901230501234",
    },
    "demo_organic": {
        "bg_color": (243, 246, 240),       # 参照经典有机=浅绿白卡瓶身 (参照图+AI直出同源佐证; 深绿实为低碳装元素)
        "accent_color": (16, 96, 60),      # 经典绿
        "gold_color": (226, 186, 92),      # 金盾徽章金
        "base_roughness": 90,              # 淋膜纸面缎光 (~0.35)
        "sides_color": (236, 241, 232),    # 参照浅色瓶身: 侧条同系浅绿白
        "protein": "3.8", "energy": "318", "fat": "4.6", "carb": "5.2",
        "title": "经典有机纯牛奶",
        "subtitle": "3.8g 蛋白质 · 专属有机牧场",
        "barcode": "6901230505678",
    },
    "demo_cny": {
        "bg_color": (168, 28, 38),         # 春节限定: 中国红
        "accent_color": (238, 205, 110),   # 皇家金
        "gold_color": (238, 205, 110),
        "base_roughness": 85,              # 亮面红卡纸
        "sides_color": (168, 28, 38),
        "protein": "3.6", "energy": "309", "fat": "4.4", "carb": "5.0",
        "title": "经典纯牛奶",
        "subtitle": "马年限定版 · 金玉满堂",
        "barcode": "6901230502026",
    },
    "demo_jersey": {
        "bg_color": (22, 24, 28),          # 娟姗奢享黑金
        "accent_color": (218, 182, 95),    # 皇家金
        "gold_color": (238, 205, 110),     # 高亮镜面金
        "base_roughness": 55,              # 镜面高光涂层 (~0.21)
        "protein": "4.0", "energy": "330", "fat": "4.8", "carb": "5.4",
        "title": "经典娟姗纯牛奶",
        "subtitle": "4.0g 原生高蛋白 · 珍稀娟姗牛",
        "barcode": "6901230509999",
    },
    "demo_a2": {
        "bg_color": (240, 246, 252),       # A2β-酪蛋白: 蓝白科技感
        "accent_color": (28, 60, 120),     # 深海蓝
        "gold_color": (180, 200, 230),
        "base_roughness": 90,
        "sides_color": (226, 236, 248),
        "protein": "3.8", "energy": "322", "fat": "4.5", "carb": "5.1",
        "title": "经典A2β-酪蛋白有机纯牛奶",
        "subtitle": "A2β-酪蛋白 · 更亲和易吸收",
        "barcode": "6901230503001",
    },
    "demo_lowfat": {
        "bg_color": (232, 244, 236),       # 高钙低脂: 青绿轻享
        "accent_color": (0, 110, 90),
        "gold_color": (120, 200, 170),
        "base_roughness": 95,
        "sides_color": (222, 238, 228),
        "protein": "3.6", "energy": "262", "fat": "1.2", "carb": "5.6",
        "title": "经典高钙低脂牛奶",
        "subtitle": "低脂 50% 减负 · 高钙 125mg",
        "barcode": "6901230504002",
    },
    "demo_dream38": {
        "bg_color": (250, 244, 230),       # 3.8g 梦幻盖: 奶油白金
        "accent_color": (150, 110, 40),
        "gold_color": (212, 175, 55),
        "base_roughness": 80,
        "sides_color": (244, 236, 218),
        "protein": "3.8", "energy": "318", "fat": "4.5", "carb": "5.0",
        "title": "经典纯奶梦幻盖",
        "subtitle": "3.8g/100mL 优质乳蛋白 · 甘蔗基盖",
        "barcode": "6901230505003",
    },
    "demo_dream40": {
        "bg_color": (248, 246, 252),       # 4.0g 蛋白: 高光白紫
        "accent_color": (88, 52, 140),
        "gold_color": (200, 170, 220),
        "base_roughness": 75,
        "sides_color": (240, 236, 248),
        "protein": "4.0", "energy": "332", "fat": "4.9", "carb": "5.3",
        "title": "经典4.0g蛋白纯牛奶",
        "subtitle": "4.0g 浓缩蛋白 · 浓醇加倍",
        "barcode": "6901230506004",
    },
    "demo_skim": {
        "bg_color": (228, 240, 250),       # 脱脂: 冰蓝轻盈
        "accent_color": (40, 110, 180),
        "gold_color": (150, 200, 240),
        "base_roughness": 95,
        "sides_color": (218, 234, 246),
        "protein": "3.6", "energy": "245", "fat": "0.0", "carb": "5.8",
        "title": "经典脱脂纯牛奶",
        "subtitle": "0 负担 · 脱脂不脱营养",
        "barcode": "6901230507005",
    },
    "demo_meadow": {
        "bg_color": (232, 196, 120),       # 呼伦贝尔有机: 金草甸特别版
        "accent_color": (20, 60, 130),
        "gold_color": (238, 205, 110),
        "base_roughness": 100,
        "sides_color": (226, 190, 116),
        "protein": "3.9", "energy": "325", "fat": "4.7", "carb": "5.2",
        "title": "经典草原有机纯牛奶",
        "subtitle": "北纬49° 黄金奶源带限定",
        "barcode": "6901230508006",
    },
}


_SERIF = "/System/Library/Fonts/Supplemental/Songti.ttc"  # 仅保留作旧引用; 实际解析见 pipelines/common/fonts.py


def get_serif_font(size):
    """衬线中文字体 (跨平台)。"""
    return _load_font(size, kind="serif", index=1)


def get_font(size):
    """中文黑体字体 (跨平台)。"""
    return _load_font(size, kind="cjk")


def generate_crease_normal_map():
    """利乐钻八角竖向折痕 + 顶部/底部封合压线 Normal Map (全 SKU 通用)"""
    norm = np.zeros((H, W, 3), dtype=np.uint8)
    norm[:, :, 0] = 128
    norm[:, :, 1] = 128
    norm[:, :, 2] = 255

    # 竖向折痕: 正面区外缘(60/980) + 八角倒角内缘(~146/894), 背面对称(1060/1146/1894/1980)
    crease_x = [60, 146, 894, 980, 1060, 1146, 1894, 1980]
    body_rows = slice(FRONT[1], FRONT[3])
    for cx in crease_x:
        for dx in range(-9, 10):
            x = cx + dx
            if 0 <= x < W:
                slope = int(38 * np.sin(dx / 9.0 * np.pi))
                norm[body_rows, x, 0] = np.clip(128 + slope, 0, 255)

    # 横向封口压线 (顶 y=100 / 底 y=1950)
    for cy in [FRONT[1], FRONT[3]]:
        for dy in range(-7, 8):
            y = cy + dy
            if 0 <= y < H:
                slope = int(35 * np.sin(dy / 7.0 * np.pi))
                norm[y, :, 1] = np.clip(128 + slope, 0, 255)

    # 细微纸面纤维噪点
    rng = np.random.default_rng(2026)
    grain = rng.integers(-2, 3, size=(H, W, 2), dtype=np.int16)
    norm[:, :, :2] = np.clip(norm[:, :, :2].astype(np.int16) + grain, 0, 255).astype(np.uint8)

    Image.fromarray(norm).save(os.path.join(OUTPUT_DIR, "tetrapak_common_normal.png"))
    print("[OK] tetrapak_common_normal.png")


def draw_amx_side_strips(draw, draw_metal, cfg, aegean=(26, 78, 150)):
    """酸奶系列侧条: 爱琴蓝底 + 白字竖排 GREEKY + 小圆顶"""
    for region in (SIDE_L, SIDE_R):
        draw.rectangle(region, fill=aegean)
        rx = (region[0] + region[2]) // 2
        top_ = region[1] + 150
        for i, ch in enumerate("GREEKY"):
            draw.text((rx, top_ + i * 175), ch, fill=(240, 246, 252), font=get_font(118), anchor="mm")
        dr_ = 40
        draw.pieslice([rx - dr_, region[3] - 420 - dr_, rx + dr_, region[3] - 420 + dr_], 180, 360, fill=(240, 246, 252))


def draw_side_strips(draw_albedo, draw_metal, cfg):
    """两侧条: 品牌色底 + 烫金徽标点 (同步写金属遮罩)"""
    for rect in (SIDE_L, SIDE_R):
        x0, y0, x1, y1 = rect
        draw_albedo.rectangle(rect, fill=cfg.get("sides_color", cfg["accent_color"]))
        # 顶部小烫金方标
        cx = (x0 + x1) // 2
        s = (x1 - x0) - 8
        draw_albedo.rectangle([cx - s // 2, y0 + 60, cx + s // 2, y0 + 60 + s], fill=cfg["gold_color"])
        draw_metal.rectangle([cx - s // 2, y0 + 60, cx + s // 2, y0 + 60 + s], fill=255)


def draw_top_bottom(draw_albedo, cfg):
    """顶: 喷码区 (生产日期); 底: 素色"""
    draw_albedo.rectangle(TOP, fill=(246, 244, 240))
    draw_albedo.text((TOP[0] + 40, TOP[1] + 40), "20261106 G6",
                     fill=(128, 122, 110), font=get_font(16))   # 淡灰点阵喷码 (原30px黑字在45°读作暗槽)
    draw_albedo.rectangle(BOTTOM, fill=(235, 235, 230))


def _leaf(draw, cx, cy, length, width, angle, color):
    """参数化叶片 (椭圆叶形 + 旋转), 用于花环/水彩点缀"""
    pts = []
    for t in np.linspace(0, 2 * np.pi, 26):
        px = length * np.cos(t)
        py = width * np.sin(t) * (0.55 + 0.45 * np.cos(t))
        ca, sa = np.cos(angle), np.sin(angle)
        pts.append((cx + px * ca - py * sa, cy + px * sa + py * ca))
    draw.polygon(pts, fill=color)


def _reset_front(draw, draw_metal, cfg):
    """覆盖默认版式: 清空正面区 + 清金属遮罩"""
    draw.rectangle(FRONT, fill=cfg["bg_color"])
    draw_metal.rectangle(FRONT, fill=0)


def draw_yogurt_front(draw, draw_metal, cfg, gold=False):
    """酸奶系列 205g 利乐钻正面 (参照版式): 顶部横排酸奶系列/希腊风味酸奶 + 中部爱琴海场景 + 下部深蓝信息块"""
    _reset_front(draw, draw_metal, cfg)
    fx0, fy0, fx1, fy1 = FRONT
    w = fx1 - fx0
    cx = (fx0 + fx1) // 2
    aegean = cfg["accent_color"]
    navy = (18, 52, 110)
    white = (252, 253, 255)
    goldc = cfg["gold_color"] if gold else aegean
    draw.text((cx, fy0 + 265), "希腊酸奶", fill=navy, font=get_font(int(w * 0.175)), anchor="mm")
    draw.text((cx, fy0 + 445), ("金装 " if gold else "") + "希腊风味酸奶", fill=(45, 55, 70),
              font=get_font(int(w * 0.062)), anchor="mm")
    band_y = fy0 + 540
    band_h = 700
    draw.rectangle([fx0 + 60, band_y, fx1 - 60, band_y + band_h], fill=(238, 245, 251))
    sea_y = band_y + int(band_h * 0.62)
    draw.rectangle([fx0 + 60, sea_y, fx1 - 60, band_y + band_h], fill=(206, 228, 244))
    dome_r = int(w * 0.135)
    for dx_, rr in [(int(w * 0.24), dome_r), (int(w * 0.52), int(dome_r * 0.74)),
                    (int(w * 0.73), int(dome_r * 0.55))]:
        cx_ = fx0 + dx_
        draw.pieslice([cx_ - rr, sea_y - rr, cx_ + rr, sea_y + rr], 180, 360, fill=aegean)
        draw.rectangle([cx_ - int(rr * 0.62), sea_y, cx_ + int(rr * 0.62), sea_y + int(rr * 1.15)], fill=white)
        draw.rectangle([cx_ - 5, sea_y - rr - int(rr * 0.4), cx_ + 5, sea_y - rr], fill=aegean)
    bw_ = int(w * 0.20)
    bcx, bcy = fx0 + int(w * 0.60), band_y + int(band_h * 0.80)
    draw.ellipse([bcx - bw_, bcy - int(bw_ * 0.55), bcx + bw_, bcy + int(bw_ * 0.55)],
                 fill=white, outline=(195, 210, 230), width=5)
    draw.arc([bcx - int(bw_ * 0.6), bcy - int(bw_ * 0.32), bcx + int(bw_ * 0.6), bcy + int(bw_ * 0.32)],
             200, 80, fill=(216, 230, 245), width=int(bw_ * 0.24))
    nb0 = band_y + band_h + 60
    nb1 = nb0 + int(w * 0.34)
    draw.rectangle([fx0 + 60, nb0, fx1 - 60, nb1], fill=navy)
    draw.text((cx, nb0 + int(w * 0.085)), "希腊风味 常温保存", fill=white,
              font=get_font(int(w * 0.052)), anchor="mm")
    draw.text((cx, nb1 + int(w * 0.11)), "GREEKY", fill=goldc,
              font=get_font(int(w * 0.075)), anchor="mm")
    draw.text((cx, fy1 - 150), f"净含量: {cfg.get('net', '205 g')}", fill=(100, 112, 132),
              font=get_font(int(w * 0.042)), anchor="mm")
    draw.rectangle([fx0 + 60, fy0 + 120, fx0 + 88, fy1 - 120], fill=aegean)


def draw_yogurt_gift_front(draw, draw_metal, cfg):
    """酸奶礼盒横版正面: 左蓝竖带 GREEKY 竖排 + 中部横排希腊风味酸奶 + 酸奶碗 + 金装标"""
    fx0, fy0, fx1, fy1 = 60, 816, 980, 1234        # GIFT_FRONT 横条 (与 01 GIFT_FRONT_UV 约定一致)
    w = fx1 - fx0
    h = fy1 - fy0
    cy = (fy0 + fy1) // 2
    aegean = (26, 78, 150)
    navy = (18, 52, 110)
    white = (252, 253, 255)
    goldc = cfg["gold_color"]
    draw.rectangle([fx0, fy0, fx1, fy1], fill=(248, 251, 254))
    bx1_ = fx0 + int(w * 0.235)
    draw.rectangle([fx0, fy0, bx1_, fy1], fill=aegean)
    dr_ = int(w * 0.045)
    dcx = fx0 + int(w * 0.105)
    draw.pieslice([dcx - dr_, fy0 + int(h * 0.12) - dr_, dcx + dr_, fy0 + int(h * 0.12) + dr_],
                  180, 360, fill=white)
    draw.rectangle([dcx - int(dr_ * 0.62), fy0 + int(h * 0.12), dcx + int(dr_ * 0.62), fy0 + int(h * 0.20)],
                   fill=aegean)
    amb_y = fy0 + int(h * 0.36)
    for i, ch in enumerate("GREEKY"):
        draw.text((dcx, amb_y + i * int(w * 0.0245)), ch, fill=white,
                  font=get_font(int(w * 0.023)), anchor="mm")
    draw.text((dcx, fy1 - int(h * 0.10)), "净含量", fill=(210, 228, 245),
              font=get_font(int(w * 0.026)), anchor="mm")
    mx = bx1_ + int(w * 0.04)
    draw.text((mx, fy0 + int(h * 0.25)), "希腊酸奶", fill=navy,
              font=get_font(int(w * 0.105)), anchor="lm")
    draw.text((mx + int(w * 0.30), fy0 + int(h * 0.24)), "®", fill=navy,
              font=get_font(int(w * 0.022)), anchor="lm")
    draw.text((mx, fy0 + int(h * 0.42)), "希腊风味酸奶", fill=(45, 55, 70),
              font=get_font(int(w * 0.058)), anchor="lm")
    jb = [fx1 - int(w * 0.13), fy0 + int(h * 0.07), fx1 - int(w * 0.02), fy0 + int(h * 0.29)]
    draw.rounded_rectangle(jb, radius=8, fill=goldc)
    draw.text(((jb[0] + jb[2]) // 2, (jb[1] + jb[3]) // 2), "金装", fill=white,
              font=get_font(int(w * 0.042)), anchor="mm")
    bowl_cx = mx + int(w * 0.155)
    bowl_cy = fy0 + int(h * 0.66)
    br_ = int(w * 0.125)
    draw.ellipse([bowl_cx - br_, bowl_cy - int(br_ * 0.62), bowl_cx + br_, bowl_cy + int(br_ * 0.62)],
                 fill=(240, 244, 250), outline=(190, 205, 225), width=4)
    sw_ = int(br_ * 0.72)
    draw.arc([bowl_cx - sw_, bowl_cy - int(sw_ * 0.58), bowl_cx + sw_, bowl_cy + int(sw_ * 0.58)],
             200, 80, fill=(215, 228, 244), width=int(br_ * 0.22))
    draw.arc([bowl_cx - int(sw_ * 0.55), bowl_cy - int(sw_ * 0.32), bowl_cx + int(sw_ * 0.55), bowl_cy + int(sw_ * 0.32)],
             210, 70, fill=(228, 238, 249), width=int(br_ * 0.16))
    dm_cx = mx + int(w * 0.42)
    dm_r = int(w * 0.068)
    draw.pieslice([dm_cx - dm_r, bowl_cy - int(br_ * 0.4) - dm_r, dm_cx + dm_r, bowl_cy - int(br_ * 0.4) + dm_r],
                  180, 360, fill=aegean)
    draw.rectangle([dm_cx - int(dm_r * 0.6), bowl_cy - int(br_ * 0.4), dm_cx + int(dm_r * 0.6),
                    bowl_cy + int(br_ * 0.16)], fill=(252, 253, 255), outline=(205, 220, 238), width=2)
    draw.text((mx, fy1 - int(h * 0.13)), "希腊风味 常温保存", fill=(75, 92, 120),
              font=get_font(int(w * 0.036)), anchor="lm")
    draw.text((mx, fy1 - int(h * 0.055)), f"净含量: {cfg.get('net', '205 g x 12')}  蛋白质 3.2g/100g",
              fill=(95, 108, 130), font=get_font(int(w * 0.030)), anchor="lm")


def _squeeze(draw, text, x0, y0, x1, y1, color, weight):
    """把文字渲染进指定盒并横向压缩 (参照书法窄长), weight=加墨描边像素。"""
    from PIL import Image as _I
    from PIL import ImageDraw as _ID
    bw, bh = x1 - x0, y1 - y0
    tmp = _I.new("RGBA", (bw * 2, bh * 2), (0, 0, 0, 0))
    td = _ID.Draw(tmp)
    f = get_serif_font(min(int(bh * 2 * 0.92), int(bw * 2 / max(1, len(text)) * 0.96)))
    for dx in range(weight * 2):
        td.text((bw, bh + dx // 2), text, fill=color + (255,), font=f, anchor="mm")
    tmp = tmp.resize((bw, bh), _I.LANCZOS)
    draw._image.paste(tmp, (x0, y0), tmp)


def draw_classic_front(draw, draw_metal, cfg):
    """经典低碳装正面: 仅 kraft 纸基 + 纤维; 品牌印刷层由 15_texture_lift.py
    从参照照片像素提升叠入 (人眼不可辨目标, 程序化重绘达不到)。"""
    _reset_front(draw, draw_metal, cfg)
    fx0, fy0, fx1, fy1 = FRONT
    import random as _rd
    rng = _rd.Random(11)
    for _ in range(2600):
        px_, py_ = rng.randint(fx0, fx1), rng.randint(fy0, fy1)
        g_ = rng.randint(-14, 10)
        draw.point((px_, py_), fill=(146 + g_, 124 + g_, 86 + g_))

    # 程序化保留元素 (源照片分辨率不足 lift): 纯牛奶 squeeze 书法 / 双指标 / 低碳牧场 / 净含量
    green = (15, 61, 31)

    def Y(f):
        return fy0 + int((fy1 - fy0) * f)

    def X(f):
        return fx0 + int((fx1 - fx0) * f)

    w = fx1 - fx0
    h = fy1 - fy0
    iy = Y(0.605)
    draw.text((X(0.10), iy), "3.6", fill=green, font=get_font(int(w * 0.135)), anchor="lm")
    draw.text((X(0.10) + int(w * 0.145), iy - 16), "g", fill=green, font=get_font(int(w * 0.042)), anchor="lm")
    draw.text((X(0.10) + int(w * 0.145), iy + 18), "100mL", fill=green, font=get_font(int(w * 0.036)), anchor="lm")
    draw.text((X(0.10), iy + int(h * 0.045)), "原生乳蛋白", fill=green, font=get_font(int(w * 0.048)), anchor="lm")
    draw.line([X(0.47), iy - 34, X(0.47), iy + 40], fill=green, width=4)
    draw.text((X(0.52), iy), "120", fill=green, font=get_font(int(w * 0.125)), anchor="lm")
    draw.text((X(0.52) + int(w * 0.155), iy - 16), "mg", fill=green, font=get_font(int(w * 0.040)), anchor="lm")
    draw.text((X(0.52) + int(w * 0.155), iy + 18), "100mL", fill=green, font=get_font(int(w * 0.034)), anchor="lm")
    draw.text((X(0.52), iy + int(h * 0.045)), "原生高钙", fill=green, font=get_font(int(w * 0.048)), anchor="lm")
    _squeeze(draw, "低碳", X(0.10), Y(0.655), X(0.44), Y(0.715), green, 2)
    _squeeze(draw, "牧场", X(0.52), Y(0.655), X(0.86), Y(0.715), green, 2)
    lb = [X(0.44), Y(0.075), X(0.84), Y(0.315)]
    draw.rounded_rectangle(lb, radius=8, fill=green)
    draw.text(((lb[0] + lb[2]) // 2, Y(0.160)), "经典", fill=(206, 168, 82),
              font=get_serif_font(int((lb[2] - lb[0]) * 0.40)), anchor="mm")
    draw.text(((lb[0] + lb[2]) // 2, Y(0.262)), "CLASSIC", fill=(206, 168, 82),
              font=get_font(int((lb[2] - lb[0]) * 0.13)), anchor="mm")
    draw.text((X(0.94), Y(0.068)), "源自经典严选牧场", fill=green,
              font=get_font(int((fy1 - fy0) * 0.026)), anchor="rm")
    _squeeze(draw, "纯牛奶", X(0.08), Y(0.705), X(0.92), Y(0.925), green, 3)
    draw.text((X(0.08), Y(0.935)), "净含量: 250mL", fill=green, font=get_font(int(h * 0.036)), anchor="lm")
    draw.text((X(0.08), Y(0.978)), "生产日期/保质期至: 见盒顶部喷码", fill=green,
              font=get_font(int(h * 0.026)), anchor="lm")

def draw_cny_front(draw, draw_metal, cfg):
    """春节马年限定红装: 中国红底 + 经典金字标 + 金叶花环 + 白字竖排纯牛奶"""
    _reset_front(draw, draw_metal, cfg)
    fx0, fy0, fx1, fy1 = FRONT
    w = fx1 - fx0
    cx = (fx0 + fx1) // 2
    gold = (238, 205, 110)
    deep_gold = (196, 158, 66)
    # 顶部饰线: 金玉满堂贺岁装
    draw.text((cx, fy0 + 120), "— 金玉满堂 · 马年限定 —", fill=gold,
              font=get_font(int(w * 0.056)), anchor="mm")
    # 左上经典金框标 (红底金字)
    lw_ = int(w * 0.30)
    lb = [fx0 + int(w * 0.10), fy0 + 200, fx0 + int(w * 0.10) + lw_, fy0 + 200 + lw_]
    draw.rounded_rectangle(lb, radius=16, outline=gold, width=8)
    draw.text((lb[0] + 18, lb[1] + 22), "经典", fill=gold, font=get_font(int(lw_ * 0.40)))
    draw.text((lb[0] + 16, lb[1] + int(lw_ * 0.58)), "CLASSIC", fill=(250, 236, 200),
              font=get_font(int(lw_ * 0.15)))
    draw_metal.rounded_rectangle(lb, radius=16, outline=255, width=8)
    # 右上马年徽章 (金色圆形)
    r_ = int(w * 0.105)
    bc = [fx1 - int(w * 0.10) - 2 * r_, fy0 + 210, fx1 - int(w * 0.10), fy0 + 210 + 2 * r_]
    draw.ellipse(bc, fill=deep_gold)
    draw.text(((bc[0] + bc[2]) // 2, (bc[1] + bc[3]) // 2 - int(r_ * 0.25)), "马年",
              fill=(255, 244, 214), font=get_font(int(r_ * 0.7)), anchor="mm")
    draw.text(((bc[0] + bc[2]) // 2, (bc[1] + bc[3]) // 2 + int(r_ * 0.42)), "限定",
              fill=(255, 244, 214), font=get_font(int(r_ * 0.5)), anchor="mm")
    # 竖排大字 纯牛奶 (白色书法位)
    for i, ch in enumerate("纯牛奶"):
        draw.text((int(fx0 + w * 0.24), fy0 + 560 + i * 235), ch, fill=(252, 248, 240),
                  font=get_font(215))
    # 金叶花环
    ring_cx, ring_cy, ring_r = int(cx + w * 0.24), fy0 + 1000, int(w * 0.27)
    for ang in range(0, 360, 22):
        a = np.radians(ang)
        lx = ring_cx + ring_r * np.cos(a) * 0.94
        ly = ring_cy + ring_r * np.sin(a) * 1.0
        col = gold if ang % 44 == 0 else deep_gold
        _leaf(draw, lx, ly, w * 0.075, w * 0.038, a + 0.6, col)
    draw.text((ring_cx, ring_cy - 40), "3.6g", fill=(168, 28, 38),
              font=get_font(int(w * 0.11)), anchor="mm")
    draw.text((ring_cx, ring_cy + 52), "120mg 钙", fill=(255, 244, 214),
              font=get_font(int(w * 0.055)), anchor="mm")
    # 底部净含量
    draw.text((cx, fy1 - 130), "净含量: 250mL", fill=(255, 236, 200),
              font=get_font(int(w * 0.052)), anchor="mm")


def draw_organic_front(draw, draw_metal, cfg):
    """复刻经典有机纯牛奶 (参照图: 深绿瓶身): 经典绿方标+金描边 + 金盾徽章 + 水彩叶 + 米白竖排品名"""
    _reset_front(draw, draw_metal, cfg)
    fx0, fy0, fx1, fy1 = FRONT
    w = fx1 - fx0
    cx = (fx0 + fx1) // 2
    green = (16, 96, 60)  # 经典绿方标 (浅色瓶身, 原版配色)
    # 顶部居中经典绿方标 (加大: 参照方标占比~34%)
    lw_ = int(w * 0.34)
    lb = [cx - lw_ // 2, fy0 + 120, cx + lw_ // 2, fy0 + 120 + lw_]
    draw.rounded_rectangle(lb, radius=18, fill=green, outline=(214, 182, 95), width=6)
    draw.text((lb[0] + lw_ // 2, lb[1] + int(lw_ * 0.32)), "经典", fill=(250, 250, 248),
              font=get_font(int(lw_ * 0.40)), anchor="mm")
    draw.text((lb[0] + lw_ // 2, lb[1] + int(lw_ * 0.70)), "CLASSIC", fill=(214, 182, 95),
              font=get_font(int(lw_ * 0.15)), anchor="mm")
    draw.text((cx, lb[3] + 58), "3.8g 优质乳蛋白 · 专属有机牧场", fill=(16, 96, 60),
              font=get_font(int(w * 0.052)), anchor="mm")
    # 金盾徽章 (活性乳铁蛋白 65mg)
    shield_cy = fy0 + 800
    sw, sh = int(w * 0.36), int(w * 0.42)
    sx0, sy0 = cx - sw // 2, shield_cy - sh // 2
    sx1, sy1 = cx + sw // 2, shield_cy + sh // 2
    shield = [(sx0 + 28, sy0), (sx1 - 28, sy0), (sx1, sy0 + int(sh * 0.26)),
              (sx1, sy0 + int(sh * 0.60)), (cx, sy1), (sx0, sy0 + int(sh * 0.60)),
              (sx0, sy0 + int(sh * 0.26))]
    draw.polygon(shield, fill=(226, 186, 92), outline=(198, 154, 62))
    draw_metal.polygon(shield, fill=255)
    draw.text((cx, sy0 + int(sh * 0.20)), "活性", fill=(250, 250, 248),
              font=get_font(int(sh * 0.15)), anchor="mm")
    draw.text((cx, sy0 + int(sh * 0.36)), "乳铁蛋白", fill=(250, 250, 248),
              font=get_font(int(sh * 0.15)), anchor="mm")
    draw.text((cx, sy0 + int(sh * 0.55)), "65", fill=(250, 250, 248),
              font=get_font(int(sh * 0.24)), anchor="mm")
    draw.text((cx, sy0 + int(sh * 0.72)), "mg/100mL", fill=(250, 250, 248),
              font=get_font(int(sh * 0.10)), anchor="mm")
    # 水彩植物点缀 (盾周)
    leaf_cols = [(70, 140, 80), (110, 170, 95), (80, 150, 120), (90, 160, 110), (70, 130, 150)]
    for (dx, dy, ln, wd, ang, ci) in [
        (-0.26, -0.10, 0.09, 0.042, -0.9, 0), (0.26, -0.06, 0.08, 0.04, 0.8, 1),
        (-0.30, 0.14, 0.10, 0.045, -1.6, 2), (0.30, 0.18, 0.09, 0.042, 1.5, 3),
        (-0.16, 0.26, 0.07, 0.036, -0.4, 4), (0.18, 0.28, 0.075, 0.036, 2.4, 0),
    ]:
        _leaf(draw, cx + int(w * dx), shield_cy + int(w * dy),
              w * ln, w * wd, ang, leaf_cols[ci])
    # 竖排品名 有机纯牛奶 (下部居中书法位)
    for i, ch in enumerate("有机纯牛奶"):
        draw.text((int(cx), fy0 + 1108 + i * 118), ch, fill=(16, 96, 60), font=get_font(118))
    # 底部净含量
    draw.text((cx, fy1 - 44), "净含量: 250mL", fill=(226, 232, 224),
              font=get_font(int(w * 0.040)), anchor="mm")


def generate_sku_textures(sku_key, cfg):
    # 1. 画布: Albedo + ORM 矩阵 + 金属遮罩
    albedo = Image.new("RGB", (W, H), cfg["bg_color"])
    draw = ImageDraw.Draw(albedo)

    orm = np.zeros((H, W, 3), dtype=np.uint8)
    orm[:, :, 0] = 250                     # R: AO 高通过率
    orm[:, :, 1] = cfg["base_roughness"]   # G: 基底纸面粗糙度
    orm[:, :, 2] = 0                       # B: 默认非金属

    metal_mask = Image.new("L", (W, H), 0)
    draw_metal = ImageDraw.Draw(metal_mask)

    # 2. 正面视觉区 (FRONT)
    fx0, fy0, fx1, fy1 = FRONT
    # 烫金徽章绶带
    draw.rectangle([fx0 + 190, fy0 + 260, fx1 - 190, fy0 + 340], fill=cfg["gold_color"])
    draw_metal.rectangle([fx0 + 190, fy0 + 260, fx1 - 190, fy0 + 340], fill=255)
    draw.text((fx0 + 265, fy0 + 268), "CLASSIC · 经典", fill=(30, 30, 30), font=get_font(48))
    # 主标题 (烫金) 与副标题
    draw.text((fx0 + 150, fy0 + 430), cfg["title"], fill=cfg["gold_color"], font=get_font(86))
    draw_metal.text((fx0 + 150, fy0 + 430), cfg["title"], fill=255, font=get_font(86))
    draw.text((fx0 + 160, fy0 + 580), cfg["subtitle"], fill=cfg["accent_color"], font=get_font(42))
    # 蛋白含量大字块
    draw.text((fx0 + 150, fy0 + 760), cfg["protein"] + "g", fill=cfg["gold_color"], font=get_font(120))
    draw_metal.text((fx0 + 150, fy0 + 760), cfg["protein"] + "g", fill=255, font=get_font(120))
    draw.text((fx0 + 150, fy0 + 910), "优质乳蛋白 / 100mL", fill=cfg["accent_color"], font=get_font(38))
    # 净含量
    draw.text((fx0 + 200, fy1 - 220), f"净含量: {cfg.get('net', '250 mL')}", fill=cfg["accent_color"], font=get_font(46))

    # 2.5 参照复刻版式覆盖 (电商在售牛皮纸装 / 白底金盾装)
    if sku_key == "demo_classic":
        draw_classic_front(draw, draw_metal, cfg)
    elif sku_key == "demo_organic":
        draw_organic_front(draw, draw_metal, cfg)
    elif sku_key == "demo_cny":
        draw_cny_front(draw, draw_metal, cfg)
    elif sku_key == "demo_yogurt_gift":
        draw.rectangle(FRONT, fill=cfg["bg_color"])
        draw_metal.rectangle(FRONT, fill=0)
        draw_yogurt_gift_front(draw, draw_metal, cfg)
        draw_amx_side_strips(draw, draw_metal, cfg)
    elif sku_key.startswith("demo_yogurt_"):
        draw_yogurt_front(draw, draw_metal, cfg, gold=cfg.get("amx_gold", False))
        draw_amx_side_strips(draw, draw_metal, cfg)

    # 3. 背面合规信息区 (BACK)
    nx0, ny0, nx1, ny1 = BACK
    draw.rectangle([nx0 + 110, ny0 + 250, nx1 - 110, ny0 + 880],
                   fill=(250, 250, 250), outline=(40, 40, 40), width=4)
    draw.text((nx0 + 260, ny0 + 268), "营养成分表", fill=(20, 20, 20), font=get_font(44))

    nutrients = [
        ("项目", "每100mL", "NRV%"),
        ("能量", cfg["energy"] + " 千焦(kJ)", "4%"),
        ("蛋白质", cfg["protein"] + " 克(g)", "6%"),
        ("脂肪", cfg["fat"] + " 克(g)", "7%"),
        ("碳水化合物", cfg["carb"] + " 克(g)", "2%"),
        ("钠", "65 毫克(mg)", "3%"),
        ("钙", "125 毫克(mg)", "16%"),
    ]
    for idx, (c1, c2, c3) in enumerate(nutrients):
        ry = ny0 + 330 + idx * 75
        draw.line([(nx0 + 130, ry - 12), (nx1 - 130, ry - 12)], fill=(180, 180, 180), width=2)
        draw.text((nx0 + 145, ry), c1, fill=(30, 30, 30), font=get_font(32))
        draw.text((nx0 + 370, ry), c2, fill=(30, 30, 30), font=get_font(32))
        draw.text((nx0 + 620, ry), c3, fill=(30, 30, 30), font=get_font(32))
    draw.text((nx0 + 130, ny0 + 900), "GB 25190 — 全脂灭菌乳", fill=(60, 60, 60), font=get_font(30))

    # EAN-13 视觉条码 (确定性伪随机, 供 CV 朝向/OCR 训练)
    bx0, by0, bx1, by1 = nx0 + 200, ny0 + 1160, nx1 - 200, ny0 + 1500
    draw.rectangle([bx0, by0, bx1, by1], fill=(255, 255, 255))
    rng = np.random.default_rng(int(cfg["barcode"][-6:]))
    cur_x = bx0 + 40
    while cur_x < bx1 - 40:
        bar_w = int(rng.choice([4, 8, 14]))
        draw.rectangle([cur_x, by0 + 25, cur_x + bar_w, by1 - 60], fill=(10, 10, 10))
        cur_x += bar_w + int(rng.choice([4, 8, 12]))
    draw.text((bx0 + 70, by1 - 55), cfg["barcode"], fill=(10, 10, 10), font=get_font(38))

    # 4. 侧条 / 顶底
    draw_side_strips(draw, draw_metal, cfg)
    draw_top_bottom(draw, cfg)
    # 顶/底/侧条粗糙度: 顶部喷码区略哑光, 侧条同基底
    ty0, ty1 = TOP[1], TOP[3]
    orm[ty0:ty1, TOP[0]:TOP[2], 1] = 120
    for rect in (SIDE_L, SIDE_R, BOTTOM):
        orm[rect[1]:rect[3], rect[0]:rect[2], 1] = cfg["base_roughness"]

    # 4.5 印刷光油 (spot varnish): 图文区比纸底略亮略滑 -> roughness 下调
    alb = np.asarray(albedo).astype(np.int16)
    _bg = np.array(cfg["bg_color"], dtype=np.int16)
    gfx = (np.abs(alb - _bg).sum(axis=-1) > 60)
    orm[:, :, 1] = np.where(gfx, np.maximum(28, orm[:, :, 1].astype(np.int16) - 30),
                            orm[:, :, 1]).astype(np.uint8)
    # 4.6 折边/压痕 AO: 各面边界内缩带微暗 (真实折边遮蔽)
    for rect in (FRONT, BACK):
        x0, y0, x1, y1 = rect
        bd = min(26, (x1 - x0) // 3, (y1 - y0) // 3)
        orm[y0:y0 + bd, x0:x1, 0] = 205
        orm[y1 - bd:y1, x0:x1, 0] = 205
        orm[y0:y1, x0:x0 + bd, 0] = 205
        orm[y0:y1, x1 - bd:x1, 0] = 205
    # 4.7 牛皮纸纤维: 哑光纸面粗糙度细噪声 (淋膜纸不加)
    if cfg["base_roughness"] >= 100:
        _rng = np.random.default_rng(7)
        _fib = _rng.normal(0, 5, (H, W)).astype(np.int16)
        orm[:, :, 1] = np.clip(orm[:, :, 1].astype(np.int16) + _fib, 0, 255).astype(np.uint8)

    # 4.75 侧/顶/底区素纸化 (防跨区印刷屑成为游离几何源)
    import random as _rd2
    _rng2 = _rd2.Random(5)
    for rect in (SIDE_L, SIDE_R, TOP, BOTTOM):
        x0, y0, x1, y1 = rect
        for yy in range(y0, y1):
            for xx in range(x0, x1, 1):
                g2 = _rng2.randint(-10, 8)
                _sc = cfg.get("sides_color", cfg["bg_color"])
                draw.point((xx, yy), fill=(_sc[0] + g2, _sc[1] + g2, _sc[2] + g2))

    # 4.8 R2 规范: 区域边缘 16px 颜色/粗糙度扩张 (Khronos §UV + 审计 R2:
    #     防 mipmap/倒角面/压缩纹理跨岛串色; 复制边界像素填 gutter)
    GUT = 16
    _alb = np.asarray(albedo).copy()
    for rect in (FRONT, BACK, SIDE_L, SIDE_R, TOP, BOTTOM):
        x0, y0, x1, y1 = rect
        for arr in (_alb, orm):
            arr[max(0, y0 - GUT):y0, x0:x1] = arr[y0:y0 + 1, x0:x1]
            arr[y1:min(H, y1 + GUT), x0:x1] = arr[y1 - 1:y1, x0:x1]
            arr[y0:y1, max(0, x0 - GUT):x0] = arr[y0:y1, x0:x0 + 1]
            arr[y0:y1, x1:min(W, x1 + GUT)] = arr[y0:y1, x1 - 1:x1]
    albedo = Image.fromarray(_alb)

    # 5. 金属遮罩合并进 ORM: 烫金 -> Roughness 38 / Metallic 240
    is_gold = np.array(metal_mask) > 128
    orm[is_gold, 1] = 38
    orm[is_gold, 2] = 240

    # 6. 背面 (+Y 面自外侧看呈水平镜像): 刀模内容预镜像, 渲染时还原为正向
    bx0, by0, bx1, by1 = BACK
    albedo.paste(albedo.crop(BACK).transpose(Image.FLIP_LEFT_RIGHT), BACK)
    orm[by0:by1, bx0:bx1, :] = orm[by0:by1, bx0:bx1, :][:, ::-1, :]

    albedo.save(os.path.join(OUTPUT_DIR, f"{sku_key}_albedo.png"))
    Image.fromarray(orm).save(os.path.join(OUTPUT_DIR, f"{sku_key}_orm.png"))
    print(f"[OK] {sku_key}: albedo + ORM ({'含烫金金属区' if is_gold.any() else '无金属区'})")


if __name__ == "__main__":
    generate_crease_normal_map()
    # 防回归: 贴图重生后自动链式参照印刷层提升 (杜绝 base-only 覆盖 lift 事故)
    # 公开仓模式 (GPT R3): 参照图未入库时响亮跳过, 不再静默吞错
    import subprocess as _sp
    _lift = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "pipelines/bootstrap/15_texture_lift.py")
    if os.path.exists(_lift) and os.path.exists(os.path.join(os.path.dirname(_lift), os.pardir, os.pardir, "references", "dt_kraft800.jpg")):
        _r = _sp.run([sys.executable, _lift], check=False)
        print(f"[LIFT] 参照印刷层提升 exit={_r.returncode}" if _r.returncode == 0 else f"[LIFT][WARN] 参照印刷层提升失败 exit={_r.returncode} (不影响基础贴图)")
    else:
        print("[LIFT][SKIP] 参照印刷层提升: 参照图未入库 (公开仓模式, 跳过)")
    for k, v in SKU_PROFILES.items():
        generate_sku_textures(k, v)
    print(f"\n完成 -> {OUTPUT_DIR}")
