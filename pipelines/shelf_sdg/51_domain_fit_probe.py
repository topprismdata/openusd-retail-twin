#!/usr/bin/env python
"""纯合成臂的**域内可学性 vs 跨域迁移**判别 (2026-11-24)。

问题
----
已知的全部事实 (都来自本仓已有产物):

  * 真实图 147 框/图 -> mAP 0.886; 真实图**砍到 22 框/图** -> 0.844 (密度只值 ~4 pp);
  * 合成图 21.8 框/图 -> 在真实 test 上 mAP **0.227**;
  * 把合成的**标签口径**对齐到真实 (单框面积 0.0031 vs 0.0030、宽高比 0.93 vs 1.05)
    -> 0.207, **反而更差**;
  * 标注与渲染物体一致、可见度过滤从未触发 (label_semantics.json)。

所以: 差距**不是框数** (密度实验已证), **不是标签口径** (形状臂已证)。那还剩什么?
两个候选, 从来没被分开测过:

  (a) **域内都学不会** -> 合成数据本身病态 (外观退化 / 单一模板过拟合 / 标签语义再深一层的错),
      那么"合成不可用"是数据生成的问题, 有得修;
  (b) **域内学得很好, 一到真实域就不行** -> 纯粹的 sim2real 外观差距, 那么负结论是
      关于"外观真实度"的, 下一步该投的是渲染真实度 (贵), 而不是继续调标签口径 (没用)。

判别方法 (不需要新训练, 只用本地已有的权重)
------------------------------------------
对每条纯合成臂的权重, 在三个评测集上跑 mAP@0.5:

  1. **自己池的 val** (域内可学性);
  2. **别的合成池的 val** (跨池迁移: 同生成器, 不同配方/种子);
  3. **真实 SKU-110K test** (跨域迁移 = 已发布的那个数, 用来对账)。

同时评 `best.pt` 与 `last.pt`: best 是**按合成 val** 选的, 如果 best 在域内显著高于
last, 说明"域内自选模"本身就在吃域内的便宜 —— 这个差值就是域内过拟合的直接读数。

产物:
  output/benchmark/domain_fit_probe.json / .md  (26 号会发布到 docs/research/benchmark/)

用法:
    python pipelines/shelf_sdg/51_domain_fit_probe.py --seeds 42,43,44
"""
import argparse
import json
import os
import shutil
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
PUB = os.path.join(BASE, "docs", "research", "benchmark")

# 臂 -> (权重目录模板, 自己的池 yaml)
ARMS = {
    "r1": ("runs_r1_s{seed}", os.path.join(BENCH, "synth_single", "dataset.yaml")),
    "r1shape": ("runs_r1shape_s{seed}", os.path.join(BENCH, "synth_single_shape", "dataset.yaml")),
    "r3pm": ("runs_R3pm_s{seed}", os.path.join(BENCH, "synth_single_R3pm", "dataset.yaml")),
}
# 每条臂的**自己池** (域内可学性就看它)
OWN_POOL = {"r1": "pool_r1", "r1shape": "pool_shape", "r3pm": "pool_r3pm"}
# 评测集: 名字 -> (yaml, split)
POOLS = {
    "pool_r1": (os.path.join(BENCH, "synth_single", "dataset.yaml"), "val"),
    "pool_shape": (os.path.join(BENCH, "synth_single_shape", "dataset.yaml"), "val"),
    "pool_r3pm": (os.path.join(BENCH, "synth_single_R3pm", "dataset.yaml"), "val"),
    "pool_big": (os.path.join(BENCH, "synth_bigpool", "dataset.yaml"), "val"),
    "real_test": (os.environ.get("SKU110K_YAML", "SKU-110K.yaml"), "test"),
}
REAL_YAML = os.environ.get("SKU110K_YAML", "SKU-110K.yaml")


def resolve_device():
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def evaluate(ckpt, yaml_path, split, imgsz=640, batch=8):
    """评一个权重 -> mAP@0.5 (失败返回 None, 不中断整轮)。"""
    if not os.path.isfile(ckpt):
        return None
    if not os.path.isabs(yaml_path):
        yaml_path = os.path.join(BASE, yaml_path)
    try:
        from ultralytics import YOLO
        m = YOLO(ckpt)
        r = m.val(data=yaml_path, split=split, imgsz=imgsz, batch=batch,
                  device=resolve_device(), max_det=1000, workers=2, verbose=False)
        return {"map50": float(r.box.map50), "map50_95": float(r.box.map)}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


