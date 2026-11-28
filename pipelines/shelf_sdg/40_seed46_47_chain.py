#!/usr/bin/env python3
"""seed 46/47 续跑链 (2026-11-23 晚): 把四个臂各补两个 seed, 收紧两处 CI。

为什么还要再补两个 seed
------------------------
上一轮 (seed 43/44/45) 之后, 全篇只剩两处结论的样本量停在 n=3:

  | 结论                                       | 现在 n | 补到 n=5 后 |
  |--------------------------------------------|--------|-------------|
  | Δ(R2−R0) = +0.13pp, CI [−0.13, +0.40]      |   3    | 头部结论 (头条) |
  | Δ(R3pm−R1) = −11.45pp, CI [−21.78, −1.13]  |   3    | 域对齐负结果 |

R3pm 尤其需要: 它的 seed 间波动很大 (0.0704 ~ 0.1895, std 0.0536), 而 CI 的上界
−1.13pp 几乎贴着 0 → 再加两个 seed 才敢说"显著更差"。

本链做的事 (每个 seed):
  1. r1   (纯合成, 160 图, ~5 min)   —— 便宜, 先跑, 保证 r1/r3pm 同 seed 配对尽早凑齐
  2. r3pm (域对齐配方, 160 图, ~5 min) —— 上面那条配对的两端
  3. r2   (真实 + 合成, ~110 min)      —— 头部配对的一端
  4. r0   (纯真实, ~100 min)           —— 头部配对的另一端
  5. 四个臂各测一次计数指标 (600 张, conf 0.35) —— 上一轮只测了 seed 45 一次, 无法区分
     "臂间差异" 与 "seed 波动"

跑完自动: 36 号汇总 (配对统计的唯一事实源) -> 38 号汇总 -> 26 号发布 -> 28 号闸门。

与 35/39 号链同样的纪律:
  * 阶段化 + 产物存在就 SKIP → 可续跑, 中断不丢已完成的部分;
  * 子进程输出重定向到独立日志文件 (不 capture_output: 父进程一死, 子进程写 stdout 就是
    BrokenPipeError, 直接死掉且不留报错);
  * 一个 seed 内的顺序按"便宜的先跑", 保证任何中断下都先拿到 r1/r3pm 配对。

用法:
  python pipelines/shelf_sdg/40_seed46_47_chain.py [--seeds 46,47] [--arms r1,r3pm,r2,r0]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PY = sys.executable
LOG = os.path.join(BENCH, "chain_seed46_47.log")

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
ENV.setdefault("BLENDER_PYTHON", os.path.join(os.path.expanduser("~"), "projects", "venvbpy", "Scripts", "python.exe"))
ENV.pop("BLENDER_BIN", None)

# 臂的运行目录 (计数脚本要用权重)
RUN_DIR = {"r0": "runs_{arm}_s{seed}", "r1": "runs_{arm}_s{seed}",
           "r2": "runs_{arm}_s{seed}", "r3pm": "runs_R3pm_s{seed}"}
# 便宜的先跑
ARM_ORDER = {"r1": 0, "r3pm": 1, "r2": 2, "r0": 3}


def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(BENCH, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(cmd, keep_prefixes=("[BENCH]", "[PROTOCOL]", "[MEM-GUARD]", "[COUNT]")):
    log("RUN " + " ".join(cmd[1:]))
    t0 = time.time()
    step_log = os.path.join(BENCH, "chain_steps",
                            re.sub(r"[^A-Za-z0-9_.-]+", "_", "_".join(cmd[1:3])) + ".log")
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
    """训一个臂。产物 json 已存在就 SKIP (可续跑)。"""
    out = os.path.join(BENCH, f"sku110k_{arm}_s{seed}.json")
    if os.path.exists(out):
        log(f"SKIP {arm} seed={seed} (已存在)")
        return True
    if arm == "r3pm":
        # 38 号自己的训练入口 (合成集固定, 只换训练 seed)
        cmd = [PY, "pipelines/shelf_sdg/38_r3_protocol_matched.py",
               "--stage", "train", "--seeds", str(seed)]
    else:
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


def count(arm, seed):
    """计数业务指标 (600 张, conf 0.35) —— 每个 (臂, seed) 一份, 看臂间差异是不是只是 seed 波动。

    **坏模型的计数直接跳过**: map50 < 0.5 的臂 (纯合成臂) 每图能吐上千个框, NMS 把 600 张
    图的计数拖到 100 分钟还没完 (实测 r3pm_s46 一次跑了 100 分钟无输出, 进程读盘 0 MB/s),
    而且这种模型的"计数能力"本来就没有可解释性 (它只数出真值的 14%~57%)。
    """
    out = os.path.join(BENCH, f"count_{arm}_s{seed}.json")
    if os.path.exists(out):
        log(f"SKIP count {arm} seed={seed} (已存在)")
        return True
    art = os.path.join(BENCH, f"sku110k_{arm}_s{seed}.json")
    try:
        m = json.load(open(art, encoding="utf-8")).get("map50")
    except Exception:
        m = None
    if m is not None and m < 0.5:
        log(f"SKIP count {arm} seed={seed} (map50={m:.4f} < 0.5: 计数指标无意义且病态慢)")
        return True
    w = os.path.join(BENCH, RUN_DIR[arm].format(arm=arm, seed=seed), "train", "weights", "best.pt")
    if not os.path.exists(w):
        log(f"  !! 权重不存在, 跳过计数: {w}")
        return False
    return run([PY, "pipelines/shelf_sdg/17_count_eval.py",
                "--arm", f"{arm}_s{seed}", "--weights", w])


def finalize(seeds):
    """汇总 -> 发布 -> 闸门。"""
    log("=== 汇总 (36 号: 配对统计的唯一事实源) ===")
    run([PY, "pipelines/shelf_sdg/36_fourarm_seed_variance.py"])
    log("=== 汇总 (38 号: R3pm + 域差距 + 构成) ===")
    run([PY, "pipelines/shelf_sdg/38_r3_protocol_matched.py", "--stage", "summarize",
         "--seeds", ",".join(str(s) for s in seeds)])
    log("=== 发布产物 ===")
    run([PY, "pipelines/shelf_sdg/26_publish_artifacts.py"])
    log("=== 文档闸门 ===")
    run([PY, "pipelines/shelf_sdg/28_doc_consistency_check.py"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="46,47")
    ap.add_argument("--arms", default="r1,r3pm,r2,r0")
    ap.add_argument("--no-count", action="store_true", help="跳过计数指标")
    ap.add_argument("--finalize-only", action="store_true", help="只跑汇总/发布/闸门")
    args = ap.parse_args()
    seeds = [int(s) for s in str(args.seeds).split(",") if str(s).strip()]
    arms = [a.strip() for a in str(args.arms).split(",") if a.strip()]
    arms.sort(key=lambda a: ARM_ORDER.get(a, 99))

    os.makedirs(BENCH, exist_ok=True)
    if not args.finalize_only:
        log(f"=== seed46/47 链开始 (arms={arms}, seeds={seeds}) ===")
        for seed in seeds:
            for arm in arms:
                log(f"--- 训练 {arm} seed {seed} ---")
                if not train(arm, seed):
                    log(f"  !! {arm} s{seed} 失败, 跳过该臂的计数")
                    continue
                if not args.no_count:
                    count(arm, seed)
        log("=== 训练部分结束 ===")
    finalize(seeds)
    log("=== 全流程结束 ===")


if __name__ == "__main__":
    main()
