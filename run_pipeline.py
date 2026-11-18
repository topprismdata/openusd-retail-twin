#!/usr/bin/env python3
"""
run_pipeline.py - 全管线一键编排器 (fail-fast, 分阶段计时, 闸门退出码透传)

用法:
  python3 run_pipeline.py --draft   # 草档回归: 单平台/低采样/qa-only (~5min)
  python3 run_pipeline.py --full    # 全量: 四平台/20图SDG/四阶段板 (~20min+)
  python3 run_pipeline.py --draft --keep-going   # 失败不中断, 汇总所有阶段
  python3 run_pipeline.py --draft --only bootstrap,ecom   # 只跑指定阶段

阶段:
  bootstrap  程序化贴图自举 (PIL, ~2s)
  ecom       电商套图渲染 (Blender/Cycles Metal-RT)
  gate_ecom  套图排版五闸 (PIL, 退出码 0=PASS)
  sdg        货架合成数据+巡检仪表盘 (Blender)
  topprism   Topprism 虚拟产品线: 标签生成 + 杯体渲染 (PIL + Blender)
  pack       刀版资产线: spec 加载 + 资产五闸 (qa-only 跳渲染)
  report     汇总 QA 报告 JSON + 阶段账目 -> output/pipeline_runs/

纪律: Blender 阶段严格串行 (Metal 单实例); CWD 类脚本统一以仓库根为 cwd。
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BLENDER = os.environ.get("BLENDER_BIN", "/Applications/Blender.app/Contents/MacOS/Blender")
RUN_DIR = ROOT / "output" / "pipeline_runs"


def stage(name):
    def deco(fn):
        fn.stage_name = name
        return fn
    return deco


@stage("bootstrap")
def st_bootstrap(draft):
    return [sys.executable, "pipelines/bootstrap/00_bootstrap_textures.py"], ROOT


@stage("ecom")
def st_ecom(draft):
    cmd = [BLENDER, "-b", "-P", "pipelines/ecommerce/01_comfy_usd_compositor.py", "--",
           "--sku", "demo_organic", "--scene", "grassland"]
    # SKU 存在性断言 (GPT R3: 禁止未知 SKU 以空配置静默运行)
    import importlib.util as _ilu
    _sp = _ilu.spec_from_file_location("boot", ROOT / "pipelines/bootstrap/00_bootstrap_textures.py")
    _bm = _ilu.module_from_spec(_sp); _sp.loader.exec_module(_bm)
    assert "demo_organic" in _bm.SKU_PROFILES, "SKU demo_organic 不在 00.SKU_PROFILES"
    if draft:
        cmd += ["--only", "01_JD_WhiteBG_800x800"]
    return cmd, ROOT


@stage("gate_ecom")
def st_gate_ecom(draft):
    img = ROOT / "output/multi_platform/01_JD_WhiteBG_800x800.png"
    if not img.exists():
        raise FileNotFoundError(f"上阶段产物缺失: {img}")
    return [sys.executable, "pipelines/ecommerce/10_layout_qa_gate.py", str(img)], ROOT


@stage("sdg")
def st_sdg(draft):
    n, s = ("4", "32") if draft else ("20", "64")
    return [BLENDER, "-b", "-P", "pipelines/shelf_sdg/02_shelf_sdg_inspector.py", "--",
            "--num-images", n, "--samples", s], ROOT


@stage("train")
def st_train(draft):
    """YOLO 臂: 02 的 SDG 数据集 -> YOLOv11n MPS 微调 + 验证集首检.
    内存门 (记忆硬约束): <10GB 拒跑; <18GB 设 MPS watermark 0.5."""
    try:
        subprocess.run([sys.executable, "-c", "import ultralytics"], capture_output=True, timeout=60, check=True)
    except Exception:
        STAGE_LOG.append({"stage": "train", "exit": 0, "sec": 0.0, "status": "SKIPPED",
                          "note": "ultralytics 未安装 (pip install ultralytics 后重跑)"})
        print("⏭️  [train] SKIPPED: ultralytics 未安装")
        return (None, None)
    free_gb = _avail_mem_gb()
    env = dict(os.environ)
    note = f"可用内存 {free_gb:.0f}GB"
    if free_gb < 10:
        STAGE_LOG.append({"stage": "train", "exit": 0, "sec": 0.0, "status": "SKIPPED",
                          "note": note + " <10GB, 内存门拒跑"})
        print(f"⏭️  [train] SKIPPED: {note} <10GB (内存硬约束)")
        return (None, None)
    if free_gb < 18:
        env["PYTORCH_MPS_HIGH_WATERMARK_RATIO"] = "0.5"
        note += " <18GB, 已限 MPS watermark 0.5"
    epochs = "2" if draft else "10"
    print(f"ℹ️  [train] {note}; epochs={epochs} (SDG 数据集: output/sdg_shelf)")
    return ([sys.executable, "pipelines/shelf_sdg/05_train_yolo_mps.py", "--epochs", epochs], ROOT, env)


def _avail_mem_gb():
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout
        page = int(out.split("page size of")[1].split()[0])
        free = inactive = spec = 0
        for line in out.splitlines():
            if line.startswith("Pages free"):
                free = int(line.split(":")[1].strip().rstrip("."))
            elif line.startswith("Pages inactive"):
                inactive = int(line.split(":")[1].strip().rstrip("."))
            elif line.startswith("Pages speculative"):
                spec = int(line.split(":")[1].strip().rstrip("."))
        return (free + inactive + spec) * page / 2**30
    except Exception:
        return 999.0  # 无法探测时不阻拦


@stage("topprism")
def st_topprism(draft):
    r = []
    r.append(([sys.executable, "pipelines/topprism_virtual/32_topprism_yogurt_label.py"], ROOT))
    if not draft:
        r.append(([BLENDER, "-b", "-P", "pipelines/topprism_virtual/33_topprism_yogurt_cup.py"], ROOT))
    return r


@stage("pack")
def st_pack(draft):
    cmd = [BLENDER, "-b", "-P", "pipelines/pack_dieline/30_pack_asset_line.py", "--",
           "--spec", "specs/pack_458.json"]
    if draft:
        cmd += ["--qa-only"]
    return cmd, ROOT


@stage("report")
def st_report(draft):
    """汇总阶段账目与最近一次 QA 报告 -> output/pipeline_runs/summary.json"""
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    qa = ROOT / "output/qa_gate_report.json"
    summary = {"stages": STAGE_LOG, "qa_gate_report": None}
    if qa.exists():
        try:
            summary["qa_gate_report"] = json.loads(qa.read_text())
        except Exception as e:
            summary["qa_gate_report"] = {"error": str(e)}
    out = RUN_DIR / f"summary_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"[report] 账目已写 {out}")
    return None, None


STAGE_LOG = []


def run_one(tag, cmd, cwd, log_path, timeout, env=None):
    t0 = time.time()
    print(f"\n▶ [{tag}] {' '.join(str(c) for c in cmd[:6])}...")
    with open(log_path, "w") as lf:
        p = subprocess.run(cmd, cwd=str(cwd), stdout=lf, stderr=subprocess.STDOUT,
                           timeout=timeout, env=env)
    dt = time.time() - t0
    ok = p.returncode == 0
    STAGE_LOG.append({"stage": tag, "exit": p.returncode, "sec": round(dt, 1)})
    print(f"{'✅' if ok else '❌'} [{tag}] exit={p.returncode} {dt:.1f}s  (log: {log_path})")
    if not ok:
        tail = Path(log_path).read_text(errors="replace").strip().splitlines()[-5:]
        for line in tail:
            print(f"    | {line}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", action="store_true", help="草档 (默认 false=全量)")
    ap.add_argument("--with-train", action="store_true", help="接上 YOLO 臂 (02 数据集→05 微调, 内存门+ultralytics 预检)")
    ap.add_argument("--keep-going", action="store_true")
    ap.add_argument("--only", default="", help="逗号分隔阶段名过滤")
    ap.add_argument("--stage-timeout", type=int, default=900)
    a = ap.parse_args()
    if not Path(BLENDER).exists():
        sys.exit(f"Blender 不存在: {BLENDER} (可 env BLENDER_BIN 覆盖)")

    stages = {fn.stage_name: fn for fn in
              [st_bootstrap, st_ecom, st_gate_ecom, st_sdg, st_train, st_topprism, st_pack, st_report]}
    order = ["bootstrap", "ecom", "gate_ecom", "sdg", "train", "topprism", "pack", "report"]
    if not a.with_train:
        order.remove("train")
    if a.only:
        order = [s for s in order if s in a.only.split(",")]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    failed = []
    for name in order:
        fn = stages[name]
        res = fn(a.draft)
        # 归一: (cmd,cwd[,env]) 元组 -> 单元素; list[(cmd,cwd),..] -> 多元素; (None,None) -> 已跳过/纯汇总
        if res and res[0] is None:
            continue
        units = [res] if isinstance(res, tuple) else res
        for i, unit in enumerate(units):
            cmd, cwd = unit[0], unit[1]
            env = unit[2] if len(unit) > 2 else None
            tag = name if len(units) == 1 else f"{name}.{i}"
            timeout = max(a.stage_timeout, 3600) if name == "train" else a.stage_timeout
            ok = run_one(tag, cmd, cwd, RUN_DIR / f"{tag.replace('.', '_')}.log", timeout, env)
            if not ok:
                failed.append(tag)
                if not a.keep_going:
                    print(f"\n⛔ fail-fast 于 [{tag}] — 后续阶段中止 (--keep-going 可跑完)")
                    st_report(a.draft)
                    sys.exit(1)

    print("\n" + "=" * 52)
    for e in STAGE_LOG:
        mark = {"SKIPPED": "⏭️"}.get(e.get("status"), "✅" if e["exit"] == 0 else "❌")
        note = f"  ({e['note']})" if e.get("note") else ""
        print(f"  {mark} {e['stage']:<14} exit={e['exit']}  {e['sec']}s{note}")
    print("=" * 52)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
