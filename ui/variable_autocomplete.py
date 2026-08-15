r"""变量自动补全（`{{` 触发）：模板内容编辑器输入 `{{` 弹候选列表。

- 触发：光标前文本匹配 `\{\{(\w*)$`（\w 含中文，支持中文变量名）→ 按
  前缀过滤候选（注册表内置 + 用户自定义，filter_candidates）
- ↑↓ 移动选择、Enter 接受、Esc/失焦关闭；其他键照常编辑（继续过滤）
- 接受时把光标前的 `{{` 替换为完整变量文本；input 变量走后缀规则
  （{{input:name}} 已存在 → 插 {{input:name2}}，next_input_insert）
- 候选排序：常用（config favorite_variables，默认全部预设）在前，
  其余按来源类别

⚠️ 弹层不用 Qt.Popup（会夺键盘焦点，编辑器收不到 ↑↓/Enter）：用
FramelessWindowHint + WA_ShowWithoutActivating 顶层窗，编辑器持焦点并
转发方向键/回车/Esc，失焦即隐藏。点击列表项同样接受。
"""
import re

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent, QTextCursor
from PySide6.QtWidgets import (
    QListWidget,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.template.registry import (
    filter_candidates,
    next_input_insert,
)
from ui.template_components import load_favorite_variables

_TRIGGER_RE = re.compile(r"\{\{(\w*)$")


class _CandidatePopup(QWidget):
    """候选弹层：QListWidget 列表 + 定位在光标下方。"""

    selected = Signal(str)  # 插入文本

    def __init__(self, parent=None):
        # ⚠️ 必须带 Qt.Window：否则只是编辑器的**子控件**，被裁剪在编辑器
        # 内部（实测 2026-08：缺 Qt.Window 时补全弹层永不出现）。配合
        # WA_ShowWithoutActivating 顶层窗 + NoFocus，编辑器保持键盘焦点并
        # 转发方向键/回车/Esc；StaysOnTopHint 保证浮在主窗之上。
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Window
                         | Qt.WindowStaysOnTopHint)
        self.setObjectName("variableAutocomplete")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._inserts: list[str] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setUniformItemSizes(True)
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay.addWidget(self._list)

    def show_at(self, inserts: list[str], global_pos) -> None:
        self._inserts = inserts
        self._list.clear()
        for ins in inserts:
            self._list.addItem(ins)
        self._list.setCurrentRow(0)
        self.adjustSize()
        w = max(self.sizeHint().width(), 200)
        h = min(self.sizeHint().height(), 200)
        self.resize(w, h)
        # 屏幕边缘夹紧（光标附近弹层不能被推出屏幕外）
        x, y = global_pos.x(), global_pos.y() + 6
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - self.width()))
            y = max(geo.top(), min(y, geo.bottom() - self.height()))
        self.move(x, y)
        self.show()
        self.raise_()

    def move_selection(self, delta: int) -> None:
        n = self._list.count()
        if n == 0:
            return
        row = self._list.currentRow()
        self._list.setCurrentRow((row + delta) % n)

    def current_insert(self) -> str | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._inserts):
            return self._inserts[row]
        return None

    def mousePressEvent(self, event) -> None:
        super().mousePressEvent(event)
        item = self._list.itemAt(event.position().toPoint())
        if item is not None:
            self._list.setCurrentRow(self._list.row(item))
            ins = self.current_insert()
            if ins is not None:
                self.selected.emit(ins)
                self.hide()


