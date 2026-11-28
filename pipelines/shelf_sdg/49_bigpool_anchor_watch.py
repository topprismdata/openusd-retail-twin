#!/usr/bin/env python
"""大池剂量链的**锚点看门狗** (2026-11-24)。

问题
----
大池剂量链 (47 号) 是 2026-11-24 09:20 启动的, 它内存里的 DOSES **还没有 0 档** ——
0 档是后来补的 (剂量轴的锚点必须跟着自己的池走, 见 48 号的回归测试: 老逻辑会把 0 档
塞给"行数最多的池", 大池行数一多, 旧池的曲线就会整条消失)。等它渲完 2800 张再开跑,
就会缺 6 个 0 档格点 (2 预算 x 3 seed) -> 大池那条曲线没有基准, 算不出配对差值。

两种处理
--------
`--mode restart`      盯住链子日志, 一旦出现 "RUN frac=" (说明渲染已完成、链子进了
                      训练阶段) 就**杀掉链子进程树**, 用当前代码重新拉起
                      `--stage single,train`:
                        * render 阶段会因"已渲够 2800 张"而跳过 (不会重渲, 更不会清空);
                        * single 阶段幂等 (copy2 覆盖 + 标签重写);
                        * train 阶段按新 DOSES 跑满 8 档 x 3 seed x 2 预算, 0 档同批跑完。
                      代价: 正在训练的那一个格点作废 (约 0.5 机时, 会重跑)。
`--mode anchor-only`  等链子自己跑完 ("=== 大池剂量链结束 ==="), 再补
                      `--stage train --doses 0` (6 个锚点格点, 约 1.5 机时)。
                      代价: 锚点与其它格点不在同一批 -> 批次差异会被算进配对差值。

无论哪种, 结束时大池都有 0 档; 闸门 [11]/[11b]/[11c] 会复核锚点与池归属。

用法:
    python pipelines/shelf_sdg/49_bigpool_anchor_watch.py --mode restart
    python pipelines/shelf_sdg/49_bigpool_anchor_watch.py --mode anchor-only
"""
import argparse
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CHAIN = os.path.join(BASE, "pipelines", "shelf_sdg", "47_bigpool_dose_chain.py")
LOG = os.path.join(BASE, "output", "benchmark", "bigpool_dose_chain.log")
WLOG = os.path.join(BASE, "output", "benchmark", "anchor_watch.log")
POLL = 60

PS_FIND = os.path.join(BASE, "output", "benchmark", "_find_chain_pid.ps1")


def log(m):
    line = f"[WATCH {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    try:
        with open(WLOG, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def read_log():
    try:
        with open(LOG, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception:
        return ""


def chain_pids():
    """找正在跑的链子进程 (python.exe 且命令行含 47_bigpool_dose_chain.py)。"""
    script = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
              "Where-Object { $_.CommandLine -like '*47_bigpool_dose_chain*' } | "
              "ForEach-Object { $_.ProcessId }")
    with open(PS_FIND, "w", encoding="utf-8") as fh:
        fh.write(script)
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-File", PS_FIND], capture_output=True, text=True, timeout=60)
        return [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    except Exception as e:
        log(f"找链子进程失败: {type(e).__name__}: {e}")
        return []


def kill_chain():
    pids = chain_pids()
    if not pids:
        log("没找到链子进程 (可能已经结束)")
        return False
    for pid in pids:
        log(f"杀掉链子进程树 pid={pid}")
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True)
    time.sleep(10)
    return True


def run_chain(stage, doses=None, tag="relaunch"):
    cmd = [sys.executable, CHAIN, "--stage", stage]
    if doses:
        cmd += ["--doses", doses]
    out = os.path.join(BASE, "output", "benchmark", f"bigpool_chain_{tag}.log")
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    with open(out, "a", encoding="utf-8") as fh:
        p = subprocess.Popen(cmd, cwd=BASE, stdout=fh, stderr=subprocess.STDOUT,
                             creationflags=flags)
    log(f"拉起链子: {' '.join(cmd[1:])} (pid={p.pid}) -> {out}")
    return p.pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("restart", "anchor-only"), default="anchor-only")
    args = ap.parse_args()

    log(f"看门狗启动 (mode={args.mode}); 盯 {LOG}")
    while True:
        txt = read_log()
        if "=== 大池剂量链结束 ===" in txt:
            log("链子已跑完 -> 补 0 档锚点")
            run_chain("train", doses="0", tag="anchor")
            log("锚点补跑已拉起, 看门狗退出")
            return 0
        if args.mode == "restart" and "RUN frac=" in txt:
            log("链子进入训练阶段 -> 杀掉并用新代码重启 (train 阶段带 0 档)")
            if kill_chain():
                run_chain("single,train", tag="restart")
                log("重启完成, 看门狗退出")
                return 0
            log("杀链子失败, 继续盯")
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
