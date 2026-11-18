#!/usr/bin/env python3
"""
04 - 零售品牌 12 盒礼盒装、塑料提手与割箱陈列 (Cut-Case Tray) 3D 生成器

中国快消线下最核心陈列形态: 12 盒提手礼盒 + 割箱堆头 (顶部开口露出 12 个梦幻盖)。
输出: output/giftbox/carton_giftbox_12pk.usdc / carton_cutcase_tray.usdc + 端架陈列渲染图

运行:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P 04_giftbox_and_tray_builder.py
"""
import os
import math
import bpy
from mathutils import Matrix, Vector

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEX_DIR = os.path.join(BASE_DIR, "assets", "textures")
OUT_DIR = os.path.join(BASE_DIR, "output", "giftbox")
os.makedirs(OUT_DIR, exist_ok=True)

# 经典礼盒真实尺寸: 265 x 145 x 142 mm; 单盒 48 x 44 x 136 mm
BOX_W, BOX_D, BOX_H = 0.265, 0.145, 0.142
PACK_W, PACK_D, PACK_H = 0.048, 0.044, 0.136

UV_REGIONS = {
    "FRONT":  (60 / 2048, 1 - 1950 / 2048, 980 / 2048, 1 - 100 / 2048),
    "BACK":   (1060 / 2048, 1 - 1950 / 2048, 1980 / 2048, 1 - 100 / 2048),
    "SIDE_L": (984 / 2048, 1 - 1950 / 2048, 1022 / 2048, 1 - 100 / 2048),
    "SIDE_R": (1024 / 2048, 1 - 1950 / 2048, 1062 / 2048, 1 - 100 / 2048),
    "TOP":    (60 / 2048, 1 - 92 / 2048, 980 / 2048, 1 - 10 / 2048),
    "BOTTOM": (1060 / 2048, 1 - 92 / 2048, 1980 / 2048, 1 - 10 / 2048),
}


