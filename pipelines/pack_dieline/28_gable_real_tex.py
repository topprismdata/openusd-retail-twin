#!/usr/bin/env python3
"""28 - 山形包真像素正面贴图合成: 13-SKU 真实 albedo atlas FRONT 区裁片 → gable 包画布。

GPT 盲评 round1 方向: 包装真像素是第一杠杆 (PIL 标签文字失真 = 渲染穿帮最强信号)。
画布布局 (960x2720, 白底, numpy 向量化):
  - 顶带 y<790 白 + 纵向微渐变 + 轻噪 (纸面折叠暗示)
  - 肩线 60px 软过渡 (去像素级硬切)
  - 印刷区 y 720..2592: FRONT 裁片(内缩14px/侧去相邻面板彩条) resize (940,1930), x=10
  - 侧面采样点 (0.004,0.5)*canvas = (4,1360) 落在白边 → 侧面纯白不 smear
用法: python3 28_gable_real_tex.py
输出: assets/textures/fresh/gable_real_{organic,classic,lowfat}.png
"""
import os
import numpy as np
from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEX = os.path.join(BASE, "assets", "textures")
OUT = os.path.join(TEX, "fresh")
os.makedirs(OUT, exist_ok=True)

CANVAS_W, CANVAS_H = 960, 2592   # R11: 参照 40×30×108 → 顶面纵横比 1:2.7
BODY_TOP = 720   # 肩线 v 边界 h_body/total = 78/108
PRINT_W, PRINT_H = 940, CANVAS_H - BODY_TOP   # 1872
PRINT_X = 10
FADE = 60

SKUS = {
    "organic": "demo_organic_albedo.png",
    "classic": "demo_classic_albedo.png",
    "lowfat":  "demo_lowfat_albedo.png",
    "skim":    "demo_skim_albedo.png",     # R10: 10+SKU 战役 (脱脂, PIL 时代 atlas)
    "jersey":  "demo_jersey_albedo.png",   # R10: 娟姗
}


def main():
    rng = np.random.default_rng(7)
    for name, atlas in SKUS.items():
        a = Image.open(os.path.join(TEX, atlas)).convert("RGB")
        assert a.size == (2048, 2048), f"{atlas} 尺寸异常 {a.size}"
        # 内缩 14px/侧: 去 atlas 相邻面板彩条残留 (vision 实测穿帮)
        crop = a.crop((74, 104, 926, 1944)).resize((PRINT_W, PRINT_H), Image.LANCZOS)
        canvas = np.full((CANVAS_H, CANVAS_W, 3), 250, dtype=np.float32)
        canvas[..., 2] = 248
        # 白带纸面微渐变 + 轻噪
        band = canvas[:BODY_TOP]
        ramp = (4.0 * np.arange(BODY_TOP, dtype=np.float32) / BODY_TOP)[:, None, None]
        noise = rng.integers(-1, 2, size=(BODY_TOP, CANVAS_W, 1), dtype=np.int32)
        band[:] = np.clip(band + ramp + noise, 240, 255)
        # 肩线软过渡: 印刷顶部 FADE 行与白线性混合
        crop_np = np.asarray(crop, dtype=np.float32)
        alpha = np.linspace(1.0, 0.0, FADE, dtype=np.float32)[:, None, None]   # 越靠上越白
        crop_np[:FADE] = alpha * 250.0 + (1 - alpha) * crop_np[:FADE]
        crop_np[:FADE, :, 2] = alpha[:, :, 0] * 248.0 + (1 - alpha[:, :, 0]) * crop_np[:FADE, :, 2]
        y1 = BODY_TOP + PRINT_H
        canvas[BODY_TOP:y1, PRINT_X:PRINT_X + PRINT_W] = crop_np
        out_im = Image.fromarray(np.clip(canvas, 0, 255).astype(np.uint8))
        out_p = os.path.join(OUT, f"gable_real_{name}.png")
        out_im.save(out_p)
        px = out_im.getpixel((4, 1360))
        print(name, "->", out_p, "侧采样点RGB =", px)
        assert px[0] > 235 and px[1] > 235 and px[2] > 235, f"{name} 侧采样点非白"


if __name__ == "__main__":
    main()
