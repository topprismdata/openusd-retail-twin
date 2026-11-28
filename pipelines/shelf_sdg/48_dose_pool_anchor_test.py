#!/usr/bin/env python
"""剂量轴**锚点按池归属**的回归测试 (2026-11-24)。

背景
----
31 号按"合成池"分组汇总剂量-反应 (剂量轴必须是单变量: 池不变, 只有剂量在变)。
配对差值的基准是**同池的 0 档** (同 seed、同真实子集、不加合成), 所以 0 档锚点
必须**跟着自己的池走**。

曾经出过的真事故 (2026-11-24 修)
-------------------------------
老代码把 0 档一律塞给"行数最多的池"。大池剂量链 (47 号) 是 8 档 x 3 seed, 行数必然
超过老池 -> 0 档锚点被抢走 -> **老池曲线因为没有基准而整条消失** (报告照出, 只是少
了一条曲线, 属于静默失败)。现在 21 号为 0 档也记 synth_pool, 31 号按它归属。

这个测试做什么
--------------
真实产物要等大池 (47 号) 跑完才有"两个池"的场景, 而那要十几个小时。所以这里在临时
目录里**伪造**一个大池 (8 档 x 3 seed + 自己的 0 档锚点), 跑 31 号的 collect(),
断言:

  1. 两个池都出现;
  2. **每个池都保住自己的 0 档锚点**, 且锚点数值来自自己的产物;
  3. 老池的档位与斜率不受大池影响。

同时复刻一次老逻辑, 证明"锚点被抢"确实会让老池曲线塌成 0 条剂量行 —— 即这个测试
守的是一条真会被踩的规则, 而不是自己发明的规则。

用法: python pipelines/shelf_sdg/48_dose_pool_anchor_test.py
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)

_spec = importlib.util.spec_from_file_location(
    "dose31", os.path.join(BASE, "pipelines", "shelf_sdg", "31_dose_response.py"))
d31 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(d31)

BENCH_REAL = os.path.join(BASE, "output", "benchmark")
BIG_SHA = "f" * 64          # 伪造的大池指纹

fails = []


def check(cond, msg):
    print(("  OK   " if cond else "  FAIL ") + msg)
    if not cond:
        fails.append(msg)


def make_fake_bench(tmp):
    """造一个 BENCH: 真实的老池产物 + 伪造的大池产物。"""
    bench = os.path.join(tmp, "benchmark")
    os.makedirs(bench)
    for f in os.listdir(BENCH_REAL):
        if f.startswith("budget_real") and f.endswith(".json"):
            shutil.copy(os.path.join(BENCH_REAL, f), bench)
    shutil.copytree(os.path.join(BENCH_REAL, "budget"), os.path.join(bench, "budget"))
    for dose in (0, 40, 80, 160, 320, 640, 1280, 2240):
        for seed in (42, 43, 44):
            art = {
                "arm": f"budget:real0.05_synth{dose}_big_s{seed}",
                "dataset": {"cell": {"real_frac": 0.05, "synth_n": dose},
                            "n_real": 411, "n_synth": dose,
                            "synth_pool": {"path": "fake_bigpool", "n_images": 2240,
                                           "names_sha256": BIG_SHA}},
                "protocol": {"seed": seed, "epochs": 10, "select": "last",
                             "budget_seed": 20261120, "real_frac": 0.05, "synth_n": dose},
                "map50": 0.80 + 0.001 * dose + 0.002 * (seed - 42),
            }
            with open(os.path.join(bench, f"budget_real0.05_synth{dose}_big_s{seed}.json"),
                      "w", encoding="utf-8") as fh:
                json.dump(art, fh, ensure_ascii=False)
    return bench


def main():
    tmp = tempfile.mkdtemp(prefix="dose_pool_anchor_")
    try:
        bench = make_fake_bench(tmp)
        d31.BENCH = bench
        cells_by_pool, headline, files_by_pool, conflicts = d31.collect(0.05)
        print("池数量:", len(cells_by_pool))
        check(len(cells_by_pool) == 2, "两个池都出现在 collect() 结果里 (老池 + 大池)")

        legacy_pids = [p for p in cells_by_pool if str(p).startswith("legacy:")]
        big_pids = [p for p in cells_by_pool if not str(p).startswith("legacy:")]
        check(len(legacy_pids) == 1, "老池的 pid 以 legacy: 开头")
        check(len(big_pids) == 1, "大池的 pid = 产物里记的 names_sha256")
        if not (legacy_pids and big_pids):
            return 1
        lp, bp = legacy_pids[0], big_pids[0]
        legacy, big = cells_by_pool[lp], cells_by_pool[bp]

        check(0 in legacy, "老池保住了自己的 0 档锚点 (老逻辑会把它抢走)")
        check(0 in big, "大池有自己的 0 档锚点")
        check(sorted(legacy) == [0, 40, 80, 160], f"老池档位不变: {sorted(legacy)}")
        check(sorted(big) == [0, 40, 80, 160, 320, 640, 1280, 2240],
              f"大池档位完整: {sorted(big)}")

        legacy_anchor = legacy[0]
        big_anchor = big[0]
        real_anchor = {}
        for f in os.listdir(bench):
            if f.startswith("budget_real0.05_synth0") and f.endswith(".json"):
                d = json.load(open(os.path.join(bench, f), encoding="utf-8"))
                sd = (d.get("protocol") or {}).get("seed")
                if sd is not None and not (d.get("dataset") or {}).get("synth_pool"):
                    real_anchor[sd] = d["map50"]
        check(legacy_anchor == real_anchor,
              "老池锚点 = 老池产物里的 0 档数值 (没被大池顶替)")
        check(all(abs(big_anchor[s] - (0.80 + 0.002 * (s - 42))) < 1e-9 for s in (42, 43, 44)),
              "大池锚点 = 大池产物里的 0 档数值")

        for pid, cells, label in ((lp, legacy, "老池"), (bp, big, "大池")):
            _doses, rows, slope = d31.dose_rows_for(cells, 0.8862)
            check(len(rows) >= 2, f"{label} 曲线算出 {len(rows)} 个剂量行 (配对差值有基准)")
            check(slope is not None, f"{label} 斜率算出来了: {slope}")

        # 复刻老逻辑, 证明"锚点被抢"是真会发生的
        old = {pid: {n: dict(s) for n, s in cp.items()} for pid, cp in cells_by_pool.items()}
        cnt = {pid: sum(len(s) for n, s in cp.items() if n > 0) for pid, cp in old.items()}
        main_pid = max(cnt, key=lambda k: cnt[k])
        for pid, cp in old.items():
            if 0 in cp and pid != main_pid:
                old[main_pid].setdefault(0, {}).update(cp.pop(0))
        for pid, cp in old.items():
            label = "大池" if pid == bp else "老池"
            _doses, rows, _slope = d31.dose_rows_for(cp, 0.8862)
            if label == "老池":
                check(len(rows) == 0,
                      "复刻老逻辑: 老池曲线塌成 0 条剂量行 (这正是被修掉的静默失败)")
        print()
        print("结果:", "PASS" if not fails else f"FAIL ({len(fails)} 项)")
        return 1 if fails else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
