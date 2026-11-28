"""实验协议指纹与产物清单 (纯标准库)。

为什么需要它
------------
四臂对照这类实验, 结果 JSON 里如果只有 ``protocol`` 字典和几个指标, 第三方无法回答:

- 训练集到底由哪些文件组成? 合成占比是多少?
- train/val 划分是哪一份文件? 有没有泄漏?
- 实跑的 batch/epochs/设备是什么? 与声明的协议一致吗?
- 用的权重是哪一份? 能否校验?
- 依赖版本是什么?

所以这里把"协议指纹"定义为对下列全部内容的 sha256::

    protocol(声明) + data(数据组成) + splits(划分指纹) + actual(实跑配置)
    + deps(依赖版本) + checkpoint(权重出处)

任何一项变了, ``protocol_hash`` 必变 —— 这正是可复现需要的性质。

另外保留 :func:`legacy_protocol_hash`: 2026-11-08 已发布数字对应的是"只哈希
protocol 字典"的旧算法 (json.dumps 默认分隔符), 用于与历史结果对齐, 不与新哈希混用。

用法::

    from pipelines.common.protocol import build_manifest, dir_fingerprint, write_json

    manifest = build_manifest(
        PROTOCOL,
        data={"sources": [...], "synth_ratio": 0.11},
        splits={"train": split_fingerprint([("img_000.png", p), ...])},
        actual={"epochs": 10, "batch": 4, "device": "cuda", "wall_sec": 812.3},
        checkpoint={"selection": "best", "path": "...", "sha256": "..."},
    )
    write_json(out_path, {**report, "protocol_manifest": manifest})
"""
import hashlib
import json
import math
import os
import platform
import statistics
import sys

__all__ = [
    "canonical", "sha16", "legacy_protocol_hash", "file_sha256", "dir_fingerprint",
    "split_fingerprint", "runtime_versions", "build_manifest", "write_json",
    "T_CRIT_95", "ci95_t",
]

#: 双侧 95% 的 t 临界值 (df -> t)。**唯一一份**, 别在别处再抄一张 ——
#: 汇总脚本与文档核对脚本必须用同一张表, 否则 CI 会互相打架。
#: (2026-11-27 扩到 df=30: 原来只到 df=5, n>=7 时 fallback 到 1.96 会把 CI 算窄 ✗)
T_CRIT_95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
             8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
             14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
             20: 2.086, 25: 2.060, 30: 2.042}


def ci95_t(diffs):
    """配对差值的 95% CI (双侧 t, **df = n-1**) -> (mean, lo, hi)。

    **全仓唯一实现** ✓: 臂脚本、汇总脚本、文档核对脚本都必须走这里 ✓。
    为什么必须唯一 (2026-11-27 的实测教训 ✓): 有 9 个臂脚本各自抄了一份
    ``{2: 12.7062, 3: 4.3027, ...}`` —— 那张表的**键整体偏移了 1** (键 2 装的是 df=1
    的值 ✓), 再按 ``n-1`` 去查 -> 实际用 df = n-2 -> n=3 的 CI 宽了约 3 倍 ✗ ->
    6 条已发布判语因此从"显著"被压成"未检出差异" ✗。抄表比抄错公式更危险 ✓。

    用法:
        mean, lo, hi = ci95_t(diffs)
    """
    diffs = list(diffs)
    n = len(diffs)
    if n == 0:
        raise ValueError("ci95_t: 空差值列表")
    mean = sum(diffs) / n
    if n < 2:
        return mean, None, None
    sd = statistics.stdev(diffs)
    t = T_CRIT_95.get(n - 1, 1.96)
    hw = t * sd / math.sqrt(n)
    return mean, mean - hw, mean + hw


def canonical(obj):
    """规范化 JSON 文本 (排序键 + 紧凑分隔符), 用于稳定哈希。"""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha16(obj):
    """任意可 JSON 化对象的 16 位十六进制摘要。"""
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()[:16]


def legacy_protocol_hash(protocol):
    """旧版协议哈希 (仅 protocol 字典, json.dumps 默认分隔符)。

    与 2026-11-08 已发布四臂数字里的 ``protocol_hash`` 同算法, 用于对齐历史结果。
    新实验请用 :func:`build_manifest` 产出的 ``protocol_hash``。
    """
    return hashlib.sha256(json.dumps(protocol, sort_keys=True).encode()).hexdigest()[:16]


