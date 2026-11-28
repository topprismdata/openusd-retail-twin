# 30_pack_asset_line.py — 刀版图→参数化包装资产标准管线 (ESR Packaging Asset Line v1)
# 流程: spec 加载 → 刀版解析(折线自动检测+面板裁切) → 尺寸解算/复核 → 参数化建模
#       → 门禁(体积/印刷精度/照片比例) → 四视角QA渲染 → manifest 落盘
# 用法: Blender -b -P pipelines/pack_dieline/30_pack_asset_line.py -- --spec specs/pack_458.json [--qa-only]
# 新 SKU 接入 = 只写一份 specs/pack_<sku>.json, 零代码。
import bpy, bmesh, json, math, os, sys, random, hashlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
from pipelines.common.runtime_env import configure_cycles  # noqa: E402


def _configure_pack_cycles(sc):
    """按平台选择 Cycles 后端; 显式要求 CPU 时才回落 CPU (审计 B-5)。

    返回实际使用的 scene device ('GPU' / 'CPU')。
    """
    import os as _os
    force_cpu = _os.environ.get("PACK_FORCE_CPU", "0") == "1"
    if force_cpu:
        sc.cycles.device = 'CPU'
        return 'CPU'
    try:
        backend, ndev = configure_cycles(scene=sc, denoise=True)
        print(f"[pack] cycles backend={backend} devices={ndev}")
        return sc.cycles.device
    except Exception as e:
        print(f"[pack] GPU 配置失败, 回落 CPU: {type(e).__name__}: {e}")
        sc.cycles.device = 'CPU'
        return 'CPU'


argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
spec_path = os.path.join(BASE_DIR, argv[argv.index("--spec") + 1]) if "--spec" in argv else \
    os.path.join(BASE_DIR, "specs/pack_458.json")
QA_ONLY = "--qa-only" in argv
spec = json.load(open(spec_path))
SKU = spec["sku"]
TEX_DIR = os.path.join(BASE_DIR, spec.get("texture_dir", "assets/textures/pack"))
OUT_DIR = os.path.join(BASE_DIR, spec.get("out_dir", "output/pack_qa"), SKU)
os.makedirs(TEX_DIR, exist_ok=True)
os.makedirs(OUT_DIR, exist_ok=True)
fail = []

# ---------- 1) 刀版解析 ----------
from PIL import Image, ImageFilter
import numpy as np
dl = spec["dieline"]
src = Image.open(dl["image"]).convert("RGB")
A = np.asarray(src).astype(np.int32)
px = dl.get("panels_x")
if not px:   # 折线自动检测: 低饱和贯穿灰竖线聚簇
    band = A[dl["body_y"][0]:dl["body_y"][1]]
    sat = band.max(axis=2) - band.min(axis=2)
    lum = band.mean(axis=2)
    colscore = ((lum > 120) & (lum < 228) & (sat < 30)).mean(axis=0)
    cand = np.where(colscore > 0.75)[0]
    px, grp = [], []
    if len(cand):
        s = prev = cand[0]
        for c in cand[1:]:
            if c - prev > 6:
                grp.append(int((s + prev) / 2)); s = c
            prev = c
        grp.append(int((s + prev) / 2))
    px = grp
y0b, y1b = dl["body_y"]
y0r, y1r = dl["roof_y"]
pmap = dl["panel_map"]
panels = {}
mm_per_px = None
for face, seg in pmap.items():
    x0, x1 = px[seg] + 8, px[seg + 1] - 8   # R17: 内缩切掉刀版辅助线
    c = src.crop((x0, y0b, x1, y1b))
    p = os.path.join(TEX_DIR, f"{SKU}_{face}.png")
    c.save(p)
    panels[face] = p
roof_tex = {}
for face, seg in dl["roof"].items():        # R17: slopeF/slopeB/endL/endR
    x0, x1 = px[seg] + 8, px[seg + 1] - 8
    p = os.path.join(TEX_DIR, f"{SKU}_{face}.png")
    src.crop((x0, y0r + 15, x1, y1r - 12)).save(p)
    roof_tex[face] = p

