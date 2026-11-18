#!/usr/bin/env python3
"""32 - 酸奶微距翻新: 物性/湿润度/细纹理/食物摄影可信度 (方法轮移植自飞溅十轮战役)
针对 GPT R11 短板: "白色几何甜点感, 物性/湿润度/细纹理/食物摄影可信度不足"
运行: Blender -b -P 32_yogurt_macro.py -- --sku demo_organic --res 900 --samples 96 [--out final]
产物: output/yogurt_macro/{draft,final}.png
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


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--sku", default="demo_organic")
    p.add_argument("--res", type=int, default=900)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--out", default="draft")
    a = p.parse_args(argv)
    return a


def fresh(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    comfy.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.view_settings.exposure = -0.30
    world = bpy.data.worlds.new("Env")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.62, 0.585, 0.54, 1)
    bg.inputs[1].default_value = 0.95
    scene.world = world
    return scene


def dairy_mat(name="Yogurt"):
    """酸奶物性: 乳染基色 + 双尺度微纹理 + SSS 暖衰减 + 顶面湿光泽 (clearcoat)"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.935, 0.908, 0.855, 1)
    bsdf.inputs["Roughness"].default_value = 0.42
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.50
        bsdf.inputs["Subsurface Radius"].default_value = (0.035, 0.018, 0.008)
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.16
        bsdf.inputs["Coat Roughness"].default_value = 0.22
    # 双尺度 bump: 细颗粒(奶体) + 中尺度(搅拌纹)
    n_fine = nt.nodes.new("ShaderNodeTexNoise")
    n_fine.inputs["Scale"].default_value = 90.0
    n_fine.inputs["Detail"].default_value = 4.0
    n_med = nt.nodes.new("ShaderNodeTexNoise")
    n_med.inputs["Scale"].default_value = 24.0
    n_med.inputs["Detail"].default_value = 6.0
    b_fine = nt.nodes.new("ShaderNodeBump")
    b_fine.inputs["Strength"].default_value = 0.30
    b_med = nt.nodes.new("ShaderNodeBump")
    b_med.inputs["Strength"].default_value = 0.42
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = "ADD"
    nt.links.new(n_fine.outputs[0], b_fine.inputs[0])
    nt.links.new(n_med.outputs[0], b_med.inputs[0])
    nt.links.new(b_fine.outputs[0], add.inputs[0])
    nt.links.new(b_med.outputs[0], add.inputs[1])
    nt.links.new(add.outputs[0], bsdf.inputs["Normal"])
    return mat


def build_yogurt_body():
    """酸奶体: 带中央峰的穹顶 + 螺旋搅拌纹(波纹置换) + 沿碗壁弯月面"""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=64, radius=0.106, location=(0.02, 0.0, 0.080))
    yo = bpy.context.active_object
    yo.scale = (1.0, 0.93, 0.44)
    bpy.ops.object.transform_apply(scale=True)
    # 螺旋搅拌纹: wave+distortion 沿 z 混合, 置换加深
    dv = yo.modifiers.new("Swirl", "DISPLACE")
    tex = bpy.data.textures.new("SwirlTex", "CLOUDS")
    tex.noise_scale = 0.028
    tex.noise_depth = 4
    dv.texture = tex
    dv.strength = 0.0028
    tex.noise_scale = 0.055
    smv = yo.modifiers.new("Smooth", "SMOOTH")
    smv.factor = 0.62
    smv.iterations = 6
    mat = dairy_mat("Yogurt")
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    # 搅拌纹染色: 高失真波纹 → 微色差 ramp
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 11.0
    wave.inputs["Distortion"].default_value = 18.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.905, 0.872, 0.812, 1)
    ramp.color_ramp.elements[1].color = (0.955, 0.930, 0.878, 1)
    nt.links.new(wave.outputs[0], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], bsdf.inputs["Base Color"])
    yo.data.materials.append(mat)
    # 中央拉峰 (勺子提起的酸奶尖)
    bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.034, radius2=0.0035, depth=0.046,
                                    location=(0.012, -0.004, 0.127))
    peak = bpy.context.active_object
    peak.rotation_euler = (0.10, 0.14, 0.7)
    sm = peak.modifiers.new("Smooth", "SMOOTH")
    sm.factor = 0.6
    sm.iterations = 6
    dv2 = peak.modifiers.new("Swirl", "DISPLACE")
    dv2.texture = tex
    dv2.strength = 0.005
    peak.data.materials.append(mat)
    # 勺拉厚褶: 两道大弧榫压入穹顶 (真帧语言: 厚酸奶褶皱垂坠)
    for fk, (fx, fy, fa) in enumerate([(-0.022, 0.020, 0.5)]):
        bpy.ops.mesh.primitive_torus_add(major_radius=0.040, minor_radius=0.0105,
                                         location=(0.02 + fx, 0.0 + fy, 0.092), rotation=(math.pi / 2 + 0.55, 0, fa))
        fold = bpy.context.active_object
        fold.scale = (1.0, 0.72, 0.62)
        bpy.ops.object.transform_apply(scale=True)
        fold.data.materials.append(mat)
        bpy.ops.object.shade_smooth()
    # 弯月面: 酸奶沿碗壁上爬的湿润接合环
    bpy.ops.mesh.primitive_torus_add(major_radius=0.100, minor_radius=0.008, location=(0.02, 0.0, 0.082))
    men = bpy.context.active_object
    men.scale = (1.0, 0.95, 0.35)
    bpy.ops.object.transform_apply(scale=True)
    men_mat = dairy_mat("Meniscus")
    mb = men_mat.node_tree.nodes.get("Principled BSDF")
    if "Coat Weight" in mb.inputs:
        mb.inputs["Coat Weight"].default_value = 0.45
        mb.inputs["Coat Roughness"].default_value = 0.08
    mb.inputs["Roughness"].default_value = 0.24
    men.data.materials.append(men_mat)
    bpy.ops.object.shade_smooth()
    return yo


