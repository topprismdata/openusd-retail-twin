#!/usr/bin/env python3
"""18_post_grade.py — 实拍色对齐后处理 (R72, 系统Python环境; Blender内numpy会产生黑块伪影故隔离)

模式A reinhard: 标准 LAB 统计色迁移 (Reinhard et al. 2001) — 渲染主体区 LAB mean/std
       对表实拍主体区, blend 控制强度。教科书标准解, 零手调曲线。
模式B families: 分族 HSV 校正 (R61-71 数学, 已离线验证无黑块)。

用法: python3 18_post_grade.py [--src path] [--out path]   # 默认读写 spec 驱动的 match 输出
"""
import cv2, json, os, sys
import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = json.load(open(os.path.join(REPO, 'specs', 'pack_458.json')))
pg = spec['match_view'].get('post_grade') or {}
src = os.path.join(REPO, 'output/pack_qa/pinmu_458/hero_match_real.png')
ref = '/tmp/blind_X.jpg'
out = src
for i, a in enumerate(sys.argv):
    if a == '--src': src = sys.argv[i+1]
    if a == '--out': out = sys.argv[i+1]
    if a == '--ref': ref = sys.argv[i+1]
# R75: 裸位置参数=src — 曾因位置参数被静默忽略而三轮"离线验证"实际反复grade已损文件
if len(sys.argv) > 1 and not sys.argv[1].startswith('-'):
    src = sys.argv[1]
    out = out if '--out' in sys.argv else src

img = cv2.imread(src)
ref_im = cv2.imread(ref)
mode = pg.get('mode', 'reinhard')

if mode == 'reinhard':
    # 主体区 = 非背景(<235灰) — LAB mean/std 对表, blend 混合
    blend = pg.get('blend', 0.85)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref_lab = cv2.cvtColor(ref_im, cv2.COLOR_BGR2LAB).astype(np.float32)
    m_in = img.max(-1) < 235
    m_ref = ref_im.max(-1) < 235
    # 阈值放宽到 200 提高主体纯度(白底贡献会稀释统计)
    m_in = img.max(-1) < 200
    m_ref = ref_im.max(-1) < 200
    for ch in range(3):
        a = lab[..., ch][m_in]; b = ref_lab[..., ch][m_ref]
        mu_a, sd_a = a.mean(), a.std() + 1e-6
        mu_b, sd_b = b.mean(), b.std() + 1e-6
        shifted = (lab[..., ch] - mu_a) * (sd_b / sd_a) + mu_b
        lab[..., ch] = (1 - blend) * lab[..., ch] + blend * shifted
    out_im = np.clip(lab, 0, 255).astype(np.uint8)
    out_im = cv2.cvtColor(out_im, cv2.COLOR_LAB2BGR)
    cv2.imwrite(out, out_im)
    print(f"[GRADE] reinhard blend={blend} 写 {out}")

