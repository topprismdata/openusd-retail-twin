#!/usr/bin/env python3
"""真实元素采集重组: 从官方在售图/官方白底图提取品牌真像素, 替换程序化版式
P0 资产修复 (GPT/Gemini 双评审收敛项): 字体/插画/徽章改用品牌真像素, 消灭"视觉身份被重设计"

用法: python3 08_photo_dieline.py
前置: python3 00_bootstrap_textures.py (先画底版)
输出: assets/textures/{demo_classic,demo_organic}_albedo.png 被原位增强
"""
import os
import sys
import numpy as np
from PIL import Image, ImageFilter, ImageEnhance

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.fonts import load_font  # noqa: E402
TEX = os.path.join(BASE, "assets", "textures")
REF = os.path.join(BASE, "references")

W, H = 2048, 2048
FRONT = (60, 100, 980, 1950)
BACK = (1060, 100, 1980, 1950)
CLASSIC_BG = (146, 124, 86)          # 与 00 profile 一致 (渲染已校准)


PHOTO_KRAFT_MED = None  # 全局照片牛皮纸中位, 首次调用时从净区计算


def _photo_scale():
    """全局归一系数: target_bg / 照片净区中位 (整张照片光照均匀, 单系数正确)"""
    global PHOTO_KRAFT_MED
    if PHOTO_KRAFT_MED is None:
        src = Image.open(os.path.join(REF, "dt_kraft800.jpg")).convert("RGB")
        arr = np.array(src.crop((408, 262, 452, 292))).reshape(-1, 3).astype(np.float32)
        med = np.maximum(np.median(arr, axis=0), 1.0)
        PHOTO_KRAFT_MED = med
    scale = np.array(CLASSIC_BG, dtype=np.float32) / PHOTO_KRAFT_MED
    return np.clip(scale, 0.3, 1.8)


def norm_sprite(img):
    """逐精灵亮部中位归一: kraft 为亮类像素, 取亮度 60 分位以上的中位做基准,
    使每个精灵的底色都对齐 CLASSIC_BG (容忍照片箱面明暗渐变)"""
    arr = np.array(img).astype(np.float32)
    lum = arr.mean(axis=2)
    thr = np.percentile(lum, 60)
    bright = arr[lum >= thr]
    med = np.maximum(np.median(bright, axis=0), 1.0)
    scale = np.clip(np.array(CLASSIC_BG, dtype=np.float32) / med, 0.3, 1.8)
    return Image.fromarray(np.clip(arr * scale, 0, 255).astype(np.uint8))


def paste_region(atlas, region, content):
    """内容拉伸填满 region (预拉伸: 渲染时经 UV 压缩还原比例)"""
    x0, y0, x1, y1 = region
    c = content.resize((x1 - x0, y1 - y0), Image.LANCZOS)
    atlas.paste(c, (x0, y0))


def quad_crop(img, quad, out_w, out_h):
    """QUAD 校正: data = UL, LL, LR, UR (源图四角) -> out 矩形"""
    return img.transform((out_w, out_h), Image.QUAD, data=quad, resample=Image.BICUBIC)


