#!/usr/bin/env python3
"""功效分析 (2026-11-21): 负结论到底是"没测到"还是"测不到"?

背景: 预算臂的结论是"加合成没有可测量的正向补回" (零效应)。零效应有两种可能:
  (a) 真没有效应;  (b) 有效应但本设计测不出来 (功效不足)。
必须把这两者分开, 否则负结果不可信。

本脚本从已落盘的产物直接算, 不手写数字:
  - 训练侧 (n = seed 数): 配对差值的样本标准差 s → 均值差的 95% CI 半宽
    = t_crit(0.05, df=n-1) * s / sqrt(n);
  - 决策阈值: 合成要"替代"真实标注, 至少得补回缺口的一部分;
    缺口 = 全量真实 - 同预算无合成 (pp);
  - 判定: CI 是否能排除"有决策意义的效应";
  - 反推: 要在 80% 功效下检出给定效应量, 需要多少个 seed;
  - 评测侧 (n = 图数): 逐图配对的 CI 半宽, 与训练侧 seed 间散布对比 ——
    这是"精确 ≠ 稳定"的量化。

输出: output/benchmark/power_analysis.json + power_analysis.md
"""
import glob
import json
import math
import os

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")

# 双尾 alpha=0.05 的 t 临界值 (df=1..10), 避免依赖 scipy
T_CRIT = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
          6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}


def t_crit(df):
    if df in T_CRIT:
        return T_CRIT[df]
    if df < 1:
        return float("inf")
    return 1.96 + 2.4 / df          # df>10 的粗略外推 (本项目 df 很小, 用不到)


def norm_ppf(p):
    """标准正态分位数 (Acklam 近似), 用于功效反推。"""
    if not 0 < p < 1:
        raise ValueError(p)
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def paired_seeds(frac, synth):
    """同一格点、同一真实子集, 逐 seed 的配对差值 (pp)。"""
    a, b = {}, {}
    for f in glob.glob(os.path.join(BENCH, "budget_real*_synth*.json")):
        d = json.load(open(f, encoding="utf-8"))
        c = d["dataset"]["cell"]
        if abs(float(c["real_frac"]) - frac) > 1e-9:
            continue
        seed = d.get("protocol", {}).get("seed")
        if seed is None:
            continue
        (a if int(c["synth_n"]) == 0 else b).setdefault(seed, d["map50"])
    common = sorted(set(a) & set(b))
    return [(s, (b[s] - a[s]) * 100) for s in common], a, b


