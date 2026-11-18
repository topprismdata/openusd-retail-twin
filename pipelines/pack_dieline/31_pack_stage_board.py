# 四阶段产品资产板 (R19): NVIDIA Omniverse 风格
#   ① CAD线框(工程折线, Freestyle蓝线) ② 白模网格(粘土+拓扑线) ③ 物理材质(纸板无印刷) ④ 印刷成品
# GPT行业规范: 四阶段锁相机/几何/画幅; ③④锁灯光(HDRI+三点)。相机=三分之二视角。
import bpy, os, sys, math, json, importlib.util
import numpy as np
from PIL import Image   # R80: ImageDraw/ImageFont 随拼版移至 compose_stage_board.py

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
spec_path = argv[argv.index("--spec") + 1] if "--spec" in argv else "specs/pack_458.json"
OUT_DIR = os.path.join(BASE, argv[argv.index("--out") + 1] if "--out" in argv else "output/pack_qa/pinmu_458/stage_board")
os.makedirs(OUT_DIR, exist_ok=True)
spec_abs = os.path.join(BASE, spec_path)

# ---- 导入管线模块 (其导入守卫: 只构建函数, 不渲染不写manifest) ----
sys.argv = ["stage_board", "--", "--spec", spec_abs]
sp = importlib.util.spec_from_file_location("packline", os.path.join(BASE, "30_pack_asset_line.py"))
pl = importlib.util.module_from_spec(sp)
sp.loader.exec_module(pl)
spec = pl.spec

bpy.ops.wm.read_factory_settings(use_empty=True)   # 必须在取 scene 引用之前 (旧引用会失效)
sc = bpy.context.scene
sc.render.engine = 'CYCLES'
sc.cycles.samples = 96
sc.cycles.device = 'CPU'
sc.render.resolution_x, sc.render.resolution_y = 900, 1200
sc.render.image_settings.file_format = 'PNG'
sc.view_settings.view_transform = 'Standard'

WOB_MM = spec.get("material", {}).get("paper_wobble_mm", 0.0022) / 1000.0   # R38: 鼓胀幅度mm→m
ob = pl.build_gable_top()
# R31-P2 盲评"大面绝对平整=CG感": 真实灌装屋顶包大面微凸/翘曲。bmesh一次性几何编辑:
# SIMPLE式网格细分(cuts=2, UV插值保持) + 确定性平滑噪声沿法线位移±1.2mm(局部坐标, 四阶段一致);
# 底圈顶点不动(保落地); 折棱相邻顶点位移相近→折线仍清晰。5.2 Displace数据纹理API已节点化不可编程, 故走bmesh
import bmesh
from mathutils import Vector
bm = bmesh.new()
bm.from_mesh(ob.data)
bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=2, use_grid_fill=True)
bm.normal_update()
def _wobble(co):
    # 确定性平滑伪噪声[-1,1] (无random依赖, 跨进程可复现)
    x, y, z = co
    return (math.sin(x * 14.3 + math.sin(y * 8.3) * 2.1) *
            math.sin(y * 12.1 + math.sin(z * 6.7) * 1.7) *
            math.sin(z * 9.7 + math.sin(x * 10.9) * 1.3))
for v in bm.verts:
    if v.co.z < 0.0015:      # 底圈不位移, 保落地接触
        continue
    if v.co.z > pl.hb + pl.hr - 0.001:   # R40b: 鳍片区(热压刚性平板)不位移, 防文字扭皱
        continue
    w = _wobble(v.co)
    v.co += v.normal * (WOB_MM * w)   # R38: spec驱动(原2.2mm)
