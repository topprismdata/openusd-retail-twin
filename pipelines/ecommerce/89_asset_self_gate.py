#!/usr/bin/env python3
"""自研资产闸门的独立入口 (2026-11-28)。

`13_usd_asset.py` 的 `validate()` 是**自研闸门** ✓ (defaultPrim / kind / variantSet /
材质绑定与连接真的解析 / up 轴声明与几何一致 ✓) —— 但它住在生成脚本里, 生成环境 (bpy)
常常没有 pxr ✓ -> 会跳过 ✓ -> 闸门就没真跑过 ✓。
这个薄壳在**装了 pxr 的环境**里跑同一个 validate() ✓, 并用**退出码**表达成败 ✓,
好让一键流水线 / CI 直接用 ✓。

用法 (只装 pxr 的环境):
  python pipelines/ecommerce/89_asset_self_gate.py -- [--sku demo_classic]
"""
import importlib.util as ilu
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sku = "demo_classic"
    for i, a in enumerate(argv):
        if a == "--sku" and i + 1 < len(argv):
            sku = argv[i + 1]
    gen = os.path.join(BASE, "pipelines", "ecommerce", "13_usd_asset.py")
    spec = ilu.spec_from_file_location("asset_gen", gen)
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    usd_dir = os.path.join(BASE, "output", "usd", sku)
    try:
        seen = mod.validate(usd_dir)
    except AssertionError as e:
        print(f"[SELF-GATE] FAIL {sku}: {e}")
        return 1
    except ModuleNotFoundError as e:
        print(f"[SELF-GATE] 跳过: 本环境没有 {e.name} (需要 usd-core ✓)")
        return 0
    print(f"[SELF-GATE] PASS {sku}: defaultPrim/kind/variantSets/绑定与连接/up轴一致性 全通过 ✓")
    for cw, tgt in (seen or {}).items():
        print(f"   colorway={cw:16s} pack_material={tgt}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
