#!/usr/bin/env python3
"""收尾链 (2026-11-23 晚): 形状先验臂的"渲染完 -> 训练 -> 汇总 -> 发布 -> 闸门"。

为什么要等
----------
本轮有两条长任务并行: ① 40 号链 (seed 46/47 的四臂复跑, 占 GPU ~8 h);
② 43 号的形状先验臂渲染 (200 图, 占 CPU ~8 h)。形状臂的**训练**要 GPU, 必须等 ① 结束,
否则两条 YOLO 训练抢 4 GB 显存会 OOM。

本脚本做的事 (全自动, 不用盯):
  1. 等形状渲染完成 (SDG 目录里出满 200 张图 + split_manifest ✅);
  2. 等 40 号链的进程退出 (GPU 空出来);
  3. 训练形状臂 (seeds 42/43/44 —— 与 R1 对照同 seed, 配对比较);
  4. 36 号汇总 (配对统计的唯一事实源, 会自动纳入 r1shape 臂 ✅);
  5. 43 号汇总 (域差距三因子 + 构成);
  6. 26 号发布 + 28 号文档闸门。

用法: python pipelines/shelf_sdg/44_shape_finisher.py
日志: output/benchmark/chain_shape_finisher.log
"""
import glob
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PY = sys.executable
LOG = os.path.join(BENCH, "chain_shape_finisher.log")

SDG_OUT = os.path.join(BENCH, "sdg_shape")
EXPECT_IMAGES = 200
# 形状臂的 seed 集 (2026-11-24 从 42,43,44 扩到 42–47):
# 原来只有 3 个 seed 时, 配对 CI [−29.33, +8.08] **跨 0** -> 结论只能写"未达统计显著",
# 而 5 个 seed 时 CI [−18.69, −3.92] **不含 0** -> "显著更差"成立。3 个 seed 不足以
# 分辨这个量级的效应, 所以补到与 R1 对照臂同样的 6 个 seed。
SEEDS = "42,43,44,45,46,47"

ENV = dict(os.environ)
ENV.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
ENV.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
# 2026-11-24: 不再无条件强制 CPU 渲染 —— 收尾链里渲染与训练是**串行**的
# (先渲染完再训练), GPU 本来就空着, 强制 CPU 白白慢一倍 (实测 OPTIX 18 s/图 vs CPU 40 s/图)。
# 只有当同机还有别的 GPU 任务时才用 SDG_RENDER_DEVICE=cpu 让路。
if os.environ.get("SDG_RENDER_DEVICE", "").strip().lower() == "cpu":
    ENV["FORCE_CPU_RENDER"] = "1"
else:
    ENV.pop("FORCE_CPU_RENDER", None)


def log(msg):
    line = f"[{time.strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(BENCH, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(label, args, timeout=28800):
    log(f"=== {label} :: {' '.join(args[1:])}")
    t0 = time.time()
    step_log = os.path.join(BENCH, "chain_steps",
                            "finisher_" + os.path.basename(args[1]).replace(".py", "") + ".log")
    os.makedirs(os.path.dirname(step_log), exist_ok=True)
    with open(step_log, "a", encoding="utf-8", errors="ignore") as f:
        r = subprocess.run(args, env=ENV, cwd=BASE, stdout=f, stderr=subprocess.STDOUT,
                           timeout=timeout)
    log(f"=== {label} 结束 (退出码 {r.returncode}, {(time.time() - t0) / 60:.1f} min)")
    return r.returncode == 0


def render_done():
    n = len(glob.glob(os.path.join(SDG_OUT, "images", "train", "*.png"))) + \
        len(glob.glob(os.path.join(SDG_OUT, "images", "val", "*.png")))
    man = os.path.join(SDG_OUT, "split_manifest.json")
    return n >= EXPECT_IMAGES and os.path.exists(man)


def chain_running():
    """40 号链还在跑吗 (它占着 GPU)。"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
         "Where-Object { $_.CommandLine -like '*40_seed46_47_chain*' }).Count"],
        capture_output=True, text=True)
    try:
        return int(out.stdout.strip() or "0") > 0
    except ValueError:
        return False


def main():
    log("=== 收尾链开始 ===")
    # 1) 等 40 号链结束 (它占 GPU ~8 h)。**顺序很关键**: 渲染与训练同时跑时, 渲染会把
    #    12 核吃满 -> YOLO 训练的数据加载被饿死 (实测 r3pm 训练被拖成 61 分钟, 正常 5 分钟),
    #    渲染自己也被拖成 7.5 分钟/图 (独占时约 40 秒/图)。所以**串行**: 链 -> 渲染 -> 训练。
    while chain_running():
        log("等 40 号链结束 (GPU 还占着)")
        time.sleep(300)
    log("GPU 空出来了")
    # 2) 渲染 (独占 CPU, ~40 s/图 -> 200 图约 2.5 h)
    if not render_done():
        run("渲染形状先验合成集", [PY, "pipelines/shelf_sdg/43_r1shape_arm.py",
                                   "--stage", "render", "--threads", "10"])
    else:
        log("渲染已存在, 跳过")
    # 3) 训练形状臂
    run("训练形状臂", [PY, "pipelines/shelf_sdg/43_r1shape_arm.py", "--stage", "train",
                       "--seeds", SEEDS])
    # 4) 汇总 (配对统计的唯一事实源)
    run("四臂汇总 (36)", [PY, "pipelines/shelf_sdg/36_fourarm_seed_variance.py"])
    run("形状臂汇总 (43)", [PY, "pipelines/shelf_sdg/43_r1shape_arm.py", "--stage", "summarize",
                            "--seeds", SEEDS])
    # 5) 发布 + 闸门
    run("发布产物", [PY, "pipelines/shelf_sdg/26_publish_artifacts.py"])
    run("文档闸门", [PY, "pipelines/shelf_sdg/28_doc_consistency_check.py"])
    log("=== 收尾链结束 ===")


if __name__ == "__main__":
    main()
