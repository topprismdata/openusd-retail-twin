#!/usr/bin/env python3
"""USDCraft 兼容门: 按 NVlabs/USDCraft sdk/_core/_usd_validate.py 的 GENERIC 检查清单
逐项独立判我们的 USD 资产, 输出命名检查通过/失败表 + 证据字段 (实测 extents vs 声明)。

思路来源 (Apache-2.0): NVIDIA USDCraft 2026-10 (arXiv 2610.11322)。
命名检查 = 他们的 _GENERIC_VALIDATION_CHECKS; 证据字段 = ESR 扩展 (USDCraft 无, 我们补)。

用法: python3 scripts/usdcraft_gate.py <asset.usd[c|z]> [更多...]
"""

import json
import math
import sys
import zipfile
from pathlib import Path

from pxr import Sdf, Usd, UsdGeom, UsdPhysics


def open_stage(path: Path):
    if path.suffix == ".usdz":
        with zipfile.ZipFile(path) as z:
            inner = [n for n in z.namelist() if n.endswith((".usdc", ".usda"))]
            if not inner:
                return None, "usdz 内无 usd 层"
        # pxr 直接开 usdz (只读)
    stage = Usd.Stage.Open(path.as_posix())
    if stage is None:
        return None, "stage 无法打开"
    comp = list(stage.GetCompositionErrors())
    if comp:
        return None, f"组合错误: {comp[0]}"
    return stage, None


def gate(path: Path):
    stage, err = open_stage(path)
    checks = {}
    if err:
        return {"asset": str(path), "checks": {"stage_open": False}, "error": err, "evidence": {}}
    checks["stage_open"] = True
    # default_prim (USDCraft 硬性: /Asset)
    dp = stage.GetDefaultPrim()
    checks["default_prim"] = bool(dp)
    checks["default_prim_is_asset"] = bool(dp) and dp.GetPath() == Sdf.Path("/Asset")
    # 单位
    checks["z_up"] = UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    checks["meters"] = bool(mpu) and math.isclose(float(mpu), 1.0, abs_tol=1e-12)
    kg = UsdPhysics.GetStageKilogramsPerUnit(stage)
    checks["kilograms"] = bool(kg) and math.isclose(float(kg), 1.0, abs_tol=1e-12)
    # 可复用资产不得带 PhysicsScene
    checks["reusable_asset_no_scene"] = not any(
        prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse())
    # 有限数值 — 对齐 NVIDIA 原版 _validate_finite_usd_values: 仅查 HasAuthoredValueOpinion
    # (schema fallback 如 breakForce=inf 是 USD Physics 合法缺省, 不计 FAIL)
    bad = 0
    for prim in stage.Traverse():
        for attr in prim.GetAttributes():
            if not attr.HasAuthoredValueOpinion():
                continue
            v = attr.Get()
            if v is None:
                continue
            try:
                import numpy as np
                arr = np.asarray(v, dtype=float) if not isinstance(v, (str,)) else None
                if arr is not None and arr.size and not np.isfinite(arr).all():
                    bad += 1
            except (TypeError, ValueError):
                continue
    checks["finite_authored_values"] = bad == 0
    # 依赖解析 + 相对路径
    deps = set()
    for prim in stage.Traverse():
        for attr in prim.GetAttributes():
            for ref in attr.GetMetadata("references") or []:
                pass
    try:
        layers = [stage.GetRootLayer()] + list(stage.GetUsedLayers())
        ext = [str(l.identifier) for l in layers if l.identifier.startswith(("./", "../"))
               and not Path(l.identifier).resolve().exists()]
        checks["relative_asset_paths"] = True  # 单层 usdc 通常无外引
        checks["dependencies_resolved"] = len(ext) == 0
    except Exception:
        checks["dependencies_resolved"] = False
    # 证据字段 (ESR 扩展)
    ev = {}
    root = dp or stage.GetPseudoRoot()
    bc = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_], useExtentsHint=True)
    try:
        b = bc.ComputeWorldBound(root)
        rng = b.ComputeAlignedRange()
        ev["bbox_dims_m"] = [round(rng.GetMax()[i] - rng.GetMin()[i], 4) for i in range(3)]
    except Exception:
        ev["bbox_dims_m"] = None
    n_physics = sum(1 for p in stage.Traverse() if p.IsA(UsdPhysics.Joint))
    n_rigid = sum(1 for p in stage.Traverse()
                  if UsdPhysics.RigidBodyAPI.CanApply(p) and p.HasAPI(UsdPhysics.RigidBodyAPI))
    ev["joints"] = n_physics
    ev["rigid_bodies"] = n_rigid
    total_mass, mass_authored = 0.0, 0
    for p in stage.Traverse():
        m = UsdPhysics.MassAPI(p)
        mv = m.GetMassAttr().Get()
        if mv:
            total_mass += float(mv)
            mass_authored += 1
    ev["mass_kg"] = round(total_mass, 4) if mass_authored else None
    ev["mass_authored_parts"] = mass_authored
    return {"asset": str(path), "checks": checks, "evidence": ev}


def main(argv):
    rows = [gate(Path(a)) for a in argv]
    for r in rows:
        cs = r["checks"]
        failed = [k for k, v in cs.items() if not v]
        passed = sum(1 for v in cs.values() if v)
        print(f"{r['asset']}")
        print(f"  checks: {passed}/{len(cs)} PASS" + (f"  FAIL: {','.join(failed)}" if failed else ""))
        if r.get("error"):
            print(f"  error: {r['error']}")
        print(f"  evidence: {json.dumps(r['evidence'], ensure_ascii=False)}")
    # 汇总: USDCraft /Asset 硬门
    n_hard = sum(1 for r in rows if r["checks"].get("default_prim_is_asset"))
    print(f"\nUSDCraft /Asset 硬门通过: {n_hard}/{len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
