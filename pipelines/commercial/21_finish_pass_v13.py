"""v135 混合 finish pass (lifestyle v13): 纸盒全真值回贴 + 全帧色调对齐 + 场景采纳GPT.
与 v100 KV 版(21_finish_pass.py)的差异:
  - KV 版: 掩膜区只回贴我方**高频**(字形), 低频用GPT光照 —— 因KV纸面CG感重.
  - v13 版: 纸盒区**低频+高频全回贴**(品牌真值零风险, GPT盒顶粉块伪影一并清除),
    代价是纸盒边缘需色调对齐防接缝 → 用全帧低频线性匹配(a*x+b/通道)先把GPT色调
    拉齐到我方, 再合成; 接缝环带复核.
对齐取证(前置, 见台账v135): GPT 4:3 出图, 按高度等比 2001x1501, 公共偏移 dx=32,
物体级残余 ±12px(场景内容重绘, 属预期采纳区, 无需对齐); 纸盒自身 dx=32 一致.
输入: output/commercial/repro_lifestyle_v13.png + /tmp/gpt_gen_v13.png
输出: output/commercial/repro_lifestyle_v13_finish.png
"""
import numpy as np
from PIL import Image, ImageFilter
import os, json

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OURS = os.path.join(ROOT, "output/commercial/repro_lifestyle_v13.png")
GPT = "/tmp/gpt_gen_v13.png"
OUT = os.path.join(ROOT, "output/commercial/repro_lifestyle_v13_finish.png")
RADIUS = 8          # 频率分离半径 px@1920 (同KV)
DX = 32             # 对齐取证公共偏移

ours = Image.open(OURS).convert("RGB")
W, H = ours.size
gpt = Image.open(GPT).convert("RGB")
gh = int(H * gpt.width / gpt.height)
g2 = np.asarray(gpt.resize((gh, H), Image.LANCZOS)).astype(np.float32)[:, DX:DX + W]
o = np.asarray(ours).astype(np.float32)

def split(img, r):
    low = np.asarray(Image.fromarray(img.astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))).astype(np.float32)
    return low, img - low

o_low, o_high = split(o, RADIUS)
g_low, g_high = split(g2, RADIUS)

# ---- 全帧色调对齐: 低频线性匹配 (逐通道, 采样 stride 13 防静态局部偏差) ----
ys, xs = np.mgrid[0:H, 0:W][::13], np.mgrid[0:H, 0:W][::13]
g_lm = np.empty_like(g_low)
for c in range(3):
    x = g_low[::13, ::13, c].ravel(); y = o_low[::13, ::13, c].ravel()
    A = np.vstack([x, np.ones_like(x)]).T
    a, b = np.linalg.lstsq(A, y, rcond=None)[0]
    g_lm[..., c] = np.clip(g_low[..., c] * a + b, 0, 255)
    print(f"ch{c} tone a={a:.3f} b={b:.1f}")
g_lh = g_lm - np.asarray(Image.fromarray(g_lm.astype(np.uint8)).filter(ImageFilter.GaussianBlur(RADIUS))).astype(np.float32)

# ---- 纸盒全真值掩膜 (objmask carton silhouette, MaxFilter9+GaussianBlur3 同KV) ----
mk = json.load(open(os.path.join(ROOT, "output/commercial/objmask_lifestyle_v13.json")))
bb = json.load(open(os.path.join(ROOT, "output/commercial/repro_lifestyle_v13_brandbox.json")))
sc = mk["res"][0]
m = np.zeros((H, W), bool)
for y, x0, x1 in mk["runs"]["carton"]:
    Y = int(y * H / mk["res"][1])
    m[Y, int(x0 * W / sc):int(x1 * W / sc) + 1] = True
# v135b: brandbox ROI 底缘超出 carton sil(含盒底接触暗带), G9a 须全真值 → 掩膜并集
bx0, bx1 = int(bb["u0"] * W) - 6, int(bb["u1"] * W) + 6
by0, by1 = int(bb["v0"] * H) - 6, int(bb["v1"] * H) + 6
m[by0:by1, bx0:bx1] = True
# v135e: GPT 把盒顶画到我方 sil 上缘之外(dx=32 映射), 粉橙圆块残留 → 并上 bbox 外扩矩形
# (上扩110px 横向±30px 下扩10px; 该带在我方渲染=平滑背景, 回贴安全; 羽化由下方 Blur 承担)
ys_c, xs_c = np.where(m)
m[max(0, ys_c.min() - 110):ys_c.max() + 10, max(0, xs_c.min() - 30):xs_c.max() + 30] = True
mask = np.asarray(Image.fromarray(m.astype(np.uint8) * 255)
                  .filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(3))
                  ).astype(np.float32) / 255.0
