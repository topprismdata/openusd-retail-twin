#!/usr/bin/env python3
"""声明式场景运行时 (v103): 规格驱动 + 渲染前几何闸 + 实拍状态回写。

为什么需要它 (量化证据, 不是偏好):
  34_commercial_repro.py 1782 行 / 41 个 env 开关, 全仓 64 个, 零声明式配置;
  manifest.json 只写不读。场景状态隐式散落在过程式代码里 →
  同一病根手工产出六个 bug: 猜对象名 / 杯奶不同步 / 盘出画 / clamp 洗品牌 /
  品牌框测错对象 / manifest 记改造前假值。
  第七例: 规格里手填 footprint_r=0.060, 而吐司双片实测 186x128mm → 穿模闸会漏判。
  故**几何量一律运行时实测**, 规格只声明意图(位置/角色/约束), 不写测量值。

本模块把三件事变成运行时强制:
  1. 身份解析: 按 material/name/name_prefix 声明, 解析不到就 raise (不静默跳过)
  2. 几何闸: 摆位后实测穿模间隙 / 入画 / 贴地, 不过就 raise (不产废片)
  3. 溯源: 相机/曝光/灯具/画幅/品牌框一律从**实拍状态**回写, 不复制输入参数

不做全量 USD 化: 程序化 shader / glTF 透射 / Mantaflow / 品牌 UV 无法无损往返
UsdPreviewSurface, 会砸掉已双轮盲评的冻结交付。USD 继续做资产层(13_usd_asset.py)。
"""
import hashlib
import json
import math
import os

import bpy
import mathutils as mu


class SpecError(RuntimeError):
    pass


def load(path):
    with open(path) as fh:
        raw = fh.read()
    spec = json.loads(raw)
    if spec.get("schema") != 1:
        raise SpecError("unsupported spec schema: %r" % spec.get("schema"))
    for key in ("name", "frame", "camera", "objects", "constraints"):
        if key not in spec:
            raise SpecError("spec 缺字段: %s" % key)
    spec["_path"] = path
    spec["_sha"] = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return spec


def resolve(sel):
    """声明式身份解析。仓库既有约定: glTF 对象名不可靠, 玻璃只能按材质抓。"""
    out = []
    for ob in bpy.data.objects:
        if ob.type != "MESH":
            continue
        if "material" in sel:
            if ob.data.materials and any(m and m.name == sel["material"] for m in ob.data.materials):
                out.append(ob)
        elif "name" in sel:
            if ob.name == sel["name"]:
                out.append(ob)
        elif "name_prefix" in sel:
            if ob.name.lower().startswith(sel["name_prefix"].lower()):
                out.append(ob)
        else:
            raise SpecError("selector 无 material/name/name_prefix: %r" % sel)
    return out


def subtree_meshes(root):
    """root(或 root 列表)及其全部后代中的 MESH。

    接受列表: reg[id] = [main] + carry 从属件(杯内奶/盘上可颂, 无父链),
    只测 roots[0] 会漏掉从属件足迹 → 穿模闸漏判。
    """
    out = []
    stack = list(root) if isinstance(root, (list, tuple)) else [root]
    while stack:
        ob = stack.pop()
        if ob.type == "MESH" and ob.data and len(ob.data.vertices):
            out.append(ob)
        stack.extend(list(ob.children))
    return out


def world_bbox(root):
    """子树全部顶点的世界包围盒 (逐顶点, 不用 bound_box: Empty/父级 bbox 不含子件)。"""
    meshes = subtree_meshes(root)
    if not meshes:
        raise SpecError("[%s] 子树无网格, 无法测量" % root.name)
    mn = mu.Vector((1e9, 1e9, 1e9))
    mx = mu.Vector((-1e9, -1e9, -1e9))
    for ob in meshes:
        mw = ob.matrix_world
        for v in ob.data.vertices:
            p = mw @ v.co
            for k in range(3):
                if p[k] < mn[k]:
                    mn[k] = p[k]
                if p[k] > mx[k]:
                    mx[k] = p[k]
    return mn, mx


