#!/usr/bin/env python3
"""接触阴影**半影宽度**判据 (入库, 补 shadow_probe 缺的维度)。

为什么需要它: `shadow_probe` 只量 depth(深度), 不量柔和度。实测冲突 ——
候选 carton depth **+0.411** 比参照 0.198 更深, 但外部评审仍把"缺接触阴影/AO、
物体像贴在桌面上"列为 #2 致命缺陷。沿阴影方向做亮度恢复剖面后两者同时成立:
  候选 carton 落差27.4 半影**0.130** / oat_bowl 落差64.6 半影**0.110**
  参照 燕麦碗   落差38.4 半影**0.260**  (物体高单位)
→ 我的阴影**更深但更窄硬**, 参照**更浅但半影宽约一倍**。depth 测不到这个。

物理: 半影宽度 ∝ 光源**角尺寸**。故杠杆是投影主光的 size(w/h), 不是能量、
不是 world 强度(后者只改深度不改宽度)。

**测量局限(必须披露)**: 候选侧用 manifest 真值投影 + 真实物体高归一, 可靠;
参照无 manifest, 只能用目视锚点与目视投影高归一 → 其数值有不确定度, 不可当精确门。

用法: python3 shadow_penumbra.py <候选图> --manifest <实拍manifest> [--ids carton,oat_bowl]
**本工具只作候选侧诊断, 不作门, 不可跨图/跨分辨率比较(v120-v121 定性)**:
  ①参照无 manifest, 锚点与物体高只能目视估 → "参照0.260 vs 候选0.130" 证据不足, 该跨图结论已撤回;
  ②判据随分辨率变: **同一配置** 1920 得 carton 0.130、640 得 0.200(采样窗±2px 与 t 步长量化);
  ③**判据本身有效**(负向对照已验): 同一张图换采样方向 → 240°阴影侧 落差18.8/半影0.200,
    60°受光侧 落差10.5/半影**0.020**, 120° 落差170.4/半影**0.130** → 对方向敏感, 确在测阴影结构。
    先前怀疑"判据无效"已被此对照推翻。
  ④**但"角尺寸"这个杠杆对该指标无效**: base640 / ×2 / ×3 / **装置有效的×1.5**(1.95x2.40m,
    灯心z0.95→1.30, 整面脱开几何)四档, 半影恒为 carton 0.200 / oat_bowl 0.160,
    而落差 10.5→18.8 明显变化 → 深度可变、宽度不变。按止损纪律停止该支线。
  ⑤装置校验纪律: ×2 灯面 z=-0.270..2.170、×3 z=-0.880..2.780 **穿桌面**故实验无效;
    遮挡判据须用 **z < fillet_z(y)**(圆角是曲面), 不能简化为 y>1.2 ——
    基线 y_max=1.375 处曲面 z≈0.013, 灯面在其上方并未被遮(先前"基线亦穿圆角"的说法已撤回)。
"""

# v120 这三个 import 曾被一次 PUT 连带覆盖(只补了 docstring 闭合符), 运行时 NameError;
# py_compile 查不出, 且 `| tail` 会吞退出码 → 必须无管道实跑验证。
import argparse
import json
import math
import numpy as np
from PIL import Image

W = np.array([0.2126, 0.7152, 0.0722])


def basis(loc, tgt):
    loc = np.array(loc, float)
    tgt = np.array(tgt, float)
    z = loc - tgt
    z /= np.linalg.norm(z)
    x = np.cross([0, 0, 1.0], z)
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    return loc, x, y, z


def profile(L, m, proj, H, Wd, dir_deg, tmax=0.45, n=46):
    """沿 dir_deg(世界XY) 从真实前底缘锚点 outward 采样, t 以**物体真实高**归一。"""
    hw = m["zmax"] - m["zmin"]
    th = math.radians(dir_deg)
    out = []
    for t in np.linspace(0.0, tmax, n):
        wx = m["anchor"][0] + hw * t * math.cos(th)
        wy = m["anchor"][1] + hw * t * math.sin(th)
        u, v = proj((wx, wy, m["zmin"]))
        px, py = int(u * Wd), int(v * H)
        if 2 < px < Wd - 3 and 2 < py < H - 3:
            out.append((float(t), float(L[py - 2:py + 3, px - 2:px + 3].mean())))
    return out


def summarize(prof):
    """最暗点→环境亮度的 90% 恢复距离 = 半影宽度(物体高单位)。"""
    if len(prof) < 20:
        return None
    ts = np.array([p[0] for p in prof])
    vs = np.array([p[1] for p in prof])
    half = int(len(vs) * 0.5)
    amb = float(np.median(vs[int(len(vs) * 0.75):]))
    il = int(np.argmin(vs[:half]))
    lo = float(vs[il])
    thr = lo + 0.9 * (amb - lo)
    rec = next((ts[i] for i in range(il, len(vs)) if vs[i] >= thr), None)
    return {"dark": lo, "ambient": amb, "drop": amb - lo,
            "penumbra": (float(rec - ts[il]) if rec is not None else None),
            "t_dark": float(ts[il])}


def measure(img, manifest, spec, ids, dir_deg):
    man = json.load(open(manifest))
    sp = json.load(open(spec))
    a = np.asarray(Image.open(img).convert("RGB")).astype(float)
    H, Wd, _ = a.shape
    L = a @ W
    loc, x, y, z = basis(man["camera"]["loc"], sp["camera"]["target"])
    f = man["camera"]["lens"] / 1000.0
    sw = 0.036
    ar = Wd / H

    def proj(P):
        d = np.asarray(P, float) - loc
        Z = d @ z
        return ((d @ x) / (-Z) * f / sw + 0.5, 0.5 - (d @ y) / (-Z) * f / sw * ar)

    out = {}
    for k in ids:
        m = man["geometry_gate"]["measured"].get(k)
        if not m or "anchor" not in m:
            continue
        s = summarize(profile(L, m, proj, H, Wd, dir_deg))
        if s:
            out[k] = s
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("images", nargs="+")
    p.add_argument("--manifest", default="output/commercial/manifest_lifestyle_1l_highkey.json")
    p.add_argument("--spec", default="specs/lifestyle_1l.json")
    p.add_argument("--ids", default="carton,oat_bowl")
    p.add_argument("--dir", type=float, default=240.0,
                   help="阴影方向(世界XY度); 由 shadow_probe 的 shadow_dir_deg 给出")
    a = p.parse_args()
    ids = a.ids.split(",")
    print("半影宽度(物体高单位) — **仅候选侧诊断**: 不作门, 不可跨图/跨分辨率比较(见文件头 v120 撤回)")
    for img in a.images:
        res = measure(img, a.manifest, a.spec, ids, a.dir)
        print("\n%s" % img)
        for k, s in res.items():
            pn = "%.3f" % s["penumbra"] if s["penumbra"] is not None else ">tmax(未恢复)"
            print("  %-11s 最暗%6.1f 环境%6.1f 落差%5.1f 半影=%s"
                  % (k, s["dark"], s["ambient"], s["drop"], pn))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())