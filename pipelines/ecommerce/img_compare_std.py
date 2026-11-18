#!/usr/bin/env python3
# 标准图片对比框架 (R41): SSIM + LPIPS + CLIP余弦 + 色彩直方图, 渲染vs实拍统一仪器
# 用法: python3 img_compare_std.py A.jpg B.jpg [--label A名 B名] [--regions]
import sys, json, argparse
import numpy as np
from PIL import Image

def load_rgb(p, size=None):
    im = Image.open(p).convert("RGB")
    if size: im = im.resize(size, Image.LANCZOS)
    return im

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("a"); ap.add_argument("b")
    ap.add_argument("--label", nargs=2, default=["A", "B"])
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    from skimage.metrics import structural_similarity as ssim_fn
    import torch, lpips, open_clip

    imA, imB = load_rgb(args.a), load_rgb(args.b)
    size = imA.size
    imB = imB.resize(size, Image.LANCZOS)
    a = np.asarray(imA, dtype=np.float32); b = np.asarray(imB, dtype=np.float32)
    lab = f"{args.label[0]} vs {args.label[1]} @{size[0]}x{size[1]}"
    out = {"pair": lab}

    # 1) SSIM (灰度, 标准窗口)
    la = 0.2126*a[...,0]+0.7152*a[...,1]+0.0722*a[...,2]
    lb = 0.2126*b[...,0]+0.7152*b[...,1]+0.0722*b[...,2]
    out["ssim"] = float(ssim_fn(la, lb, data_range=255))

    # 2) LPIPS (Alex)
    loss_fn = lpips.LPIPS(net='alex', verbose=False)
    ta = torch.from_numpy(a.transpose(2,0,1)[None]/255.*2-1).float()
    tb = torch.from_numpy(b.transpose(2,0,1)[None]/255.*2-1).float()
    with torch.no_grad():
        out["lpips"] = float(loss_fn(ta, tb).item())

    # 3) CLIP 余弦
    clipm, _, pre = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
    clipm.eval()
    def emb(im):
        with torch.no_grad():
            e = clipm.encode_image(pre(im).unsqueeze(0))
            return e / e.norm(dim=-1, keepdim=True)
    out["clip_cos"] = float(emb(imA) @ emb(imB).T)

    # 4) 色彩: RGB直方图相关 + 全局均值差
    for i, ch in enumerate("RGB"):
        ha = np.histogram(a[...,i], bins=64, range=(0,255), density=True)[0]
        hb = np.histogram(b[...,i], bins=64, range=(0,255), density=True)[0]
        out[f"hist_corr_{ch}"] = float(np.corrcoef(ha, hb)[0,1])
    out["mean_rgb_diff"] = [float(x) for x in (a.mean((0,1)) - b.mean((0,1)))]

    print("== 标准对比:", lab)
    print("SSIM  = %.4f  (1=同结构)" % out["ssim"])
    print("LPIPS = %.4f  (0=感知相同)" % out["lpips"])
    print("CLIP  = %.4f  (语义余弦)" % out["clip_cos"])
    print("直方图相关 R/G/B = %.3f/%.3f/%.3f" % (out["hist_corr_R"], out["hist_corr_G"], out["hist_corr_B"]))
    print("均值差 RGB =", [round(x,1) for x in out["mean_rgb_diff"]])
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), ensure_ascii=False, indent=1)
        print("JSON →", args.json_out)

if __name__ == "__main__":
    main()
