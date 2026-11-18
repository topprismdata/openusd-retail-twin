#!/usr/bin/env python3
"""v100 品牌方纯牛奶1L gable-top 砖盒几何 (Tetra Brik Aseptic 1000 Square 形态).
主体 75x75x165mm + gable 屋脊顶 35mm + 白色旋盖 (gable 斜面). 总高 ~200mm.
UV 同经典 atlas 契约 (FRONT/BACK/SIDE/TOP/BOTTOM). 旋盖可开 (倒奶从盖口)."""
import bpy
import math
import mathutils as mu
import os   # v107 必须模块级: 函数内 import os 会让 os 成为局部名,
            # 使更早的 PAPER_DEFORM 读取抛 UnboundLocalError(实测已崩, 会打坏冻结KV分支)

# 尺寸 (米): 1L 砖盒
BW, BD, BH = 0.075, 0.075, 0.165   # 主体宽/深/高
GH = 0.035                          # gable 顶高
TOTAL_H = BH + GH                   # ~0.200
CAP_R, CAP_H = 0.014, 0.010         # 旋盖半径/高

# UV atlas 契约 (归一化, v=y-up, 同 01_comfy)
UV = {
    "FRONT":  (60/2048, 1-1944/2048, 940/2048, 1-104/2048),
    "BACK":   (1112/2048, 1-1944/2048, 1992/2048, 1-104/2048),
    "SIDE_L": (972/2048, 1-1944/2048, 1010/2048, 1-104/2048),
    "SIDE_R": (1042/2048, 1-1944/2048, 1080/2048, 1-104/2048),
    "TOP":    (60/2048, 1-72/2048, 940/2048, 1-8/2048),
    "BOTTOM": (1112/2048, 1-72/2048, 1992/2048, 1-8/2048),
}