def center_xy(root):
    lo, hi = world_bbox(root)
    return ((lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5)


def footprint_r(root):
    """实测水平足迹半径 = 中心到最远顶点的 XY 距离 (比 bbox 对角紧, 仍保守)。"""
    cx, cy = center_xy(root)
    r = 0.0
    for ob in subtree_meshes(root):
        mw = ob.matrix_world
        for v in ob.data.vertices:
            p = mw @ v.co
            d = math.hypot(p.x - cx, p.y - cy)
            if d > r:
                r = d
    return r


def move_to(root, xy, ground=False):
    """按子树世界底面中心平移; glTF 用 matrix_world 烘焙过变换, location 语义不可靠。"""
    lo, hi = world_bbox(root)
    d = mu.Vector((xy[0] - (lo.x + hi.x) * 0.5,
                   xy[1] - (lo.y + hi.y) * 0.5,
                   -lo.z if ground else 0.0))
    root.matrix_world = mu.Matrix.Translation(d) @ root.matrix_world
    bpy.context.view_layer.update()
    return d


def project_uv(scene, pts):
    import bpy_extras
    cam = scene.camera
    return [bpy_extras.object_utils.world_to_camera_view(scene, cam, p) for p in pts]


def bbox_uv(scene, root):
    lo, hi = world_bbox(root)
    pts = [mu.Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y) for z in (lo.z, hi.z)]
    uv = project_uv(scene, pts)
    return (min(p.x for p in uv), max(p.x for p in uv),
            1.0 - max(p.y for p in uv), 1.0 - min(p.y for p in uv))


def bottom_front_anchor(roots, lo, hi):
    """真实前底缘锚点: 底部2%高度内 y 最小(最朝相机)的顶点。

    不能用 cy - r*k 推: r 是**外接圆半径**(纸盒58mm), 而盒体真实半深仅37.5mm
    → 会向相机多推约20mm, 采样落到接触阴影带之外的亮桌面上,
    产出"纸盒无接触阴影"的**测器伪影**(视觉取证: 阴影带确实存在, 在采样窗上方)。
    """
    zband = lo.z + max(0.0005, (hi.z - lo.z) * 0.02)
    best = None
    for ob in subtree_meshes(roots):
        mw = ob.matrix_world
        for v in ob.data.vertices:
            p = mw @ v.co
            if p.z <= zband and (best is None or p.y < best.y):
                best = p
    if best is None:
        raise SpecError("前底缘锚点为空(底部2%%带内无顶点)")
    return (best.x, best.y, best.z)


def measure(reg):
    """实测登记表: 每件(含 carry 从属件)的中心/足迹半径/高度/贴地/前底缘锚点。
    规格不写这些值 —— 手填测量值已被证明是错源(footprint_r 60mm vs 实测102.5mm)。"""
    out = {}
    for k, roots in reg.items():
        lo, hi = world_bbox(roots)
        cx, cy = center_xy(roots)
        ax, ay, az = bottom_front_anchor(roots, lo, hi)
        out[k] = {"root": roots[0].name, "n_mesh": len(subtree_meshes(roots)),
                  "cx": cx, "cy": cy, "r": footprint_r(roots),
                  "zmin": lo.z, "zmax": hi.z,
                  "anchor": [ax, ay, az],
                  # 真实世界bbox: 投影遮挡框必须用它, 不能用外接圆半径 r 当半extent
                  # (纸盒 r=58mm vs 真实半宽37.5mm → 框放大55%, 误挡合法桌面采样窗)
                  "bbox": [lo.x, lo.y, lo.z, hi.x, hi.y, hi.z]}
    return out


