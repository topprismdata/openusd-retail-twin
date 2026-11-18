# 五阶段产品数字资产展示板 (R82): 客户汇报级 Industrial Digital Asset Showcase
# 对标 Unilever×NVIDIA Omniverse (GPT 方案 docs/reviews/gpt_pinmu_stageboard_beautify.md)。
# 三层布局: 顶部资产身份栏 + 中部五阶段演进(4开发+1参照) + 底部资产元信息栏。16:9 3840x2160。
# 第⑤格=REAL-WORLD REFERENCE(验证参照, 虚线连接, 非生产工序)。从已渲 stage_1..4 + 实拍裁切拼版, 无需 Blender。
import os, json, argparse
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ap = argparse.ArgumentParser()
ap.add_argument("--spec", default="specs/pack_458.json")
ap.add_argument("--out", default="output/pack_qa/pinmu_458/stage_board")
a = ap.parse_args()
spec = json.load(open(os.path.join(BASE, a.spec)))
OUT_DIR = os.path.join(BASE, a.out)

# ---- 画布 / 配色 (GPT 规范) ----
W, H = 3840, 2160
M = 154                                   # 安全边距 4%
NAVY = (23, 43, 69)                       # #172B45 标题/身份
CANVAS = (243, 245, 247)                  # #F3F5F7 主画布
WHITE = (255, 255, 255)                   # 图片卡片
GREEN = (118, 185, 0)                     # #76B900 状态强调(仅完成态)
MUTED = (90, 107, 123)                    # 次要文字
BORDER = (216, 222, 228)                  # 细线/卡片边
LIGHT = (248, 250, 252)                   # chip 底
AMBER = (189, 150, 80)                    # #BD9650 pending/规划态
board = Image.new("RGB", (W, H), CANVAS)
d = ImageDraw.Draw(board)

CN = "/System/Library/Fonts/Hiragino Sans GB.ttc"
EN = "/System/Library/Fonts/HelveticaNeue.ttc"
def cn(s, bold=False): return ImageFont.truetype(CN, s, index=2 if bold else 0)
def en(s, bold=False): return ImageFont.truetype(EN, s, index=1 if bold else 0)
def txt(x, y, s, font, fill, anchor="la"): d.text((x, y), s, font=font, fill=fill, anchor=anchor)

def dashed_v(x, y0, y1, fill, width=2, dash=14, gap=10):
    y = y0
    while y < y1:
        d.line([x, y, x, min(y + dash, y1)], fill=fill, width=width); y += dash + gap
def dashed_h(x0, x1, y, fill, width=3, dash=14, gap=10):
    x = x0
    while x < x1:
        d.line([x, y, min(x + dash, x1), y], fill=fill, width=width); x += dash + gap

# ---- 产品竖直范围测量 (逐列顶部背景参考定屋顶峰 + 蓝掩膜定底) ----
def prod_rows(img):
    h, w = img.shape[:2]
    bg = img[0:5, :, :].astype(int).mean(0)
    diff = np.abs(img.astype(int) - bg[None, :, :]).sum(2)
    tpc = np.argmax(diff > 40, axis=0); tpc[~(diff > 40).any(0)] = h
    top = int(tpc[int(w * 0.3):int(w * 0.7)].min())
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    blue = (hsv[..., 0] >= 95) & (hsv[..., 0] <= 135) & (hsv[..., 1] > 60)
    return top, int(np.where(blue.any(1))[0].max())

_s4 = cv2.imread(os.path.join(OUT_DIR, "stage_4_final.png"))
_H4, _W4 = _s4.shape[:2]
_rt, _rb = prod_rows(_s4)
_C = 0.82
_crop_h = int(_H4 * _C)
_pf = cv2.imread(os.path.join(BASE, spec["folded_photo_ref"]))
_prt, _prb = prod_rows(_pf)
_box = spec.get("folded_photo_crop", [60, 16, 958, 1598])
PHOTO_FRAC = (min(_prb, _box[3]) - max(_prt, _box[1])) / (_box[3] - _box[1])

