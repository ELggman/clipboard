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
    "accent": "#007AFF",      # 系统蓝（导航/菜单选中等）
    "accent_text": "#FFFFFF",
    # 按钮蓝（比 accent 浅一档，用户要求柔和）
    "accent_soft": "#2E90FF",
    "accent_soft_pressed": "#1F7AE0",  # 按下态加深（QSS 不支持 opacity，须显式色）
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
    "accent_soft": "#4DA3FF",
    "accent_soft_pressed": "#3D8CFF",
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

/* 顶部导航（Raycast 风格）：透明无边框，项由自绘 delegate 画——
   默认 16px 次要色；选中 = 蓝胶囊 #007AFF 白字 10px 圆角（设计规范） */
QListView#topnav {
    background: transparent;
    border: none;
    font-size: 16px;
}

/* 类型筛选条（历史页 全部/文本/URL…）：同款配色，四周圆角。
   ⚠️ 必须独立 objectName——复用 #topnav 会连带顶部导航圆角化 */
QListView#typeTabs {
    background: $sidebar;
    border: none;
    border-radius: 8px;
    font-size: 13px;
    padding: 4px 8px;
}
QListView#typeTabs::item {
    height: 28px;
    padding: 0 14px;
    margin: 0 2px;
    border-radius: 6px;
}
QListView#typeTabs::item:hover { background: $hover; }
QListView#typeTabs::item:selected {
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
/* 代码详情视图：行号是独立 gutter 组件（item_detail_popup._CodeView），
   与文本区并排。padding 必须为 0：通用 QPlainTextEdit 规则的 8px 顶部
   内边距会把文本压下半行高，与 gutter 的 contentOffset 行号错位。
   背景必须不透明（$window = 弹窗底色）：macOS 上透明 QPlainTextEdit
   viewport 的首行合成渲染异常（实测：代码第一行显示不全/被裁剪）。
   选中色用 $selection_bg（浅蓝）与文本弹窗一致——通用 QPlainTextEdit
   规则的 $accent 深蓝在此显式覆盖 */
QPlainTextEdit#codeView {
    background: $window;
    border: none;
    border-radius: 0;
    padding: 0px;
    selection-background-color: $selection_bg;
}

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

/* 详情弹层：背景必须不透明（macOS 的 Qt.Popup 是 NSPanel，可能走透明合成，
   曾导致 QPlainTextEdit 首行渲染错位——§9 坑速查）；元信息与按钮 */
QWidget#itemDetail {
    background: $window;
}
QLabel#detailMeta { color: $secondary; font-size: 12px; }

/* 按钮统一：文字色、字号、尺寸（primary/secondary 同 padding 同高） */
QPushButton { color: $text; font-size: 13px; }
QPushButton#primaryButton,
QPushButton#secondaryButton {
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
}
QPushButton#primaryButton {
    background: $accent_soft;  /* 浅一档的按钮蓝 */
    color: $accent_text;
}
QPushButton#primaryButton:pressed { background: $accent_soft_pressed; }
QPushButton#secondaryButton {
    background: $search_bg;
    color: $text;
}
QPushButton#secondaryButton:pressed { background: $separator; }
/* destructive：破坏性操作（清空/删除）确认按钮，macOS 红色惯例 */
QPushButton#destructiveButton {
    background: #FF453A;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
}
QPushButton#destructiveButton:pressed { background: #D63A30; }

/* 状态栏 */
QStatusBar { color: $secondary; font-size: 11px; background: transparent; }
QStatusBar::item { border: none; }
/* 隐私模式状态指示（📋 / 🔒，§9.4） */
QLabel#privacyStatus { color: $secondary; font-size: 11px; padding: 0 8px; }
QLabel#privacyStatus[paused="true"] { color: $accent_soft; }

/* 设置页分区标题（隐私模式等） */
QLabel#sectionTitle { color: $secondary; font-size: 12px; font-weight: 600; }

/* 设置页滚动容器：透明背景、无边框（内容少时不露灰底） */
QScrollArea { background: transparent; border: none; }
QWidget#settingsContainer { background: transparent; }

/* 会话下拉（历史页顶部）与搜索范围下拉：搜索框风格 */
QComboBox#sessionCombo, QComboBox#searchScope {
    background: $search_bg;
    border: none;
    border-radius: 8px;
    padding: 4px 10px;
    font-size: 12px;
    color: $text;
}
QComboBox#sessionCombo::drop-down, QComboBox#searchScope::drop-down {
    border: none;
    width: 18px;
}
QComboBox#sessionCombo QAbstractItemView,
QComboBox#searchScope QAbstractItemView {
    background: $window;
    border: 1px solid $separator;
    border-radius: 8px;
    padding: 4px;
    selection-background-color: $accent;
    selection-color: $accent_text;
    color: $text;
}
/* 会话管理菜单按钮：圆形省略号 */
QPushButton#sessionMenuBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: $secondary;
    font-size: 15px;
}
QPushButton#sessionMenuBtn:hover { background: $search_bg; }

