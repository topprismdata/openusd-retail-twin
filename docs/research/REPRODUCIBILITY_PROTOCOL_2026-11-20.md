# 四臂实验的可复现化改造 (2026-11-20)

对象：`pipelines/shelf_sdg/` 里的 SDG 数据集生成、四臂训练/评测、消融臂与报告生成。
目标：让"这个数字是用哪份数据、哪份划分、哪份权重、什么环境跑出来的"**可被第三方事后核验**。

---

## 1. 改造前: 五个不可复现的缺口

| # | 缺口 | 证据 | 后果 |
|---|---|---|---|
| F1 | **train/val 按 `idx%5` 从同一条随机流切** | `02_shelf_sdg_inspector.py:424` | R1 (纯合成) 用合成 val 选 `best.pt` → 指标系统性偏高; 且 val 不是种子互斥的留出 |
| F2 | **同一 idx 的图随 `--num-images` 变化而变化** | `02:336` 单条 `random.Random(seed)` 顺序消费 | 数据集不可逐字节复现; "同一 seed 两次跑"得到不同数据集 |
| F3 | **协议哈希只覆盖协议字典** | `14_sku110k_baseline.py:101` | 数据组成、划分、实跑 batch、依赖版本、权重出处全部在哈希之外 → 换了数据哈希不变 |
| F4 | **权重只落在 `runs/` (被 .gitignore 排除)** | `14: main()` | 仓内无从校验"这个数字是用哪份权重跑出来的", 复现链断点 |
| F5 | **设备写死 `mps` + 内存探测只认 macOS `vm_stat`** | `14: PROTOCOL["device"]="mps"`; `14: available_gb()` | Windows/Linux 上四臂根本跑不起来 (不是数值问题, 是直接报错) |

---

## 2. 改造后

### 2.1 划分: 种子互斥 + 逐图可核 (F1/F2)

`02_shelf_sdg_inspector.py`:

- 每张图的布局种子独立派生: `layout_seed = sha256(f"{base_seed}|{split}|{idx}")[:8]`
  → **train/val 消费互不相干的随机流**; `img_000` 的**布局与标注**只取决于 `(seed, split, 0)`,
  与生成顺序、生成总数无关。

  **实测 (2026-11-20, Windows / GTX 1050 Ti / OptiX)**: 同一 seed 下分别生成 20 张与 6 张,
  共有 idx 的 **标注文件 sha256 逐张一致**; 但 **PNG 字节不一致** —— 逐像素比较:
  最大差 **1/255**, 平均差 0.0, 差异像素占比 4.4e-5。这是 GPU (OptiX) 采样的浮点非确定性,
  不是逻辑差异。
  **结论**: 数据 (几何/标注) 逐字节可复现; **渲染像素只保证 ±1/255** (GPU)。
  论文里若要宣称"图可复现", 应写"标注与布局逐字节可复现, 渲染像素在 GPU 上存在 ≤1/255 采样差";
  CPU 渲染是否逐字节一致**本轮未测**。
- 划分比例显式化: `--val-ratio` (默认 0.2), 交错分配 (两集都覆盖完整货架形态)。
- 落盘 `output/sdg_shelf/split_manifest.json`:

```json
{
  "schema": "sdg_split_manifest/1",
  "base_seed": 42, "val_ratio": 0.2,
  "split_policy": "seed-disjoint deterministic: ...",
  "scene_id": "…", "n_train": 4, "n_val": 1,
  "train_scene_ids": ["…"], "val_scene_ids": ["…"], "scene_overlap": true,
  "residual_limitation": "仓内只有一套货架模板 …",
  "images": [{"image": "img_000.png", "split": "train", "layout_seed": 12345678,
              "scene_id": "…", "png_sha256": "…", "label_sha256": "…", "n_boxes": 27}, …]
}
```

### 2.2 协议指纹: 覆盖实验的每一个组成部分 (F3)

新增 `pipelines/common/protocol.py`。`protocol_hash` = 对下列全部内容的 sha256 前 16 位:

| 组成 | 内容 |
|---|---|
| `protocol` | 声明的协议字典 (模型/超参/设备策略/seed) |
| `data` | 数据组成: 各来源图数、目录内容指纹、SDG 划分清单哈希 |
| `splits` | 训练/验证集的**文件级**指纹 (名单 sha256 + 内容 sha256) |
| `actual` | 实跑配置: 实际 epochs/batch/workers/设备/耗时/权重选择 |
| `deps` | python / torch / ultralytics / numpy 版本 |
| `checkpoint` | 权重出处: 路径 + sha256 + 选择方式 (best/last) |

同时保留 `protocol_hash_legacy` (旧算法, 只哈希协议字典) —— 用来和 2026-11-08
已发布数字 (0.886 / 0.868 / 0.133) 对齐, 两个哈希不混用。

### 2.3 权重归档 (F4)

`output/benchmark/weights/<arm>/{best,last}.pt` + sha256 写进报告的 `checkpoint` 字段。
`--select last` 可显式改用最后一个 epoch 的权重 (R1 用它可避免"用合成 val 选模型")。

### 2.4 跨平台 (F5)

- 设备: 协议写 `"device": "auto"` → 运行时按 `cuda > mps > cpu` 选, 实际值写进 `actual`。
  (四臂同改, 不做单臂调参; 历史协议 `PROTOCOL_V1` 原样保留用于对齐旧数字。)
- 内存: 改用 `runtime_env.available_memory_gb()` (跨平台), 原 `vm_stat` 实现删除。
- 数据集根目录: `env SKU110K_ROOT` > 原 macOS 硬编码路径; 符号链接失败时自动退回复制。

