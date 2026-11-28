#!/usr/bin/env python
"""用 **官方** SimReady 验证器 (simready-validate) 跑本仓资产, 与自研闸门对照的前半段。

与本仓的关系:
- 官方工具装在**隔离环境**里 (官方 wheel 需要 usd-core; 本仓训练环境不带它,
  装了会动到训练协议 -> 违反"协议自证"纪律)。所以本脚本**不在**训练 venv 跑。
- 自研闸门那一半由 82 号脚本产出 (asset_self_gate.json), 84 号脚本做对照。

用法 (隔离环境):
    python pipelines/shelf_sdg/83_simready_official_validate.py -- \
        --subjects ours:output/usd/demo_classic/Product.usda \
        --subjects usdcraft:assets/usdcraft/rigid/.../physx/model.usdc
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "output", "benchmark", "simready_official_validation.json")


def _dump(obj):
    """把官方结果对象转成可 JSON 化的结构 (尽量保留 requirement 细节)。"""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_dump(v) for v in obj]
    if hasattr(obj, "__dict__"):
        return {str(k): _dump(v) for k, v in vars(obj).items() if not str(k).startswith("_")}
    return str(obj)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    subjects = []
    only_profiles = None
    out_path = OUT
    for i, a in enumerate(argv):
        if a == "--subjects" and i + 1 < len(argv):
            tag, _, rel = argv[i + 1].partition(":")
            subjects.append((tag, rel))
        elif a == "--profiles" and i + 1 < len(argv):
            only_profiles = [p for p in argv[i + 1].split(",") if p]
        elif a == "--out" and i + 1 < len(argv):
            out_path = argv[i + 1]
            if not os.path.isabs(out_path):
                out_path = os.path.join(BASE, out_path)
    if not subjects:
        print("no --subjects given")
        return 2

    import simready.validate as sv

    sv.initialize([], [], [])
    profiles = sv.get_available_profiles()
    if only_profiles:
        profiles = {k: v for k, v in profiles.items() if k in only_profiles}
    print(f"[SIMREADY] version={getattr(sv, '__version__', '?')} profiles={len(profiles)}")
    for pid, vers in list(profiles.items())[:40]:
        print(f"  profile {pid}: {vers}")

    rows = []
    for tag, rel in subjects:
        path = rel if os.path.isabs(rel) else os.path.join(BASE, rel)
        if not os.path.exists(path):
            rows.append({"tag": tag, "path": rel, "error": "asset_not_found"})
            print(f"  [MISS] {tag} {rel}")
            continue
        for pid, vers in profiles.items():
            if isinstance(vers, dict):
                # profiles 是 {version: spec}; 取最高版本
                def _key(v):
                    try:
                        return tuple(int(x) for x in str(v).split("."))
                    except Exception:
                        return (0,)
                version = max(vers.keys(), key=_key) if vers else None
            elif isinstance(vers, (list, tuple)):
                version = vers[0] if vers else None
            else:
                version = None
            t0 = time.time()
            try:
                result = sv.validate_stage_against_profiles(
                    __import__("pxr").Usd.Stage.Open(path),
                    [sv.ProfileTarget(pid, version)] if version else [sv.ProfileTarget(pid)],
                    asset_path=path,
                )
                res = result[0] if isinstance(result, list) and result else result
            except Exception as e:  # 官方工具的错误要保留原样, 不吞
                rows.append({"tag": tag, "path": rel, "profile": pid, "profile_version": version,
                             "error": f"{type(e).__name__}: {e}"})
                print(f"  [ERR ] {tag} {pid}: {type(e).__name__}: {e}")
                continue
            if res is None:
                rows.append({"tag": tag, "path": rel, "profile": pid, "profile_version": version,
                             "result": None, "note": "unavailable_execution (不是 measured failure)"})
                print(f"  [NONE] {tag} {pid}")
                continue
            summary = getattr(res, "features_summary", None)
            try:
                passed = bool(sv.features_summary_passed(summary)) if summary else None
            except Exception:
                passed = None
            features = _dump(summary) if summary else {}
            blocking = []
            failed = []
            for name, entry in (summary or {}).items():
                try:
                    if sv.is_blocking_failure(entry):
                        blocking.append(name)
                except Exception:
                    pass
                if isinstance(entry, dict) and entry.get("passed") is False:
                    failed.append(name)
            rows.append({
                "tag": tag, "path": rel, "profile": pid, "profile_version": version,
                "passed": passed, "blocking_failures": blocking, "failed_features": failed,
                "features_summary": features,
                "elapsed_s": round(time.time() - t0, 3),
            })
            print(f"  [{'PASS' if passed else ('FAIL' if passed is False else 'NONE')}] {tag} {pid} "
                  f"failed={len(failed)} blocking={len(blocking)} {time.time()-t0:.1f}s")

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "pipelines/shelf_sdg/83_simready_official_validate.py",
        "tool": {"package": "simready-validate", "version": getattr(sv, "__version__", "?"),
                 "license": "Apache-2.0",
                 "env": "隔离 venv (Temp/srvenv) —— 官方 wheel 需要 usd-core, 不装进训练 venv"},
        "profiles_available": {k: (v if isinstance(v, (list, tuple)) else [v]) for k, v in profiles.items()},
        "subjects": [{"tag": t, "path": p} for t, p in subjects],
        "results": rows,
        "not_done": [
            "未跑 simready-benchmark (需 Isaac Sim 6.1 + Linux/Windows x86-64, 本机没有)",
            "未跑官方 simready-manage (未安装) —— simready-package 已在 85/86 号跑过 ✓",
            "未对全部 200 件 USDCraft 资产跑全量 (只取样例)",
            "未安装 usd-profiles-nvidia 的其它 tier wheel (只用默认 catalog)",
        ],
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"[SIMREADY] -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