/* 搜索范围切换按钮（全部会话/本会话，历史页）：点按切换无弹层 */
QPushButton#searchScopeBtn {
    background: $search_bg;
    border: none;
    border-radius: 8px;
    padding: 0;
    font-size: 12px;
    color: $text;
}
QPushButton#searchScopeBtn:hover { background: $separator; }
QPushButton#searchScopeBtn:pressed { background: $scrollbar_hover; }

/* 收藏夹触发（收藏夹行，仅收藏夹页显示）：悬停展开浮层面板。
   ⚠️ 必须带背景色——MainWindow 上下文中无背景的控件渲染空白
   （Qt 6.9 macOS 实测：QLabel 文字 + 背景可靠） */
QLabel#collectionTrigger {
    background: $search_bg;
    border-radius: 8px;
    padding: 0 10px;
    color: $secondary;
    font-size: 13px;
}
QLabel#collectionTrigger:hover { background: $scrollbar_hover; }

/* 模板页三栏卡片（设计规范：白色卡片 16px 圆角、大量留白） */
QFrame#templateCard {
    background: $window;
    border: 1px solid $separator;
    border-radius: 16px;
}
QLabel#cardTitle {
    color: $text;
    font-size: 15px;
    font-weight: 600;
}
QLabel#fieldLabel {
    color: $secondary;
    font-size: 13px;
}
QLabel#emptyHint {
    color: $secondary;
    font-size: 13px;
}
QPushButton#ghostBtn {
    background: $search_bg;
    border: none;
    border-radius: 8px;
    padding: 4px 10px;
    color: $secondary;
    font-size: 13px;
}
QPushButton#ghostBtn:hover { background: $hover; }
QListView#sourceList, QListView#templateList {
    background: transparent;
    border: none;
}
/* 触发方式分段控件（胶囊容器 + 选中 accent） */
QFrame#segGroup {
    background: $search_bg;
    border-radius: 10px;
}
QPushButton#segBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 14px;
    color: $secondary;
    font-size: 13px;
}
QPushButton#segBtn:hover { background: $hover; }
QPushButton#segBtn:checked {
    background: $accent;
    color: $accent_text;
}
/* 变量胶囊（点击插入编辑器）：11px/8px 内边距——太宽会把折叠态也挤折行，
   新增按钮掉到第二行（实测 y=28 错位） */
QPushButton#varTag {
    background: $search_bg;
    border: none;
    border-radius: 999px;
    padding: 4px 8px;
    color: $text;
    font-size: 11px;
    font-family: Menlo, Monaco, monospace;
}
QPushButton#varTag:hover { background: $hover; color: $accent; }
/* 变量区滚动容器：透明无边框（viewport 也需透明，否则白底矩形） */
QScrollArea#varScroll {
    background: transparent;
    border: none;
}
QScrollArea#varScroll > QWidget > QWidget {
    background: transparent;
}

/* 模板代码编辑器（等宽 + Pygments 高亮） */
QPlainTextEdit#templateEditor {
    background: $content;
    border: 1px solid $separator;
    border-radius: 10px;
    padding: 8px;
    font-family: Menlo, Monaco, monospace;
    font-size: 13px;
}
QPushButton#dangerBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 6px 12px;
    color: #FF3B30;
    font-size: 13px;
}
QPushButton#dangerBtn:hover { background: $hover; }

/* 收藏夹浮层面板：悬浮覆盖在条目区上方 */
QFrame#collectionPanel {
    background: $window;
    border: 1px solid $separator;
    border-radius: 10px;
}

/* 收藏夹页当前收藏夹标题（面板收回后常驻） */
QLabel#collectionTitle {
    color: $secondary;
    font-size: 13px;
    font-weight: 600;
    padding: 0 4px;
}
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
    # Link 角色承载强调色（导航胶囊选中态等自绘控件取色用）
    pal.setColor(QPalette.ColorRole.Link, QColor(p["accent"]))
    return pal


def apply_theme(app: QApplication, mode: str = "system") -> str:
    """应用主题（mode: system / light / dark），返回实际生效的模式。"""
    resolved = _resolve_mode(app, mode)
    palette = LIGHT if resolved == "light" else DARK
    app.setPalette(_build_palette(palette))
    app.setStyleSheet(build_stylesheet(palette))
    logger.info("主题已应用: %s", resolved)
    return resolved