### 2.5 协议偏差可显式声明 (--epochs / --select)

| 开关 | 作用 | 记账方式 |
|---|---|---|
| `--epochs N` | 覆盖协议里的 epochs | **写回 protocol 字典** → 进 `protocol_hash`。不会再出现"实跑 15ep / 协议写 10ep"这种事后才发现的不一致 |
| `--select best\|last` | 选权重 | 记进 `actual.checkpoint_selection` 与 `checkpoint.selection`。R1 建议 `last` —— 用合成 val 选 `best` 会偏乐观 |
| `--seed N` | 全局种子 | 记进 protocol / 划分清单 |

### 2.6 环境变量

| 变量 | 作用 | 缺省 |
|---|---|---|
| `SKU110K_ROOT` | SKU-110K 数据集根目录 (含 `images/` `labels/` `annotations/annotations_test.csv` `train.txt` `val.txt`) | `/opt/homebrew/datasets/SKU-110K` (原仓硬编码) |
| `SKU110K_YAML` | 评测集 yaml | `SKU-110K.yaml` |
| `TORCH_DEVICE` | 强制训练设备 (cuda/mps/cpu) | 自动 cuda > mps > cpu |

原仓把数据集路径写死成 macOS 的 Homebrew 路径, 换机即失效; 现在两处都可覆盖。

### 2.7 场景级留出 (2026-11-21, 审计 F6)

原先只有一个 `scene_id` (全数据集 20 张图共用) —— 于是 train/val 只是"同一场景的抖动副本",
种子互斥 ≠ 场景独立。现在:

- **场景** = 一组共享结构化参数的图像: 上架哪些 bay/层位、SKU 配比、LED 灯光色温与强度、
  世界光强度、相机距离/高度/偏航、错位率 —— 全部由 `(base_seed, scene_idx)` 派生,
  因此可复现, 且不同场景在几何与成像条件上确实不同;
- **一个场景的全部图像必属同一个 split**; train/val 的场景集合互不相交
  (`split_manifest.json` 里 `scene_level_holdout: true` / `scene_overlap: false`);
- 划分按**图像数**逼近 `val_ratio` (不是按场景数取整 —— 否则末尾不足一个场景容量的残余场景
  会把比例带偏: 5 张图 / 每场景 4 张时"取 1 个场景"会得到 4 张 val = 80%);
- 图内布局种子由 `(base_seed, scene_idx, img_in_scene)` 派生, **不含 split** ——
  场景归属变化时图像内容仍逐字节不变;
- `--split-mode image` 保留旧行为 (单场景 + 按 idx 交错) 作为对照。

**仍然残留**: 不同场景是**同一套货架模板 (gondola_v1) 的参数化变体**, 不是不同的货架结构/店型。
真正的场景外推需要多套货架模板或真实店头照片 —— 这一点已写进 `split_manifest.json`
的 `residual_limitation`, 论文里必须照此表述。

### 2.8 标注预算臂 (2026-11-21, 审计 F1)

新增 `pipelines/shelf_sdg/21_annotation_budget.py`: 跑 (real_frac, synth_n) 网格,
每个格点在**同一份真实 test 集**上评测 —— 这是唯一能回答"合成能否替代手工标注"的实验形态
(R2 = 全量真实 + 合成追加, 从未减少过标注量)。真实子集用**固定种子的随机抽样**
(不是"取前 k 张", 否则排序偏置会混进结果), 名单与 sha256 落盘; 输出 `budget_curve.json` / `.md`。

**2026-11-21 真数据全量跑完的结果 (seed 42; 多 seed 汇总见 §2.9 与 `budget_seed_variance.md`)**:

| 真实比例 | 真实图数 | 合成训练图 | mAP@0.5 | Δ vs 全量真实 | protocol_hash |
|---:|---:|---:|---:|---:|---|
| 1.00 | 8,219 | 0 | 0.8862 | +0.00 | `a8cabd7336aee2c4` |
| 0.05 | 411 | 0 | 0.7946 | −9.16 | `e52193f75b4400a2` |
| 0.05 | 411 | 160 | 0.7855 | −10.07 | `f7ef7fb0fd34ed07` |
| 0.02 | 164 | 0 | 0.7086 | −17.76 | `4b56a36c9b3037d8` |
| 0.02 | 164 | 160 | 0.6787 | −20.75 | `b8b33b27faaf7d1d` |

⚠️ **单 seed 的差值不是效应量**: 同一格点只换训练 seed 就差 ~2pp, 且"加合成"的差值会变号
(seed 42 −0.91pp / seed 43 +1.00pp) → 结论应表述为"**没有可测量的正向补回**"(零效应),
详见 §2.9 的方差表与 §2.11 的逐图配对检验, 以及
`docs/research/BUDGET_ARM_CONCLUSION_2026-11-21.md` 的口径表。

复现命令 (与本次实跑逐字一致):

```bash
# SDG 合成集: 200 图, 场景级留出 → train 160 / val 40
python3 pipelines/shelf_sdg/02_shelf_sdg_inspector.py \
  --num-images 200 --split-mode scene --images-per-scene 4 --seed 42 \
  --out-dir output/sdg_shelf

# 预算格点: 全量真实 + 5%/2% 真实 × (无合成 / 160 张合成)
python3 pipelines/shelf_sdg/21_annotation_budget.py \
  --fracs 1,0.05,0.02 --synth 0,200 --epochs 10 --select last \
  --budget-seed 20261120 \
  --synth-dir output/sdg_shelf/images/train

python3 pipelines/shelf_sdg/21_annotation_budget.py --merge-only   # → budget_curve_all.md
```

