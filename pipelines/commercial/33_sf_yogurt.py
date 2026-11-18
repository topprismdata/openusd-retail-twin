#!/usr/bin/env python3
"""33 - 酸奶微距 v2: 专业莓果碗资产 (Sketchfab CC-BY iJacques) + 酸奶浇注带 (自研液体语言)
资产: A bowl of berries — 670k faces, 9 PBR textures, https://sketchfab.com/3d-models/a-bowl-of-berries-2e198e82d83d440e857d3a2251e767d8
运行: Blender -b -P 33_sf_yogurt.py -- --sku demo_organic --res 900 --samples 96 [--out final]
产物: output/yogurt_macro/sf_{draft,final}.png
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
G = 9.8


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--sku", default="demo_organic")
    p.add_argument("--res", type=int, default=900)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--out", default="draft")
    return p.parse_args(argv)


def fresh(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    comfy.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.view_settings.exposure = -0.42
    world = bpy.data.worlds.new("Env")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.60, 0.575, 0.53, 1)
    bg.inputs[1].default_value = 1.2
    scene.world = world
    return scene


def dairy_mat(name="Yogurt"):
    """酸奶材质 R14: 粗糙度分区(湿亮斑↔哑光体) + 细颗粒/单向拖痕双层 bump (微观物性)"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.945, 0.905, 0.832, 1)
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.50
        bsdf.inputs["Subsurface Radius"].default_value = (0.035, 0.018, 0.008)
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.18
        bsdf.inputs["Coat Roughness"].default_value = 0.20
    tc = nt.nodes.new("ShaderNodeTexCoord")
    # 粗糙度分区: 湿亮斑 ↔ 哑光体
    n_rough = nt.nodes.new("ShaderNodeTexNoise")
    n_rough.inputs["Scale"].default_value = 15.0
    n_rough.inputs["Detail"].default_value = 4.0
    r_ramp = nt.nodes.new("ShaderNodeValToRGB")
    r_ramp.color_ramp.elements[0].position = 0.38
    r_ramp.color_ramp.elements[0].color = (0.16, 0.16, 0.16, 1)
    r_ramp.color_ramp.elements[1].position = 0.74
    r_ramp.color_ramp.elements[1].color = (0.55, 0.55, 0.55, 1)
    nt.links.new(tc.outputs["Object"], n_rough.inputs["Vector"])
    nt.links.new(n_rough.outputs[0], r_ramp.inputs[0])
    nt.links.new(r_ramp.outputs[0], bsdf.inputs["Roughness"])
    # 双层 bump: 细颗粒 + 单向拉伸拖痕 (细裂褶/勺擦痕)
    n_fine = nt.nodes.new("ShaderNodeTexNoise")
    n_fine.inputs["Scale"].default_value = 90.0
    b_fine = nt.nodes.new("ShaderNodeBump")
    b_fine.inputs["Strength"].default_value = 0.16
    nt.links.new(tc.outputs["Object"], n_fine.inputs["Vector"])
    nt.links.new(n_fine.outputs[0], b_fine.inputs[0])
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1.0, 6.0, 6.0)
    n_st = nt.nodes.new("ShaderNodeTexNoise")
    n_st.inputs["Scale"].default_value = 30.0
    n_st.inputs["Detail"].default_value = 2.0
    b_st = nt.nodes.new("ShaderNodeBump")
    b_st.inputs["Strength"].default_value = 0.14
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs[0], n_st.inputs["Vector"])
    nt.links.new(n_st.outputs[0], b_st.inputs[0])
    nt.links.new(b_fine.outputs[0], b_st.inputs["Normal"])
    # 细微裂褶: Voronoi F1 碎纹 bump (R18 去雕塑化)
    n_v = nt.nodes.new("ShaderNodeTexVoronoi")
    n_v.inputs["Scale"].default_value = 68.0
    b_v = nt.nodes.new("ShaderNodeBump")
    b_v.inputs["Strength"].default_value = 0.06
    nt.links.new(tc.outputs["Object"], n_v.inputs["Vector"])
    nt.links.new(n_v.outputs[0], b_v.inputs[0])
    nt.links.new(b_st.outputs[0], b_v.inputs["Normal"])
    nt.links.new(b_v.outputs[0], bsdf.inputs["Normal"])
    return mat

def jitter(ob, amt, seed=3):
    """顶点法向微抖 (有机边缘, data-API)"""
    import random as _rj
    _r = _rj.Random(seed)
    for vv in ob.data.vertices:
        n = vv.normal
        d = amt * _r.uniform(-1.0, 1.0)
        vv.co += n * d
    return ob


