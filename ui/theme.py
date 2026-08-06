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
    "accent": "#007AFF",      # 系统蓝（导航/按钮等强调）
    "accent_text": "#FFFFFF",
    # 列表选中高亮：浅蓝半透明 + 深色文字（macOS 原生选中风格，比实心蓝柔和）
    # 注意：QColor 的 8 位十六进制是 AARRGGBB 顺序（alpha 前置），
    # 不支持 "rgba()" 函数字符串（实测解析失败）
    "selection_bg": "#33007AFF",
    "selection_text": "#1D1D1F",
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
    # 列表选中高亮：macOS 深色模式的选中蓝（#3D82F7）比 #0A84FF 柔和
    "selection_bg": "#3D82F7",
    "selection_text": "#FFFFFF",
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

/* 历史列表：条目渲染由 HistoryDelegate 全权负责（自绘选中/hover/缩略图）。
   ⚠️ 不要加 padding / ::item 规则：QSS 的 padding 会被应用到每个条目的
   option.rect，导致高亮背景相对条目内容整体偏移（实测：高亮下移、文字顶出框） */
QListView#historyList {
    background: transparent;
    border: none;
    font-size: 13px;
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

/* 数据页侧边列表（收藏夹/片段），与顶部导航同风格 */
QListView#sideList {
    background: $sidebar;
    border: none;
    border-radius: 10px;
    font-size: 13px;
    padding: 4px;
}
QListView#sideList::item {
    height: 28px;
    padding: 0 10px;
    border-radius: 6px;
    margin: 1px 2px;
}
QListView#sideList::item:hover { background: $hover; }
QListView#sideList::item:selected {
    background: $accent;
    color: $accent_text;
}

/* 输入类控件（片段表单等）：NSSearchField 风格 */
QLineEdit, QPlainTextEdit {
    background: $search_bg;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: $accent;
}
QPlainTextEdit { padding: 8px 10px; }

/* 右键菜单：Apple 风格（圆角浮层、选中强调色、分隔线） */
QMenu {
    background: $window;
    border: 1px solid $separator;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 6px 28px 6px 14px;
    border-radius: 6px;
    font-size: 13px;
}
QMenu::item:selected {
    background: $accent;
    color: $accent_text;
}
QMenu::separator {
    height: 1px;
    background: $separator;
    margin: 4px 10px;
}

/* 详情弹层：元信息与按钮 */
QLabel#detailMeta { color: $secondary; font-size: 12px; }
QPushButton#primaryButton {
    background: $accent;
    color: $accent_text;
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
    font-size: 13px;
}
QPushButton#primaryButton:hover { background: $accent; }
QPushButton#primaryButton:pressed { opacity: 0.8; }

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
    # 选中高亮用独立的 selection 色（列表条目浅蓝 + 深字，macOS 原生风格）
    pal.setColor(QPalette.ColorRole.Highlight, QColor(p["selection_bg"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(p["selection_text"]))
    return pal


def apply_theme(app: QApplication, mode: str = "system") -> str:
    """应用主题（mode: system / light / dark），返回实际生效的模式。"""
    resolved = _resolve_mode(app, mode)
    palette = LIGHT if resolved == "light" else DARK
    app.setPalette(_build_palette(palette))
    app.setStyleSheet(build_stylesheet(palette))
    logger.info("主题已应用: %s", resolved)
    return resolved
