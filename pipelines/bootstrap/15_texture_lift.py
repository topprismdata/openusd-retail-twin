#!/usr/bin/env python3
"""参照印刷层像素提升 (texture lift): 从 references/dt_kraft800.jpg 箱正面
把参照包装印刷元素 (经典标/源自文案/奶牛+月桂花环/纯牛奶书法字/双指标/净含量)
去光照后按单盒量测分区叠入 albedo, 替代程序化重绘。

流程: 00 生成纸基 -> 15 叠真实印刷层 -> 重算 ORM 光油/金属 -> 渲染。
用法: python3 15_texture_lift.py [--sku classic|organic]
  classic: dt_kraft800 -> demo_classic (原版, kraft 基 ORM 重算)
  organic: dt_kraft800 奶牛花环 -> demo_organic 深绿瓶身方标-金盾间空档
"""
import argparse
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEX = os.path.join(BASE, "assets", "textures")
SRC = os.path.join(BASE, "references", "dt_kraft800.jpg")
if not os.path.exists(SRC):
    print("[LIFT][SKIP] 参照图 references/dt_kraft800.jpg 未入库 (公开仓模式) — 本流程仅在有授权参照素材的私有环境运行")
    raise SystemExit(0)
FRONT = (60, 104, 940, 1944)
GLOBAL_KRAFT = np.array([186, 160, 116])   # 箱正面干净 kraft 区中值 (目视核定)

# 源框 (dt_kraft800.jpg 800x800 坐标, 目视+掩膜核定)
SRC_RECTS = {
    "cow":    (460, 333, 700, 485),
}
# 目标分区 (FRONT 内归一化, 量测自 dt_m_main 单盒)
DST = {
    "cow":    (0.06, 0.30, 0.94, 0.58),
}
# organic: 深绿瓶身布局 (方标底~500px, 金盾顶~719px, 空档归一化 0.215-0.33)
DST_ORGANIC = {
    "cow":    (0.14, 0.215, 0.86, 0.33),
}
CHUN_X = (0.14, 0.42, 0.70)     # 纯/牛/奶 横排中心


