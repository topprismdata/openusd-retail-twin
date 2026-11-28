#!/usr/bin/env python
"""恢复后衔接链 (2026-11-24): 等恢复渲染完 -> 重建派生产物 -> 起大池剂量链。

背景
----
2026-11-24 我在测 GPU 渲染时踩了 `--out` 的坑, 把 R1 对照集 (output/sdg_shelf, 200 张)
的图像清空了。根因已修 (见 README ④′′′′ 与协议文档)。本链负责把一切恢复并接上
GPU 通路修好后变得可行的新实验:

    1. 等 output/sdg_shelf 恢复渲染完 (200 张, GPU 18 s/图);
    2. 跑 46 号脚本: 重建 synth_single (单类化) + 域差距产物, 并**与重建前逐文件比对**
       -> 确认恢复无损 (若像素不一致, 说明重渲与原批次有别, 必须记录);
    3. 起 47 号大池剂量链 (渲染 2800 张大池 -> 单类化 -> 训练各剂量档)。

为什么要重建而不是直接用: `output/sdg_shelf` 是**源**, `output/benchmark/synth_single`
(单类化) 是 R1 对照臂的数据源, `domain_gap_measure.json` 是域差距三因子的来源。
源变了, 派生物必须重建, 否则"源"与"派生物"对不上 —— 数据组成就不可核验了。

用法:
    python pipelines/shelf_sdg/48_post_restore_chain.py
"""
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
SDG = os.path.join(BASE, "output", "sdg_shelf")
PY = sys.executable
LOG = os.path.join(BENCH, "post_restore_chain.log")
EXPECT_IMAGES = 200


def log(m):
    line = f"[CHAIN48 {time.strftime('%m-%d %H:%M:%S')}] {m}"
    print(line, flush=True)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def n_images():
    a = len(os.listdir(os.path.join(SDG, "images", "train"))) if os.path.isdir(os.path.join(SDG, "images", "train")) else 0
    b = len(os.listdir(os.path.join(SDG, "images", "val"))) if os.path.isdir(os.path.join(SDG, "images", "val")) else 0
    return a + b


def main():
    log("=== 恢复衔接链开始 ===")
    # 1) 等恢复渲染完成
    while n_images() < EXPECT_IMAGES:
        log(f"等 sdg_shelf 恢复渲染 ({n_images()}/{EXPECT_IMAGES})")
        time.sleep(120)
    log(f"sdg_shelf 恢复完成: {n_images()} 张")

    # 2) 重建派生产物并校验一致性
    log("重建派生产物 (46 号: 单类化 + 域差距 + 逐文件比对)")
    r = subprocess.run([PY, os.path.join(BASE, "pipelines/shelf_sdg/46_rebuild_after_restore.py")],
                       cwd=BASE, capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        log("  " + line)
    if r.returncode != 0:
        log(f"!! 重建链退出码 {r.returncode}: {(r.stderr or '')[-400:]}")
        log("   (若报的是'像素与重建前不一致', 说明重渲结果与原批次有别 —— "
            "这必须记录进文档, 后续引用该集合的产物都要重跑)")
    else:
        log("重建完成且与此前产物自洽")

    # 3) 密度诊断 (45 号): README 里"差距在密度不在形状"这句断言**从未实测过**。
    #    它比大池链便宜得多 (3 个 seed x 13 分钟 vs 14 小时渲染), 而且直接回答
    #    "如果把真实数据的框密度稀释到合成侧的水平, mAP 掉多少" —— 若掉得不多,
    #    那密度就不是差距的主因, 大池剂量实验的解读也要跟着改。
    log("起密度诊断 (45 号: 真实训练集框密度 147 -> 22 框/图)")
    env = dict(os.environ)
    env.setdefault("SKU110K_ROOT", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K"))
    env.setdefault("SKU110K_YAML", os.path.join(os.path.expanduser("~"), "datasets", "SKU-110K", "SKU-110K.yaml"))
    r = subprocess.run([PY, os.path.join(BASE, "pipelines/shelf_sdg/45_density_diagnostic.py"),
                        "--boxes-per-image", "22", "--seeds", "42,43,44"],
                       cwd=BASE, env=env)
    log(f"密度诊断结束 (退出码 {r.returncode})")

    # 4) 大池剂量链 (GPU 渲染 -> 单类化 -> 各剂量档训练)
    log("起大池剂量链 (47 号)")
    r = subprocess.run([PY, os.path.join(BASE, "pipelines/shelf_sdg/47_bigpool_dose_chain.py"),
                        "--stage", "all"],
                       cwd=BASE)
    log(f"大池剂量链结束 (退出码 {r.returncode})")
    log("=== 恢复衔接链结束 ===")


if __name__ == "__main__":
    main()
