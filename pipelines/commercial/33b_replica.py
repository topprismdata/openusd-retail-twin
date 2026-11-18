#!/usr/bin/env python3
"""33b - 参照B忠实复刻 (intl_128865): 白木桌+碟勺+格兰诺拉+莓果+酸奶+玻璃罐+玫瑰
+ 经典盒体入画 (商品位=参照图玻璃罐位置). 静态摆拍, 无浇注.
比例基准 (参照B实测): 碗 Ø16.5cm 外撇浅碗 h7.5cm / 碟 Ø21cm 薄 / 罐 Ø7.4 h8.5 /
草莓=碗径25% / 盒体 250ml 13.6cm 直立商品位.
运行: Blender -b -P 33b_replica.py -- --res 1920 --samples 256 --out final
产物: output/yogurt_macro/replica_{draft,final}.png
"""
import math
import os
import sys

import bpy

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

import importlib.util as _ilu


def _imp(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


comfy = _imp("comfy01", os.path.join(BASE_DIR, "pipelines/ecommerce/01_comfy_usd_compositor.py"))
heroes = _imp("heroes26", os.path.join(BASE_DIR, "pipelines/commercial/26_creative_heroes.py"))

OUT_DIR = os.path.join(BASE_DIR, "output", "yogurt_macro")
SF_DIR = os.path.join(BASE_DIR, "assets", "sf_models", "berries")

# 场景锚点 (参照B比例): 碗 Ø0.165 外撇浅碗
BC = (0.10, -0.02)
BZ = 0.014           # 碗底坐碟
RIM = BZ + 0.075     # 碗沿
FILL = BZ + 0.052    # 内容面


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--res", type=int, default=1920)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--out", default="final")
    return p.parse_args(argv)


def fresh(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    comfy.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.view_settings.exposure = -0.35
    world = bpy.data.worlds.new("Env")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.62, 0.60, 0.56, 1)
    bg.inputs[1].default_value = 0.50
    scene.world = world
    return scene


def ceramic_mat(name="Ceramic", tint=(0.82, 0.81, 0.79)):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*tint, 1)
    b.inputs["Roughness"].default_value = 0.13
    if "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = 1.0
        b.inputs["Coat Roughness"].default_value = 0.06
    return m


def wood_table():
    """白木条桌: 横向拼板 0.115m 间距 + 细木纹"""
    bpy.ops.mesh.primitive_plane_add(size=2.6, location=(0.05, 0.15, 0.0))
    tb = bpy.context.active_object
    m = bpy.data.materials.new("WoodWhite")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    b.inputs["Roughness"].default_value = 0.52
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.0, 54.6, 1.0)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    wv = nt.nodes.new("ShaderNodeTexWave")
    wv.wave_type = "BANDS"
    wv.bands_direction = "Y"
    nt.links.new(mp.outputs[0], wv.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.0
    ramp.color_ramp.elements[0].color = (0.50, 0.47, 0.43, 1)
    ramp.color_ramp.elements[1].position = 0.12
    ramp.color_ramp.elements[1].color = (0.70, 0.67, 0.62, 1)
    nt.links.new(wv.outputs[0], ramp.inputs[0])
    mp2 = nt.nodes.new("ShaderNodeMapping")
    mp2.inputs["Scale"].default_value = (2.0, 46.0, 1.0)
    nt.links.new(tc.outputs["Object"], mp2.inputs["Vector"])
    ns = nt.nodes.new("ShaderNodeTexNoise")
    ns.inputs["Detail"].default_value = 6.0
    nt.links.new(mp2.outputs[0], ns.inputs["Vector"])
    nsr = nt.nodes.new("ShaderNodeValToRGB")
    nsr.color_ramp.elements[0].position = 0.35
    nsr.color_ramp.elements[0].color = (0.88, 0.88, 0.88, 1)
    nsr.color_ramp.elements[1].position = 0.75
    nsr.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1)
    nt.links.new(ns.outputs[0], nsr.inputs[0])
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MULTIPLY"
    mix.inputs["Fac"].default_value = 0.6
    nt.links.new(ramp.outputs[0], mix.inputs[1])
    nt.links.new(nsr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], b.inputs["Base Color"])
    tb.data.materials.append(m)
    return tb


