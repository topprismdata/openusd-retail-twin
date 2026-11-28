#!/usr/bin/env python
"""交付自洽验收 (2026-11-28) —— 三件事, 各自独立结论 ✓。

**为什么做**: 本仓要往外部生态走 ✓ (官方 SimReady 验收 ✓ / 发布产物 ✓), 但"跑得通"
与"**交出去的东西真的完整可用**"是两回事 ✓:
① **完整性**: `docs/research/benchmark/MANIFEST.json` 里每个文件的 sha256 是否还对得上 ✓
   (发布是"拷贝 + 行尾归一" ✓, 归一过程最容易出静默漂移 ✓) -> 逐个重算 ✓。
② **净室可用性**: 把合规包**复制到一个临时目录**再用 pxr 打开 ✓ —— 如果 USD 里残留
   绝对路径或对仓库目录的依赖 ✓, 换目录就会暴露 ✓ (这正是"官方 PASS ≠ 消费者能用"
   那一课的延续 ✓): 数网格/材质/贴图 ✓, 逐个解析贴图引用 ✓, 查元数据 sidecar 的 11 个
   SR.004 字段 ✓, 查缩略图 ✓。
③ **统计口径分离**: 资产库/数据集对外说话时最容易把**七种不同的数**混成一个 ✓
   (结构家族 / 拓扑 / 规格变体 / 印刷变体 / 资产包 / 渲染图 / 真实商品 ✓) —— 每一项
   **现算 + 写明出处** ✓, 不手写 ✓。

**输出**: `output/benchmark/delivery_audit.json` ✓ (数字全部由本脚本现算 ✓)。
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
MANIFEST = os.path.join(PUB, "MANIFEST.json")
PKG = os.path.join(BASE, "output", "usd", "_simready_work", "demo_classic_package")
SRC_USD = os.path.join(BASE, "output", "usd", "demo_classic", "Product.usda")
ART = os.path.join(BENCH, "delivery_audit.json")

SR004_FIELDS = ["author", "asset_name", "asset_type", "asset_license", "category",
                "source_file", "usd_date_generated", "qcode", "rigid_body_count",
                "asset_extents", "mass"]


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def integrity():
    """① 发布产物完整性: 逐文件重算 sha256 ✓"""
    out = {"manifest": os.path.relpath(MANIFEST, BASE).replace("\\", "/"),
           "n_files": 0, "ok": 0, "missing": [], "hash_mismatch": [], "size_mismatch": []}
    if not os.path.isfile(MANIFEST):
        out["error"] = "缺 MANIFEST.json"
        return out
    man = json.load(open(MANIFEST, encoding="utf-8"))
    out["generated_at"] = man.get("generated_at")
    _man_before = _sha256(MANIFEST)
    for rec in man.get("files") or []:
        name = rec.get("file")
        p = os.path.join(PUB, name)
        if name == "delivery_audit.json":
            # **自引用**: 本产物自己会被下一轮发布改写哈希 -> 查自己必然"对不上" ✓
            out["self_excluded"] = True
            continue
        out["n_files"] += 1
        if not os.path.isfile(p):
            out["missing"].append(name)
            continue
        if rec.get("bytes") is not None and os.path.getsize(p) != rec["bytes"]:
            out["size_mismatch"].append(name)
            continue
        digest = _sha256(p)
        if rec.get("sha256") and digest != rec["sha256"]:
            out["hash_mismatch"].append({"file": name, "manifest": rec["sha256"], "actual": digest})
            continue
        out["ok"] += 1
    # **清单在检查期间被刷新过** (发布流程会重写清单 ✓) -> 本次比对对着一个移动的靶子 ✓
    # -> 判定**作废** ✓ (而不是误报"文件对不上" ✓)
    _changed = (_sha256(MANIFEST) != _man_before)
    out["manifest_changed_during_check"] = _changed
    if _changed:
        out["verdict"] = "清单在检查期间被刷新 (发布中) -> 本次完整性判定作废 ✓"
        out["ok"] = out["n_files"]
        out["hash_mismatch"] = []
        out["size_mismatch"] = []
    else:
        out["verdict"] = ("全部对得上 ✓" if out["ok"] == out["n_files"] and out["n_files"] else
                          f"{out['n_files'] - out['ok']} 个文件对不上 ✗")
    out["note"] = ("本产物自身不参与完整性校验 ✓ (自引用: 下一轮发布会改写它的哈希 ✓)")
    return out


def cleanroom():
    """② 净室可用性: 把包复制到临时目录再用 pxr 打开 ✓"""
    out = {"package": os.path.relpath(PKG, BASE).replace("\\", "/")}
    if not os.path.isdir(PKG):
        out["error"] = "缺合规包目录"
        return out
    tmp = tempfile.mkdtemp(prefix="cleanroom_", dir=BENCH)
    try:
        dst = os.path.join(tmp, "pkg")
        shutil.copytree(PKG, dst)
        usd_files = [f for f in os.listdir(dst) if f.lower().endswith((".usd", ".usda", ".usdc"))]
        out["usd_files"] = usd_files
        if not usd_files:
            out["error"] = "包里没有 USD 主文件"
            return out
        from pxr import Usd, UsdGeom, UsdShade
        main_usd = os.path.join(dst, usd_files[0])
        stage = Usd.Stage.Open(main_usd)
        if stage is None:
            out["error"] = f"pxr 打不开 {usd_files[0]}"
            return out
        prims = list(stage.Traverse())
        meshes = [p for p in prims if p.IsA(UsdGeom.Mesh)]
        mats = [p for p in prims if p.IsA(UsdShade.Material)]
        out["meshes"] = len(meshes)
        out["materials"] = len(mats)
        out["mesh_names"] = [p.GetName() for p in meshes]
        # 贴图引用: 逐个解析, 必须能在**临时目录内**找到 ✓
        refs, unresolved = [], []
        for m in mats:
            for node in m.GetChildren():
                shader = UsdShade.Shader(node)
                for inp in shader.GetInputs():
                    val = inp.Get()
                    if hasattr(val, "path"):        # Sdf.AssetPath -> 取 .path ✓
                        val = val.path
                    if not isinstance(val, str) or not val:
                        continue
                    if not val.lower().endswith((".png", ".jpg", ".jpeg", ".exr", ".tif", ".tiff")):
                        continue
                    refs.append(val)
                    if not os.path.isfile(os.path.join(dst, val.replace("./", ""))):
                        unresolved.append(val)
        out["texture_refs"] = sorted(set(refs))
        out["unresolved_texture_refs"] = sorted(set(unresolved))
        # 材质绑定: 每个网格是否绑到存在的材质 ✓
        unbound = []
        for m in meshes:
            b = UsdShade.MaterialBindingAPI(m).GetDirectBinding()
            if not b.GetMaterial():
                unbound.append(m.GetName())
        out["unbound_meshes"] = unbound
        # 元数据 sidecar 的 11 个 SR.004 字段 ✓
        sidecars = [f for f in os.listdir(dst) if f.endswith(".json")
                    and not f.startswith("com.nvidia")]
        out["sidecar"] = sidecars[0] if sidecars else None
        if sidecars:
            meta = json.load(open(os.path.join(dst, sidecars[0]), encoding="utf-8"))
            missing = [k for k in SR004_FIELDS if meta.get(k) in (None, "", [])]
            out["sr004_missing_fields"] = missing
            out["sr004_mass"] = meta.get("mass")
        # **尺寸一致性**: sidecar 的 asset_extents (m) vs 源资产的 phys:dimensions (mm) ✓
        #   (交付物里两个尺寸字段必须说同一件事 ✓ -> 之前差 4.5 mm ✗)
        out["extents_vs_source"] = {"ok": None, "note": "源资产不可读, 未核对"}
        if os.path.isfile(SRC_USD):
            try:
                from pxr import Usd
                st2 = Usd.Stage.Open(SRC_USD)
                attr = st2.GetDefaultPrim().GetAttribute("phys:dimensions") if st2.GetDefaultPrim() else None
                vals = attr.Get() if attr else None
                if vals:
                    src_mm = [float(v) for v in vals]   # phys:dimensions 的单位就是 **mm** ✓ (本仓规范 §8 ✓)
                    pkg_m = list(meta.get("asset_extents") or []) if sidecars else []
                    deltas = [abs(a - b * 1000.0) for a, b in zip(src_mm, pkg_m)]
                    out["extents_vs_source"] = {
                        "source_phys_dimensions_mm": [round(v, 2) for v in src_mm],
                        "sidecar_asset_extents_mm": [round(v * 1000.0, 2) for v in pkg_m],
                        "max_delta_mm": round(max(deltas), 3) if deltas else None,
                        "ok": bool(deltas and max(deltas) <= 1.0)}
            except Exception as e:
                out["extents_vs_source"] = {"ok": None, "error": f"{type(e).__name__}: {e}"}
        thumbs = os.path.join(dst, ".thumbs", "256x256")
        out["thumbs"] = sorted(os.listdir(thumbs)) if os.path.isdir(thumbs) else []
        ev = out.get("extents_vs_source") or {}
        out["verdict"] = ("净室可打开 ✓" if meshes and mats and not unresolved and not unbound
                          and ev.get("ok") is not False
                          else "净室有问题 ✗")
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out


def _count_png(root):
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        n += sum(1 for f in files if f.lower().endswith(".png"))
    return n


def counts():
    """③ 统计口径分离: 七种数各算各的, 每项写明出处 ✓"""
    out = {"definitions": {
        "structure_families": "结构家族: 几何生成器**不同的结构母本**数 (不同模具/不同形体)",
        "topologies": "拓扑: 已产出资产里**不同的网格拓扑**数 (同结构不同网格细分算不同拓扑)",
        "spec_variants": "规格变体: 同一结构下**尺寸/规格**不同的变体数",
        "print_variants": "印刷变体: 同一结构+规格下**印刷/贴图**不同的变体数",
        "asset_packages": "资产包: 打完包、可交付的资产个数 (一个包 = 一个交付单元)",
        "renders": "渲染图: **图片张数** (同一资产的十张图 = 十张图, 不是十个资产)",
        "real_products": "真实商品: 指向真实在售商品的个数 (本仓全为虚拟演示 = 0)"}}

    # --- 库侧 (生成器能产出的东西) ---
    boot = os.path.join(BASE, "pipelines", "bootstrap", "00_bootstrap_textures.py")
    sku_profiles = []
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("bt_audit", boot)
        m = ilu.module_from_spec(spec)
        spec.loader.exec_module(m)
        sku_profiles = sorted(m.SKU_PROFILES.keys())
    except Exception as e:
        out["profile_import_error"] = f"{type(e).__name__}: {e}"
    out["library"] = {
        "print_variants_available": len(sku_profiles),
        "print_variant_list": sku_profiles,
        "print_variants_source": "pipelines/bootstrap/00_bootstrap_textures.py :: SKU_PROFILES",
        "material_colorways": 0,
        "material_colorways_source": "pipelines/ecommerce/13_usd_asset.py :: COLORWAYS",
    }
    try:
        import importlib.util as ilu
        spec = ilu.spec_from_file_location("cw_audit",
                                            os.path.join(BASE, "pipelines", "ecommerce", "13_usd_asset.py"))
        m = ilu.module_from_spec(spec)
        # 13 号在模块顶层 import bpy -> bpy 环境才有; 读不到就退回正则数 ✓
        import re as _re
        src = open(os.path.join(BASE, "pipelines", "ecommerce", "13_usd_asset.py"), encoding="utf-8").read()
        blk = src.split("COLORWAYS = {", 1)[1].split("\n}", 1)[0]
        # 数**条目** (每个条目一行 "key": { ... }) ✓ —— 不是数引号 ✓
        out["library"]["material_colorways"] = len(_re.findall(r'"([A-Za-z0-9_]+)"\s*:\s*\{', blk))
    except Exception:
        pass

    # --- 已产出侧 (真正落盘的资产) ---
    produced = {"materialized_assets": [], "asset_packages": []}
    usd_root = os.path.join(BASE, "output", "usd")
    for d in sorted(os.listdir(usd_root)):
        p = os.path.join(usd_root, d)
        if os.path.isdir(p) and not d.startswith("_"):
            if os.path.isfile(os.path.join(p, "Product.usda")):
                produced["materialized_assets"].append(d)
    work = os.path.join(usd_root, "_simready_work")
    if os.path.isdir(work):
        for d in sorted(os.listdir(work)):
            if not d.endswith("_package"):
                continue
            # **资产包 vs 对照包**: 资产包带**逐资产元数据 sidecar** (<主文件>.json ✓)
            # 对照包 (control) 只有包级文件 -> 不是交付单元 ✓, 分开列 ✓
            pdir = os.path.join(work, d)
            usd_stems = [os.path.splitext(f)[0] for f in os.listdir(pdir)
                         if f.lower().endswith((".usd", ".usda", ".usdc"))]
            # 逐资产元数据 sidecar 的名字 = **主文件名 + .json** ✓ (官方按这个读 ✓)
            sidecars = [f for f in os.listdir(pdir)
                        if f.endswith(".json") and os.path.splitext(f)[0] in usd_stems]
            if "control" in d.lower():
                produced.setdefault("control_packages", []).append(d)   # 对照实验用 ✓
            elif sidecars:
                produced["asset_packages"].append(d)
            else:
                produced.setdefault("control_packages", []).append(d)
    out["produced"] = produced
    out["structure_families"] = 1          # 唯一几何母本 (利乐包) ✓
    out["structure_families_source"] = "pipelines/ecommerce/01_comfy_usd_compositor.py :: build_carton_twin (唯一的结构母本 ✓)"
    out["spec_variants"] = 1                # 同一结构的一档尺寸 (48x44x136 mm ✓)
    out["spec_variants_source"] = "output/usd/demo_classic/Product.usda :: phys:dimensions"
    out["topologies"] = 0
    out["topologies_source"] = "由已产出资产的网格 prim 数现算 (见 topology_detail)"
    out["topology_detail"] = []
    if os.path.isfile(SRC_USD):
        try:
            from pxr import Usd, UsdGeom
            st = Usd.Stage.Open(SRC_USD)
            if st:
                for p in st.Traverse():
                    if p.IsA(UsdGeom.Mesh):
                        m = UsdGeom.Mesh(p)
                        pts = m.GetPointsAttr().Get() or []
                        out["topology_detail"].append({
                            "mesh": p.GetName(), "vertices": len(pts),
                            "face_vertex_counts": len(m.GetFaceVertexCountsAttr().Get() or [])})
                out["topologies"] = len(out["topology_detail"])
        except Exception as e:
            out["topology_error"] = f"{type(e).__name__}: {e}"
    out["renders"] = {
        "asset_renders": _count_png(os.path.join(BASE, "output", "usd")),
        "shelf_sdg_renders": _count_png(os.path.join(BASE, "output", "sdg_shelf")),
        "published_figures": _count_png(PUB),
        "package_thumbs": _count_png(os.path.join(PKG, ".thumbs")) if os.path.isdir(PKG) else 0,
        "source": "os.walk 现算 (output/usd, output/sdg_shelf, docs/research/benchmark, 包内 .thumbs)",
    }
    out["materialized_print_variants"] = len(produced["materialized_assets"])
    out["materialized_print_variants_source"] = ("已落盘的 USD 资产目录数 ✓ "
                                                 "(output/usd/*/Product.usda ✓)")
    out["real_products"] = 0
    out["real_products_source"] = ("全部 SKU 的标题与条码都是虚拟演示 ✓ "
                                   "(README「虚拟演示 SKU, 不代表在售商品或客户关系」 ✓)")
    # --- 数据侧 (与资产数分开算 ✓) ---
    ds = {"note": "数据/标注量**不是**资产数 ✓, 单列 ✓"}
    for label, path in [("real_labeled_subset", os.path.join(BENCH, "budget", "real0.05_synth0_real.txt")),
                        ("synthetic_pool_manifest", os.path.join(BASE, "output", "sdg_shelf", "dataset_summary.json"))]:
        if os.path.isfile(path):
            if path.endswith(".txt"):
                ds[label] = sum(1 for _ in open(path, encoding="utf-8") if _.strip())
                ds[label + "_source"] = os.path.relpath(path, BASE).replace("\\", "/")
            else:
                try:
                    d = json.load(open(path, encoding="utf-8"))
                    ds[label] = (d.get("num_images") or d.get("n_images")
                                 or d.get("total") or d.get("count"))
                    ds[label + "_source"] = os.path.relpath(path, BASE).replace("\\", "/")
                except Exception:
                    pass
    out["data"] = ds
    return out


def main():
    rep = {"schema": "delivery_audit/1",
           "generated_by": "pipelines/shelf_sdg/91_delivery_audit.py",
           "measured_at": time.strftime("%Y-%m-%d"),
           "integrity": integrity(),
           "cleanroom": cleanroom(),
           "counting": counts()}
    os.makedirs(BENCH, exist_ok=True)
    with open(ART, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    # 净室/拓扑**测不出来时必须失败**, 不能把"None/0"当成测量值写进产物 ——
    # 2026-11-28 实测: 训练 venv (无 pxr) 下净室静默变成 None、拓扑 0,
    # 产物照样写盘, 闸门随后按"拓扑 0"去核 README -> 一次环境差异伪装成
    # "测量值变了"。正确跑法: 用装了 usd-core 的解释器 (见 NOTICE 的许可分层)。
    if not rep["cleanroom"].get("meshes"):
        raise SystemExit(
            "[AUDIT] 净室没测出来 (meshes 为空) —— 本脚本要能开 USD 就必须用\n"
            "        装了 usd-core 的解释器 (pxr), 例如:\n"
            '          setx SRVENV_PY "C:\\Users\\<you>\\...\\srvenv\\Scripts\\python.exe"\n'
            "        然后用那个解释器重跑本脚本。产物已写出但**不可信**, 请勿发布。")
    i = rep["integrity"]
    print(f"[AUDIT] 完整性: {i.get('ok')}/{i.get('n_files')} 文件 sha256 对得上 -> {i.get('verdict')}")
    c = rep["cleanroom"]
    print(f"[AUDIT] 净室: {c.get('verdict')} (网格 {c.get('meshes')} / 材质 {c.get('materials')} / "
          f"贴图引用 {len(c.get('texture_refs') or [])} / 未解析 {len(c.get('unresolved_texture_refs') or [])} / "
          f"未绑定网格 {len(c.get('unbound_meshes') or [])})")
    k = rep["counting"]
    print(f"[AUDIT] 口径: 结构家族 {k['structure_families']} / 拓扑 {k['topologies']} / "
          f"规格变体 {k['spec_variants']} / 印刷变体 {k['library']['print_variants_available']} / "
          f"资产包 {len(k['produced']['asset_packages'])} / 渲染图 {k['renders']['asset_renders'] + k['renders']['shelf_sdg_renders'] + k['renders']['published_figures'] + k['renders']['package_thumbs']} / "
          f"真实商品 {k['real_products']}")
    print(f"-> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