def import_berries(target_bowl_d=0.215):
    """导入专业莓果碗: 全展平(data.transform) + 碗径定标 + 材质修复(Emission→Principled)"""
    import mathutils

    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(SF_DIR, "scene.gltf"))
    imported = [o for o in bpy.data.objects if o not in before]
    meshes = [o for o in imported if o.type == "MESH"]
    # 展平: 网格空间==世界空间 (技能: data.transform, 不逐点回写)
    bpy.context.view_layer.objects.active = meshes[0]
    for o in meshes:
        o.select_set(True)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in imported:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    # 材质修复
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
            # R25 蓝莓去塑料化: 果粉微凹凸+果霜白霜变化 (仅 Sphere*=蓝莓)
            if o.name.startswith("Sphere"):
                pr.inputs["Roughness"].default_value = 0.68
                _tc = nt.nodes.new("ShaderNodeTexCoord")
                _nb = nt.nodes.new("ShaderNodeBump")
                _nb.inputs["Strength"].default_value = 0.35
                _nn = nt.nodes.new("ShaderNodeTexNoise")
                _nn.inputs["Scale"].default_value = 260.0
                nt.links.new(_tc.outputs["Object"], _nn.inputs["Vector"])
                nt.links.new(_nn.outputs[0], _nb.inputs[0])
                nt.links.new(_nb.outputs[0], pr.inputs["Normal"])
                if "Coat Weight" in pr.inputs:
                    pr.inputs["Coat Weight"].default_value = 0.4
                    pr.inputs["Coat Roughness"].default_value = 0.45
            nt.links.new(pr.outputs[0], out.inputs[0])
    # 碗径定标 (Cylinder=碗)
    bowl = next(o for o in meshes if o.name.startswith("Cylinder"))
    bx_min = min(c[0] for c in bowl.bound_box)
    bx_max = max(c[0] for c in bowl.bound_box)
    bz_min = min(c[2] for c in bowl.bound_box)
    sc = target_bowl_d / (bx_max - bx_min)
    root = bpy.data.objects.new("SF_Root", None)
    bpy.context.scene.collection.objects.link(root)
    for o in meshes:
        o.parent = root
    root.scale = (sc, sc, sc)
    # 碗中心 x/y 对齐到 (-0.02, 0.01), 碗底贴台面
    bcx = (min(c[0] for c in bowl.bound_box) + bx_max) / 2
    bcy = (min(c[1] for c in bowl.bound_box) + max(c[1] for c in bowl.bound_box)) / 2
    root.location = (-0.02 - bcx * sc, 0.01 - bcy * sc, -bz_min * sc + 0.002)
    print(f"[SF] scale={sc:.6f} meshes={len(meshes)}")
    return root, meshes


def viscous_stream(mat, mouth):
    """高黏流柱: 变径椭圆环管+横向摆动+底部外翻没入堆体 (R17 ROI-1, 替代规则圆管)"""
    import bmesh as _bm
    import mathutils as _mv
    p0 = _mv.Vector(mouth)
    p1 = _mv.Vector((0.030, -0.008, 0.100))  # 没入堆体顶
    n = 26
    rings = []
    for k in range(n):
        t = k / (n - 1)
        c = p0.lerp(p1, 0.35 * t + 0.65 * t ** 1.9)  # 先慢后快=重力加速
        d = p1 - p0
        perp = _mv.Vector((-d.y, d.x, 0))
        if perp.length > 1e-6:
            perp.normalize()
            c += perp * (0.009 * math.sin(t * 5.0 + 1.2) * (0.3 + t))
        rad = 0.0085 + 0.0035 * math.sin(t * 2.6 + 0.4) + 0.008 * t ** 2.0
        if t > 0.80:
            rad += (t - 0.80) * 0.05  # 底部外翻展开
        ell = 1.0 + 0.28 * math.sin(t * 6.5 + 2.0)
        rings.append((c, rad, ell, t))
    # R28 落点裙摆: 从柱底连续外翻没入堆体 (同一曲面, 消除"柱落团上"接缝)
    rings += [(_mv.Vector((0.0305, -0.0075, 0.0955)), 0.020, 1.05, 1.05),
              (_mv.Vector((0.0315, -0.0070, 0.0905)), 0.027, 1.02, 1.10),
              (_mv.Vector((0.0325, -0.0065, 0.0860)), 0.033, 0.98, 1.15)]
    bm = _bm.new()
    vs_prev = None
    first_ring = None
    for ri, (c, rad, ell, t) in enumerate(rings):
        if ri == 0:
            dv = rings[1][0] - c
        elif ri == len(rings) - 1:
            dv = c - rings[len(rings) - 2][0]
        else:
            dv = rings[ri + 1][0] - rings[ri - 1][0]
        dv.normalize()
        u = dv.cross(_mv.Vector((0, 0, 1)))
        if u.length < 1e-5:
            u = _mv.Vector((1, 0, 0))
        u.normalize()
        v = dv.cross(u).normalized()
        m = 12
        vs = []
        for a in range(m):
            th = a / m * 2 * math.pi + 0.3 * t
            wob = 1.0 + 0.22 * math.sin(3 * th + t * 4.0)
            pos = c + u * (rad * math.cos(th) * wob) + v * (rad * ell * math.sin(th) * wob)
            vs.append(bm.verts.new(pos))
        if vs_prev is not None:
            for a in range(m):
                b2 = (a + 1) % m
                bm.faces.new((vs_prev[a], vs_prev[b2], vs[b2], vs[a]))
        if first_ring is None:
            first_ring = vs
        vs_prev = vs
    if first_ring:
        bm.faces.new(list(reversed(first_ring)))  # 顶口封盖
    bm.normal_update()
    me = bpy.data.meshes.new("ViscStream")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("ViscStream", me)
    bpy.context.scene.collection.objects.link(ob)
    jitter(ob, 0.0011, seed=17)
    me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    # 堆体落点卷边: 3 枚浆凸贴流柱底 (冲击融合)
    for oi in range(4):
        a2 = oi * 1.57 + 0.5
        _blob(f"ImpactLip{oi}", (0.030 + 0.024 * math.cos(a2), -0.008 + 0.024 * math.sin(a2), 0.103),
              0.010, (1.4, 0.9, 0.35), (0, 0, a2), mat, seg=20)
    return ob