def _assign_uv(obj):
    """按面法线赋 UV (主体±Y/±X/±Z; gable 斜面归 TOP)."""
    mesh = obj.data
    uvl = mesh.uv_layers[0] if len(mesh.uv_layers) else mesh.uv_layers.new(name="atlas")
    for poly in mesh.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 1:
            region = UV["FRONT"] if n.y < 0 else UV["BACK"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vz = mesh.vertices[vi].co.x, mesh.vertices[vi].co.z
                uvl.data[li].uv = (region[0] + (vx/BW + 0.5)*(region[2]-region[0]),
                                   region[1] + (vz/BH)*(region[3]-region[1]))
        elif ax == 0:
            region = UV["SIDE_L"] if n.x < 0 else UV["SIDE_R"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vy, vz = mesh.vertices[vi].co.y, mesh.vertices[vi].co.z
                uvl.data[li].uv = (region[0] + (vy/BD + 0.5)*(region[2]-region[0]),
                                   region[1] + (vz/BH)*(region[3]-region[1]))
        else:
            region = UV["TOP"] if n.z > 0 else UV["BOTTOM"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vy = mesh.vertices[vi].co.x, mesh.vertices[vi].co.y
                uvl.data[li].uv = (region[0] + (vx/BW + 0.5)*(region[2]-region[0]),
                                   region[1] + (vy/BD + 0.5)*(region[3]-region[1]))


def build_carton_1l(loc=(0,0,0), cap_open=True):
    """返回 (carton_obj, cap_obj). carton origin=底面中心."""
    # ---- 主体 (cube, origin 底面中心) ----
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0,0,BH/2))
    body = bpy.context.active_object
    body.name = "Carton1L_Body"
    body.scale = (BW, BD, BH)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    body.data.transform(mu.Matrix.Translation((0,0,BH/2)))  # z∈[0,BH]
    body.location = (0,0,0)

    # ---- gable 屋脊顶 (手工 mesh: 两端三角+两斜面) ----
    # 顶点: 主体顶面四角 + 屋脊线两端
    z0 = BH
    z1 = BH + GH
    hw, hd = BW/2, BD/2
    # 屋脊沿 X 方向 (前后斜面朝向 ±Y)
    verts = [
        (-hw, -hd, z0), (hw, -hd, z0), (hw, hd, z0), (-hw, hd, z0),  # 0-3 顶面四角
        (-hw, 0, z1), (hw, 0, z1),                                    # 4-5 屋脊线
    ]
    faces = [
        (0, 1, 5, 4),   # 前斜面 (-Y)
        (2, 3, 4, 5),   # 后斜面 (+Y)
        (0, 4, 3),      # 左三角 (-X)
        (1, 2, 5),      # 右三角 (+X)
    ]
    gme = bpy.data.meshes.new("Carton1L_Gable")
    gme.from_pydata(verts, [], faces)
    gme.update(); gme.validate()
    gable = bpy.data.objects.new("Carton1L_Gable", gme)
    bpy.context.collection.objects.link(gable)
    for p in gable.data.polygons:
        p.use_smooth = False

    # ---- 合并主体+gable ----
    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True); gable.select_set(True)
    bpy.context.view_layer.objects.active = body
    bpy.ops.object.join()
    carton = bpy.context.active_object
    carton.name = "Carton1L"
    # 微圆角
    bev = carton.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.0012; bev.segments = 2; bev.limit_method = 'ANGLE'; bev.angle_limit = math.radians(40)
    bpy.ops.object.modifier_apply(modifier="Bevel")
    # v100 纸面微形变 (E40配方: 消刚性CG感, 须先subdivide n-gon无内部顶点)
    import bmesh
    _bm = bmesh.new()
    _bm.from_mesh(carton.data)
    bmesh.ops.subdivide_edges(_bm, edges=_bm.edges[:], cuts=8, use_grid_fill=True)
    _bm.to_mesh(carton.data)
    _bm.free()
    import mathutils as _pw
    _pn = _pw.noise
    # v118 跨进程非确定性根因: mathutils.noise **无法设种**(5.2 已无 noise.seed 属性),
    # 实测同配置两独立进程 carton zmax 0.19972886 vs 0.19979805(差0.07mm)、sha 不同;
    # 经 camera.focus_distance(0.9783→0.9844, 漂6mm)放大为整图 mean 0.83/255 max244。
    # 后果: 本分支此前所有"单变量"对照都带此漂移。PAPER_NOISE_DET=1 改用确定性值噪声
    # (哈希格点+smoothstep三线性插值, 同为低频平滑场, 不改纸面微波的美术方向);
    # 默认0=沿用 mathutils.noise → 冻结KV分支逐位不变。
    def _det_nv(p):
        import hashlib as _hl
        import struct as _st

        def _h(i, j, k, s):
            d = _hl.sha256(_st.pack("<4i", i, j, k, s)).digest()[:4]
            return (_st.unpack("<I", d)[0] / 4294967295.0) * 2.0 - 1.0
        ix, iy, iz = math.floor(p.x), math.floor(p.y), math.floor(p.z)
        fx, fy, fz = p.x - ix, p.y - iy, p.z - iz
        sx, sy, sz = [f * f * (3.0 - 2.0 * f) for f in (fx, fy, fz)]
        out = []
        for s in (11, 23, 37):          # 三分量独立盐
            a = _h(ix, iy, iz, s) + sx * (_h(ix + 1, iy, iz, s) - _h(ix, iy, iz, s))
            b = _h(ix, iy + 1, iz, s) + sx * (_h(ix + 1, iy + 1, iz, s) - _h(ix, iy + 1, iz, s))
            c = _h(ix, iy, iz + 1, s) + sx * (_h(ix + 1, iy, iz + 1, s) - _h(ix, iy, iz + 1, s))
            d = _h(ix, iy + 1, iz + 1, s) + sx * (_h(ix + 1, iy + 1, iz + 1, s) - _h(ix, iy + 1, iz + 1, s))
            ab = a + sy * (b - a)
            cd = c + sy * (d - c)
            out.append(ab + sz * (cd - ab))
        return _pw.Vector(out)
    _nv = _det_nv if os.environ.get("PAPER_NOISE_DET", "0") == "1" else _pn.noise_vector
    _pme = carton.data
    _bb_z = [v.co.z for v in _pme.vertices]
    _zmin, _zmax = min(_bb_z), max(_bb_z)
    for _pv2 in _pme.vertices:
        _wp = _pv2.co
        _n1 = _nv(_wp * 18.0)
        _n2 = _nv(_wp * 45.0 + _pw.Vector((7.3, 2.1, 4.4)))
        _n3 = _nv(_wp * 120.0 + _pw.Vector((3.1, 8.7, 1.9)))
        # v107 形变幅度 env 门控(默认1.0=冻结分支逐位不变)。
        # 外部双序盲评两序均指认"纸盒波浪状凹陷/结构坍塌/建模错误" → 按实测降幅验证。
        _ds = float(os.environ.get("PAPER_DEFORM", "1.0"))
        _disp = _ds * (0.0025 * _n1[0] + 0.0012 * _n2[1] + 0.0006 * _n3[2])
        _top_t = (_wp.z - _zmin) / max(1e-6, _zmax - _zmin)
        if _top_t > 0.85:
            _nt = _nv(_wp * 80.0 + _pw.Vector((5.5, 1.3, 9.2)))
            _disp += _ds * 0.001 * _nt[0] * ((_top_t - 0.85) / 0.15)
        _pv2.co += _pv2.normal * _disp
    _pme.update()
    _assign_uv(carton)
    carton.location = loc

    # ---- 材质 (贴图) ----
    mat = bpy.data.materials.new("Mat_Carton1L")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = nt.nodes.get("Principled BSDF")
    tex_p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets/textures/carton_1l_albedo.png")
    if os.path.exists(tex_p):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(tex_p)
        nt.links.new(t.outputs["Color"], bsdf.inputs["Base Color"])
    # v106 纸材纤维法线 (外部盲评判"纸盒边缘生硬/缺纸材纹理", 代码核查证实本材质原先
    # **完全没有法线贴图**: 只有 albedo+Roughness+Coat+SSS; 仓库 tetrapak_common_normal.png
    # 仅在经典SKU路径(01_comfy:571-578)接线, 1L路径漏接)。
    # env 门控默认关: 暗调KV冻结分支(POUR_1L=1)零影响, 只由 lifestyle 配方显式开启。
    if os.environ.get("PAPER_NRM", "0") == "1":
        _np_p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "assets/textures/tetrapak_common_normal.png")
        if os.path.exists(_np_p):
            _tn = nt.nodes.new("ShaderNodeTexImage")
            _tn.image = bpy.data.images.load(_np_p, check_existing=True)
            _tn.image.colorspace_settings.name = "Non-Color"
            _nm = nt.nodes.new("ShaderNodeNormalMap")
            _nm.inputs["Strength"].default_value = float(os.environ.get("PAPER_NRM_S", "0.45"))
            nt.links.new(_tn.outputs["Color"], _nm.inputs["Color"])
            nt.links.new(_nm.outputs["Normal"], bsdf.inputs["Normal"])
            print("[CARTON1L] 纸材法线已接 strength=%.2f" % _nm.inputs["Strength"].default_value)
        else:
            print("[CARTON1L] 纸材法线贴图缺失, 跳过:", _np_p)
    # v122 光泽 env 门控(默认全等原值 → 冻结KV分支逐位不变)。
    # 0.18/0.25 是 v100 E40 为**暗调KV**设计的缎光配方(当初为让形变有高光可扭曲);
    # 高调生活场景下形变已降至0.35, 缎光不再需要, 外部评审连续判"塑料感/缺哑光漫反射细节"。
    bsdf.inputs["Roughness"].default_value = float(os.environ.get("PAPER_ROUGH", "0.18"))
    if "Coat Weight" in bsdf.inputs:
        bsdf.inputs["Coat Weight"].default_value = float(os.environ.get("PAPER_COAT", "0.25"))
        bsdf.inputs["Coat Roughness"].default_value = float(os.environ.get("PAPER_COAT_R", "0.10"))
    if "Subsurface Weight" in bsdf.inputs:
        bsdf.inputs["Subsurface Weight"].default_value = 0.05   # 纸基微透
        bsdf.inputs["Subsurface Radius"].default_value = (0.01, 0.008, 0.005)
    carton.data.materials.append(mat)

    # ---- 旋盖 (gable 前斜面, 白色 HDPE 扁圆柱) ----
    # 盖位置: 前斜面 (-Y 侧) 中心偏上, 法线朝 -Y+Z
    cap_cx, cap_cy, cap_cz = 0, -hd*0.55, z0 + GH*0.55
    bpy.ops.mesh.primitive_cylinder_add(radius=CAP_R, depth=0.007, vertices=32,
                                        location=(cap_cx, cap_cy, cap_cz))
    cap = bpy.context.active_object
    cap.name = "Carton1L_Cap"
    # 盖轴朝前斜面外法线 (0, -GH, hd) 归一化; cylinder 轴 Z → 法线
    _nrm = mu.Vector((0, -GH, hd)).normalized()
    cap.rotation_euler = _nrm.to_track_quat('Z', 'Y').to_euler()
    # 螺纹环 (盖底 torus, 消"白球"感 → 明确旋盖结构)
    bpy.ops.mesh.primitive_torus_add(major_radius=CAP_R*0.92, minor_radius=0.0012,
                                     major_segments=32, minor_segments=8,
                                     location=(cap_cx, cap_cy, cap_cz))
    _ring = bpy.context.active_object
    _ring.rotation_euler = cap.rotation_euler
    _ring.parent = cap
    _ring.matrix_parent_inverse = cap.matrix_world.inverted()
    # 防滑纹 (bevel)
    cbev = cap.modifiers.new("CapBevel", "BEVEL")
    cbev.width = 0.0008; cbev.segments = 2
    bpy.ops.object.modifier_apply(modifier="CapBevel")
    cmat = bpy.data.materials.new("Mat_Carton1L_Cap")
    cmat.use_nodes = True
    cb = cmat.node_tree.nodes.get("Principled BSDF")
    cb.inputs["Base Color"].default_value = (0.92, 0.92, 0.90, 1)
    cb.inputs["Roughness"].default_value = 0.30
    if "Subsurface Weight" in cb.inputs:
        cb.inputs["Subsurface Weight"].default_value = 0.1
    cap.data.materials.append(cmat)
    cap.parent = carton
    cap.matrix_parent_inverse = carton.matrix_world.inverted()

    if cap_open:
        # 开盖: 盖沿法线抬起+侧移 (露出盖口, 盖仍挂在盒旁)
        cap.location = (cap_cx + 0.013, cap_cy - 0.009, cap_cz + 0.005)   # v100 贴近盖口 (刚拧开, 非远距悬浮)
        cap.rotation_euler = (math.radians(100), 0, math.radians(15))

    return carton, cap


def spout_pos():
    """倒奶出液口 (相对 carton origin): 前斜面旋盖口中心."""
    hd = BD/2
    return mu.Vector((0, -hd*0.55, BH + GH*0.55))