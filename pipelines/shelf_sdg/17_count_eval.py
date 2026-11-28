#!/usr/bin/env python3
"""四臂计数业务指标 (shelf-monitor 口径): 每测试图预测 facings 数 vs 真值数。

真值: /opt/homebrew/datasets/SKU-110K/annotations/annotations_test.csv (image,x1,y1,x2,y2,...)
预测: 各臂 best.pt 在 test 前 600 图 (conf 0.35, max_det 1000)
输出: output/benchmark/count_<arm>.json {mae, mape, pearson_r, n_images}
用法: python3 17_count_eval.py --arm r0
"""
import csv
import json
import os
import sys
from collections import defaultdict

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import file_sha256, runtime_versions, write_json  # noqa: E402
from pipelines.common.runtime_env import torch_device  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
# 2026-11-20: 数据集根目录改为 env (原代码硬编码 macOS Homebrew 路径, 换机即失效)
ROOT = os.environ.get("SKU110K_ROOT", "/opt/homebrew/datasets/SKU-110K")
N_EVAL = 600
CONF = 0.35
SAMPLE_SEED = 20261120   # 抽样种子: 固定后可复算, 抽样名单落盘


def gt_counts():
    per = defaultdict(int)
    with open(os.path.join(ROOT, "annotations", "annotations_test.csv")) as f:
        for row in csv.reader(f):
            if not row or row[0].startswith("image"):
                continue
            per[os.path.basename(row[0])] += 1
    return per


