#!/usr/bin/env python3
"""四臂 seed45 链结束后自动接着跑: R3 域对齐臂的协议对齐复跑 -> 汇总 -> 计数指标。

为什么要串成一条: 四臂链要 ~3.5 h (GPU), R3pm 渲染还要 ~2-3 h (GPU) —— 两者不能并行
(4 GB 显存的 1050 Ti, YOLO 训练 + Cycles 同时跑会 OOM)。串起来就不需要人盯着。

用法 (Windows):
    python pipelines/shelf_sdg/39_after_seed45_pipeline.py
日志: output/benchmark/chain_after_seed45.log
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PY = sys.executable
LOG = os.path.join(BENCH, "chain_after_seed45.log")

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
ENV.setdefault("BLENDER_PYTHON", os.path.join(os.path.expanduser("~"), "projects", "venvbpy", "Scripts", "python.exe"))
# 让 blender_command() 走 bpy wheel (5.2.4, 与现有产物同版本) —— 不走 BLENDER_BIN
ENV.pop("BLENDER_BIN", None)

WAIT_ARTIFACT = os.path.join(BENCH, "sku110k_r1_s45.json")


def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8", errors="ignore") as fh:
        fh.write(line + "\n")


def run(label, args, timeout=28800):
    log(f"=== {label} :: {' '.join(args[1:])}")
    t0 = time.time()
    r = subprocess.run(args, cwd=BASE, env=ENV, timeout=timeout)
    log(f"--- {label} 退出码 {r.returncode} ({(time.time() - t0) / 60:.1f} min)")
    return r.returncode


def verify_control_recipe():
    """渲一张**默认参数**的图, 与对照集第 0 张的标签逐字比对。

    目的: 确认现在用的那套合成集 (对照组) 确实是 02 的默认配方
    (cam_mult 1.0 / lens 28 / misalign 0.10 / bays 1) —— 它的产物里没记这些参数
    (dataset_summary 是 2026-11-23 才补的), 不核验就只能靠推断。
    比**标签**而不是像素: 渲染有 GPU 采样噪声 (像素可能差 ≤1/255), 但布局与框是确定的。
    """
    probe = os.path.join(BENCH, "sdg_ctrl_probe")
    sys.path.insert(0, BASE)
    from pipelines.common.runtime_env import blender_command
    cmd = blender_command() + ["-b", "-P",
                                os.path.join(BASE, "pipelines/shelf_sdg/02_shelf_sdg_inspector.py"), "--",
                                "--num-images", "1", "--seed", "42", "--val-ratio", "0.2",
                                "--images-per-scene", "4", "--split-mode", "scene",
                                "--samples", "64", "--out", probe]
    log("=== 对照配方核验: 渲 1 张默认参数的图")
    with open(os.path.join(BENCH, "chain_steps", "ctrl_probe.log"), "w",
              encoding="utf-8", errors="ignore") as fh:
        r = subprocess.run(cmd, cwd=BASE, env=ENV, stdout=fh, stderr=subprocess.STDOUT,
                           timeout=3600)
    if r.returncode != 0:
        log(f"    探针渲染失败 (退出码 {r.returncode}) -> 对照配方**未核验**")
        return
    # 探针渲的是 scene 0 的第 0 张; 对照集的第 0 张也是 scene 0 第 0 张 (同 base_seed)
    for split in ("train", "val"):
        a = os.path.join(probe, "labels", split, "img_000.txt")
        b = os.path.join(BASE, "output", "sdg_shelf", "labels", split, "img_000.txt")
        if not (os.path.exists(a) and os.path.exists(b)):
            continue
        la = open(a, encoding="utf-8").read().split("\n")
        lb = open(b, encoding="utf-8").read().split("\n")
        same = la == lb
        log(f"    {split}/img_000 标签比对: {'一致 ✅' if same else '不一致 ❌'} "
            f"(探针 {len([x for x in la if x.strip()])} 行 / 对照 "
            f"{len([x for x in lb if x.strip()])} 行)")
        if not same:
            log("    !! 对照集的配方与 02 的默认参数不同 -> R3pm 的'只差一个变量'前提要重新审视")
    with open(os.path.join(BENCH, "control_recipe_verification.json"), "w",
              encoding="utf-8") as fh:
        import json
        json.dump({"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                   "control_set": "output/sdg_shelf",
                   "probe_dir": os.path.relpath(probe, BASE).replace("\\", "/"),
                   "note": "对照集 img_000 的标签与'默认参数重渲'逐字比对的结果见日志"},
                  fh, ensure_ascii=False, indent=2)


def main():
    os.makedirs(BENCH, exist_ok=True)
    log("等四臂 seed45 链 (等 output/benchmark/sku110k_r1_s45.json)")
    waited = 0
    while not os.path.exists(WAIT_ARTIFACT):
        time.sleep(60)
        waited += 1
        if waited % 10 == 0:
            log(f"    还在等 ({waited} min)")
    time.sleep(90)   # 让链自己跑完 36 号汇总
    log("链结束 -> 开始 R3pm")

    rc = run("R3pm 渲染", [PY, "pipelines/shelf_sdg/38_r3_protocol_matched.py", "--stage", "render"])
    if rc != 0:
        log(f"渲染失败 (退出码 {rc}) -> 跳过训练/汇总; 日志 output/benchmark/chain_steps/r3pm_render.log")
        raise SystemExit(rc)

    # 对照组的配方核验: 当前那套合成集 (output/sdg_shelf) 的产物里**没记**相机/错位率/bays
    # (2026-11-23 之前 dataset_summary 不写这些), 所以"对照组用的是 02 的默认参数"是推断。
    # 这里渲**一张**默认参数的图, 跟对照集的第 0 张**标签**逐字比对 ——
    # 标签一致 = 对照组确实是默认参数 (布局种子与图序相同, 差异只可能来自配方参数)。
    verify_control_recipe()

    run("R3pm 训练", [PY, "pipelines/shelf_sdg/38_r3_protocol_matched.py",
                      "--stage", "train", "--seeds", "42,43,44,45"])
    run("汇总 36 (含 r3pm 组与 R3pm−R1 配对)",
        [PY, "pipelines/shelf_sdg/36_fourarm_seed_variance.py"], timeout=600)
    run("汇总 38 (域差距因子对比)",
        [PY, "pipelines/shelf_sdg/38_r3_protocol_matched.py", "--stage", "summarize",
         "--seeds", "42,43,44,45"], timeout=1800)

    log("=== 四臂计数指标 (seed 45 权重, conf 0.35, 600 张随机抽样)")
    for arm in ("r0", "r1", "r2"):
        w = os.path.join(BENCH, f"runs_{arm}_s45", "train", "weights", "best.pt")
        if os.path.exists(w):
            run(f"count {arm}", [PY, "pipelines/shelf_sdg/17_count_eval.py",
                                 "--arm", arm, "--weights", w], timeout=3600)
        else:
            log(f"跳过 count {arm} (权重不存在: {w})")
    log("=== 全流程结束 ===")


if __name__ == "__main__":
    main()
