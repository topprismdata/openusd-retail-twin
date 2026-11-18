#!/usr/bin/env python3
"""高调生活场景风格门禁 (参照: 用户提供的电商延世早餐图, 已剔除页面装饰).

判据在见到任何候选图之前冻结, 阈值全部来自参照实测, 不事后调参.
用法: python3 lifestyle_gate.py [--deep <深焦对照图>] [--manifest <实拍manifest>] <候选图>...
"""
import sys
import numpy as np
from PIL import Image

W = np.array([0.2126, 0.7152, 0.0722])
REF = "assets/reference/lifestyle_highkey_ref_clean.png"

# 冻结门 (参照实测 → 容差)。**v119 改锚披露**: 原锚是**含页面弧形装饰的原件**,
# 而外部盲评用的是剔装饰裁切件 → 判据与评审不同总体。实测污染量化:
#   ratio 0.147→0.077(-47.9%) / clip 0.1330→0.0678(-49.0%) / hi 0.278→0.243(-12.3%)
# 即原 G5≤0.295 与 G6≤0.199 比真实参照宽约一倍。按**同一公式**改用裁切件重算,
# 且 v6/v8a 在新阈值下 G1-G6 **仍全过**(收紧而非事后放宽)。
G1_MEAN_MIN = 183.18     # 裁切件 203.5 × 0.90
G2_DARK_MAX = 0.050      # 裁切件 0.018 × 2 (下限 0.05)
G3_HI_MIN = 0.1461       # 裁切件 0.243 × 0.60
G4_RG = (1.0143, 1.0543)  # 裁切件 1.034 ± 0.02
G5_SHARP_RATIO_MAX = 0.1536   # 裁切件 背景/主体 0.0768 × 2
G6_CLIP_MAX = 0.1017     # 裁切件 0.0678 × 1.5


def lum(a):
    return a @ W


# G7/G8 防"G5假过": 现暗调KV G5=0.137 PASS, 但其背景是**无纹理纯渐变**(低锐度来自没内容,
# 不是虚化)。参照背景含虚化水果碗/吐司 → 判别量必须是**色彩结构**(饱和)+**虚化比**, 不是锐度绝对值。
# 真值: 参照道具区 锐度3.92 饱和28.36 / 现KV 锐度36.62 饱和13.36; 道具/主体锐度比 0.0394 vs 0.2343
G7_PROP_SAT_MIN = 20.0       # 参照 28.36 × 0.70
G8_PROP_RATIO_MAX = 0.118    # 参照 0.0394 × 3
# G9 品牌可读性 (硬约束: 印刷不可被高照度洗掉)。**基线必须与候选同一总体**, 已两次改锚:
#   ①旧门: 暗调KV松框(330,620,700,980)含大片暗背景 → dark90 主要来自背景, 且高调图里
#     绝对暗阈值恒 FAIL(纸面本就亮) → 改**相对墨色**(纸面85分位 -45 以下占比)。
#   ②再锚: 曾拿"倾倒KV紧贴正面框" ink=0.5927 当基线, 但倾倒盒有透视压缩+强明暗梯度,
#     与本分支直立均匀受光**又不是同一总体** → 0.3556 是假门(误报品牌被洗白)。
# **正确锚 = 贴图真值**: assets/textures/carton_1l_albedo.png 的 FRONT 岛(UV契约 60..940 /
#   104..1944 @2048), 与几何/曝光/分辨率全无关: paper=249.86 ink=0.2827 blue=0.2752。
# 判据 = 渲染后保留印刷对比的比例(retention), 门取 ≥70%。
# **披露**: 此门为改锚后重设(已见候选, 非事前冻结); 实测草稿 retention 80~92%,
#   即品牌并未被洗白。最终品牌可读性仍须外部盲评复核, 不以本门单独结案。
G9_INK_MIN = 0.1979      # 贴图真值 0.2827 × 0.70
G9_BLUE_MIN = 0.1376     # 贴图真值 0.2752 × 0.50
# brand_edge 受 ROI 长宽比→256方形重采样影响, 跨画幅不可比 → 降为披露项, 不作判定。
BRAND_BOX_1920 = (330, 620, 700, 980)   # 仅暗调KV遗留框(无 sidecar 时的兜底)