# ---------- 1b) 分区HSV色校准 (R53: 用户指令显示色=实拍一致, albedo刀版真值让位) ----------
# spec match_view.zone_calib: [{"blue":{dH,s,v},"yellow":{...}}] 逐pass累积;
# 色相族掩膜+腐蚀5+羽化21只动族内像素; red 区不动(v2已判对齐); 纯numpy(Blender无cv2)
zone_calib = spec.get("match_view", {}).get("zone_calib") or []
if zone_calib:
    def _rgb2hsv(rgb):   # rgb float 0-255 → cv2刻度 H(0-179) S(0-255) V(0-255)
        mx = rgb.max(-1); mn = rgb.min(-1); c = mx - mn
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        h = np.zeros_like(mx)
        nz = c > 1e-6
        mr = nz & (mx == r); mg = nz & (mx == g) & ~mr; mb = nz & ~mr & ~mg
        h[mr] = (60 * ((g[mr] - b[mr]) / c[mr]) % 360) / 2
        h[mg] = (60 * ((b[mg] - r[mg]) / c[mg] + 2)) / 2
        h[mb] = (60 * ((r[mb] - g[mb]) / c[mb] + 4)) / 2
        s = np.where(mx > 1e-6, c / np.maximum(mx, 1e-6) * 255, 0)
        return h, s, mx

    def _huerotate(rgb, deg):   # 绕灰轴色相旋转(luma 0.213/0.715/0.072)
        th = np.deg2rad(deg); cA, sA = np.cos(th), np.sin(th)
        m = np.array([
            [0.213 + 0.787 * cA - 0.213 * sA, 0.715 - 0.715 * cA - 0.715 * sA, 0.072 - 0.072 * cA + 0.928 * sA],
            [0.213 - 0.213 * cA + 0.143 * sA, 0.715 + 0.285 * cA + 0.140 * sA, 0.072 - 0.072 * cA - 0.283 * sA],
            [0.213 - 0.213 * cA - 0.787 * sA, 0.715 - 0.715 * cA + 0.715 * sA, 0.072 + 0.928 * cA + 0.072 * sA]])
        return rgb @ m.T

    def _apply_zone(rgb, zone, dlt, wgt):
        # v: V(max通道)均匀缩放; s: 向灰轴收放 m'=M-f(M-c); dH: 色相旋转
        if dlt.get("v", 1.0) != 1.0:
            rgb = rgb * (1 + (dlt["v"] - 1) * wgt[..., None])
        if dlt.get("s", 1.0) != 1.0:
            f = 1 + (dlt["s"] - 1) * wgt
            mx = rgb.max(-1, keepdims=True)
            rgb = mx - f[..., None] * (mx - rgb)
        if dlt.get("dH", 0.0) != 0.0:
            # 向量化色相旋转: 按 wgt 分 12 档旋转后加权混合
            acc = np.zeros_like(rgb)
            for i in range(12):
                lo, hi = i / 12, (i + 1) / 12
                sel = ((wgt >= lo) & (wgt < hi))[..., None]
                if not sel.any():
                    continue
                acc += sel * _huerotate(rgb, dlt["dH"] * (lo + hi) / 2)
            rgb = np.where(wgt[..., None] > 0, acc, rgb)
        return rgb

    for tp in list(panels.values()) + list(roof_tex.values()):
        im = np.asarray(Image.open(tp).convert("RGB")).astype(np.float32)
        Hh, Ss, Vv = _rgb2hsv(im)
        for cal in zone_calib:
            for zone, dlt in cal.items():
                if zone == "blue":
                    fm = (Hh >= 100) & (Hh <= 135) & (Ss > 60)
                elif zone == "yellow":
                    fm = (Hh >= 18) & (Hh <= 40) & (Ss > 60)
                else:
                    continue
                if fm.sum() < 300:
                    continue
                mi = Image.fromarray(fm.astype(np.uint8) * 255)
                mi = mi.filter(ImageFilter.MinFilter(5))                 # 腐蚀5
                wgt = np.asarray(mi.filter(ImageFilter.GaussianBlur(10)), dtype=np.float32) / 255.0  # 羽化
                im = _apply_zone(im, zone, dlt, wgt)
        Image.fromarray(np.clip(im, 0, 255).astype(np.uint8)).save(tp)
    print(f"[PACK] zone_calib applied: {len(zone_calib)} pass(es)")

