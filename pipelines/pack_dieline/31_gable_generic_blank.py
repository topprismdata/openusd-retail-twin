# 31_gable_generic_blank.py — 公开资源拓扑 → 通用空白屋顶包 3D (v2 自动取景)
# 拓扑来源(公开): DielineMaker DM-GABLE-CRASH-01 官方页折叠序列
#   "Back roof, Top fin, Front roof, Gable end, Gable fold-in" + "fin seals four boards thick"
#   + "liquid fillers use a heat-sealed blank with the same top"(平底热封版)
# 版式佐证: SIG Artwork Manual V7 p8-10 · 尺寸: DM 默认 70×70×195 · 印刷: 纯空白
# 端部: 塞入式(fold band + recessed triangle + corner ears) — 修掉品慕线单三角简化
# 许可: 自研参数化实现, 公开资源仅作结构参照, 不复制任何图纸(docs/DIELINE_SOURCES.md)
import bpy, bmesh, math, os, sys
from mathutils import Vector

W, D, HB = 0.070, 0.070, 0.195
HR = 0.035
HF = 0.012
LEAN = math.radians(15.0)
ROLL_R = 0.0025
HALFGAP = 0.0015
BAND = 0.002
EAR = 0.008
HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, HERE)
from pipelines.common.runtime_env import configure_cycles  # noqa: E402

OUT = os.path.join(HERE, "output", "pack", "generic")
os.makedirs(OUT, exist_ok=True)

for c in (bpy.data.objects, bpy.data.meshes, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
    for x in list(c):
        c.remove(x)

def tform(dy, dz):
    return (dy * math.cos(LEAN) - dz * math.sin(LEAN),
            dy * math.sin(LEAN) + dz * math.cos(LEAN))

bm = bmesh.new()
V = bm.verts.new
x0, x1 = -W/2, W/2
y0, y1 = -D/2, D/2
z0, z1, z2 = 0.0, HB, HB + HR

bL, bR, bB, bF = V((x0,y0,z0)), V((x1,y0,z0)), V((x1,y1,z0)), V((x0,y1,z0))
wF_L, wF_R = V((x0,y0,z1)), V((x1,y0,z1))
wB_L, wB_R = V((x0,y1,z1)), V((x1,y1,z1))
rL, rR = V((x0,0,z2)), V((x1,0,z2))
_t, _r, _u1 = HALFGAP, ROLL_R, HF - ROLL_R
fbL = V((x0,)+tform(-_t,0)); fbR = V((x1,)+tform(-_t,0))
aL = [V((x0,)+tform(-_t*math.cos(a*math.pi/4), _u1+_r*math.sin(a*math.pi/4))) for a in range(5)]
aR = [V((x1,)+tform(-_t*math.cos(a*math.pi/4), _u1+_r*math.sin(a*math.pi/4))) for a in range(5)]
A, B, C = wF_R, wB_R, rR
A2, B2, C2 = V((x1-BAND,y0,z1)), V((x1-BAND,y1,z1)), V((x1-BAND,0,z2))
Am, Bm, Cm = wF_L, wB_L, rL
A2m, B2m, C2m = V((x0+BAND,y0,z1)), V((x0+BAND,y1,z1)), V((x0+BAND,0,z2))
eFR = [V((x1,y0+EAR,z1)), V((x1,y0,z1+EAR))]
eBR = [V((x1,y1-EAR,z1)), V((x1,y1,z1+EAR))]
eFL = [V((x0,y0+EAR,z1)), V((x0,y0,z1+EAR))]
eBL = [V((x0,y1-EAR,z1)), V((x0,y1,z1+EAR))]

F = bm.faces.new
F((bF, bB, bR, bL))                                # 底
F((bL, bR, wF_R, wF_L))                            # 墙前
F((bB, bF, wB_L, wB_R))                            # 墙后
F((bF, bL, wF_L, wB_L))                            # 墙左
F((bR, bB, wB_R, wF_R))                            # 墙右
F((wF_L, wF_R, rR, rL))                            # 前坡
F((wB_R, wB_L, rL, rR))                            # 后坡
F((rL, rR, aR[0], aL[0]))                          # 前鳍面
for i in range(4):
    F((aL[i], aR[i], aR[i+1], aL[i+1]))            # 卷弧
F((rR, rL, aL[4], aR[4]))                          # 后鳍面
F((A,  B,  B2, A2)); F((B,  C,  C2, B2)); F((C,  A,  A2, C2)); F((A2, B2, C2))    # +X 塞入端
F((Am, Bm, B2m, A2m)); F((Bm, Cm, C2m, B2m)); F((Cm, Am, A2m, C2m)); F((A2m, B2m, C2m))  # -X
F((A, eFR[0], eFR[1])); F((B, eBR[0], eBR[1]))
F((Am, eFL[0], eFL[1])); F((Bm, eBL[0], eBL[1]))

bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
mesh = bpy.data.meshes.new("GableGeneric")
bm.to_mesh(mesh); bm.free()
ob = bpy.data.objects.new("GableGeneric", mesh)
bpy.context.collection.objects.link(ob)

paper = bpy.data.materials.new("PaperBlank")
paper.use_nodes = True
bsdf = paper.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.90, 0.888, 0.862, 1)
bsdf.inputs["Roughness"].default_value = 0.45
ob.data.materials.append(paper)

try:
    bpy.ops.mesh.primitive_plane_add(size=2.4, location=(0, 0, -0.0005))
    gob = bpy.context.active_object
