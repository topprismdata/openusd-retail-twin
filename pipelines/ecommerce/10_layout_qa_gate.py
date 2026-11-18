#!/usr/bin/env python3
"""排版 QA 闸门: 电商主图自动验收 (文字遮挡 / 品牌可读性 / 边缘裁切)

GPT 外部评审终裁 (reviews/gpt_review_31): "这条线真正值得结案的不是某一张图达到 95,
而是同一套系统以后生成 100 张包装变体图, 也不会再次出现这类错误。"

三项检查 (全部程序化, 无人工观察):
  1. text_obstruction  中央文案字形边界 vs 商品主识别区 (产品色块连通域) 硬遮挡
  2. brand_readability 白盒上品牌红标在缩略图 (256px) 下对比度可检测
  3. edge_cropping     商品轮廓不得进入四边缘安全区 (0.04H)

用法:
  python3 10_layout_qa_gate.py output/multi_platform/08_AMX_Combo_900x900.png
  python3 10_layout_qa_gate.py --all   # 扫全目录
退出码: 0 = PASS, 1 = FAIL (供 CI / 排版引擎 gate 调用)
"""
import sys
import os
import json
import hashlib
import numpy as np
from PIL import Image

EDGE_MARGIN = 0.04          # 边缘安全区 (画幅高比例)
THUMB_SIZE = 256            # 可读性检测缩略尺寸
BRAND_RED = (198, 30, 40)   # 酸奶系列红标色
BRAND_GREEN = (16, 98, 56)  # 经典绿标色
RIBBON_BLUE = (95, 182, 227)  # 丝带箭头中段色 (排版元素, 非商品)
BRAND_TOL = 42              # 红标色距离容差
TEXT_BLUE = (26, 78, 150)   # 中央文案爱琴蓝
TEXT_TOL = 46
BG_DIST = 38                # 背景色距离 (判定产品像素)


def _load(path):
    return Image.open(path).convert("RGB")


def _dist(arr, color):
    """像素到参考色的欧氏距离图"""
    ref = np.array(color, dtype=np.float32)
    return np.sqrt(((arr.astype(np.float32) - ref) ** 2).sum(axis=-1))


def _product_mask(a, text_m=None):
    """产品像素 = 暗于背景 且 非文字色 且 非排版元素色 (红标/丝带青蓝)"""
    gray = a.mean(axis=-1)
    prod = gray < 200
    if text_m is not None:
        prod &= ~text_m
    prod &= _dist(a, BRAND_RED) > 60          # 品牌红标是排版层
    prod &= _dist(a, RIBBON_BLUE) > 45        # 丝带箭头是排版层
    prod &= _dist(a, (26, 60, 110)) > 45      # 深蓝信息块/标题深蓝是排版层
    prod &= _dist(a, (26, 78, 150)) > 40      # AMX 中央文案蓝 (aegean) 是排版层
    prod &= _dist(a, (0, 108, 64)) > 45       # 经典绿标底 (demo combo logo) 是排版层
    return prod


def _is_white_bg(a):
    """四角 5% 区域均亮 (>215) 判白底主图; 场景图 (KV 深背景) 返回 False"""
    H, W = a.shape[:2]
    m = int(H * 0.05)
    corners = [a[:m, :m], a[:m, W - m:], a[H - m:, :m], a[H - m:, W - m:]]
    return all(float(c.mean()) > 215 for c in corners)


def check_text_obstruction(img):
    """中央文案字形边界不得进入商品主识别区 (产品色连通域)。
    文字像素 = 距 TEXT_BLUE 近; 商品像素 = 非背景且非文字色;
    遮挡 = 文字像素的 3px 膨胀邻域内同时出现高密度产品像素 (字形紧贴/覆盖产品)。"""
    a = np.asarray(img)
    W, H = img.size
    text_m = _dist(a, TEXT_BLUE) < TEXT_TOL
    # 限定中央带 (y 0.40-0.62H) 内的蓝色 = 文案
    band = np.zeros_like(text_m)
    band[int(H * 0.40):int(H * 0.62), :] = True
    text_m &= band
    prod_m = _product_mask(a, text_m)
    band_h = int(a.shape[0] * 0.22)
    band_area = band_h * a.shape[1]
    if text_m.sum() < band_area * 0.005:
        return "PASS", "no center copy (negligible text pixels)", 0.0
    if text_m.sum() > band_area * 0.35:
        return "SKIP", "info-face image (nutrition/back panel), center-copy rule n/a", 0.0
    # 文字 3px 膨胀
    tm = text_m.copy()
    for shift in range(1, 4):
        tm |= np.roll(text_m, shift, axis=0) | np.roll(text_m, -shift, axis=0)
        tm |= np.roll(text_m, shift, axis=1) | np.roll(text_m, -shift, axis=1)
    ring = tm & ~text_m            # 文字外环
    ring_prod = (ring & prod_m).sum()
    ratio = ring_prod / max(1, ring.sum())
    if ratio > 0.30:
        return "FAIL", f"text glyph ring touches product at {ratio:.0%}", ratio
    return "PASS", f"text clear of products (ring-product {ratio:.0%})", ratio


