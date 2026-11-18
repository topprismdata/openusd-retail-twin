#!/usr/bin/env python3
"""
36_open_asset_zoo.py — 开源零售资产动物园: Sketchfab CC 资产批量清洗入库 + Topprism 徽章化
配方继承 35_sneaker_import(已验证): 灯/相机先建·glTF 末位导入·Emission→Principled 重建·
tuple bbox·自动定向(最长轴→X, glTF 导入已 Z-up)·真实尺度定标。
新增: 主贴图 TOPPRISM 徽章(蓝紫渐变三角+字标, 右下角 12% 区域) — 无品牌开源资产统一 Topprism 化。
用法: Blender -b -P pipelines/bootstrap/36_open_asset_zoo.py [--only name1,name2]
"""
import bpy, bmesh, math, os, sys, json
from mathutils import Vector

HERE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRATCH = "/Volumes/ghb/ai3d-pipeline/scratch/zoo"
OUT_DIR = os.path.join(HERE, "output/zoo")
os.makedirs(OUT_DIR, exist_ok=True)

# (key, 展示名, uid, 目标长度m)  长度=最长轴
ZOO = [
    ("coffee_bag",   "咖啡纸袋扫描", "4873908248a04f7b9af32a58a1918a28", 0.140),
    ("spray_bottle", "喷雾清洁瓶",   "1611833f3eaa41bbba2b6944269429ab", 0.240),
    ("mannequin",    "时装人台",     "644b113218b94c94b5f07be0b6f455a3", 0.800),
    ("candies",      "糖果组 CC0",   "8dd602aff1204c548105462cccd492d6", 0.160),
    ("cereal_box",   "谷物盒(虚构牌)", "070e0d3816bb444e883533a7297b3da7", 0.220),
    ("mason_jar",    "梅森玻璃罐",     "6414d60acf08412abbf80ad0a60fcebe", 0.160),
]

BP, PURPLE, CYAN = (47, 107, 240), (139, 60, 240), (0, 144, 240)

