#!/usr/bin/env python3
"""参照照 → atlas FRONT/BACK 区真像素重建 (E1/E2 战役管线固化, 2026-11-15)

用法:
  python3 21_front_rebuild.py --sku demo_organic --src references/jd_lowfat/organic_16.jpg \
      --crop 1062,357,1292,888 --unforeshorten 1.0 --region front

管线 (jd-relay-product-photo-sourcing 技能):
  1) 裁纯正面 (去侧脸 sliver + 顶部屋顶折痕带, 保留完整 logo)
  2) --unforeshorten x向拉伸回真比例 (3/4 视角照片 ~1.5; 纯正面 1.0)
  3) 保纵横比贴入 (宽贴合 920, 垂直白边补齐, 边缘色从真盒上下缘采样)
     — 直接拉伸会变形致文字重影/瓶盖扭曲 (2.37x 事故教训)
  4) 色阶拉伸 p5→12 / p95→242 线性 + gamma 1.10 压墨 (真照片墨浅, 高键光必褪色)
  5) BACK 区: 贴入前 FLIP_LEFT_RIGHT (BACK 区 UV 为翻转映射, 00 行 ~700)
  6) 渲染侧配 LABEL_GAMMA=1.30 (01 已有 env 钩子)
  7) 自动备份原 atlas 为 <sku>_albedo_vPIL_backup.png (仅首次)
"""
import argparse
import os
import shutil

import numpy as np
from PIL import Image

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEX_DIR = os.path.join(BASE_DIR, "assets", "textures")

# atlas 区契约 (00 docstring): FRONT x[60,980] y[100,1950]; BACK x[1060,1980]
REGIONS = {
    "front": (60, 100, 980, 1950),
    "back": (1060, 100, 1980, 1950),
}
REGION_W = 920
REGION_H = 1850
PAD_TOP = 200  # 顶部白边 (内容垂直居中偏上)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sku", required=True)
    p.add_argument("--src", required=True, help="参照照路径")
    p.add_argument("--crop", required=True, help="x0,y0,x1,y1 纯正面裁剪框")
    p.add_argument("--unforeshorten", type=float, default=1.0, help="x向透视去前缩系数")
    p.add_argument("--region", choices=["front", "back"], default="front")
    p.add_argument("--pad-top", type=int, default=PAD_TOP)
    p.add_argument("--gamma", type=float, default=1.10)
    args = p.parse_args()

    atlas_path = os.path.join(TEX_DIR, f"{args.sku}_albedo.png")
    backup = os.path.join(TEX_DIR, f"{args.sku}_albedo_vPIL_backup.png")
    if not os.path.exists(backup) and os.path.exists(atlas_path):
        shutil.copy(atlas_path, backup)
        print(f"[backup] {backup}")

    src = Image.open(args.src).convert("RGB")
    x0, y0, x1, y1 = (int(v) for v in args.crop.split(","))
    box = src.crop((x0, y0, x1, y1))
    w0, h0 = box.size

    # 透视去前缩
    if args.unforeshorten != 1.0:
        box = box.resize((int(w0 * args.unforeshorten), h0), Image.LANCZOS)
    bw, bh = box.size

    # 保纵横比贴入: 宽贴合优先; 内容更瘦长超高时改定高贴+左右白边
    bh2 = int(bh * REGION_W / bw)
    if bh2 <= REGION_H:
        arr_fit = np.asarray(box.resize((REGION_W, bh2), Image.LANCZOS))
        a_top = tuple(int(v) for v in arr_fit[2:6].reshape(-1, 3).mean(0))
        a_bot = tuple(int(v) for v in arr_fit[-4:].reshape(-1, 3).mean(0))
        pad_top = max(0, min(args.pad_top, REGION_H - bh2))
        pad_bot = REGION_H - bh2 - pad_top
        canvas = Image.new("RGB", (REGION_W, REGION_H))
        canvas.paste(Image.new("RGB", (REGION_W, pad_top), a_top), (0, 0))
        canvas.paste(Image.fromarray(arr_fit), (0, pad_top))
        canvas.paste(Image.new("RGB", (REGION_W, pad_bot), a_bot), (0, pad_top + bh2))
    else:
        fh = REGION_H
        fw = int(bw * REGION_H / bh)
        arr_fit = np.asarray(box.resize((fw, fh), Image.LANCZOS))
        x_off = (REGION_W - fw) // 2
        canvas = Image.new("RGB", (REGION_W, REGION_H),
                           tuple(int(v) for v in arr_fit.reshape(-1, 3).mean(0)))
        canvas.paste(Image.fromarray(arr_fit), (x_off, 0))
        bh2 = fh
        pad_top = 0

    if args.region == "back":
        canvas = canvas.transpose(Image.FLIP_LEFT_RIGHT)  # BACK 区 UV 翻转映射预镜像

    atlas = Image.open(atlas_path).convert("RGB")
    a = np.asarray(atlas).astype(float)
    rx0, ry0, rx1, ry1 = REGIONS[args.region]
    a[ry0:ry1, rx0:rx1] = np.asarray(canvas).astype(float)

    # 色阶拉伸 + 压墨
    reg = a[ry0:ry1, rx0:rx1]
    lum = reg @ [0.299, 0.587, 0.114]
    p5, p95 = np.percentile(lum, [5, 95])
    st = np.clip((reg - p5) * (242.0 - 12.0) / max(p95 - p5, 1) + 12.0, 0, 255)
    st = np.power(st / 255.0, args.gamma) * 255.0
    a[ry0:ry1, rx0:rx1] = st
    Image.fromarray(a.astype(np.uint8)).save(atlas_path)
    l2 = a[ry0:ry1, rx0:rx1] @ [0.299, 0.587, 0.114]
    print(f"[done] {args.sku} {args.region}: p5/p50/p95 = "
          f"{np.percentile(l2, 5):.0f}/{np.percentile(l2, 50):.0f}/{np.percentile(l2, 95):.0f} "
          f"(content {REGION_W}x{bh2}, pad_top {pad_top})")


if __name__ == "__main__":
    main()
