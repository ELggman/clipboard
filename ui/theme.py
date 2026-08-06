"""主题：浅色 / 深色 / 跟随系统（Apple 风格，DEVELOPMENT.md §6 界面设计）。

设计要点：
- 调色板取自 macOS 系统色（正文 #1D1D1F / 次要 #6E6E73 / 强调 #007AFF 等）
- QSS 由调色板用 string.Template 生成（QSS 含 {}，不能走 %-format）
- 只样式化自定义区域（侧边栏/搜索框/列表/状态栏/占位提示），
  其余控件保持 Qt 原生 macOS 外观
- 跟随系统：bootstrap 里监听 colorSchemeChanged 动态重应用
"""
import logging
import string

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

# ---- 调色板（macOS 系统色） ----

LIGHT = {
    "window": "#FFFFFF",      # 主内容背景
    "sidebar": "#F0F0F2",     # 左侧导航底（接近 Finder 侧边栏）
    "content": "#F5F5F7",     # 备用面
    "text": "#1D1D1F",
    "secondary": "#6E6E73",
    "separator": "#E3E3E6",
    "search_bg": "#E9E9EB",   # NSSearchField 底色
    "accent": "#007AFF",      # 系统蓝
    "accent_text": "#FFFFFF",
    "hover": "rgba(0, 0, 0, 0.06)",
    "hover_item": "rgba(0, 0, 0, 0.04)",
    "scrollbar": "rgba(0, 0, 0, 0.22)",        # 滚动条滑块（默认太浅不可见）
    "scrollbar_hover": "rgba(0, 0, 0, 0.38)",
}

DARK = {
    "window": "#1E1E1E",
    "sidebar": "#26262A",
    "content": "#2C2C2E",
    "text": "#F5F5F7",
    "secondary": "#98989D",
    "separator": "#3A3A3C",
    "search_bg": "#3A3A3C",
    "accent": "#0A84FF",
    "accent_text": "#FFFFFF",
    "hover": "rgba(255, 255, 255, 0.08)",
    "hover_item": "rgba(255, 255, 255, 0.06)",
    "scrollbar": "rgba(255, 255, 255, 0.25)",
    "scrollbar_hover": "rgba(255, 255, 255, 0.42)",
}

_QSS = string.Template("""
QMainWindow, QDialog, QWidget#quickPaste {
    background: $window;
}
QWidget { color: $text; }

/* ⚠️ 不要加 QWidget { outline: none; }：实测会干扰 QListView::item:selected
   的背景绘制（选中态渲染成浅色 tint），详见 git 历史 commit 说明 */

/* 顶部导航：水平分段式（Apple 工具栏风格）
   ⚠️ 选择器必须用 QListView#id（实测 Qt 6.11 macOS 风格忽略
   QListWidget#id::item:selected，选中背景不生效） */
QListView#topnav {
    background: $sidebar;
    border: none;
    border-bottom: 1px solid $separator;
    font-size: 13px;
    padding: 4px 8px;
}
QListView#topnav::item {
    height: 28px;
    padding: 0 14px;
    margin: 0 2px;
    border-radius: 6px;
}
QListView#topnav::item:hover { background: $hover; }
QListView#topnav::item:selected {
    background: $accent;
    color: $accent_text;
}

/* 搜索框：NSSearchField 风格 */
QLineEdit#searchBox {
    background: $search_bg;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: $accent;
}

/* 历史列表：条目渲染由 HistoryDelegate 全权负责（自绘选中/hover/缩略图），
   不要再加 ::item 规则——QSS 的 item padding/margin 会干扰 delegate 的行几何 */
QListView#historyList {
    background: transparent;
    border: none;
    font-size: 13px;
    padding: 4px 8px;
}

/* 滚动条：圆角细条 + 半透明滑块（QSS 样式后为非 overlay，不再压住选中高亮） */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
}
QScrollBar::handle:vertical {
    background: $scrollbar;
    border-radius: 5px;
    min-height: 30px;
    margin: 2px;
}
QScrollBar::handle:vertical:hover { background: $scrollbar_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: $scrollbar;
    border-radius: 5px;
    min-width: 30px;
    margin: 2px;
}
QScrollBar::handle:horizontal:hover { background: $scrollbar_hover; }

/* 占位提示（未实现的页面） */
QLabel#placeholder { color: $secondary; font-size: 13px; }

/* 状态栏 */
QStatusBar { color: $secondary; font-size: 11px; background: transparent; }
QStatusBar::item { border: none; }
""")


def _resolve_mode(app: QApplication, mode: str) -> str:
    """把 system 解析为 light/dark；返回实际模式。"""
    if mode != "system":
        return mode
    resolved = "dark" if app.styleHints().colorScheme() == 1 else "light"
    logger.info("跟随系统主题: %s", resolved)
    return resolved


def build_stylesheet(palette: dict) -> str:
    return _QSS.substitute(**palette)


def _build_palette(p: dict) -> QPalette:
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(p["window"]))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(p["text"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(p["window"]))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(p["content"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(p["text"]))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(p["secondary"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(p["accent_text"]))
    return pal


def apply_theme(app: QApplication, mode: str = "system") -> str:
    """应用主题（mode: system / light / dark），返回实际生效的模式。"""
    resolved = _resolve_mode(app, mode)
    palette = LIGHT if resolved == "light" else DARK
    app.setPalette(_build_palette(palette))
    app.setStyleSheet(build_stylesheet(palette))
    logger.info("主题已应用: %s", resolved)
    return resolved
