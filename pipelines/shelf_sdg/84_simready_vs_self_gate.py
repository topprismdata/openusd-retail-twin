#!/usr/bin/env python
"""把"官方 SimReady 验证"与"本仓自研资产闸"并排成一份差异报告。

输入 (都由脚本现算, 不手写):
  - output/benchmark/asset_self_gate.json          (82 号脚本: 自研闸 5 项检查)
  - output/benchmark/simready_official_validation.json (83 号脚本: 官方验证器结果)

输出:
  - output/benchmark/simready_vs_self_gate.json
  - output/benchmark/simready_vs_self_gate.md

读法 (写在报告里, 避免被误读):
  - 两边**检查的不是同一件事**: 自研闸查 GLB/网格侧的 Khronos 发布目标; 官方查 USD 资产对
    SimReady profile 的合规。所以差异表的主体是**覆盖面差异**, 不是"谁更严"。
  - 官方结果里 `passed=null` 表示**执行不可用**(unavailable), 不是"资产失败"。
"""
import ast
import json
import os
import re
import sys
import time

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SELF = os.path.join(BASE, "output", "benchmark", "asset_self_gate.json")
OFFICIAL = os.path.join(BASE, "output", "benchmark", "simready_official_validation.json")
OUT_JSON = os.path.join(BASE, "output", "benchmark", "simready_vs_self_gate.json")
OUT_MD = os.path.join(BASE, "output", "benchmark", "simready_vs_self_gate.md")

# 自研闸 5 项检查 -> 官方 SimReady 是否覆盖 (依据: 官方 profile 的 feature/requirement 语义)
COVERAGE = [
    ("origin_units", "原点落在底面中心 + 尺寸符合规格 (mm)",
     "部分", "官方有单位/尺度/原点类 requirement (以 profile 为准); 但官方**不校验具体毫米数是否符合本仓 SKU 规格**"),
    ("topology", "ngon=0 / 非流形边=0 / 三角面数 <= 100k",
     "部分", "官方几何 feature 覆盖三角化与流形类要求; **100k 上限是 Khronos 发布目标, 官方不管**"),
    ("uv_01", "UV 落在 [0,1]",
     "部分", "官方材质/UV feature 覆盖 UV 合法性与绑定"),
    ("uv_atlas", "atlas 岛间 >=32px 间隙 + 零重叠 + 16px gutter",
     "不覆盖", "这是 **glTF/Khronos atlas 规范**, 与 SimReady profile 无关 -> 官方工具不会替我们查"),
    ("export_targets", "材质数 <=3 / 贴图 mime 限定 / 无灯光 / 文件 <=5MB",
     "不覆盖", "这是 **glTF 发布目标**, 与 SimReady profile 无关 -> 官方工具不会替我们查"),
]

