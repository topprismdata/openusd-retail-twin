#!/usr/bin/env python3
"""合成剂量-反应链 (2026-11-22): 回答"只测了一个合成剂量 (160 张)"这条审稿意见。

设计: **同一个合成池** (output/benchmark/synth_single/images/train) 上取**嵌套子集**
40 ⊂ 80 ⊂ 160 —— `sample_subset` 对不同 n 用同一个 shuffle 种子, 所以子集是嵌套的:
剂量轴干净, 池子不变 (不会把"池子变了"混进"剂量变了")。

160 张剂量档的结果来自标注预算臂本身 (seed 42/43/44), 本脚本补 40 与 80 两档。

用法:
    python3 pipelines/shelf_sdg/32_dose_chain.py 0.05 0.02
可续跑: 已落盘的格点会被 SKIP。日志默认写 output/benchmark/dose_chain.log (env LOG_FILE 可覆盖)。
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
SYNTH = os.path.join(BENCH, "synth_single", "images", "train")
LOG = os.environ.get("LOG_FILE", os.path.join(BENCH, "dose_chain.log"))

DOSES = [40, 80]          # 160 档已存在 (预算臂格点, seed 42/43/44)
SEEDS = [42, 43]
FRACS = [float(x) for x in (sys.argv[1:] or ["0.05"])]


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def done_json(seed, frac, synth):
    return os.path.join(BENCH, f"budget_real{frac:g}_synth{synth}_dose_s{seed}.json")


def main():
    os.chdir(BASE)
    log(f"=== 合成剂量-反应链开始 (剂量 {DOSES}, seed {SEEDS}, 预算 {FRACS}) ===")
    for frac in FRACS:
        for seed in SEEDS:
            for synth in DOSES:
                if os.path.exists(done_json(seed, frac, synth)):
                    log(f"SKIP seed={seed} frac={frac:g} dose={synth} (已完成)")
                    continue
                cmd = [sys.executable, "pipelines/shelf_sdg/21_annotation_budget.py",
                       "--fracs", f"{frac:g}", "--synth", str(synth),
                       "--epochs", "10", "--select", "last",
                       "--budget-seed", "20261120", "--seed", str(seed),
                       "--run-tag", f"dose_s{seed}", "--synth-dir", SYNTH]
                log(f"RUN seed={seed} frac={frac:g} dose={synth}")
                t0 = time.time()
                r = subprocess.run(cmd, capture_output=True, text=True)
                for line in (r.stdout or "").splitlines():
                    if line.startswith("[BUDGET]"):
                        log("  " + line)
                if r.returncode != 0:
                    log(f"  !! 退出码 {r.returncode}: {(r.stderr or '')[-500:]}")
                else:
                    log(f"  完成 {(time.time() - t0) / 60:.1f} min")
    log("=== 合成剂量-反应链完成 ===")


if __name__ == "__main__":
    main()
