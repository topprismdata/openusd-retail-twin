# Gable-top Reference Benchmark · 第一轮结构验证包

> 2026-11-18 · 目标：回答「公开资源哪部分可构成可复用结构母本，哪部分必须独立实现工业封合」。
> 方法：以演示型 458mL 参数化拓扑（`30_pack_asset_line.py:build_gable_top`，68.3×68.3×105.2mm）为被测件，
> 与四个公开资源做 2D 展开拓扑＋折叠运动逐维比对（不只比 3D 外观）。
> 资源决策总表见 `docs/DIELINE_SOURCES.md`；原始调研见 `docs/reviews/gpt_dieline_public_resources_r3.md`。
> 机器可读合同：`assets/reference/pack/gable_ref_contracts.json`。

## 一、证据采集实录（全部为当日实测，非转录）

| 资源 | 采集动作 | 证据 |
|---|---|---|
| SIG Artwork Manual V7 | 官方 PDF 直下 14.4MB（`api.sig.biz`），46 页全文检索＋6 关键页 110dpi 渲染 | `docs/pack/sig_ref_pages/sig_p{8,9,10,22,23,24}.png`；p8-10=cb/cf 版式结构图（顶前/顶后面板、纵缝、顶+底封口禁印区、耳片禁印区），p22=EDF 开启器禁印区定义（cb2/3/4/5/8/9） |
| DielineMaker DM-GABLE-CRASH-01 | 官方页面 HTML 全文挖取（297KB） | 折叠序列：「Crash-lock flap (back), Glued web, Crash-lock flap (front)」＋「Back roof, Top fin, Front roof, **Gable end, Gable fold-in** and 17 more」；FAQ：「fin that seals **four boards thick**…liquid fillers use a **heat-sealed blank with the same top**」；默认 70×70×195 |
| ECMA A55.75.01.03 | Packdroid 页面 SSR 文本（boxblanks ECMA 页为 SPA 无服务端文本） | 「long-seam glued carton…**1-2-3 snap-lock base**…gabled lid with a **claw lock** at the top」 |
| Grab3D Milk Carton | GLB 直下 372KB，glTF 头解析 | 2 mesh/2 材质，bbox 165×245×97mm（含螺旋盖）；CC0 页面声明已核入 `assets/models/gabletop_cc0/CREDITS.md` |
| 我方参数化 | `build_gable_top` 源码提取 | 四墙身＋前后坡面板(hr=13)＋山墙端三角(endL/endR)＋全长连续脊鳍(hf=14，前倾 20°，卷弧 r=2.5，半层距 1.5)；V_FOLD=0.725；脊沿 X；平底整体封闭 |

## 二、逐维比对表

| 维度 | 我方 68.3×68.3×105.2 | DM-GABLE-CRASH-01 | ECMA A55.75.01.03 | SIG cb/cf 版式 | Grab3D CC0 |
|---|---|---|---|---|---|
| 主体四壁＋纵缝 | ✓ 缝位=A条码墙(真品刀版定案) | ✓ 4 面板 | ✓ 纵缝糊接 | ✓ 纵缝标注在侧板 | ✓(近似) |
| 双坡屋顶 | ✓ hr=13 → 坡角 atan(13/34.15)=**20.9°** | ✓ Front/Back roof | ✓ gabled lid | ✓ top front/back 面板 | ✓ |
| 山墙端部 | **单三角面（简化）** | **Gable end＋Gable fold-in（塞入式）** | **爪锁 claw lock** | ear 禁印区（真耳片） | 单三角(近似) |
| 脊鳍 | ✓ 全长连续 hf=14，前倾 20°，卷边 r2.5 | ✓ fin 四层封合 | ✗ 无鳍（机械爪锁） | 顶封口禁印区即鳍封合位 | 卷边无独立鳍 |
| 底部 | 平底整体封闭（=热封底的 3D 近似） | crash/snap-lock（纸艺），**注明液灌=同顶热封底** | 1-2-3 snap-lock | 底封口禁印区 | 平底 |
| 禁印区概念 | 无独立概念（鳍面共用坡纹理，R41 定案） | — | — | **顶+底禁印区＋EDF 耳片禁印区（白）** | — |
| 参数化 | ✓ spec 驱动 | ✓ 尺寸可改，导出 Pro | ✓ 码系参数化 | 版式系列 cb1-cb9/cf2-cf9 | ✗ 固定模型 |