elif mode == 'families':
    from PIL import Image, ImageFilter
    arr = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32)
    for fam in (pg.get('families') or []):
        lo, hi = fam['hue']
        mx = arr.max(-1); mn = arr.min(-1); c = np.maximum(mx-mn, 1e-6)
        r, g, b = arr[...,0], arr[...,1], arr[...,2]
        h = np.zeros_like(mx); nz = c > 1e-6
        mrr = nz&(mx==r); mgr = nz&(mx==g)&~mrr; mbb = nz&~mrr&~mgr
        h[mrr] = (60*((g[mrr]-b[mrr])/c[mrr])%360)/2
        h[mgr] = (60*((b[mgr]-r[mgr])/c[mgr]+2))/2
        h[mbb] = (60*((r[mbb]-g[mbb])/c[mbb]+4))/2
        s = np.where(nz, c/np.maximum(mx,1e-6)*255, 0)
        s_lo = fam.get('s_lo', 60)
        m_s = (s > s_lo) if 's_hi' not in fam else (s > s_lo) & (s <= fam['s_hi'])
        fmk = ((h>=lo)&(h<=hi)&m_s).astype(np.uint8)*255
        # R73: 腐蚀5再羽化 — 羽化掩膜渗到字形边界的低色度像素会被旋转出彩色噪点
        fmk = cv2.erode(fmk, np.ones((5, 5), np.uint8))
        # R75: blur 6→2.5 — σ6羽化渗~12px, 字形边界又拿到0.3-0.5权重
        wgt = np.asarray(Image.fromarray(fmk).filter(ImageFilter.GaussianBlur(2.5)), dtype=np.float32)/255.0
        if fam.get('s',1.0)!=1.0:
            f = 1+(fam['s']-1)*wgt; mx3 = arr.max(-1,keepdims=True)
            arr = mx3 - f[...,None]*(mx3-arr)
        if fam.get('v',1.0)!=1.0:
            arr = arr*(1+(fam['v']-1)*wgt[...,None])
        # R76h: 白区白平衡 — photo白B/G=0.947偏暖, 渲染中性
        rg, bg = fam.get('r_gain',1.0), fam.get('b_gain',1.0)
        if rg!=1.0 or bg!=1.0:
            arr = arr*np.stack([np.full_like(wgt,rg), np.ones_like(wgt), np.full_like(wgt,bg)],-1)*(wgt[...,None]) + arr*(1-wgt[...,None])
        vg = fam.get('v_gamma',1.0)
        if vg!=1.0:
            v0 = arr.max(-1); k = ((v0/255.0)**vg*255.0)/np.maximum(v0,1e-3)
            arr = arr*(1+(k-1)*wgt)[...,None]
        if fam.get('dH',0.0):
            mxh = arr.max(-1); mnh = arr.min(-1); ch = np.maximum(mxh-mnh,1e-6)
            rh,gh,bh = arr[...,0],arr[...,1],arr[...,2]
            hdeg = np.zeros_like(mxh)
            m1 = mxh==rh; m2 = (mxh==gh)&~m1; m3 = ~m1&~m2
            hdeg[m1] = (60*((gh[m1]-bh[m1])/ch[m1])%360)
            hdeg[m2] = 60*((bh[m2]-rh[m2])/ch[m2]+2)
            hdeg[m3] = 60*((rh[m3]-gh[m3])/ch[m3]+4)
            hdeg = (hdeg + fam['dH']*2*wgt)%360
            seg = np.floor(hdeg/60)%6; ffn = hdeg/60-seg
            pq = ch*(1-ffn); tq = ch*ffn
            # R75: 重建表必须加回值域地板 mnh — 纯色相表把近中性像素的 V 地板剥掉,
            # 暖白(235,233,230)会被重建成(235,3,230)纯品红(实测G通道崩15)
            r2 = np.select([seg==0,seg==1,seg==2,seg==3,seg==4,seg==5],[mxh,pq,mnh,mnh,tq,mxh])
            g2 = np.select([seg==0,seg==1,seg==2,seg==3,seg==4,seg==5],[tq,mxh,mxh,pq,mnh,mnh])
            b2 = np.select([seg==0,seg==1,seg==2,seg==3,seg==4,seg==5],[mnh,mnh,tq,mxh,mxh,pq])
            # R75b: 偏移逐扇区正解 — 色度条目(pq/tq)共6处需+mnh: r@seg1,4; g@seg0,3; b@seg2,5
            # seg3漏加曾把蓝像素G塌到pq→紫罗兰镶边(R74真根因); 统一+mnh则蓝段V虚高
            off_r = np.select([seg==0,seg==1,seg==2,seg==3,seg==4,seg==5],[0,mnh,0,0,mnh,0])
            off_g = np.select([seg==0,seg==1,seg==2,seg==3,seg==4,seg==5],[mnh,0,0,mnh,0,0])
            off_b = np.select([seg==0,seg==1,seg==2,seg==3,seg==4,seg==5],[0,0,mnh,0,0,mnh])
            rot = np.stack([r2+off_r, g2+off_g, b2+off_b], -1)
            valid = (wgt>0.003)&(ch>8)
            arr = np.where(valid[...,None], rot, arr)
    cv2.imwrite(out, cv2.cvtColor(np.clip(arr,0,255).astype(np.uint8), cv2.COLOR_RGB2BGR))
    print(f"[GRADE] families x{len(pg.get('families') or [])} 写 {out}")
