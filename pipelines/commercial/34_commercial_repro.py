#!/usr/bin/env python3
"""34 - 电商商业图复刻 (Gemini 会话参数格式): 参照=复古木桌+侧逆光商业静物
产品位=经典孪生盒体 (替换参照玻璃瓶商品); 牛奶杯=真3D玻璃+SSS牛奶 (Gemini 参数).

参数表 (源自 Gemini 会话, 尺度适配米制真尺寸):
  玻璃: Transmission 1.0 / Rough 0.04 / IOR 1.45 / Base (1,1,1)
  牛奶: Base (0.96,0.95,0.91) / SSS Weight 0.5 / Radius (0.012,0.010,0.008)m / Rough 0.3
  金属盖: Base (0.85,0.65,0.40) / Metallic 1.0 / Rough 0.25
  木桌: Base (0.25,0.15,0.08) / Rough 0.5 + 拼板缝
  主光: Area 左前上45° 暖5200K / 轮廓光: Area 右后 强度1.6x主光 / World 0.15 暖
  Cycles: transparent_max_bounces 24 / max_bounces 12 / Look Medium High Contrast
运行: Blender -b -P 34_commercial_repro.py -- --res 1920 --samples 256 --out final
产物: output/commercial/repro_{draft,final}.png
"""
import math
import os
import sys

import bpy

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)

import importlib.util as _ilu


def _imp(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    m = _ilu.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


comfy = _imp("comfy01", os.path.join(BASE_DIR, "pipelines/ecommerce/01_comfy_usd_compositor.py"))
heroes = _imp("heroes26", os.path.join(BASE_DIR, "pipelines/commercial/26_creative_heroes.py"))

OUT_DIR = os.path.join(BASE_DIR, "output", "commercial")


DIAG = os.environ.get("REPRO_DIAG", "")
ABL = os.environ.get("REPRO_ABLATE", "")
BOV = os.environ.get("REPRO_BOUNCE", "")


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--res", type=int, default=1920)
    p.add_argument("--samples", type=int, default=256)
    p.add_argument("--out", default="final")
    return p.parse_args(argv)


def fresh(args):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    comfy.setup_metal_engine(samples=args.samples)
    scene = bpy.context.scene
    scene.cycles.max_bounces = 12
    scene.cycles.transparent_max_bounces = 24   # 多层玻璃折射不发黑 (Gemini)
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Very High Contrast"
    scene.render.resolution_x = args.res
    # v102 画幅: RES_ASPECT 未设=1.0 → 与原正方形逐位等价 (冻结分支零影响)
    _aspect = float(os.environ.get("RES_ASPECT", "1.0"))
    scene.render.resolution_y = int(round(args.res / _aspect))
    scene.view_settings.exposure = (-0.60 if os.environ.get("POUR_LOW", "0") == "1" else -2.0) if os.environ.get("POUR", "0") == "1" else -0.60
    if os.environ.get("POUR_EXPO", ""):   # v99 多角度: 逐机位曝光补偿 (未设=分支原值, 冻结分支零影响)
        scene.view_settings.exposure = float(os.environ["POUR_EXPO"])
    world = bpy.data.worlds.new("Env")
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.35, 0.26, 0.18, 1)   # 暖室内环境底色
    bg.inputs[1].default_value = 0.08                     # World Strength 0.15 (Gemini)
    scene.world = world
    return scene


def wood_table():
    """复古深木桌 + 拼板缝"""
    bpy.ops.mesh.primitive_plane_add(size=3.0, location=(0, 0.2, 0.0))
    tb = bpy.context.active_object
    tb.location = (0, -0.05, 0.0)
    tb.scale = (1.0, 2.5 / 3.0, 1.0)   # 远缘截于 fillet 切点 y=1.2
    m = bpy.data.materials.new("WoodRetro")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    # 1) 拼板: 缝沿 X (板条纵深走向), 板宽~16cm, SAW 复位线做缝
    mpP = nt.nodes.new("ShaderNodeMapping")
    mpP.inputs["Scale"].default_value = (6.0, 1.0, 1.0)
    nt.links.new(tc.outputs["Object"], mpP.inputs["Vector"])
    # v72 资产级: 缝坐标低频噪声 warp (板缝自然蜿蜒/板宽微变, 破程序平行规律)
    nsW = nt.nodes.new("ShaderNodeTexNoise")
    nsW.inputs["Scale"].default_value = 0.9
    nsW.inputs["Detail"].default_value = 2.0
    nt.links.new(tc.outputs["Object"], nsW.inputs["Vector"])
    wsub = nt.nodes.new("ShaderNodeVectorMath")
    wsub.operation = "SUBTRACT"
    wsub.inputs[1].default_value = (0.5, 0.5, 0.5)
    nt.links.new(nsW.outputs["Color"], wsub.inputs[0])
    wmul = nt.nodes.new("ShaderNodeVectorMath")
    wmul.operation = "SCALE"
    wmul.inputs["Scale"].default_value = 0.030   # ±1.5cm warp
    nt.links.new(wsub.outputs[0], wmul.inputs[0])
    wadd = nt.nodes.new("ShaderNodeVectorMath")
    wadd.operation = "ADD"
    nt.links.new(mpP.outputs[0], wadd.inputs[0])
    nt.links.new(wmul.outputs[0], wadd.inputs[1])
    wvP = nt.nodes.new("ShaderNodeTexWave")
    wvP.wave_type = "BANDS"
    wvP.bands_direction = "X"
    wvP.wave_profile = "SAW"
    nt.links.new(wadd.outputs[0], wvP.inputs["Vector"])
    rampP = nt.nodes.new("ShaderNodeValToRGB")
    rampP.color_ramp.elements[0].position = 0.0
    rampP.color_ramp.elements[0].color = (0.045, 0.026, 0.014, 1)
    rampP.color_ramp.elements[1].position = 0.05
    rampP.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt.links.new(wvP.outputs[0], rampP.inputs[0])
    # 2) 纤维: 噪声沿 Y 拉伸 (纵向纤维)
    mpF = nt.nodes.new("ShaderNodeMapping")
    mpF.inputs["Scale"].default_value = (30.0, 2.5, 1.0)
    nt.links.new(tc.outputs["Object"], mpF.inputs["Vector"])
    nsF = nt.nodes.new("ShaderNodeTexNoise")
    nsF.inputs["Detail"].default_value = 10.0
    nsF.inputs["Roughness"].default_value = 0.65
    nt.links.new(mpF.outputs[0], nsF.inputs["Vector"])
    # 3) 大尺度色变 (板间色差/老化)
    nsL = nt.nodes.new("ShaderNodeTexNoise")
    nsL.inputs["Scale"].default_value = 1.2
    nsL.inputs["Detail"].default_value = 2.0
    nt.links.new(tc.outputs["Object"], nsL.inputs["Vector"])
    rampL = nt.nodes.new("ShaderNodeValToRGB")
    rampL.color_ramp.elements[0].position = 0.35
    rampL.color_ramp.elements[0].color = (0.095, 0.052, 0.026, 1)
    rampL.color_ramp.elements[1].position = 0.65
    rampL.color_ramp.elements[1].color = (0.145, 0.085, 0.045, 1)
    nt.links.new(nsL.outputs["Fac"], rampL.inputs[0])
    # 纤维调制色
    mixF = nt.nodes.new("ShaderNodeMixRGB")
    mixF.blend_type = "MULTIPLY"
    mixF.inputs["Fac"].default_value = 0.30
    nt.links.new(rampL.outputs[0], mixF.inputs[1])
    nt.links.new(nsF.outputs["Fac"], mixF.inputs[2])
    # 拼板缝乘入
    mixP = nt.nodes.new("ShaderNodeMixRGB")
    mixP.blend_type = "MULTIPLY"
    mixP.inputs["Fac"].default_value = 0.60   # v71 板缝对比 -29%
    nt.links.new(mixF.outputs[0], mixP.inputs[1])
    nt.links.new(rampP.outputs[0], mixP.inputs[2])
    nt.links.new(mixP.outputs[0], b.inputs["Base Color"])
    # 4) roughness 变化 (清漆不匀)
    mrR = nt.nodes.new("ShaderNodeMapRange")
    mrR.inputs["To Min"].default_value = 0.42
    mrR.inputs["To Max"].default_value = 0.62
    nt.links.new(nsF.outputs["Fac"], mrR.inputs["Value"])
    nt.links.new(mrR.outputs[0], b.inputs["Roughness"])
    # 5) 双 bump 链: 纤维细 bump -> 拼板缝 bump
    bpF = nt.nodes.new("ShaderNodeBump")
    bpF.inputs["Strength"].default_value = 0.10
    nt.links.new(nsF.outputs["Fac"], bpF.inputs["Height"])
    bpP = nt.nodes.new("ShaderNodeBump")
    bpP.inputs["Strength"].default_value = 0.22
    nt.links.new(wvP.outputs[0], bpP.inputs["Height"])
    nt.links.new(bpF.outputs[0], bpP.inputs["Normal"])
    nt.links.new(bpP.outputs[0], b.inputs["Normal"])
    tb.data.materials.append(m)
    return tb


def real_glass(loc=(-0.075, -0.040)):
    """真 3D 玻璃杯+牛奶 (Cycles 折射): 2.5D 投影在 V2 标尺下达到天花板, 换物理渲染.
    阴影射线 tint 透明 = 产品 viz 标准 trick (防玻璃死黑阴影)."""
    import mathutils
    x, y = loc
    H, R = 0.105, 0.036
    # v83 锥台杯 (下窄上宽, 用户选定): 均匀壁厚3mm + 底厚6mm + 圆口
    # 淘汰 v74 薄壁2-3mm+超厚底12mm (怪异根源: 白色实心柱塞薄玻璃管)
    prof = [(0.0, 0.0), (0.022, 0.0), (0.025, 0.0015), (0.0265, 0.006),
            (0.0285, 0.020), (0.0310, 0.050), (0.0335, 0.080), (0.0355, 0.100), (0.0360, 0.105),
            (0.0355, 0.1065), (0.0340, 0.1068), (0.0330, 0.1060),
            (0.0325, 0.100), (0.0305, 0.080), (0.0280, 0.050), (0.0255, 0.020),
            (0.0235, 0.010), (0.0200, 0.0065), (0.0, 0.006)]
    me = bpy.data.meshes.new("GlassProfile")
    verts = [(px, 0.0, pz) for px, pz in prof]
    edges = [(i, i + 1) for i in range(len(verts) - 1)]
    me.from_pydata(verts, edges, [])
    g = bpy.data.objects.new("MilkGlass", me)
    bpy.context.collection.objects.link(g)
    g.location = (x, y, 0.0)
    scr = g.modifiers.new("Spin", "SCREW")
    scr.axis = "Z"
    scr.angle = math.radians(360)
    scr.steps = 64
    scr.use_merge_vertices = True
    bpy.context.view_layer.objects.active = g
    bpy.ops.object.modifier_apply(modifier="Spin")
    bpy.ops.object.shade_auto_smooth(angle=math.radians(40))
    gm = bpy.data.materials.new("GlassClear")
    gm.use_nodes = True
    nt = gm.node_tree
    pb = nt.nodes.get("Principled BSDF")
    pb.inputs["Transmission Weight"].default_value = 1.0
    pb.inputs["Roughness"].default_value = 0.015
    pb.inputs["IOR"].default_value = 1.45
    if DIAG:
        # 分路径诊断: 替换表面 BSDF (其余场景冻结)
        ntd = gm.node_tree
        ntd.nodes.clear()
        od = ntd.nodes.new("ShaderNodeOutputMaterial")
        if DIAG == "glossy":
            gd = ntd.nodes.new("ShaderNodeBsdfGlossy")
            gd.inputs["Roughness"].default_value = 0.015
            ntd.links.new(gd.outputs[0], od.inputs["Surface"])
        else:
            rd = ntd.nodes.new("ShaderNodeBsdfRefraction")
            rd.inputs["IOR"].default_value = 1.45
            rd.inputs["Roughness"].default_value = 0.0
            ntd.links.new(rd.outputs[0], od.inputs["Surface"])
        return g
    out = nt.nodes.get("Material Output")
    lp = nt.nodes.new("ShaderNodeLightPath")
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    tr.inputs["Color"].default_value = (0.55, 0.55, 0.53, 1)
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Shadow Ray"], mx.inputs["Fac"])
    nt.links.new(pb.outputs[0], mx.inputs[1])
    nt.links.new(tr.outputs[0], mx.inputs[2])
    nt.links.new(mx.outputs[0], out.inputs["Surface"])
    g.data.materials.append(gm)
    # v79 牛奶一体 spin 剖面: 底贴腔底/壁贴内壁(留0.1mm防z-fight)/顶真弯月面爬升
    # 淘汰 v74 cylinder+悬浮torus (根因: 奶柱底z10穿腔底z12, 壁隙1.25mm空气缝, 弯月面离壁1.3mm)
    MH = 0.066
    ztop = 0.012 + MH   # 液面中心高 78mm (坐腔底 z12, 不再穿底)
    # 内壁剖面插值 (玻璃内腔 r(z)), 牛奶 r = 内壁 - 0.0001
    _inner = [(0.012, 0.0), (0.0125, 0.0220), (0.0145, 0.0290), (0.022, 0.0313),
              (0.050, 0.0318), (0.100, 0.0328)]
    def _ir(z):
        for (z0, r0), (z1, r1) in zip(_inner, _inner[1:]):
            if z0 <= z <= z1:
                return r0 + (r1 - r0) * (z - z0) / (z1 - z0)
        return _inner[-1][1]
    _gap = 0.0001
    _zc = ztop - 0.0025          # v79c 弯月面爬升 2.5mm (DOF 下可见)
    _rw = _ir(ztop) - _gap       # 贴壁半径
    mprof = [(0.0, 0.0121), (0.0219, 0.0126), (0.0289, 0.0146), (0.0312, 0.0221),
             (_ir(0.050) - _gap, 0.050), (_rw, _zc),
             (_rw, ztop), (_rw - 0.0010, ztop - 0.0002), (_rw - 0.0030, ztop - 0.0010),
             (_rw - 0.0070, ztop - 0.0020), (0.0, ztop - 0.0025)]
    mme = bpy.data.meshes.new("MilkProfile")
    mverts = [(px, 0.0, pz) for px, pz in mprof]
    medges = [(i, i + 1) for i in range(len(mverts) - 1)]
    mme.from_pydata(mverts, medges, [])
    mk = bpy.data.objects.new("Milk", mme)
    bpy.context.collection.objects.link(mk)
    mk.location = (x, y, 0.0)
    mscr = mk.modifiers.new("Spin", "SCREW")
    mscr.axis = "Z"
    mscr.angle = math.radians(360)
    mscr.steps = 64
    mscr.use_merge_vertices = True
    bpy.context.view_layer.objects.active = mk
    bpy.ops.object.modifier_apply(modifier="Spin")
    bpy.ops.object.shade_auto_smooth(angle=math.radians(35))
    mm = bpy.data.materials.new("Milk")
    mm.use_nodes = True

    mp = mm.node_tree.nodes.get("Principled BSDF")
    # v80 牛奶=不透明乳浊液 (物理修正): 表面漫反射为主, SSS 仅薄边缘暖透
    # v79b weight0.9 错误=高SSS自发光死白(评审"发光白固体"); 真牛奶不透明, 散射只在边缘
    mp.inputs["Base Color"].default_value = (0.92, 0.90, 0.86, 1)
    mp.inputs["Roughness"].default_value = 0.10   # v89b 液面镜面 (0.18 高光仍弱)
    if "Coat Weight" in mp.inputs:
        mp.inputs["Coat Weight"].default_value = 0.4
        mp.inputs["Coat Roughness"].default_value = 0.08   # 液面亮缘 (专业参考 meniscus 高光)
    if "Subsurface Weight" in mp.inputs:
        mp.inputs["Subsurface Weight"].default_value = 0.15
        mp.inputs["Subsurface Radius"].default_value = (1.0, 0.80, 0.55)
        mp.inputs["Subsurface Scale"].default_value = 0.004
    if "Specular IOR Level" in mp.inputs:
        mp.inputs["Specular IOR Level"].default_value = 0.35
    mk.data.materials.append(mm)
    return g