### 判定

1. **我方顶部拓扑与工业版式（SIG cb / DM 顶部）一致**：四壁＋双坡＋全长鳍。坡角 20.9° 与 SIG/Elopak 资料展示的常规坡度域相符（未获数值公差，判定=一致而非验证公差）。
2. **端部是唯一简化**：真品=多层折叠压合端（SIG ear、DM gable fold-in、ECMA claw lock 三方独立佐证），我方=单三角。影响域：展开刀版复现/端视特写；3D 正视外观已过实拍对齐＋GPT assembly PASS，**记为已知边界，非缺陷**。
3. **底部方向正确**：我方平底封闭=液灌热封底的合理近似；DM/ECMA 的锁底是纸艺替代，**不可反向套用**到液灌资产。
4. **DM 文档实证了三层分解**：同一顶部 fin（4 层）跨纸艺/液灌两用 → Layer1 顶几何通用成立；Layer2 封合必须分「纸艺锁底/工业热封」两条 profile。
5. **换印生成（SDG/多市场）需补禁印区纪律**：按 SIG p8-10/p22，顶+底封口禁印区＋耳片/开启器 EDF 禁印区。真品鳍面印「此处开启/需冷藏」=品牌方已合规裁切；自产 Artwork Variant 必须自留禁印边距。

## 三、资源采用裁决（第一轮验证后）

| 资源 | 裁决 | 依据 |
|---|---|---|
| DielineMaker DM-GABLE-CRASH-01 | ✅ **L1 拓扑交叉验证源**（折叠序列文字证据已采）；导出文件 Pro 付费，暂不购买 | 顶部四层鳍描述与我方一致；商用 ToS |
| boxblanks GABLE 系 | ✅ **空白变体产能源**；GABLE 未 plate-check → 每变体生成前过 2D 拓扑核对 | FAQ 商用免署名原文已核 |
| ECMA A55.75/A60.75 | ✅ 结构分类参照；❌ 原图不入商业资产库 | All rights reserved |
| SIG V7 手册 | ✅ **工业封合/禁印区证据基线**（本仓库已存关键页＋URL）；PDF 14.4MB 不入库只存引用 | 官方公开 |
| Grab3D CC0 | ✅ 已入库 `assets/models/gabletop_cc0/`（A2 外观参照，CC0 零义务） | glTF 实测 |
| Sketchfab cebbi CC BY | ⏳ 候选 3D 对照（下载需 OAuth，未取）；如取则署名随 CREDITS | 合同标注 |

## 四、结论（回答本轮问题）

- **可复用结构母本（Layer1）**：公开资源足以支撑——DM 顶部拓扑＋boxblanks 参数化生成＋ECMA 分类骨架。
- **必须独立实现（Layer2 工业封合）**：热封鳍四层结构、平底热封、禁印区工程化——公开生态只有描述与版式证据，无生产级刀版文件；我方参数化（hf/lean/roll/halfgap）即独立实现，已有实拍+刀版定案背书。
- **Layer3 市场变体**：只能来自合法品牌素材或自产 Artwork（守 SIG 禁印区）。

## 五、诚实边界

- 未做物理打样验证；「一致」= 拓扑/文献级一致，非尺寸公差验证。
- Sketchfab CC BY 模型未取得（OAuth 未配）。
- DM 2D 刀版文件未导出（Pro），flat_topology_verified=false——折叠序列来自官方页面文字，非图纸实测。
- Elopak grid「不允许修改」条款 → 其 grid 仅作参照，从未复制。