def yogurt_pour(mat, mouth=None):
    """酸奶浇注: 高黏流柱 + 溅起微滴 (R17 重构)"""
    viscous_stream(mat, mouth)
    # 溅起微滴 (data-API: 导入后安全)
    import random as _rd

    _r = _rd.Random(4)
    for k in range(10):
        th = _r.uniform(0, 6.28)
        rr = 0.040 + _r.uniform(0, 0.055)
        z = 0.105 + _r.uniform(0.01, 0.10)
        _blob(f"Drop{k}", (rr * math.cos(th), rr * math.sin(th), z),
              0.0035 + _r.uniform(0, 0.005), (1, 0.9, 1.3), (_r.uniform(-0.4, 0.4), _r.uniform(-0.4, 0.4), th), mat, seg=14)


def wet_mat(name="YogurtWet"):
    """湿润酸奶: 低粗糙高清漆 (独立材质, 不受 dairy 粗糙度链接影响)"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.93, 0.895, 0.835, 1)
    bsdf.inputs["Roughness"].default_value = 0.14
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.55
        bsdf.inputs["Coat Roughness"].default_value = 0.10
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.45
        bsdf.inputs["Subsurface Radius"].default_value = (0.035, 0.018, 0.008)
    return mat


def yogurt_strands(mat, berry_pts):
    """黏附拉丝: 堆体缘→莓果细连丝 (R14 high #2 失控感)"""
    import mathutils as _mv
    ctr = _mv.Vector((0.030, -0.008, 0.098))
    for si, bp in enumerate(berry_pts[:3]):
        p1 = _mv.Vector(bp)
        p1.z = min(bp[2] + 0.004, 0.106)
        d = p1 - ctr
        d.z = 0
        if d.length < 0.02:
            continue
        d.normalize()
        p0 = ctr + d * 0.044
        p0.z = 0.094
        v = p1 - p0
        L = v.length
        if L < 0.004:
            continue
        vn = v.normalized()
        rot = (0.0, -math.asin(max(-0.9, min(0.9, vn.z))), math.atan2(vn.y, vn.x))
        _blob(f"Strand{si}", tuple(p0 + v / 2), 0.0032, (L / 0.0064, 1.0, 1.0), rot, mat, seg=12)


def _blob(name, loc, radius, scale, rot, mat, seg=48):
    """data-API 椭球 (导入后创建安全)"""
    import bmesh as _bm
    bm = _bm.new()
    _bm.ops.create_uvsphere(bm, u_segments=seg, v_segments=max(12, seg * 2 // 3), radius=radius)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    ob.scale = scale
    ob.rotation_euler = rot
    bpy.context.scene.collection.objects.link(ob)
    me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    return ob


def yogurt_mound(mat, berry_pts):
    """希腊酸奶 hero: 径向折叠5道 + 勺拖槽(带翻唇) + 双顶峰 + 细噪声 (bmesh 顶点位移)"""
    import bmesh as _bm
    import random as _rd
    bpy.ops.mesh.primitive_uv_sphere_add(segments=72, ring_count=52, radius=0.050, location=(0.030, -0.008, 0.099))
    m = bpy.context.active_object
    m.scale = (1.06, 0.94, 0.46)
    bpy.ops.object.transform_apply(scale=True)
    me = m.data
    bm = _bm.new()
    bm.from_mesh(me)
    _r = _rd.Random(11)
    for v in bm.verts:
        x, y, z = v.co
        r = math.hypot(x, y)
        if r < 1e-5:
            continue
        th = math.atan2(y, x)
        # 径向折叠 5 道 (向外伸出瓣状褶, 幅值随半径增大)
        push = 0.0145 * math.sin(6 * th + 0.7) * min(1.0, r / 0.030)
        # 勺拖槽: φ=1.9 方向带状压痕, 内侧压深外侧翻唇
        gx, gy = math.cos(1.9), math.sin(1.9)
        side = x * (-gy) + y * gx
        dline, along = abs(side), x * gx + y * gy
        if abs(along) < 0.045 and dline < 0.016:
            push += -0.0075 * math.cos(dline / 0.016 * math.pi / 2) ** 2
            if dline > 0.009:
                push += 0.0045 * (1.0 if side > 0 else 0.35) * math.cos(max(0.0, (dline - 0.009) / 0.007) * math.pi / 2)
        # 双顶峰 (scoop 尖)
        push += 0.005 * math.exp(-((x - 0.004) ** 2 + (y + 0.006) ** 2) / 0.0001)
        push += 0.0035 * math.exp(-((x + 0.014) ** 2 + (y - 0.010) ** 2) / 0.00008)
        # R18 去雕塑化: 塌边回缩 (外缘向内下收)
        if r > 0.036:
            push -= 0.0035 * (r - 0.036) / 0.014
        # 不对称塌陷: 左前象限局部下沉 (勺挖后回塌)
        _cq = x * math.cos(2.2) + y * math.sin(2.2)
        if _cq > 0 and r < 0.030:
            push -= 0.004 * math.exp(-_cq * _cq / 0.0004)
        n = v.normal
        nz = _r.uniform(-0.0020, 0.0020)
        v.co.x += n.x * push
        v.co.y += n.y * push
        v.co.z += max(n.z, 0.3) * push * 1.1 + nz * (0.6 if z > 0 else 0.25)
    bm.to_mesh(me)
    bm.free()
    smv = m.modifiers.new("Smooth", "SMOOTH")
    smv.factor = 0.5
    smv.iterations = 3
    me.materials.append(mat)
    # R23 缘口垂坠 x2 (破过度完整)
    _blob("RimDroop0", (0.062, -0.026, 0.096), 0.011, (0.9, 0.7, 1.1), (0.3, 0.2, 0.5), mat, seg=20)
    _blob("RimDroop1", (-0.002, 0.042, 0.098), 0.009, (1.0, 0.7, 1.2), (-0.2, 0.3, 1.8), mat, seg=20)
    bpy.ops.object.shade_smooth()
    # 包裹垂瓣: 向最近 2 颗莓果方向伸出的低垂浆舌 (接触包裹)
    for bi, bp in enumerate(berry_pts[:3]):
        import mathutils as _mv
        ctr = _mv.Vector((0.030, -0.008, 0.098))
        d = _mv.Vector(bp) - ctr
        d.z = 0
        if d.length < 1e-4:
            continue
        d.normalize()
        pos = ctr + d * 0.036
        pos.z = 0.090
        _blob(f"MoundLobe{bi}", tuple(pos), 0.021, (1.35, 0.85, 0.38), (0, 0, math.atan2(d.y, d.x)), mat, seg=36)
    return m


def yogurt_contact(mat, wet, berry_pts, berry_sizes=None):
    """接触逻辑: 贴顶薄膜帽 x2 (包莓顶) + 侧垂丝 + 接触积液 (R17 ROI-2)"""
    for fi, bp in enumerate(berry_pts[:2]):
        sz = berry_sizes[fi] if berry_sizes else 0.030
        _cap = _blob(f"YogCap{fi}", (bp[0], bp[1], bp[2] + sz * 0.22), sz * 0.52,
              (1.25, 1.0, 0.22), (0.15 + 0.1 * fi, -0.2 - 0.1 * fi, 0.5 + fi * 0.9), mat, seg=40)
        jitter(_cap, sz * 0.06, seed=5 + fi)
        _blob(f"YogDrip{fi}", (bp[0] * 0.92 + 0.004, bp[1] * 0.92, bp[2] - sz * 0.30), sz * 0.20,
              (0.7, 0.7, 1.9), (0, 0, fi * 1.1 + 0.4), mat, seg=16)
    for pi, bp in enumerate(berry_pts[:2]):
        _blob(f"WetPool{pi}", (bp[0] * 0.75 + 0.008, bp[1] * 0.75 + 0.004, 0.088), 0.015, (1.2, 0.9, 0.14), (0, 0, pi * 1.3), wet, seg=32)
    # R23 湿润接触桥: 堆缘↔莓果黏附桥 x2 (湿亮)
    if len(berry_pts) >= 2:
        import mathutils as _mb2
        _ctr = _mb2.Vector((0.030, -0.008, 0.100))
        for wi, bp in enumerate(berry_pts[:2]):
            _p1 = _mb2.Vector(bp)
            _p1.z = max(bp[2] - 0.006, 0.092)
            _mid = (_ctr + _p1) / 2
            _dirv = _p1 - _ctr
            _L = max(_dirv.length - 0.030, 0.006)
            _dn = _dirv.normalized()
            _rot = (0.0, -math.asin(max(-0.9, min(0.9, _dn.z))), math.atan2(_dn.y, _dn.x))
            _blob(f"WetBridge{wi}", tuple(_ctr + _dn * (0.030 + _L / 2 + 0.002)), 0.0055,
                  (_L / 0.011, 0.8, 0.7), _rot, wet, seg=12)
    # R22 去完美化: 远端莓果小薄帽 x2 (蓝莓果粉酸奶渍)
    for fi, bp in enumerate(berry_pts[2:4]):
        sz2 = (berry_sizes[2 + fi] if berry_sizes and len(berry_sizes) > 2 + fi else 0.030)
        _blob(f"YogTint{fi}", (bp[0] + 0.003 * (1 - fi), bp[1] - 0.002, bp[2] + sz2 * 0.24), sz2 * 0.42,
              (1.1, 0.85, 0.16), (0.3, -0.2, 1.0 + fi), mat, seg=28)


def half_bury(meshes, mat):
    """深半埋莓果 x2: 复制沉入酸奶缘, 一深一斜 (R14 high #2 失控感)"""
    import mathutils as _mv
    ctr = _mv.Vector((0.030, -0.008, 0.100))
    cands = []
    for o in meshes:
        if not o.type == "MESH" or o.name.startswith(("Cylinder", "SF")):
            continue
        pts = [o.matrix_world @ _mv.Vector(c) for c in o.bound_box]
        c = sum(pts, _mv.Vector()) / 8.0
        size = max((max(p[i] for p in pts) - min(p[i] for p in pts)) for i in range(3))
        if not (0.014 < size < 0.040):
            continue
        cands.append(((c - ctr).length, o, c))
    cands.sort(key=lambda t: t[0])
    for k, (_, best, c) in enumerate(cands[:2]):
        dupe = best.copy()
        dupe.data = best.data
        bpy.context.scene.collection.objects.link(dupe)
        sink = ctr + (c - ctr).normalized() * 0.030
        sink.z = 0.086 if k == 0 else 0.091
        dupe.location = dupe.location + (sink - c)
        dupe.rotation_euler = (0.5 + 0.3 * k, 0.2 - 0.25 * k, 0.9 + k * 1.7)
    return cands[0][1] if cands else None


def oat_mat():
    """燕麦片材质: 赖皮暖棕"""
    m = bpy.data.materials.new("Oat")
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.80, 0.65, 0.40, 1)
    b.inputs["Roughness"].default_value = 0.62
    if "Subsurface Weight" in b.inputs:
        b.inputs["Subsurface Weight"].default_value = 0.15
        b.inputs["Subsurface Radius"].default_value = (0.008, 0.005, 0.002)
    return m


def oats_and_mix(ymat, wet, bps, bsz):
    """局部混合系统: 燕麦 x7 + 压覆半埋 + 拖痕 smear (R19 ROI-1 真实早餐语义)"""
    import random as _ro
    om = oat_mat()
    _r = _ro.Random(23)
    # 堆右翼散落 4 片 (贴堆面坡向)
    flank = [(0.062, -0.014, 0.112, 0.7), (0.055, -0.028, 0.108, 2.1), (0.070, -0.002, 0.106, 1.2), (0.046, 0.020, 0.114, 2.8)]
    for oi, (ox, oy, oz, orot) in enumerate(flank):
        _blob(f"Oat{oi}", (ox, oy, oz), 0.0065, (1.7, 0.9, 0.14), (_r.uniform(-0.3, 0.3), _r.uniform(-0.3, 0.3), orot), om, seg=14)
    # R22 燕麦基底层: 堆顶+碗心密集散布 20 片 (评审板尺寸下一眼可辨)
    # R26 真实燕麦卷片尺寸 (长 19mm) + 前景可见带聚簇
    for oi in range(20):
        th = _r.uniform(0, 6.28)
        rr2 = 0.008 + _r.uniform(0, 0.036) ** 0.7
        ox = 0.030 + rr2 * math.cos(th)
        oy = -0.008 + rr2 * math.sin(th) * 0.92
        oz = 0.112 + _r.uniform(0, 0.010) - rr2 * 0.35
        _blob(f"OatBase{oi}", (ox, oy, oz), 0.0092 + _r.uniform(0, 0.0018),
              (1.9, 0.75, 0.22), (_r.uniform(-0.45, 0.45), _r.uniform(-0.45, 0.45), _r.uniform(0, 6.28)), om, seg=12)
    # R26 前景聚簇: 画面前下方碗沿布面 6 片大卷片 (板尺寸一眼可辨)
    for oi, (ox, oy, orz) in enumerate([(0.082, -0.128, 0.5), (0.108, -0.150, 1.8), (0.062, -0.158, 2.9),
                                         (0.130, -0.122, 0.2), (0.095, -0.170, 1.1), (0.145, -0.162, 2.4)]):
        _blob(f"OatFront{oi}", (ox, oy, 0.004), 0.0105, (1.9, 0.8, 0.2), (_r.uniform(-0.15, 0.15), _r.uniform(-0.15, 0.15), orz), om, seg=12)
    # R23 参与混合: 被压进堆缘 4 片 (半埋+斜插) + 斜靠莓果 2 片
    for oi, (ox, oy, oz, rx2, rz2) in enumerate([(0.058, -0.008, 0.104, 0.9, 0.4), (0.020, 0.034, 0.106, 0.7, 2.2),
                                                  (0.048, 0.030, 0.100, 1.0, 1.3), (0.008, -0.046, 0.102, 0.8, 0.9)]):
        _blob(f"OatPress{oi}", (ox, oy, oz), 0.0058, (1.6, 0.85, 0.35), (rx2, 0.2, rz2), om, seg=12)
    # 莓间低洼 4 片 (半埋)
    for oi, (ox, oy, oz) in enumerate([(0.058, 0.014, 0.098), (-0.006, 0.030, 0.096), (0.012, -0.044, 0.094), (0.046, -0.040, 0.098)]):
        _blob(f"OatLow{oi}", (ox, oy, oz), 0.0055, (1.7, 0.9, 0.10), (_r.uniform(-0.3, 0.3), _r.uniform(-0.3, 0.3), _r.uniform(0, 6.28)), om, seg=12)
    # 前莓顶 1 片 + 碗沿 1 片 + 台面 1 片 (散落叙事)
    if bps:
        bp0 = bps[0]
        _blob("OatBerry", (bp0[0], bp0[1] - 0.004, bp0[2] + bsz[0] * 0.42), 0.006, (1.6, 0.9, 0.15), (0.2, 0.4, 1.9), om, seg=14)
    _blob("OatRim", (0.088, -0.070, 0.082), 0.0055, (1.5, 0.9, 0.16), (0.4, -0.5, 0.8), om, seg=14)
    _blob("OatTable", (0.128, -0.148, 0.004), 0.006, (1.7, 0.9, 0.13), (0, 0, 2.4), om, seg=14)
    # 拖痕 smear: 堆心→前莓的薄铺三连 (混合语义)
    if len(bps) >= 1:
        bx, by, bz = bps[0]
        for si, tt in enumerate([0.25, 0.5, 0.75]):
            sx = 0.030 + (bx - 0.030) * tt
            sy = -0.008 + (by + 0.008) * tt
            sz2 = 0.108 - (0.108 - bz) * tt
            _blob(f"Smear{si}", (sx, sy, sz2), 0.011 - si * 0.001,
                  (1.9 - si * 0.2, 0.75, 0.10), (0.1, -0.1, 0.6 + si * 0.4), ymat, seg=20)
    # 深压覆: 堆缘莓粒下沉 (把 WetPool 换成压覆积液)
    if len(bps) >= 2:
        bp1 = bps[1]
        _blob("PressPool", (bp1[0] * 0.8 + 0.006, bp1[1] * 0.8 + 0.005, bp1[2] - bsz[1] * 0.45),
              0.013, (1.25, 0.95, 0.12), (0, 0, 0.9), wet, seg=24)


def cloth_table():
    """奶油织物桌布: 织纹双层 bump + 大尺度软褶 (R20, 替代 CG 平面)"""
    bpy.ops.mesh.primitive_plane_add(size=14.0, location=(-0.1, 0.4, 0.0006))
    cl = bpy.context.active_object
    cmat = bpy.data.materials.new("Cloth")
    cmat.use_nodes = True
    nt = cmat.node_tree
    b = nt.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.615, 0.555, 0.455, 1)
    b.inputs["Roughness"].default_value = 0.82
    if "Sheen Weight" in b.inputs:
        b.inputs["Sheen Weight"].default_value = 0.35
        b.inputs["Sheen Roughness"].default_value = 0.4
    tc = nt.nodes.new("ShaderNodeTexCoord")
    # R21: 真实亚麻布纹贴图提升 (Pexels 7794365, albedo+bump 同源)
    _img = bpy.data.images.load(os.path.join(BASE_DIR, "assets", "reference", "cloth_linen.jpg"), check_existing=True)
    _img.colorspace_settings.name = "sRGB"
    itex = nt.nodes.new("ShaderNodeTexImage")
    itex.image = _img
    itex.extension = "REPEAT"
    m_uv = nt.nodes.new("ShaderNodeMapping")
    m_uv.inputs["Scale"].default_value = (12.0, 12.0, 1.0)
    nt.links.new(tc.outputs["UV"], m_uv.inputs["Vector"])
    nt.links.new(m_uv.outputs[0], itex.inputs["Vector"])
    nt.links.new(itex.outputs[0], b.inputs["Base Color"])
    rgb2bw = nt.nodes.new("ShaderNodeRGBToBW")
    nt.links.new(itex.outputs[0], rgb2bw.inputs[0])
    b_w2 = nt.nodes.new("ShaderNodeBump")
    b_w2.inputs["Strength"].default_value = 0.5
    nt.links.new(rgb2bw.outputs[0], b_w2.inputs[0])
    n_r = nt.nodes.new("ShaderNodeTexNoise")
    n_r.inputs["Scale"].default_value = 9.0
    rr = nt.nodes.new("ShaderNodeValToRGB")
    rr.color_ramp.elements[0].position = 0.35
    rr.color_ramp.elements[0].color = (0.72, 0.72, 0.72, 1)
    rr.color_ramp.elements[1].position = 0.8
    rr.color_ramp.elements[1].color = (0.92, 0.92, 0.92, 1)
    nt.links.new(tc.outputs["Object"], n_r.inputs["Vector"])
    nt.links.new(n_r.outputs[0], rr.inputs[0])
    nt.links.new(rr.outputs[0], b.inputs["Roughness"])
    nt.links.new(b_w2.outputs[0], b.inputs["Normal"])
    cl.data.materials.append(cmat)
    for pl in cl.data.polygons:
        pl.use_smooth = True
    dv = cl.modifiers.new("Fold", "DISPLACE")
    tex = bpy.data.textures.new("ClothFold", "CLOUDS")
    tex.noise_scale = 0.45
    tex.noise_depth = 3
    dv.texture = tex
    dv.strength = 0.02
    smv = cl.modifiers.new("Smooth", "SMOOTH")
    smv.factor = 0.7
    smv.iterations = 4
    return cl


def honey_drizzle():
    """蜂蜜淋酱: 琥珀高光条 x3 (堆顶) + 莓面蜜池 x2 + 台面滴落 (参照 intl_4006362 的琥珀光)"""
    hmat = bpy.data.materials.new("Honey")
    hmat.use_nodes = True
    b = hmat.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.86, 0.42, 0.05, 1)
    b.inputs["Roughness"].default_value = 0.06
    if "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = 1.0
        b.inputs["Coat Roughness"].default_value = 0.04
    if "Subsurface Weight" in b.inputs:
        b.inputs["Subsurface Weight"].default_value = 0.3
        b.inputs["Subsurface Radius"].default_value = (0.02, 0.01, 0.002)
    _blob("Honey1", (0.052, -0.018, 0.124), 0.011, (1.7, 0.55, 0.16), (0.1, -0.2, 0.8), hmat, seg=24)
    _blob("HoneyPool1", (0.064, -0.034, 0.116), 0.010, (1.0, 0.8, 0.12), (0, 0, 0.4), hmat, seg=20)
    _blob("HoneyPool2", (-0.012, 0.030, 0.116), 0.009, (1.0, 0.8, 0.12), (0, 0, 1.2), hmat, seg=20)
    _blob("HoneyDrop", (-0.004, -0.070, 0.006), 0.008, (1.0, 1.0, 0.35), (0, 0, 0), hmat, seg=16)
    # 落点回流褶 x2 + 湿亮斑 (R18 ROI-3, 不扩结构)
    _blob("BackFold0", (0.052, 0.006, 0.104), 0.012, (1.5, 0.7, 0.22), (0.5, 0.2, 0.9), hmat, seg=20)
    _blob("BackFold1", (0.004, 0.036, 0.102), 0.010, (1.3, 0.8, 0.24), (0.4, -0.3, -0.7), hmat, seg=20)


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    scene = fresh(args)
    heroes.world_hdri(0.10, 1.3)
    cloth_table()
    # 母本景深
    import mathutils as _mu

    _land = _mu.Vector((0.025, -0.005, 0.105))
    _mouth_t = _mu.Vector((0.055, -0.030, 0.34))  # 经典裁切: 盒体完全出画顶, 纯流柱落碗
    _pour = (_land - _mouth_t).normalized()
    _cam_dir = (_mu.Vector((0.180, -0.500, 0.128)) - _mouth_t).normalized()
    _y = (_cam_dir - _cam_dir.dot(_pour) * _pour).normalized()  # 标签朝相机
    _x = _y.cross(_pour).normalized()
    _H = 0.326 * 0.85
    carton = heroes.carton_master(args.sku, scale=0.85,
                                  loc=tuple(_mouth_t - _H * _pour))
    carton.rotation_euler = _mu.Matrix((_x, _y, _pour)).transposed().to_euler()
    for _ob in (carton,):
        for _c in list(_ob.users_collection):
            _c.objects.unlink(_ob)
        scene.collection.objects.link(_ob)
        _ob.hide_render = False
        _ob.hide_viewport = False
    # EMIT 诊断: 盒体自发光 (临时)
    if os.environ.get("EMIT_CARTON") == "1":
        for _m in carton.data.materials:
            if _m and _m.use_nodes:
                _nt = _m.node_tree
                for _n in list(_nt.nodes):
                    if _n.type != "OUTPUT_MATERIAL":
                        _nt.nodes.remove(_n)
                _o = _nt.nodes.new("ShaderNodeEmission")
                _o.inputs[0].default_value = (1, 0.2, 0.1, 1)
                _o.inputs[1].default_value = 2.0
                _out = next(_n for _n in _nt.nodes if _n.type == "OUTPUT_MATERIAL")
                _nt.links.new(_o.outputs[0], _out.inputs[0])
    # 盒面专光: 前左上柔光打亮标签 (前倾后主光成背光)
    cfill = bpy.data.lights.new("CartonFill", "AREA")
    cfill.energy = 20
    cfill.size = 0.45
    cfill.color = (1.0, 0.96, 0.90)
    cfo = bpy.data.objects.new("CartonFill", cfill)
    scene.collection.objects.link(cfo)
    cfo.location = (-0.42, -0.28, 0.62)
    _cd = _mu.Vector((0.075, -0.045, 0.280)) - _mu.Vector(cfo.location)
    cfo.rotation_euler = _cd.to_track_quat("-Z", "Y").to_euler()

    # 专业莓果碗 (carton ops 块之后、data-API 后件之前导入: ops 件全部在导入前创建)
    sf_root, sf_meshes = import_berries()
    # 莓果世界坐标采样 (小网格=莓果, 供酸奶体包裹接触)
    import mathutils as _mv
    _bps = []
    _bsz = []
    for _o in sf_meshes:
        if _o.name.startswith(("Cylinder", "SF")):
            continue
        _pts = [_o.matrix_world @ _mv.Vector(c) for c in _o.bound_box]
        _c = sum(_pts, _mv.Vector()) / 8.0
        _sz = max((max(p[i] for p in _pts) - min(p[i] for p in _pts)) for i in range(3))
        _dc = (_c - _mv.Vector((0.030, -0.008, 0.100))).length
        if 0.014 < _sz < 0.090 and _dc < 0.070:
            _bps.append(tuple(_c))
            _bsz.append(_sz)
    _bps.sort(key=lambda p: (p[0] - 0.030) ** 2 + (p[1] + 0.008) ** 2)

    # 酸奶浇注 (十轮液体语言): 从盒口实测世界坐标引出
    _carton = next((o for o in bpy.data.objects if o.name.startswith("Carton_")), None)
    assert _carton is not None, "carton object missing"
    bpy.context.view_layer.update()
    _mouth = _carton.matrix_world @ _mv.Vector((0, 0, 0.326))  # 盒口=顶面中心(scale后即设计口位)
    print(f"[SF] carton mouth={tuple(round(v, 4) for v in _mouth)} berries={len(_bps)}")
    _ym = dairy_mat("Yogurt")
    _yw = wet_mat()
    yogurt_pour(_ym, _mouth)
    yogurt_mound(_ym, _bps)
    yogurt_contact(_ym, _yw, _bps, _bsz)
    yogurt_strands(_ym, _bps)
    oats_and_mix(_ym, _yw, _bps, _bsz)
    half_bury(sf_meshes, None)
    # 陶瓷碗釉面: clearcoat 高光 (玻璃感替代, 无几何风险)
    for _o in sf_meshes:
        if _o.name.startswith("Cylinder"):
            for _m in _o.data.materials:
                if _m and _m.use_nodes:
                    _b = _m.node_tree.nodes.get("Principled BSDF")
                    if _b is not None and "Coat Weight" in _b.inputs:
                        _b.inputs["Coat Weight"].default_value = 1.0
                        _b.inputs["Coat Roughness"].default_value = 0.06
    # 碗底接触阴影 (接地, 器皿不再悬浮)
    csm = bpy.data.materials.new("ContactShade")
    csm.use_nodes = True
    _cb = csm.node_tree.nodes.get("Principled BSDF")
    _cb.inputs["Base Color"].default_value = (0.18, 0.15, 0.12, 1)
    _cb.inputs["Roughness"].default_value = 0.7
    if "Alpha" in _cb.inputs:
        _cb.inputs["Alpha"].default_value = 0.35
    _blob("BowlContact", (-0.016, 0.014, 0.003), 0.104, (1.04, 1.0, 0.015), (0, 0, 0), csm, seg=48)
    honey_drizzle()
    # 食摄光: 柔窗光侧逆 + 暖补
    heroes.key_fill_light(key_loc=(0.55, -0.50, 0.50), key_e=0.22)
    rim = bpy.data.lights.new("Rim", "AREA")
    rim.energy = 38
    rim.size = 0.9
    rim.color = (0.93, 0.90, 0.85)
    ro = bpy.data.objects.new("Rim", rim)
    scene.collection.objects.link(ro)
    ro.location = (-0.50, 0.38, 0.48)
    import mathutils as _mu

    _d = _mu.Vector((0.0, 0.0, 0.09)) - _mu.Vector(ro.location)
    ro.rotation_euler = _d.to_track_quat("-Z", "Y").to_euler()
    bounce = bpy.data.lights.new("Bounce", "AREA")
    bounce.energy = 6
    bounce.size = 0.7
    bounce.color = (1.0, 0.97, 0.92)
    bo = bpy.data.objects.new("Bounce", bounce)
    scene.collection.objects.link(bo)
    bo.location = (0.35, -0.42, 0.18)
    _bd = _mu.Vector((0.02, -0.01, 0.10)) - _mu.Vector(bo.location)
    bo.rotation_euler = _bd.to_track_quat("-Z", "Y").to_euler()
    heroes.setup_cam(loc=(0.115, -0.410, 0.435), look_at=(0.008, -0.006, 0.088), lens=46, fstop=6.3)
    import os as _os
    if _os.environ.get("HIDE_RB") == "1" and rb:
        rb.hide_render = True
    if _os.environ.get("HIDE_SF") == "1":
        for _o in bpy.data.objects:
            if _o.name.startswith(("Blackberry", "Sphere", "Strawberry", "Cylinder", "SF_Root")) or (_o.parent and _o.parent.name == "SF_Root"):
                _o.hide_render = True
    out = os.path.join(OUT_DIR, f"sf_{args.out}.png")
    scene.render.filepath = out
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    # R29 摄影捕获签名后处理: 黑位+暗角+横向色差+亮度相关颗粒 (破"过净渲染"数字签名)
    _raw = os.path.join(OUT_DIR, "sf_raw.png")
    os.rename(out, _raw)
    _photographic_post(_raw, out)
    print(f"[SF-YOGURT] {out}")


