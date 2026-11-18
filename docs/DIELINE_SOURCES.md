# 公开刀版资源决策表（Gable-top 屋顶包）

> 2026-11-18 · 触发：用户判断「一定有公开数据」→ **核实为正确**，修正前轮「无公开等价」结论。
> 原始调研：`docs/reviews/gpt_dieline_public_resources_r3.md`（GPT 38704 字/50+检索）＋工程侧独立核查。
> 目标结构：利乐 Rex 式屋顶包（双坡+脊鳍热封），演示型 458mL=68.3×68.3×105.2mm。
> 用途：①结构交叉验证 ②空白盒型变体产能（SDG/多市场换印）③品牌通用资产。

## 一、结构分类纪律（防误判）

| 级 | 定义 | 判定要点 |
|---|---|---|
| A1 | 工业液体包装顶部结构（连续鳍片+封合区） | 描述含 fin/seal/ultrasonic，或官方手册 |
| A2 | gable 外观+机械锁底（非热封） | ECMA 75 系=机械闭合 |
| B | 手工纸艺 milk carton | Cricut/Silhouette 系 |
| C | 通用 gable gift box | 婚礼/糖果盒 |
| U | 结构证据不足 | 仅凭名称 |

**gable-top 是结构类别，Tetra Rex 是产品体系，aseptic 是工艺属性——三者不等号。**

## 二、资源决策表

| 资源 | 结构 | 许可（关键原文） | 裁决 |
|---|---|---|---|
| **DielineMaker** DM-GABLE-CRASH-01 | A1*（「fin that seals four boards thick」+液体灌装版同顶热封底） | ToS：导出文件可个人+商用；禁再分发模板本身；导出=Pro付费 | ✅ 立即采用·顶部鳍片结构参照 |
| **Box Blanks** GABLE/GABLE-AUTO/SNAP/SKILLET | A2 | FAQ：「Dielines generated on this site are yours to use, commercially or otherwise, with no attribution required」自研参数化非复制ECMA图纸；**GABLE 未 plate-check**；网页许可≠API许可 | ✅ 立即采用·空白变体产能（先结构核对） |
| **ECMA** A55.75.01.03/A60.75.00.03/A01.75/A10.75 | B（机械闭合） | 官方PDF公开可下载；「All rights reserved」禁复制出版物 | ✅ 结构分类参照；❌ 原图不入商业资产库 |
| **SIG Artwork Manual V7** | A1（官方：压力+超声封合/封口禁印区/Keyline） | 官方PDF免费公开 | ✅ 立即采用·工业封合证据基线 |
| **Elopak Design Guide** | A1（「grid 不允许修改」/顶鳍禁印原则） | 公开指南；生产 Keyline 需申请 | ✅ 同上 |
| **Tetra Pak Design Manual** | A1 | 需 My Tetra Pak 账户/申请 | ✅ 申请访问 |
| **Packmage B063**（牛奶盒/屋顶式/利乐包） | U→高潜力（官方描述「也称利乐包」） | 标题「免费下载」；部分盒型免费/部分禁导出；无独立商用许可原文 | ⏳ 授权确认后采用（申请空白DXF+书面商用权） |
| **Sketchfab cebbi Milk Carton** | A1外观（官方描述1L Tetra Rex 形状） | CC BY（署名保留） | ✅ 3D 外观对照（入 Blender 正交对比） |
| **Grab3D Milk Carton** | A2外观（螺旋盖装饰款） | CC0 | 辅助通用资产 |
| Pacdora（177 牛奶酸奶条目）/几何实验室（1839盒型）/Packdroid（ECMA 75系可浏览） | U | 许可未核 | 🔍 筛查候选，逐项核许可 |
| Cricut/Silhouette/So Fontsy | B | 个人/付费商用/禁原始文件分发 | ❌ 不入工业结构库 |
| Openclipart/Free3D/嘉立创/远鸿 | C/插画/Editorial Only | 各异 | ❌ 辅助素材 |

\* A1*＝顶部描述与目标相近，但公开模板底部仍为 Crash/Snap-lock，未经无菌灌装验证。

## 三、采纳：刀版三层分解（进 AUTOMATION_DESIGN 架构）

1. **Layer 1 Universal Gable Geometry**：四壁/双坡/端耳/纵缝/基础折叠 ← ECMA+BoxBlanks+DielineMaker
2. **Layer 2 Industrial Sealing System**：连续鳍片/热封超声封合/禁印区 ← SIG+Elopak+TetraPak 授权资料
3. **Layer 3 Market & Product Variant**：尺寸/板厚/容量/开口/Artwork ← 自有参数化+合法品牌素材

空白变体产能公式：`Gable Geometry Master + Industrial Sealing Profile + Size Variant + Artwork Variant`。禁止混合不同厂商封合结构冒充通用标准。

## 四、立即执行：结构验证包（第一轮）

用 68.3×68.3×105.2 参数化对照 4 资源：DielineMaker / BoxBlanks GABLE / ECMA A55.75 / Sketchfab Rex(署名)＋SIG/Elopak 公开手册。
核验维度：主体四壁+纵缝糊口/双坡角度+脊线/端耳折叠顺序/鳍片长度宽度层数/复合折线/底部封合/UV 禁印区/板厚补偿。
**原则：必须比 2D 展开拓扑+折叠运动，不能只比成型 3D 外观。**
产物：`Gable-top Reference Benchmark` 结构比对报告＋每资源 reference contract（GPT 12.2 契约格式）。

## 五、诚实边界

- 0 个「CC0 且可直接生产的 Tetra Rex 完整工业刀版」——公开生态是「生成器多、生产刀版数据缺」。
- 学术/开源渠道无满足条件的刀版数据集（GitHub/Kaggle/HF/Zenodo 已查，负面结果记录）。
- 无菌灌装=工艺属性，任何外观相似都不能推导工艺正确。
- 客户刀版授权与公开资源**互不相干**：结构相似≠授权解决。