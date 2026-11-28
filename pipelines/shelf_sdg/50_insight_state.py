#!/usr/bin/env python
"""算出这个项目此刻的**决策相关状态** (2026-11-24)。

为什么要有这个脚本
----------------
主动性不是"想得多", 而是**持续掌握状态并据此排序**。靠记忆掌握状态必然漏: 跑着的任务
什么时候结束、闸门是不是红的、有没有新产物已经落地但还没写进文档、README 里哪些结论
还挂着 ⚠️ —— 这些都会在会话里漂移。这个脚本把它们**每次现算**, 产出给决策用的输入。

它算什么
--------
1. **在跑的任务**: 从进程命令行里认出本仓的流水线, 并读它们的进度产物 (渲了多少张 /
   训练到第几轮 / 已完成多少格点)。
2. **闸门状态**: 直接跑 28 号一致性检查, 报绿/红与检查项数。
3. **文档滞后**: 比 README 的修改时间与各产物的修改时间 -> "有结果已经落地, 但还没写
   进文档" 的清单 (这是最容易漏、也最该马上处理的一类洞)。
4. **README 里仍挂着的未闭合项**: 所有 ⚠️ / ❌ / 未闭合 / 待补测 的行号 + 摘要。

输出是**给人看的清单**, 不是自动结论; 结论由人或 agent 判断后写进
`docs/research/INSIGHT_QUEUE.md`。

用法:
    python pipelines/shelf_sdg/50_insight_state.py
    python pipelines/shelf_sdg/50_insight_state.py --json
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
README = os.path.join(BASE, "README.md")
PY = sys.executable

# 本仓的流水线脚本 (出现在命令行里就算在跑)
PIPES = ("57_texture_arm", "52_photorealism_probe", "55_input_probe",
         "62_texture_arm_diagnose", "64_shelfwall_arm", "64b_shelfwall_chain", "63_context_probe",
         "47_bigpool", "45_density", "21_annotation_budget", "02_shelf_sdg",
         "49_bigpool_anchor", "48_dose_pool",
         # 2026-11-26/27: I-19 / I-20 / I-22 / I-26 这几条臂与探针
         # (漏登记会让状态脚本把"正在跑"报成"没有在跑" ✓ -> 决策依据直接失真 ✓)
         "66_context_suppress_arm", "67_context_suppress_probe",
         "68_pretrain_finetune_arm", "69_mixstyle_arm",
         "70_ctxsupp_pool_parity", "71_recover_pf_arm",
         "73_real_budget_epoch_arm",
         # 2026-11-28: I-28 轮数轴饱和点探针 (漏登记 -> 状态脚本把"正在跑"报成"没有在跑" ✓)
         "81_epoch_saturation_probe", "82_epoch_saturation_report")


def sh(cmd, timeout=120):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return f"<{type(e).__name__}: {e}>"


def running_jobs():
    """在跑的本仓流水线 (进程命令行 + 各自的进度)。

    注意: 一个脚本会拉起子进程 (shim -> blender -> python), 所以同一条流水线会出现
    好几个 python.exe。按**脚本归组**只留一行, 否则状态看起来像跑了很多份。
    """
    ps = ("$ErrorActionPreference='SilentlyContinue';"
          "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "ForEach-Object { \"$($_.ProcessId)|$($_.CommandLine)\" }")
    out = sh(["powershell", "-NoProfile", "-Command", ps])
    grouped = {}
    for line in out.splitlines():
        if "|" not in line:
            continue
        pid, cl = line.split("|", 1)
        if not any(p in cl for p in PIPES):
            continue
        which = next((p for p in PIPES if p in cl), "?")
        g = grouped.setdefault(which, {"script": which, "pids": [], "cmd": cl.strip()[:150]})
        g["pids"].append(pid.strip())
    jobs = []
    for which, g in grouped.items():
        jobs.append({"script": which, "n_processes": len(g["pids"]),
                     "pids": g["pids"][:4], "cmd": g["cmd"],
                     "progress": job_progress(which)})
    return jobs


def job_progress(which):
    """从进度产物里读"到哪了" (能读到多少读多少, 读不到就写未知)。"""
    try:
        if which == "47_bigpool":
            n = len(glob.glob(os.path.join(BENCH, "sdg_bigpool", "images", "*", "*.png")))
            done = len(glob.glob(os.path.join(BENCH, "budget_real*_synth*_big_s*.json")))
            return {"rendered": f"{n}/2800", "grid_points_done": done, "grid_points_total": 48}
        if which == "45_density":
            runs = sorted(glob.glob(os.path.join(BENCH, "density_runs_*", "train", "results.csv")))
            out = []
            for r in runs:
                try:
                    rows = open(r, encoding="utf-8").read().strip().split("\n")
                    out.append(f"{os.path.basename(os.path.dirname(os.path.dirname(r)))}: "
                               f"{len(rows) - 1}/10 轮")
                except Exception:
                    pass
            return {"runs": out}
        if which.startswith("81_epoch_saturation"):
            runs = sorted(glob.glob(os.path.join(BENCH, "runs_pf_ctrld_s*", "train", "results.csv")))
            out = []
            for r in runs:
                try:
                    rows = open(r, encoding="utf-8").read().strip().split("\n")
                    out.append(f"{os.path.basename(os.path.dirname(os.path.dirname(r)))}: "
                               f"{len(rows) - 1}/80 轮")
                except Exception:
                    pass
            art = os.path.join(BENCH, "epoch_saturation_probe.json")
            done = []
            if os.path.isfile(art):
                try:
                    done = sorted((json.load(open(art, encoding="utf-8")).get("per_seed") or {}).keys())
                except Exception:
                    pass
            return {"runs": out, "seeds_finished": done}
        if which == "21_annotation_budget":
            return {"note": "单格点训练 (看 output/benchmark/budget_real*.json 的新增)"}
        if which == "02_shelf_sdg":
            return {"note": "渲染中 (看 sdg_bigpool/images 的新增张数)"}
        if which == "57_texture_arm":
            n = len(glob.glob(os.path.join(BENCH, "sdg_shelf_tex", "images", "train", "*.png")))
            seeds = sorted(glob.glob(os.path.join(BENCH, "runs_tex_s*", "train", "weights", "last.pt")))
            return {"rendered": f"{n}/200", "trained_seeds": len(seeds)}
        if which == "52_photorealism_probe":
            # 臂日志里每完成一个 seed 打一行 "真实 test mAP50" -> 数行数就知道跑到哪
            out = []
            for lg in ("syn2real_blurR_arms.log", "syn2real_blur_arms.log",
                       "syn2real_diversity_arms.log"):
                p = os.path.join(BENCH, lg)
                if os.path.isfile(p):
                    lines = [l for l in open(p, encoding="utf-8", errors="ignore")
                             if "mAP50 =" in l]
                    out.append(f"{lg}: {len(lines)} 个评测")
            return {"progress": out}
        if which == "55_input_probe":
            p = os.path.join(BENCH, "input_probe_multimodel_pr.log")
            n = 0
            if os.path.isfile(p):
                n = sum(1 for l in open(p, encoding="utf-8", errors="ignore")
                        if "mAP50 =" in l)
            return {"evals_done": n}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    return {}


def gate_status():
    """跑一致性闸门, 报绿/红。"""
    p = os.path.join(BASE, "pipelines", "shelf_sdg", "28_doc_consistency_check.py")
    try:
        r = subprocess.run([PY, p], capture_output=True, text=True, cwd=BASE, timeout=900)
        out = (r.stdout or "") + (r.stderr or "")
        checks = len(re.findall(r"^\[\d+[a-z]?\]", out, re.M))
        return {"ok": r.returncode == 0, "checks": checks,
                "problems": [x.strip(" -") for x in re.findall(r"^  - (.*)$", out, re.M)],
                "tail": out.strip().splitlines()[-1] if out.strip() else ""}
    except Exception as e:
        return {"ok": None, "error": f"{type(e).__name__}: {e}"}


def doc_lag():
    """结果已经落地, 但 README 还没更新的清单 (按新到旧)。

    只看**实验产物** (output/benchmark), 不看发布副本 (docs/research/benchmark) ——
    后者每次跑 26 号都会被原样拷一遍, 全是噪声, 会把真正的"结果已落地但文档没跟上"
    淹掉。
    """
    if not os.path.exists(README):
        return {"error": "README 不存在"}
    rmt = os.path.getmtime(README)
    items = []
    for pat in ("output/benchmark/*.json", "output/benchmark/density_curve.*"):
        for f in glob.glob(os.path.join(BASE, pat)):
            try:
                mt = os.path.getmtime(f)
            except OSError:
                continue
            if mt > rmt:
                # **臂还在跑的时候产物是逐 seed 增量写的** -> 它"比 README 新"没有意义
                # (README 本来就不该写半成品) -> 用产物自己声明的 seed 数判断 ✓
                # (不硬编码期望值 ✓; 产物没声明 seeds 就照旧计入 ✓)
                if f.endswith(".json"):
                    try:
                        d = json.load(open(f, encoding="utf-8"))
                    except Exception:
                        d = {}
                    exp = (d.get("design") or {}).get("seeds")
                    if exp and len(d.get("per_seed") or {}) < len(exp):
                        continue
                items.append({"file": os.path.relpath(f, BASE).replace("\\", "/"),
                              "age_min": round((time.time() - mt) / 60, 1)})
    items.sort(key=lambda x: -x["age_min"])
    return {"readme_mtime": time.strftime("%m-%d %H:%M", time.localtime(rmt)),
            "newer_than_readme": items[:40], "n_newer": len(items)}


def open_claims():
    """README 里仍挂着的未闭合项 (行号 + 摘要)。"""
    pat = re.compile(r"(⚠️|❌|未闭合|未重跑|待补测|正在补测|不可复现|缺)")
    out = []
    try:
        for i, line in enumerate(open(README, encoding="utf-8"), 1):
            if pat.search(line):
                out.append({"line": i, "text": line.strip()[:160]})
    except OSError as e:
        return {"error": str(e)}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    state = {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "jobs": running_jobs(),
        "gate": gate_status(),
        "doc_lag": doc_lag(),
        "open_claims": open_claims(),
    }
    if args.json:
        print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0

    print(f"=== 状态 {state['at']} ===")
    print(f"\n[1] 在跑的任务 ({len(state['jobs'])})")
    for j in state["jobs"]:
        # 注意: 一条流水线可能有多个 python 进程 (shim -> blender -> python),
        # 这里打印的是**进程组** (pids 列表), 不是单个 pid (旧代码按 j['pid'] 取值 ->
        # 键根本不存在, 状态脚本一跑就崩, 等于没有状态脚本)。
        print(f"  - {j['script']} (pid {','.join(j.get('pids') or ['?'])}): {j['progress']}")
    if not state["jobs"]:
        print("  (无)")
    g = state["gate"]
    print(f"\n[2] 闸门: {'绿 ✅' if g.get('ok') else '红 ❌' if g.get('ok') is False else '未知'} "
          f"({g.get('checks', '?')} 项检查)")
    for p in g.get("problems", [])[:10]:
        print(f"  ! {p}")
    dl = state["doc_lag"]
    print(f"\n[3] 文档滞后: README 修改于 {dl.get('readme_mtime')}; "
          f"有 {dl.get('n_newer', '?')} 个产物比它新")
    for it in dl.get("newer_than_readme", [])[:12]:
        print(f"  - {it['file']} ({it['age_min']:.0f} 分钟前)")
    oc = state["open_claims"]
    print(f"\n[4] README 里挂着的未闭合项 ({len(oc) if isinstance(oc, list) else '?'} 行)")
    for c in (oc if isinstance(oc, list) else [])[:12]:
        print(f"  - L{c['line']}: {c['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
