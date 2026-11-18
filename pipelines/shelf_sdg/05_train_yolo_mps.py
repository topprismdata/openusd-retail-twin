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
SDG_DIR = os.path.join(BASE_DIR, "output", "sdg_shelf")
PRED_DIR = os.path.join(SDG_DIR, "predict")


def verify_apple_silicon_mps():
    if torch.backends.mps.is_available():
        print("[PyTorch] Apple Silicon MPS 硬件加速已激活")
        return "mps"
    print("[Warn] 未检测到 MPS, 回退 CPU")
    return "cpu"


def main():
    epochs = 15
    if "--epochs" in sys.argv:
        epochs = int(sys.argv[sys.argv.index("--epochs") + 1])

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


if __name__ == "__main__":
    main()
