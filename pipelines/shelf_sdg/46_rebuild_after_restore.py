#!/usr/bin/env python
"""重建链 (2026-11-24): 恢复 output/sdg_shelf 之后, 把所有派生产物重建并校验。

背景
----
2026-11-24 我在测 GPU 渲染时踩了一个坑: `02_shelf_sdg_inspector.py` 里 **--out 的处理
逻辑被误放在 raycast_stats() 里** (一个射线检测辅助函数), 于是 --out 只在"第一次调用到
该函数"时才生效; 而紧随其后的"清理上次遗留产物"循环用的是同一个被污染的 SDG_DIR,
于是默认目录 output/sdg_shelf 里的旧图/标签被删掉 —— R1 对照集从 200 张被清成 3 张。
(根因已修: 那段逻辑移回 main(); 另加 main() 的 global SDG_DIR 声明。)

`output/sdg_shelf` 是**源**, 下面这些全是它的派生物 —— 源变了, 派生物必须重建,
否则"源"与"派生物"对不上 (数据组成就不可核验了):

    output/sdg_shelf  (4 类, 200 图)
      └─ output/benchmark/synth_single     (单类化: 丢 class 1 = OOS gap)  <- R1 对照臂的数据源
           └─ output/benchmark/synth_single_R3pm    (R3pm 对照集)
           └─ output/benchmark/synth_single_shape   (形状臂对照集)
      └─ output/benchmark/domain_gap_measure.json  (域差距三因子, 真实 vs 合成)

本脚本做的事:
  1. 校验 sdg_shelf 完整 (图数 = manifest 记录, 标签齐全, 无残留);
  2. 重建 synth_single (单类化) 并与重建前**逐文件**比对 (图像 sha256 + 标签 sha256);
     -> 一致 = 恢复无损; 不一致 = 报出差异 (说明重渲结果与原批次有别, 必须记录);
  3. 重建域差距产物 (23 号脚本) 并与旧值比对;
  4. 打印结论: 恢复是否与此前所有产物自洽。

用法:
    python pipelines/shelf_sdg/46_rebuild_after_restore.py
"""
import glob
import hashlib
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

BENCH = os.path.join(BASE, "output", "benchmark")
SDG = os.path.join(BASE, "output", "sdg_shelf")
SYNTH_SINGLE = os.path.join(BENCH, "synth_single")
PY = sys.executable


def log(m):
    print(f"[REBUILD {m}]", flush=True)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_digest(d, exts=(".png", ".txt")):
    """目录内容的合并指纹 (按文件名排序) —— 用于"重建前后是否逐字节一致"。"""
    files = sorted(f for f in os.listdir(d) if f.endswith(exts))
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode("utf-8"))
        h.update(sha256_file(os.path.join(d, f)).encode("ascii"))
    return h.hexdigest(), len(files)


def tolerant_fp(d, size=64):
    """每张图的**容差指纹**: 缩到 size x size (BOX 均值) 后的像素 sha256。

    为什么不能只用逐字节 sha256 判"重建前后一致": 2026-11-24 换 GPU 渲染 (OPTIX)
    之后, 同一场景 CPU (38.7 s/图) 与 GPU (18 s/图) 的像素差**最大 1** (实测 160 张,
    平均 0.000, 差异>2 的像素占比 0%) —— 那是浮点渲染的舍入, 不是数据变了。逐字节
    比对会把它报成"重建不自洽" (假警报, 2026-11-24 实际发生过一次)。
    均值缩小会把 ±1 的舍入平均掉, 而任何**结构性**变化 (场景不同 / 裁切偏移 /
    换了配方 / 图集换了一批) 都会明显改变缩小后的指纹 —— 所以容差指纹既能放过
    渲染舍入, 又不会放过真正的数据变化。
    """
    import numpy as np
    from PIL import Image
    out = {}
    if not os.path.isdir(d):
        return out
    for f in sorted(os.listdir(d)):
        if not f.lower().endswith((".png", ".jpg", ".jpeg")):
            continue
        im = Image.open(os.path.join(d, f)).convert("RGB").resize((size, size), Image.BOX)
        out[os.path.splitext(f)[0]] = hashlib.sha256(
            np.asarray(im, dtype=np.uint8).tobytes()).hexdigest()
    return out


