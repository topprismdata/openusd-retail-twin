#!/usr/bin/env python3
"""19_lightfield_audit.py — 光场一致性审计 (框架仪器, spec 声明目标)

把 photo/render 的蓝面板四边形透视规整到规范坐标系, 量:
  光斑位置(0-1), 面板L分位(p10/p50/p90/p99), 亮度梯度dx/dy, L场Pearson, 白区色温
对照 spec.match_view.rig_match.targets 容差判 PASS/FAIL。审计退出码≠0 即不达标。

用法: python3 19_lightfield_audit.py --photo /tmp/blind_X.jpg \
      --render output/pack_qa/pinmu_458/hero_match_real.png [--json-out xxx.json]
"""
import argparse, json, os, sys
import numpy as np
import cv2

def panel_canonical(img, W=400, Hc=700):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H_, S_ = hsv[...,0].astype(int), hsv[...,1].astype(int)
    m = cv2.morphologyEx(((H_>=100)&(H_<=135)&(S_>60)).astype(np.uint8),
                         cv2.MORPH_CLOSE, np.ones((35,35),np.uint8))
    m = cv2.erode(m, np.ones((9,9),np.uint8))
    ys, xs = np.where(m>0)
    pts = np.column_stack([xs, ys]).astype(np.float32)
    src = np.array([pts[np.argmin(pts[:,0])], pts[np.argmin(pts[:,1])],
                    pts[np.argmax(pts[:,0])], pts[np.argmax(pts[:,1])]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(src, np.array([[0,0],[W,0],[W,Hc],[0,Hc]], dtype=np.float32))
    warp = cv2.warpPerspective(img, M, (W, Hc))
    return cv2.cvtColor(warp, cv2.COLOR_BGR2LAB)[...,0].astype(float), warp.astype(np.float32)

def lightfield(img):
    # R76c: 全部指标在原始坐标+蓝掩膜总体(与 rig_match 声明目标同口径) — warp 只用于可视化
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H_, S_ = hsv[...,0].astype(int), hsv[...,1].astype(int)
    # R76f: 与色对齐V仪器同口径(hue100-135 S>60, erode15, 无close) — close(35)会把白波浪
    # 蓝白边缘并进总体, photo p90=198实为波浪边像素, 面板光场必须纯面板蓝
    m = ((H_>=100)&(H_<=135)&(S_>60)).astype(np.uint8)
    m = cv2.erode(m, np.ones((15,15),np.uint8))
    L = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[...,0].astype(np.float32)
    Lm = np.where(m>0, L, 0)
    k = np.ones((61,61))/61
    Ls = np.where(m>0, cv2.filter2D(Lm, -1, k), 0)
    iy, ix = np.unravel_index(np.argmax(Ls), Ls.shape)
    gy, gx = np.gradient(Ls)
    ys, xs = np.where(m>0)
    y0,y1 = np.percentile(ys,[2,98]); x0,x1 = np.percentile(xs,[2,98])
    wm = (hsv[...,1].astype(int)<30)&(hsv[...,2].astype(int)>180)
    w = img[wm]
    wb = (float(w[:,0].mean()/w[:,1].mean()), float(w[:,2].mean()/w[:,1].mean())) if len(w)>500 else (None, None)
    return {
        "spot": [round((ix-x0)/max(x1-x0,1),2), round((iy-y0)/max(y1-y0,1),2)],
        "L_p10_p50_p90_p99": [round(float(np.percentile(L[m>0],p))) for p in (10,50,90,99)],
        "grad": [round(float(np.mean(gx[m>0])),1), round(float(np.mean(gy[m>0])),1)],
        "white_BG_RG": [round(wb[0],3) if wb[0] else None, round(wb[1],3) if wb[1] else None],
    }

ap = argparse.ArgumentParser()
ap.add_argument('--photo', default='/tmp/blind_X.jpg')
ap.add_argument('--render', default='output/pack_qa/pinmu_458/hero_match_real.png')
ap.add_argument('--spec', default='specs/pack_458.json')
ap.add_argument('--json-out', default=None)
a = ap.parse_args()

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = json.load(open(a.spec if os.path.isabs(a.spec) else os.path.join(REPO, a.spec)))
tg = (spec['match_view'].get('rig_match') or {}).get('targets')

ph_r = lightfield(cv2.imread(a.photo))
rd_r = lightfield(cv2.imread(a.render))
pear = float(np.corrcoef(np.load('/tmp/Lp_canon.npy').ravel(), np.load('/tmp/Lr_canon.npy').ravel())[0,1]) if os.path.exists('/tmp/Lp_canon.npy') else None
rd_r['pearson_photo'] = round(pear,3) if pear is not None else None

verdict, fails = "PASS", []
if tg:
    tol = (spec['match_view'].get('rig_match') or {}).get('tol', {})
    ts, tol_s = tol.get('spot', 0.18), tol.get('spot', 0.18)
    d_spot = max(abs(x-y) for x,y in zip(ph_r['spot'], rd_r['spot']))
    (verdict, fails) = (verdict, fails) if d_spot <= ts else (verdict, fails+["spot Δ%.2f>%.2f" % (d_spot, ts)])
    tl = tol.get('L', 18)
    for i,(x,y) in enumerate(zip(ph_r['L_p10_p50_p90_p99'][:3], rd_r['L_p10_p50_p90_p99'][:3])):
        if abs(x-y) > tl: fails.append("L%d Δ%d>%d" % (i, abs(x-y), tl))
    tg2 = tol.get('grad', 4)
    for i,(x,y) in enumerate(zip(ph_r['grad'], rd_r['grad'])):
        if abs(x-y) > tg2: fails.append("grad%d Δ%.1f>%.1f" % (i, abs(x-y), tg2))
    tw = tol.get('white', 0.045)
    for i,(x,y) in enumerate(zip(ph_r['white_BG_RG'], rd_r['white_BG_RG'])):
        if x and y and abs(x-y) > tw: fails.append("wb%d Δ%.3f>%.3f" % (i, abs(x-y), tw))
    verdict = "FAIL" if fails else "PASS"
else:
    verdict = "NOTARGETS"

out = {"photo": ph_r, "render": rd_r, "verdict": verdict, "fails": fails,
       "targets": tg}
# GPT主管评测用: 叠图差可视化(亮度场伪彩+差热图)
lp_canon, _ = panel_canonical(cv2.imread(a.photo))
lr_canon, _ = panel_canonical(cv2.imread(a.render))
la = cv2.normalize(lp_canon, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
lb = cv2.normalize(lr_canon, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
heat = cv2.applyColorMap(np.abs(la.astype(int)-lb.astype(int)).astype(np.uint8), cv2.COLORMAP_JET)
pair = np.hstack([cv2.applyColorMap(la, cv2.COLORMAP_INFERNO),
                  np.full((la.shape[0],6,3),255,np.uint8),
                  cv2.applyColorMap(lb, cv2.COLORMAP_INFERNO),
                  np.full((la.shape[0],6,3),255,np.uint8), heat])
cv2.imwrite('/tmp/lightfield_audit_maps.png', pair)
out["maps"] = "/tmp/lightfield_audit_maps.png"
print(json.dumps(out, ensure_ascii=False, indent=1))
if a.json_out:
    jp = a.json_out if os.path.isabs(a.json_out) else os.path.join(REPO, a.json_out)
    json.dump(out, open(jp,'w'), ensure_ascii=False, indent=1)
sys.exit(0 if verdict in ("PASS","NOTARGETS") else 2)