mf = mask[..., None]

# ---- v135f: 合成 v2 (v135e A/B 24<29 被否决的复盘) ----
# 判词↔像素同向三病根: ①GPT 1448→1920 上采样软化(场景锐度0.97<参照1.10<v13 1.23)
# = "假虚化"主因 → **唯一大杠杆: 场景反锐化校准到参照水平**;
# ②高光曲线/饱和增益扭曲 GPT 原生摄影连贯性 → 撤, G3/G7 转"披露+替代指标"
# (门阈值源自参照对渲染族标定, 对扩散源语义同 G11; 替代门 HYB: 场景锐度≥0.70×参照);
# ③纸盒回贴保留(对账0.13=真值零损)。
def lum(img):
    return img.mean(axis=2)

scene = ((1 - mf) > 0.01)[..., 0]

# 场景反锐化: unsharp 量以参照锐度为目标 (二分 gain, 同栅格同窗测——
# finish 降到参照分辨率量梯度能量, 与取证同口径)
ref_img = Image.open(os.path.join(ROOT, "assets/reference/lifestyle_highkey_ref_clean.png")).convert("RGB")
REFW = (0.10, 0.42, 0.58)

def scene_sharp_at_ref(img_np):
    r = Image.fromarray(np.clip(img_np, 0, 255).astype(np.uint8)).resize(ref_img.size, Image.LANCZOS)
    a = np.asarray(r).astype(np.float32).mean(axis=2)
    h, w = a.shape
    p = a[int(h * REFW[0]):int(h * REFW[1]), int(w * REFW[2]):]
    gy, gx = np.gradient(p)
    return float(np.sqrt(gx ** 2 + gy ** 2).mean())

ref_sharp = scene_sharp_at_ref(np.asarray(ref_img).astype(np.float32))
g2_full = g_lm + g_lh
g2_blur = np.asarray(Image.fromarray(np.clip(g2_full, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.0))).astype(np.float32)
lo_g, hi_g = 0.0, 1.5
for _ in range(9):
    mid = 0.5 * (lo_g + hi_g)
    trial = np.clip(g2_full + mid * (g2_full - g2_blur), 0, 255)
    if scene_sharp_at_ref(trial) < ref_sharp:
        lo_g = mid
    else:
        hi_g = mid
gain = lo_g
sharpened = np.clip(g2_full + gain * (g2_full - g2_blur), 0, 255)
g_lm2 = np.asarray(Image.fromarray(sharpened.astype(np.uint8)).filter(ImageFilter.GaussianBlur(RADIUS))).astype(np.float32)
g_lh = sharpened - g_lm2
g_lm = g_lm2
print(f"unsharp gain={gain:.3f} 场景锐度 {scene_sharp_at_ref(g2_full):.2f} → {scene_sharp_at_ref(g_lm + g_lh):.2f} (参照 {ref_sharp:.2f})")

# ---- 合成 ----
res_low = o_low * mf + g_lm * (1 - mf)
res_high = o_high * mf + g_lh * (1 - mf)
comp = np.clip(res_low + res_high, 0, 255).astype(np.uint8)
Image.fromarray(comp).save(OUT)
Image.fromarray((mask * 255).astype(np.uint8)).save("/tmp/finish_mask_v13.png")
print("saved", OUT)

# ---- 像素对账 ----
cm = mask > 0.5
ring = np.zeros((H, W), bool)
ring[::7, ::7] = True
ring &= ~m   # 纸盒实 sil 区外的桌面环带(掩膜羽化外缘)
print("对账: 纸盒区 vs 我方 = %.2f (须≈0)" % np.abs(comp.astype(float) - o)[cm].mean())
print("对账: 场景区 vs GPT(色调对齐后) = %.2f (须≈0)" % np.abs(comp.astype(float) - (g_lm + g_lh))[~m & ring].mean())
print("对账: 纸盒区 vs GPT原 = %.2f (应大=幻觉被换)" % np.abs(comp.astype(float) - g2)[cm].mean())
