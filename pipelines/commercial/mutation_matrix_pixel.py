#!/usr/bin/env python3
"""P0-A Mutation 捕获矩阵(像素级) — 联合结论第二条准入测试。

对 v17 定稿做数值域故障注入, 逐个跑 11 项门, 记录捕获情况:
- 阴性对照: 无损往返必须保持 11/11 PASS (防门误报)
- 弱锐化对照: 观察双侧门是否惩罚过度锐化
- 品牌涂毁: G9a/G9c 必须捕获
- 其余按预期门矩阵判定
输出: output/commercial/mutation_catch_matrix.json + 控制台矩阵
"""
import json, subprocess, sys, copy
import numpy as np
from PIL import Image, ImageFilter

SRC = "output/commercial/repro_lifestyle_v17.png"
DEEP = "output/commercial/repro_lifestyle_v17_deep.png"
MANI = "output/commercial/manifest_ls_v17.json"
BB = "output/commercial/repro_lifestyle_v17_brandbox.json"

img = np.asarray(Image.open(SRC).convert("RGB")).astype(np.float64)
H, W = img.shape[:2]
bb = json.load(open(BB))
u0, u1 = int(bb["u0"] * W), int(bb["u1"] * W)
v0, v1 = int(bb["v0"] * H), int(bb["v1"] * H)


def mutate_dark_shadows(a):
    b = a.copy()
    lum = b.mean(axis=2)
    w = np.clip(1.0 - lum / 90.0, 0, 1)[..., None]
    b = b + 25.0 * w
    return np.clip(b, 0, 255)


def mutate_compress_highlights(a):
    b = a.copy()
    lum = b.mean(axis=2)
    w = np.clip((lum - 190.0) / 65.0, 0, 1)[..., None]
    b = b - 38.0 * w
    return np.clip(b, 0, 255)


def mutate_cool(a):
    b = a.copy()
    b[..., 0] *= 0.93
    b[..., 2] *= 1.14
    return np.clip(b, 0, 255)


def mutate_desat(a):
    lum = a @ np.array([0.299, 0.587, 0.114])
    return np.clip(lum[..., None] * 0.55 + a * 0.45, 0, 255)


def mutate_brand_erase(a):
    b = a.copy()
    # 用 ROI 外的桌面暗色均值覆盖(抹掉墨色与品牌蓝)
    ref = np.concatenate([a[v0:v1, max(0, u0 - 60):u0], a[v0:v1, u1:u1 + 60]], axis=1)
    fill = ref.reshape(-1, 3).mean(axis=0)
    b[v0:v1, u0:u1] = fill
    return np.clip(b, 0, 255)


def mutate_blur(a):
    return np.asarray(Image.fromarray(a.astype(np.uint8)).filter(
        ImageFilter.GaussianBlur(4.0))).astype(np.float64)


def mutate_sharpen(a):
    return np.asarray(Image.fromarray(a.astype(np.uint8)).filter(
        ImageFilter.UnsharpMask(radius=3, percent=110, threshold=2))).astype(np.float64)


CASES = [
    ("阴性_无损往返", None, "全部门(不得误报)"),
    ("像素_亮度-20%", lambda a: np.clip(a * 0.80, 0, 255), "G1"),
    ("像素_暗部抬升", mutate_dark_shadows, "G2b"),
    ("像素_高光压平", mutate_compress_highlights, "G3"),
    ("像素_冷调偏移", mutate_cool, "G4"),
    ("像素_降饱和", mutate_desat, "G7"),
    ("像素_品牌涂毁", mutate_brand_erase, "G9a,G9c"),
    ("像素_全图模糊", mutate_blur, "G8,G10,G11"),
    ("对照_弱锐化", mutate_sharpen, "观察G8上界/G10/G11(不得无代价奖励)"),
]


def run_gate(cand_path):
    p = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lifestyle_gate.py"), "--deep", DEEP, "--manifest", MANI, cand_path],
        capture_output=True, text=True, timeout=300)
    out = p.stdout + p.stderr
    res = {}
    total = None
    import re
    for m in re.finditer(r"(G\d+\w?)\s+.*?(PASS|FAIL|N/A)(?:\s+实测\s+([\w.\-]+))?", out):
        res[m.group(1)] = (m.group(2), m.group(3))
    m = re.search(r"→\s*(\d+)/(\d+)\s*PASS", out)
    if m:
        total = f"{m.group(1)}/{m.group(2)}"
    return res, total, out


rows = []
summary = {}
for name, fn, expect in CASES:
    import shutil, re as _re
    stem = "output/commercial/mut_" + _re.sub(r"[^\w\u4e00-\u9fff]", "_", name)
    outp = stem + ".png"
    if fn is None:
        Image.fromarray(img.astype(np.uint8)).save(outp)  # 无损重编码往返
    else:
        Image.fromarray(fn(img).astype(np.uint8)).save(outp)
    # sidecar 配对复制(门脚本按 <候选名>_brandbox/_regions.json 解析真值ROI)
    shutil.copy("output/commercial/repro_lifestyle_v17_brandbox.json", stem + "_brandbox.json")
    shutil.copy("output/commercial/repro_lifestyle_v17_regions.json", stem + "_regions.json")
    res, total, raw = run_gate(outp)
    failed = [k for k, v in res.items() if v[0] == "FAIL"]
    passed = [k for k, v in res.items() if v[0] == "PASS"]
    rows.append({"mutation": name, "expect": expect, "total": total,
                 "failed": failed, "passed_n": len(passed)})
    caught = [g for g in expect.split(",") if g.strip() in failed]
    summary[name] = {"expect": expect, "failed": failed,
                     "caught": caught, "total": total}
    print(f"{name:14s} → {total}  FAIL={failed or '无'}  预期门捕获={caught or '—'}")

json.dump({"rows": rows, "summary": summary},
          open("output/commercial/mutation_catch_matrix.json", "w"),
          ensure_ascii=False, indent=2)
print("\n矩阵已存 output/commercial/mutation_catch_matrix.json")
