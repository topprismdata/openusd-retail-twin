---
description: The Blender renderer has a fixed CLI contract. Its arguments go after `--`, and the output directory flag is `--out`. A direct `python ..._inspector.py` call silently runs with defaults and can wipe the previous dataset.
condition: "(python[0-9.]*(?:\\.exe)?\\s+[^\\n]*02_shelf_sdg_inspector\\.py)|(--out-dir)"
scope: tool:bash
interruptMode: never
repeatMode: after-gap
agents: main
---
[渲染器 CLI 契约提醒] 这条命令违反了 `02_shelf_sdg_inspector.py` 的调用契约。

契约：
```sh
blender -b -P pipelines/shelf_sdg/02_shelf_sdg_inspector.py -- --num-images 200 --out output/sdg_shelf
```
- 参数必须写在 `--` 之后。脚本按 `sys.argv` 里 `--` 之后的部分取参；直接 `python xxx.py --num-images 200`
  不会报错，而是走默认值。
- 输出目录参数是 `--out`，不是 `--out-dir`。
- 新建输出目录前，脚本会清掉该目录下的旧产物。参数写错时，清掉的是**上一轮**的对照组。

改用上面的 `blender -b -P ... -- ...` 形式。跑之前先确认 `--out` 指向的目录
不是你要保留的对照数据。