# ---------- 2) 尺寸解算/复核 ----------
D = spec["dims_mm"]
w, d, hb, hr = D["w"] / 1000, D["d"] / 1000, D["h_body"] / 1000, D["h_ridge"] / 1000
hf = D.get("h_fin", 0) / 1000   # R40: 端封鳍片高(实拍图定案: 低坡12+立鳍14, 旧24全坡=拓扑错误)
V = spec["volume_ml"] / 1e6
fill = spec.get("fill", 0.93)
V_model = w * d * hb * fill
resid = abs(V_model - V) / V
front_img = Image.open(panels["front"])
dpi_front = front_img.size[0] / (D["w"] / 25.4)   # px/inch
aspect = (hb + hr + hf) / w   # R40: 总高含鳍
ok_vol = resid <= spec["gates"]["volume_residual_max"]
ok_dpi = dpi_front >= spec["gates"]["min_dpi"]
if not ok_vol: fail.append(f"volume_residual {resid:.3f} > {spec['gates']['volume_residual_max']}")
if not ok_dpi: fail.append(f"dpi {dpi_front:.0f} < {spec['gates']['min_dpi']}")
print(f"[PACK] V_model={V_model*1e6:.1f}mL resid={resid:.3f} dpi={dpi_front:.0f} aspect={aspect:.2f}")

# ---------- 3) 参数化建模 (gable_top 模板) ----------
def _face_mat(name, tex_path, rough=None):
    matcfg = spec.get("material", {})
    if rough is None:
        rough = matcfg.get("roughness", 0.38)  # R18: GPT基准0.48, spec声明
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        img = bpy.data.images.load(tex_path)
        img.colorspace_settings.name = "sRGB"
        t = m.node_tree.nodes.new("ShaderNodeTexImage")
        t.image = img; t.extension = 'EXTEND'
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Roughness"].default_value = rough
        if "Specular IOR Level" in b.inputs:
            b.inputs["Specular IOR Level"].default_value = matcfg.get("ior_level", 0.5)
        if "Coat Weight" in b.inputs:
            b.inputs["Coat Weight"].default_value = matcfg.get("coat_weight", 0.0)
        m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    return m

