#!/usr/bin/env python3
"""
05 - 基于 Apple Silicon (MPS) 的 YOLOv11 微调训练与推理闭环

输入: 02 生成的 output/sdg_shelf/dataset.yaml (4 类终端状态, 零人工标注)
输出: runs/ 权重 + val 指标 + 对验证图的首检预测可视化

运行:
  pip install ultralytics torch torchvision
  python3 05_train_yolo_mps.py [--epochs 15]
"""
import os
import sys
import glob
import shutil
import torch
from ultralytics import YOLO

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
from pipelines.common.runtime_env import torch_device  # noqa: E402

SDG_DIR = os.path.join(BASE_DIR, "output", "sdg_shelf")
PRED_DIR = os.path.join(SDG_DIR, "predict")


def verify_apple_silicon_mps():
    """选择训练设备: CUDA (NVIDIA) > MPS (Apple Silicon) > CPU。

    历史函数名保留以兼容既有调用点; 覆盖范围由 TORCH_DEVICE 环境变量强制。
    """
    device = torch_device()
    if device == "cuda":
        print("[PyTorch] CUDA 硬件加速已激活")
    elif device == "mps":
        print("[PyTorch] Apple Silicon MPS 硬件加速已激活")
    else:
        print("[Warn] 未检测到 GPU 加速 (CUDA/MPS), 回退 CPU")
    return device


def main():
    epochs = 15
    if "--epochs" in sys.argv:
        epochs = int(sys.argv[sys.argv.index("--epochs") + 1])
    seed = 42
    if "--seed" in sys.argv:
        seed = int(sys.argv[sys.argv.index("--seed") + 1])

    dataset_yaml = os.path.join(SDG_DIR, "dataset.yaml")
    n_train = len(glob.glob(os.path.join(SDG_DIR, "images/train/*.png")))
    n_val = len(glob.glob(os.path.join(SDG_DIR, "images/val/*.png")))
    if n_train == 0:
        sys.exit("[Error] 未找到训练集 — 请先运行 02_shelf_sdg_inspector.py")
    print(f"[Data] train={n_train} val={n_val}")

    device = verify_apple_silicon_mps()
    model = YOLO("yolo11n.pt")

    results = model.train(
        data=dataset_yaml,
        epochs=epochs,
        imgsz=640,
        batch=8,
        seed=seed,        # 2026-11-20: 显式固定随机种子 (原先未设 -> 每次训练不同)
        device=device,
        workers=2,
        project=os.path.join(BASE_DIR, "runs"),
        name="demo_shelf_oos_detector",
        exist_ok=True,
        verbose=True,
    )

    # 验证集指标
    metrics = model.val()
    print("\n=== 验证集指标 ===")
    print(f"mAP50: {metrics.box.map50:.3f}  mAP50-95: {metrics.box.map:.3f}")

    # 用 best 权重对验证图做首检预测
    best = os.path.join(BASE_DIR, "runs", "demo_shelf_oos_detector", "weights", "best.pt")
    detector = YOLO(best)
    os.makedirs(PRED_DIR, exist_ok=True)
    val_imgs = sorted(glob.glob(os.path.join(SDG_DIR, "images/val/*.png")))[:2]
    for vp in val_imgs:
        detector.predict(vp, save=True, project=PRED_DIR, name="pred", exist_ok=True,
                         conf=0.4, device=device)
        print(f"[Predict] {os.path.basename(vp)} -> {PRED_DIR}")
    # predict 会落在 PRED_DIR/pred 下, 拷到 PRED_DIR 顶层方便查看
    for f in glob.glob(os.path.join(PRED_DIR, "pred", "*.jp*g")):
        shutil.copy(f, PRED_DIR)
    print(f"\n[Done] 权重: {best}\n[Done] 预测可视化: {PRED_DIR}")

    # 2026-11-20: 把"这次训练用了哪份数据/划分/权重"落盘 (可复现凭证)
    try:
        from pipelines.common.protocol import build_manifest, file_sha256, runtime_versions, write_json
        sm = os.path.join(SDG_DIR, "split_manifest.json")
        manifest = build_manifest(
            {"model": "yolo11n.pt", "imgsz": 640, "epochs": epochs, "batch": 8,
             "workers": 2, "seed": seed, "device": device},
            data={"sdg_dir": SDG_DIR, "split_manifest_sha256": file_sha256(sm)},
            actual={"epochs": epochs, "device": device},
            deps=runtime_versions(),
            checkpoint={"path": best.replace("\\", "/"), "sha256": file_sha256(best),
                        "selection": "best"})
        write_json(os.path.join(SDG_DIR, "train_manifest.json"), manifest)
        print(f"[Done] 训练凭证 -> {os.path.join(SDG_DIR, 'train_manifest.json')} "
              f"(hash={manifest['protocol_hash']})")
    except Exception as e:
        print(f"[Warn] 训练凭证写入失败 (不影响训练结果): {e}")


if __name__ == "__main__":
    main()
