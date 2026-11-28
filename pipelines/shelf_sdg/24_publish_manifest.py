#!/usr/bin/env python3
"""产物清单 (2026-11-21, 审计行动 9: 给产物写 manifest, 哈希 + 生成参数)。

把随仓发布的基准产物 (docs/research/benchmark/) 逐个记 sha256 + 字节数 + 来源脚本 +
protocol_hash, 写 docs/research/benchmark/MANIFEST.json。第三方拿到仓后可直接核对
"报告里的数字对应哪一个文件、哪个哈希"。

只读文件 + 写一个 json, 不需要 GPU。
"""
import hashlib
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PUB = os.path.join(BASE, "docs", "research", "benchmark")
BENCH = os.path.join(BASE, "output", "benchmark")
OUT = os.path.join(PUB, "MANIFEST.json")

# 产物 → 生成脚本 (证据链: 这个文件是谁写的)
PRODUCER = {
    "sku110k_r0.json": "pipelines/shelf_sdg/14_sku110k_baseline.py --arm r0",
    "sku110k_r1.json": "pipelines/shelf_sdg/14_sku110k_baseline.py --arm r1",
    "sku110k_r2.json": "pipelines/shelf_sdg/14_sku110k_baseline.py --arm r2",
    "sku110k_R3-full.json": "pipelines/shelf_sdg/14_sku110k_baseline.py --arm r3",
    "count_pilot.json": "pipelines/shelf_sdg/17_count_eval.py --weights <pilot last.pt>",
    "count_real1.json": "pipelines/shelf_sdg/17_count_eval.py --weights <real1 last.pt>",
    "domain_gap_measure.json": "pipelines/shelf_sdg/23_domain_gap_measure.py",
    "BUDGET_CURVE.md": "21_annotation_budget.py (--merge-only) → merge_curve.py",
    "budget_seed_variance.md": "pipelines/shelf_sdg/22_budget_seed_variance.py",
    "budget_seed_variance.json": "pipelines/shelf_sdg/22_budget_seed_variance.py",
    # 2026-11-22 新增
    "power_analysis.md": "pipelines/shelf_sdg/29_power_analysis.py",
    "power_analysis.json": "pipelines/shelf_sdg/29_power_analysis.py",
    "dose_response.md": "pipelines/shelf_sdg/31_dose_response.py",
    "dose_response.json": "pipelines/shelf_sdg/31_dose_response.py",
    "dose_response.png": "pipelines/shelf_sdg/31_dose_response.py",
    "budget_curve_figure.png": "pipelines/shelf_sdg/27_budget_curve_figure.py",
    "count_threshold_sweep.md": "pipelines/shelf_sdg/33_count_threshold_sweep.py",
    "count_threshold_sweep.png": "pipelines/shelf_sdg/33_count_threshold_sweep.py",
    "count_real0.05.json": "pipelines/shelf_sdg/17_count_eval.py --arm real0.05 --conf-sweep ...",
    # 2026-11-22 晚: 已发布四臂的多种子汇总
    "fourarm_seed_variance.md": "pipelines/shelf_sdg/36_fourarm_seed_variance.py",
    "fourarm_seed_variance.json": "pipelines/shelf_sdg/36_fourarm_seed_variance.py",
    # 2026-11-24: 密度因子的首次直接实测 (真实数据侧稀释框密度)
    "density_curve.md": "pipelines/shelf_sdg/45b_density_report.py",
    "density_curve.json": "pipelines/shelf_sdg/45b_density_report.py",
    "density_curve.png": "pipelines/shelf_sdg/45b_density_report.py",
    "gpu_cpu_equivalence.json": "pipelines/shelf_sdg/46_rebuild_after_restore.py",
    # 2026-11-25: sim2real 机制定位与干预探针
    "domain_fit_probe.json": ("pipelines/shelf_sdg/51_domain_fit_probe.py "
                              "(探针; 若中途被杀则由 51b_domain_fit_log_parse.py 从日志还原)"),
    "syn2real_interventions.json": "pipelines/shelf_sdg/52_photorealism_probe.py",
    "syn2real_interventions.md": "pipelines/shelf_sdg/52_photorealism_probe.py",
    "spectral_gap.json": "pipelines/shelf_sdg/54_spectral_gap.py",
    "input_probe.json": "pipelines/shelf_sdg/55_input_probe.py",
}
PRODUCER_PREFIX = {
    "budget_real": "pipelines/shelf_sdg/21_annotation_budget.py (--run-tag <seed 复跑>)",
    "sku110k_r1_scene": "pipelines/shelf_sdg/14_sku110k_baseline.py --arm r1 --arm-tag <tag>",
    # 2026-11-22: 多种子复跑带来的新文件 (count_real1_s43.json / count_real0.05_s44.json …)
    "count_real": "pipelines/shelf_sdg/17_count_eval.py --arm <格点> [--weights <last.pt>]",
    "paired_image_eval": "pipelines/shelf_sdg/25_paired_image_eval.py --weights-a/--weights-b",
}
# 2026-11-22 晚: 四臂的多种子复跑产物 (sku110k_r0_s43.json …) —— 用正则而不是前缀,
# 否则 sku110k_r1_scenebest.json (敏感性复跑) 会被错标成"多种子复跑"。
SEED_RUN_RE = re.compile(r"^sku110k_(r\d+)_s(\d+)\.json$")


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def producer_for(name):
    if name in PRODUCER:
        return PRODUCER[name]
    m = SEED_RUN_RE.match(name)
    if m:
        return (f"pipelines/shelf_sdg/14_sku110k_baseline.py --arm {m.group(1)} "
                f"--arm-tag s{m.group(2)} --seed {m.group(2)}")
    for pre, p in PRODUCER_PREFIX.items():
        if name.startswith(pre):
            return p
    return "未知 (手工产物)"


