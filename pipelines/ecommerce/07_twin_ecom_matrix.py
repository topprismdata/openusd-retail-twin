#!/usr/bin/env python3
"""目标一: 基于数字孪生生成电商商品图 (资产驱动矩阵 + 证据清单)

同一 OpenUSD 商品母本 -> 3 SKU x 4 平台 = 12 张电商图
每张图记录母本资产哈希/渲染配方 -> manifest.json (ESR 证据链)
另产出 platform_matrix.png 接触表 (一母本 -> 全平台矩阵)

用法: python3 07_twin_ecom_matrix.py [--scene emerald_kv]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "output")
MP = os.path.join(OUT, "multi_platform")
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"
import os as _os
RENDER_SKUS = _os.environ.get("RENDER_SKUS", "").split(",") if _os.environ.get("RENDER_SKUS") else None
SKUS = RENDER_SKUS or ["demo_organic", "demo_classic", "demo_jersey", "demo_cny",
        "demo_a2", "demo_lowfat", "demo_dream38", "demo_dream40",
        "demo_skim", "demo_meadow"]
PLATFORMS = [
    "01_JD_WhiteBG_800x800",
    "02_Tmall_Hero_1x1_1600x1600",
    "03_Douyin_Feed_9x16_1080x1920",
    "04_Xiaohongshu_Note_3x4_1242x1660",
    "05_Back_Nutrition_1600x1600",
    "06_Hero_45deg_1600x1600",
]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def render_sku(sku, scene):
    """跑 01 生成单 SKU 全平台图, 归档到 multi_platform/<sku>/"""
    log = f"/tmp/matrix_{sku}.log"
    r = subprocess.run(
        [BLENDER, "-b", "-P", os.path.join(BASE, "pipelines/ecommerce/01_comfy_usd_compositor.py"),
         "--", "--sku", sku, "--scene", scene],
        capture_output=True, text=True, timeout=900)
    with open(log, "w") as f:
        f.write(r.stdout[-4000:] + r.stderr[-2000:])
    n_ok = r.stdout.count("[Success]")
    dst = os.path.join(MP, sku)
    os.makedirs(dst, exist_ok=True)
    moved = []
    for p in PLATFORMS:
        src = os.path.join(MP, f"{p}.png")
        if os.path.exists(src):
            shutil.move(src, os.path.join(dst, f"{p}.png"))
            moved.append(f"{p}.png")
    return n_ok, moved


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default="emerald_kv")
    args = ap.parse_args()

    tex_dir = os.path.join(BASE, "assets", "textures")
    manifest = {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "pipeline": "OpenUSD twin master -> Blender Cycles (Metal) -> platform compositor",
        "scene": args.scene, "samples": 192,
        "skus": {},
    }

    for i, sku in enumerate(SKUS):
        print(f"[{i+1}/{len(SKUS)}] 渲染 {sku} ...", flush=True)
        n_ok, moved = render_sku(sku, args.scene)
        usdz = os.path.join(OUT, "ar_models", f"retail_{sku}.usdz")
        albedo = os.path.join(tex_dir, f"{sku}_albedo.png")
        manifest["skus"][sku] = {
            "platforms": moved,
            "twin_asset": {
                "usdz": os.path.relpath(usdz, BASE) if os.path.exists(usdz) else None,
                "usdz_sha256_16": sha256(usdz) if os.path.exists(usdz) else None,
                "albedo_sha256_16": sha256(albedo) if os.path.exists(albedo) else None,
            },
            "renders_ok": n_ok,
        }
        print(f"  -> {len(moved)} 平台图, usdz={'OK' if os.path.exists(usdz) else 'MISSING'}", flush=True)

    # 旗舰 SKU(organic) 回填顶层, 保持 Streamlit 工作台路径不变
    hero = os.path.join(MP, "demo_organic")
    for p in PLATFORMS:
        src = os.path.join(hero, f"{p}.png")
        if os.path.exists(src):
            shutil.copy(src, os.path.join(MP, f"{p}.png"))

    mf = os.path.join(MP, "manifest.json")
    with open(mf, "w") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[Manifest] {mf}")
    build_sheet(SKUS if RENDER_SKUS else list(manifest["skus"].keys()))


def build_sheet(skus):
    """母本裂变接触表: 行=SKU, 列=平台, 一屏总览 output/platform_matrix.png"""
    from PIL import Image, ImageDraw, ImageFont
    import os
    CELL, GAP, HEAD = 300, 12, 236
    cols = PLATFORMS
    W = GAP + HEAD + len(cols) * (CELL + GAP)
    H = GAP + HEAD + len(skus) * (CELL + GAP) + 44
    font_path = next((p for p in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc"] if os.path.exists(p)), None)
    def F(sz):
        return ImageFont.truetype(font_path, sz) if font_path else ImageFont.load_default()
    names = {"demo_organic": "经典有机·白瓶金盾", "demo_classic": "经典纯牛奶·电商牛皮纸",
             "demo_cny": "经典·马年新春限定", "demo_a2": "经典A2β-酪蛋白·蓝白",
             "demo_lowfat": "经典高钙低脂·青绿", "demo_dream38": "经典梦幻盖3.8·奶油白金",
             "demo_dream40": "经典4.0蛋白·白紫", "demo_skim": "经典脱脂·冰蓝",
             "demo_meadow": "经典草原·金草甸",
             "demo_jersey": "经典娟姗·黑金", "demo_cny": "春节马年限定·红金"}
    col_names = ["电商白底", "天猫 KV", "抖音 9:16", "小红书 3:4", "背面营养表", "45° 轴测"]
    sheet = Image.new("RGB", (W, H), (242, 242, 240))
    d = ImageDraw.Draw(sheet)
    for c, cn in enumerate(col_names):
        d.text((GAP + HEAD + c * (CELL + GAP) + CELL // 2, GAP + 14), cn,
               fill=(40, 42, 40), font=F(26), anchor="mm")

    def cell_fit(im, white_bg):
        """白底图按内容 bbox 紧裁再垫白成方 (缩略图可读), 其余中心裁方"""
        if white_bg:
            g = im.convert("L").point(lambda v: 0 if v > 244 else 255)
            bb = g.getbbox()
            if bb:
                pad = 14
                im = im.crop((max(0, bb[0] - pad), max(0, bb[1] - pad),
                              min(im.width, bb[2] + pad), min(im.height, bb[3] + pad)))
                side = max(im.size)
                base = Image.new("RGB", (side, side), (255, 255, 255))
                base.paste(im, ((side - im.width) // 2, (side - im.height) // 2))
                im = base
        s = max(CELL / im.width, CELL / im.height)
        im = im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)
        cx, cy = (im.width - CELL) // 2, (im.height - CELL) // 2
        return im.crop((cx, cy, cx + CELL, cy + CELL))

    for r, sku in enumerate(skus):
        y = GAP + HEAD + r * (CELL + GAP)
        d.text((GAP + 10, y + CELL // 2), names.get(sku, sku), fill=(40, 42, 40), font=F(26))
        for c, p in enumerate(cols):
            x = GAP + HEAD + c * (CELL + GAP)
            f = os.path.join(MP, sku, f"{p}.png")
            if os.path.exists(f):
                im = Image.open(f).convert("RGB")
                sheet.paste(cell_fit(im, c in (0, 4, 5)), (x, y))
            else:
                d.rectangle([x, y, x + CELL, y + CELL], outline=(200, 200, 198), width=2)
    dst = os.path.join(OUT, "platform_matrix.png")
    sheet.save(dst)
    print(f"[Sheet] {dst}")


if __name__ == "__main__":
    main()
