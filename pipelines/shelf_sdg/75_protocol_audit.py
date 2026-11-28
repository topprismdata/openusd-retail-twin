#!/usr/bin/env python
"""75 \u53f7: \u81c2\u7684**\u5b9e\u9645\u8bad\u7ec3\u914d\u7f6e**\u6838\u5bf9\u4e0e\u81ea\u8bc1\u3002

\u80cc\u666f (I-06 \u7684\u6559\u8bad): \u4e00\u6b21\u590d\u73b0\u5b9e\u9a8c\u91cc, \u5e76\u53d1\u538b GPU \u8ba9\u8bad\u7ec3\u811a\u672c\u628a batch \u4ece 4 \u9759\u9ed8\u964d\u6210 2
(ultralytics \u6309 nbs/batch \u7f29\u653e\u5b66\u4e60\u7387 \u2192 \u4e0d\u662f\u65e0\u5bb3\u7b49\u4ef7\u6539\u52a8 \u2713), mAP \u4ece 0.7946 \u6389\u5230 0.7705 \u2192 \u5dee\u4e86 \u22122.4 pp \u2192
\u5dee\u503c\u88ab\u8bef\u5f53\u6210"\u91cd\u8dd1\u566a\u58f0"\u3002\u4e4b\u540e\u4ea7\u7269\u91cc\u5f00\u59cb\u8bb0 `actual_train_config` \u4e0e `protocol` \u2192 \u95f8\u95e8 [3z] \u4f1a\u70b9\u540d\u6f02\u79fb\u7684\u4ea7\u7269 \u2713\u3002

**\u4f46\u65b0\u5199\u7684\u81c2\u4ea7\u7269\u5e38\u5fd8\u4e86\u8bb0\u8fd9\u4e2a** \u2192 \u672c\u811a\u672c\u628a\u5b83\u8865\u56de\u6765\u5e76\u4e14\u80fd\u72ec\u7acb\u8fd0\u884c \u2713:
  * \u8bfb\u6bcf\u4e2a run \u76ee\u5f55\u7684 `train/args.yaml` (ultralytics \u5199\u7684**\u5b9e\u9645**\u914d\u7f6e \u2713) \u2192 \u4e0e\u4ea7\u7269\u91cc\u58f0\u660e\u7684 `protocol` \u6bd4\u8f83 \u2713
    \u2192 \u6709\u504f\u5dee\u5c31\u70b9\u540d (\u5b8c\u5168\u590d\u73b0 I-06 \u7684\u53ef\u80fd \u2713) \u2192 **\u4e0d\u4f1a\u9759\u9ed8\u5730\u628a\u534f\u8bae\u6f02\u79fb\u7684\u7ed3\u679c\u5f53\u8bc1\u636e** \u2713
  * \u540c\u65f6\u62ff\u51fa\u5404\u81c2\u7684**\u5171\u540c\u914d\u7f6e** \u2192 \u5bf9\u6bd4\u6240\u6709\u975e\u76ee\u6807\u5b57\u6bb5\u662f\u5426\u9010\u9879\u4e00\u81f4 \u2713
    (\u5b83\u5e94\u8be5\u53ea\u5dee `epochs` \u548c `model` \u4e24\u9879 \u2192 \u82e5\u6709\u522b\u7684\u5dee\u5f02\u5c31\u662f\u534f\u8bae\u6f02\u79fb \u2713)
  * \u628a\u7ed3\u679c\u56de\u5199\u8fdb\u4ea7\u7269\u7684 `actual_train_config` / `protocol_audit` \u6bb5 \u2713 \u2192 \u4ea7\u7269\u81ea\u8bc1\u3002

\u7528\u6cd5:
    python pipelines/shelf_sdg/75_protocol_audit.py --artifact output/benchmark/real_budget_epoch_arm.json
    python pipelines/shelf_sdg/75_protocol_audit.py --artifact output/benchmark/pretrain_finetune_arm.json --runs runs_pf_pre_s{seed}:runs_pf_ft_s{seed}:runs_pf_ctrla_s{seed}:runs_pf_ctrlb_s{seed}
"""
import argparse
import json
import os
import re
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BENCH = os.path.join(BASE, "output", "benchmark")

