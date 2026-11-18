#!/usr/bin/env python3
"""v103 高调生活场景早餐分支 (用户参照驱动: 电商延世 Milk Talk 早餐图).

**规格驱动**: 所有数值(画幅/色彩/机位/灯具/摆位/约束)来自 specs/lifestyle_1l.json,
由 scene_runtime 强制执行几何闸并回写实拍溯源。本模块只保留**程序化材质构建**
(浅色木桌/明亮背景/卡片中性化) —— 这部分是 shader 图, 无法用数值声明表达。

参照实测规格 (assets/reference/lifestyle_highkey_ref.png, 已剔页面装饰):
  画幅 1338x1046 (1.279) / 亮度均值 205.6 / 暗部<40 1.7% / 高光>240 27.8% / R/G 1.031
  分区锐度: 上部背景14.7 | 左侧主体99.4 | 右上中景3.9(饱和28.4) | 右下前景81.4
  → 背景/主体 0.147, 道具/主体 0.039 (浅景深); 光位右上237.8>左上217.2 = 侧逆光偏右上

只在 LIFESTYLE=1 时被 34_commercial_repro.py 调用 (渲染前), 默认路径零影响。
品牌印刷=硬约束: 不碰纸盒 UV/贴图。
"""
import os

import bpy
import mathutils as mu

import scene_runtime as rt

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _aim(obj, target):
    obj.rotation_euler = (mu.Vector(target) - mu.Vector(obj.location)).to_track_quat("-Z", "Y").to_euler()