# R39c: 逐面毫米UV(位移后, 面内两轴投影/19mm=UV即tile单位, 跨面密度均匀; 根治FLAT投影立面退化)
bm.faces.ensure_lookup_table()
uv_lay = bm.loops.layers.uv.new("UVTile")   # R41: 双UV层——UVMap=印刷面板UV(细分插值保留), UVTile=毫米平铺(凹凸图专用), 互不污染
from mathutils import Vector as _V
for fce in bm.faces:
    n = fce.normal
    ax = [abs(n.x), abs(n.y), abs(n.z)]
    skip = ax.index(max(ax))          # 法线主导轴=面法向, 其余两轴为面内u/v
    axes = [i for i in range(3) if i != skip]
    for lp in fce.loops:
        co = lp.vert.co
        u = co[axes[0]] / 0.019       # mm→tile单位
        v = co[axes[1]] / 0.019
        lp[uv_lay].uv = (u, v)
bm.to_mesh(ob.data)
bm.free()
ob.data.update()
if "UVMap" in ob.data.uv_layers:
    ob.data.uv_layers["UVMap"].active_render = True   # R41: 印刷UV为渲染活动层; 凹凸图经UV Map节点显式取UVTile
# R21: 折边3mm压圆bevel - 真实工艺特征(纸盒折边非锐利), 折边fresnel高光条的光学来源; 四阶段几何一致
bv = ob.modifiers.new("Bevel", 'BEVEL')
bv.width = 0.003
bv.segments = 3
bv.angle_limit = math.radians(50)
bv.harden_normals = False
# R27: bevel把折棱变成~165°钝角, freestyle crease阈值(145°)抓不到→①线框缺屋顶折线;
# 直标主折线边(底圈/檐口圈/竖棱/山墙斜边), lineset按edge_mark选择。5.2: use_freestyle_mark→EDGE域BOOLEAN属性
sp = pl.SPEC if hasattr(pl, "SPEC") else json.load(open(os.path.join(BASE, "specs/pack_458.json")))
D = sp.get("dims_mm", {})
W = D.get("w", 68.3) / 2000.0   # mm→m半宽
DD = D.get("d", 68.3) / 2000.0
HB = D.get("h_body", 105.2) / 1000.0
HR = D.get("h_ridge", 24.0) / 1000.0
TOL = 0.0008
attr = ob.data.attributes.get("freestyle_edge_mark")
if attr is None:
    attr = ob.data.attributes.new("freestyle_edge_mark", 'BOOLEAN', 'EDGE')
for i, e in enumerate(ob.data.edges):
    mx = (ob.data.vertices[e.vertices[0]].co + ob.data.vertices[e.vertices[1]].co) / 2
    ax, ay, az = abs(mx.x), abs(mx.y), mx.z
    on_corner = ax > W - TOL and ay > DD - TOL          # 四竖棱
    on_eave = az > HB - TOL and az < HB + TOL           # 檐口圈
    on_base = az < TOL                                   # 底圈
    on_ridge = az > HB + HR - TOL and ay < TOL           # 脊线
    on_gable_slant = (az > HB - TOL) and (az < HB + HR + TOL) and (ax > W - TOL)  # 山墙斜边
    if on_corner or on_eave or on_base or on_ridge or on_gable_slant:
        attr.data[i].value = True
H = pl.hb + pl.hr + pl.hf   # R40: 总高含立鳍
orig_slots = list(ob.data.materials)

