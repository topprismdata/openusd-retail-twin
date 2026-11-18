# GitHub 展示资源 · Topprism 虚拟酸奶产品

> 用途：公开 GitHub 仓库的封面/展示图。品牌 = 我方公司自有品牌（棱镜极智能 / Topprism, topprismdata.com），
> 产品为**虚拟演示 SKU（非在售、无真实条码）**，避免公开仓库出现真实客户品牌素材的合规风险。

## 资产清单

| 文件 | 内容 | 来源 |
|---|---|---|
| `yog_three_quarter.png` | 主图 · 三四视图 1920² | `pipelines/topprism_virtual/33_topprism_yogurt_cup.py` Blender/Cycles Metal |
| `yog_label_front.png` | 标签正面特写 1920² | 同上 |
| `yog_front.png` / `yog_close.png` / `yog_lid.png` | 正视 / 近摄 / 盖顶 1400² | 同上 |
| `yog_lifestyle_gpt.png` | 早餐生活方式场景图 | ChatGPT 文生图（relay 驱动） |
| `cup_label.png` | 杯身标签贴图 2048×560（杯面实比） | `pipelines/topprism_virtual/32_topprism_yogurt_label.py` PIL |
| `lid_texture.png` | 盖膜贴图 1024² | 同上 |
| `topprism_logo.png` | 公司 GitHub 组织头像（品牌 logo 同源） | github.com/topprismdata |

## 设计语言
- Logo：蓝→紫渐变空心三角（棱镜）——取自公司 GitHub org 头像（`#2F6BF0 → #8B3CF0 → #0090F0`）
- 母题：棱镜色散 → 光谱条
- 强制标注：`虚拟演示产品 · 非销售品 · TOPPRISM DATA`（标签与盖膜均印）

## README 引用片段（直接粘贴）

```markdown
<p align="center">
  <img src="docs/images/topprism/yog_three_quarter.png" width="420" alt="Topprism 虚拟酸奶">
  <img src="docs/images/topprism/yog_label_front.png" width="420" alt="标签特写">
</p>

> 演示资产：Topprism® 虚拟酸奶杯（自有品牌，非在售）——参数化建模 + Cycles 渲染 +
> 程序化标签生成全链路，替代真实客户品牌用于公开仓库展示。
```

## 合规边界
- 虚拟条码 `690123 45678` 为占位图案，非真实 GS1 编码商品。
- 公开仓库不得包含真实客户品牌的印刷像素与刀版素材（见 `.gitignore` 边界清单）——真实品牌素材保持私有。