#!/usr/bin/env python3
# 图像对比标准框架 v2 (用户实战协议落地): SIFT配准 → 重叠掩码 → SSIM/PSNR/LabΔE/HSV分区/直方图 (+LPIPS/CLIP辅助)
# 基准原则: 刀版/设计稿色值 > 实拍色值(实拍=真值×光照×白平衡); 渲染验收=中性照度下albedo≈刀版色; 全区域掩码统计, 禁单点
# 用法: python3 img_compare_v2.py REF.jpg TEST.jpg [--label 参考 待测] [--json-out out.json]
import sys, argparse, json
import numpy as np
import cv2

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ref"); ap.add_argument("test")
    ap.add_argument("--label", nargs=2, default=["参考", "待测"])
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    ref = cv2.imread(args.ref); tes = cv2.imread(args.test)
    assert ref is not None and tes is not None, "图像读取失败"
    out = {"pair": f"{args.label[0]} vs {args.label[1]}"}

    # ---------- 一、空间配准 (SIFT+RANSAC) ----------
    g1 = cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY)
    g2 = cv2.cvtColor(tes, cv2.COLOR_BGR2GRAY)
    sift = cv2.SIFT_create(nfeatures=4000)
    k1, d1 = sift.detectAndCompute(g1, None)
    k2, d2 = sift.detectAndCompute(g2, None)
    bf = cv2.BFMatcher()
    raw = bf.knnMatch(d2, d1, k=2)          # 待测→参考
    good = [m for m, n in raw if m.distance < 0.75 * n.distance]
    out["good_matches"] = len(good)
    H = None; inliers = 0
    if len(good) >= 4:
        src_pts = np.float32([k2[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32([k1[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 4.0)
        inliers = int(mask.sum()) if mask is not None else 0
    out["inliers"] = inliers
    reg_ok = len(good) >= 12 and inliers >= 10 and H is not None
    out["registration_ok"] = bool(reg_ok)
    if not reg_ok:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("✗ 配准未过线 (好匹配≥12 且内点≥10), 指标全废 — 请先保证同机位/可配准视角")
        sys.exit(2)
    h, w = g1.shape
    warped = cv2.warpPerspective(tes, H, (w, h))

    # ---------- 三、重叠掩码: 双方非背景(<235灰)交集 → 腐蚀9px+15px ----------
    m_ref = (cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY) < 235).astype(np.uint8)
    m_tes = (cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY) < 235).astype(np.uint8)
    ov = (m_ref & m_tes)
    ov = cv2.erode(ov, np.ones((9, 9), np.uint8))
    ov = cv2.erode(ov, np.ones((15, 15), np.uint8))
    if ov.sum() < 300:
        print("✗ 重叠掩码<300px, 指标不可信"); sys.exit(2)
    out["overlap_px"] = int(ov.sum())

    # ---------- 二、指标层 (重叠区内) ----------
    from skimage.metrics import structural_similarity as ssim_fn
    wref = ref.copy(); wtes = warped.copy()
    m3 = ov.astype(bool)
    la = cv2.cvtColor(wref, cv2.COLOR_BGR2GRAY).astype(np.float32)
    lb = cv2.cvtColor(wtes, cv2.COLOR_BGR2GRAY).astype(np.float32)
    # SSIM 全图(窗口统计), 但只报告重叠区均值
    ssim_map = ssim_fn(la, lb, data_range=255, full=True)[1]
    out["ssim_overlap"] = float(ssim_map[m3].mean())
    psnr = cv2.PSNR(wref, wtes)
    out["psnr"] = float(psnr)
    # Lab ΔE
    labA = cv2.cvtColor(wref, cv2.COLOR_BGR2Lab).astype(np.float32)
    labB = cv2.cvtColor(wtes, cv2.COLOR_BGR2Lab).astype(np.float32)
    dE = np.sqrt(((labA - labB) ** 2).sum(-1))
    dEov = dE[m3]
    out["dE_mean"] = float(dEov.mean())
    out["dE_p50"] = float(np.percentile(dEov, 50))
    out["dE_p95"] = float(np.percentile(dEov, 95))
    # HSV 分区 S/V 迁移 (S>60 下限防灰白污染; 白区单独)
    hsvA = cv2.cvtColor(wref, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsvB = cv2.cvtColor(wtes, cv2.COLOR_BGR2HSV).astype(np.float32)
    zones = {"蓝": (100, 135), "黄": (18, 40)}
    for zn, (h0, h1) in zones.items():
        mzA = (m3 & (hsvA[..., 0] >= h0) & (hsvA[..., 0] <= h1) & (hsvA[..., 1] > 60))
        mzB = (m3 & (hsvB[..., 0] >= h0) & (hsvB[..., 0] <= h1) & (hsvB[..., 1] > 60))
        ent = {"ref_px": int(mzA.sum()), "test_px": int(mzB.sum())}
        if mzA.sum() >= 300:
            ent["ref_S"] = float(hsvA[..., 1][mzA].mean()); ent["ref_V"] = float(hsvA[..., 2][mzA].mean())
        if mzB.sum() >= 300:
            ent["test_S"] = float(hsvB[..., 1][mzB].mean()); ent["test_V"] = float(hsvB[..., 2][mzB].mean())
        out[zn] = ent
    mredA = (m3 & ((hsvA[..., 0] < 8) | (hsvA[..., 0] > 172)) & (hsvA[..., 1] > 60))
    mredB = (m3 & ((hsvB[..., 0] < 8) | (hsvB[..., 0] > 172)) & (hsvB[..., 1] > 60))
    red = {"ref_px": int(mredA.sum()), "test_px": int(mredB.sum())}
    if mredA.sum() >= 300:
        red["ref_S"] = float(hsvA[..., 1][mredA].mean()); red["ref_V"] = float(hsvA[..., 2][mredA].mean())
        red["ref_BGR"] = [float(x) for x in wref[mredA].mean(0)[::-1]]
    if mredB.sum() >= 300:
        red["test_S"] = float(hsvB[..., 1][mredB].mean()); red["test_V"] = float(hsvB[..., 2][mredB].mean())
        red["test_BGR"] = [float(x) for x in wtes[mredB].mean(0)[::-1]]
    out["红"] = red
    mwhA = (m3 & (hsvA[..., 1] < 40) & (hsvA[..., 2] > 150))
    mwhB = (m3 & (hsvB[..., 1] < 40) & (hsvB[..., 2] > 150))
    wht = {"ref_px": int(mwhA.sum()), "test_px": int(mwhB.sum())}
    if mwhA.sum() >= 300:
        wht["ref_V"] = float(hsvA[..., 2][mwhA].mean())
    if mwhB.sum() >= 300:
        wht["test_V"] = float(hsvB[..., 2][mwhB].mean())
    out["白"] = wht
    # 直方图相关 (配准后有效)
    hc = []
    for i in range(3):
        ha = cv2.calcHist([wref], [i], ov.astype(np.uint8) * 255, [64], [0, 256])
        hb = cv2.calcHist([wtes], [i], ov.astype(np.uint8) * 255, [64], [0, 256])
        hc.append(float(cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL)))
    out["hist_corr_BGR"] = hc

    print("== 标准对比 v2:", out["pair"])
    print("配准: 好匹配=%d 内点=%d → %s | 重叠=%dpx" % (out["good_matches"], inliers, "PASS" if reg_ok else "FAIL", out["overlap_px"]))
    print("SSIM(重叠)=%.4f (>0.6中等/>0.8高) | PSNR=%.1f" % (out["ssim_overlap"], out["psnr"]))
    print("Lab ΔE mean=%.1f p50=%.1f p95=%.1f (<2无感/2-10可感/10-49明显)" % (out["dE_mean"], out["dE_p50"], out["dE_p95"]))
    for zn in ("蓝", "红", "黄", "白"):
        z = out[zn]
        s = "%s: ref_px=%d test_px=%d" % (zn, z.get("ref_px", 0), z.get("test_px", 0))
        if "ref_S" in z: s += " | ref S=%.0f V=%.0f" % (z["ref_S"], z["ref_V"])
        if "test_S" in z: s += " | test S=%.0f V=%.0f" % (z["test_S"], z["test_V"])
        if "ref_BGR" in z: s += " | ref BGR=%s" % [round(x) for x in z["ref_BGR"]]
        if "test_BGR" in z: s += " | test BGR=%s" % [round(x) for x in z["test_BGR"]]
        ok = (z.get("ref_px", 0) >= 300 and z.get("test_px", 0) >= 300)
        print(s + ("" if ok else "  [样本<300 不可信]"))
    print("直方图相关 BGR =", [round(x, 3) for x in hc])
    if args.json_out:
        json.dump(out, open(args.json_out, "w"), ensure_ascii=False, indent=1)
        print("JSON →", args.json_out)

if __name__ == "__main__":
    main()