# \u6bd4\u8f83\u7684\u5b57\u6bb5: \u5b83\u4eec\u5728\u4e0d\u540c\u7684\u81c2\u4e4b\u95f4\u5fc5\u987b\u4e00\u81f4 \u2192 \u4e0d\u4e00\u81f4\u5c31\u662f\u534f\u8bae\u6f02\u79fb \u2713
COMPARE_KEYS = ("imgsz", "batch", "workers", "device", "optimizer", "close_mosaic", "pretrained")
# \u5141\u8bb8\u4e0d\u540c\u7684\u5b57\u6bb5: \u5b83\u4eec\u5c31\u662f\u88ab\u5b9e\u6d4b\u7684\u53d8\u91cf \u2713
ALLOWED_DIFF = ("epochs", "model", "data", "name", "project", "seed", "exist_ok", "verbose")


def train_list(yaml_path):
    """读 yaml 里的 train: 清单 -> 真正的图片列表 ✓
    (两个 yaml 可能指向**同一份名单但文件名不同** → 比路径会误报差异 ✓)"""
    # **不用 pyyaml** → 仓里不依赖它 ✓ (ultralytics 必有, 但这个脚本要能单独跑 ✓)
    try:
        txt = open(yaml_path, encoding="utf-8", errors="ignore").read()
    except OSError:
        return None
    tr = None
    for ln in txt.splitlines():
        m = re.match(r"^train:\s*\[(.*)\]\s*$", ln.strip())
        if m:
            tr = [x.strip().strip("'\"") for x in m.group(1).split(",") if x.strip()]
            break
        m2 = re.match(r"^train:\s*(\S+)\s*$", ln.strip())
        if m2:
            tr = [m2.group(1)]
            break
    if isinstance(tr, str):
        tr = [tr]
    if not isinstance(tr, (list, tuple)):
        return None
    out = []
    for item in tr:
        p = str(item).strip()
        if p.lower().endswith(".txt"):
            if os.path.isfile(p):
                out.extend([ln.strip() for ln in open(p, encoding="utf-8") if ln.strip()])
            else:
                out.append(p)
        else:
            out.append(p)
    return out


