#!/usr/bin/env python3
"""资产**消费端**检查: 用 Blender (一个真实下游消费者) 打开我们打好的官方包, 看它到底能不能用。

2026-11-28 为什么加这个: 官方验证器 (Package-Candidate / Material) 对我们的包**全 PASS**,
但 Blender 导入后 **材质 0 / 贴图 0** —— 原因是我们用的是**自定义关系名**
`material:binding:pack` / `:cap`, 而标准 USD 消费者认的是 `material:binding` ✓。
**"官方 PASS" 不等于 "消费者能用"** —— 所以要有一个**消费端**的证据 ✓。

用法 (bpy 环境):
  python tools/blender_shim.py -b -P 88_asset_consume_check.py -- \
      --usd output/usd/_simready_work/demo_classic_package/demo_classic.usda
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "output", "benchmark", "asset_consume_check.json")
DEFAULT_USD = os.path.join(BASE, "output", "usd", "_simready_work",
                            "demo_classic_package", "demo_classic.usda")


def main():
    import bpy

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    usd = DEFAULT_USD
    for i, a in enumerate(argv):
        if a == "--usd" and i + 1 < len(argv):
            usd = argv[i + 1]
    if not os.path.isabs(usd):
        usd = os.path.join(BASE, usd)
    if not os.path.exists(usd):
        print(f"[CONSUME] 找不到 {usd}")
        return 2

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.usd_import(filepath=usd)

    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    slots = {}
    for o in meshes:
        slots[o.name] = [s.material.name if s.material else None for s in o.material_slots]
    textures = [i.filepath for i in bpy.data.images if i.source == "FILE"]
    materials = [m.name for m in bpy.data.materials if m.name and m.name != "Dots Stroke"]

    # 朝向核对 (消费端世界里的"立着没有") ✓
    # **这条是弱检查**: Blender 自己的世界是 Z-up, 它的 USD 导入器按 Z-up 处理 ✓
    # -> 2026-11-28 实测: 把 USD 的 upAxis 改回 Y, 这里**照样**显示"立着" ✓
    # -> 所以它**测不出**"声明层"的 upAxis 问题 ✓; 声明层由两处负责:
    #    ① 13 号自己闸门里的"最长轴 == 声明 up 轴"断言 ✓ (负向测试报红 ✓)
    #    ② 官方 UN.006 ("Stage has upAxis of 'Y', not 'Z'") ✓
    # 这里保留它, 只当"消费端冒烟"用 (万一资产是躺平的模型, 至少能看出来 ✓)
    tallest_axis = None
    tallest = -1.0
    for o in meshes:
        for corner in o.bound_box:
            w = o.matrix_world @ __import__("mathutils").Vector(corner)
            for i, v in enumerate((w.x, w.y, w.z)):
                if v > tallest:
                    tallest = v
                    tallest_axis = i
    # Blender 导入 USD 会按 upAxis 换算 -> 这里量的是**消费端世界**里的最高轴 ✓
    standing = (tallest_axis == 2)

    payload = {
        "generated_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "pipelines/ecommerce/88_asset_consume_check.py",
        "consumer": "Blender (bpy wheel) 的 USD 导入器 —— 真实下游消费者",
        "usd": os.path.relpath(usd, BASE).replace("\\", "/"),
        "objects": len(bpy.data.objects),
        "meshes": len(meshes),
        "materials": materials,
        "material_slots": slots,
        "textures": [t.replace("\\", "/") for t in textures],
        "tallest_axis_in_consumer_world": "XYZ"[tallest_axis] if tallest_axis is not None else None,
        "standing_up": standing,
        "verdict": ("materials_bound" if materials else "NO_MATERIAL_BOUND")
                   + ("" if standing else "+LAID_DOWN"),
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[CONSUME] 网格 {len(meshes)} / 材质 {len(materials)} / 贴图 {len(textures)}")
    for k, v in slots.items():
        print(f"   {k}: {v}")
    print(f"[CONSUME] 消费端世界里最高轴 = {'XYZ'[tallest_axis] if tallest_axis is not None else '?'} "
          f"({'立着 ✓' if standing else '侧躺 ✗'})")
    print(f"[CONSUME] -> {OUT}")
    if not materials:
        print("[CONSUME] 失败: 消费者看不到任何材质 (标准 material:binding 没授权?)")
        return 1
    if not standing:
        print("[CONSUME] 失败: 消费端里资产是侧躺的 (声明的 upAxis 与几何不一致?)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
