"""提取扫描草莓: GLB -> strawberry.blend
v136 教训落实: 贴图立刻解包成实体文件(packed blob 空存根曾致蓝莓纹理从未被采样);
隔离渲染验证采样链通过后才允许集成生产场景。
- 去果梗(pedicel, 12.8mm 立梗在粥面侧躺时穿帮)
- 合并 主体+85种子+6花萼 -> 单 mesh 多材质槽
- 烘焙 matrix_world(资产级), 原点=包围盒中心, zmin=0
"""
import bpy, os, sys, tempfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GLB = os.path.join(BASE, "assets", "models", "strawberry", "strawberry.glb")
OUT_BLEND = os.path.join(BASE, "assets", "models", "strawberry", "strawberry.blend")
TEX_DIR = os.path.join(BASE, "assets", "models", "strawberry", "textures")
os.makedirs(TEX_DIR, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=GLB)

# 1. 去果梗
for o in list(bpy.data.objects):
    if o.type == 'MESH' and 'pedicel' in o.name.lower():
        bpy.data.objects.remove(o, do_unlink=True)

mesh_obs = [o for o in bpy.data.objects if o.type == 'MESH']
print("[STRAW] parts:", len(mesh_obs))

# 2. 烘焙 world 矩阵到网格数据
for o in mesh_obs:
    mw = o.matrix_world.copy()
    o.data.transform(mw)
    o.matrix_world = __import__('mathutils').Matrix.Identity(4)

# 3. 合并为单 mesh(保留多材质槽)
for o in mesh_obs:
    o.select_set(True)
bpy.context.view_layer.objects.active = mesh_obs[0]
bpy.ops.object.join()
root = bpy.context.view_layer.objects.active
root.name = "StrawberryScan"
me = root.data
me.name = "StrawberryScanMesh"

# 4. 原点=包围盒中心, zmin=0
from mathutils import Vector
bb = [root.matrix_world @ Vector(c) for c in root.bound_box]
xs = [v.x for v in bb]; ys = [v.y for v in bb]; zs = [v.z for v in bb]
cx, cy = (min(xs)+max(xs))/2, (min(ys)+max(ys))/2
me.transform(__import__('mathutils').Matrix.Translation(Vector((-cx, -cy, -min(zs)))))
print("[STRAW] joined v=%d f=%d 尺寸 %.1fx%.1fx%.1f mm"
      % (len(me.vertices), len(me.polygons),
         (max(xs)-min(xs))*1000, (max(ys)-min(ys))*1000, (max(zs)-min(zs))*1000))

# 5. 贴图解包成实体文件(v136 关键; 两段式: 先手动写真实字节防悬空, 存档后官方解包)
os.makedirs(TEX_DIR, exist_ok=True)
for im in bpy.data.images:
    if im.name in ('', 'Render Result') or not im.packed_file:
        continue
    fname = os.path.basename(im.filepath_raw) or (im.name + '.png')
    dst = os.path.join(TEX_DIR, fname)
    with open(dst, 'wb') as f:
        f.write(im.packed_file.data)   # 真实字节(此贴图的 packed 数据非存根)
    im.filepath = dst
    print("[STRAW] 写字节", im.name, "->", dst, "size=%dx%d" % im.size[:],
          "colorspace=", im.colorspace_settings.name)

# 6. 存 blend
bpy.ops.wm.save_as_mainfile(filepath=OUT_BLEND)
print("[STRAW] saved", OUT_BLEND)

# 6b. 重开存档做官方解包(blend 目录已解析, //textures/ 落地), 再存
bpy.ops.wm.open_mainfile(filepath=OUT_BLEND)
for im in bpy.data.images:
    if im.name in ('', 'Render Result') or not im.packed_file:
        continue
    r = im.unpack(method='WRITE_LOCAL')
    print("[STRAW] 官方解包", im.name, "ret=", r, "->", im.filepath)
bpy.ops.wm.save_mainfile()
print("[STRAW] 复存完成")

# 7. 隔离渲染验证(灰地+studio光, 无生产场景)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.read_homefile(use_empty=True)
with bpy.data.libraries.load(OUT_BLEND, link=False) as (src, dst):
    dst.meshes = [n for n in src.meshes if n == "StrawberryScanMesh"]
    dst.materials = [n for n in src.materials]
ob = bpy.data.objects.new("Straw", bpy.data.meshes["StrawberryScanMesh"])
bpy.context.scene.collection.objects.link(ob)
ob.scale = (0.72, 0.72, 0.72)  # 43mm -> 31mm(碗内份量)
# world 光
w = bpy.data.worlds.new("W"); bpy.context.scene.world = w
w.use_nodes = True
w.node_tree.nodes["Background"].inputs[0].default_value = (0.9, 0.9, 0.9, 1)
w.node_tree.nodes["Background"].inputs[1].default_value = 1.2
# key light
ld = bpy.data.lights.new("K", 'AREA'); ld.energy = 300; ld.size = 1.0
lo = bpy.data.objects.new("K", ld); bpy.context.scene.collection.objects.link(lo)
lo.location = (0.3, -0.4, 0.5); lo.rotation_euler = (0.9, 0, 0.5)
# 相机
cd = bpy.data.cameras.new("C"); co = bpy.data.objects.new("C", cd)
bpy.context.scene.collection.objects.link(co)
co.location = (0.06, -0.22, 0.13); co.rotation_euler = (1.32, 0, 0.25)
cd.lens = 60
bpy.context.scene.camera = co
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.device = 'GPU'; sc.cycles.samples = 96
sc.render.resolution_x = 640; sc.render.resolution_y = 640
sc.render.filepath = os.path.join(tempfile.gettempdir(), 'straw_solo.png')
bpy.ops.render.render(write_still=True)
print("[STRAW] solo render done")
