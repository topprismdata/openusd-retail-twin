# USDCraft 思路研究 — NVIDIA LLM 写资产程序 → SimReady USD (2026-11-25)

> 研究对象: nvidia/USDCraft-10K 数据集 (Apache-2.0) + NVlabs/USDCraft 代码仓 (Apache-2.0) +
> arXiv 2610.11322。本地: `~/usdcraft_study/{dataset,code}`。验证 harness: `scripts/usdcraft_gate.py`。
> 北极星关联: ESR (Evidence-Simulation-Ready) 框架 — 见 photo-dieline `docs/esr/ESR-measurement-v0.1.md`。

## 〇、论文精读补正 (2026-11-25 二次修订; 首版仅凭摘要+代码仓, 本节以正文+附录 A–G 为准)

**成本实测 (附录 D.7, 替代首版瞎估)**: 单件 API 成本 USDCraft–Astra **$0.851** (560K input tokens,
缓存重), Sol $0.97, Claude Opus 5 $4.51, Gemini 3.8 Flash $0.86。10K ≈ **$8.5K** (Astra)。
时间: 生成中位 4.9 min (Astra), 重建 4.2 min, 源分析+复检加价 1–2 min — 首版"5–10 分钟"正确。

**作者模型矛盾 (卡 vs 论文, 如实记录)**: HF 卡称数据集用 DeepSeek-V4.1-Flash 写;
论文 §4.5 称 10k "produced entirely with USDCraft–Astra" (GPT-6 Astra low)。
两处必有一处过时/不实 — 引用时注明出处分歧。

**评测口径 = 无量纲相似度, 非计量学 (首版推断获正文证实)**: 附录 C.1 — 预测与参照各自
中心化+归一化到单位最长边后比较 (gIoU/Chamfer 均在 normalized coordinates); 距离误差
AE/LE 也是归一化坐标。**全文无 mm 级计量口径, 无不确定度, 无参考测量链** — ESR 楔子成立。

**绝对尺度的证据地位 (附录 A.3, ESR 楔子的最硬实证)**: 疑似单位归一化网格的物理尺度来自
**图像估计的"尺度假设", 建模期间冻结**; D.6 参照系评测显示该误差被保留 (USDCraft 影响小,
纯图像法崩盘)。即: 他们的绝对尺度 = 未验证假设传播进资产, 无卡尺/无 u_ref/无对账门。
论文原话纪律: "Distinguish measured dimensions from hypotheses; missing surfaces do not
establish empty space" (G.1 prompt) — 认识论与我们同源, 但**只到声明级, 未到测量级**。

**10K 本身无逐件质量审计 (重要诚实点)**: 论文严格评测 (USDCraft-bench 60+40 件, 48 类;
Lightwheel 243 件) 只覆盖 ~百件级; 10K 库发布的是**生成时机械检查 + SimReady 结构合规**,
无逐件几何证据审计。我们的反超轴: 确定性门链可以对**全部** 10K 逐件出 mm 级闭合/尺寸
对账/物理推导证据 — 质量覆盖本身就是差异化。

**消融验证架构选择 (Table 6/7)**: 作者 harness 贡献最大增益 (SDK 关节定义 vs 裸 USD 坐标),
**工具支持比骨干模型更重要** (USDCraft–Sol 全指标胜 Mini Workflow–Astra);
**独立观察 agent 使全部指标下降** (Table 7) — 单循环作者优于分离批评者, 与我们
"家族级单作者 + 确定性门禁"架构互证。

**可学走的三件**:
1. **b/e_profile 残差分解** (式 2): median 偏移 vs Q0.9 形状残差区分"错位"vs"变形" —
   两个修复动作不同。我们门禁是精确闭合不需拟合, 但 TDE 缺陷诊断可借此二分法;
2. **观测面 vs 未知空间**的轴向编码 (192 格细分, 32/24/16 切片文本预算) — R05 形变实物
   测量中"可靠观测 vs 假设补全"的表述可直接借用;
3. **G.2 baseline prompt 里的 PhysX/Newton 物理创作条款** (重力保持分析/关节阻力三态/
   摩擦静态≥动态/验证 json 契约) — 我们 USD 物理层 (P0-①) 的条款清单直接抄结构。

**论文自报局限**: 细网格 (球拍线/购物车钢丝) 重建失真; 柔性件仅静态标注态 (Isaac 未验证
柔性动力学)。零售包装不在其失败集也不在其覆盖集。

