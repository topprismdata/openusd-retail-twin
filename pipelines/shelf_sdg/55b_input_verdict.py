#!/usr/bin/env python
"""55 号输入扰动探针的**判读** (2026-11-25)。

为什么单独拆一个脚本
--------------------
判据是会随证据变化的 (比如再加一个模型、换一个扰动集), 而评测本身很贵 (12 次 val)。
把"算判读"从"跑评测"里拆出来, 就能在不重跑评测的前提下重算结论 —— 也避免
"结论写死在跑评测的脚本里"这种改不动的情况。

判读逻辑 (修正版)
------------------
关键前提: **同一张真实图**, 两个模型
  - `real_411` (真实图训练): 告诉我们"这个任务本身对某个输入通道敏不敏感";
  - `synth_R1` (合成图训练): 告诉我们"跨域那个模型对同一通道的反应"。
两者对同一扰动的**反应差**才是判据。

  1. 若 real_411 在"削高频"(blur/jpeg)下**掉很多** -> 高频通道对这个任务有用;
  2. 此时:
     - synth_R1 在同样扰动下**涨分** -> 真实照片的高频正在**误导**合成模型
       -> 卡点在高频/纹理, 修法: 给合成图补上匹配真实的高频 (PASTA / 照片退化);
     - synth_R1 **掉分** -> 合成模型**依赖**高频, 而合成图的高频统计与真实不同
       -> 同样是卡点在高频/纹理, 修法相同 (让合成图的高频统计追上真实图);
     - synth_R1 **几乎不变** -> 合成模型**根本没用**高频通道, 它栽在别处
       -> 卡点在内容/语义/全局风格, 该投渲染器 (商品纹理、包装、材质、相机);
  3. 若 real_411 在削高频下**也不敏感** -> 高频对这个任务不重要
     -> 频谱/Pasta 那一族干预不值得投, 该看内容与布局。

用法:
    python pipelines/shelf_sdg/55b_input_verdict.py
"""
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
SRC = os.path.join(BENCH, "input_probe.json")
BLUR = ("blur2", "blur4", "jpeg30")     # 削高频的扰动
ADD = ("noise20",)                     # 加高频的扰动
FLAT = ("half_res",)                   # 丢细节的扰动


def log(m):
    print(m, flush=True)


def main():
    if not os.path.exists(SRC):
        log(f"缺产物 {SRC}")
        return 1
    d = json.load(open(SRC, encoding="utf-8"))
    res = d.get("results") or {}
    var_desc = d.get("variants") or {}

    def get(model, variant):
        r = res.get(f"{model}|{variant}")
        return r["map50"] if r else None

    models = sorted({v["model"] for v in res.values()})
    syn = "synth_R1"
    real = "real_411"
    out = {"schema": "input_probe_verdict/1",
           "generated_by": "pipelines/shelf_sdg/55b_input_verdict.py",
           "measured_at": "2026-11-25",
           "source": "output/benchmark/input_probe.json"}

    def deltas(model):
        b = get(model, "orig")
        if b is None:
            return {}
        return {v: round((get(model, v) - b) * 100, 2)
                for v in var_desc if v != "orig" and get(model, v) is not None}

    out["delta_pp"] = {m: deltas(m) for m in models}
    ds, dr = out["delta_pp"].get(syn, {}), out["delta_pp"].get(real, {})

    real_blur = min([dr.get(v, 0) for v in BLUR], default=0.0)
    syn_blur = min([ds.get(v, 0) for v in BLUR], default=0.0)
    syn_blur_max = max([ds.get(v, 0) for v in BLUR], default=0.0)

    if real_blur <= -3.0:
        if syn_blur_max > 1.0:
            verdict = ("卡点在**高频/纹理通道**: 真实模型在削高频下明显掉分 (说明这个任务"
                       "用高频), 而合成模型在同样扰动下**涨分** -> 真实照片的高频正在"
                       "**误导**它。修法: 给合成图补上与真实匹配的高频统计 "
                       "(PASTA 振幅扰动 / 照片退化)。")
        elif syn_blur < -1.0:
            verdict = ("卡点在**高频/纹理通道**: 合成模型在削高频下**掉分** -> 它**依赖**"
                       "高频, 而合成图的高频统计与真实不同 (真实高频带高约 20 dB)。"
                       "修法同样是让合成图的高频统计追上真实图 (PASTA / 照片退化)。")
        else:
            verdict = ("合成模型对输入的高频通道**几乎不敏感** (±1 pp), 尽管真实模型很敏感"
                       " -> 它栽在别处: **内容/语义** (真实商品有包装纹理, 合成是无纹理白盒)。"
                       "该投渲染器/纹理素材, 而不是继续在频谱上加噪。")
    else:
        verdict = (f"真实模型在削高频下也不敏感 (最小 Δ {real_blur:+.2f} pp) -> "
                   "**高频对这个任务不重要**, 频谱/PASTA 那一族干预不值得投; "
                   "该看内容语义与全局外观 (材质/包装/背景/相机)。")

    out["real_blur_min_delta_pp"] = real_blur
    out["synth_blur_min_delta_pp"] = syn_blur
    out["synth_blur_max_delta_pp"] = syn_blur_max
    out["conclusion"] = verdict
    d["verdict"] = out
    d["conclusion"] = verdict
    with open(SRC, "w", encoding="utf-8") as fh:
        json.dump(d, fh, ensure_ascii=False, indent=2)
    shutil.copy2(SRC, os.path.join(PUB, "input_probe.json"))

    lines = ["# 输入扰动探针: 判读 (2026-11-25)", "",
             f"真实 test 前 {d.get('n_images')} 张, 只扰动输入 (标签原样)。", "",
             "| 扰动 | " + " | ".join(f"{m} mAP50" for m in models) +
             " | " + " | ".join(f"{m} Δ(pp)" for m in models) + " |",
             "|---|" + "---|" * (2 * len(models))]
    for v in var_desc:
        row = [var_desc.get(v, v)]
        for m in models:
            r = res.get(f"{m}|{v}")
            row.append(f"{r['map50']:.4f}" if r else "—")
        for m in models:
            row.append(f"{out['delta_pp'].get(m, {}).get(v, 0):+.2f}"
                       if v != "orig" and out["delta_pp"].get(m, {}).get(v) is not None
                       else "—")
        lines.append("| " + " | ".join(row) + " |")
    lines += ["", f"**结论**: {verdict}", "",
              "判读规则: 真实模型在削高频下掉多少 = 这个任务用不用高频; "
              "合成模型对同一扰动的反应 = 它栽在哪条通道。"]
    md = "\n".join(lines) + "\n"
    with open(os.path.join(BENCH, "input_probe_verdict.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    shutil.copy2(os.path.join(BENCH, "input_probe_verdict.md"),
                 os.path.join(PUB, "input_probe_verdict.md"))
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
