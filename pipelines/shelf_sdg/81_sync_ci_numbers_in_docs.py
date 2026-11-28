#!/usr/bin/env python
"""把文档里引用的 95% CI **数字**按产物重算后的规范口径同步一遍 (2026-11-27 起长期用)。

为什么需要这个脚本: 产物里的 CI 是由 `pipelines.common.protocol.ci95_t` 算的 ✓,
文档里的 CI 是**抄**的 ✓ -> 口径一改 (比如 I-28 那次 ✓), 文档就会跟产物对不上 ✓ ->
**手抄的地方一定会漏** ✓ -> 所以这一步必须现算 ✓。

本脚本只做**数字**替换 ✓: 从产物里存的 per-seed 差值算出 (旧口径 CI, 规范口径 CI),
在文档里找到旧数字的写法 (U+2212 与 ASCII 两种减号 ✓), 换成新的 ✓。
**判语与叙述不由本脚本改** ✓ —— 那是结论, 要人按新数字重写 ✓ (闸门 28 号会报出对不上的地方 ✓)。

用法:
    python pipelines/shelf_sdg/81_sync_ci_numbers_in_docs.py            # 只报
    python pipelines/shelf_sdg/81_sync_ci_numbers_in_docs.py --apply    # 真改
"""
import glob
import json
import math
import os
import re
import statistics
import sys

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, BASE)
from pipelines.common.protocol import ci95_t  # noqa: E402

BENCH = os.path.join(BASE, "output", "benchmark")
MINUS = "\u2212"

# I-28 之前的错误口径: 表按 df 索引但查 n-1 -> 实际 df = n-2 ✓ (只用于识别"旧数字" ✓)
OLD_TABLE = {2: 12.7062, 3: 4.3027, 4: 3.1824, 5: 2.7764}

DOCS = ["README.md", "docs/research/INSIGHT_QUEUE.md",
        "docs/research/GENERATOR_ARM_CONCLUSION_2026-11-26.md"]


def old_ci(diffs):
    n = len(diffs)
    mean = sum(diffs) / n
    sd = statistics.stdev(diffs)
    hw = OLD_TABLE.get(n - 1, 1.96) * sd / math.sqrt(n)
    return mean - hw, mean + hw


def walk(node, path=""):
    if isinstance(node, dict):
        if isinstance(node.get("per_seed_pp"), list) and node.get("per_seed_pp"):
            yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def fmt(a, b):
    return f"{a:+.2f}, {b:+.2f}".replace("-", MINUS)


def main():
    apply = "--apply" in sys.argv
    pairs = {}
    for f in sorted(glob.glob(os.path.join(BENCH, "*.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
        except Exception:
            continue
        for path, node in walk(d):
            vals = [float(x) for x in node["per_seed_pp"]]
            if len(vals) < 2:
                continue
            lo_o, hi_o = old_ci(vals)
            _m, lo_n, hi_n = ci95_t(vals)
            if lo_n is None:
                continue
            if abs(lo_o - lo_n) < 5e-4 and abs(hi_o - hi_n) < 5e-4:
                continue
            pairs[(fmt(lo_o, hi_o), fmt(lo_n, hi_n))] = (os.path.basename(f), path)

    total = 0
    for doc in DOCS:
        p = os.path.join(BASE, doc)
        if not os.path.isfile(p):
            continue
        s = open(p, encoding="utf-8").read()
        n_doc = 0
        for (old_txt, new_txt), (art, path) in pairs.items():
            # 文档里同一对数字可能被**换行**断开 (队列按 ~100 字折行 ✓) ->
            # 所以要用**容忍空白**的正则, 并把分隔空白原样留下 ✓ (不破坏折行 ✓)
            num_old = old_txt.replace(MINUS, "-")
            pat = re.compile(re.escape(num_old).replace(r"\ ", r"(\s+)"))

            def _sub(m, _new=new_txt):
                sep = m.group(1) if m.groups() else ", "
                a, b = _new.split(", ")
                return f"{a}{sep}{b}"

            s, n = pat.subn(_sub, s)
            if n:
                n_doc += n
                print(f"  {doc:52s} {old_txt} -> {new_txt}  (x{n}, 来自 {art} {path[:26]})")
        if n_doc and apply:
            open(p, "w", encoding="utf-8").write(s)
        total += n_doc
    print(f"\n{'已写入' if apply else '仅报告'}: 共替换 {total} 处 CI 数字 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
