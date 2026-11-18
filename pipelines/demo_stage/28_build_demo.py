#!/usr/bin/env python3
"""28 - 单文件对外 Demo 页生成器: 全部证据 base64 内嵌 (JPEG q88), 双击即开, 微信可传。
用法: python3 28_build_demo.py
产物: output/demo/retail_twin_demo.html
"""
import base64
import io
import os

from PIL import Image

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(BASE, "output", "demo")
os.makedirs(OUT, exist_ok=True)

CM = os.path.join(BASE, "output", "creative_matrix")
BM = os.path.join(BASE, "output", "benchmark")
OA = os.path.join(BASE, "output", "open_assets", "texverse_v2")
ORG_DIR = os.path.join(BASE, "output", "multi_platform", "demo_organic")


def b64_jpeg(path, max_w=1600, q=88, crop=None):
    im = Image.open(path).convert("RGB")
    if crop:
        im = im.crop(crop)
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def img(path, caption="", max_w=1600):
    if not os.path.exists(path):
        return f'<div class="miss">缺图: {os.path.basename(path)}</div>'
    c = f'<figcaption>{caption}</figcaption>' if caption else ""
    return f'<figure><img src="{b64_jpeg(path, max_w)}" loading="lazy"/>{c}</figure>'


CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;background:#fafaf8;color:#1a1a1a;line-height:1.7}
.wrap{max-width:1080px;margin:0 auto;padding:0 28px 80px}
header{background:#0d2b1e;color:#fff;padding:64px 28px 56px;text-align:center}
header h1{font-size:34px;letter-spacing:2px;font-weight:700}
header p{margin-top:14px;font-size:17px;color:#bcd8c8}
header .tag{display:inline-block;margin-top:22px;font-size:13px;color:#0d2b1e;background:#e8f3ec;border-radius:20px;padding:6px 18px}
h2{font-size:24px;margin:64px 0 8px;padding-left:14px;border-left:5px solid #0d2b1e}
h2+p.lead{color:#555;font-size:15px;margin-bottom:20px}
figure{margin:18px 0}
figure img{width:100%;border-radius:10px;box-shadow:0 4px 24px rgba(0,0,0,.09)}
figcaption{font-size:13px;color:#777;text-align:center;margin-top:8px}
.miss{background:#fdd;color:#900;padding:8px 14px;border-radius:6px;font-size:13px}
table{width:100%;border-collapse:collapse;margin:16px 0;font-size:14.5px}
th{background:#0d2b1e;color:#fff;font-weight:600;padding:10px 12px;text-align:left}
td{padding:10px 12px;border-bottom:1px solid #e5e5e0;vertical-align:top}
tr:nth-child(even) td{background:#f6f6f3}
.cards{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:18px 0}
.card{background:#fff;border:1px solid #e8e8e3;border-radius:12px;padding:22px;box-shadow:0 2px 12px rgba(0,0,0,.05)}
.card h3{font-size:17px;color:#0d2b1e;margin-bottom:10px}
.card .num{font-size:30px;font-weight:800;color:#1a6b45}
.card p{font-size:14px;color:#444}
.big{font-size:20px;font-weight:700;color:#1a6b45}
.quote{background:#f0f7f2;border-left:4px solid #1a6b45;padding:16px 20px;border-radius:0 8px 8px 0;margin:18px 0;font-size:15px}
.warn{background:#fdf6ec;border-left:4px solid #c98a2b;padding:14px 18px;border-radius:0 8px 8px 0;margin:14px 0;font-size:13.5px;color:#7a5b1e}
footer{margin-top:70px;padding-top:24px;border-top:1px solid #ddd;font-size:12.5px;color:#888}
footer a{color:#1a6b45;text-decoration:none}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;margin:18px 0}
.grid3 img{border-radius:10px;box-shadow:0 3px 14px rgba(0,0,0,.08);width:100%}
.badge{display:inline-block;font-size:12px;padding:2px 10px;border-radius:10px;margin-right:6px}
.ok{background:#e6f4ea;color:#1a6b45}
.half{background:#fdf6ec;color:#8a6216}
.co{background:#e6f4ea;color:#1a6b45;border:1px dashed #1a6b45}
.steps{display:flex;align-items:center;gap:10px;margin:18px 0}
.step{flex:1;background:#fff;border:1px solid #e8e8e3;border-radius:12px;padding:14px;box-shadow:0 2px 12px rgba(0,0,0,.05)}
.step img{width:100%;border-radius:8px}
.step p{font-size:13.5px;color:#555;text-align:center;margin-top:10px}
.step-tag{display:inline-block;font-size:14px;font-weight:700;border-radius:14px;padding:3px 14px;margin-bottom:10px}
.g1{background:#eee;color:#666}
.g2{background:#e8f0e4;color:#3d6b35}
.g3{background:#0d2b1e;color:#ffd76e}
.arrow{font-size:30px;color:#1a6b45;font-weight:800;flex:0 0 auto}
.note{font-size:13px;color:#777;margin-top:6px}
"""

HTML = f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>零售商品数字孪生 · OpenUSD 母本管线 Demo</title>
<style>{CSS}</style></head>
<body>
<header>
  <h1 style="font-size:30px">一次建立可信商品资产，多平台、多场景持续复用</h1>
  <p style="font-size:16px;color:#bcd8c8">解决三个业务问题: 包装一致性 · 制作效率 · 创意复用</p>
  <div style="margin-top:20px">
    <span style="display:inline-block;font-size:14px;font-weight:600;color:#0d2b1e;background:#e8f3ec;border-radius:8px;padding:8px 18px;margin:0 4px">技术可行性 Demo</span>
    <span style="display:inline-block;font-size:14px;font-weight:600;color:#7a5b1e;background:#fdf2d9;border-radius:8px;padding:8px 18px;margin:0 4px">商业 ROI 待试点验证</span>
    <span style="display:inline-block;font-size:14px;font-weight:600;color:#0d2b1e;background:#dcebe2;border-radius:8px;padding:8px 18px;margin:0 4px">100% 离线 MacBook 生成</span>
  </div>
  <p style="margin-top:16px;font-size:12.5px;color:#8fae9c">需要品牌方提供: 官方 VI 稿与品牌授权素材 (当前包装为研究重建, 非官方认证资产)</p>
</header>
<div class="wrap">

<h2>① 同一 SKU 的三种输出任务 + 管线演进</h2>
<p class="lead">下面三张是<b>同一经典有机母本</b>的三种输出任务: 电商白底 / 天猫场景 / 牛奶飞溅。同母本同管线, 仅切换输出参数——证明的是<b>生产管线控制变量能力</b>, 不是图片质量的严格比较。</p>
<div class="grid3">
<img src="{b64_jpeg(os.path.join(ORG_DIR, '01_JD_WhiteBG_800x800.png'))}"/>
<img src="{b64_jpeg(os.path.join(ORG_DIR, '02_Tmall_Hero_1x1_1600x1600.png'), crop=(612, 96, 1134, 1470))}"/>
<img src="{b64_jpeg(os.path.join(CM, 'splash_demo_organic.png'), max_w=800)}"/>
</div>
<figcaption>电商白底 800² · 天猫场景 1:1 (裁切至经典有机单盒; 原图为经典双品同框构图) · 牛奶飞溅 1920² (流体管线) —— 同一有机母本, 输出受控可复现</figcaption>
<div class="warn" style="margin-top:10px"><b>演进示意 (非受控对照)</b>: 下板展示管线能力演进方向; 其中"白底平拍/场景图"代表行业现状两种生产方式, "孪生微距×变体"为本管线新增能力。严格同视角对照与逐项耗时标注在试点首周补齐。</div>
{img(os.path.join(BM, "three_generations.png"), "管线演进示意板: 白底平拍 → 场景图 → 孪生微距×变体")}

<h2>② 价值阶梯: 证据分级呈现</h2>
<table>
<tr><th>层级</th><th>价值主张</th><th>本 Demo 已验证</th><th>尚未验证 (待试点/外部证据)</th></tr>
<tr><td><b>L1</b> 拍摄省钱</td><td>免重复棚拍降低成本</td><td>— (管线可跑通, 未记财务账)</td><td>~50% 成本降低来自<b>联合利华官方口径</b>, 不自动迁移本项目</td></tr>
<tr><td><b>L2</b> 全球一致性</td><td>一次母本全渠道统一</td><td>同母本 4 平台输出一致 (§⑤)</td><td>包装一致性独立评分 (字符准确率/结构偏差) 待建立</td></tr>
<tr><td><b>L3</b> 平台自由度</td><td>四平台构图一键裂变</td><td>✓ 经典有机 4 平台实渲</td><td>各平台安全区/可读性规范符合性待逐项核验</td></tr>
<tr><td><b>L4</b> 规模化敏捷</td><td>多 SKU 换标小时级</td><td>✓ 8 SKU 一键换标实渲</td><td>增量工时/失败返工的独立效率基准待测量</td></tr>
<tr><td><b>L5</b> 创意资产复利</td><td>母本成为创意生产系统</td><td>✓ 3 创意方向技术打通 (§⑥, 探索级)</td><td>经营收益不宣称; 创意规模化能力待 Brief→参数链路验证</td></tr>
</table>

<h2>③ 双巨头官方实证: 行业可行性证据</h2>
<div class="cards">
<div class="card"><h3>联合利华 × NVIDIA Omniverse</h3>
<span class="big">≈2× 速度 · ≈50% 成本 · 5:1 重复制作比</span>
<p>OpenUSD 商品母本保存结构/材质/印刷/语言变体/灯光/机位与获批感官特效; Dove/TRESemmé 等全球品牌已运行。</p>
<p style="font-size:12px;color:#777;margin-top:8px">口径: 联合利华官方应用效果, 测量对象为其全球内容生产体系 · <a href="https://www.nvidia.com/en-us/case-studies/unilever/" style="color:#1a6b45">nvidia.com/en-us/case-studies/unilever</a> · GTC 2025 S71412</p></div>
<div class="card"><h3>雀巢 (2025-06-11 官宣)</h3>
<span class="big">OpenUSD + Omniverse 内部孪生内容服务</span>
<p>覆盖 Nescafé Dolce Gusto / Nespresso / Purina, 目标=规模化生成电商与数字媒体商品视觉。</p>
<p style="font-size:12px;color:#777;margin-top:8px">口径: 雀巢官方公告, 证实 USD/Omniverse 管线存在; 不据此宣称其既有 CGI 广告均接入该管线 · <a href="https://www.nestle.com/media/news/brands-ai-digital-twins-content-service" style="color:#1a6b45">nestle.com/media/news/brands-ai-digital-twins-content-service</a></p></div>
</div>
<div class="quote"><b>方法论三分纪律</b> (外部评审确认): 商品数字孪生 (可验证母本) ≠ CGI 创意 (飞溅/超现实) ≠ AI 生图 (快但包装不可信)。最有说服力的展示 = 三者结合。<b>外部案例只证明行业可行性, 不替代本项目自身实证。</b></div>

<h2>④ 国内市场修正判断</h2>
<div class="quote">国内<b>不缺创意</b>: 头部白奶沙漠实景联名、高端鲜奶×影视IP (18.1 亿曝光)、新兴牧场城市互动、奶酪IP化。<br/>
<b>真正缺位</b>: 把一次性创意沉淀为<b>可重复生成、可验证、可跨渠道复用的孪生资产系统</b>——创意是一次性事件, 资产才有复利。</div>

<h2>⑤ 平台自由度与规模化敏捷 (L3/L4 实证)</h2>
<p class="lead">准确口径: <b>8 款 SKU 一键换标 (白底) + 1 款 SKU 四画幅验证</b>, 尚无 32 张全组合独立输出; 参数档案覆盖 13 SKU (其余 5 款仅模板能力)。画幅适配是平台规范的必要非充分条件, 安全区/可读性核验待做。</p>
{img(os.path.join(BM, "matrix_wall.png"), "换标×画幅矩阵墙: 8 SKU 白底换标 + 经典有机四画幅, 同一母本输出")}

<h2>⑥ 创意三方向 · 技术探索样张 (未达摄影级验收)</h2>
<p class="lead">同一母本的 N 种表达 — <b>管线能力打通证明</b>, 不是成品级创意交付。诚实分级: 飞溅=流体管线已打通 (液膜连续性/液滴尺度待优化) · 酸奶=方向验证 (物性表达未达商业可用) · 早餐=叙事雏形 (道具/生活痕迹待补)。</p>
{img(os.path.join(BM, "creative_matrix.png"), "最小验证矩阵: 3 SKU × 3 创意方向 (探索样张)")}

<h2>⑦ 验收框架: 不比"哪张好看", 比系统</h2>
<table>
<tr><th>验证维度</th><th>要求</th><th>本 demo 状态</th></tr>
<tr><td>资产准确性</td><td>包装结构/字体/图案/净含量真实准确</td><td><span class="badge half">🔶 参数可追溯 ≠ 包装真实准确; 需官方四视角保真验收</span></td></tr>
<tr><td>创意扩展</td><td>同一 SKU 生成白底/飞溅/微距/场景</td><td><span class="badge ok">✓ 三方向 9 图</span></td></tr>
<tr><td>变体生产</td><td>3 SKU × 3 创意 × 3 渠道全通过</td><td><span class="badge half">🔶 已有: 8 SKU 换标 + 1 SKU 四画幅 + 3 创意探索; 全组合未核验</span></td></tr>
<tr><td>生产效率</td><td>母本成本 / 单张边际成本 / 修正时间</td><td><span class="badge co">共创项 · 试点首周即可记账闭环</span><div class="note">管线全程已埋点计时, 只差财务口径确认——这正是本 demo 为客户把关的起点</div></td></tr>
<tr><td>商业价值</td><td>与传统商品图同流量 A/B</td><td><span class="badge co">共创项 · 需真实投放流量</span><div class="note">建议试点: 任选 1 个 campaign 的 A/B 资源位, 两周出对照数据</div></td></tr>
</table>
<div class="warn"><b>诚实边界</b>: ①所有包装为参数化复刻 (结构/印刷位/配色对齐官方, 文字细节以官方VI稿为准); ②酸奶微距质感为方向验证未到成品级; ③效率与转化两项待真实业务数据。本页是<b>管线能力证明</b>, 不是逐像素成品交付。</div>

<h2>⑦′ 保真验收: 四视角逐项检查 (试点动作①已执行)</h2>
{img(os.path.join(BM, "qa_board.png"), "四视角+旋盖细节+10 项检查清单: 2 项达标 / 4 项部分对齐 / 4 项占位 / 1 项待测 / 1 项需授权")}
<div class="note">当场抓到并如实记录: 侧条留白 (真实包装含竖排信息) · 旋盖滚花纹理未建 · 营养表为程序化占位。官方认证资产需 VI 授权素材 + 分光色差测量 + 官方字库比对。</div>

<h2>⑧ 技术底座</h2>
<table>
<tr><th>层</th><th>选型</th></tr>
<tr><td>母本</td><td>OpenUSD 规范 · 参数化 SKU 档案 (13 款) · DreamCap 旋盖 · MaterialX/UsdPreviewSurface</td></tr>
<tr><td>渲染</td><td>Blender Cycles + Apple Metal-RT · Studio HDRI (Poly Haven 4K) · Mantaflow 流体 · 全离线 Mac</td></tr>
<tr><td>资产扩展</td><td>TexVerse/DTC 8K 实扫 GLB 接入 · 开源资产白底/棚拍/特写三图管线</td></tr>
<tr><td>交付</td><td>本页单文件 (0.8MB, 全图内嵌) · 原图 1920px PNG · 24/25/26/27/29/30 一键复现脚本</td></tr>
<tr><td>效率账本 (实测)</td><td>受控渲染 <b>18.5 秒/张</b> (1600px, 192spp, Metal-RT, /usr/bin/time 实测) · 流体创意 ~1-3 分钟/张 (含 Mantaflow 烘焙) · 人工修订时间未系统记录 (待试点记账)</td></tr>
</table>

<footer>
<b>引用</b>: NVIDIA/Unilever 案例研究 (nvidia.com/en-us/case-studies/unilever) · 雀巢官宣 (nestle.com/media/news/brands-ai-digital-twins-content-service) · GTC 2025 S71412 · 外部评审报告 (output/benchmark/gpt_giants_report.md)<br/>
生成时间: 2026-11-09 · 数字孪生管线 · 全部图像 100% 程序化生成于 MacBook (Apple Silicon, Metal-RT)
</footer>
</div>
</body></html>"""

out = os.path.join(OUT, "retail_twin_demo.html")
open(out, "w").write(HTML)
print(f"[DEMO] {out} {os.path.getsize(out) / 1e6:.1f}MB")
