#!/usr/bin/env python3
"""离线提取真扫描蓝莓 → 独立 .blend 资产库 (一次性, 不在渲染期跑)。

动机: 外部评审多轮把"蓝莓塑料感/缺果粉与水润感"列入 #1 材质缺陷。仓内已有 CC-BY 真扫描
资产 `assets/sf_models/berries/`(¡Jacques), 子代理当初判"670k面挑不干净"→保持程序化蓝莓,
但**从未实测**。本仓探针实测推翻该判断: 按材质可**唯一分离**
`Sphere.037_Blueberry_0`(30172v/53504f), baseColor/normal/metallicRoughness 各 2048² 齐备。

为什么离线提取而不在渲染期 import glTF:
  ①本仓既有坑: `bpy.ops.import_scene.gltf` 有 ops 污染(扰动 active/selection), 必须放管线最末;
    道具是在 layout 期构建的, 中途 import 会踩坑。
  ②整包 670k 面, 只用其中 1 件 → 提前提取避免每次渲染都导入全包。
  提取后运行时用 `bpy.data.libraries.load`(纯数据 API, 不碰 ops)。

必须处理的实测坑: glTF 带巨大父级缩放, 蓝莓 world bbox 实测 **996518mm ≈ 1km**。
本脚本烘焙 matrix_world 后归一为**单位半径**(最大 XY 半径=1.0, zmin=0), 运行时按真实 rb 缩放。

用法(离线一次):
  blender -b --factory-startup -P extract_scan_berry.py
产出: assets/models/blueberry/blueberry.blend (网格+材质+贴图已 pack)
"""
import os
import math   # 本轮第三次同类漏 import(lifestyle_scene/shadow_probe/此处); py_compile 查不出
import sys

import bpy
import mathutils

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "assets", "sf_models", "berries", "scene.gltf")
OUT_DIR = os.path.join(BASE, "assets", "models", "blueberry")
OUT = os.path.join(OUT_DIR, "blueberry.blend")


def main():
    if not os.path.exists(SRC):
        raise SystemExit("源资产缺失: %s" % SRC)
    os.makedirs(OUT_DIR, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    before = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.gltf(filepath=SRC)
    new = [o for o in bpy.data.objects if o.name not in before]
    berry = [o for o in new if o.type == "MESH"
             and any(m and "blueberry" in m.name.lower() for m in o.data.materials)]
    if len(berry) != 1:
        raise SystemExit("蓝莓按材质应唯一分离, 实得 %d 件" % len(berry))
    ob = berry[0]
    mat = next(m for m in ob.data.materials if m and "blueberry" in m.name.lower())

    # 烘焙世界变换(消除 glTF 父级巨缩放), 再归一为单位半径、底面贴 z=0
    me = ob.data
    mw = ob.matrix_world.copy()
    me.transform(mw)
    ob.matrix_world = mathutils.Matrix.Identity(4)
    vs = [v.co for v in me.vertices]
    rmax = max(math.hypot(v.x, v.y) for v in vs)
    zmin = min(v.z for v in vs)
    if rmax <= 1e-9:
        raise SystemExit("退化网格: rmax=0")
    k = 1.0 / rmax
    for v in me.vertices:
        v.co = mathutils.Vector((v.co.x * k, v.co.y * k, (v.co.z - zmin) * k))
    me.update()
    me.name = "ScanBlueberry"
    ob.name = "ScanBlueberry"
    mat.name = "ScanBlueberryMat"

    # 只留这一件: 其余对象/网格/材质/贴图全清(避免把整包 670k 面与碗/草莓带进库)
    for o in list(bpy.data.objects):
        if o is not ob:
            bpy.data.objects.remove(o, do_unlink=True)
    for m in list(bpy.data.meshes):
        if m is not me:
            bpy.data.meshes.remove(m)
    for m in list(bpy.data.materials):
        if m is not mat:
            bpy.data.materials.remove(m)
    keep_img = {n.image for n in mat.node_tree.nodes
                if n.type == "TEX_IMAGE" and n.image}
    for im in list(bpy.data.images):
        if im not in keep_img:
            bpy.data.images.remove(im)
    for im in keep_img:
        im.pack()

    vs = [v.co for v in me.vertices]
    rr = max(math.hypot(v.x, v.y) for v in vs)
    zz = [v.z for v in vs]
    print("[EXTRACT] verts=%d polys=%d rmax=%.6f z=%.6f..%.6f imgs=%d"
          % (len(me.vertices), len(me.polygons), rr, min(zz), max(zz), len(keep_img)))
    assert abs(rr - 1.0) < 1e-5, "归一失败 rmax=%.6f" % rr
    assert abs(min(zz)) < 1e-6, "底面未贴0 zmin=%.6f" % min(zz)
    assert len(keep_img) >= 3, "贴图不足(应含 baseColor/normal/metallicRoughness)"
    assert all(im.packed_file for im in keep_img), "贴图未 pack, 库将依赖外部路径"

    bpy.ops.wm.save_as_mainfile(filepath=OUT)
    print("[SAVED]", OUT, "bytes=%d" % os.path.getsize(OUT))
    return 0


if __name__ == "__main__":
    sys.exit(main())