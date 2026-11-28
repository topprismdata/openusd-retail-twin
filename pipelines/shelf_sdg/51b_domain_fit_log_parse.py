#!/usr/bin/env python
"""**51 号探针的日志还原器** (2026-11-25)。

为什么需要它
------------
51 号 `domain_fit_probe.py` 只在**全部评测跑完后**才写产物 (它要先把 summary 汇总好)。
但它一跑就是几个小时 (3 臂 × 3 seed × 2 权重 × 4 个评测集 = 72 次评测), 中途被机器
负载/超时杀掉的话, **已经跑完的几十次评测就全白费** —— 日志里有, 产物里没有。

本脚本把探针的**日志**按探针自己的 schema 还原成 `domain_fit_probe.json`:
* 只解析探针自己打印的行 (`  <臂> s<seed> <best|last>.pt -> <评测集>: <mAP50>`),
  所以数字**不是手写的**, 是探针输出的搬运;
* 探针跑完写出自己的产物后, 本脚本的产物会被覆盖 (以探针为准);
* 附 `--check` 只比对两边是否一致, 不写文件。

用法:
    python pipelines/shelf_sdg/51b_domain_fit_log_parse.py            # 写产物
    python pipelines/shelf_sdg/51b_domain_fit_log_parse.py --check    # 只比对
"""
import argparse
import json
import os
import re
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
LOG = os.path.join(BENCH, "domain_fit_probe.log")
OUT_JSON = os.path.join(BENCH, "domain_fit_probe.json")

OWN_POOL = {"r1": "pool_r1", "r1shape": "pool_shape", "r3pm": "pool_r3pm"}
EVAL_NAMES = ("pool_r1", "pool_shape", "pool_r3pm", "pool_big", "real_test")
PAT = re.compile(r"^  (\w+) s(\d+) (best\.pt|last\.pt) -> (\w+): ([0-9.]+)\s*$")


def parse_log(path):
    rows = {}
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = PAT.match(line.rstrip("\n"))
            if not m:
                continue
            arm, seed, ck, ev, val = m.group(1), int(m.group(2)), m.group(3), \
                m.group(4), float(m.group(5))
            key = (arm, seed, ck)
            r = rows.setdefault(key, {"arm": arm, "seed": seed, "ckpt": ck,
                                      "evals": {}})
            r["evals"][ev] = {"map50": val}
    return rows


def summarize(rows):
    arms = sorted({k[0] for k in rows})
    summary = {}
    for arm in arms:
        for ck in ("best.pt", "last.pt"):
            vals = {k: [] for k in EVAL_NAMES}
            for (a, _s, c), r in rows.items():
                if a != arm or c != ck:
                    continue
                for k in EVAL_NAMES:
                    e = r["evals"].get(k)
                    if e and "map50" in e:
                        vals[k].append(e["map50"])
            if not any(vals.values()):
                continue
            s = {k: ({"mean": round(statistics.mean(v), 4),
                      "sd": round(statistics.stdev(v), 4) if len(v) > 1 else 0.0,
                      "n": len(v)} if v else None)
                 for k, v in vals.items()}
            own = s.get(OWN_POOL.get(arm, "pool_r1"))
            rt = s.get("real_test")
            if own and rt:
                s["domain_fit_minus_transfer_pp"] = round(
                    (own["mean"] - rt["mean"]) * 100, 2)
            summary[f"{arm}/{ck}"] = s
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对, 不写文件")
    args = ap.parse_args()

    rows = parse_log(LOG)
    if not rows:
        print(f"日志里没有可解析的评测行: {LOG}")
        return 1
    summary = summarize(rows)
    n_ev = sum(len(r["evals"]) for r in rows.values())
    print(f"解析到 {len(rows)} 个 (臂,seed,权重) 组合, {n_ev} 次评测")
    for k, s in summary.items():
        own = s.get(OWN_POOL.get(k.split("/")[0], "pool_r1"))
        rt = s.get("real_test")
        print(f"  {k}: 域内 {own['mean'] if own else '—'} / 真实 "
              f"{rt['mean'] if rt else '—'}"
              + (f" (差 {s.get('domain_fit_minus_transfer_pp')} pp)" if own and rt else ""))

    if args.check:
        if os.path.exists(OUT_JSON):
            ref = json.load(open(OUT_JSON, encoding="utf-8"))
            rs = ref.get("summary") or {}
            bad = []
            for k, s in summary.items():
                if k in rs:
                    for f in ("mean", "n"):
                        for ev in EVAL_NAMES:
                            a = (s.get(ev) or {}).get(f)
                            b = ((rs[k].get(ev) or {}).get(f))
                            if a is not None and b is not None and a != b:
                                bad.append((k, ev, f, a, b))
            print(f"与产物比对: {'一致' if not bad else f'{len(bad)} 处不一致'}")
            for x in bad[:8]:
                print("   ", x)
        else:
            print("产物不存在, 无从比对")
        return 0

    rep = {"schema": "domain_fit_probe/1",
           "generated_by": "pipelines/shelf_sdg/51b_domain_fit_log_parse.py",
           "note": ("从 51 号探针的**日志**还原 (探针自己打印的评测行); "
                    "探针跑完后会用自己的产物覆盖本文件。"),
           "measured_at": "2026-11-25",
           "question": ("纯合成臂: 域内(自己池 val)能不能学会? 学会后到真实域还剩多少?"
                        " -> 决定下一步是修数据生成器还是投渲染真实度"),
           "arms": {k[0]: None for k in rows},
           "per_record": [rows[k] for k in sorted(rows)],
           "summary": summary}
    for p in (OUT_JSON, os.path.join(PUB, "domain_fit_probe.json")):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
    print(f"已写 {OUT_JSON}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