def camera_mapped_glass(scene, cam, jloc=(-0.052, 0.105)):
    """2.5D 相机投影牛奶杯 (用户方案): 实拍照片经 Window 坐标精确投到锥台代理上.
    代理供轮廓/遮挡/DOF; 照片烘焙真实折射/高光/杯壁; 阴影射线 75% 透射防死黑;
    接地用径向渐变假软影. 单视角英雄图标准 VFX 技法 (camera projection / matte)."""
    import bpy_extras
    import mathutils
    jx, jy = jloc
    H = 0.100
    bpy.ops.mesh.primitive_cone_add(radius1=0.028, radius2=0.0365, depth=H,
                                    location=(jx, jy, H / 2), vertices=48)
    proxy = bpy.context.active_object
    bpy.ops.object.shade_smooth()
    bpy.context.view_layer.update()

    pts = [proxy.matrix_world @ mathutils.Vector(c) for c in proxy.bound_box]
    uv = [bpy_extras.object_utils.world_to_camera_view(scene, cam, p) for p in pts]
    minx, maxx = min(u.x for u in uv), max(u.x for u in uv)
    miny, maxy = min(u.y for u in uv), max(u.y for u in uv)
    sx, sy = (maxx - minx) * 1.02, (maxy - miny) * 1.02
    minx -= (sx - (maxx - minx)) / 2
    miny -= (sy - (maxy - miny)) / 2
    img = bpy.data.images.load(os.path.join(BASE_DIR, "assets", "reference", "milk_glass_crop.png"),
                               check_existing=True)
    img.colorspace_settings.name = "sRGB"
    m = bpy.data.materials.new("MilkGlassProj")
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.vector_type = "POINT"
    mp.inputs["Scale"].default_value = (1.0 / sx, 1.0 / sy, 1.0)
    mp.inputs["Location"].default_value = (-minx / sx, -miny / sy, 0.0)
    nt.links.new(tc.outputs["Window"], mp.inputs["Vector"])
    it = nt.nodes.new("ShaderNodeTexImage")
    it.image = img
    it.extension = "CLIP"
    nt.links.new(mp.outputs[0], it.inputs["Vector"])
    _wm = nt.nodes.new("ShaderNodeMixRGB")
    _wm.blend_type = "MULTIPLY"
    _wm.inputs["Fac"].default_value = 0.55
    _wm.inputs[2].default_value = (1.0, 0.93, 0.82, 1)
    nt.links.new(it.outputs["Color"], _wm.inputs[1])
    _sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    nt.links.new(tc.outputs["Window"], _sep.inputs[0])
    _mr = nt.nodes.new("ShaderNodeMapRange")
    _mr.inputs["From Min"].default_value = 0.0
    _mr.inputs["From Max"].default_value = 0.35
    _mr.inputs["To Min"].default_value = 0.12
    _mr.inputs["To Max"].default_value = 1.0
    nt.links.new(_sep.outputs["Y"], _mr.inputs["Value"])
    _gm = nt.nodes.new("ShaderNodeMixRGB")
    _gm.blend_type = "MULTIPLY"
    _gm.inputs["Fac"].default_value = 1.0
    nt.links.new(_wm.outputs[0], _gm.inputs[1])
    _cmb = nt.nodes.new("ShaderNodeCombineXYZ")
    nt.links.new(_mr.outputs[0], _cmb.inputs["X"])
    nt.links.new(_mr.outputs[0], _cmb.inputs["Y"])
    nt.links.new(_mr.outputs[0], _cmb.inputs["Z"])
    nt.links.new(_cmb.outputs[0], _gm.inputs[2])
    _lw = nt.nodes.new("ShaderNodeLayerWeight")
    _lw.inputs["Blend"].default_value = 0.35
    _lr = nt.nodes.new("ShaderNodeValToRGB")
    _lr.color_ramp.elements[0].position = 0.70
    _lr.color_ramp.elements[1].position = 0.92
    nt.links.new(_lw.outputs["Facing"], _lr.inputs["Fac"])
    _emx = nt.nodes.new("ShaderNodeMixRGB")
    _emx.blend_type = "ADD"
    _emx.inputs[2].default_value = (0.6, 0.6, 0.6, 1)
    nt.links.new(_lr.outputs[0], _emx.inputs["Fac"])
    nt.links.new(_gm.outputs[0], _emx.inputs[1])
    _nz = nt.nodes.new("ShaderNodeTexNoise")
    _nz.inputs["Scale"].default_value = 40.0
    _nz.inputs["Detail"].default_value = 4.0
    _nmx = nt.nodes.new("ShaderNodeMixRGB")
    _nmx.blend_type = "ADD"
    _nmx.inputs["Fac"].default_value = 0.05
    nt.links.new(_emx.outputs[0], _nmx.inputs[1])
    nt.links.new(_nz.outputs["Fac"], _nmx.inputs[2])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Strength"].default_value = 0.55
    nt.links.new(_nmx.outputs[0], em.inputs["Color"])
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    lp = nt.nodes.new("ShaderNodeLightPath")
    mx = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Shadow Ray"], mx.inputs["Fac"])
    nt.links.new(em.outputs[0], mx.inputs[1])
    tr2 = nt.nodes.new("ShaderNodeBsdfTransparent")
    tr2.inputs["Color"].default_value = (0.75, 0.75, 0.75, 1)
    nt.links.new(tr2.outputs[0], mx.inputs[2])
    # 解析锥台剪影掩膜: 抠除照片灰底柱/底带 (Window 坐标梯形)
    _cx = (minx + maxx) / 2
    _dxn = nt.nodes.new("ShaderNodeMath"); _dxn.operation = "SUBTRACT"; _dxn.inputs[1].default_value = _cx
    nt.links.new(_sep.outputs["X"], _dxn.inputs[0])
    _adx = nt.nodes.new("ShaderNodeMath"); _adx.operation = "ABSOLUTE"
    nt.links.new(_dxn.outputs[0], _adx.inputs[0])
    _ty = nt.nodes.new("ShaderNodeMapRange")
    _ty.inputs["From Min"].default_value = miny
    _ty.inputs["From Max"].default_value = maxy
    nt.links.new(_sep.outputs["Y"], _ty.inputs["Value"])
    _rr = nt.nodes.new("ShaderNodeMapRange")
    _rr.inputs["From Min"].default_value = 0.0
    _rr.inputs["From Max"].default_value = 1.0
    _rr.inputs["To Min"].default_value = 0.028
    _rr.inputs["To Max"].default_value = 0.0365
    nt.links.new(_ty.outputs[0], _rr.inputs["Value"])
    _kw = nt.nodes.new("ShaderNodeMath"); _kw.operation = "MULTIPLY"
    _kw.inputs[1].default_value = (sx / 2) / 0.0365
    nt.links.new(_rr.outputs[0], _kw.inputs[0])
    _dv = nt.nodes.new("ShaderNodeMath"); _dv.operation = "DIVIDE"
    nt.links.new(_adx.outputs[0], _dv.inputs[0])
    nt.links.new(_kw.outputs[0], _dv.inputs[1])
    _mrg = nt.nodes.new("ShaderNodeMapRange")
    _mrg.inputs["From Min"].default_value = 0.90
    _mrg.inputs["From Max"].default_value = 1.0
    _mrg.inputs["To Min"].default_value = 1.0
    _mrg.inputs["To Max"].default_value = 0.0
    nt.links.new(_dv.outputs[0], _mrg.inputs["Value"])
    _ftr = nt.nodes.new("ShaderNodeBsdfTransparent")
    _fmix = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(_mrg.outputs[0], _fmix.inputs["Fac"])
    nt.links.new(_ftr.outputs[0], _fmix.inputs[1])
    nt.links.new(mx.outputs[0], _fmix.inputs[2])
    nt.links.new(_fmix.outputs[0], out.inputs["Surface"])
    proxy.data.materials.append(m)
    # 接地假软影: 径向渐变暗斑
    bpy.ops.mesh.primitive_circle_add(radius=0.065, fill_type='NGON', location=(jx, jy, 0.0015), vertices=48)
    sh = bpy.context.active_object
    sm = bpy.data.materials.new("ContactShadow")
    sm.use_nodes = True
    nt2 = sm.node_tree
    nt2.nodes.clear()
    o2 = nt2.nodes.new("ShaderNodeOutputMaterial")
    tc2 = nt2.nodes.new("ShaderNodeTexCoord")
    gr = nt2.nodes.new("ShaderNodeTexGradient")
    gr.gradient_type = "SPHERICAL"
    mp2 = nt2.nodes.new("ShaderNodeMapping")
    mp2.inputs["Scale"].default_value = (18.0, 18.0, 18.0)
    nt2.links.new(tc2.outputs["Object"], mp2.inputs["Vector"])
    nt2.links.new(mp2.outputs[0], gr.inputs["Vector"])
    rp = nt2.nodes.new("ShaderNodeValToRGB")
    rp.color_ramp.elements[0].position = 0.0
    rp.color_ramp.elements[0].color = (0, 0, 0, 1)
    rp.color_ramp.interpolation = "EASE"
    rp.color_ramp.elements[1].position = 0.35
    rp.color_ramp.elements[1].color = (1, 1, 1, 1)
    nt2.links.new(gr.outputs[0], rp.inputs[0])
    tr3 = nt2.nodes.new("ShaderNodeBsdfTransparent")
    df = nt2.nodes.new("ShaderNodeBsdfDiffuse")
    df.inputs["Color"].default_value = (0.03, 0.025, 0.022, 1)
    mx2 = nt2.nodes.new("ShaderNodeMixShader")
    nt2.links.new(rp.outputs[0], mx2.inputs["Fac"])
    nt2.links.new(df.outputs[0], mx2.inputs[1])
    nt2.links.new(tr3.outputs[0], mx2.inputs[2])
    nt2.links.new(mx2.outputs[0], o2.inputs["Surface"])
    sh.data.materials.append(sm)
    sh.visible_shadow = False
    return proxy




def lighting():
    """商业侧逆光: 主光左前上45°暖5200K + 轮廓光右后1.6x (Gemini)"""
    import mathutils as _mu
    key = bpy.data.lights.new("Key", "SPOT")
    key.energy = 1.2 if (os.environ.get("POUR", "0") == "1" and os.environ.get("POUR_LOW", "0") != "1") else 2.45
    key.spot_size = math.radians(30)
    key.spot_blend = 0.5
    key.shadow_soft_size = float(os.environ.get("KEY_SIZE", "0.06"))
    key.color = (1.0, 0.87, 0.72)   # ~5200K 暖
    ko = bpy.data.objects.new("Key", key)
    bpy.context.scene.collection.objects.link(ko)
    ko.location = (-0.55, -0.45, 0.55)
    kd = _mu.Vector((0, 0, 0.10)) - _mu.Vector(ko.location)
    ko.rotation_euler = kd.to_track_quat("-Z", "Y").to_euler()
    rim = bpy.data.lights.new("Rim", "AREA")
    rim.energy = 30 if (os.environ.get("POUR", "0") == "1" and os.environ.get("POUR_LOW", "0") != "1") else 60
    if os.environ.get("RIM_W", ""):   # v99 多角度: 逐机位轮廓光补偿 (背面机位 rim 变主光, 未设=分支原值)
        rim.energy = float(os.environ["RIM_W"])
    rim.spread = math.radians(20)
    rim.size = 0.12
    rim.color = (1.0, 0.93, 0.82)
    ro = bpy.data.objects.new("Rim", rim)
    bpy.context.scene.collection.objects.link(ro)
    ro.location = (0.30, 0.62, 0.55)
    rd = _mu.Vector((0.0, 0.02, 0.13)) - _mu.Vector(ro.location)
    ro.rotation_euler = rd.to_track_quat("-Z", "Y").to_euler()
    ro.visible_glossy = False   # 杀桌面镜反射带, 保留盒体漫射勾边
    ro.visible_shadow = False


