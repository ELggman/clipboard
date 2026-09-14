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

from PySide6.QtCore import Qt
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
    # 按钮状态色（设计规范 §5：hover / pressed / disabled）
    "accent_soft_hover": "#2682EE",
    "accent_soft_disabled": "#C7C7CC",
    "secondary_hover": "#E5E5EA",
    "secondary_pressed": "#D1D1D6",
    "btn_disabled_text": "#AEAEB2",
    "ghost_hover": "rgba(0, 0, 0, 0.05)",
    "ghost_pressed": "rgba(0, 0, 0, 0.10)",
    "danger_hover": "rgba(255, 59, 48, 0.10)",
    # 输入框聚焦环（设计规范：1px 半透明蓝）
    "focus_ring": "rgba(0, 122, 255, 0.35)",
    # 菜单分隔线（设计规范 §17：浅灰蓝线，不用深色实线）
    "menu_separator": "rgba(60, 60, 67, 0.12)",
    # 工具提示底色（设计规范 §25：深色浮层，浅/深主题一致）
    "tooltip_bg": "rgba(30, 30, 30, 0.92)",
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
    "accent_soft_hover": "#4798F7",
    "accent_soft_disabled": "#3A3A3C",
    "secondary_hover": "#414144",
    "secondary_pressed": "#4A4A4C",
    "btn_disabled_text": "#6E6E73",
    "ghost_hover": "rgba(255, 255, 255, 0.08)",
    "ghost_pressed": "rgba(255, 255, 255, 0.16)",
    "danger_hover": "rgba(255, 69, 58, 0.18)",
    "focus_ring": "rgba(10, 132, 255, 0.55)",
    "menu_separator": "rgba(255, 255, 255, 0.12)",
    "tooltip_bg": "rgba(30, 30, 30, 0.92)",
}

# 当前生效的调色板（自绘控件取色用）：apply_theme 时更新。
# 自绘控件（如 ui/fluent_combo.py）不能用 QSS 取色，改读这里；
# 注意 rgba(...) 只适用于 QSS——QColor 不解析 rgba() 函数串（§9），
# 自绘请只取十六进制项（content / separator / search_bg / accent_soft / text / secondary …）。
_CURRENT_PALETTE: dict = LIGHT


def current_palette() -> dict:
    """返回当前生效的调色板字典（自绘控件取色）。"""
    return _CURRENT_PALETTE