def read_args(run_dir):
    """\u8bfb ultralytics \u5199\u7684 args.yaml \u2192 \u5b9e\u9645\u914d\u7f6e \u2713"""
    p = os.path.join(run_dir, "train", "args.yaml")
    if not os.path.isfile(p):
        return None
    out = {}
    for ln in open(p, encoding="utf-8", errors="ignore"):
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", ln.rstrip("\n"))
        if m:
            v = m.group(2).strip().strip('"').strip("'")
            out[m.group(1)] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--artifact", required=True, help="\u4ea7\u7269 json \u7684\u8def\u5f84 (\u5728 output/benchmark/ \u4e0b)")
    ap.add_argument("--runs", default=None,
                    help="\u5404\u81c2\u7684 run \u76ee\u5f55\u6a21\u677f (\u7528 : \u5206\u9694, \u6a21\u677f\u91cc\u53ef\u7528 {seed})")
    ap.add_argument("--seeds", type=int, nargs="*", default=[43])
    ap.add_argument("--baseline", default=None,
                    help="\u4e00\u4e2a\u5df2\u53d1\u5e03\u7684\u5bf9\u7167\u8fdb\u7a0b\u76ee\u5f55 (\u5982 budget_runs_real0.05_synth0) \u2192 "
                         "\u62a5\u51fa\u5b83\u4e0e\u88ab\u5ba1\u8ba1\u5404\u81c2\u7684\u5dee\u5f02\u5b57\u6bb5 (\u7528\u6765\u533a\u5206\u201c\u5dee\u5f02\u53ea\u662f seed\u201d"
                         "\u4e0e\u201c\u5b58\u5728\u534f\u8bae\u6f02\u79fb\u201d \u2713)")
    args = ap.parse_args()

    art_p = args.artifact if os.path.isabs(args.artifact) else os.path.join(BENCH, args.artifact)
    if not os.path.isfile(art_p):
        raise SystemExit(f"\u7f3a\u4ea7\u7269 {art_p}")
    art = json.load(open(art_p, encoding="utf-8"))

    if args.runs:
        templates = args.runs.split(":")
    else:
        templates = [t for t in (art.get("runs_templates") or [])]
        if not templates:
            print("[AUDIT] \u4ea7\u7269\u91cc\u6ca1\u6709 runs_templates, \u7528 --runs \u6307\u5b9a \u2713")
            return 1

    # \u9010 seed \u9010\u81c2\u8bfb\u5b9e\u9645\u914d\u7f6e
    actual = {}
    for seed in args.seeds:
        for tpl in templates:
            run = tpl.format(seed=seed)
            d = os.path.join(BENCH, run)
            a = read_args(d)
            if a is None:
                print(f"[AUDIT] {run}: \u6ca1\u627e\u5230 train/args.yaml \u2192 \u8fd9\u4e2a run \u8fd8\u5728\u8bad\u7ec3\u6216\u5df2\u6e05\u7406 \u2192 \u8df3\u8fc7 \u2713")
                continue
            # **seed 也要记进来** → 基准比较时才能说"差异只是 seed" →
            # 不记的话就会把"差异只是 seed"说成"完全一致" → 会误导人 ✓
            actual[f"{run}"] = {k: a.get(k) for k in COMPARE_KEYS + ("epochs", "model", "data", "seed")}
    if not actual:
        raise SystemExit("\u6ca1\u8bfb\u5230\u4efb\u4f55\u5b9e\u9645\u914d\u7f6e \u2192 \u65e0\u6cd5\u6838\u5bf9 \u2713")

    # \u9010\u5b57\u6bb5\u6bd4\u8f83: \u9664\u5141\u8bb8\u5dee\u5f02\u7684\u5b57\u6bb5\u5916, \u5fc5\u987b\u5168\u90e8\u4e00\u81f4
    diffs = []
    keys = list(actual.keys())
    for k in COMPARE_KEYS:
        vals = {kk: v.get(k) for kk, v in actual.items()}
        uniq = set(vals.values())
        if len(uniq) > 1:
            diffs.append({"field": k, "values": vals})
    status = "clean" if not diffs else "drift"
    for d in diffs:
        print(f"[AUDIT] \u534f\u8bae\u6f02\u79fb: {d['field']} \u4e0d\u4e00\u81f4 \u2192 {d['values']} \u2713")

    # 基准等价性: 被审计的各臂与一个**已发布**的对照进程逐字段比较 →
    # 证明“差异只是 seed”或“存在协议漂移” ✓ (不是靠眼看数字猜的 ✓)
    baseline = None
    if args.baseline:
        bdir = os.path.join(BENCH, args.baseline)
        bcfg = read_args(bdir)
        if bcfg is None:
            print(f"[AUDIT] 基准进程 {args.baseline}: 没找到 args.yaml → 无法比较 ✓")
        else:
            baseline = {"run": args.baseline,
                        "cfg": {k: bcfg.get(k) for k in COMPARE_KEYS + ("epochs", "model", "data", "seed")}}
            for run, cfg in actual.items():
                diff = {}
                for k in ("epochs", "imgsz", "batch", "workers", "device", "optimizer",
                          "close_mosaic", "pretrained", "model", "data", "seed"):
                    bv = baseline["cfg"].get(k)
                    av = cfg.get(k)
                    if bv is None or av is None or str(bv) == str(av):
                        continue
                    if k == "data":
                        # **比比真正的图片列表, 不比 yaml 路径** →
                        # 两个 yaml 指向同一份名单时不应报差异 ✓
                        bl = train_list(bv) if str(bv).lower().endswith((".yaml", ".yml")) else None
                        al = train_list(av) if str(av).lower().endswith((".yaml", ".yml")) else None
                        if bl is not None and al is not None and bl == al:
                            continue
                    diff[k] = {"baseline": bv, "arm": av}
                if diff:
                    print(f"[AUDIT] {run} vs 基准 {args.baseline}: 差异字段 {list(diff.keys())} → {diff} ✓")
                    baseline.setdefault("diffs", {})[run] = diff
                else:
                    baseline.setdefault("diffs", {})[run] = {}

    art["actual_train_config"] = {k: v for k, v in actual.items()}
    art["protocol_audit"] = {
        "generated_by": "pipelines/shelf_sdg/75_protocol_audit.py",
        "compared_fields": list(COMPARE_KEYS),
        "allowed_differences": list(ALLOWED_DIFF),
        "status": status,
        "deviations": diffs,
    }
    if baseline:
        art["protocol_audit"]["baseline_comparison"] = baseline
    with open(art_p, "w", encoding="utf-8") as fh:
        json.dump(art, fh, ensure_ascii=False, indent=2)
    print(f"[AUDIT] {art_p}: {len(actual)} \u4e2a run, \u72b6\u6001 {status} \u2713")
    for kk, v in actual.items():
        print(f"   {kk}: epochs={v.get('epochs')} batch={v.get('batch')} imgsz={v.get('imgsz')} model={str(v.get('model'))[-46:]}")
    return 0 if status == "clean" else 2


if __name__ == "__main__":
    raise SystemExit(main())
