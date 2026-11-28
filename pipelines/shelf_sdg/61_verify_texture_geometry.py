#!/usr/bin/env python
"""纹理臂的**单变量**验证: 几何必须与白盒对照池逐帧相同 (2026-11-25)。

为什么要有这个检查
----------------
纹理臂 (57 号) 的全部意义在于"同配方 / 同 seed / 同场景布局, **只改商品表面像素**"。
但这个前提是**会悄悄坏**的: 渲染器改了任何影响布局的东西 (SKU 配比、错位率、
相机、形状采样、类别过滤口径), 纹理臂就会变成"同时改了几样东西"的臂, 而结果会被
读成"贴图有用/有害" —— 而真正变的是别的东西。

本脚本按**标签**验证: 标签就是几何, 所以
  纹理池 (原始 4 类) 去掉 class 1 (14/43/57 号同逻辑) 之后, 与**单类化后的**
  对照池 (synth_single) 逐帧逐框比较 xywh。
两个必须做对的地方 (都踩过):
  1. **类别口径**: 对照池已经是单类 (class 1 被丢), 纹理池是原始 4 类 -> 不丢
     class 1 就比, 框数必然不同 (27 vs 30), 会误判成"几何变了"。
  2. **行序**: 框的输出顺序不保证一致 -> 按**集合**比, 不按行序比。

用法:
    python pipelines/shelf_sdg/61_verify_texture_geometry.py
"""
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
BENCH = os.path.join(BASE, "output", "benchmark")
CTRL_LAB = os.path.join(BENCH, "synth_single", "labels", "train")
TEX_LAB = os.path.join(BENCH, "sdg_shelf_tex", "labels", "train")
OUT_JSON = os.path.join(BENCH, "texture_geometry_parity.json")
DROP_CLASSES = {1}


def geom(path):
    """返回该标签文件的框几何集合 (xywh, 去掉被丢的类)。"""
    out = set()
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            p = line.split()
            if len(p) >= 5 and int(float(p[0])) not in DROP_CLASSES:
                out.add(tuple(round(float(x), 5) for x in p[1:5]))
    return out


def main():
    if not os.path.isdir(CTRL_LAB) or not os.path.isdir(TEX_LAB):
        print(f"[跳过] 标签目录不存在: {CTRL_LAB} / {TEX_LAB}")
        return 0
    names = sorted(f for f in os.listdir(TEX_LAB) if f.endswith(".txt"))
    same, diff, missing, examples = 0, 0, 0, []
    for n in names:
        a, b = os.path.join(CTRL_LAB, n), os.path.join(TEX_LAB, n)
        if not os.path.isfile(a):
            missing += 1
            continue
        ga, gb = geom(a), geom(b)
        if ga == gb:
            same += 1
        else:
            diff += 1
            if len(examples) < 5:
                examples.append({"file": n, "ctrl_boxes": len(ga), "tex_boxes": len(gb),
                                 "intersection": len(ga & gb)})
    ok = (diff == 0 and missing == 0 and same > 0)
    rep = {"schema": "texture_geometry_parity/1",
           "generated_by": "pipelines/shelf_sdg/61_verify_texture_geometry.py",
           "checked": {"control_labels": os.path.relpath(CTRL_LAB, BASE).replace("\\", "/"),
                       "texture_labels": os.path.relpath(TEX_LAB, BASE).replace("\\", "/"),
                       "drop_classes": sorted(DROP_CLASSES)},
           "n_images": len(names), "identical": same, "different": diff,
           "missing_in_control": missing, "examples": examples,
           "verdict": ("几何逐帧相同 -> 纹理臂确实是**只改商品表面**的单变量对照"
                       if ok else "几何不一致 -> 纹理臂混进了别的变量, 结果不可按贴图解读")}
    with open(OUT_JSON, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print(f"[GEOM] {same}/{len(names)} 张几何完全相同, 不同 {diff}, 对照池缺 {missing}")
    print(f"[GEOM] {rep['verdict']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