except Exception:
    gb = bmesh.new()
    bmesh.ops.create_grid(gb, x_segments=1, y_segments=1, size=1.2)
    gmesh = bpy.data.meshes.new("Ground"); gb.to_mesh(gmesh); gb.free()
    gob = bpy.data.objects.new("Ground", gmesh)
    gob.location = (0, 0, -0.0005)
    bpy.context.collection.objects.link(gob)
gm = bpy.data.materials.new("GroundMat"); gm.use_nodes = True
gbdf = gm.node_tree.nodes["Principled BSDF"]
gbdf.inputs["Base Color"].default_value = (0.30, 0.30, 0.31, 1)
gbdf.inputs["Roughness"].default_value = 0.85
gob.data.materials.append(gm)

world = bpy.data.worlds.new("W"); bpy.context.scene.world = world
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (1, 1, 1, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.35

def area(name, loc, size, power, rot):
    L = bpy.data.lights.new(name, 'AREA'); L.size = size; L.energy = power
    lo = bpy.data.objects.new(name, L); lo.location = loc
    lo.rotation_euler = [math.radians(a) for a in rot]
    bpy.context.collection.objects.link(lo)
area("Key",  (0.45, -0.55, 0.65), 0.5, 120, (55, 0, 35))
area("Fill", (-0.55, -0.35, 0.35), 0.6, 35, (70, 0, -45))
area("Top",  (0.0, 0.05, 0.85), 0.7, 45, (0, 0, 0))

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
    cam_ob.location = tgt + fwd           # 先定向再算距
    cam_ob.rotation_euler = fwd.to_track_quat('Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    mw = cam_ob.matrix_world.inverted()
    th, tv = math.tan(HALF_H(lens)), math.tan(HALF_V(lens))
    need = 0.05
    for p in pts:
        c = mw @ p
        if c.z < -1e-6:
            need = max(need, abs(c.x)/th, abs(c.y)/tv)
    cam_ob.location = tgt + fwd * (need * margin)
    sc = bpy.context.scene
    sc.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    print("rendered", name, "dist", round(need*margin,3), flush=True)

def manual_render(name, tgt, az, el, dist, lens=70.0):
    tgt = Vector(tgt)
    azr, elr = math.radians(az), math.radians(el)
    fwd = Vector((math.cos(elr)*math.sin(azr), -math.cos(elr)*math.cos(azr), math.sin(elr)))
    cam.lens = lens
    cam_ob.location = tgt + fwd * dist
    cam_ob.rotation_euler = fwd.to_track_quat('Z', 'Y').to_euler()
    sc = bpy.context.scene
    sc.render.filepath = os.path.join(OUT, name)
    bpy.ops.render.render(write_still=True)
    print("rendered", name, flush=True)

sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.samples = 96
sc.render.resolution_x = 1400
sc.render.resolution_y = 1050
try:
    sc.view_settings.look = 'AgX - Punchy'
    print("look punchy on")
except Exception as e:
    print("look:", e)
try:
    backend, ndev = configure_cycles(scene=sc, denoise=True)
    print(f"Cycles backend={backend} devices={ndev}")
except Exception as e:
    print("GPU fail, CPU:", e)

GN = ["GableGeneric"]
fit_render("gen_three_quarter.png", -35, 24, GN, lens=55, margin=1.35)
fit_render("gen_front.png", 0, 10, GN, lens=55, margin=1.35)
fit_render("gen_top.png", 0, 80, GN, lens=50, margin=1.15)
manual_render("gen_end_close.png", (W*0.5, 0, z1), 30, 14, 0.24, lens=70)

# ---------- Grab3D CC0 模型对照(同环境) ----------
cc0_names = []
try:
    glb = os.path.join(HERE, "assets", "models", "gabletop_cc0", "milk_carton_cc0.glb")
    bpy.ops.import_scene.gltf(filepath=glb)
    cc0_names = [o.name for o in bpy.data.objects if o.type == 'MESH' and o.name != "GableGeneric"]
    pts = corners_of(cc0_names)
    if pts:
        xs=[p.x for p in pts]; ys=[p.y for p in pts]; zs=[p.z for p in pts]
        cx, cy, zmin = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2, min(zs)
        s = 0.30 / max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-zmin)
        for n in cc0_names:
            o = bpy.data.objects[n]
            o.location = ((o.location.x-cx)*s, (o.location.y-cy)*s, (o.location.z-zmin)*s)
            o.scale = (s, s, s)
        for o in bpy.data.objects:
            if o.type == 'MESH' and o.name != "GableGeneric" and o.parent and o.parent.type == 'EMPTY':
                o.parent.matrix_world = o.parent.matrix_world.__class__()
        cen = sum(pts, Vector()) / len(pts)
        ds = sorted((p - cen).length for p in pts)
        med = ds[len(ds)//2]
        pts_f = [p for p in pts if (p - cen).length <= 3.0 * max(med, 1e-6)]
        if len(pts_f) >= 8:
            pts = pts_f
            print("cc0 outlier filter:", len(pts), "->", len(pts_f))
        fit_render("cc0_three_quarter.png", -35, 18, cc0_names, lens=55, margin=1.35, pts_override=pts)
        fit_render("cc0_front.png", 0, 10, cc0_names, lens=55, margin=1.35)
    else:
        print("GLB import: no meshes")
except Exception as e:
    print("GLB import failed:", e)

print("GENERIC_DONE_MARKER_v2", flush=True)