def apply_layout(scene, spec):
    """解析既有件 → 摆位(含 carry 同步) → 建道具。返回 {id: [root]}。"""
    reg = {}
    for item in spec["objects"]:
        obs = resolve(item["select"])
        if not obs:
            raise SpecError("[%s] 解析不到对象: %r" % (item["id"], item["select"]))
        main = obs[0]
        d = move_to(main, item["xy"], item.get("ground", False))
        # carry: 无父链的从属件必须同 delta 平移 (杯内奶/盘上可颂), 否则留在原位。
        # 登记进 reg 让**求解器也整组同步** —— 只移 roots[0] 会让该 bug 在求解阶段复发。
        carried = []
        for csel in item.get("carry", []):
            cos = resolve(csel)
            if not cos:
                raise SpecError("[%s] carry 解析不到: %r" % (item["id"], csel))
            for co in cos:
                co.matrix_world = mu.Matrix.Translation(d) @ co.matrix_world
            carried.extend(cos)
            print("[RT-CARRY] %s += %s" % (item["id"], [o.name for o in cos]))
        reg[item["id"]] = [main] + carried
    bpy.context.view_layer.update()

    props = spec.get("props", [])
    if props:
        import lifestyle_props
        for p in props:
            fn = getattr(lifestyle_props, p["fn"], None)
            if fn is None:
                raise SpecError("lifestyle_props 无函数 %s" % p["fn"])
            ob = fn(loc=(p["xy"][0], p["xy"][1], p.get("z", 0.0)),
                    name="LS_" + p["id"], **dict(p.get("args", {})))
            if ob is None:
                got = resolve({"name_prefix": "LS_" + p["id"]})
                if not got:
                    raise SpecError("[%s] 道具未创建" % p["id"])
                ob = got[0]
            reg[p["id"]] = [ob]
    bpy.context.view_layer.update()
    return reg


def geometry_gates(scene, spec, reg, meas):
    """渲染前几何闸: 穿模 / 入画 / 贴地。任一不过 raise, 不产废片。"""
    c = spec["constraints"]
    gap_min = c["min_gap_mm"] / 1000.0
    margin = c["frame_margin"]
    gtol = c["ground_tol_mm"] / 1000.0
    decl = {i["id"]: i for i in spec["objects"]}
    decl.update({p["id"]: p for p in spec.get("props", [])})
    # cloth(餐巾)是软底衬, 允许被碗压住 → 不参与碰撞
    ids = [k for k in reg if decl[k].get("role") != "cloth"]
    rows, fails = [], []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            ma, mb = meas[a], meas[b]
            gap = math.hypot(ma["cx"] - mb["cx"], ma["cy"] - mb["cy"]) - (ma["r"] + mb["r"])
            rows.append((a, b, gap))
            if gap < gap_min:
                fails.append("穿模 %s↔%s 间隙%.1fmm < %.1fmm" % (a, b, gap * 1000, gap_min * 1000))
    for k in ids:
        u0, u1, v0, v1 = bbox_uv(scene, reg[k])   # 整组(含carry从属件)
        if u0 < margin or u1 > 1 - margin:
            fails.append("出画(横) %s u=%.3f..%.3f" % (k, u0, u1))
        if v1 > 1 - margin or v0 < -0.05:
            fails.append("出画(纵) %s v=%.3f..%.3f" % (k, v0, v1))
        if decl[k].get("ground") and abs(meas[k]["zmin"]) > gtol:
            fails.append("未贴地 %s zmin=%.2fmm" % (k, meas[k]["zmin"] * 1000))
    worst = min(rows, key=lambda r: r[2]) if rows else None
    for k in sorted(meas):
        m = meas[k]
        print("[RT-MEAS] %-12s root=%-18s mesh=%2d r=%6.1fmm h=%5.1fmm zmin=%+6.2fmm"
              % (k, m["root"], m["n_mesh"], m["r"] * 1000,
                 (m["zmax"] - m["zmin"]) * 1000, m["zmin"] * 1000))
    print("[RT-GATE] 对数=%d 最小间隙=%s" %
          (len(rows), "%.1fmm(%s↔%s)" % (worst[2] * 1000, worst[0], worst[1]) if worst else "n/a"))
    for f in fails:
        print("[RT-GATE][FAIL]", f)
    if fails:
        raise SpecError("几何闸未过 (%d项), 拒绝渲染" % len(fails))
    return {"pairs": len(rows), "min_gap_mm": worst[2] * 1000 if worst else None,
            "measured": {k: {kk: (round(vv, 5) if isinstance(vv, float) else vv)
                             for kk, vv in m.items()} for k, m in meas.items()}}