def honey_pool(pos, r=0.020, seed=0):
    """蜜洼: 不规则琥珀高光薄洼 (真帧: 蜜汁在酸奶面聚成金洼)"""
    import random as _rh

    _r = _rh.Random(seed)
    bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=r, depth=0.0035, location=(pos[0], pos[1], pos[2]))
    hp = bpy.context.active_object
    hp.scale = (1.0, _r.uniform(0.6, 0.9), 1.0)
    hp.rotation_euler = (0, 0, _r.uniform(0, 3.1))
    bpy.ops.object.transform_apply(scale=True)
    dv = hp.modifiers.new("Irreg", "DISPLACE")
    tex = bpy.data.textures.new("HoneyTex", "VORONOI")
    tex.noise_scale = r * 0.9
    dv.texture = tex
    dv.strength = 0.003
    mat = bpy.data.materials.new(f"Honey{seed}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.78, 0.46, 0.10, 1)
    bsdf.inputs["Roughness"].default_value = 0.04
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.6
    hp.data.materials.append(mat)
    bpy.ops.object.shade_smooth()


def jam_swirl():
    """果酱: 压入酸奶体的不规则浆池 + 拖尾 (替代浮在表面的圆环)"""
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=0.036, depth=0.007, location=(0.028, 0.006, 0.1235))
    jam = bpy.context.active_object
    jam.scale = (1.0, 0.82, 1.0)
    bpy.ops.object.transform_apply(scale=True)
    dv = jam.modifiers.new("Irreg", "DISPLACE")
    tex = bpy.data.textures.new("JamTex", "VORONOI")
    tex.noise_scale = 0.012
    dv.texture = tex
    dv.strength = 0.004
    mat = bpy.data.materials.new("Jam")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.272, 0.030, 0.046, 1)
    bsdf.inputs["Roughness"].default_value = 0.19
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.55
        bsdf.inputs["Subsurface Radius"].default_value = (0.018, 0.004, 0.002)
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.35
        bsdf.inputs["Coat Roughness"].default_value = 0.06
    jam.data.materials.append(mat)
    bpy.ops.object.shade_smooth()
    # 拖尾: 果酱被搅出的细痕
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0.062, -0.014, 0.121))
    tail = bpy.context.active_object
    tail.scale = (0.040, 0.0035, 0.0016)
    tail.rotation_euler = (0, 0, -0.6)
    tail.location.z = 0.1265
    bpy.ops.object.transform_apply(scale=True)
    bev = tail.modifiers.new("Bev", "BEVEL")
    bev.width = 0.0015
    tail.data.materials.append(mat)
    return jam