## 〇b、代码精读补正 (2026-11-25 三次修订)

诚实覆盖度: 已读 architecture.md/AGENTS.md/EVIDENCE.md/policy.py/_usd_validate.py(核心段)/
hinges.py; **未读** axial.py (1987 行)、observation.py (1341)、geometry_qc.py (1732)、
compile/storage/viewer 全部、_mesh/ 27 文件大部 — 下述结论仅覆盖已读部分。

1. **policy.py = 教义即代码范本**: 物理创作纪律是一段带 `__PRODUCT__` 槽位的字符串模板渲染进
   两产品 Author 任务 (漂移不可能)。内容深到: 接触摩擦系数表按材质 (metal .25/.18, painted
   .40/.30, rubber .90/.70, static≥dynamic≥0)、质量推导纪律 (`estimate_mass_from_density` +
   fill_fraction, **area×thickness×density 论证式** — 与我们纸板克重物理同款, 直接引用其表述)、
   重力保持力臂公式逐项写出 (axis_world·((COM−joint)×(m·g)))、惯量比 100:1 筛选明确标注
   "untested, not an NVIDIA threshold"、弧度合同、PhysX/Newton 摩擦模型非等价声明。
   **采纳**: pack-zoo 契约的门禁纪律渲染成同样的一份 policy 文本进生成管线。
2. **EVIDENCE.md = 开源最严证据权威矩阵**: 八通道正/负权威表 (语义图像不给度量、源渲染不能
   变第二语义图、候选渲染无回溯权威); 表面即证据模型 (非表面一律 UNKNOWN, 闭壳内部≠实体);
   AXIAL 字节预算 (32KiB 核心/56KiB 熔断 — "runaway fuse 不是截断触发器, 放不进就大声失败");
   FACE_FEATURES 物理阈值 (pitch=max(2mm, 延展/400), 凸起 8–120mm/≥3mm 高); "readings 永远
   不是 discrepancies"; recall 是参考线不是目标; 每次检查记源/候选哈希并标 current/stale/
   unverified (只述绑定不述质量)。全部是**结构证据** — 仍无计量/不确定度, 楔子再证。
3. **_usd_validate.py 实现质量 (生产级)**: /Asset 须带 Physics 变体集 {none, physics, physx,
   newton} 且默认 physx, 逐变体验组合/有限值/物理图; 有限值走查带环保护 (id set)、TimeCode
   解包、Vt/Gf 数组向量化 + 逐元素错误定位 "[i][j]"; 依赖闭包用 ComputeAllDependencies;
   flattened 入口禁保留组合弧。**我们 usdcraft_gate.py 是子集复刻** — 真合规直接跑他们的验证器
   (已验证可跑通我们资产), P0-① 同时补 Physics 变体集接口。
4. **hinges.py 源自 Articraft (Apache-2.0 署名保留)** — 论文基线之一与其 SDK 有代码血缘;
   SDK 原语 = CadQuery 可组合领域件 (桶铰/钢琴铰带孔位 pattern), 我们同类物 = 模板家族,
   抽象层级一致。

**对 P0 的三处修订**: ① 真合规用他们验证器而非自刻; ② /Asset 除 defaultPrim 外补 Physics
变体集; ③ 质量推导措辞照引 "area×thickness×density + fill_fraction 论证" 进我们的
纸板物理 (克重表 × 展开面积), 来源注释强制。

## 一、他们是什么 (2026-10-08 发布)

LLM 写 Python 资产程序 (`model.py`, 基于自带几何 SDK: CADQuery 辅助/铰链/扫掠/壳体库) →
编译为 USD/URDF/USDZ + PhysX/Newton 物理 → agent 对照渲染与几何测量自检修复 → SimReady 包。
两模式: **Generation** (文/图→新资产) 与 **Reconstruction** (扫描网格+一张实物照→带关节资产)。
10K 资产 (8222 关节 + 1778 刚体) / 1000 类, Z-up 米/kg, Isaac Sim 免调加载; 数据集用
DeepSeek-V4.1-Flash 写, 代码仓默认 GPT-6 Astra low effort (与论文 §4.5 矛盾, 见 §〇)。

## 二、可学的思路 (架构文档逐条提炼)

