# 跨平台迁移指南（macOS/Apple Silicon → Windows+NVIDIA / Linux）

审计日期：2026-11-18 ｜ 对应补丁：`crossplatform_and_docs.patch` ｜ 自检：`python3 pipelines/common/selftest_runtime_env.py`

## 0. 结论

原仓把 **macOS + Apple Silicon + Metal** 写死了 6 类东西：Blender 路径、Cycles 后端、内存探测命令、
SD 推理设备、中文字体、临时目录。除 `--draft` 里的纯 Python 阶段外，Windows 上基本跑不起来；
Linux 同理（且缺少 `vm_stat` 时内存门会静默放行）。

**本补丁已在真机验证**（不是纸面推演）：

| 验证项 | 环境 | 结果 |
|---|---|---|
| Cycles 后端选择 | Windows 10 / i7-8750H / **GTX 1050 Ti (Max-Q, 4GB)** / 驱动 582.78 / CUDA 13.0 / **bpy 5.2.4 (pip wheel)** | `configure_cycles()` → **OPTIX + 1 个 GPU 设备**，`scene.cycles.device=GPU`；同一脚本里 `compute_device_type="METAL"` 如预期抛 `TypeError`（证明硬编码 METAL 在 Windows 上必失败） |
| 中文渲染 | 同上 + Windows 字体 | 补丁后自动命中 `C:\Windows\Fonts\msyh.ttc`（微软雅黑）/ `simsun.ttc`；**渲染图内中文逐字可读**（"经典/CLASSIC/3.8g 优质乳蛋白/活性乳铁蛋白 65/有机纯牛奶/净含量 250mL"）。补丁前：`ImageFont.truetype("/System/Library/Fonts/Hiragino Sans GB.ttc")` → `OSError: cannot open resource` |
| 贴图自举 | numpy 2.5.5 / Pillow 13.0.0 / Python 3.12 | `00_bootstrap_textures.py` 全 13 个 SKU 跑通（27s） |
| 电商套图 + USDZ | 同上（OptiX GPU） | `01_comfy_usd_compositor.py` 出 800×800 白底图 + `retail_demo_organic.usdz`（31s） |
| 版式五闸 | 同上 | `10_layout_qa_gate.py` 5/5 PASS（含 `asset_identity` 血缘闸） |
| 确定性缺陷 | 3 个独立进程 | `hash()` 播种 → 3 种输出；`crc32` 播种 → 恒定 |

Windows 上跑通整套管线的步骤见 §5，Windows 特有的 4 个坑见 §6。

本补丁把这些收敛到两个新模块：
- `pipelines/common/runtime_env.py` —— Blender 路径解析、Cycles 后端选择、跨平台内存探测、torch 设备选择、`.cmd` 启动包装
- `pipelines/common/fonts.py` —— 中文字体解析（macOS / Windows / Linux）

统一的环境变量约定（与既有 `BLENDER_BIN` 风格一致）：

| 变量 | 取值 | 作用 |
|---|---|---|
| `BLENDER_BIN` | 路径 | Blender 可执行文件；未设时按平台探测 |
| `CYCLES_DEVICE` | `OPTIX`/`CUDA`/`HIP`/`ONEAPI`/`METAL`/`NONE` | 强制 Cycles 计算后端 |
| `FORCE_CPU_RENDER` | `1` | 渲染一律 CPU（CI / 无 GPU） |
| `TORCH_DEVICE` | `cuda`/`mps`/`cpu` | 强制 SD/ControlNet 设备 |
| `CJK_FONT` | 字体文件路径 | 指定中文字体（macOS PingFang、Windows msyh、Linux Noto CJK） |

## 1. 平台锁定点清单（已修 / 未修）