# R31 盲评不合格重修(GPT判Y4.5/Z5.5, 99.5%识破): 根因=表面零变化(恒定rough+单频bump+绝对平面)=塑料感。
# 纸基复合shader三件套: ①roughness空间变化(宏观mottle+微观纤维) ②双频bump(纤维180+波状30, 大面非绝对平整) ③涂层光学与基色分离。
# 贴图像素不动(品牌资产约束); ②③④共用同一基材模型(GPT流程建议)
def add_substrate(mat, rough, coat_w, coat_r, bump_fiber=0.16, bump_wavy=0.28,
                  bump_map=None, bump_tile=3.6, bump_strength=0.25, coat_map_frac=0.35, rough_map_amp=0.03,
                  rough_mottle_amp=0.09, coat_r_mottle_amp=0.08):   # R38: 斑驳幅度参数化(覆膜化=收窄)
    # R37 texture-lift: bump_map=实拍白区提取的微观凹凸图(随机/多尺度/特征~0.6mm), 替代程序化纤维噪声(盲评R4"纵向拉丝似木纹"元凶);
    # 涂层法线以 coat_map_frac 弱跟随同图(R4"缺缎面不均匀高光"), 粗糙度微调制 rough_map_amp
    if mat is None or not mat.use_nodes:
        return
    nt = mat.node_tree
    pb = nt.nodes.get("Principled BSDF")
    if pb is None:
        return
    # ①粗糙度空间变化: 宏观mottle(尺45, ±0.07)叠加基础值 → 高光与漫反射有局部差异(实拍特征)
    # R39b: Generated坐标噪声在正立面各向异性(z129mm/x68mm=2:1纵向拉伸)=盲评"纵向拉丝"实凶(条纹残差4.9倍实拍), 有实拍图时整链裁除
    pb.inputs["Roughness"].default_value = rough
    use_map = bump_map and os.path.exists(os.path.join(BASE, bump_map))
    if not pb.inputs["Roughness"].is_linked and not use_map:
        nzA = nt.nodes.new("ShaderNodeTexNoise")
        nzA.inputs["Scale"].default_value = 45.0
        nzA.inputs["Detail"].default_value = 2.0
        nzA2 = nt.nodes.new("ShaderNodeTexNoise")     # R33: 中尺度260 = 纤维簇粗糙度斑驳(多尺度要求)
        nzA2.inputs["Scale"].default_value = 260.0
        nzA2.inputs["Detail"].default_value = 3.0
        mr = nt.nodes.new("ShaderNodeMapRange")
        mr.inputs["From Min"].default_value = 0.0
        mr.inputs["From Max"].default_value = 1.0
        mr.inputs["To Min"].default_value = -rough_mottle_amp
        mr.inputs["To Max"].default_value = rough_mottle_amp
        nt.links.new(nzA.outputs["Fac"], mr.inputs["Value"])
        mr2 = nt.nodes.new("ShaderNodeMapRange")
        mr2.inputs["To Min"].default_value = -0.05
        mr2.inputs["To Max"].default_value = 0.05
        nt.links.new(nzA2.outputs["Fac"], mr2.inputs["Value"])
        adA = nt.nodes.new("ShaderNodeMath")
        adA.operation = 'ADD'
        nt.links.new(mr.outputs["Result"], adA.inputs[0])
        nt.links.new(mr2.outputs["Result"], adA.inputs[1])
        ad = nt.nodes.new("ShaderNodeMath")
        ad.operation = 'ADD'
        ad.inputs[1].default_value = rough
        nt.links.new(adA.outputs["Value"], ad.inputs[0])
        nt.links.new(ad.outputs["Value"], pb.inputs["Roughness"])
    if "Coat Weight" in pb.inputs:
        pb.inputs["Coat Weight"].default_value = coat_w
        if "Coat Roughness" in pb.inputs:
            pb.inputs["Coat Roughness"].default_value = coat_r
            if not pb.inputs["Coat Roughness"].is_linked and coat_w > 0.3:
                nzD = nt.nodes.new("ShaderNodeTexNoise")      # R31b: 涂层粗糙度空间变化(真实涂层非光学玻璃, mottle穿过涂层)
                nzD.inputs["Scale"].default_value = 60.0
                nzD.inputs["Detail"].default_value = 2.0
                mrD = nt.nodes.new("ShaderNodeMapRange")
                mrD.inputs["To Min"].default_value = -0.08
                mrD.inputs["To Max"].default_value = 0.08
                nt.links.new(nzD.outputs["Fac"], mrD.inputs["Value"])
                adD = nt.nodes.new("ShaderNodeMath")
                adD.operation = 'ADD'
                adD.inputs[1].default_value = coat_r
                nt.links.new(mrD.outputs["Result"], adD.inputs[0])
                nt.links.new(adD.outputs["Value"], pb.inputs["Coat Roughness"])
    if "Specular IOR Level" in pb.inputs and pb.inputs["Specular IOR Level"].default_value > 0.10:
        pb.inputs["Specular IOR Level"].default_value = 0.06   # 镜面白反射去饱和(R18实证)
    if not pb.inputs["Normal"].is_linked:
        map_normal_chain = None
        if bump_map and os.path.exists(os.path.join(BASE, bump_map)):
            # R37: 实拍微纹理图替代程序化纤维噪声
            timg = bpy.data.images.load(os.path.join(BASE, bump_map))
            timg.colorspace_settings.name = "Non-Color"
            texM = nt.nodes.new("ShaderNodeTexImage")
            texM.image = timg
            texM.extension = "REPEAT"   # R39c/R41: 凹凸图经UVTile毫米层采样(显式UV Map节点), 与印刷UVMap解耦
            uvT = nt.nodes.new("ShaderNodeUVMap")
            uvT.uv_map = "UVTile"
            nt.links.new(uvT.outputs["UV"], texM.inputs["Vector"])
            bmpM = nt.nodes.new("ShaderNodeBump")
            bmpM.inputs["Strength"].default_value = bump_strength
            bmpM.inputs["Distance"].default_value = 0.01   # R37b: 缺省1.0m把±0.04图高度摊到1m间距=法线扰动湮灭
            nt.links.new(texM.outputs["Color"], bmpM.inputs["Height"])
            map_normal_chain = bmpM
            # 粗糙度微调制: 图值→±rough_map_amp 叠入粗糙度和
            mrM = nt.nodes.new("ShaderNodeMapRange")
            mrM.inputs["To Min"].default_value = -rough_map_amp
            mrM.inputs["To Max"].default_value = rough_map_amp
            nt.links.new(texM.outputs["Color"], mrM.inputs["Value"])
            # R39b: 涂层粗糙度同图微调制(缎面不均匀, ±0.02; 替代被裁的Generated噪声链)
            if "Coat Roughness" in pb.inputs and coat_w > 0.3 and not pb.inputs["Coat Roughness"].is_linked:
                mrC = nt.nodes.new("ShaderNodeMapRange")
                mrC.inputs["To Min"].default_value = -0.02
                mrC.inputs["To Max"].default_value = 0.02
                nt.links.new(texM.outputs["Color"], mrC.inputs["Value"])
                adC = nt.nodes.new("ShaderNodeMath")
                adC.operation = 'ADD'
                adC.inputs[1].default_value = coat_r
                nt.links.new(mrC.outputs["Result"], adC.inputs[0])
                nt.links.new(adC.outputs["Value"], pb.inputs["Coat Roughness"])
            srcR = pb.inputs["Roughness"]
            if srcR.is_linked:
                lkR = [lk for lk in nt.links if lk.to_socket == srcR]
                prevFrom = lkR[0].from_socket if lkR else None
                if prevFrom:
                    adR = nt.nodes.new("ShaderNodeMath")
                    adR.operation = 'ADD'
                    nt.links.remove(lkR[0])
                    nt.links.new(prevFrom, adR.inputs[0])
                    nt.links.new(mrM.outputs["Result"], adR.inputs[1])
                    nt.links.new(adR.outputs["Value"], srcR)
            # 涂层弱跟随(缎面不均匀高光); 无coat则忽略
            if "Coat Normal" in pb.inputs and coat_w > 0.3:
                bmpMC = nt.nodes.new("ShaderNodeBump")
                bmpMC.inputs["Strength"].default_value = bump_strength * coat_map_frac
                bmpMC.inputs["Distance"].default_value = 0.01
                nt.links.new(texM.outputs["Color"], bmpMC.inputs["Height"])
                nt.links.new(bmpMC.outputs["Normal"], pb.inputs["Coat Normal"])
        else:
            nzB = nt.nodes.new("ShaderNodeTexNoise")               # 微观纤维(程序化; R4盲评"纵向拉丝"来源, 有实拍图时被替代)
            nzB.inputs["Scale"].default_value = 320.0
            nzB.inputs["Detail"].default_value = 3.0
            bmpB = nt.nodes.new("ShaderNodeBump")
            bmpB.inputs["Strength"].default_value = bump_fiber
            nt.links.new(nzB.outputs["Fac"], bmpB.inputs["Height"])
            map_normal_chain = bmpB
        nzC = nt.nodes.new("ShaderNodeTexNoise")               # 宏观波状: 大面非绝对平整(灌装鼓胀/纸板趨曲)
        nzC.inputs["Scale"].default_value = 28.0
        nzC.inputs["Detail"].default_value = 1.0
        bmpC = nt.nodes.new("ShaderNodeBump")
        bmpC.inputs["Strength"].default_value = bump_wavy
        nt.links.new(nzC.outputs["Fac"], bmpC.inputs["Height"])
        if map_normal_chain is not None:
            nt.links.new(map_normal_chain.outputs["Normal"], bmpC.inputs["Normal"])   # 细→粗级联
        nt.links.new(bmpC.outputs["Normal"], pb.inputs["Normal"])
        # 图模式下涂层法线已接弱跟随; 程序化模式涂层保持光滑(纤维在涂层之下, R30); 清理误接
        if "Coat Normal" in pb.inputs and pb.inputs["Coat Normal"].is_linked and not (bump_map and coat_w > 0.3):
            for lk in list(nt.links):
                if lk.to_socket == pb.inputs["Coat Normal"]:
                    nt.links.remove(lk)