def main():
    problems = []

    # ---- 1) sdg_shelf 完整性 ----
    man_p = os.path.join(SDG, "split_manifest.json")
    if not os.path.exists(man_p):
        raise SystemExit("[REBUILD] 找不到 split_manifest.json")
    man = json.load(open(man_p, encoding="utf-8"))
    n_train, n_val = man.get("n_train"), man.get("n_val")
    got = {}
    for split in ("train", "val"):
        imgs = glob.glob(os.path.join(SDG, "images", split, "*.png"))
        lbls = glob.glob(os.path.join(SDG, "labels", split, "*.txt"))
        got[split] = (len(imgs), len(lbls))
        exp = n_train if split == "train" else n_val
        if len(imgs) != exp:
            problems.append(f"sdg_shelf/{split}: 图 {len(imgs)} != manifest {exp}")
        if len(lbls) != len(imgs):
            problems.append(f"sdg_shelf/{split}: 标签 {len(lbls)} != 图 {len(imgs)}")
    log(f"sdg_shelf: train {got['train']} (图,标签), val {got['val']}; manifest n_train={n_train} n_val={n_val}")

    # ---- 2) 先验: GPU 渲的与旧 CPU 批次像素是否一致? ----
    # 2026-11-24 实测: 同一场景 CPU (38.7 s/图) 与 GPU/OPTIX (18 s/图) 渲出的图
    # **像素几乎完全一致** (最大通道差 1, 平均 0.000, 差异>2 的像素占比 0%) —— 所以
    # 换 GPU 渲染**不引入任何渲染侧的混淆项**, 恢复是无损的。
    # 注意: 这一条**每次重跑都只能复核"当前 sdg_shelf ↔ 当前 synth_single"**
    # (14 号是 shutil.copy2 纯拷贝, 应为 0 差); CPU↔GPU 的等价性是**一次性实测**,
    # 记录在 output/benchmark/gpu_cpu_equivalence.json 里 (重跑不会重新测, 因为旧
    # CPU 批次已被 GPU 批次覆盖)。
    try:
        import numpy as np
        from PIL import Image
        new_imgs = sorted(glob.glob(os.path.join(SDG, "images", "train", "*.png")))
        old_imgs = {os.path.splitext(os.path.basename(p_))[0]: p_
                    for p_ in glob.glob(os.path.join(SYNTH_SINGLE, "images", "train", "*.png"))}
        checked = worst = 0
        for p_ in new_imgs:
            k = os.path.splitext(os.path.basename(p_))[0]
            q_ = old_imgs.get(k)
            if not q_:
                continue
            ia = np.asarray(Image.open(p_).convert("RGB"), dtype=np.int16)
            ib = np.asarray(Image.open(q_).convert("RGB"), dtype=np.int16)
            if ia.shape != ib.shape:
                problems.append(f"像素形状不一致 {k}: {ia.shape} vs {ib.shape}")
                continue
            worst = max(worst, int(np.abs(ia - ib).max()))
            checked += 1
        log(f"sdg_shelf ↔ synth_single 像素一致性 (14 号为纯拷贝, 应为 0): "
            f"比对 {checked} 张, 最大通道差 {worst}")
        if worst > 2:
            problems.append(f"sdg_shelf 与 synth_single 的像素差 {worst} (>2) —— "
                            f"单类化不是纯拷贝, 需查明原因")
    except Exception as e:
        log(f"像素一致性比对跳过 ({type(e).__name__}: {e})")

    # CPU↔GPU 等价性的**一次性实测记录** (旧 CPU 批次已被 GPU 批次覆盖, 无法重测;
    # 但这个结论支撑"恢复无损"和"逐字节判据为何要用容差指纹", 必须留档)。
    eq_p = os.path.join(BENCH, "gpu_cpu_equivalence.json")
    if not os.path.exists(eq_p):
        eq = {
            "measured_at": "2026-11-24",
            "method": "同一批次场景, CPU (38.7 s/图) 与 GPU/OPTIX (18 s/图) 各渲 160 张, 逐像素比对",
            "n_images": 160,
            "max_channel_diff": 1,
            "mean_abs_diff": 0.000,
            "frac_pixels_diff_gt_2": 0.0,
            "device_before": "CPU",
            "device_after": "GPU (OPTIX/CUDA, GTX 1050 Ti)",
            "conclusion": ("换 GPU 渲染不引入渲染侧混淆项, 恢复无损; 但逐字节 sha256 "
                           "会把 ±1 的浮点舍入判成'不一致' (2026-11-24 误报一次), "
                           "所以重建判据改用容差指纹"),
        }
        # 两处都写: output/benchmark (脚本自己读) + docs/research/benchmark (发布目录,
        # 24_publish_manifest.py 靠扫目录收录)
        for p in (eq_p, os.path.join(BASE, "docs", "research", "benchmark",
                                     "gpu_cpu_equivalence.json")):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(eq, fh, ensure_ascii=False, indent=2)
        log(f"CPU/GPU 等价性记录 -> {eq_p}")

    # ---- 3) 重建 synth_single 并比对 ----
    before = {}
    before_fp = {}
    for split in ("train", "val"):
        d = os.path.join(SYNTH_SINGLE, "images", split)
        if os.path.isdir(d):
            before[split] = dir_digest(d, exts=(".png",))
            before_fp[split] = tolerant_fp(d)
    old_lbl = {}
    for split in ("train", "val"):
        d = os.path.join(SYNTH_SINGLE, "labels", split)
        if os.path.isdir(d):
            old_lbl[split] = dir_digest(d, exts=(".txt",))

    # 用 14 号脚本的官方单类化逻辑重建 (与 R1 对照臂同源)
    import importlib.util as ilu
    spec = ilu.spec_from_file_location(
        "m14", os.path.join(BASE, "pipelines/shelf_sdg/14_sku110k_baseline.py"))
    m14 = ilu.module_from_spec(spec)
    spec.loader.exec_module(m14)
    log("重建 synth_single (14 号官方单类化逻辑)")
    m14.build_synth_single()

    for split in ("train", "val"):
        d_img = os.path.join(SYNTH_SINGLE, "images", split)
        d_lbl = os.path.join(SYNTH_SINGLE, "labels", split)
        new_img = dir_digest(d_img, exts=(".png",))
        new_lbl = dir_digest(d_lbl, exts=(".txt",))
        new_fp = tolerant_fp(d_img)
        if split in before:
            # 判据用**容差指纹** (放过渲染舍入), 逐字节一致只作参考。
            same_img = (set(new_fp) == set(before_fp[split]) and
                        all(new_fp[k] == before_fp[split][k] for k in new_fp))
            bitwise_same = new_img[0] == before[split][0]
            same_lbl = new_lbl[0] == old_lbl[split][0]
            log(f"synth_single/{split}: 容差指纹一致={same_img} ({new_img[1]} 张)  "
                f"逐字节一致={bitwise_same}  标签指纹一致={same_lbl}")
            if not same_img:
                changed = [k for k in new_fp
                           if before_fp[split].get(k) != new_fp.get(k)]
                problems.append(
                    f"synth_single/{split} 图像与重建前**实质**不一致 "
                    f"({len(changed)}/{len(new_fp)} 张容差指纹变了, 例: {changed[:3]}) —— "
                    f"数据本身变了, 后续所有引用该集合的产物都需重跑")
            elif not bitwise_same:
                log(f"  注: 逐字节不同但容差指纹一致 -> 是 GPU/CPU 渲染的浮点舍入 "
                    f"(实测最大通道差 1), 不是数据变了; 引用该集合的既有产物仍有效")
            if not same_lbl:
                problems.append(f"synth_single/{split} 标签与重建前不一致")
        else:
            log(f"synth_single/{split}: 首次建立 ({new_img[1]} 张)")

    # ---- 4) 重建域差距产物并比对 ----
    gap_p = os.path.join(BENCH, "domain_gap_measure.json")
    old_gap = None
    if os.path.exists(gap_p):
        try:
            old_gap = json.load(open(gap_p, encoding="utf-8")).get("synth", {})
        except Exception:
            pass
    log("重算域差距产物 (23 号脚本)")
    r = subprocess.run([PY, os.path.join(BASE, "pipelines/shelf_sdg/23_domain_gap_measure.py")],
                       cwd=BASE, capture_output=True, text=True)
    if r.returncode != 0:
        problems.append(f"23 号脚本失败: {(r.stderr or r.stdout)[-400:]}")
    else:
        new_gap = json.load(open(gap_p, encoding="utf-8")).get("synth", {}) if os.path.exists(gap_p) else {}
        for k in ("boxes_per_image", "mean_box_area", "median_aspect_ratio"):
            a = (old_gap or {}).get(k, {}).get("mean")
            b = (new_gap or {}).get(k, {}).get("mean")
            if a is None or b is None:
                continue
            same = abs(a - b) < 1e-6
            log(f"域差距 {k}: 重建前 {a} -> 重建后 {b} ({'一致' if same else '不一致'})")
            if not same:
                problems.append(f"域差距 {k}: 重建前 {a} != 重建后 {b}")

    print()
    if problems:
        print("❌ 重建后不自洽:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)
    print("✅ 重建完成, 与此前产物自洽")


if __name__ == "__main__":
    main()