def lathe_bowl():
    """白瓷碗(外撇浅碗)+薄碟+小勺 (参照B比例)"""
    import bmesh
    cm = ceramic_mat("BowlCeramic")
    profile = [(0.000, 0.002), (0.050, 0.002), (0.058, 0.005), (0.068, 0.018),
               (0.077, 0.045), (0.0825, 0.068), (0.0815, 0.075), (0.076, 0.077),
               (0.072, 0.072), (0.067, 0.045), (0.056, 0.016), (0.038, 0.008), (0.000, 0.008)]
    bm = bmesh.new()
    verts = [bm.verts.new((r, 0, z)) for r, z in profile]
    for a, b in zip(verts, verts[1:]):
        bm.edges.new((a, b))
    bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:], axis=(0, 0, 1), cent=(0, 0, 0),
                   angle=6.2832, steps=64, use_merge=True)
    me = bpy.data.meshes.new("Bowl")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("Bowl", me)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = (BC[0], BC[1], BZ)
    ob.data.materials.append(cm)
    for p in ob.data.polygons:
        p.use_smooth = True
    # 薄碟
    bpy.ops.mesh.primitive_cylinder_add(radius=0.105, depth=0.010, location=(BC[0], BC[1], 0.006), vertices=96)
    sa = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    sa.data.materials.append(ceramic_mat("Saucer"))
    bpy.ops.mesh.primitive_torus_add(major_radius=0.098, minor_radius=0.005, location=(BC[0], BC[1], 0.011))
    tor = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    tor.data.materials.append(ceramic_mat("SaucerRim"))
    # 小勺 搁碟前缘
    sm = ceramic_mat("Spoon")
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.020, location=(0.048, -0.098, 0.016), segments=48, ring_count=32)
    sb = bpy.context.active_object
    sb.scale = (1.25, 0.8, 0.42)
    bpy.ops.object.shade_smooth()
    sb.data.materials.append(sm)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.007, depth=0.10, location=(0.006, -0.142, 0.024),
                                        rotation=(0, math.radians(115), math.radians(38)), vertices=32)
    hd = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    hd.data.materials.append(sm)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.009, location=(-0.028, -0.178, 0.040), segments=32, ring_count=24)
    tip = bpy.context.active_object
    tip.scale = (1.0, 0.55, 0.85)
    bpy.ops.object.shade_smooth()
    tip.data.materials.append(sm)
    return ob