1. **语义质量指令先行, 无语义评审**: 语义/功能质量由 Author (LLM) 在 `model.py` 可编辑期用
   焦点测试+诊断修复; **刻意拒绝**第二评审员/评分/最佳候选选择器/多 agent 审批层。
2. **Host 门窄且机械可复现 (fail-closed)**: 可执行可导出源/schema 结构/数值有限性/必需文件/
   依赖闭包/哈希/规范绑定。新 blocker 必须落在这个边界内。
3. **门禁证据诚实性 (关键, 与 ESR 同认识论)**: "静态检查只建立它们实际测量的证据;
   不建立 Isaac Sim 导入、运行时启动、求解器稳定性"。候选渲染是**输出反馈, 不是目标证据**。
4. **Reconstruction 证据契约**: 源网格=度量权威 (它可靠解析的属性); 图像固定身份/形态/姿态类;
   未解析的度量属性=**受限假设 (constrained hypotheses)**; 任何 agent 动作前做原子输入快照
   (哈希清单); Generation 的单图尺寸估计明确标注为 Author 假设而非源测量。
5. **产品分离**: Generation 与 Reconstruction 的请求语义/图像角色/证据权威不合并; Edit 不实现。
6. **单一策略源**: 物理创作政策 (柔性件规则/质量/材料/接触/关节限位/弧度) 是一份文本
   (`pipeline/policy.py`) 渲染进两个产品的 Author 任务。
7. **机器自有清单**: SDK 文档是 Author 机器清单的一部分 (`sdk/_profiles.py` 所有), 仓库散文
   改动不改变 Author 行为。

## 三、实测证据 (梅森罐 R040_01 解剖)

- **三方对账通**: prompt "9×9×15cm" = `model.json.asset_extents [0.09,0.09,0.15]` =
  pxr 实测 bbox [0.09,0.09,0.15] — "geometrically grounded" 在此件上数值成立。
- 质量 3 刚体可加和 (0.2863+0.0290+0.0218 = 0.3371kg = 侧车 mass) ✓
- 交互标注: customData["usdcraft"].features 每部件带 graspable/function/prim 路径/面数。
- 包完整性: packaging.json 含 content_hash/package_hash + 三个 .metadata 哈希;
  conformance 记录 = 特征制 (FET_030/031/032/033_STANDARD, 版本+passed+failing_requirements+依赖)。
- 验证器命名检查清单 (`_usd_validate.py`): stage_open / default_prim=/Asset / z_up / meters /
  kilograms / reusable_asset_no_scene / finite_authored_values / dependencies_resolved /
  relative_asset_paths / vendor_namespace_isolation / physics_graph_acyclic /
  joint_parent_child_order / articulation_root_coverage / articulation_root_body_binding /
  physx|newton_schema_consistency / mass_inertia_or_collision_derivation /
  collider_dimensions / collider_scale。

## 四、我们的缺口清单 (`scripts/usdcraft_gate.py` 实测 4 件)

| 检查 | geometry.usdc ×2 | giftbox | ar usdz |
|---|---|---|---|
| 结构 9 项 (单位/有限值/依赖/无场景…) | PASS | PASS | PASS |
| **default_prim = /Asset** | **FAIL** | **FAIL** | **FAIL** |
| 物理 (joints/rigid/mass) | 全空 | 全空 | 全空 |

- 结构层唯一硬缺口: default prim 未设 `/Asset` (导出时加一行)。
- **证据缺口实例 (ESR 价值证明)**: `output/usd/*/geometry.usdc` 实测高 **141.4mm** vs
  TWIN_ASSET_SPEC §1 声明利乐砖 **136mm**, 差 5.4mm 无人对账 (屋顶坡口径? 需冻结口径并回填)。
  声明 vs 实测对账正是 ESR 测量层的定义域 — USDCraft 记 extents 但无不确定度/无对账门。
- ar usdz 实测 56.6×49.8×117.5 (包装层 rotX+scale 后) — 与源层口径需分层对账。

## 五、采纳计划