def studio_rig(scene):
    """v101 商业棚拍反射场 (GPT技术评审 P0 最高杠杆单变量实验).
    只改布光: 大柔光箱主光 + 两条可见玻璃反射条 + 黑旗 + 低功率SPOT塑桌面.
    Filmic/f8/材质/几何全部冻结 → 归因"布光导致的CG感" vs "几何材质导致的CG感".
    能量按灯具面积/距离重标定, 不套用旧SPOT数值 (GPT明确警告)."""
    import mathutils as _ms
    _aim = _ms.Vector((0.0, 0.0, 0.12))

    def _rect(name, loc, w, h, energy, color=(1.0, 0.97, 0.92), target=None):
        li = bpy.data.lights.new(name, "AREA")
        li.shape = "RECTANGLE"
        li.size = w
        li.size_y = h
        li.energy = energy
        li.color = color
        ob = bpy.data.objects.new(name, li)
        scene.collection.objects.link(ob)
        ob.location = loc
        _t = target if target is not None else _aim
        ob.rotation_euler = (_t - _ms.Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        return ob

    # A 主柔光箱: 大面积→软阴影 + 纸盒平滑明暗过渡 (替代SPOT主导)
    _rect("StudioKey", (-0.45, -0.55, 0.60),
          float(os.environ.get("RIG_KEY_W", "0.65")), float(os.environ.get("RIG_KEY_H", "0.90")),
          float(os.environ.get("RIG_KEY_E", "60")))
    # B 后侧分离光: 暗背景中勾出蓝盒轮廓
    _rect("StudioSep", (0.10, 0.55, 0.45), 0.20, 0.65,
          float(os.environ.get("RIG_SEP_E", "25")), color=(1.0, 0.95, 0.88))
    # C/D 玻璃反射条: 窄而连续亮边 (必须参与 glossy 路径才有灯型反射)
    _gc = _ms.Vector((-0.075, -0.040, 0.07))
    _rect("GlassStripL", (-0.30, -0.20, 0.10), 0.06, 0.45,
          float(os.environ.get("RIG_SL_E", "15")), target=_gc)
    _rect("GlassStripR", (0.24, -0.22, 0.10), 0.04, 0.35,
          float(os.environ.get("RIG_SR_E", "10")), target=_gc)
    # E 黑旗: 深色反射条→玻璃曲面体积感 (纯遮挡, 只进反射不进画面)
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.30, 0.05, 0.12))
    _flag = bpy.context.active_object
    _flag.name = "BlackFlag"
    _flag.rotation_euler = (0, math.radians(-90), 0)   # 法线 -X (朝玻璃)
    _flag.scale = (0.50, 0.15, 1.0)                    # 局部X→世界Z: 0.5m高 0.15m深
    _fm = bpy.data.materials.new("FlagBlack")
    _fm.use_nodes = True
    _fb = _fm.node_tree.nodes.get("Principled BSDF")
    _fb.inputs["Base Color"].default_value = (0.01, 0.01, 0.01, 1)
    _fb.inputs["Roughness"].default_value = 0.9
    _flag.data.materials.append(_fm)
    _flag.visible_camera = False
    # 旧灯降权: SPOT只塑桌面; Rim恢复glossy参与 (原 visible_glossy=False 杀灯型反射=反效果)
    bpy.data.lights["Key"].energy = float(os.environ.get("RIG_SPOT_E", "0.6"))
    bpy.data.objects["Rim"].visible_glossy = True
    bpy.data.lights["Rim"].energy = float(os.environ.get("RIG_RIM_E", "20"))
    bpy.data.lights["BgWash"].energy = float(os.environ.get("RIG_WASH_E", "1.5"))
    # F 食物造型光: 只照可颂+盘 (光链接隔离), 独立能量标定
    _rect("FoodKey", (0.05, -0.35, 0.35), 0.30, 0.30,
          float(os.environ.get("RIG_FOOD_E", "6")), target=_ms.Vector((0.114, 0.02, 0.035)))


def apply_light_linking(scene, carton=None):
    """v101 光链接: 每盏灯只照该照的物体 (GPT"每种光都有明确职责").
    能量阶梯三档全FAIL根因=无职责隔离: 主柔光箱把可颂/玻璃一起打爆,
    等比降能量又让纸盒跌破曝光基线 → 必须按物体分光.
    必须在渲染前调用: studio_rig 建于物体创建之前, 此时对象尚不存在."""
    def _coll(name, objs):
        c = bpy.data.collections.new(name)
        scene.collection.children.link(c)
        for o in objs:
            if o is not None:
                c.objects.link(o)
        return c

    def _by_mat(names):
        return [o for o in scene.objects if o.type == 'MESH'
                and any(m and m.name in names for m in o.data.materials)]

    # v101 回归修复: 盒体由调用点传入(1L=Carton1L, 250ml=Carton_{sku}), 不硬编码
    _carton = carton if carton is not None else bpy.data.objects.get("Carton1L")
    _pack = ([_carton] + [c for c in _carton.children if c.type == 'MESH']) if _carton else []
    _glass = _by_mat({"GLS0002_Glass", "GlassClear"})   # v101: proc分支材质名GlassClear(199行)
    _liquid = _by_mat({"Milk", "MilkHero"})
    _plate = bpy.data.objects.get("Plate")
    # v101 漏光修复: glTF 节点名为小写 'croissant'(网格名才是 Croissant_...),
    # 原 startswith("Croissant") 漏掉可颂 → FoodKey 只照到盘(=1), 可颂欠曝88.4
    _food = [o for o in scene.objects if o.type == 'MESH' and "croissant" in o.name.lower()]
    if _plate is not None:
        _food.append(_plate)
    _flag = bpy.data.objects.get("BlackFlag")
    _map = {
        # v101 架构修复: 柔光箱必须照玻璃(软反射), 只把食物摘出去交FoodKey.
        # 曾把receiver限为纸盒 → 玻璃只剩窄反射条, periodic 0.530→0.826(比基线0.730更差)
        "StudioKey": _pack + _glass + _liquid,   # A 主柔光箱: 纸盒明暗过渡 + 玻璃软反射
        "StudioSep": _pack + _glass + _liquid,   # B 分离光: 勾轮廓, 玻璃保留软边
        "GlassStripL": _glass + _liquid,   # C 玻璃反射条: 只进杯/液
        "GlassStripR": _glass + _liquid,   # D 第二条反射轮廓
        "FoodKey": _food,              # F 食物光: 只照可颂+盘
    }
    _glass_mode = os.environ.get("GLASS", "model")
    for _ln, _objs in _map.items():
        _ob = bpy.data.objects.get(_ln)
        if _ob is None:
            continue
        if not _objs:
            # 该分支无此类物体(GLASS=proc 不建盘/可颂): 灭灯防溢光, 不静默漏光
            _ob.data.energy = 0.0
            print("[RIG-LINK] %s 无受体 → energy=0" % _ln)
            continue
        _ob.light_linking.receiver_collection = _coll("LL_" + _ln, _objs)
        if _flag is not None and _ln.startswith("GlassStrip"):
            _ob.light_linking.blocker_collection = _coll("LB_" + _ln, [_flag])
    print("[RIG-LINK] " + ", ".join("%s=%d" % (k, len(v)) for k, v in _map.items()))
    # 断言按分支预期(防静默漏光, 又不误崩合法组合): model分支建盘+可颂, proc分支只建玻璃
    assert _pack, "[RIG-LINK] 纸盒职责集为空"
    assert _glass, "[RIG-LINK] 玻璃职责集为空(查 GLS0002_Glass / GlassClear)"
    if _glass_mode == "model":
        assert _food, "[RIG-LINK] 食物职责集为空(model分支应建盘+可颂)"


