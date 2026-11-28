#!/usr/bin/env python3
"""
02 - 商超货架陈列仿真、异常注入与 YOLO 合成数据集 + AI 巡检仪表盘 (Mac Metal-RT)

设计对齐 5 轮自审定版:
  - 固定对象池 (Fixed Object Pool): 池子建一次, 逐图仅换材质指针/变换矩阵/可见性
    (本 demo 每图 20-40 框, persistent_data 关闭更稳; 万帧级批量才需要池+持久化, 见 README)
  - 4 类终端异常状态机: 70% 合规 / 15% 缺货 OOS / 10% 朝向错位 / 5% 竞品入侵
  - 冷柜 LED 灯带眩光 + 前沿价签条遮挡 + 背板
  - 盒体真实尺寸 48x44x136mm, 底面中心 origin, 显式 UV (与 00 atlas 契约一致)

输出:
  output/sdg_shelf/
    images/{train,val}/img_XXX.png      合成货架图
    labels/{train,val}/img_XXX.txt      YOLO 标注 (4 类状态)
    annotations/img_XXX.json            每图业务元数据 (OSA/合规率/槽位状态)
    shelf_raw_rgb.png / Retail_Shelf_Inspection_Dashboard.png   首图巡检看板
    dataset.yaml                        YOLO 训练配置 (供 05)

运行:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P 02_shelf_sdg_inspector.py -- \
      --num-images 20 --seed 42
"""
import os
import sys
import math
import time
import json
import random
import argparse

# 2026-11-24: 依赖检查**放在所有第三方 import 之前** —— 之前 numpy/PIL 的
# ModuleNotFoundError 会直接抛 traceback, 完全看不出"是你用错了解释器"。
# 本脚本需要: bpy (Blender API) + mathutils + numpy + Pillow。
# **仓库的 venv 解释器全都有** (带 bpy + Pillow + numpy 的那个);
# 系统 python 与官方 Blender 自带的 python 都没有 (2026-11-24 实测: 走官方
# blender.exe 时脚本在 `import PIL` 处就崩了, 而 blender_command() 的优先级把
# 官方安装排在 bpy wheel 之前 —— 所以**必须用 venv 解释器调用本仓库的脚本**,
# 由它经 tools/blender_shim.py 走 bpy 模块路径)。
_MISSING = []
for _mod, _hint in (
        ("bpy", "Blender 的 Python API (bpy wheel, venv 里已有)"),
        ("numpy", "数值计算 (venv 里已有)"),
        ("PIL", "PNG 读写 (Pillow, venv 里已有)")):
    try:
        __import__(_mod)
    except ModuleNotFoundError:
        _MISSING.append(f"{_mod} ({_hint})")
if _MISSING:
    raise SystemExit(
        "[SDG] 缺依赖: " + ", ".join(_MISSING) + "\n"
        "        本脚本必须用仓库的 venv 解释器运行:\n"
        f"          {sys.executable} <调用方脚本>\n"
        "        (由它经 tools/blender_shim.py 走 bpy 模块路径 —— 官方 blender.exe "
        "自带的 python 没有 Pillow/numpy。)")
import numpy as np
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
from pipelines.common.runtime_env import configure_cycles  # noqa: E402
from pipelines.common.protocol import file_sha256, sha16, write_json  # noqa: E402

TEX_DIR = os.path.join(BASE_DIR, "assets", "textures")
SDG_DIR = os.path.join(BASE_DIR, "output", "sdg_shelf")
# 实际生效的 Cycles 计算后端与 GPU 设备数 (setup_scene 填), 写进产物摘要 ——
# "这批图是 CPU 还是 GPU 渲的"必须可核验, 否则跨批次比较有隐藏混淆项。
CYCLES_RENDER_INFO = ("unknown", 0)
for sub in ("images/train", "images/val", "labels/train", "labels/val", "annotations"):
    os.makedirs(os.path.join(SDG_DIR, sub), exist_ok=True)

PACK_W, PACK_D, PACK_H = 0.048, 0.044, 0.136

UV_REGIONS = {
    "FRONT":  (60 / 2048, 1 - 1950 / 2048, 980 / 2048, 1 - 100 / 2048),
    "BACK":   (1060 / 2048, 1 - 1950 / 2048, 1980 / 2048, 1 - 100 / 2048),
    "SIDE_L": (984 / 2048, 1 - 1950 / 2048, 1022 / 2048, 1 - 100 / 2048),
    "SIDE_R": (1024 / 2048, 1 - 1950 / 2048, 1062 / 2048, 1 - 100 / 2048),
    "TOP":    (60 / 2048, 1 - 92 / 2048, 980 / 2048, 1 - 10 / 2048),
    "BOTTOM": (1060 / 2048, 1 - 92 / 2048, 1980 / 2048, 1 - 10 / 2048),
}

CLASS_MAP = {"COMPLIANT": 0, "OOS_GAP": 1, "MISALIGNED": 2, "INTRUSION": 3}
COLORS = {
    "COMPLIANT": (46, 213, 115),
    "OOS_GAP": (255, 71, 87),
    "MISALIGNED": (255, 165, 2),
    "INTRUSION": (165, 94, 234),
}
LABELS_CN = {
    "COMPLIANT": "合规",
    "OOS_GAP": "缺货(OOS)",
    "MISALIGNED": "朝向错位",
    "INTRUSION": "竞品侵入",
}

# 2026-11-24: 货架结构 (层数 / 每层排面数) 改成**运行时可配** —— 密度是域差距三因子里
# 差距最大的那个 (真实 147 框/图 vs 合成 21.8, 6.7 倍), 但它原先是硬编码常量, 根本没法
# 单独干预。默认仍是 3 层 x 10 排面 (与此前所有产物逐字节同配方)。
SHELF_LEVELS = [0.15, 0.45, 0.75]
MISALIGN_P = 0.10      # 层板顶面 z (层高 0.30m, 净空 164mm > 盒高 136mm)
LEVEL_SKUS = ["demo_jersey", "demo_organic", "demo_classic"]
N_FACINGS = 10
X_START, X_SPACING = -0.36, 0.08
RES_W, RES_H = 1440, 1080
# 密度旋钮: 额外层数与每层排面数 (0 = 用上面那套默认值)。
# 层高 0.30m 是按 3 层设计的, 加层要同时把相机拉远, 否则顶层会出画 —— 见 build_gondola/camera。
EXTRA_LEVELS = 0
EXTRA_FACINGS = 0

# 2026-11-25: **风格开关** (I-17 "真实货架墙"臂)。默认 "legacy" = 此前所有产物的
# 逐字节配方 (干净的三层金属货架 + 均匀 LED + 整齐排面)。"shelfwall" 按 63 号上下文
# 剥离探针的机制改**环境**: 有纹理的层板/背板、价签、竖向隔板(遮挡)、明暗不均的光、
# 货位有前后错位。**商品本身不动**(仍是白盒) —— 表面/几何是另外两个变量, 已各自被
# 实测否掉 (I-14 表面 -13.2 pp; 形状先验 -10.66 pp), 这里只测"上下文"这一个。
STYLE = "legacy"
# 商品贴图开关 (auto/none) —— 2026-11-25 加 (I-17 用 none 把商品表面钉回白盒)
PRODUCT_TEXTURE = "auto"