def camera_mapped_glass(scene, cam):
    """2.5D 相机投影牛奶杯 (用户方案): 实拍照片经 Window 坐标精确投到锥台代理上.
    代理供轮廓/遮挡/DOF; 照片烘焙真实折射/高光/杯壁; 阴影射线 75% 透射防死黑;
    接地用径向渐变假软影. 单视角英雄图标准 VFX 技法 (camera projection / matte)."""
    import bpy_extras
    import mathutils
    jx, jy = -0.052, 0.105
    H = 0.115
    bpy.ops.mesh.primitive_cone_add(radius1=0.028, radius2=0.0365, depth=H,
                                    location=(jx, jy, H / 2), vertices=48)
    proxy = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    bpy.context.view_layer.update()
    pts = [proxy.matrix_world @ mathutils.Vector(c) for c in proxy.bound_box]
    uv = [bpy_extras.object_utils.world_to_camera_view(scene, cam, p) for p in pts]
    minx, maxx = min(u.x for u in uv), max(u.x for u in uv)
    miny, maxy = min(u.y for u in uv), max(u.y for u in uv)
    sx, sy = (maxx - minx) * 1.02, (maxy - miny) * 1.02
    minx -= (sx - (maxx - minx)) / 2
    miny -= (sy - (maxy - miny)) / 2
    img = bpy.data.images.load(os.path.join(BASE_DIR, "assets", "reference", "milk_glass_crop.png"),
                               check_existing=True)
    img.colorspace_settings.name = "sRGB"
    m = bpy.data.materials.new("MilkGlassProj")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.vector_type = "POINT"
    mp.inputs["Scale"].default_value = (1.0 / sx, 1.0 / sy, 1.0)
    mp.inputs["Location"].default_value = (-minx / sx, -miny / sy, 0.0)
    nt.links.new(tc.outputs["Window"], mp.inputs["Vector"])
    it = nt.nodes.new("ShaderNodeTexImage")
    it.image = img
    it.extension = "CLIP"
    nt.links.new(mp.outputs[0], it.inputs["Vector"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 1.0
    nt.links.new(it.outputs["Color"], em.inputs["Color"])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    lp = nt.nodes.new("ShaderNodeLightPath")
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Shadow Ray"], mx.inputs["Fac"])
    nt.links.new(em.outputs[0], mx.inputs[1])
    tr2 = nt.nodes.new("ShaderNodeBsdfTransparent")
    tr2.inputs["Color"].default_value = (0.75, 0.75, 0.75, 1)
    nt.links.new(tr2.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    proxy.data.materials.append(m)
    # 接地假软影: 径向渐变暗斑
    bpy.ops.mesh.primitive_circle_add(radius=0.055, fill_type='NGON', location=(jx, jy, 0.0015), vertices=48)
    sh = bpy.context.active_object
    sm = bpy.data.materials.new("ContactShadow")
    sm.use_nodes = True
    nt2 = sm.node_tree
    nt2.nodes.clear()
    o2 = nt2.nodes.new("ShaderNodeOutputMaterial")
    tc2 = nt2.nodes.new("ShaderNodeTexCoord")
    gr = nt2.nodes.new("ShaderNodeTexGradient")
    gr.gradient_type = "SPHERICAL"
    mp2 = nt2.nodes.new("ShaderNodeMapping")
    mp2.inputs["Scale"].default_value = (18.0, 18.0, 18.0)
    nt2.links.new(tc2.outputs["Object"], mp2.inputs["Vector"])
    nt2.links.new(mp2.outputs[0], gr.inputs["Vector"])
    rp = nt2.nodes.new("ShaderNodeValToRGB")
    rp.color_ramp.elements[0].position = 0.0
    rp.color_ramp.elements[0].color = (0, 0, 0, 1)
    rp.color_ramp.elements[1].position = 1.0
    rp.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt2.links.new(gr.outputs[0], rp.inputs[0])
    tr3 = nt2.nodes.new("ShaderNodeBsdfTransparent")
    df = nt2.nodes.new("ShaderNodeBsdfDiffuse")
    df.inputs["Color"].default_value = (0.35, 0.33, 0.30, 1)
    mx2 = nt2.nodes.new("ShaderNodeMixShader")
    nt2.links.new(rp.outputs[0], mx2.inputs["Fac"])
    nt2.links.new(df.outputs[0], mx2.inputs[1])
    nt2.links.new(tr3.outputs[0], mx2.inputs[2])
    nt2.links.new(mx2.outputs[0], o2.inputs["Surface"])
    sh.data.materials.append(sm)
    sh.visible_shadow = False
    return proxy


def rose(loc, r0, seed):
    """风格化粉玫瑰: 双环花瓣+花心 (背景失焦)"""
    import random as _rr
    rnd = _rr.Random(seed)
    pm_out = bpy.data.materials.new("RoseOut")
    pm_out.use_nodes = True
    bo = pm_out.node_tree.nodes.get("Principled BSDF")
    bo.inputs["Base Color"].default_value = (0.84, 0.40, 0.50, 1)
    bo.inputs["Roughness"].default_value = 0.55
    pm_in = bpy.data.materials.new("RoseIn")
    pm_in.use_nodes = True
    bi = pm_in.node_tree.nodes.get("Principled BSDF")
    bi.inputs["Base Color"].default_value = (0.92, 0.58, 0.64, 1)
    bi.inputs["Roughness"].default_value = 0.55
    for ring, (n, rad, tilt, mat) in enumerate([(9, 1.0, 62, pm_out), (7, 0.62, 34, pm_in)]):
        for i in range(n):
            th = 6.2832 * i / n + rnd.uniform(-0.15, 0.15) + ring * 0.4
            pr = r0 * rad * rnd.uniform(0.9, 1.1)
            px = loc[0] + pr * 0.62 * math.cos(th)
            py = loc[1] + pr * 0.62 * math.sin(th)
            pz = loc[2] + r0 * 0.30 * (1 - ring * 0.28)
            bpy.ops.mesh.primitive_uv_sphere_add(radius=pr * 0.52, location=(px, py, pz), segments=24, ring_count=16)
            pe = bpy.context.active_object
            pe.scale = (1.15, 0.7, 0.35)
            pe.rotation_euler = (math.radians(-tilt) * math.cos(th) * 0.4 + math.radians(tilt) * 0.5 * rnd.uniform(0.8, 1.2), math.radians(tilt) * 0.55, th)
            bpy.ops.object.shade_smooth()
            pe.data.materials.append(mat)
    pm_c = bpy.data.materials.new("RoseC")
    pm_c.use_nodes = True
    bc = pm_c.node_tree.nodes.get("Principled BSDF")
    bc.inputs["Base Color"].default_value = (0.72, 0.28, 0.36, 1)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r0 * 0.22, location=(loc[0], loc[1], loc[2] + r0 * 0.24), segments=24, ring_count=16)
    ce = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    ce.data.materials.append(pm_c)


def blob(name, loc, radius, scale, rot, mat, seg=32):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=loc, segments=seg, ring_count=max(12, seg // 2))
    ob = bpy.context.active_object
    ob.scale = scale
    ob.rotation_euler = rot
    bpy.ops.object.shade_smooth()
    ob.data.materials.append(mat)
    return ob


def yogurt_mat(name="Yog", tint=(0.90, 0.89, 0.86)):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (*tint, 1)
    b.inputs["Roughness"].default_value = 0.45
    if "Subsurface Weight" in b.inputs:
        b.inputs["Subsurface Weight"].default_value = 0.25
        b.inputs["Subsurface Radius"].default_value = (0.012, 0.008, 0.004)
    tc = m.node_tree.nodes.new("ShaderNodeTexCoord")
    nb = m.node_tree.nodes.new("ShaderNodeBump")
    nb.inputs["Strength"].default_value = 0.18
    nn = m.node_tree.nodes.new("ShaderNodeTexNoise")
    nn.inputs["Scale"].default_value = 42.0
    m.node_tree.links.new(tc.outputs["Object"], nn.inputs["Vector"])
    m.node_tree.links.new(nn.outputs[0], nb.inputs[0])
    m.node_tree.links.new(nb.outputs[0], b.inputs["Normal"])
    return m


def granola_mat(seed_color=1):
    m = bpy.data.materials.new(f"Granola{seed_color}")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    cols = [(0.52, 0.375, 0.20, 1), (0.45, 0.315, 0.16, 1), (0.58, 0.43, 0.245, 1)]
    b.inputs["Base Color"].default_value = cols[seed_color % 3]
    b.inputs["Roughness"].default_value = 0.72
    tc = m.node_tree.nodes.new("ShaderNodeTexCoord")
    nb = m.node_tree.nodes.new("ShaderNodeBump")
    nb.inputs["Strength"].default_value = 0.85
    nn = m.node_tree.nodes.new("ShaderNodeTexNoise")
    nn.inputs["Scale"].default_value = 130.0
    m.node_tree.links.new(tc.outputs["Object"], nn.inputs["Vector"])
    m.node_tree.links.new(nn.outputs[0], nb.inputs[0])
    m.node_tree.links.new(nb.outputs[0], b.inputs["Normal"])
    return m


def import_fruits():
    """导入莓果 gltf; 按单果分组 (Blackberry-A/B.., Strawberry-A.., Sphere.037); 隐藏 gltf 碗"""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SF_DIR, "scene.gltf"))
    imported = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in imported if o.type == "MESH"]
    bpy.context.view_layer.objects.active = meshes[0]
    for o in meshes:
        o.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in imported:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    for o in meshes:
        for m in o.data.materials:
            if not m or not m.use_nodes:
                continue
            nt = m.node_tree
            em = next((n for n in nt.nodes if n.type == "EMISSION"), None)
            tex = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image), None)
            if em is None and any(n.type == "BSDF_PRINCIPLED" for n in nt.nodes):
                continue
            for n in list(nt.nodes):
                if n.type not in ("TEX_IMAGE", "OUTPUT_MATERIAL"):
                    nt.nodes.remove(n)
            out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
            pr = nt.nodes.new("ShaderNodeBsdfPrincipled")
            pr.inputs["Roughness"].default_value = 0.52
            if tex:
                nt.links.new(tex.outputs[0], pr.inputs["Base Color"])
            nt.links.new(pr.outputs[0], out.inputs[0])
    import mathutils
    groups = {}
    for o in meshes:
        if o.name.startswith("Cylinder"):
            o.hide_render = True
            o.hide_viewport = True
            continue
        key = o.name.split("_")[0]
        groups.setdefault(key, []).append(o)
    fruits = {}
    for key, objs in groups.items():
        pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
        fruits[key] = (sum(pts, mathutils.Vector()) / len(pts), objs)
    return fruits