def raspberry(pos, r=0.015, seed=0):
    """树莓: 20+ 小核果球簇成半球 (替代光滑塑料珠)"""
    import random as _rd

    _r = _rd.Random(seed)
    mat = bpy.data.materials.new(f"Rasp{seed}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.43, 0.052, 0.062, 1)
    bsdf.inputs["Roughness"].default_value = 0.46
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.28
        bsdf.inputs["Subsurface Radius"].default_value = (0.005, 0.0015, 0.0008)
    dr = r * 0.34
    for ring, (rr, n, z) in enumerate([(0.0, 1, 0.0), (0.62, 6, 0.24), (1.0, 10, 0.42), (1.25, 5, 0.62)]):
        for k in range(n):
            th = 2 * math.pi * k / n + ring * 0.5
            off = _r.uniform(-0.06, 0.06) * r
            bpy.ops.mesh.primitive_uv_sphere_add(segments=14, ring_count=10, radius=dr * _r.uniform(0.85, 1.1),
                                                 location=(pos[0] + rr * dr * math.cos(th) + off,
                                                           pos[1] + rr * dr * math.sin(th) + off,
                                                           pos[2] + z * dr * 1.7))
            d = bpy.context.active_object
            d.data.materials.append(mat)
            bpy.ops.object.shade_smooth()
    # 湿润高光珠
    for k in range(2):
        th = _r.uniform(0, 6.28)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=10, ring_count=8, radius=0.0012,
                                             location=(pos[0] + math.cos(th) * r * 0.7, pos[1] + math.sin(th) * r * 0.7, pos[2] + r * 0.5))
        w = bpy.context.active_object
        wmat = bpy.data.materials.new(f"W{seed}{k}")
        wmat.use_nodes = True
        wb = wmat.node_tree.nodes.get("Principled BSDF")
        wb.inputs["Roughness"].default_value = 0.03
        wb.inputs["Base Color"].default_value = (0.80, 0.50, 0.14, 1)  # 琥珀蜜珠
        if "Coat Weight" in wb.inputs:
            wb.inputs["Coat Weight"].default_value = 1.0
        w.data.materials.append(wmat)


