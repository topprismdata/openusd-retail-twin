#!/usr/bin/env python
"""**输入扰动探针: 合成训练的模型到底卡在哪条"通道"上?** (2026-11-25)

动机
----
51 号探针已证明: 纯合成臂在**自己池上** mAP 0.995, 跨合成池 0.92–0.97, 跨到真实只剩
**0.24** -> 瓶颈是 sim2real 的**外观**差距。但"外观"里还有好几条通道 (高频纹理 / 光度 /
分辨率细节 / 内容语义), **分不清该修哪条**就会瞎投渲染器。

本探针**不动训练**, 只动**输入**: 把真实 test 图做各种退化, 看**两个模型**的反应差异
  - 合成模型 (`runs_r1_s43`, 纯合成训练)
  - 真实模型 (411 张真实子集训练, 与 R2 的真实臂同协议)
判读:
  * 若合成模型在"模糊/去高频"的真实图上**反而涨分**, 而真实模型在同样扰动下**掉分**
    -> 真实图的**高频通道正在误导合成模型** -> 卡点在高频/纹理 ->
       该做的是"给合成图补高频" (PASTA / 照片退化), 而不是重做渲染器内容;
  * 若合成模型在任何扰动下都**不涨甚至掉**, 说明它缺的不是某个频带, 而是**内容语义**
    (真实商品有包装纹理, 合成是白盒) -> 该投渲染器/纹理素材。

产物: output/benchmark/input_probe.json / .md -> docs/research/benchmark/

用法:
    python pipelines/shelf_sdg/55_input_probe.py --n 800
"""
import argparse
import json
import os
import shutil
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
REAL_YAML = os.environ.get("SKU110K_YAML", "SKU-110K.yaml")
OUT_DIR = os.path.join(BENCH, "input_probe")
OUT_JSON = os.path.join(BENCH, "input_probe.json")

MODELS = {
    "synth_R1": os.path.join(BENCH, "runs_r1_s43", "train", "weights", "best.pt"),
    "real_411": os.path.join(BENCH, "budget_runs_real0.05_synth0", "train",
                             "weights", "last.pt"),
}
VARIANTS = ["orig", "blur2", "blur4", "jpeg30", "noise20", "half_res"]
VAR_DESC = {
    "orig": "原图 (参照)",
    "blur2": "高斯模糊 σ=2 (削高频)",
    "blur4": "高斯模糊 σ=4 (削更多高频)",
    "jpeg30": "JPEG 质量 30 重编码 (丢高频+块效应)",
    "noise20": "加高斯噪声 σ=20 (补高频)",
    "half_res": "降采样到 50% 再放大 (丢细节)",
}


def log(m):
    print(f"[INP {time.strftime('%m-%d %H:%M:%S')}] {m}", flush=True)


def dataset_dirs():
    p = REAL_YAML if os.path.isabs(REAL_YAML) else os.path.join(BASE, REAL_YAML)
    d = os.path.dirname(p)
    with open(os.path.join(d, "test.txt"), "r", encoding="utf-8") as fh:
        items = [l.strip() for l in fh if l.strip()]
    return d, items


