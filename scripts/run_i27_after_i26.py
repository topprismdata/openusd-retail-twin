#!/usr/bin/env python
"""I-27: 等 I-26 的臂跑完后, 立即跑 67 号探针 (复用到 I-20 的两个权重) 。

为什么链在一起: GPU 只有一张卡 (GTX 1050 Ti 4GB ✓), 两个任务并发会抢显存 → 串行比并发快 ✓。
探针只需评测 (不训练 ✓) -> 它不会抢训练的显存太多 ✓。

为什么只评 I-20 的两个权重: I-20 的问题是"**合成预训练把商品定义污染了后续微调**"这句推论 ✓ ->
测它就是拿分工臂 (runs_pf_ft_s{seed}) 与 ctrl_a (runs_pf_ctrla_s{seed}) 放在同一把梯子上:
  * 分工臂的上下文依赖度 > ctrl_a -> 污染机制成立 ✓
  * 两者在"剥离上下文的真实图”上也差 -> 机制在别的地方 → README 里那句推论要改写 ✓
判读口径与 67 号完全一致 (同一份 300 张名单、原图 vs 剥离版 ✓) -> 与 I-19 的探针直接可比 ✓。
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
ARM = "pipelines/shelf_sdg/73_real_budget_epoch_arm.py"
PROBE = "pipelines/shelf_sdg/67_context_suppress_probe.py"


def arm_finished():
    """I-26 的臂写完最后一行就会把产物路径写进日志 ✓
    (用日志的末行判断而不是 tasklist: 在这个环境里 tasklist 的 stdout 可能为空 ✓)"""
    log = os.path.join(BASE, "output", "benchmark", "rbe_arm.log")
    try:
        with open(log, encoding="utf-8") as fh:
            tail = fh.read()[-4000:]
    except OSError:
        return False
    return "real_budget_epoch_arm.json" in tail


def main():
    # 等 I-26 的臂退出 (它的进程名里带 73_real_budget_epoch_arm ✓)
    while not arm_finished():
        time.sleep(30)
    print("[I27] I-26 的臂已退出, 开始探针", flush=True)
    cmd = [PY, PROBE,
           "--seeds", "43", "44", "45",
           "--arm-run", "runs_pf_ft_s{seed}",
           "--control-run", "runs_pf_ctrla_s{seed}",
           "--out", "output/benchmark/pretrain_finetune_probe.json",
           "--schema", "pretrain_finetune_probe/1",
           "--question", ("合成预训练是否把“什么是商品”定义到了合成域的上下文上? "
                         "(I-20: 合成预训练 + 真实微调比同真实曝光的纯真实对照差 2.01 pp ✓)")]
    r = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
    print(r.stdout[-4000:])
    if r.returncode != 0:
        print(r.stderr[-4000:], file=sys.stderr)
        return r.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