def file_sha256(path, chunk=1 << 20):
    """文件内容 sha256 (十六进制全文)。文件不存在返回 None。"""
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def file_fingerprint(path, name=None):
    """单个文件的指纹 (路径/大小/sha256)。模型权重这类二进制靠它才能复现。"""
    if not path or not os.path.isfile(path):
        return {"path": path, "exists": False, "sha256": None, "bytes": None}
    return {"path": os.path.abspath(path), "name": name or os.path.basename(path),
            "exists": True, "sha256": file_sha256(path), "bytes": os.path.getsize(path)}


def dir_fingerprint(root, exts=None, max_files=None):
    """目录内容指纹: 文件数 + 总字节 + 内容 sha256 (按相对路径排序)。

    exts: 只统计这些后缀 (如 ``(".png", ".jpg")``); None = 全部文件。
    max_files: 只取前 N 个 (按排序后) —— 抽样模式, 会在返回值里标注 sampled=True。
    """
    if not root or not os.path.isdir(root):
        return {"path": root, "exists": False, "n_files": 0, "total_bytes": 0, "sha256": None}
    names = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if exts and not fn.lower().endswith(tuple(exts)):
                continue
            names.append(os.path.relpath(os.path.join(dirpath, fn), root).replace("\\", "/"))
    names.sort()
    sampled = False
    if max_files is not None and len(names) > max_files:
        names = names[:max_files]
        sampled = True
    total = 0
    h = hashlib.sha256()
    for rel in names:
        p = os.path.join(root, rel.replace("/", os.sep))
        sha = file_sha256(p)
        total += os.path.getsize(p)
        h.update(f"{rel}\t{sha}\n".encode("utf-8"))
    return {"path": root, "exists": True, "n_files": len(names), "total_bytes": total,
            "sha256": h.hexdigest(), "sampled": sampled}


def split_fingerprint(items):
    """划分指纹: items = [(名称, 文件路径), ...]。

    返回两个哈希:
      - ``names_sha256``: 只看"有哪些样本" —— 用来判断划分定义变了没;
      - ``sha256``: 名称 + 文件内容 —— 用来判断样本内容变了没。
    两者分开是必要的: 划分名单相同但图片被重生成, 同样要能被检出。
    """
    rows = []
    total = 0
    for name, path in items:
        sha = file_sha256(path)
        if sha is None:
            continue
        size = os.path.getsize(path)
        total += size
        rows.append((name, sha, size))
    rows.sort()
    nh = hashlib.sha256()
    ch = hashlib.sha256()
    for name, sha, size in rows:
        nh.update(f"{name}\n".encode("utf-8"))
        ch.update(f"{name}\t{sha}\t{size}\n".encode("utf-8"))
    return {"n": len(rows), "total_bytes": total,
            "names_sha256": nh.hexdigest(), "sha256": ch.hexdigest()}


def runtime_versions():
    """依赖版本快照 (装不上的模块跳过, 不抛错)。"""
    out = {"python": platform.python_version(), "platform": sys.platform}
    for mod in ("torch", "ultralytics", "numpy", "PIL"):
        try:
            m = __import__(mod)
            out[mod] = getattr(m, "__version__", "unknown")
        except Exception:
            out[mod] = None
    return out


def build_manifest(protocol, data=None, splits=None, actual=None, deps=None,
                   checkpoint=None, extra=None):
    """组装协议清单并算出覆盖全部组成的 protocol_hash。

    返回的 dict 里 ``protocol_hash`` 是**新**算法 (覆盖全部组成);
    ``protocol_hash_legacy`` 是旧算法 (仅 protocol 字典), 便于与历史数字对齐。
    """
    payload = {
        "protocol": protocol,
        "data": data or {},
        "splits": splits or {},
        "actual": actual or {},
        "deps": deps if deps is not None else runtime_versions(),
        "checkpoint": checkpoint or {},
        "extra": extra or {},
    }
    manifest = dict(payload)
    manifest["protocol_hash"] = sha16(payload)
    manifest["protocol_hash_legacy"] = legacy_protocol_hash(protocol)
    return manifest


def write_json(path, obj):
    """原子写 JSON (UTF-8, 缩进 2), 返回写入路径。"""
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path
