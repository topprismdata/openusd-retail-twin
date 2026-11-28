#!/usr/bin/env python
"""官方 SimReady 打包链对"本仓 USD 资产"到底能补上什么 —— 逐步实测。

背景 (2026-11-27): 官方验证器给本仓资产点了 4 条与"资产包"有关的缺口:
  NP.005  资产目录只允许一个 USD 主文件 (本仓现在 3 个)
  AA.001  依赖引用必须在资产根内 (贴图指到 assets/textures/)
  SR.002  缺 .thumbs/256x256/<主文件>.png
  SR.004  缺 11 个元数据字段
本脚本按"改造成本从低到高"依次试三步, 每步都用**官方验证器**重测, 记录缺口的收敛:

  step1 扁平化: Product.usda + geometry.usdc + materials.usda -> 单个 USD 文件 (pxr UsdUtils)
  step2 官方打包: simready-package 生成资产包 (BOM / 缩略图 / 元数据 sidecar)
  step3 重验:   官方验证器对 step2 的产物再跑一遍

跑法 (只装了 pxr + 官方工具的隔离环境):
    python pipelines/shelf_sdg/85_simready_packaging_effect.py -- \
        --asset output/usd/demo_classic --work output/usd/_simready_work
"""
import json
import os
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "output", "benchmark", "simready_packaging_effect.json")
REPORT = os.path.join(BASE, "output", "benchmark", "simready_vs_self_gate.md")
SELF_GATE = os.path.join(BASE, "output", "benchmark", "asset_self_gate.json")

GAPS_OF_INTEREST = ("NP.005", "AA.001", "SR.002", "SR.004", "RB.001", "SL.001", "VM.PS.001")


def _run_official_validate(asset_path, profiles=None, tag="probe"):
    """调 83 号脚本 (同环境) 对一个资产跑官方验证, 返回 (状态表, requirement 缺口)。"""
    script = os.path.join(BASE, "pipelines", "shelf_sdg", "83_simready_official_validate.py")
    tmp_out = os.path.join(BASE, "output", "benchmark", "_probe_validation.json")
    cmd = [sys.executable, script, "--", "--subjects", f"{tag}:{asset_path}", "--out", tmp_out]
    if profiles:
        cmd += ["--profiles", ",".join(profiles)]
    subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    d = json.load(open(tmp_out, encoding="utf-8"))
    statuses, gaps = {}, []
    for row in d["results"]:
        if row.get("tag") != "probe":
            continue
        statuses[row.get("profile")] = ("PASS" if row.get("passed") else
                                        ("FAIL" if row.get("passed") is False else "UNAVAILABLE"))
        for fname, entry in (row.get("features_summary") or {}).items():
            if not isinstance(entry, dict) or entry.get("passed") is not False:
                continue
            reqs = entry.get("failing requirements") or []
            if isinstance(reqs, str):
                try:
                    reqs = json.loads(reqs.replace("'", '"'))
                except Exception:
                    reqs = [reqs]
            msgs = entry.get("requirement_messages") or {}
            if isinstance(msgs, str):
                try:
                    msgs = json.loads(msgs)
                except Exception:
                    msgs = {}
            for code in reqs:
                m = msgs.get(code) if isinstance(msgs, dict) else ""
                if isinstance(m, list):
                    m = m[0] if m else ""
                gaps.append({"profile": row.get("profile"), "feature": fname,
                             "requirement": str(code), "message": str(m)[:240]})
    return statuses, gaps


def _gaps_of(gaps):
    out = {}
    for g in gaps:
        code = g["requirement"]
        for k in GAPS_OF_INTEREST:
            if code.endswith(k):
                out.setdefault(k, []).append(f"{g['profile']}/{g['feature']}")
    return {k: sorted(set(v)) for k, v in out.items()}


def _gap_messages(gaps):
    """每个关注 requirement 的官方原话 (去重)。"""
    out = {}
    for g in gaps:
        code = g["requirement"]
        for k in GAPS_OF_INTEREST:
            if code.endswith(k):
                out.setdefault(k, set()).add((g.get("message") or "")[:200])
    return {k: sorted(v) for k, v in out.items()}


