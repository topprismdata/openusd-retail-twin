# NOTICE

本文件记录 `topprismdata/openusd-retail-twin` 的第三方组件与素材署名要求。

## 1. 许可分层

| 范围 | 许可 | 说明 |
|---|---|---|
| 本仓自研代码（`pipelines/`、`run_pipeline.py`、`pipelines/common/`、`specs/`） | Apache-2.0 | 见 `LICENSE`（全文 Apache-2.0） |
| 第三方 Python 依赖 | 各自上游许可 | 见 `requirements.txt` 顶部清单；`ultralytics` 为 AGPL-3.0（商用闭源需授权） |
| Blender / bpy | GPL | 作为独立进程调用，本仓不分发其二进制 |
| `assets/` 下的第三方模型 / 贴图 / HDRI / 字体 | **各自上游许可，未被本仓重新授权** | 逐项见 `docs/ASSET_CREDITS.md` |

> 使用 `assets/` 中任何素材前，必须先读该素材目录下的 `CREDITS.md` / `license*.txt`，
> 并按其要求署名、保留许可声明、确认是否允许商用（CC-BY-NC / 仅研究用途的素材不得用于客户交付）。

## 2. 署名模板（按上游许可填写后随交付物附带）

```
本项目使用了以下第三方资源：

- 名称: <资源名>
  来源: <原始 URL>
  作者: <作者/机构>
  许可: <SPDX 标识 + 许可链接>
  改动: <说明: 重拓扑 / 定标 / 贴图重建 / 品牌化处理>

本仓库内的第三方素材保留其原始许可，不适用本仓库的 Apache-2.0 授权。
```

## 3. 本仓自有品牌资产

- `Topprism®` 虚拟产品（酸奶杯 / 标签 / 展示图）：本仓自建虚拟演示 SKU，非在售商品，标签与盖膜强制印制「虚拟演示产品 · 非销售品」。
- `docs/images/topprism/`、`output/github_topprism/` 下的产出物同属该虚拟 SKU。

## 4. 第三方资产署名清单（CC-BY 必须在**交付物**中带上）

以下 8 个 Sketchfab 模型为 **CC-BY-4.0**（允许商用，但**必须署名**）。仓库此前只在
`assets/models/zoo/lic_*.txt` 里留了许可快照，`docs/ASSET_CREDITS.md` 未列，**署名义务未闭合**。
对外交付含这些资产的图/页/文档时，须附上对应 credit line：

```
This work is based on "Cereal Box \"Nutty Nuts\"" (https://sketchfab.com/3d-models/cereal-box-nutty-nuts-070e0d3816bb444e883533a7297b3da7) by pateodor (https://sketchfab.com/pateodor) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

This work is based on "Spray Bottle" (https://sketchfab.com/3d-models/spray-bottle-1611833f3eaa41bbba2b6944269429ab) by Anthony Yanez (https://sketchfab.com/paulyanez) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

This work is based on "Coffee Paper Bag 3D Scan" (https://sketchfab.com/3d-models/coffee-paper-bag-3d-scan-4873908248a04f7b9af32a58a1918a28) by grafi (https://sketchfab.com/zdenkoroman) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

This work is based on "Mason Jar" (https://sketchfab.com/3d-models/mason-jar-6414d60acf08412abbf80ad0a60fcebe) by macintij (https://sketchfab.com/macintij) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

This work is based on "Fashion Figure Base" (https://sketchfab.com/3d-models/fashion-figure-base-644b113218b94c94b5f07be0b6f455a3) by Tiko (https://sketchfab.com/tikoavp) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

This work is based on "CC0 - Candies" (https://sketchfab.com/3d-models/cc0-candies-8dd602aff1204c548105462cccd492d6) by plaggy (https://sketchfab.com/plaggy) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

This work is based on "CC0 - Tin Can Box" (https://sketchfab.com/3d-models/cc0-tin-can-box-c4ca0de729654551b75d9358485b1e4e) by plaggy (https://sketchfab.com/plaggy) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)

This work is based on "Headphones Free Model by Oscar Creative" (https://sketchfab.com/3d-models/headphones-free-model-by-oscar-creative-db92168ca39541939d0110e64a37f92e) by OSCAR CREATIVO (https://sketchfab.com/oscar_creativo) licensed under CC-BY-4.0 (http://creativecommons.org/licenses/by/4.0/)
```

其余第三方资产（蓝莓 / 玻璃杯 / 可颂 / 草莓 / 运动鞋 Sketchfab 线 / 桌面纹理 / HDRI）的 credit line 见
`docs/ASSET_CREDITS.md`；本文件不重复。

## 5. 已知需要复核的条目

| 条目 | 状态 | 动作 |
|---|---|---|
| `assets/models/sneaker_trellis/PROVENANCE.json` 记录的输入图 | **Dreamstime 图库预览图**（免费下载通常仅限编辑用途）。**更正：该 JPG 本身不在仓内**，仓内只有这份 429 B 的来源记录（url + sha256），不构成再分发 | 论文/发布前：把来源换成可引用条目，或改用可公开引用的输入图；若日后把该图放入仓库，需先取得订阅/授权 |
| `assets/models/zoo/` 8 个模型 | 许可为 CC-BY-4.0（允许商用），但 `docs/ASSET_CREDITS.md` 未列，署名义务未闭合 | 已在本文件第 4 节补齐 credit line；同时把 `docs/ASSET_CREDITS.md` 章节编号修正（现存在重复的 "## 4."） |
| `assets/models/strawberry/license_page.html` | 上游页面快照，页面可能已变更 | 改为保存带时间戳的许可摘录，勿固化整页 HTML |
| `assets/models/croissant/CREDITS.md` | 自述"与源站 4k glTF 未逐字节核对（无下载回执）" | 补下载回执或校验值 |
| `yolo11n.pt`（仓根） | Ultralytics 权重（AGPL-3.0 生态） | `git rm --cached yolo11n.pt`，改为首次运行自动下载，并在 README/requirements 保留 AGPL 提示 |
| **`assets/hdri/brown_photostudio_01_4k.hdr`（25.5MB）与 `studio_small_08_2k.hdr`** | **无任何许可主张**，但被 5 个脚本引用 | 在线核验 polyhaven 来源并补进 `docs/ASSET_CREDITS.md`；否则从仓内移除 |
| `assets/models/strawberry/textures/*.png`（5.3MB）、`assets/textures/{shelf_pop_header,shelf_price_strip*,case_grille,floor_tiles}.png` | 无许可记录；其中货架 POP / 价签疑为实拍门店裁切（含真实品牌 POP） | 补来源或替换为程序化生成；与 README 的"不含品牌印刷文件"冲突 |
| `assets/web/model-viewer.min.js`（935KB, Apache-2.0） | 无 LICENSE/NOTICE；且画廊实际从 CDN 加载，仓内这份**未被引用** | `git rm --cached`（或补 Apache-2.0 LICENSE/NOTICE） |
| `assets/texverse/shortlist.json` | 已被 `.gitignore` 忽略却仍被 git 跟踪；内含 ShareAlike 条目与受商标保护商品名 | `git rm --cached assets/texverse/shortlist.json` |
| **SKU-110K 评测数据集** | 上游条款：**仅供接收者专有、仅限学术与非商业用途** | 本仓四臂结论**不得**进入客户提案或商业交付物；对外展示须换用可商用数据集复跑 |
| 字体（渲染用） | macOS 系统字体路径（已改为跨平台解析，见 `pipelines/common/fonts.py`） | 跨平台商业交付建议改用 OFL 字体（Noto Sans CJK / 思源黑体）并在 NOTICE 登记 |
