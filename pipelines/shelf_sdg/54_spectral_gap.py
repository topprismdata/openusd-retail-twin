#!/usr/bin/env python
"""**频谱差距: 合成图 vs 真实图** —— 定量测量 + PASTA 强度标定 (2026-11-25)。

为什么做这个
------------
52 号的 `pasta` 臂要往合成图的高频振幅谱里补能量, 但补多少必须**有依据**:
PASTA (Chattopadhyay et al., ICCV 2023) 的出发点是"合成图的高频振幅变化比真实图小
(纹理变化不足)", 但"小多少"需要在本项目的数据上量出来。

本脚本:
1. 对**真实 SKU-110K 训练图**与**合成池图**分别算**径向平均幅值谱** (log10),
   逐频带给出真实/合成的 dB 值与差距;
2. 用**二分法**标定 PASTA 的 σ: 使扰动后合成图的高频带 (r>0.5) 平均谱水平
   **追上真实图**在同一频带的水平 (单变量: 只动振幅, 相位不动 -> 框仍有效);
3. 产物: output/benchmark/spectral_gap.json / .md
        output/benchmark/syn2real_pasta_calib.json (52 号据此生成干预池)

用法:
    python pipelines/shelf_sdg/54_spectral_gap.py --n-real 120 --n-synth 120
"""
import argparse
import glob
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
REAL_YAML = os.environ.get("SKU110K_YAML", "SKU-110K.yaml")
SYNTH_POOL = os.path.join(BENCH, "synth_single", "images", "train")
NB = 48          # 频带数
R_HI = 0.5       # 高频带起点 (归一化半径)


def log(m):
    print(f"[SPEC {__import__('time').strftime('%m-%d %H:%M:%S')}] {m}", flush=True)


