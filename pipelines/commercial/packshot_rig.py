#!/usr/bin/env python3
"""P1-A 白底主图产线 (Packshot rig): 声明式规格 + 运行时测量 + GS1技术闸。

设计(联合结论第四条 P1-A):
  - 正交相机正面视图: 零透视畸变(GS1要求正脸无梯形失真)
  - 纯白世界(Standard变换, 线性1.0→255) + 三区平光: 无影棚语义
  - 无地面接触影: GS1产品图规范无影优先; "悬浮检查"由此不适用(NOT_APPLICABLE, 披露)
  - 所有关键尺寸运行时测量(spec只声明意图), 沿用 P0 纪律
闸(GS1_TECHNICAL_PASS 层, 内部技术检查, 收件方验收另走人工):
  P1 背景纯度(边缘带≥252/p05≥248) P2 主体高度填充[0.72,0.92]
  P3 居中≤3% P4 静区≥6% P5 纵横比畸变≤5%(正交应≈0)
  P6 品牌墨色存在(中央带相对墨色≥0.02, 防涂毁类)

运行: Blender -b -P packshot_rig.py -- [--samples 128] [--out packshot_v1]
输出: output/commercial/repro_packshot_<out>.png + repro_packshot_<out>_manifest.json
"""
import argparse
import json
import os
import sys
import hashlib

import bpy

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

import brick_carton_1l as y1l  # noqa: E402

FILL_H_BAND = (0.72, 0.92)   # 主体高/画幅高
CENTER_TOL = 0.03
MARGIN_MIN = 0.06
ASPECT_TOL = 0.05
BG_BORDER = 0.04             # 边缘带宽度(占画幅)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def purge_default_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)


def world_bbox(objs):
    import mathutils
    pts = []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in objs:
        oe = o.evaluated_get(dg)
        for c in oe.bound_box:
            pts.append(oe.matrix_world @ mathutils.Vector(c))
    xs = [p.x for p in pts]
    ys = [p.y for p in pts]
    zs = [p.z for p in pts]
    return (min(xs), max(xs), min(ys), max(ys), min(zs), max(zs))


def build(spec):
    # 盒体构建参数: 规格为缺省, 外部env优先(本仓标定开关语义)
    # v5教训: 独立路径默认PAPER_DEFORM=1.0, 产线规格0.35 → 3倍变形=视觉验收"褶皱/鼓胀"
    cb = spec.get("carton_build", {})
    os.environ["PAPER_DEFORM"] = os.environ.get("PAPER_DEFORM",
                                                str(cb.get("paper_deform", 1.0)))
    carton, _cap = y1l.build_carton_1l(loc=(0, 0, 0), cap_open=False)
    bpy.context.view_layer.update()
    objs = [o for o in bpy.data.objects if o.type == "MESH"]
    bb = world_bbox(objs)
    h = bb[5] - bb[4]
    w = bb[1] - bb[0]
    cz = (bb[4] + bb[5]) / 2.0
    # ---- 相机: 正交, 正面(-y), 垂直居中 ----
    cam = bpy.data.cameras.new("PackCam")
    cam.type = "ORTHO"
    cam.ortho_scale = h / float(spec.get("fill_target", 0.82))
    co = bpy.data.objects.new("PackCam", cam)
    bpy.context.collection.objects.link(co)
    co.location = (0.0, -1.0, cz)
    co.rotation_euler = (1.5707963, 0.0, 0.0)   # 沿+y看, 正脸平行传感器
    bpy.context.scene.camera = co
    # ---- 三区平光: 左/右45°柔光 + 顶光 ----
    lw = spec.get("light", {})
    for nm, loc, rot, size, pw in (
        ("KeyL", (-0.5, -0.7, cz + h * 0.35), (1.1, 0.0, 0.65), 1.2, lw.get("side_w", 150)),
        ("KeyR", (0.5, -0.7, cz + h * 0.35), (1.1, 0.0, -0.65), 1.2, lw.get("side_w", 150)),
        ("Top", (0.0, -0.15, cz + h + 0.45), (0.0, 0.25, 0.0), 0.8, lw.get("top_w", 120)),
    ):
        ld = bpy.data.lights.new(nm, "AREA")
        ld.energy = float(pw)
        ld.size = size
        lo = bpy.data.objects.new(nm, ld)
        bpy.context.collection.objects.link(lo)
        lo.location = loc
        lo.rotation_euler = rot
    return carton, bb, h, w


