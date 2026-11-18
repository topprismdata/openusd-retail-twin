#!/usr/bin/env python3
"""20_perspective_audit.py — 透视一致性审计 (框架仪器, spec 声明目标)

量两图的盒体透视指标:
  左/右竖棱倾角(度, 相对竖直, 外八为正), 竖棱收敛角(左右棱夹角), 顶/底宽度比(顶部收缩率)
对照 spec.match_view.persp_match.targets 判 PASS/FAIL。透视=相机距离×焦距的可测结果。

用法: python3 20_perspective_audit.py --photo /tmp/blind_X.jpg \
      --render output/pack_qa/pinmu_458/hero_match_real.png [--json-out xxx.json]
"""
import argparse, json, os, sys
import numpy as np
import cv2

def edges_metrics(img):
    """蓝面板竖棱倾角+宽度比(原始坐标; 两图同口径, 壁面直段40-90%高度带)"""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H_, S_ = hsv[...,0].astype(int), hsv[...,1].astype(int)
    m = ((H_ >= 100) & (H_ <= 135) & (S_ > 60)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    ys, xs = np.where(m > 0)
    y0, y1 = np.percentile(ys, [2, 98]).astype(int)
    # 壁面直段: 蓝掩膜高度40-90% (波峰/坡面过渡避开)
    r_top, r_bot = int(y0 + (y1 - y0) * 0.60), int(y0 + (y1 - y0) * 0.88)  # R78: 波峰以下纯壁面段
    lx, rx, rr = [], [], []
    for r_ in range(r_top, r_bot, 3):
        row = np.where(m[r_] > 0)[0]
        if len(row) > 10:
            lx.append(row[0]); rx.append(row[-1]); rr.append(r_)
    lx, rx, rr = np.array(lx), np.array(rx), np.array(rr)
    if len(rr) < 20: return None
    kl = np.polyfit(rr, lx, 1)
    kr = np.polyfit(rr, rx, 1)
    angL = np.degrees(np.arctan(kl[0]))
    angR = np.degrees(np.arctan(kr[0]))
    wt, wb = [], []
    for r_ in range(r_top, r_top + (r_bot - r_top) // 5):
        row = np.where(m[r_] > 0)[0]
        if len(row) > 10: wt.append(row[-1] - row[0])
    for r_ in range(r_bot - (r_bot - r_top) // 5, r_bot):
        row = np.where(m[r_] > 0)[0]
        if len(row) > 10: wb.append(row[-1] - row[0])
    return {
        "edgeL_deg": round(float(angL), 2),
        "edgeR_deg": round(float(angR), 2),
        "converge_deg": round(float(abs(angL - angR)), 2),
        "top_bottom_w": round(float(np.median(wt) / max(np.median(wb), 1)), 3),
        "band_px": int(rr[-1] - rr[0]),
    }

ap = argparse.ArgumentParser()
ap.add_argument('--photo', default='/tmp/blind_X.jpg')
ap.add_argument('--render', default='output/pack_qa/pinmu_458/hero_match_real.png')
ap.add_argument('--spec', default='specs/pack_458.json')
ap.add_argument('--json-out', default=None)
a = ap.parse_args()

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = json.load(open(a.spec if os.path.isabs(a.spec) else os.path.join(REPO, a.spec)))
pm = spec['match_view'].get('persp_match') or {}
tg, tol = pm.get('targets'), pm.get('tol', {})

ph = edges_metrics(cv2.imread(a.photo))
rd = edges_metrics(cv2.imread(a.render))
fails = []
verdict = "NOTARGETS"
if tg:
    for key, t in tol.items() if isinstance(tol, dict) else []:
        pass
    t_ = tol
    for key in ("edgeL_deg", "edgeR_deg", "converge_deg", "top_bottom_w"):
        if key in tg and ph.get(key) is not None and rd.get(key) is not None:
            d = abs(ph[key] - rd[key]); tt = t_.get(key, t_.get(key.replace('_deg', ''), 99))
            if d > tt: fails.append("%s Δ%.2f>%.2f (photo %.2f render %.2f)" % (key, d, tt, ph[key], rd[key]))
    verdict = "FAIL" if fails else "PASS"

out = {"photo": ph, "render": rd, "verdict": verdict, "fails": fails, "targets": tg}
print(json.dumps(out, ensure_ascii=False, indent=1))
if a.json_out:
    jp = a.json_out if os.path.isabs(a.json_out) else os.path.join(REPO, a.json_out)
    json.dump(out, open(jp, 'w'), ensure_ascii=False, indent=1)
sys.exit(0 if verdict in ("PASS", "NOTARGETS") else 2)