def get_mac_font(size):
    for f in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    # 2026-11-24 加护栏: 本脚本的正式调用方式是 `blender -b -P <此脚本> -- <参数>`
    # (参数在 "--" 之后; blender_shim.py 复刻了这个约定)。但如果有人直接
    # `python 02_shelf_sdg_inspector.py --num-images 200` 来跑, argv 就是空的 ->
    # **所有参数被静默忽略**, 退回默认值 (num_images=20, out=None) -> 渲染会写进
    # 默认目录 output/sdg_shelf 并**清空那里的既有产物** (2026-11-24 实测踩过:
    # R1 对照集 200 张被清成 3 张)。所以这里明确报错而不是静默用默认值。
    if not argv:
        raise SystemExit(
            "[SDG] 没有收到参数 —— 本脚本必须按 `blender -b -P <此脚本> -- <参数>` 调用, "
            "参数在 `--` 之后 (直接 `python <此脚本> --num-images N` 不会生效, "
            "且会清空默认输出目录 output/sdg_shelf)。\n"
            "        仓库内请用 42/43 号脚本 (它们通过 blender_command() 正确传参)。")
    p = argparse.ArgumentParser()
    p.add_argument("--num-images", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--out", default=None, help="SDG 输出目录覆盖 (消融臂隔离)")
    p.add_argument("--cam-mult", type=float, default=1.0, help="相机距离倍率 (A1/A2 密度尺度因子)")
    p.add_argument("--lens", type=float, default=28.0, help="镜头焦距 mm (A1/A2)")
    p.add_argument("--misalign", type=float, default=0.10, help="朝向错位概率 (A3 朝向因子)")
    p.add_argument("--bays", type=int, default=1, help="联排货架墙 bay 数 (A1b 密度因子)")
    p.add_argument("--val-ratio", type=float, default=0.2,
                   help="验证集占比 (2026-11-20 审计: 原按 idx%%5 硬切, 改为显式参数)")
    p.add_argument("--images-per-scene", type=int, default=4,
                   help="每个场景的图像数 (2026-11-20 审计 F6: 场景级留出 —— "
                        "同一场景的全部图像必须同属一个 split)")
    p.add_argument("--split-mode", choices=("scene", "image"), default="scene",
                   help="scene=场景级留出 (默认, F6 修复); image=旧的按 idx 交错切分 (仅供对照)")
    # 2026-11-23: 形状先验 (朝向因子) —— 之前所有配方都只改"摆什么/摆多少", 从没改过
    # "商品长什么样": 所有商品共用同一个箱子 (PACK_W/PACK_H), 于是投影宽高比被钉在 0.32,
    # 离真实域 (逐图中位宽高比均值 1.05) 差 3 倍。real=按真实域的形状分布采样。
    p.add_argument("--shape-profile", choices=("mono", "real"), default="mono",
                   help="mono=所有商品同形 (历史行为); real=按真实域逐图宽窄构成采样 (朝向因子)")
    p.add_argument("--shape-profile-json", default=None,
                   help="形状先验 JSON (默认 output/benchmark/real_shape_profile.json)")
    p.add_argument("--shape-aspect-gain", type=float, default=1.10,
                   help="目标投影宽高比 -> 世界宽高比的标定系数 (探针渲染实测)")
    p.add_argument("--shape-area-gain", type=float, default=0.782,
                   help="目标投影框面积 -> 世界正面面积的标定系数 (探针渲染实测)")
    p.add_argument("--shape-max-width", type=float, default=0.14,
                   help="商品世界宽度上限 (槽位间距 0.08; 允许少量跨槽 -> 真实货架也挤)")
    # 2026-11-24: 断点续渲 —— 大池任务要渲 2800 张 (约 10 机时), 中途崩一次就全废。
    # --resume 不清空输出目录, 跳过**已经渲好且三件副产物齐全**的图, 其余照渲;
    # 先核对上次落盘的 dataset_summary.json 里"这批图是用什么参数渲的", 参数不一致
    # 就直接拒绝 (否则会把两批不同配方的图拼成一批, 数据组成就不可核验了)。
    p.add_argument("--resume", action="store_true",
                   help="断点续渲: 保留已渲的图, 跳过它们, 只补缺的 (参数必须与上次一致)")
    # 2026-11-25: 风格开关 (I-17)。legacy = 此前所有产物 (逐字节一致); shelfwall =
    # 按 63 号探针的机制把**环境**改成真实货架墙 (纹理层板/价签/隔板/不匀光照/前后错位),
    # 商品本身不动。
    p.add_argument("--style", choices=("legacy", "shelfwall", "ctxwall"), default="legacy",
                   help="legacy=历史干净货架 (默认); shelfwall=真实货架墙 (I-17 上下文臂); "
                        "ctxwall=只改上下文质感 (I-18 去混淆臂, 其余与 legacy 相同)")
    # 2026-11-25: 商品贴图开关。auto = 用了工作区里就贴 (历史行为); none = 一律白盒。
    # I-17 的货架墙臂要的是"只改环境" -> 商品表面必须回到对照臂的白盒 (I-14 实测:
    # 可读印刷包装让模型把商品定义收窄, 掉 13.2 pp)。
    p.add_argument("--product-texture", choices=("auto", "none"), default="auto",
                   help="auto=有贴图就贴 (默认); none=商品一律白盒")
    return p.parse_args(argv)


def derive_layout_seed(base_seed, split, img_idx):
    """每张图的布局种子: 只由 (base_seed, split, idx) 决定。

    2026-11-20 审计修复 (audit F3):
      原实现是单条 RNG 流 `random.Random(seed)` 顺序消费, 于是
        1) 同一 idx 在 --num-images 变化时布局会变 (数据集不可逐字节复现);
        2) train/val 取自同一条流的前后片段 (idx%5), 划分不是种子互斥的。
      现在按 (split, idx) 派生独立种子: train 与 val 的随机流互不相干,
      且 img_000 的像素只取决于 (seed, split, 0), 与生成顺序/总数无关。
    """
    import hashlib
    h = hashlib.sha256(f"{base_seed}|{split}|{img_idx}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def split_for_index(img_idx, val_ratio):
    """按 val_ratio 交错分配 train/val (交错而非尾段, 保证两集都覆盖完整货架形态)。"""
    period = max(2, int(round(1.0 / max(val_ratio, 1e-6))))
    return "val" if img_idx % period == (period - 1) else "train"


# ---------------------------------------------------------------------------
# 场景级留出 (2026-11-20, 审计 F6)
#
# 原状: 全数据集只有一个场景 (scene_id 由模板+bays 哈希而来, 20 张图共用),
#       于是 train/val 只是"同一场景的抖动副本" —— 种子互斥 ≠ 场景独立。
# 现在: 场景 = 一组共享结构化参数 (上架的 bay/层位、SKU 配比、灯光、世界光、
#       相机位姿、错位率) 的图像集合; 一个场景的全部图像必属同一个 split,
#       train 与 val 的场景集合互不相交。
# ---------------------------------------------------------------------------


def derive_scene_seed(base_seed, scene_idx):
    """场景参数种子: 只由 (base_seed, scene_idx) 决定 —— 与图像总数无关。"""
    import hashlib
    h = hashlib.sha256(f"{base_seed}|scene|{scene_idx}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def derive_image_seed(base_seed, scene_idx, img_in_scene):
    """场景内逐图种子: 只由 (base_seed, scene_idx, img_in_scene) 决定。

    刻意**不**包含 split: 场景归属若因场景总数变化而调整, 图像内容仍逐字节不变,
    只有它落在 images/train 还是 images/val 会变 (清单里如实记录)。
    """
    import hashlib
    h = hashlib.sha256(f"{base_seed}|scene|{scene_idx}|img|{img_in_scene}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def scene_profiles(args):
    """构造每个场景的结构化参数 (几何/上架/光照/相机/缺陷率)。

    每个参数只由 (base_seed, scene_idx) 派生, 因此:
      - 同一 scene_idx 的场景在任何一次运行里都一样 (可复现);
      - 不同 scene_idx 的场景在几何/光照/摆货/缺陷率上都不一样 (场景多样性来源)。
    """
    n_scenes = max(1, math.ceil(args.num_images / max(1, args.images_per_scene)))
    profiles = []
    for s in range(n_scenes):
        rng = random.Random(derive_scene_seed(args.seed, s))
        n_bays_active = rng.randint(1, max(1, args.bays))
        active_bays = sorted(rng.sample(range(max(1, args.bays)), n_bays_active))
        n_levels = rng.randint(2, len(SHELF_LEVELS))
        active_levels = sorted(rng.sample(range(len(SHELF_LEVELS)), n_levels))
        sku_by_level = {lvl: LEVEL_SKUS[rng.randrange(len(LEVEL_SKUS))]
                        for lvl in range(len(SHELF_LEVELS))}
        misalign_p = round(min(0.6, max(0.0, args.misalign * rng.uniform(0.5, 1.5))), 4)
        light_color = tuple(round(v, 4) for v in (0.86 + rng.uniform(0, 0.12),
                                                  0.90 + rng.uniform(0, 0.08),
                                                  0.96 + rng.uniform(0, 0.06)))
        profile = {
            "scene_index": s,
            "active_bays": active_bays,
            "active_levels": active_levels,
            "sku_by_level": sku_by_level,
            "misalign_p": misalign_p,
            "light": {"color": list(light_color), "energy": round(rng.uniform(3.5, 7.0), 3)},
            "world_strength": round(rng.uniform(0.18, 0.34), 4),
            "camera": {"dist_mult": round(rng.uniform(0.88, 1.18), 4),
                       "height": round(rng.uniform(0.42, 0.60), 4),
                       "yaw_deg": round(rng.uniform(-4.0, 4.0), 3)},
        }
        profile["scene_id"] = sha16(profile)[:12]
        profiles.append(profile)
    return profiles


def assign_scene_splits(profiles, val_ratio, base_seed, scene_sizes=None):
    """把场景分配到 train/val: 按图像数逼近目标比例, 场景集合互不相交。

    - 目标: val 的**图像数**尽量接近 val_ratio * 总图像数 (只按场景数取整会让
      最后一个不足一个场景容量的残余场景把比例带偏 —— 例如 5 张图 / 每场景 4 张
      时"按场景数取 1 个"会得到 4 张 val = 80%);
    - 选法: 贪心 —— 先按"离剩余目标差多少"排序, 逐个加入不超过目标的场景;
      最后再看再加一个场景是否更接近目标;
    - 平局用场景 id 哈希决定 → 完全确定, 与图像顺序无关;
    - 至少 1 个 val 场景、1 个 train 场景。
    """
    n = len(profiles)
    sizes = dict(scene_sizes or {})
    if n < 2:
        return ({p["scene_index"]: "train" for p in profiles},
                {"n_scenes": n, "n_val_scenes": 0,
                 "note": "场景数 <2, 无法做场景级留出 (train/val 会共享场景)"})
    total_images = sum(sizes.get(p["scene_index"], 0) for p in profiles)
    target = total_images * val_ratio
    ordered = sorted(profiles, key=lambda p: sha16({"assign": base_seed, "scene_id": p["scene_id"]}))

    def size(p):
        return sizes.get(p["scene_index"], 0)

    chosen, acc = [], 0
    remaining = ordered[:]
    while remaining and len(chosen) < n - 1:
        remaining.sort(key=lambda p: (abs(size(p) - (target - acc)), size(p)))
        cand = remaining.pop(0)
        if size(cand) <= (target - acc) or not chosen:
            chosen.append(cand)
            acc += size(cand)
        else:
            continue
    # 再加一个场景是否更接近目标?
    if remaining and len(chosen) < n - 1:
        remaining.sort(key=lambda p: (abs(size(p) - (target - acc)), size(p)))
        cand = remaining[0]
        if abs((acc + size(cand)) - target) < abs(acc - target):
            chosen.append(cand)
            acc += size(cand)

    val_ids = {p["scene_id"] for p in chosen}
    split_of = {p["scene_index"]: ("val" if p["scene_id"] in val_ids else "train")
                for p in profiles}
    return split_of, {"n_scenes": n, "n_val_scenes": len(chosen),
                      "val_images": acc, "total_images": total_images,
                      "val_image_ratio": (round(acc / total_images, 4) if total_images else None),
                      "target_images": round(target, 2),
                      "val_scene_ids": sorted(val_ids)}


def apply_scene_profile(scene, cam, world, pool, profile, args):
    """把场景参数落到 Blender 场景上 (灯光/世界光/相机取景)。"""
    for o in bpy.data.objects:
        if o.type == "LIGHT":
            o.data.color = tuple(profile["light"]["color"])
            o.data.energy = profile["light"]["energy"]
    bg = world.node_tree.nodes["Background"]
    # 货架之外的世界颜色: legacy 是明亮的蓝灰 (假背景)。shelfwall/ctxwall 把它换成
    # 暗的店内环境 —— 注意**必须在这里改**: 逐场景的 apply_scene_profile 会覆盖
    # main() 里设的世界颜色 (只在这里设等于没改, I-17 实测证实: 画面外围仍是亮蓝灰)。
    if args.style in ("shelfwall", "ctxwall"):
        bg.inputs[0].default_value = (0.22, 0.22, 0.24, 1.0)
    else:
        bg.inputs[0].default_value = (*profile["light"]["color"], 1.0)
    bg.inputs[1].default_value = profile["world_strength"]

    xs = [it["base_x"] for it in pool
          if it.get("bay") in profile["active_bays"] and it.get("lvl") in profile["active_levels"]]
    cam_x = (sum(xs) / len(xs)) if xs else 0.0
    c = profile["camera"]
    cam.location = (cam_x,
                    -1.05 * args.cam_mult * c["dist_mult"],
                    c["height"])
    cam.rotation_euler = (math.radians(88), 0, math.radians(c["yaw_deg"]))
    bpy.context.view_layer.update()


def assign_box_uv(obj, w, d, h):
    # Blender 5.x primitive cube 自带默认 UVMap 层, 必须写入第 0 层 (active_render)
    mesh = obj.data
    uvl = mesh.uv_layers[0] if len(mesh.uv_layers) else mesh.uv_layers.new(name="atlas")
    for poly in mesh.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 1:
            region = UV_REGIONS["FRONT"] if n.y < 0 else UV_REGIONS["BACK"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vz = mesh.vertices[vi].co.x, mesh.vertices[vi].co.z
                uvl.data[li].uv = (region[0] + (vx / w + 0.5) * (region[2] - region[0]),
                                   region[1] + (vz / h) * (region[3] - region[1]))
        elif ax == 0:
            region = UV_REGIONS["SIDE_L"] if n.x < 0 else UV_REGIONS["SIDE_R"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vy, vz = mesh.vertices[vi].co.y, mesh.vertices[vi].co.z
                uvl.data[li].uv = (region[0] + (vy / d + 0.5) * (region[2] - region[0]),
                                   region[1] + (vz / h) * (region[3] - region[1]))
        else:
            region = UV_REGIONS["TOP"] if n.z > 0 else UV_REGIONS["BOTTOM"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vy = mesh.vertices[vi].co.x, mesh.vertices[vi].co.y
                uvl.data[li].uv = (region[0] + (vx / w + 0.5) * (region[2] - region[0]),
                                   region[1] + (vy / d + 0.5) * (region[3] - region[1]))


def create_material_for_sku(sku_key):
    mat = bpy.data.materials.new(f"ShelfMat_{sku_key}")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.35
    albedo_p = os.path.join(TEX_DIR, f"{sku_key}_albedo.png")
    orm_p = os.path.join(TEX_DIR, f"{sku_key}_orm.png")
    if PRODUCT_TEXTURE == "none":
        # I-17: 一律白盒 (对照臂的商品表面) —— 只改环境
        albedo_p = orm_p = None
    if albedo_p and os.path.exists(albedo_p):
        tc = nodes.new("ShaderNodeTexImage")
        tc.image = bpy.data.images.load(albedo_p)
        links.new(tc.outputs["Color"], bsdf.inputs["Base Color"])
    if orm_p and os.path.exists(orm_p):
        to = nodes.new("ShaderNodeTexImage")
        to.image = bpy.data.images.load(orm_p)
        to.image.colorspace_settings.name = "Non-Color"
        sep = nodes.new("ShaderNodeSeparateColor")
        links.new(to.outputs["Color"], sep.inputs["Color"])
        links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    return mat


def setup_scene(samples):
    global CYCLES_RENDER_INFO
    scene = bpy.context.scene
    CYCLES_RENDER_INFO = configure_cycles(scene=scene, samples=samples, denoise=True)
    scene.render.use_persistent_data = False   # 逐图 hide_render 切换, 持久化会吃到陈旧状态
    scene.render.resolution_x, scene.render.resolution_y = RES_W, RES_H


def make_noisy_material(name, base_color, noise_scale=18.0, dark=0.55,
                        rough=0.45, bump=0.15):
    """带程序化斑驳纹理的材质 (真实货架的层板/背板不是纯色)。

    63 号探针显示真实照片的"框外像素"(货架纹理/背板/价签) 值 22.76 pp —— 本仓此前的
    渲染是**纯色金属 + 纯色背板**, 这正是要改的那部分。噪声用 Blender 的 Noise
    Texture -> ColorRamp -> Base Color, 另加 Bump 让高光有起伏。
    """
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = rough
    tex = nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = noise_scale
    tex.inputs["Detail"].default_value = 6.0
    tex.inputs["Roughness"].default_value = 0.7
    ramp = nodes.new("ShaderNodeValToRGB")
    c0 = tuple(min(1.0, c * dark) for c in base_color[:3]) + (1.0,)
    c1 = tuple(min(1.0, c * (2.0 - dark)) for c in base_color[:3]) + (1.0,)
    ramp.color_ramp.elements[0].position = 0.35
    ramp.color_ramp.elements[0].color = c0
    ramp.color_ramp.elements[1].position = 0.68
    ramp.color_ramp.elements[1].color = c1
    links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bmp = nodes.new("ShaderNodeBump")
    bmp.inputs["Strength"].default_value = bump
    links.new(tex.outputs["Fac"], bmp.inputs["Height"])
    links.new(bmp.outputs["Normal"], bsdf.inputs["Normal"])
    return mat


def add_cubes_merged(name, locations, scale, mat):
    """把多个同尺寸小立方体合成**一个** mesh 对象 (纯装饰: 价签行 / 隔板行)。

    为什么必须合并: 渲染器给每个标注商品做 32×32 的**像素级可见性射线检测**
    (raycast_stats), 而 Blender 的 ray_cast 会遍历场景里的**所有**对象 -> 场景对象数
    线性放大渲染时间。实测: 加了 174 个装饰立方体后, 单张从 ~18 s 变成 ~80-100 s
    (4-5 倍, 与对象数倍率一致)。合并成 1 个对象后视觉完全一样, 时间回到原量级。
    """
    bpy.ops.object.select_all(action="DESELECT")
    objs = []
    for loc in locations:
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
        o = bpy.context.active_object
        o.scale = scale
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        objs.append(o)
    if not objs:
        return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.join()
    merged = bpy.context.active_object
    merged.name = name
    if mat is not None:
        merged.data.materials.append(mat)
    return merged


def build_shelfwall(n_bays):
    """I-17 的"真实货架墙"环境 (63 号探针机制: 上下文值 22.76 pp)。

    与 legacy 的差别**只在环境**, 商品白盒完全不动:
      * 层板/背板: 程序化斑驳纹理 (不是纯色金属)
      * 前沿价签条: 保留黄条 + 加一排白色小价签 (不可读, 只是"有东西"的杂乱)
      * 竖向隔板: 每个排面之间立一片薄板 -> 商品被部分遮挡 (真实货架如此)
      * 光照: 每层 LED 能量不均 + 一盏偏暖的侧光 -> 明暗不均 (不是均匀棚拍)
    """
    metal = make_noisy_material("ShelfWornMetal", (0.17, 0.18, 0.20),
                                noise_scale=26.0, dark=0.5, rough=0.42)
    back_mat = make_noisy_material("ShelfBackPanel", (0.30, 0.28, 0.26),
                                    noise_scale=9.0, dark=0.6, rough=0.75)
    tag_mat = bpy.data.materials.new("YellowPriceRail")
    tag_mat.use_nodes = True
    tag_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.95, 0.78, 0.12, 1)
    label_mat = bpy.data.materials.new("PriceLabelPaper")
    label_mat.use_nodes = True
    lm = label_mat.node_tree.nodes["Principled BSDF"]
    lm.inputs["Base Color"].default_value = (0.92, 0.92, 0.90, 1)
    lm.inputs["Roughness"].default_value = 0.8

    for bay in range(n_bays):
        off = bay * BAY_W
        # 背板 (瓦楞纸/塑料背板的暖灰)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(off, 0.13, 0.50))
        back = bpy.context.active_object
        back.scale = (1.10, 0.02, 1.10)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        back.data.materials.append(back_mat)
        for z in SHELF_LEVELS:
            # 层板 (磨损金属)
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(off, 0.0, z - 0.008))
            board = bpy.context.active_object
            board.scale = (1.04, 0.24, 0.016)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            board.data.materials.append(metal)
            # 前沿黄色价签条
            bpy.ops.mesh.primitive_cube_add(size=1.0, location=(off, -0.118, z - 0.010))
            tag = bpy.context.active_object
            tag.scale = (1.00, 0.008, 0.032)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            tag.data.materials.append(tag_mat)
            # 一排白色小价签 (贴黄条前面) —— 真实货架的"杂乱"的一部分
            # (整排合成一个 mesh: 见 add_cubes_merged 的说明 —— 对象数线性放大渲染时间)
            n_lab = int(1.00 / 0.055)
            lab_specs = [(off - 0.50 + 0.028 + i * 0.055, -0.1235, z - 0.010)
                         for i in range(n_lab)]
            add_cubes_merged(f"PriceLabels_{off}_{z}", lab_specs, (0.038, 0.002, 0.022), label_mat)
            # 竖向隔板: 每个排面之间一片薄板 -> 两侧商品被部分遮挡 (同样合成一个 mesh)
            div_specs = [(off + X_START - X_SPACING / 2 + i * X_SPACING, 0.0, z + 0.09)
                         for i in range(N_FACINGS + 1)]
            add_cubes_merged(f"Dividers_{off}_{z}", div_specs, (0.006, 0.20, 0.18), metal)
            # 层下 LED: 能量逐层不同 (顶灯衰减不均) + 颜色略偏冷
            bpy.ops.object.light_add(type="AREA", location=(off, -0.05, z + 0.275))
            led = bpy.context.active_object
            led.data.shape = "RECTANGLE"
            led.data.size = 0.85
            led.data.size_y = 0.04
            led.data.energy = 5.0 * (1.0 - 0.18 * (SHELF_LEVELS.index(z) / max(1, len(SHELF_LEVELS) - 1)))
            led.data.color = (0.92, 0.96, 1.0)
    # 一盏偏暖的侧光 (真实店里的顶灯/侧灯不均匀)
    bpy.ops.object.light_add(type="AREA", location=(-0.55, -0.55, 1.25))
    fill = bpy.context.active_object
    fill.data.shape = "RECTANGLE"
    fill.data.size = 1.2
    fill.data.size_y = 0.8
    fill.data.energy = 12.0
    fill.data.color = (1.0, 0.93, 0.82)


def build_ctxwall(n_bays):
    """I-18 "上下文质感"臂 (去混淆版): **只改环境质感**, 其余与 legacy 逐项相同。

    与 legacy 的差别**只有这四项**:
      * 背板: 纯色金属 -> 程序化斑驳 (真实货架背板不是纯色)
      * 前沿价签条: 加一排白色小价签 (不可读, 只制造"杂乱"的上下文)
      * 竖向隔板: 每个排面之间立一片薄板 (立在商品**后面**, 不遮挡商品)
      * 货架之外: 亮蓝灰假背景 -> 暗的店内环境
    **保持不变**: 相机 (cam_mult 1.0 / bays 1) 、商品白盒与摆位/朝向、密度 (10 排面/层)、
    每层 LED 灯带与能量、商品材质。 —— 所以它与 legacy 的差异**只有上下文**。

    为什么需要它: I-17 ("真实货架墙"臂) 把环境、相机、密度、光照一起改了, 结果真实域
    mAP50 从 0.253 崩到 0.007 —— 那个结果**分不清**是"上下文质感"还是"别的东西"
    (最可能是正面平光把商品拍成了扁平白板, 模型学成了"找扁平竖条")。
    """
    build_gondola(noisy_back=True)

    metal = make_noisy_material("ShelfWornMetal", (0.17, 0.18, 0.20),
                                noise_scale=26.0, dark=0.5, rough=0.42)
    label_mat = bpy.data.materials.new("PriceLabelPaper")
    label_mat.use_nodes = True
    lm = label_mat.node_tree.nodes["Principled BSDF"]
    lm.inputs["Base Color"].default_value = (0.92, 0.92, 0.90, 1)
    lm.inputs["Roughness"].default_value = 0.8

    for z in SHELF_LEVELS:
        # 一排白色小价签 (贴黄条前面) —— 合成一个 mesh (对象数线性放大渲染时间)
        n_lab = int(1.00 / 0.055)
        lab_specs = [(-0.50 + 0.028 + i * 0.055, -0.1235, z - 0.010) for i in range(n_lab)]
        add_cubes_merged(f"PriceLabels_{z}", lab_specs, (0.038, 0.002, 0.022), label_mat)
        # 竖向隔板: 立在商品**后面**、且**不高于商品** (高 0.13 < 商品高 0.136) ——
        # 否则从上方俯视的层板 (相机 z≈0.50, 下层 z=0.15) 会被隔板挡掉商品上半身,
        # 可见面积掉到 15% 以下 -> 商品被"可见性过滤"整排丢掉 (实测: 下层 10 个
        # 槽位全丢)。这里必须让隔板不改变商品的可见性, 否则就不是"只改上下文"。
        div_specs = [(X_START - X_SPACING / 2 + i * X_SPACING, 0.10, z + 0.065)
                     for i in range(N_FACINGS + 1)]
        add_cubes_merged(f"Dividers_{z}", div_specs, (0.006, 0.05, 0.13), metal)


def build_gondola(noisy_back=False):
    """冷柜: 背板 + 3 层金属层板 + 前沿价签条 + 层下 LED 灯带

    noisy_back=True (I-18 的 ctxwall): 背板换成程序化斑驳材质 —— **只改背板表面**,
    层板/价签条/灯光/相机/商品摆位全部保持 legacy 原样 (见 build_ctxwall)。
    """
    metal = bpy.data.materials.new("ShelfDarkMetal")
    metal.use_nodes = True
    b = metal.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.14, 0.15, 0.17, 1)
    b.inputs["Roughness"].default_value = 0.35

    tag_mat = bpy.data.materials.new("YellowPriceRail")
    tag_mat.use_nodes = True
    tag_mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.95, 0.78, 0.12, 1)

    # 背板 (scale=全尺寸: size-1 cube verts ±0.5, 全宽 1.10m 覆盖 z -0.05..1.05)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0.13, 0.50))
    back = bpy.context.active_object
    back.scale = (1.10, 0.02, 1.10)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    back.data.materials.append(
        make_noisy_material("ShelfBackPanelWorn", (0.30, 0.28, 0.26),
                            noise_scale=9.0, dark=0.6, rough=0.75)
        if noisy_back else metal)

    for z in SHELF_LEVELS:
        # 层板 (全宽 1.04m, 全深 0.24m, 顶面= z)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0.0, z - 0.008))
        board = bpy.context.active_object
        board.scale = (1.04, 0.24, 0.016)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        board.data.materials.append(metal)
        # 前沿黄色价签条 (真实底部遮挡干扰; 顶面高出层板 6mm)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, -0.118, z - 0.010))
        tag = bpy.context.active_object
        tag.scale = (1.00, 0.008, 0.032)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        tag.data.materials.append(tag_mat)
        # 层下 LED 冷白灯带 (包装顶部真实眩光; 与上层板底留 9mm 间隙防穿插)
        bpy.ops.object.light_add(type="AREA", location=(0, -0.05, z + 0.275))
        led = bpy.context.active_object
        led.data.shape = "RECTANGLE"
        led.data.size = 0.85
        led.data.size_y = 0.04
        led.data.energy = 5.0
        led.data.color = (0.92, 0.96, 1.0)


BAY_W = 1.06


def replicate_bays(n_bays):
    """把首个 bay 的结构对象沿 x 复制 n_bays-1 次 (A1b 密度因子)。"""
    if n_bays <= 1:
        return
    struct = [o for o in bpy.data.objects if o.name.startswith(("Cube", "Area", "Plane"))
              and o.type in {"MESH", "LIGHT"}]
    for k in range(1, n_bays):
        for o in struct:
            d = o.copy()
            if o.data:
                d.data = o.data.copy()
            d.location.x += k * BAY_W
            bpy.context.collection.objects.link(d)


def build_pool(n_bays=1):
    """固定对象池: 3 层 x 10 排面, 建一次; 逐图仅改材质/变换/可见性"""
    mats = {sku: create_material_for_sku(sku) for sku in LEVEL_SKUS}
    intruder = bpy.data.materials.new("Competitor_Blue")
    intruder.use_nodes = True
    intruder.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.08, 0.25, 0.85, 1)
    intruder.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.4
    mats["intruder"] = intruder

    pool = []
    for lvl_idx, z_base in enumerate(SHELF_LEVELS):
        for bay in range(n_bays):
            for slot_i in range(N_FACINGS):
                if STYLE == "shelfwall":
                    # I-17: shelfwall 的每个 bay 的结构是 build_shelfwall 自己建的
                    # (第 k 个 bay 的中心在 k*BAY_W) -> 商品也按同一个基准摆, 否则
                    # 第 2 个 bay 的商品会落在自己层板的左边 0.26 m (legacy 的
                    # replicate_bays 是"复制结构", 商品坐标另算, 两者本来就有偏移)。
                    bx = bay * BAY_W + X_START + slot_i * X_SPACING
                else:
                    bx = X_START + (slot_i + bay * N_FACINGS) * X_SPACING
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(bx, -0.03, z_base))
                box = bpy.context.active_object
                box.name = f"Pool_L{lvl_idx}_S{slot_i}"
                box.scale = (PACK_W, PACK_D, PACK_H)
                # 显式只烘焙缩放: transform_apply 默认 location/rotation=True 会把
                # 创建位置烘进网格, 再赋 location 即双重位移 (渲染飞出+bound_box 世界化)
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                # origin 移到底面中心
                from mathutils import Matrix
                box.data.transform(Matrix.Translation((0, 0, PACK_H / 2)))
                box.location = (bx, -0.03, z_base)
                bev = box.modifiers.new("Bevel", "BEVEL")
                bev.width = 0.003
                bev.segments = 2
                try:
                    bpy.ops.object.shade_smooth()
                    bpy.ops.object.shade_auto_smooth(angle=math.radians(40))
                except AttributeError:
                    pass
                assign_box_uv(box, PACK_W, PACK_D, PACK_H)
                box.data.materials.append(mats[LEVEL_SKUS[lvl_idx]])
                pool.append({"obj": box, "lvl": lvl_idx, "slot": slot_i + bay * N_FACINGS,
                             "bay": bay,
                             "planned_sku": LEVEL_SKUS[lvl_idx], "base_x": bx})
    return pool, mats


class ShapeSampler:
    """按真实域的形状分布给每张图/每个商品采样**投影宽高比与投影面积** (2026-11-23)。

    为什么需要它: 此前所有 SDG 配方 (含"域对齐"配方) 都只调"摆什么/摆多少/镜头",
    **从没调过商品本身的长宽** —— 全池商品共用 PACK_W x PACK_H, 于是投影宽高比被钉在
    0.32 左右, 而真实域逐图中位宽高比的均值是 1.05 (p10 0.38 / p90 1.92)。
    "朝向因子"其实是在生成器里**可以表达**的, 只是没被操作。

    采样方式 (与真实域同构):
      * 每张图先采一个"宽窄构成" m ~ 真实域逐图中位宽高比的经验分布;
      * 图内每个商品在中位宽高比上加对数正态抖动 (尺度取真实域图内 log-IQR);
      * **面积也按真实域的单框面积分布采样** —— 只固定面积是行不通的: 槽位间距 0.08
        限制了盒子宽度, 宽盒子只能做矮盒子 (否则要占邻居的槽位), 所以真实域那种
        "又宽又扁"的商品必须靠**同时**缩小面积才做得出来 (2026-11-23 探针实测)。
      * 于是这次干预同时动**朝向因子与尺度因子**两个 (密度因子不动) —— 报告里
        必须写清这一点, 不能说成"只动朝向"。

    标定: 目标(投影)宽高比/面积 -> 世界宽高比/面积的换算系数由探针实测 (42 号脚本),
    这里用 --shape-aspect-gain / --shape-area-gain 传入。
    """

    def __init__(self, profile_path, gain=1.10, area_gain=0.782, max_width=0.14):
        with open(profile_path, "r", encoding="utf-8") as fh:
            prof = json.load(fh)
        real = prof["real"]
        self._im = real["per_image_median_aspect"]
        self._iqr = real["within_image_log_iqr"]["mean"]
        self._area = real["per_box_area"]
        self._curve = self._qcurve(self._im)
        self._area_curve = self._qcurve(self._area)
        self._sigma = self._iqr / 1.349 if self._iqr > 0 else 0.0
        self.gain = gain
        self.area_gain = area_gain
        self.max_width = max_width
        self.n_sampled = 0

    @staticmethod
    def _qcurve(table):
        """分位数表 -> [(分位, 取值)] (供反 CDF 插值)。"""
        out = []
        for k, v in table.items():
            if k.startswith("p") and isinstance(v, (int, float)):
                out.append((float(k[1:]) / 100.0, float(v)))
        out.sort()
        return out

    @staticmethod
    def _inv_cdf(curve, u):
        """按分位数表反 CDF 采样 (线性插值)。"""
        if not curve:
            return 0.0
        if u <= curve[0][0]:
            return curve[0][1]
        if u >= curve[-1][0]:
            return curve[-1][1]
        for (q0, v0), (q1, v1) in zip(curve, curve[1:]):
            if q0 <= u <= q1:
                t = (u - q0) / (q1 - q0) if q1 > q0 else 0.0
                return v0 + t * (v1 - v0)
        return curve[-1][1]

    def _sample_image_median(self, rng):
        return self._inv_cdf(self._curve, rng.random())

    def scales_for(self, rng, n):
        """返回 n 个商品的 (sx, sy, sz) 物体缩放系数 (相对 PACK_W/PACK_D/PACK_H)。"""
        m = self._sample_image_median(rng)
        out = []
        for _ in range(n):
            a_proj = max(0.08, m * math.exp(rng.gauss(0.0, self._sigma)))
            area_proj = self._inv_cdf(self._area_curve, rng.random())
            a_world = a_proj * self.gain
            area_world = area_proj / self.area_gain
            w = math.sqrt(area_world * a_world)
            h = area_world / w if w > 0 else PACK_H
            d = w * (PACK_D / PACK_W)
            if w > self.max_width:   # 槽位间距 0.08; 允许少量跨槽 (真实货架也挤)
                f = self.max_width / w
                w *= f
                d *= f
                h /= f
            out.append((w / PACK_W, d / PACK_D, h / PACK_H))
        self.n_sampled += 1
        return out


def layout_image(pool, mats, rng, profile=None, shape=None):
    """状态机注入 + 返回本图标注记录 (OOS 槽位保留投影坐标)

    profile 非空时 (场景级留出模式) 只摆 profile 指定的 bay/层位, SKU 配比与错位率
    也取自该场景 —— 于是不同场景的图在几何/摆货/缺陷分布上确实不同。

    shape 非空 (ShapeSampler) 时按真实域形状分布给每个商品采样长宽 -> 朝向因子。
    """
    records = []
    active_bays = set(profile["active_bays"]) if profile else None
    active_levels = set(profile["active_levels"]) if profile else None
    sku_by_level = profile["sku_by_level"] if profile else None
    misalign_p = profile["misalign_p"] if profile else MISALIGN_P
    # 形状先验: 只对"这一图会渲染出来"的槽位采样 (被场景过滤掉的槽位不用管)
    if shape is not None:
        visible = [it for it in pool
                   if active_bays is None or (it.get("bay") in active_bays
                                              and it.get("lvl") in active_levels)]
        scales = shape.scales_for(rng, len(visible))
        shape_map = {id(it["obj"]): s for it, s in zip(visible, scales)}
    else:
        shape_map = {}
    for item in pool:
        if active_bays is not None:
            if item.get("bay") not in active_bays or item.get("lvl") not in active_levels:
                item["obj"].hide_render = True     # 该场景不上这排/这层
                continue
        roll = rng.random()
        if roll < 0.15:
            status = "OOS_GAP"
        elif roll < 0.15 + misalign_p:
            status = "MISALIGNED"
        elif roll < 0.15 + misalign_p + 0.05:
            status = "INTRUSION"
        else:
            status = "COMPLIANT"

        box = item["obj"]
        # 形状先验: 物体级缩放 (网格已把 PACK_W/PACK_H 烘进顶点, 这里改物体缩放即可)
        sc = shape_map.get(id(box))
        if sc is not None:
            box.scale = sc
        if STYLE == "shelfwall":
            # I-17: 货位不再是一排整齐的等距盒子 —— 前后错位 + 侧向错位 -> 商品之间
            # 互相部分遮挡 (真实货架墙的常态), 也让"框外像素"里有邻居的轮廓。
            bx = item["base_x"] + rng.uniform(-0.012, 0.012)
            by = -0.03 + rng.uniform(-0.016, 0.010)
            bz = SHELF_LEVELS[item["lvl"]] + rng.uniform(-0.002, 0.002)
        else:
            bx = item["base_x"] + rng.uniform(-0.004, 0.004)
            by = -0.03 + rng.uniform(-0.004, 0.004)
            bz = SHELF_LEVELS[item["lvl"]]
        box.location = (bx, by, bz)
        sku = sku_by_level[item["lvl"]] if sku_by_level else item["planned_sku"]

        if status == "OOS_GAP":
            box.hide_render = True
            box.rotation_euler = (0, 0, 0)
        elif status == "MISALIGNED":
            box.hide_render = False
            box.rotation_euler = (0, 0, math.radians(82 + rng.uniform(-5, 5)))
            box.data.materials[0] = mats[sku]
        elif status == "INTRUSION":
            box.hide_render = False
            box.rotation_euler = (0, 0, math.radians(rng.uniform(-4, 4)))
            box.data.materials[0] = mats["intruder"]
        else:
            box.hide_render = False
            box.rotation_euler = (0, 0, math.radians(rng.uniform(-3.5, 3.5)))
            box.data.materials[0] = mats[sku]

        records.append({
            "obj": box, "sku": sku, "status": status,
            "level": item["lvl"] + 1, "slot": item["slot"] + 1,
            "class_id": CLASS_MAP[status],
        })
    return records


def project_bbox(scene, cam, obj, w, h):
    """8 顶点世界投影取极值 (bevel 内缩量 ~3mm 忽略; 像素级 Cryptomatte 掩膜见 README 扩展位)"""
    pts = [world_to_camera_view(scene, cam, obj.matrix_world @ Vector(c)) for c in obj.bound_box]
    xs = [p.x * w for p in pts]
    ys = [(1.0 - p.y) * h for p in pts]
    x1, y1, x2, y2 = max(0, int(min(xs))), max(0, int(min(ys))), min(w, int(max(xs))), min(h, int(max(ys)))
    if x2 < x1 or y2 < y1:
        print(f"[DegBBox] {obj.name} loc={tuple(round(v,3) for v in obj.matrix_world.translation)} "
              f"xs={tuple(round(v,1) for v in xs)} ys={tuple(round(v,1) for v in ys)} "
              f"cam={tuple(round(v,3) for v in cam.matrix_world.translation)}")
        x1, x2 = min(x1, x2), max(x1, x2)
        y1, y2 = min(y1, y2), max(y1, y2)
    return (x1, y1, x2, y2)


def write_dataset_yaml():
    lines = [
        f"path: {SDG_DIR}",
        "train: images/train",
        "val: images/val",
        "names:",
        "  0: COMPLIANT",
        "  1: OOS_GAP",
        "  2: MISALIGNED",
        "  3: INTRUSION",
    ]
    with open(os.path.join(SDG_DIR, "dataset.yaml"), "w") as f:
        f.write("\n".join(lines))


def main():
    # SDG_DIR 是模块级全局 (write_dataset_yaml 等其它函数也读它) —— 这里显式声明,
    # 否则 Python 会把本函数里对它的赋值当成**局部变量**, 读到未赋值就 UnboundLocalError。
    global SDG_DIR
    args = parse_args()
    manifest_entries = []
    # 形状先验 (朝向因子): profile=real 时按真实域形状分布采样商品长宽
    shape_sampler = None
    if args.shape_profile == "real":
        sj = args.shape_profile_json or os.path.join(
            BASE_DIR, "output", "benchmark", "real_shape_profile.json")
        if not os.path.exists(sj):
            raise SystemExit(f"[SDG] 形状先验 JSON 不存在: {sj} (先跑 41_real_shape_profile.py)")
        shape_sampler = ShapeSampler(sj, gain=args.shape_aspect_gain,
                                     area_gain=args.shape_area_gain,
                                     max_width=args.shape_max_width)
        print(f"[SDG] 形状先验: {sj} (gain={args.shape_aspect_gain}, "
              f"area_gain={args.shape_area_gain}, max_width={args.shape_max_width}, "
              f"图内 log-IQR={shape_sampler._iqr}, sigma={shape_sampler._sigma:.3f})")
    # 2026-11-20 审计 F6: 场景级留出 —— 场景参数只由 (base_seed, scene_idx) 派生;
    # 一个场景的全部图像同属一个 split, train/val 的场景集合互不相交。
    profiles = scene_profiles(args)
    legacy_scene_id = sha16({"template": "gondola_v1", "bays": args.bays, "cam_mult": args.cam_mult,
                              "lens": args.lens, "misalign": args.misalign,
                              "style": args.style,
                              "res": [RES_W, RES_H]})[:12]
    if args.split_mode == "scene":
        ips = max(1, args.images_per_scene)
        scene_sizes = {s: max(0, min(ips, args.num_images - s * ips))
                       for s in range(len(profiles))}
        split_of, split_info = assign_scene_splits(profiles, args.val_ratio, args.seed, scene_sizes)
    else:
        split_of = {}
        split_info = {"n_scenes": len(profiles), "n_val_scenes": None,
                      "note": "--split-mode image: 旧行为 (按 idx 交错切分), 不做场景级留出"}

    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_scene(args.samples)
    scene = bpy.context.scene

    # 2026-11-24 修: **--out 的处理原本被误放在 raycast_stats() 里** (一个射线检测
    # 辅助函数), 于是它只在"第一次调用到该函数"时才生效:
    #   * 若某次运行没触发 raycast (如某图没有带 obj 的记录), --out 就不生效,
    #     渲染结果写回默认目录 output/sdg_shelf;
    #   * 更糟: 紧随其后的"清理上次遗留产物"循环用的是**同一个被污染的 SDG_DIR**,
    #     于是默认目录里的旧图/标签被删掉 —— 2026-11-24 实测把 R1 对照集
    #     (output/sdg_shelf) 从 200 张清成 3 张。
    # 现在这段逻辑回到 main() 的正确位置: 先定目录, 再按该目录清理。
    if args.out:
        # 必须转绝对路径 —— Blender 把相对的 render.filepath 按 blend 文件目录
        # 解析 (bpy 模块下是临时目录), 于是渲染结果不落在这里, 后面 PIL 打开就 FileNotFoundError。
        globals()["SDG_DIR"] = os.path.abspath(args.out)
        print(f"[SDG] 输出目录覆盖 -> {SDG_DIR}")
    # 清掉上一次运行遗留的图/标签 —— 否则"目录里的图"会多于 split_manifest 记录的那批
    # (run_pipeline 复用同一 output 目录), 训练臂会把旧图一起吃进去, 而清单查不出来
    # —— 数据组成就又不可核验了。**用 globals() 读**, 因为本函数里 SDG_DIR 是局部名。
    for sub in ("images/train", "images/val", "labels/train", "labels/val", "annotations"):
        os.makedirs(os.path.join(SDG_DIR, sub), exist_ok=True)
    if args.resume:
        # 断点续渲: **不清空**。但必须先核对"上次这批图是用什么参数渲的" ——
        # 参数变了还续渲, 会把两批不同配方的图拼成一批 (数据组成不可核验)。
        prev_p = os.path.join(SDG_DIR, "dataset_summary.json")
        if os.path.exists(prev_p):
            try:
                prev = json.load(open(prev_p, encoding="utf-8"))
            except Exception as e:
                raise SystemExit(f"[SDG] --resume: 读 {prev_p} 失败 ({type(e).__name__}: {e}) "
                                 f"-> 无法确认参数一致, 拒绝续渲")
            now_recipe = {"cam_mult": args.cam_mult, "lens": args.lens,
                          "misalign": args.misalign, "bays": args.bays,
                          "samples": args.samples, "style": args.style}
            checks = [("seed", args.seed), ("num_images", args.num_images),
                      ("val_ratio", args.val_ratio), ("split_mode", args.split_mode),
                      ("images_per_scene", args.images_per_scene),
                      ("recipe", now_recipe)]
            for k, v in checks:
                ov = prev.get(k)
                if k == "recipe" and isinstance(ov, dict):
                    # 老配方里没有 "style" 这个键 (2026-11-25 之前) -> 视为 legacy,
                    # 否则历史池会被"配方变了"误拒 (legacy 与 legacy 必须仍能续渲)。
                    ov = dict(ov)
                    ov.setdefault("style", "legacy")
                if ov is not None and ov != v:
                    raise SystemExit(f"[SDG] --resume: 参数不一致 —— 上次 {k}={ov}, 现在 {v}。"
                                     f"续渲会把两批不同配方的图混在一起, 拒绝。")
            print(f"[RESUME] 参数与上次一致 (seed={args.seed}, num_images={args.num_images})")
        else:
            print(f"[RESUME] 没有上一轮的 dataset_summary.json -> 按新任务开始")
    else:
        removed = 0
        for sub in ("images/train", "images/val", "labels/train", "labels/val", "annotations"):
            d = os.path.join(SDG_DIR, sub)
            for f in (os.listdir(d) if os.path.isdir(d) else []):
                fp = os.path.join(d, f)
                if os.path.isfile(fp):
                    os.remove(fp)
                    removed += 1
        if removed:
            print(f"[CLEAN] 清掉上一次运行的遗留产物 {removed} 个 "
                  f"(只删 images/labels/annotations 下的文件)")

    global STYLE, PRODUCT_TEXTURE
    STYLE = args.style
    PRODUCT_TEXTURE = args.product_texture

    world = bpy.data.worlds.new("Store")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.9, 0.95, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.25   # 店内环境光
    if STYLE in ("shelfwall", "ctxwall"):
        # I-17/I-18: 真实照片里从来看不到"货架之外" —— 那一带是暗的店内环境, 不是明亮的
        # 空背景。留着 legacy 的亮蓝灰会在画面边缘留下一块"假背景"。
        world.node_tree.nodes["Background"].inputs[0].default_value = (0.22, 0.22, 0.24, 1)
        world.node_tree.nodes["Background"].inputs[1].default_value = 0.35
    scene.world = world

    if STYLE == "shelfwall":
        # I-17: 真实货架墙环境 (自带 bays, 不再调用 replicate_bays)
        build_shelfwall(args.bays)
    elif STYLE == "ctxwall":
        # I-18: 只改上下文质感, 相机/商品/密度/光照与 legacy 相同
        build_ctxwall(args.bays)
    else:
        build_gondola()
    pool, mats = build_pool(args.bays)

    # 巡检手机正视角相机 (28mm: 保证 L2 盒顶 + 三层板全部入幅)
    bpy.ops.object.camera_add(location=((args.bays - 1) * BAY_W / 2,
                                        -1.05 * args.cam_mult,
                                        0.50 * (1.0 + 0.25 * (args.cam_mult - 1))))
    cam = bpy.context.active_object
    cam.data.lens = args.lens
    cam.rotation_euler = (math.radians(88), 0, 0)
    scene.camera = cam
    bpy.context.view_layer.update()

    # 近似相机内参 (36mm 水平 sensor)
    fx = RES_W / (2 * math.atan(18.0 / cam.data.lens))
    intrinsics = {"fx": round(fx, 1), "fy": round(fx, 1), "cx": RES_W / 2, "cy": RES_H / 2}

    font = get_mac_font(16)
    font_h = get_mac_font(30)
    font_s = get_mac_font(22)

    # P0-2: 像素级遮挡采样 (相机射线网格, 首命中=本品才算可见) -> 紧致框+可见面积过滤
    _dg = bpy.context.evaluated_depsgraph_get()

    def raycast_stats(rec_obj, x1, y1, x2, y2, grid=32):
        from mathutils import Vector
        sc_ = bpy.context.scene
        camd = sc_.camera.data
        mw = sc_.camera.matrix_world
        origin = mw.translation
        fw = mw.to_quaternion() @ Vector((0, 0, -1))
        rt = mw.to_quaternion() @ Vector((1, 0, 0))
        up = mw.to_quaternion() @ Vector((0, 1, 0))
        sw, sh = RES_W, RES_H
        half_w = math.tan(camd.angle / 2.0)
        half_h = half_w * sh / sw
        vis_xs, vis_ys, vis_n, tot = [], [], 0, 0
        target = rec_obj.evaluated_get(_dg)
        for i in range(grid):
            for j in range(grid):
                u = (x1 + (x2 - x1) * (i + 0.5) / grid) / sw * 2 - 1
                v = 1 - (y1 + (y2 - y1) * (j + 0.5) / grid) / sh * 2
                d = (fw + rt * (u * half_w) + up * (v * half_h)).normalized()
                tot += 1
                hit, loc, nrm, hidx, hob, hmat = sc_.ray_cast(_dg, origin, d)
                if hit and hob is not None and hob.name == rec_obj.name:
                    vis_n += 1
                    px = int((u + 1) / 2 * sw)
                    py = int((1 - v) / 2 * sh)
                    vis_xs.append(px)
                    vis_ys.append(py)
        if vis_n == 0:
            return None
        frac = vis_n / tot
        return (min(vis_xs), min(vis_ys), max(vis_xs) + 1, max(vis_ys) + 1), vis_n, frac

    VIS_MIN = 0.15          # Neurolabs 口径: 可见面积占比过低不入库
    global MISALIGN_P
    MISALIGN_P = args.misalign
    if STYLE != "shelfwall":
        # shelfwall 的各 bay 是 build_shelfwall 自己建的 (不再复制)
        replicate_bays(args.bays)
    dashboard_built = False
    summary = []
    n_resumed = 0
    cur_scene_idx = None
    for img_idx in range(args.num_images):
        if args.split_mode == "scene":
            scene_idx = img_idx // max(1, args.images_per_scene)
            profile = profiles[scene_idx]
            split = split_of[scene_idx]
            img_in_scene = img_idx % max(1, args.images_per_scene)
            layout_seed = derive_image_seed(args.seed, scene_idx, img_in_scene)
            scene_id = profile["scene_id"]
        else:
            # 旧行为 (对照用): 单一场景 + 按 idx 交错切分 + 种子含 split
            scene_idx = 0
            profile = None
            split = split_for_index(img_idx, args.val_ratio)
            layout_seed = derive_layout_seed(args.seed, split, img_idx)
            scene_id = legacy_scene_id
        if scene_idx != cur_scene_idx:
            if profile is not None:
                apply_scene_profile(scene, cam, world, pool, profile, args)
            cur_scene_idx = scene_idx
        rng_i = random.Random(layout_seed)
        img_t0 = time.perf_counter()

        img_name = f"img_{img_idx:03d}.png"
        raw_path = os.path.join(SDG_DIR, "images", split, img_name)
        label_path = os.path.join(SDG_DIR, "labels", split, img_name.replace(".png", ".txt"))
        ann_path = os.path.join(SDG_DIR, "annotations", img_name.replace(".png", ".json"))
        if args.resume and all(os.path.exists(p) for p in (raw_path, label_path, ann_path)):
            # 已渲好且三件副产物齐全 -> 跳过渲染, **从磁盘重建** manifest 条目。
            # 划分/布局种子是由 (base_seed, scene_idx, img_in_scene) 派生的确定性量,
            # 所以跳过不渲染的图不会影响其余图的归属与内容。
            try:
                with open(label_path, encoding="utf-8") as fh:
                    n_boxes = len([ln for ln in fh.read().split("\n") if ln.strip()])
                with open(ann_path, encoding="utf-8") as fh:
                    prev_meta = json.load(fh)
                prev_sum = prev_meta.get("shelf_compliance_summary") or {}
                summary.append(prev_sum | {"image_id": img_name, "split": split})
                manifest_entries.append({
                    "image": img_name, "split": split, "layout_seed": layout_seed,
                    "scene_index": scene_idx, "scene_id": scene_id,
                    "png_sha256": file_sha256(raw_path),
                    "label_sha256": file_sha256(label_path),
                    "n_boxes": n_boxes, "sec": 0.0, "resumed": True,
                })
                n_resumed += 1
                continue
            except Exception as e:
                print(f"[RESUME] {img_name} 重建失败 ({type(e).__name__}: {e}) -> 重新渲染")
        records = layout_image(pool, mats, rng_i, profile, shape=shape_sampler)
        bpy.context.view_layer.update()
        if img_idx == 0:
            sc = scene.camera
            print(f"[CamDebug] scene.camera={sc.name if sc else None} "
                  f"loc={tuple(round(v,3) for v in sc.matrix_world.translation)} "
                  f"rot_euler_deg={tuple(round(math.degrees(a),1) for a in sc.rotation_euler)} "
                  f"lens={sc.data.lens} type={sc.data.type}")

        # img_name / raw_path / label_path 已在循环开头算好 (resume 判据要用)
        scene.render.filepath = raw_path
        _pidx = 0
        for rec in records:
            if rec.get("obj") is not None:
                _pidx += 1
                rec["obj"].pass_index = _pidx
                rec["_pidx"] = _pidx
        bpy.ops.render.render(write_still=True)

        # YOLO 标注 + 业务元数据 (P0-2: 掩膜紧致框 + 可见面积过滤)
        import numpy as np
        yolo_lines, annotations = [], []
        n_filtered = 0
        for rec in records:
            x1, y1, x2, y2 = project_bbox(scene, cam, rec["obj"], RES_W, RES_H) if rec.get("obj") else (0, 0, 0, 0)
            fx1, fy1, fx2, fy2 = x1, y1, x2, y2   # 整品框 (可见区域框之前)
            vis_frac = None
            if rec.get("obj") is not None:
                st = raycast_stats(rec["obj"], x1, y1, x2, y2)
                if st is None:
                    n_filtered += 1
                    continue
                (mx1, my1, mx2, my2), vis_px, vis_frac = st
                if vis_frac < VIS_MIN:
                    n_filtered += 1
                    annotations.append({
                        "sku": rec["sku"], "status": rec["status"], "class_id": rec["class_id"],
                        "level": rec["level"], "slot": rec["slot"],
                        "bbox_xyxy": [mx1, my1, mx2, my2], "visible_frac": round(vis_frac, 3),
                        "filtered": "low_visibility",
                    })
                    continue
                x1, y1, x2, y2 = mx1, my1, mx2, my2
            cx = (x1 + x2) / 2.0 / RES_W
            cy = (y1 + y2) / 2.0 / RES_H
            bw = (x2 - x1) / RES_W
            bh = (y2 - y1) / RES_H
            yolo_lines.append(f"{rec['class_id']} {cx:.5f} {cy:.5f} {bw:.5f} {bh:.5f}")
            # 2026-11-23: 同时落"整品框"与"可见占比" ——
            # 合成标签的框是**可见区域**紧致框, 真实标注的框是整品框, 这个口径差以前
            # 没有任何数字 (审计 F7 的残留项)。visible_frac = 可见像素占整品框面积的比例,
            # 于是"框语义差"可以量化: 框面积比 = visible_frac。
            ann = {
                "sku": rec["sku"], "status": rec["status"], "class_id": rec["class_id"],
                "level": rec["level"], "slot": rec["slot"],
                "bbox_xyxy": [x1, y1, x2, y2],
                "bbox_source": "object_index_mask" if rec.get("obj") else "planned_projection",
            }
            if rec.get("obj") is not None and vis_frac is not None:
                ann["visible_frac"] = round(vis_frac, 3)
                ann["bbox_full_xyxy"] = [fx1, fy1, fx2, fy2]
            # 2026-11-23: 记下商品的**世界尺寸** —— 探针要用它拟合"世界宽高比 -> 投影宽高比"
            # 的换算系数 (投影受透视影响, 不是常数倍, 必须实测)
            if rec.get("obj") is not None:
                _sc = rec["obj"].scale
                _w = PACK_W * _sc.x
                _h = PACK_H * _sc.z
                ann["world_w"] = round(_w, 5)
                ann["world_h"] = round(_h, 5)
                ann["world_ar"] = round(_w / _h, 4) if _h > 0 else None
            annotations.append(ann)

        # label_path 已在循环开头算好 (resume 判据要用)
        with open(label_path, "w") as f:
            f.write("\n".join(yolo_lines))

        # 2026-11-20: 划分清单 (逐图记录 split/布局种子/内容指纹) —— 泄漏与偷换都可事后核验
        manifest_entries.append({
            "image": img_name,
            "split": split,
            "layout_seed": layout_seed,
            "scene_index": scene_idx,
            "scene_id": scene_id,
            "png_sha256": file_sha256(raw_path),
            "label_sha256": file_sha256(label_path),
            "n_boxes": len(yolo_lines),
            "sec": round(time.perf_counter() - img_t0, 2),
        })

        counts = {k: sum(1 for r in records if r["status"] == k) for k in CLASS_MAP}
        total = len(records)
        meta = {
            "image_id": img_name,
            "split": split,
            "camera_intrinsics": intrinsics,
            "shelf_compliance_summary": {
                "total_planned_slots": total,
                "compliant_facings": counts["COMPLIANT"],
                "oos_gaps_detected": counts["OOS_GAP"],
                "misaligned_facings": counts["MISALIGNED"],
                "foreign_intrusions": counts["INTRUSION"],
                "osa_rate": round((total - counts["OOS_GAP"]) / total, 3),
            },
            "annotations": annotations,
        }
        with open(os.path.join(SDG_DIR, "annotations", img_name.replace(".png", ".json")), "w") as f:
            json.dump(meta, f, ensure_ascii=False, indent=1)
        summary.append(meta["shelf_compliance_summary"] | {"image_id": img_name, "split": split})

        # 首图 -> 巡检对比仪表盘
        if not dashboard_built:
            dashboard_built = True
            raw_img = Image.open(raw_path).convert("RGB")
            draw = ImageDraw.Draw(raw_img)
            for rec, ann in zip(records, annotations):
                st = rec["status"]
                x1, y1, x2, y2 = ann["bbox_xyxy"]
                col = COLORS[st]
                draw.rectangle([x1, y1, x2, y2], outline=col, width=4)
                draw.rectangle([x1, max(0, y1 - 26), x1 + 96, y1], fill=col)
                draw.text((x1 + 4, max(0, y1 - 24)), LABELS_CN[st], fill=(15, 15, 15), font=font)

            raw_copy = Image.open(raw_path).convert("RGB")
            dash = Image.new("RGB", (RES_W * 2 + 60, RES_H + 170), (16, 20, 26))
            ddraw = ImageDraw.Draw(dash)
            osa = (total - counts["OOS_GAP"]) / total * 100
            comp = counts["COMPLIANT"] / total * 100
            header = (f"零售终端冰柜/货架 OpenUSD 合成数据与 AI 巡检看板  |  总槽位: {total}   "
                      f"货架有货率 (OSA): {osa:.1f}%   排面完美合规率: {comp:.1f}%   "
                      f"[合规:{counts['COMPLIANT']}  缺货告警:{counts['OOS_GAP']}  "
                      f"错位:{counts['MISALIGNED']}  竞品入侵:{counts['INTRUSION']}]")
            ddraw.text((35, 45), header, fill=(240, 245, 250), font=font_h)
            ddraw.text((35, 95), "▼ 左图: Blender Metal-RT 物理光追合成货架 (含 LED 眩光与价签遮挡)",
                       fill=(160, 175, 190), font=font_s)
            ddraw.text((RES_W + 55, 95), "▼ 右图: 零人工标注自动导出的 2D 紧致框与终端异常分类真值",
                       fill=(46, 213, 115), font=font_s)
            dash.paste(raw_copy, (20, 140))
            dash.paste(raw_img, (RES_W + 40, 140))
            dash.save(os.path.join(SDG_DIR, "Retail_Shelf_Inspection_Dashboard.png"))
            raw_copy.save(os.path.join(SDG_DIR, "shelf_raw_rgb.png"))
            print("[Success] 巡检仪表盘已生成")

        print(f"[{img_idx + 1}/{args.num_images}] {img_name} ({split}) "
              f"OSA={meta['shelf_compliance_summary']['osa_rate']}")

    if n_resumed:
        print(f"[RESUME] 复用了已渲好的 {n_resumed} 张, 本次新渲 "
              f"{len(manifest_entries) - n_resumed} 张")

    # 划分清单 (2026-11-20): 逐图 split + 布局种子 + 内容 sha256 + 场景归属
    train_scenes = sorted({e["scene_id"] for e in manifest_entries if e["split"] == "train"})
    val_scenes = sorted({e["scene_id"] for e in manifest_entries if e["split"] == "val"})
    scene_table = []
    for p in profiles:
        imgs = [e for e in manifest_entries if e["scene_index"] == p["scene_index"]]
        if not imgs:
            continue
        scene_table.append({
            "scene_index": p["scene_index"],
            "scene_id": p["scene_id"],
            "split": imgs[0]["split"],
            "n_images": len(imgs),
            "images": [e["image"] for e in imgs],
            "profile": {k: v for k, v in p.items() if k != "scene_index"},
        })
    split_manifest = {
        "schema": "sdg_split_manifest/2",
        "generated_by": "pipelines/shelf_sdg/02_shelf_sdg_inspector.py",
        "base_seed": args.seed,
        "val_ratio": args.val_ratio,
        "split_mode": args.split_mode,
        "images_per_scene": args.images_per_scene,
        "split_policy": (
            "scene-level holdout: 场景参数由 (base_seed, scene_idx) 派生, 一个场景的全部图像"
            "同属一个 split, train/val 的场景集合互不相交; 图内布局种子由 "
            "(base_seed, scene_idx, img_in_scene) 派生 (不含 split, 故图像内容与场景归属无关)"
            if args.split_mode == "scene" else
            "legacy image-level split: 单一场景, 按 idx 交错切分, 种子含 split (仅供对照)"),
        "n_train": sum(1 for e in manifest_entries if e["split"] == "train"),
        "n_val": sum(1 for e in manifest_entries if e["split"] == "val"),
        "n_resumed": n_resumed,
        "resume_note": ("本次运行复用了已渲好的图 (--resume); 这些图的 sec 记 0, "
                        "不影响它们的像素与标签 —— 划分与布局种子是由 "
                        "(base_seed, scene_idx, img_in_scene) 派生的确定性量") if n_resumed else None,
        "train_scene_ids": train_scenes,
        "val_scene_ids": val_scenes,
        "scene_overlap": bool(set(train_scenes) & set(val_scenes)),
        "scene_level_holdout": args.split_mode == "scene" and not (set(train_scenes) & set(val_scenes)),
        "split_assignment": split_info,
        "scenes": scene_table,
        "residual_limitation": (
            "场景级留出只保证 train/val 不共享同一场景; 场景之间仍是同一套货架模板 (gondola_v1) "
            "的参数化变体 (上架 bay/层位、SKU 配比、灯光、相机位姿、错位率), "
            "不是不同的货架结构/店型。真正的场景外推需多套货架模板或真实店头照片。"),
        "images": manifest_entries,
    }
    secs = [e.get("sec") or 0.0 for e in manifest_entries]
    total_sec = round(sum(secs), 2)
    split_manifest["throughput"] = {
        "total_sec": total_sec,
        "n_images": len(manifest_entries),
        "sec_per_image": round(total_sec / len(manifest_entries), 2) if manifest_entries else None,
        "images_per_min": round(len(manifest_entries) / (total_sec / 60), 2) if total_sec > 0 else None,
        "note": ("实测值 (含渲染 + 射线标注); 万图产能属水平外推, 非实测"
                 + ("; 本次含 --resume, 复用的图 sec 记 0 -> 实测吞吐被**低估**"
                    if n_resumed else "")),
    }
    write_json(os.path.join(SDG_DIR, "split_manifest.json"), split_manifest)

    # 汇总
    # 2026-11-23: 把"这批图是谁渲的"记进产物 —— 渲染器版本不同 = 像素分布不同,
    # 跨批次比较时是个隐藏混淆项 (之前 dataset_summary 里完全没有这一项)。
    try:
        # 2026-11-24 修: 原来记的是 `globals().get("CYCLES_DEVICE")` —— 那是**环境变量名**
        # (在 runtime_env 里叫 CYCLES_DEVICE_ENV), 模块里根本没有这个变量, 所以这个字段
        # **永远是 null**, 产物无法回答"这批图是 CPU 还是 GPU 渲的"。现在记实际生效的
        # 后端与设备数 (configure_cycles 的返回值), 外加渲染器身份。
        backend, ndev = CYCLES_RENDER_INFO
        renderer = {"blender": bpy.app.version_string,
                    "engine": scene.render.engine,
                    "samples": args.samples,
                    "cycles_backend": backend,
                    "cycles_gpu_devices": ndev,
                    "cycles_device": scene.cycles.device,
                    "resolution": [RES_W, RES_H]}
    except Exception as e:
        renderer = {"error": f"{type(e).__name__}: {e}"}
    with open(os.path.join(SDG_DIR, "dataset_summary.json"), "w") as f:
        json.dump({"num_images": args.num_images, "seed": args.seed, "resolution": [RES_W, RES_H],
                   "val_ratio": args.val_ratio, "split_manifest": os.path.join("split_manifest.json"),
                   "split_mode": args.split_mode, "images_per_scene": args.images_per_scene,
                   "n_scenes": len(profiles),
                   # 2026-11-23: 配方参数也要落盘 —— 之前产物里完全没记"这批图是用什么
                   # 相机/错位率/bays 渲的", 于是"对照组到底是不是默认参数"只能靠猜。
                   "recipe": {"cam_mult": args.cam_mult, "lens": args.lens,
                              "misalign": args.misalign, "bays": args.bays,
                              "samples": args.samples, "style": args.style},
                   "scene_level_holdout": split_manifest["scene_level_holdout"],
                   "renderer": renderer,
                   "intrinsics_default": intrinsics, "per_image": summary}, f, ensure_ascii=False, indent=1)
    write_dataset_yaml()
    print(f"[Done] 数据集 -> {SDG_DIR} ({args.num_images} images); "
          f"划分清单 -> split_manifest.json (train={split_manifest['n_train']} val={split_manifest['n_val']})")


if __name__ == "__main__":
    main()