_QSS = string.Template("""
QMainWindow, QDialog {
    background: $window;
}
QWidget { color: $text; }

/* Quick Paste 弹窗（⌥⇧V 最近列表）：透明容器 + 圆角毛玻璃浮层卡片。
   容器 WA_TranslucentBackground，阴影由 QGraphicsDropShadowEffect 画在
   _SHADOW_GAP 留白区；卡片 12px 圆角 + 1px 分隔线（apple-design 材料层） */
QWidget#quickPaste {
    background: transparent;
}
QFrame#quickPasteCard {
    background: $window;
    border: 1px solid $separator;
    border-radius: 12px;
}
QFrame#quickPasteCard QWidget { background: transparent; }
QLabel#quickPasteTitle { color: $secondary; font-size: 13px; }
QLabel#quickPasteHint  { color: $secondary; font-size: 12px; }
QListWidget#quickPasteList { background: transparent; border: none; }

/* ⚠️ 不要加 QWidget { outline: none; }：实测会干扰 QListView::item:selected
   的背景绘制（选中态渲染成浅色 tint），详见 git 历史 commit 说明 */

/* 顶部导航（Raycast 风格）：透明无边框，项由自绘 delegate 画——
   默认 16px 次要色；选中 = 蓝胶囊 #007AFF 白字 10px 圆角（设计规范） */
QListView#topnav {
    background: transparent;
    border: none;
    font-size: 16px;
}

/* 类型筛选条（历史页 全部/文本/URL…）：Compact Tab——透明底，
   选中项 = 蓝胶囊 9px 圆角白字（UI 优化：40px 高） */
QListView#typeTabs {
    background: transparent;
    border: none;
    font-size: 13px;
}
QListView#typeTabs::item {
    height: 30px;
    padding: 0 14px;
    margin: 4px 2px;
    border-radius: 9px;
    color: $secondary;   /* 次要灰：深色主题下不再被硬编码 #3A3A3C 吃掉 */
}
QListView#typeTabs::item:hover { background: $hover; }
QListView#typeTabs::item:selected {
    background: $accent;
    color: $accent_text;
}

/* 时间线页右侧计数（当前时间段条目数）：次要色小字，叠加在分段条
   透明区右端。⚠️ 不加 padding-right：右缘已贴 tabs 右缘（页边距 10px），
   加了会把「156 条」这类宽度顶过 44px 空隙、压到最后一个胶囊。 */
QLabel#timelineCount {
    color: $secondary;
    font-size: 12px;
}

/* 搜索框：NSSearchField 风格（UI 优化：40px 高、11px 圆角、
   focus 白底 + 蓝边；蓝光 ring 由代码 QGraphicsDropShadowEffect 实现） */
QLineEdit#searchBox {
    background: $search_bg;
    border: 1px solid transparent;
    border-radius: 11px;
    padding: 0 10px;
    font-size: 14px;
    color: $text;
    /* 选中用半透明蓝 + 主题文字色（实心 $accent 会与浅色 HighlightedText
       叠出「深字压深蓝」不可读，§9） */
    selection-background-color: $selection_bg;
    selection-color: $selection_text;
}
QLineEdit#searchBox:focus {
    background: $window;
    border: 1px solid $focus_ring;
}

/* 历史列表：浅灰底（UI 优化——条目正常透明/hover 白/选中淡蓝，
   由 HistoryDelegate 自绘；列表背景不再透白色） */
QListView#historyList {
    background: $content;
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

/* 输入类控件（片段表单等）：NSSearchField 风格。
   边框占位 1px 透明：focus 换蓝边时不发生内容 1px 跳动。
   QTextEdit 覆盖详情弹层全文区——此前漏掉，dark 下原生白底（§9） */
QLineEdit, QPlainTextEdit, QTextEdit {
    background: $search_bg;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
    selection-background-color: $selection_bg;
    selection-color: $selection_text;
}
QPlainTextEdit { padding: 8px 10px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {
    border: 1px solid $focus_ring;
}
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
    selection-color: $selection_text;
}

/* 右键菜单：Apple 风格（圆角浮层、选中强调色、分隔线） */
QMenu {
    background: $window;
    border: 1px solid $separator;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 8px 28px 8px 14px;
    border-radius: 6px;
    font-size: 13px;
}
/* 悬停 = 浅色底（设计规范 §17：soft hover，不用实心蓝），文字保持主题色 */
QMenu::item:selected {
    background: $hover;
    color: $text;
}
QMenu::item:disabled {
    color: $btn_disabled_text;
}
QMenu::separator {
    height: 1px;
    background: $menu_separator;
    margin: 4px 10px;
}

/* 工具提示：Apple 深色浮层（设计规范 §25：7px 圆角、11-12px 字，
   浅/深主题同一深底白字） */
QToolTip {
    background-color: $tooltip_bg;
    color: #FFFFFF;
    border: none;
    border-radius: 7px;
    padding: 6px 8px;
    font-size: 12px;
}

/* 详情弹层：背景必须不透明（macOS 的 Qt.Popup 是 NSPanel，可能走透明合成，
   曾导致 QPlainTextEdit 首行渲染错位——§9 坑速查）；元信息与按钮 */
QWidget#itemDetail {
    background: $window;
}
QLabel#detailMeta { color: $secondary; font-size: 12px; }
QLabel#detailStats { color: $secondary; font-size: 11px; padding-top: 2px; }

/* 自绘下拉框（ui/fluent_combo.py）：闭合态由 paintEvent 自绘（不用 QSS，
   规避 §9 的 QComboBox QSS 坑）；只有**弹层**（普通 QWidget/QListWidget）走 QSS。
   弹层同 Quick Paste 范式：透明容器 + 圆角卡片——非透明顶层窗口直接写
   border-radius 会露出直角残影，故圆角只画在内层卡片上 */
QWidget#fluentComboPopup {
    background: transparent;
}
QFrame#fluentComboCard {
    background: $window;
    border: 1px solid $separator;
    border-radius: 8px;
}
QListWidget#fluentComboList {
    background: transparent;
    border: none;
    outline: none;
    font-size: 13px;
}
QListWidget#fluentComboList::item {
    height: 28px;
    border-radius: 6px;
    padding: 0 8px;
    color: $text;
}
QListWidget#fluentComboList::item:hover { background: $hover_item; }
QListWidget#fluentComboList::item:selected {
    background: $selection_bg;
    color: $selection_text;
}

/* 按钮统一：默认 = 浅灰底 + 9px 圆角（设计规范 §5.1）。未指定
   objectName 的按钮（个别「取消」）也落到统一外观；各具名按钮
   （primary/secondary/ghost/…）用 id 规则覆盖默认底。 */
QPushButton {
    background: $content;
    border: none;
    border-radius: 9px;
    color: $text;
    font-size: 13px;
}
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
QPushButton#primaryButton:hover { background: $accent_soft_hover; }
QPushButton#primaryButton:pressed { background: $accent_soft_pressed; }
QPushButton#primaryButton:disabled {
    background: $accent_soft_disabled;
    color: $btn_disabled_text;
}
QPushButton#secondaryButton {
    background: $search_bg;
    color: $text;
}
QPushButton#secondaryButton:hover { background: $secondary_hover; }
QPushButton#secondaryButton:pressed { background: $secondary_pressed; }
QPushButton#secondaryButton:disabled { color: $btn_disabled_text; }
/* destructive：破坏性操作（清空/删除）确认按钮，macOS 红色惯例 */
QPushButton#destructiveButton {
    background: #FF453A;
    color: #FFFFFF;
    border: none;
    border-radius: 6px;
    padding: 6px 18px;
}
QPushButton#destructiveButton:hover { background: #E5433A; }
QPushButton#destructiveButton:pressed { background: #D63A30; }
QPushButton#destructiveButton:disabled {
    background: $accent_soft_disabled;
    color: $btn_disabled_text;
}

/* 状态栏 */
QStatusBar { color: $secondary; font-size: 11px; background: transparent; }
QStatusBar::item { border: none; }
/* 隐私模式状态指示（📋 / 🔒，§9.4） */
QLabel#privacyStatus { color: #34C759; font-size: 11px; padding: 0 8px; }
QLabel#privacyStatus[paused="true"] { color: $secondary; }

/* 设置页分区标题（隐私模式等） */
QLabel#sectionTitle { color: $secondary; font-size: 12px; font-weight: 600; }

/* 设置页滚动容器：透明背景、无边框（内容少时不露灰底） */
QScrollArea { background: transparent; border: none; }
QWidget#settingsContainer { background: transparent; }

/* QComboBox 全部保持 Qt 原生 macOS 外观，不写任何 QSS：
   ⚠️ 现行做法：本应用已在调用点改用自绘下拉框 ui/fluent_combo.py
   （Fluent 观感，避开下面的坑），下述约束针对**残留的真 QComboBox**依然成立。
   ——
   实测（§9）在 macOS 上给 QComboBox 设 QSS 背景/border 会：
   1) 尾部 drop-down 区域渗出原生按钮的灰色矩形块；
   2) `border: 1px solid transparent` 渲染成顶部/边缘灰色线段；
   3) 弹层改成样式化 QListView 后内容显示不全（原生菜单自动适配宽度、
   完整显示全部选项，macOS 原生的下拉箭头 + 扁平外观即设计规范 §8 目标）。
   需要一致性时改代码（setFixedSize / QProxyStyle），不靠 QSS。
   ⚠️ 也不得给 QComboBox QAbstractItemView 写规则——同样会触发
   样式化弹层导致裁剪。
   （原 #sessionCombo / #searchScope 样式已移除；searchScope 未再用。）
   深色主题跟随：原生组合框深/浅外观由 apply_theme() 的
   QStyleHints.setColorScheme() 切换（macOS 上即设置 NSAppearance），
   不要试图用 QSS 覆盖 macStyle 的 bezel。 */
/* 会话管理菜单按钮：圆形省略号 */
QPushButton#sessionMenuBtn {
    background: transparent;
    border: none;
    border-radius: 6px;
    color: $secondary;
    font-size: 15px;
}
QPushButton#sessionMenuBtn:hover { background: $search_bg; }

/* 会话创建时间（右侧靠右，次要灰——填充 ⋯ 按钮右侧留白） */
QLabel#sessionCreated { color: $secondary; font-size: 12px; }

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

/* 搜索范围（全部会话/本会话）：Apple 风格 segmented——外层灰底圆角，
   选中项白块 + 深字（UI 优化：取代大蓝块；objectName 独立于模板页
   segGroup，互不影响） */
QFrame#scopeSeg {
    background: $search_bg;
    border-radius: 10px;
}
QPushButton#scopeSegBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    color: $secondary;   /* 次要灰：深色主题下不再被硬编码 #6E6E73 吃掉 */
    font-size: 12px;
    min-height: 28px;   /* 填满外层 seg 36px（减 margins 3×2） */
}
QPushButton#scopeSegBtn:hover { background: $hover; }
QPushButton#scopeSegBtn:checked {
    background: $window;
    color: $text;
    font-weight: 500;
}

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
/* ghost：工具栏次要操作（展开/变量库/新增）——设计规范 §5.4 透明底，
   hover/pressed 浅色反馈（原为实心灰，改透明更接近 Apple 工具栏） */
QPushButton#ghostBtn {
    background: transparent;
    border: none;
    border-radius: 8px;
    padding: 4px 10px;
    color: $secondary;
    font-size: 13px;
}
QPushButton#ghostBtn:hover { background: $ghost_hover; }
QPushButton#ghostBtn:pressed { background: $ghost_pressed; }
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

/* 「变量库」弹层：分组面板 + 行按钮（★ 在前，点击行插入/★ 切常用） */
QWidget#variableLibrary {
    background: $window;
    border: 1px solid $separator;
    border-radius: 10px;
}
QScrollArea#varLibraryScroll { background: transparent; border: none; }
QScrollArea#varLibraryScroll > QWidget > QWidget { background: transparent; }
QLabel#groupHeader {
    color: $secondary;
    font-size: 11px;
    padding: 5px 2px 2px 2px;
}
QPushButton#varLibRow {
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 5px 8px;
    color: $text;
    font-size: 12px;
    font-family: Menlo, Monaco, monospace;
    text-align: left;
}
QPushButton#varLibRow:hover { background: $hover; color: $accent; }

/* 变量自动补全弹层：不透明背景（macOS 弹层透明合成坑，§9） */
QWidget#variableAutocomplete {
    background: $window;
    border: 1px solid $separator;
    border-radius: 10px;
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
QPushButton#dangerBtn:hover { background: $danger_hover; }
QPushButton#dangerBtn:pressed { background: $danger_hover; }

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

/* 命名对话框校验错误：红字 + 输入框红框（同名会话/收藏夹新建失败时对话框内报错） */
QLabel#dialogError {
    color: #FF3B30;
    font-size: 12px;
    font-weight: 600;
}
QLineEdit[error="true"] {
    border: 1px solid #FF3B30;
}
""")


