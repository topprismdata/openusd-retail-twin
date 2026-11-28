"""跨平台字体解析 (CJK 优先)。

背景: 仓库原实现只列 macOS 系统字体 (/System/Library/Fonts/...)。在 Windows/Linux 上
- truetype 直接抛 OSError (08_photo_dieline.py)
- 或静默回落 load_default() -> 中文全部渲染成豆腐块 (00_bootstrap_textures.py 等)

本模块按 平台默认 -> 环境变量覆盖 -> load_default 的顺序解析字体。
Pillow 为惰性 import, 因此本模块可在无 Pillow 的环境里被安全 import。
"""
import os

#: 环境变量: 显式指定字体文件 (优先级最高)
FONT_ENV = "CJK_FONT"

CJK_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    # Windows
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    # Linux
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

SERIF_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    r"C:\Windows\Fonts\simsun.ttc",
    r"C:\Windows\Fonts\simfang.ttf",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
]

LATIN_CANDIDATES = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

_CANDIDATES = {
    "cjk": CJK_CANDIDATES,
    "serif": SERIF_CANDIDATES,
    "latin": LATIN_CANDIDATES,
}


def find_font_path(kind="cjk"):
    """返回可用的字体文件路径; 找不到返回 None。"""
    override = os.environ.get(FONT_ENV)
    if override and os.path.isfile(override):
        return override
    for path in _CANDIDATES.get(kind, CJK_CANDIDATES):
        if os.path.isfile(path):
            return path
    return None


def load_font(size, kind="cjk", index=0):
    """加载 PIL 字体对象; 找不到任何可用字体时回落 ImageFont.load_default()。"""
    from PIL import ImageFont

    path = find_font_path(kind)
    if path:
        try:
            return ImageFont.truetype(path, size, index=index)
        except Exception:
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()
