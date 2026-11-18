"""v100 ControlNet tile img2img: 业界标准"增强照片感保结构/文字".
原理: 在我方单张渲染上 img2img (低denoise 0.35) + ControlNet tile 锁结构.
  → 模型原生保留文字/几何, 只补摄影质感. 无第二张图, 无合成错位.
依赖: diffusers, torch MPS, SD1.5 + control_v11f1e_sd15_tile (huggingface.co).
"""
import os, sys, time
import torch
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
INPUT = os.path.join(ROOT, "output/commercial/repro_pour_1l_kv.png")
OUT = os.path.join(ROOT, "output/commercial/repro_pour_1l_cn.png")
STRENGTH = float(os.environ.get("CN_STRENGTH", "0.35"))
CN_SCALE = float(os.environ.get("CN_SCALE", "0.8"))
RES = int(os.environ.get("CN_RES", "1024"))
SEED = int(os.environ.get("CN_SEED", "42"))

device = "mps" if torch.backends.mps.is_available() else "cpu"
dtype = torch.float32   # MPS fp16 VAE decode溢出NaN→黑图(实测), SD1.5须fp32
print(f"device={device} dtype={dtype} strength={STRENGTH} cn_scale={CN_SCALE} res={RES}")

t0 = time.time()
print("loading SD1.5 base...")
from diffusers import StableDiffusionControlNetImg2ImgPipeline, ControlNetModel, UniPCMultistepScheduler

controlnet = ControlNetModel.from_pretrained(
    "lllyasviel/control_v11f1e_sd15_tile", torch_dtype=dtype)
print(f"  controlnet loaded ({time.time()-t0:.0f}s)")

pipe = StableDiffusionControlNetImg2ImgPipeline.from_pretrained(
    "stable-diffusion-v1-5/stable-diffusion-v1-5",
    controlnet=controlnet, torch_dtype=dtype, safety_checker=None)
pipe.scheduler = UniPCMultistepScheduler.from_config(pipe.scheduler.config)
pipe = pipe.to(device)
pipe.enable_attention_slicing()
print(f"  pipeline ready ({time.time()-t0:.0f}s)")

# 输入图
img = Image.open(INPUT).convert("RGB").resize((RES, RES), Image.LANCZOS)
print(f"input: {img.size}")

prompt = (
    "commercial studio photography, professional product shot, "
    "Retail 1L milk carton pouring milk into glass cup, "
    "croissant on plate, warm wooden table, morning side-backlight, "
    "photorealistic paper texture, sharp print text, Canon EOS R5, "
    "85mm f/2.8, studio softbox lighting, 8k uhd"
)
negative = (
    "cartoon, illustration, painting, drawing, anime, 3d render, CGI, "
    "plastic, blurry text, distorted text, watermark, low quality"
)

generator = torch.Generator(device=device).manual_seed(SEED)
print("generating...")
result = pipe(
    prompt=prompt,
    negative_prompt=negative,
    image=img,
    control_image=img,
    strength=STRENGTH,
    controlnet_conditioning_scale=CN_SCALE,
    num_inference_steps=30,
    guidance_scale=7.5,
    generator=generator,
).images[0]
print(f"  done ({time.time()-t0:.0f}s total)")

result.save(OUT)
# 也存1920版 (upscale back)
result.resize((1920, 1920), Image.LANCZOS).save(OUT.replace(".png", "_1920.png"))
print(f"saved {OUT}")

# 文字保真对账: 与原图文字区高频相关
orig = np.asarray(img).astype(float)
res = np.asarray(result).astype(float)
from PIL import ImageFilter
def hf(a, r=3):
    low = np.asarray(Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))).astype(float)
    return a - low
oh, rh = hf(orig), hf(res)
# 文字区 (纸盒正面)
y0, y1, x0, x1 = int(RES*0.15), int(RES*0.55), int(RES*0.25), int(RES*0.72)
corr = np.corrcoef(oh[y0:y1, x0:x1].ravel(), rh[y0:y1, x0:x1].ravel())[0, 1]
sad = np.abs(oh[y0:y1, x0:x1] - rh[y0:y1, x0:x1]).mean()
print(f"文字区高频相关={corr:.3f} (越接近1=字形越保真) SAD={sad:.1f}")