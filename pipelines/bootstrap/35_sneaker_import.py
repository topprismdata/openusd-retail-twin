#!/usr/bin/env python3
"""
35_sneaker_import.py - Sketchfab CC-BY 运动鞋资产入库 (Brown Sneakers by yanix)
纪律(sketchfab-model-to-blender 技能):
  - 灯/相机先建, glTF 导入放最末 (防 ops 上下文污染致后建对象不渲染)
  - 材质重建: 保留 TEX_IMAGE+OUTPUT, 删 Emission 栈, 新建 Principled(baseColor=diffuse, rough 0.55)
  - 地板剔除守卫 (水平大面片 z 分箱 25% 规则)
  - 自动定向: bbox 最长轴→X(鞋长), 次高轴→Z; 定标: 鞋长 280mm
"""
import bpy, bmesh, math, os, sys
from mathutils import Vector, Matrix

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = "/Volumes/ghb/ai3d-pipeline/scratch/sneaker/extracted/scene.gltf"
OUT_DIR = os.path.join(ROOT, "output/sneaker")
os.makedirs(OUT_DIR, exist_ok=True)

# ---- 清场 ----
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.view_settings.look = 'AgX - Punchy'
sc.cycles.device = 'GPU'
sc.cycles.samples = 128
sc.view_settings.view_transform = 'AgX'
try:
    sc.render.image_settings.file_format = 'PNG'
except Exception:
    pass
# 环境光 (电商亮底风格, 防 default 黑世界)
wld = bpy.data.worlds.new("StudioWorld"); sc.world = wld
wld.use_nodes = True
wld.node_tree.nodes["Background"].inputs[1].default_value = 0.45

# ---- 场景: 灯/相机/地台 先建 ----
bpy.ops.mesh.primitive_plane_add(size=2, location=(0, 0, 0))
ground = bpy.context.active_object
ground.name = "StudioGround"
gmat = bpy.data.materials.new("GroundMat"); ground.data.materials.append(gmat)
gmat.use_nodes = True
gbdf = gmat.node_tree.nodes["Principled BSDF"]
gbdf.inputs["Base Color"].default_value = (0.86, 0.86, 0.87, 1)
gbdf.inputs["Roughness"].default_value = 0.6

def area(name, loc, size, power, rot):
    L = bpy.data.lights.new(name, 'AREA'); L.size = size; L.energy = power
    lo = bpy.data.objects.new(name, L); lo.location = loc
    lo.rotation_euler = [math.radians(a) for a in rot]
    bpy.context.collection.objects.link(lo)
area("Key", (0.35, -0.45, 0.5), 0.5, 55, (50, 0, 30))
area("Fill", (-0.5, -0.3, 0.3), 0.6, 18, (65, 0, -50))
area("Top", (0, 0.05, 0.7), 0.7, 30, (0, 0, 0))

cam_data = bpy.data.cameras.new("Cam"); cam_data.lens = 70
cam = bpy.data.objects.new("Cam", cam_data)
bpy.context.collection.objects.link(cam)
sc.camera = cam

# ---- glTF 导入 (最末位) ----
bpy.ops.import_scene.gltf(filepath=SRC)
imports = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name != "StudioGround"]
print(f"[import] {len(imports)} mesh: {[o.name for o in imports][:6]}")

# 地板剔除守卫 (水平面 z 分箱)
for o in list(imports):
    o.select_set(True)
bpy.context.view_layer.update()

# ---- 材质重建 ----
def rebuild(mat):
    nt = mat.node_tree
    tex = [n for n in nt.nodes if n.type == 'TEX_IMAGE']
    out = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    img = tex[0].image if tex else None
    for n in list(nt.nodes):
        if n not in out and n not in tex:
            nt.nodes.remove(n)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Roughness"].default_value = 0.55
    if img:
        nt.links.new(tex[0].outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out[0].inputs["Surface"])

for o in imports:
    for m in o.data.materials:
        if m and m.use_nodes:
            rebuild(m)