OFFICIAL_ONLY = [
    ("物理属性", "mass / inertia / 碰撞代理 / 关节 (profile 依类型而定)"),
    ("语义与元数据", "sem:brand / sem:skuId / sem:productCategory / render:* / phys:*"),
    ("分层 profile", "按 Profile 选 requirement 集合 (Robotics-Prop / Package / ...)"),
    ("验证回执", "validation receipt (可 --audit 比对上次结果)"),
]


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def main():
    if not (os.path.exists(SELF) and os.path.exists(OFFICIAL)):
        print("missing inputs: run 82 (repo venv) and 83 (official-tool venv) first")
        return 2
    with open(SELF, encoding="utf-8") as f:
        selfr = json.load(f)
    with open(OFFICIAL, encoding="utf-8") as f:
        off = json.load(f)

    rows = []
    for r in off["results"]:
        if "error" in r:
            rows.append({"tag": r.get("tag"), "profile": r.get("profile"), "status": "ERROR",
                         "detail": r["error"]})
            continue
        if r.get("result", "x") is None or (r.get("passed") is None and not r.get("features_summary")):
            rows.append({"tag": r.get("tag"), "profile": r.get("profile"), "status": "UNAVAILABLE",
                         "detail": r.get("note", "unavailable_execution (不是 measured failure)")})
            continue
        rows.append({
            "tag": r.get("tag"), "profile": r.get("profile"),
            "profile_version": r.get("profile_version"),
            "status": "PASS" if r.get("passed") else "FAIL",
            "failed_features": r.get("failed_features", []),
            "blocking_failures": r.get("blocking_failures", []),
            "n_features": len(r.get("features_summary") or {}),
            "elapsed_s": r.get("elapsed_s"),
        })

    # requirement 级缺口 (只对"本仓自己的资产"抽取, 便于直接排期)
    gaps = []
    for r in off["results"]:
        if r.get("tag") != "ours":
            continue
        fs = r.get("features_summary") or {}
        for fname, entry in fs.items():
            if not isinstance(entry, dict) or entry.get("passed") is not False:
                continue
            reqs = entry.get("failing requirements") or []
            msgs = entry.get("requirement_messages") or {}
            if isinstance(reqs, str):
                try:
                    reqs = ast.literal_eval(reqs)
                except Exception:
                    reqs = [reqs]
            if isinstance(msgs, str):
                try:
                    msgs = json.loads(msgs)
                except Exception:
                    msgs = {}
            for code in reqs:
                m = msgs.get(code) if isinstance(msgs, dict) else None
                if isinstance(m, list):
                    m = m[0] if m else ""
                gaps.append({"profile": r.get("profile"), "feature": fname,
                             "requirement": str(code), "message": _norm(str(m))[:300]})

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "script": "pipelines/shelf_sdg/84_simready_vs_self_gate.py",
        "official_tool": off.get("tool"),
        "official_profiles_available": list((off.get("profiles_available") or {}).keys()),
        "official_results": rows,
        "our_asset_requirement_gaps": gaps,
        "self_gate": {"sku": selfr.get("sku"), "overall": selfr.get("overall"),
                      "checks": selfr.get("checks")},
        "coverage_map": [{"self_check": c, "what": w, "official_coverage": cov, "why": why}
                         for c, w, cov, why in COVERAGE],
        "official_only": [{"area": a, "detail": d} for a, d in OFFICIAL_ONLY],
        "verdict": {
            "replaceable": [],
            "keep": ["atlas 间隙/重叠/gutter", "glTF 发布目标(材质数/mime/体积)"],
            "reason": ("自研闸里 **atlas 间隙/重叠/gutter** 与 **glTF 发布目标** 两项官方工具不管 -> "
                       "官方工具不能替代自研闸, 只能**叠加**一层 USD 侧合规校验; "
                       "自研闸守的是渲染/发布面, 官方验的是仿真面"),
        },
        "not_done": off.get("not_done", []) + [
            "本仓资产的单文件合规包在 86 号脚本里另做 (Package-Candidate 已 PASS) —— "
            "这份差异报告评的是**原始三文件资产** output/usd/demo_classic/Product.usda"
        ],
    }
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # ---- markdown ----
    md = []
    md.append("# 官方 SimReady 验证器 vs 本仓自研资产闸: 差异报告\n")
    md.append(f"生成时间: {payload['generated_at']} · 脚本: `{payload['script']}`\n")
    tool = payload.get("official_tool") or {}
    md.append(f"官方工具: **{tool.get('package')} {tool.get('version')}** (许可 {tool.get('license')}) · "
              f"运行环境: {tool.get('env')}\n")
    md.append("## 一句话结论\n")
    md.append(f"> {payload['verdict']['reason']}。\n")
    md.append("## 官方验证结果 (逐资产 x profile)\n")
    md.append("| 资产 | profile | 版本 | 结果 | 失败 feature | 阻断失败 | feature 数 | 耗时 |")
    md.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        md.append(f"| {r.get('tag')} | {r.get('profile')} | {r.get('profile_version') or '-'} | "
                  f"**{r['status']}** | {len(r.get('failed_features') or [])} | "
                  f"{len(r.get('blocking_failures') or [])} | {r.get('n_features', '-')} | "
                  f"{r.get('elapsed_s', '-')}s |")
    md.append("\n> `UNAVAILABLE` = 官方执行不可用 (checker ERROR / profile 未解析), **不是** measured failure; "
              "`ERROR` = 调用本身报错。两者都不许读成\"资产不合规\"。\n")
    if payload["our_asset_requirement_gaps"]:
        md.append("## 本仓资产被官方点名的具体 requirement (可直接排期)\n")
        md.append("| profile | feature | requirement | 官方原话 |")
        md.append("|---|---|---|---|")
        for g in payload["our_asset_requirement_gaps"]:
            md.append(f"| {g['profile']} | `{g['feature']}` | `{g['requirement']}` | {_norm(g['message'])} |")
        md.append("")
    md.append("## 自研闸 (本仓, 82 号脚本现算)\n")
    md.append(f"资产 `{payload['self_gate'].get('sku')}` · 总判据 **{payload['self_gate'].get('overall')}**\n")
    md.append("| 检查 | 判据 | 细节 |")
    md.append("|---|---|---|")
    for k, v in (payload["self_gate"]["checks"] or {}).items():
        md.append(f"| {k} | {v.get('verdict')} | {_norm(v.get('detail'))} |")
    md.append("\n## 覆盖面差异 (这是本报告的主体)\n")
    md.append("| 自研检查 | 内容 | 官方是否覆盖 | 说明 |")
    md.append("|---|---|---|---|")
    for c in payload["coverage_map"]:
        md.append(f"| `{c['self_check']}` | {c['what']} | **{c['official_coverage']}** | {c['why']} |")
    md.append("\n### 只有官方有的那一层\n")
    for o in payload["official_only"]:
        md.append(f"- **{o['area']}**: {o['detail']}")
    md.append("\n## 本轮明确没做的事\n")
    for n in payload["not_done"]:
        md.append(f"- {n}")
    md.append("")
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    print(f"[DIFF] -> {OUT_JSON}")
    print(f"[DIFF] -> {OUT_MD}")
    for r in rows:
        print(f"  {r.get('tag')}: {r.get('profile')} -> {r['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