def build_gable_top():
    """R41 标准利乐屋顶包拓扑 (用户实拍+原刀版定案):
    1) 四墙身 2) 前后坡面板(竖高hr=13) 3) 山墙两端三角端封板(endL/endR纹理)
    4) 全长连续脊鳍(坡面板过脊折线延伸hf=14, 鳍面印「此处开启/本品需冷藏」=坡面纹理顶部30%带, v_fold=0.70)
    脊沿X(A端↔C端), 墙: -Y=front(D), +Y=back(B), -X=wallL(A条码), +X=wallR(C卖点)"""
    bm = bmesh.new()
    x0, x1 = -w / 2, w / 2
    y0, y1 = -d / 2, d / 2
    z0, z1, z2 = 0.0, hb, hb + hr
    z3 = z2 + hf
    # R77b: 鳍前倾+顶宽卷边(实拍细节: 脊鳍前倾~20°, 顶缘双纸层卷弧r≈2.5mm带高光渐变)
    _cb = spec.get('carton_build') or {}
    LEAN = math.radians(_cb.get('fin_lean_deg', 20))
    _t = _cb.get('fin_halfgap_mm', 1.5) / 1000.0     # 半层距(总厚3mm)
    _r = _cb.get('fin_roll_r_mm', 2.5) / 1000.0      # 卷弧半径
    _u1 = max(hf - _r, hf * 0.6)                      # 折线过渡痕(卷弧起点)
    _tf = lambda dy, dz: (dy*math.cos(LEAN) - dz*math.sin(LEAN), dy*math.sin(LEAN) + dz*math.cos(LEAN))
    _arc = [(_tf(-_t*math.cos(a*math.pi/4), _u1 + _r*math.sin(a*math.pi/4))) for a in range(5)]  # a=0..4 → 0,45,90,135,180°
    V = bm.verts.new
    vs = [V(p) for p in [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),          # 0-3 底
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),          # 4-7 墙顶
        (x0, 0, z2), (x1, 0, z2),                                        # 8-9 脊
        (x0, _tf(-_t, 0)[0], z2 + _tf(-_t, 0)[1]),                       # 10 鳍前顶基(斜接脊)
        (x0, _arc[0][0], z2 + _arc[0][1]),                               # 11 卷弧起点(前层顶)
        (x0, _arc[1][0], z2 + _arc[1][1]),                               # 12
        (x0, _arc[2][0], z2 + _arc[2][1]),                               # 13 crest
        (x0, _arc[3][0], z2 + _arc[3][1]),                               # 14
        (x0, _arc[4][0], z2 + _arc[4][1]),                               # 15 卷弧终点(后层顶)
        (x1, _tf(-_t, 0)[0], z2 + _tf(-_t, 0)[1]),                       # 16 鳍前顶基(x1)
        (x1, _arc[0][0], z2 + _arc[0][1]),                               # 17
        (x1, _arc[1][0], z2 + _arc[1][1]),                               # 18
        (x1, _arc[2][0], z2 + _arc[2][1]),                               # 19 crest
        (x1, _arc[3][0], z2 + _arc[3][1]),                               # 20
        (x1, _arc[4][0], z2 + _arc[4][1])]]                              # 21 卷弧终点
    fk = bm.faces.layers.int.new("fk")   # R78g: bmesh→mesh面序不保证=创建序, 显式打键解耦
    for _f, _kid in [(bm.faces.new((vs[0], vs[3], vs[2], vs[1])), 0),
                     (bm.faces.new((vs[0], vs[1], vs[5], vs[4])), 1),
                     (bm.faces.new((vs[2], vs[3], vs[7], vs[6])), 2),
                     (bm.faces.new((vs[3], vs[0], vs[4], vs[7])), 3),
                     (bm.faces.new((vs[1], vs[2], vs[6], vs[5])), 4),
                     (bm.faces.new((vs[4], vs[5], vs[9], vs[8])), 5),
                     (bm.faces.new((vs[6], vs[7], vs[8], vs[9])), 6),
                     (bm.faces.new((vs[4], vs[8], vs[7])), 7),
                     (bm.faces.new((vs[5], vs[6], vs[9])), 8)]:
        _f[fk] = _kid
    for _f, _kid in [(bm.faces.new((vs[8], vs[9], vs[17], vs[11])), 9),
                     (bm.faces.new((vs[11], vs[17], vs[18], vs[12])), 10),
                     (bm.faces.new((vs[12], vs[18], vs[19], vs[13])), 11),
                     (bm.faces.new((vs[13], vs[19], vs[20], vs[14])), 12),
                     (bm.faces.new((vs[14], vs[20], vs[21], vs[15])), 13),
                     (bm.faces.new((vs[9], vs[8], vs[15], vs[21])), 14)]:
        _f[fk] = _kid
    # R78g2: 法线翻转按kid取面(顺序解耦)
    _fm = {f[fk]: f for f in bm.faces}
    if _fm[9].normal.y > 0: _fm[9].normal_flip()
    if _fm[14].normal.y < 0: _fm[14].normal_flip()
    mesh = bpy.data.meshes.new(f"Pack_{SKU}")
    bm.to_mesh(mesh); bm.free()
    ob = bpy.data.objects.new(f"Pack_{SKU}", mesh)
    ob.location = (0, 0, 0)
    bpy.context.collection.objects.link(ob)
    uvl = ob.data.uv_layers.new(name="UVMap")
    keys = ["bottom", "front", "back", "wallL", "wallR", "slopeF", "slopeB", "endL", "endR", "finF", "rollA", "rollB", "rollC", "rollD", "finB"]
    V_FOLD = 0.725  # R52: 数值定位折线=纹理顶27.7%(行差分峰值176/635, 白带过渡23.3%), 旧0.70偏5%=鳍底采样进坡面艺术=吸管孔区叠印
    fkl = ob.data.attributes.get("fk")
    for pi, poly in enumerate(ob.data.polygons):
        kid = fkl.data[pi].value if fkl else 0
        key = keys[kid] if kid < len(keys) else "bottom"
        for li in poly.loop_indices:
            co = ob.data.vertices[ob.data.loops[li].vertex_index].co
            if key in ("front", "back"):
                u = 0.01 + 0.98 * (co.x - x0) / w
                v = 0.01 + 0.98 * min((co.z - z0) / z1, 0.99)
            elif key in ("wallL", "wallR"):
                u = 0.01 + 0.98 * (co.y - y0) / d
                v = 0.01 + 0.98 * min((co.z - z0) / z1, 0.99)
            elif key in ("slopeF", "slopeB", "finF", "finB"):
                u = 0.01 + 0.98 * (co.x - x0) / w
                if key.startswith("fin"):
                    # R77b: 按鳍面自身坐标归一化到全带 — 前倾后世界z压缩(cos20), 旧式只采到0.929=箭头/冷藏段丢失
                    _dzf = (co.z - z2) / math.cos(LEAN) if LEAN > 1e-6 else (co.z - z2)
                    v = V_FOLD + min(_dzf / max(_u1, 1e-6), 1.0) * (0.99 - V_FOLD)
                else:
                    v = 0.01 + (co.z - z1) / max(hr, 1e-6) * (V_FOLD - 0.01)
            elif key in ("endL", "endR"):
                u = 0.01 + 0.98 * (co.y - y0) / d
                v = 0.01 + 0.98 * min((co.z - z1) / max(z2 - z1, 1e-6), 0.99)
            else:
                u, v = 0.004, 0.5
            # R79: 背/左/左端/后坡从外侧看屏幕右方向与front/right相反, u需水平翻转否则整面反字
            if key in ("back", "wallL", "endL", "slopeB", "finB"):
                u = 1.0 - u
            uvl.data[li].uv = (u, v)
    white = bpy.data.materials.get(f"Mat_{SKU}_White")
    if white is None:
        white = bpy.data.materials.new(f"Mat_{SKU}_White")
        white.use_nodes = True
        white.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.965, 0.958, 0.945, 1)
        white.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.42
    slots = [white] + [_face_mat(f"Mat_{SKU}_{k}", panels[k]) for k in pmap] + \
            [_face_mat(f"Mat_{SKU}_{k}", os.path.join(TEX_DIR, f"{SKU}_{k}.png"))
             for k in dl["roof"]]
    slot_of = {"bottom": 0, "front": 1, "back": 2, "wallL": 3, "wallR": 4,
               "slopeF": 5, "slopeB": 6, "endL": 7, "endR": 8,
               "finF": 5, "finB": 6}   # R41: 鳍=坡面板延伸, 共用坡纹理
    for m in slots:
        ob.data.materials.append(m)
    if os.environ.get("FIN_DEBUG"):
        red = bpy.data.materials.new("DBG_red")
        red.use_nodes = True
        red.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 0, 0, 1)
        ob.data.materials.append(red)
        _fk2 = ob.data.attributes.get("fk")
        if os.environ.get("FIN_DEBUG"):
            import colorsys
            for pi, poly in enumerate(ob.data.polygons):
                kid_v = _fk2.data[pi].value if _fk2 else -1
                r_, g_, b_ = colorsys.hsv_to_rgb((kid_v*0.13)%1.0, 1.0, 1.0)
                poly.material_index = 0
                dbg_m = bpy.data.materials.get(f"DBG_{kid_v}")
                if dbg_m is None:
                    dbg_m = bpy.data.materials.new(f"DBG_{kid_v}")
                    dbg_m.use_nodes = True
                    dbg_m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (r_, g_, b_, 1)
                    ob.data.materials.append(dbg_m)
                poly.material_index = len(ob.data.materials) - 1

    fkl2 = ob.data.attributes.get("fk")
    for pi, poly in enumerate(ob.data.polygons):
        kid = fkl2.data[pi].value if fkl2 else 0
        poly.material_index = slot_of.get(keys[kid] if kid < len(keys) else "bottom", 0)
    if os.environ.get("FIN_DEBUG"):   # R78g3: 探针必须插在权威槽位循环之后(此前三次探针全被覆盖, 从未生效)
        dbg = os.environ["FIN_DEBUG"]
        if dbg == "2":
            ob.data.materials[1] = ob.data.materials[0]   # slot1改白=隐身
        for pi, poly in enumerate(ob.data.polygons):
            kid = fkl2.data[pi].value if fkl2 else -1
            if dbg == "2":
                poly.material_index = 0 if kid == 9 else 1   # 0=红只留finF, 1=白隐(纯白底)
            elif kid == 9:
                pass   # R78g4: finF走正常材质(UV已验证0.725-0.977), 探针完成使命
    return ob

