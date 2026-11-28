#!/usr/bin/env python3
"""R1 规范整改: 单 SKU 真正 OpenUSD 化 (docs/TWIN_ASSET_SPEC.md §7/§8, 审计 R1)。

产出 output/usd/<sku>/ 层栈:
  geometry.usdc   网格+UV (无材质, Blender 导出)
  materials.usda  UsdPreviewSurface 材质层 (贴图引用+色彩空间)
  Product.usda    资产接口层: defaultPrim / kind=component / variantSets(colorway) /
                  SimReady 语义与物理元数据 (sem:*, phys:*)
并做独立读取验证 (pxr): defaultPrim/kind/variant 切换后材质贴图路径确实变化。

用法 (Blender 内):
  blender -b -P 13_usd_asset.py -- --sku demo_classic

**下一步 (官方 SimReady 合规包)**: 本脚本产出的是**三文件 reference 组合** (Product.usda +
geometry.usdc + materials.usda) —— 官方 NP.005 要求资产目录里**只有一个** USD 主文件 ✓。
合规包由后继脚本接力产出, **整条链一条命令** ✓:
  `python pipelines/shelf_sdg/90_simready_package_pipeline.py -- --sku demo_classic`
  (自研闸门 -> 生成 -> 缩略图 -> 单文件合规包+官方验收 -> 消费端检查 -> 发布 -> 文档闸门 ✓)
其中: 87 号 (bpy 环境) 用**同源**几何渲染 256x256 缩略图 ✓; 86 号 (只装 pxr 的环境) 导出单文件 +
补 variantSet + 11 字段 sidecar + 贴图改 anchored -> 官方 validate/package 验收 ✓;
89 号 (`pipelines/ecommerce/89_asset_self_gate.py`) 是本 validate() 的**独立入口** ✓。
"""
import os
import sys

# bpy / mathutils 只在"生成"阶段需要 -> 延迟导入, 这样 validate() 可以在**只装了 pxr 的
# 环境**(如官方 SimReady 工具环境)里单独跑, 而生成仍在 Blender 环境里跑 (双环境架构)。
BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

COLORWAYS = {
    "kraft_lowcarbon": {"albedo": "demo_classic_albedo.png", "cap": (0.055, 0.30, 0.155)},
    "white_laminated": {"albedo": "demo_organic_albedo.png", "cap": (0.93, 0.93, 0.92)},
}


def write_materials(path, sku):
    blocks = []
    for cw, cfg in COLORWAYS.items():
        blocks.append(f'''
def Material "M_pack_{cw}"
{{
    token outputs:surface.connect = </Materials/M_pack_{cw}/BSDF.outputs:surface>
    def Shader "BSDF"
    {{
        uniform token info:id = "UsdPreviewSurface"
        color3f inputs:diffuseColor.connect = </Materials/M_pack_{cw}/tex_diffuse.outputs:rgb>
        float inputs:roughness.connect = </Materials/M_pack_{cw}/tex_orm.outputs:g>
        float inputs:metallic.connect = </Materials/M_pack_{cw}/tex_orm.outputs:b>
        token outputs:surface
    }}
    def Shader "tex_diffuse"
    {{
        uniform token info:id = "UsdUVTexture"
        token inputs:sourceColorSpace = "sRGB"
        asset inputs:file = @../../../assets/textures/{cfg["albedo"]}@
        float3 outputs:rgb
    }}
    def Shader "tex_orm"
    {{
        uniform token info:id = "UsdUVTexture"
        token inputs:sourceColorSpace = "raw"
        asset inputs:file = @../../../assets/textures/{sku}_orm.png@
        float outputs:g
        float outputs:b
    }}
}}
def Material "M_cap_{cw}"
{{
    token outputs:surface.connect = </Materials/M_cap_{cw}/BSDF.outputs:surface>
    def Shader "BSDF"
    {{
        uniform token info:id = "UsdPreviewSurface"
        color3f inputs:diffuseColor = ({cfg["cap"][0]}, {cfg["cap"][1]}, {cfg["cap"][2]})
        float inputs:roughness = 0.68
        token outputs:surface
    }}
}}''')
    header = '#usda 1.0\n(\n    metersPerUnit = 1\n    defaultPrim = "Materials"\n)\n\ndef Scope "Materials"\n{\n'
    inner = "\n".join(blocks)
    inner = "\n".join(("    " + l) if l.strip() else l for l in inner.split("\n"))
    open(path, "w").write(header + inner + "\n}\n")