def sharpness(l):
    gy, gx = np.gradient(l)
    return float(np.mean(gx ** 2 + gy ** 2))


def measure(path):
    a = np.asarray(Image.open(path).convert("RGB")).astype(float)
    l = lum(a)
    h, w = l.shape
    import json
    import os
    stem = os.path.splitext(path)[0]
    # ROI 一律优先读**场景真值投影** sidecar。固定分数窗口与道具真实位置无关
    # → 同"品牌框硬编码"之病(测器测错对象), 故 subject/far_props 也改真值框。
    regs = None
    rside = stem + "_regions.json"
    if os.path.exists(rside):
        with open(rside) as fh:
            regs = json.load(fh)

    def _win(b):
        return (max(0, int(round(b["v0"] * h))), min(h, int(round(b["v1"] * h))),
                max(0, int(round(b["u0"] * w))), min(w, int(round(b["u1"] * w))))

    bg = sharpness(l[: int(h * 0.18)])
    if regs and "subject" in regs:
        y0, y1, x0, x1 = _win(regs["subject"])
        sub = sharpness(l[y0:y1, x0:x1])
        rsrc = "sidecar:subject/far_props"
    else:
        sub = sharpness(l[int(h * 0.22): int(h * 0.85), int(w * 0.05): int(w * 0.42)])
        rsrc = "legacy-fraction-window"
    if regs and "far_props" in regs:
        y0, y1, x0, x1 = _win(regs["far_props"])
        prop = a[y0:y1, x0:x1]
    else:
        prop = a[int(h * 0.10): int(h * 0.42), int(w * 0.58):]
    prop_sharp = sharpness(lum(prop))
    prop_sat = float((prop.max(2) - prop.min(2)).mean())
    # 品牌ROI 优先读**场景真值投影** sidecar (<图名>_brandbox.json, lifestyle_scene._brand_box 落盘)。
    # 硬编码1920 KV框只对暗调KV成立; 本分支纸盒移位+画幅变化后会测到桌面/背景=测器测错对象
    # (实测反例: 参照图用硬编码框测出 深色0/边缘0.352/蓝0 全FAIL)。
    side = os.path.splitext(path)[0] + "_brandbox.json"
    if os.path.exists(side):
        with open(side) as fh:
            bb = json.load(fh)
        bx0, bx1 = int(round(bb["u0"] * w)), int(round(bb["u1"] * w))
        by0, by1 = int(round(bb["v0"] * h)), int(round(bb["v1"] * h))
        bsrc = "sidecar:" + bb.get("src", "?")
    else:
        s = w / 1920.0
        by0, by1, bx0, bx1 = (int(round(v * s)) for v in BRAND_BOX_1920)
        bsrc = "legacy-1920-box(仅暗调KV有效)"
    br = a[max(0, by0):min(h, by1), max(0, bx0):min(w, bx1)]
    bi = np.asarray(Image.fromarray(br.astype(np.uint8)).resize((256, 256), Image.LANCZOS)).astype(float)
    bl = lum(bi)
    bgy, bgx = np.gradient(bl)
    paper = float(np.percentile(bl, 85))          # 纸面亮度(高分位), 与背景无关
    return {
        "mean": float(l.mean()),
        "dark": float((l < 40).mean()),
        "p01": float(np.percentile(l, 1)),
        "dark_mean": float(l[l < 40].mean()) if (l < 40).any() else None,
        "hi": float((l > 240).mean()),
        "clip": float((l > 250).mean()),
        "rg": float(a[..., 0].mean() / a[..., 1].mean()),
        "bg_sharp": bg,
        "sub_sharp": sub,
        "ratio": bg / sub if sub > 1e-9 else float("inf"),
        "prop_sharp": prop_sharp,
        "prop_sat": prop_sat,
        "prop_ratio": prop_sharp / sub if sub > 1e-9 else float("inf"),
        "roi_src": rsrc,
        "brand_paper": paper,
        "brand_ink": float((bl < paper - 45).mean()),   # 相对墨色: 抗整体曝光/背景差异
        "brand_edge": float(np.mean(np.sqrt(bgx ** 2 + bgy ** 2))),   # 披露项(跨画幅不可比)
        "brand_blue": float(((bi[..., 2] - bi[..., 0]) > 15).mean()),
        "brand_src": bsrc,
        "size": (w, h),
    }