# ---------- 4) 场景+四视角QA ----------
def setup_and_render(ob):
    sc = bpy.context.scene
    sc.render.resolution_x = sc.render.resolution_y = 900
    sc.render.image_settings.file_format = 'PNG'
    sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
    sc.world.node_tree.nodes["Background"].inputs[1].default_value = 0.9
    for pos, e in [((1.5, -1.6, 1.4), 3.0), ((-1.5, -1.2, 0.9), 1.2), ((0, 1.5, 1.2), 0.8)]:
        bpy.ops.object.light_add(type="AREA", location=pos)
        L = bpy.context.active_object
        L.data.size = 0.8; L.data.energy = e
        L.constraints.new("TRACK_TO").target = ob
    sc.cycles.samples = 128
    # 2026-11-18 审计 B-5: 原代码 try/except pass 静默锁 CPU (except 永不触发, 因为 'CPU' 恒合法),
    # 与 README 的 "Metal-RT" 声明及按 Metal 标定的门禁阈值 (specs/pack_458.json tol) 矛盾。
    # 现在: 默认走 GPU (后端由 runtime_env 自动选), 仅在显式要求时回落 CPU, 且必须打印。
    _dev = _configure_pack_cycles(sc)
    print(f"[pack] cycles device={_dev}")
    views = {"front": (0, -0.34, 0.08), "side": (0.34, -0.05, 0.08),
             "three_quarter": (0.26, -0.26, 0.16), "top": (0.001, -0.16, 0.30)}
    from mathutils import Vector
    ctr = Vector((0, 0, (hb + hr) / 2))
    for nm, loc in views.items():
        bpy.ops.object.camera_add(location=loc)
        cam = bpy.context.active_object
        cam.data.lens = 50
        cam.rotation_euler = (ctr - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        sc.camera = cam
        sc.render.filepath = os.path.join(OUT_DIR, f"qa_{nm}.png")
        bpy.ops.render.render(write_still=True)
        bpy.data.objects.remove(cam)

# ---------- 4b) 白底主图 hero 模式 (Light Path 世界分离 + 正交正面) ----------
def hero_render(ob):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'   # Shadow Catcher 是 Cycles 专属; 工厂默认 EEVEE 会静默忽略 (本bug根因)
    sc.cycles.samples = int(os.environ.get("MV_SAMPLES", "192")) if "--match" in argv else 192
    sc.cycles.device = 'CPU'      # 单实例安全档 (Metal 并发纪律)
    sc.render.resolution_x = int(os.environ.get("MV_RES_X", "1800")) if "--match" in argv else 1800
    sc.render.resolution_y = int(os.environ.get("MV_RES_Y", "2400")) if "--match" in argv else 2400
    sc.render.image_settings.file_format = 'PNG'
    mv0 = spec.get("match_view") or {}
    sc.view_settings.view_transform = mv0.get("view_transform", "Standard")   # R42: match可声明AgX(实拍对账需胶片滚降)
    sc.view_settings.look = mv0.get("look", "None")   # R56: AgX - Punchy(实拍艳黄S254V230超出AgX base可显色域)
    sc.view_settings.exposure = mv0.get("exposure", 0.0)   # R42: match曝光spec驱动(亮度主导变量, 均值差-67→0锚实拍)
    sc.render.film_transparent = True              # 世界对相机透明; PIL后合成纯白 (shadow catcher 配套)
    sc.world = bpy.data.worlds.new("HeroW")
    sc.world.use_nodes = True
    nt = sc.world.node_tree
    nt.nodes.clear()
    outn = nt.nodes.new("ShaderNodeOutputWorld")
    bg_cam = nt.nodes.new("ShaderNodeBackground")   # 相机射线: 纯白 255
    bg_cam.inputs[0].default_value = (1.0, 1.0, 1.0, 1)   # inputs[0]=Color! (默认0.8灰是本bug根因)
    bg_cam.inputs[1].default_value = 1.0
    bg_lit = nt.nodes.new("ShaderNodeBackground")   # 照明: 0.85 留墨色余量
    bg_lit.inputs[0].default_value = (1.0, 1.0, 1.0, 1)
    bg_lit.inputs[1].default_value = 0.85
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg_lit.outputs["Background"], mix.inputs[1])   # fac=0→非相机射线
    nt.links.new(bg_cam.outputs["Background"], mix.inputs[2])   # fac=1→相机射线 (实测语义)
    nt.links.new(mix.outputs["Shader"], outn.inputs["Surface"])
    # Shadow Catcher 地面: 只捕接触阴影, 本体不显灰 (合成后=纯白+自然投影)
    bpy.ops.mesh.primitive_plane_add(size=6, location=(0, 0, -0.001))
    g = bpy.context.active_object
    g.is_shadow_catcher = True
    # 灯光预算账: 世界0.85→纸面≈0.83线性(显示≈235); 形塑灯合计 1.75W 低强度防爆白
    H = hb + hr
    mv = spec.get("match_view")
    rig = (mv or {}).get("rig")   # R18: GPT行业配方(HDRI底光0.15-0.25+三点受控光), docs/reviews/gpt_consult_recipe.txt
    if rig:
        if rig.get("hdri"):
            env = nt.nodes.new("ShaderNodeTexEnvironment")
            eimg = bpy.data.images.load(os.path.join(BASE_DIR, rig["hdri"]))
            eimg.colorspace_settings.name = "Non-Color"
            env.image = eimg
            if rig.get("hdri_rot_deg"):   # GPT: 旋转避开正面大面积白色反射
                mp = nt.nodes.new("ShaderNodeMapping")
                mp.inputs["Rotation"].default_value[2] = math.radians(rig["hdri_rot_deg"])
                nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
            nt.links.new(env.outputs["Color"], bg_lit.inputs[0])
        bg_lit.inputs[1].default_value = rig.get("world", 0.85)
        for lt in rig["lights"]:
            bpy.ops.object.light_add(type="AREA", location=lt["pos"])
            L = bpy.context.active_object
            L.data.shape = 'RECTANGLE' if lt.get("size_y") else 'SQUARE'
            L.data.size = lt["size"]
            if lt.get("size_y"):
                L.data.size_y = lt["size_y"]
            L.data.energy = lt["energy"]
            if lt.get("color"):
                L.data.color = tuple(lt["color"])
    else:
        for pos, size, e in [((0.5, -1.1, H * 1.6), 1.4, 0.65),
                             ((-0.9, -0.7, H * 0.8), 1.2, 0.30),
                             ((0.8, 0.9, H * 1.1), 1.0, 0.40)]:
            bpy.ops.object.light_add(type="AREA", location=pos)
            L = bpy.context.active_object
            L.data.size = size
            L.data.energy = e
            L.constraints.new("TRACK_TO").target = ob
    _dev = _configure_pack_cycles(sc)
    print(f"[pack] cycles device={_dev}")
    from mathutils import Vector
    ctr = Vector((0, 0, H / 2))
    views = [("hero_front_ortho", None, 50), ("hero_three_quarter", (0.34, -0.42, H * 0.75), 60),
             ("hero_side", (0.55, -0.06, H * 0.50), 60)]
    if mv:
        views.append(("hero_match_real", tuple(mv["loc_m"]), mv.get("lens_mm", 50)))
    if "--match" in argv:   # 只渲实拍同机位视图
        views = [v for v in views if v[0] == "hero_match_real"]
    for nm, loc, lens_mm in views:
        g.hide_render = loc is None   # 正交主图: 纯白浮盒
        bpy.ops.object.camera_add()
        cam = bpy.context.active_object
        if loc is None:
            cam.data.type = 'ORTHO'
            cam.data.ortho_scale = H / 0.82   # 高填充 0.82 (竖幅大边=高)
            cam.location = (0, -1.0, H / 2)
            cam.rotation_euler = (math.radians(90), 0, 0)
        else:
            cam.data.lens = lens_mm
            cam.location = loc
            cam.data.clip_start = 0.02   # R77: 28mm近距0.118m, 默认0.1近裁剪面会削掉盒体
            q = (ctr - Vector(loc)).to_track_quat("-Z", "Y")
            _roll = math.radians(mv.get("roll_deg", 0)) if mv else 0
            if _roll:
                from mathutils import Quaternion
                q = q @ Quaternion((0.0, 0.0, 1.0), _roll)   # R78: 实拍手持侧倾(绕视轴roll)
            cam.rotation_euler = q.to_euler()
        sc.camera = cam
        sc.render.filepath = os.path.join(OUT_DIR, f"{nm}.png")
        bpy.ops.render.render(write_still=True)
        img = Image.open(sc.render.filepath).convert("RGBA")
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        out = Image.alpha_composite(white, img).convert("RGB")
        # R72: post_grade 移至 18_post_grade.py (系统Python) — Blender内numpy分族运算产生黑块伪影;
        # spec match_view.post_grade 仍为声明式因子源, 渲染后链式调用: python3 18_post_grade.py
        out.save(sc.render.filepath)
        hero_gates(sc.render.filepath, ortho=(loc is None))
        bpy.data.objects.remove(cam)

