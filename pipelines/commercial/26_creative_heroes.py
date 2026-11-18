#!/usr/bin/env python3
"""26 - 创意三方向: 牛奶飞溅 hero (Mantaflow) / 酸奶微距 (希腊酸奶系) / 早餐叙事 (高端白奶系)
复用 01 的 build_carton_twin 数字母本 + Metal-RT 引擎。
运行:
  Blender -b -P 26_creative_heroes.py -- \
      --skus demo_classic,demo_organic,demo_yogurt_original \
      --scenes splash,yogurt,breakfast --res 1400
产物: output/creative_matrix/{scene}_{sku}.png
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

OUT_DIR = os.path.join(BASE_DIR, "output", "creative_matrix")
HDRI = os.path.join(BASE_DIR, "assets", "hdri", "brown_photostudio_01_4k.hdr")
HERO_S = 2.4  # hero 放大倍率 (真实母本 136mm → hero 326mm, 微距戏剧化)


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--skus", default="demo_classic,demo_organic,demo_yogurt_original")
    p.add_argument("--scenes", default="splash,yogurt,breakfast")
    p.add_argument("--res", type=int, default=1400)
    p.add_argument("--samples", type=int, default=128)
    args = p.parse_args(argv)
    return args


def fresh_scene(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    comfy.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.render.film_transparent = False
    scene.view_settings.exposure = -0.35
    scene.frame_start, scene.frame_end = 1, 36
    scene.frame_set(1)
    return scene


def world_hdri(strength=0.4, rot_z=0.4):
    world = bpy.data.worlds.new("Env")
    world.use_nodes = True
    wnt = world.node_tree
    for n in list(wnt.nodes):
        wnt.nodes.remove(n)
    coord = wnt.nodes.new("ShaderNodeTexCoord")
    mapping = wnt.nodes.new("ShaderNodeMapping")
    env = wnt.nodes.new("ShaderNodeTexEnvironment")
    bg = wnt.nodes.new("ShaderNodeBackground")
    out = wnt.nodes.new("ShaderNodeOutputWorld")
    env.image = bpy.data.images.load(HDRI)
    mapping.inputs["Rotation"].default_value = (0, 0, rot_z)
    wnt.links.new(coord.outputs["Generated"], mapping.inputs["Vector"])
    wnt.links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    wnt.links.new(env.outputs[0], bg.inputs[0])
    wnt.links.new(bg.outputs[0], out.inputs[0])
    bg.inputs[1].default_value = strength
    bpy.context.scene.world = world
    return world


def carton_master(sku, scale=HERO_S, loc=(0, 0, 0)):
    carton = comfy.build_carton_twin(sku)[0]
    carton.scale = (scale, scale, scale)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    carton.location = loc
    return carton


def make_obstacle(obj):
    m = obj.modifiers.new("Fluid", "FLUID")
    m.fluid_type = "EFFECTOR"
    m.effector_settings.effector_type = "COLLISION"
    return m


def milk_mat(name="Milk", rough=0.09):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.90, 0.875, 0.83, 1)
    bsdf.inputs["Roughness"].default_value = max(rough, 0.055)
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.32
        bsdf.inputs["Subsurface Radius"].default_value = (0.045, 0.028, 0.018)
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.25
    return mat


def key_fill_light(key_loc=(1.1, -1.0, 1.5), key_e=0.9, warm=True):
    key = bpy.data.lights.new("Key", "AREA")
    key.energy = key_e * 40
    key.size = 0.9
    ko = bpy.data.objects.new("Key", key)
    bpy.context.scene.collection.objects.link(ko)
    ko.location = key_loc
    import mathutils

    d = mathutils.Vector((0, 0, 0.16)) - mathutils.Vector(key_loc)
    ko.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if warm:
        key.color = (1.0, 0.93, 0.84)
    fill = bpy.data.lights.new("Fill", "AREA")
    fill.energy = 22
    fill.size = 1.4
    fill.color = (0.85, 0.9, 1.0)
    fo = bpy.data.objects.new("Fill", fill)
    bpy.context.scene.collection.objects.link(fo)
    fo.location = (-1.3, -0.6, 0.5)
    d2 = mathutils.Vector((0, 0, 0.14)) - mathutils.Vector(fo.location)
    fo.rotation_euler = d2.to_track_quat("-Z", "Y").to_euler()
    return ko


def setup_cam(loc, look_at, lens=50, fstop=4.0):
    import mathutils

    cam_data = bpy.data.cameras.new("Cam")
    cam_data.lens = lens
    cam_data.dof.use_dof = True
    cam_data.dof.aperture_fstop = fstop
    cam_data.dof.focus_distance = (mathutils.Vector(look_at) - mathutils.Vector(loc)).length
    cam = bpy.data.objects.new("Cam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    d = mathutils.Vector(look_at) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def wood_table(size=2.2):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0, 0, 0))
    t = bpy.context.active_object
    mat = bpy.data.materials.new("Wood")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 3.2
    wave.inputs["Distortion"].default_value = 6.0
    wave.inputs["Detail"].default_value = 3.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.34, 0.21, 0.11, 1)
    ramp.color_ramp.elements[1].color = (0.52, 0.35, 0.19, 1)
    nt.links.new(wave.outputs[0], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.42
    t.data.materials.append(mat)
    return t


# ---------- A. 牛奶飞溅 hero (Mantaflow) ----------
def build_splash(sku, args):
    scene = fresh_scene(args)
    world_hdri(0.15, 0.9)
    # Mantaflow 域
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.26))
    dom = bpy.context.active_object
    dom.scale = (0.58, 0.58, 0.52)
    bpy.ops.object.transform_apply(scale=True)
    fmod = dom.modifiers.new("Fluid", "FLUID")
    fmod.fluid_type = "DOMAIN"
    fmod.domain_settings.domain_type = "LIQUID"
    fmod.domain_settings.resolution_max = 128
    fmod.domain_settings.mesh_smoothen_pos = 3
    fmod.domain_settings.mesh_smoothen_neg = 4
    fmod.domain_settings.mesh_particle_radius = 1.4
    fmod.domain_settings.cache_type = "ALL"
    fmod.domain_settings.cache_frame_start = 1
    fmod.domain_settings.cache_frame_end = 36
    dom.data.materials.append(milk_mat("DomainMilk", 0.07))
    carton = carton_master(sku)
    for child in list(carton.children_recursive):
        make_obstacle(child)
    make_obstacle(carton)
    # 牛奶池
    bpy.ops.mesh.primitive_cylinder_add(radius=0.34, depth=0.006, location=(0, 0, 0.003))
    pool = bpy.context.active_object
    pool.data.materials.append(milk_mat("Pool", 0.14))
    make_obstacle(pool)
    # 入流奶滴
    # v4 背向入流: 冠溅在母本背后升起 (v5 对撞伞膜实验失败已回滚; 几何重构战役另行开题)
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.055, location=(-0.13, 0.10, 0.40))
    inflow = bpy.context.active_object
    imod = inflow.modifiers.new("Fluid", "FLUID")
    imod.fluid_type = "FLOW"
    imod.flow_settings.flow_type = "LIQUID"
    imod.flow_settings.use_inflow = True
    imod.flow_settings.use_initial_velocity = True
    imod.flow_settings.velocity_coord = (0.5, -0.3, -4.4)
    inflow.hide_render = True
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.045, location=(0.12, 0.11, 0.42))
    inflow2 = bpy.context.active_object
    imod2 = inflow2.modifiers.new("Fluid", "FLUID")
    imod2.fluid_type = "FLOW"
    imod2.flow_settings.flow_type = "LIQUID"
    imod2.flow_settings.use_inflow = True
    imod2.flow_settings.use_initial_velocity = True
    imod2.flow_settings.velocity_coord = (-0.4, -0.28, -3.9)
    inflow2.hide_render = True
    key_fill_light(key_loc=(1.0, -1.1, 1.5), key_e=0.95)
    rim = bpy.data.lights.new("Rim", "AREA")
    rim.energy = 70
    rim.size = 0.7
    rim.color = (0.88, 0.93, 1.0)
    ro = bpy.data.objects.new("Rim", rim)
    bpy.context.scene.collection.objects.link(ro)
    ro.location = (-0.9, 0.9, 0.9)
    import mathutils as _mu
    _d = _mu.Vector((0, 0, 0.2)) - _mu.Vector(ro.location)
    ro.rotation_euler = _d.to_track_quat("-Z", "Y").to_euler()
    setup_cam(loc=(0.30, -0.52, 0.24), look_at=(0.0, 0.005, 0.18), lens=45, fstop=5.0)
    print("[SPLASH] baking fluid...")
    bpy.context.view_layer.objects.active = dom
    with bpy.context.temp_override(active_object=dom, object=dom):
        bpy.ops.fluid.bake_all()
    scene.frame_set(11)
    return scene


# ---------- B. 酸奶微距 (希腊酸奶系) ----------
def creamy_mat(name, col=(0.97, 0.95, 0.91, 1), rough=0.34, sss=0.5):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = col
    bsdf.inputs["Roughness"].default_value = rough
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = sss
        bsdf.inputs["Subsurface Radius"].default_value = (0.012, 0.008, 0.005)
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 22.0
    noise.inputs["Detail"].default_value = 6.0
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.22
    nt.links.new(noise.outputs[0], bump.inputs[0])
    nt.links.new(bump.outputs[0], bsdf.inputs["Normal"])
    return mat


def berry(pos, r=0.016, col=(0.42, 0.07, 0.10, 1), bumpy=False):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=r, location=pos)
    b = bpy.context.active_object
    if bumpy:
        m = b.modifiers.new("Displace", "DISPLACE")
        tex = bpy.data.textures.new("BerryTex", "VORONOI")
        tex.noise_scale = r * 0.7
        m.texture = tex
        m.strength = r * 0.55
    mat = creamy_mat(f"Berry{r}", col, 0.30, 0.35)
    b.data.materials.append(mat)
    return b


def build_yogurt(sku, args):
    scene = fresh_scene(args)
    world_hdri(0.12, 2.2)
    wood_table(1.6)
    # 白瓷碗 (实心圆台+倒角)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.118, depth=0.048, location=(0.02, 0.0, 0.024), vertices=64)
    bowl = bpy.context.active_object
    bev = bowl.modifiers.new("Rim", "BEVEL")
    bev.width = 0.006
    bev.segments = 4
    bowl.data.materials.append(creamy_mat("Bowl", (0.90, 0.885, 0.86, 1), 0.28, 0.0))
    bowl.location.z = 0.022
    # 酸奶主体
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.098, location=(0.02, 0.0, 0.086))
    yo = bpy.context.active_object
    yo.scale = (1.0, 0.92, 0.42)
    bpy.ops.object.transform_apply(scale=True)
    # 旋涡置换: 云纹理扰动穹顶表面
    dv = yo.modifiers.new("Swirl", "DISPLACE")
    tex = bpy.data.textures.new("SwirlTex", "CLOUDS")
    tex.noise_scale = 0.035
    tex.noise_depth = 3
    dv.texture = tex
    dv.strength = 0.006
    yog_mat = creamy_mat("Yogurt")
    yog_nt = yog_mat.node_tree
    yog_bsdf = yog_nt.nodes.get("Principled BSDF")
    wave = yog_nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 9.0
    wave.inputs["Distortion"].default_value = 14.0
    ramp = yog_nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.965, 0.945, 0.90, 1)
    ramp.color_ramp.elements[1].color = (0.88, 0.85, 0.80, 1)
    yog_nt.links.new(wave.outputs[0], ramp.inputs[0])
    yog_nt.links.new(ramp.outputs[0], yog_bsdf.inputs["Base Color"])
    yo.data.materials.append(yog_mat)
    # 果酱旋涡
    bpy.ops.mesh.primitive_torus_add(major_radius=0.034, minor_radius=0.011, location=(0.015, 0.01, 0.126))
    jam = bpy.context.active_object
    jam.scale = (1.0, 0.85, 0.42)
    bpy.ops.object.transform_apply(scale=True)
    jam.data.materials.append(creamy_mat("Jam", (0.36, 0.05, 0.09, 1), 0.16, 0.55))
    berry((0.060, -0.030, 0.128), 0.014, (0.42, 0.07, 0.10, 1), True)
    berry((0.088, 0.020, 0.118), 0.012, (0.10, 0.09, 0.24, 1), True)
    berry((0.020, 0.058, 0.128), 0.013, (0.42, 0.07, 0.10, 1), True)
    # 勺子
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0075, depth=0.16, location=(0.15, -0.14, 0.012),
                                        rotation=(math.pi / 2, 0, -0.5))
    handle = bpy.context.active_object
    steel = bpy.data.materials.new("Steel")
    steel.use_nodes = True
    sb = steel.node_tree.nodes.get("Principled BSDF")
    sb.inputs["Base Color"].default_value = (0.75, 0.76, 0.78, 1)
    sb.inputs["Metallic"].default_value = 1.0
    sb.inputs["Roughness"].default_value = 0.14
    handle.data.materials.append(steel)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.028, location=(0.225, -0.20, 0.010))
    spoon = bpy.context.active_object
    spoon.scale = (1.15, 0.7, 0.28)
    bpy.ops.object.transform_apply(scale=True)
    spoon.data.materials.append(steel)
    # 母本站在后方景深处
    carton = carton_master(sku, scale=1.9, loc=(-0.16, -0.09, 0))
    key_fill_light(key_loc=(0.6, -0.8, 0.7), key_e=0.55)
    setup_cam(loc=(0.18, -0.36, 0.24), look_at=(0.0, 0.0, 0.05), lens=58, fstop=3.2)
    return scene


# ---------- C. 早餐叙事 (高端白奶系) ----------
def build_breakfast(sku, args):
    scene = fresh_scene(args)
    world_hdri(0.25, 1.3)
    wood_table(2.6)
    carton = carton_master(sku, scale=1.7, loc=(-0.10, 0.02, 0))
    # 木砧板 + 水煮蛋
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0.09, -0.09, 0.008))
    board = bpy.context.active_object
    board.scale = (0.20, 0.13, 0.008)
    bpy.ops.object.transform_apply(scale=True)
    board.data.materials.append(creamy_mat("Board", (0.58, 0.42, 0.24, 1), 0.5, 0.0))
    for k, p in enumerate([(0.05, -0.065), (0.12, -0.115)]):
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.021, location=(p[0], p[1], 0.021))
        egg = bpy.context.active_object
        egg.scale = (1.0, 0.92, 1.22)
        bpy.ops.object.transform_apply(scale=True)
        egg.data.materials.append(creamy_mat(f"Egg{k}", (0.93, 0.89, 0.82, 1), 0.42, 0.35))
    # 亚麻餐巾
    bpy.ops.mesh.primitive_plane_add(size=0.16, location=(0.16, 0.12, 0.002))
    nap = bpy.context.active_object
    nap.rotation_euler = (0, 0, 0.5)
    m = nap.modifiers.new("Cloth", "DISPLACE")
    tex = bpy.data.textures.new("Linen", "CLOUDS")
    tex.noise_scale = 0.012
    m.texture = tex
    m.strength = 0.0035
    nap.data.materials.append(creamy_mat("Linen", (0.88, 0.85, 0.80, 1), 0.8, 0.0))
    # 晨光
    sun = bpy.data.lights.new("Sun", "SUN")
    sun.energy = 2.0
    sun.angle = math.radians(2.5)
    sun.color = (1.0, 0.85, 0.65)
    so = bpy.data.objects.new("Sun", sun)
    bpy.context.scene.collection.objects.link(so)
    so.rotation_euler = (math.radians(55), 0, math.radians(-38))
    key_fill_light(key_loc=(0.8, -0.9, 1.0), key_e=0.7, warm=True)
    setup_cam(loc=(-0.03, -0.58, 0.27), look_at=(-0.05, 0.01, 0.11), lens=45, fstop=3.5)
    return scene


BUILDERS = {"splash": build_splash, "yogurt": build_yogurt, "breakfast": build_breakfast}


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    skus = [s for s in args.skus.split(",") if s]
    scenes = [s for s in args.scenes.split(",") if s]
    for scene_name in scenes:
        for sku in skus:
            sc = BUILDERS[scene_name](sku, args)
            out = os.path.join(OUT_DIR, f"{scene_name}_{sku}.png")
            sc.render.filepath = out
            sc.render.image_settings.file_format = "PNG"
            bpy.ops.render.render(write_still=True)
            print(f"[HERO26] {scene_name}_{sku} -> {out}")
            if scene_name == "splash":
                # 清掉烘焙缓存避免下个 SKU 串味
                bpy.context.view_layer.objects.active = bpy.context.scene.objects.get("Cube")
                if bpy.context.view_layer.objects.active:
                    with bpy.context.temp_override(active_object=bpy.context.view_layer.objects.active):
                        bpy.ops.fluid.free_all()
    print("[HERO26] done")


if __name__ == "__main__":
    main()