def enhance_classic():
    """经典牛皮纸装: 从电商平台 800px 主图采集参照元素精灵, 按单盒版式重组"""
    src = Image.open(os.path.join(REF, "dt_kraft800.jpg")).convert("RGB")
    atlas = Image.open(os.path.join(TEX, "demo_classic_albedo.png")).convert("RGB")

    fx0, fy0, fx1, fy1 = FRONT
    carton = Image.open(os.path.join(REF, "dt_m_main.jpg")).convert("RGB")  # 参照单盒立图 (版式+底色同源)
    # 1) 参照牛皮纸底色铺满正面 (中位采样 (300,470) 20px patch -> 归一到 CLASSIC_BG)
    flat = carton.crop((657, 260, 671, 345))       # 干净牛皮纸区 (与元素同源照片, 色调一致)
    flat = norm_sprite(flat)
    # 按行取中位 (消窄条光照梯度) + 柔化 (保纸感消条纹)
    fa = np.array(flat)
    row_med = np.median(fa, axis=1, keepdims=True).astype(np.float32)
    flat = Image.fromarray(np.clip(row_med, 0, 255).astype(np.uint8)).resize((44, 86), Image.LANCZOS).filter(ImageFilter.GaussianBlur(3))
    # 行中位竖向渐变直接拉伸铺满全脸: 零接缝零条纹 (纸质感由上游柔化保留)
    atlas.paste(flat.resize((fx1 - fx0, fy1 - fy0), Image.LANCZOS), (fx0, fy0))

    # 1.5) 顶部折边阴影: 前脸顶端 22px 渐变压暗 + 折线, 读作真实纸盒折叠
    _top = np.array(atlas.crop((fx0, fy0, fx1, fy0 + 40))).astype(np.float32)
    for i in range(40):
        k = 1.0 - 0.20 * (1.0 - i / 40.0) ** 1.4
        _top[i] *= k
    atlas.paste(Image.fromarray(np.clip(_top, 0, 255).astype(np.uint8)), (fx0, fy0))
    from PIL import ImageDraw as _ID
    _ID.Draw(atlas).line([(fx0, fy0 + 20), (fx1, fy0 + 20)], fill=(112, 94, 62), width=2)
    _ID.Draw(atlas).line([(fx0, fy0 + 21), (fx1, fy0 + 21)], fill=(168, 146, 108), width=1)

    # 2) 参照元素精灵 — 版式真值来自 dt_m_main.jpg 真实单盒立图 (电商低碳12盒详情主图):
    #    经典标块 12.5-44% / 通栏奶牛花丛插画 39-64% / 徽章行 55-66% /
    #    低碳牧场行 65-75% / 横排纯牛奶书法 74-98% (分数坐标与参照盒逐元素重合)
    carton = Image.open(os.path.join(REF, "dt_m_main.jpg")).convert("RGB")
    W, H = fx1 - fx0, fy1 - fy0
    # name: (dt_m_main 源裁切框, 正面分数框 (x0, y0, x1, y1))
    sprites = {
        "logo":    ((672, 238, 758, 357),  (0.18, 0.125, 0.82, 0.44)),
        "cow2":    ((658, 330, 782, 428),  (0.0, 0.389, 1.0, 0.639)),
        "badges":  ((666, 392, 772, 433),  (0.10, 0.55, 0.90, 0.66)),
        "ditang":  ((668, 428, 768, 466),  (0.10, 0.647, 0.90, 0.753)),
        "shufa_h": ((660, 460, 778, 548),  (0.12, 0.736, 0.88, 0.98)),
    }
    from PIL import ImageDraw
    d = None
    for name, (box, fr) in sprites.items():
        sp = norm_sprite(carton.crop(box))
        x0, y0 = int(fx0 + fr[0] * W), int(fy0 + fr[1] * H)
        x1, y1 = int(fx0 + fr[2] * W), int(fy0 + fr[3] * H)
        sp = sp.resize((max(1, x1 - x0), max(1, y1 - y0)), Image.LANCZOS)
        # 牛皮区整体替换为脸底色 (脸底取样), 艺术像素保留 — 根除矩形衬底
        _arr0 = np.array(sp).astype(np.float32)
        _bord = np.concatenate([_arr0[:2].reshape(-1, 3), _arr0[-2:].reshape(-1, 3),
                                _arr0[:, :2].reshape(-1, 3), _arr0[:, -2:].reshape(-1, 3)])
        _bgm = np.median(_bord, axis=0)
        _dist0 = np.sqrt(((_arr0 - _bgm) ** 2).sum(axis=2))
        _art = np.clip((_dist0 - 30) / 26.0, 0, 1)
        _art = np.array(Image.fromarray((_art * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3))).astype(np.float32)[:, :, None] / 255.0
        if not hasattr(enhance_classic, "_bgfill"):
            _fs = np.array(atlas.crop((fx0, fy1 - 38, fx1, fy1 - 10))).reshape(-1, 3)
            enhance_classic._bgfill = np.median(_fs, axis=0)
        sp = Image.fromarray(np.clip(_arr0 * _art + enhance_classic._bgfill[None, None, :] * (1 - _art), 0, 255).astype(np.uint8))
        # 逐元素专项增强 — 掩码版: 只增强艺术像素, 牛皮纸边原样保留 (防矩形补丁)
        if name in ("logo", "badges", "shufa_h", "cow2"):
            arr = np.array(sp).astype(np.float32)
            border = np.concatenate([arr[:2].reshape(-1, 3), arr[-2:].reshape(-1, 3),
                                     arr[:, :2].reshape(-1, 3), arr[:, -2:].reshape(-1, 3)])
            bg_med = np.median(border, axis=0)
            dist = np.sqrt(((arr - bg_med) ** 2).sum(axis=2))
            mask = np.clip((dist - 22) / 30.0, 0, 1)
            mimg = Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))
            mask = np.array(mimg).astype(np.float32)[:, :, None] / 255.0
            if name in ("logo", "badges", "shufa_h"):
                e = ImageEnhance.Color(sp).enhance(1.22)
                e = ImageEnhance.Contrast(e).enhance(1.18)
                e = e.filter(ImageFilter.UnsharpMask(radius=1.6, percent=162, threshold=1))
            else:
                ea = np.power(arr / 255.0, 0.88)
                e = Image.fromarray(np.clip(ea * 255, 0, 255).astype(np.uint8))
                e = ImageEnhance.Contrast(e).enhance(1.10)
                e = ImageEnhance.Color(e).enhance(1.16)
                e = e.filter(ImageFilter.UnsharpMask(radius=2.2, percent=120, threshold=2))
            out = arr * (1 - mask) + np.array(e).astype(np.float32) * mask
            sp = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
        else:
            sp = sp.filter(ImageFilter.UnsharpMask(radius=2, percent=135, threshold=2))
        # 羽化贴边: 精灵牛皮边与脸底自然过渡, 消矩形拼接痕
        w_, h_ = sp.size
        feather = 14
        am = np.ones((h_, w_), dtype=np.float32)
        ramp = np.linspace(0, 1, feather)
        am[:feather] *= ramp[:, None]; am[-feather:] *= ramp[::-1][:, None]
        am[:, :feather] *= ramp[None, :]; am[:, -feather:] *= ramp[::-1][None, :]
        atlas.paste(sp, (x0, y0), Image.fromarray((am * 255).astype(np.uint8)))
        if d is None:
            d = ImageDraw.Draw(atlas)

    # 3) 底部小字区: 用脸部自身像素条覆盖旧层 (色调连续无拼接痕), 再深墨直绘
    _src = atlas.crop((fx0, fy1 - 38, fx1, fy1 - 10)).resize((fx1 - fx0, 195), Image.LANCZOS)
    _am = np.ones((195, fx1 - fx0), dtype=np.float32)
    _ramp = np.linspace(0, 1, 12)
    _am[:12] *= _ramp[:, None]; _am[-12:] *= _ramp[::-1][:, None]
    atlas.paste(_src, (fx0, fy1 - 192), Image.fromarray((_am * 255).astype(np.uint8)))
    d.text(((fx0 + fx1) // 2, fy1 - 125), "净含量: 250mL", fill=(38, 31, 20),
           font=load_font(int((fx1 - fx0) * 0.058), kind="cjk"),
           anchor="mm")
    d.text(((fx0 + fx1) // 2, fy1 - 48), "生产日期/保质期至: 见盒顶部喷码", fill=(58, 49, 33),
           font=load_font(int((fx1 - fx0) * 0.035), kind="cjk"),
           anchor="mm")

    # 3.5) 纸面印刷颗粒: 全脸 2.5% 亮度噪声 + 极轻水平纤维条纹 (纸感)
    _face = np.array(atlas.crop((fx0, fy0, fx1, fy1))).astype(np.float32)
    rng = np.random.default_rng(42)
    Hf, Wf = _face.shape[:2]
    # 低频不均匀斑块场: 8x14 随机格 -> 平滑放大到全脸 (印刷/纸面自然差异, 非"统一滤层")
    blotch = rng.normal(1.0, 0.45, (8, 14))
    blotch = np.array(Image.fromarray(((blotch - blotch.min()) / np.ptp(blotch) * 255).astype(np.uint8))
                      .resize((Wf, Hf), Image.BICUBIC).filter(ImageFilter.GaussianBlur(24))
                      ).astype(np.float32) / 255.0
    blotch = 0.35 + 1.25 * blotch  # [0.35, 1.6]
    _noise = rng.normal(0, 2.0, (Hf, Wf)) * blotch
    _fiber = (np.sin(np.arange(Hf) * 1.7) * 0.8)
    _face = np.clip(_face + _noise[:, :, None] + _fiber[:, None, None], 0, 255)
    atlas.paste(Image.fromarray(_face.astype(np.uint8)), (fx0, fy0))

    # 4) 清正面金属遮罩 (旧版式烫金区已错位; 真实金墨在照片里已烘焙)
    orm = np.array(Image.open(os.path.join(TEX, "demo_classic_orm.png")))
    orm[fy0:fy1, fx0:fx1, 2] = 0
    Image.fromarray(orm).save(os.path.join(TEX, "demo_classic_orm.png"))

    atlas.save(os.path.join(TEX, "demo_classic_albedo.png"))
    print("[OK] demo_classic: 参照元素重组完成 (logo/牧场文案/奶牛花环/书法/徽章)")


def enhance_organic():
    """有机白瓶装: 从官方白底图 ref1 (1920x1080) QUAD 校正取真实正/背面全幅"""
    src = Image.open(os.path.join(REF, "ref1.jpg")).convert("RGB")
    atlas = Image.open(os.path.join(TEX, "demo_organic_albedo.png")).convert("RGB")

    # 正面 (左盒平正面): 手工标定四角 UL,LL,LR,UR (原图坐标)
    front = quad_crop(src, (556, 352, 536, 966, 822, 966, 798, 356), 920, 1850)
    paste_region(atlas, FRONT, front)
    # 背面/信息面 (右盒): UL,LL,LR,UR
    back = quad_crop(src, (1122, 240, 1114, 956, 1488, 956, 1446, 248), 920, 1850)
    paste_region(atlas, BACK, back)

    orm = np.array(Image.open(os.path.join(TEX, "demo_organic_orm.png")))
    orm[FRONT[1]:FRONT[3], FRONT[0]:FRONT[2], 2] = 0
    orm[BACK[1]:BACK[3], BACK[0]:BACK[2], 2] = 0
    Image.fromarray(orm).save(os.path.join(TEX, "demo_organic_orm.png"))

    atlas.save(os.path.join(TEX, "demo_organic_albedo.png"))
    print("[OK] demo_organic: 参照图正/背面全幅贴图完成")


if __name__ == "__main__":
    from PIL import ImageFont
    enhance_classic()
    enhance_organic()
    print("[Done] 08 照片刀模增强完成")