def badge_texture(gltf_dir):
    """在最大贴图右下角烙 TOPPRISM 徽章(返回是否改贴图)"""
    from PIL import Image, ImageDraw, ImageFont
    tex_dir = None
    for cand in ("textures", "Textures", "."):
        p = os.path.join(gltf_dir, cand) if cand != "." else gltf_dir
        if os.path.isdir(p):
            tex_dir = p; break
    if not tex_dir:
        return False
    imgs = [os.path.join(tex_dir, f) for f in os.listdir(tex_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg"))]
    if not imgs:
        return False
    tgt = max(imgs, key=os.path.getsize)
    try:
        im = Image.open(tgt).convert("RGBA")
    except Exception:
        return False
    if min(im.size) < 256:
        return False
    W, H = im.size
    s = int(min(W, H) * 0.16)          # 徽章边长
    x0, y0 = W - int(s*1.5) - int(W*0.03), H - s - int(H*0.03)
    # 底板(白圆角)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([x0, y0, x0+int(s*1.5), y0+s], radius=int(s*0.12), fill=(255,255,255,235))
    # 渐变三角棱镜
    cx, cy = x0+int(s*0.38), y0+s//2
    pts = [(cx, cy-int(s*0.30)), (cx-int(s*0.26), cy+int(s*0.18)), (cx+int(s*0.26), cy+int(s*0.18))]
    for i in range(3):
        d.line([pts[i], pts[(i+1) % 3]], fill=(BP, PURPLE, CYAN)[i], width=max(3, s//14))
    # 字标
    try:
        f = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", int(s*0.26))
    except Exception:
        f = ImageFont.load_default()
    d.text((x0+int(s*0.72), y0+s//2), "TOPPRISM", font=f, fill=(24, 28, 38, 255), anchor="lm")
    im.save(tgt)
    return True

def rebuild(mat):
    nt = mat.node_tree
    tex = [n for n in nt.nodes if n.type == 'TEX_IMAGE']
    out = [n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL']
    for n in list(nt.nodes):
        if n not in out and n not in tex:
            nt.nodes.remove(n)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.inputs["Alpha"].default_value = 1.0   # glTF BLEND 透明壳防隐形
    if tex and tex[0].image:
        nt.links.new(tex[0].outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(bsdf.outputs["BSDF"], out[0].inputs["Surface"])

def bbox(objs):
    pts = []
    for o in objs:
        for v in o.data.vertices:
            pts.append(o.matrix_world @ v.co)
    xs = [p.x for p in pts]; ys = [p.y for p in pts]; zs = [p.z for p in pts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

def process(key, disp, uid, target_len):
    src_dir = os.path.join(SCRATCH, "x_" + uid)
    gltf = os.path.join(src_dir, "scene.gltf")
    if not os.path.exists(gltf):
        for f in os.listdir(src_dir):
            if f.endswith(".gltf"):
                gltf = os.path.join(src_dir, f); break
    branded = badge_texture(src_dir)
    # 清场
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'; sc.cycles.device = 'GPU'; sc.cycles.samples = 96
    sc.view_settings.view_transform = 'AgX'; sc.view_settings.look = 'AgX - Punchy'
    wld = bpy.data.worlds.new("W"); sc.world = wld; wld.use_nodes = True
    wld.node_tree.nodes["Background"].inputs[1].default_value = 0.45
    # 灯/相机/地台先建
    bpy.ops.mesh.primitive_plane_add(size=2)
    g = bpy.context.active_object; g.name = "G"
    gm = bpy.data.materials.new("GM"); g.data.materials.append(gm); gm.use_nodes = True
    gb = gm.node_tree.nodes["Principled BSDF"]
    gb.inputs["Base Color"].default_value = (0.86, 0.86, 0.87, 1); gb.inputs["Roughness"].default_value = 0.6
    def area(name, loc, size, power, rot):
        L = bpy.data.lights.new(name, 'AREA'); L.size = size; L.energy = power
        lo = bpy.data.objects.new(name, L); lo.location = loc
        lo.rotation_euler = [math.radians(a) for a in rot]
        bpy.context.collection.objects.link(lo)
    area("Top", (0, 0.05, 0.7), 0.7, 30, (0, 0, 0))
    cd = bpy.data.cameras.new("C"); cd.lens = 60
    cam = bpy.data.objects.new("C", cd); bpy.context.collection.objects.link(cam)
    sc.camera = cam
    # glTF 末位导入
    bpy.ops.import_scene.gltf(filepath=gltf)
    imports = [o for o in bpy.context.scene.objects if o.type == 'MESH' and o.name != "G"]
    if not imports:
        print(f"[{key}] NO_MESH"); return
    root = bpy.data.objects.new("R", None)
    bpy.context.collection.objects.link(root)
    for o in imports:
        mw = o.matrix_world.copy(); o.parent = root; o.matrix_world = mw
    bpy.context.view_layer.update()
    for o in list(root.children):
        if o.type != 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)
    imports = [c for c in root.children if c.type == 'MESH']
    for o in imports:
        for m in o.data.materials:
            if m and m.use_nodes:
                rebuild(m)
    # 法线重算 (铁罐黑斑修)
    for o in imports:
        try:
            with bpy.context.temp_override(selected_objects=[o], active_object=o):
                bpy.ops.mesh.recalc_face_normals()
        except Exception:
            pass
    bpy.context.view_layer.update()
    (mn, mx) = bbox(imports)
    dims = [mx[i]-mn[i] for i in range(3)]
    rz = 90 if sorted(range(3), key=lambda i: -dims[i])[0] == 1 else 0
    root.rotation_euler = (0, 0, math.radians(rz))
    bpy.context.view_layer.update()
    (mn, mx) = bbox(imports)
    length = max(mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2])
    s = target_len / length
    root.scale = (s, s, s)
    bpy.context.view_layer.update()
    (mn, mx) = bbox(imports)
    root.location = (-(mn[0]+mx[0])/2, -(mn[1]+mx[1])/2, -mn[2])
    bpy.context.view_layer.update()
    (mn, mx) = bbox(imports)
    c = Vector(((mn[0]+mx[0])/2, (mn[1]+mx[1])/2, (mn[2]+mx[2])/2))
    r = max(mx[0]-mn[0], mx[1]-mn[1], mx[2]-mn[2]) * 0.5
    az, el = math.radians(35), math.radians(15)
    half_vfov = math.atan(12.0 / 60.0)          # 60mm 镜头垂直半视场
    d = r * 1.12 / math.sin(half_vfov)     # 焦距感知取景, 12% 裕量
    cam.location = c + Vector((math.sin(az)*math.cos(el)*d, -math.cos(az)*math.cos(el)*d, math.sin(el)*d))
    cam.rotation_euler = (c - cam.location).to_track_quat('-Z', 'Y').to_euler()
    bpy.context.view_layer.update()
    sc.render.filepath = os.path.join(OUT_DIR, key + ".png")
    sc.render.resolution_x = 1200; sc.render.resolution_y = 1200
    bpy.ops.render.render(write_still=True)
    # 打包 blend (小资产才存)
    blend_p = os.path.join(HERE, "assets/models/zoo", key + ".blend")
    os.makedirs(os.path.dirname(blend_p), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=blend_p, compress=True)
    mb = os.path.getsize(blend_p) / 1048576
    print(f"[{key}] OK branded={branded} blend={mb:.1f}MB dims=({mx[0]-mn[0]:.2f},{mx[1]-mn[1]:.2f},{mx[2]-mn[2]:.2f})")

argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
only = argv[argv.index("--only")+1].split(",") if "--only" in argv else None
manifest = []
for key, disp, uid, tl in ZOO:
    if only and key not in only:
        continue
    process(key, disp, uid, tl)
    manifest.append({"key": key, "display": disp, "uid": uid,
                     "src": f"https://sketchfab.com/3d-models/{uid}",
                     "license": open(os.path.join(SCRATCH, f"lic_{uid}.txt")).read()[:200] if os.path.exists(os.path.join(SCRATCH, f"lic_{uid}.txt")) else "see package"})
json.dump(manifest, open(os.path.join(OUT_DIR, "zoo_manifest.json"), "w"), ensure_ascii=False, indent=2)
print("ZOO_DONE_MARKER", flush=True)