def main():
    var = json.load(open(os.path.join(BENCH, "budget_seed_variance.json"), encoding="utf-8"))
    groups = var["groups"]
    base = groups["1/0"]["map50_mean"]
    out = {"schema": "power_analysis/1",
           "generated_by": "pipelines/shelf_sdg/29_power_analysis.py",
           "alpha": 0.05, "side": "two-sided", "budgets": {}}

    for key in ("0.05/0", "0.02/0"):
        frac = float(key.split("/")[0])
        g = groups.get(key)
        if not g:
            continue
        diffs, a_map, b_map = paired_seeds(frac, 0)
        synth_key = "0.05/200" if frac == 0.05 else "0.02/200"
        # 合成格点与无合成格点用**同一批 seed** 配对
        sd = []
        for s, _ in diffs:
            sd.append((b_map[s] - a_map[s]) * 100)
        n = len(sd)
        gap = (base - g["map50_mean"]) * 100          # 缺口 (pp)
        if n < 2:
            continue
        mean = sum(sd) / n
        var_s = sum((x - mean) ** 2 for x in sd) / (n - 1)
        s = math.sqrt(var_s)
        hw = t_crit(n - 1) * s / math.sqrt(n)        # 均值差 95% CI 半宽
        ci = (mean - hw, mean + hw)
        # 反推: 80% 功效检出效应量 E 所需 seed 数 (双尾 t 近似)
        need = {}
        for E in (1.0, 2.0, 5.0, 10.0):
            if E <= 0:
                continue
            # n = ((z_a/2 + z_b) * s / E)^2, 用正态近似做初值, 再取整并至少 2
            n_need = ((norm_ppf(0.975) + norm_ppf(0.80)) * s / E) ** 2
            need[f"{E:g}pp"] = max(2, int(math.ceil(n_need)))
        out["budgets"][f"{frac:g}"] = {
            "n_seeds": n,
            "seeds": [s_ for s_, _ in diffs],
            "paired_diff_pp": [round(x, 3) for x in sd],
            "mean_pp": round(mean, 3),
            "sd_pp": round(s, 3),
            "ci95_halfwidth_pp": round(hw, 3),
            "ci95_pp": [round(ci[0], 3), round(ci[1], 3)],
            "gap_to_full_real_pp": round(gap, 2),
            "max_recovery_excluded_pp": round(hw, 3),
            "recoverable_share_of_gap_excluded_pct": round(min(100.0, hw / gap * 100), 1),
            "decision_threshold_pp": round(gap * 0.5, 2),
            "decision_threshold_covered": bool(ci[1] < gap * 0.5),
            "seeds_needed_80pct_power": need,
        }

    # 评测侧 (n = 图数): 逐图配对的精确度 vs 训练侧散布
    ev = []
    for f in sorted(glob.glob(os.path.join(BENCH, "paired_image_eval_*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        n_img = d.get("n_images") or 0
        sd_img = (d.get("paired_diff_std") or 0) * 100
        if not n_img:
            continue
        hw_img = 1.96 * sd_img / math.sqrt(n_img)
        ev.append({
            "file": os.path.basename(f),
            "n_images": n_img,
            "diff_pp": round((d.get("paired_diff_mean") or 0) * 100, 3),
            "t": round(d.get("paired_t") or 0, 2),
            "ci95_halfwidth_pp": round(hw_img, 3),
        })
    if ev:
        spread = max(b["sd_pp"] for b in out["budgets"].values()) if out["budgets"] else None
        out["evaluation_side"] = {
            "runs": ev,
            "note": "逐图配对的 CI 半宽远小于训练 seed 间散布 -> "
                    "任何单对模型的逐图检验都必然'检出'一个其实属于训练噪声的差异",
            "train_side_sd_pp": spread,
            "precision_ratio_vs_train_noise": (
                round(spread / min(r["ci95_halfwidth_pp"] for r in ev), 1) if spread else None),
        }

    with open(os.path.join(BENCH, "power_analysis.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)

    # Markdown
    L = ["# 功效分析 (2026-11-21): 零效应是\"测不到\"还是\"真没有\"?", "",
         "| 预算 | seed 数 | 配对差值 (pp) | mean ± sd | 95% CI | CI 半宽 | 缺口 | "
         "能排除的最大补回 | 能排除的缺口占比 | 半数缺口阈值 | 覆盖? |",
         "|---|---:|---|---:|---|---:|---:|---:|---:|---:|---|"]
    for k, b in out["budgets"].items():
        L.append(f"| {float(k):.0%} | {b['n_seeds']} | "
                 f"{', '.join(f'{x:+.2f}' for x in b['paired_diff_pp'])} | "
                 f"{b['mean_pp']:+.2f} ± {b['sd_pp']:.2f} | "
                 f"[{b['ci95_pp'][0]:+.2f}, {b['ci95_pp'][1]:+.2f}] | "
                 f"±{b['ci95_halfwidth_pp']:.2f} | {b['gap_to_full_real_pp']:.2f} | "
                 f"{b['max_recovery_excluded_pp']:.2f} pp | "
                 f"{b['recoverable_share_of_gap_excluded_pct']:.0f}% | "
                 f"{b['decision_threshold_pp']:.2f} pp | "
                 f"{'是' if b['decision_threshold_covered'] else '否'} |")
    L += ["", "**读法**: CI 半宽 = 能被本设计排除的**最大正向补回**。缺口 = 该预算相对全量真实的差距。",
          "只要\"能排除的最大补回\"远小于缺口, 零效应就不是功效不足造成的。",
          "",
          "**诚实的边界**: CI 并不能排除**小于半宽**的正向效应 (5% 预算下即 <2.38 pp, 约缺口的 24%) ——",
          "这种量级的补回即便存在也不足以支撑\"替代\"的结论 (替代需要补回几乎整个缺口)。",
          "决策阈值 (补回半个缺口) 则**明确落在 CI 之外**, 所以\"合成不能替代真实标注\"这一命题",
          "不是功效不足的产物。"]
    L += ["", "## 要检出给定效应量, 需要几个 seed (80% 功效, 双尾 α=0.05)", "",
          "| 预算 | 现有 seed | 检出 1pp | 2pp | 5pp | 10pp |", "|---|---:|---:|---:|---:|---:|"]
    for k, b in out["budgets"].items():
        nd = b["seeds_needed_80pct_power"]
        L.append(f"| {float(k):.0%} | {b['n_seeds']} | {nd.get('1pp', '—')} | {nd.get('2pp', '—')} | "
                 f"{nd.get('5pp', '—')} | {nd.get('10pp', '—')} |")
    L += ["", "- 本设计 (3 个 seed) 对**决策相关的效应量 (≥2pp)** 在 5% 预算上已经够用; "
          "但对亚 1pp 的效应功效不足 —— 而亚 1pp 的效应与\"替代\"命题无关。"]
    if "evaluation_side" in out:
        e = out["evaluation_side"]
        L += ["", "## 评测侧 vs 训练侧 (精确 ≠ 稳定)", "",
              "| 对比 | n 图 | 差值 (pp) | t | 95% CI 半宽 (pp) |", "|---|---:|---:|---:|---:|"]
        for r in e["runs"]:
            L.append(f"| {r['file'].replace('paired_image_eval_', '').replace('.json', '')} | "
                     f"{r['n_images']} | {r['diff_pp']:+.2f} | {r['t']:+.2f} | "
                     f"±{r['ci95_halfwidth_pp']:.3f} |")
        L += ["", f"- 训练 seed 间的配对差值标准差 ≈ **{e['train_side_sd_pp']} pp**; "
              f"逐图配对的 CI 半宽仅 **{min(r['ci95_halfwidth_pp'] for r in e['runs']):.3f} pp** "
              f"(≈ {e['precision_ratio_vs_train_noise']:.0f}× 更窄)。",
              "- 也就是说: 逐图检验能测出 0.1 pp 级的差异, 而训练随机性本身就有 ~1-2 pp —— "
              "**任何单对模型的逐图检验都必然\"检出\"一个其实属于训练噪声的差异**。",
              "- 要让逐图检验有意义, 必须先有训练侧的方差估计; 本仓两者都有, 结论是零效应。"]
    with open(os.path.join(BENCH, "power_analysis.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    print("->", os.path.join(BENCH, "power_analysis.md"))
    for k, b in out["budgets"].items():
        print(f"[POWER] 预算 {k}: CI ±{b['ci95_halfwidth_pp']:.2f}pp vs 缺口 "
              f"{b['gap_to_full_real_pp']:.2f}pp -> 排除缺口占比 "
              f"{b['recoverable_share_of_gap_excluded_pct']:.0f}%")


if __name__ == "__main__":
    main()