def import_glass_model(loc=(-0.075, -0.040), fill=0.72):
    """v84 开源真模玻璃杯 (用户"手搓剖面怪异"→换开源模型): Tall Drinking Glass
    by AleixoAlonso, CC-BY-4.0 (署名入台账), 1468 面, 自带 KHR_transmission 玻璃材质.
    glTF 导入必须在管线最末 (ops 污染坑); 牛奶圆柱按实测内腔半径收寸."""
    import mathutils as _mv
    x, y = loc
    bpy.ops.import_scene.gltf(filepath=os.path.join(BASE_DIR, "assets", "models", "glass_tall", "scene.gltf"))
    # 只抓 glTF 带来的网格 (按玻璃材质过滤; bpy.data.objects 全场含产线 mesh 不可裸抓)
    meshes = [o for o in bpy.data.objects if o.type == 'MESH'
              and any(m.name == "GLS0002_Glass" for m in o.data.materials)]
    assert meshes, "glass mesh not found by material"
    # v85 游戏资产玻璃=零厚度壳 → Cycles 全内反射读作金属 (用户"不像玻璃"根因)
    # Solidify 实体化 2mm 真实壁厚 (外壳+内壁+杯口圈=真体积, 折射才成立)
    _nv0 = len(meshes[0].data.vertices)
    sol = meshes[0].modifiers.new("Solidify", "SOLIDIFY")
    sol.thickness = -0.002    # 局部单位 (米), 向内
    sol.offset = -1
    sol.use_rim = True
    bpy.context.view_layer.objects.active = meshes[0]
    meshes[0].select_set(True)
    with bpy.context.temp_override(active_object=meshes[0], selected_editable_objects=[meshes[0]],
                                   selected_objects=[meshes[0]]):
        bpy.ops.object.modifier_apply(modifier="Solidify")
    me = meshes[0].data
    _nv1 = len(me.vertices)
    assert _nv1 > _nv0, f"solidify failed (verts {_nv0}->{_nv1})"
    print(f"[GLASS-MODEL] solidify verts {_nv0}->{_nv1}")
    # v98b E2: 玻璃微 roughness 0->0.02 (棱纹硬反射"金属感"柔化, 锐边几何保留); IOR 保 1.45
    _gm = bpy.data.materials.get("GLS0002_Glass")
    if _gm and _gm.use_nodes:
        _gb = _gm.node_tree.nodes.get("Principled BSDF")
        if _gb:
            _gb.inputs["Roughness"].default_value = 0.02
            print("[GLASS-MODEL] roughness 0.02 applied")
    # v98 E10-A 棱面振幅软化 (GPT P0"重复像太干净直均匀强烈"): 径向向均值半径收缩 35%
    # 棱脊变浅 -> 折射重复像对比降, 保留条纹杯纹理 (非 smooth 糊棱, 是振幅缩放)
    _me_g = meshes[0].data
    _rs = [math.hypot(v.co.x, v.co.y) for v in _me_g.vertices if math.hypot(v.co.x, v.co.y) > 1e-6]
    _r_mean = sum(_rs) / len(_rs)
    _FLUTE_SOFT = float(os.environ.get("FLUTE_SOFT", "0.55"))
    import random as _fr
    _fr.seed(11)
    # 每棱随机振幅系数 (破完美周期=机械感根因): 按方位角分 24 扇区, 各扇区独立缩放
    _n_sec = 24
    _sec_k = [_fr.uniform(0.72, 1.28) for _ in range(_n_sec)]
    # v101 壁厚保全(WALL_FIX=1): Solidify 2mm壁厚在618行先应用, 原缩放对内外壁
    # 一视同仁拉向r_mean → 壁厚同比压扁 t=0.002*(1-soft)*sec_k
    # (soft=0.55→0.65~1.15mm; soft=0.85→0.22~0.38mm=近零厚度壳→全内反射→盲评"金属栅栏")
    # 修法: 只缩外壁(前_nv0个=原始顶点), 内壁按缩放前捕获的偏移向量重建
    # → 壁厚与方向(侧壁径向/杯底法向)同时保全; 未设WALL_FIX时逐位不变
    _WALL_FIX = os.environ.get("WALL_FIX", "0") == "1"
    _offs = None
    if _WALL_FIX and _nv1 == 2 * _nv0:
        _offs = [(_me_g.vertices[_i + _nv0].co - _me_g.vertices[_i].co).copy()
                 for _i in range(_nv0)]
    _vlist = _me_g.vertices[:_nv0] if _offs is not None else _me_g.vertices
    for _v in _vlist:
        _r = math.hypot(_v.co.x, _v.co.y)
        if _r > 1e-6:
            _ang = math.atan2(_v.co.y, _v.co.x)
            _sec = int((_ang + math.pi) / (2 * math.pi) * _n_sec) % _n_sec
            _r_new = _r_mean + (_r - _r_mean) * (1.0 - _FLUTE_SOFT) * _sec_k[_sec]
            _sc_f = _r_new / _r
            _v.co.x *= _sc_f
            _v.co.y *= _sc_f
    if _offs is not None:
        for _i, _off in enumerate(_offs):
            _me_g.vertices[_i + _nv0].co = _me_g.vertices[_i].co + _off
        _wt = [o.length for o in _offs if o.length > 1e-6]
        print("[GLASS-WALL] 壁厚保全: n=%d min=%.2fmm max=%.2fmm (设计2.00mm)"
              % (len(_wt), min(_wt) * 1000, max(_wt) * 1000))
    _me_g.update()
    # v98 E10-B (GPT 优先): 内壁圆滑 -- solidify 内壁继承外壁棱面=双重棱面放大重复像
    # 真实压制棱面玻璃内壁光滑。内壁顶点 (r<r_mean) 径向平滑到圆 (周向移动平均), 外壁保棱面
    _INNER_SMOOTH = float(os.environ.get("INNER_SMOOTH", "1"))
    if _INNER_SMOOTH > 0:
        _inner = [v for v in _me_g.vertices if 1e-6 < math.hypot(v.co.x, v.co.y) < _r_mean]
        # 按 z 分层, 每层内壁顶点按角度排序, 半径做周向移动平均 (窗口 5)
        from collections import defaultdict as _dd
        _layers = _dd(list)
        for v in _inner:
            _zk = round(v.co.z, 5)
            _layers[_zk].append(v)
        for _zk, _vs in _layers.items():
            _vs.sort(key=lambda v: math.atan2(v.co.y, v.co.x))
            _rs = [math.hypot(v.co.x, v.co.y) for v in _vs]
            _n = len(_vs)
            if _n < 5:
                continue
            _sm = [sum(_rs[(i + d) % _n] for d in range(-2, 3)) / 5 for i in range(_n)]
            for v, _r_new in zip(_vs, _sm):
                _r = math.hypot(v.co.x, v.co.y)
                _sc_f = _r_new / _r
                v.co.x *= _sc_f
                v.co.y *= _sc_f
        _me_g.update()
    if _WALL_FIX and _nv1 == 2 * _nv0:
        # v101 真实测量(非自证): 上面 [GLASS-WALL] 用的是我自己重放的偏移向量=同义反复;
        # INNER_SMOOTH 之后还会改内壁半径 → 必须对**最终网格**逐对量真实壁厚
        _wt2 = [(_me_g.vertices[_i + _nv0].co - _me_g.vertices[_i].co).length
                for _i in range(_nv0)]
        _wt2 = [t for t in _wt2 if t > 1e-6]
        _wt2.sort()
        print("[GLASS-WALL-FINAL] 最终壁厚 n=%d min=%.2f p05=%.2f p50=%.2f max=%.2f mm"
              % (len(_wt2), _wt2[0] * 1000, _wt2[int(len(_wt2) * 0.05)] * 1000,
                 _wt2[len(_wt2) // 2] * 1000, _wt2[-1] * 1000))
    print(f"[GLASS-MODEL] flute soft {_FLUTE_SOFT} + jitter + inner_smooth={_INNER_SMOOTH}: r_mean={_r_mean:.4f}")
    bpy.context.view_layer.update()
    # 世界坐标实测 (ops 污染下 transform_apply 不可信)
    wv = [(meshes[0].matrix_world @ v.co) for v in me.vertices]
    _zs = [p.z for p in wv]
    zmin, zmax = min(_zs), max(_zs)
    r_out = max(math.hypot(p.x, p.y) for p in wv)
    # v86 比例修复: hero 盒体 HERO_S=2.4 放大 (真实136mm→326mm) → 杯 125mm 只有盒高 38%
    # (真实世界杯≈盒高85%) = "比例不真实"。目标: 高 195mm (盒高 60%) + 径 105mm (真实杯宽比 1.86:1)
    # v88 用户裁定: 杯太高, 至少减 50% → 150→70mm (-53%), 径 62mm 保持 (=盒宽 1.29×)
    # 矮墩直身杯 1.13:1 (rocks 类), 深度仍在焦平面 0.62m 全杯锐利
    _h_t, _d_t = 0.070, 0.062
    sw = _d_t / (2 * r_out)
    sh = _h_t / (zmax - zmin)
    mo = meshes[0]
    mo.scale = (sw, sw, sh)
    mo.location = (x, y, 0.0)
    bpy.context.view_layer.objects.active = mo
    mo.select_set(True)
    with bpy.context.temp_override(active_object=mo, selected_editable_objects=[mo],
                                   selected_objects=[mo]):
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # v98b E2 回滚 smooth-by-angle: 30°>棱纹面间角=棱纹锐边全糊=磨砂玻璃 (vision 3/10)。改材质微 roughness 柔化硬反射, 几何保 flat 锐棱
    # 缩放烘焙后 local=world, 直接用网格顶点实测 (半径一律相对杯心, 世界原点会被 loc 污染)
    _pts = [(mo.matrix_world @ v.co) for v in me.vertices]
    _cx, _cy = x, y
    _rel = [(p.x - _cx, p.y - _cy, p.z) for p in _pts]
    _zs = [t[2] for t in _rel]
    zmin, zmax = min(_zs), max(_zs)
    zlo = zmin + (zmax - zmin) * 0.45
    zhi = zmin + (zmax - zmin) * 0.60
    rads = [math.hypot(t[0], t[1]) for t in _rel if zlo <= t[2] <= zhi]
    r_out = max(math.hypot(t[0], t[1]) for t in _rel)
    # v87b 射线内测真内壁: 从杯心向外 ray_cast 首 hit=内壁 (顶点聚类会被罗纹凹谷骗,
    # v87 曾把外壁纹谷 43.1mm 当内径 → 43mm 奶柱穿壁 4mm, 杯身中段被白色奶块"替换")
    dg = bpy.context.evaluated_depsgraph_get()
    _zs_probe = [zmin + (zmax - zmin) * f for f in (0.35, 0.45, 0.55, 0.65)]
    _hits = []
    for _pz in _zs_probe:
        for _dx, _dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (0.707, 0.707), (-0.707, -0.707)):
            hit, loc, nrm, idx, ob, mw = bpy.context.scene.ray_cast(
                dg, _mv.Vector((_cx, _cy, _pz)), _mv.Vector((_dx, _dy, 0)))
            if hit and ob.original == mo:
                _hits.append(math.hypot(loc.x - _cx, loc.y - _cy))
    assert _hits, "ray cast hit no glass"
    r_in = (sum(_hits) / len(_hits)) - 0.0008
    assert r_in < r_out - 0.0015, f"r_in sanity fail: r_in={r_in*1000:.1f} r_out={r_out*1000:.1f}"
    # 实测内腔底: 下段 30% 内、半径 < 内壁 80% 的最高顶点
    _zc = zmin + (zmax - zmin) * 0.30
    _zc_rmax = r_in * 0.8
    _floors = [t[2] for t in _rel if t[2] < _zc and math.hypot(t[0], t[1]) < _zc_rmax]
    _floor = (max(_floors) if _floors else zmin + 0.005) + 0.0005
    rim_z = zmax
    ztop = _floor + (rim_z - _floor) * fill   # v87 杯身 58% (专业参考 55-60%); v93 POUR=0.82 注入中
    MH = ztop - _floor
    # v101 潜伏bug修复: 把实测杯内径/杯心挂到玻璃对象, 供液体裁剪同源读取
    # (原 build_pour_sim 硬编码 _GR=0.0235, FLUTE_SOFT 改径向几何后液体被全裁空 → max() 崩)
    mo["cup_r_in"] = r_in
    mo["cup_cx"] = x
    mo["cup_cy"] = y
    bpy.ops.mesh.primitive_cylinder_add(radius=r_in - 0.0008, depth=MH,
                                        location=(x, y, _floor + MH / 2), vertices=64)
    mk = bpy.context.active_object
    # v98 E31b 顶盖细分 (grid_fill 清空 mesh 回退): subdivide n-gon 生成内部顶点供位移
    import bmesh as _bmk
    _bmk_obj = _bmk.new()
    _bmk_obj.from_mesh(mk.data)
    _top_faces = [f for f in _bmk_obj.faces if all(v.co.z > MH / 2 - 0.001 for v in f.verts)]
    if _top_faces:
        _bmk.ops.subdivide_edges(_bmk_obj, edges=list({e for f in _top_faces for e in f.edges}), cuts=8, use_grid_fill=True)
    _bmk_obj.to_mesh(mk.data)
    _bmk_obj.free()
    for _c in list(mk.users_collection):
        _c.objects.unlink(mk)
    bpy.context.scene.collection.objects.link(mk)   # ops 污染坑: 强链防静默不渲

    mm = bpy.data.materials.new("Milk")
    mm.use_nodes = True
    mp = mm.node_tree.nodes.get("Principled BSDF")
    mp.inputs["Base Color"].default_value = (0.82, 0.80, 0.76, 1)   # v98 E26 降白 (液面死白真根因: 此 Milk 材质独立于 MilkHero, E22/E25 改错对象)
    mp.inputs["Roughness"].default_value = 0.30   # 粗糙化破液面镜像
    if "Coat Weight" in mp.inputs:
        mp.inputs["Coat Weight"].default_value = 0.05   # 0.4->0.05 去亮膜 (coat 镜面=死白主因)
        mp.inputs["Coat Roughness"].default_value = 0.2
    if "Subsurface Weight" in mp.inputs:
        mp.inputs["Subsurface Weight"].default_value = 0.10
        mp.inputs["Subsurface Radius"].default_value = (0.02, 0.015, 0.01)   # 1.0m->2cm (原 radius 过大=奶面发光)
        mp.inputs["Subsurface Scale"].default_value = 0.002
    mk.data.materials.append(mm)
    # v98 E30 顶盖=可见液面: 弯月爬升 2mm + 入射冲击坑 3mm + 涟漪环 (引擎液体被顶盖遮挡, 交互须在此)
    _mk_r = r_in - 0.0008
    _mk_top = _floor + MH
    _imp_lx, _imp_ly = -0.080 - x, 0.009 - y   # 入射点 local 坐标 (世界 -0.080,0.009)
    for _v in mk.data.vertices:
        if _v.co.z > MH / 2 - 0.001:   # 顶盖顶点
            _rr = math.hypot(_v.co.x, _v.co.y)
            _t_n = min(1.0, _rr / _mk_r)
            _ri = math.hypot(_v.co.x - _imp_lx, _v.co.y - _imp_ly)
            # v98 E34 回退冲击凹陷 (E33 凹陷被读作机械圆孔): 只留弯月爬升, 液面交互止损 (16 轮 E18-E33 均不可见/伪影)
            _meniscus = 0.0015 * (_t_n ** 3)
            _v.co.z += _meniscus
    # glTF 玻璃材质收尾: Alpha 1 + OPAQUE (alpha blend 废折射) + IOR + 阴影射线透明 (对齐产线惯例)
    for m2 in bpy.data.materials:
        if m2.name == "GLS0002_Glass":
            bnt2 = m2.node_tree
            for n in bnt2.nodes:
                if n.type == 'BSDF_PRINCIPLED':
                    n.inputs["Alpha"].default_value = 1.0
                    n.inputs["Roughness"].default_value = 0.01
                    if "Metallic" in n.inputs:
                        # v85b 根因: glTF metallicFactor 缺省=1.0 → Blender 导入全金属压过
                        # Transmission → 镜面金属感 (用户"不像玻璃"); Sketchfab 网页预览器
                        # 认 KHR_transmission 显示玻璃, Cycles 认 Metallic 显示金属
                        n.inputs["Metallic"].default_value = 0.0
                    if "IOR" in n.inputs:
                        n.inputs["IOR"].default_value = 1.45
            m2.blend_method = 'OPAQUE'
            # Is Shadow Ray → Transparent (防玻璃死黑阴影)
            _out2 = next((n for n in bnt2.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output), None)
            _pb2 = next(n for n in bnt2.nodes if n.type == 'BSDF_PRINCIPLED')
            if _out2 and _pb2:
                _lp2 = bnt2.nodes.new("ShaderNodeLightPath")
                _tr2 = bnt2.nodes.new("ShaderNodeBsdfTransparent")
                _tr2.inputs["Color"].default_value = (0.62, 0.62, 0.60, 1)
                _mx2 = bnt2.nodes.new("ShaderNodeMixShader")
                bnt2.links.new(_lp2.outputs["Is Shadow Ray"], _mx2.inputs["Fac"])
                bnt2.links.new(_pb2.outputs[0], _mx2.inputs[1])
                bnt2.links.new(_tr2.outputs[0], _mx2.inputs[2])
                bnt2.links.new(_mx2.outputs[0], _out2.inputs["Surface"])
    print(f"[GLASS-MODEL] sw={sw:.3f} sh={sh:.3f} r_in={r_in*1000:.1f}mm milk_h={MH*1000:.0f}mm loc=({x},{y})")
    return mo, mk


def import_plate(loc=(0.114, 0.02)):
    """v92 白瓷盘 (程序化轮廓旋转体): r_out 85mm, 井底 62mm 半径 z6mm, 盘沿 14mm.
    可颂托盘 (用户"面包不能直接放桌上"); 位置约束: 足迹距盒角≥5mm, 右缘<13° 半视场."""
    import bmesh, mathutils
    x, y = loc
    # v98 E3 浅凹薄边餐盘重建 (GPT P1"带倒角的实心圆柱体"): 底面凹穹顶 (中心悬空 4mm, 足圈着地)
    # + 盘沿壁 11mm→3mm + 盘面浅凹连续曲面 (井底 z4→沿 z12.5 缓升)
    prof = [(0.000, 0.0040), (0.040, 0.0045), (0.055, 0.0058), (0.065, 0.0082),
            (0.075, 0.0110), (0.082, 0.0128), (0.085, 0.0125),
            (0.085, 0.0095), (0.082, 0.0060), (0.075, 0.0035), (0.068, 0.0018),
            (0.062, 0.0012), (0.058, 0.0012), (0.058, 0.0000), (0.050, 0.0000),
            (0.040, 0.0025), (0.020, 0.0038), (0.000, 0.0040)]
    bm = bmesh.new()
    verts = [bm.verts.new((r, 0.0, z)) for r, z in prof]
    for a, b in zip(verts, verts[1:]):
        bm.edges.new((a, b))
    bmesh.ops.spin(bm, geom=bm.verts[:] + bm.edges[:], axis=(0, 0, 1),
                   cent=(0, 0, 0), angle=math.radians(360), steps=96, use_duplicate=False)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    me = bpy.data.meshes.new("Plate")
    bm.to_mesh(me); bm.free()
    po = bpy.data.objects.new("Plate", me)
    bpy.context.scene.collection.objects.link(po)
    po.location = (x, y, 0.0)
    pm = bpy.data.materials.new("PlateCeramic")
    pm.use_nodes = True
    pp = pm.node_tree.nodes.get("Principled BSDF")
    pp.inputs["Base Color"].default_value = (0.90, 0.88, 0.85, 1)
    pp.inputs["Roughness"].default_value = 0.16
    if "Coat Weight" in pp.inputs:
        pp.inputs["Coat Weight"].default_value = 0.5
        pp.inputs["Coat Roughness"].default_value = 0.06
    po.data.materials.append(pm)
    for _pp2 in me.polygons:
        _pp2.use_smooth = True   # v98 E3: 连续曲面高光 (flat=圆台感)
    print(f"[PLATE] r_out=85mm loc=({x},{y}) shallow-rebuilt")


def import_croissant(loc=(0.114, 0.02), rot_z_deg=50.0, target_len=0.120, z0=0.006):
    """v90 面包道具: PolyHaven croissant (CC0) — 奶+面包经典早餐静物组合.
    glTF 管线最末导入 (ops 污染坑); v92 120mm 上盘 (z0=盘井底 6mm), 对角摆位."""
    import mathutils as _cv
    x, y = loc
    before = {o.name for o in bpy.data.objects}
    bpy.ops.import_scene.gltf(filepath=os.path.join(BASE_DIR, "assets", "models", "croissant", "croissant_4k.gltf"))
    news = [o for o in bpy.data.objects if o.type == 'MESH' and o.name not in before]
    mo = news[0]
    for o in news[1:]:
        o.data = mo.data  # 单网格假设外的兜底: 并入主网格数据
        bpy.data.objects.remove(o)
    mo.parent = None  # 脱父链防 glTF 空物体变换污染
    bpy.context.view_layer.update()
    mn = [1e9] * 3; mx = [-1e9] * 3
    for v in mo.data.vertices:
        p = mo.matrix_world @ v.co
        for k in range(3):
            mn[k] = min(mn[k], p[k]); mx[k] = max(mx[k], p[k])
    size = [mx[k] - mn[k] for k in range(3)]
    sc = target_len / size[0]
    M = _cv.Matrix.Scale(sc, 4) @ _cv.Euler((0, 0, math.radians(rot_z_deg))).to_matrix().to_4x4()
    mo.matrix_world = M @ mo.matrix_world
    bpy.context.view_layer.update()
    mn = [1e9] * 3; mx = [-1e9] * 3
    for v in mo.data.vertices:
        p = mo.matrix_world @ v.co
        for k in range(3):
            mn[k] = min(mn[k], p[k]); mx[k] = max(mx[k], p[k])
    cx, cy = (mn[0] + mx[0]) / 2, (mn[1] + mx[1]) / 2
    mo.matrix_world = _cv.Matrix.Translation((x - cx, y - cy, -mn[2] + z0)) @ mo.matrix_world
    bpy.context.view_layer.update()
    for m2 in mo.data.materials:
        if m2 and m2.use_nodes:
            for n in m2.node_tree.nodes:
                if n.type == 'BSDF_PRINCIPLED':
                    n.inputs["Alpha"].default_value = 1.0
            m2.blend_method = 'OPAQUE'
    print(f"[CROISSANT] len={target_len*1000:.0f}mm loc=({x},{y}) rot={rot_z_deg:.0f}deg")


def _spout_cut(tgt, carton):
    """v98 E6 布尔真切口 (GPT: 附加纸片/唇均判穿插): 盒体最低角真实布尔挖洞,
    奶流起点在洞内 -- 零附加可见几何, 开口=盒体自身拓扑."""
    import mathutils as _mv3
    # 切割体: 小球置于尖角顶点 (挖穿角尖形成圆形开口)
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.0062, location=(tgt[0], tgt[1], tgt[2] + 0.0022),
                                         segments=24, ring_count=12)
    cutter = bpy.context.active_object
    cutter.name = "SpoutCutter"
    cutter.display_type = "WIRE"
    cutter.hide_render = True
    # 对盒体及子网格逐一布尔 (c1 可能有 cap/lip 子件)
    targets = [carton] + [c for c in carton.children if c.type == "MESH"]
    # v98 E7: 盒壳零厚度=布尔只切单层皮无内壁 (诊断: 射线向上 5.2mm 命中盒体=没切穿)
    # 先 Solidify 2mm 纸板厚 -> 布尔切穿双壁 = 真实开口有内壁/厚度 (GPT 三段结构之"纸盒开口")
    for t in targets:
        sol = t.modifiers.new("SpoutSolid", "SOLIDIFY")
        sol.thickness = 0.002
        sol.offset = -1
        sol.use_rim = True
        bpy.context.view_layer.objects.active = t
        t.select_set(True)
        with bpy.context.temp_override(active_object=t, selected_editable_objects=[t], selected_objects=[t]):
            bpy.ops.object.modifier_apply(modifier="SpoutSolid")
    for t in targets:
        bm = t.modifiers.new("SpoutBool", "BOOLEAN")
        bm.operation = "DIFFERENCE"
        bm.object = cutter
        bm.solver = "EXACT"
        bpy.context.view_layer.objects.active = t
        t.select_set(True)
        with bpy.context.temp_override(active_object=t, selected_editable_objects=[t], selected_objects=[t]):
            try:
                bpy.ops.object.modifier_apply(modifier="SpoutBool")
            except RuntimeError as _e:
                print("[SPOUT] bool skip", t.name, _e)
                t.modifiers.remove(bm)
    bpy.data.objects.remove(cutter)
    print(f"[SPOUT] boolean cut at ({tgt[0]:.3f},{tgt[1]:.3f},{tgt[2]:.3f})")


def _splash_crown(pos):
    """v98 E19 杯口入射溅起冠: 液柱撞击杯口液面的可见响应 (薄冠+微溅滴).
    3°俯角下杯内液面不可见, 杯口是唯一可见交互区."""
    import mathutils as _sc
    _P = _sc.Vector(pos)
    _mm = bpy.data.materials.get("MilkHero")
    # 薄冠: 入射点周围隆起环 (torus, 薄 0.6mm, 半径 4mm)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.004, minor_radius=0.0006,
                                     location=(_P.x, _P.y, _P.z + 0.0008))
    _cr = bpy.context.active_object
    _cr.name = "SplashCrown"
    _cr.data.materials.append(_mm)
    for _p in _cr.data.polygons:
        _p.use_smooth = True
    # 微溅滴: 3 颗小球冠外 (溅起液滴, 半径 0.5-0.8mm)
    import random as _sr
    _sr.seed(3)
    for _i in range(3):
        _ang = _sr.uniform(0, 6.28)
        _rd = _sr.uniform(0.005, 0.007)
        _hz = _sr.uniform(0.001, 0.003)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=_sr.uniform(0.0005, 0.0008),
            location=(_P.x + _rd * math.cos(_ang), _P.y + _rd * math.sin(_ang), _P.z + _hz),
            segments=12, ring_count=8)
        _dr = bpy.context.active_object
        _dr.name = f"SplashDrop{_i}"
        _dr.data.materials.append(_mm)
    print(f"[SPLASH-CROWN] at ({_P.x:.3f},{_P.y:.3f},{_P.z:.3f})")


