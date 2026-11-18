# 数字孪生资产规范 (TWIN_ASSET_SPEC v1)

本项目的商品数字孪生资产**按公开规范方法**生产与验收，不靠个人经验调参。
规范来源（2026-11-08 学习核定）：

| 规范 | 版本/来源 | 管辖范围 |
|---|---|---|
| Khronos 3D Commerce《Real-time Asset Creation Guidelines》 | v1.0.0 (2020-10) | 几何/UV/材质/贴图/灯光/发布目标 |
| OpenUSD《Principles of Scalable Asset Structure》 | NVIDIA/AOUSD | 资产容器/层栈/入口/变体 |
| NVIDIA SimReady Specification | Omniverse SimReady (2026) | 语义/物理/传感器元数据能力 |

## 1. 坐标·尺度·原点 (Khronos §Coordinate)
- 建模单位 1 unit = 1 m；交付 glTF/USDZ 时 Y-up、+Z 朝前（USDZ 包装层 rotX(-90°)+scale(100) 已实现）。
- 资产中心底面置世界原点 (0,0,0)（`mesh.transform` 移 origin 已实现）。
- 真实尺度强制：标准利乐砖 48×44×136 mm、利乐钻/礼盒按实测 mm 值；禁止 size=1+scale 直觉给值（历史 bug #10）。

## 2. 几何 (Khronos §Geometry)
- 源资产与参照照片视觉一致；小表面细节进法线贴图而非几何。
- 四边面为主；bevel 修改器导出前必须三角化/四边形化清理 ngon（验收闸检查）。
- 无孔、无非流形、无重叠面；倒角做边缘过渡（bevel 0.5–0.9 mm 级）。
- 导出前重置 transform/修改器栈（`transform_apply(location=False, rotation=False, scale=True)` 纪律）。

## 3. UV (Khronos §UV)
- atlas 全 0-1、不重叠、少浪费；**区域间留 gutter ≥ 16 px**，且印刷元素距区域边界 ≥ gutter + 倒角采样宽（历史金楔 bug 的规范化解法）。
- 缝放自然断裂处（盒体八棱）；logo/书法等细节件可放大 UV 保分辨率。
- AO 需非平铺 UV（我们 atlas 即非平铺，满足）。

## 4. 材质·贴图 (Khronos §Materials/§Textures)
- Metallic-Roughness PBR；ORM 打包 (R=AO,G=Rough,B=Metal) 已实现。
- sRGB 仅 basecolor/emissive；ORM/normal 为 linear（Blender Non-Color 已实现）。
- 法线 OpenGL 切空间；2K；源贴图 PNG（已实现）。
- 材质数最小化；透明/不透明分网格分材质（alpha 交付单独文件已实现）。
- 纸型差异用参数表达：牛皮纸 rough≈0.84/coat≈0.02；淋膜白卡 coat≈0.30（GPT P1-4 口径）。

## 5. 灯光 (Khronos §Rendering)
- **导出资产不含任何灯光**；渲染用一致 IBL/棚拍 rig 做材质校验；白底平台地板中性且关 GI 反弹（防场景色洗）。

## 6. 发布目标 (Khronos §Publishing)
- 单资产 < 5 MB；≤ 100k tris；贴图 1K/2K；Source Asset 单一真源 → 按目标减面。
- 我们的 Source = 2048² 贴图 + bevel 源网格；GLB/USDZ 为发布目标。

## 7. 资产容器 (OpenUSD §Structure)
- 资产 = 命名 + 版本 + 结构化容器；工作流分层：`geometry.usda` / `material.usda` / `labels_<sku>.usda` 层栈。
- 根层 `defaultPrim` 入口；`kind = component`；轻量元数据 loft 到 payload 之上。
- SKU 变体用 **variantSets**（colorway/cap/label），禁止每 SKU 从零重建（当前违反，整改项 R1）。

## 8. SimReady 元数据 (NVIDIA SimReady)
- 语义：`sem:productCategory`, `sem:brand`, `sem:skuId`, `sem:barcode`。
- 物理：`phys:mass` (g), `phys:collisionProxy` (盒体包围盒), `phys:dimensions` (mm)。
- 传感器/渲染：`render:pbrWorkflow = metallicRoughness`, `render:textureSet = 2K`。
- 落地：usdz/glb 导出时写 custom extras / USD custom attributes（整改项 R2）。

## 9. 验收闸门 (本项目 ESR 纪律)
- 渲染级五闸 (`10_layout_qa_gate.py`)：text_obstruction / brand_readability / edge_cropping / stray_geometry / asset_identity。
- 资产级闸 (`12_asset_spec_gate.py`)：tri 数 / ngon / 流形 / 原点 / 单位 / 无灯光 / 贴图规格与色彩空间 / 材质数 / 文件大小 —— 对应本规范 §1-§6 条款逐条机器验收。
- 外部对抗评审 (GPT 同标尺) 只做视觉复刻度，不替代上述机器闸。

## 10. 整改账目 (2026-11-08)
- [x] R1 真 USD 化（§7/§8）：13_usd_asset.py 层栈 + defaultPrim/kind/variantSets + sem/phys 元数据，pxr 独立验证通过。
- [x] R2 atlas 规范（§3）：32px 岛间隙 + 零重叠 + 16px 边缘扩张；uv_atlas 闸机器验收。
- [x] 资产级闸（§9）：12_asset_spec_gate.py 五检全 PASS（3 SKU）。
- [ ] R3 10 SKU 家族迁移至同一层栈与闸。
- [ ] R4 retail semantics + physics 与场景实例状态分离。
- [ ] R5 SimReady Foundation profile 官方验证（不适用项公开）。
