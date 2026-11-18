"""平台适配管线: 从冻结商业主视觉 (repro_final.png) 生成各平台上架尺寸变体.

三审终裁 (v75 冻结, 92/100 PASS) 后的交付阶段:
- 天猫主图 800x800 (方形, 主体居中裁切)
- 天猫详情页氛围图 750 宽竖版 (上裁产品区)
- 电商场景图 800x800 (同天猫主图裁切策略, 独立文件)
- 小红书/内容场 1242x1660 竖版 (3:4 裁切)
白底主图不在此管线: 三审裁"深暖场景不适用白底用途", 白底=独立资产战役 (另立).

用法: python3 36_platform_adapt.py --src output/commercial/repro_final.png --out output/platform/
产出: output/platform/*.png + manifest.json (裁切窗/用途/冻结源 hash)
"""
import argparse
import hashlib
import json
import os

from PIL import Image

# (name, 目标尺寸, 裁切窗比例 (x0,y0,x1,y1) 相对源图, 用途)
VARIANTS = [
    ("tmall_main_800", (800, 800), (0.10, 0.28, 0.90, 0.98), "天猫主图: 主体+玻璃前景, 方形"),
    ("tmall_detail_750", (750, 1000), (0.18, 0.20, 0.82, 1.00), "天猫详情页氛围图: 竖版产品区"),
    ("jd_scene_800", (800, 800), (0.10, 0.28, 0.90, 0.98), "电商场景图: 同主图裁切策略"),
    ("xhs_content_1242", (1242, 1660), (0.22, 0.10, 0.78, 0.85), "小红书/内容场: 3:4 竖版"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="output/commercial/repro_final.png")
    ap.add_argument("--out", default="output/platform")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    im = Image.open(args.src).convert("RGB")
    W, H = im.size
    sha = hashlib.sha256(open(args.src, "rb").read()).hexdigest()[:16]
    manifest = {"source": args.src, "source_sha256_16": sha, "source_size": [W, H], "variants": []}
    for name, (tw, th), (x0, y0, x1, y1), usage in VARIANTS:
        box = (int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H))
        crop = im.crop(box)
        # 保持裁切窗宽高比贴合目标: 先中心修边再 resize
        cw, ch = crop.size
        tar = tw / th
        cur = cw / ch
        if cur > tar:
            nw = int(ch * tar)
            dx = (cw - nw) // 2
            crop = crop.crop((dx, 0, dx + nw, ch))
        else:
            nh = int(cw / tar)
            dy = (ch - nh) // 2
            crop = crop.crop((0, dy, cw, dy + nh))
        out = crop.resize((tw, th), Image.LANCZOS)
        p = os.path.join(args.out, name + ".png")
        out.save(p)
        manifest["variants"].append({"file": p, "size": [tw, th], "crop": box, "usage": usage})
        print(f"[ADAPT] {name} {tw}x{th} <- crop{box}")
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, ensure_ascii=False)
    print(f"[ADAPT] {len(VARIANTS)} variants -> {args.out}")


if __name__ == "__main__":
    main()
