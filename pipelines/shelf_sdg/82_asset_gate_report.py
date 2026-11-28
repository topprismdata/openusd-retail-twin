#!/usr/bin/env python
"""把自研资产级闸 (12_asset_spec_gate.py) 的 5 项检查落成 JSON 产物。

用途: 与 **官方** SimReady 验证器 (83 号脚本, 在官方工具的隔离环境里跑) 做
逐项对照 -> 84 号脚本出"官方 vs 自研"的差异报告。

与 12 号脚本的关系: 检查项与判定逻辑 **完全复用** 12 号的函数 (不复制实现),
所以两份产物必须在同一资产上给出同一批 verdict; 28 号闸门会核这条一致性。

用法: python pipelines/shelf_sdg/82_asset_gate_report.py -- --sku demo_classic
"""
import importlib.util as ilu
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "output", "benchmark", "asset_self_gate.json")


def _load(path, name):
    spec = ilu.spec_from_file_location(name, path)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sku = argv[argv.index("--sku") + 1] if "--sku" in argv else "demo_classic"

    import bpy  # noqa: F401  (12 号脚本同样依赖 bpy)

    gate = _load(os.path.join(BASE, "pipelines", "ecommerce", "12_asset_spec_gate.py"), "self_gate")
    comp = _load(os.path.join(BASE, "pipelines", "ecommerce", "01_comfy_usd_compositor.py"), "comp")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    pack, cap, lip = comp.build_carton_twin(sku)
    bpy.context.view_layer.update()
    spec_dims = (comp.PACK_W, comp.PACK_D, comp.PACK_H)

    glb = os.path.join(BASE, "output", "ar_models", f"_gate_{sku}.glb")
    os.makedirs(os.path.dirname(glb), exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    for o in (pack, cap, lip):
        if o:
            o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB", use_selection=True,
                              export_materials="EXPORT", export_image_format="WEBP")

    checks = {
        "origin_units": gate.check_origin_dims(pack, spec_dims),
        "topology": gate.check_topology(pack),
        "uv_01": gate.check_uv(pack),
        "uv_atlas": gate.check_uv_atlas(os.path.join(BASE, "assets", "textures"), sku, comp.UV_REGIONS),
        "export_targets": gate.check_export(glb),
    }
    overall = "FAIL" if any(v[0] == "FAIL" for v in checks.values()) else "PASS"

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "pipelines/shelf_sdg/82_asset_gate_report.py",
        "reuses": "pipelines/ecommerce/12_asset_spec_gate.py",
        "sku": sku,
        "spec_dims_mm": [round(v * 1000, 1) for v in spec_dims],
        "overall": overall,
        "checks": {k: {"verdict": v[0], "detail": v[1]} for k, v in checks.items()},
        "note": "自研闸门检查的是 GLB/网格侧 (Khronos 发布目标), 不是 USD stage; 官方 SimReady 验的是 USD 资产 -> 两者覆盖面不同, 详见 84 号差异报告",
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.remove(glb)
    print(f"[SELF-GATE-REPORT] {overall} {sku} -> {OUT}")
    for k, v in checks.items():
        print(f"  {k:16s} {v[0]:4s}  {v[1]}")


if __name__ == "__main__":
    main()
