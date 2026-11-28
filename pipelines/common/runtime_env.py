"""跨平台运行时助手 (纯标准库)。

存在理由: 仓库原本把 macOS/Apple Silicon 当成唯一运行环境, 导致
- Blender 路径硬编码 "/Applications/Blender.app/..."
- Cycles 计算设备硬编码 "METAL"
- 内存门依赖 macOS 专有的 `vm_stat`
- SD/ControlNet 硬编码 MPS

本模块把这些收敛成"环境变量 > 平台默认 > 自动探测"三级策略, 普通 Python
(run_pipeline.py) 与 Blender 内嵌 Python 都能 import (Blender 侧只用标准库部分,
bpy 相关逻辑在函数内部惰性 import)。

环境变量
--------
BLENDER_BIN      Blender 可执行文件路径 (优先于一切自动探测)
CYCLES_DEVICE    强制 Cycles 计算设备: OPTIX | CUDA | HIP | ONEAPI | METAL | NONE
FORCE_CPU_RENDER 置 1 时渲染一律走 CPU (CI / 无 GPU 环境)
TORCH_DEVICE     强制 SD/ControlNet 设备: cuda | mps | cpu
"""
import os
import shutil
import subprocess
import sys

BLENDER_ENV = "BLENDER_BIN"
CYCLES_DEVICE_ENV = "CYCLES_DEVICE"
FORCE_CPU_ENV = "FORCE_CPU_RENDER"
TORCH_DEVICE_ENV = "TORCH_DEVICE"

#: 各平台 Cycles 后端优先级 (取第一个真正枚举出设备的)
CYCLES_TYPES_BY_PLATFORM = {
    "darwin": ["METAL"],
    "win32": ["OPTIX", "CUDA", "HIP", "ONEAPI"],
    "linux": ["OPTIX", "CUDA", "HIP", "ONEAPI"],
}


# --------------------------------------------------------------------------- #
# Blender 可执行文件
# --------------------------------------------------------------------------- #
def blender_candidates():
    """按优先级返回本机可能的 Blender 路径。"""
    if sys.platform == "darwin":
        return ["/Applications/Blender.app/Contents/MacOS/Blender"]
    if os.name == "nt":
        roots = [
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", os.path.expanduser(r"~\AppData\Local")),
        ]
        found = []
        for root in roots:
            base = os.path.join(root, "Blender Foundation")
            if not os.path.isdir(base):
                continue
            for version in sorted(os.listdir(base), reverse=True):
                exe = os.path.join(base, version, "blender.exe")
                if os.path.isfile(exe):
                    found.append(exe)
        # 2026-11-23: 官方安装包也常被解到 ~/blender/blender-<ver>-windows-x64/ 下
        # (本机就是这么装的) —— 之前的候选列表漏了它, 导致 blender_bin() 落到
        # 不存在的 C:\blender\blender.exe 兜底路径。
        home_blender = os.path.join(os.path.expanduser("~"), "blender")
        if os.path.isdir(home_blender):
            for entry in sorted(os.listdir(home_blender), reverse=True):
                exe = os.path.join(home_blender, entry, "blender.exe")
                if os.path.isfile(exe):
                    found.append(exe)
        found.append(r"C:\blender\blender.exe")
        return found or [r"C:\blender\blender.exe"]
    return ["/usr/bin/blender", "/snap/bin/blender", "/usr/local/bin/blender",
            "/opt/blender/blender"]