def brand_box(scene, carton, face):
    """品牌ROI 从**正面印刷面顶点**投影, 落 sidecar。

    硬编码像素框会测错对象: 参照图(延世瓶位置不同)用暗调KV框测出 深色0/边缘0.352/蓝0。
    """
    ax, lim = face["local_axis"], face["local_max"]
    idx = {"x": 0, "y": 1, "z": 2}[ax]
    mw = carton.matrix_world
    front = [mw @ v.co for v in carton.data.vertices if v.co[idx] < lim]
    if len(front) < 3:
        raise SpecError("品牌正面顶点不足 n=%d (阈值 %s<%.4f)" % (len(front), ax, lim))
    uv = project_uv(scene, front)
    u0, u1 = min(p.x for p in uv), max(p.x for p in uv)
    v0, v1 = 1.0 - max(p.y for p in uv), 1.0 - min(p.y for p in uv)
    if not (u1 > u0 and v1 > v0):
        raise SpecError("品牌ROI退化")
    if u0 < -0.05 or u1 > 1.05:
        raise SpecError("品牌面出画 u=%.3f..%.3f" % (u0, u1))
    box = {"u0": u0, "v0": v0, "u1": u1, "v1": v1,
           "src": "scene-projection(front-face)", "n_pts": len(front)}
    side = os.path.splitext(scene.render.filepath)[0] + "_brandbox.json"
    with open(side, "w") as fh:
        json.dump(box, fh, indent=1)
    print("[RT-BRAND] u=%.3f..%.3f v=%.3f..%.3f n=%d → %s"
          % (u0, u1, v0, v1, len(front), os.path.basename(side)))
    return box


def regions_box(scene, spec, reg):
    """把**主体/远景道具/近景道具**的真实投影框落 sidecar, 供验收门用。

    为什么: 门禁原用固定分数窗口(如 h*0.10..0.42, w*0.58..)当"道具区",
    与道具真实位置无关 → 又一次"测器测错对象"(同品牌框硬编码之病)。
    """
    decl = {i["id"]: i for i in spec["objects"]}
    decl.update({p["id"]: p for p in spec.get("props", [])})
    groups = {"subject": [], "far_props": [], "near_props": []}
    for k in reg:
        role = decl[k].get("role", "")
        if role == "hero":
            groups["subject"].append(k)
        elif role == "prop_far":
            groups["far_props"].append(k)
        elif role in ("prop_near", "prop"):
            groups["near_props"].append(k)
    out = {}
    for g, ks in groups.items():
        if not ks:
            continue
        u0 = v0 = 1e9
        u1 = v1 = -1e9
        for k in ks:
            a, b, c, d = bbox_uv(scene, reg[k])
            u0, u1 = min(u0, a), max(u1, b)
            v0, v1 = min(v0, c), max(v1, d)
        out[g] = {"u0": max(0.0, u0), "u1": min(1.0, u1),
                  "v0": max(0.0, v0), "v1": min(1.0, v1), "ids": ks}
    fp = os.path.splitext(scene.render.filepath)[0] + "_regions.json"
    with open(fp, "w") as fh:
        json.dump(out, fh, indent=1)
    for g, b in out.items():
        print("[RT-REGION] %-10s u=%.3f..%.3f v=%.3f..%.3f ids=%s"
              % (g, b["u0"], b["u1"], b["v0"], b["v1"], b["ids"]))
    return out


def write_provenance(scene, spec, out_dir, gate_info, brand):
    """实拍状态回写 (不复制输入参数): 相机/曝光/灯具/画幅全部读回真实值。"""
    cam = scene.camera
    vs = scene.view_settings
    man = {
        "spec": os.path.basename(spec["_path"]),
        "spec_sha": spec["_sha"],
        "camera": {"loc": [round(v, 4) for v in cam.location],
                   "lens": cam.data.lens, "fstop": cam.data.dof.aperture_fstop,
                   "focus_distance": round(cam.data.dof.focus_distance, 4),
                   "dof": bool(cam.data.dof.use_dof)},
        "color": {"view_transform": vs.view_transform, "look": vs.look,
                  "exposure": vs.exposure, "gamma": vs.gamma},
        "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        "world_strength": bpy.data.worlds["Env"].node_tree.nodes["Background"].inputs["Strength"].default_value,
        "lights": {n: bpy.data.lights[n].energy for n in sorted(bpy.data.lights.keys())},
        "samples": scene.cycles.samples,
        "clamp_indirect": scene.cycles.sample_clamp_indirect,
        "geometry_gate": gate_info,
        "brand_box": brand,
    }
    fp = os.path.join(out_dir, "manifest_%s.json" % spec["name"])
    with open(fp, "w") as fh:
        json.dump(man, fh, indent=1)
    print("[RT-PROV] %s (lights=%d)" % (os.path.basename(fp), len(man["lights"])))
    return man


