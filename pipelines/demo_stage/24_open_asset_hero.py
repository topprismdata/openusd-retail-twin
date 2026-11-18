#!/usr/bin/env python3
"""24 - 开源资产棚拍 hero 渲染: GLB 商品 + Poly Haven 棚拍 HDRI, Blender Cycles Metal

用法: Blender -b -P 24_open_asset_hero.py -- --assets a.glb b.glb --label texverse_test
产物: output/open_assets/<label>/  白底单品 + 4k 棚拍 HDRI 组合台
"""
import argparse
import math
import os
import sys

import bpy

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(BASE_DIR, "output", "open_assets")


def clear_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".ply":
        bpy.ops.wm.ply_import(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        raise ValueError(f"unsupported: {path}")


def normalize_object(objs, target_h=0.20):
    """归一化: 落地 z=0, 最大边统一 target_h, 原点居中"""
    import mathutils
    mins = mathutils.Vector((1e9,) * 3)
    maxs = mathutils.Vector((-1e9,) * 3)
    for o in objs:
        if o.type != "MESH":
            continue
        for c in o.bound_box:
            w = o.matrix_world @ mathutils.Vector(c)
            mins = mathutils.Vector(map(min, mins, w))
            maxs = mathutils.Vector(map(max, maxs, w))
    size = maxs - mins
    scale = target_h / max(max(size), 1e-6)
    cx, cy = (mins.x + maxs.x) / 2, (mins.y + maxs.y) / 2
    roots = [o for o in objs if o.parent is None]
    for r in roots:
        r.scale = (r.scale[0] * scale, r.scale[1] * scale, r.scale[2] * scale)
        r.location.x -= cx * scale
        r.location.y -= cy * scale
        r.location.z -= mins.z * scale
    return size * scale


def setup_hdri(hdr_path, strength=1.0, rot_z=0.0):
    world = bpy.data.worlds.new("StudioHDRI")
    bpy.context.scene.world = world
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(hdr_path)
    mapping = nt.nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value = (0, 0, math.radians(rot_z))
    coord = nt.nodes.new("ShaderNodeTexCoord")
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(coord.outputs["Generated"], env.inputs["Vector"])
    nt.links.new(env.outputs[0], bg.inputs[0])
    nt.links.new(bg.outputs[0], out.inputs[0])


def setup_camera(loc, look_at, lens=85):
    import mathutils
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = lens
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    d = mathutils.Vector(look_at) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def setup_ground():
    """中性白 地台 + 阴影收集"""
    bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, 0))
    g = bpy.context.active_object
    mat = bpy.data.materials.new("Ground")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.92, 0.92, 0.92, 1)
    bsdf.inputs["Roughness"].default_value = 0.6
    g.data.materials.append(mat)
    return g


def render(out_path, res=1600, samples=128, transparent=False):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == "METAL"
    sc.cycles.device = "GPU"
    sc.cycles.samples = samples
    sc.render.resolution_x = res
    sc.render.resolution_y = res
    sc.render.film_transparent = transparent
    sc.view_settings.view_transform = "AgX"
    sc.render.image_settings.file_format = "PNG"
    sc.render.filepath = out_path
    bpy.ops.render.render(write_still=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", required=True, help="逗号分隔 GLB/PLY 路径")
    ap.add_argument("--label", default="run")
    ap.add_argument("--hdr", default=os.path.join(BASE_DIR, "assets", "hdri", "brown_photostudio_01_4k.hdr"))
    ap.add_argument("--res", type=int, default=1600)
    args = ap.parse_args(argv)

    paths = [p for p in args.assets.split(",") if p]
    for p in paths:
        if not os.path.exists(p):
            print(f"[SKIP] missing {p}")
            paths.remove(p)
    if not paths:
        print("[FATAL] no assets")
        sys.exit(1)

    out = os.path.join(OUT_DIR, args.label)
    os.makedirs(out, exist_ok=True)
    clear_scene()
    setup_ground()

    # 逐件导入, 归一化, 沿 x 排开
    xs, spacing = [], 0.0
    group = []
    for i, p in enumerate(paths):
        before = set(bpy.data.objects)
        import_glb(p)
        new_objs = [o for o in bpy.data.objects if o not in before]
        size = normalize_object(new_objs, target_h=0.22)
        spacing = max(spacing, size.x + 0.09)
        group.append((p, new_objs, size))
    total_w = sum(s[2].x for s in group) + 0.09 * (len(group) - 1)
    x = -total_w / 2
    for p, objs, size in group:
        roots = [o for o in objs if o.parent is None]
        dx = x + size.x / 2
        for r in roots:
            r.location.x += dx
        x += size.x + 0.09
        xs.append(dx)

    # 两版光照: 1) 白底棚拍 (HDRI 低强度+透明)  2) 棚拍 HDRI 全强度带环境
    total_w = sum(s_[2].x for s_ in group) + 0.09 * (len(group) - 1)
    import math as _m
    hfov = 2 * _m.atan(36 / (2 * 72))
    dist = (total_w / 2 + 0.10) / _m.tan(hfov / 2) + 0.15
    cam = setup_camera(loc=(0, -dist, 0.14), look_at=(0, 0, 0.10), lens=72)

    setup_hdri(args.hdr, strength=0.55, rot_z=25)
    render(os.path.join(out, "white_bg.png"), res=args.res, samples=160, transparent=True)

    setup_hdri(args.hdr, strength=1.0, rot_z=25)
    render(os.path.join(out, "studio_hero.png"), res=args.res, samples=160, transparent=False)

    # 45° 特写
    import mathutils
    mid_x = xs[len(xs) // 2] if xs else 0
    cam.location = (mid_x + 0.28, -0.62, 0.20)
    cam.rotation_euler = (mathutils.Vector((mid_x, 0, 0.085)) - mathutils.Vector(cam.location)).to_track_quat("-Z", "Y").to_euler()
    render(os.path.join(out, "closeup_45.png"), res=args.res, samples=160)

    print(f"[HERO] done -> {out}")


if __name__ == "__main__":
    main()
