# 开源高清贴图商品资产调研 (2026-11-09, 本地 web_search × GPT relay 联网 双路合并)

## A. 商品 3D 资产 (照片级, 含贴图)
| 源 | 规模/规格 | 许可 | 零售贴合 | 核验 |
|---|---|---|---|---|
| **TexVerse** (HF, 2025-08) | 858K 模型/158K 带 PBR, 2K/4K/8K 分辨率分仓, metadata 可按 license+max_texture 筛 | 逐资产 CC (CC0 6139/CC BY 699K/NC 类 13.2 万) | ⭐⭐⭐⭐ 按包装/瓶罐/日化关键词筛 | ✅ 卡面核验 |
| **Meta DTC** (CVPR 2025) | 2000 件 digital-twin 级扫描 (杂货零售) + DSLR/AR 眼镜多光照图像序列 | CC BY-NC 4.0 (demo 可用, 商用不行) | ⭐⭐⭐⭐⭐ | ✅ GitHub 核验 |
| **ASOS/Coles** (2025-09) | 50 件真实超市商品, iPhone SfM 4032px 源, 水密 PLY, 14.6GB | 数据集页未标注, Monash bridges 下载 | ⭐⭐⭐⭐⭐ 通用品牌无版权雷 | ✅ 论文+页面核验 |
| Sketchfab CC 过滤 | 品类最全成品库, 精品 4K-8K 扫描 | CC0/CC-BY 可筛 | ⭐⭐⭐⭐ | 已知 |
| GSO / OmniObject3D / ABO / YCB / IPA-3D1K / HOPE | 各 28-8000 件, 1-2K 贴图, 物理干净 | CC 系/BY-SA | ⭐⭐⭐ 仿真备选 | 论文核验 |
| Scansmatter | 4K PBR 超市食品 | **商业授权 (排除)** | — | GPT 核验条款 |

## B. 图生 3D (对照实验, 非主路径)
- **TRELLIS.2** 官方: MIT, PBR (BaseColor/Rough/Metal), 24GB CUDA; 非官方 MPS 移植 trellis-mac (M4 Pro 24GB 可跑, 峰值 ~18GB, 512-2048 烘焙) — M1 Max 64GB 可试
- **Hunyuan3D 2.1** hy3dpaint: PBR 生成, Shape 10GB+Paint 21GB CUDA; 区域限制许可 (欧盟/英国/韩排除)
- 共同短板: **文字/条码/营养表幻觉不可信** — 只作对照组, 不进主 demo

## C. 结构与光照 (本次最大新发现)
- **PackBox Studio** (GitHub, MIT): 参数化刀模→3D 折叠工具, 支持 STD/Mailer/RSC/Tray/AutoLock, 可贴任意分辨率原创图案 → 结构 MIT + 图案自绘 = 零版权雷, 文字 100% 可控
- **Open HDRI Studio** (openhdri.org): 实物棚拍 CC0, 最高 29K EXR, Fly/Big Studio/Snoot/Cyclorama 产品摄影光型 | ✅ 页面核验
- Poly Haven (CC0 16K HDRI + 8K 材质): 环境补充

## D. GPT+本地 合并结论: demo 三件套
1. **主角**: DTC/ASOS 实扫商品 (照片级底座) + TexVerse/Sketchfab 按 license≥2K 筛出的瓶罐包装 (量)
2. **结构可控件**: PackBox 折叠纸盒 + 自绘 4K 图案 (解决文字保真, 对标我们 A 维度的正解)
3. **光照**: Open HDRI Studio CC0 棚拍 + Poly Haven 场景
管线不动: Blender Metal-RT → OpenUSD → 既有 SDG/planogram 巡检; 叙事升级为"开源实扫资产→USD 零售孪生→证据化巡检"。