权重用 `--select last` (不用 val 挑权重): 否则格点间会出现"val 选权重"的选择偏差。
代价是预算臂的数字与四臂的 best.pt **不可直接对齐** (0.8862 是用 last 选权重跑出来的),
所以预算臂只做**格点之间**的比较。

**判读**: 合成没有补回任何缺口, 反而轻微损害 (5%: −0.91pp; 2%: −2.99pp) →
"合成可替代大规模手工标注"**在本数据集上不成立**。

### 2.9 seed 方差 (2026-11-21, 把"显著性不可判定"往前推一格)

`21_annotation_budget.py` 新增 `--run-tag` (格点名后缀, 复跑不覆盖既有结果) 与已有的 `--seed`
(训练随机性) 配合: **真实/合成子集固定** (`--budget-seed` 不变), 只换训练 seed → 同一格点内
"加合成 vs 不加合成"成为**配对**比较, 方差可以直接估。

```bash
for s in 43 44; do
  python3 pipelines/shelf_sdg/21_annotation_budget.py \
    --fracs 0.05,0.02 --synth 0,200 --epochs 10 --select last \
    --budget-seed 20261120 --seed $s --run-tag s$s \
    --synth-dir output/benchmark/synth_single/images/train
done
python3 pipelines/shelf_sdg/22_budget_seed_variance.py   # → budget_seed_variance.{md,json}
```

### 2.10 域差距度量 (2026-11-21, 补上审计里"归因不可核验"的那个文件)

`23_domain_gap_measure.py` 落盘 `output/benchmark/domain_gap_measure.json`: 对比真实 train 与
SDG 合成 train 的**标签统计** (框/图、单图框面积占比和、平均框面积、宽高比、布局相似度、分辨率分布),
把"合成为什么帮不上忙"从推测变成可核验的数字 (本机实测: 框/图 21.8 vs 147.0 = 0.148×,
框面积 1.77×, 布局相似度 0.823 vs 0.696, 分辨率 1440×1080 vs 手机竖拍混合集)。
**边界**: 标签统计只刻画分布形状, 不等于特征空间距离; 特征级差距未测。

### 2.11 逐图配对评测 (2026-11-21, 审计行动 8: 让显著性可判定)

训练侧的 seed 方差只是噪声的一部分; 真正的检验对象是**评测集**。`25_paired_image_eval.py`
对两个模型在**同一份真实 test 集**上逐图算 AP@0.5 (101 点插值, 与 COCO eval 同口径),
再做**配对**统计 (n = 图数 = 2,935, 而不是 n = seed 数 = 3~5):

```bash
python3 pipelines/shelf_sdg/25_paired_image_eval.py \
  --weights-a output/benchmark/budget_runs_real0.05_synth0/train/weights/last.pt \
  --weights-b output/benchmark/budget_runs_real0.05_synth200/train/weights/last.pt \
  --label-a "5% 真实 无合成" --label-b "5% 真实 +160 合成" --tag real0.05
```

脚本同时输出**数据集级 pooled AP@0.5** (全局按置信度排序后统一匹配), 用来**校验**逐图 AP
实现与 ultralytics 报告的 mAP@0.5 一致 (两者应逐位接近; 若不一致, 说明实现有错)。
逐图 AP 的**均值不等于**数据集级 mAP (每图等权 vs 按检测数加权) —— 只有配对差值用于推断。

### 2.12 产物清单 (2026-11-21, 审计行动 9)

`24_publish_manifest.py` 为随仓发布的基准产物 (`docs/research/benchmark/`) 逐个记
sha256 + 字节数 + 生成脚本 + protocol_hash → `MANIFEST.json`。第三方拿到仓后可直接核对
"报告里的数字对应哪个文件、哪个哈希"。

### 2.12b 功效分析 / 剂量-反应 / 合并工具 (2026-11-21 晚)

| 脚本 | 作用 | 输出 |
|---|---|---|
| `29_power_analysis.py` | 从已落盘产物现算功效: 配对差值的 95% CI、**能排除的最大正向补回**、缺口对比、反推所需 seed 数; 并对比评测侧 CI 半宽与训练侧散布 | `output/benchmark/power_analysis.json` / `.md` |
| `30_merge_sdg_sets.py` | 合并多个 SDG 实例 (不同 `--seed`): 文件名前缀防冲突、**逐图内容 sha256 去重**、跨实例场景级留出复核 | 合并后的 `split_manifest.json` (schema 3-merged) |
| `31_dose_response.py` | 合成剂量-反应: 同一池的嵌套子集 (40 ⊂ 80 ⊂ 160) 上算配对差值、斜率 (pp/100 张)、补回率 | `output/benchmark/dose_response.json` / `.md` + `dose_response.png` |
| `32_dose_chain.py` | 剂量链驱动器 (可续跑, 已完成格点 SKIP); 跑 40/80 两档 × 2 seed × 2 预算 | 各格点 `budget_real*_synth{40,80}_dose_s*.json` |
| `33_count_threshold_sweep.py` | 计数指标的置信阈值敏感性: 从各臂 `conf_sweep` 出表 + 图 | `output/benchmark/count_threshold_sweep.md` / `.png` |
| `26_publish_artifacts.py` | 产物发布 + **行尾归一 + 清单刷新** (归一必须在算哈希之前) | `docs/research/benchmark/` + `MANIFEST.json` |
| `27_budget_curve_figure.py` | 论文图: 左=预算曲线 (seed 误差棒 + 每点标 n=), 右=逐图配对差值 | `docs/research/benchmark/budget_curve_figure.png` |
| `28_doc_consistency_check.py` | 文档↔产物一致性闸门 (CI 必跑): 哈希引用 / 清单 sha256 / **跨 3 个 seed 的 13 个格点数值** | 退出码非 0 = 失败 |