def build_pour(spout, milk_top, glass_c=(-0.083, 0.008)):
    """v98 E8 液流起始段重构 (GPT 处方: 起点入内腔+椭圆液膜->圆截面平滑过渡, 消"白色布带"平直截面).
    自定义截面 mesh: 每环椭圆半轴 a(u),b(u) smoothstep 过渡到圆 r(u); 起点延伸进盒内腔 8mm."""
    import mathutils as _pv
    S = _pv.Vector(spout)
    M = _pv.Vector((glass_c[0], glass_c[1], milk_top - 0.005))
    import random as _pr
    _pr.seed(7)
    p1, p2 = _pr.uniform(0, 6.28), _pr.uniform(0, 6.28)
    # 起点延伸进内腔 (沿 S->M 反方向 8mm): 起始截面藏盒内不可见
    _dir = (M - S).normalized()
    S_in = S - _dir * 0.006   # v98 E14 起点=开口内 6mm (射线诊断: >=10mm 穿盒壁=正面白斑; 5mm 干净); 锥尖藏开口内
    n_ring, n_seg = 64, 24   # v98 E15 环密度 40->64: 锥尖过渡平滑消阶梯折点 (GPT 允许的一次局部微调)
    # 中心线 (含低频 S 弯+高频微抖, 与 v97b 一致)
    centers = []
    for k in range(n_ring):
        u = k / (n_ring - 1)
        _env = min(1.0, u / 0.12)
        _bend = (0.0035 if os.environ.get("POUR_1L", "0") == "1" else 0.0018) * math.sin(math.pi * u + p1) * u   # v100 1L S弯加强
        px = S_in.x + (M.x - S_in.x) * u + _bend + _env * (0.0006 * math.sin(2.6 * math.pi * u + p1) + 0.0004 * math.sin(5.3 * math.pi * u + p2))
        py = S_in.y + (M.y - S_in.y) * u + _env * 0.0005 * math.sin(3.1 * math.pi * u + p2)
        pz = S_in.z + (M.z - S_in.z) * u
        centers.append(_pv.Vector((px, py, pz)))
    # 截面半轴: 出口椭圆液膜 (a0=1.7r 宽, b0=0.45r 薄) -> 圆 r, smoothstep t=u/0.22
    r_base = 0.0045 if os.environ.get("POUR_1L", "0") == "1" else 0.0032   # v100 1L大流量液柱加粗
    verts, faces = [], []
    for k in range(n_ring):
        u = k / (n_ring - 1)
        t = min(1.0, u / 0.22)   # v98 E9 回退 v98m 基准 (GPT: v98p REJECT, v98m KEEP)
        sm = t * t * (3 - 2 * t)   # smoothstep: 切线连续
        _grav = 1.0 - (0.62 if os.environ.get("POUR_1L", "0") == "1" else 0.50) * (u ** 1.2)   # v100 1L重力锥度加强
        # v98 E14 锥尖过渡前 4% (~2mm 全在开口内): 开口处全径, 可见段纯柱面
        _tip = min(1.0, u / 0.04)
        _tip_sm = _tip * _tip * (3 - 2 * _tip)
        # v98 E32 轮廓微变化 (GPT"圆管感"): 沿程低频厚薄 + 周向微起伏, 幅度 2-3% (不引入球帽/接头)
        _contour = 1.0 + (0.09 if os.environ.get("POUR_1L", "0") == "1" else 0.05) * math.sin(3.3 * math.pi * u + p1) + (0.045 if os.environ.get("POUR_1L", "0") == "1" else 0.025) * math.sin(6.1 * math.pi * u + p2)   # v100 1L轮廓变化x1.8
        # 末端铺展: 最后 8% 半径微扩 1.12x (液柱入液面铺展过渡, 非硬插)
        _spread = 1.0 + 0.12 * max(0.0, (u - 0.92) / 0.08) ** 1.5
        r = r_base * _grav * _tip_sm * _contour * _spread
        # v98 E10 去椭圆液膜: ObjectID 取证=液膜宽 1.7r(11mm)>布尔开口, 边缘伸出盒外=楔形突起+布带感同源
        # 起点即圆截面 (r3.2mm<开口), 起点已入内腔 8mm 无外露端盖
        a = r
        b = r
        # 局部标架: 切向 T, 法向 N (水平侧向), B=T×N
        T = (centers[min(k + 1, n_ring - 1)] - centers[max(k - 1, 0)]).normalized()
        N = _pv.Vector((0, 0, 1)).cross(T)
        if N.length < 1e-6:
            N = _pv.Vector((1, 0, 0))
        N.normalize()
        B = T.cross(N).normalized()
        for j in range(n_seg):
            th = 2 * math.pi * j / n_seg
            p = centers[k] + N * (a * math.cos(th)) + B * (b * math.sin(th))
            verts.append(tuple(p))
    for k in range(n_ring - 1):
        for j in range(n_seg):
            j2 = (j + 1) % n_seg
            faces.append((k * n_seg + j, k * n_seg + j2, (k + 1) * n_seg + j2, (k + 1) * n_seg + j))
    # 底盖 (入液面端)
    faces.append(tuple(range((n_ring - 1) * n_seg, n_ring * n_seg)))
    me = bpy.data.meshes.new("MilkStream")
    me.from_pydata(verts, [], faces)
    me.update()
    me.validate()
    ob = bpy.data.objects.new("MilkStream", me)
    bpy.context.scene.collection.objects.link(ob)
    for _p3 in me.polygons:
        _p3.use_smooth = True
    mm = bpy.data.materials.new("MilkHero")
    mm.use_nodes = True
    mp = mm.node_tree.nodes.get("Principled BSDF")
    mp.inputs["Base Color"].default_value = (0.80, 0.78, 0.74, 1)   # v98 E28 液柱与液面统一降白 (液柱 MilkHero 过白=死白主因)
    mp.inputs["Roughness"].default_value = 0.30
    if "Subsurface Weight" in mp.inputs:
        mp.inputs["Subsurface Weight"].default_value = 0.10
        mp.inputs["Subsurface Radius"].default_value = (0.02, 0.015, 0.01)
    if "Coat Weight" in mp.inputs:
        mp.inputs["Coat Weight"].default_value = 0.05
    ob.data.materials.append(mm)
    print(f"[POUR] E8 film-to-round stream: spout_in=({S_in.x:.3f},{S_in.y:.3f},{S_in.z:.3f}) -> milk_top={milk_top:.3f}")
    return ob, verts, faces   # v98 E9: 供单一液体网格合并



def splash_impact(center, milk_top):
    """v96 液面冲击形态 (v94 引擎化丢失 v93 细节的补回): 注入点冠+涟漪环2道+柱根凸.
    z 对齐引擎液面实测 _mt, 环随半径外扩微降 (冲击波传播)."""
    import mathutils as _sv
    C = _sv.Vector((center[0], center[1], milk_top))
    specs = [  # (major, minor, dz)  z=烘焙实测液面 (运行时对齐)
        (0.009, 0.0008, 0.0010),    # v98 冲击冠变薄 1.5→0.8mm (厚冠=膏状), 半径 7.5→9mm 更贴液面
        (0.014, 0.0005, 0.0005),    # 涟漪 1
        (0.020, 0.0003, 0.0001),    # 涟漪 2
    ]
    for i, (maj, mnr, dz) in enumerate(specs):
        bpy.ops.mesh.primitive_torus_add(major_radius=maj, minor_radius=mnr, location=(C.x, C.y, milk_top + dz))
        t = bpy.context.active_object
        t.name = f"ImpactRing{i}"
        t.data.materials.append(bpy.data.materials["MilkHero"])
    bpy.ops.mesh.primitive_uv_sphere_add(radius=0.0042, location=(C.x, C.y, milk_top + 0.0008), segments=24, ring_count=12)
    _root = bpy.context.active_object
    _root.name = "ImpactBulge"
    _root.data.materials.append(bpy.data.materials["MilkHero"])
    print(f"[SPLASH] rings at ({C.x:.3f},{C.y:.3f}) z={milk_top:.4f}")


