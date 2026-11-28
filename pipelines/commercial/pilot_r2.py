#!/usr/bin/env python3
"""P1-B R2 结构化AI: ControlNet-tile img2img (MPS), keras桩屏蔽TF互操作崩溃。
基图=官方Artwork(§3相同Artwork口径); 种子=torch.Generator(11/22/33)。
用法: python3 pilot_r2.py S1 11  (scene∈{S1,S2}, seed∈{11,22,33})
"""
import json
import os
import sys
import time

sys.modules["keras"] = None          # autogluon拖入的keras3在TF互操作处原生崩(diffusers探测即跳过)
sys.modules["tensorflow"] = None

import torch
from PIL import Image
from diffusers import StableDiffusionControlNetPipeline, ControlNetModel

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pipelines.common.runtime_env import torch_device, torch_generator  # noqa: E402

BASE = "assets/reference/milk_1l"
PROMPTS = {
 "S1": "commercial e-commerce product photograph of a retail pure milk 1L tetra brick carton, " 
       "gable top with blue cap, blue and white packaging with Chinese print, "
       "single carton centered front view, pure white seamless background, no shadow, "
       "studio packshot lighting, sharp print, high quality",
 "S2": "bright high-key breakfast scene photograph, retail milk brick carton on light wooden table, "
       "oat bowl with strawberries, glass of milk, toast, soft window light, shallow depth of field, "
       "commercial food advertising photography, high quality",
}
NEG = "text artifacts, garbled characters, deformed geometry, extra limbs, low quality, blurry, watermark"


def main():
    scene, seed = sys.argv[1], int(sys.argv[2])
    t0 = time.time()
    if scene == "S1":
        base = Image.open(f"{BASE}/detail1.jpg").convert("RGB")
    else:
        base = Image.open(f"{BASE}/carton1l_main.jpg").convert("RGB")
    w, h = base.size
    scale = 768 / max(w, h)
    base = base.resize((int(w * scale) // 8 * 8, int(h * scale) // 8 * 8), Image.LANCZOS)

    # 设备: CUDA (NVIDIA) > MPS (Apple Silicon) > CPU; MPS 的 fp16 VAE 解码会出 NaN 黑图, 故 MPS 走 fp32
    device = torch_device()
    dtype = torch.float32 if device == "mps" else torch.float16

    # RV5.1下载卡死(网络) → 回退本仓已缓存完整SD1.5(4.0G, 离线local_files_only)
    cn = ControlNetModel.from_pretrained(
        "lllyasviel/control_v11f1e_sd15_tile", torch_dtype=dtype,
        local_files_only=True)
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        "stable-diffusion-v1-5/stable-diffusion-v1-5",
        controlnet=cn, torch_dtype=dtype, safety_checker=None,
        local_files_only=True)
    pipe.to(device)
    pipe.set_progress_bar_config(disable=True)
    g = torch_generator(device, seed)
    img = pipe(PROMPTS[scene], base, num_inference_steps=28,
               controlnet_conditioning_scale=0.55, strength=0.62,
               guidance_scale=7.0, negative_prompt=NEG, generator=g).images[0]
    out = f"output/pilot_p1b/R2_{scene}_r{seed}.png"
    img.save(out)
    mani = {
        "route": "R2结构化AI", "scene": "S1_packshot" if scene == "S1" else "S2_lifestyle",
        "repeat": str(seed),
        "tool": "ControlNet-tile img2img (lllyasviel/control_v11f1e_sd15_tile + SD1.5, MPS fp16)",
        "base_image": f"{BASE}/" + ("detail1.jpg" if scene == "S1" else "carton1l_main.jpg"),
        "structure_constraint": {"type": "tile", "conditioning_scale": 0.55, "strength": 0.62},
        "seed": seed, "steps": 28, "guidance": 7.0,
        "gen_seconds": round(time.time() - t0), "output": out,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    json.dump(mani, open(out.replace(".png", "_manifest.json"), "w"), ensure_ascii=False, indent=1)
    print("R2", scene, "r" + str(seed), "→", out, mani["gen_seconds"], "s")


if __name__ == "__main__":
    main()
