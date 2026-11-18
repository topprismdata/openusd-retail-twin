#!/usr/bin/env python3
"""
26 - 货架全景合成: 13 SKU 乳品冷柜版 (用户权威参照 2026-11-15)

用户供图 (pic.rmb.bdstatic.com/bjh/240914/dump/4768b71939c4c3fd1e2fa2fea5bd5285.jpeg,
4096x2457 实拍) 判定: 真实牛奶货架 = 开放式冷藏风幕柜, 非木质常温架。本版对齐参照五特征:
(1) 白色柜体+侧立柱 (2) 层板底 LED 灯带冷白光 (3) 单排面零间隙密排 (4) 黄促销签为主的
亚克力价签槽 (5) 品牌色块分区陈列。

运行:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P 26_shelf_panorama.py -- [--samples 192] [--out name]
"""
import os
import sys
import math
import argparse
import importlib.util
import random

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_s01 = importlib.util.spec_from_file_location("comp01", os.path.join(BASE_DIR, "pipelines/ecommerce/01_comfy_usd_compositor.py"))
m01 = importlib.util.module_from_spec(_s01)
_s01.loader.exec_module(m01)

import bpy
from mathutils import Vector

OUT_DIR = os.path.join(BASE_DIR, "output", "shelf")
os.makedirs(OUT_DIR, exist_ok=True)

# 冷柜几何: 白钢层板 (板深 0.115 容双排), 层距 > 最高品+盖 0.170
CASE_W, CASE_D, SHELF_T = 0.86, 0.115, 0.010
ROW_Z = (0.370, 0.185, 0.0)
CASE_H = 0.58

YOG_B = (m01.YOG_BW, m01.YOG_BD, m01.YOG_BH)
YOG_G = (m01.YOG_GW, m01.YOG_GD, m01.YOG_GH)

# v13 品牌色块分区 (横向连续色带, 参照用户供图"品牌阵列"):
# 顶层 经典: 白绿(有机)→草原绿(纯牛奶)→深海蓝(a2)→黑金(娟姗)→金红(cny)
ROW_TOP = (["demo_organic"] * 4 + ["demo_classic"] * 4 + ["demo_a2"] * 3 +
           ["demo_jersey"] * 2 + ["demo_cny"] * 2)
# 中层 功能+梦幻盖: 青绿(低脂)→冰蓝(脱脂)→蓝金(呼伦贝尔)→甘蔗白(dream38)→幻紫(dream40)
ROW_MID = (["demo_lowfat"] * 3 + ["demo_skim"] * 4 + ["demo_meadow"] * 3 +
           ["demo_dream38"] * 2 + ["demo_dream40"] * 3)
# 底层 酸奶系列: 爱琴白蓝(原味)→金白(金装); 礼盒不进冷柜 (常温端架另属)
ROW_BOT = [("demo_yogurt_original", YOG_B)] * 10 + [("demo_yogurt_gold", YOG_B)] * 5


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--samples", type=int, default=192)
    p.add_argument("--out", default="shelf_coldcase_v13")
    return p.parse_args(argv)


def _box(name, sx, sy, sz, loc, color, rough=0.55):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    ob = bpy.context.active_object
    ob.name = name
    ob.scale = (sx, sy, sz)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mat = bpy.data.materials.new(f"Mat_{name}")
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = color + (1.0,)
    b.inputs["Roughness"].default_value = rough
    ob.data.materials.append(mat)
    return ob


