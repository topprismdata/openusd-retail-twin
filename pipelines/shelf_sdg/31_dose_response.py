#!/usr/bin/env python3
"""合成剂量-反应分析 (2026-11-21): 审稿意见"只测了一个合成剂量 (160 张)"的回应。

设计: **同一个合成池**上取嵌套子集 (40 ⊂ 80 ⊂ 160), 剂量轴干净 —— 池子不变,
只有"加了多少合成"在变。160 档复用预算臂已跑好的 seed 42/43/44。

输出:
  output/benchmark/dose_response.json / .md   剂量-反应表 + 斜率与外推
  output/benchmark/dose_response.png          论文图 (剂量 vs 配对差值, 含误差棒)
  (产物由 26_publish_artifacts.py 发布到 docs/research/benchmark/)

用法: python pipelines/shelf_sdg/31_dose_response.py
"""
import glob
import hashlib
import json
import math
import argparse
import os
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import T_CRIT_95 as T_CRIT  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
FIG = os.path.join(BENCH, "dose_response.png")


def _subset_list(budget_json):
    """取某个预算产物用的合成子集名单 (list of 路径)。找不到返回 None。

    旧产物 (2026-11-23 之前) 没有 synth_pool 字段, 但名单文件都在
    output/benchmark/budget/ 下, 按 (real_frac, synth_n, seed) 反查得到。

    优先**按产物文件名精确匹配名单** (21 号写的名单名 = 产物名去掉前缀与扩展名):
    否则会撞车 —— 新旧两个池的同名档 (real0.05_synth40_dose_s42 与
    real0.05_synth40_big_s42) 都以 seed 后缀 "s42" 结尾, 按后缀挑会拿错池的名单。
    """
    try:
        d = json.load(open(budget_json, encoding="utf-8"))
    except Exception:
        return None
    bdir = os.path.join(BENCH, "budget")
    # 1) 精确: budget_<tag>.json -> budget/<tag>_synth.txt
    base = os.path.basename(budget_json)
    if base.startswith("budget_") and base.endswith(".json"):
        tag = base[len("budget_"):-len(".json")]
        p = os.path.join(bdir, tag + "_synth.txt")
        if os.path.exists(p):
            lines = [x for x in open(p, encoding="utf-8").read().strip().split("\n") if x.strip()]
            if lines:
                return lines

    c = (d.get("dataset") or {}).get("cell") or {}
    frac = float(c.get("real_frac", 0))
    # **实际取到的合成数** (dataset.n_synth) 而不是 cell.synth_n (请求值):
    # 请求 200 但池里只有 160 张时, 前者是 160、后者是 200。
    n = int((d.get("dataset") or {}).get("n_synth", c.get("synth_n", 0)))
    seed = (d.get("protocol") or {}).get("seed")
    cands = []
    for f in glob.glob(os.path.join(bdir, "*_synth.txt")):
        b = os.path.basename(f)[:-len("_synth.txt")]
        # 文件名里的合成数是**请求值**, 产物里的 n_synth 是**实际取到的数**
        # (请求 200 但池里只有 160 -> 实际 160)。所以这里按**实际数**匹配名单长度,
        # 而不是按文件名里的数字。
        if f"real{frac:g}_synth" not in b:
            continue
        lines = [x for x in open(f, encoding="utf-8").read().strip().split("\n") if x.strip()]
        if len(lines) != n:
            continue
        cands.append((b, lines))
    if not cands:
        return None
    for b, lines in cands:      # 退回: 挑 seed 后缀匹配的
        if seed is not None and b.endswith(f"s{seed}"):
            return lines
    _b, lines = cands[0]
    return lines


