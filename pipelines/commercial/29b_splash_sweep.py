#!/usr/bin/env python3
"""29b - 飞溅几何矩阵扫参: 对撞射流 (射速 × 撞高 × 采样帧) 8 组合快扫
运行: Blender -b -P 29b_splash_sweep.py -- --sku demo_organic
产物: output/splash_sweep/sp{speed}_z{zcm}_f{frame}.png (900px, 96spp, 判形用)
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

OUT_DIR = os.path.join(BASE_DIR, "output", "splash_sweep")
HDRI = os.path.join(BASE_DIR, "assets", "hdri", "brown_photostudio_01_4k.hdr")

# 8 组合: (speed, collide_z, frame)
COMBOS = [
    (2.0, 0.375, 10),
    (2.0, 0.375, 14),
    (3.0, 0.340, 10),
    (3.0, 0.375, 12),
    (3.0, 0.410, 14),
    (4.0, 0.375, 10),
    (4.0, 0.410, 16),
    (3.0, 0.410, 20),
]


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--sku", default="demo_organic")
    p.add_argument("--combo", type=int, default=-1, help="只跑 COMBOS[i]; -1=全部")
    p.add_argument("--res", type=int, default=900)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--out", default="", help="覆盖输出文件名")
    args = p.parse_args(argv)
    return args


def build_scene(args, speed, cz, frame):
    scene = heroes.fresh_scene(args)
    heroes.world_hdri(0.15, 0.9)
    # 域 (覆盖撞点上方 + 落池)
    bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 0.28))
    dom = bpy.context.active_object
    dom.scale = (0.58, 0.58, 0.56)
    bpy.ops.object.transform_apply(scale=True)
    fmod = dom.modifiers.new("Fluid", "FLUID")
    fmod.fluid_type = "DOMAIN"
    fmod.domain_settings.domain_type = "LIQUID"
    fmod.domain_settings.resolution_max = 100
    fmod.domain_settings.mesh_smoothen_pos = 3
    fmod.domain_settings.mesh_smoothen_neg = 4
    fmod.domain_settings.mesh_particle_radius = 1.4
    fmod.domain_settings.cache_type = "ALL"
    fmod.domain_settings.cache_frame_start = 1
    fmod.domain_settings.cache_frame_end = 36
    dom.data.materials.append(heroes.milk_mat("DomainMilk", 0.07))
    # 母本 + 池
    carton = heroes.carton_master(args.sku)
    for child in list(carton.children_recursive):
        heroes.make_obstacle(child)
    heroes.make_obstacle(carton)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.34, depth=0.006, location=(0, 0, 0.003))
    pool = bpy.context.active_object
    pool.data.materials.append(heroes.milk_mat("Pool", 0.14))
    heroes.make_obstacle(pool)
    # 对撞射流对 (对称)
    for sx in (-1, 1):
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.04, location=(sx * 0.14, 0, cz))
        inf = bpy.context.active_object
        imod = inf.modifiers.new("Fluid", "FLUID")
        imod.fluid_type = "FLOW"
        imod.flow_settings.flow_type = "LIQUID"
        imod.flow_settings.use_inflow = True
        imod.flow_settings.use_initial_velocity = True
        imod.flow_settings.velocity_coord = (-sx * speed, 0.0, 0.1)
        inf.hide_render = True
    heroes.key_fill_light(key_loc=(1.0, -1.1, 1.5), key_e=0.95)
    heroes.setup_cam(loc=(0.30, -0.52, 0.24), look_at=(0.0, 0.005, 0.18), lens=45, fstop=5.0)
    print(f"[SWEEP] baking sp={speed} z={cz} ...")
    bpy.context.view_layer.objects.active = dom
    with bpy.context.temp_override(active_object=dom, object=dom):
        bpy.ops.fluid.bake_all()
    scene.frame_set(frame)
    return scene


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    combos = COMBOS if args.combo < 0 else [COMBOS[args.combo]]
    for speed, cz, frame in combos:
        scene = build_scene(args, speed, cz, frame)
        name = args.out if args.out else f"sp{speed:.0f}_z{int(cz*1000)}_f{frame}"
        scene.render.filepath = os.path.join(OUT_DIR, f"{name}.png")
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
        print(f"[SWEEP] done {name}")
        try:
            bpy.context.view_layer.objects.active = bpy.context.scene.objects.get("Cube")
            if bpy.context.view_layer.objects.active:
                with bpy.context.temp_override(active_object=bpy.context.view_layer.objects.active):
                    bpy.ops.fluid.free_all()
        except Exception:
            pass
    print("[SWEEP] all done")


if __name__ == "__main__":
    main()