def letterbox_gray(im, size=640, pad=114):
    """按 ultralytics 的 letterbox 规则把图缩到 size×size 再转灰度。

    **为什么必须做这一步**: 真实 SKU-110K 图是 3024×3024, 合成图是 1440×1080 ——
    直接比原始像素的谱, 差的是**分辨率**而不是"高频纹理多少"。检测器看到的是
    letterbox 到 640×640 之后的图, 所以谱也必须在**同一个输入空间**里比,
    否则 (a) 差距测错, (b) PASTA 的 σ 会按错误的量级标定。
    """
    from PIL import Image
    import numpy as np
    w, h = im.size
    r = size / max(w, h)
    nw, nh = max(1, round(w * r)), max(1, round(h * r))
    im2 = im.resize((nw, nh), Image.BILINEAR)
    canvas = Image.new("RGB", (size, size), (pad, pad, pad))
    canvas.paste(im2, ((size - nw) // 2, (size - nh) // 2))
    return np.asarray(canvas.convert("L"), dtype=np.float64)



# ---------------------------------------------------------------- 谱计算

def radial_profile(gray):
    """返回 (频带中心 r, 各频带平均 log10 幅值)。"""
    import numpy as np
    h, w = gray.shape
    F = np.fft.fft2(gray)
    amp = np.abs(F)
    fy = np.fft.fftfreq(h)[:, None]
    fx = np.fft.fftfreq(w)[None, :]
    r = np.sqrt(fy ** 2 + fx ** 2) / 0.70710678   # 归一化: 最大 1 (角点 Nyquist)
    prof = np.zeros(NB)
    cnt = np.zeros(NB)
    edges = np.linspace(0, 1.0, NB + 1)
    idx = np.clip(np.digitize(r.ravel(), edges) - 1, 0, NB - 1)
    a = np.log10(amp.ravel() + 1e-8)
    for b in range(NB):
        m = idx == b
        if m.any():
            prof[b] = a[m].sum()
            cnt[b] = m.sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        prof = np.where(cnt > 0, prof / np.maximum(cnt, 1), np.nan)
    centers = (edges[:-1] + edges[1:]) / 2.0
    return centers, prof


def profile_of_files(files, n, limit=None, blur=0.0):
    import numpy as np
    from PIL import Image, ImageFilter
    acc, cnt = np.zeros(NB), np.zeros(NB)
    used = 0
    for f in files:
        if used >= n:
            break
        try:
            im = Image.open(f).convert("RGB")
        except Exception:
            continue
        a = letterbox_gray(im)
        if blur > 0:
            # 在**输入空间**上模糊: 去掉"细小内容结构"(商品边缘/文字/纹理),
            # 留下"成像质感"(传感器噪声级的高频)。这样可以把高频差拆成
            # "内容密度贡献" 与 "成像质感贡献" 两部分。
            a = np.asarray(Image.fromarray(a.astype("uint8"))
                           .filter(ImageFilter.GaussianBlur(blur)),
                           dtype=np.float64)
        if a.std() < 1e-3:
            continue
        centers, prof = radial_profile(a)
        ok = ~np.isnan(prof)
        acc[ok] += prof[ok]
        cnt[ok] += 1
        used += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    return centers, out, used


def real_train_files():
    """从 SKU-110K 的 yaml 里取 train 列表 (该 venv **没有 pyyaml**, 手工解析)。"""
    p = REAL_YAML if os.path.isabs(REAL_YAML) else os.path.join(BASE, REAL_YAML)
    d = os.path.dirname(p)
    tr = None
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith("train:"):
                v = s.split(":", 1)[1].strip()
                if v.startswith("["):
                    tr = [x.strip().strip("'\"") for x in v.strip("[]").split(",")
                          if x.strip()]
                elif v:
                    tr = [v]
                break
    out = []
    for t in (tr or []):
        t = t if os.path.isabs(t) else os.path.join(d, t)
        if os.path.isfile(t) and t.lower().endswith(".txt"):
            with open(t, "r", encoding="utf-8") as fh:
                for line in fh:
                    q = line.strip()
                    if not q:
                        continue
                    out.append(q if os.path.isabs(q) else os.path.join(d, q))
        elif os.path.isdir(t):
            out += [os.path.join(t, x) for x in sorted(os.listdir(t))
                    if x.lower().endswith((".jpg", ".jpeg", ".png"))]
    return out


# ---------------------------------------------------------------- 标定

def synth_profiles_with_sigma(synth_files, sigma, n, hp_start=0.15):
    """对合成图加 PASTA 扰动后重算谱。"""
    import numpy as np
    from PIL import Image
    spec = os.path.join(BASE, "pipelines", "shelf_sdg", "52_photorealism_probe.py")
    import importlib.util
    s = importlib.util.spec_from_file_location("p52", spec)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    acc, cnt = np.zeros(NB), np.zeros(NB)
    used = 0
    for f in synth_files:
        if used >= n:
            break
        im = Image.open(f).convert("RGB")
        arr = np.asarray(im, dtype=np.float32)
        out = m._pasta(arr, np.random.default_rng(used + 1), sigma=sigma,
                       hp_start=hp_start)
        # 扰动在**原始分辨率**上做 (那是数据层面的干预), 但谱在**输入空间**上量
        # (letterbox 到 640×640) —— 与真实域的谱在同一个空间里比, 标定才有意义。
        gray = letterbox_gray(Image.fromarray(out.astype(np.uint8)))
        centers, prof = radial_profile(gray)
        ok = ~np.isnan(prof)
        acc[ok] += prof[ok]
        cnt[ok] += 1
        used += 1
    with np.errstate(invalid="ignore", divide="ignore"):
        out_prof = np.where(cnt > 0, acc / np.maximum(cnt, 1), np.nan)
    return centers, out_prof


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-real", type=int, default=120)
    ap.add_argument("--n-synth", type=int, default=120)
    ap.add_argument("--blur", type=float, default=1.0,
                    help="真实图在输入空间上的高斯模糊 σ (用于拆分'内容密度'与'成像质感')")
    ap.add_argument("--no-calib", action="store_true")
    args = ap.parse_args()

    import numpy as np
    rf = real_train_files()
    sf = sorted(glob.glob(os.path.join(SYNTH_POOL, "*.png")))
    log(f"真实图候选 {len(rf)} 张, 合成图 {len(sf)} 张")
    centers, real_prof, n_real = profile_of_files(rf, args.n_real)
    centers, syn_prof, n_syn = profile_of_files(sf, args.n_synth)
    centers, realblur_prof, _ = profile_of_files(rf, args.n_real, blur=args.blur)
    log(f"谱: 真实 {n_real} 张, 合成 {n_syn} 张 (真实另算一份模糊 σ={args.blur})")

    hi = centers >= R_HI
    gap_hi = float(np.nanmean(real_prof[hi]) - np.nanmean(syn_prof[hi]))
    gap_finish = float(np.nanmean(realblur_prof[hi]) - np.nanmean(syn_prof[hi]))
    gap_content = float(np.nanmean(real_prof[hi]) - np.nanmean(realblur_prof[hi]))
    log(f"高频带 (r>={R_HI}) 总差距 = {gap_hi * 20:.2f} dB | "
        f"其中 内容结构贡献 = {gap_content * 20:.2f} dB, "
        f"成像质感差距 = {gap_finish * 20:.2f} dB")

    calib = None
    if not args.no_calib:
        lo, hi_b = 0.0, 1.0
        best = None
        for _ in range(9):
            mid = (lo + hi_b) / 2
            _, p = synth_profiles_with_sigma(sf, mid, min(args.n_synth, 60))
            d = float(np.nanmean(real_prof[hi]) - np.nanmean(p[hi]))
            log(f"  sigma={mid:.4f} -> 高频差距 {d:+.3f}")
            if best is None or abs(d) < abs(best[1]):
                best = (mid, d)
            if d > 0:
                lo = mid
            else:
                hi_b = mid
            if abs(d) < 0.01:
                break
        calib = {"sigma": round(best[0], 4), "residual_log10": round(best[1], 4),
                 "n_synth_used": min(args.n_synth, 60),
                 "rule": "使扰动后合成图高频带 (r>=%.2f) 平均谱水平追平真实图" % R_HI}
        _, p = synth_profiles_with_sigma(sf, calib["sigma"], args.n_synth)
        calib["after_profile"] = [None if np.isnan(v) else round(float(v), 4)
                                  for v in p]
        with open(os.path.join(BENCH, "syn2real_pasta_calib.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(calib, fh, ensure_ascii=False, indent=2)
        log(f"标定 sigma = {calib['sigma']} (残差 {calib['residual_log10']:+.3f})")

    rep = {"schema": "spectral_gap/1",
           "generated_by": "pipelines/shelf_sdg/54_spectral_gap.py",
           "measured_at": "2026-11-25",
           "n_real": n_real, "n_synth": n_syn, "n_bands": NB,
           "freq_centers": [round(float(c), 4) for c in centers],
           "real_profile_log10": [None if np.isnan(v) else round(float(v), 4)
                                  for v in real_prof],
           "real_blur_profile_log10": [None if np.isnan(v) else round(float(v), 4)
                                       for v in realblur_prof],
           "synth_profile_log10": [None if np.isnan(v) else round(float(v), 4)
                                   for v in syn_prof],
           "gap_per_band_db": [None if (np.isnan(a) or np.isnan(b))
                               else round(float((a - b) * 20), 2)
                               for a, b in zip(real_prof, syn_prof)],
           "high_band_gap_db": round(gap_hi * 20, 2),
           "high_band_gap_finish_db": round(gap_finish * 20, 2),
           "high_band_gap_content_db": round(gap_content * 20, 2),
           "blur_sigma": args.blur,
           "calibration": calib,
           "note": ("log10 幅值 -> dB 用 20*log10; 正值 = 真实图该频带能量更高。"
                    "PASTA 扰动只加振幅噪声(相位不动), 所以结构与框不变。"
                    "谱在**检测器输入空间**(letterbox 640x640)里量, 否则比的是分辨率差。"
                    "总差距拆成两部分: 内容结构贡献 (真实图模糊后仍高于合成的部分) 与 "
                    "成像质感差距 (模糊掉内容结构后仍差的部分)。")}
    with open(os.path.join(BENCH, "spectral_gap.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    os.makedirs(PUB, exist_ok=True)
    import shutil
    shutil.copy2(os.path.join(BENCH, "spectral_gap.json"),
                 os.path.join(PUB, "spectral_gap.json"))

    lines = ["# 频谱差距: 合成图 vs 真实图 (2026-11-25)", "",
             f"真实 {n_real} 张 vs 合成 {n_syn} 张, 径向平均 log10 幅值谱, "
             f"共 {NB} 个频带。", "",
             "谱在**检测器输入空间**(letterbox 640×640)里量 —— 否则比的是分辨率差, "
             "不是纹理多少。", "",
             "| 频带中心 r | 真实 (log10) | 真实·模糊σ1 (log10) | 合成 (log10) | "
             "总差距 (dB) |",
             "|---:|---:|---:|---:|---:|"]
    for c, rp, rb, sp, g in zip(centers, real_prof, realblur_prof, syn_prof,
                                rep["gap_per_band_db"]):
        lines.append(f"| {c:.3f} | {rp:.3f} | {rb:.3f} | {sp:.3f} | "
                     f"{('+' + format(g, '.2f')) if g is not None else '—'} |")
    lines += ["", f"**高频带 (r ≥ {R_HI}) 总差距 = {rep['high_band_gap_db']:+.2f} dB** "
              "(正值 = 真实图高频能量更高 = 合成图纹理/细节不足)。",
              f"拆开看: **内容结构贡献 = {rep['high_band_gap_content_db']:+.2f} dB**"
              f"(真实图模糊掉细节后仍比合成图多的部分 —— 主要是真实图有 7 倍多的物体/边缘), "
              f"**成像质感差距 = {rep['high_band_gap_finish_db']:+.2f} dB**"
              f"(模糊掉内容结构后仍差的部分)。"]
    if calib:
        lines += ["", f"PASTA 强度标定: **σ = {calib['sigma']}** "
                  f"(残差 {calib['residual_log10']:+.3f} log10)。",
                  "标定规则: 使扰动后合成图的高频带平均谱水平追平真实图。"]
    lines += ["", "依据: PASTA (Chattopadhyay et al., ICCV 2023) —— "
              "合成图高频振幅变化不足会损害 sim2real 迁移。"]
    md = "\n".join(lines) + "\n"
    with open(os.path.join(BENCH, "spectral_gap.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    shutil.copy2(os.path.join(BENCH, "spectral_gap.md"),
                 os.path.join(PUB, "spectral_gap.md"))
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