def build_pour_sim(spout, milk_top, glass_mo, milk_mk, carton_c1):
    """v94 Mantaflow 真流体 (用户"没用引擎, 流体不对"): 入流盒嘴+重力域+玻璃/奶面碰撞.
    四大坑位按台账: fluid_type 改名/FLOW+LIQUID+inflow/域显式 LIQUID/bake_all 需激活+temp_override.
    域紧包液柱+杯口: 90x80x130mm, res 140 → 网格 ~0.64mm 对 3mm 柱 8-9 cell."""
    import os as _os
    S = spout
    # 域 (先创建 = 第一个求值)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-0.09, 0.01, 0.09))
    dom = bpy.context.active_object
    dom.scale = (0.09, 0.08, 0.13)
    dom.name = "PourDomain"
    fmod = dom.modifiers.new("Fluid", "FLUID")
    fmod.fluid_type = "DOMAIN"
    dset = fmod.domain_settings
    dset.domain_type = "LIQUID"   # 坑3: 默认 GAS = 静默无液面
    dset.resolution_max = 100   # v94e 降 res: 140 下 surface 重建碎片化 (23B 空 mesh 为主), 100 是 minrepro 成功档
    dset.mesh_smoothen_pos = 3
    dset.mesh_smoothen_neg = 4
    dset.mesh_particle_radius = 3.2   # v94i 再加厚: 速度高处细柱低于重建阈值(面缺失)
    dset.gravity = (0.0, 0.0, -9.81)
    dset.cache_type = "MODULAR"   # v94: MODULAR 全窗口 bake_data/bake_mesh 是 5.2.2 headless 唯一能写满帧序列的路径 (bake_all 只写首帧假成功)
    cache_dir = os.path.join(BASE_DIR, "output", "fluid_cache_pour")
    _os.makedirs(cache_dir, exist_ok=True)
    dset.use_mesh = True
    dset.cache_frame_start = 1
    dset.cache_frame_end = 50
    dset.cache_directory = cache_dir
    # 入流: 盒嘴小球, 初速向下偏杯心
    import mathutils as _pv3
    # v94h inflow=竖直圆柱 (Mantaflow 流量=对象体积/cell 填充, 球 38mm³/帧 vs 柱段需求 400mm³ = 滴落不成柱)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.0045, depth=0.02,
                                        location=(S[0], S[1], S[2] - 0.013), vertices=24)
    infl = bpy.context.active_object   # 圆柱 z 95..115, 顶缘距尖角 3mm
    infl.name = "PourInflow"
    infl.hide_render = True
    imod = infl.modifiers.new("Fluid", "FLUID")
    imod.fluid_type = "FLOW"   # 坑1: 无 OBSTACLE/INFLOW 枚举
    iset = imod.flow_settings
    iset.flow_type = "LIQUID"
    iset.use_inflow = True
    iset.use_initial_velocity = True
    iset.velocity_coord = (-0.04, 0.0, -0.45)   # v94i 折中速度
    # 隧穿防线: 高速流每帧位移 33mm >> cell 0.64mm → 需 CFL 自适应子步
    try:
        dset.use_adaptive_timesteps = True
        dset.timesteps_max = 16
    except Exception as _e:
        print("[POUR-SIM] adaptive timesteps n/a:", _e)
    # 碰撞体: 玻璃壁 / 奶面(柱顶) / 盒体
    effs = []
    for ob in (glass_mo, milk_mk):
        em = ob.modifiers.new("FluidEff", "FLUID")
        em.fluid_type = "EFFECTOR"
        em.effector_settings.effector_type = "COLLISION"
        effs.append(ob)
    if os.environ.get("POUR_CARTON_EFF", "1") == "1":
        for _c in [carton_c1] + list(carton_c1.children):
            if _c.type == "MESH":
                em = _c.modifiers.new("FluidEff", "FLUID")
                em.fluid_type = "EFFECTOR"
                em.effector_settings.effector_type = "COLLISION"
                effs.append(_c)
    # 烘焙 (有缓存跳过)
    _need = fmod.domain_settings.cache_frame_end - fmod.domain_settings.cache_frame_start + 1
    _have = len([f for f in os.listdir(os.path.join(cache_dir, "data")) if f.endswith(".vdb")]) if os.path.isdir(os.path.join(cache_dir, "data")) else 0
    if _have < _need or os.environ.get("FORCE_BAKE", "0") == "1":
        bpy.context.view_layer.objects.active = dom
        with bpy.context.temp_override(active_object=dom, object=dom):
            bpy.ops.fluid.bake_data()
            bpy.ops.fluid.bake_mesh()
        print("[POUR-SIM] baked %d frames res=%d (data=%d)" % (_need, fmod.domain_settings.resolution_max, len(os.listdir(os.path.join(cache_dir, "data")))))
    else:
        print("[POUR-SIM] cache hit (%d/%d frames), skip bake" % (_have, _need))
    _sc = bpy.context.scene
    _sc.frame_set(int(os.environ.get("FLUID_FRAME", "35")))
    # v94d 静态化液体网格: to_mesh 固化为普通对象渲染 (绕开域 cube 被渲的管线怪癖)
    bpy.context.view_layer.update()
    _dg = bpy.context.evaluated_depsgraph_get()
    _de = dom.evaluated_get(_dg)
    _me = _de.to_mesh()
    if os.environ.get("DIAG_FRAMES", "0") == "1":
        # 逐帧轨迹诊断: 液体动没动
        for _f in (3, 6, 10, 18, 30, 45):
            _sc.frame_set(_f)
            bpy.context.view_layer.update()
            _dg2 = bpy.context.evaluated_depsgraph_get()
            _de2 = dom.evaluated_get(_dg2)
            _me2 = _de2.to_mesh()
            if len(_me2.vertices):
                _zs = [(_de2.matrix_world @ v.co).z for v in _me2.vertices]
                print("[POUR-TRACE] frame %d verts=%d z %.1f..%.1fmm" % (_f, len(_me2.vertices), min(_zs)*1000, max(_zs)*1000))
            else:
                print("[POUR-TRACE] frame %d EMPTY" % _f)
            _de2.to_mesh_clear()
        _de.to_mesh_clear()
        return
    if len(_me.vertices) > 30:   # >30: 排除域 cube 8 顶点 fallback
        mm = bpy.data.materials.get("MilkHero")
        if mm is None:
            mm = bpy.data.materials.new("MilkHero")
            mm.use_nodes = True
        new_me = bpy.data.meshes.new("PourLiquidMesh")
        _ws = [tuple(_de.matrix_world @ v.co) for v in _me.vertices]
        # v98 E17 圆柱裁剪 (杯内壁半径内): 原 x 盒 -120..-48 远宽于杯径 31mm, 保留杯外溢流碎片
        # = GPT"左侧溢边平台/右侧浪头"根因。只留杯内液体, 切杯外溢流
        # v101 等价性纪律: 主路径完全沿用原硬编码常量, 对所有原本可跑配置逐位零影响
        # (曾改为实测 r_in-0.0008=0.0233 与 milk_top 相对z带, 但250ml实测 milk_top 有
        #  0.054/0.057/0.070 三种 → 只对0.057等价, 属回归; 故还原, 实测值只用于空集兜底)
        _GCX, _GCY = -0.083, 0.008   # 杯中心
        _GR = 0.0235   # 杯内壁半径 ~23.5mm (留 1mm 余量防切壁)
        _BZ = (0.040, 0.055)
        def _in_cup(p):
            return (p[0] - _GCX) ** 2 + (p[1] - _GCY) ** 2 <= _GR ** 2 and _BZ[0] <= p[2] <= _BZ[1]
        _keep = [all(_in_cup(_ws[i]) for i in poly.vertices) for poly in _me.polygons]
        _vi = sorted({i for poly in _me.polygons if _keep[poly.index] for i in poly.vertices})
        if not _vi:
            # v101 锚点修正: 原z带锚静态奶液圆柱顶 milk_top, 但仿真液面可高于它
            # (实测 FLUTE_SOFT=0.85: 流体z max=0.0604 > milk_top=0.0584 → z带内顶点=0)
            # 改锚"径向达标顶点自身的z最大值" → 该顶点必在带内, 保证非空
            _mr = float(glass_mo.get("cup_r_in", 0.0243)) - 0.0008
            _mcx = float(glass_mo.get("cup_cx", _GCX))
            _mcy = float(glass_mo.get("cup_cy", _GCY))
            _rz = [p[2] for p in _ws if math.hypot(p[0] - _mcx, p[1] - _mcy) <= _mr]
            if _rz:
                _zt = max(_rz)
                _GCX, _GCY, _GR = _mcx, _mcy, _mr
                _BZ = (_zt - 0.015, _zt + 1e-6)
                print("[POUR-SIM] z带改锚仿真液面: %.4f → (%.4f,%.4f)" % (milk_top, _BZ[0], _BZ[1]))
                _keep = [all(_in_cup(_ws[i]) for i in poly.vertices) for poly in _me.polygons]
                _vi = sorted({i for poly in _me.polygons if _keep[poly.index] for i in poly.vertices})
        if not _vi:
            # v101 诊断: 报流体网格真实世界bbox与径向分布, 不再猜裁剪口径
            _bx = [p[0] for p in _ws]; _by = [p[1] for p in _ws]; _bz2 = [p[2] for p in _ws]
            _rad = [math.hypot(p[0] - _GCX, p[1] - _GCY) for p in _ws]
            _rad.sort()
            raise RuntimeError(
                "[POUR-SIM] 液体裁剪后为空 | 裁剪: 杯心(%.4f,%.4f) R=%.4f z带(%.4f,%.4f) | "
                "流体bbox x(%.4f,%.4f) y(%.4f,%.4f) z(%.4f,%.4f) verts=%d | "
                "径向 min=%.4f p50=%.4f max=%.4f | z带内顶点=%d 径向达标=%d"
                % (_GCX, _GCY, _GR, _BZ[0], _BZ[1],
                   min(_bx), max(_bx), min(_by), max(_by), min(_bz2), max(_bz2), len(_ws),
                   _rad[0], _rad[len(_rad) // 2], _rad[-1],
                   sum(1 for p in _ws if _BZ[0] <= p[2] <= _BZ[1]),
                   sum(1 for r in _rad if r <= _GR)))
        _remap = {vi: k for k, vi in enumerate(_vi)}
        _kept_ws = [list(_ws[i]) for i in _vi]   # list 可改 (E18 液面位移)
        # v98 E18 液面弯月面+入射冲击 (GPT 主任务: 液面形态真实性+入射响应)
        # 顶面顶点 (z>0.048) 径向位移: 入射点中心凹陷 (冲击坑) + 边缘弯月爬升 (润湿)
        _IMPACT = (-0.080, 0.009)   # 液柱入射点 (杯心略偏)
        _surf_z = 0.050
        for _p in _kept_ws:
            if _p[2] > 0.048:
                _rr = math.hypot(_p[0] - _GCX, _p[1] - _GCY)
                _ri = math.hypot(_p[0] - _IMPACT[0], _p[1] - _IMPACT[1])
                _t_n = min(1.0, _rr / _GR)
                # v98 E29 弯月面爬升 2mm + 冲击坑 3mm/10mm + 涟漪环 (液面已可见, 加大交互)
                _meniscus = 0.002 * (_t_n ** 3)
                _crater = -0.003 * max(0.0, 1.0 - (_ri / 0.010) ** 2)
                _ripple = 0.0008 * math.sin(_ri / 0.004 * math.pi) * max(0.0, 1.0 - _ri / 0.020)
                _p[2] = _p[2] + _meniscus + _crater + _ripple
        new_me.from_pydata(_kept_ws, [],
                           [tuple(_remap[i] for i in poly.vertices) for poly in _me.polygons if _keep[poly.index]])
        new_me.update()
        new_me.validate()
        lo = bpy.data.objects.new("PourLiquid", new_me)
        bpy.context.scene.collection.objects.link(lo)
        lo.data.materials.append(mm)
        for _p2 in new_me.polygons:
            _p2.use_smooth = True   # v98 E1: from_pydata 默认 flat=引擎液体块状膏感根因
        if os.environ.get("POUR_SOLO") == "1":
            scn.render.engine = "BLENDER_WORKBENCH"
            scn.display.shading.color_type = "RANDOM"
            for _o2 in list(bpy.data.objects):
                if _o2.name not in ("PourLiquid", "Cam", "Sun"):
                    _o2.hide_render = True
            for _o2 in bpy.data.objects:
                if _o2.name == "PourLiquid":
                    _o2.hide_render = False
        bpy.context.view_layer.update()
        _lzs = [(lo.matrix_world @ v.co).z for v in lo.data.vertices]
        _lxs = [(lo.matrix_world @ v.co).x for v in lo.data.vertices]
        _milk_top_sim = max(_lzs)
        print("[POUR-BAKE-FIX] liquid frozen: verts=%d world x %.3f..%.3f z %.3f..%.3f mat=%s hide=%s loc=%s" % (
            len(_me.vertices), min(_lxs), max(_lxs), min(_lzs), max(_lzs),
            lo.data.materials[0].name if lo.data.materials else None,
            lo.hide_render, tuple(round(v, 3) for v in lo.location)))
    else:
        print("[POUR-BAKE-FIX] liquid EMPTY")
        _milk_top_sim = 0.070   # fallback: 上次烘焙实测
    _de.to_mesh_clear()
    dom.hide_render = True   # 域 cube 不再渲染 (液体已静态化)
    infl.hide_render = True
    # 流体材质 (技能牛奶配方)
    mm = bpy.data.materials.get("MilkHero") or bpy.data.materials.new("MilkHero")
    mm.use_nodes = True
    mp = mm.node_tree.nodes.get("Principled BSDF")
    mp.inputs["Base Color"].default_value = (0.80, 0.78, 0.74, 1)   # v98 E28 统一 Milk 材质参数
    mp.inputs["Roughness"].default_value = 0.30
    if "Subsurface Weight" in mp.inputs:
        mp.inputs["Subsurface Weight"].default_value = 0.10
        mp.inputs["Subsurface Radius"].default_value = (0.02, 0.015, 0.01)
    if "Coat Weight" in mp.inputs:
        mp.inputs["Coat Weight"].default_value = 0.05
    dom.data.materials.clear()
    dom.data.materials.append(mm)
    print(f"[POUR-SIM] domain=(-0.09,0.01,0.09) res=140 frame={_sc.frame_current}")
    return _milk_top_sim



def main():
    args = parse_args()
    os.makedirs(OUT_DIR, exist_ok=True)
    scene = fresh(args)
    scene.cycles.max_bounces = 12
    scene.cycles.transmission_bounces = 12
    scene.cycles.transparent_max_bounces = 12
    WHITE = os.environ.get("WHITE", "0") == "1"   # JD 白底主图: 白世界+平光+单盒正视+无DOF+渲染前清场
    if WHITE:
        bpy.data.worlds["Env"].node_tree.nodes.get("Background").inputs["Strength"].default_value = 0.05   # world 压暗: 背景=独立 emission 白板 (摄影棚背景纸法), 产品光比由灯全权
        scene.cycles.sample_clamp_indirect = 3.0   # v95d: 白环境 GI 渗色 clamp (大白反弹洗亮方牌深绿假说)
        scene.cycles.max_bounces = 4
        scene.cycles.diffuse_bounces = 2
        bpy.data.worlds["Env"].node_tree.nodes.get("Background").inputs["Color"].default_value = (1.0, 1.0, 1.0, 1)
    else:
        wood_table()
    # 产品位: 经典孪生盒体 x2 错落 (替换参照玻璃瓶商品)
    import mathutils as _mu
    if os.environ.get("POUR_1L", "0") == "1":
        import brick_carton_1l as _y1l
        # v107 规格驱动纸盒构建期参数: 纸盒在 lifestyle_scene.apply **之前**构建,
        # 故必须在此从规格取值注入(env 只作传输, specs/lifestyle_1l.json 才是单一来源)。
        # LIFESTYLE 未设时整段不执行 → 冻结KV分支逐位零影响。
        if os.environ.get("LIFESTYLE", "0") == "1":
            import json as _cjson
            _sp = os.environ.get("LS_SPEC", os.path.join(BASE_DIR, "specs", "lifestyle_1l.json"))
            with open(_sp) as _cf:
                _cb = _cjson.load(_cf).get("carton_build", {})
            if "paper_deform" in _cb:
                os.environ["PAPER_DEFORM"] = str(_cb["paper_deform"])
            if _cb.get("paper_normal"):
                os.environ["PAPER_NRM"] = "1"
                os.environ["PAPER_NRM_S"] = str(_cb.get("paper_normal_strength", 0.45))
            # v118 确定性噪声: mathutils.noise 跨进程不可复现(5.2无noise.seed),
            # 实测两进程 carton sha 不同→focus漂6mm→整图 mean0.83/max244;
            # DET=1 两进程 sha 全等(7af3b36b1e7cbf31) 已验。默认0=冻结KV走原noise。
            if _cb.get("paper_noise_det"):
                os.environ["PAPER_NOISE_DET"] = "1"
            # v122 光泽(哑光纸): 0.18/0.25 是暗调KV的缎光配方, 高调场景被评审连续判"塑料感"
            for _k, _e in (("paper_rough", "PAPER_ROUGH"),
                           ("paper_coat", "PAPER_COAT"),
                           ("paper_coat_r", "PAPER_COAT_R")):
                if _k in _cb:
                    os.environ[_e] = str(_cb[_k])
            print("[CARTON-SPEC] deform=%s nrm=%s/%s det=%s rough=%s coat=%s/%s" % (
                os.environ.get("PAPER_DEFORM", "1.0"), os.environ.get("PAPER_NRM", "0"),
                os.environ.get("PAPER_NRM_S", "0.45"), os.environ.get("PAPER_NOISE_DET", "0"),
                os.environ.get("PAPER_ROUGH", "0.18"), os.environ.get("PAPER_COAT", "0.25"),
                os.environ.get("PAPER_COAT_R", "0.10")))
        c1, _cap1l = _y1l.build_carton_1l(loc=(0.0, 0.02, 0.0), cap_open=True)   # v100 1L gable-top 砖盒+旋盖
        c1.rotation_euler = (0, 0, math.radians(-16))
    else:
        c1 = heroes.carton_master("demo_organic", scale=1.0, loc=(0.0, 0.02, 0.0))
        c1.rotation_euler = (0, 0, math.radians(-16))
    for _c in (c1,):
        for _o in ([_c] + list(_c.children)):
            if _o.type == "MESH":
                _bv = _o.modifiers.new("EdgeBevel", "BEVEL")
                _bv.width = 0.0015
                _bv.segments = 2
                _bv.limit_method = "ANGLE"
    # 牛奶杯 (内容物提示) 前左: 2.5D 相机投影 (用户批准技法)
    # v91 用户裁定: 不要麦穗 (程序化+billboard 双路径移除), 场景=单奶盒+玻璃杯牛奶+可颂
    lighting()
    # v40: 背景 kick 洗光 (消地平线暗带; 锥掠产品顶上方)
    import mathutils as _mw
    wk = bpy.data.lights.new("BgWash", "SPOT")
    wk.energy = 4.0
    wk.spot_size = math.radians(55)
    wk.spot_blend = 0.9
    wk.shadow_soft_size = 0.15
    wk.color = (1.0, 0.88, 0.74)
    wo = bpy.data.objects.new("BgWash", wk)
    scene.collection.objects.link(wo)
    wo.location = (0, -0.2, 0.9)
    wd = _mw.Vector((0, 1.2, 0.1)) - _mw.Vector(wo.location)
    wo.rotation_euler = wd.to_track_quat("-Z", "Y").to_euler()
    if ABL == "key":
        bpy.data.lights["Key"].energy = 0.0
    import mathutils as _mb
    bounce = bpy.data.lights.new("Bounce", "AREA")
    bounce.energy = float(os.environ.get("BOUNCE_W", "5" if (os.environ.get("POUR", "0") == "1" and os.environ.get("POUR_LOW", "0") != "1") else "9"))
    bounce.size = float(os.environ.get("BOUNCE_SIZE", "1.2"))   # v70 真变量: 麦穗投影源角尺寸
    bounce.color = (1.0, 0.95, 0.88)
    bo = bpy.data.objects.new("Bounce", bounce)
    scene.collection.objects.link(bo)
    bo.location = (-0.30, -0.55, 0.22)
    bd = _mb.Vector((-0.010, -0.014, 0.10)) - _mb.Vector(bo.location)
    bo.rotation_euler = bd.to_track_quat("-Z", "Y").to_euler()
    bo.visible_shadow = True
    if ABL == "bounce":
        bpy.data.lights["Bounce"].energy = 0.0
    if BOV == "aim":
        # v36: 仅改朝向 (瞄准主盒正面中心)
        bt = _mb.Vector((-0.010, -0.014, 0.10)) - _mb.Vector(bo.location)
        bo.rotation_euler = bt.to_track_quat("-Z", "Y").to_euler()
    if BOV in ("pos", "pos14", "pos9"):
        # v37: 仅改位置 (正面半球), 朝向重瞄同点
        bo.location = (-0.30, -0.55, 0.22)
        bt = _mb.Vector((-0.010, -0.014, 0.10)) - _mb.Vector(bo.location)
        bo.rotation_euler = bt.to_track_quat("-Z", "Y").to_euler()
    if BOV == "pos14":
        bpy.data.lights["Bounce"].energy = 14
    if BOV == "pos9":
        bpy.data.lights["Bounce"].energy = 9
    if os.environ.get("STUDIO_RIG", "0") == "1":   # v101 单变量: 只换布光, 未设=冻结分支零影响
        studio_rig(scene)
    # 相机: 商业静物低机位 3/4 视 (85mm f/4)
    cam = bpy.data.cameras.new("Cam")
    cam.lens = 78.0
    cam.dof.use_dof = os.environ.get("WHITE", "0") != "1"
    cam.dof.aperture_fstop = float(os.environ.get("FSTOP", "8.0"))   # v69 景深单变量
    cam.dof.focus_distance = (0.95 if os.environ.get("POUR_LOW", "0") == "1" else 1.21) if os.environ.get("POUR", "0") == "1" else 0.62
    co = bpy.data.objects.new("Cam", cam)
    scene.collection.objects.link(co)
    _POUR_LOW = os.environ.get("POUR_LOW", "0") == "1"   # v98 E35 双分支: 低机位 hero KV (GPT 艺术指导)
    co.location = ((0.02, -0.95, 0.17) if _POUR_LOW else (0.02, -0.95, 0.78)) if os.environ.get("POUR", "0") == "1" else (0.02, -0.60, 0.17)
    tgt = _mu.Vector((0.01, 0.03, 0.12)) if os.environ.get("POUR", "0") == "1" else _mu.Vector((0.01, 0.03, 0.09))
    if os.environ.get("WHITE", "0") == "1":
        co.location = (0.0, -0.45, 0.17)   # 微俯 8°: 底部接触投影入画 (正视看不见地面)
        tgt = _mu.Vector((0.0, 0.02, 0.095))
    # v99 多角度拍摄: POUR_AZ/POUR_EL 球面机位 (灯光/材质/构图冻结, 只变机位; az=0→正面-Y, 正→+X 右侧)
    _paz, _pel = os.environ.get("POUR_AZ", ""), os.environ.get("POUR_EL", "")
    if os.environ.get("POUR", "0") == "1" and (_paz or _pel):
        _azr = math.radians(float(_paz or "0"))
        _elr = math.radians(float(_pel or "3"))
        _R = 0.95   # 与低机位同半径 → focus_distance 不变
        co.location = (tgt.x + _R * math.cos(_elr) * math.sin(_azr),
                       tgt.y - _R * math.cos(_elr) * math.cos(_azr),
                       tgt.z + _R * math.sin(_elr))
        cam.dof.focus_distance = _R   # 陷阱: 焦距必须=实际机位-主体距离
    co.rotation_euler = (tgt - _mu.Vector(co.location)).to_track_quat("-Z", "Y").to_euler()
    scene.camera = co

    # v30 单变量: 暖调渐变背景板 (进相机+玻璃透射两族; 上部深黑保负空间)
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0, 2.4, 1.0))
    bd2 = bpy.context.active_object
    bd2.rotation_euler = (math.radians(90), 0, 0)
    bd2.scale = (4.0, 2.5, 1.0)
    bm = bpy.data.materials.new("WarmBackdrop")
    bm.use_nodes = True
    bnt = bm.node_tree
    bnt.nodes.clear()
    bo2 = bnt.nodes.new("ShaderNodeOutputMaterial")
    bdf = bnt.nodes.new("ShaderNodeBsdfDiffuse")
    bdf.inputs["Roughness"].default_value = 0.9
    geo = bnt.nodes.new("ShaderNodeNewGeometry")
    sepz = bnt.nodes.new("ShaderNodeSeparateXYZ")
    bnt.links.new(geo.outputs["Position"], sepz.inputs[0])
    mrz = bnt.nodes.new("ShaderNodeMapRange")
    mrz.inputs["From Min"].default_value = 0.0
    mrz.inputs["From Max"].default_value = 1.4
    bnt.links.new(sepz.outputs["Z"], mrz.inputs["Value"])
    bramp = bnt.nodes.new("ShaderNodeValToRGB")
    bramp.color_ramp.elements[0].position = 0.0
    bramp.color_ramp.elements[0].color = (0.234, 0.135, 0.072, 1)
    bramp.color_ramp.elements[1].position = 1.0
    bramp.color_ramp.elements[1].color = (0.0216, 0.0144, 0.0108, 1)
    e_mid = bramp.color_ramp.elements.new(0.35)
    e_mid.color = (0.162, 0.09, 0.050, 1)
    bnt.links.new(mrz.outputs[0], bramp.inputs["Fac"])
    bnt.links.new(bramp.outputs[0], bdf.inputs["Color"])
    bnt.links.new(bdf.outputs[0], bo2.inputs["Surface"])
    bd2.data.materials.append(bm)
    # v45: cyclorama 圆角 R1.2 (切桌面@y1.2/z0, 切墙@y2.4/z1.2)
    import bmesh
    me = bpy.data.meshes.new("CycFillet")
    bmg = bmesh.new()
    N = 32
    rowsv = []
    for i in range(N + 1):
        t = math.radians(90) * i / N
        y = 1.2 + 1.2 * math.sin(t)
        z = 1.2 - 1.2 * math.cos(t)
        rowsv.append((bmg.verts.new((-2.0, y, z)), bmg.verts.new((2.0, y, z))))
    for i in range(N):
        bmg.faces.new((rowsv[i][0], rowsv[i][1], rowsv[i + 1][1], rowsv[i + 1][0]))
    bmg.to_mesh(me)
    bmg.free()
    fo2 = bpy.data.objects.new("CycFillet", me)
    scene.collection.objects.link(fo2)
    for pg in me.polygons:
        pg.use_smooth = True
    fo2.data.materials.append(bm)
    # v32 单变量: 双侧 scrim (掠射反射/侧向透射环境结构)
    import mathutils as _ms
    for _sx in (-0.55, 0.55):
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(_sx, -0.05, 0.12))
        sc = bpy.context.active_object
        sc.scale = (0.4, 0.25, 1.0)
        sd = _ms.Vector((-0.075, -0.04, 0.06)) - _ms.Vector(sc.location)
        sc.rotation_euler = sd.to_track_quat("Z", "Y").to_euler()
        smat = bpy.data.materials.new(f"Scrim{_sx > 0}")
        smat.use_nodes = True
        snt = smat.node_tree
        snt.nodes.clear()
        so = snt.nodes.new("ShaderNodeOutputMaterial")
        se = snt.nodes.new("ShaderNodeEmission")
        se.inputs["Strength"].default_value = 1.2
        se.inputs["Color"].default_value = (1.0, 0.85, 0.70, 1)
        snt.links.new(se.outputs[0], so.inputs["Surface"])
        sc.data.materials.append(smat)
        sc.visible_camera = False
        sc.visible_shadow = False
        _sp = os.environ.get("REPRO_SCRIM_PATH", "")
        if _sp == "glossy":
            sc.visible_glossy = False
        elif _sp == "trans":
            sc.visible_transmission = False
        elif _sp == "diffuse":
            sc.visible_diffuse = False
    # v64: rim 镜族窄白卡 (杯口后上方, 仅 rim 区环境供光)
    import mathutils as _mr4
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(-0.10, 0.90, 0.20))   # v65 镜族解: 仰角~6°
    rc = bpy.context.active_object
    rc.scale = (0.15, 0.03, 1.0)
    rd4 = _mr4.Vector((-0.075, -0.04, 0.105)) - _mr4.Vector(rc.location)
    rc.rotation_euler = rd4.to_track_quat("Z", "Y").to_euler()
    rm4 = bpy.data.materials.new("RimCard")
    rm4.use_nodes = True
    rnt = rm4.node_tree
    rnt.nodes.clear()
    ro4 = rnt.nodes.new("ShaderNodeOutputMaterial")
    re4 = rnt.nodes.new("ShaderNodeEmission")
    re4.inputs["Strength"].default_value = 2.0
    re4.inputs["Color"].default_value = (1.0, 0.97, 0.92, 1)
    rnt.links.new(re4.outputs[0], ro4.inputs["Surface"])
    rc.data.materials.append(rm4)
    rc.visible_camera = False
    rc.visible_shadow = False
    if os.environ.get("GLASS", "model") == "proc":
        real_glass((-0.075, -0.040))
    # v26 单变量: 白反射卡 (仅反射可见, 消杯口黑边/包壳感)
    import mathutils as _mc
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=(-0.06, -0.30, 0.10))
    card = bpy.context.active_object
    card.scale = (0.10, 0.14, 1.0)   # v75 P2处方: 反射卡窄化→窗式细高光
    cd = _mc.Vector((-0.083, 0.008, 0.035)) - _mc.Vector(card.location)   # v89 瞄矮杯中心
    card.rotation_euler = cd.to_track_quat("Z", "Y").to_euler()
    cm = bpy.data.materials.new("ReflCard")
    cm.use_nodes = True
    cnt = cm.node_tree
    cnt.nodes.clear()
    co2 = cnt.nodes.new("ShaderNodeOutputMaterial")
    ce = cnt.nodes.new("ShaderNodeEmission")
    ce.inputs["Strength"].default_value = 3.0
    ce.inputs["Color"].default_value = (1.0, 0.98, 0.95, 1)
    cnt.links.new(ce.outputs[0], co2.inputs["Surface"])
    card.data.materials.append(cm)
    card.visible_camera = False
    card.visible_shadow = False
    if ABL == "card":
        bpy.data.materials["ReflCard"].node_tree.nodes["Emission"].inputs["Strength"].default_value = 0.0
    # v84: 开源真模玻璃杯 (glTF 导入必须在所有自研几何之后 = ops 污染坑)
    if os.environ.get("GLASS", "model") == "model":
        POUR = os.environ.get("POUR", "0") == "1"
        _glass_mo, _milk_mk = import_glass_model((-0.083, 0.008), fill=0.80 if POUR else 0.72)   # v98 E21 fill 0.70->0.80: 35°俯角液面近杯口易见 (50mm 太低被杯壁挡)
        import_plate((0.114, 0.02))   # v92: 白瓷盘托可颂, 足迹距盒角 5mm, 右缘 12.4°<13°
        import_croissant((0.114, 0.02), 50.0, 0.120, 0.006)   # v92: 120mm 上盘井底, 对角 50°
        if POUR:
            # v98 E35 包装纸面形变 (GPT"顶面太干净边缘太直缺受力感"): 毫米级低频法向位移
            # 真实利乐包受折叠/运输/倾倒应力: 面微鼓/棱微弯, 幅度 0.4mm (盒高~136mm 的 0.3%)
            import mathutils as _pw
            _pn = _pw.noise
            for _po in [c1]:
                if _po.type != 'MESH':
                    continue
                _pme = _po.data
                # v98 E37 面细分 (n-gon 无内部顶点=位移无效, 同液面陷阱): subdivide 生成内部顶点
                import bmesh as _bmc
                _bmc_obj = _bmc.new()
                _bmc_obj.from_mesh(_pme)
                if os.environ.get("POUR_1L", "0") != "1":   # v101: 1L模块已cuts=8, 再cuts=10=716k顶点(实测)
                    _bmc.ops.subdivide_edges(_bmc_obj, edges=_bmc_obj.edges[:], cuts=10, use_grid_fill=True)
                _bmc_obj.to_mesh(_pme)
                _bmc_obj.free()
                # v101 O(N²)修复: 包围盒/世界矩阵是循环不变量, 提到循环外
                # (原每顶点重算全体顶点 = 716k² = 5.1e11 次 matrix@vector → 5小时不出图)
                _mw_c1 = _po.matrix_world
                _bb_z = [(_mw_c1 @ _vv.co).z for _vv in _pme.vertices]
                _zmin, _zmax = min(_bb_z), max(_bb_z)
                for _pv2 in _pme.vertices:
                    _wp = _mw_c1 @ _pv2.co
                    _n1 = _pn.noise_vector(_wp * 18.0)   # 低频 (~55mm 波长)
                    _n2 = _pn.noise_vector(_wp * 45.0 + _pw.Vector((7.3, 2.1, 4.4)))   # 中频 (~22mm)
                    _n3 = _pn.noise_vector(_wp * 120.0 + _pw.Vector((3.1, 8.7, 1.9)))   # v98 E39 高频折痕 (~8mm 波长)
                    _disp = 0.003 * _n1[0] + 0.0015 * _n2[1] + 0.0008 * _n3[2]   # 低频鼓+中频+高频折痕 (高光扭曲可见)
                    # v98 E41 顶部 15% 折边受力感 (GPT 刀1): 顶边局部起伏+封口折线微扰, 轻微不完美非做旧
                    _top_t = (_wp.z - _zmin) / max(1e-6, _zmax - _zmin)
                    if _top_t > 0.85:
                        _nt = _pn.noise_vector(_wp * 80.0 + _pw.Vector((5.5, 1.3, 9.2)))
                        _disp += 0.0012 * _nt[0] * ((_top_t - 0.85) / 0.15)   # 顶部折边 1.2mm 局部起伏
                    _pv2.co += _pv2.normal * _disp
                _pme.update()
            # v98 E36 棱边微圆角 (GPT"边缘太直锐利"): bevel 0.6mm 软化棱线
            _bev = c1.modifiers.new("CartonSoft", "BEVEL")
            _bev.width = 0.0006
            _bev.segments = 2
            _bev.limit_method = 'ANGLE'
            _bev.angle_limit = math.radians(40)
            # v93 倒奶: 盒 Y 轴 -35° 悬空, 最低角(盒嘴)对杯口上方 48mm; 奶柱+液面漩涡
            if os.environ.get("POUR_1L", "0") == "1":
                c1.rotation_euler = (0, math.radians(-140), math.radians(-16))   # v100 1L砖盒: 盖口法线(0,-0.68,0.73)转至朝下, 倾角-140°
            else:
                c1.rotation_euler = (0, math.radians(-115), math.radians(-16))   # v93e gable尖嘴
            bpy.context.view_layer.update()
            _verts = []
            for _o in [c1] + list(c1.children):
                if _o.type == 'MESH':
                    _verts += [(_o.matrix_world @ v.co) for v in _o.data.vertices]
            _low = min(_verts, key=lambda p: p.z)
            _tgt = (-0.078, 0.010, 0.118)
            import mathutils as _mp
            if os.environ.get("POUR_1L", "0") == "1":
                _spout_world = c1.matrix_world @ _y1l.spout_pos()   # 旋盖口世界坐标
                c1.location = c1.location + (_mp.Vector(_tgt) - _spout_world)
            else:
                c1.location = c1.location + (_mp.Vector(_tgt) - _low)
            bpy.context.view_layer.update()
            # 量奶面: 奶材质网格最高 z
            _mt = 0.0
            for _o in bpy.data.objects:
                if _o.type == 'MESH' and _o.data.materials and any(m and m.name == 'Milk' for m in _o.data.materials):
                    _mz = max((_o.matrix_world @ v.co).z for v in _o.data.vertices)
                    _mt = max(_mt, _mz)
            _mt_sim = build_pour_sim(_tgt, _mt, _glass_mo, _milk_mk, c1)   # v98 E9: 先烘引擎液体, 返回实测液面 z
            # v98 E9b 删 splash_impact torus 环: GPT"独立几何组件叠加"=杯口白环伪影; 单 mesh 引擎液体已含液面
            # v98 E4: 出奶嘴开口结构 -- 最低点布尔真切口 (E7 Solidify 壁厚)
            if os.environ.get("POUR_1L", "0") != "1":
                _spout_cut(_tgt, c1)   # gable布尔开口; 1L旋盖已开无需切
            import mathutils as _spv
            _s_in = _spv.Vector(_tgt) + _spv.Vector((0.0, 0.0, 0.0018))   # v98 E6b 起点=布尔洞口中心
            _stream_data = build_pour(tuple(_s_in), _mt_sim)   # v98 E9: 液柱几何
            # v98 E19 杯口入射溅起冠 (GPT"液柱入射响应", 3°俯角唯一可见交互区)
            _splash_crown((-0.080, 0.009, 0.070))
            # v98 E9 单一液体网格: 引擎堆积+液柱合并 (消独立 mesh 重叠环形接缝)
            _s_ob, _s_v, _s_f = _stream_data
            _liq = bpy.data.objects.get("PourLiquid")
            if _liq is not None:
                _lv = [tuple(_liq.matrix_world @ v.co) for v in _liq.data.vertices]
                _lf = [tuple(p.vertices) for p in _liq.data.polygons]
                _off = len(_lv)
                _merged = bpy.data.meshes.new("PourLiquidSingle")
                _merged.from_pydata(_lv + list(_s_v), [], _lf + [tuple(i + _off for i in f) for f in _s_f])
                _merged.update(); _merged.validate()
                for _pm in _merged.polygons:
                    _pm.use_smooth = True
                _liq.data = _merged
                bpy.data.objects.remove(_s_ob)
                print(f"[POUR-E9] single liquid mesh: {len(_lv)}+{len(_s_v)} verts")
    # 治理: 冻结配置 manifest
    import json as _json
    _man = {
        "bounce": {"loc": [round(v, 3) for v in bo.location], "energy": bpy.data.lights["Bounce"].energy},
        "key": {"energy": bpy.data.lights["Key"].energy},
        "wash": {"energy": bpy.data.lights["BgWash"].energy, "blend": round(bpy.data.lights["BgWash"].spot_blend, 2)},
        "card_emission": bpy.data.materials["ReflCard"].node_tree.nodes["Emission"].inputs["Strength"].default_value,
        "scrims_emission": 1.2,
        "cyc_radius": 1.2,
        "camera": {"loc": [round(v, 3) for v in co.location], "lens": cam.lens, "fstop": cam.dof.aperture_fstop},
        "exposure": scene.view_settings.exposure,
        "samples": scene.cycles.samples,
    }
    with open(os.path.join(OUT_DIR, "manifest.json"), "w") as _f:
        _json.dump(_man, _f, indent=1)
    if os.environ.get("WHITE", "0") == "1":
        _keep = {c1} | set(c1.children)   # 白底主图=纯产品: 杯/奶也清
        _keep |= {getattr(_o, "parent", None) for _o in _keep} - {None}
        _nk = 0
        for _o in list(bpy.context.scene.objects):
            if _o in _keep or (_o.parent and _o.parent in _keep):
                continue
            if _o.type in ("MESH", "LIGHT"):
                _o.hide_render = True; _nk += 1
        print(f"[WHITE] hidden {_nk} objects")
        # 接触投影: 盒底柔和椭圆暗片 (白底主图防"浮空", JD 允许浅投影)
        _NO_SH = os.environ.get("SHADOW", "1") == "0"   # SHADOW=0 才跳过; 默认创建
        import mathutils as _mw4
        if not _NO_SH:
            bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.02, 0.0008))
            _sh = bpy.context.active_object
            _sh.scale = (0.075, 0.115, 1.0)
            _sm = bpy.data.materials.new("ContactShadow")
        _sm.use_nodes = True
        _mp2 = _sm.node_tree.nodes.get("Principled BSDF")
        _mp2.inputs["Base Color"].default_value = (0.74, 0.74, 0.74, 1)   # v95 浅投影 (电商白底规范: 淡)
        _mp2.inputs["Roughness"].default_value = 0.9
        if "Metallic" in _mp2.inputs:
            _mp2.inputs["Metallic"].default_value = 0.0
            _mp2.inputs["Alpha"].default_value = 1.0
        _sh.data.materials.append(_sm)
        _sh.visible_shadow = False
        import mathutils as _mw3
        # 左强右弱: 白盒右缘留浅暗边
        # v95b 降曝光: 白卡 251→~235, 方牌绿回深 (白字对比恢复)
        for _i, (_lx, _ly, _lz, _en) in enumerate([(-0.60, -0.75, 0.35, 18), (0.60, -0.75, 0.35, 11), (0.0, -0.25, 0.80, 8)]):
            _pl = bpy.data.lights.new(f"FlatKey{_i}", "AREA")
            _pl.energy = _en; _pl.size = 0.5; _pl.color = (1.0, 1.0, 1.0)
            _po = bpy.data.objects.new(f"FlatKey{_i}", _pl)
            scene.collection.objects.link(_po)
            _po.location = (_lx, _ly, _lz)
            _pd = _mw3.Vector((0.0, 0.02, 0.105)) - _mw3.Vector(_po.location)
            _po.rotation_euler = _pd.to_track_quat("-Z", "Y").to_euler()
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=(0.0, 0.55, 0.105))
        _bp = bpy.context.active_object
        _bp.rotation_euler = (math.radians(90), 0, 0)
        _bp.scale = (1.6, 1.6, 1.0)
        bpy.context.view_layer.update()
        _bm2 = bpy.data.materials.new("WhiteBGBrd")
        _bm2.use_nodes = True
        _bnt2 = _bm2.node_tree
        _bnt2.nodes.clear()
        _bo2 = _bnt2.nodes.new("ShaderNodeOutputMaterial")
        _bem = _bnt2.nodes.new("ShaderNodeEmission")
        _bem.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1)
        _bem.inputs["Strength"].default_value = 1.05
        _bnt2.links.new(_bem.outputs[0], _bo2.inputs["Surface"])
        _bp.data.materials.append(_bm2)
        _bp.visible_shadow = False
        print("[WHITE-BG] board at", tuple(_bp.location), "dims", tuple(round(v, 2) for v in _bp.dimensions), "render-hide", _bp.hide_render, "in-scene", _bp.name in [o.name for o in scene.objects])
    out = os.path.join(OUT_DIR, f"repro_{args.out}.png")
    scene.render.filepath = out
    scene.render.image_settings.file_format = "PNG"
    vl = scene.view_layers[0]
    if os.environ.get("REPRO_PASSES"):
        vl.use_pass_glossy_direct = True
        vl.use_pass_glossy_indirect = True
        vl.use_pass_transmission_direct = True
        vl.use_pass_transmission_indirect = True
    if os.environ.get("STUDIO_RIG", "0") == "1":   # v101 光链接: 物体已创建, 渲染前生效
        apply_light_linking(scene, c1)
    if os.environ.get("LIFESTYLE", "0") == "1":   # v102 高调生活场景分支 (用户参照驱动)
        import lifestyle_scene
        lifestyle_scene.apply(scene, c1)
        # manifest 在 1637 行已落盘, 但本分支在其后改了相机/曝光/灯具/画幅 →
        # 必须按**实拍参数**补写, 否则溯源链记录的是改造前假值 (LIFESTYLE 未设时不执行=默认零影响)
        _man["camera"] = {"loc": [round(v, 3) for v in co.location], "lens": cam.lens,
                          "fstop": cam.dof.aperture_fstop,
                          "focus_distance": round(cam.dof.focus_distance, 4)}
        _man["exposure"] = scene.view_settings.exposure
        _man["view_transform"] = scene.view_settings.view_transform
        _man["look"] = scene.view_settings.look
        _man["resolution"] = [scene.render.resolution_x, scene.render.resolution_y]
        _man["world_strength"] = bpy.data.worlds["Env"].node_tree.nodes["Background"].inputs["Strength"].default_value
        _man["lifestyle_lights"] = {n: bpy.data.lights[n].energy for n in
                                    ("Key", "Rim", "BgWash", "Bounce", "LS_Window", "LS_Fill", "LS_BgBright")
                                    if n in bpy.data.lights}
        _man["lifestyle"] = True
        with open(os.path.join(OUT_DIR, "manifest.json"), "w") as _f2:
            _json.dump(_man, _f2, indent=1)
    if os.environ.get("OBJ_MASK", "0") == "1":   # v126 几何真值掩膜(默认关=冻结分支零影响)
        import object_mask
        object_mask.dump(scene, os.path.join(OUT_DIR, "objmask_%s.json" % args.out))
    bpy.ops.render.render(write_still=True)
    if os.environ.get("REPRO_PASSES"):
        ngp = bpy.data.node_groups.new("PassDump", "CompositorNodeTree")
        rl2 = ngp.nodes.new("CompositorNodeRLayers")
        fo = ngp.nodes.new("CompositorNodeOutputFile")
        fo.directory = os.path.join(OUT_DIR, "passes")
        fo.file_name = "v32"
        names = {"GlossDir": "gloss_dir", "GlossInd": "gloss_ind", "TransDir": "trans_dir", "TransInd": "trans_ind"}
        for sock in rl2.outputs:
            if sock.name in names:
                fo.file_slots.new(names[sock.name])
                ngp.links.new(sock, fo.inputs[names[sock.name]])
        scene.compositing_node_group = ngp
        bpy.ops.render.render(write_still=True)
    # 图灵维: 胶片颗粒+径向暗角 (确定性 numpy 后步, 5.2 合成器无纹理节点)
    import numpy as _np
    img = bpy.data.images.load(out)
    w, h = img.size
    px = _np.empty(w * h * 4, dtype=_np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(h, w, 4)
    if os.environ.get("WHITE", "0") == "1":
        # 白底电商后期: 近白背景拉纯白; 中央竖带 (产品+投影) 保护区不拉伸
        _lum = rgb[..., :3].mean(axis=2)
        _t0, _t1 = 0.72, 0.82
        _w = _np.clip((_lum - _t0) / (_t1 - _t0), 0, 1)
        _yy, _xx = _np.mgrid[0:h, 0:w].astype(_np.float32)
        _nx, _ny = _xx / w, _yy / h
        _protect = (_np.abs(_nx - 0.5) < 0.16)   # 全高竖带: 产品+底部投影 (0.95 截断曾拉白 y1883+ 投影)
        _w = _np.where(_protect, 0.0, _w)[..., None]
        rgb[..., :3] = rgb[..., :3] * (1 - _w) + 1.0 * _w
        rgb[..., :3] = _np.clip(rgb[..., :3], 0, 1)
        img.pixels.foreach_set(rgb.ravel())
        img.update()
        img.filepath_raw = out
        img.file_format = "PNG"
        img.save()
        print(f"[REPRO] {out}")
        return
    w, h = img.size
    px = _np.empty(w * h * 4, dtype=_np.float32)
    img.pixels.foreach_get(px)
    rgb = px.reshape(h, w, 4)
    rng = _np.random.default_rng(7)
    # v115 GRAIN 未设=0.010 原值(冻结KV分支逐位不变)。外部评审#1缺陷"焦外廉价高斯/数码涂抹"
    # 已数值归因: 候选背景拉普拉斯var 134.61 vs 参照 6.80, 反解噪声σ 2.594 vs 0.583/255;
    # 本行常量0.010线性预测var=130.1≈实测134.6 → 平坦虚化区的高频**几乎全是本后期颗粒**。
    grain = rng.normal(0.0, float(os.environ.get("GRAIN", "0.010")), (h, w, 1)).astype(_np.float32)
    yy, xx = _np.mgrid[0:h, 0:w].astype(_np.float32)
    r = _np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    vig = 1.0 - float(os.environ.get("VIG", "0.30")) * _np.clip((r - 0.62) / 0.55, 0, 1) ** 2   # v102 VIG 未设=0.30 原值
    rgb[..., :3] = _np.clip(rgb[..., :3] * vig[..., None] + grain, 0, 1)
    img.pixels.foreach_set(rgb.ravel())
    img.update()
    img.filepath_raw = out
    img.file_format = "PNG"
    img.save()
    print(f"[REPRO] {out}")


if __name__ == "__main__":
    main()
