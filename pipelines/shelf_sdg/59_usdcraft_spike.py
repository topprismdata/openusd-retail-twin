#!/usr/bin/env python
"""USDCraft 资产可用性探针 (2026-11-25) —— 30 分钟就能回答"第二级内容干预值不值得做"。

要回答三件事:
  1. **能不能导进 Blender**: 资产是 PhysX 扁平 stage (Z-up, 米), 入口 `physx/model.usdc`;
  2. **贴图/标签 decal 在不在**: 带贴图的对象有一个 `textures/decal_*.png`, 导进来后
     标签文字是否可见 (这才是"商品外观"的关键);
  3. **尺度合不合适**: 货架商品是 5-25 cm 小件, 资产的包围盒必须落在那个量级,
     否则要自己缩放/挑选。

用法 (必须用 blender 的 "--" 约定传参, 否则参数会被静默忽略):
    python tools/blender_shim.py -b -P pipelines/shelf_sdg/59_usdcraft_spike.py -- \
        --asset assets/usdcraft/rigid/<...>/<obj>/physx/model.usdc --out output/benchmark/usdc_spike
"""
import argparse
import json
import os
import sys

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    raise SystemExit("[SPIKE] 没有收到参数 —— 必须按 "
                     "`blender -b -P <此脚本> -- <参数>` 调用")


def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default


import bpy  # noqa: E402
from mathutils import Vector  # noqa: E402

ASSET = opt("--asset")
# Blender 的 cwd 不是仓根 (它把相对路径解析成 C:\...), 所以这里一律转绝对路径
if ASSET:
    ASSET = os.path.abspath(ASSET)
OUT = os.path.abspath(opt("--out", "output/benchmark/usdc_spike"))
SAMPLES = int(opt("--samples", "24"))
os.makedirs(OUT, exist_ok=True)


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_asset(path):
    """导进 USD stage。返回导入后的网格物体列表。"""
    before = set(bpy.data.objects)
    bpy.ops.wm.usd_import(filepath=path)
    return [o for o in bpy.data.objects if o not in before and o.type == "MESH"]


def bbox_report(objs):
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    tris = 0
    for o in objs:
        tris += len(o.data.polygons)
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    return {"n_mesh": len(objs), "n_faces": tris,
            "min_m": [round(v, 4) for v in lo],
            "max_m": [round(v, 4) for v in hi],
            "size_m": [round(hi[i] - lo[i], 4) for i in range(3)]}


def count_textures():
    """导进来的贴图节点数 (贴图没接上 = 资产是纯色 -> 外观干预没意义)。"""
    n_img = 0
    n_linked = 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        for slot in o.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes:
                continue
            for node in mat.node_tree.nodes:
                if node.type == "TEX_IMAGE":
                    n_img += 1
                    if any(l.to_node.type == "TEX_IMAGE" for l in mat.node_tree.links
                           if l.to_socket == node.inputs[0]):
                        n_linked += 1
    return {"tex_nodes": n_img, "tex_nodes_wired": n_linked}


def main():
    clear_scene()
    print(f"[SPIKE] 资产: {ASSET}")
    objs = import_asset(ASSET)
    rep = {"asset": ASSET, **bbox_report(objs), **count_textures()}
    # 放一个地面 + 相机 + 灯, 渲一张看贴图/几何
    bpy.ops.mesh.primitive_plane_add(size=4.0)
    ground = bpy.context.active_object
    gm = bpy.data.materials.new("Ground")
    gm.use_nodes = True
    gm.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.5, 0.5, 0.5, 1)
    ground.data.materials.append(gm)
    for o in objs:
        o.rotation_euler = (0, 0, 0)
        # 资产是 Z-up, Blender 是 Z-up 也行; 只把最小点落到地面
        zmin = min((o.matrix_world @ Vector(c))[2] for c in o.bound_box)
        o.location.z -= zmin
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for corner in o.bound_box:
            w = o.matrix_world @ Vector(corner)
            for i in range(3):
                lo[i] = min(lo[i], w[i])
                hi[i] = max(hi[i], w[i])
    c = (lo + hi) / 2
    size = max(hi[i] - lo[i] for i in range(3))
    dist = max(0.18, size * 3.0)          # 相机距离随物体大小走, 别用固定值
    bpy.ops.object.camera_add(location=(c.x + dist * 0.7, -dist, c.z + dist * 0.5))
    cam = bpy.context.active_object
    # 让相机**真的看向**物体中心 (别猜欧拉角)
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    bpy.ops.object.light_add(type="AREA", location=(c.x + 0.8, -0.9, c.z + 1.2))
    bpy.context.object.data.energy = 250
    bpy.ops.object.light_add(type="AREA", location=(c.x - 1.0, -0.5, c.z + 0.6))
    bpy.context.object.data.energy = 80
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.samples = SAMPLES
    sc.render.resolution_x, sc.render.resolution_y = 900, 900
    sc.render.filepath = os.path.join(OUT, "spike.png")
    bpy.ops.render.render(write_still=True)
    rep["render"] = sc.render.filepath
    rep["size_cm"] = [round(v * 100, 1) for v in rep["size_m"]]
    with open(os.path.join(OUT, "spike.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print("[SPIKE] " + json.dumps(rep, ensure_ascii=False))


main()