def _photographic_post(raw_path, out_path):
    """R29: 模拟真实相机捕获签名 — 黑位/暗角/色差/颗粒, 确定性 seed=7."""
    import numpy as _np
    from PIL import Image as _PImg
    _im = _PImg.open(raw_path).convert("RGB")
    _a = _np.asarray(_im).astype(_np.float32) / 255.0
    h, w = _a.shape[:2]
    # 1) 传感器黑位提升 + 轻微高光压缩
    _a = 0.008 + _a * (1.0 - 0.35 * _np.clip(_a - 0.82, 0, None))
    # 2) cos^4 近似暗角 (中心不动, 角 -10%)
    _yy, _xx = _np.mgrid[0:h, 0:w].astype(_np.float32)
    _r = _np.sqrt(((_xx - w / 2) / (w / 2)) ** 2 + ((_yy - h / 2) / (h / 2)) ** 2)
    _a *= (1.0 - 0.10 * _np.clip(_r - 0.55, 0, None) ** 1.5 * 2.2)[..., None]
    # 3) 横向色差: R 外扩 +0.22%, B 内缩 -0.22% (径向 CA)
    def _cscale(ch, f):
        w2, h2 = int(w * f), int(h * f)
        im2 = _PImg.fromarray((ch * 255).astype("uint8")).resize((w2, h2), _PImg.BILINEAR)
        arr = _np.asarray(im2).astype(_np.float32) / 255.0
        if f >= 1.0:
            l, t = (w2 - w) // 2, (h2 - h) // 2
            return _np.asarray(im2.crop((l, t, l + w, t + h))).astype(_np.float32) / 255.0
        l, t = (w - w2) // 2, (h - h2) // 2
        out = _np.empty((h, w), _np.float32)
        out[t:t+h2, l:l+w2] = arr
        if t > 0: out[:t, :] = out[t, :][None, :]
        if t + h2 < h: out[t+h2:, :] = out[t+h2-1, :][None, :]
        if l > 0: out[:, :l] = out[:, l][:, None]
        if l + w2 < w: out[:, l+w2:] = out[:, l+w2-1][:, None]
        return out
    _a[..., 0] = _cscale(_a[..., 0], 1.0022)
    _a[..., 2] = _cscale(_a[..., 2], 0.9978)
    # 4) 亮度相关高斯颗粒 (暗部少亮部多), sigma=2.0/255
    _rng = _np.random.default_rng(7)
    _g = _rng.normal(0, 2.0, (h, w, 1)) / 255.0
    _a = _a + _g * (0.35 + 0.65 * _a.mean(axis=2, keepdims=True))
    _a = _np.clip(_a, 0, 1)
    _PImg.fromarray((_a * 255).astype("uint8")).save(out_path)


if __name__ == "__main__":
    main()