def write_product(path, sku, profile, dims_mm="(48, 38, 113)", half_mm="(24, 19, 57)",
                  mass_g="212.9"):
    variants = []
    for cw, cfg in COLORWAYS.items():
        variants.append(
            '        "%s" {\n'
            '            asset sem:approvedAlbedo = @../../../assets/textures/%s@\n'
            '            color3f sem:capColor = (%s, %s, %s)\n'
            '            rel material:binding:pack = </Product/M_pack_%s>\n'
            '            rel material:binding:cap = </Product/M_cap_%s>\n'
            '        }' % (cw, cfg["albedo"], cfg["cap"][0], cfg["cap"][1], cfg["cap"][2], cw, cw))
    body = f'''#usda 1.0
(
    defaultPrim = "Product"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "Product" (
    kind = "component"
    prepend references = [@./geometry.usdc@, @./materials.usda@]
    variantSets = "colorway"
)
{{
    custom string sem:brand = "{profile.get('title', sku).split('纯')[0] or 'DEMO'}"
    custom string sem:skuId = "{sku}"
    custom string sem:barcode = "{profile.get('barcode', '-')}"
    custom string sem:productCategory = "beverage/carton/aseptic-brick"
    # 物理元数据: 字段名**对齐本仓规范** docs/TWIN_ASSET_SPEC.md §8 ✓
    #   phys:mass (g) / phys:collisionProxy (盒体包围盒, mm) / phys:dimensions (mm) ✓
    #   (之前写的是 phys:dimensionsMM / phys:collisionProxyHalfExtentsMM, 与规范不一致 ✗ ->
    #    2026-11-28 改名对齐 ✓; 没有别的消费者, 改名无连带影响 ✓)
    custom double phys:mass = {mass_g}  # g, 网格体积 x 水密度 (内容物质量, 未计包装 ✓)
    custom double3 phys:dimensions = {dims_mm}  # 实测自构建网格世界包围盒 (GPT R2: 与几何单源)
    custom double3 phys:collisionProxy = {dims_mm}  # 盒体包围盒 (mm) ✓
    custom double3 phys:collisionProxyHalfExtentsMM = {half_mm}  # 半长 (旧名保留, 便于对拍 ✓)
    custom string render:pbrWorkflow = "metallicRoughness"
    custom string render:textureSet = "2K-webp-publish / 2K-png-source"
    # 默认态的材质绑定 (不是只在 variant 里写) -> 任何消费者**不选 variant** 也能拿到有效绑定 ✓
    # (variant 里的绑定会覆盖它 ✓)
    rel material:binding:pack = </Product/M_pack_kraft_lowcarbon>
    rel material:binding:cap = </Product/M_cap_kraft_lowcarbon>
    variantSet "colorway" = {{
{chr(10).join(variants)}
    }}
}}
'''
    open(path, "w").write(body)


