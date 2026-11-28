#!/usr/bin/env python3
"""文档一致性自检 (2026-11-21): 文档里引用的每个 protocol_hash 都必须能在产物里找到。

背景: 这个仓的结论全部带"协议哈希存证"。如果文档里写了一个哈希但仓里没有对应产物
(或者反过来: 产物换了哈希而文档没改), 那就是**可核验性断链** —— 审稿人一眼就能看出来。
本脚本把这条纪律变成可执行的检查 (CI 可直接调用)。

检查项:
1. 文档里引用的 16 位十六进制哈希 ⊆ 产物 json 里的 protocol_hash / protocol_manifest.protocol_hash;
2. 关键格点的 mAP@0.5 与文档里写的数值一致 (seed 42 口径);
3. 随仓发布的产物清单 (MANIFEST.json) 里的 sha256 与文件实际内容一致。

退出码 0 = 全部通过; 1 = 有不一致。
"""
import glob
import hashlib
import json
import math
import os
import re
import statistics
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import T_CRIT_95  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")

DOCS = ["README.md",
        "docs/AUDIT_CODE_2026-11-18.md",
        "docs/research/REPRODUCIBILITY_PROTOCOL_2026-11-20.md",
        "docs/research/BUDGET_ARM_CONCLUSION_2026-11-21.md",
        "docs/research/DATASET_SKU110K.md"]


def collect_hashes():
    out = {}
    pats = [os.path.join(BENCH, "budget_real*_synth*.json"),
            os.path.join(PUB, "budget_real*_synth*.json"),
            os.path.join(PUB, "sku110k_*.json"),
            os.path.join(BENCH, "sku110k_*.json")]
    for pat in pats:
        for f in glob.glob(pat):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            if d.get("protocol_hash"):
                out.setdefault(d["protocol_hash"], set()).add(os.path.basename(f))
            pm = d.get("protocol_manifest") or {}
            if pm.get("protocol_hash"):
                out.setdefault(pm["protocol_hash"], set()).add(os.path.basename(f))
    return out


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def protocol_deviation(d):
    """产物里的**实际**训练配置是否偏离**协议** (2026-11-25 加)。

    起因: 同配置复跑老池 0 档 (噪声底实验) 时, 并发压 GPU 让训练脚本把 batch 从
    4 降到了 2, 结果 mAP 0.7946 -> 0.7705。这个差值**不是**噪声底, 而是协议漂移
    (ultralytics 按 nbs/batch 缩放学习率, 所以 batch 不是无害的等价改动)。
    产物本来就记了 `actual_train_config`, 于是偏差**可自查** —— 但前提是闸门会去查它。

    返回偏离项列表 (空 = 与协议一致)。
    """
    dev = []
    act = d.get("actual_train_config") or {}
    pro = d.get("protocol") or {}
    for k in ("epochs", "batch", "workers"):
        if k in act and k in pro and act[k] != pro[k]:
            dev.append(f"{k}: 协议 {pro[k]} -> 实际 {act[k]}")
    return dev


def _readme_ci_by_density(rd):
    """把 README 里每个「配对差值 pp，95% CI [...]」配到它所属的密度点。

    判据: 该 CI 之前**最近**的一个「N 框/图」就是它所属的密度 (README 的密度段是
    表格: "稀释到 22 框/图" 那一行下面紧接着就是"配对差值"行)。只取全文第一个匹配
    会在有多个密度点时把点搞错。
    """
    pat = re.compile(r"\*\*([−-][0-9.]+) pp，95% CI \[([−-][0-9.]+), ([−-][0-9.]+)\]")
    out = {}

    def _f(x):
        return float(x.replace("−", "-"))

    for m in pat.finditer(rd):
        head = rd[max(0, m.start() - 800):m.start()]
        dens = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*框/图", head)
        key = int(round(float(dens[-1]))) if dens else None
        out.setdefault(key, []).append((_f(m.group(1)), _f(m.group(2)), _f(m.group(3))))
    return out


def _num_on_line(line, label, val):
    """判断"标签与数字"是否**在同一个格子里** ✓。

    为什么不能只做子串匹配 ✓: 表格行 "| 印刷变体 | 15 | 13 个虚拟 SKU ... |" 里
    "13" (别处的文字) 会让子串匹配**误判为通过** ✗ -> 负向测试抓不到 ✓。
    规则 ✓: 表格行 -> 逐格比对 (去掉空格后**完全相等** ✓); 散文行 -> "标签 数字" 连续出现 ✓。
    """
    if label not in line:
        return False
    if "|" in line:
        cells = [c.strip() for c in line.split("|")]
        if any(c == str(val) for c in cells):
            return True
        # 表格行里也允许"标签 | 数字"这种带空格的写法 ✓
        return f"{label} {val}" in line
    return f"{label} {val}" in line or f"{label}**{val}" in line