BPM = spec.get("material", {}).get("paper_bump_map")           # R37 texture-lift: 实拍白区微凹凸图
BPT = spec.get("material", {}).get("paper_bump_tile", 3.6)     # 208px图≈19mm物理, 68.3mm面→3.6 tile
BPS = spec.get("material", {}).get("paper_bump_strength", 0.25)
SPR = spec.get("material", {}).get("paper_rough", 0.30)          # R38 覆膜化
SCR = spec.get("material", {}).get("paper_coat_r", 0.22)
SRM = spec.get("material", {}).get("paper_rough_mottle", 0.09)
SCM = spec.get("material", {}).get("paper_coat_r_mottle", 0.08)
for i, m in enumerate(orig_slots):
    if m is None:
        continue
    if i == 0:  # 白基材槽(封口/折边): 暖白, 与③同族
        pb = m.node_tree.nodes.get("Principled BSDF") if m.use_nodes else None
        if pb is not None and "Base Color" in pb.inputs and not pb.inputs["Base Color"].is_linked:
            pb.inputs["Base Color"].default_value = (0.84, 0.81, 0.765, 1)
        add_substrate(m, rough=SPR-0.04, coat_w=1.0, coat_r=SCR, bump_map=BPM, bump_tile=BPT, bump_strength=BPS, rough_mottle_amp=SRM, coat_r_mottle_amp=SCM)   # R38覆膜化=③④基材连续
    else:       # R79c: 印刷槽对齐单独版30(_face_mat coat=0/rough=spec) — coat_w0.85覆膜高光是三分之四机位脱饱和主因(S181 vs 238), 去覆膜+粗糙度对齐→④色=单独版
        add_substrate(m, rough=spec.get("material", {}).get("roughness", 0.5), coat_w=spec.get("material", {}).get("coat_weight", 0.0), coat_r=SCR-0.04, bump_fiber=0.12, bump_wavy=0.08, bump_map=BPM, bump_tile=BPT, bump_strength=BPS, rough_mottle_amp=SRM, coat_r_mottle_amp=SCM)

