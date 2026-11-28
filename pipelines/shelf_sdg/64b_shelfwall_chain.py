#!/usr/bin/env python
"""等货架墙臂渲染完 -> 自动接单类化 + 训练 + 评测 (2026-11-25)。

为什么要有这个: 渲染 200 张要 ~1.7 h, 训练 3 seed 再 ~1.5 h —— 不接上就得守着。
判据: 渲染目录里的图数达到 RECIPE.num_images (或渲染进程退出) 才往下走,
否则**不启动训练** (半渲完的池会把"渲了多久"混进结果里)。
"""
import glob
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
RAW = os.path.join(BENCH, "sdg_shelf_wall")
PY = sys.executable
LOG = os.path.join(BENCH, "shelfwall_arm_chain.log")


def log(m):
    line = f"[CHAIN {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def n_images():
    return (len(glob.glob(os.path.join(RAW, "images", "train", "*.png")))
            + len(glob.glob(os.path.join(RAW, "images", "val", "*.png"))))


def render_alive():
    import psutil
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
            if "02_shelf_sdg_inspector" in cl or ("64_shelfwall_arm" in cl and "--stage" in cl
                                                 and "render" in cl):
                return True
        except Exception:
            pass
    return False


def main():
    target = 200
    log(f"等渲染完成 (目标 {target} 张)")
    while True:
        n = n_images()
        if n >= target:
            log(f"渲染完成: {n} 张")
            break
        if not render_alive():
            log(f"渲染进程已退出, 但只有 {n} 张 (目标 {target}) -> 收手, 不训练")
            return 1
        time.sleep(60)
    for stage in ("single", "train"):
        log(f"跑 stage={stage}")
        r = subprocess.run([PY, os.path.join(BASE, "pipelines/shelf_sdg/64_shelfwall_arm.py"),
                            "--stage", stage], cwd=BASE)
        log(f"stage={stage} 退出码 {r.returncode}")
        if r.returncode != 0:
            return r.returncode
    log("臂全部完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