def hero_gates(path, ortho=True):
    a = np.asarray(Image.open(path).convert("RGB")).astype(np.int32)
    lum = a.mean(axis=2)
    h, wd = lum.shape
    if ortho:   # GS1 主图: 四角纯白 + 剪影填充满格
        corners = np.concatenate([lum[:40, :40].ravel(), lum[:40, -40:].ravel(),
                                  lum[-40:, :40].ravel(), lum[-40:, -40:].ravel()])
        sub = lum < 245
        rows = np.where(sub.mean(axis=1) > 0.005)[0]
        fill_h = (rows[-1] - rows[0] + 1) / h if len(rows) else 0
    else:       # 透视: 上角纯白; 填充按深色内容 (白纸顶与背景融合是白底图设计特性, 只报告)
        tc = np.concatenate([lum[:40, :40].ravel(), lum[:40, -40:].ravel()])
        dark = np.where((lum < 200).mean(axis=1) > 0.005)[0]
        fill_h = (dark[-1] - dark[0] + 1) / h if len(dark) else 0
        corners = tc
    bg_ok = (corners >= 252).mean() >= 0.95
    blow = ((lum >= 252) & (lum < 254)).mean()   # 背景是精确255, 252-254带=纸面过曝梯度
    ink = (lum < 120).mean()
    ok = bg_ok and ink >= 0.02 and blow <= 0.10 and (not ortho or 0.72 <= fill_h <= 0.92)
    print(f"[HERO] {os.path.basename(path)} bg={'OK' if bg_ok else 'FAIL'} "
          f"fill_h={fill_h:.2f} ink={ink:.3f} blow={blow:.3f} -> {'PASS' if ok else 'FAIL'}")