# ---- 灯光 (R28: spec.stage_lighting 摄影框架布光, 与match_view.rig(hero标定)隔离; 缺省回退旧rig) ----
# R79: 四阶段板改用标定 match_view rig(出单独版好色的那套光) — stage_lighting 130W/-2.5 把蓝洗白(S129 vs 238), grade 救不回饱和; 光为世界系+grade相机无关→④色对齐单独版, 柔光下②③材质差更显
_mv = spec["match_view"]
rig = dict(_mv["rig"])
rig["exposure"] = _mv.get("exposure", -1.2) - 0.4   # R79d: 去覆膜后S已对齐231, 剩亮度V207 vs 161; 无覆膜压0.4档不脱饱和→V/S双对齐单独版
rig["view_transform"] = _mv.get("view_transform", "AgX")
rig["look"] = _mv.get("look", "None")
sc.world = bpy.data.worlds.new("W"); sc.world.use_nodes = True
sc.view_settings.view_transform = rig.get("view_transform", "Standard")   # AgX=摄影肩部滚降, 替代Standard硬削顶
sc.view_settings.exposure = rig.get("exposure", 0.0)
try:
    sc.view_settings.look = rig.get("look", "None")        # R31: AgX-Punchy 提升印刷墨饱和(盲评Z"蓝偏灰偏浅"的色彩管理侧)
