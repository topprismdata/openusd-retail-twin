# SKU-110K 数据集来源与指纹 (2026-11-21 实测)

本文件是"评测集到底用的是哪一份"的可核验凭据 —— 补上审计 F4 (`14:147,181,199`、`16:104`)
留下的缺口: 之前四臂 json 只记了协议与指标, 仓内无从判断评测集规模与内容。

## 1. 来源

| 项 | 值 |
|---|---|
| 打包 | `SKU110K_fixed.tar.gz` (官方 CVPR19 challenge 修复版) |
| URL | `htt<SKU110K_ROOT>` (换机时用 env `SKU110K_ROOT` 覆盖) |
| 数据集 yaml | `<SKU110K_ROOT>\SKU-110K.yaml` (env `SKU110K_YAML`) |
| 原始许可 | 随包 `LICENSE.txt`; 论文引用 Goldman et al., CVPR 2019 "Precise Detection in Densely Packed Scenes" |

### 许可条款 (逐字核对 `LICENSE.txt`, 2026-11-21)

> All photos and data contained in this directory (the "Photos") are provided for the exclusive use by you
> and solely for academic and non-commercial purposes. You shall not, directly or indirectly:
> (i) transfer, distribute, disseminate or otherwise provide access to the Photos;
> (ii) sell, offer to sell, transfer, market or otherwise commercialize the Photos;
> (iii) modify, copy or create derivative works of the Photos.

**本仓的合规边界 (据此定, 不是推测)**:

| 允许 | 禁止 | 本仓做法 |
|---|---|---|
| 学术与非商业用途的本地研究 | 分发/提供访问 (i) | ✅ 数据集**不入仓** (在 `<SKU110K_ROOT>`, 换机用 env 指向); 仓内只有 split 名单、标签抽样 sha256、指标 json |
| 本地派生标注 (YOLO 格式) | 制作照片的衍生作品 (iii) | ✅ 派生标签**同样不入仓**, 只入 **sha256 指纹**; 仓内不发布任何图像或图像派生文件 |
| 引用与报告指标 | 商业化 (ii) | ✅ 指标与协议可公开; 若日后用于商业交付或客户提案, 须换用可商用数据集复跑 |

**⚠️ 一个尚未定论的点**: 训练产出的**模型权重**是否构成条款 (iii) 所指的"衍生作品", 许可文本没有
界定, 各法域判例也不一致。**本仓的处理是: 权重不进仓** (`output/` 被排除, 只留 sha256)。
若论文要发布权重, 请自行评估该风险, 或改为发布**结构与指标**而非权重文件。

## 2. 规模 (由 `annotations_{train,val,test}.csv` 实算)

| split | 图像 | 框 |
|---|---:|---:|
| train | 8,219 | 1,208,482 |
| val | 588 | 90,968 |
| test | 2,936 | 431,546 |
| 合计 | 11,743 | 1,730,996 |

单类 (`nc: 1`, class 0 = `product`), 平均 147 框/图 —— 与论文描述一致。

## 3. 指纹 (sha256)

| 文件 | sha256 | 字节 |
|---|---|---:|
| `train.txt` | `a63f1cc02475cac948b85ecdbaf350187679b5ad83886904aac0d6de9559c8eb` | 204,370 |
| `val.txt` | `6233ea4c7fa82a93e36e3d8e2bf59a646624184ab45ef86052228bedfe9dd79e` | 12,826 |
| `test.txt` | `ec5bcf3343130337f74d3cdf101e74c6af982c148b1972a74ed6f395db3eaeb8` | 69,355 |
| `SKU-110K.yaml` | `e469320c2e05f7c9222f3e708d288edd4e242e872660155e26486553d286378a` | 111 |
| `prep_summary.json` | `eb0ab9a276e71331b2fb695b2633c6bc4f7b316a89b72ccd844c5498a9ab42af` | 296 |

标注目录抽样指纹 (每 split 前 200 个标签文件逐个 sha256 后再哈希):
`train` `2386b9ecf2965f358f217445c606031301903b6c59f92b10b4e2030e66a3dc1b` ·
`val` `2a1400bb962e34a606a7352ec93be9280693356b721569a2cd6d36a0334fbfa7` ·
`test` `74398af879b6f2558474b63abf263e3d997622b050df2e9e30479ad4b946c89f`

## 4. 转换方法 (仓内脚本: `tools/` 之外的一次性脚本, 逻辑已固化在此)

原始 CSV 8 列: `image, x1, y1, x2, y2, class, image_width, image_height` (无表头)。
转换: 逐行取框 → 归一化 xywh → 写 `labels/<stem>.txt` (class 恒为 0)；
同时按 CSV 里出现的图像名排序写出 `train.txt / val.txt / test.txt` (每行 `./images/<name>`)。

> 说明: 官方 CSV 的 class 列是字符串 `object`, 无 SKU 类别信息 —— 单类化是数据集本身的属性,
> 不是本仓的选择。

## 5. 与仓内协议的对齐

`14_sku110k_baseline.py` 的四个臂与 `21_annotation_budget.py` 都从 env `SKU110K_YAML`
读这份 yaml; `17_count_eval.py` 从 `SKU110K_ROOT/annotations/annotations_test.csv` 取真值计数。
换机只需设两个环境变量, 不再有 macOS Homebrew 硬编码路径。

## 6. 已知数据侧噪音 (不影响口径, 但要写进论文的 limitation)

评测时 PIL 会报 `Corrupt JPEG data: N extraneous bytes before marker 0xd9` /
`premature end of data segment` —— SKU-110K 里确有一批非标准 JPEG。
实测: 2,936 张 test 图里 **1 张被 ultralytics 判为损坏并跳过** (实测 2,935 张参与评测,
431,419 个实例), 训练/评测吞吐与指标不受影响。
