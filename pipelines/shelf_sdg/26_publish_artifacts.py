#!/usr/bin/env python3
"""把基准产物从 output/benchmark/ 发布到 docs/research/benchmark/ (随仓交付), 并刷新清单。

为什么需要这一步: output/ 被 .gitignore 排除, 所以**实验产物默认不入仓**; 但论文要引用的
数字必须有随仓版本 (带 sha256), 否则读者只能相信 README 里的文字。

发布哪些 (白名单, 避免把中间产物/大文件带进仓):
  budget_real*.json          每格点结果 (含 protocol_hash 与子集指纹)
  budget_seed_variance.*     seed 方差与配对比较
  paired_image_eval_*.*      逐图配对评测 (评测集侧检验)
  count_*.json               计数指标
  domain_gap_measure.json    域差距量化
  BUDGET_CURVE.md            曲线表 (由 21_annotation_budget.py --merge-only 生成)

**不发布**: 图像、标签、权重 (SKU-110K 许可明确禁止分发/衍生作品分发; 权重是否属衍生作品未界定)。
"""
import fnmatch
import json
import os
import shutil
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(BASE, "output", "benchmark")
DST = os.path.join(BASE, "docs", "research", "benchmark")

PATTERNS = ("budget_real*.json", "budget_seed_variance.*", "paired_image_eval_*.*",
            "count_*.json", "domain_gap_measure.json",
            # 2026-11-27: 官方 SimReady 验证 vs 本仓自研资产闸的对照产物 (82/83/84 号)
            "asset_self_gate.json", "simready_official_validation.json",
            "simready_vs_self_gate.*", "simready_packaging_effect.json", "simready_compliant_package.json", "asset_consume_check.json", "simready_usdcraft_sweep.*",
            # 2026-11-22: 新增的两个分析产物 (功效分析 / 剂量-反应) 也要随仓, 否则读者
            # 只能信 README 里的文字 —— 与上面的预算格点 json 同一原则。
            "power_analysis.*", "dose_response.*", "count_threshold_sweep.*",
            # 2026-11-22 晚: 已发布四臂的多种子汇总 (r0/r1/r2 各 3 个 seed)
            "fourarm_seed_variance.*",
            # 2026-11-23: 标注口径差实测 (审计 F7)
            "label_semantics.*",
            # 2026-11-23: R3 域对齐臂的协议对齐复跑 (脚本 38)
            "r3_protocol_matched.*",
            # 2026-11-23: 形状先验臂 (只动朝向因子, 脚本 41-43)
            "r1shape_arm.*",
            "shape_probe.*",
            "real_shape_profile.*",
            # 2026-11-25: sim2real 机制定位 (域内可学性) 与干预探针
            "domain_fit_probe.*",
            "syn2real_interventions.*",
            "spectral_gap.*",
            "input_probe.*",
            # 2026-11-25: 商品表面臂 (纹理臂) 与它的两个诊断产物
            #   texture_arm.json            -> 臂结果 (last-vs-last 配对)
            #   texture_geometry_parity.json -> 单变量前提 (几何逐帧相同) 的核对结果
            #   texture_arm_diagnosis.json  -> 机制诊断 (precision/recall 分解 + 可视化)
            "texture_arm.json",
            "texture_geometry_parity.json",
            "texture_arm_diagnosis.json",
            # 2026-11-25: 上下文剥离探针 (I-16) —— 真实上下文值多少
            "context_probe.json",
            # 2026-11-25: 真实货架墙臂 (I-17) —— 按探针机制改生成器的结果
            "shelfwall_arm.json",
            # 2026-11-26: I-18 上下文臂 + "商品定义收窄"的量化诊断
            "shelfwall_arm_ctx.json",
            "definition_narrowing.json",
            # 2026-11-26: I-19 训练时抑制上下文依赖臂
            "context_suppress_arm.json",
            # 2026-11-26: I-19 的机制探针 + 掩膜池单变量性核对
            "context_suppress_probe.json",
            "ctxsupp_pool_parity.json",
            # 2026-11-27: I-20 分工臂 (合成预训练+真实微调) 与 I-22 MixStyle 臂
            "pretrain_finetune_arm.json",
            "mixstyle_arm.json",
            # 2026-11-27: 排除链总图的数字清单 (74 号, 从各臂产物里读 ✓)
            "exclusion_chain.json",
            # 2026-11-27: I-26 真实标注训练预算轴 (73 号) + I-27 的机制探针 (67 号复用) ✓
            "real_budget_epoch_arm.json",
            "pretrain_finetune_probe.json",
            # 2026-11-28: 交付自洽验收 (完整性 / 净室可用性 / 统计口径分离, 91 号) ✓
            "delivery_audit.json")

CURVE_SRC = os.path.join(SRC, "budget_curve.md")
CURVE_DST = os.path.join(DST, "BUDGET_CURVE.md")

# 2026-11-23: 四臂的多种子复跑产物 (sku110k_r0_s43.json …) 要随仓 —— 用正则而不是通配,
# 否则 sku110k_r1_scenebest.json (敏感性复跑, 不是 seed 复跑) 会被混进来。
import re

ARM_SEED_RE = re.compile(r"^sku110k_(r\d+|r3pm|r1shape)_s\d+\.json$")


def main():
    if not os.path.isdir(SRC):
        raise SystemExit(f"[PUBLISH] 没有 {SRC} —— 先跑基准")
    os.makedirs(DST, exist_ok=True)
    copied = []
    for f in sorted(os.listdir(SRC)):
        if f.endswith(".tmp") or f.endswith(".lock") or f.startswith("."):
            continue
        if not (any(fnmatch.fnmatch(f, pat) for pat in PATTERNS)
                or ARM_SEED_RE.match(f)):
            continue
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, f))
        copied.append(f)
    if os.path.exists(CURVE_SRC):
        shutil.copy2(CURVE_SRC, CURVE_DST)
        copied.append("BUDGET_CURVE.md")
    # 仓内文本统一 LF (Windows 上写出来是 CRLF) —— 先归一再算哈希,
    # 否则 MANIFEST 里的 sha256 会与仓内实际文件对不上 (自检 28 会报不一致)。
    # 同时做**路径去本机化**: 产物里记的绝对路径带本机用户名, 发布版不该带。
    # (必须在这一步做 —— 发布目录每次都被本脚本从 output/ 重新拷贝覆盖。)
    sys.path.insert(0, os.path.join(BASE, "pipelines", "common"))
    from publish_paths import scrub_bytes
    for f in copied:
        p = os.path.join(DST, f)
        try:
            data = open(p, "rb").read()
        except OSError:
            continue
        if b"\x00" in data[:8000]:      # 二进制 (图) 不动
            continue
        norm = scrub_bytes(data.replace(b"\r\n", b"\n"))
        if norm != data:
            open(p, "wb").write(norm)
    # 刷新清单
    r = subprocess.run([sys.executable, os.path.join(BASE, "pipelines/shelf_sdg/24_publish_manifest.py")],
                       capture_output=True, text=True)
    print(r.stdout.strip() or r.stderr.strip())
    print(f"[PUBLISH] 已发布 {len(copied)} 个产物 → {DST}")
    for f in copied:
        print("   ", f)


if __name__ == "__main__":
    main()
