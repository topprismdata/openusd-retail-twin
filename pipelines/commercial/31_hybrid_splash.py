#!/usr/bin/env python3
"""31 - HYBRID 飞溅: 程序化英雄形态 (抛物线液舌+颈缩液滴链+波状冠环) — 无烘焙, 30s级迭代
GPT 指令: 主液膜/主液舌/关键断裂边界 = 程序化建模控制; 仿真只留二级微滴 (本脚本用解析微滴替代)
运行: Blender -b -P 31_hybrid_splash.py -- --sku demo_organic --res 900 --samples 96   (draft)
      Blender -b -P 31_hybrid_splash.py -- --sku demo_organic --res 1920 --samples 256 --out final
产物: output/hybrid_splash/{draft,final}.png
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

OUT_DIR = os.path.join(BASE_DIR, "output", "hybrid_splash")
HDRI = os.path.join(BASE_DIR, "assets", "hdri", "brown_photostudio_01_4k.hdr")
G = 9.8


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--sku", default="demo_organic")
    p.add_argument("--res", type=int, default=900)
    p.add_argument("--samples", type=int, default=96)
    p.add_argument("--out", default="draft")
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args(argv)
    return args


def fresh(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    comfy.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.render.resolution_x = args.res
    scene.render.resolution_y = args.res
    scene.view_settings.exposure = -0.52
    world = bpy.data.worlds.new("Env")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.565, 0.552, 0.53, 1)
    bg.inputs[1].default_value = 0.28
    scene.world = world
    return scene


def milk_v2(name="MilkHero"):
    """英雄奶液材质: 半透奶白 + 低粗糙高光泽 (薄缘透光)"""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.925, 0.898, 0.852, 1)
    bsdf.inputs["Roughness"].default_value = 0.06
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.42
        bsdf.inputs["Subsurface Radius"].default_value = (0.06, 0.032, 0.014)
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.35
    return mat


def tongue_curve(scene, mat, p0, v0, t_end=0.30, n=26, r0=0.0062, r1=0.0009):
    """抛物线液舌: 重力一致的锥形变径曲线 (point.radius 驱动 bevel 锥化)"""
    cu = bpy.data.curves.new("Tongue", "CURVE")
    cu.dimensions = "3D"
    sp = cu.splines.new("POLY")
    sp.points.add(n - 1)
    import random as _rd

    _r = _rd.Random(int(p0[0] * 1000) + int(v0[2] * 100))
    _w1, _w2 = _r.uniform(2.0, 4.0), _r.uniform(5.0, 8.0)
    _ph = _r.uniform(0, 6.28)
    _lat = [(_r.uniform(-1, 1), _r.uniform(-1, 1)) for _ in range(3)]
    for k in range(n):
        t = t_end * k / (n - 1)
        u = k / (n - 1)
        _wob = 0.006 * math.sin(_w1 * u * math.pi + _ph) + 0.003 * math.sin(_w2 * u * math.pi + _ph * 1.7)
        x = p0[0] + v0[0] * t + _wob * _lat[0][0]
        y = p0[1] + v0[1] * t + _wob * _lat[1][1]
        z = p0[2] + v0[2] * t - 0.5 * G * t * t - 0.004 * math.sin(3.0 * u * math.pi + _ph)  # 纵向波动
        sp.points[k].co = (x, y, z, 1)
        _neck = 0.12 * math.sin(2.1 * u * math.pi + _ph)  # 局部颈缩: 半径非单调
        sp.points[k].radius = max(0.15, 1.0 - 0.82 * u ** 1.25 + _neck * (1.0 - u))
    cu.bevel_depth = r0
    cu.bevel_resolution = 6
    cu.use_fill_caps = True
    ob = bpy.data.objects.new("Tongue", cu)
    ob.data.materials.append(mat)
    bpy.context.scene.collection.objects.link(ob)
    import random as _r2

    _rr = _r2.Random(int(v0[0] * 977))
    ob.scale = (1.0, _rr.uniform(0.5, 0.72), 1.0)  # 截面椭圆扁化=液膜感
    bpy.ops.object.transform_apply(scale=True)
    return ob


def tongue_fingers(scene, mat, p0, v0, t_end, main_r0, seed):
    """液膜指状分裂: 每条主舌 2 根细指 (更短/更薄/快速尖灭) — 高速液膜失稳形态"""
    import random as _rf

    _r = _rf.Random(seed * 131 + 7)
    for fi in range(2):
        ang = _rf.uniform(0.14, 0.26) * (1 if fi % 2 == 0 else -1)
        vx, vz = v0[0], v0[2]
        vx2 = vx * math.cos(ang) - v0[1] * math.sin(ang)
        vy2 = vx * math.sin(ang) + v0[1] * math.cos(ang)
        v2 = (vx2, vy2, vz * _rf.uniform(0.88, 1.06))
        tongue_curve(scene, mat, p0, v2, t_end=t_end * _rf.uniform(0.55, 0.72), n=16, r0=main_r0 * 0.42, r1=0.0006)


def droplet_chain(scene, mat, p0, v0, t_start, n=5, seed=0):
    """颈缩液滴链: 沿同一弹道延伸, 球径先增后减 (液桥断裂形态)"""
    import random

    rnd = random.Random(seed)
    t = t_start
    dt = 0.022
    for k in range(n):
        t += dt * (1.0 + 0.25 * k)
        x = p0[0] + v0[0] * t
        y = p0[1] + v0[1] * t
        z = p0[2] + v0[2] * t - 0.5 * G * t * t
        if z < 0.004:
            break
        r = 0.011 * (1.0 - 0.13 * k) * (1.0 + 0.2 * rnd.random())
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, radius=r, location=(x, y, z))
        dp = bpy.context.active_object
        _rr = random.Random(seed * 17 + k)
        dp.scale = (_rr.uniform(0.85, 1.1), _rr.uniform(0.8, 1.0), _rr.uniform(1.05, 1.4))
        dp.rotation_euler = (_rr.uniform(-0.4, 0.4), _rr.uniform(-0.4, 0.4), _rr.uniform(0, 6.28))
        bpy.ops.object.transform_apply(scale=True)
        dp.data.materials.append(mat)
        bpy.ops.object.shade_smooth()


def reed_spikes(scene, mat, R=0.118, z_base=0.008, n_spikes=20, seed=23):
    """真帧形态: 20+ 根细簧刺 (粗细/高度/倾角全随机) + 顶端串珠球 — Edgerton 1957 对标"""
    import random as _rs

    _r = _rs.Random(seed)
    for k in range(n_spikes):
        th = 2 * math.pi * (k + _r.uniform(-0.35, 0.35)) / n_spikes  # 间距不规则
        h = _r.uniform(0.022, 0.055)
        tilt = _r.uniform(-0.22, 0.22)
        rr = R * _r.uniform(0.96, 1.05)
        x, y = rr * math.cos(th), rr * math.sin(th)
        bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.0026, radius2=0.0011, depth=h,
                                        location=(x, y, z_base + h / 2))
        reed = bpy.context.active_object
        reed.rotation_euler = (tilt * math.sin(th), tilt * math.cos(th), 0)
        reed.data.materials.append(mat)
        bpy.ops.object.shade_smooth()
        # 串珠顶端 (Rayleigh 失稳小球)
        tx, ty = x + tilt * math.sin(th) * h * 0.5, y + tilt * math.cos(th) * h * 0.5
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12,
                                             radius=_r.uniform(0.004, 0.0075), location=(tx, ty, z_base + h + 0.002))
        bead = bpy.context.active_object
        bead.data.materials.append(mat)
        bpy.ops.object.shade_smooth()


def crown_collar(scene, mat, R=0.105, z_base=0.006, z_top=0.085, waves=7, amp=0.016, seg=96):
    """波状冠环飘带: 双排顶点薄带 + solidify, 顶部边缘起伏+局部豁口"""
    verts, faces = [], []
    import random

    rnd = random.Random(11)
    for k in range(seg):
        th = 2 * math.pi * k / seg
        rr = R * (1.0 + amp * (0.6 * math.sin(waves * th + 0.8) + 0.4 * math.sin(4.3 * th + 2.2)) / R * 0.55)
        gap = rnd.random() < 0.06  # 局部豁口 (液膜破裂)
        zt = z_top * (0.45 + 0.35 * math.sin(waves * th + 1.7) + 0.2 * math.sin(5.7 * th + 0.4))
        flare = 1.0 + 0.34 * (zt / max(z_top, 1e-6))  # 喇叭形: 越高越外翻
        verts.append((rr * math.cos(th), rr * math.sin(th), z_base))
        verts.append((rr * flare * math.cos(th), rr * flare * math.sin(th), zt if not gap else z_base + 0.01))
    for k in range(seg - 1):
        a, b = k * 2, k * 2 + 1
        c, d = (k + 1) * 2, (k + 1) * 2 + 1
        faces.append((a, c, d, b))
    me = bpy.data.meshes.new("Crown")
    me.from_pydata(verts, [], faces)
    me.validate()
    ob = bpy.data.objects.new("Crown", me)
    bpy.context.scene.collection.objects.link(ob)
    m = ob.modifiers.new("Sol", "SOLIDIFY")
    m.thickness = 0.0015
    m.offset = -1
    sm = ob.modifiers.new("Sm", "SUBSURF")
    sm.levels = 2
    sm.render_levels = 2
    ob.data.materials.append(mat)
    # 唇缘串珠 (真帧: 小球并入唇线)
    for k in range(0, seg, 4):
        th = 2 * math.pi * k / seg + 0.3
        rr = R * (1.0 + amp * math.sin(waves * th + 0.8) / R * 0.55) * 1.12
        zt = z_top * (0.45 + 0.35 * math.sin(waves * th + 1.7) + 0.2 * math.sin(5.7 * th + 0.4)) + 0.012
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12,
                                             radius=0.0026 + 0.0012 * math.sin(5 * th), location=(rr * flare * math.cos(th), rr * flare * math.sin(th), zt))
        dp = bpy.context.active_object
        dp.scale = (1.0 + 0.3 * math.sin(5 * th), 0.85 + 0.2 * math.cos(4 * th), 1.1 + 0.35 * math.sin(2 * th + 1.0))
        dp.rotation_euler = (0.3 * math.sin(3 * th), 0.3 * math.cos(2 * th), th)
        bpy.ops.object.transform_apply(scale=True)
        dp.data.materials.append(mat)
        bpy.ops.object.shade_smooth()
    return ob


def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    import random

    rnd = random.Random(args.seed)
    scene = fresh(args)
    mat = milk_v2()
    # 母本 + 池 (复用 26)
    heroes.world_hdri(0.15, 0.9)
    carton = heroes.carton_master(args.sku)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.36, depth=0.006, vertices=64, location=(0, 0, 0.003))
    pool = bpy.context.active_object
    pool_mat = heroes.milk_mat("Pool", 0.16)
    _pb = pool_mat.node_tree.nodes.get("Principled BSDF")
    if _pb:
        _pb.inputs["Base Color"].default_value = (0.868, 0.826, 0.752, 1)
    pool.data.materials.append(pool_mat)
    # 接触暗带: 冠环正下方半透明深色环 (软接触阴影)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.128, minor_radius=0.024, location=(0, 0, 0.007))
    band = bpy.context.active_object
    band.scale = (1, 1, 0.06)
    bpy.ops.object.transform_apply(scale=True)
    bmat = bpy.data.materials.new("ContactBand")
    bmat.use_nodes = True
    bb = bmat.node_tree.nodes.get("Principled BSDF")
    bb.inputs["Base Color"].default_value = (0.52, 0.47, 0.40, 1)
    if "Alpha" in bb.inputs:
        bb.inputs["Alpha"].default_value = 0.30
    bmat.blend_method = "BLEND"
    band.data.materials.append(bmat)
    bpy.ops.object.shade_smooth()
    _pt = bpy.data.textures.new("PoolNoise", "CLOUDS")
    _pt.noise_scale = 0.09
    _pm = pool.modifiers.new("Rim", "DISPLACE")
    _pm.texture = _pt
    _pm.strength = 0.010
    _pm.mid_level = 0.5
    # 放射薄液辐条 (飞溅落液在台面拖出的薄液条)
    for si in range(5):
        _a = si * 2 * math.pi / 5 + 0.5 + si * si * 0.37
        _len = 0.10 + (si % 3) * 0.05
        bpy.ops.mesh.primitive_cube_add(size=1, location=(math.cos(_a) * (0.15 + _len / 2), math.sin(_a) * (0.15 + _len / 2), 0.004))
        _sp = bpy.context.active_object
        _sp.scale = (_len, 0.008, 0.0012)
        _sp.rotation_euler = (0, 0, _a)
        bpy.ops.object.transform_apply(scale=True)
        _sp.data.materials.append(heroes.milk_mat("Pool", 0.12))
    # 冠环
    crown_collar(scene, mat, R=0.112, z_top=0.095, waves=12, amp=0.014)
    reed_spikes(scene, mat)
    # 三条英雄液舌 (从盒肩出发, 弹道一致)
    H = 0.326
    launches = [
        ((0.058, -0.02, H * 0.62), (2.30, -0.70, 2.55), 0.26, 0),
        ((-0.058, -0.015, H * 0.66), (-2.45, -0.60, 2.80), 0.28, 1),
        ((0.02, 0.058, H * 0.60), (0.65, 2.15, 2.30), 0.24, 2),
    ]
    for p0, v0, t_end, seed in launches:
        tongue_curve(scene, mat, p0, v0, t_end=t_end)
        tongue_fingers(scene, mat, p0, v0, t_end, 0.0062, seed)
        droplet_chain(scene, mat, p0, v0, t_start=t_end, seed=seed)
        # 根球倒角: 液舌根部埋入盒面, 消"断头桩"
        bpy.ops.mesh.primitive_uv_sphere_add(segments=20, ring_count=14, radius=0.012, location=p0)
        root = bpy.context.active_object
        root.data.materials.append(mat)
        bpy.ops.object.shade_smooth()
    # 雾级微滴 (近距细雾, 增空气感)
    for k in range(40):
        th2 = rnd.random() * 2 * math.pi
        r2 = 0.05 + rnd.random() * 0.30
        x2, y2 = r2 * math.cos(th2), r2 * math.sin(th2)
        z2 = 0.03 + rnd.random() * 0.34
        if abs(x2) < 0.085 and abs(y2) < 0.085:
            continue
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=0.0018 + rnd.random() * 0.0032, location=(x2, y2, z2))
        mist = bpy.context.active_object
        mist.data.materials.append(mat)
        bpy.ops.object.shade_smooth()
    # 二级微滴 (弹道散布, 解析替代仿真)
    for k in range(26):
        th = rnd.random() * 2 * math.pi
        r0 = 0.06 + rnd.random() * 0.16
        v = 1.1 + rnd.random() * 1.5
        el = 0.6 + rnd.random() * 0.8
        t = 0.16 + rnd.random() * 0.14
        vx, vy, vz = v * math.cos(el) * math.cos(th), v * math.cos(el) * math.sin(th), v * math.sin(el)
        x, y, z = vx * t, vy * t, H * 0.8 + vz * t - 0.5 * G * t * t
        if z < 0.006:
            continue
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.004 + rnd.random() * 0.008, location=(x, y, z))
        dp = bpy.context.active_object
        dp.scale = (1.0, 0.82 + rnd.random() * 0.2, 1.25)
        dp.rotation_euler = (rnd.random() * 0.6 - 0.3, rnd.random() * 0.6 - 0.3, th)
        bpy.ops.object.transform_apply(scale=True)
        dp.data.materials.append(mat)
        bpy.ops.object.shade_smooth()
    # 灯光相机 (v4 配方)
    heroes.key_fill_light(key_loc=(1.0, -1.1, 1.5), key_e=0.95)
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
    heroes.setup_cam(loc=(0.30, -0.52, 0.24), look_at=(0.0, 0.005, 0.18), lens=45, fstop=5.0)
    out = os.path.join(OUT_DIR, f"{args.out}.png")
    scene.render.filepath = out
    scene.render.image_settings.file_format = "PNG"
    bpy.ops.render.render(write_still=True)
    print(f"[HYBRID] {out}")


if __name__ == "__main__":
    main()