| 项 | 状态 | 说明 |
|---|---|---|
| usdcraft_gate.py 兼容门 | ✅ 已建 | 命名检查复刻 + ESR 证据字段 (bbox/mass/joints); 接入 12_asset_spec_gate 待做 |
| default_prim=/Asset | 待做 | 导出管线 (01 compositor / 13_usd_asset) 设 defaultPrim |
| 尺寸证据对账 | 待做 | 声明 mm (SPEC) vs stage 实测 vs USDZ 包装层 三方对账 + 容差门 (复用 R5 compare 语义 max(tol,k·u)) |
| 包结构约定 | 待做 | packaging.json (id/许可/sha256) + qcode 语义锚 + extents/mass 侧车 + 双缩略图 az45/el30 朝 −Y |
| Reconstruction 桥 (R5→仿真) | 远期 | R5 真实实物 → USDCraft reconstruction → 带测量溯源 (u_ref) 的数字孪生 — ESR 活演示 |
| ESR 继承记账 | ✅ photo-dieline §1 | "候选渲染≠目标证据"与 inverse-crime 禁令同类认识论, 记入继承映射 |

## 〇c、真合规闭环补正 (2026-11-27; 首版凭复刻 gate, 本节以 NVIDIA 原验证器实测为准)

**采纳计划三项全部关闭**:

1. **真合规验证**: `hfpackage` 全部 15 usdc 资产过 NVIDIA 原版 `_validate_usd_asset
   (backend='physx')` **15/15 PASS** — 含 default_prim/单位/无场景/有限值/依赖/供应商命名空间/
   物理图无环/articulation 绑定/PhysX schema 一致性全链。
2. **COM 哨兵修复**: 42 个 `physics:centerOfMass=(-inf,-inf,-inf)` 显式 authored 意见 →
   按 Link 网格顶点质心重写 (均匀密度近似, derived 口径; `photo-dieline/scripts/fix_com_finite.py`)。
   根因: 失传的内联结构化步骤写哨兵值; 我方复刻 gate 先抓出 (原版 `HasAuthoredValueOpinion`
   口径下同判 — COM 是显式 authored, 两验证器一致)。
3. **复刻 gate 语义修正**: finite 检查补 `HasAuthoredValueOpinion` 限定 (对齐原版 187-227 行);
   关节 `breakForce/Torque=inf` 是 USD Physics 合法 fallback (inf=不可断, 未 authored),
   非哨兵 bug — 复刻版曾误判 3 件 legacy 族。

**证据歧义教训**: 复刻 gate 无 authorship 限定 → schema fallback 被当坏值 (假阳性);
独立 pxr 遍历带 `IsAuthored()` → 又漏掉 API 写入的 COM (IsAuthored 对 API fallback 返回 False
但 `HasAuthoredValueOpinion` 为 True)。正确口径只有一种: 原版源码为准, 逐行对齐。

## 〇d、合规面扩至零售设备 (2026-11-27; 采纳线延伸)

nv960_fixture 20 类 (购物车/篮/陈列架/分配器×7/流利架/丝网容器系/果篮/桶) 全部经
author_compile 门禁 + NVIDIA 原版 `_validate_usd_asset(physx)` **20/20 PASS**。
资产合规总面 = **35/35** (15 包装 + 20 设备)。

对标亮点: shopping_cart (293 部件, 含钢丝网格) 是 NVIDIA 论文自报的 Reconstruction 失败
案例类型 ("细网格购物车钢丝重建失真") — 我方参数化 authoring 路径一次过其全量校验。
方法面全程 NVIDIA 同构 (参数化 authoring → USD → 其验证器), 未越用户指令边界。

## 〇e、后端方言对照实验 (2026-11-27; Newton 32/35 疑点裁决)

**疑点**: 我方 35 资产过 physx 35/35, 但 Newton 后端 32/35 — 3 个带关节 legacy 件
(beverage_can_330/food_container_1l/rsc_rsc_closed) 报 "conflicting vendor schema"。

**对照实验** (NVIDIA 自家数据集本地子集, R168 带关节 cube shelf 09, 4 关节):
generic FAIL / physx PASS / **newton FAIL — 同款冲突错误, 同一 prim 位形**。
其发行结构 = `rigid/<域>/<资产>/physx/model.usdc` — **按后端分目录, 单文件单方言**;
vendor schema (PhysxJointAPI 类) 由其 authoring harness 施加进对应后端文件, 非消费者运行时。

**裁决**: 我方 3 件 Newton "失败" = PhysX 方言文件配错后端验证, 与 NVIDIA 自家资产行为逐字一致。
真合规姿态 = 35/35 physx (我方方言), 与其发行模型同构。Newton 方言导出 = 独立分发产物
(其模型隐含, 当前范围外, 不作缺陷计)。
