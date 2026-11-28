#!/usr/bin/env bash
# v102 伊利1L 高调生活场景早餐图 (用户参照驱动: 京东延世 Milk Talk 早餐场景)
#
# 参照: assets/reference/lifestyle_highkey_ref.png (1338x1046, md5 e8c64c10440fa2a9241bd4b67d2b8659)
# 复刻的是**风格**(高调窗光/浅景深/生活场景/静态摆拍), 产品仍为伊利1L砖盒 —
# 品牌印刷是硬约束资产, 本配方不碰 UV/贴图。
#
# 与暗调倒奶KV的关键差异:
#   POUR=0        静态摆拍, 无倒奶液柱 (参照本身没有倒奶动作)
#   LIFESTYLE=1   启用 lifestyle_scene.apply(): 浅色木桌/明亮背景/窗光/生活场景机位/早餐道具
#   RES_ASPECT    参照画幅 1.279 横向 (默认1.0=原正方形, 冻结分支零影响)
#   VIG=0.06      暗角必须降档: 默认0.30 压角会直接打爆 G1亮度/G2暗部 两道高快门
#   WALL_FIX=1    玻璃壁厚塌陷修复 (v101 已验证胜出变量, 默认关须显式给)
#
# 验收门 (见任何候选图之前冻结, 阈值来自参照实测): python3 /tmp/lifestyle_gate.py <候选图>
#   G1 亮度均值≥185 / G2 暗部<40≤0.050 / G3 高光>240≥0.167 / G4 R/G∈[1.011,1.051]
#   G5 背景/主体锐度比≤0.295 / G6 clip>250≤0.199 / G7 道具区饱和≥20 / G8 道具/主体锐度比≤0.118
#   G9a-c 品牌可读性 (深色≥0.1178 / 边缘≥3.054 / 品牌蓝≥0.0221) — 防高照度洗掉印刷
#
# 用法: bash render_1l_lifestyle.sh [draft|final]
set -e
# 仓库根 (不是脚本所在目录): LS_SPEC / 输出路径都相对仓库根解析
ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT_DIR"

MODE="${1:-final}"
# v106 版本化输出名: 原固定 lifestyle_v1 会**覆盖**上一版(与KV配方同类缺陷, 已自曝)。
# LS_TAG 显式指定版本; 不给则用时间戳, 保证任何一版都可回溯比对。
TAG="${LS_TAG:-$(date +%m%d%H%M)}"
if [ "$MODE" = "draft" ]; then
  RES=640; SAMPLES=32; OUT="lifestyle_draft_${TAG}"
else
  RES=1920; SAMPLES=256; OUT="lifestyle_${TAG}"
fi

# v103 规格驱动: 画幅/色彩/机位/灯具/摆位/约束全在 specs/lifestyle_1l.json,
# 由 scene_runtime 强制几何闸(穿模/入画/贴地)并回写实拍溯源。
# 这里只留**分支选择**开关, 不再堆数值旋钮 (原 41 个 env 是手工改的病根)。
PYTHONUNBUFFERED=1 \
ALBEDO_V67=1 \
POUR=0 \
POUR_1L=1 \
WALL_FIX=1 \
LIFESTYLE=1 \
LS_SPEC="${LS_SPEC:-$ROOT_DIR/specs/lifestyle_1l.json}" \
LS_RES="$RES" \
  "${BLENDER_BIN:-/Applications/Blender.app/Contents/MacOS/Blender}" -b -P pipelines/commercial/34_commercial_repro.py \
  -- --res "$RES" --samples "$SAMPLES" --out "$OUT"

echo "出图: output/commercial/repro_${OUT}.png"
echo "验收: python3 lifestyle_gate.py output/commercial/repro_${OUT}.png"
echo "现1L暗调KV交付图未被覆盖: output/commercial/repro_pour_1l_kv.png"