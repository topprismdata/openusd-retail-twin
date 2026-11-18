# 33_topprism_yogurt_cup.py — 虚拟品牌 Topprism 酸奶杯 3D + 渲染 (GitHub 展示)
# 杯型: 160g 锥度圆杯 (顶Ø88 底Ø66 高98mm) + 铝箔易撕盖 (Ø94, 拱顶+褶边)
# 复用已验证纪律: view_layer.update / FOV横向拟合(无-c.z) / AgX-Punchy / pixel-stat 验收
import bpy, bmesh, math, os
from mathutils import Vector, Matrix

TOP_R, BOT_R, CUP_H = 0.044, 0.033, 0.098
LID_R = 0.047
LID_DOMe = 0.006
WALL_T = 0.0012
SEG = 96
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(HERE, "output", "github_topprism")
os.makedirs(OUT, exist_ok=True)

for c in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights, bpy.data.images):
    for x in list(c):
        c.remove(x)

# ---------- 杯体 (旋转成性, 封闭固体轮廓) ----------
# 轮廓 (r, z): 外壁上行 -> 唇口卷 -> 内壁下行 -> 内底 -> 底外缘 -> 闭合
prof = [
    (BOT_R, 0.004),                    # 底外缘(略抬, 视觉稳定)
    (BOT_R*0.96, 0.002),
    (BOT_R*0.80, 0.0),                 # 底心
    (TOP_R - 0.004, CUP_H - 0.010),    # 外壁锥面
    (TOP_R - 0.001, CUP_H - 0.003),
    (TOP_R, CUP_H - 0.001),            # 唇外
    (TOP_R, CUP_H),                    # 唇顶
    (TOP_R - 0.0022, CUP_H - 0.0005),  # 唇内
    (TOP_R - 0.0035, CUP_H - 0.004),   # 内壁顶
    (TOP_R - 0.006 - WALL_T, CUP_H*0.55),
    (BOT_R*0.55, 0.010),               # 内壁下
    (0.0, 0.008),                      # 内底心
]
bm = bmesh.new()
verts_ring = []
for (r, z) in prof:
    ring = []
    for i in range(SEG + 1):                      # 复制接缝顶点, 杜绝跨缝四边形拉花
        a = 2*math.pi*i/SEG
        ring.append(bm.verts.new((r*math.cos(a), r*math.sin(a), z)))
    verts_ring.append(ring)
n = len(prof)
for k in range(n):
    k2 = (k+1) % n
    for i in range(SEG):
        i2 = i + 1
        bm.faces.new((verts_ring[k][i], verts_ring[k][i2], verts_ring[k2][i2], verts_ring[k2][i]))
bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
mesh = bpy.data.meshes.new("YogCup")
bm.to_mesh(mesh); bm.free()
cup = bpy.data.objects.new("YogCup", mesh)
bpy.context.collection.objects.link(cup)

# ---------- 杯身材质: 标签全包 (柱面UV) ----------
label = bpy.data.images.load(os.path.join(OUT, "cup_label.png"))
mat = bpy.data.materials.new("CupLabel"); mat.use_nodes = True
nt = mat.node_tree
bsdf = nt.nodes["Principled BSDF"]
tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = label
tex.interpolation = 'Smart'
nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.5
cup.data.materials.append(mat)
uvl = mesh.uv_layers.new(name="UVMap")
for poly in mesh.polygons:
    for li in poly.loop_indices:
        co = mesh.vertices[mesh.loops[li].vertex_index].co
        if co.z > CUP_H - 0.001:            # 唇顶用标签顶带色
            uvl.data[li].uv = (0.5, 0.97)
        elif co.z > CUP_H*0.28:             # 侧壁 = 标签区
            theta = (math.atan2(co.y, co.x) + math.pi) / (2*math.pi)   # 接缝置于 -X(背)
            v = (co.z - CUP_H*0.28) / (CUP_H*0.72)
            uvl.data[li].uv = (theta, 0.02 + 0.96*v)
        else:                                # 底部白
            uvl.data[li].uv = (0.5, 0.01)

# ---------- 铝箔盖 ----------
bm2 = bmesh.new()
# 拱顶: 径向剖面 7 点, 边缘褶边(32 波); z 抬到杯顶
RINGS = 7
LID_Z = CUP_H - 0.0034                          # 盖底坐于唇口
rings = []
for k in range(RINGS):
    t = k / (RINGS-1)
    r = LID_R * (0.15 + 0.85*t)
    z = LID_DOMe * math.sin(t * math.pi * 0.62) if t < 0.95 else LID_DOMe*0.55
    ring = []
    for i in range(SEG + 1):
        a = 2*math.pi*i/SEG
        rr = r + (0.0014*math.sin(32*a) if t > 0.92 else 0.0)
        ring.append(bm2.verts.new((rr*math.cos(a), rr*math.sin(a), LID_Z + z)))
    rings.append(ring)
for k in range(RINGS-1):
    for i in range(SEG):
        i2 = i + 1
        bm2.faces.new((rings[k][i], rings[k][i2], rings[k+1][i2], rings[k+1][i]))
# 底面封边(薄)
bot = [bm2.verts.new((LID_R*math.cos(2*math.pi*i/SEG), LID_R*math.sin(2*math.pi*i/SEG), LID_Z - 0.0004)) for i in range(SEG + 1)]
for i in range(SEG):
    i2 = i + 1
    bm2.faces.new((rings[-1][i2], rings[-1][i], bot[i], bot[i2]))
