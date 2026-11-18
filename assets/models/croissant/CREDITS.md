# Croissant 资产授权凭据 (P0 审计整改)

## 资产
- 来源: Poly Haven — **Croissant** (photogrammetry scan)
  页面: https://polyhaven.com/a/croissant (快照日期 2026-11-13)
- 作者: Dario Barresi (Scanning), Greg Zaal (Processing)
- 许可证: **CC0 1.0 Universal** (页面明示 "[CC0] License", 站点许可证页
  https://polyhaven.com/en/license 声明全部资产 CC0, 含商用/无需署名)
- 尺寸标称: 0.2m wide, 最高 8K 纹理; 本仓采用 **4K glTF 变体**
  (`croissant_4k.gltf` + `croissant.bin` + `textures/`)

## 仓内文件
- `croissant_4k.gltf` / `croissant.bin` / `textures/`
- 使用位置: 两条交付分支白瓷盘上 (34_commercial_repro.py `import_croissant()`)

## 审计状态
- [x] 来源页面在线且明示 CC0 (2026-11-13 快照)
- [x] 作者与工艺记录 (Dario Barresi / Greg Zaal)
- [ ] **字节同一性**: 本仓副本与 Poly Haven 当前 4k glTF 下载未做逐字节核对
      (无下载回执存档)。若需更强审计, 重新下载 4k glTF 并 diff。
      依据: 文件名/结构 (gltf+bin+textures, 4k) 与 docstring 台账一致。
- CC0 无需署名; 本文件为自愿归档, 不构成许可条件。