def _probe(scene, reg):
    """一次性实测: 中心/半径/半extent/zmin。之后求解全用解析式, 不再遍历顶点。

    必须这样: 在搜索循环里反复 world_bbox 会重算全体顶点 (carton 5970 + 道具数千)
    → O(N²) 卡死, 本仓已有该事故记录。
    """
    import bpy_extras
    cam = scene.camera
    mw = cam.matrix_world
    loc = mw.translation
    q = mw.to_quaternion()
    # zc 必须取相机 local **+Z**(后向): 分母用 (-Z), 前方点 Z<0 → -Z>0。
    # 取 -Z(前向) 会让 u 左右翻转, 求解器把道具往画外推 (自查修掉的符号bug)。
    zc = (q @ mu.Vector((0, 0, 1))).normalized()
    xc = (q @ mu.Vector((1, 0, 0))).normalized()
    yc = (q @ mu.Vector((0, 1, 0))).normalized()
    f = cam.data.lens / 1000.0
    sw = cam.data.sensor_width / 1000.0
    rx, ry = scene.render.resolution_x, scene.render.resolution_y
    ar = rx / ry

    def proj(p):
        d = p - loc
        Z = d.dot(zc)
        return ((d.dot(xc)) / (-Z) * f / sw + 0.5,
                0.5 - (d.dot(yc)) / (-Z) * f / sw * ar)

    # 自校验: 解析式 vs bpy_extras 官方投影 (符号/传感器/画幅任一错都会在此暴露)
    err = 0.0
    for probe in (mu.Vector((0.0, 0.0, 0.10)), mu.Vector((-0.20, 0.30, 0.05)),
                  mu.Vector((0.18, -0.05, 0.02))):
        u, v = proj(probe)
        ref = bpy_extras.object_utils.world_to_camera_view(scene, cam, probe)
        err = max(err, abs(u - ref.x), abs(v - (1.0 - ref.y)))
    print("[RT-PROJ] 解析↔官方投影最大偏差 %.6f (归一化)" % err)
    if err > 1e-4:
        raise SpecError("解析投影与官方不符 %.6f, 拒绝用于求解" % err)

    pr = {}
    for k, roots in reg.items():
        lo, hi = world_bbox(roots)
        cx, cy = (lo.x + hi.x) * 0.5, (lo.y + hi.y) * 0.5
        pr[k] = {"cx": cx, "cy": cy, "cz": (lo.z + hi.z) * 0.5,
                 "hx": (hi.x - lo.x) * 0.5, "hy": (hi.y - lo.y) * 0.5,
                 "hz": (hi.z - lo.z) * 0.5, "zmin": lo.z, "r": footprint_r(roots)}
    return pr, proj