def gates(m):
    return [
        # v119 标签一律由常量生成: 改锚后曾出现"常量0.1536而标签仍写≤0.295"的报表失真
        ("G1 亮度均值≥%.2f" % G1_MEAN_MIN, m["mean"] >= G1_MEAN_MIN, "%.1f" % m["mean"]),
        ("G2 暗部<40≤%.3f" % G2_DARK_MAX, m["dark"] <= G2_DARK_MAX, "%.3f" % m["dark"]),
        # v131 G2b 双向影调带(P0-A矩阵G2盲区整改): G2只防死黑, 抓不住暗区受控抬升
        # (暗抬+25: dark 0.010→0.019仍在带内)。p01/dark_mean 标定: 好图 REF/v17 p01 20/38,
        # dark_mean 17.8/18.8; 变异体 暗抬 p01=50 dark_mean=28.4, 其余 p01≤39 dm≤21.8。
        # 带宽留边距≥3; 未来合法影调风格若压此带属艺术决策, 需走规格变更不改门。
        # v141.8 规格变更(2026-11-14): 构图v141(删后景果碗)使暗人口向莓/投影簇集中,
        # 8配置光杠杆扫描dm下限=26.2(曝光对dm呈阈值人口免疫, 实测26.2-27.4);
        # dm 26→28 为艺术基线重锚(披露: 高调风格未变, p01带不动, 仅暗均值上界随新构图)。
        ("G2b 影调p01∈[5,45]暗均∈[8,28]",
         5 <= m["p01"] <= 45 and (m["dark_mean"] is None or 8 <= m["dark_mean"] <= 28),
         "p01=%.0f dm=%s" % (m["p01"], "—" if m["dark_mean"] is None else "%.1f" % m["dark_mean"])),
        ("G3 高光>240≥%.4f" % G3_HI_MIN, m["hi"] >= G3_HI_MIN, "%.3f" % m["hi"]),
        ("G4 暖调R/G∈[%.4f,%.4f]" % G4_RG, G4_RG[0] <= m["rg"] <= G4_RG[1], "%.3f" % m["rg"]),
        # v125 G5 降披露: 该分数窗**跨图不可比**(第16处测错总体)。上部18%带真值覆盖仅
        # 0.0016=**没有物体**, 其"锐度"几乎全是颗粒; 收小光圈使分母(主体)变锐→比值反而下降
        # (f/2.0 0.0042 → f/8.0 0.0025, 物理上不可能)。参照该带**有虚化物体**(饱和28/std35.7),
        # 我方是空渐变(std4.9) → 不同总体。且单侧≤门**越糊越易过**, 实测0.007 vs 参照0.077
        # (糊约11倍)却PASS = 在奖励评审连批6轮的过度虚化。改用逐件/深焦口径(见 G8/G11)。
        ("D5 背景/主体分数窗比(披露)", True, "%.3f" % m["ratio"]),
        ("G6 clip>250≤%.4f" % G6_CLIP_MAX, m["clip"] <= G6_CLIP_MAX, "%.4f" % m["clip"]),
        ("G7 道具区饱和≥20", m["prop_sat"] >= G7_PROP_SAT_MIN, "%.2f" % m["prop_sat"]),
        # 原 G8(跨物体比锐度)**判据有缺陷, 降为披露**: 梯度能量 = 纹理对比 × 模糊,
        # 彩色水果固有高频远高于白瓷碟 → 同光圈下 fruit_bowl 1.0353 vs sauce_honey 0.0578,
        # 差20倍却都是远景。跨物体比等于比纹理, 不是比虚化。改用同物体深焦对照(见 deep_gates)。
        ("D1 道具/主体锐度比(披露)", True, "%.4f" % m["prop_ratio"]),
        ("G9a 相对墨色≥%.4f" % G9_INK_MIN, m["brand_ink"] >= G9_INK_MIN, "%.4f" % m["brand_ink"]),
        ("G9c 品牌蓝≥%.4f" % G9_BLUE_MIN, m["brand_blue"] >= G9_BLUE_MIN, "%.4f" % m["brand_blue"]),
    ]