def validate(usd_dir):
    """独立读取验证 (pxr)。

    2026-11-27 加强: 不再只查"关系有目标字符串", 而是查**目标 prim 真的存在**且
    **shader 连接真的解析** —— 原来的弱断言放过了"materials.usda 被 reference 进来后
    连接路径落在引用作用域之外 -> 连接被 USD 忽略 -> 组合后的资产其实没有材质绑定"
    这个静默故障 (官方 SimReady 验证器把它抓了出来 ✓)。
    """
    from pxr import Usd, UsdGeom
    stage = Usd.Stage.Open(os.path.join(usd_dir, "Product.usda"))
    root = stage.GetDefaultPrim()
    assert root and root.GetName() == "Product", "defaultPrim missing"
    assert root.GetKind() == "component", "kind missing"
    vs = root.GetVariantSets()
    names = vs.GetNames()
    assert "colorway" in names, "variantSet missing"

    def _check_binding(label):
        rel = root.GetRelationship("material:binding:pack")
        targets = list(rel.GetTargets())
        assert targets, f"material binding empty ({label})"
        for t in targets:
            prim = stage.GetPrimAtPath(t)
            assert prim and prim.IsValid(), f"material binding target 不存在 ({label}): {t}"
            conns = prim.GetAttribute("outputs:surface").GetConnections()
            assert conns, f"材质 outputs:surface 没有解析出连接 ({label}): {t}"
            bsdf = prim.GetChild("BSDF")
            assert bsdf and bsdf.IsValid(), f"材质缺 BSDF ({label}): {t}"
            dconn = bsdf.GetAttribute("inputs:diffuseColor").GetConnections()
            assert dconn, f"BSDF.inputs:diffuseColor 没有解析出连接 ({label}): {t}"

    _check_binding("默认态(未选 variant)")
    seen = {}
    for cw in COLORWAYS:
        vs.SetSelection("colorway", cw)
        attr = root.GetAttribute("sem:approvedAlbedo")
        seen[cw] = str(attr.Get())
        _check_binding(f"variant {cw}")
    assert len(set(seen.values())) == len(COLORWAYS), "variant switch has no effect"
    _up = UsdGeom.GetStageUpAxis(stage)
    assert _up == "Z", f"upAxis 声明是 {_up}, 应为 Z (几何本身就是 Z 高的 ✓)"
    assert abs(UsdGeom.GetStageMetersPerUnit(stage) - 1.0) < 1e-9

    # 2026-11-28 新增: **声明的 up 轴必须和几何真的朝向一致** ✓
    # 旧版只断言"元数据写着 Y"(✓ 断言通过), 但几何其实是 Z 高的 (Blender Z-up ->
    # GLB -> USD 的数据本身就是 Z 高 ✓) -> 根层声明 Y = **把资产侧躺 90 度** ✗
    # 官方验证器点名的 UN.006 ("Stage has upAxis of 'Y', not 'Z'") 就是这条 ✓
    # -> 自己闸门必须查"最长轴 == 声明的 up 轴" ✓ (只查元数据 = 查不出来 ✓)
    _bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    _range = None
    for _prim in stage.Traverse():
        if _prim.GetTypeName() != "Mesh":
            continue
        _b = _bbox.ComputeWorldBound(_prim).ComputeAlignedRange()
        _range = _b if _range is None else _range.UnionWith(_b)
    assert _range is not None, "资产里没有网格, 无法核对朝向"
    _ext = [_range.GetMax()[i] - _range.GetMin()[i] for i in range(3)]
    _tallest = max(range(3), key=lambda i: _ext[i])
    assert _tallest == 2, (
        f"几何最长轴是 {'XYZ'[_tallest]} (extents={['%.4f' % e for e in _ext]}), "
        f"但 upAxis 声明的是 Z -> 声明与几何不一致 (消费端会把资产放倒)")
    return seen