class VariableAutocompleteEditor(QPlainTextEdit):
    """模板内容编辑器：输入 `{{` 弹变量补全候选。

    set_custom_variables() 注入用户自定义变量（编辑弹窗变量区增删时同步）。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._custom: list[str] = []
        self._popup = _CandidatePopup(self)
        self._popup.selected.connect(self._accept)
        self.textChanged.connect(self._maybe_update)
        self.cursorPositionChanged.connect(self._maybe_update)
        # 弹层失焦隐藏：延时判定（真实失焦才关；弹层 show() 的异步夺焦
        # 由 _recent_show + _restore_focus 补偿，见 focusOutEvent）
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(30)
        self._hide_timer.timeout.connect(self._maybe_hide_popup)
        # 「刚显示弹层」标记：show() 后短暂窗口内的 focusOut 视为弹层自身
        # 夺焦（offscreen 平台实测；真 macOS WA_ShowWithoutActivating 不会夺焦），
        # 超时清除，避免把用户真实的点击离开误判为夺焦
        self._recent_show = False
        self._recent_show_timer = QTimer(self)
        self._recent_show_timer.setSingleShot(True)
        self._recent_show_timer.setInterval(100)
        self._recent_show_timer.timeout.connect(
            lambda: setattr(self, "_recent_show", False))

    def set_custom_variables(self, custom: list[str]) -> None:
        """外部注入用户自定义变量（编辑弹窗「＋ 新增/删除」时同步）。"""
        self._custom = list(custom)

    # ---- 触发 / 更新 ----

    def _current_prefix(self) -> str | None:
        tc = self.textCursor()
        text = self.toPlainText()[: tc.position()]
        m = _TRIGGER_RE.search(text)
        return m.group(1) if m else None

    def _maybe_update(self) -> None:
        if not self.isVisible() or not self.hasFocus():
            self._popup.hide()
            return
        prefix = self._current_prefix()
        if prefix is None:
            self._popup.hide()
            return
        cands = filter_candidates(prefix, self._custom, load_favorite_variables())
        if not cands:
            self._popup.hide()
            return
        if self._popup.isVisible() and self._popup._inserts == cands:
            return  # 弹层已显示相同候选：不重建（防 focusIn 重入反复 show）
        pos = self.viewport().mapToGlobal(self.cursorRect().bottomLeft())
        self._popup.show_at(cands, pos)
        self._mark_recent_show()

    def _mark_recent_show(self) -> None:
        """标记刚显示弹层（show() 在部分平台会异步夺焦编辑器）。"""
        self._recent_show = True
        self._recent_show_timer.start()

    def _restore_focus(self) -> None:
        """弹层 show() 夺焦补偿：焦点还给编辑器（无夺焦时为 no-op）。"""
        self._recent_show = False
        if not self.hasFocus():
            self.activateWindow()
            self.setFocus()

    def _maybe_hide_popup(self) -> None:
        """延时失焦判定：焦点确已离开编辑器才关弹层。"""
        if not self.hasFocus():
            self._popup.hide()

    # ---- 键盘路由 ----

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._popup.isVisible():
            key = event.key()
            if key in (Qt.Key_Down, Qt.Key_Up):
                self._popup.move_selection(1 if key == Qt.Key_Down else -1)
                return
            if key in (Qt.Key_Return, Qt.Key_Enter):
                ins = self._popup.current_insert()
                if ins is not None:
                    self._popup.selected.emit(ins)
                else:
                    self._popup.hide()
                return
            if key == Qt.Key_Escape:
                self._popup.hide()
                return
        super().keyPressEvent(event)

    # ---- 接受 ----

    def _accept(self, insert: str) -> None:
        """把光标前的 `{{` 替换为完整变量文本（input 走后缀规则）。"""
        tc = self.textCursor()
        pos = tc.position()
        text = self.toPlainText()
        start = text.rfind("{{", 0, pos)
        if start == -1:
            start = pos
        if insert.startswith("{{input:") and insert.endswith("}}"):
            base = insert[len("{{input:"):-len("}}")]
            insert = next_input_insert(text[:start], base)
        tc.setPosition(start)
        tc.setPosition(pos, QTextCursor.MoveMode.KeepAnchor)
        tc.insertText(insert)
        self._popup.hide()
        self.setFocus()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        if self._recent_show:
            # 弹层 show() 的异步夺焦（真 macOS WA_ShowWithoutActivating 不会）：
            # 同步夺回焦点，不关弹层（singleShot 在处理器内排的队同一次
            # processEvents 不触发，实测 restore 要等下一次事件循环）
            self._restore_focus()
        else:
            # 真实失焦（点击别处/切应用）：延时确认后关弹层
            self._hide_timer.start()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._maybe_update()  # 点击进入光标前已是 {{… 的已有内容 → 立即弹
