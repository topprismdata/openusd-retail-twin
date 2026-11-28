#!/usr/bin/env python3
"""一键跑通"官方 SimReady 合规包"流水线 (2026-11-28)。

为什么要一键: 这条链跨**两个环境** (bpy 生成 / pxr 官方验证) ✓, 手工串容易漏步骤、
漏环境 -> 把"跑过一次"变成"每次都能跑" ✓。

步骤 (顺序固定 ✓):
  1) 89_asset_self_gate.py            (pxr)  自研闸门 (与生成脚本同一个 validate() ✓)
  2) 13_usd_asset.py                  (bpy)  生成源资产 (三文件 reference 组合 ✓)
  3) 87_asset_thumbnail.py            (bpy)  渲染 256x256 缩略图 (同源几何 ✓)
  4) 86_simready_compliant_package.py (pxr)  单文件合规包 + 官方 validate/package 验收 ✓
  5) 88_asset_consume_check.py        (bpy)  消费端检查 (Blender 真导入 ✓)
  6) 26_publish_artifacts.py          (仓)   发布产物 ✓
  7) 28_doc_consistency_check.py      (仓)   文档闸门 ✓

用法:
  python pipelines/shelf_sdg/90_simready_package_pipeline.py -- [--sku demo_classic] [--skip-publish]
环境变量可覆盖解释器路径:
  ORTHO_PY   仓内训练/渲染环境 (bpy wheel) 的 python ✓
  SRVENV_PY  官方 SimReady 隔离环境 (只装 pxr) 的 python ✓
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
def _default_interpreter(env_name):
    """解释器优先级: 环境变量 > 当前解释器 (带 bpy/numpy 的仓库 venv)。

    刻意不写死任何机器上的绝对路径 —— 那个默认值在本仓之外不存在, 会让脚本
    在别的机器上静默跑起错误的解释器 (或直接 FileNotFoundError)。"""
    v = os.environ.get(env_name, "").strip()
    if v:
        return v
    return sys.executable


REPO_PY = _default_interpreter("ORTHO_PY")
SR_PY = _default_interpreter("SRVENV_PY")
SHIM = os.path.join(BASE, "tools", "blender_shim.py")


def run(label, argv, cwd=BASE):
    print(f"\n=== [{label}] {' '.join(argv[-4:])}")
    t0 = time.time()
    p = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=3600)
    out = (p.stdout or "") + (p.stderr or "")
    tail = [l for l in out.splitlines()
            if l.strip() and not l.startswith("Warning: in _ReportErrors")
            and "ERROR:simready.validate" not in l
            and "RuntimeError: Validation execution unavailable" not in l
            and not l.startswith("  File ") and not l.startswith("    ")]
    for l in tail[-14:]:
        print("   ", l[:170])
    print(f"    -> rc={p.returncode} 用时 {time.time()-t0:.0f}s")
    return p.returncode


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    sku = "demo_classic"
    skip_publish = "--skip-publish" in argv
    for i, a in enumerate(argv):
        if a == "--sku" and i + 1 < len(argv):
            sku = argv[i + 1]

    pkg_dir = os.path.join(BASE, "output", "usd", f"{sku}_pkg")
    packaged = os.path.join(BASE, "output", "usd", "_simready_work", f"{sku}_package",
                             f"{sku}.usda")

    steps = [
        ("1/8 自研闸门 (官方 pxr 环境)",
         [SR_PY, "pipelines/ecommerce/89_asset_self_gate.py", "--", "--sku", sku]),
        ("2/8 生成源资产 (bpy)",
         [REPO_PY, SHIM, "-b", "-P", "pipelines/ecommerce/13_usd_asset.py", "--",
          "--sku", sku]),
        ("3/8 渲染缩略图 (bpy)",
         [REPO_PY, SHIM, "-b", "-P", "pipelines/ecommerce/87_asset_thumbnail.py", "--",
          "--sku", sku, "--stem", f"{sku}.usda", "--out", pkg_dir]),
        ("4/8 组装合规包 + 官方验收 (官方 pxr 环境)",
         [SR_PY, "pipelines/shelf_sdg/86_simready_compliant_package.py", "--", "--sku", sku]),
        ("5/8 消费端检查 (bpy)",
         [REPO_PY, SHIM, "-b", "-P", "pipelines/ecommerce/88_asset_consume_check.py", "--",
          "--usd", packaged]),
    ]
    for label, cmd in steps:
        rc = run(label, cmd)
        if rc != 0:
            print(f"[PIPELINE] 失败于: {label} (rc={rc})")
            return rc

    if not skip_publish:
        rc = run("6/8 发布产物 (仓)",
                 [REPO_PY, "pipelines/shelf_sdg/26_publish_artifacts.py"])
        if rc != 0:
            print("[PIPELINE] 失败于: 6/8 发布产物")
            return rc
        # 交付自洽验收**放在发布之后** ✓: 完整性校验的对象是**发布后的仓内产物** ✓
        #   (放在发布前, 清单还没刷新 ✓ -> 比对的是上一轮的清单 ✓ -> 判据滞后一轮 ✓)
        rc = run("7/8 交付自洽验收 + 统计口径 (官方 pxr 环境)",
                 [SR_PY, "pipelines/shelf_sdg/91_delivery_audit.py"])
        if rc != 0:
            print("[PIPELINE] 失败于: 7/8 交付自洽验收")
            return rc
        rc = run("8/8 文档闸门 (仓)",
                 [REPO_PY, "pipelines/shelf_sdg/28_doc_consistency_check.py"])
        if rc != 0:
            print("[PIPELINE] 失败于: 8/8 文档闸门")
            return rc
    print("\n[PIPELINE] 全链通过 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
