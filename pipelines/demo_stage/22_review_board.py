#!/usr/bin/env python3
"""22 - 三方对比评审板拼装: [真实参照 | GPT AI 直出 | OpenUSD 渲染]

用途: 拼 13 SKU 三方对比板供 GPT 评审 OpenUSD 渲染是否满足电商要求。
用法: python3 22_review_board.py --out /tmp/review_board.png --skus demo_classic demo_organic ...
参照缺失的 SKU 显示占位说明 (references/ai_gen + output/multi_platform 同源)。
"""
import argparse
import importlib.util as ilu
import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CELL_W, CELL_H, BAR_H, PAD = 340, 420, 34, 6


def _profiles():
    spec = ilu.spec_from_file_location("b00", os.path.join(BASE, "pipelines/bootstrap/00_bootstrap_textures.py"))
    m = ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.SKU_PROFILES


REF_IMG = {
    "demo_organic": "references/dt_m_main.jpg",
    # demo_cny=马年限定红金款, 无已验证参照
    "demo_yogurt_original": "references/yogurt_ref/main_01.jpg",
    "demo_yogurt_gold": "references/yogurt_ref/main_01.jpg",
    "demo_yogurt_gift": "references/yogurt_ref/main_01.jpg",
}


def load_contain(path, w, h):
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    im.thumbnail((w, h))
    return im


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skus", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="三方对比评审板")
    a = ap.parse_args()
    prof = _profiles()
    try:
        font = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 17)
        font_s = ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", 13)
    except Exception:
        font = font_s = ImageFont.load_default()

    rows = len(a.skus)
    W = 3 * CELL_W + 4 * PAD
    H = rows * (CELL_H + BAR_H + PAD) + BAR_H + 2 * PAD
    board = Image.new("RGB", (W, H), (246, 247, 249))
    d = ImageDraw.Draw(board)
    d.text((PAD, PAD), a.title, fill=(30, 30, 30), font=font)

    heads = ["① 真实参照 (电商/官方)", "② GPT AI 直出生图", "③ OpenUSD 数字孪生渲染"]
    for c, htxt in enumerate(heads):
        x0 = PAD + c * (CELL_W + PAD)
        d.rectangle([x0, PAD + BAR_H, x0 + CELL_W, PAD + 2 * BAR_H - 4], fill=(228, 231, 236))
        d.text((x0 + 8, PAD + BAR_H + 7), htxt, fill=(50, 50, 50), font=font_s)

    for r, sku in enumerate(a.skus):
        y0 = PAD + BAR_H + r * (CELL_H + BAR_H + PAD)
        p = prof.get(sku, {})
        d.rectangle([PAD, y0, W - PAD, y0 + BAR_H - 4], fill=(38, 66, 108))
        d.text((PAD + 8, y0 + 6), f"{p.get('title', sku)} · {p.get('subtitle', '')}", fill=(255, 255, 255), font=font_s)
        cy = y0 + BAR_H
        # ① 参照
        ref = REF_IMG.get(sku)
        x0 = PAD
        d.rectangle([x0, cy, x0 + CELL_W, cy + CELL_H], fill=(255, 255, 255), outline=(210, 210, 210))
        if ref and os.path.exists(os.path.join(BASE, ref)):
            im = load_contain(os.path.join(BASE, ref), CELL_W - 8, CELL_H - 8)
            board.paste(im, (x0 + (CELL_W - im.width) // 2, cy + (CELL_H - im.height) // 2))
        else:
            d.text((x0 + 14, cy + CELL_H // 2 - 10), "真实参照未入库\n(references/)", fill=(160, 160, 160), font=font_s)
        # ② AI 直出
        ai_p = os.path.join(BASE, "references", "ai_gen", f"ai_gen_{sku}.png")
        x1 = PAD + CELL_W + PAD
        d.rectangle([x1, cy, x1 + CELL_W, cy + CELL_H], fill=(255, 255, 255), outline=(210, 210, 210))
        if os.path.exists(ai_p):
            im = load_contain(ai_p, CELL_W - 8, CELL_H - 8)
            board.paste(im, (x1 + (CELL_W - im.width) // 2, cy + (CELL_H - im.height) // 2))
        else:
            d.text((x1 + 14, cy + CELL_H // 2 - 10), "AI 直出样本缺失", fill=(160, 160, 160), font=font_s)
        # ③ 渲染
        rd_p = os.path.join(BASE, "output", "multi_platform", sku, "01_JD_WhiteBG_800x800.png")
        if not os.path.exists(rd_p):
            rd_p = os.path.join(BASE, "output", "multi_platform", "01_JD_WhiteBG_800x800.png")
        x2 = PAD + 2 * (CELL_W + PAD)
        d.rectangle([x2, cy, x2 + CELL_W, cy + CELL_H], fill=(255, 255, 255), outline=(210, 210, 210))
        if os.path.exists(rd_p):
            im = load_contain(rd_p, CELL_W - 8, CELL_H - 8)
            board.paste(im, (x2 + (CELL_W - im.width) // 2, cy + (CELL_H - im.height) // 2))
        else:
            d.text((x2 + 14, cy + CELL_H // 2 - 10), "渲染缺失 (待补渲)", fill=(160, 160, 160), font=font_s)

    board.save(a.out, quality=92)
    print(f"[BOARD] {a.out} {board.size[0]}x{board.size[1]} rows={rows}")


if __name__ == "__main__":
    main()