def sha256_lf(path, scrub=False):
    """行尾归一 (CRLF→LF) 后的 sha256 —— 用于比对发布版与 output/benchmark/ 的同一产物。

    `scrub=True` 时同时做路径去本机化: 发布版已被 26 号脚本 scrub 过, 所以比对
    时必须对 output 副本用同一套规则, 否则 `matches_output_copy_lf` 会因为
    路径写法不同而恒为 false (看起来像"产物对不上", 其实是替换造成的)。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        data = f.read()
    data = data.replace(b"\r\n", b"\n")
    if scrub:
        sys.path.insert(0, os.path.join(BASE, "pipelines", "common"))
        from publish_paths import scrub_bytes
        data = scrub_bytes(data)
    h.update(data)
    return h.hexdigest()


def main():
    entries = []
    for name in sorted(os.listdir(PUB)):
        p = os.path.join(PUB, name)
        if not os.path.isfile(p) or name == "MANIFEST.json":
            continue
        rec = {"file": name, "bytes": os.path.getsize(p), "sha256": sha256(p),
               "sha256_lf": sha256_lf(p), "produced_by": producer_for(name)}
        counterpart = os.path.join(BENCH, name)
        if os.path.isfile(counterpart):
            rec["matches_output_copy_lf"] = (sha256_lf(counterpart, scrub=True) == rec["sha256_lf"])
        if name.endswith(".json"):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if isinstance(d, dict):
                    for k in ("protocol_hash", "arm", "map50", "map50_95"):
                        if k in d:
                            rec[k] = d[k]
                    ck = d.get("checkpoint") or {}
                    if ck.get("sha256"):
                        rec["checkpoint_sha256"] = ck["sha256"]
                    dset = d.get("dataset") or {}
                    if dset.get("cell"):
                        rec["cell"] = dset["cell"]
                    if dset.get("n_real") is not None:
                        rec["n_real"] = dset["n_real"]
                    if dset.get("n_synth") is not None:
                        rec["n_synth"] = dset["n_synth"]
                    if d.get("weights"):
                        rec["weights"] = d["weights"]
            except Exception:
                rec["parse"] = "非 JSON 或无法解析"
        entries.append(rec)
    out = {
        "schema": "benchmark_manifest/1",
        "generated_by": "pipelines/shelf_sdg/24_publish_manifest.py",
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "note": "本清单覆盖随仓发布的基准产物。`sha256` 是**发布版** (仓内统一 LF 行尾) 的哈希; "
                "`sha256_lf` 与 `matches_output_copy_lf` 用于比对仓内 output/benchmark/ 的同一产物"
                "(发布时拷贝, 行尾归一后内容一致)。protocol_hash 见各 json "
                "(覆盖协议+数据+划分+实跑配置+依赖+权重)。",
        "dataset_fingerprints": "docs/research/DATASET_SKU110K.md + docs/research/sku110k_fingerprints.json",
        "files": entries,
    }
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[MANIFEST] {len(entries)} 个产物 → {OUT}")
    for e in entries:
        print(f"  {e['sha256'][:16]}  {e['bytes']:>8}  {e['file']}")


if __name__ == "__main__":
    main()