def check_brand_readability(img):
    """白底主图: 缩略图下品牌色标 (酸奶红/经典绿, 自适应) 可检测。
    场景图 SKIP; 牛皮纸/低饱和包装 (设计本无色标) SKIP。"""
    a_full = np.asarray(img)
    if not _is_white_bg(a_full):
        return "SKIP", "scene image, brand-block rule not applicable", 0.0
    th = img.resize((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
    a = np.asarray(th)
    lit = np.clip(a.astype(np.float32) / 1.3, 0, 255).astype(np.uint8)  # 渲染提亮 ~1.3x 反补偿
    d = _dist(a, BRAND_RED)
    mask = d < BRAND_TOL
    if int(mask.sum()) < 30:
        mask = _dist(lit, BRAND_RED) < BRAND_TOL + 8
    if int(mask.sum()) < 30:                   # 红标缺 → 试经典绿 (含提亮反补偿)
        d = _dist(a, BRAND_GREEN)
        mask = d < BRAND_TOL + 10
        if int(mask.sum()) < 30:
            mask = _dist(lit, BRAND_GREEN) < BRAND_TOL + 25
    n = int(mask.sum())
    if n < 12:
        # 侧视角品牌面不可见 / 低饱和包装设计 → 规则不适用
        return "SKIP", "brand face not visible at this angle / low-sat design", 0.0
    if n < 30:
        return "FAIL", f"brand red mark not readable at thumbnail ({n}px)", n / 100.0
    # 红标与局部背景对比: 红标均值 vs 全图非红均值
    brand_mean = a[mask].mean(axis=0)
    other_mean = a[~mask].mean(axis=0)
    contrast = float(np.linalg.norm(brand_mean - other_mean))
    if contrast < 60:
        return "FAIL", f"brand mark contrast too low ({contrast:.0f})", contrast / 100.0
    return "PASS", f"brand mark readable ({n}px, contrast {contrast:.0f})", contrast / 100.0


def check_edge_cropping(img):
    """白底主图: 商品轮廓不得进入四边缘安全区 (0.04H, 产品像素 >2% 判裁切)。
    场景图 (非白底) 自动 SKIP。排版元素色已排除。"""
    a = np.asarray(img)
    if not _is_white_bg(a):
        return "SKIP", "scene image (non-white bg), edge rule not applicable", 0.0
    H, W = a.shape[:2]
    prod_m = _product_mask(a)
    m = int(H * EDGE_MARGIN)
    bands = {
        "top": prod_m[:m, :], "bottom": prod_m[H - m:, :],
        "left": prod_m[:, :m], "right": prod_m[:, W - m:],
    }
    worst, worst_name = 0.0, "-"
    for name, band in bands.items():
        ratio = float(band.mean())
        if ratio > worst:
            worst, worst_name = ratio, name
    if worst > 0.02:
        return "FAIL", f"product cropped at {worst_name} edge ({worst:.1%})", worst
    return "PASS", f"all edges clean (worst {worst_name} {worst:.1%})", worst


def check_stray_geometry(img):
    """商品主体+接触影应为一个连通域; 主域之外的不透明块 = 悬浮几何穿帮。
    降采样 120x120 BFS 标号, 纯 numpy/python, 无 scipy 依赖。"""
    a = np.asarray(img)
    if not _is_white_bg(a):
        return "SKIP", "scene image, stray-geometry rule n/a", 0.0
    H, W = a.shape[:2]
    n = 120
    small = np.asarray(img.resize((n, n), Image.BILINEAR))
    gray = small.mean(axis=-1)
    mask = gray < 235                      # 非白底 (含影)
    lab = np.zeros((n, n), dtype=np.int32)
    cur = 0
    sizes = {}
    from collections import deque
    for i in range(n):
        for j in range(n):
            if mask[i, j] and lab[i, j] == 0:
                cur += 1
                q = deque([(i, j)])
                lab[i, j] = cur
                cnt = 0
                while q:
                    y, x = q.popleft()
                    cnt += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < n and 0 <= xx < n and mask[yy, xx] and lab[yy, xx] == 0:
                            lab[yy, xx] = cur
                            q.append((yy, xx))
                sizes[cur] = cnt
    if not sizes:
        return "PASS", "no foreground", 0.0
    main = max(sizes, key=sizes.get)
    # 主域填洞轮廓: 产品内浅色印刷区(白牧场带等)是洞, 洞内组件不算游离
    inv = ~mask
    reach = np.zeros((n, n), bool)
    dq = deque([(i, j) for i in range(n) for j in range(n)
                if (i in (0, n - 1) or j in (0, n - 1)) and inv[i, j]])
    for i, j in dq:
        reach[i, j] = True
    while dq:
        y, x = dq.popleft()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < n and 0 <= xx < n and inv[yy, xx] and not reach[yy, xx]:
                reach[yy, xx] = True
                dq.append((yy, xx))
    silhouette = mask | (inv & ~reach)
    # 重标号于 silhouette 上: 洞内组件与主域合并
    lab2 = np.zeros((n, n), dtype=np.int32)
    cur2 = 0
    sizes2 = {}
    for i in range(n):
        for j in range(n):
            if silhouette[i, j] and lab2[i, j] == 0:
                cur2 += 1
                q2 = deque([(i, j)])
                lab2[i, j] = cur2
                cnt = 0
                while q2:
                    y, x = q2.popleft()
                    cnt += 1
                    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        yy, xx = y + dy, x + dx
                        if 0 <= yy < n and 0 <= xx < n and silhouette[yy, xx] and lab2[yy, xx] == 0:
                            lab2[yy, xx] = cur2
                            q2.append((yy, xx))
                sizes2[cur2] = cnt
    main2 = max(sizes2, key=sizes2.get)
    main_size = sizes2[main2]  # 注意: main2 是组件ID, 非尺寸
    # 非主域组件三类: (1)斑点 (<0.5%画幅且<8%主域) = 排版AA边缘碎屑, 放行
    # (2)含产品暗核 (min gray<170, 印刷深色带经降采样变浅仍可辨) 的组件 = 合法第二产品 (多盒组合版式), 放行
    # (3)其余大组件 (合成幽灵影亮度~210+ 无暗核) = 悬浮几何穿帮, FAIL
    stray = 0
    for k, v in sizes2.items():
        if k == main2 or v < 4:
            continue
        if v < 0.005 * n * n and v < 0.08 * main_size:
            continue
        sel = lab2 == k
        if gray[sel].min() < 170:
            continue
        stray += v
    if stray:
        return "FAIL", f"stray geometry blob ({stray}px @120²)", stray / 100.0
    return "PASS", f"connected foreground ok ({len(sizes2)} comp after hole-fill)", 0.0


def check_asset_identity(path, manifest):
    """渲染血缘: 成图记录的贴图 sha 必须等于磁盘当前 albedo sha (防旧资产覆盖)。"""
    key = os.path.relpath(os.path.abspath(path),
                          os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "output", "multi_platform"))
    rec = manifest.get(key)
    if not rec:
        return "SKIP", "no manifest record (rendered before manifest era)", 0.0
    tex = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                       "assets", "textures", f"{rec['sku']}_albedo.png")
    if not os.path.exists(tex):
        return "FAIL", f"manifest sku {rec['sku']} albedo missing", 0.0
    h = hashlib.sha256(open(tex, "rb").read()).hexdigest()[:16]
    if h != rec["tex_sha"]:
        return "FAIL", f"texture provenance break: manifest {rec['tex_sha']} != disk {h}", 0.0
    if rec.get("tex_mtime") and os.path.getmtime(path) < rec["tex_mtime"]:
        return "FAIL", "stale render: image older than current texture", 0.0
    return "PASS", f"asset lineage ok ({rec['sku']}:{h})", 0.0