# ================= 顶部资产身份栏 =================
txt(M, 66, "PRODUCT DIGITAL TWIN  ·  PACKAGING ASSET", en(26), MUTED)
txt(M, 104, "品慕 458mL 屋顶包", cn(78, True), NAVY)
txt(M, 208, "PINMU  ·  458 mL  ·  GABLE TOP CARTON  ·  DAIRY BEVERAGE PACKAGING", en(30), MUTED)
# 右侧三枚身份 chip
ASSET_ID = "PKG-PM-458"
ASSET_VER = "R82"
chips = [("ASSET ID", ASSET_ID), ("ASSET VERSION", ASSET_VER), ("WORKFLOW", "4 Dev + 1 Ref")]
cw, cg = 300, 40
cx = W - M - (cw * 3 + cg * 2)
for lab, val in chips:
    d.rounded_rectangle([cx, 96, cx + cw, 214], radius=12, fill=LIGHT, outline=BORDER, width=2)
    txt(cx + 24, 118, lab, en(21), MUTED)
    txt(cx + 24, 152, val, en(38, True), NAVY)
    cx += cw + cg
d.line([M, 280, W - M, 280], fill=BORDER, width=2)

# ================= 中部五阶段演进 =================
txt(M, 322, "01 / DIGITAL ASSET DEVELOPMENT", en(36, True), NAVY)
txt(M, 372, "FROM ENGINEERING GEOMETRY TO PRODUCT-ACCURATE VISUALIZATION", en(24), MUTED)

stages = [
    ("01", "GEOMETRY", "Reconstructed Geometry", "工程几何", "Engineering Geometry Definition · 折线 / 隐藏棱", "VISUAL COMPLETE", "stage_1_cad.png"),
    ("02", "FORM", "Solid Form", "实体白模", "Solid Mesh · 完整实体结构 / 折面", "VISUAL COMPLETE", "stage_2_mesh.png"),
    ("03", "MATERIAL", "Physical Material", "物理材质", "Material Assignment · Paperboard 粗糙度 / 表面 / 光学", "VISUAL COMPLETE", "stage_3_material.png"),
    ("04", "PRINT", "Printed Product", "印刷成品", "Artwork Applied · 印刷贴图 / 成品", "VISUAL COMPLETE", "stage_4_final.png"),
    ("05", "REF", "Real Reference", "实拍参照", "Reference Photo · 真实商品对照", "REFERENCE", None),
]
PW = 672
gap = 28
div_zone = 88                              # 第⑤栏前独立分隔区
xs = [M]
for i in range(1, 5):
    xs.append(xs[-1] + PW + (gap if i < 4 else div_zone))
CARD_Y, CARD_H = 560, 1000
PAD = 26
IMG_W = PW - 2 * PAD                       # 620 标准图宽
# 标准渲染图高 (82%中心裁后按IMG_W宽resize) + 产品高度 (供实拍对齐)
_crop_w = int(_W4 * _C)
H_std = int(IMG_W * _crop_h / _crop_w)
render_prod_h = (_rb - _rt) / _crop_h * H_std

def fit_render(fn):
    im = Image.open(os.path.join(OUT_DIR, fn)).convert("RGB")
    w0, h0 = im.size
    im = im.crop((int(w0 * (1 - _C) / 2), int(h0 * (1 - _C) / 2), int(w0 * (1 + _C) / 2), int(h0 * (1 + _C) / 2)))
    return im.resize((IMG_W, int(IMG_W * im.size[1] / im.size[0])), Image.LANCZOS)