def pool_leakage():
    """各池的 train/val **场景**是否相交 —— 域内 mAP 会不会是泄漏抬高的?

    必须查: 本仓吃过一次亏 (已发布四臂用旧的 idx%5 划分 -> train/val 同场景)。
    域内 0.995 这种数如果来自泄漏, 就不能说"合成域学得会"。
    """
    out = {}
    for label, src in (("r1", os.path.join(BASE, "output", "sdg_shelf")),
                       ("shape", os.path.join(BENCH, "sdg_shape")),
                       ("r3pm", os.path.join(BENCH, "sdg_R3pm"))):
        man = os.path.join(src, "split_manifest.json")
        if not os.path.exists(man):
            out[label] = {"error": "缺 split_manifest.json"}
            continue
        try:
            d = json.load(open(man, encoding="utf-8"))
        except Exception as e:
            out[label] = {"error": f"{type(e).__name__}: {e}"}
            continue
        scenes = d.get("scenes") or []
        tr = {s.get("scene_id") for s in scenes if s.get("split") == "train"}
        va = {s.get("scene_id") for s in scenes if s.get("split") == "val"}
        out[label] = {"split_mode": d.get("split_mode"),
                      "split_policy": d.get("split_policy"),
                      "n_train_scenes": len(tr), "n_val_scenes": len(va),
                      "scene_overlap": len(tr & va),
                      "leak_free": len(tr & va) == 0}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", default="42,43,44")
    ap.add_argument("--arms", default=",".join(ARMS))
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--stage", choices=("eval", "leak"), default="eval",
                    help="leak = 只跑划分泄漏检查并写进产物")
    args = ap.parse_args()
    seeds = [int(x) for x in args.seeds.split(",") if x.strip()]
    arms = [a for a in args.arms.split(",") if a.strip()]

    if args.stage == "leak":
        leak = pool_leakage()
        p = os.path.join(BENCH, "domain_fit_probe.json")
        rep = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        rep["pool_scene_leakage"] = leak
        for k, v in leak.items():
            if v.get("leak_free") is False:
                print(f"[LEAK] 池 {k}: train/val **场景重叠 {v.get('scene_overlap')}** "
                      f"→ 域内数字不可信")
            else:
                print(f"[LEAK] 池 {k}: 场景级留出, 重叠 {v.get('scene_overlap')} "
                      f"(train {v.get('n_train_scenes')} / val {v.get('n_val_scenes')})")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)
        if os.path.exists(p):
            shutil.copy2(p, os.path.join(PUB, "domain_fit_probe.json"))
        return 0

    rows = []
    for arm in arms:
        tpl, own_pool = ARMS[arm]
        for seed in seeds:
            run = os.path.join(BENCH, tpl.format(seed=seed))
            for ck in ("best.pt", "last.pt"):
                ckpt = os.path.join(run, "train", "weights", ck)
                if not os.path.isfile(ckpt):
                    continue
                rec = {"arm": arm, "seed": seed, "ckpt": ck,
                       "checkpoint": os.path.relpath(ckpt, BASE).replace("\\", "/"),
                       "evals": {}}
                for name, (ypath, split) in POOLS.items():
                    if not os.path.exists(ypath if os.path.isabs(ypath)
                                          else os.path.join(BASE, ypath)):
                        rec["evals"][name] = None
                        continue
                    r = evaluate(ckpt, ypath, split, batch=args.batch)
                    rec["evals"][name] = r
                    print(f"  {arm} s{seed} {ck} -> {name}: "
                          f"{r.get('map50') if r else None}", flush=True)
                rows.append(rec)

    # 汇总: 每臂的域内/跨池/真实 三项 (取 last.pt 与 best.pt 各自)
    summary = {}
    for arm in arms:
        for ck in ("best.pt", "last.pt"):
            vals = {"pool_r1": [], "pool_shape": [], "pool_r3pm": [],
                    "pool_big": [], "real_test": []}
            for r in rows:
                if r["arm"] != arm or r["ckpt"] != ck:
                    continue
                for k in vals:
                    e = r["evals"].get(k)
                    if e and "map50" in e:
                        vals[k].append(e["map50"])
            if not any(vals.values()):
                continue
            summary[f"{arm}/{ck}"] = {
                k: ({"mean": round(statistics.mean(v), 4),
                     "sd": round(statistics.stdev(v), 4) if len(v) > 1 else 0.0,
                     "n": len(v)} if v else None)
                for k, v in vals.items()}
            s = summary[f"{arm}/{ck}"]
            own = s.get(OWN_POOL.get(arm, "pool_r1"))
            rt = s["real_test"]
            if own and rt:
                s["domain_fit_minus_transfer_pp"] = round(
                    (own["mean"] - rt["mean"]) * 100, 2)

    rep = {"schema": "domain_fit_probe/1",
           "generated_by": "pipelines/shelf_sdg/51_domain_fit_probe.py",
           "measured_at": "2026-11-24",
           "question": ("纯合成臂: 域内(自己池 val)能不能学会? 学会��到真实域还剩多少?"
                        " -> 决定下一步是修数据生成器还是投渲染真实度"),
           "arms": {a: ARMS[a][0] for a in arms},
           "pools": {k: {"yaml": v[0], "split": v[1]} for k, v in POOLS.items()},
           "per_record": rows,
           "summary": summary}

    os.makedirs(BENCH, exist_ok=True)
    for p in (os.path.join(BENCH, "domain_fit_probe.json"),
              os.path.join(PUB, "domain_fit_probe.json")):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(rep, fh, ensure_ascii=False, indent=2)

    lines = ["# 域内可学性 vs 跨域迁移 (2026-11-24)", "",
             "每条纯合成臂的权重, 在自己池的 val (域内)、别的池的 val (跨池)、真实 test "
             "(跨域) 上评测。", "",
             "| 臂 / 权重 | 域内 (自己池) | R1池 | 形状池 | R3pm池 | 真实 test | 域内−真实 |",
             "|---|---|---|---|---|---|---:|"]
    for k, s in summary.items():
        def cell(name):
            v = s.get(name)
            return f"{v['mean']:.4f} ± {v['sd']:.4f} (n={v['n']})" if v else "—"
        d = s.get("domain_fit_minus_transfer_pp")
        own_name = OWN_POOL.get(k.split("/")[0], "pool_r1")
        lines.append(f"| {k} | {cell(own_name)} | {cell('pool_r1')} | "
                     f"{cell('pool_shape')} | {cell('pool_r3pm')} | {cell('real_test')} | "
                     f"{('%+.2f pp' % d) if d is not None else '—'} |")
    lines += ["", "**读法**: 域内高、真实低 -> 合成域学得会, 差距是跨域外观 (sim2real); "
              "域内也低 -> 合成数据本身病态 (生成器/多样性), 该修的是数据而不是渲染真实度。"]
    md = "\n".join(lines) + "\n"
    for p in (os.path.join(BENCH, "domain_fit_probe.md"),
              os.path.join(PUB, "domain_fit_probe.md")):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(md)
    print("\n" + md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