def main():
    import bpy
    from mathutils import Vector

    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sku = argv[argv.index("--sku") + 1] if "--sku" in argv else "demo_classic"
    import importlib.util as ilu
    spec = ilu.spec_from_file_location("comp", os.path.join(BASE, "pipelines/ecommerce/01_comfy_usd_compositor.py"))
    comp = ilu.module_from_spec(spec)
    spec.loader.exec_module(comp)

    out = os.path.join(BASE, "output", "usd", sku)
    os.makedirs(out, exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True)
    pack, cap, lip = comp.build_carton_twin(sku)
    bpy.context.view_layer.update()
    # 记下对象名: 下面 read_factory_settings() 会**作废**这些 bpy 对象引用
    # (StructRNA of type Object has been removed ✓) -> 名字要在这里先取出来 ✓
    obj_names = {o.name: ("cap" if o.name.startswith(("Cap", "Lip")) else "pack")
                 for o in (pack, cap, lip) if o is not None}
    # 物理元数据单源实测: 世界包围盒 (与几何同源, 防 GPT R2 指出的 20% 声明偏差)
    #   **取整资产的并集包围盒** ✓ (pack + cap + lip ✓): 之前只量了 pack ✓ ->
    #   交付 sidecar 的 asset_extents (整资产 ✓) 与 phys:dimensions (只 pack ✓) **对不上** ✗
    #   -> 同一个交付物里两个尺寸字段差 4.5 mm ✗ -> 现在统一成并集 ✓
    _bb = []
    for _o in (pack, cap, lip):
        if _o is None:
            continue
        _bb += [_o.matrix_world @ Vector(c) for c in _o.bound_box]
    _d = [max(p[i] for p in _bb) - min(p[i] for p in _bb) for i in range(3)]
    dims_mm = "(" + ", ".join(f"{v*1000:.1f}" for v in _d) + ")"
    half_mm = "(" + ", ".join(f"{v*500:.1f}" for v in _d) + ")"
    # 质量: 用**网格体积**算 (Blender 里量 ✓) -> 内容物质量 (水基 1 g/cm^3 ✓)
    #   2026-11-28: 本仓规范 (docs/TWIN_ASSET_SPEC.md §8) 要求 `phys:mass` (g) ✓
    #   之前资产里**没有**这个字段 ✗ -> 现在补上 ✓ (86 号再据此写官方的 physics:mass ✓)
    import bmesh
    _bm = bmesh.new()
    _bm.from_mesh(pack.data)
    _vol_m3 = abs(_bm.calc_volume())
    _bm.free()
    mass_g = _vol_m3 * 1e6  # m^3 -> cm^3 -> g (水基 ✓)
    mass_g_str = f"{mass_g:.1f}"
    print(f"  [MASS] 网格体积 {_vol_m3*1e6:.1f} cm^3 -> phys:mass {mass_g_str} g (水基估算, 未计包装 ✓)")
    bpy.ops.object.select_all(action="DESELECT")
    for o in (pack, cap, lip):
        if o:
            o.select_set(True)
    # **网格数据改名** -> USD 里的 Mesh prim 名才有意义 ✓
    # (Blender 默认叫 "Cube"/"Cylinder" ✓ -> glTF 中转后原样变成 USD prim 名 ✓
    #  -> 下游消费者在 USD 里看到的是 "Cube"/"Cylinder_001" ✗ (交付质量缺陷 ✓))
    for o, mname in ((pack, "M_pack"), (cap, "M_cap"), (lip, "M_lip")):
        if o:
            o.data.name = mname
    bpy.ops.export_scene.gltf(filepath=os.path.join(out, "_tmp.glb"), export_format="GLB",
                              use_selection=True, export_materials="NONE")
    # 经 glb 中转得干净网格层 (无材质/无灯光), 再转 usdc
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=os.path.join(out, "_tmp.glb"))
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.wm.usd_export(filepath=os.path.join(out, "geometry.usdc"),
                          export_materials=False, selected_objects_only=True)
    os.remove(os.path.join(out, "_tmp.glb"))

    profile = comp.SKU_PROFILES.get(sku, {})
    write_materials(os.path.join(out, "materials.usda"), sku)
    write_product(os.path.join(out, "Product.usda"), sku, profile, dims_mm, half_mm, mass_g_str)
    # 网格 -> 材质角色的映射 (给 86 号组装合规包用):
    # 我们用的是**自定义关系名** material:binding:pack / :cap -> **标准 USD 消费者
    # (Blender / Omniverse / Isaac) 认的是 `material:binding`**, 认不到我们的自定义名
    # -> 2026-11-28 实测: 官方验证器 Package-Candidate / Material 全 PASS, 但 Blender
    # 导入后 **材质 0 / 贴图 0** -> 官方 profile 也没抓到这条 -> 自己补上标准绑定 ✓
    # 这里只记 Blender **对象名** -> 角色 (对象名会原样出现在 USD prim 路径里 ✓,
    # 不依赖 Blender 的网格数据名 "Cube"/"Cylinder" 这种内部名 ✓)
    import json as _json
    roles = dict(obj_names)
    with open(os.path.join(out, "_material_roles.json"), "w", encoding="utf-8") as f:
        _json.dump(roles, f, ensure_ascii=False, indent=2)
    try:
        seen = validate(out)
    except ModuleNotFoundError as e:
        # 生成环境 (bpy) 不一定带 pxr -> 独立读取验证放到**只装 pxr 的环境**里跑
        print(f"[USD-ASSET] 已生成 {sku} -> {out}")
        print(f"  [跳过] 本环境没有 {e.name}: 独立读取验证请在装了 usd-core 的环境里跑 "
              f"validate() (官方 SimReady 工具环境即可)")
        return
    print(f"[USD-ASSET] PASS {sku}: defaultPrim/kind/variantSets/upAxis/metersPerUnit 验证通过")
    for cw, tgt in seen.items():
        print(f"  colorway={cw:16s} pack_material={tgt}")


if __name__ == "__main__":
    main()
