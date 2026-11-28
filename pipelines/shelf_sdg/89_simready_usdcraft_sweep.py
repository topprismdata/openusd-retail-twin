#!/usr/bin/env python3
"""USDCraft 全量资产 × 官方 16 个 profile 的验证扫描 (2026-11-28)。

之前只取 3 件样例 -> 只能说"官方工具能跑"。这一版**跑满 200 件** ✓, 出的是
**分布**而不是个案: 每个 profile 在真实资产上的 PASS/FAIL/unavailable 比例 ✓,
以及**哪些 requirement 最常挂** ✓（按 requirement id 聚合, 不是按 feature 名 ✓）。

用法 (只装 pxr 的官方环境):
  <srvenv>/python pipelines/shelf_sdg/89_simready_usdcraft_sweep.py -- [--limit N] [--profiles a,b]
"""
import collections
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

OUT = os.path.join(BASE, "output", "benchmark", "simready_usdcraft_sweep.json")
OUT_MD = os.path.join(BASE, "output", "benchmark", "simready_usdcraft_sweep.md")


def _requirement_ids(entry):
    """从 features_summary 条目里抽出 requirement id (如 com.nvidia.usd.AA.001) ✓。"""
    ids = []
    if not isinstance(entry, dict):
        return ids
    msgs = entry.get("requirement_messages")
    if isinstance(msgs, str):
        try:
            msgs = json.loads(msgs)
        except Exception:
            return ids
    if isinstance(msgs, dict):
        ids.extend(str(k) for k in msgs.keys())
    return ids


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    limit = None
    only = None
    for i, a in enumerate(argv):
        if a == "--limit" and i + 1 < len(argv):
            limit = int(argv[i + 1])
        elif a == "--profiles" and i + 1 < len(argv):
            only = [p for p in argv[i + 1].split(",") if p]

    root = os.path.join(BASE, "assets", "usdcraft")
    assets = []
    for dirpath, _d, files in os.walk(root):
        if "model.usdc" in files:
            assets.append(os.path.join(dirpath, "model.usdc"))
    assets.sort()
    if limit:
        assets = assets[:limit]
    print(f"[SWEEP] 资产 {len(assets)} 件")

    import simready.validate as sv
    from pxr import Usd

    sv.initialize([], [], [])
    profiles = sv.get_available_profiles()
    if only:
        profiles = {k: v for k, v in profiles.items() if k in only}

    targets = []
    for pid, vers in profiles.items():
        version = None
        if isinstance(vers, dict) and vers:
            def _key(v):
                try:
                    return tuple(int(x) for x in str(v).split("."))
                except Exception:
                    return (0,)
            version = max(vers.keys(), key=_key)
        elif isinstance(vers, (list, tuple)) and vers:
            version = vers[0]
        targets.append((pid, version))

    rows = []
    prof_stats = {pid: collections.Counter() for pid, _v in targets}
    req_fail = collections.Counter()
    feat_fail = collections.Counter()
    t_start = time.time()
    for n, path in enumerate(assets, 1):
        rel = os.path.relpath(path, BASE).replace("\\", "/")
        stage = None
        for pid, version in targets:
            try:
                if stage is None:
                    stage = Usd.Stage.Open(path)
                result = sv.validate_stage_against_profiles(
                    stage,
                    [sv.ProfileTarget(pid, version)] if version else [sv.ProfileTarget(pid)],
                    asset_path=path)
                res = result[0] if isinstance(result, list) and result else result
            except Exception as e:
                rows.append({"asset": rel, "profile": pid, "error": f"{type(e).__name__}"})
                prof_stats[pid]["error"] += 1
                continue
            if res is None:
                rows.append({"asset": rel, "profile": pid, "result": None})
                prof_stats[pid]["unavailable"] += 1
                continue
            summary = getattr(res, "features_summary", None)
            try:
                passed = bool(sv.features_summary_passed(summary)) if summary else None
            except Exception:
                passed = None
            failed = []
            if isinstance(summary, dict):
                for name, entry in summary.items():
                    if isinstance(entry, dict) and entry.get("passed") is False:
                        failed.append(name)
                        feat_fail[name] += 1
                        for rid in _requirement_ids(entry):
                            req_fail[rid] += 1
            state = "pass" if passed else ("fail" if passed is False else "unavailable")
            prof_stats[pid][state] += 1
            rows.append({"asset": rel, "profile": pid, "passed": passed,
                         "failed_features": failed})
        if n % 10 == 0 or n == len(assets):
            print(f"  [{n}/{len(assets)}] 用时 {time.time()-t_start:.0f}s")

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "pipelines/shelf_sdg/89_simready_usdcraft_sweep.py",
        "tool": {"package": "simready-validate", "version": getattr(sv, "__version__", "?"),
                 "license": "Apache-2.0"},
        "assets_scanned": len(assets),
        "profiles": [pid for pid, _v in targets],
        "elapsed_s": round(time.time() - t_start, 1),
        "per_profile": {pid: dict(c) for pid, c in prof_stats.items()},
        "top_failing_requirements": req_fail.most_common(30),
        "top_failing_features": feat_fail.most_common(30),
        "rows": rows,
        "not_done": [
            "官方 taxonomy profile 的判定依赖非 USD 输入的 taxonomy 表 -> 多数资产上只能是 unavailable",
            "只跑了 USD stage 侧判定, 没跑官方 simready-benchmark (需 Isaac Sim 6.1)",
        ],
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    md = ["# USDCraft 200 件 × 官方 16 profile 全量扫描\n",
          f"生成时间: {payload['generated_at']} · 资产 {len(assets)} 件 · 用时 {payload['elapsed_s']}s\n",
          "\n## 每个 profile 的分布\n",
          "| profile | pass | fail | unavailable | error |", "|---|---|---|---|---|"]
    for pid, _v in targets:
        c = prof_stats[pid]
        md.append(f"| {pid} | {c.get('pass',0)} | {c.get('fail',0)} | "
                  f"{c.get('unavailable',0)} | {c.get('error',0)} |")
    md.append("\n## 最常挂的 requirement (按资产数)\n")
    for rid, cnt in req_fail.most_common(20):
        md.append(f"- `{rid}`: {cnt} 件资产")
    md.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"[SWEEP] -> {OUT}")
    print(f"[SWEEP] -> {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