except Exception:
    pass
nt = sc.world.node_tree
bg = nt.nodes["Background"]
if rig.get("hdri"):
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    eimg = bpy.data.images.load(os.path.join(BASE, rig["hdri"]))
    eimg.colorspace_settings.name = "Non-Color"
    env.image = eimg
    if rig.get("hdri_rot_deg"):
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Rotation"].default_value[2] = math.radians(rig["hdri_rot_deg"])
        nt.links.new(mp.outputs["Vector"], env.inputs["Vector"])
    nt.links.new(env.outputs["Color"], bg.inputs[0])
bg.inputs[1].default_value = rig.get("world", 0.85)
for lt in rig["lights"]:
    bpy.ops.object.light_add(type="AREA", location=lt["pos"])
    L = bpy.context.active_object
    L.data.shape = 'RECTANGLE' if lt.get("size_y") else 'SQUARE'
    L.data.size = lt["size"]
    if lt.get("size_y"):
        L.data.size_y = lt["size_y"]
    L.data.energy = lt["energy"]
    if lt.get("spread"):
        L.data.spread = math.radians(lt["spread"])   # R32: 光束角120°(默认180°过度包裹=发灰)
    if lt.get("color"):
        L.data.color = tuple(lt["color"])
    L.constraints.new("TRACK_TO").target = ob

# ---- 地面 Shadow Catcher (②③④; ①浮盒无地面) ----
bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, -0.001))
floor = bpy.context.active_object
floor.is_shadow_catcher = True

# ---- 相机 (四阶段锁定: 三分之二视角) ----
from mathutils import Vector
ctr = Vector((0, 0, H / 2))
CAM_LOC, CAM_LENS = (0.235, -0.29, H * 0.74), 60   # R31c: 推近30%, 产品占画幅~75%   # R31c: 推近38%, 产品占画幅~70%
bpy.ops.object.camera_add()
cam = bpy.context.active_object
cam.data.lens = CAM_LENS
cam.location = CAM_LOC
cam.rotation_euler = (ctr - Vector(CAM_LOC)).to_track_quat("-Z", "Y").to_euler()
sc.camera = cam

# ---- 材质 ----
def plain(name, base=(0.92, 0.92, 0.92, 1), rough=0.5, emission=False):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    if emission:
        nt2 = m.node_tree
        nt2.nodes.remove(b)
        em = nt2.nodes.new("ShaderNodeEmission")
        em.inputs[0].default_value = base
        em.inputs[1].default_value = 1.0
        nt2.links.new(em.outputs[0], nt2.nodes["Material Output"].inputs["Surface"])
    else:
        b.inputs["Base Color"].default_value = base
        b.inputs["Roughness"].default_value = rough
        if "Specular IOR Level" in b.inputs:
            b.inputs["Specular IOR Level"].default_value = 0.05
    return m