def place_group(center, objs, target, size, rot=None):
    """组绕组心缩放+旋转+平移 (世界矩阵直接变换)"""
    import mathutils
    pts = [o.matrix_world @ mathutils.Vector(c) for o in objs for c in o.bound_box]
    cur = max(max(p[k] for p in pts) - min(p[k] for p in pts) for k in range(3))
    s = size / cur
    m = mathutils.Matrix.Translation(target)
    if rot:
        m = m @ rot.to_matrix().to_4x4()
    m = m @ mathutils.Matrix.Scale(s, 4) @ mathutils.Matrix.Translation(-center)
    for o in objs:
        o.matrix_world = m @ o.matrix_world
    return objs


def copy_group(objs):
    dup = []
    for o in objs:
        d = o.copy()
        bpy.context.scene.collection.objects.link(d)
        dup.append(d)
    return dup


def contents():
    """碗内容 (参照B): 格兰诺拉左半 + 酸奶坨右半 (不冒过碗沿)"""
    import random as _rr
    rnd = _rr.Random(11)
    bed = yogurt_mat("Bed")
    blob("FillBed", (BC[0], BC[1], FILL - 0.016), 0.066, (1.0, 0.95, 0.22), (0, 0, 0), bed, seg=48)
    gms = [granola_mat(i) for i in range(3)]
    for i in range(13):
        th = rnd.uniform(0, 6.28)
        rr2 = rnd.uniform(0, 1) ** 0.6
        gx = BC[0] - 0.016 + rr2 * 0.036 * math.cos(th)
        gy = BC[1] + 0.003 + rr2 * 0.031 * math.sin(th)
        gz = FILL + 0.002 + rnd.uniform(0, 0.010) - rr2 * 0.008
        blob(f"Gran{i}", (gx, gy, gz), rnd.uniform(0.007, 0.011),
             (1.0, rnd.uniform(0.8, 1.0), rnd.uniform(0.55, 0.75)),
             (rnd.uniform(0, 1.2), rnd.uniform(0, 1.2), rnd.uniform(0, 6.28)),
             gms[i % 3], seg=20)
    dg = yogurt_mat("Dollop")
    blob("Dollop", (BC[0] + 0.022, BC[1] - 0.002, FILL + 0.002), 0.031, (1.0, 0.86, 0.45), (0, 0, 0), dg, seg=48)
    blob("Dollop2", (BC[0] + 0.011, BC[1] - 0.028, FILL - 0.002), 0.017, (1.0, 0.85, 0.42), (0.3, 0, 0.6), dg, seg=32)
    return bed, dg


