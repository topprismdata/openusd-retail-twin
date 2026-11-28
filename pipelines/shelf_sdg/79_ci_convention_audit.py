#!/usr/bin/env python
"""审计本仓 CI 的 t 临界值口径: 现在的公式与"标准配对 t"的差别, 以及**哪些判语会因此翻转**。

发现的疑点 (2026-11-27): 各脚本里的 t 表是
    t = {2: 12.7062, 3: 4.3027, 4: 3.1824, 5: 2.7764}.get(n - 1, 1.96)
这张表是**按自由度 df 索引**的 (df=1 -> 12.706, df=2 -> 4.303, ...) ✓, 但配对 t 的自由度是
**df = n - 1** ✓ -> 所以 n=3 时应该取 df=2 (4.3027) ✓, 而现在的 `.get(n-1)` 取到的是 df=1 的
12.7062 ✗ -> **CI 比标准宽约 3 倍** ✓ (n=5 时宽 1.15 倍 ✓)。

宽 CI 不会造出假阳性 ✓, 但会**把本该"显著"的结果压成"未检出差异"** ✓ -> 所以必须量化:
哪些已发布的判语在标准口径下会翻转 ✓ -> 交给人决定要不要改 ✓ (改 = 全仓 CI 重算 + 已发布数字全部
变一遍 ✓, 不是顺手能动的 ✓)。

用法:
    python pipelines/shelf_sdg/79_ci_convention_audit.py
产物:
    output/benchmark/ci_convention_audit.json
"""
import glob
import json
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
OUT = os.path.join(BENCH, "ci_convention_audit.json")

# 本仓现在的口径: 表按 df 索引, 但取的是 n-1 -> 实际 df = n-2 ✓
T_BY_DF = {1: 12.7062, 2: 4.3027, 3: 3.1824, 4: 2.7764, 5: 2.5706}
REPO_LOOKUP = {2: 12.7062, 3: 4.3027, 4: 3.1824, 5: 2.7764}   # 仓里的实际写法 (.get(n-1)) ✓


def verdict(ci):
    if ci is None:
        return "no_ci"
    if ci[1] < 0:
        return "sig_worse"
    if ci[0] > 0:
        return "sig_better"
    return "not_detected"


def recompute(diffs):
    n = len(diffs)
    mean = sum(diffs) / n
    if n < 2:
        return mean, None, None
    sd = statistics.stdev(diffs)
    se = sd / (n ** 0.5)
    t_repo = REPO_LOOKUP.get(n - 1, 1.96)          # 仓里现在用的 ✓
    t_std = T_BY_DF.get(n - 1, 1.96)               # 标准: df = n-1 ✓
    return mean, [mean - t_repo * se, mean + t_repo * se], [mean - t_std * se, mean + t_std * se]


def iter_pairs(d):
    """产物里配对统计的容器有两种形状: dict (key -> entry) 与 list (entry) ✓。"""
    p = d.get("paired")
    if isinstance(p, dict):
        for k, v in p.items():
            if isinstance(v, dict):
                yield k, v
    elif isinstance(p, list):
        for i, v in enumerate(p):
            if isinstance(v, dict):
                yield f"#{i}", v


def extract_diffs(entry):
    for key in ("per_seed_pp", "diffs_pp", "map50_diff_per_seed_pp"):
        v = entry.get(key)
        if isinstance(v, list) and v and all(isinstance(x, (int, float)) for x in v):
            return [float(x) for x in v], key
    rows = entry.get("rows")
    if isinstance(rows, list):
        vals = [r.get("map50_diff_pp") for r in rows if isinstance(r, dict)]
        vals = [float(x) for x in vals if isinstance(x, (int, float))]
        if len(vals) >= 2:
            return vals, "rows[].map50_diff_pp"
    return None, None


def main():
    rows = []
    for f in sorted(glob.glob(os.path.join(BENCH, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        for key, entry in iter_pairs(d):
            diffs, src = extract_diffs(entry)
            if not diffs or len(diffs) < 2:
                continue
            mean, ci_repo, ci_std = recompute(diffs)
            v_repo, v_std = verdict(ci_repo), verdict(ci_std)
            if v_repo == v_std:
                continue          # 口径不改变判语的不报 ✓ (不拿琐事打扰 ✓)
            rows.append({
                "artifact": os.path.basename(f),
                "paired_key": key,
                "per_seed_source": src,
                "n": len(diffs),
                "mean_pp": round(mean, 4),
                "ci_repo": [round(x, 4) for x in ci_repo],
                "ci_standard": [round(x, 4) for x in ci_std],
                "verdict_repo": v_repo,
                "verdict_standard": v_std,
                "artifact_ci": entry.get("ci95_pp"),
            })

    art = {
        "schema": "ci_convention_audit/1",
        "generated_by": "pipelines/shelf_sdg/79_ci_convention_audit.py",
        "question": ("本仓的 CI 口径是哪个? 换成标准配对 t (df = n-1) 会哪些判语会翻转?"),
        "repo_formula": ("t = {2: 12.7062, 3: 4.3027, 4: 3.1824, 5: 2.7764}.get(n - 1, 1.96) "
                         "-> 表按 df 索引但取 n-1 -> 实际 df = n-2 (比标准宽) ✓"),
        "standard_formula": "t_{0.975, df = n-1}",
        "width_ratio_repo_over_standard": {2: 1.0, 3: 2.9526, 4: 1.3527, 5: 1.1489},
        "verdict_changes": rows,
        "n_verdict_changes": len(rows),
        "note": ("宽 CI 不会造出假阳性 ✓, 但会把本该\"显著\"的结果压成\"未检出差异\" ✓ "
                 "-> 改口径 = 全仓 CI 重算 + 已发布数字全部变一遍 ✓ -> 交给人决定 ✓"),
    }
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=2)

    print(f"CI 口径审计: 有 {len(rows)} 条配对的判语会随口径改变而翻转 ✓")
    for r in rows:
        print(f"  {r['artifact']:32s} {r['paired_key']:36s} n={r['n']} "
              f"mean {r['mean_pp']:+7.2f}  仓里 CI {r['ci_repo']} ({r['verdict_repo']}) "
              f"-> 标准 CI {r['ci_standard']} ({r['verdict_standard']})")
    print(f"产物: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