**为什么 17_count_eval.py 必须 `stream=True`**: 非流式 `predict` 会把 600 张图的 `orig_img`
全留在内存里 (实测 ~10 GB), 直接触发训练侧的 `[MEM-GUARD] 可用 X GB < 10GB, 拒跑`;
流式只保留每图的框数。这是本轮实测踩到的坑, 已写进脚本注释。

### 2.12c 计数指标的阈值敏感性 + 合成剂量链 (2026-11-22)

```bash
# 计数指标扫多个置信阈值 (单点 0.35 不稳健)
python3 pipelines/shelf_sdg/17_count_eval.py --arm real1 \
  --weights output/benchmark/budget_runs_real1_synth0/train/weights/last.pt \
  --conf-sweep 0.15,0.25,0.35,0.5,0.65

# 合成剂量-反应链 (同一合成池的嵌套子集 40 ⊂ 80 ⊂ 160; 可续跑, 已完成的格点会 SKIP)
python3 pipelines/shelf_sdg/32_dose_chain.py 0.05 0.02
```

**⚠️ 口径陷阱 (源码级)**: "只在最低阈值推理一次, 再按 conf 过滤框" 与 "逐阈值各推理一次"
**语义上不等价** —— ultralytics 的 `non_max_suppression` 里 conf 过滤在 NMS **之前**
(`utils/nms.py`: `filt = xc[xi]; x = x[filt];` 之后才做 NMS), 低分框会先参与抑制, 可能压掉
本该保留的高分框。本数据集上两者数值恰好一致 (单类密集货架, 低分框基本是已被抑制的重复框),
但不能依赖这个巧合 → 计数指标统一按**逐阈值各跑一次 `predict`** 定义, 已写进 `17_count_eval.py`。

**⚠️ 另一个易混点**: 同一目录下的权重会被后续实验覆盖 —— `budget_runs_real0.05_synth0/.../last.pt`
现在是 **10 epoch** 的格点权重 (sha `cebe040b…`), 而早期 `count_pilot.json` 用的是 **2 epoch**
冒烟权重 (sha `57ed73ca…`)。两者在 conf 0.35 上的 count MAE 分别是 20.76 与 29.13 ——
**差异来自训练轮数, 不是评估口径**。每个计数产物都记了 `weights.sha256`, 引用时必须核对。

### 2.12d 全量真实格点的多种子复跑 (2026-11-22)

审计里最硬的一条限制是"全量真实只有 1 次运行, 它的方差未知", 而"相对全量真实的缺口"
偏偏是全篇最常被引用的那个数 → 把**参照物本身**也做成多种子。

```bash
# 全量真实格点 (frac=1) 只换训练 seed 复跑 43/44。
# frac=1.0 时 sample_subset() 直接返回全集 (顺序不变) → real_subset_sha256 与 seed 42 那次
# 完全相同 → 两次之间只有训练随机性, 没有数据差异。链可续跑: 每步产物 json 存在就 SKIP。
python3 pipelines/shelf_sdg/34_fullreal_seed_chain.py --seeds 43,44

# 只补跑逐图配对 (训练与计数产物都在时)
python3 pipelines/shelf_sdg/34_fullreal_seed_chain.py --seeds 42 --paired-only
```

产出:

| 文件 | 内容 |
|---|---|
| `budget_real1_synth0_s{43,44}.json` | 格点结果 (mAP@0.5 / mAP@0.5:0.95 / P / R) |
| `count_real1_s{43,44}.json` | 计数指标 (与 `count_real1.json` 同一份 600 张名单、同一 conf 0.35) |
| `paired_image_eval_gap_real1_s{seed}.json` | 5% 真实 vs 全量真实 的逐图配对 AP (同 seed) |
| `budget_seed_variance.{md,json}` | 自动重算, 多出"相对全量真实的缺口 (跨格点, 按 seed 配对)"一节 (差值均值 / 95% CI / t), 以及计数指标那一侧的缺口 |

**坑**: seed 42 那一跑的目录**不带** run-tag 后缀 (`budget_runs_real1_synth0/`), 其它 seed 带
`_s<seed>` → 取权重别按目录名猜, 用 34 脚本里的 `_ckpt()`。

### 2.12e 已发布四臂的多种子复跑 (2026-11-22 晚)

四臂 (r0 真实 / r1 纯合成 / r2 真实+合成 / r3-full) 的数字来自 2026-11-08 的**单次运行** (seed 42),
于是全篇最后一条"单次运行支撑的结论"是 **"R2 真实+合成 相对 R0 真实: Δ −1.77pp ≤ 2pp, 未检出差异"**
—— 没有方差, 就说不清这个 −1.77pp 里有多少是训练噪声。

```bash
# 14 号脚本新增 --seed (seed 是协议的一部分 → 覆盖后 protocol_hash 随之改变)
# 链按 **seed 轮转** 跑: r2 s43 → r0 s43 → r2 s44 → r0 s44 → r1 s43 → r1 s44,
# 这样任何时刻中断, 手上都有完整的一对 r0/r2 同 seed 结果。
python pipelines/shelf_sdg/35_fourarm_seed_chain.py --seeds 43,44 --arms r2,r0,r1

# 汇总 (mean±std + 按 seed 配对的 r2−r0 差值与 CI)
python pipelines/shelf_sdg/36_fourarm_seed_variance.py
```

产出:

