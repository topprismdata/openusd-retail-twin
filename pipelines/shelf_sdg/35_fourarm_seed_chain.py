#!/usr/bin/env python3
"""已发布四臂 (r0/r1/r2) 的多种子复跑链 (2026-11-22 晚)。

背景: 四臂 (R0 真实 / R1 纯合成 / R2 真实+合成 / R3-full) 是 2026-11-08 的产物, 每臂**只跑过一次**
(seed 42)。于是全篇还剩一处用单次运行支撑的结论:
    "R2 真实+合成 vs R0 真实: Δ −1.77pp ≤ 2pp, **未检出差异**"
—— 没有方差, 就不知道这个 −1.77pp 里有多少是训练噪声, "未检出差异"到底是"确实接近"还是
"单次运行的运气"。

本链把 r0/r2 各跑 seed 43/44 (数据、协议、权重选择口径全不变, 只换训练 seed),
r1 (纯合成, 只有 160 张图, 很便宜) 也顺带跑两个 seed。
跑完由 `36_fourarm_seed_variance.py` 汇总成 mean±std 与配对 CI。

与 34 号链同样的纪律:
  * 阶段化 (先训练, 后汇总) —— 中断时留下的永远是上游结果;
  * 子进程输出重定向到独立日志文件, **不要用 capture_output=True** (父进程一死,
    子进程下一次写 stdout 就是 BrokenPipeError, 直接死掉且不留报错);
  * 可续跑: 产物 json 存在就 SKIP。

用法:
  python pipelines/shelf_sdg/35_fourarm_seed_chain.py [--seeds 43,44] [--arms r2,r0,r1]
"""
import argparse
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PY = sys.executable
LOG = os.path.join(BENCH, "chain_fourarm_seeds.log")

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))

# 臂 → 单次训练大致耗时 (分钟), 用于排序: 先跑便宜的, 保证任何中断下都有可用的配对
ARMS = [("r2", 110), ("r0", 110), ("r1", 10)]


def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(BENCH, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(cmd, keep_prefixes=("[BENCH]", "[PROTOCOL]", "[MEM-GUARD]")):
    log("RUN " + " ".join(cmd[1:]))
    t0 = time.time()
    step_log = os.path.join(BENCH, "chain_steps",
                            re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(cmd[1])) + ".log")
    os.makedirs(os.path.dirname(step_log), exist_ok=True)
    with open(step_log, "a", encoding="utf-8", errors="ignore") as f:
        r = subprocess.run(cmd, env=ENV, cwd=BASE, stdout=f, stderr=subprocess.STDOUT)
    try:
        txt = open(step_log, "r", encoding="utf-8", errors="ignore").read()
        for line in txt.splitlines():
            if any(line.startswith(p) for p in keep_prefixes):
                log("  " + line)
        if r.returncode != 0:
            log(f"  !! 退出码 {r.returncode} (完整输出见 {step_log})")
            log("  " + txt[-900:].replace("\n", "\n  "))
            return False
    except OSError:
        pass
    log(f"  完成 {(time.time() - t0) / 60:.1f} min")
    return True


def train(arm, seed):
    out = os.path.join(BENCH, f"sku110k_{arm}_s{seed}.json")
    if os.path.exists(out):
        log(f"SKIP {arm} seed={seed} (已存在)")
        return True
    cmd = [PY, "pipelines/shelf_sdg/14_sku110k_baseline.py",
           "--arm", arm, "--arm-tag", f"s{seed}", "--seed", str(seed), "--select", "best"]
    if not run(cmd):
        return False
    try:
        import json
        d = json.load(open(out, encoding="utf-8"))
        log(f"  {arm} s{seed}: map50={d['map50']:.4f} map50_95={d['map50_95']:.4f} "
            f"wall={d.get('wall_sec')}s")
    except Exception as e:
        log(f"  !! 读产物失败: {e}")
    return True


def variance():
    out = os.path.join(BENCH, "fourarm_seed_variance.json")
    if os.path.exists(out):
        log("重跑 36_fourarm_seed_variance.py")
        run([PY, "pipelines/shelf_sdg/36_fourarm_seed_variance.py"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="43,44")
    ap.add_argument("--arms", default="r2,r0,r1")
    args = ap.parse_args()
    seeds = [int(s) for s in str(args.seeds).split(",") if str(s).strip()]
    arms = [a.strip() for a in str(args.arms).split(",") if a.strip()]
    order = {a: i for i, (a, _) in enumerate(ARMS)}
    arms.sort(key=lambda a: order.get(a, 99))

    os.makedirs(BENCH, exist_ok=True)
    log(f"=== 四臂多种子链开始 (arms={arms}, seeds={seeds}) ===")
    # 阶段 A: 训练。顺序 = **按 seed 轮转** (r2 s43 → r0 s43 → r2 s44 → r0 s44 → r1 …) ——
    # 这样中断时"r0 vs r2 同 seed 配对"总能凑齐一对, 而不是"只跑完一个臂的全套"。
    for seed in seeds:
        for arm in arms:
            log(f"--- 训练 {arm} seed {seed} ---")
            train(arm, seed)
    variance()
    log("=== 四臂多种子链结束 ===")


if __name__ == "__main__":
    main()
