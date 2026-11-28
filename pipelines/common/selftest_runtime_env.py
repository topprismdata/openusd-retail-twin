"""runtime_env 自检 (纯 Python, 无需 Blender / bpy)。

用法: python3 pipelines/common/selftest_runtime_env.py
退出码 0 = 全部通过。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pipelines.common import runtime_env as rt  # noqa: E402

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name} {detail}")
        FAILURES.append(name)


def main():
    print("[1] Blender 路径解析")
    os.environ.pop("BLENDER_BIN", None)
    check("blender_bin() 返回非空", bool(rt.blender_bin()), rt.blender_bin())
    check("blender_candidates() 非空", len(rt.blender_candidates()) > 0)
    os.environ["BLENDER_BIN"] = "/custom/blender"
    check("BLENDER_BIN 覆盖生效", rt.blender_bin() == "/custom/blender")
    os.environ.pop("BLENDER_BIN", None)

    print("[2] Cycles 后端候选")
    os.environ.pop("CYCLES_DEVICE", None)
    os.environ.pop("FORCE_CPU_RENDER", None)
    cands = rt.cycles_device_candidates()
    check("候选非空", len(cands) > 0, str(cands))
    if sys.platform == "darwin":
        check("macOS 只用 METAL", cands == ["METAL"], str(cands))
    else:
        check("非 macOS 优先 OPTIX/CUDA", cands[0] in ("OPTIX", "CUDA"), str(cands))
    os.environ["CYCLES_DEVICE"] = "CUDA"
    check("CYCLES_DEVICE 覆盖", rt.cycles_device_candidates() == ["CUDA"])
    os.environ["CYCLES_DEVICE"] = "NONE"
    check("CYCLES_DEVICE=NONE -> CPU", rt.cycles_device_candidates() == [])
    os.environ.pop("CYCLES_DEVICE", None)
    os.environ["FORCE_CPU_RENDER"] = "1"
    check("FORCE_CPU_RENDER -> 无 GPU 候选", rt.cycles_device_candidates() == [])
    os.environ.pop("FORCE_CPU_RENDER", None)

    print("[3] 内存探测")
    mem = rt.available_memory_gb()
    check("返回正数或 inf", mem > 0, str(mem))
    check("量级合理 (<1TB)", mem < 1024, str(mem))

    print("[4] torch 设备")
    os.environ.pop("TORCH_DEVICE", None)
    dev = rt.torch_device()
    check("设备在已知集合内", dev in ("cuda", "mps", "cpu"), dev)
    os.environ["TORCH_DEVICE"] = "cpu"
    check("TORCH_DEVICE 覆盖", rt.torch_device() == "cpu")
    os.environ.pop("TORCH_DEVICE", None)

    print("[5] 临时目录")
    check("temp_dir() 存在", os.path.isdir(rt.temp_dir()), rt.temp_dir())

    print("[6] Cycles GPU 实际可用性 (需要 bpy)")
    # 2026-11-24 加: 光测"候选非空"不够 —— 真正的问题是**设备枚举拿不到设备**
    # (Blender 5.x 里 get_devices() 不刷新设备列表, 要用 refresh_devices()),
    # 结果是静默退回 CPU 而产物里还写着 cycles_device=null。
    # 这里实际调一次 configure_cycles, 把真正生效的后端与设备数打出来。
    try:
        import bpy  # noqa: F401
        # configure_cycles 会改 Blender 的全局偏好 (compute_device_type / 设备 use 标志),
        # 这里先存后还原 —— 自检不该给同进程的后续渲染留下副作用。
        prefs = bpy.context.preferences.addons["cycles"].preferences
        saved_type = prefs.compute_device_type
        saved_use = {d.id: d.use for d in prefs.devices}
        try:
            backend, ndev = rt.configure_cycles(samples=1, denoise=False)
            forced_cpu = os.environ.get("FORCE_CPU_RENDER", "").strip() not in ("", "0", "false", "False")
            if forced_cpu:
                check("强制 CPU 时后端为 CPU", backend == "CPU", backend)
            else:
                check("GPU 后端可选 (OPTIX/CUDA/HIP/ONEAPI/METAL)",
                      backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"), backend)
                if backend == "CPU":
                    print(f"        NOTE 机器上没有可用 GPU 后端 -> 渲染会走 CPU "
                          f"(这本身不是错误, 但要记住渲染耗时按 CPU 估)")
                else:
                    check("GPU 设备数 > 0", ndev > 0, str(ndev))
        finally:
            try:
                prefs.compute_device_type = saved_type
                for d in prefs.devices:
                    if d.id in saved_use:
                        d.use = saved_use[d.id]
            except Exception:
                pass
    except Exception as e:
        print(f"  SKIP  无法导入 bpy ({type(e).__name__}: {e}) —— 跳过 GPU 实测")

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)} 项 -> {FAILURES}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