def _pale_table(scene, spec=None):
    """深复古木桌 → 浅色白洗木桌 (参照桌面 lum~190-215)."""
    tb = next((o for o in scene.objects if o.type == "MESH" and o.data.materials
               and any(m and m.name == "WoodRetro" for m in o.data.materials)), None)
    if tb is None:
        raise rt.SpecError("未找到 WoodRetro 桌面 (LIFESTYLE 需非 WHITE 分支)")
    m = bpy.data.materials.new("LS_PaleWood")
    m.use_nodes = True
    nt = m.node_tree
    b = nt.nodes.get("Principled BSDF")
    tc = nt.nodes.new("ShaderNodeTexCoord")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (26.0, 2.2, 1.0)
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    ns = nt.nodes.new("ShaderNodeTexNoise")
    ns.inputs["Detail"].default_value = 8.0
    ns.inputs["Roughness"].default_value = 0.55
    nt.links.new(mp.outputs[0], ns.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    # v112 桌面反射率走规格单一来源。原 0.72-0.86 线性 = sRGB 221-239(**未计光照已近白**),
    # 是灯具类杠杆全部失效的真因: world/主光/补光/背景洗光/光比共8档都压不住接触区过曝
    # (carton clip 恒 0.20-0.32)。实测底部桌面 232.2 vs 参照 189.9, 中段 216.3 vs 192.6。
    _tb = (spec or {}).get("table", {})
    _lo = _tb.get("albedo_low", [0.72, 0.66, 0.58])
    _hi = _tb.get("albedo_high", [0.86, 0.81, 0.74])
    ramp.color_ramp.elements[0].position = 0.30
    ramp.color_ramp.elements[0].color = tuple(_lo) + (1.0,)
    ramp.color_ramp.elements[1].position = 0.72
    ramp.color_ramp.elements[1].color = tuple(_hi) + (1.0,)
    nt.links.new(ns.outputs["Fac"], ramp.inputs[0])
    nt.links.new(ramp.outputs[0], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = float(_tb.get("roughness", 0.52))
    bp = nt.nodes.new("ShaderNodeBump")
    bp.inputs["Strength"].default_value = 0.06
    nt.links.new(ns.outputs["Fac"], bp.inputs["Height"])
    nt.links.new(bp.outputs[0], b.inputs["Normal"])
    # v141 步骤9: 真实桌面贴图(LS_TABLE_TEX=路径, 默认关). Poly Haven wood_table_worn
    # CC0: diff+nor+rough. 白洗: 降饱和至0.35+提亮混白0.55 → 参照lum 190-215.
    _texdir = os.environ.get("LS_TABLE_TEX", "")
    if _texdir:
        import os as _os
        _root = _texdir  # v141: 目录语义(含三张wood_table_worn jpg)
        _img_diff = bpy.data.images.load(_os.path.join(_root, "wood_table_worn_diff_2k.jpg"), check_existing=True)
        _img_nor = bpy.data.images.load(_os.path.join(_root, "wood_table_worn_nor_gl_2k.jpg"), check_existing=True)
        _img_rgh = bpy.data.images.load(_os.path.join(_root, "wood_table_worn_rough_2k.jpg"), check_existing=True)
        _tex_uv = nt.nodes.new("ShaderNodeTexCoord")
        _map_uv = nt.nodes.new("ShaderNodeMapping")
        _map_uv.inputs["Scale"].default_value = (1.0, 1.0, 1.0)
        # v141.2: Generated坐标(bbox归一0-1) — Object坐标在微local bbox上把整图拉成单色
        nt.links.new(_tex_uv.outputs["Generated"], _map_uv.inputs["Vector"])
        _nd = nt.nodes.new("ShaderNodeTexImage")
        _nd.image = _img_diff
        nt.links.new(_map_uv.outputs[0], _nd.inputs["Vector"])
        _hs = nt.nodes.new("ShaderNodeHueSaturation")
        _hs.inputs["Saturation"].default_value = 0.85   # v142.1: 木纹色再推
        _hs.inputs["Value"].default_value = 1.0
        nt.links.new(_nd.outputs["Color"], _hs.inputs["Color"])
        _mx = nt.nodes.new("ShaderNodeMix")
        _mx.blend_type = 'MIX'   # 5.2: blend_type须先于data_type(否则socket集重置)
        _mx.data_type = 'RGBA'
        _fc = next(_s for _s in _mx.inputs if _s.identifier == 'Factor_Float')
        _fc.default_value = 0.12
        _c2 = next(_s for _s in _mx.inputs if _s.identifier == 'B_Color')
        _c2.default_value = (0.86, 0.84, 0.80, 1.0)
        _c1 = next(_s for _s in _mx.inputs if _s.identifier == 'A_Color')
        nt.links.new(_hs.outputs["Color"], _c1)
        _bc = nt.nodes.new("ShaderNodeBrightContrast")
        _bc.inputs["Brightness"].default_value = 0.04
        _bc.inputs["Contrast"].default_value = 0.55
        _out = next(_s for _s in _mx.outputs if _s.identifier == 'Result_Color')  # outputs[key]按名字查, identifier必须next
        nt.links.new(_out, _bc.inputs["Color"])
        _bcout = next(_s for _s in _bc.outputs if _s.identifier == 'Color')
        nt.links.new(_bcout, b.inputs["Base Color"])
        _nn = nt.nodes.new("ShaderNodeTexImage")
        _nn.image = _img_nor
        _nn.image.colorspace_settings.name = 'Non-Color'
        nt.links.new(_map_uv.outputs[0], _nn.inputs["Vector"])
        _nm = nt.nodes.new("ShaderNodeNormalMap")
        _nm.inputs["Strength"].default_value = 1.2
        nt.links.new(_nn.outputs["Color"], _nm.inputs["Color"])
        nt.links.new(_nm.outputs["Normal"], b.inputs["Normal"])
        _nr = nt.nodes.new("ShaderNodeTexImage")
        _nr.image = _img_rgh
        _nr.image.colorspace_settings.name = 'Non-Color'
        nt.links.new(_map_uv.outputs[0], _nr.inputs["Vector"])
        _mr = nt.nodes.new("ShaderNodeMapRange")
        _mr.inputs['To Min'].default_value = 0.38
        _mr.inputs['To Max'].default_value = 0.62
        nt.links.new(_nr.outputs["Color"], _mr.inputs["Value"])
        nt.links.new(_mr.outputs['Result'], b.inputs["Roughness"])
    tb.data.materials.clear()
    tb.data.materials.append(m)


def _bright_backdrop(scene):
    """暖调暗渐变背景 → 明亮奶油渐变 (参照上部背景 lum231)."""
    bm = bpy.data.materials.get("WarmBackdrop")
    if bm is None:
        raise rt.SpecError("未找到 WarmBackdrop")
    ramp = next((n for n in bm.node_tree.nodes if n.type == "VALTORGB"), None)
    if ramp is None:
        raise rt.SpecError("WarmBackdrop 无 ColorRamp")
    els = ramp.color_ramp.elements
    els[0].position = 0.0
    els[0].color = (0.62, 0.585, 0.545, 1)
    els[len(els) - 1].position = 1.0
    els[len(els) - 1].color = (0.86, 0.835, 0.795, 1)
    for e in list(els)[1:-1]:
        e.color = (0.74, 0.705, 0.665, 1)


def _neutralize_cards(scene, spec=None):
    """暗调KV遗留 emission 卡 → 中性日光色, 强度由规格控制。

    取证: 原实现**只改颜色不改强度** → ReflCard 3.0 / RimCard 2.0 / Scrim 1.2 原样保留;
    这些卡 `visible_camera=False` 但**参与漫射**, 位置 z=0.10-0.20 紧贴桌面,
    不在任何灯具开关作用域内 → 8档灯具标定(world/主光/补光/背景洗光/光比)全败的可能真因。
    症状: 盒下 under 恒比 away **亮**(depth -0.20~-0.30, 符号与阴影相反)=盒前有亮池。
    已排除: 镜面高光(roughness 0.52→0.85 clip 0.09→0.09 几乎不动)。
    """
    _cs = (spec or {}).get("cards", {})
    _scale = float(_cs.get("strength_scale", 1.0))
    n = 0
    for m in bpy.data.materials:
        if not m.use_nodes or m.name not in ("ReflCard", "RimCard", "ScrimTrue", "ScrimFalse"):
            continue
        for nd in m.node_tree.nodes:
            if nd.type == "EMISSION":
                nd.inputs["Color"].default_value = (1.0, 0.99, 0.97, 1)
                _base = _cs.get("base", {}).get(m.name)
                if _base is not None:
                    nd.inputs["Strength"].default_value = float(_base) * _scale
                else:
                    nd.inputs["Strength"].default_value *= _scale
                n += 1
    return n


def _lights(scene, spec):
    ls = spec["lights"]
    # LS_DEMOTE_* 仅标定扫描用(会记入实拍溯源); 不设=规格单一来源
    for name, e in ls["demote"].items():
        li = bpy.data.lights.get(name)
        if li is not None:
            li.energy = float(os.environ.get("LS_DEMOTE_" + name.upper(), str(e)))
    if ls.get("rim_glossy"):
        ro = bpy.data.objects.get("Rim")
        if ro is not None:
            ro.visible_glossy = True   # 高调下需要窗光在玻璃/纸面上的反射
    for d in ls["add"]:
        li = bpy.data.lights.new(d["name"], "AREA")
        li.shape = "RECTANGLE"
        li.size = d["w"]
        li.size_y = d["h"]
        # LS_E_<灯名> 仅标定扫描用; 不设=规格值
        li.energy = float(os.environ.get("LS_E_" + d["name"].upper(), str(d["energy"])))
        if d.get("color"):   # v141.3: 可选灯光色(默认不变)
            li.color = tuple(d["color"])
        ob = bpy.data.objects.new(d["name"], li)
        scene.collection.objects.link(ob)
        ob.location = tuple(d["loc"])
        _aim(ob, d["target"])


def _camera(scene, spec, carton):
    c = spec["camera"]
    cam = scene.camera
    if cam is None:
        raise rt.SpecError("无相机")
    cd = cam.data
    cd.lens = c["lens"]
    cd.dof.use_dof = True
    # LS_FSTOP 仅标定扫描用(会记入实拍溯源); final 不设=规格单一来源
    cd.dof.aperture_fstop = float(os.environ.get("LS_FSTOP", str(c["fstop"])))
    cam.location = tuple(c["loc"])
    _aim(cam, c["target"])
    bpy.context.view_layer.update()
    # 焦点 = 纸盒正面印刷面中心 (品牌必须合焦); 用实测顶点而非猜坐标
    face = next(o for o in spec["objects"] if o["id"] == c["focus_on"])["brand_face"]
    idx = {"x": 0, "y": 1, "z": 2}[face["local_axis"]]
    pts = [carton.matrix_world @ v.co for v in carton.data.vertices if v.co[idx] < face["local_max"]]
    fp = mu.Vector((sum(p.x for p in pts) / len(pts),
                    min(p.y for p in pts),
                    sum(p.z for p in pts) / len(pts)))
    cd.dof.focus_distance = (fp - mu.Vector(cam.location)).length
    f, N, sw = cd.lens / 1000.0, cd.dof.aperture_fstop, 0.036
    print("[LS-CAM] lens=%.0f f/%.1f focus=%.3fm" % (cd.lens, N, cd.dof.focus_distance))
    for label, dy in (("纸盒背面", 0.075), ("中景道具+0.20m", 0.20), ("背景+0.40m", 0.40)):
        coc = (f * f * dy) / (N * (cd.dof.focus_distance + dy) * (cd.dof.focus_distance - f))
        print("[LS-DOF] %-16s CoC=%.3fmm → %.1fpx"
              % (label, coc * 1000, coc / sw * scene.render.resolution_x))


def _post_solve_inject(scene, spec, reg, meas):
    """MUT_POSTSOLVE 注入器 v2 (默认no-op, 生产路径零影响)。

    P0-A 矩阵结论: solve_layout 吸收 spec-xy 级故障 → 间隙门在 spec 面不可击穿。
    本钩子提供 post-solve 注入面: solve 之后 / 测量之前 直接改世界状态,
    然后**强制 rt.measure(reg) 重测** —— 门只吃注入后的新鲜世界状态,
    绝不复用 solve 的 stale meas(否则即"测器测错对象"事故重演)。

    语法: MUT_POSTSOLVE="op:obj:args[|op2:obj2:args2]"
      translate:oat_bowl:dx,dy,dz   世界系位移
      lift:oat_bowl:dz              抬升z(悬浮故障)
      scale:toast:s                 均匀缩放
    """
    raw = os.environ.get("MUT_POSTSOLVE", "").strip()
    if not raw:
        return meas
    for part in raw.split("|"):
        seg = [x.strip() for x in part.strip().split(":")]
        if len(seg) != 3 or seg[0] not in ("translate", "lift", "scale") or seg[1] not in reg:
            raise SystemExit("[MUT][POST-SOLVE] 语法/对象错: %r" % part)
        op, name, args = seg
        obj = reg[name][0]
        if op == "translate":
            dx, dy, dz = (float(x) for x in args.split(","))
            obj.location.x += dx
            obj.location.y += dy
            obj.location.z += dz
        elif op == "lift":
            obj.location.z += float(args)
        elif op == "scale":
            s = float(args)
            obj.scale = tuple(v * s for v in obj.scale)
        print("[MUT][POST-SOLVE] %s %s %s" % (op, name, args))
    # 改 location 后 matrix_world 是 stale 的(后台模式不自动刷新) —
    # 必须显式 view_layer.update() 否则 measure 读旧矩阵 = 注入静默无效
    bpy.context.view_layer.update()
    return rt.measure(reg)   # 重测: 注入后的世界状态


def apply(scene, carton):
    """LIFESTYLE=1 主入口: 读规格 → 环境/材质/布光/机位 → 摆位 → 几何闸 → 溯源."""
    spec_path = os.environ.get("LS_SPEC", os.path.join(BASE_DIR, "specs", "lifestyle_1l.json"))
    spec = rt.load(spec_path)
    # 参照溯源: 规格声明的参照图必须与磁盘一致 (防换了参照却沿用旧门)
    ref = spec["reference"]
    import hashlib
    with open(os.path.join(BASE_DIR, ref["path"]), "rb") as fh:
        got = hashlib.md5(fh.read()).hexdigest()
    if got != ref["md5"]:
        raise rt.SpecError("参照图 md5 不符: 规格 %s vs 磁盘 %s" % (ref["md5"], got))

    vs = scene.view_settings
    col = spec["color"]
    try:
        vs.view_transform = col["view_transform"]
    except TypeError:
        vs.view_transform = "Standard"
    try:
        vs.look = col["look"]
    except TypeError:
        pass
    # 曝光: 规格单一来源; LS_EXPO 仅用于标定扫描(会记入实拍溯源, 不影响默认路径)
    vs.exposure = float(os.environ.get("LS_EXPO", str(col["exposure"])))
    fr = spec["frame"]
    # LS_RES 仅草稿降采样用 (final 不设=规格单一来源); 否则 --res 640 会被规格1920覆盖
    _res = int(os.environ.get("LS_RES", str(fr["res"])))
    scene.render.resolution_x = _res
    scene.render.resolution_y = int(round(_res / fr["aspect"]))
    vs.gamma = 1.0
    # 后期暗角/颗粒: **规格作缺省, 外部显式 env 优先**(与本仓 LS_* 标定开关同语义)。
    # v126c 自曝: 原为**无条件赋值**, 把命令行 GRAIN=0.010 改回规格0.0023 →
    # 颗粒对照两次实为同配置(两图 mean abs diff 0.001774/max5 = 跨进程噪声),
    # 得出的"高光std比1.00x"是**假结论**, 已撤回。标定开关必须能被外部覆盖。
    os.environ["VIG"] = os.environ.get("VIG", str(col["vignette"]))
    # v115 颗粒: 原0.010线性 → 背景拉普拉斯var134.61(参照6.80), 反解σ2.594 vs 参照0.583
    # → 平坦虚化区高频几乎全是本颗粒 = 评审#1"廉价高斯/数码涂抹"。规格取0.0023。
    os.environ["GRAIN"] = os.environ.get("GRAIN", str(col.get("grain", 0.010)))
    bg = bpy.data.worlds["Env"].node_tree.nodes.get("Background")
    bg.inputs[0].default_value = tuple(spec["world"]["color"]) + (1.0,)
    # LS_WORLD 仅标定扫描用(会记入实拍溯源); 不设=规格单一来源
    bg.inputs[1].default_value = float(os.environ.get("LS_WORLD", str(spec["world"]["strength"])))
    # v140 商业棚拍调研方案(§14/COMMERCIAL_RESEARCH): LS_HDRI=<hdr路径> 时世界环境
    # 换 Poly Haven HDRI(默认关, 冻结KV路径零影响)。选型 Studio Small 08(GPT R3裁决
    # 首选基线: 大柔箱八角箱中性环绕, 白包装/陶瓷/食品反射来源)。釉面/玻璃空反射的
    # 机理修复: Cycles反射真实但旧环境只有平色灯=没东西可映。
    _hdri = os.environ.get("LS_HDRI", "")
    if _hdri and os.path.exists(_hdri):
        _wnt = bpy.data.worlds["Env"].node_tree
        _env = _wnt.nodes.new("ShaderNodeTexEnvironment")
        _env.image = bpy.data.images.load(_hdri, check_existing=True)
        _map = _wnt.nodes.new("ShaderNodeMapping")
        _texco = _wnt.nodes.new("ShaderNodeTexCoord")
        _wnt.links.new(_texco.outputs["Generated"], _map.inputs["Vector"])
        _wnt.links.new(_map.outputs["Vector"], _env.inputs["Vector"])
        _wnt.links.new(_env.outputs["Color"], bg.inputs[0])
        print("[LS-HDRI] 已接入:", os.path.basename(_hdri),
              "强度=", bg.inputs[1].default_value)
    _rd = spec.get("render", {})
    scene.cycles.max_bounces = int(_rd.get("max_bounces", 12))
    scene.cycles.diffuse_bounces = int(_rd.get("diffuse_bounces", 4))
    # 台账389行: 高照度把品牌深绿方牌推进高肩→白字失对比, 解含 clamp 3。
    # 但 clamp_indirect 同时作用于**玻璃透射/折射间接路径** → 高调背景(线性亮度远超3)
    # 穿过玻璃碗的亮光会被削掉, 疑为"碗读作黑环"真因(填充率/阴影射线/壁厚/法线四项已实测排除)。
    scene.cycles.sample_clamp_indirect = float(_rd.get("clamp_indirect", 3.0))

    _pale_table(scene, spec)
    _bright_backdrop(scene)
    nc = _neutralize_cards(scene, spec)
    _lights(scene, spec)
    reg = rt.apply_layout(scene, spec)
    _camera(scene, spec, reg[spec["camera"]["focus_on"]][0])
    # 摆位由**约束求解**得出(规格给意图, 求解器满足穿模/入画/景深分层), 不手摆坐标:
    # 手填 footprint_r=0.060 而吐司双片实测102.5mm → 手算"间隙19mm"是假数字, 闸实测-23.3mm穿模
    # P1-B先导重复种子: LS_SEED 缺省7=历史行为不变(外部env优先语义)
    meas = rt.solve_layout(scene, spec, reg, seed=int(os.environ.get("LS_SEED", "7")))
    meas = _post_solve_inject(scene, spec, reg, meas)
    gate = rt.geometry_gates(scene, spec, reg, meas)
    face = next(o for o in spec["objects"] if o.get("brand_face"))["brand_face"]
    brand = rt.brand_box(scene, reg[spec["camera"]["focus_on"]][0], face)
    rt.regions_box(scene, spec, reg)   # 主体/远近道具真值框 → 门禁不再用分数窗口猜
    out_dir = os.path.dirname(scene.render.filepath)
    rt.write_provenance(scene, spec, out_dir, gate, brand)
    print("[LS] spec=%s sha=%s vt=%s expo=%.2f cards=%d"
          % (os.path.basename(spec_path), spec["_sha"], vs.view_transform, vs.exposure, nc))