def main():
    arm = sys.argv[sys.argv.index("--arm") + 1] if "--arm" in sys.argv else "r0"
    from ultralytics import YOLO
    # 2026-11-21: 允许显式指定权重 (预算臂的权重不在 runs_<arm>/ 下, 硬编码路径找不到)
    if "--weights" in sys.argv:
        w = sys.argv[sys.argv.index("--weights") + 1]
    else:
        w = os.path.join(BENCH, f"runs_{arm}", "train", "weights", "best.pt")
        if arm == "r0" and not os.path.exists(w):
            w = os.path.join(BENCH, "runs_r0", "train", "weights", "best.pt")
    if not os.path.exists(w):
        raise SystemExit(f"[COUNT] 权重不存在: {w}")
    model = YOLO(w)
    gt = gt_counts()
    pool = sorted(gt)
    # 2026-11-20 (审计 F12): 原实现取排序后前 600 张 —— 确定性但有偏 (按文件名前缀聚簇)。
    # 改为固定种子的随机抽样, 并把抽样名单指纹落盘, 使"评的是哪 600 张"可核验。
    rng = np.random.default_rng(SAMPLE_SEED)
    k = min(N_EVAL, len(pool))
    idx = np.sort(rng.choice(len(pool), size=k, replace=False)) if k else np.array([], dtype=int)
    names = [pool[i] for i in idx]
    imgs = [os.path.join(ROOT, "images", n) for n in names]
    device = torch_device()
    # 2026-11-21: --conf-sweep 扫多个置信阈值 (计数指标对阈值敏感, 单点不稳健)
    confs = [float(x) for x in sys.argv[sys.argv.index("--conf-sweep") + 1].split(",")] \
        if "--conf-sweep" in sys.argv else [CONF]
    import hashlib
    sample_sha = hashlib.sha256("\n".join(names).encode("utf-8")).hexdigest()
    # 抽样名单落盘 (审计 F12): 光有 sha256 只能"验一致", 落盘才看得到评了哪几张
    sample_list = os.path.join(BENCH, f"count_sample_{arm}.txt")
    with open(sample_list, "w", encoding="utf-8") as fh:
        fh.write("\n".join(names) + ("\n" if names else ""))
    sweep = []
    gc = [gt[n] for n in names]
    gc_a = np.asarray(gc, float)
    for cf in confs:
        # 2026-11-22: **必须逐阈值各跑一次 predict** (口径 = "在该阈值下直接推理后数框")。
        # 曾试过"只在最低阈值推理一次, 再按 conf 过滤框"来省 4 次推理 —— 语义上**不等价**:
        # ultralytics 的 non_max_suppression 里 conf 过滤在 NMS **之前**
        # (utils/nms.py: filt = xc[xi]; x = x[filt]; 之后才 NMS), 所以低分框会先参与抑制,
        # 可能把本该保留的高分框压掉。本数据集上实测两者数值恰好一致 (单类密集货架,
        # 低分框基本是已被抑制的重复框), 但**不能依赖这个巧合**, 口径按逐阈值推理定义。
        # 必须 stream=True —— 非流式会把 600 张图的 orig_img 全留在内存里
        # (实测 ~10 GB, 直接触发训练侧的 MEM-GUARD); 流式只留每图的框数。
        #
        # 2026-11-23: **加时间预算**。实测: 对"坏模型"(r3pm 那种 map50~0.08 的), 每图能吐
        # 上千个框, NMS 把 600 张图的计数拖到 100 分钟还没完 (进程读盘 0 MB/s, GPU 空转
        # 100%) —— 一个辅助指标不该拖垮整条链。超预算就截断并**如实标注** (n_images 用
        # 实际跑完的数, 并标 partial), 不静默当成完整结果。
        import time as _time
        budget = float(sys.argv[sys.argv.index("--time-budget") + 1]) \
            if "--time-budget" in sys.argv else 1200.0
        t0 = _time.time()
        pc = []
        partial = False
        for res in model.predict(imgs, conf=cf, max_det=1000, device=device,
                                 verbose=False, stream=True):
            pc.append(len(res.boxes))
            if _time.time() - t0 > budget:
                partial = True
                print(f"[COUNT] {arm} conf={cf}: 超时间预算 {budget:.0f}s, "
                      f"已算 {len(pc)}/{len(imgs)} 张 (截断)")
                break
        pc_a = np.asarray(pc, float)
        gc_used = gc_a[:len(pc_a)]          # 截断时真值也要同步截断 (否则长度不匹配)
        mae = float(np.abs(pc_a - gc_used).mean()) if len(pc_a) else 0.0
        mape = float((np.abs(pc_a - gc_used) / np.maximum(1, gc_used)).mean() * 100) if len(pc_a) else 0.0
        r = float(np.corrcoef(pc_a, gc_used)[0, 1]) if pc_a.std() > 0 and gc_used.std() > 0 else 0.0
        sweep.append({"conf": cf, "count_mae": round(mae, 2),
                      "count_mape_pct": round(mape, 2), "pearson_r": round(r, 3),
                      "mean_pred": round(float(pc_a.mean()), 1) if len(pc_a) else 0.0,
                      "n_used": len(pc_a), "partial": partial})
        print(f"[COUNT] {arm} conf={cf} MAE={mae:.2f} MAPE={mape:.2f}% r={r:.3f} "
              f"(pred {pc_a.mean():.1f} vs gt {gc_used.mean():.1f})"
              + (" [截断]" if partial else ""))
    # 2026-11-22: 头条指标固定取标准阈值 0.35 (与已发布文档同口径), 而不是阈值列表的第一项
    head = next((s for s in sweep if abs(s["conf"] - CONF) < 1e-9), sweep[0])
    CONF_USED = head["conf"]
    mae = head["count_mae"]
    mape = head["count_mape_pct"]
    r = head["pearson_r"]
    pc_a_mean = head["mean_pred"]
    rep = {"arm": arm, "n_images": len(names), "conf": CONF_USED,
           "count_mae": round(mae, 2), "count_mape_pct": round(mape, 2),
           "pearson_r": round(r, 3),
           "mean_pred": round(float(pc_a_mean), 1),
           "mean_gt": round(float(gc_used.mean()), 1),
           "partial": bool(head.get("partial")),
           "n_evaluated": int(head.get("n_used", len(names))),
           "time_budget_sec": budget if confs else None,
           "conf_sweep": sweep,
           "sample": {"seed": SAMPLE_SEED, "n_pool": len(pool), "n_sampled": len(names),
                      "names_sha256": sample_sha,
                      "list_path": os.path.relpath(sample_list, BASE).replace("\\", "/"),
                      "list_sha256": file_sha256(sample_list),
                      "policy": "random sample with fixed seed (2026-11-20 替代'排序取前600')"},
           "weights": {"path": w.replace("\\", "/"), "sha256": file_sha256(w)},
           "device": device,
           "deps": runtime_versions()}
    write_json(os.path.join(BENCH, f"count_{arm}.json"), rep)
    print(f"[COUNT] {arm} MAE={rep['count_mae']} MAPE={rep['count_mape_pct']}% r={rep['pearson_r']} "
          f"(pred {rep['mean_pred']} vs gt {rep['mean_gt']}) n={len(names)} sample={sample_sha[:12]}")


if __name__ == "__main__":
    main()
