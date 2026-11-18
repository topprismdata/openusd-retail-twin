# lifestyle_props.py — 高调生活方式场景道具库（构建-only，禁止渲染）
#
# 参照: assets/reference/lifestyle_highkey_ref.png (电商延世牛奶早餐场景)
#   右下: 淡蓝釉面深碗 + 燕麦粥 + 蓝莓, 置于蓝白细斜条纹餐巾上
#   右上: 透明玻璃碗 + 彩色切块水果 (西瓜红/蜜瓜橙/葡萄紫)
#   右中: 两片浅金色吐司斜叠
#   中后: 白瓷小碗 (深碗形) 盛橙色果酱
#
# 契约:
#   - 只构建网格与材质, 绝不调用 bpy.ops.render.*
#   - 不 import PIL; 材质全程序化 shader 节点, 唯一外部资产 napkin 的
#     assets/reference/cloth_linen.jpg (R20/R21 台账: 微米织纹必须真图, bpy.data.images.load)
#   - 单位=米, 桌面 z=0, 物体底面贴地
#   - 所有对象显式 link 到 bpy.context.scene.collection (ops 污染坑: 强链防静默不渲)
#   - 材质名用传入 name 前缀, 不与主脚本 (Milk/MilkHero/GlassClear/...) 冲突
#   - 随机全部走 random.Random(固定seed), 同输入同输出
#
# 用法: /Applications/Blender.app/Contents/MacOS/Blender -b --factory-startup -P lifestyle_props.py

import math
import os
import random
import zlib

import bpy
import bmesh
from mathutils import Matrix

TAU = math.tau


# ---------------------------------------------------------------- helpers

def _uid(name):
    """name → 稳定 seed (跨进程确定性)."""
    return zlib.crc32(name.encode("utf-8")) & 0xFFFF


def _link(ob):
    """强链: 从 ops 默认集合摘除, 显式挂到 scene.collection."""
    for c in list(ob.users_collection):
        c.objects.unlink(ob)
    bpy.context.scene.collection.objects.link(ob)
    return ob


def _obj(name, me):
    return _link(bpy.data.objects.new(name, me))


