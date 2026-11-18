#!/usr/bin/env python3
"""29 - 四视角包装保真验收: 正面/侧面/背面/45° + 顶部细节, 同一母本受控渲染
运行: Blender -b -P 29_four_view_qa.py -- --sku demo_organic --res 1600
产物: output/qa_four_view/{front,side,back,deg45,cap_top}.png
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

OUT_DIR = os.path.join(BASE_DIR, "output", "qa_four_view")
HDRI = os.path.join(BASE_DIR, "assets", "hdri", "brown_photostudio_01_4k.hdr")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--sku", default="demo_organic")
    p.add_argument("--res", type=int, default=1600)
    args = p.parse_args(argv)
    return args


def fresh(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    comfy.setup_metal_engine(samples=192)
    scene = bpy.context.scene
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.render.film_transparent = False
    # 世界: 中性灰环境 (保真验收用光, 不做氛围)
    world = bpy.data.worlds.new("QAEnv")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.82, 0.84, 0.86, 1)
    bg.inputs[1].default_value = 0.55
    scene.world = world
    # 主光: 柔和顶前光
    key = bpy.data.lights.new("Key", "AREA")
    key.energy = 150
    key.size = 1.2
    ko = bpy.data.objects.new("Key", key)
    bpy.context.scene.collection.objects.link(ko)
    ko.location = (0.6, -0.9, 1.2)
    import mathutils

    d = mathutils.Vector((0, 0, 0.07)) - mathutils.Vector(ko.location)
    ko.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    return scene


def cam_shot(scene, angle_deg, dist=0.42, z=0.068, lens=85):
    import mathutils

    a = math.radians(angle_deg)
    cam_data = bpy.data.cameras.new("C")
    cam_data.lens = lens
    cam = bpy.data.objects.new("C", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam.location = (dist * math.sin(a), -dist * math.cos(a), z)
    d = mathutils.Vector((0, 0, 0.068)) - mathutils.Vector(cam.location)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    shots = [("front", 0), ("side", 90), ("back", 180), ("deg45", 45)]
    for name, ang in shots:
        scene = fresh(args)
        comfy.build_carton_twin(args.sku)
        cam_shot(scene, ang)
        scene.render.filepath = os.path.join(OUT_DIR, f"{name}.png")
        scene.render.image_settings.file_format = "PNG"
        bpy.ops.render.render(write_still=True)
        print(f"[QA] {name} done")
    # 顶部旋盖细节 (俯视特写)
    scene = fresh(args)
    comfy.build_carton_twin(args.sku)
    import mathutils

    cam_data = bpy.data.cameras.new("C")
    cam_data.lens = 90
    cam = bpy.data.objects.new("C", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam_data.clip_start = 0.02
    cam.location = (0.055, -0.055, 0.26)
    d = mathutils.Vector((0.0, 0.0, 0.136)) - mathutils.Vector(cam.location)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.render.filepath = os.path.join(OUT_DIR, "cap_top.png")
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"[QA] cap_top done")
    print("[QA] all done")


if __name__ == "__main__":
    main()