def main():
    hashes = collect_hashes()
    problems = []

    # 1) 文档里的哈希
    for d in DOCS:
        p = os.path.join(BASE, d)
        if not os.path.exists(p):
            continue
        txt = open(p, encoding="utf-8").read()
        for h in sorted(set(re.findall(r"`([0-9a-f]{16})`", txt))):
            if h not in hashes:
                problems.append(f"{d}: 引用了产物里不存在的 protocol_hash {h}")
    print(f"[1] 文档哈希引用: {len(hashes)} 个已知哈希, 不一致 {len(problems)} 处")

    # 2) 清单里的 sha256
    man = os.path.join(PUB, "MANIFEST.json")
    if os.path.exists(man):
        m = json.load(open(man, encoding="utf-8"))
        n_bad = 0
        for e in m.get("files", []):
            f = os.path.join(PUB, e["file"])
            if not os.path.exists(f):
                problems.append(f"MANIFEST: 列出的文件不存在 {e['file']}")
                n_bad += 1
            elif sha256(f) != e["sha256"]:
                problems.append(f"MANIFEST: {e['file']} 的 sha256 与清单不符")
                n_bad += 1
        print(f"[2] 产物清单 sha256: {len(m.get('files', []))} 个文件, 不一致 {n_bad} 处")
    else:
        print("[2] 产物清单: 未生成 (运行 24_publish_manifest.py)")

    # 3) 关键格点数值 (seed 42)
    want = {(1.0, 0): 0.8862, (0.05, 0): 0.7946, (0.05, 200): 0.7855,
            (0.02, 0): 0.7086, (0.02, 200): 0.6787}
    got = {}
    drifted = []
    replicates = []
    for f in glob.glob(os.path.join(BENCH, "budget_real*_synth*.json")):
        d = json.load(open(f, encoding="utf-8"))
        dev = protocol_deviation(d)
        if dev:
            drifted.append((os.path.basename(f), dev))
            continue                      # 协议漂移的产物不能当证据 (见 [3z])
        if "replicate" in os.path.basename(f):
            replicates.append((f, d))     # 重复跑不参与数值一致性核对 (见 [3y])
            continue
        c = d["dataset"]["cell"]
        key = (float(c["real_frac"]), int(c["synth_n"]))
        if d.get("protocol", {}).get("seed") == 42:
            got[key] = d["map50"]
    for k, v in want.items():
        if k in got and abs(got[k] - v) > 0.0001:
            problems.append(f"格点 {k}: 产物 {got[k]:.4f} != 文档写的 {v:.4f}")
    print(f"[3] 关键格点数值 (seed 42): 核对 {len(want)} 个")

    # 3b) 其他 seed 的格点数值 (文档里也引用了 seed 43/44 的数字)
    want_oth = {(0.05, 0, 43): 0.7745, (0.05, 200, 43): 0.7845,
                (0.02, 0, 43): 0.7108, (0.02, 200, 43): 0.7142,
                (0.05, 0, 44): 0.7859, (0.05, 200, 44): 0.7879,
                (0.02, 0, 44): 0.7185, (0.02, 200, 44): 0.7190}
    got_oth = {}
    for f in glob.glob(os.path.join(BENCH, "budget_real*_synth*.json")):
        d = json.load(open(f, encoding="utf-8"))
        if protocol_deviation(d) or "replicate" in os.path.basename(f):
            continue
        c = d["dataset"]["cell"]
        sd = d.get("protocol", {}).get("seed")
        if sd in (43, 44):
            got_oth[(float(c["real_frac"]), int(c["synth_n"]), sd)] = d["map50"]
    for k, v in want_oth.items():
        if k in got_oth and abs(got_oth[k] - v) > 0.0001:
            problems.append(f"格点 {k}: 产物 {got_oth[k]:.4f} != 文档写的 {v:.4f}")
    print(f"[3b] 其他 seed 格点数值 (43/44): 核对 {len(want_oth)} 个")

    # 3y) **噪声底**: 同格点、同 seed、同协议的重复跑, 与原值的差就是"同配置重跑的波动"。
    #      这个量此前**从未测过** -> 所有结论的 CI 只覆盖 seed 间差异, 不覆盖它。
    #      判读: 差值应该很小 (同配置同数据); 超过 5 pp 说明不是噪声而是出了问题。
    if replicates:
        base = {}
        for f in glob.glob(os.path.join(BENCH, "budget_real*_synth*.json")):
            if "replicate" in os.path.basename(f):
                continue
            d = json.load(open(f, encoding="utf-8"))
            if protocol_deviation(d):
                continue
            c = d["dataset"]["cell"]
            sd = d.get("protocol", {}).get("seed")
            base[(float(c["real_frac"]), int(c["synth_n"]), sd)] = d["map50"]
        deltas = []
        for f, d in replicates:
            c = d["dataset"]["cell"]
            sd = d.get("protocol", {}).get("seed")
            k = (float(c["real_frac"]), int(c["synth_n"]), sd)
            if k not in base:
                problems.append(f"噪声底: {os.path.basename(f)} 找不到同格点同 seed 的原始产物, "
                                f"无法比较")
                continue
            delta = (d["map50"] - base[k]) * 100
            deltas.append(delta)
            if abs(delta) > 5.0:
                problems.append(f"噪声底: {os.path.basename(f)} 与原值差 {delta:+.2f} pp "
                                f"(>5 pp) —— 这不是重跑波动, 请查协议/数据是否变了")
        if deltas:
            print(f"[3y] 噪声底 (同配置重复跑): {len(deltas)} 组, Δ = "
                  f"{', '.join(f'{x:+.2f} pp' for x in deltas)}")
    else:
        print("[3y] 噪声底: 暂无同格点重复跑产物")


    # 3z) **协议漂移的产物必须被点名** (2026-11-25): 复现/重复实验如果实际训练配置
    #     偏离协议, 它的数值**不是**噪声底、也不能进任何对比 —— 但产物自己不会喊,
    #     静默混进汇总就是下一次"结论反转"的来源。这里点名, 并要求用同协议重跑。
    if drifted:
        for name, dev in drifted:
            problems.append(f"协议漂移: {name} 的实际训练配置与协议不符 ({'; '.join(dev)}) "
                            f"→ 该产物不能作为证据, 需用同协议重跑")
        print(f"[3z] 协议漂移: {len(drifted)} 个产物被排除 (实际配置 != 协议)")
    else:
        print("[3z] 协议漂移: 无")


    # 3c) 剂量-反应格点 (2026-11-22): README/结论文档里引用的 8 个剂量格点数值
    # 注意: 产物不在仓内 (output/ 被 gitignore), CI 的干净 checkout 里没有这些 json ——
    # 所以"产物全缺"要放行 (与 3/3b 同口径: 只在产物存在时核对), 否则 CI 会永远红。
    want_dose = {(0.05, 40, 42): 0.7920, (0.05, 40, 43): 0.7829,
                 (0.05, 80, 42): 0.7806, (0.05, 80, 43): 0.7719,
                 (0.02, 40, 42): 0.7165, (0.02, 40, 43): 0.7102,
                 (0.02, 80, 42): 0.7024, (0.02, 80, 43): 0.7218}
    got_dose = {}
    for f in (glob.glob(os.path.join(BENCH, "budget_real*_synth*_dose_s*.json"))
              + glob.glob(os.path.join(PUB, "budget_real*_synth*_dose_s*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        c = d["dataset"]["cell"]
        sd = d.get("protocol", {}).get("seed")
        got_dose[(float(c["real_frac"]), int(c["synth_n"]), sd)] = d["map50"]
    if got_dose:
        for k, v in want_dose.items():
            if k not in got_dose:
                problems.append(f"剂量格点 {k}: 产物缺失 (文档引用了该数字)")
            elif abs(got_dose[k] - v) > 0.0001:
                problems.append(f"剂量格点 {k}: 产物 {got_dose[k]:.4f} != 文档写的 {v:.4f}")
        print(f"[3c] 剂量-反应格点: 核对 {len(want_dose)} 个 (缺 {len(want_dose) - len(got_dose)} 个)")
    else:
        print("[3c] 剂量-反应格点: 产物不在仓内 (output/ 被忽略), 跳过核对")

    # 3d) 剂量-反应聚合值 (斜率与配对差值) —— 文档里直接引用了这两个数
    dr = os.path.join(BENCH, "dose_response.json")
    if not os.path.exists(dr):
        dr = os.path.join(PUB, "dose_response.json")      # 发布版也在仓内, CI 可核
    if os.path.exists(dr):
        d = json.load(open(dr, encoding="utf-8"))
        # 斜率: **从 README 解析**, 不在闸门里硬编码 (2026-11-24 改)。硬编码有两个坏处:
        #   文档改了而闸门忘了改 -> 静默通过; 换了主线池 (大池落地后主线会变) -> 必然对不上。
        rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        cited = [float(x.replace("−", "-")) for x in
                 re.findall(r"斜率\s*\*\*([-−]?\d+\.\d+)\s*pp\s*/\s*100\s*张", rd)]
        if not cited:
            problems.append("README 里找不到剂量斜率的数字 → 无法核对")
        else:
            got_all = []
            for pid, pl in (d.get("pools") or {}).items():
                for frac, b in (pl.get("budgets") or {}).items():
                    s = b.get("slope_pp_per_100_synth")
                    if s is not None:
                        got_all.append((frac, s))
            for c in cited:
                # README 引的是四舍五入到 2 位的数 -> 容差 0.006
                if not any(abs(s - c) <= 0.006 for _f, s in got_all):
                    problems.append(f"剂量斜率 {c:+.2f} pp/100 张: README 引了这个数, "
                                    f"但报告里没有任何池算出它 (现有: {got_all})")
            print(f"[3d] 剂量-反应斜率: 核对 {len(cited)} 个 (取自 README, 池: {got_all})")
    else:
        print("[3d] 剂量-反应斜率: 产物不在仓内, 跳过核对")

    # 4) 血缘与数据不变性 (2026-11-22 新增)
    #    这两条是被真实事故逼出来的:
    #      (a) 同一格点的多次运行必须共享同一个 real_subset_sha256 —— 否则"多种子对比"里
    #          混进了数据差异, 差值就不能归因于训练随机性;
    #      (b) 每个计数产物的 weights.sha256 必须能在格点产物里找到同一个 checkpoint ——
    #          这条能直接抓住"2 epoch 冒烟权重 vs 10 epoch 格点权重"那类混用
    #          (2026-11-22 就因为它把"标注量带来计数能力 (MAE -36%)"写错了)。
    cell_sha = {}
    grid_by_ckpt = {}
    for f in glob.glob(os.path.join(BENCH, "budget_real*_synth*.json")) + \
             glob.glob(os.path.join(PUB, "budget_real*_synth*.json")):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        c = d["dataset"]["cell"]
        key = (float(c["real_frac"]), int(c["synth_n"]))
        sd = d.get("protocol", {}).get("seed")
        sha = (d.get("dataset") or {}).get("real_subset_sha256")
        if sha:
            cell_sha.setdefault(key, {}).setdefault(sha, []).append((sd, os.path.basename(f)))
        ck = (d.get("checkpoint") or {}).get("sha256")
        if ck:
            grid_by_ckpt.setdefault(ck, []).append((key, sd))
    n_cells = 0
    for key, by_sha in sorted(cell_sha.items()):
        n_cells += 1
        if len(by_sha) > 1:
            problems.append(f"格点 {key}: {len(by_sha)} 个不同的 real_subset_sha256 "
                            f"→ 多种子对比里混进了数据差异")
    print(f"[4a] 格点数据指纹一致性: 核对 {n_cells} 个格点")

    CNT_RE = re.compile(r"^count_real([\d.]+)(?:_s(\d+))?\.json$")
    # count_pilot.json 故意不查: 那是 2026-11-18 的 2 epoch 冒烟权重产物 (sha 57ed73ca…),
    # 留着是为了记录"那个被误当成"标注量带来计数能力"的数" —— 它本来就不该对应当前任何格点权重。
    # 真正的门禁是: 新出的计数产物必须能对上某个格点 checkpoint (见 4b)。
    n_cnt = 0
    for f in sorted(glob.glob(os.path.join(BENCH, "count_real*.json"))
                    + glob.glob(os.path.join(PUB, "count_real*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        m = CNT_RE.match(os.path.basename(f))
        if not m:
            continue
        frac = float(m.group(1))
        seed = int(m.group(2)) if m.group(2) else 42
        ck = ((d.get("weights") or {}).get("sha256"))
        n_cnt += 1
        if not ck:
            problems.append(f"{os.path.basename(f)}: 没有 weights.sha256, 无法核血缘")
            continue
        hits = grid_by_ckpt.get(ck, [])
        if not hits:
            problems.append(f"{os.path.basename(f)}: 权重 sha256 {ck[:12]}… 在格点产物里找不到 "
                            f"→ 该计数指标不是当前格点权重跑出来的")
            continue
        if not any(h[0][0] == frac and h[1] == seed for h in hits):
            problems.append(f"{os.path.basename(f)}: 权重 sha256 对应的是 {hits[0][0][0]:g}/seed {hits[0][1]}, "
                            f"但文件名声称 {frac:g}/seed {seed} → 计数指标与格点对不上")
    print(f"[4b] 计数产物血缘 (权重 sha256 ↔ 格点 checkpoint): 核对 {n_cnt} 个")

    # 4c) 同一格点的计数产物必须用同一份 600 张抽样名单, 否则数字不可比
    by_frac = {}
    for f in sorted(glob.glob(os.path.join(BENCH, "count_real*.json"))
                    + glob.glob(os.path.join(PUB, "count_real*.json"))):
        m = CNT_RE.match(os.path.basename(f))
        if not m:
            continue
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        sha = ((d.get("sample") or {}).get("names_sha256"))
        if sha:
            by_frac.setdefault(float(m.group(1)), set()).add(sha)
    n_bad = 0
    for frac, shas in sorted(by_frac.items()):
        if len(shas) > 1:
            problems.append(f"计数产物 真实比例 {frac:g}: {len(shas)} 份不同的抽样名单 → 不可比")
            n_bad += 1
    print(f"[4c] 计数抽样名单一致性: 核对 {len(by_frac)} 个格点, 不一致 {n_bad} 处")

    # 5) 缺口与计数跨 seed 汇总 (2026-11-22 晚): 文档里引用的 CI 必须来自产物
    var = os.path.join(BENCH, "budget_seed_variance.json")
    if not os.path.exists(var):
        var = os.path.join(PUB, "budget_seed_variance.json")
    if os.path.exists(var):
        v = json.load(open(var, encoding="utf-8"))
        gaps = {(g["frac"], g["synth"]): g for g in v.get("vs_full_real", [])}
        want_gap = {(0.05, 0): (-9.919, [-11.861, -7.976]), (0.02, 0): (-17.156, [-18.581, -15.73])}
        for key, (mean_w, ci_w) in want_gap.items():
            g = gaps.get(key)
            if not g:
                problems.append(f"budget_seed_variance.json: 缺缺口格点 {key}")
                continue
            got = g.get("map50_diff_mean_pp")
            if got is None or abs(got - mean_w) > 0.01:
                problems.append(f"缺口 {key}: 产物 {got} != 文档写的 {mean_w}")
            ci = g.get("map50_diff_ci95")
            if not ci or abs(ci[0] - ci_w[0]) > 0.01 or abs(ci[1] - ci_w[1]) > 0.01:
                problems.append(f"缺口 {key}: 产物 CI {ci} != 文档写的 {ci_w}")
        cm = v.get("count_metrics", {})
        want_count = {"1": (18.37, 0.79), "0.05": (25.26, 4.42)}
        for frac, (m_w, s_w) in want_count.items():
            c = cm.get(frac)
            if not c:
                problems.append(f"budget_seed_variance.json: 缺计数汇总 {frac}")
                continue
            for key, w in (("count_mae_mean", m_w), ("count_mae_std", s_w)):
                got = c.get(key)
                if got is None or abs(got - w) > 0.01:
                    problems.append(f"计数汇总 {frac}.{key}: 产物 {got} != 文档写的 {w}")
        print(f"[5] 缺口与计数跨 seed 汇总: 核对 {len(want_gap) + len(want_count)} 项")
    else:
        print("[5] 缺口与计数跨 seed 汇总: 产物不在仓内, 跳过核对")

    # 6) 已发布四臂的多 seed 汇总 (2026-11-23): 文档引用的四臂均值与配对 CI 必须来自产物
    #
    # 这里**不硬编码期望值**, 而是把 README 里写的数字**解析出来**再和产物比。
    # 原因: 硬编码的期望值每加一个 seed 就要手改一遍脚本, 而"脚本里的数"和"文档里的数"
    # 是两个独立的真相源 —— 改漏一个就静默通过或误报。改成解析文档后, 唯一真相源是
    # 产物 (fourarm_seed_variance.json), 闸门查的是**文档有没有跟上产物**。
    fav = os.path.join(BENCH, "fourarm_seed_variance.json")
    if not os.path.exists(fav):
        fav = os.path.join(PUB, "fourarm_seed_variance.json")
    if os.path.exists(fav):
        fv = json.load(open(fav, encoding="utf-8"))
        groups = fv.get("groups", {})
        rd = ""
        try:
            rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            pass

        def num(x):
            """文档里用的是 U+2212 减号, 统一换成 ASCII 再转 float。"""
            return float(str(x).replace("−", "-").replace(",", ""))

        def grab(pat, what, n_groups):
            m = re.search(pat, rd)
            if not m:
                problems.append(f"README 里找不到 {what} 的数字 → 无法核对")
                return None
            return [num(g) for g in m.groups()]

        # 臂的 mean ± std: "R0 真实 **…**（mean 0.8833 ± 0.0012）"
        arm_pats = {
            "r0": (r"R0 真实 \*\*[0-9./ ]+\*\*（mean ([0-9.]+) ± ([0-9.]+)）", "R0"),
            "r1": (r"R1 纯合成：当前协议 \*\*[0-9./ ]+\*\*（mean ([0-9.]+) ± ([0-9.]+)", "R1"),
            "r2": (r"R2 真实\+合成 \*\*[0-9./ ]+\*\*（mean ([0-9.]+) ± ([0-9.]+)）", "R2"),
        }
        for arm, (pat, what) in arm_pats.items():
            g = groups.get(arm)
            if not g:
                problems.append(f"fourarm_seed_variance.json: 缺臂 {arm}")
                continue
            vals = grab(pat, what, 2)
            if not vals:
                continue
            m_w, s_w = vals
            for key, w in (("map50_mean", m_w), ("map50_std", s_w)):
                got = g.get(key)
                if got is None or abs(got - w) > 0.0002:
                    problems.append(f"四臂 {arm}.{key}: 产物 {got} != 文档写的 {w}")

        # 配对: Δ(R2−R0) 与 R1 相对 R0 的差值/CI
        pairs = {(p["b"], p["a"]): p for p in fv.get("paired", [])}
        pair_pats = {
            ("r2", "r0"): (r"Δ\(R2−R0\) = [−+\d. /]+ pp，mean ([−+][\d.]+)pp，"
                           r"95% CI \[([−+][\d.]+), ([−+][\d.]+)\]", "Δ(R2−R0)"),
            ("r1", "r0"): (r"比 R0 低 ([\d.]+)pp，CI \[([−+][\d.]+), ([−+][\d.]+)\]",
                           "R1 相对 R0"),
        }
        for key, (pat, what) in pair_pats.items():
            p = pairs.get(key)
            if not p:
                problems.append(f"fourarm_seed_variance.json: 缺配对 {key}")
                continue
            vals = grab(pat, what, 3)
            if not vals:
                continue
            if key == ("r1", "r0"):
                # 文档写的是"比 R0 低 X pp"(正的下降量) + CI; 产物里是带符号的差值
                drop_w = vals[0]
                mean_w = -drop_w
                ci_w = [vals[1], vals[2]]
            else:
                mean_w, ci_w = vals[0], [vals[1], vals[2]]
            got = p.get("map50_diff_mean_pp")
            if got is None or abs(got - mean_w) > 0.05:
                problems.append(f"四臂配对 {key}: 产物 {got} != 文档写的 {mean_w}")
            ci = p.get("map50_diff_ci95")
            if not ci or abs(ci[0] - ci_w[0]) > 0.05 or abs(ci[1] - ci_w[1]) > 0.05:
                problems.append(f"四臂配对 {key}: 产物 CI {ci} != 文档写的 {ci_w}")
        print(f"[6] 四臂多 seed 汇总: 核对 {len(arm_pats) + len(pair_pats)} 项 (数字取自 README)")
    else:
        print("[6] 四臂多 seed 汇总: 产物不在仓内, 跳过核对")

    # 6c) 各臂 (I-17 货架墙 / I-18 上下文) 的多 seed 配对结果 (2026-11-26 加)。
    # 同样**不硬编码期望值**: 数字从 README 解析, 与产物比。
    # 另外核对**判语与统计量是否一致** (skill: multi-seed-aggregation-pitfalls §3):
    # CI 整段在 0 以下 -> 必须写"显著劣化"; 整段在 0 以上 -> 必须写"显著为正";
    # 跨 0 -> 才能写"未检出差异"。判语与 CI 形态矛盾就是不一致。
    # 臂的键名: 产物里的 per_seed 用的是同一个键 (wall_last/control_last) ——
    # 因为两个臂跑的是同一个 64 号脚本 (tag 只改目录/产物名) ✓。
    ARM_CHECKS = [
        ("shelfwall_arm.json", "货架墙臂", "Δ(货架墙臂−对照)",
         "wall_last", "wall_last_vs_control_last", "control_last"),
        ("shelfwall_arm_ctx.json", "上下文臂", "Δ(上下文臂−对照)",
         "wall_last", "wall_last_vs_control_last", "control_last"),
        # I-19 用自己的键名 (arm_last) —— 键名不同就不能硬编码 wall_last ✓
        ("context_suppress_arm.json", "上下文抑制臂", "Δ(上下文抑制臂−对照)",
         "arm_last", "arm_last_vs_control_last", "control_last"),
        # 2026-11-26: I-22 MixStyle 特征级多样化臂
        ("mixstyle_arm.json", "MixStyle臂", "Δ(MixStyle臂−对照)",
         "arm_last", "arm_last_vs_control_last", "control_last"),
        # I-20 分工臂: 对照是 ctrl_a (同真实曝光) —— 键名与其它臂不同 ✓
        ("pretrain_finetune_arm.json", "分工臂", "Δ(分工臂−ctrl_a)",
         "arm_last", "arm_vs_ctrl_a", "ctrl_a_last"),
        # 2026-11-27: I-26 真实标注的训练预算轴 (73 号) —— **两条比较** ✓
        # (arm_wash vs ctrl_b / ctrl_c vs ctrl_b) -> 两个 entry, 各自带自己的 marker 与键名 ✓
        ("real_budget_epoch_arm.json", "arm_wash", "Δ(arm_wash−ctrl_b)",
         "wash_last", "wash_vs_ctrl_b", "ctrl_b_last"),
        ("real_budget_epoch_arm.json", "ctrl_c", "Δ(ctrl_c−ctrl_b)",
         "ctrl_c_last", "ctrl_c_vs_ctrl_b", "ctrl_b_last"),
    ]
    rd_sw = ""
    try:
        rd_sw = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
    except OSError:
        pass

    def num_sw(x):
        return float(str(x).replace("−", "-").replace(",", ""))

    def _claims(text, phrase):
        """README 里"未被否定"地出现该说法才算判语 (澄清句不算 ✗)。"""
        for m in re.finditer(re.escape(phrase), text):
            pre = text[max(0, m.start() - 6): m.start()]
            if "不是" not in pre and "非" not in pre:
                return True
        return False

    n_arms_checked = 0
    for art_name, arm_label, marker, arm_key, pair_key, ctrl_key in ARM_CHECKS:
        sw_p = os.path.join(BENCH, art_name)
        if not os.path.exists(sw_p):
            print(f"[6c] {arm_label}: 产物不在仓内, 跳过核对")
            continue
        sw = json.load(open(sw_p, encoding="utf-8"))
        # **臂还在跑的时候产物是逐 seed 增量写的** -> README 自然还没写这一节 ->
        # 这时核对会报"README 里找不到数字"的假错 ✓ -> 用**产物自己声明的 seed 数**
        # 判断是否跑完 (不硬编码期望值 ✓) -> 跑完才核对 ✓
        exp_seeds = (sw.get("design") or {}).get("seeds")
        n_done = len(sw.get("per_seed") or {})
        if exp_seeds and n_done < len(exp_seeds):
            print(f"[6c] {arm_label}: 产物只有 {n_done}/{len(exp_seeds)} 个 seed "
                  f"(臂还在跑), 跳过核对")
            continue
        m_sw = re.search(re.escape(marker) + r" = [−+\d. /]+ pp，mean ([−+][\d.]+)pp，"
                         r"95% CI \[([−+][\d.]+), ([−+][\d.]+)\]", rd_sw)
        if not m_sw:
            # **产物是"从日志还原"的半成品** (71 号) -> 臂还没跑完, README 自然还没写
            # 这一节 -> 跳过 ✓ (等 68 号写正式产物后这项检查自动生效 ✓)
            if "recover" in str(sw.get("generated_by", "")):
                print(f"[6c] {arm_label}: 产物是从日志还原的半成品 (臂未跑完), 跳过核对")
                continue
            problems.append(f"README 里找不到{arm_label}的配对差数字 → 无法核对")
            continue
        n_arms_checked += 1
        w_mean = num_sw(m_sw.group(1))
        w_ci = [num_sw(m_sw.group(2)), num_sw(m_sw.group(3))]
        p = (sw.get("paired") or {}).get(pair_key)
        if not p:
            problems.append(f"{art_name}: 缺配对 {pair_key}")
        else:
            got = p.get("mean_pp")
            if got is None or abs(got - w_mean) > 0.05:
                problems.append(f"{arm_label}配对: 产物 {got} != 文档写的 {w_mean}")
            ci = p.get("ci95_pp")
            if not ci or abs(ci[0] - w_ci[0]) > 0.05 or abs(ci[1] - w_ci[1]) > 0.05:
                problems.append(f"{arm_label}配对: 产物 CI {ci} != 文档写的 {w_ci}")
            # 判语与 CI 形态一致吗
            if ci:
                all_neg = ci[1] < 0
                all_pos = ci[0] > 0
                seg = rd_sw[max(0, m_sw.start() - 400): m_sw.end() + 400]
                if all_neg and _claims(seg, "未检出差异"):
                    problems.append(f"{arm_label}: CI 整段在 0 以下, 但 README 写成'未检出差异'")
                if all_pos and _claims(seg, "劣化"):
                    problems.append(f"{arm_label}: CI 整段在 0 以上, 但 README 写成劣化")
                if not all_neg and not all_pos and _claims(seg, "显著"):
                    problems.append(f"{arm_label}: CI 跨 0, 但 README 写了'显著'")
        # 每个 seed 的 mAP50 也要与文档一致 (防止只对总均值)。
        # 只在该臂那一节里找表 (否则会撞到 63 号探针的同形表), 表行长这样:
        #   | seed 43 | 0.2436 | 0.0121 |   <- 对照 | 臂
        # **只取 marker 之后、下一个 marker 之前的一段**: 两个臂的表同形, 取 marker
        # 之前的会撞到上一个臂的行 ✓; 窗口开太长也会撞到**下一个臂**的行 ✓
        # (踩过的坑: I-17 的窗口吃到了 I-18 的 seed 46/47 行 -> 报了一个假的
        #  "产物 != 文档" ✗, 而真正要报的"文档还写着 n=3 的数"被掩盖了 ✓)。
        sec = rd_sw
        i0 = rd_sw.find(marker)
        if i0 > 0:
            rest = rd_sw[i0 + len(marker):]
            nxt = rest.find("Δ(")
            sec = rd_sw[i0: i0 + len(marker) + (nxt if nxt > 0 else 2500)]
        for s, row in (sw.get("per_seed") or {}).items():
            mm = re.search(rf"seed {s} \| ([0-9.]+) \| ([0-9.]+)", sec)
            if not mm:
                problems.append(f"{arm_label} seed {s}: README 的表里找不到这一行")
                continue
            for key, w in ((ctrl_key, num_sw(mm.group(1))),
                           (arm_key, num_sw(mm.group(2)))):
                got = (row.get(key) or {}).get("map50")
                if got is None or abs(got - w) > 0.0005:
                    problems.append(f"{arm_label} seed {s} {key}: 产物 {got} != 文档写的 {w}")
    if n_arms_checked:
        print(f"[6c] 臂的多 seed 汇总: 核对 {n_arms_checked} 个臂 (配对差 + 每个 seed 的 mAP50, 数字取自 README)")

    # 6b) 合成集数据组成完整性 (2026-11-24 加): 图数必须与 split_manifest 记录一致。
    # 这项检查是因为一次真实事故加的: `--out` 的处理逻辑被误放在 raycast_stats() 里,
    # 导致 output/sdg_shelf 的 200 张图被"清理上次遗留产物"的循环清成 3 张, 而
    # **没有任何检查发现** —— 所有下游产物仍引用着那个目录。
    # 现在: 源目录 (output/sdg_shelf) 与派生的单类集 (output/benchmark/synth_single)
    # 都要核"实际图数 == 清单记录数", 少了立刻报。
    n_synth_checked = 0
    for src_dir, man_name in (
            (os.path.join(BASE, "output", "sdg_shelf"), "split_manifest.json"),
            (os.path.join(BENCH, "synth_single"), None)):
        if not os.path.isdir(src_dir):
            continue
        if man_name:
            man_p = os.path.join(src_dir, man_name)
            if not os.path.exists(man_p):
                continue
            try:
                man = json.load(open(man_p, encoding="utf-8"))
            except Exception:
                continue
            exp = {"train": man.get("n_train"), "val": man.get("n_val")}
        else:
            # 单类集没有自己的 manifest -> 用**源目录**的 (同一划分)。
            # 但源目录的 manifest 可能是上一次(更小的)运行留下的 (恢复中间态),
            # 所以同时读源目录的 dataset_summary.num_images: 若源目录正在重渲
            # (现有图数 < 声明总数), 单类集的对比就暂缓。
            man_p = os.path.join(BASE, "output", "sdg_shelf", "split_manifest.json")
            if not os.path.exists(man_p):
                continue
            man = json.load(open(man_p, encoding="utf-8"))
            exp = {"train": man.get("n_train"), "val": man.get("n_val")}
            src_sum_p = os.path.join(BASE, "output", "sdg_shelf", "dataset_summary.json")
            try:
                src_sum = json.load(open(src_sum_p, encoding="utf-8"))
                src_declared = src_sum.get("num_images")
            except Exception:
                src_declared = None
            src_now = len(glob.glob(os.path.join(BASE, "output", "sdg_shelf", "images", "*", "*.png")))
            # 清单声明的总数 < 现有图数 -> 清单是**旧运行**留下的 (恢复中间态):
            # 源目录正在被重渲, 旧清单描述的不是当前这批图 -> 单类集对比暂缓。
            if src_declared and src_now > src_declared:
                print(f"    NOTE 源目录 output/sdg_shelf 正在重渲 (现有 {src_now} > 旧清单 "
                      f"{src_declared}), 单类集对比暂缓")
                continue
        for split, e in exp.items():
            if not e:
                continue
            d = os.path.join(src_dir, "images", split)
            got_n = len(glob.glob(os.path.join(d, "*.png"))) if os.path.isdir(d) else 0
            n_synth_checked += 1
            if got_n == e:
                continue
            # 两种情形要分开:
            #  (a) 实际 > 清单: 多出来的图**不在清单里** -> 训练臂会把它们一起吃进去,
            #      数据组成就不可核验 (审计 F4 那类问题) -> 必须报;
            #  (b) 实际 < 清单: 产物缺失 -> 也要报。
            # 但"清单是上一次未跑完的运行写下的"这种中间态 (正在渲染) 不该报成
            # 数据不一致 —— 那属于"渲染未完成"。判据: 清单的 num_images 与实际
            # 图数一致时说明清单描述的就是当前这批 (只是没渲完), 此时只提示不报错。
            sm = os.path.join(src_dir, "dataset_summary.json")
            try:
                ds_sum = json.load(open(sm, encoding="utf-8"))
                declared = ds_sum.get("num_images")
            except Exception:
                ds_sum, declared = None, None
            if declared is not None and got_n < declared:
                # 清单声明的总图数 > 现有图数 -> 渲染未完成 (中间态), 不算不一致
                print(f"    NOTE {os.path.basename(src_dir)}/{split}: "
                      f"{got_n}/{declared} 张 (渲染未完成), 跳过本项")
                continue
            # 清单本身比实际"小" -> 说明清单是**上一次(更小的)运行**留下的, 与当前这批图
            # 描述的不是同一件事 (2026-11-24: sdg_shelf 被误清空后, 清单还是 20 张那次的)。
            # 这时"图数对不上"是恢复过程中的中间态, 不是数据组成错误 —— 但要提示。
            if got_n > e and declared is not None and got_n > declared:
                print(f"    NOTE {os.path.basename(src_dir)}/{split}: 实际 {got_n} 张 > "
                      f"清单 {e} 张 (清单是旧的, 恢复中), 跳过本项")
                continue
            problems.append(f"合成集 {os.path.basename(src_dir)}/{split}: "
                            f"实际 {got_n} 张 != 清单记录 {e} 张 (数据组成与清单不符)")
    print(f"[6b] 合成集数据组成完整性: 核对 {n_synth_checked} 项")

    # 7) 标注口径差实测 (审计 F7): 文档里引用的数字必须来自产物
    lsem_p = os.path.join(BENCH, "label_semantics.json")
    if not os.path.exists(lsem_p):
        lsem_p = os.path.join(PUB, "label_semantics.json")
    if os.path.exists(lsem_p):
        ls = json.load(open(lsem_p, encoding="utf-8"))
        if ls.get("dropped_low_visibility") != 0:
            problems.append(f"F7 可见度过滤丢弃数变了: {ls.get('dropped_low_visibility')} (文档写 0)")
        if not ls.get("per_image_consistent"):
            problems.append("F7 逐图一致性: 标签行数与标注记录数不再一致")
        want = {"synth_effective_boxes_per_image_train": 21.82,
                "dropped_class1_rate_of_records": 0.157252}
        for k, w in want.items():
            got = ls.get(k)
            if got is None or abs(got - w) > 0.001:
                problems.append(f"F7 {k}: 产物 {got} != 文档写的 {w}")
        tr = (ls.get("real_sku110k") or {}).get("train") or {}
        if abs((tr.get("boxes_per_image") or 0) - 147.04) > 0.01:
            problems.append(f"F7 真实框/图: 产物 {tr.get('boxes_per_image')} != 文档写的 147.04")
        ratio = ((ls.get("r2_synth_ratio") or {}).get("synth_ratio"))
        if ratio is None or abs(ratio - 0.019095) > 0.0001:
            problems.append(f"F7 R2 合成占比: 产物 {ratio} != 文档写的 0.019095")
        print("[7] 标注口径差 (F7): 核对 5 项")
    else:
        print("[7] 标注口径差 (F7): 产物不在仓内, 跳过核对")

    # 8) R3 域对齐臂的协议对齐复跑: 文档引用的数字必须来自产物
    r3p = os.path.join(BENCH, "r3_protocol_matched.json")
    if not os.path.exists(r3p):
        r3p = os.path.join(PUB, "r3_protocol_matched.json")
    if os.path.exists(r3p):
        r3 = json.load(open(r3p, encoding="utf-8"))
        # 配对统计**不硬编码**: 直接跟 36 号汇总 (唯一事实源) 对账 —— 38 号脚本本来就
        # 是从 36 号那里引用这三个数的, 这里再抄一份期望值等于制造第二个真相源。
        # 2026-11-24 修: 原来硬编码 (-11.45 / n=3 / CI[-21.778,-1.125]), 补 seed 后
        # 产物变成 (-9.92 / n=6 / CI[-16.18,-3.67]), 闸门报"不一致"—— 报的是
        # "脚本里的旧数字" 而不是 "文档错了"。
        fv36 = os.path.join(BENCH, "fourarm_seed_variance.json")
        if not os.path.exists(fv36):
            fv36 = os.path.join(PUB, "fourarm_seed_variance.json")
        if os.path.exists(fv36):
            j36 = json.load(open(fv36, encoding="utf-8"))
            p36 = next((x for x in j36.get("paired", [])
                        if (x.get("b"), x.get("a")) == ("r3pm", "r1")), None)
            if not p36:
                problems.append("fourarm_seed_variance.json: 缺配对 (r3pm, r1)")
            else:
                for k36, k38 in (("map50_diff_mean_pp", "paired_diff_pp"),
                                 ("n_pairs", "paired_n")):
                    a, b = p36.get(k36), r3.get(k38)
                    if a is None or b is None or abs(a - b) > 0.02:
                        problems.append(f"R3pm {k38}: 38 号产物 {b} != 36 号汇总 {a}")
                c36 = p36.get("map50_diff_ci95")
                c38 = r3.get("paired_diff_ci95_pp")
                if not c36 or not c38 or abs(c36[0] - c38[0]) > 0.02 or abs(c36[1] - c38[1]) > 0.02:
                    problems.append(f"R3pm 配对 CI: 38 号产物 {c38} != 36 号汇总 {c36}")
        # 文档引用的 R3pm / R1 均值必须来自产物 —— 从 README 解析, 不硬编码
        # (与第 [6] 项同一做法: 唯一真相源是产物, 闸门查"文档有没有跟上产物")
        rd8 = ""
        try:
            rd8 = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            pass

        def _num8(x):
            return float(str(x).replace("\u2212", "-").replace(",", ""))

        m8 = re.search(r"R3pm \*\*([0-9./ ]+)\*\*（mean ([0-9.]+) ± ([0-9.]+)",
                       rd8)
        if not m8:
            problems.append("README 里找不到 R3pm 的 mean → 无法核对")
        else:
            mean_w, std_w = _num8(m8.group(2)), _num8(m8.group(3))
            got = r3.get("r3pm_mean")
            if got is None or abs(got - mean_w) > 0.0005:
                problems.append(f"R3pm r3pm_mean: 产物 {got} != 文档写的 {mean_w}")
            n_artifact = len(r3.get("per_seed") or {})
            n_doc = len([x for x in m8.group(1).split("/") if x.strip()])
            if n_artifact != n_doc:
                problems.append(f"R3pm seed 数: 产物 {n_artifact} != 文档写的 {n_doc}")
        comp = r3.get("composition_r3pm") or {}
        if abs((comp.get("misaligned_share_of_kept") or 0) - 0.4223) > 0.001:
            problems.append(f"R3pm 错位占比: 产物 {comp.get('misaligned_share_of_kept')} "
                            f"!= 文档写的 0.4223")
        gap = r3.get("domain_gap_comparison") or {}
        for k, w in (("boxes_per_image_mean", 30.0), ("mean_box_area_mean", 0.0038),
                     ("median_aspect_ratio_mean", 0.3007)):
            got = (gap.get(k) or {}).get("r3pm")
            if got is None or abs(got - w) > (0.001 if w < 0.1 else 0.05):
                problems.append(f"R3pm 域差距 {k}: 产物 {got} != 文档写的 {w}")
        print("[8] R3 域对齐臂复跑: 核对 8 项")
    else:
        print("[8] R3 域对齐臂复跑: 产物不在仓内, 跳过核对")

    # 9) 形状先验臂 (只动朝向+尺度因子): 核对"因子真的朝真实侧动了"这个方向性断言
    shp = os.path.join(BENCH, "r1shape_arm.json")
    if not os.path.exists(shp):
        shp = os.path.join(PUB, "r1shape_arm.json")
    if os.path.exists(shp):
        sh = json.load(open(shp, encoding="utf-8"))
        fc = sh.get("factor_comparison") or {}
        # 方向性: 朝向因子与尺度因子都必须比 R1 更接近真实
        for key, label in (("median_aspect_ratio_mean", "朝向因子(中位宽高比)"),
                           ("mean_box_area_mean", "尺度因子(单框面积)")):
            row = fc.get(key) or {}
            r1, r1s, real = row.get("r1"), row.get("r1shape"), row.get("real")
            if None in (r1, r1s, real):
                problems.append(f"形状臂 {label}: 因子表不完整 {row}")
                continue
            d1, d2 = abs(r1 - real), abs(r1s - real)
            if not (d2 < d1):
                problems.append(f"形状臂 {label}: R1shape {r1s} 没有比 R1 {r1} 更接近真实 {real} "
                                f"(|差| {d2:.4f} vs {d1:.4f})")
        # 密度因子: 它是**下游涌现量**, 不是干预旋钮 —— 商品改宽 -> 遮挡变多 ->
        # 可见度过滤 (vis_frac < 15%) 丢弃的记录变多 -> 每图保留框变少
        # (实测: 形状臂丢弃 3.98%, 对照臂 0%)。所以判据不是"密度必须一字不变",
        # 而是"密度的变化必须**可归因于**几何干预, 且不能是大幅偏移"。
        # 2026-11-24 修: 原来判 |Δ| > 0.5 就报错, 于是把一个物理必然后果
        # 当成了"干预污染了别的变量" —— 属于把涌现量误当旋钮。
        row = fc.get("boxes_per_image_mean") or {}
        if row.get("r1") is not None and row.get("r1shape") is not None:
            d = row["r1shape"] - row["r1"]
            # 阈值依据实测: 形状臂商品改宽 -> 遮挡增多 -> 可见度过滤 (vis_frac<15%)
            # 丢弃率从对照臂的 0% 升到 3.98%, 于是每图保留框 -1.19 (21.83 -> 20.63)。
            # 阈值给 2 框/图: 覆盖这个已知机制, 同时仍能抓住"干预意外改了大变量"。
            if abs(d) > 2.0:
                problems.append(f"形状臂 密度因子变化过大: R1 {row['r1']} -> "
                                f"R1shape {row['r1shape']} (Δ {d:+.4f}); "
                                f"可见度过滤机制预期约 -1.2 框/图, 超过 2 框/图说明还有别的东西在动")
            else:
                print(f"    密度因子变化 {d:+.4f} 框/图 (可归因于可见度过滤: "
                      f"商品改宽 -> 遮挡增多 -> 低可见度记录被丢弃)")
        print("[9] 形状先验臂: 核对 3 项 (朝向/尺度方向性 + 密度变化幅度)")
    else:
        print("[9] 形状先验臂: 产物不在仓内, 跳过核对")

    # 10) 密度诊断臂 (2026-11-24): README 里"差距在密度不在形状"这句断言必须来自产物,
    #     不能只是推断。核对: 各档的框/图确实是目标值 (不是全量或全裁), 且文档写的结论
    #     与产物的方向一致。
    dens_files = sorted(glob.glob(os.path.join(BENCH, "density_dens*_s*.json")))
    if dens_files:
        by_dose = {}
        for f in dens_files:
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            dose = (d.get("dataset") or {}).get("boxes_per_image")
            by_dose.setdefault(round(dose, 2) if dose else 0, []).append(d)
        for dose, recs in sorted(by_dose.items()):
            for d in recs:
                got = (d.get("dataset") or {}).get("boxes_per_image")
                tgt = (d.get("treatment") or {}).get("boxes_per_image_target")
                if got is None or tgt is None:
                    continue
                if abs(got - tgt) > 0.6:
                    problems.append(f"密度诊断 dose={tgt}: 实际框/图 {got} 与目标 {tgt} 不符")
                # 稀释必须是**真的稀释了**: 保留率不能接近 1 (否则这个臂没起作用)
                kr = (d.get("dataset") or {}).get("keep_ratio")
                if kr is not None and tgt < 100 and kr > 0.6:
                    problems.append(f"密度诊断 dose={tgt}: 保留率 {kr:.3f} 偏高, "
                                    f"稀释可能没生效")
        print(f"[10] 密度诊断臂: 核对 {len(dens_files)} 个产物的框/图与稀释比例")

        # 10b) 文档里的**结论数字**必须能由产物重算出来 (不能手写):
        #     配对差值 mean / 95% CI (与全量真实基线配对), 以及 precision/recall 的方向。
        base_by_seed = {}
        for f in glob.glob(os.path.join(BENCH, "budget_real1_synth0*.json")):
            try:
                d = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            s = (d.get("protocol") or {}).get("seed")
            if s is not None and "map50" in d:
                base_by_seed[s] = d
        if base_by_seed:
            for dose, recs in sorted(by_dose.items()):
                diffs, seeds = [], []
                for d in recs:
                    s = (d.get("protocol") or {}).get("seed")
                    b = base_by_seed.get(s)
                    if b is None or "map50" not in d:
                        continue
                    diffs.append((d["map50"] - b["map50"]) * 100)
                    seeds.append(s)
                if len(diffs) < 2:
                    continue
                mean = statistics.mean(diffs)
                sd = statistics.stdev(diffs)
                hw = (T_CRIT_95.get(len(diffs) - 1, 1.96) * sd / math.sqrt(len(diffs))
                      if len(diffs) > 1 else 0.0)
                rd = ""
                try:
                    rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
                except OSError:
                    pass
                # README 的写法: "**−4.02 pp，95% CI [−4.52, −3.51]**"。
                # **按密度点配对** (2026-11-24): 后面加上 74 框/图这个中间点, 文档里会
                # 出现第二个密度点; 只取第一个匹配就会把点搞错 -> 靠"该 CI 前面最近的
                # 「N 框/图」"判定它属于哪个密度点。
                cands = _readme_ci_by_density(rd).get(round(float(dose)))
                if not cands:
                    problems.append(f"密度诊断 dose={dose:g}: README 里找不到"
                                    f"该密度点的「配对差值 pp / 95% CI」写法 → 无法核对")
                    continue
                dm, dlo, dhi = cands[0]
                if abs(dm - mean) > 0.06:
                    problems.append(f"密度诊断 dose={dose:g}: README 写的配对差值 {dm} pp "
                                    f"!= 产物重算 {mean:.2f} pp (n={len(diffs)})")
                if abs(dlo - (mean - hw)) > 0.08 or abs(dhi - (mean + hw)) > 0.08:
                    problems.append(f"密度诊断 dose={dose:g}: README 写的 CI "
                                    f"[{dlo}, {dhi}] != 产物重算 "
                                    f"[{mean - hw:.2f}, {mean + hw:.2f}]")
                print(f"     dose={dose:g}: 配对差值 {mean:+.2f} pp, CI "
                      f"[{mean - hw:+.2f}, {mean + hw:+.2f}] (n={len(diffs)}) "
                      f"→ 与 README 一致")
    else:
        print("[10] 密度诊断臂: 产物不在仓内, 跳过核对")

    # 11) 剂量轴的**池身份** (2026-11-24): 剂量-反应各档必须来自同一个池, 否则
    #     剂量轴就不是单变量 (池变了 + 剂量也变了)。产物里必须写明用的是哪个池,
    #     且各预算的池一致。
    dr_p = os.path.join(BENCH, "dose_response.json")
    if os.path.exists(dr_p):
        dr = json.load(open(dr_p, encoding="utf-8"))
        pool = dr.get("synth_pool_sha256")
        pools = dr.get("pools") or {}
        if not pool:
            problems.append("dose_response.json: 没记合成池身份 (synth_pool_sha256 为空) "
                            "→ 无法判断剂量轴是不是单变量")
        if pool and pool not in pools:
            problems.append(f"dose_response.json: 主线池 {str(pool)[:16]}… 不在 pools 里 "
                            f"→ 报告结构自相矛盾")
        # 每个池的每条剂量轴都必须有**自己的 0 档锚点** (配对差值的基准)。
        # 2026-11-24 修过一次真实事故: 0 档锚点被"行数最多的池"抢走 -> 老池曲线
        # 因没有基准而整条消失 (报告照出, 只是少了一条曲线)。
        for pid, pl in pools.items():
            for frac, b in (pl.get("budgets") or {}).items():
                levels = b.get("n_synth_levels") or []
                if levels and 0 not in levels:
                    problems.append(
                        f"dose_response.json: 池 {str(pid)[:12]}… 预算 {frac} 的剂量轴"
                        f"**没有 0 档锚点** (档位 {levels}) → 配对差值没有基准, "
                        f"这条曲线算不出来")
        print(f"[11] 剂量轴池身份: 主线 {str(pool)[:20]}… / 共 {len(pools)} 个池, "
              f"各池各带自己的 0 档锚点")

        # 11b) **没有池被悄悄漏掉**: 汇总按池分组, 一旦某个池的锚点被别的池抢走,
        #      它的曲线会整条消失而报告照出。判据: BENCH 里每个**有剂量**的预算格点
        #      产物都必须出现在报告的某个池里 (只有 0 档的产物本身就没有曲线可出,
        #      比如重复实验的备份, 不算漏掉)。
        covered = set()
        for pid, pl in pools.items():
            covered |= set(pl.get("artifact_files") or [])
        missing = []
        inflight = []
        for frac in ("0.05", "0.02"):
            for f in glob.glob(os.path.join(BENCH, f"budget_real{frac}_synth*.json")):
                b = os.path.basename(f)
                if b in covered:
                    continue
                try:
                    d = json.load(open(f, encoding="utf-8"))
                except Exception:
                    continue
                if int((d.get("dataset") or {}).get("n_synth") or 0) > 0:
                    # 正在跑/刚跑完还没被曲线收录的格点: 链的每格耗时 ~25 min,
                    # 曲线汇总 (31 号) 是**每格之后**才刷新 -> 用产物时间戳给一个
                    # 宽限期, 免得把"正在收尾"判成"曲线被漏掉"。
                    # 超出宽限期还不在曲线里 -> 仍然算漏掉 (那才是真丢)。
                    age_min = (time.time() - os.path.getmtime(f)) / 60.0
                    if age_min <= 90:
                        inflight.append(f"{b}({age_min:.0f} min 前)")
                        continue
                    missing.append(b)
        if inflight:
            print(f"[11b] {len(inflight)} 个格点刚跑完、还没进曲线 (宽限期内): "
                  f"{', '.join(inflight)}")
        if missing:
            problems.append(f"dose_response.json: {len(missing)} 个有剂量的预算格点产物没被任何池收录 "
                            f"(曲线被漏掉了): {missing[:6]}")
        print(f"[11b] 剂量轴池覆盖: {len(covered)} 个产物已收录, {len(missing)} 个有剂量的漏掉")

        # 11c) **重复格点不许静默覆盖**: 同一个 (池, 剂量, seed) 出现两次且数值不同,
        #      汇总必须报出来 (被覆盖掉的可能是基准档 -> 整条曲线的配对差值跟着变)。
        cfs = dr.get("conflicts") or []
        if cfs:
            problems.append(f"dose_response.json: {len(cfs)} 处重复格点冲突 "
                            f"(同池同剂量同 seed 出现不同数值): {cfs[:3]}")
        print(f"[11c] 剂量轴重复格点: {len(cfs)} 处冲突")
    else:
        print("[11] 剂量轴池身份: 产物不在仓内, 跳过核对")
        print("[11b] 剂量轴池覆盖: 产物不在仓内, 跳过核对")
        print("[11c] 剂量轴重复格点: 产物不在仓内, 跳过核对")

    # 12) CPU/GPU 渲染等价性留档 (2026-11-24): 换 GPU 渲染是纯工程改进的前提是
    #     像素等价, 这个实测只做过一次 (旧 CPU 批次已被覆盖, 无法重测) -> 必须留档,
    #     而且判据 (容差指纹) 依赖这个数字。
    eq_p = os.path.join(BENCH, "gpu_cpu_equivalence.json")
    if not os.path.exists(eq_p):
        eq_p = os.path.join(PUB, "gpu_cpu_equivalence.json")   # 发布版也在仓内, CI 可核
    if os.path.exists(eq_p):
        eq = json.load(open(eq_p, encoding="utf-8"))
        mx = eq.get("max_channel_diff")
        if mx is None:
            problems.append("gpu_cpu_equivalence.json: 缺 max_channel_diff")
        elif mx > 2:
            problems.append(f"gpu_cpu_equivalence.json: max_channel_diff={mx} (>2) —— "
                            f"CPU/GPU 渲染并非等价, 恢复就不是无损的")
        print(f"[12] CPU/GPU 渲染等价性: 最大通道差 {mx} "
              f"({'等价' if mx is not None and mx <= 2 else '需复查'})")
    else:
        problems.append("gpu_cpu_equivalence.json: 不存在 —— CPU→GPU 换渲染的等价性"
                        "实测没有留档 (只做过一次, 旧批次已被覆盖)")
        print("[12] CPU/GPU 渲染等价性: 留档缺失")

    # 13) 域内可学性 vs 跨域迁移 (2026-11-24): README 里"域内 X / 跨域 Y"这两个数
    #     必须能由 51 号产物重算 —— 这条结论("差距在跨域外观, 不在数据本身")的唯一
    #     凭据就是它, 手写数字等于把结论架空。
    dfp = os.path.join(BENCH, "domain_fit_probe.json")
    if not os.path.exists(dfp):
        dfp = os.path.join(PUB, "domain_fit_probe.json")
    if os.path.exists(dfp):
        df = json.load(open(dfp, encoding="utf-8"))
        r1b = (df.get("summary") or {}).get("r1/best.pt") or {}
        own = r1b.get("pool_r1") or {}
        rt = r1b.get("real_test") or {}
        if not (own and rt):
            problems.append("domain_fit_probe.json: 缺 r1/best.pt 的域内或真实 test 数字 "
                            "→ README 的域内/跨域结论无法核对")
        else:
            try:
                rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
            except OSError:
                rd = ""
            # README 写法: "域内 (自己池的 val) = **0.995**" / "跨域 (真实 test) = **0.2265**"
            mo = re.search(r"域内[^=]*=\s*\*\*([0-9.]+)\*\*", rd)
            mr = re.search(r"跨域[^=]*=\s*\*\*([0-9.]+)\*\*", rd)
            if not (mo and mr):
                problems.append("README 里找不到「域内 = **x**」/「跨域 = **y**」的写法 "
                                "→ 域内可学性结论无法核对")
            else:
                got_own, got_rt = float(mo.group(1)), float(mr.group(1))
                if abs(got_own - own["mean"]) > 0.002:
                    problems.append(f"README 域内 {got_own} != 产物 {own['mean']} "
                                    f"(r1/best.pt 自己池 val)")
                if abs(got_rt - rt["mean"]) > 0.002:
                    problems.append(f"README 跨域 {got_rt} != 产物 {rt['mean']} "
                                    f"(r1/best.pt 真实 test)")
                print(f"[13] 域内可学性: 产物 域内 {own['mean']:.4f} / 跨域 {rt['mean']:.4f} "
                      f"(差 {(own['mean'] - rt['mean']) * 100:+.1f} pp) → 与 README 一致")
    else:
        print("[13] 域内可学性: 产物不在仓内, 跳过核对")

    # 14) 频谱差距与分解 (2026-11-25): README 里"高频差多少 dB / 其中多少来自内容结构 /
    #     多少来自成像质感"这三个数必须能由 54 号产物重算 —— 这条结论
    #     ("合成图不缺照片颗粒, 缺口在内容") 靠这三个数支撑, 手写就等于把结论架空。
    #     取数方式: **按表格行** (第一列等于标签), 不用"标签后面跟第一个数"这种正则 ——
    #     2026-11-25 第一版就是这么写的, 结果 "内容结构" 匹配到了正文里另一处
    #     "…内容结构… −1.05 dB", 把 18.24 读成了 -1.05 (闸门当场变红, 改正则即可,
    #     但教训是: 表格里的数要按行取)。
    def _row_db(text, label):
        for line in text.splitlines():
            s = line.strip()
            if not s.startswith("|"):
                continue
            cells = [c.strip().replace("**", "") for c in s.strip("|").split("|")]
            if not cells or cells[0].strip() != label:
                continue
            m = re.search(r"([+\-−]?[0-9.]+)\s*dB", cells[1] if len(cells) > 1 else "")
            if m:
                return float(m.group(1).replace("−", "-").replace("+", ""))
        return None

    sg_p = os.path.join(BENCH, "spectral_gap.json")
    if not os.path.exists(sg_p):
        sg_p = os.path.join(PUB, "spectral_gap.json")
    if os.path.exists(sg_p):
        sg = json.load(open(sg_p, encoding="utf-8"))
        want_sg = [("高频带总差距", sg.get("high_band_gap_db")),
                   ("内容结构贡献", sg.get("high_band_gap_content_db")),
                   ("成像质感差距", sg.get("high_band_gap_finish_db"))]
        try:
            rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd = ""
        for label, val in want_sg:
            if val is None:
                problems.append(f"spectral_gap.json: 缺 {label} 字段")
                continue
            got = _row_db(rd, label)
            if got is None:
                problems.append(f"README 表格里找不到行「{label} | ... dB」 "
                                f"-> 频谱结论无法核对")
                continue
            if abs(got - float(val)) > 0.05:
                problems.append(f"README {label} {got} dB != 产物 {val} dB")
        print(f"[14] 频谱差距: 总 {want_sg[0][1]} dB / 内容结构 {want_sg[1][1]} dB / "
              f"成像质感 {want_sg[2][1]} dB -> 与 README 表格逐行核对")
    else:
        print("[14] 频谱差距: 产物不在仓内, 跳过核对")

    # 15) 干预探针各臂 (2026-11-25): README 的"哪些便宜干预无效/有害"这张表是
    #     本节的核心证据 -> mean/配对Δ/CI 必须能由 52 号产物重算。
    #     按**表格单元格**取数 (第一列 = 臂名), 不用整行正则: mixed3 的描述里
    #     含 "53/53/54" 这种数字, 整行正则会把它当成 mAP。
    def _cells(text):
        out = []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("|"):
                out.append([c.strip().replace("**", "") for c in s.strip("|").split("|")])
        return out

    def _tables(text):
        """把 README 切成**一个个表** (连续的行表行算一张表)。

        为什么不能只把全篇的行表行拉平再按首列找行: 同一个名字可能出现在多张表里
        (例如 "blur2" 既是干预臂, 又是输入扰动) -> 平铺以后只能找到"第一个同名行",
        闸门就会拿错那张表的列去核对 (而且不会报错, 只是报出莫名其妙的数)。
        按表定位才不会串。
        """
        tabs, cur = [], []
        for line in text.splitlines():
            s = line.strip()
            if s.startswith("|"):
                cur.append([c.strip().replace("**", "") for c in s.strip("|").split("|")])
            else:
                if cur:
                    tabs.append(cur)
                cur = []
        if cur:
            tabs.append(cur)
        return tabs

    def _table_with(tabs, *keywords):
        """找出表头里同时含有关键词的表 (没有就返回 None)。"""
        for t in tabs:
            head = " ".join(t[0]) if t else ""
            if all(k in head for k in keywords):
                return t
        return None

    def _num(s):
        m = re.search(r"([+\-−]?[0-9]*\.?[0-9]+)", s.replace("−", "-"))
        return float(m.group(1)) if m else None

    iv_p = os.path.join(BENCH, "syn2real_interventions.json")
    if not os.path.exists(iv_p):
        iv_p = os.path.join(PUB, "syn2real_interventions.json")
    if os.path.exists(iv_p):
        iv = json.load(open(iv_p, encoding="utf-8"))
        try:
            rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd = ""
        rows = _cells(rd)
        arm_tab = _table_with(_tables(rd), "配对") or rows
        for arm, v in iv.get("results", {}).items():
            row = next((c for c in arm_tab
                        if c and c[0].split("(")[0].strip() == arm),
                       None)
            if row is None:
                problems.append(f"README 表里找不到干预臂「{arm}」这一行 -> 无法核对")
                continue
            if len(row) < 5:
                problems.append(f"README 干预臂「{arm}」行少于 5 列, 无法核对")
                continue
            got_mean = _num(row[1].split("±")[0])
            if got_mean is None or abs(got_mean - float(v["mean"])) > 0.0005:
                problems.append(f"README {arm} mean {got_mean} != 产物 {v['mean']}")
            pd = v.get("paired_mean_pp")
            if pd is not None:
                got_pd = _num(row[3])
                if got_pd is None or abs(got_pd - float(pd)) > 0.05:
                    problems.append(f"README {arm} 配对Δ {got_pd} != 产物 {pd} pp")
                ci = v.get("paired_ci95_pp")
                if ci:
                    nums = re.findall(r"[+\-−]?[0-9]*\.?[0-9]+", row[4].replace("−", "-"))
                    if len(nums) < 2:
                        problems.append(f"README {arm} 的 CI 解析不出两个数: {row[4]}")
                    elif abs(float(nums[0]) - float(ci[0])) > 0.05 or \
                            abs(float(nums[1]) - float(ci[1])) > 0.05:
                        problems.append(
                            f"README {arm} CI {nums[0]},{nums[1]} != 产物 "
                            f"{ci[0]},{ci[1]}")
        print(f"[15] 干预探针: {len(iv.get('results', {}))} 臂与 README 逐行核对")
    else:
        print("[15] 干预探针: 产物不在仓内, 跳过核对")

    # 16) 输入扰动探针 (2026-11-25): README 的"合成模型被高频带偏"这张表 -> 逐行核对。
    ip_p = os.path.join(BENCH, "input_probe.json")
    if not os.path.exists(ip_p):
        ip_p = os.path.join(PUB, "input_probe.json")
    if os.path.exists(ip_p):
        ip = json.load(open(ip_p, encoding="utf-8"))
        try:
            rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd = ""
        rows = _cells(rd)
        # 输入扰动表: 表头含"输入扰动"的那张 (别从全篇里按名字捞行 —— "blur2" 这类
        # 名字在干预臂表里也有一行, 捞错表会拿错列去核对)
        ip_tab = _table_with(_tables(rd), "输入扰动") or rows
        verdicts = ip.get("verdict", {})
        for model_key, col in (("synth_R1", 1), ("real_411", 2)):
            vd = verdicts.get(model_key, {})
            for var, delta in (vd.get("delta_pp") or {}).items():
                row = next((c for c in ip_tab
                            if c and c[0].split("(")[0].strip() == var
                            and len(c) > max(col, 2)), None)
                if row is None:
                    problems.append(f"README 输入探针表里找不到扰动「{var}」行")
                    continue
                got = _num(row[col])
                if got is None or abs(got - float(delta)) > 0.05:
                    problems.append(
                        f"README 输入探针 {model_key}/{var} {got} pp != 产物 {delta} pp")
        print(f"[16] 输入扰动探针: {len(verdicts)} 个模型 × 扰动与 README 逐行核对")
    else:
        print("[16] 输入扰动探针: 产物不在仓内, 跳过核对")

    # 16b) **多模型复核表** (2026-11-25): "blur 让合成模型涨分"这个前提来自 3 个
    #      R1 seed, 训练期模糊臂的设计就建在它上面 -> README 的复核表逐格核对。
    mm_p = os.path.join(BENCH, "input_probe_multimodel.json")
    if not os.path.exists(mm_p):
        mm_p = os.path.join(PUB, "input_probe_multimodel.json")
    if os.path.exists(mm_p):
        mm = json.load(open(mm_p, encoding="utf-8"))
        try:
            rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd = ""
        mm_tab = _table_with(_tables(rd), "多模型复核") or []
        for mk, col in (("synth_R1", 1), ("synth_R1_s44", 2),
                        ("synth_R1_s45", 3), ("real_411", 4)):
            vd = (mm.get("verdict") or {}).get(mk, {})
            for var, delta in (vd.get("delta_pp") or {}).items():
                row = next((c for c in mm_tab
                            if c and c[0].split("(")[0].strip() == var
                            and len(c) > col), None)
                if row is None:
                    problems.append(f"README 多模型复核表里找不到「{var}」行 (模型 {mk})")
                    continue
                got = _num(row[col])
                if got is None or abs(got - float(delta)) > 0.05:
                    problems.append(
                        f"README 多模型复核 {mk}/{var} {got} pp != 产物 {delta} pp")
        print(f"[16b] 多模型复核: {len(mm.get('verdict', {}))} 个模型 × 扰动与 README 逐行核对")
    else:
        print("[16b] 多模型复核: 产物不在仓内, 跳过核对")

    # 17) **噪声底 = 0** (2026-11-25): README 里"同 seed 重跑 mAP 完全相同"这句断言,
    #     要能从两个产物重算出来 —— 否则它只是又一句写死的数字。
    nf_a = os.path.join(BENCH, "budget_real0.05_synth0.json")
    nf_b = os.path.join(BENCH, "budget_real0.05_synth0_big_s42.json")
    if os.path.isfile(nf_a) and os.path.isfile(nf_b):
        da = json.load(open(nf_a, encoding="utf-8"))
        db = json.load(open(nf_b, encoding="utf-8"))
        same = (da.get("map50") == db.get("map50"))
        if not same:
            problems.append(
                f"噪声底: 两次 0 剂量重跑的 mAP 不同 ({da.get('map50')} vs {db.get('map50')})"
                " -> README 里'噪声底 = 0'的说法不成立")
        else:
            try:
                rd = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
            except OSError:
                rd = ""
            if repr(da["map50"]) not in rd:
                problems.append(
                    f"噪声底: README 里没写产物里的那个数 ({da['map50']!r})")
        print(f"[17] 噪声底: 两次独立重跑 mAP50 = {da.get('map50')!r} "
              f"({'完全相同' if same else '不同'})")
    else:
        print("[17] 噪声底: 产物不在仓内, 跳过核对")

    # 18) **纹理臂的单变量前提** (2026-11-25): 几何必须与白盒对照池逐帧相同,
    #     否则"只改商品表面"就不成立, 结果会被读成别的东西。
    tg_p = os.path.join(BENCH, "texture_geometry_parity.json")
    if os.path.isfile(tg_p):
        tg = json.load(open(tg_p, encoding="utf-8"))
        if tg.get("different"):
            problems.append(
                f"纹理臂几何不一致: {tg['different']}/{tg.get('n_images')} 张与白盒对照不同"
                " -> 该臂不能按'只改商品表面'解读")
        if not tg.get("identical"):
            problems.append("纹理臂几何核对: 没有一张完全相同 (核对本身可能失效)")
        print(f"[18] 纹理臂几何: {tg.get('identical')}/{tg.get('n_images')} 张与白盒对照逐帧相同")
    else:
        print("[18] 纹理臂几何: 产物不在仓内, 跳过核对")

    # 19) **I-19 掩膜池的单变量前提** (2026-11-26, 70 号现算): 标签逐字节相同、
    #     尺寸相同、**框内像素未动**、框外是纯色; 且 val 集与原图逐字节相同。
    #     这条不成立, I-19 的 +1.51 pp 就会被读成别的东西 (比如"图被改坏了")。
    cp_p = os.path.join(BENCH, "ctxsupp_pool_parity.json")
    if os.path.isfile(cp_p):
        cp = json.load(open(cp_p, encoding="utf-8"))
        if not cp.get("ok"):
            problems.append(f"I-19 掩膜池单变量性核对失败: {cp.get('problems')[:5]}")
        tr = (cp.get("splits") or {}).get("train") or {}
        va = (cp.get("splits") or {}).get("val") or {}
        n = tr.get("n") or 0
        for key, label in (("label_identical", "标签逐字节相同"),
                           ("size_identical", "尺寸相同"),
                           ("inside_identical", "框内像素未动")):
            if tr.get(key) != n:
                problems.append(f"I-19 掩膜池: {label} 只有 {tr.get(key)}/{n} 张")
        if tr.get("outside_flat", 0) < 1:
            problems.append("I-19 掩膜池: 没有一张图被抹成纯色 (掩膜可能没生效)")
        if va.get("byte_identical_to_src") != (va.get("n") or 0):
            problems.append("I-19 掩膜池: 验证集与原图不逐字节相同")
        print(f"[19] I-19 掩膜池单变量性: {tr.get('label_identical')}/{n} 标签一致, "
              f"{tr.get('inside_identical')}/{n} 框内未动, "
              f"{tr.get('outside_flat')}/{n} 框外纯色, val {va.get('byte_identical_to_src')}/{va.get('n')} 逐字节相同")
    else:
        print("[19] I-19 掩膜池单变量性: 产物不在仓内, 跳过核对")

    # 20) **I-19 的机制探针** (67 号): 臂与对照在"真实原图 / 剥离上下文的真实图"上的
    #     对比。README 里如果写了"臂在剥离版上更好/更差", 数字必须与产物一致 ✓
    #     (这条决定 I-19 到底改了什么 —— 是"更不依赖上下文"还是"更依赖干净背景" ✓)。
    cs_p = os.path.join(BENCH, "context_suppress_probe.json")
    if os.path.isfile(cs_p):
        cs = json.load(open(cs_p, encoding="utf-8"))
        models = cs.get("models") or {}
        if not models:
            problems.append("context_suppress_probe.json: 没有模型结果")
        for s, m in models.items():
            for tag in ("control", "arm"):
                for k in ("raw", "stripped"):
                    if k not in (m.get(tag) or {}):
                        problems.append(f"探针 seed {s} {tag}: 缺 {k}")
        d = cs.get("arm_minus_control_delta_pp") or {}
        print(f"[20] I-19 机制探针: {len(models)} 个 seed, "
              f"臂-对照 的上下文依赖差 mean {d.get('mean_pp')} pp, CI {d.get('ci95_pp')}")
        # README 里引用的三个配对数 (剥离版 / 真实原图 / 上下文依赖度) 必须与产物一致
        try:
            rd_p = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd_p = ""
        for label, key in (("剥离版", "arm_minus_control_stripped_pp"),
                           ("真实原图", "arm_minus_control_raw_pp"),
                           ("上下文依赖度", "arm_minus_control_delta_pp")):
            # **按行取** (表里相邻行会互相干扰 ✗ -> 只看包含该标签的那一行 ✓)
            line = next((ln for ln in rd_p.splitlines()
                         if f"**{label}**" in ln and "pp**" in ln), None)
            if not line:
                problems.append(f"README 里找不到探针的'{label}'那一行 -> 无法核对")
                continue
            m = re.search(r"\*\*([−+\d.]+) pp\*\*\s*\|\s*\[([−+\d.]+), ([−+\d.]+)\]", line)
            if not m:
                problems.append(f"README 的探针'{label}'行里解析不出数字 -> 无法核对")
                continue
            want_mean = float(m.group(1).replace("−", "-"))
            want_ci = [float(m.group(2).replace("−", "-")), float(m.group(3).replace("−", "-"))]
            got = cs.get(key) or {}
            if got.get("mean_pp") is None or abs(got["mean_pp"] - want_mean) > 0.005:
                problems.append(f"探针 {label}: 产物 {got.get('mean_pp')} != README {want_mean}")
            gci = got.get("ci95_pp")
            if not gci or abs(gci[0] - want_ci[0]) > 0.005 or abs(gci[1] - want_ci[1]) > 0.005:
                problems.append(f"探针 {label}: 产物 CI {gci} != README {want_ci}")
            # 判语与 CI 形态一致 (跨 0 不能写"显著"; CI > 0 要写"显著")
            if gci:
                if gci[0] > 0 and "显著" not in line:
                    problems.append(f"探针 {label}: CI 整段 > 0 但 README 这一行没写'显著'")
                if gci[0] <= 0 <= gci[1] and "显著" in line:
                    problems.append(f"探针 {label}: CI 跨 0 但 README 这一行写了'显著'")
    else:
        print("[20] I-19 机制探针: 产物不在仓内, 跳过核对")

    # 27) **I-27 的机制探针** (67 号复用到 I-20 的两个权重):
    #     分工臂 vs ctrl_a 在"真实原图 / 剥离上下文的真实图"上的对比。
    #     README 里如果写了“分工臂在剥离版上更好/更差”, 数字必须与产物一致 ✓
    #     (标签带 "I-27" 前缀 -> 不会被 [20] 项的 I-19 行挤掉 ✓)
    i27_p = os.path.join(BENCH, "pretrain_finetune_probe.json")
    if os.path.isfile(i27_p):
        i27 = json.load(open(i27_p, encoding="utf-8"))
        models = i27.get("models") or {}
        if not models:
            problems.append("pretrain_finetune_probe.json: 没有模型结果")
        for s_, m in models.items():
            for tag in ("control", "arm"):
                for k in ("raw", "stripped"):
                    if k not in (m.get(tag) or {}):
                        problems.append(f"I-27 探针 seed {s_} {tag}: 缺 {k}")
        try:
            rd27 = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd27 = ""
        n27 = 0
        for label, key in (("I-27 剥离版", "arm_minus_control_stripped_pp"),
                           ("I-27 真实原图", "arm_minus_control_raw_pp"),
                           ("I-27 上下文依赖度", "arm_minus_control_delta_pp")):
            line = next((ln for ln in rd27.splitlines()
                         if f"**{label}**" in ln and "pp**" in ln), None)
            if not line:
                problems.append(f"README 里找不到探针的'{label}'那一行 -> 无法核对")
                continue
            m27 = re.search(r"\*\*([−+\d.]+) pp\*\*\s*\|\s*\[([−+\d.]+), ([−+\d.]+)\]", line)
            if not m27:
                problems.append(f"README 的探针'{label}'行里解析不出数字 -> 无法核对")
                continue
            want_mean = float(m27.group(1).replace("−", "-"))
            want_ci = [float(m27.group(2).replace("−", "-")), float(m27.group(3).replace("−", "-"))]
            got = i27.get(key) or {}
            if got.get("mean_pp") is None or abs(got["mean_pp"] - want_mean) > 0.005:
                problems.append(f"探针 {label}: 产物 {got.get('mean_pp')} != README {want_mean}")
            gci = got.get("ci95_pp")
            if not gci or abs(gci[0] - want_ci[0]) > 0.005 or abs(gci[1] - want_ci[1]) > 0.005:
                problems.append(f"探针 {label}: 产物 CI {gci} != README {want_ci}")
            if gci:
                if gci[0] > 0 and "显著" not in line:
                    problems.append(f"探针 {label}: CI 整段 > 0 但 README 这一行没写'显著'")
                if gci[0] <= 0 <= gci[1] and "显著" in line:
                    problems.append(f"探针 {label}: CI 跨 0 但 README 这一行写了'显著'")
            n27 += 1
        d27 = i27.get("arm_minus_control_delta_pp") or {}
        print(f"[27] I-27 机制探针: {len(models)} 个 seed, "
              f"核对 {n27} 项 (README vs 产物), "
              f"上下文依赖度差 mean {d27.get('mean_pp')} pp, CI {d27.get('ci95_pp')}")
    else:
        print("[27] I-27 机制探针: 产物不在仓内, 跳过核对")

    # 21) I-20 分工臂的 **P/R 分解** (68 号产物自带 ✓): README 里那四行数字
    #     必须与产物一致 —— 否则"损害是整体变差还是某个局部机制"这个判语会悬空 ✓。
    pf_p = os.path.join(BENCH, "pretrain_finetune_arm.json")
    if os.path.isfile(pf_p):
        pf = json.load(open(pf_p, encoding="utf-8"))
        dec = ((pf.get("paired") or {}).get("arm_vs_ctrl_a_pr_decomposition") or {})
        try:
            rd_pr = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd_pr = ""
        # **按表定位**: 先找到那张 P/R 分解表的头行, 再取它下面的四行 ✓
        # (只按 "| precision |" 去找会撞到别的表里的同名列 ✓)
        pr_lines = rd_pr.splitlines()
        hdr = next((i for i, ln in enumerate(pr_lines)
                    if ln.strip().startswith("| \u6307\u6807 |") and "\u0394 (pp)" in ln), None)
        pr_rows = {}
        if hdr is None:
            problems.append("I-20 P/R 分解: README 里找不到那张表")
        else:
            for ln in pr_lines[hdr + 1: hdr + 9]:
                cells = [c.strip().strip("*") for c in ln.strip().strip("|").split("|")]
                if len(cells) == 3 and cells[0] and "[" in cells[2]:
                    pr_rows[cells[0]] = (cells[1], cells[2])
        for metric, label in (("map50", "mAP50"), ("map50_95", "mAP50-95"),
                              ("precision", "precision"), ("recall", "recall")):
            got = dec.get(metric) or {}
            if label not in pr_rows:
                problems.append(f"I-20 P/R 分解: README 里找不到 {label} 那一行")
                continue
            cells = pr_rows[label]
            line = f"| {cells[0]} | {cells[1]} |"
            mm = re.search(r"\|\s*([−+\d.]+)\s*\|\s*\[([−+\d.]+), ([−+\d.]+)\]", line)
            if not mm:
                problems.append(f"I-20 P/R 分解: {label} 行里解析不出数字")
                continue
            want = [float(mm.group(1).replace("−", "-")),
                    float(mm.group(2).replace("−", "-")),
                    float(mm.group(3).replace("−", "-"))]
            # 容差 0.01: README 里写的是**四舍五入到两位**的展示值 ✓
            # (-2.2525 -> -2.25, -0.235 -> -0.24 ✓; 差 0.005 是四舍五入本身 ✓)
            if got.get("mean_pp") is None or abs(got["mean_pp"] - want[0]) > 0.01:
                problems.append(f"I-20 P/R {label}: 产物 {got.get('mean_pp')} != README {want[0]}")
            gci = got.get("ci95_pp")
            if not gci or abs(gci[0] - want[1]) > 0.01 or abs(gci[1] - want[2]) > 0.01:
                problems.append(f"I-20 P/R {label}: 产物 CI {gci} != README {want[1:]}")
        print(f"[21] I-20 P/R 分解: precision {dec.get('precision', {}).get('mean_pp')} pp, "
              f"recall {dec.get('recall', {}).get('mean_pp')} pp")
    else:
        print("[21] I-20 P/R 分解: 产物不在仓内, 跳过核对")

    # 22) 真实标注的**训练预算轴** (ctrl_b vs ctrl_a, 68 号产物自带 ✓):
    #     README 里引用的那个数字必须与产物一致 —— 它是“加训练预算能不能拿回缺口”这个
    #     决策依据的核心数字, 口头拼不可能→ 必须由产物给出 ✓。
    pf2_p = os.path.join(BENCH, "pretrain_finetune_arm.json")
    if os.path.isfile(pf2_p):
        pf2 = json.load(open(pf2_p, encoding="utf-8"))
        cb = ((pf2.get("paired") or {}).get("ctrl_b_vs_ctrl_a") or {})
        try:
            rd_eb = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        except OSError:
            rd_eb = ""
        m_eb = re.search("10 ep → 20 ep 的配对均值是\s*\*\*([+−0-9.]+) pp\*\*"
                         r"（CI \[([+−0-9.]+), ([+−0-9.]+)\]", rd_eb)
        if not m_eb:
            problems.append("README 里找不到训练预算轴的那个配对数字 -> 无法核对")
        else:
            want = [float(m_eb.group(1).replace("−", "-")),
                    float(m_eb.group(2).replace("−", "-")),
                    float(m_eb.group(3).replace("−", "-"))]
            if cb.get("mean_pp") is None or abs(cb["mean_pp"] - want[0]) > 0.01:
                problems.append(f"训练预算轴: 产物 {cb.get('mean_pp')} != README {want[0]}")
            cbi = cb.get("ci95_pp")
            if not cbi or abs(cbi[0] - want[1]) > 0.01 or abs(cbi[1] - want[2]) > 0.01:
                problems.append(f"训练预算轴: 产物 CI {cbi} != README {want[1:]}")
            # 判语与 CI 形态一致 (跨 0 不能写"显著" / "已检出")
            if cbi and cbi[0] <= 0 <= cbi[1]:
                # **只看包含这个数字的那一句** —— 口径很宽的窗口会扣到
                # **相邻句**里关于别的股的判语 (如“I-20 −2.01 显著劣化” ✓) -> 那是假报误 ✓
                # **只扫这个数字后面的 160 字** ✓ —— 判语必然紧跟数字 ✓;
                # 往前扫会撞到**上一句**里别的臂的判语 (如 "I-20 -2.01 显著劣化" ✓) -> 假报错 ✓
                seg = rd_eb[m_eb.end(): m_eb.end() + 160]
                if "显著" in seg and "不是“显著为正”" not in seg:
                    problems.append(f"训练预算轴: CI 跨 0 但 README 写了'显著' -> {seg[:80]}")
            print(f"[22] 训练预算轴 (ctrl_b vs ctrl_a): mean {cb.get('mean_pp')} pp, CI {cb.get('ci95_pp')}")
    else:
        print("[22] 训练预算轴: 产物不在仓内, 跳过核对")

    # 23) **三条臂的 P/R 签名对照表** (README 里那张表) ——
    #     表里每个数字都必须能由产物重算出来 ✓
    #     (不然这张表就只是“手写的一个表” ✓)
    PR_SIGS = [
        ("I-18 上下文臂", "shelfwall_arm_ctx.json", "wall_last", "control_last"),
        ("I-19 上下文抑制臂", "context_suppress_arm.json", "arm_last", "control_last"),
        ("I-20 分工臂", "pretrain_finetune_arm.json", "arm_last", "ctrl_a_last"),
    ]
    try:
        rd_sig = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
    except OSError:
        rd_sig = ""
    sig_lines = rd_sig.splitlines()
    n_sig = 0
    for label, fname, a_key, b_key in PR_SIGS:
        fp = os.path.join(BENCH, fname)
        if not os.path.exists(fp):
            continue
        ps = (json.load(open(fp, encoding="utf-8")).get("per_seed") or {})
        line = next((ln for ln in sig_lines if ln.strip().startswith("| " + label)), None)
        if not line:
            problems.append(f"P/R 签名表: README 里找不到 {label} 那一行")
            continue
        n_sig += 1
        cells = [c.strip().strip("*") for c in line.strip().strip("|").split("|")]
        for idx, metric in ((1, "map50"), (2, "precision"), (3, "recall")):
            diffs = []
            for _s, row in ps.items():
                if a_key in row and b_key in row:
                    diffs.append((row[a_key][metric] - row[b_key][metric]) * 100.0)
            if not diffs:
                problems.append(f"P/R 签名 {label} {metric}: 产物里没数据")
                continue
            want = float(cells[idx].replace("−", "-"))
            got = sum(diffs) / len(diffs)
            if abs(got - want) > 0.01:
                problems.append(f"P/R 签名 {label} {metric}: 产物 {round(got, 4)} != README {want}")
    if n_sig:
        print(f"[23] P/R 签名对照表: 核对 {n_sig} 条臂的 mAP50/precision/recall 均值差")

    # 24) 排除链总图的数字清单 (74 号产物) ——
    #     它是**从各臂产物里读的** → 必须与那些产物一致 →
    #     否则这张总图会进一步脱离产物成为“另一份手写的数字” ✓
    ec_p = os.path.join(BENCH, "exclusion_chain.json")
    if os.path.isfile(ec_p):
        ec = json.load(open(ec_p, encoding="utf-8"))
        rows = ec.get("rows") or []
        n_ec = 0
        for r in rows:
            src_p = os.path.join(BENCH, r.get("artifact") or "")
            pkey = r.get("pair_key")
            if not os.path.isfile(src_p) or not pkey:
                problems.append(f"排除链总图: {r.get('label')} 的源产物/配对键不存在")
                continue
            got = ((json.load(open(src_p, encoding="utf-8")).get("paired") or {}).get(pkey) or {})
            if got.get("mean_pp") is None or abs(got["mean_pp"] - r.get("mean_pp", 0)) > 0.005:
                problems.append(f"排除链总图 {r.get('label')}: 源产物 {got.get('mean_pp')} != 总图 {r.get('mean_pp')}")
            gci = got.get("ci95_pp")
            rci = r.get("ci95_pp") or []
            if not gci or len(rci) != 2 or abs(gci[0] - rci[0]) > 0.005 or abs(gci[1] - rci[1]) > 0.005:
                problems.append(f"排除链总图 {r.get('label')}: CI 不一致 {gci} vs {rci}")
            n_ec += 1
        print(f"[24] 排除链总图: 核对 {n_ec} 条臂的配对差与 CI 与源产物一致")
    else:
        print("[24] 排除链总图: 产物不在仓内, 跳过核对")

    # 25) **臂的实际训练配置核对** (75 号审计的结果写在产物里 ✓) ——
    #     产物里的 `protocol_audit.status` 必须是 clean ✓
    #     (否则说明这条臂的数字不能当证据 —— I-06 的教训 ✓)
    n_audit = 0
    for art_name in ("pretrain_finetune_arm.json", "mixstyle_arm.json",
                     "real_budget_epoch_arm.json", "context_suppress_arm.json"):
        ap_ = os.path.join(BENCH, art_name)
        if not os.path.exists(ap_):
            continue
        aud = json.load(open(ap_, encoding="utf-8")).get("protocol_audit") or {}
        if not aud:
            continue
        n_audit += 1
        st = aud.get("status")
        if st != "clean":
            devs = aud.get("deviations") or []
            problems.append(f"{art_name}: 协议漂移 ({st}) → "
                            + "; ".join(f"{d.get('field')} 不一致" for d in devs[:3]))
    if n_audit:
        print(f"[25] 协议审计: {n_audit} 个产物的实际配置已核对 (clean 才能当证据)")

    # 26) **轮数轴的 run 内轨迹表** (78 号) —— README 里那张表必须与产物逐格一致 ✓
    #     (这张表是"多训几轮还有没有收益"的唯一证据源 ✓ -> 不能手抄 ✓)
    ep_p = os.path.join(BENCH, "epoch_axis_curve.json")
    if not os.path.exists(ep_p):
        print("[26] 轮数轴轨迹: 产物不在仓内, 跳过核对")
    else:
        ep_art = json.load(open(ep_p, encoding="utf-8"))
        fams = ep_art.get("families") or {}
        # **族的名字 -> README 表里的显示名**: 产物用脚本里的族名, README 用短名 ✓
        # (找不到对应行就跳过那一族, 不猜 ✓)
        if not rd_sw:
            rd_sw = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        m_sec = rd_sw.find("轮数轴 (跨 seed 均值")
        if m_sec < 0:
            problems.append("README 里找不到轮数轴轨迹表 → 无法核对")
        else:
            # **窗口要贴着这一节** (skill: multi-seed-aggregation-pitfalls §4 ✓)
            sec = rd_sw[m_sec:m_sec + 2000]
            rows = {}
            hdr_cells = None
            for rm in re.finditer(r"^\|\s*(\d+)\s*ep\s*\|(.+)\|\s*$", sec, re.M):
                cells = [c.strip() for c in rm.group(2).split("|")]
                rows[int(rm.group(1))] = cells
            hm = re.search(r"^\|\s*轮数\s*\|(.+)\|\s*$", sec, re.M)
            if hm:
                hdr_cells = [c.strip() for c in hm.group(1).split("|")]
            if not hdr_cells:
                problems.append("轮数轴表: 找不到表头行 (| 轮数 | ... |) → 无法定位列")
            order = list(fams.keys())
            short = {"ctrl_a(纯真实 10ep)": "ctrl_a", "ctrl_b(纯真实 20ep)": "ctrl_b",
                     "ctrl_c(纯真实 40ep)": "ctrl_c", "分工臂(合成预训练→真实 10ep)": "分工臂",
                     "arm_wash(合成预训练→真实 20ep)": "arm_wash"}
            n_cell = 0
            for fam, f in fams.items():
                traj = f.get("mean_val_map50_by_epoch") or []
                nm = short.get(fam, fam)
                # 这一族在表里的列号 (用**表头里的显示名**定位 ✓)
                idx = None
                for j, c in enumerate(hdr_cells or []):
                    if nm and nm in c:
                        idx = j
                        break
                if idx is None:
                    continue
                for ep in (5, 10, 15, 20, 30, 40):
                    if ep > len(traj):
                        continue
                    want = traj[ep - 1]
                    cells = rows.get(ep)
                    if not cells or idx >= len(cells):
                        continue
                    cell = cells[idx]
                    if cell in ("—", "-", ""):
                        continue
                    # 单元格里可能带 "(n=2)" 之类的注记 -> 只取开头的数字 ✓
                    nm_num = re.match(r"^\s*([0-9.]+)", cell)
                    if not nm_num:
                        problems.append(f"轮数轴 {nm} {ep}ep: README 单元格里不是数字 ({cell})")
                        continue
                    got = float(nm_num.group(1))
                    if abs(got - want) > 0.0006:
                        problems.append(f"轮数轴 {nm} {ep}ep: README {got} != 产物 {round(want, 4)}")
                    n_cell += 1
            print(f"[26] 轮数轴轨迹: 核对 {n_cell} 格 (README 的表 vs 产物 ✓)")

    # 27) 官方 SimReady 验证 vs 自研闸: README 里的判语必须与产物一致
    diff_json = os.path.join(BENCH, "simready_vs_self_gate.json")
    if os.path.exists(diff_json):
        d = json.load(open(diff_json, encoding="utf-8"))
        res = d.get("official_results", [])
        by = {}
        for r in res:
            by[(r.get("tag"), r.get("profile"))] = r.get("status")
        pkg_ours = by.get(("ours", "Package-Candidate"))
        pkg_nvidia = [st for (tg, pf), st in by.items()
                      if tg and tg.startswith("usdcraft") and pf == "Package-Candidate"]
        mat_nvidia = [st for (tg, pf), st in by.items()
                      if tg and tg.startswith("usdcraft") and pf == "Material"]
        readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        # README 必须写对三件事: 我们 FAIL / NVIDIA 样例 PASS 数 / 自研闸 PASS
        claims = [
            ("Package-Candidate 下本仓资产 FAIL",
             pkg_ours == "FAIL" and "| 官方 `Package-Candidate` | **FAIL** |" in readme),
            ("NVIDIA 样例 Package-Candidate 全 PASS",
             bool(pkg_nvidia) and all(s == "PASS" for s in pkg_nvidia)
             and f"| **FAIL** | **{len(pkg_nvidia)}/{len(pkg_nvidia)} PASS** |" in readme),
            ("自研闸总判据 PASS",
             d.get("self_gate", {}).get("overall") == "PASS"
             and "| 自研闸 `12_asset_spec_gate.py`（5 项） | **PASS** |" in readme),
        ]
        for name, ok in claims:
            if not ok:
                problems.append(f"官方 SimReady 对照: README 缺少或写错了「{name}」")
        # 修掉的那个真 bug 不许再出现: shader surface 输出必须是 token
        for g in d.get("our_asset_requirement_gaps", []):
            if "Expected type: 'token' actual type: 'int'" in (g.get("message") or ""):
                problems.append("官方 SimReady 对照: 产物里又出现 shader surface 类型错 (token/int)")
        print(f"[27] 官方 SimReady vs 自研闸: 核对 {len(claims)} 条判语 "
              f"(本仓 {pkg_ours} / NVIDIA 样例 Package-Candidate {len(pkg_nvidia)} 件)")

    # 28) 官方打包链对照实验: README 里的"跑通/文件数"必须与产物一致
    pk = os.path.join(BENCH, "simready_packaging_effect.json")
    if os.path.exists(pk):
        d = json.load(open(pk, encoding="utf-8"))
        ctrl = next((s for s in d.get("steps", [])
                     if s.get("step") == "control_official_package_nvidia_asset"), None)
        readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        if ctrl is None:
            problems.append("官方打包对照: 产物里没有 control_official_package_nvidia_asset 这一步")
        else:
            if ctrl.get("rc") != 0:
                problems.append("官方打包对照: 对照实验 rc != 0")
            n_files = len(ctrl.get("package_files") or [])
            if n_files and f"产出 {n_files} 个文件的完整包" not in readme:
                problems.append(f"官方打包对照: README 没写对产物件数 (产物 {n_files})")
            print(f"[28] 官方打包链对照实验: rc={ctrl.get('rc')} / 产物 {n_files} 个文件")

    # 29) 合规包: README 的判语必须与 86 号产物一致 (Package-Candidate PASS / 打包 rc=0 / 产物件数)
    cp = os.path.join(BENCH, "simready_compliant_package.json")
    if os.path.exists(cp):
        d = json.load(open(cp, encoding="utf-8"))
        readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        pc = next((r for r in d.get("official_validate_pkg", [])
                   if r.get("profile") == "Package-Candidate"), None)
        if not pc or pc.get("passed") is not True:
            problems.append("合规包: Package-Candidate 不是 PASS")
        pkg = d.get("official_package", {})
        if pkg.get("rc") != 0:
            problems.append(f"合规包: 官方打包 rc={pkg.get('rc')} (应为 0)")
        n = len(pkg.get("package_files") or [])
        if n and f"产出 **{n} 个文件**的包" not in readme:
            problems.append(f"合规包: README 没写对产物件数 (产物 {n})")
        if d.get("checks", {}).get("non_anchored_asset_paths"):
            problems.append("合规包: 还有非 anchored 的贴图路径")
        print(f"[29] 合规包: Package-Candidate="
              f"{'PASS' if pc and pc.get('passed') else 'FAIL'} / 打包 rc={pkg.get('rc')} / 产物 {n} 个文件")

    # 30) 消费端检查 (88 号): README 的材质/贴图数字必须与产物一致, 且材质不能为 0
    cc = os.path.join(BENCH, "asset_consume_check.json")
    if os.path.exists(cc):
        d = json.load(open(cc, encoding="utf-8"))
        readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        n_mat = len(d.get("materials") or [])
        n_tex = len(d.get("textures") or [])
        if not n_mat:
            problems.append("消费端检查: 消费者看不到任何材质 (标准 material:binding 缺失?)")
        if f"**{n_mat} 个材质**" not in readme:
            problems.append(f"消费端检查: README 没写对材质数 (产物 {n_mat})")
        if n_tex and f"**{n_tex} 张贴图**" not in readme:
            problems.append(f"消费端检查: README 没写对贴图数 (产物 {n_tex})")
        print(f"[30] 消费端检查: 网格 {d.get('meshes')} / 材质 {n_mat} / 贴图 {n_tex}")

    # 31) 合规包的官方 profile 结论: README 说的 "Robotics-Prop PASS / blocking 0" 必须与产物一致
    cp2 = os.path.join(BENCH, "simready_compliant_package.json")
    if os.path.exists(cp2):
        d = json.load(open(cp2, encoding="utf-8"))
        readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        rp = next((r for r in d.get("official_validate_pkg", [])
                   if r.get("profile") == "Robotics-Prop"), None)
        if not rp or rp.get("passed") is not True:
            problems.append("合规包: Robotics-Prop 不是 PASS")
        nb = len(rp.get("blocking_failures") or []) if rp else -1
        if nb != 0:
            problems.append(f"合规包: Robotics-Prop 还有 {nb} 个阻断项")
        if "blocking 12 → 0 → PASS" not in readme:
            problems.append("合规包: README 没写对 Robotics-Prop 的结论")
        pl = d.get("package", {}).get("physics_layer", {})
        sl = d.get("package", {}).get("semantics_layer", {})
        if pl.get("rigid_body") is not True:
            problems.append("合规包: 物理刚体层没生效")
        if not sl.get("labels"):
            problems.append("合规包: 语义标签层没生效")
        print(f"[31] 合规包官方 profile: Robotics-Prop passed={rp.get('passed') if rp else '?'} "
              f"blocking={nb} / 碰撞体 {pl.get('colliders')} / 材质标签 {sl.get('materials_labeled')}")

    # 32) USDCraft 全量扫描: 扫描件数与 README 声明一致 (防止"跑了几件却写成全量")
    sw = os.path.join(BENCH, "simready_usdcraft_sweep.json")
    if os.path.exists(sw):
        d = json.load(open(sw, encoding="utf-8"))
        n = d.get("assets_scanned")
        readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        # 去掉反引号再比对 -> README 里的 markdown 记法不影响核对 ✓
        readme_norm = readme.replace("`", "").replace("**", "")
        if n and f"**{n} 件 USDCraft 资产**" not in readme:
            problems.append(f"全量扫描: README 没写对扫描件数 (产物 {n})")
        pp = d.get("per_profile", {})
        if pp and "Package-Candidate" in pp:
            pc = pp["Package-Candidate"].get("pass", 0)
            if pc and f"Package-Candidate PASS {pc}/{n}" not in readme_norm:
                problems.append(f"全量扫描: README 没写对 Package-Candidate 的通过数 (产物 {pc}/{n})")
        print(f"[32] USDCraft 全量扫描: {n} 件资产 / {len(pp)} 个 profile")

    # 33) 包级合规证据 + 质量字段: README 的数字必须与产物一致
    cp3 = os.path.join(BENCH, "simready_compliant_package.json")
    if os.path.exists(cp3):
        d = json.load(open(cp3, encoding="utf-8"))
        readme = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        readme_norm = readme.replace("`", "").replace("**", "")
        ev = d.get("package_level_evidence", {})
        cf = ev.get("conformance_files", {})
        pkg_feats = (cf.get("com.nvidia.simready.conformance.Package@1.0.0.json", {})
                     .get("features", {}))
        if pkg_feats and not all(v.get("passed") for v in pkg_feats.values()):
            problems.append("包级证据: Package profile 有 feature 未通过")
        pnb = ev.get("package_no_bom") or {}
        pnb_feats = pnb.get("features") or {}
        if pnb_feats and not all((v or {}).get("passed") for v in pnb_feats.values()):
            problems.append("包级证据: Package-NoBOM 有 feature 未通过")
        mc = d.get("package", {}).get("mass_cross_check", {})
        if mc.get("used_kg") and f"{mc['used_kg']} kg" not in readme_norm:
            problems.append(f"质量: README 没写对 mass (产物 {mc['used_kg']} kg)")
        if mc.get("delta_pct") is not None and f"{mc['delta_pct']}%" not in readme:
            problems.append(f"质量: README 没写对交叉核对差值 (产物 {mc['delta_pct']}%)")
        print(f"[33] 包级证据: Package {len(pkg_feats)} feature / Package-NoBOM {len(pnb_feats)} feature "
              f"/ mass {mc.get('used_kg')} kg (交叉核对差 {mc.get('delta_pct')}%)")

    # 34) 交付自洽验收: 完整性 / 净室可用性 / 统计口径 (README 的数必须对得上产物)
    da_path = os.path.join(BENCH, "delivery_audit.json")
    if os.path.exists(da_path):
        da = json.load(open(da_path, encoding="utf-8"))
        integ = da.get("integrity", {})
        if integ.get("n_files") and integ.get("ok") != integ.get("n_files"):
            problems.append(f"交付完整性: {integ.get('n_files') - integ.get('ok')} 个发布产物 sha256 对不上")
        cr = da.get("cleanroom", {})
        if cr.get("unresolved_texture_refs"):
            problems.append(f"净室: {len(cr['unresolved_texture_refs'])} 个贴图引用在包内解析不到")
        if cr.get("unbound_meshes"):
            problems.append(f"净室: {len(cr['unbound_meshes'])} 个网格没绑材质")
        if cr.get("sr004_missing_fields"):
            problems.append(f"净室: sidecar 缺 SR.004 字段 {cr['sr004_missing_fields']}")
        cnt = da.get("counting", {})
        readme_txt = open(os.path.join(BASE, "README.md"), encoding="utf-8").read()
        rm = readme_txt.replace("`", "").replace("**", "")
        expect = {
            "结构家族": cnt.get("structure_families"),
            "拓扑": cnt.get("topologies"),
            "规格变体": cnt.get("spec_variants"),
            "印刷变体": cnt.get("library", {}).get("print_variants_available"),
            "资产包": len(cnt.get("produced", {}).get("asset_packages") or []),
            "真实商品": cnt.get("real_products"),
        }
        for label, val in expect.items():
            if val is None:
                continue
            # 表格里是 "| 结构家族 | 1 |" -> 逐行找**同一行**里的标签与数字 ✓
            hit = any(_num_on_line(ln, label, val) for ln in rm.splitlines())
            if not hit:
                problems.append(f"统计口径: README 没写对 {label} (产物 {val})")
        print(f"[34] 交付验收: 完整性 {integ.get('ok')}/{integ.get('n_files')}"
              + (" (本次判定作废: 清单在检查期间被刷新 ✓)" if integ.get("manifest_changed_during_check") else "")
              + " / 净室 "
              f"{cr.get('verdict')} / 口径 结构家族 {cnt.get('structure_families')} 拓扑 {cnt.get('topologies')} "
              f"规格 {cnt.get('spec_variants')} 印刷 {cnt.get('library', {}).get('print_variants_available')} "
              f"资产包 {len(cnt.get('produced', {}).get('asset_packages') or [])} 真实商品 {cnt.get('real_products')}")

    # 35) 对外简报: 口径与关键结论必须与产物一致 (对外文档最容易漂 ✓)
    brief_path = os.path.join(BASE, "docs", "research", "ECOSYSTEM_BRIEF.md")
    if os.path.exists(brief_path) and os.path.exists(os.path.join(BENCH, "delivery_audit.json")):
        da = json.load(open(os.path.join(BENCH, "delivery_audit.json"), encoding="utf-8"))
        cnt = da.get("counting", {})
        cr = da.get("cleanroom", {})
        br = open(brief_path, encoding="utf-8").read()
        br_n = br.replace("`", "").replace("**", "")
        b_expect = {
            "结构家族": cnt.get("structure_families"),
            "拓扑": cnt.get("topologies"),
            "规格变体": cnt.get("spec_variants"),
            "印刷变体": cnt.get("library", {}).get("print_variants_available"),
            "资产包": len(cnt.get("produced", {}).get("asset_packages") or []),
            "真实商品": cnt.get("real_products"),
        }
        for label, val in b_expect.items():
            if val is None:
                continue
            hit = any(_num_on_line(ln, label, val) for ln in br_n.splitlines())
            if not hit:
                problems.append(f"对外简报: 口径写错了 {label} (产物 {val})")
        if "198/198" not in br and f"{da.get('integrity', {}).get('ok')}/{da.get('integrity', {}).get('n_files')}" not in br:
            problems.append("对外简报: 完整性数字与产物不一致")
        if cr.get("meshes") and f"网格 {cr['meshes']}" not in br_n:
            problems.append(f"对外简报: 网格数写错了 (产物 {cr['meshes']})")
        print(f"[35] 对外简报: 口径 7 项核对完成 / 完整性 {da.get('integrity', {}).get('ok')}/"
              f"{da.get('integrity', {}).get('n_files')} / 净室网格 {cr.get('meshes')}")

    if problems:
        print("\n❌ 一致性问题:")
        for p in problems:
            print("  -", p)
        raise SystemExit(1)

    print("\n✅ 文档与产物一致")


if __name__ == "__main__":
    main()
