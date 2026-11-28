#!/usr/bin/env python3
"""资产缩略图 (官方 SimReady SR.002 要求的 .thumbs/256x256/<主文件>.png)。

缩略图**与 USD 资产同源**: 用与 13_usd_asset.py 完全相同的 build_carton_twin() 现场搭几何
再渲染 -> 不会出现"资产改了、缩略图还是旧的"这种静默漂移 ✓。

产出两张:
  <stem>.png        影棚灰底渲染 (主缩略图, SR.002 要求的那张 ✓)
  <stem>_light.png  白底高环境光版本 (官方包也认这个后缀 ✓)

用法 (Blender 内):
  blender -b -P 87_asset_thumbnail.py -- --sku demo_classic --stem demo_classic.usda \
      --out output/usd/demo_classic_pkg
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)


def _compositor():
    """加载 01_comfy_usd_compositor (只用它的 build_carton_twin, 不跑它的渲染链)。"""
    import importlib.util as ilu
    path = os.path.join(BASE, "pipelines", "ecommerce", "01_comfy_usd_compositor.py")
    spec = ilu.spec_from_file_location("comp", path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    import bpy
    from mathutils import Vector

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sku = argv[argv.index("--sku") + 1] if "--sku" in argv else "demo_classic"
    stem = argv[argv.index("--stem") + 1] if "--stem" in argv else f"{sku}.usda"
    out = argv[argv.index("--out") + 1] if "--out" in argv else os.path.join(
        BASE, "output", "usd", f"{sku}_pkg")
    if not os.path.isabs(out):
        out = os.path.join(BASE, out)
    thumb_dir = os.path.join(out, ".thumbs", "256x256")
    os.makedirs(thumb_dir, exist_ok=True)

    comp = _compositor()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    objs = [o for o in comp.build_carton_twin(sku) if o]
    bpy.context.view_layer.update()

    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    ctr = (lo + hi) / 2.0
    size = max((hi - lo).x, (hi - lo).y, (hi - lo).z)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in \
        {i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} else "BLENDER_EEVEE"
    scene.render.resolution_x = 256
    scene.render.resolution_y = 256
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass

    # 相机: 3/4 视角, 略高于物体中心
    cam_data = bpy.data.cameras.new("ThumbCam")
    cam = bpy.data.objects.new("ThumbCam", cam_data)
    bpy.context.collection.objects.link(cam)
    cam_data.lens = 85.0
    cam.location = ctr + Vector((0.9, -1.5, 0.75)).normalized() * (size * 3.4)
    cam.rotation_euler = (ctr - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam

    # 灯光: 主光 + 补光 + 轮廓光
    def _area(name, loc, energy, size_):
        ld = bpy.data.lights.new(name, "AREA")
        ld.energy = energy
        ld.size = size_
        ob = bpy.data.objects.new(name, ld)
        bpy.context.collection.objects.link(ob)
        ob.location = loc
        ob.rotation_euler = (ctr - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        return ob

    _area("Key", ctr + Vector((1.2, -1.6, 1.8)), 260.0, size * 1.2)
    _area("Fill", ctr + Vector((-1.6, -1.0, 0.6)), 90.0, size * 1.6)
    _area("Rim", ctr + Vector((-0.4, 1.8, 1.2)), 150.0, size * 0.8)

    world = bpy.data.worlds.new("ThumbWorld")
    scene.world = world

    def _render(bg, world_strength, key_scale, path):
        world.use_nodes = True
        bg_node = world.node_tree.nodes.get("Background")
        bg_node.inputs[0].default_value = (bg[0], bg[1], bg[2], 1.0)
        bg_node.inputs[1].default_value = world_strength
        bpy.data.objects["Key"].data.energy = 260.0 * key_scale
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)

    main_png = os.path.join(thumb_dir, f"{stem}.png")
    light_png = os.path.join(thumb_dir, f"{stem}_light.png")
    _render((0.16, 0.16, 0.17), 0.55, 1.0, main_png)
    _render((0.92, 0.92, 0.93), 1.35, 1.35, light_png)

    for p in (main_png, light_png):
        print(f"[THUMB] {p} ({os.path.getsize(p) if os.path.exists(p) else 0} bytes)")


if __name__ == "__main__":
    main()