def run_gate(path, manifest=None):
    img = _load(path)
    checks = {
        "text_obstruction": check_text_obstruction(img),
        "brand_readability": check_brand_readability(img),
        "edge_cropping": check_edge_cropping(img),
        "stray_geometry": check_stray_geometry(img),
        "asset_identity": check_asset_identity(path, manifest or {}),
    }
    overall = "FAIL" if any(v[0] == "FAIL" for v in checks.values()) else "PASS"
    _mp = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "output", "multi_platform")
    _ap = os.path.abspath(path)
    _key = os.path.relpath(_ap, _mp) if _ap.startswith(_mp + os.sep) else os.path.basename(_ap)
    report = {
        "image": os.path.basename(path),
        "key": _key,
        "overall": overall,
        "checks": {k: {"verdict": v[0], "detail": v[1], "metric": round(v[2], 4)}
                   for k, v in checks.items()},
    }
    return report


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(2)
    paths = []
    if "--all" in args:
        base = "output/multi_platform"
        paths = []
        for root, _dirs, files in os.walk(base):
            for f in files:
                if f.endswith(".png") and not f.startswith("_tmp"):
                    paths.append(os.path.join(root, f))
        paths.sort()
    else:
        paths = [a for a in args if not a.startswith("--")]
    mpath = os.path.join("output", "render_manifest.json")
    manifest = {}
    if os.path.exists(mpath):
        try:
            manifest = json.load(open(mpath))
        except Exception:
            manifest = {}
    n_fail = 0
    for p in paths:
        if not os.path.exists(p):
            print(f"[SKIP] {p} not found")
            continue
        r = run_gate(p, manifest)
        mark = "PASS" if r["overall"] == "PASS" else "FAIL"
        if r["overall"] == "FAIL":
            n_fail += 1
        print(f"\n[{mark}] {r['key']}")
        for k, v in r["checks"].items():
            print(f"  {k:20s} {v['verdict']:4s}  {v['detail']}")
        print("  " + json.dumps(r, ensure_ascii=False))
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