def alpha_mask(orig, kind):
    """印刷层 alpha = 与原图局部纸基中值色的距离 (不用去光照图, 防纸基变白整块不透明)。"""
    a = np.asarray(orig).astype(int)
    h, w = a.shape[:2]
    ring = np.concatenate([a[:6].reshape(-1, 3), a[-6:].reshape(-1, 3),
                           a[:, :6].reshape(-1, 3), a[:, -6:].reshape(-1, 3)])
    rmed = np.median(ring, axis=0)
    sat = int(rmed.max()) - int(rmed.min())
    base = GLOBAL_KRAFT if sat > 40 else rmed     # 裁块边界即墨色(logo)时用全局纸基
    d = np.abs(a - base).sum(axis=-1)
    thr = 70 if kind == "cow" else 60
    m = d > thr
    mi = Image.fromarray((m * 255).astype(np.uint8))
    if kind == "cow":
        mi = mi.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))  # 开运算去噪点
    er = 1 if kind == "yuanzi" else 3
    m = np.asarray(mi.filter(ImageFilter.MinFilter(er)).filter(ImageFilter.GaussianBlur(0.5))) > 80
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sku", choices=["classic", "organic"], default="classic")
    a = ap.parse_args()
    organic = a.sku == "organic"
    dst_map = DST_ORGANIC if organic else DST
    alb_p = os.path.join(TEX, f"demo_{a.sku}_albedo.png")
    orm_p = os.path.join(TEX, f"demo_{a.sku}_orm.png")
    src = Image.open(SRC).convert("RGB")
    alb = Image.open(alb_p).convert("RGB")
    fx0, fy0, fx1, fy1 = FRONT
    fw, fh = fx1 - fx0, fy1 - fy0
    pasted_boxes = []

    for key, (sx0, sy0, sx1, sy1) in SRC_RECTS.items():
        crop = src.crop((sx0, sy0, sx1, sy1))
        m = (np.ones((crop.height, crop.width), bool) if key == "logo"
             else alpha_mask(crop, key))
        rgba = crop.convert("RGBA")
        arr = np.asarray(rgba).astype(np.float32)
        gray = arr[..., :3].mean(axis=-1, keepdims=True)
        rgb = (gray + (arr[..., :3] - gray) * 1.25) / 255.0
        rgb = np.clip(rgb, 0.0, 1.0)   # 2026-11-09: 对比增强后可为负, power(neg)=NaN 导致整块作废
        arr[..., :3] = np.clip(np.power(rgb, 1.28) * 255.0, 0, 255)   # 伽马压暗 -> 参照墨色深度
        rgba = Image.fromarray(arr.astype(np.uint8), "RGBA")
        rgba.putalpha(Image.fromarray((m * 255).astype(np.uint8)))
        if True:
            dx0, dy0, dx1, dy1 = dst_map[key]
            dw, dh = int(fw * (dx1 - dx0)), int(fh * (dy1 - dy0))
            rgba = rgba.resize((dw, dh), Image.LANCZOS)
            px, py = fx0 + int(fw * dx0), fy0 + int(fh * dy0)
        alb.paste(rgba, (px, py), rgba)
        pasted_boxes.append((px, py, px + dw, py + dh))

    if organic:
        alb.save(alb_p)  # 2026-11-09 修复: organic 分支提前 return 漏存 albedo (paste 永远丢)
        # 深绿基: 无 kraft 墨距逻辑; 仅对贴片区降低 roughness (印刷层较纸面光)
        orm = np.asarray(Image.open(orm_p).convert("RGB")).astype(np.int16)
        for (px0, py0, px1_, py1_) in pasted_boxes:
            orm[py0:py1_, px0:px1_, 1] = np.maximum(30, orm[py0:py1_, px0:px1_, 1] - 28)
        Image.fromarray(np.clip(orm, 0, 255).astype(np.uint8)).save(orm_p)
        print(f"[LIFT] {len(SRC_RECTS)} elements lifted -> {alb_p} (organic mode)")
        return

    a = np.asarray(alb).astype(np.float32)
    kraft = np.array([166, 142, 98], dtype=np.float32)
    d = np.abs(a - kraft).sum(axis=-1)
    ink = np.clip(d / 120.0, 0, 1)[..., None]
    a[..., :3] = np.clip(a[..., :3] * (1 - 0.14 * ink), 0, 255)
    alb = Image.fromarray(a.astype(np.uint8))
    alb.save(alb_p)
    # ORM 重算: 印刷区光油 + 金标金属
    orm_p = os.path.join(TEX, "demo_classic_orm.png")
    orm = np.asarray(Image.open(orm_p).convert("RGB")).astype(np.int16)
    a = np.asarray(alb).astype(int)
    kraft = np.array([176, 152, 108])
    gfx = np.abs(a - kraft).sum(axis=-1) > 90
    gfx_zone = np.zeros_like(gfx)
    gfx_zone[fy0:fy1, fx0:fx1] = gfx[fy0:fy1, fx0:fx1]
    orm[..., 1] = np.where(gfx_zone, np.maximum(28, orm[..., 1] - 30), orm[..., 1])
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    gold = (r > 150) & (g > 110) & (b < 130) & (r > b + 55)
    gold_zone = gold & gfx_zone
    orm[..., 1] = np.where(gold_zone, 38, orm[..., 1])
    orm[..., 2] = np.where(gold_zone, 240, orm[..., 2])
    Image.fromarray(np.clip(orm, 0, 255).astype(np.uint8)).save(orm_p)
    print(f"[LIFT] {len(SRC_RECTS)} elements lifted -> {alb_p}")


if __name__ == "__main__":
    main()