| 文件 | 内容 |
|---|---|
| `sku110k_r{0,1,2}_s{43,44}.json` | 各臂复跑结果 (mAP@0.5 / mAP@0.5:0.95 / P / R + protocol_hash) |
| `fourarm_seed_variance.{md,json}` | 每臂 mean±std + 配对比较 (r2−r0, r1−r0) |

**坑**: `sku110k_r1_scenebest.json` / `_scenelast.json` 是**敏感性复跑** (场景级留出合成集),
不是 seed 复跑 —— 汇总脚本只把无后缀的规范产物与 `_s<seed>` 后缀的复跑算进 seed 统计,
其它后缀单列一节, 否则同一个 seed 的两个不同实验会被当成"两次运行"。

### 2.12f 标注口径差实测 (2026-11-23, 审计 F7)

审计 F7 记的是"合成标签丢弃遮挡物 (可见面积 <15% 的不入库), 真实标注保留遮挡商品" ——
但那只是**读代码**得到的观察, 从没在**实际使用**的那套合成数据上量过数, 于是"口径差"
一直是个没有量级的东西, 也没法判断它能不能影响头条结论。

```bash
python pipelines/shelf_sdg/37_label_semantics_measure.py   # 不训练不渲染, 只读已有产物
```

实测结果 (200 图 / 5240 个目标, 逐图比对"标签行数 vs 标注记录数"):

| 项 | 结果 |
|---|---|
| 可见度过滤丢弃 | **0 / 5240** —— 一次都没触发 |
| 逐图标签行数 = 标注记录数 | 全部一致 |
| 单类化丢 class 1 (OOS gap) | 824 / 5240 = 15.7% |
| 合成有效框/图 (train) vs 真实 | **21.82 vs 147.04** (6.74×) |
| 合成在 R2 训练集里的占比 (影响上界) | **1.91%** (160 / 8219) |

→ **F7 的原话在数据层不成立**; 真实存在的口径差是 (a) 丢 OOS gap 框 15.7%、
(b) 合成框=可见区域紧致框 vs 真实框=整品框、(c) 框密度差 6.7×。
对 R2-vs-R0 头条结论的影响上界 = 合成占比 1.91% → 量级上不可能解释"未检出差异";
对 R1 (纯合成) 则是 100% —— R1 的数字就是"当前标签语义下的纯合成"水平。

产物: `docs/research/benchmark/label_semantics.{json,md}`; 闸门 `28_doc_consistency_check.py` 的
`[7]` 项把这 5 个数字钉在产物上。

### 2.12g R3 域对齐臂的协议对齐复跑 (2026-11-23)

已发布的 R3-full (纯合成 + 域对齐参数: cam_mult1.6 / lens40 / misalign0.35 / bays5) 有三重问题,
使它在仓内**不可复现、不可比较** (审计 F3/C4):

1. 协议记录与实际训练配置矛盾 (首跑 15/8 epoch, 产物 json 记 10 epoch);
2. 它的合成集是**旧划分**那一份, 2026-11-21 换成场景级留出后已被覆盖 → 现已不存在;
3. 它是 400 图的训练集, 而当前协议的 R1 是 160 图 → 即使重跑, 图数/划分/场景族都不同。

于是审计里"域对齐不是充分条件" (C7) 这条判决, 实际靠的是一次**不可复现**的运行。
`38_r3_protocol_matched.py` 把它重做成**与当前协议完全对齐**的臂, 只留一个自变量:

