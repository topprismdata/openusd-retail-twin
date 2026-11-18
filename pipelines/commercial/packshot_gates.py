#!/usr/bin/env python3
"""Packshot GS1技术闸 (纯Python, 免Blender可迭代)。
bbox 用行列剖面计数法: 单点阈值 mask 对 denoiser 白底噪声不鲁棒
(首跑实测: 散点 <246 铺满全幅 → fw=0.999/贴边/ROI读到背景)。
剖面计数: 列内<246像素数 > 0.5%帧高 才算主体列 — 散点天然被滤。
"""
import json
import sys

import numpy as np
from PIL import Image

FILL_H_BAND = (0.72, 0.92)
CENTER_TOL = 0.03
MARGIN_MIN = 0.06
ASPECT_TOL = 0.05
BG_BORDER = 0.04
PROFILE_FRAC = 0.005


def profile_bbox(img, thresh=246):
    H, W = img.shape
    mask = img < thresh
    col = mask.sum(axis=0)
    row = mask.sum(axis=1)
    cs = np.where(col > H * PROFILE_FRAC)[0]
    rs = np.where(row > W * PROFILE_FRAC)[0]
    if len(cs) < 10 or len(rs) < 10:
        return None
    return (cs.min() / W, cs.max() / W, rs.min() / H, rs.max() / H)


def gates(out_png, mani):
    spec_h = mani["carton_h_m"]
    spec_w = mani["carton_w_m"]
    img = np.asarray(Image.open(out_png).convert("L"), dtype=float)
    H, W = img.shape
    out = []
    b = int(BG_BORDER * min(H, W))
    border = np.concatenate([img[:b, :].ravel(), img[-b:, :].ravel(),
                             img[:, :b].ravel(), img[:, -b:].ravel()])
    p1 = border.mean() >= 252 and float(np.percentile(border, 5)) >= 248
    out.append(("P1 背景纯度 边缘带均值≥252且p05≥248", p1,
                "mean=%.1f p05=%.0f" % (border.mean(), np.percentile(border, 5))))
    bb = profile_bbox(img)
    if bb is None:
        out.append(("P2 主体检出", False, "剖面无主体列/行"))
        return out, False
    u0, u1, v0, v1 = bb
    fill_h = v1 - v0
    fill_w = u1 - u0
    exp_w = fill_h * (spec_w / spec_h)
    ok_fill = FILL_H_BAND[0] <= fill_h <= FILL_H_BAND[1]
    ok_ar = abs(fill_w - exp_w) / exp_w <= ASPECT_TOL
    out.append(("P2 主体高填充∈[%.2f,%.2f]" % FILL_H_BAND, ok_fill,
                "fh=%.3f fw=%.3f" % (fill_h, fill_w)))
    out.append(("P5 纵横比畸变≤%.0f%%(实测vs世界)" % (ASPECT_TOL * 100), ok_ar,
                "fw/exp=%.4f (exp=%.3f)" % (fill_w / exp_w, exp_w)))
    cx, cy = (u0 + u1) / 2, (v0 + v1) / 2
    ok_c = abs(cx - 0.5) <= CENTER_TOL and abs(cy - 0.5) <= CENTER_TOL
    out.append(("P3 居中≤%.0f%%" % (CENTER_TOL * 100), ok_c,
                "dx=%+.3f dy=%+.3f" % (cx - 0.5, cy - 0.5)))
    m = min(u0, 1 - u1, v0, 1 - v1)
    out.append(("P4 静区≥%.0f%%" % (MARGIN_MIN * 100), m >= MARGIN_MIN, "min=%.3f" % m))
    x0 = int((u0 + 0.20 * (u1 - u0)) * W)
    x1 = int((u0 + 0.80 * (u1 - u0)) * W)
    y0 = int((v0 + 0.30 * (v1 - v0)) * H)
    y1 = int((v0 + 0.75 * (v1 - v0)) * H)
    roi = img[y0:y1, x0:x1]
    paper = float(np.percentile(roi, 85))
    ink = float((roi < paper - 45).mean())
    out.append(("P6 品牌墨色存在≥0.02", ink >= 0.02, "ink=%.4f paper=%.0f" % (ink, paper)))
    # P7 白面不过曝(双向纪律): paper打满255=印刷对比被削平(首跑实证 ink=0),
    # 一侧只查"墨存在"会被过曝静默击穿 — 白面亮度必须留出墨色余量
    out.append(("P7 白面不过曝 paper≤252", paper <= 252, "paper=%.0f" % paper))
    ok = all(o[1] for o in out)
    return out, ok


def main():
    png, mani_path = sys.argv[1], sys.argv[2]
    mani = json.load(open(mani_path))
    rows, ok = gates(png, mani)
    npass = sum(1 for r in rows if r[1])
    print("[PACKSHOT-GATE] %s -> %d/%d PASS" % (png, npass, len(rows)))
    for name, okr, val in rows:
        print("   %-38s %s  实测 %s" % (name, "PASS" if okr else "FAIL", val))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