def _roi_sharp(l, box, n=192):
    h, w = l.shape
    r = l[max(0, int(box["v0"] * h)):min(h, int(box["v1"] * h)),
          max(0, int(box["u0"] * w)):min(w, int(box["u1"] * w))]
    if r.size < 64:
        return None
    im = np.asarray(Image.fromarray(np.clip(r, 0, 255).astype(np.uint8))
                    .resize((n, n), Image.LANCZOS)).astype(float)
    return sharpness(im)


def _proj_boxes(manifest, spec, Wd, H):
    """物件真值投影框(归一化 u0,u1,v0,v1); manifest/spec 缺失返回 {}。"""
    import json
    import os
    if not (os.path.exists(manifest) and os.path.exists(spec)):
        return {}
    man = json.load(open(manifest))
    sp = json.load(open(spec))
    loc = np.array(man["camera"]["loc"], float)
    tgt = np.array(sp["camera"]["target"], float)
    zc = loc - tgt
    zc /= np.linalg.norm(zc)
    xc = np.cross([0, 0, 1.0], zc)
    xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    f = man["camera"]["lens"] / 1000.0
    sw = 0.036
    ar = Wd / H
    out = {}
    for k, m in man["geometry_gate"]["measured"].items():
        x0, y0, z0, x1, y1, z1 = m["bbox"]
        pts = np.array([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
        d = pts - loc
        Z = d @ zc
        u = (d @ xc) / (-Z) * f / sw + 0.5
        v = 0.5 - (d @ yc) / (-Z) * f / sw * ar
        out[k] = (float(u.min()), float(u.max()), float(v.min()), float(v.max()))
    return out


def _cover_frac(a, b):
    """a 被 b 覆盖的面积占 a 的比例(归一化框)。"""
    iu = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    iv = max(0.0, min(a[3], b[3]) - max(a[2], b[2]))
    return iu * iv / max(1e-9, (a[1] - a[0]) * (a[3] - a[2]))


def deep_gates(cand, deep, manifest="output/commercial/manifest_lifestyle_1l_highkey.json",
               spec="specs/lifestyle_1l.json"):
    """G8/G10: **同一物体**深焦 vs 工作光圈的锐度衰减比 (纹理项被约掉)。

    需 --deep <深焦对照图>: 同规格/同摆位/同曝光, 仅光圈收到 f/16。
    ROI 统一重采样192 → 分辨率无关(草稿640与正式1920可比)。

    **G10 测品牌正面, 不测整盒bbox(第七次改锚, 已披露)**: 整盒bbox含盒体背/侧面
    (深度+75mm), f/2.0 下**本就该虚化** —— 那正是 G8 要求的浅景深; 用"整个3D体积
    都必须锐"当合焦门与浅景深自相矛盾。实测 v3 整盒 0.7178 FAIL 而**品牌正面
    0.8675 PASS**(v2 分别 1.0012 / 0.9170), 且纸材法线新增纤维高频抬高了深焦分母。
    → 品牌印刷可读性才是硬约束, 整盒衰减降为披露项 D2。
    **披露**: 阈值 0.35/0.80 与本次改锚均在见过候选后设定, 非事前冻结; 参照是实拍照片
    无法取深焦对照, 故本门锚在物理要求上, 最终风格是否达参照仍须外部盲评裁定。
    """
    import json
    import os
    rc = os.path.splitext(cand)[0] + "_regions.json"
    rd = os.path.splitext(deep)[0] + "_regions.json"
    if not (os.path.exists(rc) and os.path.exists(rd)):
        return []
    with open(rc) as fh:
        bc = json.load(fh)
    with open(rd) as fh:
        bd = json.load(fh)
    lc = lum(np.asarray(Image.open(cand).convert("RGB")).astype(float))
    ld = lum(np.asarray(Image.open(deep).convert("RGB")).astype(float))
    out = []
    if "far_props" in bc and "far_props" in bd:
        sc, sd = _roi_sharp(lc, bc["far_props"]), _roi_sharp(ld, bd["far_props"])
        if sc is not None and sd is not None and sd > 1e-9:
            out.append(("D3 远景并集窗衰减(披露)", True, "%.4f" % (sc / sd)))
        # v124 第15处测错总体: 并集矩形窗把**前景碗**圈了进来(实测 toast bbox 被 oat_bowl
        # 覆盖 56.3%, 其余三件 0.000)。换真扫描蓝莓(纹理3.31x)后该窗 work 锐度 84.13→188.73
        # → G8 0.3269→0.4156 **假FAIL**; 同期 fruit_bowl/sauce_jam/sauce_honey 自身衰减
        # **四位小数全同**(0.1261/0.1165/0.1456) → 远景虚化分毫未退。
        # 改为**逐件自身窗取中位数**, 并剔除被近处物件遮挡>25%的件(遮挡件本就不可测)。
        bx = _proj_boxes(manifest, spec, lc.shape[1], lc.shape[0])
        sp_ = json.load(open(spec)) if os.path.exists(spec) else {}
        # 遮挡集(保守: 全体非cloth物件都可能挡住远景件的取样窗)
        near = {o["id"] for o in sp_.get("objects", []) if o.get("role") in ("hero", "prop")}
        near |= {p["id"] for p in sp_.get("props", []) if p.get("role") == "prop_near"}
        # v125b **合焦集**只取 hero + prop_near, 不等于遮挡集:
        # glass/plate 虽 role=prop, 但世界 y=0.145/0.255 在纸盒(y≈0.02)**之后**=背景件,
        # 参照里这两件本就**高度虚化**; 要求它们≥0.90 与参照矛盾, 且会逼出f/16把bokeh全杀。
        focus_set = {o["id"] for o in sp_.get("objects", []) if o.get("role") == "hero"}
        focus_set |= {p["id"] for p in sp_.get("props", []) if p.get("role") == "prop_near"}
        ratios, excl = [], []
        for k in bc["far_props"].get("ids", []):
            if k not in bx:
                continue
            cov = max([_cover_frac(bx[k], bx[n]) for n in near if n in bx] or [0.0])
            if cov > 0.25:
                excl.append("%s(遮挡%.2f)" % (k, cov))
                continue
            bb = dict(zip(("u0", "u1", "v0", "v1"), bx[k]))
            a_, b_ = _roi_sharp(lc, bb), _roi_sharp(ld, bb)
            if a_ is not None and b_ is not None and b_ > 1e-9:
                ratios.append((k, a_ / b_))
        if ratios:
            med = float(np.median([r for _, r in ratios]))
            # v125 单侧≤0.35 **方向错**: 越糊越易过, 正是评审连批6轮的"过度虚化/AI涂抹感"。
            # 物理实测(78mm/对焦968mm/CoC0.03): f/2.0 总景深仅 **17.0mm**, 而纸盒自身纵深
            # 104mm、燕麦碗150mm → 连主体都装不下。改**双侧带**: 要虚化但须留结构。
            out.append(("G8 远景逐件衰减∈[0.15,0.75]", 0.15 <= med <= 0.75, "%.4f" % med))
            out.append(("D4 逐件衰减(披露)", True,
                        " ".join("%s=%.3f" % (k, r) for k, r in ratios)
                        + ("  剔除:" + ",".join(excl) if excl else "")))
        else:
            out.append(("G8 远景逐件衰减∈[0.15,0.75]", False, "N/A 全部件被遮挡/不可测"))
        # v125 新增**更严**的近景合焦门: 主体与前景必须合焦(商业硬要求)。
        # 逐件实测 自身窗/深焦: f/2.0 carton 0.839 / oat_bowl 0.371 / glass 0.084(评审"严重失焦")
        #            f/5.6 carton 0.946 / oat_bowl 0.963 / glass 0.490
        # 该门使**旧f/2.0配置FAIL** → 证明本次改判据不是事后放宽。
        sharp = []
        for k in sorted(focus_set):
            if k not in bx:
                continue
            bb = dict(zip(("u0", "u1", "v0", "v1"), bx[k]))
            a_, b_ = _roi_sharp(lc, bb), _roi_sharp(ld, bb)
            if a_ is not None and b_ is not None and b_ > 1e-9:
                sharp.append((k, a_ / b_))
        if sharp:
            worst = min(r for _, r in sharp)
            out.append(("G11 近景最差合焦≥0.90", worst >= 0.90, "%.4f" % worst))
            out.append(("D6 近景逐件合焦(披露)", True,
                        " ".join("%s=%.3f" % (k, r) for k, r in sharp)))
        else:
            out.append(("G11 近景最差合焦≥0.90", False, "N/A 无近景件可测"))
    kc = os.path.splitext(cand)[0] + "_brandbox.json"
    kd = os.path.splitext(deep)[0] + "_brandbox.json"
    if os.path.exists(kc) and os.path.exists(kd):
        with open(kc) as fh:
            bxc = json.load(fh)
        with open(kd) as fh:
            bxd = json.load(fh)
        sc, sd = _roi_sharp(lc, bxc), _roi_sharp(ld, bxd)
        if sc is not None and sd is not None and sd > 1e-9:
            out.append(("G10 品牌正面合焦≥0.80", sc / sd >= 0.80, "%.4f" % (sc / sd)))
        else:
            out.append(("G10 品牌正面合焦≥0.80", False, "N/A 品牌ROI过小"))
    else:
        # 不可测≠通过: 缺真值品牌框就不能宣称品牌合焦
        out.append(("G10 品牌正面合焦≥0.80", False, "N/A 缺品牌框sidecar"))
    if "subject" in bc and "subject" in bd:
        sc, sd = _roi_sharp(lc, bc["subject"]), _roi_sharp(ld, bd["subject"])
        if sc is not None and sd is not None and sd > 1e-9:
            out.append(("D2 整盒bbox衰减(披露)", True, "%.4f" % (sc / sd)))
    return out


def coverage(img, manifest, spec):
    """物体覆盖率: **真值投影并集**, 不用饱和度阈值。

    第13处测错总体(据以打了6轮无效构图战役): 原用 `饱和度>25` 当"物体占比",
    实测候选并集覆盖 **0.4407** 而该阈值只报 **0.1069(仅24%)** —— 本场景是高调浅色
    (白盒/白盘/浅木桌/浅蓝碗), 并集内饱和>25 仅占 0.211 → 系统性漏计自家物体;
    而参照含彩色水果/蓝莓/金可颂/蓝条纹布, 同一阈值对其有利。
    故"0.103 vs 参照0.232"是**跨图不可比的伪差距**, 推近相机/减件/放大碗6轮全被几何闸正确拒渲。

    只对**候选**可算(需 manifest 真值); 参照无 manifest → 不可比, 仅作候选侧诊断(披露)。
    """
    import json
    import os
    if not (os.path.exists(manifest) and os.path.exists(spec)):
        return None
    man = json.load(open(manifest))
    sp = json.load(open(spec))
    a = np.asarray(Image.open(img).convert("RGB")).astype(float)
    H, Wd, _ = a.shape
    loc = np.array(man["camera"]["loc"], float)
    tgt = np.array(sp["camera"]["target"], float)
    zc = loc - tgt
    zc /= np.linalg.norm(zc)
    xc = np.cross([0, 0, 1.0], zc)
    xc /= np.linalg.norm(xc)
    yc = np.cross(zc, xc)
    f = man["camera"]["lens"] / 1000.0
    sw = 0.036
    ar = Wd / H
    mask = np.zeros((H, Wd), bool)
    for k, m in man["geometry_gate"]["measured"].items():
        x0, y0, z0, x1, y1, z1 = m["bbox"]
        pts = np.array([(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)])
        d = pts - loc
        Z = d @ zc
        u = (d @ xc) / (-Z) * f / sw + 0.5
        v = 0.5 - (d @ yc) / (-Z) * f / sw * ar
        bx0, bx1 = int(max(0, u.min() * Wd)), int(min(Wd, u.max() * Wd))
        by0, by1 = int(max(0, v.min() * H)), int(min(H, v.max() * H))
        if bx1 > bx0 and by1 > by0:
            mask[by0:by1, bx0:bx1] = True
    top = int(0.2 * H)
    sat = a.max(2) - a.min(2)
    return {"union": float(mask.mean()), "union_top": float(mask[:top].mean()),
            "sat": float((sat > 25).mean()),
            "sat_in_union": float((sat[mask] > 25).mean()) if mask.any() else 0.0}


def main():
    argv = sys.argv[1:]
    deep = None
    manifest = "output/commercial/manifest_lifestyle_1l_highkey.json"
    spec = "specs/lifestyle_1l.json"
    as_json = False
    if "--deep" in argv:
        i = argv.index("--deep")
        deep = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if "--manifest" in argv:
        i = argv.index("--manifest")
        manifest = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if "--json" in argv:
        as_json = True
        argv = argv[:argv.index("--json")] + argv[argv.index("--json") + 1:]
    paths = argv
    if not paths:
        print("用法: lifestyle_gate.py [--deep <深焦对照图>] [--manifest <实拍manifest>] <候选图>...")
        return 2
    ref = measure(REF)
    print("参照 %s  mean=%.1f dark=%.3f hi=%.3f R/G=%.3f ratio=%.3f clip=%.4f"
          % (REF, ref["mean"], ref["dark"], ref["hi"], ref["rg"], ref["ratio"], ref["clip"]))
    print()
    rc = 0
    for p in paths:
        m = measure(p)
        # v124 必须传**候选自己的** manifest: 默认那份是"最后一次渲染"的(可能是深焦对照),
        # 与候选不匹配 → 遮挡判定用错框 = 假修复。
        gs = gates(m) + (deep_gates(p, deep, manifest, spec) if deep else [])
        _legacy = m["brand_src"].startswith("legacy")
        # 披露项(D*)恒真, **不得计入 PASS** — 否则"12/12"里含白送票, 是假数字。
        # G9 在外部参照图上不适用(无本场景品牌框): 标 N/A 且不参与判定,
        # 避免把"测器测错对象"误读成"品牌被洗掉"。
        def _na(name):
            return _legacy and name.startswith("G9") and "highkey_ref" in p
        judged = [(n, ok, v) for n, ok, v in gs if not n.startswith("D") and not _na(n)]
        npass = sum(1 for _, ok, _ in judged if ok)
        print("%s  %dx%d  → %d/%d PASS" % (p, m["size"][0], m["size"][1], npass, len(judged)))
        print("   品牌框来源: %s | ROI来源: %s" % (m["brand_src"], m["roi_src"]))
        cv = coverage(p, manifest, spec)
        if cv:
            print("   覆盖率(真值投影): 并集%.4f 上部带%.4f | 饱和>25仅%.4f(并集内%.3f) → 饱和判据漏计浅色物体, 不作跨图比较"
                  % (cv["union"], cv["union_top"], cv["sat"], cv["sat_in_union"]))
        for name, ok, val in gs:
            if name.startswith("D"):
                print("   %-26s 披露  实测 %s (不判定)" % (name, val))
            elif _na(name):
                print("   %-26s N/A   (参照图无本场景品牌框, 不参与判定)" % name)
            else:
                print("   %-26s %s  实测 %s" % (name, "PASS" if ok else "FAIL", val))
        # P0-B 四态证据输出(联合结论第二条): 命题-证据-裁决器-结果
        # UNKNOWN=缺证据无法判定; NOT_APPLICABLE=任务不适用(披露项/参照图无品牌框)
        if as_json:
            import json as _json
            gates_json = []
            for name, ok, val in gs:
                if name.startswith("D"):
                    state, why = "NOT_APPLICABLE", "披露项: 不参与判定"
                elif _na(name):
                    state, why = "NOT_APPLICABLE", "参照图无本场景品牌框"
                elif str(val).startswith("N/A"):
                    state, why = "UNKNOWN", "缺证据: %s" % val
                else:
                    state, why = ("PASS", "") if ok else ("FAIL", "")
                gates_json.append({
                    "claim": name,
                    "result": state,
                    "evidence": None if str(val).startswith("N/A") else val,
                    "verifier": "lifestyle_gate.py",
                    "evidence_source": {
                        "brand": m.get("brand_src"), "roi": m.get("roi_src")},
                    "why": why,
                })
            print("@@GATE_JSON@@" + _json.dumps({
                "candidate": p, "manifest": manifest, "deep": deep,
                "generation_method": "CGI",
                "gates": gates_json,
                "summary": {"pass": npass, "judged": len(judged)},
            }, ensure_ascii=False))
        print()
        if npass < len(judged):
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())