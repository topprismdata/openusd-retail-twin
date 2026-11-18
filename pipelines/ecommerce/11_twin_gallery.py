#!/usr/bin/env python3
"""数字孪生多产品画廊页生成器: 单文件自包含 HTML, 一屏陈列全 SKU 家族 3D 孪生。

每款产品一个 model-viewer 卡片 (GLB base64 内嵌, 自动旋转+轨道控制+AR),
卡片附 ESR 溯源 (glb 哈希 + albedo 哈希)。GLB 缺失时自动调 01 导出。

用法:
  python3 11_twin_gallery.py            # 导出缺失 GLB + 重建 output/twin_3d_viewer.html
  python3 11_twin_gallery.py --no-export  # 仅用已有 GLB 重建 (缺失跳过)
"""
import base64
import hashlib
import importlib.util as ilu
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
AR_DIR = os.path.join(BASE, "output", "ar_models")
TEX_DIR = os.path.join(BASE, "assets", "textures")
OUT_HTML = os.path.join(BASE, "output", "twin_3d_viewer.html")
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"

_spec = ilu.spec_from_file_location("boot", os.path.join(BASE, "pipelines/bootstrap/00_bootstrap_textures.py"))
_boot = ilu.module_from_spec(_spec)
_spec.loader.exec_module(_boot)
PROFILES = _boot.SKU_PROFILES

# 画廊陈列顺序: 牛奶家族 10 + 酸奶 3
GALLERY = ["demo_classic", "demo_organic", "demo_jersey", "demo_cny", "demo_a2",
           "demo_lowfat", "demo_dream38", "demo_dream40", "demo_skim",
           "demo_meadow", "demo_yogurt_original", "demo_yogurt_gold", "demo_yogurt_gift"]

REF = {
    "demo_classic": "电商在售主图",
    "demo_organic": "白底商品图 ref1",
    "demo_yogurt_original": "电商在售组合主图",
}


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def ensure_glb(sku):
    glb = os.path.join(AR_DIR, f"retail_{sku}.glb")
    if os.path.exists(glb):
        return glb
    if "--no-export" in sys.argv:
        return None
    r = subprocess.run([BLENDER, "-b", "-P", os.path.join(BASE, "pipelines/ecommerce/01_comfy_usd_compositor.py"),
                        "--", "--sku", sku, "--scene", "grassland", "--export-glb", glb],
                       capture_output=True, text=True, timeout=900)
    if not os.path.exists(glb):
        print(f"[WARN] {sku} GLB 导出失败: {r.stderr[-300:]}")
        return None
    print(f"[GLB] {sku} exported")
    return glb


HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>零售商品数字孪生家族 · 多产品画廊</title>
<script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/3.5.0/model-viewer.min.js"></script>
<style>
  :root { --bg:#0e1512; --card:#16211c; --line:#232c27; --fg:#e8efe9; --mut:#8fa398; --acc:#2a8866; }
  * { box-sizing:border-box; margin:0; }
  body { background:var(--bg); color:var(--fg); font:14px/1.5 -apple-system,"PingFang SC",sans-serif; padding:20px; }
  header { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom:6px; }
  h1 { font-size:22px; font-weight:600; }
  .sub { color:var(--mut); }
  .badge { background:var(--acc); color:#fff; border-radius:999px; padding:2px 10px; font-size:12px; }
  .toolbar { margin:10px 0 16px; display:flex; gap:8px; }
  .toolbar button { background:var(--card); color:var(--fg); border:1px solid var(--line); border-radius:8px; padding:6px 14px; cursor:pointer; }
  .toolbar button.on { border-color:var(--acc); color:var(--acc); }
  #grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(240px,1fr)); gap:16px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden; }
  .card model-viewer { width:100%; height:260px; --poster-color:transparent; background:transparent; }
  .meta { padding:10px 12px 12px; border-top:1px solid var(--line); }
  .meta b { display:block; font-size:15px; }
  .meta .sp { display:block; color:var(--mut); font-size:12px; margin:2px 0 6px; }
  .meta .hash { display:block; color:var(--mut); font-size:11px; font-family:ui-monospace,monospace; }
  .meta .ref { color:var(--acc); font-size:11px; }
  footer { margin-top:22px; color:var(--mut); font-size:12px; max-width:900px; }
</style>
</head>
<body>
<header>
  <h1>零售商品数字孪生家族</h1>
  <span class="sub">__COUNT__ 款 SKU · OpenUSD 母本 · 模型即所渲</span>
  <span class="badge">ESR 证据链 ✓</span>
</header>
<div class="toolbar">
  <button id="spin" class="on" onclick="togglespin(this)">自动旋转</button>
  <button onclick="zoomall(0.62)">拉近</button>
  <button onclick="zoomall(0.9)">复位</button>
</div>
<div id="grid"></div>
<footer>
  ESR = Evidence-Simulation-Ready：每款孪生的几何/贴图/渲染共用同一资产管线；卡片哈希为 GLB 与 albedo 贴图 sha256 前 16 位，可回溯到生成脚本与参照真值。iOS Safari 点卡片内「AR」可 Quick Look 置于桌面。<br>
  渲染：Blender 5.2 headless Cycles Metal-RT · 交付：OpenUSD (.usdz/.glb) · 查看：model-viewer。
</footer>
<script>
const PRODUCTS = __PRODUCTS__;
const grid = document.getElementById('grid');
for (const [key, p] of Object.entries(PRODUCTS)) {
  const card = document.createElement('div');
  card.className = 'card';
  const arAttr = p.usdz ? `ar ar-modes="webxr scene-viewer quick-look" ar-scale="fixed" ios-src="${p.usdz}"` : '';
  card.innerHTML = `
    <model-viewer camera-controls autoplay shadow-intensity="1" exposure="1.05"
      environment-image="neutral" interaction-prompt="none" ${arAttr}
      alt="${p.title} 数字孪生模型"></model-viewer>
    <div class="meta">
      <b>${p.title}</b>
      <span class="sp">${p.subtitle}</span>
      <span class="hash">glb:${p.glb_hash} · albedo:${p.tex_hash}</span>
      ${p.ref ? `<span class="ref">真值 ${p.ref}</span>` : ''}
    </div>`;
  grid.appendChild(card);
  const mv = card.querySelector('model-viewer');
  const bin = Uint8Array.from(atob(p.b64), c => c.charCodeAt(0));
  mv.src = URL.createObjectURL(new Blob([bin], { type: 'model/gltf-binary' }));
  mv.cameraOrbit = '25deg 78deg 0.5m';
  mv.rotationPerSecond = '14deg';
}
function togglespin(btn) {
  btn.classList.toggle('on');
  const on = btn.classList.contains('on');
  document.querySelectorAll('model-viewer').forEach(m => m.rotationPerSecond = on ? '14deg' : '0deg');
}
function zoomall(d) {
  document.querySelectorAll('model-viewer').forEach(m => m.cameraOrbit = `25deg 78deg ${d}m`);
}
</script>
</body>
</html>
"""


def main():
    products = {}
    for sku in GALLERY:
        glb = ensure_glb(sku)
        if not glb:
            continue
        prof = PROFILES[sku]
        tex = os.path.join(TEX_DIR, f"{sku}_albedo.png")
        usdz = os.path.join(AR_DIR, f"retail_{sku}.usdz")
        products[sku] = {
            "title": prof.get("title", sku),
            "subtitle": prof.get("subtitle", ""),
            "b64": base64.b64encode(open(glb, "rb").read()).decode(),
            "glb_hash": sha16(glb),
            "tex_hash": sha16(tex) if os.path.exists(tex) else "-",
            "usdz": f"ar_models/retail_{sku}.usdz" if os.path.exists(usdz) else "",
            "ref": REF.get(sku, ""),
        }
        print(f"[card] {sku}: glb={products[sku]['glb_hash']} tex={products[sku]['tex_hash']}")
    html = HTML_HEAD.replace("__COUNT__", str(len(products)))
    # 逐款注入 (避免单条超大 JSON 行)
    import json
    html = html.replace("__PRODUCTS__", json.dumps(products, ensure_ascii=False))
    open(OUT_HTML, "w").write(html)
    print(f"[OK] {OUT_HTML} ({os.path.getsize(OUT_HTML)/1e6:.2f} MB, {len(products)} products)")


if __name__ == "__main__":
    main()
