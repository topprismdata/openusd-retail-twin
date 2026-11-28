#!/bin/bash
# v101 伊利1L 倒奶 KV — 交付配方 (双轮位置对照盲评胜出: 44/50 与 45.5/50, base 39/41.5)
#
# 关键: WALL_FIX=1 默认关(保250ml冻结分支零影响), 故交付图必须用本脚本复现,
#       直接跑 34_commercial_repro.py 得到的是带壁厚塌陷bug的旧版。
#
# 胜出原因(唯一变量): 修既有壁厚塌陷bug, 竖纹/布光/材质/构图全部保持默认
#   Solidify 2mm 壁厚先应用, 竖纹振幅缩放把内外壁一起拉向 r_mean
#   → t = 0.002*(1-FLUTE_SOFT)*sec_k, 默认0.55档实际仅 0.65~1.15mm
#   → 近零厚度壳 → Cycles 全内反射 → 读作"金属栅栏/过曝塑料"
#   WALL_FIX=1: 只缩外壁, 内壁按缩放前偏移向量重建 → 实测 p50=2.00mm
#
# 已证伪的方向(勿重复投入):
#   - 整图AI重绘(ControlNet+SD1.5): 中文100%毁成鬼画符
#   - 频率分离两图合成: GPT重画文字, 笔画不对齐
#   - 六卡反射场+光链接: 盲评 36 vs 29 净退步
#   - 竖纹软化 FLUTE_SOFT=0.85: 外壁近圆柱=柱透镜, 条纹更锐, 盲评 44 vs 38
#
# 注意: Mantaflow 每次重烘顶点数不同(实测31494/31928/31032), 无法逐位复现;
#       指标级噪声地板 glass periodic 0.001 / col_std 0.242 / 纸盒span 0.017
set -e
# 仓库根 (两个 render_*.sh 统一 cwd, 避免同类路径错位)
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"
# 输出到独立名, 不覆盖已盲评的交付图 (Mantaflow非确定性: 重渲与已评审图差~2/255,
# 交付必须保留"被评审的那张"; 要采纳新渲图须重新盲评后再手动cp)
PYTHONUNBUFFERED=1 ALBEDO_V67=1 POUR=1 POUR_LOW=1 POUR_1L=1 WALL_FIX=1 \
  "${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}" -b -P pipelines/commercial/34_commercial_repro.py \
  -- --res 1920 --samples 256 --out pour_1l_repro
echo "重渲图: output/commercial/repro_pour_1l_repro.png"
echo "现交付图(已双轮盲评44/45.5): output/commercial/repro_pour_1l_kv.png — 未被覆盖"