"""主题测试：浅/深/跟随系统应用不崩溃、QSS 与调色板正确（offscreen）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


pytest_app = QApplication.instance() or QApplication([])


def test_apply_light_theme():
    from ui.theme import LIGHT, apply_theme

    resolved = apply_theme(pytest_app, "light")
    assert resolved == "light"
    qss = pytest_app.styleSheet()
    assert "#007AFF" in qss  # 强调色
    assert "#FFFFFF" in qss  # 窗口底色
    assert "QListView#topnav" in qss  # 选择器必须用 QListView（QListWidget 变体不生效）
    # 选中高亮：浅蓝半透明（alpha 51）+ 深色文字
    hl = pytest_app.palette().color(QPalette.ColorRole.Highlight)
    assert hl.red() == 0 and hl.green() == 122 and hl.blue() == 255
    assert hl.alpha() == 51
    assert pytest_app.palette().color(
        QPalette.ColorRole.HighlightedText) == QColor("#1D1D1F")


def test_apply_dark_theme():
    from ui.theme import DARK, apply_theme

    resolved = apply_theme(pytest_app, "dark")
    assert resolved == "dark"
    qss = pytest_app.styleSheet()
    assert "#0A84FF" in qss
    assert pytest_app.palette().color(QPalette.ColorRole.Window) == QColor("#1E1E1E")
    # 深色模式选中：macOS 深色选中蓝 #3D82F7
    assert pytest_app.palette().color(
        QPalette.ColorRole.Highlight) == QColor("#3D82F7")


def test_apply_system_theme():
    from ui.theme import apply_theme

    resolved = apply_theme(pytest_app, "system")
    assert resolved in ("light", "dark")


def test_build_stylesheet_complete():
    from ui.theme import DARK, build_stylesheet

    qss = build_stylesheet(DARK)
    # Template 无未替换占位符
    assert "$" not in qss