def _uv_full_face(ob):
    """几何定向 UV (x→u, z→v, 世界坐标归一): 每面贴满整张纹理且方向与视觉一致。
    修 Blender 5.2 原始立方体十字箱 UV (前面只采子象限, 文字带被跳过);
    corner 序映射会因各面 loop 环绕方向不同而镜像/翻转, 必须按世界几何位置映射。"""
    uvl = ob.data.uv_layers.active or ob.data.uv_layers.new(name="UVMap")
    mw = ob.matrix_world
    for poly in ob.data.polygons:
        xs, zs = [], []
        for li in poly.loop_indices:
            co = mw @ ob.data.vertices[ob.data.loops[li].vertex_index].co
            xs.append(co.x); zs.append(co.z)
        x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
        for li in poly.loop_indices:
            co = mw @ ob.data.vertices[ob.data.loops[li].vertex_index].co
            u = 0.002 + 0.996 * (co.x - x0) / max(x1 - x0, 1e-6)
            v = 0.002 + 0.996 * (co.z - z0) / max(z1 - z0, 1e-6)
            uvl.data[li].uv = (u, v)


def look_at(cam, target):
    d = Vector(target) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    m01.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.view_settings.exposure = -0.35   # v13e: 底带255镜面掠射爆白保护
    scene.render.resolution_x = 1920
    scene.render.resolution_y = 1152
    scene.render.film_transparent = False

    world = bpy.data.worlds.new("CaseWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.85, 0.88, 1)  # 冷调环境
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.04
    scene.world = world

    steel = (0.88, 0.89, 0.91)
    brand_green = (0.02, 0.40, 0.25)
    # 背墙 + 抛光地砖
    _box("BackWall", 3.0, 0.02, 2.0, (0, 0.32, 1.0), (0.58, 0.59, 0.60), rough=0.9)
    _floor = _box("Floor", 3.0, 3.0, 0.01, (0, 0, -0.070), (0.52, 0.52, 0.53), rough=0.55)   # v13i: 地板顶面降到 z=-0.065
    # v14: 地砖缝纹理 + 每砖色差 (真实感)
    floor_mat = bpy.data.materials.new("FloorTiles")
    floor_mat.use_nodes = True
    _fn = floor_mat.node_tree
    _ft = _fn.nodes.new("ShaderNodeTexImage")
    _ft.image = bpy.data.images.load(os.path.join(BASE_DIR, "assets", "textures", "floor_tiles.png"))
    _fn.links.new(_ft.outputs["Color"], _fn.nodes["Principled BSDF"].inputs["Base Color"])
    _floor.data.materials.clear()
    _floor.data.materials.append(floor_mat)
    _uv_full_face(_floor)
    # 冷柜柜体: 背板 + 侧立柱 (品牌绿饰条) + 顶底檐
    _box("CaseBack", CASE_W, 0.006, CASE_H, (0, 0.085, CASE_H / 2), (0.78, 0.79, 0.80), rough=0.6)
    for sx in (-1, 1):
        _box(f"CasePillar_{sx}", 0.020, CASE_D + 0.012, CASE_H,
             (sx * (CASE_W / 2 + 0.010), 0.030, CASE_H / 2), steel, rough=0.35)
        _box(f"CaseAccent_{sx}", 0.006, 0.006, CASE_H,
             (sx * (CASE_W / 2 - 0.002), 0.030 - CASE_D / 2 - 0.002, CASE_H / 2), brand_green, rough=0.4)
    _box("CaseTop", CASE_W + 0.044, CASE_D + 0.014, 0.014, (0, 0.030, CASE_H + 0.007), steel, rough=0.4)
    _box("CasePlinth", CASE_W + 0.044, CASE_D + 0.014, 0.060, (0, 0.030, -0.034), (0.42, 0.43, 0.44), rough=0.6)

    # 白色层板 + 前缘亚克力价签槽 (黄促销签贴图) + 板底 LED 灯带
    def _price_mat(tex, name):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        n = m.node_tree
        tt = n.nodes.new("ShaderNodeTexImage")
        tt.image = bpy.data.images.load(os.path.join(BASE_DIR, "assets", "textures", tex))
        n.links.new(tt.outputs["Color"], n.nodes["Principled BSDF"].inputs["Base Color"])
        return m
    PRICE_MATS = [_price_mat("shelf_price_strip_c.png", "PriceTop"),
                  _price_mat("shelf_price_strip.png", "PriceMid"),
                  _price_mat("shelf_price_strip_b.png", "PriceBot")]
    for zi, z in enumerate(ROW_Z):
        _box(f"Shelf_{zi}", CASE_W, CASE_D, SHELF_T, (0, 0.030, z - SHELF_T / 2), steel, rough=0.30)
        rail = _box(f"Rail_{zi}", CASE_W, 0.006, 0.028, (0, 0.030 - CASE_D / 2 + 0.004, z + 0.010),
                    (0.95, 0.95, 0.95), rough=0.25)
        rail.data.materials.clear()
        rail.data.materials.append(PRICE_MATS[zi])
        _uv_full_face(rail)

    # 板底 LED 灯带: 每块层板前缘下方 (z=板顶-0.012, 突出于价签槽之前), 冷白洗墙下层商品
    # (v13b 教训: 带塞进 rail 盒内部被遮挡; 底层带 z<0 被柜脚挡, 只装可见的两条)
    led_mat = bpy.data.materials.new("LEDStrip")
    led_mat.use_nodes = True
    _ln = led_mat.node_tree
    _em = _ln.nodes.new("ShaderNodeEmission")
    _em.inputs["Color"].default_value = (0.88, 0.93, 1.0, 1)   # 冷白 5000K+
    _em.inputs["Strength"].default_value = 20.0
    _ln.links.new(_em.outputs[0], _ln.nodes["Material Output"].inputs["Surface"])
    for z_led in (ROW_Z[0], ROW_Z[1]):
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.005, depth=CASE_W - 0.05,
                                            location=(0, 0.030 - CASE_D / 2 - 0.008, z_led - SHELF_T - 0.008))
        led = bpy.context.active_object
        led.name = f"LEDTube_{z_led}"
        led.rotation_euler = (0, math.radians(90), 0)
        led.data.materials.append(led_mat)
        # (v13g: 移除 LED 面光 — 泛光把柜前地板打到 255, 洗墙由主柔光承担)

    # 风幕柜硬件: 顶部出风口 (进画幅! z=0.545, v9/v13c 教训) + 柜脚回风格栅(百叶纹理)
    grille_mat = bpy.data.materials.new("Grille")
    grille_mat.use_nodes = True
    _gn = grille_mat.node_tree
    _gt = _gn.nodes.new("ShaderNodeTexImage")
    _gt.image = bpy.data.images.load(os.path.join(BASE_DIR, "assets", "textures", "case_grille.png"))
    _gn.links.new(_gt.outputs["Color"], _gn.nodes["Principled BSDF"].inputs["Base Color"])
    top_g = _box("AirCurtainTop", CASE_W, 0.014, 0.036, (0, -0.024, 0.528), (0.5, 0.5, 0.5), rough=0.5)   # v13h: 0.545→0.528 完整入画幅(帧顶0.542)
    top_g.data.materials.clear(); top_g.data.materials.append(grille_mat); _uv_full_face(top_g)
    ret_g = _box("ReturnGrille", CASE_W + 0.02, 0.030, 0.056, (0, 0.030 - CASE_D / 2 - 0.004, -0.028), (0.5, 0.5, 0.5), rough=0.5)   # v13j: 上仰百叶(真实回风口形态)
    ret_g.rotation_euler = (math.radians(-18), 0, 0)   # 面板上仰18°朝向俯视相机
    ret_g.data.materials.clear(); ret_g.data.materials.append(grille_mat); _uv_full_face(ret_g)

    # POP: 冷柜顶檐品牌条 (经典绿/酸奶蓝)
    pop_mat = bpy.data.materials.new("PopHeader")
    pop_mat.use_nodes = True
    _q = pop_mat.node_tree
    _pt2 = _q.nodes.new("ShaderNodeTexImage")
    _pt2.image = bpy.data.images.load(os.path.join(BASE_DIR, "assets", "textures", "shelf_pop_header.png"))
    _q.links.new(_pt2.outputs["Color"], _q.nodes["Principled BSDF"].inputs["Base Color"])
    popb = _box("PopHeader", 0.60, 0.010, 0.120, (0, 0.082, CASE_H + 0.074), (1, 1, 1))
    popb.data.materials.clear()
    popb.data.materials.append(pop_mat)
    _uv_full_face(popb)

    rng = random.Random(7)
    # 单排面零间隙密排: spacing = 品宽+2mm; 双排纵深 (后排错位半格露肩)
    for zi, row in enumerate((ROW_TOP, ROW_MID, ROW_BOT)):
        z = ROW_Z[zi]
        pw = 0.048 if zi < 2 else YOG_B[0]
        spacing = pw + 0.002
        n = len(row)
        x0 = -spacing * n / 2
        for i, item in enumerate(row):
            sku, dims = item if isinstance(item, tuple) else (item, None)
            x = x0 + spacing * (i + 0.5)
            for depth in range(2):
                xoff = (spacing * 0.5 if depth == 1 else 0.0) + rng.uniform(-0.001, 0.001)
                loc = (x + xoff,
                       0.016 + rng.uniform(-0.001, 0.001) + depth * 0.038, z)
                rot = (0, 0, math.radians(rng.uniform(-0.8, 0.8)))   # 冷柜排面更齐整
                if i == 7 and zi == 1 and depth == 0:
                    continue   # v15: 中层右4留一个缺货位 (生活气息)
                if zi == 0 and i == 3 and depth == 0:
                    rot = (0, 0, math.radians(3.2))   # 一盒没摆正
                if zi == 2 and i == 6 and depth == 0:
                    loc = (loc[0], loc[1] + 0.009, loc[2])   # 一盒没推齐
                if dims:
                    m01.build_carton_twin(sku, loc=loc, rot=rot, dims=dims)
                else:
                    m01.build_carton_twin(sku, loc=loc, rot=rot)
    bpy.context.view_layer.update()

    # 贴图去重 (双排×密排 ~150 盒; 重复 image remap 回首份后删除)
    _seen = {}
    for _img in list(bpy.data.images):
        if _img.filepath:
            _fp = os.path.abspath(bpy.path.abspath(_img.filepath))
            if _fp in _seen:
                _img.user_remap(_seen[_fp])
                bpy.data.images.remove(_img)
            else:
                _seen[_fp] = _img

    # 冷白主光 (5000K+) + 顶光; 层板灯带提供洗墙光
    aim = bpy.data.objects.new("Aim", None)
    aim.location = (0.0, 0.0, 0.20)
    bpy.context.collection.objects.link(aim)
    for pos, size, energy, color in [
        ((0.75, -1.05, 0.62), 0.9, 14.0, (0.93, 0.96, 1.0)),
        ((-0.95, -0.80, 0.45), 2.2, 4.0, (0.94, 0.96, 1.0)),
        ((0.0, -0.10, 1.60), 2.8, 8.0, (0.95, 0.97, 1.0)),
    ]:
        bpy.ops.object.light_add(type="AREA", location=pos)
        L = bpy.context.active_object
        L.data.size = size
        L.data.energy = energy
        L.data.color = color
        L.constraints.new("TRACK_TO").target = aim

    bpy.ops.object.camera_add(location=(0.0, -1.42, 0.260))
    cam = bpy.context.active_object
    scene.camera = cam
    cam.data.lens = 44
    look_at(cam, (0.0, 0.0, 0.195))
    cam.data.shift_y = 0.0
    # v14: DOF f/4 对焦前排商品面 — 前景地板虚化+远墙微融 (消"全图针锐"CG感)
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = 2.2
    cam.data.dof.focus_distance = 1.42

    out = os.path.join(OUT_DIR, f"{args.out}.png")
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    print(f"[SHELF] 冷柜版货架全景已保存: {out}")


if __name__ == "__main__":
    main()