| 项 | R1 (对照, 已有) | R3pm (本脚本) |
|---|---|---|
| 图像数 / 划分 | 200 图 = 160/40 场景级留出 | 同 ✅ |
| base_seed / val_ratio / images_per_scene / samples | 42 / 0.2 / 4 / 64 | 同 ✅ |
| 标签语义 / 单类化 | 同一套 | 同 ✅ |
| 训练协议 | YOLO11n/640/10ep/batch4/**多 seed** | 同 ✅ |
| **处理变量** | cam1.0 / lens28 / mis0.10 / bays1 | cam1.6 / lens40 / mis0.35 / bays5 |

**对照配方的核验**: 现有那套合成集的产物里**没记**相机/错位率/bays 参数
(`dataset_summary.json` 是 2026-11-23 才补 `recipe` 字段的), 所以"对照组用的是 02 的默认参数"
本来只是推断。现在用默认参数**重渲 1 张**图, 与对照集 `train/img_000` 的标签**逐字比对**:
**30 行 vs 30 行, 完全一致** → 对照组确实是默认配方, "只差一个变量"的前提成立
(比**标签**而不是像素: 渲染有 GPU 采样噪声, 但布局与框是确定的)。

```bash
python pipelines/shelf_sdg/38_r3_protocol_matched.py --stage render --seeds 42,43,44,45
python pipelines/shelf_sdg/38_r3_protocol_matched.py --stage train  --seeds 42,43,44,45
python pipelines/shelf_sdg/36_fourarm_seed_variance.py      # 汇总 (含 r3pm 组与 R3pm−R1 配对)
python pipelines/shelf_sdg/38_r3_protocol_matched.py --stage summarize
```

**配对统计只在 36 号脚本里算** (五臂汇总的唯一事实源), 38 号只引用, 避免同一个统计量在两个
脚本里各算一遍、日后对不上。

**结果 (2026-11-23 实测)**:

| 臂 | seed 42 | seed 43 | seed 44 | seed 45 | mean ± std |
|---|---:|---:|---:|---:|---:|
| R3pm (域对齐配方) | 0.1895 | 0.1359 | 0.1764 | 0.0704 | 0.1430 ± 0.0536 |
| R1 (默认配方, 对照) | 0.2265 | 0.2437 | 0.2532 | 0.2294 | 0.2421 ± 0.0120 |

按 seed 配对 (seed 43/44): **Δ(R3pm−R1) = −3.70 / −10.78 / −7.67 pp → mean −11.45pp,
95% CI [−21.78, −1.13]** → **CI 全部在 0 以下 = 域对齐配方显著更差**。

**机理 (域差距三因子, 同一套度量 = 23 号脚本)**:

| 因子 | R1 | R3pm | 真实 | 方向 |
|---|---:|---:|---:|---|
| 框密度 (框/图) | 21.83 | 30.00 | 147.04 | 更近 ✅ |
| 平均框面积 (归一化) | 0.0053 | 0.0038 | 0.0030 | 更近 ✅ |
| 中位宽高比 | 0.3232 | 0.3007 | 1.0544 | **更远 ❌** |
| 错位商品占保留框 | 12.3% | **42.2%** | — | 副作用 |

→ 结论不是"域对齐没用"。**⚠️ 2026-11-23 晚订正**：先前这里写的是"本项目的 SDG 生成器无法正确
表达域对齐"——**这个诊断是错的**。复盘发现两件事:
  (a) R3-full 配方的"域对齐"只调了镜头/错位率/bays, **从没调过商品形状** (朝向因子);
      misalign 0.35 是**绕竖轴转 82 度** (面朝错), 只把投影宽高比从 0.353 压到 0.324 ——
      所以"朝向因子变差"是**没操作**的结果, 不是"操作了反而更糟";
  (b) 朝向因子在生成器里**是可以表达的** —— 商品箱子长宽就是参数 (PACK_W/PACK_H)。
      实测真实域逐图中位宽高比均值 **1.05** vs 合成 **0.32** (3.3 倍), 单框面积
      0.0029 vs 0.0053 (合成框大 1.8 倍) -> 形状先验 (脚本 41-43) 已把这两个量按真实域
      的经验分布采样出来。
旧 R3-full 数字 (0.182) 因不可复现而作废。"把朝向因子真的对齐过去有没有用"由 43 号
形状先验臂单独回答 (只与 R1 差一个变量)。

### 2.12h 形状先验臂 (2026-11-23 晚): 只动"朝向 + 尺度"因子的干预

**为什么有这个臂**: 2.12g 的复跑把 R3-full 的失败归到"朝向因子没被操作"✅, 而朝向因子
在生成器里**是能表达的** —— 商品箱子的长宽就是参数 (PACK_W 0.048 x PACK_H 0.136)。实测:

| 量 (SKU-110K train vs 合成) | 真实 | 合成 R1 | 倍数 |
|---|---:|---:|---:|
| 逐图中位宽高比 (逐图中位数的均值) | **1.0544** | **0.3232** | 3.3× |
| 单框面积 (占图面积比) | **0.00287** | **0.00533** | 1.9× |
| 框密度 (框/图) | 147.0 | 21.8 | 6.7× |

所以生成器缺的不是"域对齐"这个概念, 而是**商品形状的多样性**: 全池商品共用一个箱子
→ 投影宽高比被钉在 0.32。

**干预 (脚本 41-43)**: 新增 `--shape-profile real`, 按真实域的经验分布给每个商品采样
投影宽高比与投影面积:
  * 每张图先采一个"宽窄构成" m ~ 真实域**逐图中位宽高比**的经验分布 (复现真实域
    "有的货架全是扁盒、有的全是竖瓶"的图间差异);
  * 图内每个商品在中位宽高比上加对数正态抖动 (sigma 取真实域图内 log-IQR / 1.349);
  * 面积也按真实域的**单框面积分布**采样 —— 只固定面积行不通: 槽位间距 0.08 限制了盒子
    宽度, 宽盒子只能做矮盒子, 所以真实域那种"又宽又扁"的商品必须同时缩小面积才做得出来
    (2026-11-23 探针实测);
  * 目标(投影)宽高比/面积 -> 世界宽高比/面积的换算系数由**探针渲染实测** (42 号脚本):
    `gain = 1/median(投影宽高比/世界宽高比) = 1/0.8234 = 1.214`,
    `area_gain = median(投影框面积/世界正面面积) = 0.7824`; 商品世界宽度上限放宽到 0.14
    (槽位间距 0.08, 允许少量跨槽)。

**协议与对照**: 与 R1 对照集**完全相同**的配方 (cam1.0/lens28/mis0.10/bays1/200 图/
场景级留出/seed 42/同一套标签语义/同一训练协议), 只多一个形状先验 ✅ → 配对比较
Δ(R1shape − R1)。

**因子预期**: 密度因子**不动** (22 框/图), 尺度因子 0.0053 → ≈0.0029 (真实 0.0029 ✅),
朝向因子 0.32 → ≈1.0 (真实 1.05 ✅)。**判读**: 若 mAP 明显改善 → 形状/尺度确实是域差距
的一部分; 若不变 → 域差距的主因在别处 (密度 6.7× / 纹理 / 布局真实度)。

### 2.13 种子统一入口

`run_pipeline.py --seed N` → 透传给 SDG 生成 (`--seed`) 与 YOLO 训练臂 (`--seed`)。
此前: SDG 固定 42、训练臂不设种子 → 同一命令两次跑出不同结果。

---

## 3. 怎么复现四臂

```bash
# 0) 环境: SKU-110K 数据集根目录 (评测集与 split 名单, 默认不在仓内)
export SKU110K_ROOT=/path/to/SKU-110K
export SKU110K_YAML=$SKU110K_ROOT/SKU-110K.yaml     # 2026-11-21: 评测 yaml 也走 env

# 0b) 工作副本不要放在系统临时目录 (2026-11-21 实测教训):
#     Windows 的临时目录清理程序在会话中途删掉了整个工作区 (仓库副本 + 两个 venv + 补丁文件),
#     数据集因为放在 <HOME>/datasets 才幸免。源码/虚拟环境/补丁一律放稳定目录。

# 0c) 本机 (Windows) 的实际取值:
#     export SKU110K_ROOT="<SKU110K_ROOT>"
#     export SKU110K_YAML="<SKU110K_ROOT>/SKU-110K.yaml"
#     export BLENDER_PYTHON="<VENV>/Scripts/python.exe"   # 装了 bpy 的解释器
#     export BLENDER_BIN="$PWD/tools/blender.cmd"                               # bpy 替身 (Windows)

# 1) 生成 SDG 数据集 (会产出 split_manifest.json; 场景级留出默认开启)
"$BLENDER_BIN" -b -P pipelines/shelf_sdg/02_shelf_sdg_inspector.py -- \
    --num-images 20 --seed 42 --val-ratio 0.2 --split-mode scene --images-per-scene 4

# 2) 四个臂 (协议一致, 只是数据不同)
python3 pipelines/shelf_sdg/14_sku110k_baseline.py --arm r0
python3 pipelines/shelf_sdg/14_sku110k_baseline.py --arm r1 --select last   # 纯合成臂建议 last
python3 pipelines/shelf_sdg/14_sku110k_baseline.py --arm r2

# 3) 域对齐消融臂
python3 pipelines/shelf_sdg/16_sdg_ablation.py --arm R3-full

# 4) 标注预算曲线 (审计 F1: 合成到底能不能替代真实标注)
export SKU110K_YAML=/path/to/SKU-110K.yaml
python3 pipelines/shelf_sdg/21_annotation_budget.py --fracs 1,0.5,0.25 --synth 0,400 --seed 42
#    -> output/benchmark/budget_curve.json / budget_curve.md

# 5) 出报告 (含复现凭证表)
python3 pipelines/shelf_sdg/18_four_arm_report.py
```

每个臂产出 `output/benchmark/sku110k_<arm>.json`, 内含
`protocol_manifest.protocol_hash` / `checkpoint.sha256` / `dataset.sources[].fingerprint`。

**归档建议**（`output/` 在 .gitignore 里, 所以结果不会自动入仓）:
1. 跑完把 `output/benchmark/sku110k_*.json` / `count_*.json` / `domain_gap_measure.json`
   复制进 `docs/research/benchmark/` 入仓 —— 这样结果 JSON 本身有版本历史;
2. 权重 (`output/benchmark/weights/<arm>/*.pt`, 每个 ~5.6MB) 别进 git,
   但把它的 sha256 留在报告里; 论文投稿时把权重作为附件或 Zenodo 条目发布,
   审稿人就能凭 sha256 确认"跑的是同一份权重"。

---

## 4. 改造后**仍然**成立的四条限制

1. **评测集在仓外**: `SKU-110K.yaml` 与 split 名单不在仓内 → 评测集 n 与 train/test 互斥性
   仍不可由本仓核验; 报告里的 `note` 已写明。
2. **场景级留出已实现, 但场景仍是同一套模板的参数化变体** (2026-11-21):
   train/val 现在**不共享场景** (`split_manifest.json` 里 `scene_level_holdout: true`),
   每个场景在层位/上架/SKU/灯光/相机/缺陷率上各不相同;
   但所有场景仍是 `gondola_v1` 这**一套**货架模板的变体 —— 真正的店型/货架结构外推
   需要多套模板或真实店头照片。论文里只能写"场景级留出 (同一模板的参数化场景族)",
   不能写"跨店泛化"。
3. **单次运行、无方差**: 每臂一次训练 (seed=42), 2pp 阈值没有功效分析 → 显著性不可判定。
   要下"等效"结论需要多 seed 重复 (本改造已让多 seed 变得可执行: `--seed` 贯通)。
   **实测补充 (2026-11-22)**: 标注预算臂已经做到多种子 —— 5%/2% 格点与**全量真实参照物**各 3 个
   seed (42/43/44), 缺口按 seed 配对给 CI (5%: −9.92 pp, CI [−11.86, −7.98]); 计数指标也做了
   3 seed (conf 0.35)。
   **实测补充 (2026-11-24, 后补 seed 46/47)**: 已发布四臂也补了多 seed (R0/R2 各 seed 43/44/45/46/47,
   R1 补到 42) → Δ(R2−R0) 在当前协议下同 seed 配对为 +0.11 / +0.04 / +0.25 / +0.23 / +0.17 pp
   (mean +0.16, CI [+0.05, +0.26], n=5) → **CI 整段在 0 以上 (显著为正)**, 即追加合成未损害基线
   (严格说略优, 幅度 +0.16pp), 5 个 seed 差值全为正;
   Δ(R3pm−R1) 6 对配对 mean −9.92 pp, CI [−16.18, −3.67] → 域对齐配方显著更差;
   Δ(R1shape−R1) 6 对配对 mean −10.66 pp, CI [−16.48, −4.83] → 形状先验臂**显著更差** (CI 整段在 0 以下, 6/6 方向为负); **但同时查出一件更要紧的事**: 2026-11-08 那版四臂是 macOS/MPS 跑的,
   且 R1/R2 的合成数据此后换过 (旧划分 → 场景级留出) → 已发布那一对**不是协议可比的 seed 复跑**,
   "Δ = −1.77pp"只能当历史协议的观测值引用 (详见 §2.12e 与 `docs/research/AUDIT_FOUR_ARM_2026-11-18.md`)。
   **仍未闭合**: R3-full 臂仍是单次运行且协议记录与实际训练配置矛盾 (与其余臂不可比), 无复跑。
   **渲染器 GPU 通路 (2026-11-24 修复)**: SDG 渲染此前**一直跑 CPU** (38.7 s/图)。根因是三处叠加:
   (a) `FORCE_CPU_RENDER=1` 被硬编码在 `42/43/44` 号脚本里 —— 理由是"渲染时 GPU 要留给 YOLO 训练",
   但该理由只在**渲染与训练并行**时成立; 收尾链里两者**串行**, 强制 CPU 纯属白慢一倍;
   (b) `02_shelf_sdg_inspector.py` 里 **`--out` 的处理逻辑被误放在 `raycast_stats()`** (一个射线检测
   辅助函数) 里 -> `--out` 只在"第一次调用到该函数"时才生效, 而紧随其后的"清理上次遗留产物"
   循环用的是同一个被污染的 `SDG_DIR` -> **默认目录 `output/sdg_shelf` 的旧图被清空**
   (实测把 R1 对照集 200 张清成 3 张); (c) `main()` 里 `SDG_DIR` 被当**局部变量** (有赋值路径),
   产物里 `cycles_device` 字段记的是**环境变量名** (模块里根本没有该变量) -> 永远是 null。
   修完实测 (GTX 1050 Ti / OPTIX / 驱动 582.78): **GPU 18 s/图 vs CPU 38.7 s/图**。
   现在 `SDG_RENDER_DEVICE=cpu|gpu` 可显式选择, 产物 `dataset_summary.json` 记 `cycles_backend` /
   `cycles_gpu_devices` / `cycles_device`。**直接后果**: 剂量-反应扩到 2,769 张 (框量等效于
   5% 真实标注) 从"CPU 28 机时 = 不可行"变成"GPU 13 机时 = 可行"。

   **形状先验臂 (2026-11-24, 最终 n=6)**: `43_r1shape_arm.py` 做了一个与 R1 配方完全相同、只多
   `--shape-profile real` 的臂 (按真实域的投影宽高比+面积分布重采样商品长宽)。**干预确实生效**:
   逐图中位宽高比 0.3232→0.9272 (真实 1.0544)、单框面积 0.0053→0.0031 (真实 0.0030), 两个因子
   都显著靠近真实侧; **但 mAP 显著更差**: Δ(R1shape−R1) mean −10.66 pp, 95% CI [−16.48, −4.83]
   (n=6, 6/6 方向为负)。→ **"域对齐"在本项目的 SDG 生成器上走不通, 且失败原因不是"没操作到位"**。
   注: 该臂动的是**朝向+尺度两个因子**; 每图保留框 21.83→20.63 是几何干预的下游必然后果
   (可见度过滤丢弃率 0%→3.98%), 不是"干预污染了别的变量"。

   **实测补充 (2026-11-20)**: 在**完全相同配置**下连跑两次 (同 seed 42 / 同数据 / 同 epochs 2),
   产出的权重 **sha256 不同** (`f81c8a11…` vs `b6683021…`) —— 即**训练过程本身不是逐字节可复现的**
   (dataloader worker 顺序 / 增强随机 / CPU 线程调度)。
   在只有 2 张图的临时评测集上, 两次的指标恰好相同 (mAP50 0.3396), 但那只是评测集太小。
   **论文写法建议**: 报告多 seed 的均值与方差, 不要用单次运行的数字下结论;
   `protocol_hash` 锁定的是**实验设置**, 不是**训练结果** —— 两者要分开讲。
4. **计数指标仍需单独跑**: `count_*.json` 由 `17_count_eval.py` 产出, 四臂报告里并列显示,
   但不参与 `protocol_hash` (它是评测输出, 不是实验输入)。

---

## 5. 与既有审计文档的关系

- `docs/research/AUDIT_FOUR_ARM_2026-11-18.md`: F1/F3/F4/F5 已在本轮修复, 状态列已更新。
- `docs/AUDIT_CODE_2026-11-18.md` 附录 B: Windows 真机实测记录 (本轮新增 05/14/18 的验证)。


---

## 6. 冒烟验证 (不需要官方数据集)

想在没有 SKU-110K 的机器上验证"整条链 + 凭证落盘"是否通:

```bash
# 1) 生成 SDG 数据集 (产出 split_manifest.json)
"$BLENDER_BIN" -b -P pipelines/shelf_sdg/02_shelf_sdg_inspector.py -- \
    --num-images 6 --samples 32 --seed 42 --out "$PWD/output/sdg_smoke"

# 2) 造一个临时小评测集 (拿 SDG 的图冒充, 只为跑通流程, 不产生任何论文数字)
#    yaml 需要 train/val/test 三个 split 键

# 3) 跑一个臂
export SKU110K_YAML="$PWD/output/smoke_eval/dataset.yaml"
python3 pipelines/shelf_sdg/14_sku110k_baseline.py --arm r1 --epochs 2 --select last

# 4) 检查凭证
python3 -c "import json;d=json.load(open('output/benchmark/sku110k_r1.json'));\
print(d['protocol_manifest']['protocol_hash'], d['checkpoint']['sha256'])"
```

**注意**：`--out` 必须传绝对路径（脚本内部会 `abspath`，但直接调 Blender 时相对路径会被
Blender 按 blend 文件目录解析，导致图不落盘 —— 2026-11-20 实测踩过）。