def render(spec, out_png, samples, a_seed="0"):
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "GPU"
    sc.cycles.samples = int(samples)
    sc.cycles.use_denoising = True
    sc.cycles.seed = int(seed) if (seed := os.environ.get("PS_SEED", a_seed)) else 0
    sc.render.resolution_x = int(spec["frame"]["res"])
    sc.render.resolution_y = int(spec["frame"]["res"])
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    vs = sc.view_settings
    vs.view_transform = "Standard"      # 线性直通: 白世界→255 纯白
    vs.look = "None"
    vs.exposure = 0.0
    vs.gamma = 1.0
    wd = bpy.data.worlds.get("PackWorld") or bpy.data.worlds.new("PackWorld")
    sc.world = wd
    wd.use_nodes = True
    nt = wd.node_tree
    nt.nodes.clear()
    # 摄影棚解: 白世界既当背景又当光源会双输(照明路径把纸面顶到255削顶,
    # v2实测全带p50=255)。Light Path.Is Camera Ray 分离: 相机看1.0(背景255),
    # 照明贡献 lit_strength=0.85 → 纸面留出墨色/形塑余量(P7≤252)。
    col = tuple(spec.get("world", {}).get("color", (1.0, 1.0, 1.0)))
    bg_cam = nt.nodes.new("ShaderNodeBackground")
    bg_cam.inputs[0].default_value = col + (1.0,)
    bg_cam.inputs[1].default_value = float(spec.get("world", {}).get("strength", 1.0))
    bg_lit = nt.nodes.new("ShaderNodeBackground")
    bg_lit.inputs[0].default_value = col + (1.0,)
    bg_lit.inputs[1].default_value = float(spec["world"].get("lit_strength", 0.85))
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    mix.inputs[0].default_value = 0.0
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_lit.outputs["Background"], mix.inputs[1])   # fac=0 非相机
    nt.links.new(bg_cam.outputs["Background"], mix.inputs[2])   # fac=1 相机
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    sc.render.filepath = out_png
    bpy.ops.render.render(write_still=True)


def gates(out_png, mani):
    # 闸逻辑单一来源: packshot_gates.py (纯Python, 免Blender可迭代; 含P7过曝门)
    from packshot_gates import gates as _g
    return _g(out_png, mani)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", default="128")
    ap.add_argument("--out", default="packshot_v1")
    ap.add_argument("--seed", default="0")   # P1-B先导: 重复种子(0=Blender默认)
    a = ap.parse_args(argv)
    spec = json.load(open(os.path.join(BASE_DIR, "specs", "packshot_1l.json")))
    purge_default_scene()
    carton, bb, h, w = build(spec)
    out_png = os.path.join(BASE_DIR, "output", "commercial", "repro_packshot_%s.png" % a.out)
    render(spec, out_png, a.samples, a.seed)
    mani_pre = {"carton_h_m": h, "carton_w_m": w}
    rows, ok = gates(out_png, mani_pre)
    npass = sum(1 for r in rows if r[1])
    print("[PACKSHOT] %s %dx%d -> %d/%d PASS" % (os.path.basename(out_png),
          int(spec["frame"]["res"]), int(spec["frame"]["res"]), npass, len(rows)))
    for name, okr, val in rows:
        print("   %-38s %s  实测 %s" % (name, "PASS" if okr else "FAIL", val))
    mani = {
        "schema": "packshot-manifest/1.0", "candidate": out_png,
        "carton_world_bbox_m": list(bb), "carton_h_m": h, "carton_w_m": w,
        "camera": {"type": "ORTHO", "ortho_scale": h / spec.get("fill_target", 0.82),
                   "view": "front", "keystone": "none(正交)"},
        "view_transform": "Standard", "samples": int(a.samples),
        "shadow_policy": "shadow-free(GS1无影优先; 接触影不适用=NOT_APPLICABLE)",
        "render_sha256": sha256_file(out_png), "gates": [
            {"claim": n, "result": ("PASS" if o else "FAIL"), "evidence": v}
            for n, o, v in rows],
        "gs1_layer": "GS1_TECHNICAL_PASS" if ok else "FAIL",
        "note": "收件方商业验收另走人工; 本闸仅为内部技术检查",
    }
    mp = out_png.replace(".png", "_manifest.json")
    json.dump(mani, open(mp, "w"), ensure_ascii=False, indent=2)
    print("[PACKSHOT] manifest →", mp, "| layer:", mani["gs1_layer"])
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
