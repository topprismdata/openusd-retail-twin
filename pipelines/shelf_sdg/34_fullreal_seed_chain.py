#!/usr/bin/env python3
"""全量真实格点 (frac=1) 的多种子复跑链 (2026-11-22)。

背景: `22_budget_seed_variance.py` 的结论文档里明写着一条限制 ——
    "全量真实格点 (frac=1) 只有 1 次运行 (单次 2.1 h), 它的**方差未知**;
     因此'相对全量真实的缺口'这一列的不确定度大于格点内的比较"。
也就是说, 全篇最核心的那个参照物 (全量真实) 自己只有单次运行,
而"5% 真实 / 2% 真实 相对全量真实差多少"却是按点估计在讲。

本链补的就是这一格:
  1. 用**同一份全量真实数据** (frac=1.0 → sample_subset 返回全集, 顺序不变,
     所以 real_subset_sha256 与 seed 42 那次完全相同) 只换训练 seed 43 / 44,
     训练 10 epoch, 口径与协议完全一致 (见 docs/research/REPRODUCIBILITY_PROTOCOL_2026-11-20.md);
  2. 每个 seed 跑计数指标 (固定 600 张抽样, 与其它臂同一份名单);
  3. 每个 seed 跑**逐图配对 AP** (5% 真实 vs 全量真实, 同 seed) → 缺口有了配对 CI;
  4. 收尾自动重跑 22_budget_seed_variance.py (它按格点自动聚合多种子结果)。

可续跑: 每一步的产物 json 存在就跳过, 中断后直接重跑即可。
不并行: 同一块 GPU 上并行训练与推理会互相饿死 (见 chain_seeds.py 的教训)。

用法:
  python pipelines/shelf_sdg/34_fullreal_seed_chain.py [--seeds 43,44] [--skip-paired]
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
LOG = os.path.join(BENCH, "chain_fullreal_seeds.log")

# 训练协议 (与已发布格点一致): frac=1.0, 无合成, 10 epoch, 取 last 权重
FRAC = 1.0
SYNTH = 0
EPOCHS = 10
SELECT = "last"
BUDGET_SEED = 20261120
# 对比臂 (逐图配对 AP 的另一半): 5% 真实、无合成
GAP_FRAC = 0.05

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))


def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(BENCH, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def run(cmd, keep_prefixes=("[BUDGET]", "[COUNT]", "[PAIRED]", "[BENCH]", "[VAR]")):
    """跑一个子步骤。

    **不要用 capture_output=True**: 那会给子进程建一根管道, 一旦链本身被杀,
    管道读端关闭 → 子进程下一次写 stdout 就会 BrokenPipeError 直接死掉
    (2026-11-22 实测踩过: 训练刚跑 1 分钟就没了, 而且没留下任何报错)。
    改成把子进程的输出重定向到独立日志文件 → 子进程与链的生命周期解耦。
    """
    log("RUN " + " ".join(cmd[1:]))
    t0 = time.time()
    step_log = os.path.join(BENCH, "chain_steps",
                            re.sub(r"[^A-Za-z0-9_.-]+", "_", os.path.basename(cmd[1])) + ".log")
    os.makedirs(os.path.dirname(step_log), exist_ok=True)
    with open(step_log, "w", encoding="utf-8", errors="ignore") as f:
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


def train(seed):
    out = os.path.join(BENCH, f"budget_real{FRAC:g}_synth{SYNTH}_s{seed}.json")
    if os.path.exists(out):
        log(f"SKIP 训练 seed={seed} (已存在)")
        return True
    cmd = [PY, "pipelines/shelf_sdg/21_annotation_budget.py",
           "--fracs", f"{FRAC:g}", "--synth", str(SYNTH),
           "--epochs", str(EPOCHS), "--select", SELECT,
           "--budget-seed", str(BUDGET_SEED), "--seed", str(seed),
           "--run-tag", f"s{seed}"]
    if not run(cmd):
        return False
    # 数据一致性: frac=1.0 时子集就是全集, sha 必须与 seed 42 那次一致
    try:
        import json
        d = json.load(open(out, encoding="utf-8"))
        sha = d["dataset"]["real_subset_sha256"]
        log(f"  real_subset_sha256={sha[:16]} n_real={d['dataset']['n_real']} "
            f"map50={d['map50']:.4f} map50_95={d['map50_95']:.4f}")
    except Exception as e:
        log(f"  !! 读产物失败: {e}")
    return True


def count_eval(seed):
    out = os.path.join(BENCH, f"count_real{FRAC:g}_s{seed}.json" if seed != 42
                       else f"count_real{FRAC:g}.json")
    if os.path.exists(out):
        log(f"SKIP 计数 seed={seed} (已存在)")
        return True
    ckpt = _ckpt(FRAC, SYNTH, seed)
    if not os.path.exists(ckpt):
        log(f"SKIP 计数 seed={seed} (权重不存在: {ckpt})")
        return False
    cmd = [PY, "pipelines/shelf_sdg/17_count_eval.py",
           "--arm", f"real{FRAC:g}_s{seed}", "--weights", ckpt]
    return run(cmd)


def count_gap_arm(seed):
    """对比臂 (5% 真实) 的计数指标 —— 缺口要在**同一个 seed** 上比, 所以对照臂也得有多 seed。"""
    arm = f"real{GAP_FRAC:g}"
    out = os.path.join(BENCH, f"count_{arm}_s{seed}.json" if seed != 42 else f"count_{arm}.json")
    if os.path.exists(out):
        log(f"SKIP 对照臂计数 seed={seed} (已存在)")
        return True
    ckpt = _ckpt(GAP_FRAC, SYNTH, seed)
    if not os.path.exists(ckpt):
        log(f"SKIP 对照臂计数 seed={seed} (权重不存在: {ckpt})")
        return False
    cmd = [PY, "pipelines/shelf_sdg/17_count_eval.py",
           "--arm", f"{arm}_s{seed}", "--weights", ckpt]
    return run(cmd)


def _ckpt(frac, synth, seed):
    """取某个 (真实比例, 合成数, seed) 的 last 权重。

    seed 42 是最早那一跑, 目录**不带** run-tag 后缀; 其它 seed 带 `_s<seed>` 后缀。
    """
    tagged = os.path.join(BENCH, f"budget_runs_real{frac:g}_synth{synth}_s{seed}",
                          "train", "weights", f"{SELECT}.pt")
    plain = os.path.join(BENCH, f"budget_runs_real{frac:g}_synth{synth}",
                         "train", "weights", f"{SELECT}.pt")
    if seed != 42 and os.path.exists(tagged):
        return tagged
    if os.path.exists(plain):
        return plain
    return tagged


def paired_gap(seed):
    """5% 真实 vs 全量真实 (同 seed) 的逐图配对 AP。"""
    tag = f"gap_real{FRAC:g}_s{seed}"
    out = os.path.join(BENCH, f"paired_image_eval_{tag}.json")
    if os.path.exists(out):
        log(f"SKIP 逐图配对 seed={seed} (已存在)")
        return True
    a = _ckpt(GAP_FRAC, SYNTH, seed)
    b = _ckpt(FRAC, SYNTH, seed)
    if not (os.path.exists(a) and os.path.exists(b)):
        log(f"SKIP 逐图配对 seed={seed} (权重缺失 a={os.path.exists(a)} b={os.path.exists(b)})")
        return False
    cmd = [PY, "pipelines/shelf_sdg/25_paired_image_eval.py",
           "--weights-a", a, "--weights-b", b,
           "--label-a", f"{GAP_FRAC:g} 真实 (seed {seed})",
           "--label-b", f"全量真实 (seed {seed})", "--tag", tag]
    return run(cmd)


def variance():
    out = os.path.join(BENCH, "budget_seed_variance.json")
    if os.path.exists(out):
        log("重跑 22_budget_seed_variance.py")
        run([PY, "pipelines/shelf_sdg/22_budget_seed_variance.py"])
    else:
        log("SKIP 方差汇总 (还没跑过 22)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="43,44")
    ap.add_argument("--skip-paired", action="store_true")
    ap.add_argument("--paired-only", action="store_true",
                    help="只补跑逐图配对 (训练与计数产物都已存在时用)")
    args = ap.parse_args()
    seeds = [int(s) for s in str(args.seeds).split(",") if str(s).strip()]

    os.makedirs(BENCH, exist_ok=True)
    log(f"=== 全量真实多种子链开始 (seeds={seeds}"
        f"{', 只补配对' if args.paired_only else ''}) ===")
    # 三个阶段分开跑, 而不是每个 seed 一口气跑完:
    #   阶段 A 训练 → 阶段 B 计数 → 阶段 C 逐图配对。
    # 这样中途被打断时, 已有的一定是**最上游**的结果 (先有全部 mAP, 再有计数, 最后配对),
    # 而不是"只跑完一个 seed 的全套"。
    ok = {}
    if not args.paired_only:
        for seed in seeds:
            log(f"--- 阶段 A: 训练 seed {seed} ---")
            ok[seed] = train(seed)
            if not ok[seed]:
                log(f"!! seed {seed} 训练失败, 跳过它的后续步骤")
        for seed in seeds:
            if not ok.get(seed):
                continue
            log(f"--- 阶段 B: 计数 seed {seed} ---")
            count_eval(seed)
            count_gap_arm(seed)
    if not args.skip_paired:
        for seed in seeds:
            log(f"--- 阶段 C: 逐图配对 seed {seed} ---")
            paired_gap(seed)
    variance()
    log("=== 全量真实多种子链结束 ===")


if __name__ == "__main__":
    main()
