# 资产授权与署名 (交付层汇总)

本文件是**对外分享渲染成果时必须随附的署名清单**。CC-BY-4.0 要求 "Author must be
credited ... copy paste this credit wherever you share it" —— 署名只放在资产目录里
不够, 交付物(图/页/文档)对外发布时须带上本清单中对应的 credit line。

适用交付物:
- `output/commercial/repro_pour_1l_kv.png` (暗调倒奶 KV, 已冻结, md5 ff7c5891…)
- `output/commercial/repro_lifestyle_v11.png` (高调生活场景当前定稿, md5 5b6df698…)
  及其后续版本; 历史版 v8a/v9/v10 同属本分支, 署名义务相同。

---

## 1. 蓝莓 (真扫描) — CC-BY-4.0, **必须署名**

> This work is based on "A bowl of berries"
> (https://sketchfab.com/3d-models/a-bowl-of-berries-2e198e82d83d440e857d3a2251e767d8)
> by ¡Jacques (https://sketchfab.com/iJacques)
> licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

- 仓内原件: `assets/sf_models/berries/`(`license.txt` 载明 CC-BY-4.0, 商用允许)
- 提取件: `assets/models/blueberry/blueberry.blend`(仅取 Blueberry 一件,
  30172 verts / 53504 polys; 碗/草莓/黑莓**未使用**)
- 改动: 烘焙 matrix_world(原 glTF 父级缩放使 bbox≈1km) → 归一单位半径, zmin=0;
  贴图 pack 进 .blend。详见 `assets/models/blueberry/CREDITS.md`。
- 使用位置: 高调生活场景分支燕麦碗内 6 颗蓝莓(`specs/lifestyle_1l.json` →
  `props[oat_bowl].args.scan_berry=true`); **暗调 KV 不使用**。

## 2. 玻璃杯 — CC-BY-4.0, **必须署名**

> "Tall Drinking Glass" by AleixoAlonso (https://sketchfab.com/AleixoAlonso),
> licensed under CC-BY-4.0
> Source: https://sketchfab.com/3d-models/tall-drinking-glass-6e1168814f8d4c44b4a833f41093905a

- 仓内: `assets/models/glass_tall/`(`CREDITS.md` + `license.txt`)
- 使用位置: 两条交付分支都用(`34_commercial_repro.py import_glass_model()`)。
- 改动: Solidify 真实壁厚 2mm + 外壁径向软化时保壁厚(WALL_FIX), 见台账 v101。

## 3. 可颂 — 台账记载 PolyHaven CC0, **授权文件缺失(待补)**

- 仓内: `assets/models/croissant/`(仅 `croissant_4k.gltf` / `.bin` / `textures/`)
- 台账依据: `34_commercial_repro.py import_croissant()` docstring 记
  "PolyHaven croissant (CC0)"。CC0 无需署名。
- **已补齐(2026-11-13)**: `assets/models/croissant/CREDITS.md` 落凭据——
  来源页 https://polyhaven.com/a/croissant 在线快照明示 CC0, 作者 Dario Barresi/Greg Zaal。
  残留弱点: 副本与源站 4k glTF 未逐字节核对(无下载回执), 见该文件审计节。
- 使用位置: 两条交付分支的白瓷盘上。

## 4. 亚麻布纹贴图 — Pexels License

- 仓内: `assets/reference/cloth_linen.jpg`（本地保留, 不入公开仓）
- 台账依据: v102/R21 记 "Pexels 7794365 亚麻布纹 albedo+bump 同源"。
- Pexels License 允许免费商用, **不强制署名**(署名属善意致谢)。
- 使用位置: 高调分支条纹餐巾的底布 albedo+bump(`lifestyle_props.napkin()`);
  条纹本身为程序化 Wave 纹理, 非第三方素材。

---

## 非第三方资产(无署名义务)

- **品牌印刷贴图**(`assets/textures/*.png` 系列): 本仓程序化绘制/真照片
  像素提升产物。**品牌印刷属硬约束资产**, 全程未经生成式重绘(见台账三条 AI
  后期路线证伪记录)。示例 SKU 印刷均为演示配置; 如呈现真实品牌元素, 商标权利归相应权利人, 与素材授权是两件事。
- 纸盒几何(`pipelines/commercial/` 砖型资产)、白瓷盘/酱碟/吐司/燕麦粥体/玻璃水果碗
  (`lifestyle_props.py`)、桌面与背景(`lifestyle_scene.py`): 均为本仓程序化建模。


## 6. 运动鞋双源资产 (2026-11-18)
- **Brown Sneakers (Sketchfab 线)**: yanix, CC-BY 4.0 (assets/models/sneaker/SKETCHFAB_LICENSE.txt)
  https://sketchfab.com/3d-models/brown-sneakers-e6c51d2e77d945d1a0efbca530fb4b5b
  用途: 零售数字孪生非食品品类演示 (pipelines/bootstrap/35_sneaker_import.py 清洗导入: Emission重建/280mm定标/自动定向)
- **Sneaker TRELLIS 生成线**: assets/models/sneaker_trellis/sneaker_trellis.glb — TRELLIS.2 (Apple Silicon MPS 移植)
  单图输入: input_photo.jpg (Dreamstime 预览图, 来源/哈希见 PROVENANCE.json; 生成物为几何重建, 不构成原图再分发)

## 复核状态

- 蓝莓 / 玻璃杯: 授权原文在仓, credit line 已核对一致 → **可随交付发布**。
- 可颂: **授权凭据待补**(见第 3 项), 发布前须闭合。
- 布纹: Pexels 记载在台账, 无强制署名义务。
- 开源资产动物园 8 个模型: 许可为 CC-BY-4.0 (允许商用, 必须署名), 此前未列入本清单 →
  credit line 已补入 `NOTICE.md` 第 4 节, **发布前须随交付物附带**。
- `assets/models/sneaker_trellis/input_photo.jpg`: Dreamstime 图库预览图已随仓分发,
  免费下载通常仅限编辑用途 → **建议从仓库移除该 JPG** (保留 sha256 与来源 URL), 商用前补授权证明。

## 7. Strawberry (v137, in production)
- Source: Innerscene 3D Parts Library, "Strawberry" (https://www.innerscene.com/tools/library/3d-parts/strawberry-3ff8e17e)
- License: CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/) — snapshot: assets/models/strawberry/license_page.html
- Usage: oat bowl fruit (specs/lifestyle_1l.json oat_bowl.args.fruit="strawberry"); extracted via extract_scan_strawberry.py

## 8. 桌面纹理 (v141)
- **wood_table_worn** (diff/nor/rough, 2048²): Poly Haven, CC0. 下载于 2026-11-14.
  https://polyhaven.com/a/wood_table_worn — 白洗处理(sat .75 + 20%白 + BrightContrast)后作生活方式场景桌面。

## 9. HDRI 棚拍环境 (R18, 四阶段板与实拍同机位渲染)
- **studio_small_09** (2k HDR, 6.3MB): Poly Haven, CC0 1.0 (https://creativecommons.org/publicdomain/zero/1.0/)
- 下载于 2026-11-16, dl.polyhaven.org 直链; 文件 assets/hdri/studio_small_09_2k.hdr
- 用途: specs/pack_458.json match_view.rig 环境底光 (strength 0.05) + 包装四阶段板 ③④阶段

## 竞品基准参照 (R48)
- (内部风格参照, 不入公开仓)
- 框架对账(2026-11-17): vs实拍 SSIM 0.369/LPIPS 0.725/CLIP 0.871 — 我方同机位R47 SSIM 0.531-0.711/LPIPS 0.70/CLIP 0.847-0.871 全面≥竞品; logo边缘双方同级锐利(vision); 竞品优势=正面构图+提亮展示风格(已用hero_front_ortho对等产出)
