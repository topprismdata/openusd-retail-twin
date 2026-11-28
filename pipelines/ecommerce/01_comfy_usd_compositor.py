#!/usr/bin/env python3
"""
01 - 多平台电商展示图矩阵 + IBL 光影提取物理合成引擎 (Mac Metal-RT)

相对 Gemini 原稿的工程修正 (见 README「对 Gemini 设计的修正」):
  - 盒体真实尺寸 48x44x136mm, origin 底面中心 (原稿尺寸减半且离地悬浮 34mm)
  - 每面显式 UV 映射到贴图 atlas 对应区域 (原稿 Cube 无 UV, 贴图必然采样失败)
  - use_persistent_data=False (原稿开启后逐张 hide_render 切换会吃到陈旧可见性)
  - ComfyUI 为可选 hook (环境变量 COMFYUI_URL), 默认纯程序化背景, 100% 离线可跑

运行:
  /Applications/Blender.app/Contents/MacOS/Blender -b -P 01_comfy_usd_compositor.py -- \
      --sku demo_organic --scene grassland
"""
import os
import sys
import math
import argparse
import urllib.request
import numpy as np
from PIL import Image
import bpy
from mathutils import Matrix, Vector

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE_DIR)
from pipelines.common.runtime_env import configure_cycles  # noqa: E402

import importlib.util as _ilu_boot
_boot_spec = _ilu_boot.spec_from_file_location("retail_boot", os.path.join(BASE_DIR, "pipelines/bootstrap/00_bootstrap_textures.py"))
_boot = _ilu_boot.module_from_spec(_boot_spec)
_boot_spec.loader.exec_module(_boot)
SKU_PROFILES = _boot.SKU_PROFILES
TEX_DIR = os.path.join(BASE_DIR, "assets", "textures")
BG_DIR = os.path.join(BASE_DIR, "assets", "backgrounds")
OUT_DIR = os.path.join(BASE_DIR, "output", "multi_platform")
USD_DIR = os.path.join(BASE_DIR, "output", "ar_models")
for d in (TEX_DIR, BG_DIR, OUT_DIR, USD_DIR):
    os.makedirs(d, exist_ok=True)

# 盒体真实物理尺寸 (米) — 经典 250ml 利乐钻
PACK_W, PACK_D, PACK_H = 0.048, 0.038, 0.113   # 250ml 参照比例 (参照照实测 H:W 2.43-2.64, 旧 1L 母本 3.0 偏高 19%)

# ---- UV atlas 契约 (与 00 脚本一致, 归一化 v=y-up) ----
UV_REGIONS = {
    "FRONT":  (60 / 2048, 1 - 1944 / 2048, 940 / 2048, 1 - 104 / 2048),   # u0,v0,u1,v1
    "BACK":   (1112 / 2048, 1 - 1944 / 2048, 1992 / 2048, 1 - 104 / 2048),
    "SIDE_L": (972 / 2048, 1 - 1944 / 2048, 1010 / 2048, 1 - 104 / 2048),
    "SIDE_R": (1042 / 2048, 1 - 1944 / 2048, 1080 / 2048, 1 - 104 / 2048),
    "TOP":    (60 / 2048, 1 - 72 / 2048, 940 / 2048, 1 - 8 / 2048),
    "BOTTOM": (1112 / 2048, 1 - 72 / 2048, 1992 / 2048, 1 - 8 / 2048),
}


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--sku", default="demo_organic")
    p.add_argument("--scene", default="grassland", choices=["grassland", "woodtable", "emerald_kv", "lowcarbon_city", "demo_yogurt_combo"])
    p.add_argument("--export-glb", default=None)
    p.add_argument("--only", default="", help="仅渲染指定平台, 逗号分隔 (换标秒级出图用)")
    return p.parse_args(argv)


# ---------------------------------------------------------------- 背景与 IBL
def get_or_generate_background(scene_type, width=1600, height=1600):
    """可选 ComfyUI hook (COMFYUI_URL, 未实现即回退), 默认程序化生成高质感背景底图"""
    bg_path = os.path.join(BG_DIR, f"bg_{scene_type}_{width}x{height}.png")
    if os.path.exists(bg_path):
        return bg_path

    comfy = os.environ.get("COMFYUI_URL", "").rstrip("/")
    if comfy:
        try:
            urllib.request.urlopen(f"{comfy}/system_stats", timeout=2)
            print("[ComfyUI] 服务在线 — 当前版本以程序化背景为准 (txt2img hook 见 README 扩展位)")
        except Exception:
            print("[ComfyUI] 不可达 — 使用程序化背景")

    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    nx, ny = x / width, y / height

    if scene_type == "grassland":
        # 呼伦贝尔草原清晨: 左上晨曦暖阳, 下半翠绿牧草
        sun = np.sqrt((nx - 0.22) ** 2 + (ny - 0.18) ** 2)
        sky = np.clip(1.0 - ny * 1.65, 0, 1)
        r = sky * (255 * np.exp(-sun * 2.5) + 135 * (1 - np.exp(-sun * 2.5))) + (1 - sky) * (38 + 45 * np.sin(nx * 6))
        g = sky * (240 * np.exp(-sun * 2.0) + 195 * (1 - np.exp(-sun * 2.0))) + (1 - sky) * (115 + 35 * np.cos(ny * 8))
        b = sky * (190 * np.exp(-sun * 3.0) + 235 * (1 - np.exp(-sun * 3.0))) + (1 - sky) * (42 + 20 * np.sin(nx * 4))
    elif scene_type == "emerald_kv":
        # 天猫 KV 翡翠绿幕: 中心径向翠绿渐变 + 底部金色辉光 (对照官方 KV 版式)
        d = np.sqrt((nx - 0.5) ** 2 + ((ny - 0.42) * 1.15) ** 2)
        glow = np.exp(-d * 3.4)
        gold = np.exp(-(((nx - 0.5) * 2.4) ** 2 + ((ny - 0.88) * 3.2) ** 2)) * 0.6
        r = 12 + 42 * glow + 215 * gold
        g = 62 + 96 * glow + 168 * gold
        b = 38 + 54 * glow + 66 * gold
    else:
        # 阳光原木早餐桌: 右上暖阳百叶窗光斑
        sun = np.sqrt((nx - 0.78) ** 2 + (ny - 0.22) ** 2)
        table = np.clip((ny - 0.55) * 3.0, 0, 1)
        gobo = 0.85 + 0.15 * np.sin((nx * 12 + ny * 8) * np.pi)
        r = (1 - table) * (245 * np.exp(-sun * 2.2) + 180) * gobo + table * 168 * gobo
        g = (1 - table) * (215 * np.exp(-sun * 2.5) + 155) * gobo + table * 122 * gobo
        b = (1 - table) * (165 * np.exp(-sun * 3.0) + 125) * gobo + table * 82 * gobo

    rgb = np.stack([np.clip(r, 0, 255), np.clip(g, 0, 255), np.clip(b, 0, 255)], axis=-1).astype(np.uint8)
    img = Image.fromarray(rgb).filter(__import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(radius=6))
    img.save(bg_path)
    print(f"[BG] 程序化背景已生成: {bg_path}")
    return bg_path


def extract_ibl_lighting_from_bg(bg_path):
    """背景图亮度前 5% 像素质心 -> 主光源方位/颜色; 下 1/4 均色 -> 地面反弹色"""
    img = Image.open(bg_path).convert("RGB").resize((256, 256))
    arr = np.asarray(img, dtype=np.float32) / 255.0
    luma = 0.2126 * arr[:, :, 0] + 0.7152 * arr[:, :, 1] + 0.0722 * arr[:, :, 2]

    thresh = np.percentile(luma, 95)
    by, bx = np.where(luma >= thresh)
    nx = (np.mean(bx) / 256.0) - 0.5
    ny = 0.5 - (np.mean(by) / 256.0)

    light_x = nx * 1.2
    light_y = -0.45
    light_z = max(0.22, 0.35 + ny * 0.5)

    sun_rgb = np.mean(arr[luma >= thresh], axis=0).tolist()
    ground_rgb = np.mean(arr[180:, :, :], axis=(0, 1)).tolist()
    return {
        "light_pos": (light_x, light_y, light_z),
        "sun_color": (sun_rgb[0], sun_rgb[1], sun_rgb[2], 1.0),
        "ground_color": (ground_rgb[0], ground_rgb[1], ground_rgb[2], 1.0),
    }


