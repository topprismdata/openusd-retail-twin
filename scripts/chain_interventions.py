#!/usr/bin/env python
"""串行实验链 (2026-11-25)。

背景: 这台机器上 `nohup bash xxx.sh` 启动的是 **WSL 的 /bin/bash** (挂载点 /mnt/c),
`/c/...` 与 `C:/...` 都进不去 -> 之前的 shell 版链一启动就 cd 失败。所以链用 Python 写
(Windows 解释器, 路径无歧义)。

步骤 (严格串行 —— 并发压显存/内存正是上次 batch 被静默降级的原因):
    1. 等 52/54/55 号三个探针全部退出;
    2. 跑 PASTA 臂 (52 号, sigma 取 54 号的标定);
    3. 跑噪声底复现 (21 号, --strict-protocol: 内存不够就拒跑, 不静默降级)。

用法:
    python scripts/chain_interventions.py
"""
import os
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 解释器: 环境变量 ORTHO_PY 优先, 否则用当前解释器 (带 bpy/numpy 的仓库 venv)
PY = os.environ.get("ORTHO_PY", "").strip() or sys.executable
BENCH = os.path.join(REPO, "output", "benchmark")
LOG = os.path.join(BENCH, "chain_interventions.log")
MARKS = ("52_photorealism", "54_spectral", "55_input_probe")


def log(m):
    line = f"[CHAIN {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def running_probes():
    try:
        import psutil
    except Exception:
        return []
    out = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
        except Exception:
            continue
        if any(m in cl for m in MARKS) and "chain_interventions" not in cl:
            out.append((p.info["pid"], cl[:120]))
    return out


def wait_probes(limit_min=240):
    t0 = time.time()
    while True:
        procs = running_probes()
        if not procs:
            return True
        if (time.time() - t0) / 60 > limit_min:
            log(f"⚠️ 等待超过 {limit_min} 分钟, 仍有 {[p[0] for p in procs]}, 继续等")
            limit_min += 60
        time.sleep(30)


def run(cmd, logfile):
    log("RUN " + " ".join(cmd[-6:]))
    with open(logfile, "a", encoding="utf-8") as fh:
        r = subprocess.run(cmd, cwd=REPO, stdout=fh, stderr=subprocess.STDOUT)
    log(f"退出码 {r.returncode} -> {os.path.basename(logfile)}")
    return r.returncode


def main():
    log("=== 链开始 ===")
    log(f"当前在跑的探针: {running_probes()}")
    wait_probes()
    log("前序探针已全部退出")

    calib = os.path.join(BENCH, "syn2real_pasta_calib.json")
    t0 = time.time()
    while not os.path.exists(calib) and (time.time() - t0) / 60 < 45:
        time.sleep(30)
    log(f"sigma 标定: {'有 ' + open(calib, encoding='utf-8').read()[:120] if os.path.exists(calib) else '缺失, 用默认值'}")

    # 2026-11-25: **PASTA 臂被取消** —— 54 号的频谱分解证伪了它的前提:
    #   高频带总差距 +17.19 dB 里, 内容结构贡献 +18.24 dB, 而"成像质感差距"只有
    #   **-1.05 dB** (合成图在抹掉内容结构后, 高频能量与真实照片**持平甚至略高**)。
    #   也就是说合成图**不缺**照片颗粒 -> 往振幅谱里加噪声只会加真实图也没有的东西。
    #   保留标定产物 (它是"成像质感差距≈0"这条证据的一部分), 但不花 GPU 去训练这一臂。
    log("PASTA 臂: 前提已被 54 号频谱分解证伪 (成像质感差距 -1.05 dB) -> 取消训练, "
        "GPU 让给噪声底复现")

    run([PY, os.path.join(REPO, "pipelines/shelf_sdg/21_annotation_budget.py"),
         "--fracs", "0.05", "--synth", "0", "--seed", "42",
         "--run-tag", "replicate_strict_s42", "--strict-protocol"],
        os.path.join(BENCH, "replicate_strict.log"))
    log("=== 链结束 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