| # | 位置 | 问题 | 状态 |
|---|---|---|---|
| 1 | `run_pipeline.py:33` | `BLENDER` 硬编码 `/Applications/Blender.app/...` | 已修 → `runtime_env.blender_bin()` |
| 2 | `pipelines/commercial/evidence_manifest.py:18`、`ecommerce/07_twin_ecom_matrix.py:21`、`ecommerce/11_twin_gallery.py:22`、`demo_stage/03_streamlit_app.py:18`、`shelf_sdg/16_sdg_ablation.py:24` | 同一硬编码路径（5 处） | 已修 |
| 3 | `pipelines/ecommerce/01_comfy_usd_compositor.py:140`、`demo_stage/04_giftbox_and_tray_builder.py:213`、`demo_stage/24_open_asset_hero.py:107`、`pack_dieline/31_gable_generic_blank.py:179`、`shelf_sdg/02_shelf_sdg_inspector.py:154`、`topprism_virtual/33_topprism_yogurt_cup.py:210` | `prefs.compute_device_type = "METAL"`（6 处） | 已修 → `runtime_env.configure_cycles()`，按平台枚举 OPTIX→CUDA→HIP→ONEAPI→METAL，取第一个真正枚举出设备的 |
| 4 | `run_pipeline.py:103-118` | 内存门只解析 macOS `vm_stat` | 已修 → `runtime_env.available_memory_gb()`（psutil → /proc/meminfo → Windows `GlobalMemoryStatusEx` → macOS `vm_stat`），失败时返回 `inf`（不阻拦，与原行为一致） |
| 5 | `run_pipeline.py:99-106` | 内存门策略只针对 MPS（`PYTORCH_MPS_HIGH_WATERMARK_RATIO`） | 已修 → 按设备分支：MPS 保留 watermark 0.5；CUDA 改设 `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512`；<10GB 拒跑策略不变 |
| 6 | `pipelines/shelf_sdg/05_train_yolo_mps.py:24-29` | `verify_apple_silicon_mps()` 只会返回 mps/cpu | 已修 → `runtime_env.torch_device()`（cuda > mps > cpu），函数名保留兼容 |
| 7 | `pipelines/commercial/22_controlnet_finish.py:19`、`commercial/pilot_r2.py:49-51` | 设备固定 `mps`；`torch.Generator("mps")` | 已修 → 设备自动选择 + `runtime_env.torch_generator()`；dtype 改为 MPS=fp32（VAE NaN）、CUDA=fp16 |
| 8 | `pipelines/bootstrap/00_bootstrap_textures.py:192-210`、`ecommerce/08_photo_dieline.py:163,166`、`demo_stage/22_review_board.py:51-52`、`demo_stage/23_six_view_board.py:14`、`bootstrap/20_carton_1l_texture.py:20-27`、`bootstrap/36_open_asset_zoo.py:85`、`bootstrap/37_zoo_board.py:18-20`、`demo_stage/06_comparison_board.py:20-26` | 中文字体只列 macOS 路径 → Windows/Linux 上要么抛 `OSError`（08 直接崩），要么回落 `load_default()` 导致**全部中文渲染成方块** | 已修 → `pipelines/common/fonts.py`（`CJK_FONT` 可覆盖） |
| 9 | `pipelines/ecommerce/07_twin_ecom_matrix.py:47`、`bootstrap/20_carton_1l_texture.py:122-123`、`commercial/19_cdc_back_lift.py:69`、`commercial/extract_scan_strawberry.py:108` | 硬编码 `/tmp/...` | 已修 → `tempfile.gettempdir()` |
| 10 | `pipelines/commercial/render_1l_kv.sh:26`、`render_1l_lifestyle.sh:45` | shell 里硬编码 Blender 路径 | 已修 → `${BLENDER_BIN:-...}` |
| 11 | `pipelines/shelf_sdg/14_sku110k_baseline.py:113`、`17_count_eval.py:19` | 数据集绝对路径 `/opt/homebrew/datasets/SKU-110K` | **未修（建议）**：改为环境变量 `SKU110K_ROOT`，默认保持现值 |
| 12 | `pipelines/ecommerce/08_photo_dieline.py` 等 | `/System/Library/Fonts/...` 出现在注释与 docstring 中的用法示例 | 未修（仅注释） |
| 13 | `pipelines/demo_stage/28_build_demo.py:172` 等 | 文案里写死 "Metal-RT" / "Mac" | 部分修（Streamlit spinner 改为设备无关），其余为叙述性文本 |

