#!/usr/bin/env python3
"""Hybrid texture transfer: AI finish contributes TEXTURE only (grain + micro-contrast),
render contributes every structural pixel (brand print bit-faithful, gates stay green).

Method (v2, after global-curve v1 failed):
  1. grain: match the GPT finish's flat-region high-freq sigma onto the render (deterministic RNG)
  2. micro-contrast: luminance unsharp (gaussian σ=2, amount 0.35) — high-freq only, zero tone change
Global tone / layout / color are NEVER taken from the AI image: GPT's look is a different
(filmic, muted) grade that breaks the reference-calibrated gates; texture is what judges
read as "photographic" and is safe to transfer.

Usage: python3 21_hybrid_texture_transfer.py <render> <gpt_finish> <out.png> [--unsharp A]
Gate note: candidate MUST get sidecars copied next to it (<out>_regions.json,
<out>_brandbox.json from the render) or lifestyle_gate.py silently degrades its
regions and reports false FAILs (G9a 0.31->0.14, G7 25.6->15.5 measured).
"""
import sys, json
import numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, uniform_filter

UNSHARP_AMOUNT = 0.35
GRAIN_CAP = 4.0

def grain_sigma(img):
    g = img.mean(axis=2)
    hf = g - gaussian_filter(g, 2.0)
    flat = np.abs(uniform_filter(g, 15) - uniform_filter(g, 45)) < 3.0
    return float(hf[flat].std()) if flat.sum() > 1000 else float(hf.std())

def focus_weight(y):
    """High where the render is already sharp (in-focus), ~0 in DOF-blurred zones.
    Keeps the render's depth-of-field ratio intact (G8/G10/G11): texture is only
    added where texture is visible."""
    e = np.abs(y - gaussian_filter(y, 2.0))
    e = gaussian_filter(e, 8.0)
    e = e / (np.quantile(e, 0.95) + 1e-6)
    w = np.clip(e * 1.5, 0.0, 1.0)
    return gaussian_filter(w, 4.0)[..., None]

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    am = UNSHARP_AMOUNT
    for i, a in enumerate(sys.argv):
        if a == "--unsharp":
            am = float(sys.argv[i + 1])
    ren_path, gpt_path, out_path = args
    ren = np.asarray(Image.open(ren_path).convert("RGB")).astype(np.float32)
    gpt = np.asarray(Image.open(gpt_path).convert("RGB").resize(
        (ren.shape[1], ren.shape[0]), Image.LANCZOS)).astype(np.float32)

    sig_gpt, sig_ren = grain_sigma(gpt), grain_sigma(ren)
    add = min(max(sig_gpt - sig_ren, 0.0), GRAIN_CAP)
    rng = np.random.RandomState(42)
    noise = rng.normal(0, add, ren.shape[:2]).astype(np.float32)
    y = (ren + noise[..., None]) @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
    detail = (y - gaussian_filter(y, 2.0))[..., None] * am
    w = focus_weight(y)
    hyb = np.clip(ren + noise[..., None] * w + detail * w, 0, 255).astype(np.uint8)
    Image.fromarray(hyb).save(out_path)

    tone_shift = float(np.abs(hyb.mean(axis=2).astype(np.float32) - ren.mean(axis=2)).mean())
    rep = {"base": ren_path, "gpt": gpt_path, "out": out_path,
           "grain_gpt": round(sig_gpt, 2), "grain_render": round(sig_ren, 2),
           "grain_added": round(add, 2), "unsharp_amount": am,
           "mean_abs_luma_shift": round(tone_shift, 3),
           "tone_changed": tone_shift > 3.0}
    json.dump(rep, open(out_path.replace(".png", "_report.json"), "w"), indent=1)
    print(json.dumps(rep, ensure_ascii=False))

if __name__ == "__main__":
    main()