for i, (num, name, enn, cnn, desc, status, fn) in enumerate(stages):
    px = xs[i]
    # 阶段头: 编号 + 名称 + 状态徽章
    txt(px, 446, num, en(58, True), NAVY)
    txt(px + 96, 452, name, en(34, True), NAVY)
    txt(px + 96, 494, f"{enn} · {cnn}", cn(23), MUTED)   # R82b: 中文字体(Hiragino含Latin)消中英混排方框缺字
    is_ref = fn is None
    badge_col = NAVY if is_ref else GREEN
    bw = 168 if is_ref else 224
    bx = px + PW - bw
    d.rounded_rectangle([bx, 452, bx + bw, 492], radius=20, outline=badge_col, width=2)
    txt(bx + bw // 2, 472, status, en(19, True), badge_col, anchor="mm")
    # 图片卡片 (统一容器: 白底/细边/同尺寸; 第⑤格 NAVY 边强调参照)
    d.rounded_rectangle([px, CARD_Y, px + PW, CARD_Y + CARD_H], radius=14,
                        fill=WHITE, outline=(NAVY if is_ref else BORDER), width=(3 if is_ref else 2))
    if is_ref:
        photo = Image.open(os.path.join(BASE, spec["folded_photo_ref"])).convert("RGB").crop(tuple(_box))
        ph_h = int(render_prod_h / PHOTO_FRAC)
        ph_w = int(ph_h * photo.size[0] / photo.size[1])
        photo = photo.resize((ph_w, ph_h), Image.LANCZOS)
        board.paste(photo, (px + (PW - ph_w) // 2, CARD_Y + (CARD_H - ph_h) // 2))
        txt(px + PW // 2, CARD_Y + CARD_H - 30, "REAL-WORLD REFERENCE", en(20, True), NAVY, anchor="mm")
    else:
        im = fit_render(fn)
        board.paste(im, (px + (PW - im.size[0]) // 2, CARD_Y + (CARD_H - im.size[1]) // 2))
    # 阶段产物说明
    txt(px + PW // 2, CARD_Y + CARD_H + 34, desc, cn(24), MUTED, anchor="ma")
    if i == 3:   # R82b: 开发态≠验收态, 第④格单独标色彩验证 pending
        txt(px + PW // 2, CARD_Y + CARD_H + 66, "Print-color validation: PENDING", en(21, True), AMBER, anchor="ma")
    # 流程连接: 01-04 实线箭头; 03→04 后到 05 虚线 (参照验证)
    cy = CARD_Y + CARD_H // 2
    if i < 3:
        x0 = px + PW + 4; x1 = xs[i + 1] - 4
        d.line([x0, cy, x1 - 8, cy], fill=MUTED, width=3)
        d.polygon([(x1, cy), (x1 - 10, cy - 6), (x1 - 10, cy + 6)], fill=MUTED)
    elif i == 3:
        dashed_h(px + PW + 4, xs[4] - 4, cy, MUTED, width=3)
        d.polygon([(xs[4] - 4, cy), (xs[4] - 14, cy - 6), (xs[4] - 14, cy + 6)], fill=MUTED)
# 第⑤栏前独立竖直虚线分隔
div_x = xs[3] + PW + div_zone // 2
dashed_v(div_x, 446, CARD_Y + CARD_H + 60, BORDER, width=2)

# ================= 底部资产元信息栏 =================
d.line([M, 1800, W - M, 1800], fill=BORDER, width=2)
txt(M, 1822, "02 / ASSET METADATA", en(32, True), NAVY)
txt(M, 1868, "MASTER SOURCE & ASSET GOVERNANCE", en(22), MUTED)   # R82b: 不提前宣称统一数字事实来源已实现
dims = spec.get("dims_mm", {})
dim_str = f"{dims.get('w',68.3)} × {dims.get('d',68.3)} × 129 mm"
fields = [
    ("MASTER SOURCE", "Blender 5.2 Project + Spec", NAVY),
    ("OPENUSD", "In Progress", AMBER),
    ("RENDER ENGINE", "Cycles · CPU", NAVY),
    ("GEOMETRY", "Reconstructed · mm", NAVY),
    ("MATERIAL", "Paperboard · PBR", NAVY),
    ("PRINT SOURCE", "Original Artwork", NAVY),
    ("DIMENSIONS", dim_str, NAVY),
    ("VALIDATION", "Print-color Pending", AMBER),
]
fw = (W - 2 * M) // 8
for i, (lab, val, vc) in enumerate(fields):
    fx = M + i * fw
    txt(fx, 1916, lab, en(20), MUTED)
    txt(fx, 1948, val, en(24, True), vc)
txt(M, 2006, "Asset Layers:  Geometry · Materials · Artwork — managed independently, composed into one product asset.", en(24), MUTED)
txt(M, 2050, "Spec-driven Blender master; OpenUSD composition in progress. Visual development stages shown — print-color validation pending.", en(21), MUTED)
txt(M, 2098, f"REVISION {ASSET_VER}  ·  CHANGE: Industrial showcase layout + asset metadata", en(22), MUTED)
gov = f"Spec Source: specs/{os.path.basename(a.spec)}   ·   3D Master: Blender 5.2   ·   Updated: 2026-11-17   ·   Owner: Retail Digital Twin"
txt(W - M, 2098, gov, en(22), MUTED, anchor="ra")

board.save(os.path.join(OUT_DIR, "stage_board.png"))
print(f"[STAGE] board={os.path.join(OUT_DIR, 'stage_board.png')} {W}x{H} industrial-3layer photo_frac={PHOTO_FRAC:.3f} render_prod_h={render_prod_h:.0f}")