def berries(fruits):
    """参照B莓果: 草莓1 侧躺 + 黑莓2 + 树莓2(黑莓染红) + 蓝莓2"""
    import mathutils
    st = fruits.get("Strawberry-A")
    if st:
        c, objs = st
        place_group(c, objs, (BC[0] + 0.002, BC[1] - 0.010, FILL + 0.024), 0.042,
                    rot=mathutils.Euler((math.radians(118), 0, math.radians(-25))))
    for key, tx, ty, tz, sz in [("Blackberry-A", -0.022, 0.024, FILL + 0.016, 0.030),
                                 ("Blackberry-B", 0.031, 0.020, FILL + 0.013, 0.028)]:
        f = fruits.get(key)
        if f:
            place_group(f[0], f[1], (BC[0] + tx, BC[1] + ty, tz), sz)
    red = bpy.data.materials.new("Raspberry")
    red.use_nodes = True
    br = red.node_tree.nodes.get("Principled BSDF")
    br.inputs["Base Color"].default_value = (0.55, 0.08, 0.08, 1)
    br.inputs["Roughness"].default_value = 0.55
    if "Coat Weight" in br.inputs:
        br.inputs["Coat Weight"].default_value = 0.35
        br.inputs["Coat Roughness"].default_value = 0.3
    for key, tx, ty, tz, sz in [("Blackberry-C", -0.016, -0.037, FILL + 0.014, 0.027),
                                 ("Blackberry-D", 0.037, -0.033, FILL + 0.012, 0.025)]:
        f = fruits.get(key)
        if not f:
            continue
        dup = copy_group(f[1])
        place_group(f[0], dup, (BC[0] + tx, BC[1] + ty, tz), sz)
        for o in dup:
            o.data.materials.clear()
            o.data.materials.append(red)
        # 原件移出画面 (树莓用复制体)
        for o in f[1]:
            o.hide_render = True
            o.hide_viewport = True
    bl = fruits.get("Sphere.037")
    if bl:
        place_group(bl[0], bl[1], (BC[0] - 0.033, BC[1] - 0.009, FILL + 0.009), 0.020)
        dup = copy_group(bl[1])
        place_group(bl[0], dup, (BC[0] + 0.014, BC[1] + 0.037, FILL + 0.009), 0.019)