if __name__ != "__main__":   # 被模块导入 (31_pack_stage_board): 只复用构建函数与灯光rig, 不执行渲染/manifest
    QA_ONLY = True

if not QA_ONLY:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    ob = build_gable_top()
    if "--hero" in argv:
        hero_render(ob)
    else:
        setup_and_render(ob)

# ---------- 5) manifest ----------
def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()
if __name__ == "__main__":
    mani = {
        "sku": SKU, "kind": spec["kind"], "brand": spec.get("brand"),
        "dims_mm": D, "volume_ml_spec": spec["volume_ml"],
        "volume_ml_model": round(V_model * 1e6, 1), "volume_residual": round(resid, 4),
        "texture_dpi": round(dpi_front, 0), "aspect_H_over_W": round(aspect, 3),
        "textures": {k: {"path": os.path.relpath(v, BASE_DIR), "size": list(Image.open(v).size),
                         "md5": md5(v)} for k, v in panels.items()},
        "dieline_source": dl["image"],
        "gates": {"volume_ok": ok_vol, "dpi_ok": ok_dpi,
                  "fail": fail},
        "qa_dir": os.path.relpath(OUT_DIR, BASE_DIR),
    }
    mp = os.path.join(OUT_DIR, "manifest.json")
    json.dump(mani, open(mp, "w"), ensure_ascii=False, indent=1)
    print(f"[PACK] manifest={mp} GATES={'FAIL:' + ';'.join(fail) if fail else 'PASS'}")