def _resolve_mode(app: QApplication, mode: str) -> str:
    """把 system 解析为 light/dark；返回实际模式。"""
    if mode != "system":
        return mode
    # ⚠️ 必须用 Qt.ColorScheme.Dark 比较：PySide6 的 enum 与 int 不相等，
    #   旧的 `== 1`（Light）恒为 False → 系统深色恒解析成浅色（潜伏 bug）
    resolved = "dark" if app.styleHints().colorScheme() == Qt.ColorScheme.Dark else "light"
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
    """应用主题（mode: system / light / dark），返回实际生效的模式。

    macOS 原生控件（QComboBox 等）的外观跟随 NSAppearance，而不是 QPalette：
    QSS 无法覆盖 macStyle 的原生 bezel（§9 坑），深色主题下不加处理，
    原生组合框会保持系统浅色外观、白底 + 应用深色浅字 → 不可读。
    Qt 6.8+ 的 QStyleHints.setColorScheme() 从根上切换整个应用的原生外观
    （macOS 上即设置 NSAppearance），原生控件随之正确变深/变浅，且不动 popup。
    """
    global _CURRENT_PALETTE
    if mode == "system":
        # 跟随系统：先解除可能残留的强制外观，再读系统真实值
        app.styleHints().unsetColorScheme()
        resolved = _resolve_mode(app, mode)
    else:
        resolved = mode
        scheme = Qt.ColorScheme.Dark if resolved == "dark" else Qt.ColorScheme.Light
        app.styleHints().setColorScheme(scheme)
        logger.info("强制原生外观: %s", scheme.name)
    palette = LIGHT if resolved == "light" else DARK
    _CURRENT_PALETTE = palette          # 供自绘控件（fluent_combo 等）取色
    app.setPalette(_build_palette(palette))
    app.setStyleSheet(build_stylesheet(palette))
    logger.info("主题已应用: %s", resolved)
    return resolved
