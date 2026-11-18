# 数据源调研账（多源：HF / Kaggle / Roboflow / GitHub / NVIDIA，2026-11-09）

目的：为 P2 真实终端校验（原阻塞于无自有现场图）与 R3/纹理真值寻找可用外部数据；大数据集一律落移动硬盘 `/Volumes/ghb/datasets/`（内部盘 92% 满）。

## 一、已获取 / 获取中

| 源 | 许可 | 体积 | 状态 | 用途 |
|---|---|---|---|---|
| shelfwise-by-form/SKUs_on_shelves_PL (HF) | **CC-BY-4.0** | 10.9GB zip | 🏃 下载中 → /Volumes/ghb/datasets/ | **P2 主源**：真实门店货架 27k 图/2M 框/8k SKU，COCO 格式 |
| neurolaboratories/reshelf-detection (GitHub) | BSD-3-Clause | 仓库 800KB | ✅ 已克隆 cpgdet129_repo/ | postprocess.py 的可见性/面积过滤参数（与本项目 P0-2 闸互参）+ 样张对（jpeg+掩膜） |
| Voxel51/sku110k_test 等 (HF) | 原 SKU-110K 许可 | 中 | 已有官方副本 | 仅镜像备用 |

## 二、可用但受限（记录约束）

| 源 | 许可 | 约束 | 处置 |
|---|---|---|---|
| valiantlynxz/norwegian-grocery (HF) | **CC-BY-NC-4.0** | 非商业 | 仅作内部真实代理评测，任何对外/商用结论不引用 |
| adnankhan-11/smart-retail-shelf-auditing-v1 (HF) | 未标许可 | 法律灰区 | 仅 streaming 内部评测（零落盘），不 redistribution |
| JamieSJS/rp2k、mteb/rp2k (HF) | 原 RP2K 许可 | 检索 parquet 1M+ 行 | 品牌包装真品图源（纹理 lift 扩 SKU），用前逐图核许可 |
| Roboflow Universe（GS25 OOS 等货架集） | 逐集许可 | 需 Roboflow API key | 待用户提供 key 后评估 |
| Kaggle（Retail Shelf Void Detection / Shelf Detection 11 类） | 逐集许可 | 需 Kaggle 登录 | 同上；Void 集与本项目 OOS 状态类直接对口 |
| WACV2026 PRAW Track 3 (Standard AI) | 竞赛协议 |  gated | 关注赛期，作外部对标 |
| NVIDIA NGC retail-object-detection trainable | NVIDIA 许可 | NGC CLI + 接受条款 | 跨厂商合成数据对照臂候选 |

## 三、死链 / 不可用（防重复踩）

| 源 | 结论 |
|---|---|
| CPGDet-129 数据短链 bit.ly/3n3jowR → dl.orangedox.com | **404 死链**（2026-11-09 实测）；仅仓库脚本/样张可用 |
| strova-ai/uk_retail_store_synthetic_dataset (HF) | 名为 synthetic retail 实为**表格**数据，与图像无关 |
| Hilbs/Packaging、saichandb/retail-shelf-db (HF) | 无卡片/无许可/内容不明，弃用 |

## 四、执行顺序
1. PL 解压 + COCO→YOLO 转换脚本（落移动硬盘），跑 P2 代理验收（R0/R2 模型在真实货架上的四状态指标）
2. norwegian-grocery 内部代理评测（NC 限制标注）
3. 若用户提供 Roboflow/Kaggle 凭证：Void Detection（OOS 对口）优先
4. NVIDIA NGC 合成集作 R3 跨厂商合成对照（许可接受后）