def blueberry(pos, r=0.012, seed=1):
    """蓝莓: 微不规则球 + 果粉哑光 + 顶端花萼冠"""
    import random as _rd

    _r = _rd.Random(seed)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=28, ring_count=20, radius=r, location=pos)
    b = bpy.context.active_object
    b.scale = (1.0, _r.uniform(0.92, 1.0), _r.uniform(0.88, 0.96))
    bpy.ops.object.transform_apply(scale=True)
    dv = b.modifiers.new("Irreg", "DISPLACE")
    tex = bpy.data.textures.new("BbTex", "VORONOI")
    tex.noise_scale = r * 0.8
    dv.texture = tex
    dv.strength = r * 0.10
    mat = bpy.data.materials.new(f"Blue{seed}")
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.042, 0.046, 0.115, 1)
    bsdf.inputs["Roughness"].default_value = 0.55  # 果粉哑光
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.15
        bsdf.inputs["Subsurface Radius"].default_value = (0.004, 0.004, 0.008)
    b.data.materials.append(mat)
    # 花萼冠 (顶端小五角星)
    bpy.ops.mesh.primitive_cone_add(vertices=5, radius1=r * 0.30, radius2=r * 0.10, depth=r * 0.22,
                                    location=(pos[0], pos[1], pos[2] + r * 0.96))
    cal = bpy.context.active_object
    cal.data.materials.append(mat)
    bpy.ops.object.shade_smooth()


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    scene = fresh(args)
    heroes.world_hdri(0.10, 1.4)
    heroes.wood_table(1.6)
    # 白瓷碗: 暖陶瓷 (微乳染 + 清漆)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.118, depth=0.048, location=(0.02, 0.0, 0.024), vertices=64)
    bowl = bpy.context.active_object
    bev = bowl.modifiers.new("Rim", "BEVEL")
    bev.width = 0.006
    bev.segments = 4
    bowl.data.materials.append(heroes.creamy_mat("Bowl", (0.865, 0.835, 0.79, 1), 0.20, 0.0))
    bowl.location.z = 0.022
    # 接触暗带 (碗底) — 十轮方法论移植
    bpy.ops.mesh.primitive_torus_add(major_radius=0.115, minor_radius=0.014, location=(0.02, 0.0, 0.004))
    band = bpy.context.active_object
    band.scale = (1, 1, 0.10)
    bpy.ops.object.transform_apply(scale=True)
    bmat = bpy.data.materials.new("ContactBand")
    bmat.use_nodes = True
    bb = bmat.node_tree.nodes.get("Principled BSDF")
    bb.inputs["Base Color"].default_value = (0.42, 0.37, 0.30, 1)
    if "Alpha" in bb.inputs:
        bb.inputs["Alpha"].default_value = 0.28
    bmat.blend_method = "BLEND"
    band.data.materials.append(bmat)
    # 酸奶体 + 果酱 + 莓果
    build_yogurt_body()
    honey_pool((0.055, 0.024, 0.1275), 0.020, seed=1)
    honey_pool((-0.020, -0.040, 0.1245), 0.015, seed=2)
    # 格兰诺拉碎堆 (真帧道具语言: 不规则烘焙碎块, 哑光)
    import random as _rg

    _r = _rg.Random(9)
    gmat = bpy.data.materials.new("Granola")
    gmat.use_nodes = True
    gb = gmat.node_tree.nodes.get("Principled BSDF")
    gb.inputs["Base Color"].default_value = (0.38, 0.245, 0.125, 1)
    gb.inputs["Roughness"].default_value = 0.72
    for k in range(13):
        th = _r.uniform(0, 6.28)
        rr = _r.uniform(0.0, 0.022)
        sz = _r.uniform(0.010, 0.019)
        bpy.ops.mesh.primitive_cube_add(size=1, location=(0.028 + rr * math.cos(th), 0.004 + rr * math.sin(th), 0.128 + _r.uniform(0, 0.010)))
        g = bpy.context.active_object
        g.scale = (sz, sz * _r.uniform(0.6, 1.0), sz * _r.uniform(0.5, 0.9))
        g.rotation_euler = (_r.uniform(0, 1.2), _r.uniform(0, 1.2), _r.uniform(0, 3.1))
        bpy.ops.object.transform_apply(scale=True)
        dv = g.modifiers.new("Crumble", "DISPLACE")
        tex = bpy.data.textures.new("CrumbleTex", "VORONOI")
        tex.noise_scale = 0.006
        dv.texture = tex
        dv.strength = 0.0022
        g.data.materials.append(gmat)
    raspberry((0.046, -0.020, 0.126), 0.018, seed=3)
    blueberry((0.010, 0.038, 0.128), 0.014, seed=5)
    raspberry((-0.012, -0.024, 0.124), 0.016, seed=7)
    # 勺子: 真勺形 (柄+凹面匙体) 靠碗沿
    steel = bpy.data.materials.new("Steel")
    steel.use_nodes = True
    sb = steel.node_tree.nodes.get("Principled BSDF")
    sb.inputs["Base Color"].default_value = (0.72, 0.73, 0.75, 1)
    sb.inputs["Metallic"].default_value = 1.0
    sb.inputs["Roughness"].default_value = 0.12
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0045, depth=0.19, location=(0.098, -0.062, 0.115),
                                        rotation=(0.32, 0.10, 0.35))
    handle = bpy.context.active_object
    handle.data.materials.append(steel)
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=24, radius=0.021, location=(0.088, -0.055, 0.158))
    spoon = bpy.context.active_object
    spoon.scale = (1.05, 0.8, 0.24)
    spoon.rotation_euler = (0.32, 0.10, 0.35)
    bpy.ops.object.transform_apply(scale=True)
    sm = spoon.modifiers.new("Concave", "DISPLACE")
    tex = bpy.data.textures.new("SpoonTex", "CLOUDS")
    tex.noise_scale = 0.05
    sm.texture = tex
    sm.strength = -0.002
    spoon.data.materials.append(steel)
    # 挂勺酸奶团 + 连接褶 (勺被拉起时酸奶垂坠)
    ymat = dairy_mat("Cling")
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=18, radius=0.0135, location=(0.086, -0.055, 0.130))
    cling = bpy.context.active_object
    cling.scale = (0.85, 0.85, 1.5)
    bpy.ops.object.transform_apply(scale=True)
    cling.data.materials.append(ymat)
    bpy.ops.object.shade_smooth()
    # 母本景深
    heroes.carton_master(args.sku, scale=2.2, loc=(-0.085, -0.155, 0))
    # 灯光: 低角度侧逆光 (食摄质感) + 弱补
    heroes.key_fill_light(key_loc=(0.62, -0.52, 0.55), key_e=0.30)
    rim = bpy.data.lights.new("Rim", "AREA")
    rim.energy = 28
    rim.size = 0.5
    rim.color = (0.92, 0.90, 0.86)
    ro = bpy.data.objects.new("Rim", rim)
    scene.collection.objects.link(ro)
    ro.location = (-0.55, 0.35, 0.55)
    import mathutils as _mu

    _d = _mu.Vector((0.02, 0.0, 0.10)) - _mu.Vector(ro.location)
    ro.rotation_euler = _d.to_track_quat("-Z", "Y").to_euler()
    heroes.setup_cam(loc=(0.150, -0.350, 0.148), look_at=(0.020, 0.005, 0.095), lens=52, fstop=2.9)
    out = os.path.join(OUT_DIR, f"{args.out}.png")
    scene.render.filepath = out
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"[YOGURT] {out}")


if __name__ == "__main__":
    main()