# ---------------------------------------------------------------- Blender 场景
def setup_metal_engine(samples=96):
    """渲染引擎初始化。

    历史名 setup_metal_engine 保留以兼容既有调用点; 实际后端由
    runtime_env.configure_cycles 自动选择 (macOS=METAL, Win/Linux=OPTIX/CUDA/HIP/ONEAPI,
    无 GPU 时回落 CPU)。可用 CYCLES_DEVICE / FORCE_CPU_RENDER 覆盖。
    """
    scene = bpy.context.scene
    configure_cycles(scene=scene, samples=samples, denoise=True)
    # 产品摄影: Standard 视图变换保住品牌饱和色 (AgX 会把深绿洗成灰绿)
    scene.view_settings.view_transform = "Standard"
    # 注意: 逐张切换 hide_render 时不能开 persistent_data (陈旧可见性 bug)
    scene.render.use_persistent_data = False


def assign_box_uv(obj, w, d, h):
    """按 UV_REGIONS 契约为盒体 6 面显式赋 UV (origin=底面中心)。
    注意: Blender 5.x primitive cube 自带默认 'UVMap' 层, 必须写入第 0 层
    (active_render), 新建第二层不会被 Image Texture 采样。"""
    mesh = obj.data
    uvl = mesh.uv_layers[0] if len(mesh.uv_layers) else mesh.uv_layers.new(name="atlas")
    for poly in mesh.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 1:                      # ±Y -> FRONT(-Y) / BACK(+Y)
            region = UV_REGIONS["FRONT"] if n.y < 0 else UV_REGIONS["BACK"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vz = mesh.vertices[vi].co.x, mesh.vertices[vi].co.z
                uvl.data[li].uv = (
                    region[0] + (vx / w + 0.5) * (region[2] - region[0]),
                    region[1] + (vz / h) * (region[3] - region[1]),
                )
        elif ax == 0:                    # ±X -> 侧条
            region = UV_REGIONS["SIDE_L"] if n.x < 0 else UV_REGIONS["SIDE_R"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vz = mesh.vertices[vi].co.z
                vy = mesh.vertices[vi].co.y
                uvl.data[li].uv = (
                    region[0] + (vy / d + 0.5) * (region[2] - region[0]),
                    region[1] + (vz / h) * (region[3] - region[1]),
                )
        else:                            # ±Z -> TOP(+Z) / BOTTOM(-Z)
            region = UV_REGIONS["TOP"] if n.z > 0 else UV_REGIONS["BOTTOM"]
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vy = mesh.vertices[vi].co.x, mesh.vertices[vi].co.y
                uvl.data[li].uv = (
                    region[0] + (vx / w + 0.5) * (region[2] - region[0]),
                    region[1] + (vy / d + 0.5) * (region[3] - region[1]),
                )


def get_pil_font(size):
    """PIL 文案层字体 (macOS 中文字体链)"""
    from PIL import ImageFont
    for _pth in ["/System/Library/Fonts/PingFang.ttc",
                 "/System/Library/Fonts/STHeiti Medium.ttc",
                 "/System/Library/Fonts/Hiragino Sans GB.ttc"]:
        if os.path.exists(_pth):
            return ImageFont.truetype(_pth, size)
    return ImageFont.load_default()


def build_yogurt_combo(sku):
    """main_02 靶 v2: 对角双组 (右上/左下), 每组 = 横版礼盒 + 斜靠 205g 砖 x2"""
    import math as _m
    def _group(gx, gy, gsku, grot, lean_dir):
        build_carton_twin("demo_yogurt_gift", loc=(gx, gy, 0),
                        rot=(0, 0, _m.radians(grot)), dims=(YOG_GW, YOG_GD, YOG_GH),
                        cap=False, bevel=0.0035, front_region=GIFT_FRONT_UV)
        bx = gx + lean_dir * (YOG_GW / 2 + YOG_BW * 0.48)
        build_carton_twin(gsku, loc=(bx, gy + 0.008, 0),
                        rot=(_m.radians(-4), 0, _m.radians(grot - lean_dir * 24)), dims=(YOG_BW, YOG_BD, YOG_BH),
                        cap=True, bevel=0.0018)
        build_carton_twin(gsku, loc=(bx + lean_dir * (YOG_BW * 0.92), gy - 0.014, 0),
                        rot=(_m.radians(-6), 0, _m.radians(grot - lean_dir * 34)), dims=(YOG_BW, YOG_BD, YOG_BH),
                        cap=True, bevel=0.0018)
    _group(0.122, 0.130, "demo_yogurt_gold", -10, +1)     # 右上组: 金装砖 (v40 基线)
    _group(-0.084, -0.104, sku, -8, +1)              # 左下组: 原味砖 (v40 基线)
    fl_ = bpy.data.objects.get("Plane")
    if fl_:
        fl_.scale = (3.2, 3.2, 1.0)
    aim_o = bpy.context.scene.objects.get("Aim")
    if aim_o:
        aim_o.location.x = 0.0
    print("[AMX] main_02 v2 场景已构建 (对角双组: 礼盒+斜靠砖)")


def build_lowcarbon_city():
    """低碳 KV 微缩绿城: 绿墙+"10"厚字+草地实例+微缩楼群+树 (对照官方 KV 版式)"""
    import random
    random.seed(7)

    def mat(base, rough=0.7):
        m = bpy.data.materials.new("KV_" + str(abs(hash(base)) % 9999))
        m.use_nodes = True
        b = m.node_tree.nodes.get("Principled BSDF")
        b.inputs["Base Color"].default_value = (*base, 1.0)
        b.inputs["Roughness"].default_value = rough
        return m

    # 地面 (草地基底)
    bpy.ops.mesh.primitive_plane_add(size=2.4, location=(0, 0.3, 0))
    g = bpy.context.active_object; g.name = "KV_Ground"
    gmat = bpy.data.materials.new("KV_GrassCarpet")
    gmat.use_nodes = True
    gb_ = gmat.node_tree.nodes.get("Principled BSDF")
    gb_.inputs["Roughness"].default_value = 0.9
    gwave = gmat.node_tree.nodes.new("ShaderNodeTexNoise")
    gwave.inputs["Scale"].default_value = 130.0
    gwave.inputs["Detail"].default_value = 6.0
    gwave.inputs["Roughness"].default_value = 0.6
    gramp = gmat.node_tree.nodes.new("ShaderNodeValToRGB")
    gramp.color_ramp.elements[0].color = (0.055, 0.135, 0.082, 1.0)
    gramp.color_ramp.elements[1].color = (0.105, 0.245, 0.142, 1.0)
    gmat.node_tree.links.new(gwave.outputs["Color"], gramp.inputs["Fac"])
    gmat.node_tree.links.new(gramp.outputs["Color"], gb_.inputs["Base Color"])
    g.data.materials.append(gmat)

    # 绿墙 (背景)
    bpy.ops.mesh.primitive_plane_add(size=3.2, location=(0, 1.05, 0.45), rotation=(math.radians(90), 0, 0))
    w = bpy.context.active_object; w.name = "KV_Wall"
    w.data.materials.append(mat((0.04, 0.13, 0.075), 0.9))

    # "10" 厚体数字 (低碳主题)
    bpy.ops.object.text_add(location=(-0.15, 0.72, 0.15), rotation=(math.radians(90), 0, math.radians(-8)))
    t = bpy.context.active_object; t.name = "KV_Num"
    t.data.body = "10"
    t.data.size = 0.375
    t.data.extrude = 0.05
    t.data.align_x = "CENTER"
    t.data.materials.append(mat((0.17, 0.50, 0.29), 0.6))

    # 草叶实例 (单叶网格 linked data, ~2400 株环带分布)
    mesh = bpy.data.meshes.new("Blade")
    verts = [(-0.0045, 0, 0), (0.0045, 0, 0), (0.0028, 0, 0.02), (0.0, 0, 0.036)]
    faces = [(0, 1, 2), (2, 1, 3)]
    mesh.from_pydata(verts, [], faces)
    gmats = [mat((0.06, 0.18, 0.10), 0.85), mat((0.08, 0.22, 0.12), 0.85), mat((0.05, 0.15, 0.085), 0.85)]
    blades = []
    for i in range(5000):
        r = random.uniform(0.155, 0.46)
        a = random.uniform(0, math.pi * 2)
        x, y = math.cos(a) * r, math.sin(a) * r * 0.85 + 0.06
        near = y < -0.12  # 镜头最近带: 密矮草, 靠虚化成植被面
        ob = bpy.data.objects.new(f"Grass_{i}", mesh)
        ob.location = (x, y, 0)
        ob.rotation_euler = (random.uniform(-0.55, 0.55), random.uniform(-0.55, 0.55), random.uniform(0, 6.28))
        sc = random.uniform(0.6, 1.5)
        ob.scale = (sc * (1.4 if near else 1.0), sc, random.uniform(0.16, 0.30) if near else random.uniform(0.30, 0.62))
        ob.data.materials.append(gmats[i % 3])
        bpy.context.collection.objects.link(ob)
        blades.append(ob)

    # 微缩楼群 (右侧, 程序化窗格)
    wm = bpy.data.materials.new("KV_Tower")
    wm.use_nodes = True
    nt = wm.node_tree
    b = nt.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = (0.10, 0.30, 0.19, 1.0)
    b.inputs["Roughness"].default_value = 0.85
    wave = nt.nodes.new("ShaderNodeTexWave")
    wave.inputs["Scale"].default_value = 26.0
    wave.inputs["Distortion"].default_value = 1.2
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (0.10, 0.30, 0.19, 1.0)
    ramp.color_ramp.elements[1].color = (0.28, 0.38, 0.32, 1.0)
    nt.links.new(wave.outputs["Color"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    for ti, (tx, ty, th, tw, rot, dy) in enumerate([(0.185, 0.24, 0.22, 0.044, -3, -0.02), (0.25, 0.32, 0.325, 0.052, -1, 0.01),
                            (0.15, 0.42, 0.175, 0.040, 2, 0.03), (0.29, 0.20, 0.19, 0.044, 4, -0.01)]):
        bpy.ops.mesh.primitive_cube_add(location=(tx, ty + dy, th / 2))
        tw_ = bpy.context.active_object; tw_.name = f"KV_Tower_{tx}"
        tw_.scale = (tw, tw, 1)
        tw_.dimensions = (tw, tw, th)
        bev2 = tw_.modifiers.new("EdgeSoft", "BEVEL")
        bev2.width = 0.006
        bev2.segments = 3
        tw_.rotation_euler = (0, 0, math.radians(rot))
        tw_.data.materials.append(wm)
    # 天际线剪影加倒角
    for ob in bpy.data.objects:
        if ob.name.startswith("KV_Sky_"):
            bvs = ob.modifiers.new("EdgeSoft", "BEVEL")
            bvs.width = 0.005
            bvs.segments = 2

    # 左前景近景楼体 (大虚化前景层, 构图左缘)
    bpy.ops.mesh.primitive_cube_add(location=(-0.40, 0.02, 0.14))
    ftower = bpy.context.active_object; ftower.name = "KV_FGTower_L"
    ftower.dimensions = (0.14, 0.10, 0.30)
    ftower.data.materials.append(wm)
    # 中后景天际线剪影 (一排高楼)
    for sx, sy, sh in [(-0.30, 0.78, 0.31), (-0.16, 0.82, 0.19), (0.02, 0.86, 0.23),
                        (0.14, 0.80, 0.185), (-0.05, 0.92, 0.26)]:
        bpy.ops.mesh.primitive_cube_add(location=(sx, sy, sh / 2))
        sk = bpy.context.active_object; sk.name = f"KV_Sky_{sx}"
        sk.dimensions = (0.08, 0.064, sh)
        sk.data.materials.append(mat((0.14, 0.33, 0.20), 0.9))
    # 背景大绿形体 (官方的弧形装置语言: 三个压扁大球)
    for dx, dy, dr in [(-0.34, 0.77, 0.30), (0.36, 0.75, 0.235), (-0.52, 0.75, 0.215)]:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=dr, location=(dx, dy, dr * 0.32))
        dome = bpy.context.active_object; dome.name = f"KV_Dome_{dx}"
        dome.scale = (1.07, 1.0, 0.40)
        dome.data.materials.append(mat((0.17, 0.33, 0.21), 0.84))

    # 树
    for tx, ty, tr_ in [(-0.34, 0.42, 0.075), (0.10, 0.56, 0.045), (-0.18, 0.62, 0.05)]:
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2, radius=tr_, location=(tx, ty, tr_ * 0.9 + 0.03))
        tree = bpy.context.active_object; tree.name = f"KV_Tree_{tx}"
        tree.data.materials.append(mat((0.07, 0.24, 0.12), 0.9))

    # 绿环境补光 (右侧反弹)
    bpy.ops.object.light_add(type="AREA", location=(0.85, -0.05, 0.45))
    gf = bpy.context.active_object; gf.name = "KV_GreenFill"
    gf.data.size = 1.0
    gf.data.energy = 9.0
    gf.data.color = (0.45, 0.78, 0.52)
    con = gf.constraints.new("TRACK_TO")
    aim = bpy.data.objects.get("KV_Aim") or bpy.context.scene.objects.get("Aim")
    if aim:
        con.target = aim
    bpy.ops.object.light_add(type="AREA", location=(-0.14, -0.50, 0.21))
    ff = bpy.context.active_object; ff.name = "KV_FrontFill"
    ff.data.size = 1.15
    ff.data.energy = 4.7
    ff.data.color = (1.0, 0.96, 0.86)
    # -- 弱右后轮廓光 (仅右缘+顶部分离, 主光15-20%) --
    bpy.ops.object.light_add(type="AREA", location=(0.30, 0.12, 0.26))
    rim = bpy.context.active_object; rim.name = "KV_RimRR"
    rim.data.size = 0.15
    rim.data.energy = 2.5
    rim.data.color = (1.0, 0.98, 0.92)
    _ra = bpy.context.scene.objects.get("Aim")
    if _ra:
        _rc2 = rim.constraints.new("TRACK_TO"); _rc2.target = _ra
    # -- 前下暖反射 (牛皮纸底部厚度) --
    bpy.ops.object.light_add(type="POINT", location=(0.0, -0.20, 0.05))
    gb = bpy.context.active_object; gb.name = "KV_GroundBounce"
    gb.data.energy = 1.4
    gb.data.color = (1.0, 0.88, 0.74)
    # -- 近景草毯洗地光 (消黑洞, 绿调不抢产品) --
    bpy.ops.object.light_add(type="AREA", location=(0.0, -0.16, 0.26))
    nw = bpy.context.active_object; nw.name = "KV_NearWash"
    nw.data.size = 1.1
    nw.data.energy = 4.5
    nw.data.color = (0.75, 0.95, 0.78)
    nw.rotation_euler = (math.radians(-42), 0, 0)  # 发射轴指向镜头侧近地带
    if os.environ.get("KV_DIAG_ONLY"):
        for L in bpy.data.objects:
            if L.type == "LIGHT" and L.name != "KV_NearWash":
                L.data.energy = 0
    if os.environ.get("KV_DIAG_FLAT"):
        bpy.context.scene.render.engine = "BLENDER_WORKBENCH"
        bpy.context.scene.display.shading.light = "FLAT"
        bpy.context.scene.display.shading.color_type = "RANDOM"
        bpy.context.scene.cycles.samples = 1
        bpy.context.scene.render.resolution_percentage = 40
    if os.environ.get("KV_DIAG_SAMPLES"):
        bpy.context.scene.cycles.samples = int(os.environ["KV_DIAG_SAMPLES"])
        bpy.context.scene.render.resolution_percentage = 40
    aim0 = bpy.context.scene.objects.get("Aim")
    if aim0:
        _c = ff.constraints.new("TRACK_TO"); _c.target = aim0
    scene = bpy.context.scene
    scene.view_settings.exposure = -0.24
    scene.view_settings.gamma = 1.04
    try:
        scene.view_settings.look = "AgX - Punchy"
    except Exception as e:
        # 2026-11-18 审计 B-4: Look 静默失败 -> 实际色彩管线与门禁标定值错配, 闸仍可能 PASS。
        # Look 是门禁阈值的标定前提, 失败必须显式暴露。
        print(f"[FATAL] view_settings.look='AgX - Punchy' 设置失败: {type(e).__name__}: {e}")
        print("        门禁阈值按 AgX-Punchy 标定, 色彩管线不一致时判定无效 -> 中止渲染")
        raise
    for L in bpy.data.objects:
        if L.type == "LIGHT" and L.name.startswith(("Key", "Fill")):
            pass
    print("[KV] 低碳微缩绿城场景已构建 (草 3200 / 楼 4 / 树 3 / 墙+10)")

build_carton_twin_placeholder = None

def assign_box_uv_front_region(obj, w, d, h, region):
    """礼盒 UV: FRONT(-Y) 面采样贴图横条子区 region, 其余面按原 UV_REGIONS 契约"""
    mesh = obj.data
    uvl = mesh.uv_layers[0] if len(mesh.uv_layers) else mesh.uv_layers.new(name="atlas")
    rx0, ry0, rx1, ry1 = region
    for poly in mesh.polygons:
        n = poly.normal
        ax = max(range(3), key=lambda i: abs(n[i]))
        if ax == 1 and n.y < 0:          # FRONT 专用横条
            for li in poly.loop_indices:
                vi = mesh.loops[li].vertex_index
                vx, vz = mesh.vertices[vi].co.x, mesh.vertices[vi].co.z
                uvl.data[li].uv = (
                    rx0 + (vx / w + 0.5) * (rx1 - rx0),
                    ry0 + (vz / h) * (ry1 - ry0),
                )
        else:
            if ax == 1:
                reg = UV_REGIONS["BACK"]
                for li in poly.loop_indices:
                    vi = mesh.loops[li].vertex_index
                    vx, vz = mesh.vertices[vi].co.x, mesh.vertices[vi].co.z
                    uvl.data[li].uv = (
                        reg[0] + (vx / w + 0.5) * (reg[2] - reg[0]),
                        reg[1] + (vz / h) * (reg[3] - reg[1]),
                    )
            elif ax == 0:
                reg = UV_REGIONS["SIDE_L"] if n.x < 0 else UV_REGIONS["SIDE_R"]
                for li in poly.loop_indices:
                    vi = mesh.loops[li].vertex_index
                    vz, vy = mesh.vertices[vi].co.z, mesh.vertices[vi].co.y
                    uvl.data[li].uv = (
                        reg[0] + (vy / d + 0.5) * (reg[2] - reg[0]),
                        reg[1] + (vz / h) * (reg[3] - reg[1]),
                    )
            else:
                reg = UV_REGIONS["TOP"] if n.z > 0 else UV_REGIONS["BOTTOM"]
                for li in poly.loop_indices:
                    vi = mesh.loops[li].vertex_index
                    vx, vy = mesh.vertices[vi].co.x, mesh.vertices[vi].co.y
                    uvl.data[li].uv = (
                        reg[0] + (vx / w + 0.5) * (reg[2] - reg[0]),
                        reg[1] + (vy / d + 0.5) * (reg[3] - reg[1]),
                    )


YOG_BW, YOG_BD, YOG_BH = 0.040, 0.030, 0.142      # 酸奶系列 205g 砖 (瘦高 3.55:1)
YOG_GW, YOG_GD, YOG_GH = 0.140, 0.050, 0.063      # 205g x12 礼盒 (横版 2.2:1)


GIFT_FRONT_UV = (60 / 2048, 816 / 2048, 980 / 2048, 1234 / 2048)   # 礼盒横版贴图子区 (归一化, 与 00 像素区 (60,816,980,1234) 对应)


def build_carton_twin(sku, loc=(0, 0, 0), rot=(0, 0, 0), dims=None, cap=True, bevel=0.0008,
                    front_region=None):
    """利乐包数字母本: 底面中心 origin + 八角倒角 + 双层清漆 + HDPE 梦幻盖(SSS); dims 可覆盖 (酸奶砖/礼盒)"""
    W_, D_, H_ = dims if dims else (PACK_W, PACK_D, PACK_H)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    pack = bpy.context.active_object
    pack.name = f"Carton_{sku}"
    pack.scale = (W_, D_, H_)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    # origin 移到底面中心: 平移 mesh 使 z ∈ [0, H]
    pack.data.transform(Matrix.Translation((0, 0, H_ / 2)))
    pack.location = loc
    pack.rotation_euler = rot

    bev = pack.modifiers.new("Octagon", "BEVEL")
    bev.width = bevel
    bev.segments = 3
    bev.harden_normals = False
    try:
        bpy.ops.object.shade_smooth()
        bpy.ops.object.shade_auto_smooth(angle=math.radians(55))   # 40° 会把顶-侧倒角面平直化成硬阴影槽
    except AttributeError:
        pass

    mat = bpy.data.materials.new(f"Mat_{sku}")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    cfg = SKU_PROFILES.get(sku, {})
    if "Coat Weight" in bsdf.inputs:            # 淋膜纸清漆层; 牛皮纸哑光近零 coat (GPT P1-4)
        _kraft = cfg.get("base_roughness", 90) >= 150
        bsdf.inputs["Coat Weight"].default_value = 0.02 if _kraft else float(os.environ.get("COAT_W", "0.10"))   # v68 哑光纸
        bsdf.inputs["Coat Roughness"].default_value = 0.42 if _kraft else 0.12

    _suf = "_v68" if os.environ.get("ALBEDO_V68") else ("_v67" if os.environ.get("ALBEDO_V67") else "")   # v99 CDC 参照背面印刷
    albedo_p = os.path.join(TEX_DIR, f"{sku}_albedo{_suf}.png")
    orm_p = os.path.join(TEX_DIR, f"{sku}_orm.png")
    norm_p = os.path.join(TEX_DIR, "tetrapak_common_normal.png")

    if os.path.exists(albedo_p):
        t = nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(albedo_p)
        if os.environ.get("TEX_DEBUG") == "1":
            import numpy as _np2
            _w2, _h2 = t.image.size
            _px2 = _np2.empty(_w2 * _h2 * 4, dtype=_np2.float32)
            t.image.pixels.foreach_get(_px2)
            _rgb2 = _px2.reshape(_h2, _w2, 4)
            _tile2 = _rgb2[256:640, 384:640, :3]
            print(f"[TEX-DEBUG] {albedo_p.split('/')[-1]} {_w2}x{_h2} cs={t.image.colorspace_settings.name} tile_mean={_tile2.reshape(-1,3).mean(axis=0).round(decimals=3).tolist()}")
        # v47 单变量: 印刷色饱和校准 (白卡 sat≈0 不受影响)
        hsv = nodes.new("ShaderNodeHueSaturation")
        hsv.inputs["Saturation"].default_value = float(os.environ.get("LABEL_SAT", "1.30"))
        hsv.inputs["Value"].default_value = 1.0
        links.new(t.outputs["Color"], hsv.inputs["Color"])
        # v66: 印刷小字反差 (gamma 1.15: 白卡=1 不受影响, 中间调墨色加深)
        gam = nodes.new("ShaderNodeGamma")
        gam.inputs["Gamma"].default_value = float(os.environ.get("LABEL_GAMMA", "1.15"))
        links.new(hsv.outputs["Color"], gam.inputs["Color"])
        # v67: 小字墨色定向加深 (mask: V∈[0.3,0.9] 且 S<0.35; 品牌色/白卡/装饰冻结)
        sepv = nodes.new("ShaderNodeSeparateColor")
        sepv.mode = "HSV"
        links.new(t.outputs["Color"], sepv.inputs["Color"])
        v1 = nodes.new("ShaderNodeMath"); v1.operation = "GREATER_THAN"; v1.inputs[1].default_value = 0.30
        links.new(sepv.outputs["Blue"], v1.inputs[0])   # HSV: Blue = V
        v2 = nodes.new("ShaderNodeMath"); v2.operation = "LESS_THAN"; v2.inputs[1].default_value = 0.90
        links.new(sepv.outputs["Blue"], v2.inputs[0])
        s1 = nodes.new("ShaderNodeMath"); s1.operation = "LESS_THAN"; s1.inputs[1].default_value = 0.35
        links.new(sepv.outputs["Green"], s1.inputs[0])  # Green = S
        mm1 = nodes.new("ShaderNodeMath"); mm1.operation = "MULTIPLY"
        links.new(v1.outputs[0], mm1.inputs[0]); links.new(v2.outputs[0], mm1.inputs[1])
        mm2 = nodes.new("ShaderNodeMath"); mm2.operation = "MULTIPLY"
        links.new(mm1.outputs[0], mm2.inputs[0]); links.new(s1.outputs[0], mm2.inputs[1])
        mm3 = nodes.new("ShaderNodeMath"); mm3.operation = "MULTIPLY"; mm3.inputs[1].default_value = float(os.environ.get("INK_DK", "0.14"))
        links.new(mm2.outputs[0], mm3.inputs[0])
        mixd = nodes.new("ShaderNodeMixRGB")
        mixd.blend_type = "MULTIPLY"
        mixd.inputs[2].default_value = (0.0, 0.0, 0.0, 1)
        links.new(mm3.outputs[0], mixd.inputs["Fac"])
        links.new(gam.outputs["Color"], mixd.inputs[1])
        links.new(mixd.outputs["Color"], bsdf.inputs["Base Color"])
    if os.path.exists(orm_p):
        t = nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(orm_p)
        t.image.colorspace_settings.name = "Non-Color"
        sep = nodes.new("ShaderNodeSeparateColor")
        links.new(t.outputs["Color"], sep.inputs["Color"])
        if os.environ.get("POUR", "0") == "1":
            # v98 E40 纸面缎光高光 (漫反射无 specular=形变不可见根因): roughness x0.5 + coat 0.25
            _rm = nodes.new("ShaderNodeMath")
            _rm.operation = 'MULTIPLY'
            _rm.inputs[1].default_value = 0.5
            links.new(sep.outputs["Green"], _rm.inputs[0])
            links.new(_rm.outputs[0], bsdf.inputs["Roughness"])
            if "Coat Weight" in bsdf.inputs:
                bsdf.inputs["Coat Weight"].default_value = 0.25
                bsdf.inputs["Coat Roughness"].default_value = 0.10
        else:
            links.new(sep.outputs["Green"], bsdf.inputs["Roughness"])
        links.new(sep.outputs["Blue"], bsdf.inputs["Metallic"])
    if os.path.exists(norm_p):
        t = nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(norm_p)
        t.image.colorspace_settings.name = "Non-Color"
        nm = nodes.new("ShaderNodeNormalMap")
        nm.inputs["Strength"].default_value = 0.45
        links.new(t.outputs["Color"], nm.inputs["Color"])
        links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])

    pack.data.materials.append(mat)
    if front_region:
        assign_box_uv_front_region(pack, W_, D_, H_, front_region)
    else:
        assign_box_uv(pack, W_, D_, H_)
    if not cap:
        return pack, None, None

    # DreamCap 旋盖 (HDPE + SSS)
    # 相对 pack 局部定位 (0,0,H+0.004), 直接 parent (matrix_parent_inverse 保持单位)
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=W_ * 0.354, depth=H_ * 0.052,
                                        location=(0, 0, H_ + H_ * 0.014))   # 下沉嵌入顶面, 消白缝
    cap = bpy.context.active_object
    cap.name = f"Cap_{sku}"
    cap.parent = pack
    _cb = cap.modifiers.new("knurl_bevel", "BEVEL")   # 滚花边软化
    _cb.width = 0.0009
    _cb.segments = 2
    cmat = bpy.data.materials.new("DreamCap_HDPE")
    cmat.use_nodes = True
    cbsdf = cmat.node_tree.nodes.get("Principled BSDF")
    _short = sku.replace("demo_", "").replace("demo_yogurt_", "")
    cap_col = {"organic": (0.93, 0.93, 0.92, 1.0),   # 经典有机: 白色梦幻盖 (参照图)
               "classic": (0.030, 0.185, 0.095, 1.0),  # 电商纯牛奶: 草原绿盖 (四压去薄荷)
               "cny": (0.85, 0.65, 0.30, 1.0),       # 春节限定: 鎏金盖
               "jersey": (0.85, 0.72, 0.32, 1.0),    # 娟姗: 黑金镜面
               "a2": (0.16, 0.32, 0.62),             # A2β: 深海蓝盖
               "lowfat": (0.05, 0.52, 0.42),         # 高钙低脂: 青绿盖
               "dream38": (0.92, 0.90, 0.84),        # 梦幻盖3.8: 甘蔗白盖
               "dream40": (0.45, 0.30, 0.62),        # 4.0蛋白: 幻紫盖
               "skim": (0.28, 0.55, 0.80),           # 脱脂: 冰蓝盖
               "hulunbeier": (0.16, 0.34, 0.62),     # 呼伦贝尔: 蓝金盖
               "original": (0.90, 0.93, 0.97, 1.0),  # 酸奶原味: 爱琴白盖
               "gold": (0.85, 0.72, 0.32, 1.0),      # 酸奶金装: 金盖
               }.get(_short, (0.85, 0.72, 0.32, 1.0))
    cbsdf.inputs["Base Color"].default_value = tuple(cap_col)[:3] + (1.0,)
    cbsdf.inputs["Roughness"].default_value = 0.68   # HDPE 哑光 (复评: 0.58 偏亮, 提至 0.68)
    if "Subsurface Weight" in cbsdf.inputs:
        cbsdf.inputs["Subsurface Weight"].default_value = 0.02
        cbsdf.inputs["Subsurface Radius"].default_value = (1.0, 0.8, 0.5)
        cbsdf.inputs["Subsurface Scale"].default_value = 0.002
    cap.data.materials.append(cmat)

    # DreamCap 防盗环: 盖底独立可断环 (参照 tamper-evident ring)
    bpy.ops.mesh.primitive_cylinder_add(vertices=48, radius=W_ * 0.362, depth=H_ * 0.014,
                                        location=(0, 0, H_ + H_ * 0.002))
    lip = bpy.context.active_object
    lip.name = f"CapLip_{sku}"
    lip.parent = pack
    lip.data.materials.append(cmat)
    return pack, cap, lip


