#!/usr/bin/env python3
"""资产级规范闸 (docs/TWIN_ASSET_SPEC.md §1-§6 逐条机器验收)。

在 Blender 内对孪生源资产做 Khronos 3D Commerce v1.0 条款验收:
  原点/单位尺度 / ngon / 流形 / 三角数 / UV 0-1 / 导出无灯光 / 材质数 / 贴图规格 / 文件<5MB
用法 (Blender 内):
  blender -b -P 12_asset_spec_gate.py -- --sku demo_classic
退出码 0=PASS 1=FAIL (可挂 CI)。
"""
import json
import math
import os
import struct
import sys

import bpy

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

MAX_TRIS = 100_000          # Khronos 发布目标
MAX_BYTES = 5 * 1024 * 1024
UV_EPS = 1e-3


def _eval_mesh(obj):
    dg = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(dg).to_mesh()


def check_origin_dims(pack, spec_dims):
    me = _eval_mesh(pack)
    zs = [ (pack.matrix_world @ v.co).z for v in me.vertices ]
    xs = [ (pack.matrix_world @ v.co).x for v in me.vertices ]
    ys = [ (pack.matrix_world @ v.co).y for v in me.vertices ]
    bottom = min(zs)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    ok_o = abs(bottom) < 0.001 and abs(cx) < 0.001 and abs(cy) < 0.001
    d = pack.dimensions
    ok_d = all(abs(d[i] - spec_dims[i]) < 0.0008 for i in range(3))
    detail = f"bottom={bottom*1000:.2f}mm center=({cx*1000:.1f},{cy*1000:.1f})mm dims=({d.x*1000:.1f},{d.y*1000:.1f},{d.z*1000:.1f})mm spec={tuple(round(v*1000,1) for v in spec_dims)}"
    return ("PASS" if (ok_o and ok_d) else "FAIL"), detail


def check_topology(pack):
    me = _eval_mesh(pack)
    ngons = sum(1 for p in me.polygons if len(p.vertices) > 4)
    edge_cnt = {}
    for p in me.polygons:
        for ek in p.edge_keys:
            edge_cnt[ek] = edge_cnt.get(ek, 0) + 1
    nonmanifold = sum(1 for v in edge_cnt.values() if v != 2)
    tris = sum(len(p.vertices) - 2 for p in me.polygons)
    ok = ngons == 0 and nonmanifold == 0 and tris <= MAX_TRIS
    return ("PASS" if ok else "FAIL"), f"ngons={ngons} nonmanifold_edges={nonmanifold} tris={tris}"


def check_uv(pack):
    me = _eval_mesh(pack)
    if not me.uv_layers:
        return "FAIL", "no UV layer"
    uv = me.uv_layers[0].data
    lo = min(min(d.uv) for d in uv)
    hi = max(max(d.uv) for d in uv)
    ok = lo >= -UV_EPS and hi <= 1 + UV_EPS
    return ("PASS" if ok else "FAIL"), f"uv range [{lo:.4f},{hi:.4f}]"