def step_flatten(asset_dir, work_dir):
    """把多层组合扁平化成一个 USD 文件 (pxr)。

    注意: `UsdUtils.FlattenLayerStack(stage)` 的签名是 (stage, tag) —— 它把 layer stack
    压进**当前 stage 的根层**, 不是"导出到某个 layer"; 所以要再 Export 一次。
    """
    from pxr import Usd, UsdUtils
    src = os.path.join(asset_dir, "Product.usda")
    stage = Usd.Stage.Open(src)
    out_dir = os.path.join(work_dir, "flattened")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "Product.usda")
    UsdUtils.FlattenLayerStack(stage)
    stage.GetRootLayer().Export(out_path)
    return out_path


def step_selfcontained(asset_dir, work_dir):
    """做一个**自包含**的单文件资产: 展平引用 + 把贴图拷进资产根并改写路径。

    官方 NP.005 要求资产目录里只有一个 USD 主文件; AA.001 要求依赖引用都在资产根内
    (我们原来的贴图指到 ../../../assets/textures/)。
    """
    import shutil as _sh
    from pxr import Usd, Sdf

    src = os.path.join(asset_dir, "Product.usda")
    stage = Usd.Stage.Open(src)
    stage.Flatten()                       # 解析所有 composition arc (含 references) -> 根层
    out_dir = os.path.join(work_dir, "selfcontained")
    os.makedirs(os.path.join(out_dir, "textures"), exist_ok=True)

    moved = []
    for prim in stage.Traverse():
        for attr in prim.GetAttributes():
            v = attr.Get()
            if not isinstance(v, Sdf.AssetPath) or not v.path:
                continue
            ap = v.path
            src_path = ap if os.path.isabs(ap) else os.path.normpath(
                os.path.join(asset_dir, ap))
            if not os.path.exists(src_path):
                continue
            base = os.path.basename(src_path)
            dst = os.path.join(out_dir, "textures", base)
            if not os.path.exists(dst):
                _sh.copy2(src_path, dst)
            attr.Set(Sdf.AssetPath("./textures/" + base))
            moved.append({"from": ap, "to": "./textures/" + base})

    out_usd = os.path.join(out_dir, "Product.usda")
    stage.GetRootLayer().Export(out_usd)

    # SR.004 sidecar: <usd_stem>.json (字段类型见官方 CAP033 文档 ✓)
    #   qcode=Wikidata Q-Code / rigid_body_count=非负整数 / asset_extents=米制 float3 / mass=千克
    sidecar = {
        "author": "TopPrism",
        "asset_name": "demo_classic",
        "asset_type": "packaging",
        "asset_license": "CC-BY-4.0",
        "category": "beverage/carton/aseptic-brick",
        "source_file": "Product.usda",
        "usd_date_generated": "2026-11-27",
        "qcode": "Q1139617",
        "rigid_body_count": 1,
        "asset_extents": [0.048, 0.038, 0.113],
        "mass": 0.32,
    }
    with open(os.path.join(out_dir, "Product.usda.json"), "w", encoding="utf-8") as f:
        json.dump(sidecar, f, ensure_ascii=False, indent=2)
    return out_usd, moved


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    asset_dir = argv[argv.index("--asset") + 1] if "--asset" in argv else "output/usd/demo_classic"
    work_dir = argv[argv.index("--work") + 1] if "--work" in argv else "output/usd/_simready_work"
    asset_dir = os.path.join(BASE, asset_dir) if not os.path.isabs(asset_dir) else asset_dir
    work_dir = os.path.join(BASE, work_dir) if not os.path.isabs(work_dir) else work_dir
    os.makedirs(work_dir, exist_ok=True)

    report = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "script": "pipelines/shelf_sdg/85_simready_packaging_effect.py",
              "asset_dir": os.path.relpath(asset_dir, BASE).replace("\\", "/"),
              "steps": [], "not_done": []}

    # ---- step0: 原始资产 ----
    st, gaps = _run_official_validate(os.path.join(asset_dir, "Product.usda"))
    report["steps"].append({"step": "step0_original", "asset": "Product.usda",
                            "statuses": st, "gaps_of_interest": _gaps_of(gaps),
                            "gap_messages": _gap_messages(gaps),
                            "n_gaps": len(gaps)})
    print("[step0] 原始资产:", {k: v for k, v in st.items() if k in ("Package-Candidate", "Material", "Robotics-Prop")})
    print("[step0] 关注缺口:", list(_gaps_of(gaps)))

    # ---- step1: 扁平化 ----
    try:
        flat = step_flatten(asset_dir, work_dir)
        st1, gaps1 = _run_official_validate(flat)
        report["steps"].append({"step": "step1_flattened", "asset": os.path.relpath(flat, BASE).replace("\\", "/"),
                                "statuses": st1, "gaps_of_interest": _gaps_of(gaps1),
                                "gap_messages": _gap_messages(gaps1), "n_gaps": len(gaps1)})
        print("[step1] 扁平化后:", {k: v for k, v in st1.items() if k in ("Package-Candidate", "Material", "Robotics-Prop")})
        print("[step1] 关注缺口:", list(_gaps_of(gaps1)))
    except Exception as e:
        report["steps"].append({"step": "step1_flattened", "error": f"{type(e).__name__}: {e}"})
        report["not_done"].append(f"扁平化失败: {type(e).__name__}: {e}")
        print("[step1] 失败:", e)

    # ---- step1b: 自包含单文件资产 (展平 + 贴图进根) ----
    try:
        sc_usd, moved = step_selfcontained(asset_dir, work_dir)
        st1b, gaps1b = _run_official_validate(sc_usd)
        report["steps"].append({"step": "step1b_selfcontained", "asset": os.path.relpath(sc_usd, BASE).replace("\\", "/"),
                                "textures_moved": moved, "statuses": st1b,
                                "gaps_of_interest": _gaps_of(gaps1b),
                                "gap_messages": _gap_messages(gaps1b), "n_gaps": len(gaps1b)})
        print("[step1b] 自包含单文件后:", {k: v for k, v in st1b.items() if k in ("Package-Candidate", "Material", "Robotics-Prop")})
        print("[step1b] 关注缺口:", list(_gaps_of(gaps1b)))
    except Exception as e:
        report["steps"].append({"step": "step1b_selfcontained", "error": f"{type(e).__name__}: {e}"})
        report["not_done"].append(f"自包含资产构建失败: {type(e).__name__}: {e}")
        print("[step1b] 失败:", e)

    # ---- step2: 官方打包 ----
    # 官方 CLI 在**隔离 venv**里, 不在 PATH -> 直接在 sys.executable 旁边找
    pkg_exe = shutil.which("simready-package") or shutil.which("simready-package.exe")
    if not pkg_exe:
        cand = os.path.join(os.path.dirname(sys.executable), "simready-package.exe")
        pkg_exe = cand if os.path.exists(cand) else None
    sc_dir = os.path.join(work_dir, "selfcontained")
    if not pkg_exe:
        report["not_done"].append("simready-package 未安装 -> 跳过官方打包步")
        print("[step2] simready-package 不在 PATH, 跳过")
    elif not os.path.isdir(sc_dir):
        report["not_done"].append("自包含资产未构建 -> 跳过官方打包步")
        print("[step2] 没有自包含资产, 跳过")
    else:
        pkg_out = os.path.join(work_dir, "package")
        cmds = [[pkg_exe, "package", sc_dir, "--root-usd", "Product.usda",
                 "--name", "demo_classic", "--license", "CC-BY-4.0", "--out", pkg_out]]
        logs = []
        failed = None
        for cmd in cmds:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
            logs.append({"cmd": " ".join(cmd), "rc": r.returncode,
                         "out_tail": (r.stdout or "")[-1200:], "err_tail": (r.stderr or "")[-1200:]})
            if r.returncode != 0:
                failed = logs[-1]
                break
        report["steps"].append({"step": "step2_official_package", "commands": logs,
                                "out": os.path.relpath(pkg_out, BASE) if os.path.isdir(pkg_out) else None})
        if failed:
            report["not_done"].append("官方打包失败 (见 step2 commands)")
            print(f"[step2] 失败于: {failed['cmd']}")
            print((failed.get("err_tail") or "")[-800:])
        else:
            files = []
            for root, _d, fs in os.walk(pkg_out):
                for f in fs:
                    files.append(os.path.relpath(os.path.join(root, f), pkg_out).replace("\\", "/"))
            report["steps"][-1]["files"] = sorted(files)
            main_usd = None
            for f in sorted(files):
                if f.endswith((".usd", ".usda", ".usdc")):
                    main_usd = os.path.join(pkg_out, f.replace("/", os.sep))
                    break
            print("[step2] 打包产物:", sorted(files)[:12])
            if main_usd:
                st2, gaps2 = _run_official_validate(main_usd)
                report["steps"].append({"step": "step3_revalidate_packaged", "statuses": st2,
                                        "gaps_of_interest": _gaps_of(gaps2),
                                        "gap_messages": _gap_messages(gaps2), "n_gaps": len(gaps2)})
                print("[step3] 打包后重验:", {k: v for k, v in st2.items() if k in ("Package-Candidate", "Material", "Robotics-Prop")})
                print("[step3] 关注缺口:", list(_gaps_of(gaps2)))

    # ---- 对照实验: 官方打包链本身可用吗 (拿 NVIDIA 样例) ----
    control_packaging(report)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[PKG-EFFECT] -> {OUT}")
    return 0


