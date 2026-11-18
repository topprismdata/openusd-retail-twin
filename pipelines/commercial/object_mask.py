#!/usr/bin/env python3
"""物件级**几何真值掩膜** (射线命中, 不用颜色阈值/bbox)。

为什么必须这样测 (本仓第17次"测错总体"):
  ①颜色掩膜有选择偏差: v123 用 `b>r+6 & L<150` 选蓝莓, 两版入选数不同(2081 vs 1315)
    = 不同总体, 报出的纹理 9.00x 实为 3.31x。
  ②**投影 bbox 含桌面/背景**: v126 探针在 oat_bowl/plate/carton 的 bbox 内测"高光区",
    得均亮 252.1/249.2/249.4 且 std 1.21/0.27/0.75 —— 这与实测**桌面**亮度(244-248)同族,
    量的是桌面不是釉面, 故"釉面高光已削顶"的结论**不成立**。
  → 唯一可靠口径: 逐像素从相机投射射线, 按**命中物件**归属。

实现: scene.ray_cast 打在 evaluated depsgraph 上(含修改器), 命中物件名归并到道具 id。
输出 JSON: 每 id 的像素索引(RLE 行程压缩, 避免几十万个整数)。
只在 OBJ_MASK=1 时由 34_commercial_repro.py 于渲染前调用; 默认关 → 冻结分支零影响。

用法(渲染时): OBJ_MASK=1 ... --out ls_mask
读取: python3 object_mask.py <mask.json> <图> [--id oat_bowl]
"""
import json
import os
import sys


def _owner_id(name, ids):
    """命中物件名 → 道具 id。道具根名 LS_<id>, 子件 LS_<id>_xxx。"""
    n = name.lower()
    best = None
    for i in ids:
        t = ("ls_" + i).lower()
        if n == t or n.startswith(t + "_") or n.startswith(t + "."):
            if best is None or len(i) > len(best):
                best = i
    if best:
        return best
    for alias, i in (("carton1l", "carton"), ("plate", "plate"),
                     ("croissant", "croissant"), ("gls0002", "glass"),
                     ("object_4", "glass"), ("cylinder", "glass")):
        if alias in n:
            return i
    return None


def dump(scene, path):
    import bpy
    import mathutils

    cam = scene.camera
    rx, ry = scene.render.resolution_x, scene.render.resolution_y
    dg = bpy.context.evaluated_depsgraph_get()
    frame = [cam.matrix_world @ v for v in cam.data.view_frame(scene=scene)]
    tl, tr, br, bl = frame[3], frame[2], frame[1], frame[0]
    # v126b 修 id 截断: 原 `o.name[3:].split("_")[0]` 把 LS_oat_bowl 截成 "oat",
    # 且把 sauce_jam/sauce_honey **合并成一个 id** → 与 manifest id 对不上、两件混测。
    # 改为从规格取准确 id(objects+props), 匹配时取最长前缀。
    ids = set()
    sp = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                      "specs", os.environ.get("LS_SPEC_NAME", "lifestyle_1l.json"))
    if os.path.exists(sp):
        d = json.load(open(sp))
        ids |= {o["id"] for o in d.get("objects", [])}
        ids |= {p["id"] for p in d.get("props", [])}
    ids |= {"carton", "glass", "plate", "croissant"}
    origin = cam.matrix_world.translation
    runs = {}
    step = max(1, int(os.environ.get("OBJ_MASK_STEP", "2")))
    hits = 0
    for py in range(0, ry, step):
        fy = py / max(1, ry - 1)
        left = tl.lerp(bl, fy)
        right = tr.lerp(br, fy)
        cur, start = None, 0
        for px in range(0, rx, step):
            p = left.lerp(right, px / max(1, rx - 1))
            d = (p - origin).normalized()
            hit, loc, nrm, idx, ob, mw = scene.ray_cast(dg, origin, d)
            k = _owner_id(ob.name, ids) if (hit and ob) else None
            if k:
                hits += 1
            if k != cur:
                if cur is not None:
                    runs.setdefault(cur, []).append([py, start, px])
                cur, start = k, px
        if cur is not None:
            runs.setdefault(cur, []).append([py, start, rx])
    out = {"res": [rx, ry], "step": step, "runs": runs, "hits": hits}
    with open(path, "w") as fh:
        json.dump(out, fh)
    print("[OBJ-MASK] ids=%s hits=%d step=%d → %s"
          % (sorted(runs), hits, step, os.path.basename(path)))
    return out


def load_mask(path):
    import numpy as np
    d = json.load(open(path))
    rx, ry, st = d["res"][0], d["res"][1], d["step"]
    out = {}
    for k, rr in d["runs"].items():
        m = np.zeros((ry, rx), bool)
        for py, x0, x1 in rr:
            m[py:py + st, x0:x1] = True
        out[k] = m
    return out


def main():
    import numpy as np
    from PIL import Image
    W = np.array([0.2126, 0.7152, 0.0722])
    if len(sys.argv) < 3:
        print("用法: object_mask.py <mask.json> <图> [--id name]")
        return 2
    masks = load_mask(sys.argv[1])
    arr = np.asarray(Image.open(sys.argv[2]).convert("RGB")).astype(float)
    L = arr @ W
    want = sys.argv[4] if len(sys.argv) > 4 and sys.argv[3] == "--id" else None
    print("=== 几何真值掩膜内统计(排除桌面/背景) ===")
    for k, m in sorted(masks.items()):
        if want and k != want:
            continue
        if m.shape != L.shape or m.sum() < 50:
            print("  %-12s 像素不足/尺寸不符" % k)
            continue
        l = L[m]
        hi = l > np.percentile(l, 95)
        print("  %-12s n=%7d p50=%5.1f p95=%5.1f p99=%5.1f max=%5.1f | "
              "高光区均%6.1f std%5.2f clip>250=%.4f"
              % (k, m.sum(), np.percentile(l, 50), np.percentile(l, 95),
                 np.percentile(l, 99), l.max(), l[hi].mean(), l[hi].std(),
                 (l > 250).mean()))
    return 0


if __name__ == "__main__":
    sys.exit(main())