def _mat(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    pb = nt.nodes.get("Principled BSDF")
    if pb is None:
        raise RuntimeError(f"[{name}] Principled BSDF 节点缺失")
    # blend_method 枚举在 4.2+ 改名/迁移, 双防御
    try:
        if hasattr(m, "blend_method"):
            m.blend_method = "OPAQUE"
    except TypeError:
        pass
    if hasattr(m, "surface_render_method"):
        try:
            m.surface_render_method = "DITHERED"
        except TypeError:
            pass
    return m, nt, pb


def _pset(pb, keys, val):
    """防御式设输入 (Specular→Specular IOR Level / Subsurface→Subsurface Weight 等 5.2 改名坑)."""
    for k in keys:
        if k in pb.inputs:
            pb.inputs[k].default_value = val
            return True
    return False


def _recalc(me):
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()


def _smooth(me):
    for p in me.polygons:
        p.use_smooth = True


def _revolve(name, profile, segments=64, cap_start=True, cap_end=True,
             recalc=True, smooth=True):
    """2D 剖面 (radius, z) 绕 Z 轴旋转成网格.

    profile 自下而上给出; 半径=0 的首/末点收为中心顶点(扇形封口).
    面序: (i,j),(i,j+1),(i+1,j+1),(i+1,j) → 外壁法线朝外;
    开曲面 (recalc=False, 如玻璃碗) 保持该一致性, Solidify offset=-1 即向内增厚.
    """
    verts = []
    faces = []
    rings = []
    n = len(profile)
    for i, (rad, z) in enumerate(profile):
        if abs(rad) < 1e-9:
            rings.append(("center", len(verts)))
            verts.append((0.0, 0.0, z))
        else:
            rings.append(("ring", len(verts)))
            for j in range(segments):
                a = TAU * j / segments
                verts.append((rad * math.cos(a), rad * math.sin(a), z))
    for i in range(n - 1):
        t0, b0 = rings[i]
        t1, b1 = rings[i + 1]
        if t0 == "center" and t1 == "ring":
            # 底部穹顶: 法线朝下/外
            for j in range(segments):
                faces.append((b0, b1 + (j + 1) % segments, b1 + j))
        elif t0 == "ring" and t1 == "center":
            # 顶部 apex: 法线朝上
            for j in range(segments):
                faces.append((b0 + j, b0 + (j + 1) % segments, b1))
        else:
            for j in range(segments):
                j2 = (j + 1) % segments
                faces.append((b0 + j, b0 + j2, b1 + j2, b1 + j))
    # 开口端补盘形封口 (剖面端点半径>0 且要求封口)
    for end, flag, down in ((0, cap_start, True), (n - 1, cap_end, False)):
        if not flag or abs(profile[end][0]) < 1e-9:
            continue
        _, base = rings[end]
        c = len(verts)
        verts.append((0.0, 0.0, profile[end][1]))
        for j in range(segments):
            j2 = (j + 1) % segments
            faces.append((c, base + (j2 if down else j), base + (j if down else j2)))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    if recalc:
        _recalc(me)
    if smooth:
        _smooth(me)
    return me


def _box_mesh(name, sx, sy, sz, bevel=0.0, bevel_segments=3, smooth=False):
    """bmesh 圆角长方体 (size=1.0 cube → 全尺寸缩放 → bevel)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    bm.transform(Matrix.Diagonal((sx, sy, sz, 1.0)))
    if bevel > 0.0:
        geom = list(bm.verts) + list(bm.edges) + list(bm.faces)
        bmesh.ops.bevel(bm, geom=geom, offset=bevel, offset_type="OFFSET",
                        profile=0.5, segments=bevel_segments,
                        affect="EDGES", clamp_overlap=True)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.validate()
    me.update()
    if smooth:
        _smooth(me)
    return me


def _sphere_mesh(name, r, sx=1.0, sy=1.0, sz=1.0, u=24, v=16):
    bm = bmesh.new()
    try:
        bmesh.ops.create_uvsphere(bm, u_segments=u, v_segments=v, radius=1.0)
    except TypeError:  # 旧 API 兼容
        bmesh.ops.create_uvsphere(bm, segments=u, ring_count=v, diameter=2.0)
    bm.transform(Matrix.Diagonal((r * sx, r * sy, r * sz, 1.0)))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.validate()
    me.update()
    _smooth(me)
    return me


def _grid_mesh(name, w, d, nx, ny, zfun):
    """w×d 平面网格 (nx×ny 顶点), zfun(u, v, x, y)→(x, y, z) 逐点位移."""
    verts = []
    for ix in range(nx):
        x0 = -w / 2.0 + w * ix / (nx - 1)
        for iy in range(ny):
            y0 = -d / 2.0 + d * iy / (ny - 1)
            verts.append(zfun(x0, y0))
    faces = []
    for ix in range(nx - 1):
        for iy in range(ny - 1):
            a = ix * ny + iy
            faces.append((a, a + ny, a + ny + 1, a + 1))  # +z 法线
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.validate()
    me.update()
    _smooth(me)
    return me


def _fnoise(x, y):
    """固定系数多频 sin 伪噪声, 确定性, 值域约 [-1.75, 1.75]."""
    return (math.sin(1.7 * x + 0.8 * math.sin(1.3 * y))
            * math.cos(1.5 * y + 0.6 * math.sin(2.1 * x))
            + 0.5 * math.sin(3.1 * x - 1.2) * math.sin(2.7 * y + 0.7)
            + 0.25 * math.sin(5.3 * x + 2.0) * math.cos(4.3 * y - 1.5))


def _ellipse_pts(r0, z0, r1, z1, n, skip_first=False):
    """从 (r0,z0) 到 (r1,z1) 的四分之一椭圆采样 n 点 (skip_first 去重)."""
    pts = []
    for k in range(n):
        t = k / (n - 1.0)
        a = (math.pi / 2.0) * t
        s, c = math.sin(a), 1.0 - math.cos(a)
        pts.append((r0 + (r1 - r0) * s, z0 + (z1 - z0) * c))
    return pts[1:] if skip_first else pts


def _col_ramp(nt, name, stops):
    """ColorRamp: stops = [(pos, (r,g,b)), ...]."""
    node = nt.nodes.new("ShaderNodeValToRGB")
    node.name = name
    cr = node.color_ramp
    while len(cr.elements) > 1:
        cr.elements.remove(cr.elements[-1])
    cr.elements[0].position = stops[0][0]
    cr.elements[0].color = stops[0][1]
    for pos, col in stops[1:]:
        e = cr.elements.new(pos)
        e.color = col
    return node


# ---------------------------------------------------------------- 1. 燕麦碗

_SCAN_BERRY_CACHE = {}


def _scan_berry_mesh():
    """真扫描蓝莓网格(单位半径, zmin=0), 读离线提取的 .blend 库; 缺库则回退程序化。

    动机: 外部评审多轮把"蓝莓塑料感/缺果粉与水润感"列 #1 材质缺陷。子代理曾判
    "670k面挑不干净"→保持程序化, 但**从未实测**; 本仓探针推翻: 按材质可唯一分离
    Sphere.037_Blueberry_0(30172v/53504f), baseColor/normal/metallicRoughness 各2048²齐备。
    用 bpy.data.libraries.load(纯数据API) 而非 import_scene.gltf —— 后者有 ops 污染
    (扰动 active/selection), 本仓记载须放管线最末, 而道具在 layout 期构建。
    来源 CC-BY-4.0 ¡Jacques "A bowl of berries"; 署名见 assets/models/blueberry/CREDITS.md。
    """
    if "me" in _SCAN_BERRY_CACHE:
        return _SCAN_BERRY_CACHE["me"]
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "assets", "models", "blueberry", "blueberry.blend")
    me = mat = None
    if not os.path.exists(p):
        print("[SCAN-BERRY] 库缺失, 回退程序化:", p)
    else:
        with bpy.data.libraries.load(p, link=False) as (src, dst):
            dst.meshes = [n for n in src.meshes if n == "ScanBlueberry"]
            dst.materials = [n for n in src.materials if n == "ScanBlueberryMat"]
        me = next((m for m in dst.meshes if m), None)
        mat = next((m for m in dst.materials if m), None)
        if me is None or mat is None:
            print("[SCAN-BERRY] 库内网格/材质缺失, 回退程序化")
            me = None
        else:
            me.materials.clear()
            me.materials.append(mat)
            # v136 备注: 贴图不显示的真根因=packed blob 空存根, 一次性解包到
            # assets/sf_models/berries/textures/ 后绝对路径可解析(生产渲染已验证)。
            # (早前"roughness 乘 0 = 镜面"假设经 dump 证伪: 0.0 乘子在 Metallic 上,
            #  对水果恰好正确; Roughness=G×0.28 半光, 解包后哑光果粉质感正常。)
            print("[SCAN-BERRY] 已载入 v=%d f=%d mat=%s"
                  % (len(me.vertices), len(me.polygons), mat.name))
    _SCAN_BERRY_CACHE["me"] = me
    # v139.1: 合并网格含3-6颗连体莓(隔离渲染实测) → 8实例同簇="珍珠串"重复感。
    # 拆 loose parts 成独立单莓网格(逐颗归一: 中心xy=0, zmin=0), 供分支逐颗轮换摆位。
    if "parts" not in _SCAN_BERRY_CACHE:
        parts = []
        if me is not None:
            import bmesh
            bm = bmesh.new()
            bm.from_mesh(me)
            bm.verts.ensure_lookup_table()
            seen = set()
            comps = []
            for v in bm.verts:
                if v.index in seen or not v.link_faces:
                    continue
                stack = [v]
                comp = []
                while stack:
                    vv = stack.pop()
                    if vv.index in seen:
                        continue
                    seen.add(vv.index)
                    comp.append(vv)
                    for e in vv.link_edges:
                        v2 = e.other_vert(vv)
                        if v2.index not in seen:
                            stack.append(v2)
                if len(comp) >= 300:
                    comps.append({vv.index: vv for vv in comp})
            bm.faces.ensure_lookup_table()
            for cmap in comps:
                sub = bmesh.new()
                vmap = {}
                for v in cmap.values():
                    vmap[v.index] = sub.verts.new(v.co)
                for f in bm.faces:
                    if all(v.index in vmap for v in f.verts):
                        sub.faces.new([vmap[v.index] for v in f.verts])
                # 归一: xy中心归零, zmin=0, 且缩放到单位半径(簇内单莓原仅0.3-0.5单位,
                # 不缩放则×rb后世界直径仅4mm=v139.5"黑点"根因)
                xs = [v.co.x for v in sub.verts]
                ys = [v.co.y for v in sub.verts]
                zs = [v.co.z for v in sub.verts]
                cx, cy, zmin = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, min(zs)
                ext = max(max(xs) - min(xs), max(ys) - min(ys))
                sc = 2.0 / max(ext, 1e-9)
                for v in sub.verts:
                    v.co.x = (v.co.x - cx) * sc
                    v.co.y = (v.co.y - cy) * sc
                    v.co.z = (v.co.z - zmin) * sc
                # v139.7: 手工faces.new朝向任意 → 重算法线(右后莓棱线根因)
                bmesh.ops.recalc_face_normals(sub, faces=sub.faces)
                # v140.3: 水密补洞(calyx开口部分角度读作穿帮圆孔)
                try:
                    bmesh.ops.holes_fill(sub, edges=sub.edges[:], sides=0)  # v142: sides=0全量补洞(calyx开口>64边时64会漏)
                except Exception:
                    pass
                pme = bpy.data.meshes.new("ScanBlueberryPart")
                sub.to_mesh(pme)
                sub.free()
                pme.materials.append(me.materials[0] if me.materials else None)
                parts.append(pme)
            bm.free()
            print("[SCAN-BERRY] 拆分单莓: %d 颗 (顶点各%d±)" % (len(parts), len(parts) and len(parts[0].vertices)))
        _SCAN_BERRY_CACHE["parts"] = parts
    return me


_STRAW_CACHE = {}


def _scan_strawberry_mesh():
    """真扫描草莓网格(原尺寸~40x40x47mm含花萼, 原点=包围盒中心/zmin=0), CC0。

    v137 用户指令"换草莓": 蓝莓 v136 已修真(贴图解包), 但碗内特写吸引力仍是评审
    食欲感短板; 红色浆果补食欲信号并增加色彩对比。来源 Innerscene 3D Parts
    Library "Strawberry" (CC0 1.0), 凭证见 assets/models/strawberry/CREDITS.md
    与 license_page.html 快照。资产=主体+85颗独立种子+6花萼 合并单 mesh
    (多材质槽序[叶/种子/红皮]); 贴图已实体解包(extract_scan_strawberry.py 两段式,
    三图 has_data=True 已验证)。缺库则回退蓝莓/程序化路径。
    """
    if "me" in _STRAW_CACHE:
        return _STRAW_CACHE["me"]
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "assets", "models", "strawberry", "strawberry.blend")
    me = None
    if not os.path.exists(p):
        print("[SCAN-STRAW] 库缺失, 回退:", p)
    else:
        with bpy.data.libraries.load(p, link=False) as (src, dst):
            dst.meshes = [n for n in src.meshes if n == "StrawberryScanMesh"]
            dst.materials = [n for n in src.materials]
        me = next((m for m in dst.meshes if m), None)
        if me is None:
            print("[SCAN-STRAW] 库内网格缺失, 回退")
        else:
            if any(m is None for m in me.materials):
                me.materials.clear()
                for nm in ("Original green food foliage",
                           "Original muted tan gold strawberry seed",
                           "Original red strawberry skin"):
                    m2 = bpy.data.materials.get(nm)
                    if m2:
                        me.materials.append(m2)
            print("[SCAN-STRAW] 已载入 v=%d f=%d slots=%s"
                  % (len(me.vertices), len(me.polygons),
                     [m.name if m else None for m in me.materials]))
    _STRAW_CACHE["me"] = me
    return me


def _oat_flake_mesh(name, rng, si):
    """v140.1 免费路线: 程序化燕麦片(真片=卷边/波缘/起伏椭圆, 非平圆片)。
    GPT R2 结构要求: 英雄片表层+碎屑; 粥面成败在湿润团块拓扑而非片模型本身。
    3 基变体 × 每实例随机形变(边波/卷曲/起伏)。si=变体号(0-2)。"""
    ph1, ph2 = rng.uniform(0, TAU), rng.uniform(0, TAU)
    curl = rng.uniform(0.35, 0.85)
    me_f = _sphere_mesh(name, 1.0, 0.011, 0.0072, 0.0009, u=20, v=12)
    for v in me_f.vertices:
        x, y, z = v.co
        rho = math.hypot(x, y)
        th = math.atan2(y, x)
        w = 1.0 + 0.30 * math.sin(3 * th + ph1) + 0.14 * math.sin(5 * th + ph2)
        v.co.x = x * w
        v.co.y = y * w
        rr = math.hypot(v.co.x, v.co.y) / 0.011
        v.co.z += 0.00080 * math.sin(2.1 * v.co.x / 0.011 + ph1) \
            * math.cos(1.7 * v.co.y / 0.0072 + ph2) \
            + curl * 0.00130 * (rr ** 2.2)
    me_f.update()
    return me_f


def _raspberry_mesh(name, rng):
    """v140.1 免费路线: 程序化树莓(聚合果: 60-80小核果斐波那契球面排布, 底部遮蔽)。
    强调色担当(GPT R4裁决: 树莓红2-3颗)。单网格, 逐核果色相变化由着色器噪点承担。"""
    n = 46
    ga = math.pi * (3.0 - math.sqrt(5.0))
    drup = []
    for i in range(n):
        zz = 1.0 - 2.0 * (i + 0.5) / n
        rr = math.sqrt(max(0.0, 1.0 - zz * zz))
        th = ga * i
        drup.append((math.cos(th) * rr, math.sin(th) * rr, zz))
    me_d2 = _sphere_mesh(name + "_DrupeletProto", 1.0, 1.0, 1.0, 1.0, u=10, v=7)
    vpr = [(v.co.x, v.co.y, v.co.z) for v in me_d2.vertices]
    verts_d, faces_d = [], []
    for (dx, dy, dz) in drup:
        if dz < -0.45:   # 底部核果不可见不生成
            continue
        cx = dx * 0.0087 + rng.uniform(-0.0006, 0.0006)   # v142.3: 抖动±0.6mm
        cy = dy * 0.0087 + rng.uniform(-0.0006, 0.0006)
        cz = dz * 0.0092 + rng.uniform(-0.0005, 0.0005)
        rd = rng.uniform(0.0029, 0.0036)                  # v142.6: 密排(>邻半距0.0024→核果互挤+沟缝, 真树莓拓扑)
        sqy = rng.uniform(0.75, 1.25)                     # 随机压扁加强
        base = len(verts_d)
        for (vx, vy, vz) in vpr:
            verts_d.append((cx + vx * rd * (1.0 + 0.22 * (1.0 - abs(dz))),
                            cy + vy * rd * sqy,
                            cz + vz * rd * (0.75 + 0.25 * (1.0 - dz))))
        for f in me_d2.polygons:
            faces_d.append(tuple(base + vi for vi in f.vertices))
    import bpy as _bpy
    me_all = _bpy.data.meshes.new(name)
    me_all.from_pydata(verts_d, [], faces_d)
    me_all.update()
    # v142.2: from_pydata默认平面着色 → 核果刻面反光="水晶珠"元凶; 全平滑
    me_all.polygons.foreach_set('use_smooth', [True] * len(me_all.polygons))
    me_all.update()
    return me_all


def oatmeal_bowl(loc=(0.0, 0.0, 0.0), r=0.075, name="OatBowl", scan_berry=False,
                 berry_scatter=False, glaze_bump=0.0, berry_tilt=0.0,
                 porridge_detail=0.0, berry_front=0.0, fruit="blueberry"):
    """淡蓝釉面陶瓷深碗(壁厚~3.5mm) + 米色燕麦粥面(低频凹凸) + 蓝莓5-8颗 + 燕麦片."""
    rng = random.Random(_uid(name))
    h = 0.73 * r          # 碗高 (参照: 深碗)
    tw = 0.0035           # 壁厚 2-4mm
    fl = 0.0032           # 内底高度 (底厚 ≈3mm)

    # --- 碗体剖面 (闭合 solid): 底 → 外壁 → 沿口 → 内壁 → 内底
    prof = [(0.0, 0.0), (0.60 * r, 0.0), (0.63 * r, 0.0)]
    prof += _ellipse_pts(0.63 * r, 0.0, r, h, 6, skip_first=True)       # 外壁
    prof += [(r - tw, h)]                                               # 沿口
    prof += _ellipse_pts(r - tw, h, 0.52 * r, fl, 6, skip_first=True)   # 内壁
    prof += [(0.34 * r, fl - 0.0004), (0.0, fl - 0.0006)]               # 内底
    me_bowl = _revolve(f"{name}_BowlMesh", prof, segments=64)

    m_glaze, nt_g, pb_g = _mat(f"{name}_Glaze")
    _pset(pb_g, ["Base Color"], (0.62, 0.74, 0.83, 1.0))   # 淡蓝/青瓷蓝
    _pset(pb_g, ["Roughness"], 0.10)
    _pset(pb_g, ["Metallic"], 0.0)
    _pset(pb_g, ["Specular IOR Level", "Specular"], 0.5)
    _pset(pb_g, ["Coat Weight", "Clearcoat"], 0.25)        # 釉面
    me_bowl.materials.append(m_glaze)
    if glaze_bump > 0.0:
        # v132 评审反复点"陶瓷釉面涂抹感/数码痕迹": 原釉面只有 base/rough/coat,
        # **完全无 bump/normal** → 完美光滑读作CG。真实釉面有橘皮微起伏。
        # 复用粥面已验证的 TexCoord(Object)→Noise→Bump→Normal 范式; 幅度刻意小
        # (Distance 0.0004m=0.4mm), 只破高光均匀性, 不改碗形。默认0=原行为。
        tc_g = nt_g.nodes.new("ShaderNodeTexCoord")
        nz_g = nt_g.nodes.new("ShaderNodeTexNoise")
        nz_g.inputs["Scale"].default_value = 120.0
        nz_g.inputs["Detail"].default_value = 2.0
        bp_g = nt_g.nodes.new("ShaderNodeBump")
        bp_g.inputs["Strength"].default_value = float(glaze_bump)
        bp_g.inputs["Distance"].default_value = 0.0004
        nt_g.links.new(tc_g.outputs["Object"], nz_g.inputs["Vector"])
        nt_g.links.new(nz_g.outputs["Fac"], bp_g.inputs["Height"])
        bsdf_g = nt_g.nodes.get("Principled BSDF")
        nt_g.links.new(bp_g.outputs["Normal"], bsdf_g.inputs["Normal"])
    root = _obj(name, me_bowl)

    # --- 燕麦粥面 (闭合穹顶 + 低频位移, 非平面)
    rp = 0.88 * r
    zf = 0.62 * h
    prof_p = [(0.0, zf + 0.0045), (0.45 * rp, zf + 0.0030), (0.80 * rp, zf + 0.0012),
              (0.97 * rp, zf - 0.0008), (rp, zf - 0.0022), (0.85 * rp, zf - 0.0060),
              (0.45 * rp, zf - 0.0075), (0.0, zf - 0.0080)]
    me_p = _revolve(f"{name}_PorridgeMesh", prof_p, segments=48)
    if porridge_detail > 0.0:
        # v134r3: shader bump 两轮被视觉证伪(MAXIMUM 压低频方差; roughness 斑驳打碎
        # 明暗对比→读作"柔化")。改**几何杠杆**——真根因: 原 3.3mm 波长位移在 48 段
        # 旋转网格 ~7mm 顶点间距上**采样混叠不可见**。细分(384→~1500v, 间距→3.5mm)
        # 让位移可采样, 再叠 11mm 波长粥块 octave。默认0=原行为逐位不变。
        import bmesh
        _bm = bmesh.new()
        _bm.from_mesh(me_p)
        bmesh.ops.subdivide_edges(_bm, edges=_bm.edges[:], cuts=2, use_grid_fill=True)
        _bm.to_mesh(me_p)
        _bm.free()
    for v in me_p.vertices:
        x, y, z = v.co
        damp = max(0.0, min(1.0, (z - (zf - 0.002)) / 0.006))
        v.co.z += 0.0028 * damp * _fnoise(x * 300.0 + 3.1, y * 300.0 - 1.7)
        if porridge_detail > 0.0:
            v.co.z += 0.0022 * damp * _fnoise(x * 90.0 - 4.2, y * 90.0 + 2.8)
    me_p.update()

    def _surf(x, y):
        dd = math.hypot(x, y)
        dome = 0.0045 * max(0.0, 1.0 - (dd / rp) ** 2) - 0.0008 * (dd / rp) ** 2
        return zf + dome + 0.0028 * _fnoise(x * 300.0 + 3.1, y * 300.0 - 1.7)

    m_po, nt_p, pb_p = _mat(f"{name}_Porridge")
    _pset(pb_p, ["Base Color"], (0.82, 0.72, 0.55, 1.0))   # 米色微黄
    _pset(pb_p, ["Roughness"], 0.55)
    _pset(pb_p, ["Metallic"], 0.0)
    tc = nt_p.nodes.new("ShaderNodeTexCoord")
    nz = nt_p.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = 30.0
    nz.inputs["Detail"].default_value = 2.0
    bp = nt_p.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.30
    bp.inputs["Distance"].default_value = 0.0025
    nt_p.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nt_p.links.new(nz.outputs["Fac"], bp.inputs["Height"])
    bsdf_p = nt_p.nodes.get("Principled BSDF")
    nt_p.links.new(bp.outputs["Normal"], bsdf_p.inputs["Normal"])
    # v140.1 湿粥体(免费路线, OAT_V140=1默认): 商业参照实测=颗粒+湿润浆液光泽+奶白
    # 混合(GPT R2 成功标准: 湿润感)。奶白涡混×Coat湿膜×SSS透光。
    import os as _os_v140
    if _os_v140.environ.get("OAT_V140", "1") == "1" and bsdf_p is not None:
        _nzm = nt_p.nodes.new("ShaderNodeTexNoise")
        _nzm.inputs["Scale"].default_value = 70.0
        _nzm.inputs["Detail"].default_value = 3.0
        _mixm = nt_p.nodes.new("ShaderNodeMix")
        _mixm.blend_type = 'MIX'   # 5.2: blend_type须先于data_type(否则socket集重置)
        _mixm.data_type = 'RGBA'
        def _psock(col, suffix):
            for _s in col:
                if _s.identifier.endswith(suffix):
                    return _s
            return None
        _sbc = _bsdf_base = bsdf_p.inputs['Base Color']
        _sA = _psock(_mixm.inputs, 'A_Color'); _sB = _psock(_mixm.inputs, 'B_Color')
        _sF = _psock(_mixm.inputs, 'Factor_Float'); _sO = _psock(_mixm.outputs, 'Result_Color')
        if _sA is not None and _sO is not None:
            _sA.default_value = (0.72, 0.60, 0.43, 1.0)   # 燕麦米色(v141.9对比加大, 原低对比色静默未替换过)
            _sB.default_value = (0.94, 0.91, 0.85, 1.0)   # 奶白浆液
            _sF.default_value = 0.62
            nt_p.links.new(tc.outputs['Object'], _nzm.inputs['Vector'])
            nt_p.links.new(_nzm.outputs['Fac'], _sF)
            nt_p.links.new(_sO, _sbc)
        _pset(pb_p, ["Roughness"], 0.46)
        # v140.3 斑块化湿膜: 凹处积液(湿,粗0.14镜面) 凸处干(粗0.5漫射) — 真粥湿态
        _nzW = nt_p.nodes.new("ShaderNodeTexNoise")
        _nzW.inputs["Scale"].default_value = 24.0
        _nzW.inputs["Detail"].default_value = 4.0
        nt_p.links.new(tc.outputs['Object'], _nzW.inputs['Vector'])
        # v140.4: 积液mask=噪点×pointiness(几何凹处): 复合调制, 高光集中在低洼积液区
        _geo = nt_p.nodes.new("ShaderNodeNewGeometry")
        _mrP = nt_p.nodes.new("ShaderNodeMapRange")
        _mrP.inputs['From Min'].default_value = 0.46
        _mrP.inputs['From Max'].default_value = 0.60
        _mrP.inputs['To Min'].default_value = 1.0   # 凹(pointiness低)→湿
        _mrP.inputs['To Max'].default_value = 0.15  # 凸→干
        _mrP.clamp = True
        nt_p.links.new(_geo.outputs['Pointiness'], _mrP.inputs['Value'])
        _mthW = nt_p.nodes.new("ShaderNodeMath")
        _mthW.operation = 'MULTIPLY'
        nt_p.links.new(_nzW.outputs['Fac'], _mthW.inputs[0])
        nt_p.links.new(_mrP.outputs['Result'], _mthW.inputs[1])
        _mrW = nt_p.nodes.new("ShaderNodeMapRange")
        _mrW.inputs['From Min'].default_value = 0.0
        _mrW.inputs['From Max'].default_value = 1.0
        _mrW.inputs['To Min'].default_value = 0.15
        _mrW.inputs['To Max'].default_value = 0.85
        nt_p.links.new(_mthW.outputs['Value'], _mrW.inputs['Value'])
        _cW = bsdf_p.inputs.get("Coat Weight") or bsdf_p.inputs.get("Clearcoat")
        if _cW is not None:
            nt_p.links.new(_mrW.outputs['Result'], _cW)
        _nzR = nt_p.nodes.new("ShaderNodeTexNoise")
        _nzR.inputs["Scale"].default_value = 40.0
        _nzR.inputs["Detail"].default_value = 3.0
        nt_p.links.new(tc.outputs['Object'], _nzR.inputs['Vector'])
        _mrR = nt_p.nodes.new("ShaderNodeMapRange")
        _mrR.inputs['From Min'].default_value = 0.0
        _mrR.inputs['From Max'].default_value = 1.0
        _mrR.inputs['To Min'].default_value = 0.08
        _mrR.inputs['To Max'].default_value = 0.35
        nt_p.links.new(_nzR.outputs['Fac'], _mrR.inputs['Value'])
        _cR = bsdf_p.inputs.get("Coat Roughness")
        if _cR is not None:
            nt_p.links.new(_mrR.outputs['Result'], _cR)
        _pset(pb_p, ["Subsurface Weight"], 0.12)           # 粥体微透光
        _srp = bsdf_p.inputs.get("Subsurface Radius")
        if _srp is not None and not _srp.is_linked:
            _srp.default_value = (0.010, 0.006, 0.004)
        _pset(pb_p, ["Subsurface Scale"], 0.012)
    # v134 备忘: shader bump(细颗粒/roughness斑驳/烘烤色斑)三轮均被视觉证伪——
    # 粥面颗粒感是**几何**特征, 已改由上方 porridge_detail 门控的网格细分+位移
    # octave 实现; 材质保持原样(scale30 低频丘 + 匀色匀粗糙)。
    me_p.materials.append(m_po)
    ob_p = _obj(f"{name}_Porridge", me_p)
    ob_p.parent = root

    # --- 蓝莓 6 颗 (深蓝紫 + 白霜感 + 顶部花萼凹)
    m_bb, nt_b, pb_b = _mat(f"{name}_Berry")
    # 外部盲评判"蓝莓塑料蜡质感, 缺水分与次表面散射" —— 代码核查证实原材质**完全没有
    # Subsurface**(只设Roughness/Metallic/噪波白霜), 评审是实据不是主观印象。
    # 蓝莓真实光学: 果皮薄蜡质(低粗糙+微coat) + 果肉半透(SSS半径毫米级, 深红紫内散射)。
    _pset(pb_b, ["Roughness"], 0.34)          # 0.62 过哑 → 果皮蜡质光泽
    _pset(pb_b, ["Metallic"], 0.0)
    _pset(pb_b, ["Subsurface Weight", "Subsurface"], 0.28)
    _pset(pb_b, ["Subsurface Radius"], (0.0035, 0.0016, 0.0022))   # 3.5/1.6/2.2mm, 红透紫
    _pset(pb_b, ["Subsurface Scale"], 0.004)
    _pset(pb_b, ["Coat Weight"], 0.22)        # 果皮薄蜡层
    _pset(pb_b, ["Coat Roughness"], 0.18)
    tc_b = nt_b.nodes.new("ShaderNodeTexCoord")
    nz_b = nt_b.nodes.new("ShaderNodeTexNoise")
    nz_b.inputs["Scale"].default_value = 55.0
    nz_b.inputs["Detail"].default_value = 3.0
    ramp_b = _col_ramp(nt_b, f"{name}_FrostRamp", [
        (0.00, (0.05, 0.04, 0.11, 1.0)),   # 深蓝紫
        (0.50, (0.06, 0.05, 0.13, 1.0)),
        (0.55, (0.42, 0.46, 0.55, 1.0)),   # 白霜斑(v142: 0.64→0.55 早现, 评审"缺果霜")
        (0.72, (0.58, 0.61, 0.68, 1.0)),
    ])
    bp_b = nt_b.nodes.new("ShaderNodeBump")
    bp_b.inputs["Strength"].default_value = 0.12   # v142: 0.05→0.12 果霜颗粒感
    _bs_b = bsdf_b = nt_b.nodes.get("Principled BSDF")
    if _bs_b is not None and not _bs_b.inputs['Roughness'].is_linked:
        _mr_b = nt_b.nodes.new("ShaderNodeMapRange")
        _mr_b.inputs['To Min'].default_value = 0.26   # v142: 粗糙摆动 0.26-0.46 (蜡↔霜)
        _mr_b.inputs['To Max'].default_value = 0.46
        nt_b.links.new(nz_b.outputs['Fac'], _mr_b.inputs['Value'])
        nt_b.links.new(_mr_b.outputs['Result'], _bs_b.inputs['Roughness'])
    bp_b.inputs["Distance"].default_value = 0.0008
    nt_b.links.new(tc_b.outputs["Object"], nz_b.inputs["Vector"])
    nt_b.links.new(nz_b.outputs["Fac"], ramp_b.inputs["Fac"])
    nt_b.links.new(nz_b.outputs["Fac"], bp_b.inputs["Height"])
    bsdf_b = nt_p.nodes.get("Principled BSDF") if False else nt_b.nodes.get("Principled BSDF")
    nt_b.links.new(ramp_b.outputs["Color"], bsdf_b.inputs["Base Color"])
    nt_b.links.new(bp_b.outputs["Normal"], bsdf_b.inputs["Normal"])
    m_eye, nt_e, pb_e = _mat(f"{name}_BerryEye")
    _pset(pb_e, ["Base Color"], (0.02, 0.02, 0.04, 1.0))
    _pset(pb_e, ["Roughness"], 0.75)
    _pset(pb_e, ["Metallic"], 0.0)

    # v123 真扫描蓝莓(声明式规格门控, 默认False=原程序化路径逐位不变)
    # v137 草莓分支(fruit=="strawberry"): 3颗真扫描草莓替代蓝莓, 其余路径逐位不变
    _straw_me = _scan_strawberry_mesh() if fruit == "strawberry" else None
    _scan_me = _scan_berry_mesh() if (scan_berry and _straw_me is None) else None
    if _straw_me is not None:
        from mathutils import Vector
        spots3 = []
        for i in range(3):
            a = TAU * i / 3 + 0.5 * math.pi + rng.uniform(-0.18, 0.18)
            rad = 0.035 * rng.uniform(0.92, 1.08)   # 两两弦距≥60mm > 2×躺放宽29mm
            spots3.append((rad * math.cos(a), rad * math.sin(a)))
        rots = [(0.25, 0.15), (1.35, 0.0), (-1.15, 0.0)]   # 立斜(花萼可见)/侧躺/对侧躺
        # v137.1 收尾刀(草稿视觉反馈): 缩比0.72→0.65(降"道具感"), 下沉6mm(去漂浮),
        # 红皮加清漆层(Coat 0.35/粗0.03)补"水润高光"——评审食欲感核心杠杆。
        _skin = bpy.data.materials.get("Original red strawberry skin")
        if _skin and _skin.node_tree:
            _bs = next((n for n in _skin.node_tree.nodes
                        if n.type == 'BSDF_PRINCIPLED'), None)
            if _bs:
                for iname, val in (("Coat Weight", 0.35), ("Coat Roughness", 0.03)):
                    _in = _bs.inputs.get(iname)
                    if _in is not None:
                        _in.default_value = val
        # v138 草莓去塑料化(外部评审"锐利镜面高光+均匀塑料红+籽无立体"三宗罪;
        # 参照真值+浆果材质科学: 真果皮=微糙哑光无镜面清漆层, 高光柔和漫射,
        # 颜色有未均匀成熟的深浅变化, 籽嵌入果皮带凹腔, 近缘透光)。
        # STRAW_MAT_V138=0 可回退 v137.1 行为(A/B 用)。
        import os as _os_v138
        if _os_v138.environ.get("STRAW_MAT_V138", "1") == "1" and _skin and _skin.node_tree:
            _bs = next((n for n in _skin.node_tree.nodes
                        if n.type == 'BSDF_PRINCIPLED'), None)
            if _bs:
                _nt = _skin.node_tree
                def _setv(node, names, val):
                    for nm in names:
                        _in = node.inputs.get(nm)
                        if _in is not None and not _in.is_linked:
                            _in.default_value = val
                            return True
                    return False
                # 1) 杀清漆层(塑料感第一根因), 降IOR光泽为软漫射
                _setv(_bs, ("Coat Weight",), 0.0)
                _setv(_bs, ("Roughness",), 0.55)
                _setv(_bs, ("Specular IOR Level", "Specular",), 0.35)
                # 2) 微粗糙斑驳: 打破均匀高光(噪点→Roughness, 0.45-0.65 摆动)
                if not _bs.inputs['Roughness'].is_linked:
                    _tc = _nt.nodes.new('ShaderNodeTexCoord')
                    _ns = _nt.nodes.new('ShaderNodeTexNoise')
                    _ns.inputs['Scale'].default_value = 180.0
                    _ns.inputs['Detail'].default_value = 4.0
                    _cr = _nt.nodes.new('ShaderNodeMapRange')
                    _cr.inputs['From Min'].default_value = 0.0
                    _cr.inputs['From Max'].default_value = 1.0
                    _cr.inputs['To Min'].default_value = 0.45
                    _cr.inputs['To Max'].default_value = 0.65
                    _nt.links.new(_tc.outputs['Object'], _ns.inputs['Vector'])
                    _nt.links.new(_ns.outputs['Fac'], _cr.inputs['Value'])
                    _nt.links.new(_cr.outputs['Result'], _bs.inputs['Roughness'])
                # 3) 颜色变化(未均匀成熟): 噪点乘 Base Color, 亮度 0.90-1.10
                _bc = _bs.inputs.get('Base Color')
                def _sock(collection, suffix):
                    for _s in collection:
                        if _s.identifier.endswith(suffix) or _s.name.endswith(suffix):
                            return _s
                    return None
                if _bc is not None and _bc.is_linked:
                    _lk = _bc.links[0] if _bc.links else None
                    if _lk is not None:
                        _src_sock = _lk.from_socket
                        _ns2 = _nt.nodes.new('ShaderNodeTexNoise')
                        _ns2.inputs['Scale'].default_value = 14.0
                        _ns2.inputs['Detail'].default_value = 6.0
                        _mr2 = _nt.nodes.new('ShaderNodeMapRange')
                        _mr2.inputs['From Min'].default_value = 0.0
                        _mr2.inputs['From Max'].default_value = 1.0
                        _mr2.inputs['To Min'].default_value = 0.90
                        _mr2.inputs['To Max'].default_value = 1.10
                        _nt.links.new(_tc.outputs['Object'], _ns2.inputs['Vector'])
                        _nt.links.new(_ns2.outputs['Fac'], _mr2.inputs['Value'])
                        _mix = _nt.nodes.new('ShaderNodeMix')
                        _mix.data_type = 'RGBA'
                        _mix.blend_type = 'MULTIPLY'
                        _s_fac = _sock(_mix.inputs, 'Factor')
                        _s_a = _sock(_mix.inputs, 'A_Color')
                        _s_b = _sock(_mix.inputs, 'B_Color')
                        _s_out = _sock(_mix.outputs, 'Result_Color')
                        if _s_a is not None and _s_out is not None:
                            _s_fac.default_value = 0.6
                            _nt.links.new(_src_sock, _s_a)
                            _nt.links.new(_mr2.outputs['Result'], _s_b)
                            _nt.links.new(_s_out, _bc)
                # 4) SSS 透光暖边(真实浆果近缘微透光)
                _setv(_bs, ("Subsurface Weight",), 0.08)
                _sss_r = _bs.inputs.get("Subsurface Radius")
                if _sss_r is not None and not _sss_r.is_linked:
                    _sss_r.default_value = (0.012, 0.004, 0.002)
                _setv(_bs, ("Subsurface Scale",), 0.02)
            # 种子 bump 强度回调(0.25→0.12: 彩色图作高度时红斑不应跟着隆起)
            _seed_m = bpy.data.materials.get("Original muted tan gold strawberry seed")
            if _seed_m and _seed_m.node_tree:
                for _n2 in _seed_m.node_tree.nodes:
                    if _n2.type == 'BUMP':
                        _n2.inputs['Strength'].default_value = 0.12
            # v138.1 叶蒂去剪纸感: 叶面 bump(彩色高频→高度0.1) + 粗糙度上调至0.72
            _fol_m = bpy.data.materials.get("Original green food foliage")
            if _fol_m and _fol_m.node_tree:
                _fbs = next((n for n in _fol_m.node_tree.nodes
                             if n.type == 'BSDF_PRINCIPLED'), None)
                _ftex = next((n for n in _fol_m.node_tree.nodes
                              if n.type == 'TEX_IMAGE' and n.image), None)
                if _fbs:
                    _setv(_fbs, ("Roughness",), 0.72)
                    if _ftex and _fbs.inputs['Normal'].is_linked is False:
                        _fbp = _fol_m.node_tree.nodes.new('ShaderNodeBump')
                        _fbp.inputs['Strength'].default_value = 0.1
                        _fol_m.node_tree.links.new(_ftex.outputs['Color'],
                                                   _fbp.inputs['Height'])
                        _fol_m.node_tree.links.new(_fbp.outputs['Normal'],
                                                   _fbs.inputs['Normal'])
                # 2b) 更细一层皮面噪点(scale 600)叠加微绒感, 与2)的斑驳层串联
                if _bs is not None and not _bs.inputs['Roughness'].is_linked:
                    _ns3 = _nt.nodes.new('ShaderNodeTexNoise')
                    _ns3.inputs['Scale'].default_value = 600.0
                    _ns3.inputs['Detail'].default_value = 3.0
                    _mr3 = _nt.nodes.new('ShaderNodeMapRange')
                    _mr3.inputs['From Min'].default_value = 0.0
                    _mr3.inputs['From Max'].default_value = 1.0
                    _mr3.inputs['To Min'].default_value = -0.04
                    _mr3.inputs['To Max'].default_value = 0.04
                    _ad3 = _nt.nodes.new('ShaderNodeMath')
                    _ad3.operation = 'ADD'
                    _nt.links.new(_tc.outputs['Object'], _ns3.inputs['Vector'])
                    _nt.links.new(_ns3.outputs['Fac'], _mr3.inputs['Value'])
                    _nt.links.new(_cr.outputs['Result'], _ad3.inputs[0])
                    _nt.links.new(_mr3.outputs['Result'], _ad3.inputs[1])
                    _nt.links.new(_ad3.outputs['Value'], _bs.inputs['Roughness'])
        # v137.2 种子/皮凸起(草稿评审"凸起感弱"): baseColor 高频→Bump, 真实改善
        # 种子触感并抬碗窗高频(G11 比值分母变大, 比值稳定化——非放松门槛)。
        for _mname, _bst in (("Original red strawberry skin", 0.15),
                             ("Original muted tan gold strawberry seed", 0.25)):
            _mm = bpy.data.materials.get(_mname)
            if not (_mm and _mm.node_tree):
                continue
            _tex = next((n for n in _mm.node_tree.nodes
                         if n.type == 'TEX_IMAGE' and n.image), None)
            _pbs = next((n for n in _mm.node_tree.nodes
                         if n.type == 'BSDF_PRINCIPLED'), None)
            if _tex and _pbs and not _pbs.inputs['Normal'].is_linked:
                _bp = _mm.node_tree.nodes.new('ShaderNodeBump')
                _bp.inputs['Strength'].default_value = _bst
                _mm.node_tree.links.new(_tex.outputs['Color'], _bp.inputs['Height'])
                _mm.node_tree.links.new(_bp.outputs['Normal'],
                                        _pbs.inputs['Normal'])
        for bi, (bx, by) in enumerate(spots3):
            ob_s = _obj(f"{name}_Berry{bi}", _straw_me)
            ob_s.scale = (0.65, 0.65, 0.65)   # 47mm→31mm含萼(碗内份量)
            ob_s.rotation_euler = (rots[bi][0] + rng.uniform(-0.12, 0.12),
                                   rots[bi][1] + rng.uniform(-0.12, 0.12),
                                   rng.uniform(0.0, TAU))
            ob_s.location = (bx, by, 0.02)
            bpy.context.view_layer.update()
            bbv = [ob_s.matrix_world @ Vector(c) for c in ob_s.bound_box]
            zmin = min(v.z for v in bbv)      # 运行时实测旋转后最低点, 手写零值禁令
            ob_s.location.z += (_surf(bx, by) - 0.006) - zmin   # 坐进粥面6mm
            ob_s.parent = root
    else:
        n_berry = 6  # v139.5: 6颗18mm(参照构图: 少而大而清晰)
        # v139 蓝莓照片级分层着色(用户两轮点名"蓝莓不对"且参照真值crop: 蓝黑靛底+
        # 明显灰白果粉哑光; 科学: 蓝色=近黑花青素皮上白蜡果粉的结构色, 无蓝色素,
        # Science Advances 2024 adk4219)。扫描贴图本身偏亮紫/无果粉/太平 → 着色器补层。
        # BERRY_MAT_V139=0 回退原贴图行为(A/B 用)。
        import os as _os_v139
        if _scan_me is not None and _os_v139.environ.get("BERRY_MAT_V139", "1") == "1":
            _bm = next((m for m in _scan_me.materials if m), None)
            if _bm and _bm.node_tree:
                _bnt = _bm.node_tree
                _bbs = next((n for n in _bnt.nodes if n.type == 'BSDF_PRINCIPLED'), None)
                def _sv9(node, names, val):
                    for nm in names:
                        _in9 = node.inputs.get(nm)
                        if _in9 is not None and not _in9.is_linked:
                            _in9.default_value = val
                            return _in9
                    return None
                if _bbs:
                    _btc = _bnt.nodes.new('ShaderNodeTexCoord')
                    # 1) 花青素暗底: 贴图 × 暗化去饱和系数(0.42,0.38,0.46), factor 0.8
                    _bc9 = _bbs.inputs.get('Base Color')
                    if _bc9 is not None and _bc9.is_linked:
                        _src9 = _bc9.links[0].from_socket
                        _dk = _bnt.nodes.new('ShaderNodeMix')
                        _dk.data_type = 'RGBA'; _dk.blend_type = 'MULTIPLY'
                        for _s9 in _dk.inputs:
                            if _s9.identifier.endswith('A_Color'):
                                _bnt.links.new(_src9, _s9); break
                        for _s9 in _dk.inputs:
                            if _s9.identifier.endswith('B_Color'):
                                _s9.default_value = (0.38, 0.33, 0.50, 1.0); break
                        _s_f = next((_s9 for _s9 in _dk.inputs if _s9.identifier.endswith('Factor')), None)
                        if _s_f is not None: _s_f.default_value = 0.85
                        _s_o = next((_s9 for _s9 in _dk.outputs if _s9.identifier.endswith('Result_Color')), None)
                        if _s_o is not None: _bnt.links.new(_s_o, _bc9)
                    # 2) 果粉结构色 Coat: 斑驳权重(噪点 0.35-0.9 × 逐果随机 0.8-1.0),
                    #    粗0.65 哑光, 色调灰白偏蓝
                    _ns9 = _bnt.nodes.new('ShaderNodeTexNoise')
                    _ns9.inputs['Scale'].default_value = 9.0
                    _ns9.inputs['Detail'].default_value = 3.0
                    _mr9 = _bnt.nodes.new('ShaderNodeMapRange')
                    _mr9.inputs['From Min'].default_value = 0.0
                    _mr9.inputs['From Max'].default_value = 1.0
                    _mr9.inputs['To Min'].default_value = 0.35
                    _mr9.inputs['To Max'].default_value = 0.75
                    _oi = _bnt.nodes.new('ShaderNodeObjectInfo')
                    _mr9b = _bnt.nodes.new('ShaderNodeMapRange')
                    _mr9b.inputs['From Min'].default_value = 0.0
                    _mr9b.inputs['From Max'].default_value = 1.0
                    _mr9b.inputs['To Min'].default_value = 0.8
                    _mr9b.inputs['To Max'].default_value = 1.0
                    _mu9 = _bnt.nodes.new('ShaderNodeMath')
                    _mu9.operation = 'MULTIPLY'
                    _bnt.links.new(_btc.outputs['Object'], _ns9.inputs['Vector'])
                    _bnt.links.new(_ns9.outputs['Fac'], _mr9.inputs['Value'])
                    _bnt.links.new(_oi.outputs['Random'], _mr9b.inputs['Value'])
                    _ns9d = _bnt.nodes.new('ShaderNodeTexNoise')
                    _ns9d.inputs['Scale'].default_value = 120.0
                    _ns9d.inputs['Detail'].default_value = 4.0
                    _mr9d = _bnt.nodes.new('ShaderNodeMapRange')
                    _mr9d.inputs['From Min'].default_value = 0.0
                    _mr9d.inputs['From Max'].default_value = 1.0
                    _mr9d.inputs['To Min'].default_value = 0.85
                    _mr9d.inputs['To Max'].default_value = 1.15
                    _mu9d = _bnt.nodes.new('ShaderNodeMath')
                    _mu9d.operation = 'MULTIPLY'
                    _bnt.links.new(_btc.outputs['Object'], _ns9d.inputs['Vector'])
                    _bnt.links.new(_ns9d.outputs['Fac'], _mr9d.inputs['Value'])
                    _bnt.links.new(_mr9.outputs['Result'], _mu9.inputs[0])
                    _bnt.links.new(_mr9d.outputs['Result'], _mu9d.inputs[0])
                    _bnt.links.new(_mr9b.outputs['Result'], _mu9d.inputs[1])
                    _cw2 = _bbs.inputs.get('Coat Weight')
                    if _cw2 is not None:
                        _bnt.links.new(_mu9d.outputs['Value'], _cw2)
                    _cw = _bbs.inputs.get('Coat Weight')
                    _sv9(_bbs, ("Coat Roughness",), 0.85)
                    # v139.8: 果粉微斑点——细噪调制Coat粗糙度0.72-0.95(打碎整团高光)
                    _cr9 = _bbs.inputs.get('Coat Roughness')
                    if _cr9 is not None and not _cr9.is_linked:
                        _ns9e = _bnt.nodes.new('ShaderNodeTexNoise')
                        _ns9e.inputs['Scale'].default_value = 600.0
                        _ns9e.inputs['Detail'].default_value = 4.0
                        _mr9e = _bnt.nodes.new('ShaderNodeMapRange')
                        _mr9e.inputs['From Min'].default_value = 0.0
                        _mr9e.inputs['From Max'].default_value = 1.0
                        _mr9e.inputs['To Min'].default_value = 0.72
                        _mr9e.inputs['To Max'].default_value = 0.95
                        _bnt.links.new(_btc.outputs['Object'], _ns9e.inputs['Vector'])
                        _bnt.links.new(_ns9e.outputs['Fac'], _mr9e.inputs['Value'])
                        _bnt.links.new(_mr9e.outputs['Result'], _cr9)
                    _ct = _bbs.inputs.get("Coat Tint")
                    if _ct is not None and not _ct.is_linked:
                        _ct.default_value = (0.88, 0.91, 0.97, 1.0)
                    # 3) 底皮粗糙度 0.63±细噪(漫射主导, 消镜面)
                    _ns9b = _bnt.nodes.new('ShaderNodeTexNoise')
                    _ns9b.inputs['Scale'].default_value = 320.0
                    _ns9b.inputs['Detail'].default_value = 4.0
                    _mr9c = _bnt.nodes.new('ShaderNodeMapRange')
                    _mr9c.inputs['From Min'].default_value = 0.0
                    _mr9c.inputs['From Max'].default_value = 1.0
                    _mr9c.inputs['To Min'].default_value = 0.60
                    _mr9c.inputs['To Max'].default_value = 0.72
                    _bnt.links.new(_btc.outputs['Object'], _ns9b.inputs['Vector'])
                    _bnt.links.new(_ns9b.outputs['Fac'], _mr9c.inputs['Value'])
                    _r9 = _bbs.inputs.get('Roughness')
                    if _r9 is not None:
                        _bnt.links.new(_mr9c.outputs['Result'], _r9)
                    # 4) 微表面 bump(scale 900, 弱) — 果皮细纹
                    if not _bbs.inputs['Normal'].is_linked:
                        _ns9c = _bnt.nodes.new('ShaderNodeTexNoise')
                        _ns9c.inputs['Scale'].default_value = 800.0
                        _ns9c.inputs['Detail'].default_value = 3.0
                        _bp9 = _bnt.nodes.new('ShaderNodeBump')
                        _bp9.inputs['Strength'].default_value = 0.09
                        _bnt.links.new(_btc.outputs['Object'], _ns9c.inputs['Vector'])
                        _bnt.links.new(_ns9c.outputs['Fac'], _bp9.inputs['Height'])
                        _bnt.links.new(_bp9.outputs['Normal'], _bbs.inputs['Normal'])
                    # 5) 掠射软绒 + 压镜面(0.15) + 近黑靛底加狠 + SSS
                    _sv9(_bbs, ("Sheen Weight",), 0.2)
                    _sv9(_bbs, ("Specular IOR Level", "Specular",), 0.05)
                    _sv9(_bbs, ("Subsurface Weight",), 0.10)
                    _sr9 = _bbs.inputs.get("Subsurface Radius")
                    if _sr9 is not None and not _sr9.is_linked:
                        _sr9.default_value = (0.008, 0.003, 0.002)
                    _sv9(_bbs, ("Subsurface Scale",), 0.015)
        if berry_scatter:
            # v131 评审两轮点名"颗粒过分规则/紫黑团状几何堆积"(v10/v11 #2致命缺陷)。
            # 原摆位是**等角72°正圆环**(a=TAU*i/(n-1), 半径仅±15%抖动) → 读作几何阵列。
            # 真实浆果: 不规则聚簇(半径分布宽)+相互接触+**随机倾角**(原只有z自转)。
            # 用拒绝采样保证两两不穿插(间隙≥0.15r), 避免"穿模"换"规则"。
            spots = []
            for _try in range(400):
                if len(spots) >= n_berry:
                    break
                rr = 0.024 * math.sqrt(rng.uniform(0.0, 1.0))   # 面积均匀, 非等半径环
                aa = rng.uniform(0.0, TAU)
                cx, cy = rr * math.cos(aa), rr * math.sin(aa)
                if all(math.hypot(cx - px, cy - py) > 0.0135 for px, py in spots):
                    spots.append((cx, cy))
            while len(spots) < n_berry:                          # 兜底: 采样不足则补中心附近
                spots.append((rng.uniform(-0.006, 0.006), rng.uniform(-0.006, 0.006)))
        else:
            spots = [(0.0, 0.002)]
            for i in range(n_berry - 1):
                a = TAU * i / (n_berry - 1) + rng.uniform(-0.15, 0.15)
                rad = 0.021 * rng.uniform(0.85, 1.15)
                spots.append((rad * math.cos(a), rad * math.sin(a)))
        for bi, (bx, by) in enumerate(spots):
            rb = 0.0090 * rng.uniform(0.95, 1.15)   # v139.5: 直径18mm(参照构图莓显著可见)
            bz = _surf(bx, by) + rb * 0.62
            if _scan_me is not None:
                # v139.2: 逐颗轮换独立单莓网格(parts)+缩放方差加宽(0.85-1.3) —
                # 消"同一三连串网格8实例"的克隆珠串感; 材质共享(逐果果粉随机仍在着色器层)。
                _parts = _SCAN_BERRY_CACHE.get("parts") or []
                _me_i = _parts[bi % len(_parts)] if _parts else _scan_me
                ob_s = _obj(f"{name}_Berry{bi}", _me_i)
                _sv9_scale = rb * rng.uniform(0.95, 1.15)
                ob_s.scale = (_sv9_scale, _sv9_scale, _sv9_scale)
                ob_s.location = (bx, by, _surf(bx, by) - rb * 0.05)   # v139.5: 下沉5%
                if berry_scatter:
                    ob_s.rotation_euler = (rng.uniform(-0.45, 0.45),
                                           rng.uniform(-0.45, 0.45),
                                           rng.uniform(0.0, TAU))   # 随机倾角破"整齐排列"
                elif berry_tilt > 0.0:
                    # v132 纯倾角(与XY散布可分离): 6颗共享同一扫描网格+同一花萼贴图,
                    # 原仅Z自转 → 花萼全朝上读作"重复/几何堆积"。加随机倾角破朝向一致,
                    # **XY摆位不动**(最小间距18.2mm不变, 无新穿模风险)。默认0=原行为。
                    ob_s.rotation_euler = (rng.uniform(-berry_tilt, berry_tilt),
                                           rng.uniform(-berry_tilt, berry_tilt),
                                           rng.uniform(0.0, TAU))
                else:
                    ob_s.rotation_euler = (0.0, 0.0, rng.uniform(0.0, TAU))
                # v139.6: 429v/颗扫描莓+强bump=分面"低多边形水果"观感(v139i vision判决
                # 决定性缺陷) → 渲染级细分2层(6颗×7k面, Cycles 开销可忽略), bump回落读作纹理
                _subd = ob_s.modifiers.new("Subd", 'SUBSURF')
                _subd.levels = 1
                _subd.render_levels = 2
                ob_s.parent = root
            else:
                me_s = _sphere_mesh(f"{name}_Berry{bi}_Mesh", rb, 1.0, 0.94, 0.86)
                ob_s = _obj(f"{name}_Berry{bi}", me_s)
                ob_s.data.materials.append(m_bb)
                ob_s.location = (bx, by, bz)
                ob_s.rotation_euler = (0.0, 0.0, rng.uniform(0.0, TAU))
                ob_s.parent = root
                me_c = _sphere_mesh(f"{name}_BerryEye{bi}_Mesh", 0.0052, 1.0, 1.0,
                                    0.38, u=12, v=8)   # r=5.2mm, z 压扁 0.38 → 花萼凹
                ob_c = _obj(f"{name}_BerryEye{bi}", me_c)
                ob_c.data.materials.append(m_eye)
                ob_c.location = (0.0, 0.0, rb * 0.86 - 0.0012)   # berry 局部顶
                ob_c.parent = ob_s

    # --- v140.1 燕麦片: 卷边程序化真片 26 半嵌入/浮置 + 10 碎屑(免费路线, OAT_V140=1)
    m_fl, nt_f, pb_f = _mat(f"{name}_Flake")
    _pset(pb_f, ["Base Color"], (0.80, 0.70, 0.50, 1.0))
    _pset(pb_f, ["Roughness"], 0.58)
    _pset(pb_f, ["Metallic"], 0.0)
    _pset(pb_f, ["Subsurface Weight"], 0.06)
    _srf = bsdf_p2 = pb_f.get("Subsurface Radius")
    if _srf is not None:
        _srf.default_value = (0.006, 0.004, 0.002)
    # 纤维纹理(Object X拉伸噪点) + 烘边(径向渐变) — 打破匀色
    tcf = nt_f.nodes.new("ShaderNodeTexCoord")
    nzf = nt_f.nodes.new("ShaderNodeTexNoise")
    nzf.inputs["Scale"].default_value = 90.0
    nzf.inputs["Detail"].default_value = 4.0
    mapf = nt_f.nodes.new("ShaderNodeMapping")
    mapf.inputs["Scale"].default_value = (0.35, 2.6, 1.0)   # 沿长轴拉伸=碾压纤维纹
    nt_f.links.new(tcf.outputs["Object"], mapf.inputs["Vector"])
    nt_f.links.new(mapf.outputs["Vector"], nzf.inputs["Vector"])
    bsdf_f = nt_f.nodes.get("Principled BSDF")
    bcf = bsdf_f.inputs['Base Color'] if bsdf_f else None
    if bcf is not None and not bcf.is_linked:
        mixf = nt_f.nodes.new("ShaderNodeMix")
        mixf.blend_type = 'MIX'
        mixf.data_type = 'RGBA'
        def _psock2(col, suffix):
            for _s in col:
                if _s.identifier.endswith(suffix):
                    return _s
            return None
        sA = _psock2(mixf.inputs, 'A_Color'); sB = _psock2(mixf.inputs, 'B_Color')
        sF2 = _psock2(mixf.inputs, 'Factor_Float'); sO2 = _psock2(mixf.outputs, 'Result_Color')
        if sA and sB and sO2:
            sA.default_value = (0.83, 0.72, 0.52, 1.0)   # 片心奶黄
            sB.default_value = (0.66, 0.53, 0.34, 1.0)   # 烘边深黄
            sF2.default_value = 0.4
            nt_f.links.new(nzf.outputs['Fac'], sF2)
            nt_f.links.new(sO2, bcf)
    if os.environ.get("OAT_V140", "1") == "1":
        _flake_variants = [_oat_flake_mesh(f"{name}_FlakeV{vi}", rng, vi) for vi in range(3)]
        for _fmv in _flake_variants:
            _fmv.materials.append(m_fl)
        n_fl = 26
        placed_f = []
        for fi in range(n_fl):
            for _try in range(60):
                a = rng.uniform(0.0, TAU)
                rad = 0.030 * math.sqrt(rng.uniform(0.0, 1.0)) ** 0.8
                fx, fy = rad * math.cos(a), rad * math.sin(a)
                if all(math.hypot(fx - px, fy - py) > 0.011 for px, py in placed_f):
                    placed_f.append((fx, fy))
                    break
            me_f = _flake_variants[fi % 3]
            ob_f = _obj(f"{name}_OatFlake{fi}", me_f)
            s = rng.uniform(0.75, 1.30) * (0.55 if fi >= 18 else 1.0)   # 后8片=碎屑
            ob_f.scale = (s, s * rng.uniform(0.8, 1.0), s)
            ob_f.location = (fx, fy, _surf(fx, fy) + (-0.0028 if fi < 16 else 0.0006))
            ob_f.rotation_euler = (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5),
                                   rng.uniform(0.0, TAU))
            ob_f.parent = root
    else:
        for fi in range(10):
            a = rng.uniform(0.0, TAU)
            rad = rng.uniform(0.028, 0.052)
            fx, fy = rad * math.cos(a), rad * math.sin(a)
            s = rng.uniform(0.8, 1.2)
            me_f = _sphere_mesh(f"{name}_Flake{fi}_Mesh", 1.0, 0.0075 * s, 0.0050 * s,
                                0.0012 * s, u=12, v=8)
            ob_f = _obj(f"{name}_Flake{fi}", me_f)
            ob_f.data.materials.append(m_fl)
            ob_f.location = (fx, fy, _surf(fx, fy) + 0.0008)
            ob_f.rotation_euler = (rng.uniform(-0.25, 0.25), rng.uniform(-0.25, 0.25),
                                   rng.uniform(0.0, TAU))
            ob_f.parent = root

    # --- v140.1 树莓×3(食品强调色, GPT R4: 树莓红2-3颗, 蓝莓群前侧左前过渡区)
    if os.environ.get("OAT_V140", "1") == "1":
        m_ras, nt_r, pb_r = _mat(f"{name}_Raspberry")
        _pset(pb_r, ["Base Color"], (0.22, 0.014, 0.010, 1.0))  # v142.7: 与mixr A一致
        _pset(pb_r, ["Roughness"], 0.62)                  # v142.4: 0.52→0.62 尘面
        _pset(pb_r, ["Coat Weight", "Clearcoat"], 0.05)   # 0.15→0.05
        _pset(pb_r, ["Coat Roughness"], 0.4)
        _pset(pb_r, ["Subsurface Weight"], 0.15)          # v142.5: 0.15(暗红基色上透光果肉, 视觉处方)
        _srr = pb_r.get("Subsurface Radius")
        if _srr is not None:
            _srr.default_value = (0.004, 0.0012, 0.0007)   # v142.6: 红透再收(防粉化)
        me_ras = _raspberry_mesh(f"{name}_RaspberryMesh", rng)
        me_ras.materials.append(m_ras)
        tcr = nt_r.nodes.new("ShaderNodeTexCoord")
        nzr = nt_r.nodes.new("ShaderNodeTexNoise")
        nzr.inputs["Scale"].default_value = 320.0   # v142: 核果级色变(核果~3mm→周期3mm)
        nzr.inputs["Detail"].default_value = 6.0
        _bpr = nt_r.nodes.new("ShaderNodeBump")           # v142.1: 核果间微凹凸(nzr创建后接线)
        _bpr.inputs["Strength"].default_value = 0.35
        _bpr.inputs["Distance"].default_value = 0.0010
        nt_r.links.new(nzr.outputs['Fac'], _bpr.inputs['Height'])
        bsr = nt_r.nodes.get("Principled BSDF")
        if bsr is not None:
            nt_r.links.new(_bpr.outputs['Normal'], bsr.inputs['Normal'])
        bcr = bsr.inputs['Base Color'] if bsr else None
        if bcr is not None and not bcr.is_linked:
            mixr = nt_r.nodes.new("ShaderNodeMix")
            mixr.blend_type = 'MIX'
            mixr.data_type = 'RGBA'
            sAr = next((_s for _s in mixr.inputs if _s.identifier.endswith('A_Color')), None)
            sBr = next((_s for _s in mixr.inputs if _s.identifier.endswith('B_Color')), None)
            sFr = next((_s for _s in mixr.inputs if _s.identifier.endswith('Factor_Float')), None)
            sOr = next((_s for _s in mixr.outputs if _s.identifier.endswith('Result_Color')), None)
            if sAr and sBr and sOr:
                sAr.default_value = (0.22, 0.014, 0.010, 1.0)   # v142.7: 杀蓝通道(粉=蓝高; 纯红浆果B≈10)
                sBr.default_value = (0.34, 0.040, 0.020, 1.0)     # 亮核果
                sFr.default_value = 0.5
                nt_r.links.new(nzr.outputs['Fac'], sFr)
                nt_r.links.new(sOr, bcr)
        for ri, (rx, ry) in enumerate([(-0.036, -0.030), (-0.008, -0.052), (-0.052, -0.006)]):
            ob_r = _obj(f"{name}_Raspberry{ri}", me_ras)
            sr = rng.uniform(0.9, 1.15)
            ob_r.scale = (sr, sr, sr * 0.9)
            ob_r.location = (rx, ry, _surf(rx, ry) + 0.0045)
            ob_r.rotation_euler = (rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3),
                                   rng.uniform(0.0, TAU))
            ob_r.parent = root

    root.location = loc
    return root


# ---------------------------------------------------------------- 2. 水果玻璃碗

_FRUIT_COLORS = {
    "Orange": (0.93, 0.45, 0.10, 1.0),   # 蜜瓜橙
    "Melon":  (0.80, 0.14, 0.12, 1.0),   # 西瓜红
    "Green":  (0.45, 0.72, 0.20, 1.0),   # 青蜜瓜
    "Yellow": (0.92, 0.78, 0.25, 1.0),   # 黄桃
    "Grape":  (0.42, 0.12, 0.45, 1.0),   # 葡萄紫
}


def fruit_bowl(loc=(0.0, 0.0, 0.0), r=0.09, name="FruitBowl", n_chunk=16, fill=1.0,
               ior=1.45, flare=0.0, wall=0.0025):
    """透明玻璃碗(Transmission 1.0 / Metallic 0 / Solidify 真实壁厚) + 彩色切块水果.

    flare: 0=近垂直筒(原状), 1=外扩浅碗(参照形态)。五项消融已锁定"碗读作黑环"真因=**折射**:
      IOR=1.0(关折射) 暗带 0.160→0.000; 整件移除碗 →0.000;
      而填充率/阴影射线/壁厚(实测2.50-2.60mm正常)/Solidify前法线(朝外128朝内0)/clamp=0 全部无效。
    机制: 原上壁 (0.97r,0.042)→(r,0.0621) **仅偏离垂直7.65°**, 2.5mm同心薄壳=柱透镜,
      浅视角掠入射→全内反射暗环(与技能记载"竖纹玻璃软化后近圆柱=柱透镜"同族)。
    flare=1 使上壁偏离垂直约37°, 破掉柱透镜条件。
    """
    rng = random.Random(_uid(name))
    h = 0.69 * r
    _k = max(0.0, min(1.0, float(flare)))

    # --- 玻璃碗: 开曲面 revolve (recalc=False 保法线朝外) + SOLIDIFY 真实壁厚
    prof = [(0.0, 0.0), ((0.42 - 0.12 * _k) * r, 0.0018),
            ((0.72 - 0.22 * _k) * r, 0.008), ((0.90 - 0.22 * _k) * r, 0.024),
            ((0.97 - 0.12 * _k) * r, 0.042), (r, h)]
    me_g = _revolve(f"{name}_GlassMesh", prof, segments=64,
                    cap_start=True, cap_end=False, recalc=False)
    m_g, nt_g, pb_g = _mat(f"{name}_Glass")
    _pset(pb_g, ["Base Color"], (1.0, 1.0, 1.0, 1.0))
    _pset(pb_g, ["Metallic"], 0.0)          # glTF metallic=1 陷阱: 必须显式清零
    _pset(pb_g, ["Transmission Weight", "Transmission"], 1.0)
    _pset(pb_g, ["Roughness"], 0.02)
    _pset(pb_g, ["IOR"], float(ior))   # 声明式入参: ior=1.0 可作"无折射"消融对照
    _pset(pb_g, ["Alpha"], 1.0)
    # v108 复用本仓既有玻璃约定: Is Shadow Ray → Transparent (防玻璃死黑阴影)。
    # 取证: 同场景饮用杯有此处理(34_commercial_repro.py:821-832), 暗<60占0.012;
    # 本碗原先**零命中**该处理, 暗<60占0.038(3倍), 且暗像素99%集中在两个**同色**大
    # 连通域(4732+2997 px, RGB均≈(30,26,21)) → 是玻璃投出的实心暗阴影, 不是果块。
    # 已证伪的假设: 填充率88%(降到12块/0.55后暗带仅0.182→0.170) / 零厚度壳(壁厚实测2.50-2.60mm正常)。
    _out_g = next((n for n in nt_g.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
    if _out_g is not None:
        _lp_g = nt_g.nodes.new("ShaderNodeLightPath")
        _tr_g = nt_g.nodes.new("ShaderNodeBsdfTransparent")
        _tr_g.inputs["Color"].default_value = (0.62, 0.62, 0.60, 1)   # 与饮用杯同值
        _mx_g = nt_g.nodes.new("ShaderNodeMixShader")
        nt_g.links.new(_lp_g.outputs["Is Shadow Ray"], _mx_g.inputs["Fac"])
        nt_g.links.new(pb_g.outputs[0], _mx_g.inputs[1])
        nt_g.links.new(_tr_g.outputs[0], _mx_g.inputs[2])
        nt_g.links.new(_mx_g.outputs[0], _out_g.inputs["Surface"])
    me_g.materials.append(m_g)
    root = _obj(name, me_g)
    sol = root.modifiers.new("Shell", "SOLIDIFY")
    sol.thickness = float(wall)             # 声明式壁厚入参(默认2.5mm, 实测min2.50/max2.60)
    sol.offset = -1.0                       # 法线朝外 → 向内增厚
    sol.use_even_offset = True
    sol.use_rim = True

    # --- 切块水果: 不规则倒角立方体, 微 SSS
    fruit_mats = {}
    for key, col in _FRUIT_COLORS.items():
        m, nt, pb = _mat(f"{name}_Fruit{key}")
        _pset(pb, ["Base Color"], col)
        _pset(pb, ["Roughness"], 0.35)
        _pset(pb, ["Metallic"], 0.0)
        _pset(pb, ["Subsurface Weight", "Subsurface"], 0.15)
        _pset(pb, ["Subsurface Radius"], (0.004, 0.003, 0.002))
        _pset(pb, ["Subsurface Scale"], 0.002)
        fruit_mats[key] = m
    keys = list(_FRUIT_COLORS.keys())
    # v107 填充量走**声明式规格入参**(specs/lifestyle_1l.json props[].args), 不再加 env 旋钮。
    # 外部双序盲评两序均把此碗读作"黑色圆环/不透明深色容器": 实测壁厚2.50-2.60mm正常
    # (已撤回零厚度壳假设), 沿口v0.00-0.30明亮(lum209-222)而v0.40-0.50暗(117/142),
    # 且填充率88%(顶高55.1mm/碗沿62.4mm) → 视线穿壁看到深色水果而非背景。
    n_chunk = int(n_chunk)
    for ci in range(n_chunk):
        s = rng.uniform(0.020, 0.030)
        zf = rng.uniform(0.70, 0.95)                       # z 向扁率
        hz = s * zf / 2.0                                  # 半高
        me_c = _box_mesh(f"{name}_Chunk{ci}_Mesh", s, s * rng.uniform(0.75, 1.0),
                         s * zf, bevel=0.0025, bevel_segments=2)
        ob_c = _obj(f"{name}_Chunk{ci}", me_c)
        ob_c.data.materials.append(fruit_mats[keys[ci % len(keys)]])
        # 外扩剖面使下部内腔收窄 → 果块分布半径同步收窄, 否则会穿碗壁
        rho = rng.uniform(0.0, 0.052) * (1.0 - 0.28 * _k)
        th = rng.uniform(0.0, TAU)
        cx, cy = rho * math.cos(th), rho * math.sin(th)
        _mr = 0.055 * (1.0 - 0.28 * _k)
        mound = float(fill) * 0.020 * max(0.0, 1.0 - (rho / _mr) ** 2)
        sink = min(0.5 * hz, 0.004)                        # 限深下沉, 底不穿桌
        ob_c.location = (cx, cy, 0.011 + mound + hz - sink)
        ob_c.rotation_euler = (rng.uniform(0.0, TAU), rng.uniform(0.0, TAU),
                               rng.uniform(0.0, TAU))
        ob_c.parent = root

    root.location = loc
    return root


# ---------------------------------------------------------------- 3. 吐司

def toast(loc=(0.0, 0.0, 0.0), n=2, name="Toast"):
    """n 片圆角吐司: 中心浅金→边缘烤色渐变(Generated 径向), crumb 噪波 bump 孔洞感, 两片略错位斜靠."""
    rng = random.Random(_uid(name))
    sx = sy = 0.095
    sz = 0.012

    m_t, nt_t, pb_t = _mat(f"{name}_Crumb")
    _pset(pb_t, ["Roughness"], 0.70)
    _pset(pb_t, ["Metallic"], 0.0)
    tc = nt_t.nodes.new("ShaderNodeTexCoord")
    sep = nt_t.nodes.new("ShaderNodeSeparateXYZ")
    nt_t.links.new(tc.outputs["Generated"], sep.inputs["Vector"])
    # d = 2*sqrt((x-0.5)^2 + (y-0.5)^2) → 径向距离 (0 中心 → ~1.4 角)
    m_subx = nt_t.nodes.new("ShaderNodeMath"); m_subx.operation = "SUBTRACT"
    m_subx.inputs[1].default_value = 0.5
    m_suby = nt_t.nodes.new("ShaderNodeMath"); m_suby.operation = "SUBTRACT"
    m_suby.inputs[1].default_value = 0.5
    m_sqx = nt_t.nodes.new("ShaderNodeMath"); m_sqx.operation = "MULTIPLY"
    m_sqy = nt_t.nodes.new("ShaderNodeMath"); m_sqy.operation = "MULTIPLY"
    m_add = nt_t.nodes.new("ShaderNodeMath"); m_add.operation = "ADD"
    m_sqrt = nt_t.nodes.new("ShaderNodeMath"); m_sqrt.operation = "SQRT"
    m_mul = nt_t.nodes.new("ShaderNodeMath"); m_mul.operation = "MULTIPLY"
    m_mul.inputs[1].default_value = 2.0
    nt_t.links.new(sep.outputs["X"], m_subx.inputs[0])
    nt_t.links.new(sep.outputs["Y"], m_suby.inputs[0])
    nt_t.links.new(m_subx.outputs[0], m_sqx.inputs[0])
    nt_t.links.new(m_subx.outputs[0], m_sqx.inputs[1])
    nt_t.links.new(m_suby.outputs[0], m_sqy.inputs[0])
    nt_t.links.new(m_suby.outputs[0], m_sqy.inputs[1])
    nt_t.links.new(m_sqx.outputs[0], m_add.inputs[0])
    nt_t.links.new(m_sqy.outputs[0], m_add.inputs[1])
    nt_t.links.new(m_add.outputs[0], m_sqrt.inputs[0])
    nt_t.links.new(m_sqrt.outputs[0], m_mul.inputs[0])
    ramp = _col_ramp(nt_t, f"{name}_BakeRamp", [
        (0.00, (0.87, 0.72, 0.46, 1.0)),   # 中心浅金 (参照: 烤色很浅)
        (0.55, (0.80, 0.62, 0.36, 1.0)),
        (0.85, (0.52, 0.30, 0.12, 1.0)),   # 边缘烤色
        (1.30, (0.38, 0.20, 0.08, 1.0)),
    ])
    nt_t.links.new(m_mul.outputs[0], ramp.inputs["Fac"])
    nz = nt_t.nodes.new("ShaderNodeTexNoise")   # crumb 孔洞
    nz.inputs["Scale"].default_value = 120.0
    nz.inputs["Detail"].default_value = 3.0
    bp = nt_t.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.40
    bp.inputs["Distance"].default_value = 0.0012
    nt_t.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nt_t.links.new(nz.outputs["Fac"], bp.inputs["Height"])
    bsdf = nt_t.nodes.get("Principled BSDF")
    nt_t.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    nt_t.links.new(bp.outputs["Normal"], bsdf.inputs["Normal"])

    root = None
    for si in range(n):
        me_s = _box_mesh(f"{name}_Slice{si}_Mesh", sx, sy, sz,
                         bevel=0.006, bevel_segments=4)
        ob_s = _obj(f"{name}_Slice{si}", me_s)
        ob_s.data.materials.append(m_t)
        if si == 0:
            ob_s.location = (0.0, 0.0, sz / 2.0)          # 平放, 底贴 z=0
            ob_s.rotation_euler = (0.0, 0.0, math.radians(12.0))
            root = ob_s
        elif si == 1:
            # 斜靠: 绕 Y 倾 7.5°, 最低角触桌面 (z=0), 抬起端底角搭在第一片沿口 (z≈0.012)
            a = math.radians(7.5)
            zc = (sx / 2.0) * math.sin(a) + (sz / 2.0) * math.cos(a)
            ob_s.location = (0.082, 0.004, zc)
            ob_s.rotation_euler = (0.0, a, math.radians(-5.0))
            ob_s.parent = root
        else:
            ob_s.location = (rng.uniform(-0.01, 0.01), rng.uniform(-0.01, 0.01),
                             sz / 2.0 + sz * si)
            ob_s.rotation_euler = (0.0, 0.0, math.radians(12.0 + rng.uniform(-6.0, 6.0)))
            ob_s.parent = root

    root.location = (loc[0], loc[1], loc[2] + sz / 2.0)   # 片0底贴 z=0: 自身偏移并入根定位
    return root


# ---------------------------------------------------------------- 4. 白瓷酱碟
def sauce_dish(loc=(0.0, 0.0, 0.0), r=0.032, fill=(0.85, 0.42, 0.12),
               name="SauceDish"):
    """白瓷小碟(旋转体浅井, 壁厚~3mm) + 酱料(传入 fill 色, 微弯月面, Roughness 0.25)."""
    h = 0.62 * r          # 碟高 (参照: 有深度的小碗)
    tw = 0.003
    fz = 0.55 * h         # 井底

    prof = [(0.0, 0.0), (0.68 * r, 0.0)]
    prof += _ellipse_pts(0.68 * r, 0.0, r, h, 6, skip_first=True)        # 外壁
    prof += [(r - tw, h)]                                                # 沿口
    prof += _ellipse_pts(r - tw, h, 0.52 * r, fz, 5, skip_first=True)    # 内壁
    prof += [(0.34 * r, fz - 0.0003), (0.0, fz - 0.0004)]                # 井底

    m_c, nt_c, pb_c = _mat(f"{name}_Porcelain")
    _pset(pb_c, ["Base Color"], (0.93, 0.92, 0.89, 1.0))
    _pset(pb_c, ["Roughness"], 0.12)
    _pset(pb_c, ["Metallic"], 0.0)
    _pset(pb_c, ["Coat Weight", "Clearcoat"], 0.30)
    me_d = _revolve(f"{name}_DishMesh", prof, segments=48)
    me_d.materials.append(m_c)
    root = _obj(name, me_d)

    # --- 酱料: 弯月面 (近壁上翘) + 低光泽
    rf = 0.50 * r
    z0 = fz + 0.0043
    prof_j = [(0.0, z0 - 0.0009), (0.40 * rf, z0 - 0.0007), (0.75 * rf, z0 - 0.0002),
              (0.93 * rf, z0 + 0.0008), (rf, z0 + 0.0026),                # 弯月面上翘
              (0.90 * rf, z0 - 0.0040), (0.50 * rf, z0 - 0.0044),
              (0.0, z0 - 0.0045)]                                          # 底嵌入井底
    m_j, nt_j, pb_j = _mat(f"{name}_Jam")
    _pset(pb_j, ["Base Color"], (fill[0], fill[1], fill[2], 1.0))
    _pset(pb_j, ["Roughness"], 0.25)
    _pset(pb_j, ["Metallic"], 0.0)
    _pset(pb_j, ["Coat Weight", "Clearcoat"], 0.15)
    me_j = _revolve(f"{name}_JamMesh", prof_j, segments=40)
    me_j.materials.append(m_j)
    ob_j = _obj(f"{name}_Jam", me_j)
    ob_j.parent = root

    root.location = loc
    return root


# ---------------------------------------------------------------- 5. 条纹餐巾

def napkin(loc=(0.0, 0.0, 0.0), w=0.22, d=0.16, name="Napkin"):
    """蓝白细斜条纹餐巾: 真图亚麻织纹(cloth_linen.jpg albedo+bump) + Wave BANDS 对角条纹叠加,
    低频正弦+noise 褶皱(谷底贴桌), 边缘非直线."""
    nx, ny = 49, 37
    amp = 0.0045

    def _zfun(x, y):
        u = 2.0 * x / w          # -1..1
        v = 2.0 * y / d
        # 褶皱: 谷底贴 z=0 (max(0,f)), 峰 ~4.5mm
        f = (math.sin(3.6 * u + 0.8 * math.sin(2.2 * v))
             * math.cos(2.8 * v + 0.7 * math.sin(1.9 * u)))
        z = amp * max(0.0, f) ** 1.15
        if f > 0.0:
            z += 0.0006
        # 边缘非完美直线: 只在边带做面内摆动
        ef = max(0.0, max(abs(u), abs(v)) - 0.75) / 0.25
        x2 = x + 0.0045 * ef * math.sin(4.0 * v + 1.3 * math.sin(2.2 * u))
        y2 = y + 0.0045 * ef * math.sin(3.4 * u - 0.8 * math.sin(1.9 * v))
        return (x2, y2, z)

    me_n = _grid_mesh(f"{name}_ClothMesh", w, d, nx, ny, _zfun)
    m_n, nt_n, pb_n = _mat(f"{name}_Cloth")
    _pset(pb_n, ["Roughness"], 0.85)
    _pset(pb_n, ["Metallic"], 0.0)
    _pset(pb_n, ["Sheen Weight", "Sheen"], 0.35)   # 微弱 sheen
    tc = nt_n.nodes.new("ShaderNodeTexCoord")
    bsdf = nt_n.nodes.get("Principled BSDF")

    # R20/R21 台账教训: 微米级程序化织纹展示尺寸物理不可解析 → 必须真图亚麻
    # (albedo sRGB + 同源 RGBToBW bump, 接法沿 33_sf_yogurt.cloth_table).
    # 22cm 餐巾前景特写: 1 tile ≈ 12cm 布面 → 织纹 ~1mm, 可解析.
    img_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                            "assets", "reference", "cloth_linen.jpg")
    m_uv = nt_n.nodes.new("ShaderNodeMapping")
    m_uv.inputs["Scale"].default_value = (1.8, 1.8, 1.0)
    nt_n.links.new(tc.outputs["Object"], m_uv.inputs["Vector"])
    if os.path.exists(img_path):
        img = bpy.data.images.load(img_path, check_existing=True)
        img.colorspace_settings.name = "sRGB"
        itex = nt_n.nodes.new("ShaderNodeTexImage")
        itex.image = img
        itex.extension = "REPEAT"
        nt_n.links.new(m_uv.outputs[0], itex.inputs["Vector"])
        rgb2bw = nt_n.nodes.new("ShaderNodeRGBToBW")
        nt_n.links.new(itex.outputs[0], rgb2bw.inputs[0])
        b_w = nt_n.nodes.new("ShaderNodeBump")     # 微织纹 bump
        b_w.inputs["Strength"].default_value = 0.30
        b_w.inputs["Distance"].default_value = 0.0004
        nt_n.links.new(rgb2bw.outputs[0], b_w.inputs["Height"])
        nt_n.links.new(b_w.outputs[0], bsdf.inputs["Normal"])
        linen_src = itex.outputs["Color"]
    else:
        print(f"[{name}] WARN cloth_linen.jpg 缺失, 退化为纯程序化白布")
        linen_src = None

    # 条纹: 厘米级宏观图案, 程序化 Wave BANDS 合法 (被判负的是微米级织纹)
    wv = nt_n.nodes.new("ShaderNodeTexWave")
    wv.wave_type = "BANDS"
    wv.bands_direction = "DIAGONAL"                # 参照: 斜向条纹
    wv.wave_profile = "SIN"
    wv.inputs["Scale"].default_value = 200.0       # 周期≈31mm → ~7 条蓝纹
    wv.inputs["Distortion"].default_value = 0.0
    # 条纹染色 tint: 白=保留亚麻本色, 蓝=染色叠在真图上
    ramp = _col_ramp(nt_n, f"{name}_StripeRamp", [
        (0.00, (1.00, 1.00, 1.00, 1.0)),
        (0.35, (1.00, 1.00, 1.00, 1.0)),
        (0.42, (0.42, 0.60, 0.78, 1.0)),           # 淡蓝灰条纹
        (0.58, (0.42, 0.60, 0.78, 1.0)),
        (0.65, (1.00, 1.00, 1.00, 1.0)),
        (1.00, (1.00, 1.00, 1.00, 1.0)),
    ])
    nt_n.links.new(tc.outputs["Object"], wv.inputs["Vector"])
    nt_n.links.new(wv.outputs["Fac"], ramp.inputs["Fac"])

    mix = nt_n.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.clamp_result = True
    mix.inputs[0].default_value = 1.0              # Factor
    col_in = [s for s in mix.inputs if s.type == "RGBA"]    # [A, B]
    col_out = [s for s in mix.outputs if s.type == "RGBA"]  # [Result]
    nt_n.links.new(ramp.outputs["Color"], col_in[1])        # B = 条纹 tint
    if linen_src is not None:
        nt_n.links.new(linen_src, col_in[0])                # A = 真图亚麻
    else:
        col_in[0].default_value = (0.90, 0.92, 0.95, 1.0)
    nt_n.links.new(col_out[0], bsdf.inputs["Base Color"])

    me_n.materials.append(m_n)
    root = _obj(name, me_n)

    root.location = loc
    return root


# ---------------------------------------------------------------- 自检

def _world_bbox(root):
    """子树汇总: (mesh对象数, 总顶点数, bbox_min, bbox_max, 材质名集合)."""
    stack = [root]
    objs = []
    while stack:
        o = stack.pop()
        objs.append(o)
        stack.extend(o.children)
    mn = [1e9, 1e9, 1e9]
    mx = [-1e9, -1e9, -1e9]
    nv = 0
    mats = set()
    for o in objs:
        if o.type != "MESH":
            continue
        nv += len(o.data.vertices)
        assert any(m for m in o.data.materials), f"{o.name} 无材质"
        for mloc in o.data.materials:
            if mloc:
                mats.add(mloc.name)
        mw = o.matrix_world
        for v in o.data.vertices:
            co = mw @ v.co
            for k in range(3):
                mn[k] = min(mn[k], co[k])
                mx[k] = max(mx[k], co[k])
    return objs, nv, tuple(mn), tuple(mx), mats


if __name__ == "__main__":
    built = [
        oatmeal_bowl(loc=(-0.15, -0.11, 0.0)),
        fruit_bowl(loc=(0.14, 0.13, 0.0)),
        toast(loc=(0.16, -0.07, 0.0)),
        sauce_dish(loc=(0.02, 0.04, 0.0)),
        napkin(loc=(-0.155, -0.115, 0.0)),
    ]
    bpy.context.view_layer.update()
    for root in built:
        objs, nv, mn, mx, mats = _world_bbox(root)
        print(f"[{root.name}] objs={len(objs)} verts={nv} "
              f"bbox_min=({mn[0]:+.4f},{mn[1]:+.4f},{mn[2]:+.4f}) "
              f"bbox_max=({mx[0]:+.4f},{mx[1]:+.4f},{mx[2]:+.4f}) "
              f"mats={len(mats)}")
        assert nv > 0, f"{root.name} 顶点数为 0"
        assert len(mats) > 0, f"{root.name} 无材质"
        tol = 0.002 if root.name.startswith("Napkin") else 0.005
        assert abs(mn[2]) < tol, f"{root.name} 底面 zmin={mn[2]:+.5f} 超差 (tol={tol})"
    print(f"[LIFESTYLE_PROPS] built={len(built)} ALL CHECKS PASSED")

def oat_scatter(loc=(0.0, 0.0, 0.0), n=12, name="OatScatter", broken=4):
    """v141 构图锚点: 桌面羊皮纸区散燕麦片(复用卷边真片生成器) + 碎屑.
    真实早餐场景: 粥碗旁散落几粒. 注册为布局prop → 门自动测距."""
    import os as _os
    rng = random.Random(_uid(name))
    root = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(root)
    m_fl, nt_f, pb_f = _mat(f"{name}_Flake")
    _pset(pb_f, ["Base Color"], (0.80, 0.70, 0.50, 1.0))
    _pset(pb_f, ["Roughness"], 0.58)
    _pset(pb_f, ["Metallic"], 0.0)
    _pset(pb_f, ["Subsurface Weight", "Subsurface"], 0.06)
    for fi in range(n):
        a = rng.uniform(0.0, TAU)
        rad = rng.uniform(0.006, 0.042)
        fx, fy = rad * math.cos(a), rad * math.sin(a)
        si = rng.randrange(3)
        me_f = _oat_flake_mesh(f"{name}_F{fi}_Mesh", rng, si)
        me_f.materials.append(m_fl)
        ob_f = _obj(f"{name}_F{fi}", me_f)
        ob_f.data.materials.append(m_fl)
        ob_f.location = (fx, fy, 0.0008 + rng.uniform(0.0, 0.0004))
        ob_f.rotation_euler = (rng.uniform(-0.45, 0.45), rng.uniform(-0.45, 0.45),
                               rng.uniform(0.0, TAU))
        ob_f.scale = (rng.uniform(0.62, 0.95),) * 3   # v142: 散片缩小(评审: 偏大偏厚)
        ob_f.parent = root
    for di in range(broken):
        a = rng.uniform(0.0, TAU)
        rad = rng.uniform(0.008, 0.045)
        fx, fy = rad * math.cos(a), rad * math.sin(a)
        me_d = _oat_flake_mesh(f"{name}_D{di}_Mesh", rng, rng.randrange(3))
        me_d.transform(Matrix.Diagonal((0.5, 0.45, 0.4, 1.0)))
        me_d.materials.append(m_fl)
        ob_d = _obj(f"{name}_D{di}", me_d)
        ob_d.data.materials.append(m_fl)
        ob_d.location = (fx, fy, 0.0006)
        ob_d.rotation_euler = (rng.uniform(-0.5, 0.5), rng.uniform(-0.5, 0.5),
                               rng.uniform(0.0, TAU))
        ob_d.parent = root
    root.location = loc
    return root
