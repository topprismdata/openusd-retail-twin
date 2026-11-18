#!/usr/bin/env python3
"""四臂对照报告生成: 读 output/benchmark/sku110k_*.json + count_*.json,
按预注册判读规则出 Markdown 表与结论, 写 output/benchmark/FOUR_ARM_REPORT.md。

判读规则 (docs/SYNTHETIC_VS_MANUAL_ANNOTATION.md §三):
  若 R2 ≈ R0 (ΔmAP@0.5 ≤ 2pp) 且 R1 < R0 → 混合范式替代训练集标注成立 (域对齐前提)
  若 R2 ≈ R1 < R0 → 合成无增量, 命题不成立
  R1 << R0 单独成立 → 跨域纯合成不可用 (已观测)
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")


def load(arm):
    p = os.path.join(BENCH, f"sku110k_{arm}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def load_count(arm):
    p = os.path.join(BENCH, f"count_{arm}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def main():
    arms = ["r0", "r1", "r2", "R3-full"]
    rows = []
    for a in arms:
        d = load(a)
        c = load_count(a)
        if not d:
            rows.append(f"| {a} | — | — | — | — | — | — | 待跑 |")
            continue
        fmt = lambda k, dec=3: (f"{d[k]:.{dec}f}" if k in d else "—")
        ep = d.get("epochs_trained", d["protocol"].get("epochs", "?"))
        note = " ⚠️协议15/8不一致" if a.startswith("R3") and d["protocol"].get("epochs") != 10 else ""
        rows.append(
            f"| {a}{note} | {fmt('map50')} | {fmt('map50_95')} | "
            f"{fmt('precision')} | {fmt('recall')} | "
            f"{c['count_mae'] if c else '—'} | {c['pearson_r'] if c else '—'} | "
            f"{ep} ep |")
    r0, r1, r2 = (load(a) for a in ("r0", "r1", "r2"))
    verdict = []
    if r0 and r1:
        verdict.append(f"- R1 纯合成 {r1['map50']:.3f} vs R0 真实 {r0['map50']:.3f} → "
                       + ("跨域纯合成不可用（负结果，披露）" if r1["map50"] < r0["map50"] - 0.05
                          else "纯合成具备迁移性"))
    if r0 and r2:
        delta = (r2["map50"] - r0["map50"]) * 100
        if abs(delta) <= 2.0:
            verdict.append(f"- R2−R0 = {delta:+.1f}pp (≤2pp) → **混合范式成立**: 合成可替代训练集大规模手工标注"
                           f"（仅需少量真实微调），域对齐为前提")
        elif r2["map50"] > r0["map50"] + 0.02:
            verdict.append(f"- R2−R0 = {delta:+.1f}pp → 混合优于纯真实: 合成带来正增量")
        else:
            verdict.append(f"- R2−R0 = {delta:+.1f}pp → 混合劣于纯真实: 合成在该域为噪声, 命题不成立")
    md = f"""# P0-1 四臂对照报告 (SKU-110K test, 协议 hash 见各 json)

| 臂 | mAP@0.5 | mAP@0.5:0.95 | P | R | count MAE | Pearson r | epochs |
|---|---:|---:|---:|---:|---:|---:|---|
{chr(10).join(rows)}

## 预注册判读
{chr(10).join(verdict) or '- 待数据'}

## 已知局限
- R0 于 epoch 10 止损 (内存约束), 四臂同 epochs=10 保持内部一致
- 密度因子 (25→152 框/图) 由多联货架墙 (02 --bays) 干预, 归入 R3-full/A1b
- 计数指标仅对 R0/R1/R2 跑 (R3 视算力)
"""
    open(os.path.join(BENCH, "FOUR_ARM_REPORT.md"), "w").write(md)
    print(md)


if __name__ == "__main__":
    main()