def oat_sprinkle():
    """细燕麦: 格兰诺拉上 8 片 + 台面散落 6 片 + 碎屑 4 粒"""
    import random as _rr
    rnd = _rr.Random(29)
    om = bpy.data.materials.new("OatFine")
    om.use_nodes = True
    b = om.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.66, 0.52, 0.31, 1)
    b.inputs["Roughness"].default_value = 0.65
    for i in range(8):
        th = rnd.uniform(0, 6.28)
        rr2 = rnd.uniform(0, 1) ** 0.5
        ox = BC[0] - 0.016 + rr2 * 0.034 * math.cos(th)
        oy = BC[1] + 0.003 + rr2 * 0.029 * math.sin(th)
        oz = FILL + 0.008 + rnd.uniform(0, 0.012)
        blob(f"SOat{i}", (ox, oy, oz), rnd.uniform(0.004, 0.0055),
             (1.8, 0.8, 0.18), (rnd.uniform(-0.4, 0.4), rnd.uniform(-0.4, 0.4), rnd.uniform(0, 6.28)), om, seg=12)
    for i, (tx, ty, tr) in enumerate([(0.185, -0.068, 0.6), (0.205, -0.095, 2.1), (0.168, -0.115, 1.2),
                                       (0.218, -0.050, 2.8), (0.145, -0.132, 0.3), (0.192, -0.120, 1.7)]):
        blob(f"TOat{i}", (tx, ty, 0.005), rnd.uniform(0.005, 0.0065),
             (1.9, 0.85, 0.2), (rnd.uniform(-0.2, 0.2), rnd.uniform(-0.2, 0.2), tr), om, seg=12)
    gm = granola_mat(1)
    for i, (tx, ty) in enumerate([(0.058, -0.140), (0.078, -0.158), (0.170, -0.088), (0.042, -0.122)]):
        blob(f"Crum{i}", (tx, ty, 0.006), rnd.uniform(0.0035, 0.0055), (1.0, 0.9, 0.6),
             (rnd.uniform(0, 1), rnd.uniform(0, 1), rnd.uniform(0, 6.28)), gm, seg=14)


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    scene = fresh(args)
    heroes.world_hdri(0.06, 1.3)
    wood_table()
    lathe_bowl()
    rose((-0.180, 0.225, 0.010), 0.045, 5)
    rose((-0.128, 0.265, 0.009), 0.038, 9)
    contents()
    fruits = import_fruits()
    berries(fruits)
    oat_sprinkle()
    import mathutils as _mu
    carton = heroes.carton_master("demo_organic", scale=1.0, loc=(-0.150, 0.160, 0.004))
    carton.rotation_euler = (0, 0, math.radians(14))
    key = bpy.data.lights.new("Key", "AREA")
    key.energy = 38
    key.size = 0.9
    key.color = (1.0, 0.97, 0.92)
    ko = bpy.data.objects.new("Key", key)
    scene.collection.objects.link(ko)
    ko.location = (-0.55, -0.30, 0.85)
    kd = _mu.Vector((0.10, -0.02, 0.08)) - _mu.Vector(ko.location)
    ko.rotation_euler = kd.to_track_quat("-Z", "Y").to_euler()
    fill = bpy.data.lights.new("Fill", "AREA")
    fill.energy = 12
    fill.size = 0.8
    fo = bpy.data.objects.new("Fill", fill)
    scene.collection.objects.link(fo)
    fo.location = (0.55, -0.45, 0.40)
    fd = _mu.Vector((0.10, -0.02, 0.06)) - _mu.Vector(fo.location)
    fo.rotation_euler = fd.to_track_quat("-Z", "Y").to_euler()
    cam = bpy.data.cameras.new("Cam")
    cam.lens = 45.0
    cam.dof.use_dof = True
    cam.dof.aperture_fstop = 3.2
    cam.dof.focus_distance = 0.46
    co = bpy.data.objects.new("Cam", cam)
    scene.collection.objects.link(co)
    co.location = (0.10, -0.40, 0.36)
    tgt = _mu.Vector((0.040, 0.048, 0.075))
    co.rotation_euler = (tgt - _mu.Vector(co.location)).to_track_quat("-Z", "Y").to_euler()
    scene.camera = co
    camera_mapped_glass(scene, co)
    out = os.path.join(OUT_DIR, f"replica_{args.out}.png")
    scene.render.filepath = out
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"[REPLICA] {out}")


if __name__ == "__main__":
    main()