def check_uv_atlas(tex_dir, sku, regions_norm):
    """R2: atlas 岛间 >=32px 间隙且零重叠; 岛外 16px gutter 均匀 (边缘扩张生效)。"""
    from PIL import Image
    import numpy as np
    ap = os.path.join(tex_dir, f"{sku}_albedo.png")
    if not os.path.exists(ap):
        return "SKIP", "no albedo"
    a = np.asarray(Image.open(ap).convert("RGB")).astype(np.int16)
    H, W = a.shape[:2]
    rects = {}
    for k, (u0, v0, u1, v1) in regions_norm.items():
        x0, x1 = int(u0 * W), int(u1 * W)
        y0, y1 = int((1 - v1) * H), int((1 - v0) * H)
        rects[k] = (x0, y0, x1, y1)
    names = list(rects)
    min_gap = 10 ** 9
    overlap = []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            ax0, ay0, ax1, ay1 = rects[names[i]]
            bx0, by0, bx1, by1 = rects[names[j]]
            ox = min(ax1, bx1) - max(ax0, bx0)
            oy = min(ay1, by1) - max(ay0, by0)
            if ox > 0 and oy > 0:
                overlap.append((names[i], names[j]))
                continue
            gap = max(min(ax0, bx0) - max(ax1, bx1) if ox <= 0 else -1,
                      min(ay0, by0) - max(ay1, by1) if oy <= 0 else -1)
            gap = max((ax0 - bx1) if ax0 >= bx1 else (bx0 - ax1) if bx0 >= ax1 else 99999,
                      (ay0 - by1) if ay0 >= by1 else (by0 - ay1) if by0 >= ay1 else 99999)
            min_gap = min(min_gap, gap)
    GUT = 16
    ring_std = 0
    for k, (x0, y0, x1, y1) in rects.items():
        rings = [a[max(0, y0 - GUT):y0, x0:x1], a[y1:min(H, y1 + GUT), x0:x1],
                 a[y0:y1, max(0, x0 - GUT):x0], a[y0:y1, x1:min(W, x1 + GUT)]]
        for r in rings:
            if r.size:
                ring_std = max(ring_std, float(r.std(axis=(0, 1)).mean()))
    ok = (not overlap) and min_gap >= 32 and ring_std <= 8
    detail = f"min_gap={min_gap}px overlaps={overlap} gutter_std={ring_std:.1f}"
    return ("PASS" if ok else "FAIL"), detail


def check_export(glb_path):
    with open(glb_path, "rb") as f:
        magic, ver, total = struct.unpack("<III", f.read(12))
        clen, ctype = struct.unpack("<II", f.read(8))
        chunk = f.read(clen)
    j = json.loads(chunk)
    mats = len(j.get("materials", []))
    imgs = j.get("images", [])
    mimes = {i.get("mimeType") for i in imgs}
    exts = set(j.get("extensionsUsed", []))
    lights = "KHR_lights_punctual" in exts or any("light" in n for n in j.get("nodes", []))
    size = os.path.getsize(glb_path)
    ok = (not lights) and mats <= 3 and size <= MAX_BYTES and mimes <= {"image/png", "image/webp"}
    detail = f"materials={mats} mimes={sorted(m for m in mimes if m)} lights={lights} size={size/1e6:.2f}MB"
    return ("PASS" if ok else "FAIL"), detail


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sku = "demo_classic"
    if "--sku" in argv:
        sku = argv[argv.index("--sku") + 1]
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("comp", os.path.join(BASE, "pipelines/ecommerce/01_comfy_usd_compositor.py"))
    comp = ilu.module_from_spec(spec)
    spec.loader.exec_module(comp)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    pack, cap, lip = comp.build_carton_twin(sku)
    bpy.context.view_layer.update()
    spec_dims = (comp.PACK_W, comp.PACK_D, comp.PACK_H)

    glb = os.path.join(BASE, "output", "ar_models", f"_gate_{sku}.glb")
    bpy.ops.object.select_all(action="DESELECT")
    for o in (pack, cap, lip):
        if o:
            o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True,
                              export_materials="EXPORT", export_image_format="WEBP")

    checks = {
        "origin_units": check_origin_dims(pack, spec_dims),
        "topology": check_topology(pack),
        "uv_01": check_uv(pack),
        "uv_atlas": check_uv_atlas(os.path.join(BASE, "assets", "textures"), sku, comp.UV_REGIONS),
        "export_targets": check_export(glb),
    }
    overall = "FAIL" if any(v[0] == "FAIL" for v in checks.values()) else "PASS"
    print(f"[ASSET-GATE] {overall} {sku}")
    for k, (verdict, detail) in checks.items():
        print(f"  {k:16s} {verdict:4s}  {detail}")
    os.remove(glb)
    sys.exit(0 if overall == "PASS" else 1)


if __name__ == "__main__":
    main()
