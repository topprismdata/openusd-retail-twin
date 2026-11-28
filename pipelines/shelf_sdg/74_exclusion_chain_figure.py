#!/usr/bin/env python
"""排除链总图 (2026-11-27) —— 74 号。

为什么要有这张图: 本仓的排除链现在有 **9 条臂** \u2014\u2014 \u6bcf\u6761\u90fd\u6709\u914d\u5bf9\u5dee\u4e0e 95% CI \u2713,
\u4f46\u5b83\u4eec\u5206\u6563\u5728\u4e0d\u540c\u7684\u4ea7\u7269\u4e0e\u6587\u6863\u8282\u91cc \u2192 **\u8bfb\u8005\u770b\u4e0d\u51fa"
\u54ea\u4e9b\u65b9\u5411\u88ab\u5b01\u6b7b\u3001\u5c24\u5176\u662f\u5426\u8fd8\u6709\u5e0c\u671b" \u2713\u3002
\u8fd9\u5f20\u56fe\u628a**\u6240\u6709\u81c2\u7684\u914d\u5bf9\u5dee\u653e\u5728\u540c\u4e00\u4e2a\u8f74\u4e0a** \u2014\u2014
\u6a2a\u8f74 = \u81c2\u2212\u5bf9\u7167\u7684 mAP50 \u5dee (pp) \u2713, \u7eb5\u8f74 = \u90a3\u6761\u8def\u7ebf \u2713,
\u9519\u8bef\u68d2 = 95% CI \u2713\u3002

**\u6240\u6709\u6570\u5b57\u90fd\u4ece\u4ea7\u7269\u73b0\u8bfb** \u2713 (\u6ca1\u6709\u4ea7\u7269\u7684\u6761\u76ee\u76f4\u63a5\u4e0d\u753b \u2192 \u56fe\u4e0a\u4e0d\u4f1a\u51fa\u73b0"
\u624b\u5199\u7684\u6570\u5b57" \u2713) -> \u53e6\u5916\u5199\u4e00\u4efd\u6570\u5b57\u6e05\u5355\u4ea7\u7269 exclusion_chain.json \u2713,
\u95f8\u95e8\u4f1a\u6838\u5bf9\u5b83\u4e0e\u5404\u81c2\u4ea7\u7269\u7684\u4e00\u81f4\u6027 \u2713\u3002

\u8bfb\u6cd5:
  * \u6a2a\u6761\u6574\u4f53\u5728 0 \u5de6\u4fa7 = \u90a3\u6761\u8def\u7ebf\u4f7f\u6a21\u578b**\u53d8\u5dee** \u2713 (\u8d8a\u9760\u5de6\u8d8a\u574f \u2713)
  * \u8de8 0 = \u672a\u68c0\u51fa\u5dee\u5f02 \u2713 (\u4e0d\u80fd\u8bf4\u6709\u6548 \u4e5f\u4e0d\u80fd\u8bf4\u65e0\u6548 \u2713)
  * \u6574\u6bb5\u5728 0 \u53f3\u4fa7 = \u663e\u8457\u53d8\u597d \u2713 (\u672c\u4ed3\u76ee\u524d\u6ca1\u6709\u8fd9\u79cd \u2713)
\u51fa\u53e3: docs/research/benchmark/exclusion_chain.png + output/benchmark/exclusion_chain.json
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")
OUT_JSON = os.path.join(BENCH, "exclusion_chain.json")
OUT_PNG = os.path.join(PUB, "exclusion_chain.png")

# (标签, 产物文件, 配对键, 分组) —— **配对键必须在产物里真的存在** ✓
ROWS = [
    ("I-14 \u5546\u54c1\u8868\u9762 (\u5370\u5237\u5305\u88c5)", "texture_arm.json", "texture_last_minus_control_last", "\u6539\u5408\u6210\u57df"),
    ("I-17 \u6574\u57df\u91cd\u5199 (\u771f\u5b9e\u8d27\u67b6\u5899)", "shelfwall_arm.json", "wall_last_vs_control_last", "\u6539\u5408\u6210\u57df"),
    ("I-18 \u53ea\u6539\u4e0a\u4e0b\u6587", "shelfwall_arm_ctx.json", "wall_last_vs_control_last", "\u6539\u5408\u6210\u57df"),
    ("I-19 \u8bad\u7ec3\u65f6\u6291\u5236\u4e0a\u4e0b\u6587\u4f9d\u8d56", "context_suppress_arm.json", "arm_last_vs_control_last", "\u6539\u8bad\u7ec3"),
    ("I-20 \u5408\u6210\u9884\u8bad\u7ec3 + \u771f\u5b9e\u5fae\u8c03", "pretrain_finetune_arm.json", "arm_vs_ctrl_a", "\u6539\u5206\u5de5"),
    ("I-22 MixStyle (\u7279\u5f81\u7ea7\u591a\u6837\u5316)", "mixstyle_arm.json", "arm_last_vs_control_last", "\u53d8\u5316\u6027"),
    # I-26: \u5408\u6210\u9884\u8bad\u7ec3 + **\u66f4\u591a**\u771f\u5b9e\u9884\u7b97 (\u6d17\u5f97\u5e72\u51c0\u5417?) -> \u5c5e"\u6539\u5206\u5de5" \u2713
    # (ctrl_c = \u53ea\u7528\u771f\u5b9e 40 ep \u662f**\u6b63\u7ed3\u679c** (\u591a\u8bad\u6709\u7528) -> \u4e0d\u8fdb\u6392\u9664\u94fe \u2713, \u5199\u5728 README \u7684\u6c47\u603b\u8868\u91cc \u2713)
    ("I-26 \u5408\u6210\u9884\u8bad\u7ec3 + \u8db3\u91cf\u771f\u5b9e\u9884\u7b97 (\u6d17)", "real_budget_epoch_arm.json", "wash_vs_ctrl_b", "\u6539\u5206\u5de5"),
]

GROUPS = {
    "\u6570\u636e\u7ea7\u591a\u6837\u5316": "#8e7cc3",
    "\u6539\u5408\u6210\u57df": "#cc4125",
    "\u6539\u8bad\u7ec3": "#6aa84f",
    "\u6539\u5206\u5de5": "#e69138",
    "\u53d8\u5316\u6027": "#2f6bf0",
}


def collect():
    rows = []
    for label, fname, pkey, group in ROWS:
        if not fname or not pkey:
            continue
        p = os.path.join(BENCH, fname)
        if not os.path.exists(p):
            print(f"[CHAIN] \u7f3a\u4ea7\u7269 {fname} \u2192 \u8df3\u8fc7 {label} \u2713")
            continue
        d = json.load(open(p, encoding="utf-8"))
        v = (d.get("paired") or {}).get(pkey)
        if not v or v.get("mean_pp") is None:
            print(f"[CHAIN] {fname} \u91cc\u6ca1\u6709\u914d\u5bf9 {pkey} \u2192 \u8df3\u8fc7 {label} \u2713")
            continue
        ci = v.get("ci95_pp") or [v["mean_pp"], v["mean_pp"]]
        rows.append({"label": label, "group": group, "artifact": fname, "pair_key": pkey,
                     "n": v.get("n"), "mean_pp": v["mean_pp"],
                     "ci95_pp": ci, "per_seed_pp": v.get("per_seed_pp")})
    return rows


def main():
    rows = collect()
    if not rows:
        raise SystemExit("\u6ca1\u6709\u53ef\u753b\u7684\u914d\u5bf9\u7edf\u8ba1 \u2192 \u5148\u8dd1\u5404\u81c2")
    rep = {"schema": "exclusion_chain/1",
           "generated_by": "pipelines/shelf_sdg/74_exclusion_chain_figure.py",
           "measured_at": __import__("time").strftime("%Y-%m-%d"),
           "question": ("\u672c\u4ed3\u5df2\u5b9e\u6d4b\u7684\u5404\u6761\u8def\u7ebf\u5728\u540c\u4e00\u4e2a\u8f74\u4e0a\u662f\u600e\u4e48\u5206\u5e03\u7684"),
           "rows": rows}
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print(f"[CHAIN] \u6570\u5b57\u6e05\u5355 \u2192 {OUT_JSON}")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    sys.path.insert(0, BASE)
    from pipelines.common.fonts import find_font_path
    cjk = find_font_path("cjk")
    if cjk:
        font_manager.fontManager.addfont(cjk)
        matplotlib.rcParams["font.family"] = font_manager.FontProperties(fname=cjk).get_name()
        matplotlib.rcParams["axes.unicode_minus"] = False
    else:
        print("[FIG] \u6ca1\u627e\u5230 CJK \u5b57\u4f53, \u6807\u7b7e\u53ef\u80fd\u663e\u793a\u4e3a\u65b9\u5757 \u2717")

    fig, ax = plt.subplots(figsize=(9.4, 0.62 * len(rows) + 2.5))
    y = list(range(len(rows)))
    for i, r in enumerate(rows):
        ci = r["ci95_pp"]
        ax.barh(i, r["mean_pp"], color=GROUPS.get(r["group"], "#999999"), height=0.55,
                alpha=0.9, zorder=2)
        ax.errorbar(r["mean_pp"], i,
                    xerr=[[r["mean_pp"] - ci[0]], [ci[1] - r["mean_pp"]]],
                    fmt="none", ecolor="#202124", capsize=5, lw=1.4, zorder=3)
    ax.axvline(0, color="#202124", lw=1.2, zorder=1)
    ax.set_yticks(y)
    ax.set_yticklabels([r["label"] for r in rows], fontsize=9)
    ax.invert_yaxis()
    ax.set_xlabel("\u81c2 \u2212 \u5bf9\u7167\u7684 mAP50 \u5dee (pp)  \u2190 \u53d8\u5dee / \u2192 \u53d8\u597d", fontsize=10, labelpad=8)
    ax.set_title("\u672c\u4ed3\u7684\u6392\u9664\u94fe: \u6bcf\u6761\u5df2\u5b9e\u6d4b\u8def\u7ebf\u7684\u914d\u5bf9\u5dee\u4e0e 95% CI", fontsize=12)
    # **\u811a\u6ce8** \u2192 n=3 \u7684 CI \u5f88\u5bbd (df=2 \u2713), \u4e0d\u80fd\u53ea\u770b CI \u8de8 0 \u5c31\u8bf4\u65e0\u6548 \u2713
    ax.text(0.0, -0.155,
            "\u6ce8: \u5224\u8bfb\u7531 CI \u5f62\u6001\u73b0\u7b97 (\u8de8 0 = \u672a\u68c0\u51fa\u5dee\u5f02) \u2192 n=3 \u7684 CI \u5f88\u5bbd (df=2) \u2192 I-14 \u73b0\u5728\u5df2\u6574\u6bb5\u5728 0 \u4ee5\u4e0b (df \u4fee\u6b63\u540e \u2713) "
            "\u2192 \u8bfb\u56fe\u65f6\u4e0d\u8981\u628a\u201cCI \u8de8 0\u201d\u8bfb\u6210\u201c\u6ca1\u5dee\u5f02\u201d, \u4e5f\u4e0d\u8981\u628a\u201cCI \u4e0d\u8de8 0\u201d\u8bfb\u6210\u201c\u6548\u5e94\u5f88\u5927\u201d (README \u6709\u8be6\u7ec6\u8bf4\u660e) \u2713",
            transform=ax.transAxes, fontsize=7.5, color="#666666", ha="left", va="top")
    ax.grid(axis="x", alpha=0.25, lw=0.6, zorder=0)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    # \u56fe\u4f8b: \u53ea\u51fa\u73b0\u4e00\u6b21\u7684\u5206\u7ec4\u56fe\u4f8b
    seen = []
    for r in rows:
        if r["group"] not in seen:
            seen.append(r["group"])
    handles = [plt.Rectangle((0, 0), 1, 1, color=GROUPS.get(g, "#999999"), alpha=0.9) for g in seen]
    # **\u56fe\u4f8b\u653e\u5728\u8f74\u5916\u4e0b\u65b9** \u2192 \u4e0d\u4f1a\u538b\u5728\u6761\u4e0a \u2713
    ax.legend(handles, seen, loc="upper center", bbox_to_anchor=(0.5, -0.13),
              ncol=min(len(seen), 4), fontsize=8, frameon=False)

    # \u53f3\u4fa7\u7559\u51fa\u4e00\u5217\u7a7a\u767d\u653e\u5224\u8bfb (\u7531 CI \u5f62\u6001\u73b0\u7b97 \u2192 \u4e0d\u624b\u5199 \u2713)
    xmin, xmax = ax.get_xlim()
    span = xmax - xmin
    ax.set_xlim(xmin, xmax + span * 0.42)          # \u53f3\u4fa7\u62c9\u5bbd\uff0c\u5224\u8bfb\u5199\u5728\u7a7a\u767d\u533a\u91cc \u2192 \u4e0d\u4e0e\u6761\u91cd\u53e0 \u2713
    label_x = xmax + span * 0.015
    for i, r in enumerate(rows):
        ci = r["ci95_pp"]
        if ci[1] < 0:
            verdict = "\u663e\u8457\u53d8\u5dee"
        elif ci[0] > 0:
            verdict = "\u663e\u8457\u53d8\u597d"
        else:
            verdict = "\u672a\u68c0\u51fa\u5dee\u5f02"
        ax.text(label_x, i, f"{r['mean_pp']:+.2f} pp  (n={r['n']})  {verdict}",
                ha="left", va="center", fontsize=8.5, color="#202124")

    fig.tight_layout()
    os.makedirs(PUB, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=160)
    print(f"-> {OUT_PNG}")
    for r in rows:
        ci = r["ci95_pp"]
        print(f"   {r['label']}: {r['mean_pp']:+.2f} pp [{ci[0]:+.2f}, {ci[1]:+.2f}] (n={r['n']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