def solve_layout(scene, spec, reg, max_iter=4000, seed=7):
    """约束求解摆位: 规格给**意图**(近似位置/角色), 求解器负责满足硬约束。

    为什么不手摆: 手填 footprint_r=0.060 而吐司双片实测 102.5mm → 手算"最小间隙19mm"
    是假数字, 几何闸实测 -23.3mm 穿模。数值必须来自实测, 位置必须由约束解出。

    硬约束: 两两足迹间隙 ≥ min_gap / 全部入画 / 贴地(由 ground 平移保证)
    软目标: 贴近规格意图位置 + 景深分层(prop_far 比 hero 远, prop_near 与 hero 同带)
    hero 固定(品牌构图锚), cloth 跟随其 follow 目标。
    """
    import random
    c = spec["constraints"]
    gap_min = c["min_gap_mm"] / 1000.0
    margin = c["frame_margin"]
    decl = {i["id"]: i for i in spec["objects"]}
    decl.update({p["id"]: p for p in spec.get("props", [])})
    pr, proj = _probe(scene, reg)
    ids = [k for k in reg if decl[k].get("role") != "cloth"]
    hero = next(k for k in ids if decl[k].get("role") == "hero")
    movable = [k for k in ids if k != hero]
    intent = {k: tuple(decl[k]["xy"]) for k in ids}
    pos = {k: (pr[k]["cx"], pr[k]["cy"]) for k in ids}

    def frame_ok(k, x, y):
        p = pr[k]
        dx, dy = x - p["cx"], y - p["cy"]
        us, vs = [], []
        for sx in (-1, 1):
            for sy in (-1, 1):
                for sz in (-1, 1):
                    u, v = proj(mu.Vector((p["cx"] + dx + sx * p["hx"],
                                           p["cy"] + dy + sy * p["hy"],
                                           p["cz"] + sz * p["hz"])))
                    us.append(u)
                    vs.append(v)
        return (min(us) >= margin and max(us) <= 1 - margin
                and max(vs) <= 1 - margin and min(vs) >= -0.05)

    def cost(pp):
        h = 0.0
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                gap = math.hypot(pp[a][0] - pp[b][0], pp[a][1] - pp[b][1]) - (pr[a]["r"] + pr[b]["r"])
                if gap < gap_min:
                    h += (gap_min - gap) * 1000.0
        for k in ids:
            if not frame_ok(k, pp[k][0], pp[k][1]):
                h += 50.0
        s = 0.0
        for k in movable:
            s += math.hypot(pp[k][0] - intent[k][0], pp[k][1] - intent[k][1])
        for k in movable:
            role = decl[k].get("role", "")
            if role == "prop_far" and pp[k][1] < pp[hero][1] + 0.06:
                s += 0.5 * (pp[hero][1] + 0.06 - pp[k][1])
            if role == "prop_near" and abs(pp[k][1] - pp[hero][1]) > 0.10:
                s += 0.2 * abs(pp[k][1] - pp[hero][1])
        return h * 100.0 + s

    rng = random.Random(seed)
    best, best_c = dict(pos), cost(pos)
    cur, cur_c = dict(best), best_c
    for it in range(max_iter):
        k = rng.choice(movable)
        step = 0.05 * (0.35 ** (it / max_iter * 3))
        cand = dict(cur)
        cand[k] = (cur[k][0] + rng.uniform(-step, step), cur[k][1] + rng.uniform(-step, step))
        cc = cost(cand)
        if cc <= cur_c:
            cur, cur_c = cand, cc
            if cc < best_c:
                best, best_c = dict(cand), cc
        if it % 800 == 799:
            cur, cur_c = dict(best), best_c
    # 应用解 (cloth 跟随 follow 目标, 保持相对偏移)
    deltas = {}
    for k in ids:
        dx, dy = best[k][0] - pr[k]["cx"], best[k][1] - pr[k]["cy"]
        deltas[k] = (dx, dy)
    for k in reg:
        d = decl[k]
        if d.get("role") == "cloth":
            tgt = d.get("follow")
            if tgt not in deltas:
                raise SpecError("[%s] cloth.follow 指向未知件 %r" % (k, tgt))
            dx, dy = deltas[tgt]
        else:
            dx, dy = deltas[k]
        if abs(dx) > 1e-9 or abs(dy) > 1e-9:
            T = mu.Matrix.Translation(mu.Vector((dx, dy, 0)))
            for ob in reg[k]:          # 整组同步: root + carry 从属件
                ob.matrix_world = T @ ob.matrix_world
    bpy.context.view_layer.update()
    moved = {k: (round(v[0] * 1000, 1), round(v[1] * 1000, 1)) for k, v in deltas.items()
             if abs(v[0]) > 1e-6 or abs(v[1]) > 1e-6}
    print("[RT-SOLVE] iter=%d cost=%.3f 位移(mm)=%s" % (max_iter, best_c, moved))
    # 自校验: 解析预测 vs 实测 (防解析式与真实几何脱节)
    meas = measure(reg)
    worst = 0.0
    for k in ids:
        ex, ey = best[k]
        worst = max(worst, abs(meas[k]["cx"] - ex), abs(meas[k]["cy"] - ey))
    print("[RT-SOLVE] 解析↔实测最大偏差 %.4fmm" % (worst * 1000))
    if worst > 0.0005:
        raise SpecError("求解器解析预测与实测不符 %.4fmm" % (worst * 1000))
    return meas