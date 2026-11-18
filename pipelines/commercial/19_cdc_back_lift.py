#!/usr/bin/env python3
"""v99b CDC 参照背面印刷提升 (修复重影): 先擦旧程序层 → 纸基 → lift 真照片 + 真实 EAN-13.
坑: 旧程序层透过掩膜显影=重影 (v99a); 掩膜用原图距离阈值收紧; BACK UV 镜像→整区水平翻转."""
import numpy as np
from PIL import Image, ImageFilter
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
REF = os.path.join(BASE, "assets/reference/milk_back")
ATLAS = os.path.join(BASE, "assets/textures/demo_organic_albedo_v67.png")
OUT = os.path.join(BASE, "assets/textures/demo_organic_albedo_v68.png")
PAPER = np.array([243.0, 246.0, 240.0])

def lift_block(src_path, crop_pct, out_w, out_h, ink_thresh=70):
    im = Image.open(src_path).convert("RGB")
    w, h = im.size
    x0, y0, x1, y1 = crop_pct
    block = im.crop((int(x0*w), int(y0*h), int(x1*w), int(y1*h)))
    block = block.resize((out_w, out_h), Image.LANCZOS)
    a = np.array(block).astype(np.float64)
    ring = np.concatenate([a[:12].reshape(-1,3), a[-12:].reshape(-1,3),
                           a[:, :12].reshape(-1,3), a[:, -12:].reshape(-1,3)])
    paper = np.median(ring, axis=0)
    dist = np.sqrt(((a - paper)**2).sum(axis=2))
    mask = (dist > ink_thresh).astype(np.uint8) * 255
    m = Image.fromarray(mask).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    mask = np.array(m).astype(np.float64) / 255.0
    blur = np.array(block.filter(ImageFilter.GaussianBlur(35))).astype(np.float64) + 1e-3
    norm = a / blur * np.median(blur.reshape(-1,3), axis=0)
    norm = np.clip(norm, 0, 255)
    gray = norm.mean(axis=2, keepdims=True)
    norm = np.clip(gray + (norm - gray) * 1.25, 0, 255) / 255.0
    norm = (norm ** 1.28) * 255.0
    return norm.astype(np.uint8), mask

def main():
    atlas = np.array(Image.open(ATLAS).convert("RGB"))
    bx0, by0, bx1, by1 = 1112, 104, 1992, 1944
    bw, bh = bx1-bx0, by1-by0
    # 1) 擦旧程序层: BACK 全区纸基 (保留极轻噪声防死平)
    rng = np.random.default_rng(68)
    back = np.tile(PAPER, (bh, bw, 1)) + rng.normal(0, 1.2, (bh, bw, 3))
    back = np.clip(back, 0, 255).astype(np.uint8)

    # 2) 图3 信息块 (配料/营养表/储存/有机码)
    rgb3, a3 = lift_block(os.path.join(REF, "202109191618333382.jpg"),
                          (0.27, 0.28, 0.66, 0.94), 700, 1210)
    # 3) 图4 厂家信息块 (不含条码, 条码用真 EAN-13)
    rgb4, a4 = lift_block(os.path.join(REF, "2021091916184183410.jpg"),
                          (0.36, 0.38, 0.67, 0.72), 700, 600)

    def paste(rgb, alpha, x, y):
        h, w = alpha.shape
        region = back[y:y+h, x:x+w].astype(np.float64)
        al = alpha[..., None]
        back[y:y+h, x:x+w] = np.clip(region*(1-al) + rgb.astype(np.float64)*al, 0, 255).astype(np.uint8)

    paste(rgb3, a3, (bw-700)//2, 100)
    paste(rgb4, a4, (bw-700)//2, 1230)
    # 4) 参照 EAN-13 条码 (占位系列)
    bar = Image.open(os.path.join(REF, "ean13_real.png")).convert("RGB")
    bar = bar.resize((620, 300), Image.LANCZOS)
    ba = np.array(bar)
    back[1530:1830, (bw-620)//2:(bw+620)//2] = ba
    # 5) BACK UV 天然镜像 (u=vx/w+0.5, 从+Y外看局部+X在观察者左) → 真照片须预镜像写入, 渲染才正常
    back = back[:, ::-1]
    atlas[by0:by1, bx0:bx1] = back
    Image.fromarray(atlas).save(OUT)
    Image.fromarray(back).resize((440, 920)).save("/tmp/atlas_back_v68b.png")
    print("saved", OUT)

if __name__ == "__main__":
    main()