mat_paper = plain("Paper_White", base=(0.845, 0.805, 0.74, 1), rough=spec.get("material", {}).get("roughness", 0.5))  # R28: 暖白涂布纸板 — AgX肩部+新柔光rig下白系可安全回到线性段, 撤牛皮替代方案; 过渡=同一白盒逐级加资产(联合利华式)
add_substrate(mat_paper, rough=SPR, coat_w=1.0, coat_r=SCR, bump_map=BPM, bump_tile=BPT, bump_strength=BPS, rough_mottle_amp=SRM, coat_r_mottle_amp=SCM)   # R31/R37/R38覆膜化
mat_clay = plain("Clay_White", base=(0.62, 0.63, 0.68, 1), rough=0.85)   # ②深冷哑光粘土: 色温码与③暖白分离+不响应硬条光(材质阶段差=照明响应差)   # ②中性哑光粘土: 无coat(与③涂层阶段拉开); GPT流程建议: 白模=白基材+真实微结构
add_substrate(mat_clay, rough=0.62, coat_w=0.0, coat_r=0.5, bump_fiber=0.12, bump_wavy=0.22, bump_map=BPM, bump_tile=BPT, bump_strength=BPS)   # ②同款微观结构(哑光; R37实拍图)
# ①CAD幽灵盒: 88%透明+12%自发光 → 透出全部可见折线 (NVIDIA线框内部结构观感)
mat_cad = bpy.data.materials.new("CAD_Ghost")
mat_cad.use_nodes = True
n2 = mat_cad.node_tree
n2.nodes.clear()
out2 = n2.nodes.new("ShaderNodeOutputMaterial")
em2 = n2.nodes.new("ShaderNodeEmission")
em2.inputs[0].default_value = (0.90, 0.90, 0.92, 1)
em2.inputs[1].default_value = 1.0
tr2 = n2.nodes.new("ShaderNodeBsdfTransparent")
mx2 = n2.nodes.new("ShaderNodeMixShader")
mx2.inputs["Fac"].default_value = 0.10   # R30: 4%太透明→Cycles深度近似背景→freestyle隐藏棱误判可见(虚线消失); 10%近背景灰=遮挡恢复且不读作填充
n2.links.new(tr2.outputs[0], mx2.inputs[1])
n2.links.new(em2.outputs[0], mx2.inputs[2])
n2.links.new(mx2.outputs[0], out2.inputs["Surface"])

def set_freestyle(mode):
    sc.render.use_freestyle = bool(mode)
    if not mode:
        return
    vl = bpy.context.view_layer
    fs = vl.freestyle_settings
    for l in list(fs.linesets):        # 该集合无clear(), 逐个remove
        fs.linesets.remove(l)
    def mk(name, vis, color, thick, dashed=False):
        ls = fs.linesets.new(name)
        ls.select_border = False           # 地板plane外边界不入线
        ls.select_by_visibility = True
        ls.visibility = vis                # 'VISIBLE'/'HIDDEN'
        if mode == "cad":
            pass  # R28c: ①渲染关bevel→锐边网格crease(145°)抓全部折线, 无需edge_mark/阈值放宽
        if ls.linestyle is None:
            ls.linestyle = bpy.data.linestyles.new(name + "_LS")
        ls.linestyle.color = color
        ls.linestyle.thickness = thick
        if dashed:                         # CAD虚线 = 隐藏棱标准画法 (联合利华四阶段①)
            lsl = ls.linestyle
            if hasattr(lsl, "use_dashed_line"):     # Blender 5.2 改名: use_dashing → use_dashed_line
                lsl.use_dashed_line = True
                lsl.dash1 = 18; lsl.gap1 = 10; lsl.dash2 = 0; lsl.dash3 = 0
            else:
                print("[STAGE] warn: use_dashed_line absent, HIDDEN keeps solid")
    if mode == "cad":
        mk("LS_vis", 'VISIBLE', (0.10, 0.22, 0.85), 3.6)     # 实线: 可见棱(含屋脊/折边结构线, R25加粗)
        mk("LS_hid", 'HIDDEN', (0.40, 0.52, 0.92), 2.0, dashed=True)  # 虚线: 隐藏棱 (CAD内部结构)
    else:
        mk("LS_mesh", 'VISIBLE', (0.10, 0.10, 0.13), 2.6)    # 白模棱线加粗可读

def swap(mats):
    for i, m in enumerate(mats):
        ob.data.materials[i] = m   # 槽位赋值 (clear/append 不触发 depsgraph 重打标, ④曾渲出陈旧材质)
    ob.data.update()
    bpy.context.view_layer.update()

