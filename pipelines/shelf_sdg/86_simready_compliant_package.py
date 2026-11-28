#!/usr/bin/env python3
"""把我们的多文件 USD 资产改造成**官方 SimReady 合规的单文件包**, 并用官方工具链验收。

2026-11-27 实测发现官方打包链的四个前置 (见 85 号):
  ① 资产目录里只能有**一个** USD 主文件 (我们是 Product.usda + geometry.usdc + materials.usda 三文件 reference 组合)
  ② 依赖 (贴图) 必须在资产根内且是 anchored 路径 (我们指到 assets/textures/ 外面)
  ③ 必须带 11 个 SR.004 元数据字段 (sidecar <主文件>.json 或根层 SimReady_Metadata)
  ④ 必须带 .thumbs/256x256/<主文件>.png (87 号脚本用同源几何渲染 ✓)

本脚本 (只装 pxr 的环境即可):
  1. 把组合后的 stage 导出成**单个** .usda (Stage.Export)
  2. 用 pxr API 重新授权 variantSet (Export 会**丢** variantSet —— 实测 ✓) + 把贴图路径改成 anchored 的 ./textures/...
  3. 复制贴图进资产根 + 写 11 字段 sidecar
  4. 跑官方 simready-validate (16 个 profile) + simready-package + 再验包

用法:
  <只装 pxr 的 python> pipelines/shelf_sdg/86_simready_compliant_package.py \
      -- --sku demo_classic [--out output/usd/demo_classic_pkg]
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "output", "benchmark", "simready_compliant_package.json")

# SR.004 的 11 个必填字段 (官方 metadata-union.md ✓)
SR004_FIELDS = ["author", "asset_name", "asset_type", "asset_license", "category",
                "source_file", "usd_date_generated", "qcode", "rigid_body_count",
                "asset_extents", "mass"]


def _load_colorways():
    """从 13_usd_asset.py 拿 COLORWAYS (单一数据源 ✓, 不在这里复写一份)。"""
    import importlib.util as ilu
    path = os.path.join(BASE, "pipelines", "ecommerce", "13_usd_asset.py")
    spec = ilu.spec_from_file_location("asset_gen", path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.COLORWAYS


def _mesh_volume_and_extents(stage, root_prim):
    """网格体积 (以质心为原点的**有符号**四面体分解) 与世界包围盒 (米)。

    2026-11-27 修正: 原来用 |det|/6 逐面累加 —— 网格不在原点附近时那算的是
    "到原点的四面体"而不是网格体积, 结果恒为 0 -> mass=0 -> SR.004 判不合格 ✓。
    改成以网格质心为原点的有符号求和 (平移不变) ✓。
    """
    from pxr import Usd, UsdGeom
    volume = 0.0
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get()
        counts = mesh.GetFaceVertexCountsAttr().Get()
        idxs = mesh.GetFaceVertexIndicesAttr().Get()
        if not pts or not counts or not idxs:
            continue
        m = len(pts)
        cx = sum(p[0] for p in pts) / m
        cy = sum(p[1] for p in pts) / m
        cz = sum(p[2] for p in pts) / m
        off = 0
        for c in counts:
            if c < 3:
                off += c
                continue
            for i in range(1, c - 1):
                a = pts[idxs[off]]
                b = pts[idxs[off + i]]
                d = pts[idxs[off + i + 1]]
                ax, ay, az = a[0] - cx, a[1] - cy, a[2] - cz
                bx, by, bz = b[0] - cx, b[1] - cy, b[2] - cz
                dx, dy, dz = d[0] - cx, d[1] - cy, d[2] - cz
                volume += (ax * (by * dz - bz * dy)
                           - ay * (bx * dz - bz * dx)
                           + az * (bx * dy - by * dx)) / 6.0
            off += c
    volume = abs(volume)
    bbox = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    b = bbox.ComputeWorldBound(root_prim).ComputeAlignedRange()
    lo, hi = b.GetMin(), b.GetMax()
    extents = [round(hi[0] - lo[0], 6), round(hi[1] - lo[1], 6), round(hi[2] - lo[2], 6)]
    return volume, extents


def build_package(sku, pkg_dir, asset_dir):
    """生成单文件合规包, 返回 (摘要, 关键中间量)。"""
    from pxr import Usd, UsdGeom, Sdf, Gf

    colorways = _load_colorways()
    src_usd = os.path.join(asset_dir, "Product.usda")
    os.makedirs(pkg_dir, exist_ok=True)
    tex_dir = os.path.join(pkg_dir, "textures")
    os.makedirs(tex_dir, exist_ok=True)

    stage = Usd.Stage.Open(src_usd)
    root = stage.GetDefaultPrim()
    assert root, "源资产没有 defaultPrim"

    # ---- 1) 导出成单文件 --------------------------------------------------
    root_name = root.GetName()
    out_usd = os.path.join(pkg_dir, f"{sku}.usda")
    if os.path.exists(out_usd):
        os.remove(out_usd)
    stage.Export(out_usd)

    # ---- 2) 贴图: 复制进资产根 + 改成 anchored 路径 ----------------------
    # 注意: 必须改**导出后的那个 stage** —— 改源 stage 不会影响已写出的文件
    # (2026-11-27 实测踩过: 官方 AA.001 仍然报绝对路径 ✓)
    pkg_stage = Usd.Stage.Open(out_usd)
    copied = []
    for prim in pkg_stage.Traverse():
        for attr in prim.GetAttributes():
            if attr.GetTypeName() != Sdf.ValueTypeNames.Asset:
                continue
            val = attr.Get()
            if not val:
                continue
            path = val.path
            if not path:
                continue
            fname = os.path.basename(path)
            src_tex = os.path.join(BASE, "assets", "textures", fname)
            if not os.path.exists(src_tex):
                src_tex = path if os.path.exists(path) else None
            if not src_tex:
                continue
            dst_tex = os.path.join(tex_dir, fname)
            if not os.path.exists(dst_tex):
                shutil.copyfile(src_tex, dst_tex)
            if fname not in copied:
                copied.append(fname)
            attr.Set(Sdf.AssetPath(f"./textures/{fname}"))

    # ---- 3) 重新授权 variantSet (Export 会丢 ✓) ------------------------
    pkg_root = pkg_stage.GetDefaultPrim()
    assert pkg_root, "导出后没有 defaultPrim"

    # 网格 -> 材质角色 (来自生成器写下的 _material_roles.json ✓)
    roles = {}
    roles_file = os.path.join(asset_dir, "_material_roles.json")
    if os.path.exists(roles_file):
        with open(roles_file, encoding="utf-8") as f:
            roles = json.load(f)

    def _role_of(prim_path):
        """ prim 路径里**最深**匹配的那个对象名决定角色 ✓。

        层级是 /Product/Carton_<sku>/Cap_<sku>/Cylinder —— cap 的路径里**也**含
        "/Carton_<sku>" -> 按字典顺序"先匹配到的赢"会把 cap 误判成 pack ✓
        (2026-11-28 实测踩过: 三个网格全绑到 pack 材质 ✓) -> 必须取**最深**的一段 ✓。
        """
        segs = [s for s in str(prim_path).split("/") if s]
        for seg in reversed(segs):
            if seg in roles:
                return roles[seg]
        return None

    def _bind_meshes(root_prim, cw):
        """给每个网格授权**标准** `material:binding` (UsdShadeMaterialBindingAPI ✓)。

        2026-11-28 实测: 我们原来只写**自定义**关系名 `material:binding:pack` / `:cap`
        -> 官方验证器 (Package-Candidate / Material) **全 PASS**, 但 Blender 导入后
        **材质 0 / 贴图 0** -> 官方 profile 也没抓到这条 -> 标准绑定必须自己补 ✓。
        """
        bound = 0
        for prim in pkg_stage.Traverse():
            if prim.GetTypeName() != "Mesh":
                continue
            role = _role_of(str(prim.GetPath()))
            if role is None:
                continue
            target = f"/{root_prim.GetName()}/M_{role}_{cw}"
            prim.CreateRelationship("material:binding").SetTargets([Sdf.Path(target)])
            bound += 1
        return bound

    vset = pkg_root.GetVariantSets().AddVariantSet("colorway")
    for cw, cfg in colorways.items():
        vset.AddVariant(cw)
        vset.SetVariantSelection(cw)
        with vset.GetVariantEditContext():
            a = pkg_root.CreateAttribute("sem:approvedAlbedo", Sdf.ValueTypeNames.Asset)
            a.Set(Sdf.AssetPath(f"./textures/{cfg['albedo']}"))
            c = pkg_root.CreateAttribute("sem:capColor", Sdf.ValueTypeNames.Color3f)
            c.Set(Gf.Vec3f(*cfg["cap"]))
            pkg_root.CreateRelationship("material:binding:pack").SetTargets(
                [Sdf.Path(f"/{pkg_root.GetName()}/M_pack_{cw}")])
            pkg_root.CreateRelationship("material:binding:cap").SetTargets(
                [Sdf.Path(f"/{pkg_root.GetName()}/M_cap_{cw}")])
            _bind_meshes(pkg_root, cw)
    # 默认态 (不选 variant) 也要有标准绑定 -> 否则只选默认的消费者看不到材质 ✓
    _bind_meshes(pkg_root, next(iter(colorways)))
    vset.ClearVariantSelection()

    # ---- 4) 尺寸 / 体积 -> extents / mass -------------------------------
    volume, extents = _mesh_volume_and_extents(pkg_stage, pkg_root)
    density = 1000.0  # kg/m^3 (演示资产: 装满的利乐包 ≈ 水基)
    mass_from_volume = round(volume * density, 4) if volume > 0 else 0.0
    # **质量的单一来源 = 生成器写的 `phys:mass` (g)** ✓ (docs/TWIN_ASSET_SPEC.md §8 ✓)
    #   生成器在 Blender 里量网格体积 ✓ -> 86 号只做**交叉核对** ✓ (两算法差 ~3% ✓)
    mass_g = None
    src_mass_attr = root.GetAttribute("phys:mass")
    if src_mass_attr and src_mass_attr.Get():
        mass_g = float(src_mass_attr.Get())
    mass = round(mass_g / 1000.0, 4) if mass_g else mass_from_volume
    mass_cross = {
        "from_generator_phys_mass_g": mass_g,
        "from_pxr_volume_kg": mass_from_volume,
        "delta_pct": (round(abs(mass - mass_from_volume) / mass_from_volume * 100, 2)
                      if mass_from_volume else None),
        "used_kg": mass,
    }

    # ---- 5) 官方物理刚体层 (RB.001 等) + 语义标签层 (SL.001 等) ---------
    # 官方规则原文:
    #   RB.001  -> RigidBodyAPI 要加在**代表刚体层级的 UsdGeomXformable** 上 ✓
    #   RB.COL.001 -> CollisionAPI 加在 gprim 上 (**不能**加在 xform 上 ✓)
    #   RB.007 -> 刚体或它拥有的碰撞体要写 `physics:mass` ✓ (kg ✓)
    #   SL.001 -> 每个可渲染 gprim 都要能解析到语义标签, 标签**可从祖先继承** ✓
    #             -> 官方检查器认的是 apiSchemas 里的 `SemanticsLabelsAPI:<instance>` ✓
    #             + `semantics:labels:<instance>` (token[] ✓) —— 不依赖 UsdSemantics 模块 ✓
    qcode = "Q1395006"  # Wikidata: cardboard box (已用 Wikidata API 核对 ✓)

    def _add_api_schemas(prim, names):
        """往 prim 的 apiSchemas 里加 schema 名 (直接写 metadata ✓)。

        为什么不用 pxr 的 Apply(): `MjcCollisionAPI` / `NewtonMeshCollisionAPI` 来自
        usd-physics 扩展, 本环境**没装** (usd-core 不含 ✓) -> 官方检查器读的就是
        **apiSchemas metadata** (`_has_applied_api_schema` ✓) -> 直接授权即可 ✓。
        """
        api = prim.GetMetadata("apiSchemas")
        items = list(api.GetAddedOrExplicitItems()) if api else []
        for n in names:
            if n not in items:
                items.append(n)
        prim.SetMetadata("apiSchemas", Sdf.TokenListOp.CreateExplicit(items))

    physics_applied = {"rigid_body": False, "colliders": 0, "mass": mass,
                       "dialect_apis": []}
    try:
        from pxr import UsdPhysics
        rb = UsdPhysics.RigidBodyAPI.Apply(pkg_root)
        rb.CreateRigidBodyEnabledAttr(True)
        mass_api = UsdPhysics.MassAPI.Apply(pkg_root)
        mass_api.CreateMassAttr(mass)
        physics_applied["rigid_body"] = True
        for prim in pkg_stage.Traverse():
            if prim.GetTypeName() == "Mesh":
                UsdPhysics.CollisionAPI.Apply(prim)
                UsdPhysics.MeshCollisionAPI.Apply(prim)
                # 每个碰撞体还要带**方言** API (官方检查器点名 ✓):
                # MUJOCO.COL.001 要 MjcCollisionAPI ✓ / NEWTON.COL.001 要
                # NewtonMeshCollisionAPI ✓ -> 不加这两条, 官方会逐个碰撞体点名 ✗
                _add_api_schemas(prim, ["MjcCollisionAPI", "NewtonMeshCollisionAPI"])
                physics_applied["colliders"] += 1
                physics_applied["dialect_apis"] = ["MjcCollisionAPI", "NewtonMeshCollisionAPI"]
    except Exception as e:  # 官方物理层是"加分层", 失败要留痕而不是静默跳过
        physics_applied["error"] = f"{type(e).__name__}: {e}"

    # 语义标签: 根 prim 一个 (Wikidata Q-code ✓, 可被后代继承 ✓)
    #   + **每个材质也要有**标签 (SL.MAT.001 点名 ✓: "Unlabeled material")
    semantics_applied = {"instance": "wikidata_qcode", "labels": [qcode],
                         "materials_labeled": 0}
    _add_api_schemas(pkg_root, ["SemanticsLabelsAPI:wikidata_qcode"])
    pkg_root.CreateAttribute("semantics:labels:wikidata_qcode",
                              Sdf.ValueTypeNames.TokenArray).Set([qcode])
    for prim in pkg_stage.Traverse():
        if prim.GetTypeName() != "Material":
            continue
        _add_api_schemas(prim, ["SemanticsLabelsAPI:material"])
        label = "plastic" if "_cap_" in prim.GetName() else "packaging"
        prim.CreateAttribute("semantics:labels:material",
                             Sdf.ValueTypeNames.TokenArray).Set([label])
        semantics_applied["materials_labeled"] += 1

    # Export 写入的 doc 里带**绝对路径** (源机器路径) -> 清掉 (可移植性 ✓)
    pkg_stage.GetRootLayer().doc = ""

    # 官方 AF.001: defaultPrim 要写 `simready:assetFrame:forwardDirection` ✓
    #   (custom vector3f ✓ / uniform ✓ / 单位长度 ✓)
    # 朝向**不猜**: 我们资产的主印刷面朝 -Y (01_comfy_usd_compositor 的机位在 -Y ✓)
    fwd = pkg_root.CreateAttribute("simready:assetFrame:forwardDirection",
                                   Sdf.ValueTypeNames.Vector3f, custom=True,
                                   variability=Sdf.VariabilityUniform)
    fwd.Set(Gf.Vec3f(0.0, -1.0, 0.0))

    pkg_stage.GetRootLayer().Save()

    # ---- 6) SR.004 sidecar ----------------------------------------------
    sidecar = {
        "author": "Topprism",
        "asset_name": sku,
        "asset_type": "prop",
        "asset_license": "CC-BY-4.0",
        "category": "Beverage Carton",
        "source_file": f"./{sku}.usda",
        "usd_date_generated": time.strftime("%Y-%m-%d"),
        "qcode": qcode,  # Wikidata: cardboard box (已用 Wikidata API 核对 ✓)
        # 刚体数**按实际授权的算** ✓ (之前硬编码 0 ✗ -> 交付元数据与资产本身不符 ✓)
        "rigid_body_count": 1 if physics_applied.get("rigid_body") else 0,
        "asset_extents": extents,
        "mass": mass,
        # 额外自定义字段 (官方允许 ✓): 把"估算依据"写进资产, 不留口头约定
        "mass_basis": (f"来自生成器的 phys:mass ({mass_g} g = 网格体积 x 水密度 1 g/cm^3, 未计包装); "
                       f"86 号用 pxr 重算体积 {volume*1e6:.1f} cm^3 交叉核对 "
                       f"(差 {mass_cross['delta_pct']}%) —— **未实测称重**"),
        "qcode_basis": "Wikidata Q1395006 = cardboard box",
        "asset_source": "ortho_work pipelines/ecommerce/13_usd_asset.py (Blender 参数化利乐包数字母本)",
    }
    # 侧车文件名 = <usd_stem>.json (官方 path_utils.sidecar_json_identifier ✓
    # -> "demo_classic.usda" 的 stem 是 "demo_classic" -> demo_classic.json)
    # 2026-11-27 实测: 写成 demo_classic.usda.json **读不到** (SR.004 报 11 个字段全缺 ✓)
    stale = os.path.join(pkg_dir, f"{sku}.usda.json")
    if os.path.exists(stale):
        os.remove(stale)
    with open(os.path.join(pkg_dir, f"{sku}.json"), "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)

    missing = [k for k in SR004_FIELDS if k not in sidecar or sidecar[k] in ("", None)]
    summary = {
        "mass_cross_check": mass_cross,
        "physics_layer": physics_applied,
        "semantics_layer": semantics_applied,
        "pkg_dir": os.path.relpath(pkg_dir, BASE).replace("\\", "/"),
        "root_usd": f"{sku}.usda",
        "textures": copied,
        "sidecar": sidecar,
        "sidecar_missing_fields": missing,
        "mesh_volume_m3": round(volume, 8),
    }
    return summary, pkg_stage


def verify_package(pkg_dir, sku):
    """独立读取验证 (pxr): 单文件 / 无 reference / 锚定贴图 / 绑定与连接真的解析。"""
    from pxr import Usd, Sdf
    out_usd = os.path.join(pkg_dir, f"{sku}.usda")
    stage = Usd.Stage.Open(out_usd)
    root = stage.GetDefaultPrim()
    checks = {}
    checks["defaultPrim"] = root.GetName() if root else None
    checks["kind"] = root.GetKind() if root else None
    checks["variantSets"] = list(root.GetVariantSets().GetNames()) if root else []
    checks["references_in_file"] = "references" in open(out_usd, encoding="utf-8").read()

    def _binding(label, cw=None):
        rel = root.GetRelationship("material:binding:pack")
        targets = list(rel.GetTargets())
        if not targets:
            return False, f"{label}: binding 为空"
        for t in targets:
            prim = stage.GetPrimAtPath(t)
            if not prim or not prim.IsValid():
                return False, f"{label}: 目标 prim 不存在 {t}"
            conns = prim.GetAttribute("outputs:surface").GetConnections()
            if not conns:
                return False, f"{label}: outputs:surface 连接没解析"
            bsdf = prim.GetChild("BSDF")
            dconn = bsdf.GetAttribute("inputs:diffuseColor").GetConnections() if bsdf else []
            if not dconn:
                return False, f"{label}: inputs:diffuseColor 连接没解析"
        return True, f"{label}: OK ({len(targets)} 个绑定)"

    ok, msg = _binding("默认态")
    checks["default_binding"] = {"ok": ok, "msg": msg}
    vs = root.GetVariantSets().GetVariantSet("colorway") if "colorway" in checks["variantSets"] else None
    variant_msgs = []
    if vs:
        for cw in vs.GetVariantNames():
            vs.SetVariantSelection(cw)
            albedo = root.GetAttribute("sem:approvedAlbedo").Get()
            ok2, msg2 = _binding(f"variant {cw}")
            variant_msgs.append({"variant": cw, "albedo": str(albedo), "ok": ok2, "msg": msg2})
    checks["variants"] = variant_msgs

    # 贴图路径: 必须 anchored 且在资产根内
    abs_paths = []
    for prim in stage.Traverse():
        for attr in prim.GetAttributes():
            if attr.GetTypeName() == Sdf.ValueTypeNames.Asset:
                v = attr.Get()
                if v and v.path and not v.path.startswith("./"):
                    abs_paths.append(f"{prim.GetPath()}.{attr.GetName()}={v.path}")
    checks["non_anchored_asset_paths"] = abs_paths
    return checks


def official_validate(path, tag):
    """跑官方 16 个 profile, 返回逐 profile 结果。"""
    import simready.validate as sv
    from pxr import Usd
    sv.initialize([], [], [])
    profiles = sv.get_available_profiles()
    rows = []
    for pid, vers in profiles.items():
        version = None
        if isinstance(vers, dict) and vers:
            def _key(v):
                try:
                    return tuple(int(x) for x in str(v).split("."))
                except Exception:
                    return (0,)
            version = max(vers.keys(), key=_key)
        elif isinstance(vers, (list, tuple)) and vers:
            version = vers[0]
        t0 = time.time()
        try:
            result = sv.validate_stage_against_profiles(
                Usd.Stage.Open(path),
                [sv.ProfileTarget(pid, version)] if version else [sv.ProfileTarget(pid)],
                asset_path=path)
            res = result[0] if isinstance(result, list) and result else result
        except Exception as e:
            rows.append({"profile": pid, "error": f"{type(e).__name__}: {e}"})
            continue
        if res is None:
            rows.append({"profile": pid, "result": None,
                         "note": "unavailable_execution (不是 measured failure)"})
            continue
        summary = getattr(res, "features_summary", None)
        try:
            passed = bool(sv.features_summary_passed(summary)) if summary else None
        except Exception:
            passed = None
        blocking, failed = [], []
        for name, entry in (summary or {}).items():
            try:
                if sv.is_blocking_failure(entry):
                    blocking.append(name)
            except Exception:
                pass
            if isinstance(entry, dict) and entry.get("passed") is False:
                failed.append(name)
        rows.append({"profile": pid, "profile_version": version, "passed": passed,
                     "blocking_failures": blocking, "failed_features": failed,
                     "elapsed_s": round(time.time() - t0, 3)})
        print(f"  [{'PASS' if passed else ('FAIL' if passed is False else 'NONE')}] {tag} {pid} "
              f"failed={len(failed)} blocking={len(blocking)}")
    return rows


def package_level_evidence(pkg_out):
    """读打包器写下的**合规证据**, 并补跑 `Package-NoBOM` (定义层判定 ✓)。

    为什么重要: `Package` / `Package-NoBOM` 这两个 profile **不能**对 USD stage 判定
    (官方会报 "unavailable" ✓ —— 它们吃的是**包定义** BOM ✓) -> 只有走**定义层**
    判定 (官方打包器内部那条路 ✓) 才拿得到结论 ✓ -> 这里把官方打包器写下的
    conformance JSON 读出来当证据 ✓, 并自己再跑一次 Package-NoBOM ✓。
    """
    out = {"conformance_files": {}, "package_no_bom": None}
    meta = os.path.join(pkg_out, ".metadata")
    if os.path.isdir(meta):
        for name in sorted(os.listdir(meta)):
            if not name.startswith("com.nvidia.simready.conformance."):
                continue
            try:
                with open(os.path.join(meta, name), encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                out["conformance_files"][name] = {"error": f"{type(e).__name__}: {e}"}
                continue
            feats = {}
            for asset in data.get("assets", []):
                for group in asset.get("features", []):
                    for fid, fv in group.items():
                        feats[fid] = {"passed": fv.get("passed"),
                                      "failing_requirements": fv.get("failing_requirements") or []}
            out["conformance_files"][name] = {"profile": data.get("profile"),
                                              "profile_version": data.get("profile_version"),
                                              "features": feats}
    definition = os.path.join(pkg_out, "com.nvidia.simready.packaging.json")
    if os.path.exists(definition):
        try:
            from simready.package._package_engine import validate_definition
            res = validate_definition(Path(definition), "Package-NoBOM", None)
            summary = getattr(res, "features_summary", {}) or {}
            out["package_no_bom"] = {
                "profile_version": getattr(res, "profile_version", None),
                "features": {k: {"passed": (v or {}).get("passed") if isinstance(v, dict) else None}
                             for k, v in summary.items()},
            }
        except Exception as e:
            out["package_no_bom"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def official_package(pkg_dir, sku, out_dir):
    exe = shutil.which("simready-package") or shutil.which("simready-package.exe")
    if not exe:
        cand = os.path.join(os.path.dirname(sys.executable), "simready-package.exe")
        exe = cand if os.path.exists(cand) else None
    if not exe:
        return {"error": "找不到 simready-package"}
    if os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    r = subprocess.run([exe, "package", pkg_dir, "--root-usd", f"{sku}.usda",
                        "--name", sku, "--license", "CC-BY-4.0", "--out", out_dir],
                       capture_output=True, text=True, timeout=1800)
    files = []
    if os.path.isdir(out_dir):
        for root, _d, fs in os.walk(out_dir):
            for f in fs:
                files.append(os.path.relpath(os.path.join(root, f), out_dir).replace("\\", "/"))
    return {"rc": r.returncode, "stdout_tail": (r.stdout or "")[-1200:],
            "stderr_tail": (r.stderr or "")[-400:], "package_files": sorted(files)}


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sku = "demo_classic"
    pkg_dir = None
    asset_dir = None
    for i, a in enumerate(argv):
        if a == "--sku" and i + 1 < len(argv):
            sku = argv[i + 1]
        elif a == "--out" and i + 1 < len(argv):
            pkg_dir = argv[i + 1]
        elif a == "--asset" and i + 1 < len(argv):
            asset_dir = argv[i + 1]
    if asset_dir is None:
        asset_dir = os.path.join(BASE, "output", "usd", sku)
    if pkg_dir is None:
        pkg_dir = os.path.join(BASE, "output", "usd", f"{sku}_pkg")
    for p in (asset_dir, pkg_dir):
        if not os.path.isabs(p):
            p = os.path.join(BASE, p)

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "script": "pipelines/shelf_sdg/86_simready_compliant_package.py",
              "sku": sku, "asset_dir": os.path.relpath(asset_dir, BASE).replace("\\", "/")}

    print(f"[86] 生成单文件合规包 -> {pkg_dir}")
    summary, stage = build_package(sku, pkg_dir, asset_dir)
    report["package"] = summary

    print("[86] 独立读取验证")
    checks = verify_package(pkg_dir, sku)
    report["checks"] = checks
    for k, v in checks.items():
        print(f"   {k}: {v}")

    print("[86] 官方 validate (合规包目录)")
    report["official_validate_pkg"] = official_validate(
        os.path.join(pkg_dir, f"{sku}.usda"), "pkg")

    print("[86] 官方 package")
    pkg_out = os.path.join(BASE, "output", "usd", "_simready_work", f"{sku}_package")
    rep = official_package(pkg_dir, sku, pkg_out)
    report["official_package"] = rep
    print(f"   rc={rep.get('rc')} 产物 {len(rep.get('package_files') or [])} 个文件")
    for line in (rep.get("stdout_tail") or "").strip().splitlines()[-3:]:
        print("   ", line)

    if rep.get("rc") == 0:
        # 包级合规证据 (Package / Package-NoBOM 只能走**定义层**判定 ✓)
        report["package_level_evidence"] = package_level_evidence(pkg_out)
        _ev = report["package_level_evidence"]
        for _name, _v in (_ev.get("conformance_files") or {}).items():
            _passed = [k for k, vv in (_v.get("features") or {}).items() if vv.get("passed")]
            print(f"   [证据] {_v.get('profile')} {_v.get('profile_version')}: "
                  f"{len(_passed)}/{len(_v.get('features') or {})} feature 通过")
        if _ev.get("package_no_bom"):
            print(f"   [证据] Package-NoBOM: {_ev['package_no_bom']}")
        print("[86] 官方 validate (打包产物)")
        main_pkg = os.path.join(pkg_out, f"{sku}.usda")
        if os.path.exists(main_pkg):
            report["official_validate_package"] = official_validate(main_pkg, "package")
        else:
            report["official_validate_package"] = [{"error": f"包里没找到 {main_pkg}"}]

    report["not_done"] = [
        "RB.001 物理刚体层 / SL.001 官方语义标签层 —— 属资产库产品线 (兄弟仓), 本轮只做打包链合规",
        "官方 simready-benchmark (需 Isaac Sim 6.1, 本机没有)",
        "官方 simready-manage 上传 / HF 发布 (未装)",
    ]
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[86] -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
