#!/usr/bin/env python
"""发布到 `docs/research/benchmark/` 时的**路径去本机化**。

产物 json 里会记录训练权重、渲染输出、SimReady 工作目录的**绝对路径**, 里面带
本机用户名 (`C:/Users/<你>/...`)。发布版随仓交付, 不该带本机信息 —— 既不必要,
也不该把机器布局写进公开仓。所以发布时统一替换:

| 原文 | 发布版 |
| --- | --- |
| 仓库根绝对路径 (`C:/.../ort-work/`) | 仓根相对路径 (`output/...`) |
| 数据集根 (`.../datasets/SKU-110K`) | `<SKU110K_ROOT>` |
| venv 根 (`.../venvbpy` / `.../srvenv`) | `<VENV>` |
| 其它本机家目录路径 | `<HOME>/...` (兜底: 去掉用户名) |

**为什么要处理转义形式**: 产物 json 里的路径是 **JSON 转义**过的, 文件里的字节是
`C:\\\\Users\\\\<user>\\\\...` (两个反斜杠)。只按正斜杠替换会漏掉它们 —— 实测漏了
148 个文件。所以这里的匹配一律用 `[/\\\\]+` (一个或多个斜杠/反斜杠), 不区分
"文件里的真反斜杠"与"JSON 转义的两个反斜杠"。

**为什么放在发布这一步做**: `26_publish_artifacts.py` 每次都从 `output/benchmark/`
**重新拷贝**覆盖发布版。所以只在发布目录里手工替换会被下次发布抹掉 —— 替换必须
是发布流水线的一环 (26 号调用它, 24 号用它比对 output 副本, 两边同一套规则,
否则清单里的 `matches_output_copy_lf` 会因为路径写法不同而恒为 false)。

用法:
    from publish_paths import scrub_text
    txt = scrub_text(open(p, encoding="utf-8").read())
"""
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SEP = r"[/\\]+"          # 一个或多个斜杠/反斜杠 (含 JSON 转义的双反斜杠)


def _rx_from_path(path):
    """把一个绝对路径编成正则 (各段之间用任意多个斜杠/反斜杠连接)。"""
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if not parts:
        return None
    return re.compile(_SEP.join(re.escape(p) for p in parts) + _SEP)


def _name_rules():
    """按**目录名**识别数据集根 / venv 根 —— 不依赖环境变量, 同样输入永远同样输出。"""
    return (
        (re.compile(r"[A-Za-z]:" + _SEP + r"(?:[^/\\]+" + _SEP + r")*?"
                    r"datasets" + _SEP + r"SKU-110K", re.I), "<SKU110K_ROOT>"),
        (re.compile(r"[A-Za-z]:" + _SEP + r"(?:[^/\\]+" + _SEP + r")*?"
                    r"(?:venvbpy|srvenv)", re.I), "<VENV>"),
    )


def _home_rx():
    """本机家目录 (兜底: 去掉用户名)。"""
    return re.compile(r"[A-Za-z]:" + _SEP + r"Users" + _SEP + r"[^/\\\"\s,;)]+" + _SEP)


def scrub_text(text):
    """把文本里的本机绝对路径换成发布版写法。"""
    if not text:
        return text
    # 1) 仓库根 -> 仓根相对 (最长前缀优先, 避免半截匹配)
    roots = [os.path.abspath(BASE)]
    for extra in (os.environ.get("SKU110K_ROOT", "").strip(),
                  os.path.dirname(os.path.dirname(os.environ.get("ORTHO_PY", "").strip()))
                  if os.environ.get("ORTHO_PY", "").strip() else ""):
        if extra:
            roots.append(extra)
    for root in roots:
        rx = _rx_from_path(root)
        if rx:
            text = rx.sub("", text)
    # 2) 数据集 / venv 根 -> 具名占位符
    for rx, token in _name_rules():
        text = rx.sub(token, text)
    # 3) 兜底: 其它本机家目录路径 -> <HOME>
    text = _home_rx().sub("<HOME>/", text)
    return text


def scrub_bytes(data):
    """按字节做同样的替换 (发布链路上文件是按字节写的)。"""
    if b"\x00" in data[:8000]:      # 二进制 (图) 不动
        return data
    try:
        return scrub_text(data.decode("utf-8")).encode("utf-8")
    except UnicodeDecodeError:
        return data