def blender_shim_path():
    """本仓的 bpy 模块替身脚本路径 (tools/blender_shim.py)。"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "tools", "blender_shim.py")


def bpy_module_available():
    """当前解释器里能不能 import bpy (PyPI 的 Blender wheel)。"""
    try:
        import importlib.util
        return importlib.util.find_spec("bpy") is not None
    except Exception:
        return False


def blender_bin():
    """解析 Blender 可执行文件路径: 环境变量 > 已安装路径 > PATH。"""
    env = os.environ.get(BLENDER_ENV)
    if env:
        return env
    for candidate in blender_candidates():
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("blender") or blender_candidates()[0]


def blender_available():
    """Blender 是否真的可用 (路径存在且可执行)。"""
    path = blender_bin()
    if os.path.isfile(path):
        return True
    return bpy_module_available()


def blender_command():
    """返回调用 Blender 的 argv 前缀。

    2026-11-23 重写。原来的实现只认"一个可执行文件路径", 在 Windows 上有两个坑:

    1. **.cmd 包装**: 本仓的 tools/blender.cmd 是 bpy 模块的转发脚本, 但 cmd.exe
       不能直接被 CreateProcess 执行 (WinError 193), 得经 cmd.exe /c 转发 ——
       而 **cmd.exe 要求 .cmd 用 CRLF 换行**: 仓里那份是 LF, cmd 解析错行后
       把一条畸形重定向当命令执行, **把 tools/blender_shim.py 截断成了 0 字节**
       (2026-11-23 实际发生)。所以现在**不再走 .cmd**: 直接用当前解释器跑
       tools/blender_shim.py (bpy wheel), 既绕开 cmd.exe 的换行坑, 也让
       "用哪个 Blender 版本渲染" 由 pip 锁死 (本仓产物是 Blender 5.2 渲的)。

    2. **版本一致性**: 官方安装包 (~/blender/blender-5.1.2 等) 与产物用的
       bpy 5.2.4 不是同一版本, 换渲染器会引入新混淆项 —— 所以优先级是
       环境变量 > bpy wheel (与产物同版本) > 官方安装包 > PATH。
    """
    env = os.environ.get(BLENDER_ENV)
    if env:
        path = env
        if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
            # 2026-11-23: cmd.exe 只认 CRLF 的批处理。仓里的 tools/blender.cmd 曾是
            # LF 换行 → cmd 解析错行, 把一条畸形重定向当命令执行, **把
            # tools/blender_shim.py 截断成 0 字节**。这里先查换行, 不对就不走它。
            try:
                with open(path, "rb") as fh:
                    raw = fh.read()
                lf_only = raw.count(b"\n") - raw.count(b"\r\n")
                if lf_only:
                    print(f"[BLENDER] 警告: {path} 是 LF 换行的批处理 (cmd.exe 会解析错行, "
                          f"曾截断 tools/blender_shim.py) —— 改走 bpy 模块直调")
                else:
                    return ["cmd.exe", "/c", path]
            except OSError:
                return ["cmd.exe", "/c", path]
        else:
            return [path]
    if bpy_module_available():
        return [sys.executable, blender_shim_path()]
    # 2026-11-24: 走到这里说明**当前解释器里没有 bpy**。此时若退回官方安装包
    # (blender.exe), 它自带的 python **没有 numpy / Pillow** —— 而
    # 02_shelf_sdg_inspector.py 需要这两个 (读 PNG、算可见度), 于是脚本会在
    # import 处崩掉, 报错完全看不出"你用错了解释器了"。
    # (实测: 官方 Blender 5.1.2 的 python 里 `import PIL` -> ModuleNotFoundError。)
    # 所以这里明确警告: 应该用仓库的 venv 解释器 (它带 bpy + Pillow + numpy)。
    for candidate in blender_candidates():
        if os.path.isfile(candidate):
            print(f"[BLENDER] 警告: 当前解释器 ({sys.executable}) 里没有 bpy, "
                  f"退回官方安装包 {candidate}。\n"
                  f"          官方 Blender 自带的 python 缺 numpy/Pillow, "
                  f"02 号脚本会在 import 处失败。\n"
                  f"          建议用仓库 venv 解释器调用: "
                  f"{sys.executable} <脚本>  (或设置 ORTHO_PY 指向带 bpy 的解释器)")
            return [candidate]
    which = shutil.which("blender")
    return [which] if which else [blender_candidates()[0]]


def blender_renderer_info():
    """渲染器身份 (写进产物清单, 便于事后核验"这批图是谁渲的")。

    返回 dict: {"mode": "bpy-module"|"exe"|"env", "path": ..., "version": ...}
    """
    cmd = blender_command()
    is_shim = (len(cmd) >= 2 and os.path.basename(cmd[0]).lower().startswith("python")
               and cmd[1].endswith("blender_shim.py"))
    info = {"mode": "bpy-module" if is_shim else "exe", "path": cmd[0]}
    if is_shim:
        info["shim"] = cmd[1]
    try:
        import bpy  # noqa: F401  (仅取版本, 不渲染)
        info["version"] = bpy.app.version_string
    except Exception as e:
        info["version"] = f"unknown ({type(e).__name__})"
    return info


# --------------------------------------------------------------------------- #
# Cycles 计算设备
# --------------------------------------------------------------------------- #
def cycles_device_candidates():
    """返回本次尝试的 compute_device_type 列表 (空列表 = 只走 CPU)。"""
    override = os.environ.get(CYCLES_DEVICE_ENV, "").strip().upper()
    if override:
        return [] if override in ("NONE", "CPU") else [override]
    if os.environ.get(FORCE_CPU_ENV, "").strip() not in ("", "0", "false", "False"):
        return []
    return list(CYCLES_TYPES_BY_PLATFORM.get(sys.platform, ["OPTIX", "CUDA", "HIP", "ONEAPI"]))


def configure_cycles(scene=None, samples=None, denoise=True, prefer_gpu=True):
    """在 Blender 内选择可用的 Cycles 计算设备。

    返回 (device_type, gpu_device_count): device_type 为实际选中的后端名
    ("OPTIX"/"CUDA"/"HIP"/"ONEAPI"/"METAL"), 无可用 GPU 时返回 ("CPU", 0)。
    """
    import bpy

    sc = scene if scene is not None else bpy.context.scene
    sc.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences

    chosen, count = "CPU", 0
    for backend in cycles_device_candidates():
        try:
            prefs.compute_device_type = backend
        except (TypeError, ValueError):
            continue  # 该平台/该 Blender 构建不提供此后端
        try:
            prefs.get_devices()
        except Exception:
            pass
        devices = list(getattr(prefs, "devices", []))
        gpu_devices = [d for d in devices if d.type == backend]
        if not gpu_devices:
            continue
        for d in devices:
            d.use = d.type == backend
        chosen, count = backend, len(gpu_devices)
        break

    sc.cycles.device = "GPU" if (chosen != "CPU" and prefer_gpu) else "CPU"
    if samples is not None:
        sc.cycles.samples = samples
    if denoise:
        sc.cycles.use_denoising = True
    print(f"[cycles] backend={chosen} devices={count} scene_device={sc.cycles.device}")
    return chosen, count


# --------------------------------------------------------------------------- #
# 内存探测 (跨平台)
# --------------------------------------------------------------------------- #
def available_memory_gb():
    """返回当前可用物理内存 (GB)。探测失败返回 float('inf') = 不阻拦。"""
    try:
        import psutil  # type: ignore

        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        pass

    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", "r") as fh:
                for line in fh:
                    if line.startswith("MemAvailable:"):
                        return int(line.split()[1]) / (1024 * 1024)
        except Exception:
            pass

    if os.name == "nt":
        try:
            import ctypes

            class _MemoryStatusEx(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            status = _MemoryStatusEx()
            status.dwLength = ctypes.sizeof(_MemoryStatusEx)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.ullAvailPhys / (1024 ** 3)
        except Exception:
            pass

    if sys.platform == "darwin":
        try:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=10).stdout
            page = int(out.split("page size of")[1].split()[0])
            free = inactive = spec = 0
            for line in out.splitlines():
                if line.startswith("Pages free"):
                    free = int(line.split(":")[1].strip().rstrip("."))
                elif line.startswith("Pages inactive"):
                    inactive = int(line.split(":")[1].strip().rstrip("."))
                elif line.startswith("Pages speculative"):
                    spec = int(line.split(":")[1].strip().rstrip("."))
            return (free + inactive + spec) * page / 2 ** 30
        except Exception:
            pass

    return float("inf")


# --------------------------------------------------------------------------- #
# torch / diffusers 设备
# --------------------------------------------------------------------------- #
def torch_device(prefer=None):
    """解析 SD/ControlNet 设备: 显式偏好 > CUDA > MPS > CPU。"""
    override = os.environ.get(TORCH_DEVICE_ENV, "").strip().lower()
    if prefer:
        return prefer
    if override:
        return override
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def torch_generator(device, seed):
    """跨平台 torch.Generator (MPS Generator 仅存在于 torch>=2.0)。"""
    import torch  # type: ignore

    try:
        return torch.Generator(device=device).manual_seed(seed)
    except Exception:
        return torch.Generator().manual_seed(seed)


def temp_dir():
    """跨平台临时目录 (替代硬编码 /tmp)。"""
    import tempfile

    return tempfile.gettempdir()
