#!/usr/bin/env python3
"""
27 - 冷柜鲜奶区全景 (用户权威参照: 风幕冷柜 鲜奶/酸奶 冷藏陈列)

对齐参照核心品类形态: 屋顶包 (gable-top) + PET 瓶鲜奶/酸奶 + 利乐砖 — 新增
程序化屋顶包与PET瓶资产 (经典有机鲜牛奶/高端鲜奶/经典鲜牛奶/酸奶瓶)。
参照五特征: 白柜体+层板底LED灯带 / 单排面零间隙密排 / 黄促销签 / 品牌色块分区 /
冷白光; v14-v15 继承: DOF、地砖、生活化排面。相机后处理: 暗角+镜头畸变+颗粒。

运行:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P 27_coldcase_fresh.py -- [--samples 512] [--out name]
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
_s26 = importlib.util.spec_from_file_location("comp26", os.path.join(BASE_DIR, "pipelines/shelf_sdg/26_shelf_panorama.py"))
m26 = importlib.util.module_from_spec(_s26)
_s26.loader.exec_module(m26)   # 复用 _box/_uv_full_face/look_at (guard 保护, 不会跑 main)

import bpy
import bmesh
from mathutils import Vector, Matrix

OUT_DIR = os.path.join(BASE_DIR, "output", "shelf")
os.makedirs(OUT_DIR, exist_ok=True)

CASE_W, CASE_D, SHELF_T = 0.86, 0.115, 0.010
ROW_Z = (0.370, 0.165, 0.0)   # R11: 底砖142与中层板空腹33→13mm
CASE_H = 0.58

TEX = os.path.join(BASE_DIR, "assets", "textures")
BOX = (m01.YOG_BW, m01.YOG_BD, m01.YOG_BH)   # 酸奶系列 205g 砖


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--samples", type=int, default=512)
    p.add_argument("--out", default="coldcase_fresh_v1")
    return p.parse_args(argv)


# ---------------- 屋顶包 (gable-top): 五边形截面挤出 ----------------
def build_gable(sku, front_tex, loc, rot_z=0.0, w=0.040, d=0.030, h_body=0.078, h_ridge=0.030):   # R11: 参照 250mL 屋顶包 40×30×108 (H:W 2.7)
    """屋顶包: 底盒 + 山形顶 (五边形截面沿深度挤出); 正面贴 front_tex, 顶/侧奶白"""
    bm = bmesh.new()
    x0, x1 = -w / 2, w / 2
    y0, y1 = -d / 2, d / 2
    z0, z1, z2 = 0.0, h_body, h_body + h_ridge
    # R9: 脊线个体差 (P0-3 阵列残留): 脊高 ±10% + 脊位偏心 ±8%W → 顶线锯齿化
    _ridge_h = h_ridge * random.uniform(0.90, 1.10)
    _ridge_x = w * random.uniform(-0.08, 0.08)
    z2 = h_body + _ridge_h
    vs = [bm.verts.new(p) for p in [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),          # 底 4
        (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (x0, y0, z1),          # 肩 4
        (_ridge_x, y0, z2), (_ridge_x, y1, z2),                           # 脊 2 (偏心)
    ]]
    faces = [
        bm.faces.new((vs[0], vs[3], vs[2], vs[1])),   # 底 (朝下)
        bm.faces.new((vs[0], vs[1], vs[4], vs[7])),   # 前墙 (y0)
        bm.faces.new((vs[2], vs[3], vs[6], vs[5])),   # 后墙 (y1)
        bm.faces.new((vs[1], vs[2], vs[5], vs[4])),   # 右斜顶
        bm.faces.new((vs[3], vs[0], vs[7], vs[6])),   # 左斜顶
        bm.faces.new((vs[0], vs[1], vs[4], vs[8], vs[7])),   # 前端面五边形 (y0)
        bm.faces.new((vs[2], vs[3], vs[6], vs[9], vs[5])),   # 后端面五边形 (y1)
    ]
    mesh = bpy.data.meshes.new(f"Gable_{sku}")
    bm.to_mesh(mesh)
    bm.free()
    ob = bpy.data.objects.new(f"Gable_{sku}", mesh)
    ob.location = (loc[0], loc[1], loc[2] + z1 * 0)   # z0=0 origin
    ob.rotation_euler = (0, 0, math.radians(rot_z))
    # R4: 逐包个体差 (注模/充填差异): 非均匀缩放 ±2.5% + 微倾
    ob.scale = (1 + random.uniform(-0.025, 0.025),
                1 + random.uniform(-0.02, 0.02),
                1 + random.uniform(-0.015, 0.025))
    ob.rotation_euler.y = math.radians(random.uniform(-1.5, 1.5))
    bpy.context.collection.objects.link(ob)

    # UV: 正面墙单独贴图会复杂化; 直接给全盒贴 front_tex 并以世界几何投影 (简单可信:
    # 正面+背面同图, 侧面拉伸可见度低)。用 box 投影式 UV: u=世界x, v=世界z
    uvl = ob.data.uv_layers.new(name="UVMap")
    mw = ob.matrix_world
    for poly in ob.data.polygons:
        is_end = abs(poly.normal.y) > 0.7   # 前/后端面: 贴满整张标签纹理
        for li in poly.loop_indices:
            co = mw @ ob.data.vertices[ob.data.loops[li].vertex_index].co
            if is_end:
                u = 0.01 + 0.98 * (co.x - x0) / max(w, 1e-6)
                v = 0.01 + 0.98 * (co.z - z0) / max(z2 - z0, 1e-6)
                uvl.data[li].uv = (u, v)
            else:
                uvl.data[li].uv = (0.004, 0.5)   # 侧/顶/底采纹理左缘白底, 不 smear

    mat = bpy.data.materials.new(f"Mat_Gable_{sku}")
    mat.use_nodes = True
    n = mat.node_tree
    t = n.nodes.new("ShaderNodeTexImage")
    t.image = bpy.data.images.load(front_tex)
    t.image.colorspace_settings.name = "sRGB"
    n.links.new(t.outputs["Color"], n.nodes["Principled BSDF"].inputs["Base Color"])
    n.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.42   # 涂布纸
    if "Coat Weight" in n.nodes["Principled BSDF"].inputs:
        n.nodes["Principled BSDF"].inputs["Coat Weight"].default_value = 0.10
    n.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.52   # v4: 涂布纸哑光
    ob.data.materials.append(mat)
    return ob


# ---------------- PET 瓶: 瓶身+肩+颈+盖, 环标 UV 圆柱自带 ----------------
def build_pet_bottle(sku, label_tex, loc, rot_z=0.0, r=0.020, h_body=0.080):   # R13: 细瓶 40mm 径 (真图)   # R11: 总高~146mm (真 250mL 瓶 135-150)
    """鲜奶/酸奶 PET 瓶: 奶白半透瓶身 + 环标带 + 白盖"""
    parts = []
    # 瓶身 (奶白, 轻透)
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=r, depth=h_body,
                                        location=(loc[0], loc[1], loc[2] + h_body / 2))
    body = bpy.context.active_object
    body.name = f"Bottle_{sku}"
    bmat = bpy.data.materials.new(f"Mat_Bottle_{sku}")
    bmat.use_nodes = True
    b = bmat.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.93, 0.94, 0.96, 1)
    b.inputs["Roughness"].default_value = 0.18
    if "Transmission Weight" in b.inputs:
        b.inputs["Transmission Weight"].default_value = 0.55   # v10: HDPE 半透加强
    # R4: HDPE 次表面散射 (奶白体积感) + 逐瓶粗糙度随机 (微表面差异)
    if "Subsurface Weight" in b.inputs:
        b.inputs["Subsurface Weight"].default_value = 0.28
        b.inputs["Subsurface Radius"].default_value = (0.012, 0.015, 0.018)
    b.inputs["Base Color"].default_value = (0.95, 0.93, 0.89, 1)   # R5: 暖白 (奶液), 薄壁处透暖
    if "Transmission Weight" in b.inputs:
        b.inputs["Transmission Weight"].default_value = 0.65   # R5: rim 透光再进
    b.inputs["Roughness"].default_value = 0.18 + random.uniform(-0.045, 0.055)
    # R6: 微冷凝 (冷柜水汽): 高频 noise → 微 bump, 瓶肩密度感
    _nt = bmat.node_tree
    _nz = _nt.nodes.new("ShaderNodeTexNoise")
    _nz.inputs["Scale"].default_value = 420.0
    _nz.inputs["Detail"].default_value = 6.0
    _nz2 = _nt.nodes.new("ShaderNodeTexNoise")   # R9: 模具级微纹理 (P0-2)
    _nz2.inputs["Scale"].default_value = 55.0
    _nz2.inputs["Detail"].default_value = 3.0
    _bp = _nt.nodes.new("ShaderNodeBump")
    _bp.inputs["Strength"].default_value = 0.06
    _bp.inputs["Distance"].default_value = 0.0008
    _bp2 = _nt.nodes.new("ShaderNodeBump")
    _bp2.inputs["Strength"].default_value = 0.03
    _bp2.inputs["Distance"].default_value = 0.0006
    _nt.links.new(_nz.outputs["Fac"], _bp.inputs["Height"])
    _nt.links.new(_nz2.outputs["Fac"], _bp2.inputs["Height"])
    _nt.links.new(_bp.outputs["Normal"], _bp2.inputs["Normal"])
    _nt.links.new(_bp2.outputs["Normal"], b.inputs["Normal"])
    body.data.materials.append(bmat)
    # R4: 逐瓶个体差 (吹模差异): 非均匀缩放; R5: 高度差 ±2.5% → 盖顶线破直 (可见)
    body.scale = (1 + random.uniform(-0.02, 0.02),
                  1 + random.uniform(-0.02, 0.02),
                  1 + random.uniform(-0.025, 0.025))
    parts.append(body)
    # 肩 (圆锥台)
    bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=r, radius2=r * 0.44, depth=0.036,
                                    location=(loc[0], loc[1], loc[2] + h_body + 0.018))
    sh = bpy.context.active_object
    sh.name = f"Shoulder_{sku}"
    sh.data.materials.append(bmat)
    # 颈+盖
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=r * 0.44, depth=0.018,
                                        location=(loc[0], loc[1], loc[2] + h_body + 0.042))
    neck = bpy.context.active_object
    neck.name = f"Neck_{sku}"
    neck.data.materials.append(bmat)
    # R9: 瓶盖个体差 (P0-3): 半径 ±4% + 高度差 ±1.2mm + 微倾 ±3° → 盖群破齐
    bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=r * 0.48 * random.uniform(0.96, 1.04), depth=0.016,
                                        location=(loc[0], loc[1], loc[2] + h_body + 0.058 + random.uniform(-0.0012, 0.0012)))
    cap = bpy.context.active_object
    cap.name = f"Cap_{sku}"
    cap.rotation_euler = (math.radians(random.uniform(-3, 3)), math.radians(random.uniform(-3, 3)), 0)
    cmat = bpy.data.materials.new(f"Mat_Cap_{sku}")
    cmat.use_nodes = True
    cb = cmat.node_tree.nodes["Principled BSDF"]
    # R10: 盖色按 SKU (经典金/酸奶原味蓝/黄桃橙/草莓粉)
    _cap_col = {"demo": (160/255, 122/255, 40/255),
                "demo_yogurt_original": (0.15, 0.35, 0.65),
                "demo_yogurt_peach": (0.95, 0.55, 0.20),
                "demo_yogurt_straw": (0.90, 0.35, 0.45),
                "wblue": (0.15, 0.35, 0.65), "wgold": (160/255, 122/255, 40/255),
                "wred": (0.80, 0.20, 0.18), "wgreen": (0.10, 0.45, 0.25)}
    _cc = next((v for k, v in _cap_col.items() if k in sku), (0.15, 0.35, 0.65))
    cb.inputs["Base Color"].default_value = (*_cc, 1)
    cb.inputs["Roughness"].default_value = 0.35
    cap.data.materials.append(cmat)
    for p in (sh, neck, cap):
        p.parent = body
        p.matrix_parent_inverse = body.matrix_world.inverted()   # v3: 保持世界位 (裸parent会叠加body变换, 部件全位移)
    body.rotation_euler = (0, 0, math.radians(rot_z))

    # 环标: 细圆柱包 label_tex (圆柱 UV 自然环绕)
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=r * 1.03, depth=0.062,
                                        location=(loc[0], loc[1], loc[2] + h_body * 0.52))
    lab = bpy.context.active_object
    lab.name = f"Label_{sku}"
    lmat = bpy.data.materials.new(f"Mat_Label_{sku}")
    lmat.use_nodes = True
    ln = lmat.node_tree
    lt = ln.nodes.new("ShaderNodeTexImage")
    lt.image = bpy.data.images.load(label_tex)
    lt.image.colorspace_settings.name = "sRGB"
    ln.links.new(lt.outputs["Color"], ln.nodes["Principled BSDF"].inputs["Base Color"])
    ln.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.38   # v10: 印膜哑光
    lab.data.materials.append(lmat)
    lab.parent = body
    lab.matrix_parent_inverse = body.matrix_world.inverted()   # v3: 保持世界位
    return body


# ---------------- 酸奶杯 (R14): 锥形杯身+铝箔盖+环标 — 真图顶排形态 ----------------
def build_cup(sku, band_tex, loc, rot_z=0.0):
    """酸奶杯: 白锥形杯身 (底 21mm 顶 26mm, 高 95mm) + 银箔盖 + 环标"""
    bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.021, radius2=0.026, depth=0.095,
                                    location=(loc[0], loc[1], loc[2] + 0.0475))
    body = bpy.context.active_object
    body.name = f"Cup_{sku}"
    cmat = bpy.data.materials.new(f"Mat_Cup_{sku}")
    cmat.use_nodes = True
    cn = cmat.node_tree
    cb = cn.nodes["Principled BSDF"]
    cb.inputs["Base Color"].default_value = (0.96, 0.96, 0.95, 1)
    cb.inputs["Roughness"].default_value = 0.32 + random.uniform(-0.04, 0.04)
    body.data.materials.append(cmat)
    body.rotation_euler = (0, 0, math.radians(rot_z))
    _sx, _sy, _sz = (1 + random.uniform(-0.02, 0.02), 1 + random.uniform(-0.02, 0.02),
                     1 + random.uniform(-0.015, 0.02))
    body.scale = (_sx, _sy, _sz)
    _h = 0.095 * _sz
    # 环标 (锥面 UV 自然包裹; 贴图上白下场) — R14b: 同步 _sx/_sy/_sz + 0.8mm 相对余量, 防杯身吞标
    bpy.ops.mesh.primitive_cone_add(vertices=32, radius1=0.0218, radius2=0.0268, depth=0.095,
                                    location=(loc[0], loc[1], loc[2] + 0.0475))
    band = bpy.context.active_object
    band.name = f"CupBand_{sku}"
    band.scale = (_sx, _sy, _sz)
    bmat = bpy.data.materials.new(f"Mat_CupBand_{sku}")
    bmat.use_nodes = True
    bn = bmat.node_tree
    bt = bn.nodes.new("ShaderNodeTexImage")
    bt.image = bpy.data.images.load(os.path.join(BASE_DIR, band_tex))
    bt.image.colorspace_settings.name = "sRGB"
    bn.links.new(bt.outputs["Color"], bn.nodes["Principled BSDF"].inputs["Base Color"])
    bn.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.36
    band.data.materials.append(bmat)
    band.parent = body
    band.matrix_parent_inverse = body.matrix_world.inverted()
    # 铝箔盖 (银色金属) — R14b: 随杯高缩放定位, 防矮杯盖悬空/高杯盖内嵌
    bpy.ops.mesh.primitive_cylinder_add(vertices=32, radius=0.0274, depth=0.0025,
                                        location=(loc[0], loc[1], loc[2] + _h + 0.0015))
    lid = bpy.context.active_object
    lid.name = f"CupLid_{sku}"
    lid.scale = (_sx, _sy, 1)
    lmat = bpy.data.materials.new(f"Mat_CupLid_{sku}")
    lmat.use_nodes = True
    ln = lmat.node_tree
    lb = ln.nodes["Principled BSDF"]
    lb.inputs["Base Color"].default_value = (0.82, 0.83, 0.85, 1)
    lb.inputs["Metallic"].default_value = 1.0
    lb.inputs["Roughness"].default_value = 0.28
    lid.data.materials.append(lmat)
    lid.parent = body
    lid.matrix_parent_inverse = body.matrix_world.inverted()
    return body


# ---------------- 品慕 458mL 屋顶包 (R17: GPT审计重构 — 屋脊沿X, 坡面朝前后, 山墙端±X) ----------------
def _pinmu_mat(slot):
    names = {"front": "pinmu_front.png", "back": "pinmu_sideBplayer.png",
             "wallL": "pinmu_back.png", "wallR": "pinmu_sideCsell.png",
             "slopeF": "pinmu_roof_slopeF.png", "slopeB": "pinmu_roof_slopeB.png",
             "endL": "pinmu_roof_endL.png", "endR": "pinmu_roof_endR.png"}
    mn = f"Mat_PinMu_{slot}"
    m = bpy.data.materials.get(mn)
    if m is None:
        m = bpy.data.materials.new(mn)
        m.use_nodes = True
        img = bpy.data.images.load(os.path.join(BASE_DIR, "assets/textures/fresh", names[slot]))
        img.colorspace_settings.name = "sRGB"
        t = m.node_tree.nodes.new("ShaderNodeTexImage")
        t.image = img
        t.extension = 'EXTEND'
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Roughness"].default_value = 0.38
        m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    return m

def build_pinmu(sku, loc, rot_z=0.0, w=0.068, d=0.068, h_body=0.106, h_ridge=0.037):
    """刀版正解: 脊沿X(A端↔C端), D顶前坡/ B顶后坡, A顶左山墙(-X)/C顶右山墙(+X);
    墙: -Y=D正面, +Y=B球员(后墙), -X=A条码墙, +X=C卖点墙"""
    bm = bmesh.new()
    x0, x1 = -w / 2, w / 2
    y0, y1 = -d / 2, d / 2
    z0, z1 = 0.0, h_body
    _rh = h_ridge * random.uniform(0.92, 1.08)
    z2 = h_body + _rh
    V = bm.verts.new
    vs = [V(p) for p in [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),   # 底 0-3
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),   # 肩 4-7
        (x0, 0, z2), (x1, 0, z2),                                  # 脊 8-9 (沿X)
    ]]
    face_keys = ["bottom", "front", "back", "wallL", "wallR", "slopeF", "slopeB", "endL", "endR"]
    bm.faces.new((vs[0], vs[3], vs[2], vs[1]))   # bottom
    bm.faces.new((vs[0], vs[1], vs[5], vs[4]))   # front wall (-Y)
    bm.faces.new((vs[2], vs[3], vs[7], vs[6]))   # back wall (+Y)
    bm.faces.new((vs[3], vs[0], vs[4], vs[7]))   # wallL (-X)
    bm.faces.new((vs[1], vs[2], vs[6], vs[5]))   # wallR (+X)
    bm.faces.new((vs[4], vs[5], vs[9], vs[8]))   # slopeF (-Y 坡, 面朝前上)
    bm.faces.new((vs[6], vs[7], vs[8], vs[9]))   # slopeB (+Y 坡)
    bm.faces.new((vs[4], vs[8], vs[7]))          # endL (-X 山墙三角)
    bm.faces.new((vs[5], vs[6], vs[9]))          # endR (+X 山墙三角)
    mesh = bpy.data.meshes.new(f"PinMu_{sku}")
    bm.to_mesh(mesh)
    bm.free()
    ob = bpy.data.objects.new(f"PinMu_{sku}", mesh)
    ob.location = loc
    ob.rotation_euler = (math.radians(random.uniform(-1.2, 1.2)), 0, math.radians(rot_z))
    ob.scale = (1 + random.uniform(-0.02, 0.02), 1 + random.uniform(-0.02, 0.02),
                1 + random.uniform(-0.012, 0.02))
    bpy.context.collection.objects.link(ob)

    # UV: 墙 v=z/z1; 侧墙 u=y/d; 坡 v=(z-z1)/(z2-z1)(坡长投影); 端三角 u=y/d v=(z-z1)/(z2-z1)
    uvl = ob.data.uv_layers.new(name="UVMap")
    mw = ob.matrix_world
    for pi, poly in enumerate(ob.data.polygons):
        key = face_keys[pi] if pi < len(face_keys) else "bottom"
        for li in poly.loop_indices:
            co = mw @ ob.data.vertices[ob.data.loops[li].vertex_index].co
            if key == "front" or key == "back":
                uvl.data[li].uv = (0.01 + 0.98 * (co.x - x0) / w, 0.01 + 0.98 * min((co.z - z0) / z1, 0.99))
            elif key == "wallL" or key == "wallR":
                uvl.data[li].uv = (0.01 + 0.98 * (co.y - y0) / d, 0.01 + 0.98 * min((co.z - z0) / z1, 0.99))
            elif key == "slopeF" or key == "slopeB":
                uvl.data[li].uv = (0.01 + 0.98 * (co.x - x0) / w,
                                   0.01 + 0.98 * min((co.z - z1) / max(z2 - z1, 1e-6), 0.99))
            elif key == "endL" or key == "endR":
                uvl.data[li].uv = (0.01 + 0.98 * (co.y - y0) / d,
                                   0.01 + 0.98 * min((co.z - z1) / max(z2 - z1, 1e-6), 0.99))
            else:
                uvl.data[li].uv = (0.004, 0.5)

    _white = bpy.data.materials.get("Mat_PinMu_White")
    if _white is None:
        _white = bpy.data.materials.new("Mat_PinMu_White")
        _white.use_nodes = True
        _b = _white.node_tree.nodes["Principled BSDF"]
        _b.inputs["Base Color"].default_value = (0.965, 0.958, 0.945, 1)
        _b.inputs["Roughness"].default_value = 0.42
    slots = [_white, _pinmu_mat("front"), _pinmu_mat("back"), _pinmu_mat("wallL"),
             _pinmu_mat("wallR"), _pinmu_mat("slopeF"), _pinmu_mat("slopeB"),
             _pinmu_mat("endL"), _pinmu_mat("endR")]
    slot_of = {"bottom": 0, "front": 1, "back": 2, "wallL": 3, "wallR": 4,
               "slopeF": 5, "slopeB": 6, "endL": 7, "endR": 8}
    for m in slots:
        ob.data.materials.append(m)
    for pi, poly in enumerate(ob.data.polygons):
        poly.material_index = slot_of.get(face_keys[pi] if pi < len(face_keys) else "bottom", 0)
    return ob


# ---------------- 行定义 (品牌色块分区, 参照: 鲜奶区) ----------------
# 顶层: 屋顶包 — 真像素印刷 (GPT盲评round1: 包装真像素第一杠杆) 三品牌带
# v11: 每 SKU 多贴图变体 (亮度/油墨微差) — 打散像素级克隆瓦片 (盲2 TOP1)
_TOP_ORG = ["assets/textures/fresh/gable_real_organic.png",
            "assets/textures/fresh/gable_real_organic_v1.png",
            "assets/textures/fresh/gable_real_organic_v2.png"]
_TOP_CLS = ["assets/textures/fresh/gable_real_classic.png",
            "assets/textures/fresh/gable_real_classic_v1.png",
            "assets/textures/fresh/gable_real_classic_v2.png"]
_TOP_LF = ["assets/textures/fresh/gable_real_lowfat.png",
           "assets/textures/fresh/gable_real_lowfat_v1.png",
           "assets/textures/fresh/gable_real_lowfat_v2.png"]
_TOP_SKIM = ["assets/textures/fresh/gable_real_skim.png"]
_TOP_JERSEY = ["assets/textures/fresh/gable_real_jersey.png"]
# R10: 10+SKU — 顶层 5 SKU 色带 (有机/经典/低脂/脱脂/娟姗), 24 包 × 0.036m = 0.864m ≤ 0.86 柜宽
_CUP_RED = ["assets/textures/fresh/cup_red.png"]
_CUP_BLUE = ["assets/textures/fresh/cup_blue.png"]
_CUP_GOLD = ["assets/textures/fresh/cup_gold.png"]
_CUP_GREEN = ["assets/textures/fresh/cup_green.png"]
_CUP_PURPLE = ["assets/textures/fresh/cup_purple.png"]
# R14: 顶排 = 16 酸奶杯五口味 (真图顶排形态), 杯径52mm pitch → 16×0.052=0.832
ROW_TOP = ([("cup_red", _CUP_RED)] * 4 + [("cup_blue", _CUP_BLUE)] * 4 +
           [("cup_gold", _CUP_GOLD)] * 3 + [("cup_green", _CUP_GREEN)] * 3 +
           [("cup_purple", _CUP_PURPLE)] * 2)
# 中层: 21 白瓶纸标 (R13: 用户令每排20+瓶; 真图细瓶40mm径) — 蓝/金/红/绿盖四SKU
_MILK = ["assets/textures/fresh/demo_milk_bottle.png", "assets/textures/fresh/demo_milk_bottle_v1.png",
         "assets/textures/fresh/demo_milk_bottle_v2.png", "assets/textures/fresh/demo_milk_bottle_v3.png"]
_WBLUE = ["assets/textures/fresh/wlabel_blue.png"]
_WGOLD = ["assets/textures/fresh/wlabel_gold.png"]
_WRED = ["assets/textures/fresh/wlabel_red.png"]
_WGREEN = ["assets/textures/fresh/wlabel_green.png"]
ROW_MID = ([("wblue", _WBLUE)] * 6 + [("wgold", _WGOLD)] * 6 +
           [("wred", _WRED)] * 5 + [("wgreen", _WGREEN)] * 4)   # 21瓶×0.041=0.861 满排
# 底层: 20 砖 — 酸奶原味/金装 + 经典cny金红
ROW_BOT = [("demo_yogurt_original", None)] * 8 + [("demo_yogurt_gold", None)] * 6 + [("demo_cny", None)] * 6


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    m01.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.view_settings.exposure = -0.35   # v9: 回 C 基准 (撤 glare 后无需 -0.5 补偿)
    scene.render.resolution_x = 2560
    scene.render.resolution_y = 1536
    scene.render.film_transparent = False

    world = bpy.data.worlds.new("CaseWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.82, 0.85, 0.88, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.04
    scene.world = world

    steel = (0.88, 0.89, 0.91)
    brand_green = (0.02, 0.40, 0.25)
    _box = m26._box
    _uv = m26._uv_full_face

    # 背墙(渐变暗化即随 DOF 融) + 地砖地板
    _box("BackWall", 3.0, 0.02, 2.0, (0, 0.32, 1.0), (0.58, 0.59, 0.60), rough=0.9)
    _floor = _box("Floor", 3.0, 3.0, 0.01, (0, 0, -0.070), (0.52, 0.52, 0.53), rough=0.55)
    floor_mat = bpy.data.materials.new("FloorTiles")
    floor_mat.use_nodes = True
    _fn = floor_mat.node_tree
    _ft = _fn.nodes.new("ShaderNodeTexImage")
    _ft.image = bpy.data.images.load(os.path.join(TEX, "floor_tiles.png"))
    _fn.links.new(_ft.outputs["Color"], _fn.nodes["Principled BSDF"].inputs["Base Color"])
    # R12: 釉面砖微反射 (真卖场瓷砖映出柜灯与商品) — 光泽面必须有内容可反
    _fn.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.28
    if "Coat Weight" in _fn.nodes["Principled BSDF"].inputs:
        _fn.nodes["Principled BSDF"].inputs["Coat Weight"].default_value = 0.25
    _floor.data.materials.clear()
    _floor.data.materials.append(floor_mat)
    _uv(_floor)

    # R12: 反射环境 — 顶灯光带 (画面外上方, 供瓶身高光/层板金属缘/地面反射取样)
    # 真卖场顶棚是长条灯盘: 暖白主带 + 冷白副带 (与柜内冷白形成色温差)
    for _spec in (((0.4, 0.35, 2.55), 3.4, 1.6, 3.0, (1.0, 0.97, 0.92)),
                  ((-1.1, 0.30, 2.45), 2.6, 1.2, 1.6, (0.90, 0.94, 1.0))):
        (_cx, _cy, _cz), _sw, _sd, _se, _sc = _spec
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(_cx, _cy, _cz), rotation=(0, 0, 0))
        _ceil = bpy.context.active_object
        _ceil.name = f"CeilBank_{_cx}"
        _ceil.scale = (_sw, _sd, 1)
        _ceil.rotation_euler = (math.pi, 0, 0)   # 面朝下
        _cmat = bpy.data.materials.new(f"CeilMat_{_cx}")
        _cmat.use_nodes = True
        _cn = _cmat.node_tree
        for _n in list(_cn.nodes):
            if _n.type != 'OUTPUT_MATERIAL':
                _cn.nodes.remove(_n)
        _ce = _cn.nodes.new("ShaderNodeEmission")
        _ce.inputs["Color"].default_value = (*_sc, 1)
        _ce.inputs["Strength"].default_value = _se
        _cn.links.new(_ce.outputs[0], _cn.nodes["Material Output"].inputs["Surface"])
        _ceil.data.materials.append(_cmat)

    # 柜体
    _box("CaseBack", CASE_W, 0.006, CASE_H, (0, 0.085, CASE_H / 2), (0.78, 0.79, 0.80), rough=0.6)
    for sx in (-1, 1):
        _box(f"CasePillar_{sx}", 0.020, CASE_D + 0.012, CASE_H,
             (sx * (CASE_W / 2 + 0.010), 0.030, CASE_H / 2), steel, rough=0.35)
        _box(f"CaseAccent_{sx}", 0.006, 0.006, CASE_H,
             (sx * (CASE_W / 2 - 0.002), 0.030 - CASE_D / 2 - 0.002, CASE_H / 2), brand_green, rough=0.4)
    _box("CaseTop", CASE_W + 0.044, CASE_D + 0.014, 0.014, (0, 0.030, CASE_H + 0.007), steel, rough=0.4)
    _box("CasePlinth", CASE_W + 0.044, CASE_D + 0.014, 0.060, (0, 0.030, -0.034), (0.42, 0.43, 0.44), rough=0.6)

    # 层板 + 价签(三套分层) + LED 灯管
    def _price_mat(tex, name):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        n = m.node_tree
        tt = n.nodes.new("ShaderNodeTexImage")
        tt.image = bpy.data.images.load(os.path.join(TEX, tex))
        n.links.new(tt.outputs["Color"], n.nodes["Principled BSDF"].inputs["Base Color"])
        return m
    PRICE_MATS = [_price_mat("shelf_price_strip_white_t1.png", "PriceTop"),
                  _price_mat("shelf_price_strip_white_t2.png", "PriceMid"),
                  _price_mat("shelf_price_strip_white_t3.png", "PriceBot")]   # R13b: 三排独立价 (单瓶/瓶/箱)
    led_mat = bpy.data.materials.new("LEDStrip")
    led_mat.use_nodes = True
    _ln = led_mat.node_tree
    _em = _ln.nodes.new("ShaderNodeEmission")
    _em.inputs["Color"].default_value = (0.88, 0.93, 1.0, 1)
    _em.inputs["Strength"].default_value = 13.0   # R9: 峰值压制 (P0-3 过曝)
    _ln.links.new(_em.outputs[0], _ln.nodes["Material Output"].inputs["Surface"])
    for zi, z in enumerate(ROW_Z):
        _box(f"Shelf_{zi}", CASE_W, CASE_D, SHELF_T, (0, 0.030, z - SHELF_T / 2), steel, rough=0.30)
        rail = _box(f"Rail_{zi}", CASE_W, 0.006, 0.028, (0, 0.030 - CASE_D / 2 + 0.004, z - 0.005),
                    (0.95, 0.95, 0.95), rough=0.25)   # R15: 立面 z-0.019..z+0.009, 商品区让空
        rail.data.materials.clear()
        rail.data.materials.append(PRICE_MATS[zi])
        _uv(rail)
    for z_led in (ROW_Z[0], ROW_Z[1]):
        bpy.ops.mesh.primitive_cylinder_add(vertices=24, radius=0.005, depth=CASE_W - 0.05,
                                            location=(0, 0.030 - CASE_D / 2 - 0.008, z_led - SHELF_T - 0.008))
        led = bpy.context.active_object
        led.name = f"LEDTube_{z_led}"
        led.rotation_euler = (0, math.radians(90), 0)
        led.data.materials.append(led_mat)

    # POP 顶牌 + 出风口/回风格栅
    pop_mat = bpy.data.materials.new("PopHeader")
    pop_mat.use_nodes = True
    _q = pop_mat.node_tree
    _pt2 = _q.nodes.new("ShaderNodeTexImage")
    _pt2.image = bpy.data.images.load(os.path.join(TEX, "shelf_pop_header.png"))
    _q.links.new(_pt2.outputs["Color"], _q.nodes["Principled BSDF"].inputs["Base Color"])
    popb = _box("PopHeader", 0.60, 0.010, 0.120, (0, 0.082, CASE_H + 0.074), (1, 1, 1))
    popb.data.materials.clear()
    popb.data.materials.append(pop_mat)
    _uv(popb)
    grille_mat = bpy.data.materials.new("Grille")
    grille_mat.use_nodes = True
    _gn = grille_mat.node_tree
    _gt = _gn.nodes.new("ShaderNodeTexImage")
    _gt.image = bpy.data.images.load(os.path.join(TEX, "case_grille.png"))
    _gn.links.new(_gt.outputs["Color"], _gn.nodes["Principled BSDF"].inputs["Base Color"])
    top_g = _box("AirCurtainTop", CASE_W, 0.014, 0.036, (0, -0.024, 0.528), (0.5, 0.5, 0.5), rough=0.5)
    top_g.data.materials.clear(); top_g.data.materials.append(grille_mat); _uv(top_g)
    ret_g = _box("ReturnGrille", CASE_W + 0.02, 0.030, 0.056, (0, 0.030 - CASE_D / 2 - 0.004, -0.028), (0.5, 0.5, 0.5), rough=0.5)
    ret_g.rotation_euler = (math.radians(-18), 0, 0)
    ret_g.data.materials.clear(); ret_g.data.materials.append(grille_mat); _uv(ret_g)

    # 邻柜延续 (两侧半高截面, DOF 下成环境纵深)
    # R8: 邻柜点亮 — 开式壳体(背板+顶盖+薄侧板, 不挡内部) + 内背板自发光 + LED 管光 + 虚拟排面
    for sx in (-1, 1):
        nx = sx * (CASE_W / 2 + 0.22)
        # 背板 (深灰, 位于排面之后)
        _box(f"NeighborCase_{sx}", 0.30, 0.012, CASE_H * 0.8,
             (nx, 0.030 + CASE_D / 2, CASE_H * 0.4), (0.62, 0.63, 0.65), rough=0.42)
        # 顶盖 + 前立柱
        _box(f"NeighborTop_{sx}", 0.30, CASE_D + 0.012, 0.012,
             (nx, 0.030, CASE_H * 0.8 + 0.006), steel, rough=0.4)
        for px in (-0.15, 0.15):
            _box(f"NeighborPillar_{sx}_{px}", 0.012, 0.02, CASE_H * 0.8,
                 (nx + px, 0.030 - CASE_D / 2 + 0.01, CASE_H * 0.4), steel, rough=0.4)
        # 内背板自发光 (冷白, 弱)
        bgm = bpy.data.materials.new(f"NeighborGlow_{sx}")
        bgm.use_nodes = True
        _bn = bgm.node_tree
        for _n in list(_bn.nodes):
            if _n.type != 'OUTPUT_MATERIAL':
                _bn.nodes.remove(_n)
        _be = _bn.nodes.new("ShaderNodeEmission")
        _be.inputs["Color"].default_value = (0.82, 0.88, 0.96, 1)
        _be.inputs["Strength"].default_value = 3.2
        _bn.links.new(_be.outputs[0], _bn.nodes["Material Output"].inputs["Surface"])
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(nx, 0.030 + CASE_D / 2 - 0.010, CASE_H * 0.42))
        _bg = bpy.context.active_object
        _bg.name = f"NeighborBack_{sx}"
        _bg.scale = (0.28, 0.004, CASE_H * 0.72)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        _bg.data.materials.append(bgm)
        for k in range(2):
            _box(f"NeighborShelf_{sx}_{k}", 0.30, CASE_D, SHELF_T,
                 (nx, 0.030, 0.10 + k * 0.14), (0.85, 0.86, 0.88), rough=0.35)
            # LED 管 (与主柜同款)
            bpy.ops.mesh.primitive_cylinder_add(vertices=16, radius=0.004, depth=0.26,
                                                location=(nx, 0.030 - CASE_D / 2 - 0.006, 0.10 + k * 0.14 - 0.008))
            _nl = bpy.context.active_object
            _nl.name = f"NeighborLED_{sx}_{k}"
            _nl.rotation_euler = (0, math.radians(90), 0)
            _nl.data.materials.append(led_mat)
            # 虚拟排面: 每层 7-8 个随机色块 (饱和真实包装色, 模糊由 DOF 承担)
            _row_seed = random.Random(100 + sx * 7 + k)
            _pack_cols = [(0.90, 0.92, 0.90), (0.16, 0.38, 0.62), (0.12, 0.40, 0.22),
                          (0.85, 0.72, 0.35), (0.92, 0.93, 0.95), (0.20, 0.25, 0.55),
                          (0.75, 0.30, 0.25)]
            for pi in range(_row_seed.randint(7, 8)):
                _pc = _pack_cols[_row_seed.randrange(len(_pack_cols))]
                _pw = 0.038
                _px = nx - 0.135 + pi * 0.040 + _row_seed.uniform(-0.004, 0.004)
                _ph = _row_seed.uniform(0.095, 0.115)
                _box(f"NeighborPack_{sx}_{k}_{pi}", _pw, 0.052, _ph,
                     (_px, 0.030, 0.10 + k * 0.14 + SHELF_T / 2 + _ph / 2), _pc, rough=0.45)

    # 陈列 (单排面零间隙 + 双排纵深 + 理货抖动; 屋顶包/PET 瓶/砖)
    # R16: 顶排三分区 (真图: 左酸奶杯6 / 中金盖白瓶5 / 右品慕458屋顶包4)
    rng = random.Random(11)
    _segs = [("cup", ROW_TOP[:6], 0.052),
             ("bottle", [("wgold", _WGOLD)] * 5, 0.041),
             ("pinmu", [("pinmu", None)] * 4, 0.072)]
    _total_w = sum(sp * len(items) for _, items, sp in _segs)
    _xc = -_total_w / 2
    for kind, items, sp in _segs:
        for j, (sku, texs) in enumerate(items):
            x = _xc + sp * (j + 0.5)
            tex = os.path.join(BASE_DIR, texs[rng.randrange(len(texs))]) if texs else None
            for depth in range(2):
                xoff = (sp * 0.5 if depth == 1 else 0.0) + rng.uniform(-0.004, 0.004)
                yv = 0.016 + rng.uniform(-0.003, 0.003) + depth * 0.038
                rot = rng.uniform(-2.5, 2.5)
                if kind == "cup":
                    build_cup(sku, tex, (x + xoff, yv, ROW_Z[0]), rot)
                elif kind == "bottle":
                    build_pet_bottle(sku, tex, (x + xoff, yv, ROW_Z[0]), rot)
                else:
                    build_pinmu(sku, (x + xoff, yv, ROW_Z[0]), rot)
        _xc += sp * len(items)

    rng = random.Random(11)
    for zi, row in enumerate((ROW_TOP, ROW_MID, ROW_BOT)):
        if zi == 0:
            continue   # R16: 顶排已由三分区块构建
        z = ROW_Z[zi]
        if zi == 0:
            pw, pitch_extra = 0.050, 0.002   # R14: 杯径 50mm
        elif zi == 1:
            pw, pitch_extra = 0.040, 0.001   # R13: 瓶径 40mm
        else:
            pw, pitch_extra = 0.040, 0.002
        spacing = pw + pitch_extra
        n = len(row)
        x0 = -spacing * n / 2
        skip = {(1, 6)} if zi == 1 else set()   # R5: 中层一个真实空缺位 (露后排)
        for i, item in enumerate(row):
            sku, texs = item
            tex = os.path.join(BASE_DIR, texs[rng.randrange(len(texs))]) if texs else None
            x = x0 + spacing * (i + 0.5)
            if (zi, i) in skip:
                continue
            for depth in range(2):
                xoff = (spacing * 0.5 if depth == 1 else 0.0) + rng.uniform(-0.004, 0.004)
                yv = 0.016 + rng.uniform(-0.003, 0.003) + depth * 0.038
                rot = rng.uniform(-2.5, 2.5)
                if i == 3 and depth == 0:
                    rot = 3.2   # 理货痕: 一盒歪 3.2° (v15 纪律)
                if i == 11 and depth == 0:
                    yv += 0.006   # 一盒未推齐
                lean = math.radians(rng.uniform(-1.6, 1.6)) if (zi == 1 and depth == 0) else 0.0
                if zi == 0:
                    build_cup(sku, tex, (x + xoff, yv, z), rot)
                elif zi == 1:
                    ob = build_pet_bottle(sku, tex, (x + xoff, yv, z), rot)
                    # R5: 可见倾斜 (绕Y轴 lean → 盖位移约±2.5mm, silhouette 破直线)
                    if lean and ob:
                        ob.rotation_euler.y = lean
                else:
                    if sku == "demo_cny" and depth == 0:
                        _box(f"Riser_{i}", pw, 0.052, 0.029,
                             (x + xoff, 0.030, z + 0.0145), (0.80, 0.81, 0.83), rough=0.35)
                        m01.build_carton_twin(sku, loc=(x + xoff, yv, z + 0.029), rot=(0, 0, math.radians(rot)), dims=BOX)
                    else:
                        m01.build_carton_twin(sku, loc=(x + xoff, yv, z), rot=(0, 0, math.radians(rot)), dims=BOX)
        # 理货痕迹: 已由 row 内 rot/offset 抖动体现 (v15 纪律)
    bpy.context.view_layer.update()

    # 贴图去重 (150+ 盒)
    _seen = {}
    for _img in list(bpy.data.images):
        if _img.filepath:
            _fp = os.path.abspath(bpy.path.abspath(_img.filepath))
            if _fp in _seen:
                _img.user_remap(_seen[_fp])
                bpy.data.images.remove(_img)
            else:
                _seen[_fp] = _img

    # R4 光照重构: 杀平光大面 fill (真实感 flatness 主因), 改层板局部 LED 池光 + 收紧主光
    # → 层板下亮/柜内顶部暗的光衰减 + 商品间互投影 + 接触阴影
    aim = bpy.data.objects.new("Aim", None)
    aim.location = (0.0, 0.0, 0.20)
    bpy.context.collection.objects.link(aim)
    for pos, size, energy, color in [
        ((0.75, -1.05, 0.62), 0.55, 11.0, (0.93, 0.96, 1.0)),   # 主光收小变定向
        ((-0.55, -0.75, 0.35), 0.7, 1.6, (0.94, 0.96, 1.0)),    # 左弱补 (原2.2m/4W → 0.7m/1.6W)
        ((0.0, -0.10, 1.60), 2.8, 1.5, (0.95, 0.97, 1.0)),      # 顶环境压平 (R5: 再降)
    ]:
        bpy.ops.object.light_add(type="AREA", location=pos)
        L = bpy.context.active_object
        L.data.size = size
        L.data.energy = energy
        L.data.color = color
        L.constraints.new("TRACK_TO").target = aim
    # 层板 LED 池光: 每层板前沿下方窄条 area, 向下打 (真实风幕柜 LED 特征)
    # R5: 更近更窄更强 → 接触阴影收紧变深 (瓶底/盒底暗线)
    for z_led in (ROW_Z[0] + 0.045, ROW_Z[1] + 0.045):
        bpy.ops.object.light_add(type="AREA", location=(0.0, 0.045, z_led))
        LL = bpy.context.active_object
        LL.name = f"LEDPool_{z_led}"
        LL.data.shape = 'RECTANGLE'
        LL.data.size = CASE_W * 0.9
        LL.data.size_y = 0.04
        LL.data.energy = 5.0
        LL.data.color = (0.90, 0.95, 1.0)
        LL.rotation_euler = (math.radians(-15), 0, 0)

    # R6: 柜内冷雾 (体积散射, 密度极低): LED 池光光路可见 + 冷感深度
    vm = bpy.data.materials.new("ColdMist")
    vm.use_nodes = True
    _vnt = vm.node_tree
    for _n in list(_vnt.nodes):
        if _n.type != 'OUTPUT_MATERIAL':
            _vnt.nodes.remove(_n)
    _vs = _vnt.nodes.new("ShaderNodeVolumeScatter")
    _vs.inputs["Color"].default_value = (0.85, 0.90, 1.0, 1)
    _vs.inputs["Density"].default_value = 0.05
    _vs.inputs["Anisotropy"].default_value = 0.3
    _vnt.links.new(_vs.outputs["Volume"], _vnt.nodes["Material Output"].inputs["Volume"])
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0.02, CASE_H / 2))
    _mist = bpy.context.active_object
    _mist.name = "CaseMist"
    _mist.scale = (CASE_W, CASE_D - 0.01, CASE_H)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    _mist.display_type = 'WIRE'
    _mist.visible_shadow = False
    _mist.data.materials.append(vm)

    # 相机 + DOF — R12: 人位机位 (过道偏轴站位/俯视/透视收敛/微滚转), 不再是目录正轴
    bpy.ops.object.camera_add(location=(0.30, -1.38, 0.50))
    cam = bpy.context.active_object
    scene.camera = cam
    cam.data.lens = 40
    cam.rotation_euler = (Vector((-0.06, 0.0, 0.22)) - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.rotation_euler.rotate_axis("Z", math.radians(0.7))   # 手持微滚转 (绕视线轴近似)
    cam.data.dof.use_dof = True
    cam.data.dof.aperture_fstop = 2.2
    cam.data.dof.focus_distance = 1.45

    # 后处理: 轻对比 + 镜头畸变 (Blender 5.2: scene.compositing_node_group + 组输出 socket; Vignette/Mix 节点已移除)
    scene.use_nodes = True
    ng = bpy.data.node_groups.new("CompChain", 'CompositorNodeTree')
    scene.compositing_node_group = ng
    ng.interface.new_socket("Image", in_out='OUTPUT', socket_type='NodeSocketColor')
    rl = ng.nodes.new("CompositorNodeRLayers")
    bc = ng.nodes.new("CompositorNodeBrightContrast")
    bc.inputs["Contrast"].default_value = 0.06
    dist = ng.nodes.new("CompositorNodeLensdist")
    dist.inputs["Distortion"].default_value = 0.012
    gout = ng.nodes.new("NodeGroupOutput")
    ng.links.new(rl.outputs["Image"], bc.inputs["Image"])
    ng.links.new(bc.outputs["Image"], dist.inputs["Image"])
    ng.links.new(dist.outputs["Image"], gout.inputs["Image"])

    outp = os.path.join(OUT_DIR, f"{args.out}.png")
    scene.render.filepath = outp
    bpy.ops.render.render(write_still=True)
    # R12b: 手机 CMOS 噪声 (PIL 后置): 暗部加权亮度噪 + 轻色噪 — 纯平滑暗部=离线渲染暴露源
    import numpy as _np
    from PIL import Image as _Image
    _im = _Image.open(outp).convert("RGB")
    _a = _np.asarray(_im).astype(_np.float32)
    _lum = _a.mean(axis=2, keepdims=True) / 255.0
    _w = (1.0 - 0.65 * _lum)   # 暗部噪声权重高 (CMOS 特征)
    _rngn = _np.random.default_rng(20261116)
    _a += _rngn.normal(0, 1.0, _a.shape) * _w          # 轻色噪
    _a += _rngn.normal(0, 2.0, (_a.shape[0], _a.shape[1], 1)) * _w   # 亮度噪
    _Image.fromarray(_np.clip(_a, 0, 255).astype(_np.uint8)).save(outp)
    print(f"[FRESH] 冷柜鲜奶区已保存: {outp}")


if __name__ == "__main__":
    main()