def build_variant(root, variant, n):
    """把真实 test 的前 n 张做成一个扰动版本 (图改, 标签原样)。"""
    from PIL import Image, ImageFilter
    import numpy as np
    d, items = dataset_dirs()
    vd = os.path.join(root, variant)
    if os.path.isdir(vd) and len(os.listdir(os.path.join(vd, "images"))) >= n:
        log(f"扰动集 {variant} 已存在, 复用")
        with open(os.path.join(vd, "dataset.yaml"), "w", encoding="utf-8") as fh:
            fh.write(f"path: {vd}\ntrain: images\nval: images\nnc: 1\nnames: [product]\n")
        return vd
    os.makedirs(os.path.join(vd, "images"), exist_ok=True)
    os.makedirs(os.path.join(vd, "labels"), exist_ok=True)
    used = 0
    for rel in items:
        if used >= n:
            break
        src = os.path.join(d, rel)
        if not os.path.isfile(src):
            continue
        name = os.path.splitext(os.path.basename(rel))[0]
        lbl = os.path.join(d, "labels", name + ".txt")
        if not os.path.isfile(lbl):
            continue
        im = Image.open(src).convert("RGB")
        if variant == "blur2":
            im = im.filter(ImageFilter.GaussianBlur(2.0))
        elif variant == "blur4":
            im = im.filter(ImageFilter.GaussianBlur(4.0))
        elif variant == "jpeg30":
            import io
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=30)
            buf.seek(0)
            im = Image.open(buf).convert("RGB")
        elif variant == "noise20":
            a = np.asarray(im, dtype=np.float32)
            rng = np.random.default_rng(abs(hash(name)) % (2 ** 31))
            a = a + rng.normal(0, 20.0, a.shape)
            im = Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
        elif variant == "half_res":
            w, h = im.size
            im = im.resize((max(1, w // 2), max(1, h // 2)), Image.BILINEAR)
            im = im.resize((w, h), Image.BILINEAR)
        im.save(os.path.join(vd, "images", name + ".jpg"), quality=95)
        shutil.copy2(lbl, os.path.join(vd, "labels", name + ".txt"))
        used += 1
    with open(os.path.join(vd, "dataset.yaml"), "w", encoding="utf-8") as fh:
        # ultralytics 的 check_det_dataset 要求 yaml 里**同时**有 train 与 val,
        # 只写 val 会在加载时抛 "'train:' key missing"。这里 train 指向同一批图
        # (我们只做评测, 不用它训练)。
        fh.write(f"path: {vd}\ntrain: images\nval: images\nnc: 1\nnames: [product]\n")
    log(f"扰动集 {variant}: {used} 张 -> {vd}")
    return vd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=800, help="test 子集大小")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    # 2026-11-25: **多模型**复核 —— 原来的探针只有 1 个合成模型 (R1 seed 43),
    #   "模糊真实图让合成模型涨 1.73 pp" 这个结论 (以及由它推出的训练期模糊臂)
    #   都建立在一个模型上。这里可以多跑几个 seed, 看这个反应是不是**模型稳健**。
    #   --out-suffix 让复核写到**另一个产物** (input_probe_multimodel.json),
    #   不覆盖已发布的 input_probe.json。
    ap.add_argument("--synth-seeds", default="",
                    help="逗号分隔的 R1 seed, 额外加进模型表 (如 44,45)")
    ap.add_argument("--out-suffix", default="",
                    help="产物文件名后缀 (复核用, 避免覆盖已发布结果)")
    args = ap.parse_args()
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    models = dict(MODELS)
    for sd in [x.strip() for x in args.synth_seeds.split(",") if x.strip()]:
        p = os.path.join(BENCH, f"runs_r1_s{sd}", "train", "weights", "best.pt")
        if os.path.isfile(p):
            models[f"synth_R1_s{sd}"] = p
        else:
            log(f"R1 seed {sd} 权重缺失, 跳过: {p}")

    from ultralytics import YOLO
    root = OUT_DIR
    os.makedirs(root, exist_ok=True)
    res = {}
    # 2026-11-25: **按 (模型, 扰动) 合并**, 别覆盖 —— 探针之前是整份覆盖写, 分两次跑
    # (先 orig/blur2/blur4, 再补别的扰动) 后一次会把前一次的行冲掉, 而报告里看不出
    # 少了行 (multi-seed-aggregation-pitfalls 同款坑)。
    out_json_pre = OUT_JSON if not args.out_suffix else OUT_JSON.replace(".json", f"{args.out_suffix}.json")
    if os.path.isfile(out_json_pre):
        try:
            prev_res = json.load(open(out_json_pre, encoding="utf-8")).get("results", {})
            if prev_res:
                log(f"已有产物含 {len(prev_res)} 行, 按 (模型,扰动) 合并")
            res.update(prev_res)
        except Exception as e:
            log(f"旧产物读不了 ({type(e).__name__}), 从头算")
    for v in variants:
        vd = build_variant(root, v, args.n)
        yaml = os.path.join(vd, "dataset.yaml")
        for mname, ckpt in models.items():
            if not os.path.isfile(ckpt):
                log(f"权重缺失 {ckpt}, 跳过")
                continue
            m = YOLO(ckpt)
            r = m.val(data=yaml, split="val", imgsz=640, batch=4, device="0",
                      max_det=1000, workers=2, verbose=False)
            key = f"{mname}|{v}"
            res[key] = {"model": mname, "variant": v, "map50": float(r.box.map50),
                        "map50_95": float(r.box.map),
                        # 2026-11-25: 记 precision / recall —— 判读扰动的**机制**要靠它:
                        # 若"模糊让合成模型涨分"来自 recall 上升 -> 是定位被规整化;
                        # 若来自 precision 上升 -> 是真实照片的高频杂乱触发了误检,
                        # 那么该修的是**背景/杂乱**, 不是商品表面。两者的下一步完全不同。
                        "precision": float(r.box.mp), "recall": float(r.box.mr)}
            log(f"{mname} @ {v}: mAP50 = {res[key]['map50']:.4f} "
                f"P = {res[key]['precision']:.4f} R = {res[key]['recall']:.4f}")

    # 判读。**判据范围 = 产物里实际存在的扰动** (合并进来的旧行也算), 不能只看本次
    # 请求的 variants —— 否则补跑一次就把"最佳扰动"的判读缩回本次范围。
    all_variants = sorted({r["variant"] for r in res.values()},
                           key=lambda v: (v != "orig", v))
    verdict = {}
    for mname in models:
        base = res.get(f"{mname}|orig")
        if not base:
            continue
        deltas = {v: round((res[f"{mname}|{v}"]["map50"] - base["map50"]) * 100, 2)
                  for v in all_variants if v != "orig" and f"{mname}|{v}" in res}
        best_v = max(deltas, key=deltas.get) if deltas else None
        # 机制判读: 最佳扰动带来的涨分是**precision** 还是 **recall** 涨出来的
        pr = None
        if best_v and f"{mname}|{best_v}" in res:
            b, n = res[f"{mname}|orig"], res[f"{mname}|{best_v}"]
            if "precision" in b and "precision" in n:
                pr = {"delta_precision_pp": round((n["precision"] - b["precision"]) * 100, 2),
                      "delta_recall_pp": round((n["recall"] - b["recall"]) * 100, 2)}
        verdict[mname] = {"orig_map50": base["map50"], "delta_pp": deltas,
                          "best_variant": best_v,
                          "best_delta_pp": deltas.get(best_v) if best_v else None,
                          "best_mechanism": pr}
    syn = verdict.get("synth_R1", {})
    rl = verdict.get("real_411", {})
    syn_best = syn.get("best_delta_pp") or 0.0
    rl_best = rl.get("best_delta_pp") or 0.0
    if syn_best > 1.0:
        conclusion = ("合成模型在扰动后的真实图上**涨分** -> 卡点在**高频/纹理通道**: "
                      "真实照片的高频细节在误导它 -> 该做的是给合成图补高频 (PASTA/照片退化)")
    elif syn_best < -1.0:
        conclusion = ("合成模型在所有扰动下都**掉分** -> 缺口不是某个频带, 而是**内容语义** "
                      "(真实商品有包装/纹理, 合成是无纹理白盒) -> 该投渲染器/纹理素材")
    else:
        conclusion = ("合成模型对输入扰动基本**不敏感** (±1 pp 内) -> 缺口既不在高频也不在"
                      "低频, 更像是**全局外观/风格** -> 需要更贴近真实分布的渲染 (材质/光照/"
                      "背景/相机), 或改走'真实图增强'路线")
    rep = {"schema": "input_probe/1",
           "generated_by": "pipelines/shelf_sdg/55_input_probe.py",
           "measured_at": "2026-11-25", "n_images": args.n,
           "variants": VAR_DESC,
           "models": {k: v for k, v in models.items()},
           "results": res, "verdict": verdict, "conclusion": conclusion,
           "note": ("只扰动输入, 不重训; 标签原样 -> mAP 变化纯粹来自输入分布。"
                    "合成模型与真实模型对同一扰动的反应差异是判读依据。"
                    "所有版本 (含 orig) 都按 JPEG q95 重存一次, 所以 orig 与各扰动版之间"
                    "只差扰动本身 (重编码对所有版本一致)。")}
    out_json = OUT_JSON if not args.out_suffix else OUT_JSON.replace(".json", f"{args.out_suffix}.json")
    out_md = os.path.join(BENCH, "input_probe.md") if not args.out_suffix else \
        os.path.join(BENCH, f"input_probe{args.out_suffix}.md")
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    os.makedirs(PUB, exist_ok=True)
    shutil.copy2(out_json, os.path.join(PUB, os.path.basename(out_json)))

    lines = ["# 输入扰动探针: 合成模型卡在哪条通道上 (2026-11-25)", "",
             f"真实 test 前 {args.n} 张, 只扰动输入 (标签原样), 两个模型分别评。", "",
             "| 扰动 | " + " | ".join(f"{m} mAP50" for m in models) + " |",
             "|---|" + "---|" * len(models)]
    for v in variants:
        row = [VAR_DESC.get(v, v)]
        for mname in models:
            r = res.get(f"{mname}|{v}")
            row.append(f"{r['map50']:.4f}" if r else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", "**相对原图的变化 (pp)**", "",
              "| 扰动 | " + " | ".join(f"{m} Δ" for m in models) + " |",
              "|---|" + "---|" * len(models)]
    for v in variants:
        if v == "orig":
            continue
        row = [VAR_DESC.get(v, v)]
        for mname in models:
            d = verdict.get(mname, {}).get("delta_pp", {}).get(v)
            row.append(f"{d:+.2f}" if d is not None else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", f"**结论**: {conclusion}"]
    md = "\n".join(lines) + "\n"
    with open(out_md, "w", encoding="utf-8") as fh:
        fh.write(md)
    shutil.copy2(out_md, os.path.join(PUB, os.path.basename(out_md)))
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
