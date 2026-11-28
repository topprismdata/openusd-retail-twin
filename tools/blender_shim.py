#!/usr/bin/env python
"""Windows 上的 "blender" 命令替身 (基于 bpy pip 模块)。

用途: 官方 Blender 发行版是 ~350MB 的 zip/安装包, CI 与批量环境不便分发;
PyPI 上的 `bpy` wheel 提供同一套 Python API (本仓库脚本只用 bpy/bmesh/mathutils),
因此可以用一个薄壳把 `blender -b -P <script.py> [-- <args>]` 的调用形式映射到模块执行。

用法:
    BLENDER_PYTHON=/path/to/python.exe python tools/blender_shim.py -b -P script.py -- --sku demo_organic
    # 或者直接让 tools/blender.cmd 转发到本脚本

支持: -b / --background (忽略) / --factory-startup (忽略) / -P <script> / -- <args...>
不支持: -a (渲染动画帧序列) / -o (输出路径) 等交互式与多帧参数 —— 仓库脚本未使用。
"""
import runpy
import sys


def main(argv):
    script = None
    passthrough = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("-b", "--background", "--factory-startup", "-noaudio", "-d", "-noaudio"):
            i += 1
            continue
        if a == "-P" and i + 1 < len(argv):
            script = argv[i + 1]
            i += 2
            continue
        if a == "--":
            passthrough = argv[i + 1:]
            break
        i += 1

    if not script:
        print("[blender_shim] 缺少 -P <script>", file=sys.stderr)
        return 2

    # Blender 的脚本参数形态: sys.argv = [<script>, "--", *args]
    sys.argv = [script] + (["--"] + passthrough if passthrough else [])
    print(f"[blender_shim] exec {script} argv={sys.argv}", file=sys.stderr)
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