def render_stage(nm, mats, freestyle=None, shadow=True):
    swap(mats)
    set_freestyle(freestyle)
    floor.hide_render = not shadow
    bv.show_render = (freestyle != "cad")   # R28c: ①关bevel渲染→freestyle在锐边网格上全拓扑抓折线(含隐藏虚线), 边标记穿bevel传播不可靠已弃; 1.5mm倒角在板尺度不可见, 几何一致性受控披露
    # R33b 用户判"②③没区别": ②平直着色(faceted clay)=数字模型阶段行业标准视觉语言(NVIDIA白模棱面), 鼓胀位移在细分网格上显形为棱面;
    # ③④光滑连续着色=物理材质/成品。着色风格是"模型→材质"阶段跃迁的显性证据
    flat = nm.startswith("2_mesh")
    ob.data.polygons.foreach_set("use_smooth", [not flat] * len(ob.data.polygons))
    ob.data.update()
    cube = bpy.data.objects.get("Cube")          # R25g: 默认Cube一直在场景里(2m白灰, 热rig下削顶成白色主体污染四格), 排查四格死白时定位
    if cube:
        cube.hide_render = True
    sc.render.filepath = os.path.join(OUT_DIR, f"stage_{nm}.png")
    bpy.ops.render.render(write_still=True)
    img = Image.open(sc.render.filepath).convert("RGBA")
    if shadow:   # 透明film下场景: 合成到spec锚定的环境底 (R34: 实拍环境底中位lum85, 固定238浅灰底=高调过曝感主源且钉死白区p95=238污染统计)
        cb = int(rig.get("cell_bg", 238))
        bgc = Image.new("RGBA", img.size, (cb, cb, cb, 255))
        Image.alpha_composite(bgc, img).convert("RGB").save(sc.render.filepath)
    else:        # CAD: 纯白
        bgc = Image.new("RGBA", img.size, (255, 255, 255, 255))
        Image.alpha_composite(bgc, img).convert("RGB").save(sc.render.filepath)
    print(f"[STAGE] {nm} done")

# ① CAD线框: 蓝色工程折线; R25: 同棚浅灰背景+同地面阴影(四格视觉一致, GPT P1)
sc.render.film_transparent = True
render_stage("1_cad", [mat_cad] * len(orig_slots),
             freestyle="cad", shadow=True)

# ② 白模网格: 粘土 + 灰色拓扑线 + 灯光 + 地面
render_stage("2_mesh", [mat_clay] * len(orig_slots),
             freestyle="mesh", shadow=True)

# ③ 物理材质: 纸板基材(无印刷) + 锁定灯光; 全槽统一paper(含chamfer折边, 材质阶段声明一致性)
render_stage("3_material", [mat_paper] * len(orig_slots), shadow=True)

# ④ 印刷成品: 完整贴图 + 锁定灯光
render_stage("4_final", orig_slots, shadow=True)

# R77: ④过实拍色对齐grade(与hero_match_real同post_grade链) — 系统Python施grade(Blender内numpy出黑块/紫边)
_s4 = os.path.join(OUT_DIR, "stage_4_final.png")
import subprocess as _sp
_r = _sp.run(["python3", os.path.join(BASE, "18_post_grade.py"), "--src", _s4, "--out", _s4],
             capture_output=True, text=True)
print("[STAGE] ④grade:", (_r.stdout or _r.stderr).strip().splitlines()[-1] if (_r.stdout or _r.stderr).strip() else "NOOUT")

# ---- 拼板 (R80: 五阶段抽到 compose_stage_board.py, 第⑤格=实拍裁切; 可单独秒级重拼) ----
import subprocess as _spc
_rc = _spc.run(["python3", os.path.join(BASE, "pipelines/pack_dieline/compose_stage_board.py"),
                "--spec", spec_abs, "--out", os.path.relpath(OUT_DIR, BASE)],
               capture_output=True, text=True)
print((_rc.stdout or _rc.stderr).strip().splitlines()[-1] if (_rc.stdout or _rc.stderr).strip() else "[STAGE] compose NOOUT")