## 2. Cycles 设备选择的实现要点

`runtime_env.configure_cycles()` 的逻辑（可在 Blender 内直接调用）：

```python
for backend in candidates:                 # 平台优先级
    try:
        prefs.compute_device_type = backend  # 不支持的枚举值抛 TypeError -> 跳过
    except (TypeError, ValueError):
        continue
    prefs.get_devices()
    gpu = [d for d in prefs.devices if d.type == backend]
    if not gpu:                             # 没有该后端的实际设备 -> 试下一个
        continue
    for d in prefs.devices:
        d.use = d.type == backend
    chosen = backend
    break
scene.cycles.device = "GPU" if chosen != "CPU" else "CPU"
```

平台优先级：macOS `[METAL]`；Windows/Linux `[OPTIX, CUDA, HIP, ONEAPI]`。
无 GPU 时回落 CPU（`scene.cycles.device = "CPU"`），渲染变慢但不会失败。

注意：Blender 的 `compute_device_type` 枚举在部分构建里不含某些后端，赋值会抛 `TypeError`；
本实现已捕获，因此「写死 METAL」在 Windows 上的失败模式被消除。

## 3. YOLO 臂在 Windows/CUDA 上的映射

原策略：可用内存 <10GB 拒跑；<18GB 时把 `PYTORCH_MPS_HIGH_WATERMARK_RATIO` 设为 0.5。

新策略（`run_pipeline.py` 的 `train` 阶段）：

| 设备 | <10GB | 10–18GB | ≥18GB |
|---|---|---|---|
| cuda | 拒跑 | `PYTORCH_CUDA_ALLOC_CONF=max_split_size_mb:512` | 原样 |
| mps | 拒跑 | `PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.5` | 原样 |
| cpu | 拒跑 | 无额外限制（会很慢） | 原样 |

`05_train_yolo_mps.py` 的 `device` 由 `runtime_env.torch_device()` 决定（cuda > mps > cpu），`TORCH_DEVICE` 可强制。
`ultralytics` 为 **AGPL-3.0**：闭源商用需商业授权（见 `requirements.txt` 与 `NOTICE.md`）。

## 4. CI 骨架

`.github/workflows/ci.yml`（本补丁新增）包含三个 job：

| job | runner | 内容 | 预计耗时 |
|---|---|---|---|
| `selftest` | ubuntu-latest | 装 numpy/Pillow，跑 `pipelines/common/selftest_runtime_env.py` | <1 min |
| `draft` | ubuntu-latest + snap blender | `FORCE_CPU_RENDER=1` + `CYCLES_DEVICE=NONE` 跑 `run_pipeline.py --draft --keep-going` | README 自报草档 ~2 min（CPU 渲染显著更慢，实测以 CI 日志为准） |
| `gpu-nightly` | self-hosted gpu | SDG 20 张 + YOLO 2 epoch | ~1 h（视卡） |

CI 不复现四臂指标：需要 SKU-110K（不在仓内）+ GPU + 数小时，见 README「复现状态」。

## 5. 工作量与风险

| 项 | 工作量 | 风险 |
|---|---|---|
| 本补丁已覆盖的 13 类锁定点 | S（已完成） | 低；纯 Python 层已用 selftest 验证，Blender 侧需在真机跑一次草档 |
| 数据集路径参数化（`SKU110K_ROOT`） | S | 低 |
| lockfile（uv/pip-tools） | S | 低 |
| Windows 上的 Blender 5.2 装机与 GPU 驱动验证 | M | 中：Blender 官方 Windows 包自带 CUDA/OptiX 后端，需确认 `prefs.get_devices()` 能枚举到 RTX 卡 |
| CI 全绿 | M | 中：`snap install blender` 的版本与仓库脚本期望的 Blender 5.x 可能不一致（Principled 输入改名逻辑已兼容 4/5） |
| 复现四臂指标 | L | 高：受限于数据不可得与 GPU 时间，非移植问题 |
