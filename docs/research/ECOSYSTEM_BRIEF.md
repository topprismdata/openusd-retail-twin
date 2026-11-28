# 对外简报 · 本仓是什么 / 验证到哪一步 / 还没验证什么

> 一页版，给第一次接触本仓的人（合作方、评审、兄弟仓产品线）**先看这一页** ✓。
> 每一个数字都能在仓内找到出处 ✓；本文档里的口径由 `91_delivery_audit.py` 现算 ✓，闸门 [34]/[35] 逐项核对 ✓。

## 一句话

本仓是一个**零售数字孪生的科研型资产与实验仓**：参数化生成带物理与语义标注的 USD 商品资产 ✓，并用**公开数据集 SKU-110K** 实测"合成数据能不能迁移到真实照片" ✓。
**它不是**面向客户的生产资产库，也**不含**任何客户品牌素材 ✓（全部为自建虚拟演示 SKU ✓）。

## 已验证（有仓内产物可查）

| 事项 | 结果 | 证据 |
|---|---|---|
| NVIDIA SimReady 官方验证（`simready-validate` 2026.10.0，16 个 profile）| `Package-Candidate` **2/2 feature 通过** ✓ / `Package` **2/2** ✓ / `Package-NoBOM` 的 `CAP030_PackagingCore` 通过 ✓ / `Material` PASS ✓ / `Robotics-Prop` PASS（blocking 0 ✓）| `output/benchmark/simready_official_validation.json` ✓、包内 `.metadata/com.nvidia.simready.conformance.*.json` ✓ |
| 合规包真的能被下游打开 | 材质绑定改成标准 `material:binding` ✓ 后，Blender 打开**网格 3 / 材质 2 / 贴图 2** ✓（官方 PASS 但消费端 0 材质的坑已修 ✓）| `output/benchmark/asset_consume_check.json` ✓ |
| 交付自洽 | 发布产物 **198/198** 个文件 sha256 对得上 ✓；把包复制到临时目录后 pxr 仍能打开 ✓（贴图引用全在包内解析到 ✓ / 0 个网格没绑材质 ✓ / SR.004 的 11 个字段齐全 ✓）| `output/benchmark/delivery_audit.json` ✓ |
| 合成→真实迁移 | 可调项被逐条实测排除（标签统计量 ✓ / 标注密度 ✓ / 照片颗粒 ✓ / 增强与多样池 ✓ / 特征级多样化 ✓ / 场景结构整域重写 ✓ / 分工预训练 ✓ …）→ 缺口未被任何单一因子解释完 ✓ | 排除链：`output/benchmark/exclusion_chain.json` + README ④ 系列 ✓ |
| 唯一还活着的一条杠杆 | 同一份 411 张真实标注，训练轮数 10→20→40 的配对收益 **+3.60 pp** ✓ 与 **+2.38 pp** ✓（CI 整段在 0 以上 ✓）；**40 轮之后还在不在涨正在测** ✓（I-28 ✓）| `output/benchmark/real_budget_epoch_arm.json` ✓ |

## 明确没做 / 没验证（不要当成已达成）

- **未通过任何外部审核**：官方验证器 PASS **不等于**外部规范审核 ✓ —— 送审与贡献者资格**都没做** ✓。
- **没有第三方独立验证**：本仓结论目前只有本方证据 ✓（成熟度自评 M2 = "自证" ✓，M3 未开始 ✓）。
- **`mass` 是估算值**：由网格体积 × 水密度得出（**未实测称重** ✓），依据写进资产元数据 ✓。
- **机器人专用 profile 仍 FAIL**：规则面向机器人资产 ✓，本仓是 prop ✓（不适用 ≠ 失败 ✓）。
- **数据集许可限制**：SKU-110K 上游仅限学术与非商业用途，**禁止分发** ✓ → 派生图像与标签**不入仓** ✓，仓内只有 split 名单、指纹与指标 ✓（详见 `docs/research/DATASET_SKU110K.md` ✓）。
- **结论不可外推到真实门店**：用的是公开数据集代理 ✓，不是真实门店/真实 SKU ✓。

## 口径（同一批东西，七个不同的数，不能相加）

| 口径 | 数 | 说明 |
|---|---|---|
| 结构家族 | 1 | 唯一的几何母本（利乐包 ✓）|
| 拓扑 | 3 | 已落盘资产的网格 prim ✓ |
| 规格变体 | 1 | 同一结构的一档尺寸 ✓ |
| 印刷变体 | 13 | 13 个**虚拟** SKU（已落盘 1 个 ✓）+ 材质 colorway 2 ✓ |
| 资产包 | 1 | 可交付的包（对照包另列 ✓）|
| 渲染图 | 226 | 资产渲染 16 + 货架仿真 202 + 发布图 6 + 包内缩略图 2 ✓ |
| 真实商品 | 0 | 全部虚拟演示 ✓ |

数据量**单列**（不是资产数 ✓）：真实标注 411 张 ✓ / 合成池 200 张 ✓。
**官方样例集的对照标尺**（NVIDIA 自家 200 件 ✓）：`Package-Candidate` 198/200 ✓ / `Material` 89/200 ✓ / **`Robotics-Prop` 0/200** ✓ —— 本仓资产多补了一层语义 + 物理方言标注 ✓（不是"比官方好" ✓，是"官方样例是裸物理资产" ✓）。

## 怎么复算

```bash
python pipelines/shelf_sdg/90_simready_package_pipeline.py -- --sku demo_classic
# 8 步: 自研闸门 -> 生成 -> 缩略图 -> 合规包+官方验收 -> 消费端检查 -> 发布 -> 交付验收 -> 文档闸门
python pipelines/shelf_sdg/91_delivery_audit.py   # 完整性 / 净室可用性 / 口径
python pipelines/shelf_sdg/28_doc_consistency_check.py   # 文档与产物一致性 (含口径逐项核对)
```

产物清单与哈希：`docs/research/benchmark/MANIFEST.json` ✓（逐文件 sha256 ✓）。

## 身份与许可边界

公开版本只含**自建虚拟演示 SKU** ✓（Topprism® 虚拟产品 ✓，标注"虚拟演示产品 · 非销售品" ✓），不含客户照片、品牌印刷文件或包装刀版 ✓；示例 SKU 档案是演示参数 ✓，不代表任何品牌合作 ✓。
