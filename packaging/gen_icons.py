"""把 resources/icon.svg 渲染成 macOS 应用图标（PNG + ICNS）。

用法:  source .venv/bin/activate && python packaging/gen_icons.py

产物:
    resources/icon.png   512×512（运行时窗口/Dock 图标 + 关于页）
    resources/icon.icns  完整 iconset（PyInstaller 打包 `icon=` 用）

依赖 QtSvg 的 QSvgRenderer 光栅化 SVG + 系统 iconutil 打包 ICNS。
"""
import subprocess
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parent.parent
SVG = ROOT / "resources" / "icon.svg"
OUT_DIR = ROOT / "resources"

# macOS iconset 命名约定（iconutil 要求）：每个点尺寸 + @2x 视网膜版本
ICONSET_SIZES = {
    "icon_16x16.png": 16,
    "icon_16x16@2x.png": 32,
    "icon_32x32.png": 32,
    "icon_32x32@2x.png": 64,
    "icon_128x128.png": 128,
    "icon_128x128@2x.png": 256,
    "icon_256x256.png": 256,
    "icon_256x256@2x.png": 512,
    "icon_512x512.png": 512,
    "icon_512x512@2x.png": 1024,
}


def render_svg(renderer: QSvgRenderer, size: int) -> QImage:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return img


def main() -> int:
    if not SVG.exists():
        print(f"缺少源图标: {SVG}", file=sys.stderr)
        return 1

    svg_bytes = SVG.read_bytes()
    renderer = QSvgRenderer(svg_bytes)
    if not renderer.isValid():
        print(f"SVG 解析失败: {SVG}", file=sys.stderr)
        return 1

    # 运行时 PNG（512，双倍清晰度，供窗口/关于页）
    runtime_png = OUT_DIR / "icon.png"
    render_svg(renderer, 512).save(str(runtime_png), "PNG")
    print(f"已生成 {runtime_png}")

    # iconset → iconutil → icns
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        for name, size in ICONSET_SIZES.items():
            render_svg(renderer, size).save(str(iconset / name), "PNG")

        icns = OUT_DIR / "icon.icns"
        subprocess.run(
            ["iconutil", "--convert", "icns", "--output", str(icns), str(iconset)],
            check=True,
        )
        print(f"已生成 {icns}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