def assign_box_uv(obj, w, d, h):
    # Blender 5.x primitive cube 自带默认 UVMap 层, 必须写入第 0 层 (active_render)
    mesh = obj.data
    uvl = mesh.uv_layers[0] if len(mesh.uv_layers) else mesh.uv_layers.new(name="atlas")
    for poly in mesh.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 1:
            region = UV_REGIONS["FRONT"] if n.y < 0 else UV_REGIONS["BACK"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vz = mesh.vertices[vi].co.x, mesh.vertices[vi].co.z
                uvl.data[li].uv = (region[0] + (vx / w + 0.5) * (region[2] - region[0]),
                                   region[1] + (vz / h) * (region[3] - region[1]))
        elif ax == 0:
            region = UV_REGIONS["SIDE_L"] if n.x < 0 else UV_REGIONS["SIDE_R"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vy, vz = mesh.vertices[vi].co.y, mesh.vertices[vi].co.z
                uvl.data[li].uv = (region[0] + (vy / d + 0.5) * (region[2] - region[0]),
                                   region[1] + (vz / h) * (region[3] - region[1]))
        else:
            region = UV_REGIONS["TOP"] if n.z > 0 else UV_REGIONS["BOTTOM"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vy = mesh.vertices[vi].co.x, mesh.vertices[vi].co.y
                uvl.data[li].uv = (region[0] + (vx / w + 0.5) * (region[2] - region[0]),
                                   region[1] + (vy / d + 0.5) * (region[3] - region[1]))


def corrugated_material(name="Mat_CorrugatedBox"):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.68, 0.52, 0.36, 1.0)
    b.inputs["Roughness"].default_value = 0.72
    return mat


def handle_material():
    mat = bpy.data.materials.new("Mat_WhitePlasticHandle")
    mat.use_nodes = True
    b = mat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.90, 0.90, 0.88, 1.0)
    b.inputs["Roughness"].default_value = 0.22
    b.inputs["Metallic"].default_value = 0.1
    return mat


def sku_material(sku="demo_organic"):
    mat = bpy.data.materials.new(f"Mat_{sku}")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = 0.38
        bsdf.inputs["Coat Roughness"].default_value = 0.12
    for fname, chan in ((f"{sku}_albedo.png", "Color"), (f"{sku}_orm.png", "NonColor"),
                        ("tetrapak_common_normal.png", "Normal")):
        p = os.path.join(TEX_DIR, fname)
        if not os.path.exists(p):
            continue
        t = nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(p)
        if chan == "NonColor":
            t.image.colorspace_settings.name = "Non-Color"
            sep = nodes.new("ShaderNodeSeparateColor")
            links.new(t.outputs["Color"], sep.inputs["Color"])
            links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
            links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
        elif chan == "Normal":
            t.image.colorspace_settings.name = "Non-Color"
            nm = nodes.new("ShaderNodeNormalMap")
            nm.inputs["Strength"].default_value = 0.45
            links.new(t.outputs["Color"], nm.inputs["Color"])
            links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
        else:
            links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def make_box(name, w, d, h, loc, bottom_origin=True):
    """size=1 cube -> 缩放到 w,d,h -> origin 移到指定位置(默认底面中心)"""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = name
    obj.scale = (w, d, h)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bottom_origin:
        obj.data.transform(Matrix.Translation((0, 0, h / 2)))
    obj.location = loc
    return obj


def build_giftbox(loc=(0, 0, 0)):
    """12 盒手提礼盒: 瓦楞箱体 + 烫金品牌面贴图 + 白色塑料提手"""
    box = make_box("Carton_12PK_GiftBox", BOX_W, BOX_D, BOX_H, loc)
    bev = box.modifiers.new("BoxBevel", "BEVEL")
    bev.width = 0.003
    bev.segments = 2
    try:
        bpy.ops.object.shade_smooth()
        bpy.ops.object.shade_auto_smooth(angle=math.radians(40))
    except AttributeError:
        pass
    box.data.materials.append(corrugated_material())
    # 品牌面: 正/背面贴经典贴图 (礼盒印刷面)
    box.data.materials.append(sku_material("demo_organic"))
    # 简化: 材质槽 0 通用瓦楞, 正背面用槽 1 (按面分配)
    for poly in box.data.polygons:
        if abs(poly.normal.y) > 0.5:
            poly.material_index = 1
    assign_box_uv(box, BOX_W, BOX_D, BOX_H)

    bpy.ops.mesh.primitive_cylinder_add(radius=0.006, depth=0.12,
                                        location=(loc[0], loc[1], loc[2] + BOX_H + 0.012))
    handle = bpy.context.active_object
    handle.name = "PlasticHandle"
    handle.rotation_euler = (0, math.radians(90), 0)
    handle.parent = box
    handle.matrix_parent_inverse = box.matrix_world.inverted()
    handle.data.materials.append(handle_material())
    return box


def build_cutcase_tray(loc=(0, 0, 0), sku="demo_organic"):
    """割箱陈列: 瓦楞托盘(四壁+底) + 3x4 网格 12 盒牛奶 (顶部梦幻盖外露)"""
    tray_h = 0.085
    wall_t = 0.008
    group = []
    floor = make_box("Tray_Floor", BOX_W, BOX_D, 0.01, (loc[0], loc[1], loc[2]))
    floor.data.materials.append(corrugated_material())
    group.append(floor)
    zt = loc[2] + 0.01   # 托盘地板顶面
    walls = [
        ("Tray_Wall_F", BOX_W, wall_t, tray_h - 0.01, (loc[0], loc[1] - BOX_D / 2 + wall_t / 2, zt)),
        ("Tray_Wall_B", BOX_W, wall_t, tray_h - 0.01, (loc[0], loc[1] + BOX_D / 2 - wall_t / 2, zt)),
        ("Tray_Wall_L", wall_t, BOX_D - 2 * wall_t, tray_h - 0.01, (loc[0] - BOX_W / 2 + wall_t / 2, loc[1], zt)),
        ("Tray_Wall_R", wall_t, BOX_D - 2 * wall_t, tray_h - 0.01, (loc[0] + BOX_W / 2 - wall_t / 2, loc[1], zt)),
    ]
    for name, w, d, h, p in walls:
        wl = make_box(name, w, d, h, p)
        wl.data.materials.append(corrugated_material())
        group.append(wl)

    # 3 x 4 网格摆 12 盒 (割箱: 上半截箱体切开, 盒上部+盖外露)
    cols, rows = 4, 3
    sku_mat = sku_material(sku)
    cap_mat = bpy.data.materials.new("DreamCap_HDPE")
    cap_mat.use_nodes = True
    cb = cap_mat.node_tree.nodes.get("Principled BSDF")
    cb.inputs["Base Color"].default_value = (0.06, 0.38, 0.20, 1.0)
    cb.inputs["Roughness"].default_value = 0.25
    if "Subsurface Weight" in cb.inputs:
        cb.inputs["Subsurface Weight"].default_value = 0.25
    for r in range(rows):
        for c in range(cols):
            px = loc[0] - BOX_W / 2 + wall_t + PACK_W / 2 + c * (PACK_W + 0.004)
            py = loc[1] - BOX_D / 2 + wall_t + PACK_D / 2 + r * (PACK_D + 0.004)
            pack = make_box(f"Pack_{r}_{c}", PACK_W, PACK_D, PACK_H, (px, py, zt))
            pack.data.materials.append(sku_mat)
            assign_box_uv(pack, PACK_W, PACK_D, PACK_H)
            bpy.ops.mesh.primitive_cylinder_add(radius=0.013, depth=0.011,
                                                location=(px, py, zt + PACK_H + 0.004))
            cap = bpy.context.active_object
            cap.name = f"Cap_{r}_{c}"
            cap.parent = pack
            cap.matrix_parent_inverse = pack.matrix_world.inverted()
            cap.data.materials.append(cap_mat)
            group.append(pack)
            group.append(cap)
    return group


def setup_render(samples=64):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = "METAL"
    prefs.get_devices()
    for d in prefs.devices:
        d.use = True
    scene.cycles.device = "GPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1600, 1200
    world = bpy.data.worlds.new("Studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.92, 0.95, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.1
    scene.world = world


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_render()

    # 端架陈列: 后排割箱堆头 x2 + 前排礼盒 x2
    build_cutcase_tray(loc=(-0.16, 0.06, 0), sku="demo_organic")
    build_cutcase_tray(loc=(0.16, 0.06, 0), sku="demo_jersey")
    build_giftbox(loc=(-0.15, -0.12, 0))
    build_giftbox(loc=(0.16, -0.12, 0))

    # 台面 + 三点布光 (能量降档)
    floor = make_box("Table", 1.2, 0.6, 0.02, (0, 0, -0.02))
    fm = bpy.data.materials.new("WoodTable")
    fm.use_nodes = True
    fb = fm.node_tree.nodes["Principled BSDF"]
    fb.inputs["Base Color"].default_value = (0.45, 0.32, 0.2, 1)
    fb.inputs["Roughness"].default_value = 0.5
    floor.data.materials.append(fm)

    bpy.ops.object.light_add(type="AREA", location=(-0.5, -0.6, 0.8))
    key = bpy.context.active_object
    key.data.energy = 40.0
    key.data.size = 0.6
    key.rotation_euler = (math.radians(45), 0, math.radians(30))
    bpy.ops.object.light_add(type="AREA", location=(0.6, -0.3, 0.4))
    rim = bpy.context.active_object
    rim.data.energy = 12.0
    rim.data.size = 0.3

    bpy.ops.object.camera_add(location=(0.05, -0.85, 0.42),
                              rotation=(math.radians(72), 0, 0))
    cam = bpy.context.active_object
    cam.data.lens = 45
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    scene.render.filepath = os.path.join(OUT_DIR, "carton_endcap_display.png")
    bpy.ops.render.render(write_still=True)
    print(f"[Success] 端架陈列渲染图 -> {scene.render.filepath}")

    # 导出 USD (礼盒 + 割箱各一份)
    for target, fname in ((("Carton_12PK_GiftBox",), "carton_giftbox_12pk.usdc"),):
        bpy.ops.object.select_all(action="DESELECT")
        for name in target:
            bpy.data.objects[name].select_set(True)
            for ch in bpy.data.objects[name].children_recursive:
                ch.select_set(True)
        bpy.ops.wm.usd_export(filepath=os.path.join(OUT_DIR, fname),
                              selected_objects_only=True, export_materials=True)
        print(f"[Exported] {fname}")

    bpy.ops.object.select_all(action="DESELECT")
    for ob in bpy.data.objects:
        if ob.name.startswith(("Tray_", "Pack_", "Cap_")):
            ob.select_set(True)
    bpy.ops.wm.usd_export(filepath=os.path.join(OUT_DIR, "carton_cutcase_tray.usdc"),
                          selected_objects_only=True, export_materials=True)
    print("[Exported] carton_cutcase_tray.usdc")


if __name__ == "__main__":
    main()