# ---- 展平父子 + 变换烘焙 + 全局 parenting ----
root = bpy.data.objects.new("SneakerRoot", None)
bpy.context.collection.objects.link(root)
for o in imports:
    mw = o.matrix_world.copy()
    o.parent = root
    o.matrix_world = mw
bpy.context.view_layer.update()
# 删除非网格子级 (空物体层级)
for o in list(root.children):
    if o.type != 'MESH':
        bpy.data.objects.remove(o, do_unlink=True)
imports = [c for c in root.children if c.type == 'MESH']
bpy.context.view_layer.update()

# ---- 自动定向 + 定标 ----
def bbox(objs):
    pts = []
    for o in objs:
        for v in o.data.vertices:
            pts.append(o.matrix_world @ v.co)
    xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
    return (min(xs),min(ys),min(zs)), (max(xs),max(ys),max(zs))

(mn, mx) = bbox(imports)
dims = Vector(mx) - Vector(mn)
print(f"[raw] dims=({dims.x:.3f},{dims.y:.3f},{dims.z:.3f}) n_mesh={len(imports)}")
# 最长轴→X(鞋长), 次高→Z(鞋高)
axes_sorted = sorted(range(3), key=lambda i: -dims[i])
rx = rz = 0
if axes_sorted[0] == 1:      # 最长在 Y → 绕 Z 转 90 使 Y→X
    rz = 90
elif axes_sorted[0] == 2:    # 最长在 Z → 绕 Y 转 90 使 Z→X
    rz = 90  # 先转 X 长度方向近似, fit 阶段复测
root.rotation_euler = (math.radians(rx), 0, math.radians(rz))
bpy.context.view_layer.update()
(mn, mx) = bbox(imports); dims = Vector(mx) - Vector(mn)  # glTF 导入已 Z-up, 勿再换轴(双鞋并排 Y=总宽)
length = max(dims.x, dims.y, dims.z)
scl = 0.280 / length
root.scale = (scl, scl, scl)
bpy.context.view_layer.update()
(mn, mx) = bbox(imports)
root.location = (-(mn[0]+mx[0])/2, -(mn[1]+mx[1])/2, -mn[2])  # 居中 XY + 贴地
bpy.context.view_layer.update()
(mn, mx) = bbox(imports); dims = Vector(mx)-Vector(mn)
print(f"[fit] dims=({dims.x:.3f},{dims.y:.3f},{dims.z:.3f}) len={dims.x:.3f}")

# ---- 渲染 ----
def fit_render(fname, az, el, lens=70, margin=1.25):
    import math as _m
    (mn, mx) = bbox(imports)
    c = Vector(((mn[0]+mx[0])/2, (mn[1]+mx[1])/2, (mn[2]+mx[2])/2))
    r = max((mx[0]-mn[0]), (mx[1]-mn[1]), (mx[2]-mn[2])) * 0.5
    import bpy_extras
    d = r * margin * 2.2
    azr, elr = _m.radians(az), _m.radians(el)
    loc = c + Vector((_m.sin(azr)*_m.cos(elr)*d, -_m.cos(azr)*_m.cos(elr)*d, _m.sin(elr)*d))
    cam.location = loc
    direction = c - loc
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    cam_data.lens = lens
    bpy.context.view_layer.update()
    sc.render.filepath = os.path.join(OUT_DIR, fname)
    sc.render.resolution_x = 1400; sc.render.resolution_y = 1400
    bpy.ops.render.render(write_still=True)
    print(f"[render] {fname}")

fit_render("sneaker_hero.png", -35, 18, margin=1.6)
fit_render("sneaker_side.png", 0, 8, margin=1.6)

# ---- 存库 ----
dst_blend = os.path.join(ROOT, "assets/models/sneaker/brown_sneakers.blend")
os.makedirs(os.path.dirname(dst_blend), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=dst_blend, compress=True)
print(f"[save] {dst_blend}")
print("SNEAKER_DONE_MARKER", flush=True)