def control_packaging(report):
    """对照实验: 官方打包链本身能不能用?

    拿 NVIDIA USDCraft 的样例资产 (已经带 .thumbs / .metadata / BOM) 跑官方打包器:
    通过 -> 说明"我们资产打包失败"是**我们资产不合规**, 不是工具链不可用 ✓。
    """
    pkg_exe = shutil.which("simready-package") or shutil.which("simready-package.exe")
    if not pkg_exe:
        cand = os.path.join(os.path.dirname(sys.executable), "simready-package.exe")
        pkg_exe = cand if os.path.exists(cand) else None
    if not pkg_exe:
        return
    hits = []
    for root, _d, files in os.walk(os.path.join(BASE, "assets", "usdcraft")):
        if "model.usdc" in files and os.path.isdir(os.path.join(root, ".thumbs")):
            hits.append(root)
            if len(hits) >= 1:
                break
    if not hits:
        report["not_done"].append("没找到带 .thumbs 的 USDCraft 样例 -> 对照实验跳过")
        return
    src = hits[0]
    out = os.path.join(BASE, "output", "usd", "_simready_work", "control_package")
    if os.path.isdir(out):
        shutil.rmtree(out)
    r = subprocess.run([pkg_exe, "package", src, "--root-usd", "model.usdc",
                        "--name", "usdc_demo", "--license", "Apache-2.0", "--out", out],
                       capture_output=True, text=True, timeout=1800)
    files = []
    if os.path.isdir(out):
        for root, _d, fs in os.walk(out):
            for f in fs:
                files.append(os.path.relpath(os.path.join(root, f), out).replace("\\", "/"))
    report["steps"].append({"step": "control_official_package_nvidia_asset", "src": os.path.relpath(src, BASE).replace("\\", "/"),
                            "rc": r.returncode, "out_tail": (r.stdout or "")[-800:],
                            "package_files": sorted(files)})
    print(f"[control] 官方打包 NVIDIA 样例: rc={r.returncode}, 产物 {len(files)} 个文件")
    for line in (r.stdout or "").strip().splitlines()[-3:]:
        print("   ", line)


if __name__ == "__main__":
    sys.exit(main())