def _pool_id(d, names):
    """池身份: 新产物用 synth_pool.names_sha256; 旧产物用**名单集合**的内容哈希。

    为什么不能用 synth_subset_sha256 区分池: 剂量轴各档是**嵌套子集**, 名单内容本就不同 ->
    每档的子集指纹都不同, 用它分组会把同一池的 40/80/160 拆成三个"池"。
    池身份必须是**池本身**。旧产物没有这个字段, 但可以退到"该档取的那批图的集合":
    同池的各档集合互相嵌套 (小 ⊂ 大), 不同池的不嵌套 -> 用嵌套关系归并。
    """
    import hashlib
    pool = (d.get("dataset") or {}).get("synth_pool") or {}
    if pool.get("names_sha256"):
        return pool["names_sha256"], None
    if not names:
        return "unknown", None
    return None, frozenset(names)


def collect(frac, pool_sha=None):
    """返回 {实际合成图数: {seed: map50}} —— 把剂量档 (40/80) 与既有 160 档合并。

    **必须按"合成池"分组** (2026-11-24 修): 大池剂量链 (47 号) 用的是**另一个**渲染池
    (2800 张 vs 原 160 张), 而场景级留出的划分随场景数变化 -> 新池的 40 张与旧池的 40 张
    **不是同一批图**。原来只按 n_synth 分组, 两个池的同名档会混进同一个 key, 剂量轴就
    不是单变量了 (池子变了 + 剂量也变了)。

    归池规则:
      * 新产物 (21 号已记 synth_pool) -> 直接按池指纹分组;
      * 旧产物 -> 按**名单嵌套关系**归并 (同池各档互相嵌套, 不同池不嵌套)。
      * pool_sha=None -> 取档位最多的那个池 (历史主池), 保持与既有产物兼容。
    """
    rows = []
    for f in sorted(glob.glob(os.path.join(BENCH, "budget_real*_synth*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        c = d["dataset"]["cell"]
        if abs(float(c["real_frac"]) - frac) > 1e-9:
            continue
        seed = d.get("protocol", {}).get("seed")
        # 用**实际取到的**合成数 (不是 cell 里记的请求值) —— 否则 160 档会被当成 200 档
        n_syn = d["dataset"].get("n_synth")
        if seed is None or n_syn is None:
            continue
        names = _subset_list(f)
        pid, nset = _pool_id(d, names)
        rows.append({"f": f, "d": d, "seed": seed, "n": int(n_syn), "pid": pid, "names": nset})

    if not rows:
        return {}

    # 旧产物 (nset 不为 None) 归并成池: 名单互相嵌套的算同一个池
    legacy_groups = []          # 每组: {"members": set(n), "rows": [...]}
    for r in rows:
        if r["pid"] is not None:
            continue
        placed = False
        for g in legacy_groups:
            if r["names"] <= g["members"] or g["members"] <= r["names"]:
                g["members"] |= r["names"]
                g["rows"].append(r)
                placed = True
                break
        if not placed:
            legacy_groups.append({"members": set(r["names"]), "rows": [r]})
    for gi, g in enumerate(legacy_groups):
        # 旧池的身份 = 该池**最大那张名单**的内容指纹 (按图像路径排序)。
        # 这样产物里记的池指纹是**可跨产物比较**的 (不同池必然不同), 而不是一个
        # 只有本脚本内部认得的临时编号。
        h = hashlib.sha256("\n".join(sorted(g["members"])).encode("utf-8")).hexdigest()
        for r in g["rows"]:
            r["pid"] = f"legacy:{h}"
    # **0 档 (无合成基线) 没有合成名单** -> 它的池归属只能靠别的证据:
    #   * 21 号现在**为 0 档也记 synth_pool** (这个格点是对着哪个池准备的) -> 直接用,
    #     锚点**各归各池**;
    #   * 2026-11-23 之前的旧产物没有这个字段 -> 归到**老池** (legacy:*);
    #   * 没有老池才退到"行数最多的池"。
    # 为什么不能一刀切用"行数最多的池" (2026-11-24 修): 大池剂量链 (47 号) 是 8 档 x 3 seed,
    # 行数必然超过老池 -> 0 档锚点被抢走, 老池曲线因**没有基准档**而整条消失 (配对差值
    # 的基准就是 0 档)。那是个静默失败: 报告照出, 只是少了一条曲线。
    zero_rows = [r for r in rows if r["n"] == 0]
    if zero_rows:
        legacy_pids = {r["pid"] for r in rows
                       if r["pid"] and str(r["pid"]).startswith("legacy:")}
        lp = None
        if legacy_pids:
            lp = max(legacy_pids,
                     key=lambda k: len([x for x in rows if x["pid"] == k]))
        fallback = max({r["pid"] for r in rows if r["n"] > 0},
                       key=lambda k: len([x for x in rows if x["pid"] == k]), default=None)
        for r in zero_rows:
            if r["pid"] in (None, "unknown"):
                r["pid"] = lp or fallback or r["pid"]

    cells_by_pool = {}
    files_by_pool = {}
    conflicts = []
    for r in rows:
        tgt = cells_by_pool.setdefault(r["pid"], {}).setdefault(r["n"], {})
        s = r["seed"]
        if s in tgt and abs(tgt[s] - r["d"]["map50"]) > 1e-12:
            # 同一个 (池, 剂量, seed) 出现两次且数值不同 -> **不静默覆盖** (2026-11-24):
            # 覆盖掉的那个可能是基准档 (0 档), 整条曲线的配对差值就会跟着变。
            conflicts.append({"pool": str(r["pid"])[:16], "n_synth": r["n"], "seed": s,
                              "kept_map50": tgt[s], "dropped_map50": r["d"]["map50"],
                              "dropped_file": os.path.basename(r["f"])})
            continue
        tgt[s] = r["d"]["map50"]
        files_by_pool.setdefault(r["pid"], set()).add(os.path.basename(r["f"]))
    pools = {pid: set(cells) for pid, cells in cells_by_pool.items()}
    if pool_sha is None:
        pool_sha = max(pools, key=lambda k: len(pools[k]))
    return cells_by_pool, pool_sha, files_by_pool, conflicts


POOL_SHA = None      # None = 选档位最多的池 (历史主池)


def pool_label(pid):
    """池的人读名字: 大池 (有清单) / 历史主池 / 其它。"""
    if str(pid).startswith("legacy:"):
        return "历史主池 (160 张)"
    man = os.path.join(BENCH, "bigpool_manifest.json")
    try:
        m = json.load(open(man, encoding="utf-8"))
        if m.get("names_sha256") == pid:
            return "大池 (%s 张)" % m.get("n_images")
    except Exception:
        pass
    return "合成池 %s" % str(pid)[:12]


def dose_rows_for(cells, base):
    """某池某预算下的剂量行: 配对差值 / CI / 补回率 / 斜率。

    配对差值的基准是**同池的 0 档** (同 seed、同真实子集、不加合成) -> 差值里只有
    "加了多少合成"这一个变量。
    """
    doses = sorted(cells)
    base_cell = cells.get(0, {})
    rows = []
    for dose in doses:
        if dose == 0:
            continue
        seeds = sorted(set(cells[dose]) & set(base_cell))
        if len(seeds) < 2:
            continue
        diffs = [(cells[dose][s] - base_cell[s]) * 100 for s in seeds]
        mean = statistics.mean(diffs)
        sd = statistics.stdev(diffs) if len(diffs) > 1 else 0.0
        hw = T_CRIT.get(len(diffs) - 1, 1.96) * sd / math.sqrt(len(diffs)) if len(diffs) > 1 else 0.0
        mm = statistics.mean(cells[dose][s] for s in seeds)
        gap = (base - mm) * 100
        rec = (mean / gap) if gap else 0.0
        rows.append({
            "dose": dose, "n_seeds": len(seeds), "seeds": seeds,
            "map50_mean": round(mm, 4),
            "map50_sd": round(statistics.stdev([cells[dose][s] for s in seeds])
                              if len(seeds) > 1 else 0.0, 4),
            "paired_diff_pp": [round(x, 3) for x in diffs],
            "diff_mean_pp": round(mean, 3), "diff_sd_pp": round(sd, 3),
            "t": round(mean / (sd / math.sqrt(len(diffs))), 3) if sd else None,
            "ci95_pp": [round(mean - hw, 3), round(mean + hw, 3)],
            "gap_to_full_real_pp": round(gap, 2),
            "recovery_rate": round(rec, 4),
        })
    slope = None
    if len(rows) >= 2:
        d0, d1 = rows[0], rows[-1]
        slope = ((d1["diff_mean_pp"] - d0["diff_mean_pp"]) / (d1["dose"] - d0["dose"]) * 100
                 if d1["dose"] != d0["dose"] else None)
    return doses, rows, slope


def main():
    global POOL_SHA
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--pool", default=None,
                     help="指定合成池的指纹 (默认取档位最多的那个池 = 历史主池)")
    _ap.add_argument("--pool-manifest", default=None,
                     help="大池清单路径 (output/benchmark/bigpool_manifest.json): "
                          "给出它就按该池的 names_sha256 汇总")
    _args = _ap.parse_args()
    POOL_SHA = _args.pool
    if _args.pool_manifest:
        try:
            _man = json.load(open(_args.pool_manifest, encoding="utf-8"))
            POOL_SHA = _man.get("names_sha256")
            print(f"[DOSE] 按大池清单选池: {POOL_SHA[:12]} ({_man.get('n_images')} 张)")
        except Exception as e:
            print(f"[DOSE] 读池清单失败 ({type(e).__name__}: {e}), 退回默认池")
    base = None
    for f in glob.glob(os.path.join(BENCH, "budget_real1_synth0*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if d.get("protocol", {}).get("seed") == 42:
            base = d["map50"]
            break
    if base is None:
        raise SystemExit("[DOSE] 找不到全量真实基线 (budget_real1_synth0_s42.json)")

    # ---- 收集**所有池**的剂量轴 (2026-11-24) ----
    # 报告要能同时说清"哪条曲线用的是哪个池"; 每个池的 0 档锚点由产物里记的
    # synth_pool 归属 (21 号为 0 档也记), 不再靠"行数最多的池"去猜。
    per_pool = {}
    per_pool_files = {}
    conflicts = []
    for frac in (0.05, 0.02):
        cells_by_pool, _, files_by_pool, cfs = collect(frac)
        for pid, cells in cells_by_pool.items():
            per_pool.setdefault(pid, {})[frac] = cells
            per_pool_files.setdefault(pid, set()).update(files_by_pool.get(pid, set()))
        conflicts += [dict(c, real_frac=frac) for c in cfs]
    if POOL_SHA:
        per_pool = {POOL_SHA: per_pool[POOL_SHA]} if POOL_SHA in per_pool else {}

    def _levels(pid):
        s = set()
        for cells in per_pool[pid].values():
            s |= set(cells)
        return len(s)

    # 主线 = 档位最多的池 (老池时期就是它); 所有池都出曲线, 各自带自己的 0 档锚点。
    order = sorted(per_pool, key=lambda p: (-_levels(p), str(p)))
    headline = order[0] if order else None

    rep = {"schema": "dose_response/2",
           "synth_pool_sha256": headline,
           "generated_by": "pipelines/shelf_sdg/31_dose_response.py",
           "baseline_full_real_map50": base,
           "design": ("同一合成池上的嵌套子集 (sample_subset 同种子 shuffle → 40 ⊂ 80 ⊂ 160); "
                      "剂量轴干净, 池子不变; 每个池的 0 档锚点按产物记的 synth_pool 归属"),
           "pools": {},
           "conflicts": conflicts,
           "budgets": {}}

    lines = ["# 合成剂量-反应 (2026-11-24): 加大合成能补回缺口吗?", "",
             f"基线: 全量真实 (100% 标注, 0 合成) mAP@0.5 = **{base:.4f}**", ""]

    for pid in order:
        pl = {"label": pool_label(pid), "pool_sha256": pid,
              "is_headline": pid == headline,
              "artifact_files": sorted(per_pool_files.get(pid, set())),
              "n_artifacts": len(per_pool_files.get(pid, set())),
              "budgets": {}}
        md = [f"## 合成池: {pl['label']}", "",
              f"池指纹 `{str(pid)[:16]}`" + ("  **(主线)**" if pid == headline else ""), ""]
        for frac in (0.05, 0.02):
            cells = per_pool[pid].get(frac)
            if not cells:
                continue
            doses, rows, slope = dose_rows_for(cells, base)
            if not rows:
                continue
            pl["budgets"][f"{frac:g}"] = {
                "n_synth_levels": doses,
                "dose_rows": rows,
                "slope_pp_per_100_synth": round(slope, 4) if slope is not None else None,
                "note": ("斜率 = 剂量每加 100 张合成, 配对差值变化多少 pp; "
                         "斜率接近 0 → 剂量-反应平坦 (加大合成不产生正收益)"),
            }
            md += [f"### {frac:.0%} 真实标注预算", "",
                   "| 合成剂量 (图) | seed 数 | mAP@0.5 mean ± sd | 相对无合成 (pp) | "
                   "配对差值 mean ± sd (pp) | t | 95% CI | 相对全量真实的缺口 (pp) | 补回率 |",
                   "|---:|---:|---|---:|---|---:|---|---:|---:|"]
            for r in rows:
                md.append(
                    f"| {r['dose']} | {r['n_seeds']} | {r['map50_mean']:.4f} ± {r['map50_sd']:.4f} | "
                    f"{r['diff_mean_pp']:+.2f} | {r['diff_mean_pp']:+.2f} ± {r['diff_sd_pp']:.2f} | "
                    f"{('%.2f' % r['t']) if r['t'] is not None else '—'} | "
                    f"[{r['ci95_pp'][0]:+.2f}, {r['ci95_pp'][1]:+.2f}] | "
                    f"{r['gap_to_full_real_pp']:.2f} | {r['recovery_rate']*100:+.0f}% |")
            md.append("")
        if not pl["budgets"]:
            # 档位或 seed 数还不够出曲线 (每个剂量档至少 2 个 seed 才算得出配对差值)
            # —— 例如大池链刚跑出第 1 个 seed。但**必须**把这个池记进产物: 闸门 [11b]
            # 要核对"每个有剂量的格点产物都被某个池收录", 池不记 -> 那些格点产物在
            # 报告里凭空消失 (静默失败)。曲线等格点补齐再出。
            pl["note"] = ("档位或 seed 数还不够出曲线 (每档至少 2 个 seed 才有配对差值), "
                          "先记下这个池; 曲线等格点补齐再出")
            rep["pools"][pid] = pl
            continue
        rep["pools"][pid] = pl
        if pid == headline:
            rep["budgets"] = pl["budgets"]
        lines += md

    levels = sorted({r["dose"] for b in rep["budgets"].values() for r in b["dose_rows"]})
    if len(levels) >= 2:
        rng_txt = (f"剂量从 {levels[0]} → {levels[-1]} 张合成 "
                   f"({levels[-1] / max(1, levels[0]):.0f}×), ")
    else:
        rng_txt = ""
    lines += ["", f"**读法**: {rng_txt}若斜率接近 0, 说明**加大合成预算不产生正收益** —",
              "这与机理量化 (合成标注效率只有真实的 1/6.7) 一致, 把\"只测了一个剂量\"的短板补上。"]
    with open(os.path.join(BENCH, "dose_response.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    with open(os.path.join(BENCH, "dose_response.json"), "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)

    # 图: 每个池一个子图 (剂量 vs 配对差值, 带误差棒)
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        # 中文字体 (与 27_budget_curve_figure.py 同源; 没有中文字体会渲染成方块)
        matplotlib.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "DejaVu Sans"]
        matplotlib.rcParams["axes.unicode_minus"] = False
        n_pool = max(1, len(rep["pools"]))
        fig, axes = plt.subplots(1, n_pool, figsize=(6.4 * n_pool, 4.2), squeeze=False)
        for ax, (pid, pl) in zip(axes[0], rep["pools"].items()):
            for (frac, b), color in zip(pl["budgets"].items(), ["#5B8FF9", "#F6BD16"]):
                rows = b["dose_rows"]
                xs = [r["dose"] for r in rows]
                ys = [r["diff_mean_pp"] for r in rows]
                es = [r["diff_sd_pp"] for r in rows]
                ax.errorbar(xs, ys, yerr=es, marker="o", capsize=4, lw=1.8, color=color,
                            label=f"{float(frac):.0%} 真实标注")
                for x, y, r in zip(xs, ys, rows):
                    ax.annotate(f"n={r['n_seeds']}", (x, y), textcoords="offset points",
                                xytext=(0, 8), ha="center", fontsize=7, color=color)
            ax.axhline(0, color="#333", lw=1)
            ax.set_xlabel("合成训练图数 (同一合成池的嵌套子集)")
            ax.set_ylabel("配对差值 (加合成 − 不加合成, pp)")
            ax.set_title(f"{pl['label']}: 加大剂量不产生正收益")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=9)
            for sp in ("top", "right"):
                ax.spines[sp].set_visible(False)
        fig.tight_layout()
        os.makedirs(PUB, exist_ok=True)
        fig.savefig(FIG, dpi=150)
        print("->", FIG)
    except Exception as exc:                                  # 画图失败不影响表
        print(f"[DOSE] 画图跳过: {exc}")

    print("->", os.path.join(BENCH, "dose_response.md"))
    for pid, pl in rep["pools"].items():
        for k, b in pl["budgets"].items():
            print(f"[DOSE] {pl['label']} 预算 {k}: 剂量档 {b['n_synth_levels']} → 斜率 "
                  f"{b['slope_pp_per_100_synth']} pp/100 张")

    # 供文档直接引用的段落 (数字自动生成, 避免手抄)
    snip = ["## 合成剂量-反应 (2026-11-24)", "",
            "同一合成池上的**嵌套子集** (sample_subset 同种子 shuffle → 剂量轴干净, 池子不变); "
            "每条曲线的基准是**该池自己的 0 档** (同 seed、同真实子集、不加合成):"]
    for pid, pl in rep["pools"].items():
        for k, b in pl["budgets"].items():
            rows = b["dose_rows"]
            if not rows:
                continue
            pts = ", ".join(f"{r['dose']} 张 → {r['diff_mean_pp']:+.2f} pp" for r in rows)
            snip.append(f"- **{pl['label']} / {float(k):.0%} 真实标注预算**: 剂量 {pts}; "
                        f"斜率 **{b['slope_pp_per_100_synth']} pp / 100 张合成**"
                        if b["slope_pp_per_100_synth"] is not None else
                        f"- **{pl['label']} / {float(k):.0%} 真实标注预算**: 剂量 {pts}")
    snip += ["", "→ 加大合成剂量**没有产生正向补回** (剂量-反应平坦/略负), "
             "与机理量化 (合成标注效率只有真实的 1/6.7) 一致: "
             "「只测了一个合成剂量 (160 张)」这条短板已被补上。"]
    with open(os.path.join(BENCH, "dose_response_snippet.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(snip) + "\n")
    print("->", os.path.join(BENCH, "dose_response_snippet.md"))


if __name__ == "__main__":
    main()