def run_pipeline():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    setup_metal_engine(samples=192)
    scene = bpy.context.scene

    world = bpy.data.worlds.new("Studio")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.85, 0.88, 0.92, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.03
    scene.world = world

    if args.scene == "lowcarbon_city":
        build_lowcarbon_city()
    elif args.scene == "demo_yogurt_combo":
        build_yogurt_combo(args.sku)
    bg_path = get_or_generate_background(args.scene, 1600, 1600)
    ibl = extract_ibl_lighting_from_bg(bg_path)
    print(f"[IBL] 主光源参数: pos={tuple(round(v,3) for v in ibl['light_pos'])}")

    if args.scene == "demo_yogurt_combo":
        hero, cap_hero, lip_hero = None, None, None
        sub, cap_sub, lip_sub = None, None, None
    else:
        hero, cap_hero, lip_hero = build_carton_twin(args.sku, loc=(0.0, 0.0, 0.0), rot=(0, 0, math.radians(-16)))
        sub, cap_sub, lip_sub = build_carton_twin("demo_classic",
                                       loc=(-0.062, 0.045, 0.0), rot=(0, 0, math.radians(14)))
    bpy.context.view_layer.update()

    # 数字孪生 3D 查看器: GLB 导出 (仅 hero 主盒 + 其盖, 移除副盒/地面)
    if getattr(args, "export_glb", None):
        bpy.data.objects.remove(sub, do_unlink=True)
        bpy.data.objects.remove(cap_sub, do_unlink=True)
        bpy.data.objects.remove(lip_sub, do_unlink=True)
        for ob in list(bpy.data.objects):
            if ob.type == "MESH" and ob.name.startswith(("Plane", "Floor")):
                bpy.data.objects.remove(ob, do_unlink=True)
        hero.rotation_euler = (0, 0, 0) if hero else None  # 查看器用正脸
        if hero is None:
            raise SystemExit("GLB export requires default scene (hero pack)")
        bpy.ops.export_scene.gltf(filepath=args.export_glb, export_format="GLB",
                                  export_materials="EXPORT", export_image_format="WEBP")
        print(f"[GLB] 数字孪生模型已导出: {args.export_glb}")


    # 影棚柔光箱 Rig: 大面积光源 = 棚拍软渐变 (小灯是硬光 CG 感的根源)
    # 能量按旧 6W/0.35m 基准折算 (~5x 面积/距离补偿), Standard VT 白卡纸防过曝
    aim = bpy.data.objects.new("Aim", None)
    aim.location = (0.0, 0.0, 0.07)  # 逐平台可被 aim_z 覆盖
    bpy.context.collection.objects.link(aim)
    for pos, size, energy, color in [
        ((0.55, -0.75, 0.85), 0.85, 34.0, (1.0, 0.98, 0.95)),  # 主柔光箱 (暖白, 收紧投影)
        ((-0.75, -0.55, 0.62), 1.7, 9.0, (0.95, 0.97, 1.0)),   # 冷补光 (抬高+放大: 防盖影在顶面成硬槽)
        ((0.0, -0.15, 2.10), 2.6, 14.0, (1.0, 1.0, 1.0)),      # 顶光 (放大抬高: 盖影软化, 消顶面硬暗槽)
        ((0.30, 0.65, 0.70), 0.8, 8.0, (0.92, 0.96, 1.0)),     # 轮廓光 (弱化地面斜影)
    ]:
        bpy.ops.object.light_add(type="AREA", location=pos)
        L = bpy.context.active_object
        L.data.size = size
        L.data.energy = energy
        L.data.color = color
        con = L.constraints.new("TRACK_TO")
        con.target = aim
    LIGHT_BASE = {L.name: L.data.energy for L in bpy.data.objects if L.type == "LIGHT"}

    bpy.ops.object.camera_add()
    cam = bpy.context.active_object
    scene.camera = cam

    PLATFORMS = {
        "01_JD_WhiteBG_800x800": dict(res=(800, 800), cam_loc=(0.0, -0.50, 0.070),
                                      cam_rot=(math.radians(88.5), 0, 0), lens=92,
                                      shift_y=0.01, white_bg=True, show_sub=False),
        "02_Tmall_Hero_1x1_1600x1600": dict(res=(1600, 1600), cam_loc=(-0.01, -0.46, 0.10),
                                            cam_rot=(math.radians(85), 0, 0), lens=85,
                                            shift_y=0.02, white_bg=False, show_sub=True),
        "03_Douyin_Feed_9x16_1080x1920": dict(res=(1080, 1920), cam_loc=(-0.01, -0.40, 0.065),
                                              cam_rot=(math.radians(91), 0, 0), lens=55,
                                              shift_y=-0.07, white_bg=False, show_sub=True),
        "04_Xiaohongshu_Note_3x4_1242x1660": dict(res=(1242, 1660), cam_loc=(0.015, -0.38, 0.16),
                                                  cam_rot=(math.radians(74), 0, math.radians(4)), lens=65,
                                                  shift_y=-0.02, white_bg=False, show_sub=True),
        # 电商套图补充 (雀巢模块 A 规格): 背面营养表特写 + 45° 轴测主图, 带 Alpha 通道
        "05_Back_Nutrition_1600x1600": dict(res=(1600, 1600), cam_loc=(0.0, 0.50, 0.075),
                                            cam_rot=(math.radians(92), 0, 0), lens=78,
                                            shift_y=0.03, shift_x=0.015, white_bg=True, show_sub=False,
                                            aim=True, save_alpha=True),
        "06_Hero_45deg_1600x1600": dict(res=(1600, 1600), cam_loc=(0.36, -0.36, 0.26),
                                        cam_rot=(0, 0, 0), lens=78,
                                        shift_y=0.0, white_bg=True, show_sub=False,
                                        aim=True, save_alpha=True),
        "08_AMX_Combo_900x900": dict(res=(900, 900), cam_loc=(0.0, -0.42, 0.10),
                                     cam_rot=(0, 0, 0), lens=45, sensor_fit="HORIZONTAL", shift_y=0.0,
                                     white_bg=True, show_sub=True,
                                     aim=True, aim_z=0.055, hero_rot=0, save_alpha=True,
                                     sub_loc=(-0.042, 0.018, 0.0)),
        "07_KV_LowCarbon_1242x1660": dict(res=(1242, 1660), cam_loc=(0.015, -0.32, 0.085),
                                          cam_rot=(math.radians(91.8), 0, math.radians(-2.5)), lens=62, sensor_fit="HORIZONTAL",
                                          white_bg=False, show_sub=False,
                                          fstop=8.0, hero_rot=-25, shift_x=-0.055, dof_focus=0.32, shift_y=-0.035),
        # 六视角验收协议 (GPT 门禁 2026-11-09): 左侧 90° + 顶视盖口 (look_at 精确取景)
        "09_Side_90deg_800x800": dict(res=(800, 800), cam_loc=(0.50, 0.0, 0.070),
                                      look_at=(0.0, 0.0, 0.070), lens=92,
                                      white_bg=True, show_sub=False),
        "10_Top_Cap_800x800": dict(res=(800, 800), cam_loc=(0.0, -0.30, 0.60),
                                   look_at=(0.0, 0.0, 0.075), lens=70,
                                   white_bg=True, show_sub=False),
    }

    # Shadow Catcher 地面 (仅白底合成平台需要; 深色场景与场景地面 z-fighting 会出黑带)
    _only_set = {a for a in args.only.split(",") if a} if args.only else None
    rendered = list(_only_set) if _only_set else list(PLATFORMS)
    needs_catcher = any(PLATFORMS[p].get("white_bg") for p in rendered if p in PLATFORMS)
    floor = None
    if needs_catcher:
        bpy.ops.mesh.primitive_plane_add(size=1.5, location=(0, 0, 0))
        floor = bpy.context.active_object
        floor.is_shadow_catcher = True
        fmat = bpy.data.materials.new("BounceFloor")
        fmat.use_nodes = True
        fmat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = ibl["ground_color"]
        floor.data.materials.append(fmat)
    floor_base_green = tuple(ibl["ground_color"])

    bg_master = Image.open(bg_path).convert("RGBA")
    if os.environ.get("KV_DIAG_PROBE"):
        from mathutils import Vector
        dg = bpy.context.evaluated_depsgraph_get()
        print("=== PROBE A: 向下打射线, 黑带处最上层是什么 ===")
        for py in (-0.04, -0.08, -0.12, -0.16):
            for px in (-0.15, 0.0, 0.15):
                hit, loc, nrm, idx, ob, mw = bpy.context.scene.ray_cast(dg, Vector((px, py, 0.4)), Vector((0, 0, -1)))
                print(f"  from({px},{py},z0.4)down -> {'HIT ' + ob.name if hit else 'VOID'} @z={loc.z:.4f}")
        print("=== PROBE B: 从洗地光位向黑带打射线, 谁挡在中间 ===")
        for py in (-0.06, -0.10, -0.14):
            tgt = Vector((0.0, py, 0.02))
            org = Vector((0.0, -0.16, 0.26))
            d = (tgt - org).normalized()
            hit, loc, nrm, idx, ob, mw = bpy.context.scene.ray_cast(dg, org, d)
            dist = (loc - org).length
            print(f"  wash->{py}: {'HIT ' + ob.name if hit else 'CLEAR'} @dist={dist:.3f} (tgt_dist={(tgt-org).length:.3f})")
        raise SystemExit(0)
    only = {a for a in args.only.split(",") if a} if args.only else None
    # ---- 排版 QA 闸门加载 (渲染后自动过闸; GPT 终裁: 系统级验收) ----
    import importlib.util as _ilu
    _gate_path = os.path.join(BASE_DIR, "10_layout_qa_gate.py")
    _gate = None
    if os.path.exists(_gate_path):
        _spec = _ilu.spec_from_file_location("layout_qa_gate", _gate_path)
        _gate = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_gate)
    _gate_records = []
    # 渲染血缘 manifest: 渲染开始前记录 sku+当前贴图 sha (闸验证本次渲染用磁盘当前贴图)
    import hashlib as _hashlib0
    import json as _json
    _mpath = os.path.join(BASE_DIR, "output", "render_manifest.json")
    _man = {}
    if os.path.exists(_mpath):
        try:
            _man = _json.load(open(_mpath))
        except Exception as e:
            # 2026-11-18 审计 B-3: 损坏的 manifest 不能被 {} 静默覆盖 (旧血缘丢失)。
            # 处理: 保留损坏副本另存, 用空血缘继续渲染, 但门禁侧 (10_layout_qa_gate.py) 判 FAIL。
            import shutil as _shutil
            import time as _time
            _bak = _mpath + ".corrupt-" + str(int(_time.time()))
            try:
                _shutil.move(_mpath, _bak)
                print(f"[WARN] render_manifest.json 读取失败 ({type(e).__name__}: {e})")
                print(f"       已另存为 {_bak}, 本次渲染从空血缘开始; 门禁将判 FAIL 直到血缘重建")
            except Exception as _e2:
                print(f"[WARN] render_manifest.json 读取失败 ({type(e).__name__}: {e}); 备份失败: {_e2}")
            _man = {}
    _tex0 = os.path.join(TEX_DIR, f"{args.sku}_albedo.png")
    _sha0 = _hashlib0.sha256(open(_tex0, "rb").read()).hexdigest()[:16] if os.path.exists(_tex0) else "-"
    for _p0 in (list(_only_set) if _only_set else list(PLATFORMS)):
        _man[_p0 + ".png"] = {"sku": args.sku, "tex_sha": _sha0,
                              "tex_mtime": os.path.getmtime(_tex0) if os.path.exists(_tex0) else 0}
    _json.dump(_man, open(_mpath, "w"), ensure_ascii=False, indent=2)
    for p_name, cfg in PLATFORMS.items():
        if only and p_name not in only:
            continue
        w, h = cfg["res"]
        scene.render.resolution_x, scene.render.resolution_y = w, h
        scene.render.film_transparent = True
        if sub is not None:
            sub.hide_render = not cfg["show_sub"]
            cap_sub.hide_render = not cfg["show_sub"]
            lip_sub.hide_render = not cfg["show_sub"]
        cam.location = cfg["cam_loc"]
        # aim=True: TRACK_TO 瞄准商品中心 (45° 轴测/背面特写), 否则用调好的欧拉角
        tr = next((c for c in cam.constraints if c.type == "TRACK_TO"), None)
        if cfg.get("hero_rot") is not None:
            if hero is not None:
                hero.rotation_euler = (0, 0, math.radians(cfg["hero_rot"]))
        if cfg.get("sub_loc") and sub is not None:
            sub.location = cfg["sub_loc"]
        if cfg.get("aim"):
            aim.location = (0.0, 0.0, cfg.get("aim_z", 0.07))
            if tr is None:
                tr = cam.constraints.new("TRACK_TO")
                tr.target = aim
                tr.track_axis = "TRACK_NEGATIVE_Z"
                tr.up_axis = "UP_Y"
            cam.rotation_euler = (0, 0, 0)
        elif tr is not None:
            cam.constraints.remove(tr)
        if not cfg.get("aim") and not cfg.get("look_at"):
            cam.rotation_euler = cfg["cam_rot"]
        if cfg.get("look_at"):
            from mathutils import Vector
            tgt = Vector(cfg["look_at"])
            cam.location = cfg["cam_loc"]
            d = tgt - cam.location
            cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        cam.data.lens = cfg["lens"]
        cam.data.sensor_fit = cfg.get("sensor_fit", "AUTO")
        cam.data.shift_y = cfg.get("shift_y", 0.0)
        cam.data.shift_x = cfg.get("shift_x", 0.0)

        # 白底平台: 地板中性+关GI反弹 (防场景绿洗); 场景平台保留环境色反弹
        if floor is not None:
            fb = floor.data.materials[0].node_tree.nodes["Principled BSDF"].inputs["Base Color"]
            if cfg["white_bg"]:
                fb.default_value = (0.62, 0.62, 0.62, 1.0)
                floor.visible_diffuse = False
                floor.visible_glossy = False
            else:
                fb.default_value = floor_base_green
                floor.visible_diffuse = True
                floor.visible_glossy = True
        # 白底平台: 弱中性环境填充(0.06, 2026-11-09 白化修复: 0.30 纯白环境=10倍包围光把浅色albedo全clip);
        # 灯组降档 0.62 + 曝光 -0.5EV (浅色albedo不再clip); 场景平台: 基准灯+中性棚拍环境
        bg_in = world.node_tree.nodes["Background"].inputs
        for L in bpy.data.objects:
            if L.type == "LIGHT" and L.name in LIGHT_BASE:
                L.data.energy = LIGHT_BASE[L.name] * (0.62 if cfg["white_bg"] else 1.0)
        if cfg["white_bg"]:
            scene.view_settings.exposure = -0.74
        else:
            scene.view_settings.exposure = -0.24
        if cfg["white_bg"]:
            bg_in[0].default_value = (0.92, 0.92, 0.92, 1.0)
            bg_in[1].default_value = 0.06
        else:
            bg_in[0].default_value = (0.85, 0.88, 0.92, 1.0)
            bg_in[1].default_value = 0.04
        # 场景图轻景深 (白底图保持全锐)
        cam.data.dof.use_dof = not cfg["white_bg"]
        if cam.data.dof.use_dof:
            cam.data.dof.aperture_fstop = cfg.get("fstop", 5.6)
            if cfg.get("aim"):
                cam.data.dof.focus_distance = (cam.location - aim.location).length
            elif cfg.get("dof_focus"):
                cam.data.dof.focus_distance = cfg["dof_focus"]
            else:
                cam.data.dof.focus_distance = 0.5
            cam.data.dof.focus_distance = max(0.2, math.dist(cam.location, (0.0, 0.0, 0.07)))

        fg_tmp = os.path.join(OUT_DIR, f"_tmp_{p_name}.png")
        scene.render.filepath = fg_tmp
        bpy.ops.render.render(write_still=True)

        fg = Image.open(fg_tmp).convert("RGBA")
        out_file = os.path.join(OUT_DIR, f"{p_name}.png")
        if p_name == "08_AMX_Combo_900x900":
            # main_02 v2: 淡蓝渐变 + logo + 无底条描边大字 + 双大弧循环箭头 (参照版式)
            import numpy as _np
            import math as _pm
            W_, H_ = fg.size
            t_ = _np.linspace(0, 1, H_)[:, None, None]
            top_ = _np.array([250, 252, 255]); bot_ = _np.array([224, 236, 249])
            grad_ = _np.ascontiguousarray((top_ * (1 - t_) + bot_ * t_).astype("uint8"))
            bgc_ = _np.ascontiguousarray(_np.repeat(grad_, W_, axis=1))
            base_ = Image.fromarray(bgc_, "RGB").convert("RGBA")
            base_.alpha_composite(fg)
            from PIL import ImageDraw as _ImageDraw
            d2_ = _ImageDraw.Draw(base_, "RGBA")
            aegean = (26, 78, 150); red = (198, 30, 40); white = (252, 253, 255)
            # 接触影由 shadow catcher 实渲自带 (锚定真实盒位, 不再画模板幽灵影)
            # 左上空气光斑 (极淡径向白光)
            gl_ = Image.new("RGBA", (W_, H_), (0, 0, 0, 0))
            dg_ = _ImageDraw.Draw(gl_)
            for k in range(16):
                t = k / 15
                dg_.ellipse([W_ * 0.08 - W_ * 0.42 * (1 - t), H_ * 0.10 - H_ * 0.42 * (1 - t),
                             W_ * 0.08 + W_ * 0.42 * (1 - t), H_ * 0.10 + H_ * 0.42 * (1 - t)],
                            fill=(255, 255, 255, int(16 * (1 - t))))
            base_.alpha_composite(gl_)
            # 中央文案: 粗体蓝字 + 白描边 (参照无底条)
            d2_.text((W_ // 2, int(H_ * 0.82)), "多款包装随机发货", fill=aegean,
                     font=get_pil_font(58), anchor="mm", stroke_width=6, stroke_fill=white)
            # (丝带箭头已删: 单盒/双盒版式下悬空无锚定, 触发门禁stray_geometry)
            # 左上 logo: 按 SKU 族切换 (demo 牛奶系=绿标 / demo_yogurt 酸奶系=红标)
            lw_ = int(W_ * 0.135)
            lbx = [int(W_ * 0.05), int(H_ * 0.032), int(W_ * 0.05) + lw_, int(H_ * 0.032) + int(lw_ * 0.44)]
            is_milk = args.sku.startswith("demo")
            logo_bg = (0, 108, 64) if is_milk else red
            logo_cn, logo_en = ("经典", "CLASSIC") if is_milk else ("希腊酸奶", "GREEKY")
            d2_.rounded_rectangle(lbx, radius=10, fill=logo_bg)
            d2_.text(((lbx[0] + lbx[2]) // 2, (lbx[1] + lbx[3]) // 2), logo_cn,
                     fill=white, font=get_pil_font(int(lw_ * 0.30)), anchor="mm")
            d2_.text((lbx[2] + int(W_ * 0.016), (lbx[1] + lbx[3]) // 2), logo_en,
                     fill=(logo_bg if is_milk else aegean), font=get_pil_font(int(lw_ * 0.155)), anchor="lm")
            fg = base_
        if p_name == "07_KV_LowCarbon_1242x1660":
            # 分区调色 (campaign 厚度): 产品区暖化提饱和, 背景区沉稳降饱和
            import numpy as np
            rgb = np.asarray(fg.convert("RGB")).astype(np.float32) / 255.0
            h_, w_ = rgb.shape[:2]
            yy, xx = np.mgrid[0:h_, 0:w_]
            # 产品几何掩膜: 椭圆 (中心 x0.44w y0.55h, 半轴 0.20w x 0.30h), 高斯羽化
            ell = ((xx - 0.44 * w_) / (0.20 * w_)) ** 2 + ((yy - 0.55 * h_) / (0.30 * h_)) ** 2
            m = np.clip(1.0 - ell, 0.0, 1.0) ** 1.5
            from PIL import ImageFilter
            mimg = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(18))
            m = np.asarray(mimg).astype(np.float32) / 255.0
            def sat_v(img, sat, val):
                gray = img.mean(axis=2, keepdims=True)
                return np.clip((gray + (img - gray) * sat) * val, 0, 1)
            bg_ = sat_v(rgb, 0.93, 0.965)
            fg_ = sat_v(rgb, 1.06, 1.01)
            fg_[..., 0] *= 1.03; fg_[..., 2] *= 0.97  # 牛皮纸暖化
            out = np.clip(bg_ * (1 - m[..., None]) + fg_ * m[..., None], 0, 1)
            fg = Image.fromarray((out * 255).astype(np.uint8)).convert("RGBA")
        if cfg["white_bg"]:
            # 电商规范: 合成到不透明白画布 (详情页不接受透明通道)
            Image.alpha_composite(Image.new("RGBA", fg.size, (255, 255, 255, 255)), fg).convert("RGB").save(out_file)
            if cfg.get("save_alpha"):
                fg.save(out_file.replace(".png", "_alpha.png"))
        else:
            comp = Image.alpha_composite(bg_master.resize((w, h), Image.Resampling.LANCZOS), fg)
            comp.convert("RGB").save(out_file)
        os.remove(fg_tmp)
        print(f"[Success] {out_file}")
        if _gate is not None:
            _man_now = {}
            _man_f = os.path.join(BASE_DIR, "output", "render_manifest.json")
            if os.path.exists(_man_f):
                try:
                    import json as _json_m
                    _man_now = _json_m.load(open(_man_f))
                except Exception as e:
                    # 同 B-3: 血缘读不出来就不许把闸门当"无血缘"跑 (本次渲染刚写过 manifest, 读失败=异常)
                    print(f"[FATAL] render_manifest.json 读取失败: {type(e).__name__}: {e}")
                    raise
            _rep = _gate.run_gate(out_file, _man_now)
            _vs = " ".join(f"{k}={v['verdict']}" for k, v in _rep["checks"].items())
            print(f"[QA-GATE] {_rep['overall']} {os.path.basename(out_file)}: {_vs}")
            _gate_records.append(_rep)

    # ---- QA 闸门报告落盘 (合并写入; 不改渲染退出码, CI 用独立 --all) ----
    if _gate_records:
        import json as _json
        import hashlib as _hashlib
        _rpath = os.path.join(BASE_DIR, "output", "qa_gate_report.json")
        _merged = {}
        if os.path.exists(_rpath):
            try:
                _merged = _json.load(open(_rpath))
            except Exception as e:
                # 同 B-3: 旧 QA 记录不能被 {} 覆盖 (历史 PASS 记录会丢)
                print(f"[FATAL] qa_gate_report.json 读取失败: {type(e).__name__}: {e}")
                raise
        for _r in _gate_records:
            _merged[_r.get("key", _r["image"])] = _r
        _json.dump(_merged, open(_rpath, "w"), ensure_ascii=False, indent=2)
        _nf = sum(1 for _r in _gate_records if _r["overall"] == "FAIL")
        print(f"[QA-GATE-SUMMARY] {len(_gate_records)} rendered, {_nf} FAIL -> {_rpath}")

    # ---- AR/QuickLook 交付: Y-up + 厘米单位包装层 -> .usdz (失败回退 .usdc) ----
    if hero is None:
        return  # demo_yogurt_combo 组合场景: 无单品类 AR 交付
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0, 0, 0))
    root = bpy.context.active_object
    root.name = "AR_Root"
    root.rotation_euler = (math.radians(-90), 0, 0)   # Z-up -> Y-up
    root.scale = (100, 100, 100)                       # 米 -> 厘米
    bpy.context.view_layer.update()
    for obj in (hero, cap_hero):
        obj.parent = root
        obj.matrix_parent_inverse = root.matrix_world.inverted()
    bpy.context.view_layer.update()

    for obj in (root, hero, cap_hero):
        obj.select_set(True)
        usdz_out = os.path.join(USD_DIR, f"retail_{args.sku}.usdz")
    try:
        bpy.ops.wm.usd_export(filepath=usdz_out, selected_objects_only=True, export_materials=True)
        print(f"[Success] Apple AR 模型已导出: {usdz_out}")
    except Exception as e:
        usdc_out = os.path.join(USD_DIR, f"retail_{args.sku}.usdc")
        bpy.ops.wm.usd_export(filepath=usdc_out, selected_objects_only=True, export_materials=True)
        print(f"[Warn] usdz 导出失败({e}), 已回退 usdc: {usdc_out}")

    for obj in (hero, cap_hero):
        obj.parent = None
    root_ref = bpy.data.objects.get("AR_Root")
    if root_ref:
        bpy.data.objects.remove(root_ref, do_unlink=True)


if __name__ == "__main__":
    run_pipeline()
