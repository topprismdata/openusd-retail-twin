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
import numpy as np
import json
import random
import argparse
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEX_DIR = os.path.join(BASE_DIR, "assets", "textures")
SDG_DIR = os.path.join(BASE_DIR, "output", "sdg_shelf")
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

SHELF_LEVELS = [0.15, 0.45, 0.75]
MISALIGN_P = 0.10      # 层板顶面 z (层高 0.30m, 净空 164mm > 盒高 136mm)
LEVEL_SKUS = ["demo_jersey", "demo_organic", "demo_classic"]
N_FACINGS = 10
X_START, X_SPACING = -0.36, 0.08
RES_W, RES_H = 1440, 1080


def get_mac_font(size):
    for f in ("/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc"):
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--num-images", type=int, default=20)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--out", default=None, help="SDG 输出目录覆盖 (消融臂隔离)")
    p.add_argument("--cam-mult", type=float, default=1.0, help="相机距离倍率 (A1/A2 密度尺度因子)")
    p.add_argument("--lens", type=float, default=28.0, help="镜头焦距 mm (A1/A2)")
    p.add_argument("--misalign", type=float, default=0.10, help="朝向错位概率 (A3 朝向因子)")
    p.add_argument("--bays", type=int, default=1, help="联排货架墙 bay 数 (A1b 密度因子)")
    return p.parse_args(argv)


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
    if os.path.exists(albedo_p):
        tc = nodes.new("ShaderNodeTexImage")
        tc.image = bpy.data.images.load(albedo_p)
        links.new(tc.outputs["Color"], bsdf.inputs["Base Color"])
    if os.path.exists(orm_p):
        to = nodes.new("ShaderNodeTexImage")
        to.image = bpy.data.images.load(orm_p)
        to.image.colorspace_settings.name = "Non-Color"
        sep = nodes.new("ShaderNodeSeparateColor")
        links.new(to.outputs["Color"], sep.inputs["Color"])
        links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    return mat


def setup_scene(samples):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    scene.cycles.device = "GPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.use_persistent_data = False   # 逐图 hide_render 切换, 持久化会吃到陈旧状态
    scene.render.resolution_x, scene.render.resolution_y = RES_W, RES_H


def build_gondola():
    """冷柜: 背板 + 3 层金属层板 + 前沿价签条 + 层下 LED 灯带"""
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
    back.data.materials.append(metal)

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
                             "planned_sku": LEVEL_SKUS[lvl_idx], "base_x": bx})
    return pool, mats


def layout_image(pool, mats, rng):
    """状态机注入 + 返回本图标注记录 (OOS 槽位保留投影坐标)"""
    records = []
    for item in pool:
        roll = rng.random()
        if roll < 0.15:
            status = "OOS_GAP"
        elif roll < 0.15 + MISALIGN_P:
            status = "MISALIGNED"
        elif roll < 0.15 + MISALIGN_P + 0.05:
            status = "INTRUSION"
        else:
            status = "COMPLIANT"

        box = item["obj"]
        bx = item["base_x"] + rng.uniform(-0.004, 0.004)
        by = -0.03 + rng.uniform(-0.004, 0.004)
        bz = SHELF_LEVELS[item["lvl"]]
        box.location = (bx, by, bz)

        if status == "OOS_GAP":
            box.hide_render = True
            box.rotation_euler = (0, 0, 0)
        elif status == "MISALIGNED":
            box.hide_render = False
            box.rotation_euler = (0, 0, math.radians(82 + rng.uniform(-5, 5)))
            box.data.materials[0] = mats[item["planned_sku"]]
        elif status == "INTRUSION":
            box.hide_render = False
            box.rotation_euler = (0, 0, math.radians(rng.uniform(-4, 4)))
            box.data.materials[0] = mats["intruder"]
        else:
            box.hide_render = False
            box.rotation_euler = (0, 0, math.radians(rng.uniform(-3.5, 3.5)))
            box.data.materials[0] = mats[item["planned_sku"]]

        records.append({
            "obj": box, "sku": item["planned_sku"], "status": status,
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
    args = parse_args()
    rng = random.Random(args.seed)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_scene(args.samples)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("Store")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.9, 0.95, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.25   # 店内环境光
    scene.world = world

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
    if args.out:
        globals()["SDG_DIR"] = args.out
        for sub in ("images/train", "images/val", "labels/train", "labels/val", "annotations"):
            os.makedirs(os.path.join(SDG_DIR, sub), exist_ok=True)
    replicate_bays(args.bays)
    dashboard_built = False
    summary = []
    for img_idx in range(args.num_images):
        records = layout_image(pool, mats, rng)
        bpy.context.view_layer.update()
        if img_idx == 0:
            sc = scene.camera
            print(f"[CamDebug] scene.camera={sc.name if sc else None} "
                  f"loc={tuple(round(v,3) for v in sc.matrix_world.translation)} "
                  f"rot_euler_deg={tuple(round(math.degrees(a),1) for a in sc.rotation_euler)} "
                  f"lens={sc.data.lens} type={sc.data.type}")

        split = "val" if img_idx % 5 == 4 else "train"
        img_name = f"img_{img_idx:03d}.png"
        raw_path = os.path.join(SDG_DIR, "images", split, img_name)
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
            annotations.append({
                "sku": rec["sku"], "status": rec["status"], "class_id": rec["class_id"],
                "level": rec["level"], "slot": rec["slot"],
                "bbox_xyxy": [x1, y1, x2, y2],
                "bbox_source": "object_index_mask" if rec.get("obj") else "planned_projection",
            })

        with open(os.path.join(SDG_DIR, "labels", split, img_name.replace(".png", ".txt")), "w") as f:
            f.write("\n".join(yolo_lines))

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

    # 汇总
    with open(os.path.join(SDG_DIR, "dataset_summary.json"), "w") as f:
        json.dump({"num_images": args.num_images, "seed": args.seed, "resolution": [RES_W, RES_H],
                   "intrinsics_default": intrinsics, "per_image": summary}, f, ensure_ascii=False, indent=1)
    write_dataset_yaml()
    print(f"[Done] 数据集 -> {SDG_DIR} ({args.num_images} images)")


if __name__ == "__main__":
    main()
