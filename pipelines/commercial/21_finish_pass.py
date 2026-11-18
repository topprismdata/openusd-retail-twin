"""v100 混合 finish pass v2: 频率分离 Detail Transfer (成熟修图技法).
v1 错误: 掩膜区贴回我方原始CG像素 → 与GPT摄影纸面质感断层(贴图感).
v2 原理 (Photoshop frequency separation / ComfyUI DetailTransfer):
  low = Gaussian(img, r)   # 低频: 光照/色彩/大面
  high = img - low         # 高频: 细节/文字边缘/纸纹
  result_low = GPT_low     # 全图用GPT摄影光照
  result_high = our_high*mask + GPT_high*(1-mask)  # 文字区用我方正确字形, 其余GPT纸纹
  result = result_low + result_high
  → 文字区: GPT光照(低频) + 我方字形(高频) = 融合且字正确; 纸面: 全GPT.
输入: repro_pour_1l_kv.png (我方) + /tmp/gpt_gen_1l.png (GPT)
输出: repro_pour_1l_finish.png
"""
import numpy as np
from PIL import Image, ImageFilter
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
OURS = os.path.join(ROOT, "output/commercial/repro_pour_1l_kv.png")
GPT = "/tmp/gpt_gen_1l.png"
OUT = os.path.join(ROOT, "output/commercial/repro_pour_1l_finish.png")
RADIUS = int(os.environ.get("FS_RADIUS", "8"))   # 频率分离半径 (px@1920)

ours = Image.open(OURS).convert("RGB")
OW, OH = ours.size
gpt = Image.open(GPT).convert("RGB").resize((OW, OH))
o = np.asarray(ours).astype(float)
g = np.asarray(gpt).astype(float)

def split(img, r):
    low = np.asarray(Image.fromarray(img.astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))).astype(float)
    high = img - low
    return low, high

o_low, o_high = split(o, RADIUS)
g_low, g_high = split(g, RADIUS)

# ---- 文字掩膜: 我方印刷区 (蓝/红墨 + 我方高频显著=文字边缘), 限纸盒zone ----
R, G, B = o[..., 0], o[..., 1], o[..., 2]
blue = (B > R + 20) & (B > G + 10) & (B > 70)
red = (R > G + 30) & (R > B + 20) & (R > 90)
hf_mag = np.abs(o_high).mean(axis=2)
yy, xx = np.mgrid[0:OH, 0:OW]
carton_zone = (yy < int(0.56 * OH)) & (xx > int(0.24 * OW)) & (xx < int(0.73 * OW))
ink = ((blue | red) | (hf_mag > 12)) & carton_zone
mimg = Image.fromarray((ink.astype(np.uint8) * 255)).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(2))
mask = np.asarray(mimg).astype(float) / 255.0
print(f"RADIUS={RADIUS} ink mask px={int(ink.sum())} zone%={round(ink.mean()*100,2)}")

# ---- 频率重组 ----
mf = mask[..., None]
res_low = g_low                                  # 全图GPT光照
res_high = o_high * mf + g_high * (1 - mf)       # 文字区我方字形, 其余GPT纸纹
comp = np.clip(res_low + res_high, 0, 255).astype(np.uint8)
Image.fromarray(comp).save(OUT)
print("saved", OUT)

# ---- 对账 ----
ink_m = mask > 0.5
# 文字区低频应≈GPT(光照融合), 高频应≈我方(字形)
cl, ch = split(comp.astype(float), RADIUS)
print(f"文字区 低频vs GPT={np.abs(cl-g_low)[ink_m].mean():.1f}(应小=光照融合) 高频vs我方={np.abs(ch-o_high)[ink_m].mean():.1f}(应小=字形保真)")
print(f"非文字区 vs GPT={np.abs(comp.astype(float)-g)[~ink_m].mean():.1f}(应≈0)")
Image.fromarray((mask * 255).astype(np.uint8)).save("/tmp/finish_mask.png")