bmesh.ops.recalc_face_normals(bm2, faces=bm2.faces)
mesh2 = bpy.data.meshes.new("YogLid")
bm2.to_mesh(mesh2); bm2.free()
lid = bpy.data.objects.new("YogLid", mesh2)
bpy.context.collection.objects.link(lid)

lid_img = bpy.data.images.load(os.path.join(OUT, "lid_texture.png"))
lmat = bpy.data.materials.new("LidMat"); lmat.use_nodes = True
lnt = lmat.node_tree
lbsdf = lnt.nodes["Principled BSDF"]
ltex = lnt.nodes.new("ShaderNodeTexImage"); ltex.image = lid_img
ltex.interpolation = 'Smart'
lnt.links.new(ltex.outputs["Color"], lbsdf.inputs["Base Color"])
lbsdf.inputs["Metallic"].default_value = 0.25
lbsdf.inputs["Roughness"].default_value = 0.5
lid.data.materials.append(lmat)
uvl2 = mesh2.uv_layers.new(name="UVMap")
for poly in mesh2.polygons:
    for li in poly.loop_indices:
        co = mesh2.vertices[mesh.loops[li].vertex_index].co
        uvl2.data[li].uv = (co.x/(2*LID_R)+0.5, co.y/(2*LID_R)+0.5)

# ---------- 地面 / 光 / 世界 ----------
try:
    bpy.ops.mesh.primitive_plane_add(size=3, location=(0, 0, 0))
    gob = bpy.context.active_object
except Exception:
    gb = bmesh.new(); bmesh.ops.create_grid(gb, x_segments=1, y_segments=1, size=1.5)
    gm2 = bpy.data.meshes.new("Ground"); gb.to_mesh(gm2); gb.free()
    gob = bpy.data.objects.new("Ground", gm2); bpy.context.collection.objects.link(gob)
gmat = bpy.data.materials.new("GroundMat"); gmat.use_nodes = True
gbdf = gmat.node_tree.nodes["Principled BSDF"]
gbdf.inputs["Base Color"].default_value = (0.50, 0.50, 0.51, 1)
gbdf.inputs["Roughness"].default_value = 0.9
gob.data.materials.append(gmat)

world = bpy.data.worlds.new("W"); bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.38

def area(name, loc, size, power, rot):
    L = bpy.data.lights.new(name, 'AREA'); L.size = size; L.energy = power
    lo = bpy.data.objects.new(name, L); lo.location = loc
    lo.rotation_euler = [math.radians(a) for a in rot]
    bpy.context.collection.objects.link(lo)
area("Key",  (0.35, -0.45, 0.5), 0.4, 55, (50, 0, 32))
area("Fill", (-0.45, -0.30, 0.30), 0.5, 22, (65, 0, -50))
area("Top",  (0.0, 0.05, 0.65), 0.6, 38, (0, 0, 0))

cam = bpy.data.cameras.new("Cam")
cam_ob = bpy.data.objects.new("Cam", cam)
bpy.context.collection.objects.link(cam_ob)
bpy.context.scene.camera = cam_ob

HALF_V = lambda lens: math.atan(12.0 / lens)
HALF_H = lambda lens: math.atan(18.0 / lens)

def corners_of(names):
    pts = []
    for n in names:
        o = bpy.data.objects[n]
        pts += [o.matrix_world @ Vector(c) for c in o.bound_box]
    return pts

def fit_render(name, az, el, names, lens=55.0, margin=1.35, tgt=None, pts_override=None):
    pts = pts_override if pts_override is not None else corners_of(names)
    if tgt:
        tgt = Vector(tgt)
    else:
        xs=[p.x for p in pts]; ys=[p.y for p in pts]; zs=[p.z for p in pts]
        tgt = Vector(((min(xs)+max(xs))/2, (min(ys)+max(ys))/2, (min(zs)+max(zs))/2))
    azr, elr = math.radians(az), math.radians(el)
    fwd = Vector((math.cos(elr)*math.sin(azr), -math.cos(elr)*math.cos(azr), math.sin(elr)))
    cam.lens = lens
    cam_ob.location = tgt + fwd
    cam_ob.rotation_euler = fwd.to_track_quat('Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    mw = cam_ob.matrix_world.inverted()
    th, tv = math.tan(HALF_H(lens)), math.tan(HALF_V(lens))
    need = 0.02
    for p in pts:
        c = mw @ p
        if c.z < -1e-6:
            need = max(need, abs(c.x)/th, abs(c.y)/tv)
    cam_ob.location = tgt + fwd * (need * margin)
    sc = bpy.context.scene
    sc.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    print("rendered", name, "dist", round(need*margin, 3), flush=True)

sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.samples = 192
try:
    sc.cycles.use_denoising = False
except Exception:
    pass
sc.render.resolution_x = 1400
sc.render.resolution_y = 1400
try:
    sc.view_settings.look = 'AgX - Punchy'
except Exception as e:
    print("look:", e)
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'METAL'
    prefs.get_devices()
    for d in prefs.devices:
        d.use = (d.type == 'METAL')
    sc.cycles.device = 'GPU'
    print("METAL GPU on")
except Exception as e:
    print("GPU fail, CPU:", e)

OB = ["YogCup", "YogLid"]
sc.render.resolution_x = 1920
sc.render.resolution_y = 1920
sc.cycles.samples = 256
fit_render("yog_three_quarter.png", 62, 16, OB, lens=60, margin=1.30)
fit_render("yog_label_front.png", 90, 4, OB, lens=75, margin=1.18, tgt=(0, 0, CUP_H*0.60))

print("YOGURT_DONE_MARKER_v1", flush=True)
