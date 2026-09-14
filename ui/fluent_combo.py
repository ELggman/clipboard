"""Fluent 风格下拉框（自绘，替代 QComboBox）。

为什么不用 QComboBox + QSS：见 ui/theme.py §9 —— macOS 上给 QComboBox 写 QSS
会 ① 尾部渗灰块 ② 边框渲染成灰线 ③ 样式化弹层裁剪内容，正是历史回归根因。
故这里**自绘闭合态**（paintEvent，取色自 ui.theme.current_palette），弹层用
一个**纯粹的 `Qt.Popup`**（不放关键字路由，原因见下）。

⚠️ 弹层**绝不能**调用 `ui.macos_patch.register_native_panel()`（真机实测）：
本应用启动时 quick paste / template picker 已把 `QNSPanel.canBecomeKeyWindow`
全局覆写装上，此时再把自己登记进 key 白名单 → 弹层会去抢 key window → 抢到后
Qt/macOS 因窗口激活变化把它 `hide()`（弹层自行消失），且此后它的窗口收不到鼠标
事件、点击直接穿透到下面的组件。四组对照实测（都装补丁）：

    登记白名单 + 取焦点 → ❌ 弹层自关 + 点击穿透
    登记白名单 + 不取焦点 → ❌ 同上（取焦点是无关变量）
    不登记 + 取焦点 → ✅ 点击落在弹层列表，正常选中
    不登记 + 不取焦点 → ✅ 同上

故本弹层**不登记白名单**（鼠标点击完全正常）。

键盘**照常可用**，已真机验证（cocoa + 装补丁 + 真 HID 键）：弹层确实不是
NS key window（NSApp.keyWindow() 仍是主窗口），但 Qt 按 **focusObject** 派发
按键——`open_popup()` 里的 `popup.list.setFocus()` 把 focusObject 设为
fluentComboList，NSEvent 从主窗口进来后由 Qt 转给该 focusObject。实测
↓ 移动 0→1、Enter 确认并收起、Esc 收起。故**不需要** key 白名单，
也不需要应用层事件过滤。

对齐的 QComboBox API 子集（由调用点反推，见迁移计划 §3）：
    addItem / count / itemText / itemData / findData / currentIndex /
    setCurrentIndex / currentData / currentText / clear / view /
    setSizeAdjustPolicy（空操作）/ currentIndexChanged(int)
"""
import logging
import time

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ui import theme

logger = logging.getLogger(__name__)

_HEIGHT = 30        # 闭合态高度（与 history_view 的「与下拉等高」标签对齐）
_RADIUS = 7
_PAD_H = 10         # 文本左右内边距
_CHEVRON_W = 20     # 右侧箭头区宽
_FONT_PX = 13
_ITEM_H = 28        # 弹层列表项高
_POPUP_PAD = 4      # 弹层卡片内边距
_MAX_POPUP_H = 280
_SHADOW_GAP = 18    # 弹层窗口比圆角卡片多出的阴影留白（同 quick_paste_popup）
_REOPEN_GUARD_S = 0.3   # 弹层收起后这段时间内，释放不开弹层（防「关掉又弹回」）


class _ComboPopup(QWidget):
    """下拉弹层：Qt.Popup 无边框面板 + 列表项（键盘 ↑↓/Enter/Esc）。"""

    chosen = Signal(int)     # 选中项 index
    dismissed = Signal()     # 关闭（Esc/点外部/选中后）

    def __init__(self, combo: "FluentComboBox"):
        super().__init__(combo, Qt.FramelessWindowHint | Qt.Popup)
        self._combo = combo
        self.setObjectName("fluentComboPopup")
        # 透明容器 + 外围阴影留白 → 圆角卡片。非透明顶层窗口直接写 QSS
        # border-radius 会露出直角残影，故与 quick_paste_popup 同范式：
        # 圆角/边框只画在内层卡片上，阴影画在留白区。
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW_GAP, _SHADOW_GAP, _SHADOW_GAP, _SHADOW_GAP)
        outer.setSpacing(0)
        self._card = QFrame(self)
        self._card.setObjectName("fluentComboCard")
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 60))
        self._card.setGraphicsEffect(shadow)
        outer.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(_POPUP_PAD, _POPUP_PAD, _POPUP_PAD, _POPUP_PAD)
        layout.setSpacing(0)
        self.list = QListWidget(self._card)
        self.list.setObjectName("fluentComboList")
        self.list.setFrameShape(QListWidget.Shape.NoFrame)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemClicked.connect(self._on_click)
        layout.addWidget(self.list)

    def place(self, x: int, y: int, width: int, height: int) -> None:
        """把圆角卡片摆到全局 (x, y, width, height)，窗口四周留出阴影区。"""
        self.resize(width + _SHADOW_GAP * 2, height + _SHADOW_GAP * 2)
        self.move(x - _SHADOW_GAP, y - _SHADOW_GAP)

    def set_items(self, texts: list[str], current: int) -> None:
        self.list.clear()
        for t in texts:
            item = QListWidgetItem(t)
            item.setSizeHint(QSize(0, _ITEM_H))
            self.list.addItem(item)
        self.list.setCurrentRow(current)

    def _on_click(self, item: QListWidgetItem) -> None:
        self.chosen.emit(self.list.row(item))

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            row = self.list.currentRow()
            if row >= 0:
                self.chosen.emit(row)
            return
        if key == Qt.Key.Key_Escape:
            self.close()
            return
        if key == Qt.Key.Key_Down:
            self.list.setCurrentRow(
                min(self.list.currentRow() + 1, self.list.count() - 1))
            return
        if key == Qt.Key.Key_Up:
            self.list.setCurrentRow(max(self.list.currentRow() - 1, 0))
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.dismissed.emit()


class FluentComboBox(QWidget):
    """自绘下拉框：闭合态 paintEvent 绘制，点击弹出 _ComboPopup。"""

    currentIndexChanged = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("fluentCombo")
        self._items: list[tuple[str, object]] = []
        self._index = -1
        self._hover = False
        self._open = False
        self._pressed = False        # 本次按下是否落在本控件内（拖入/拖出不算）
        self._suppress_open = False  # 刚收起弹层，别被随后的释放又打开
        self._suppress_open_until = 0.0   # 上一条的时间窗（见 mousePressEvent）
        self._popup: _ComboPopup | None = None

        font = QFont(self.font())
        font.setPixelSize(_FONT_PX)
        self.setFont(font)
        self.setFixedHeight(_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    # ---- QComboBox 子集 API ----

    def addItem(self, text: str, data: object = None) -> None:
        self._items.append((str(text), data))
        if self._index < 0:
            self._index = 0          # 首项自动选中（不emit，避免填充期误触槽）
        self.updateGeometry()
        self.update()

    def addItems(self, texts) -> None:
        for t in texts:
            self.addItem(t)

    def count(self) -> int:
        return len(self._items)

    def itemText(self, index: int) -> str:
        return self._items[index][0] if 0 <= index < len(self._items) else ""

    def itemData(self, index: int):
        return self._items[index][1] if 0 <= index < len(self._items) else None

    def currentIndex(self) -> int:
        return self._index

    def currentText(self) -> str:
        return self.itemText(self._index)

    def currentData(self):
        return self.itemData(self._index)

    def setCurrentIndex(self, index: int) -> None:
        if not (0 <= index < len(self._items)) or index == self._index:
            return
        self._index = index
        self.update()
        self.currentIndexChanged.emit(index)   # blockSignals 时 Qt 自动抑制

    def findData(self, value) -> int:
        for i, (_, data) in enumerate(self._items):
            if data == value:
                return i
        return -1

    def clear(self) -> None:
        self._items.clear()
        self._index = -1
        if self._popup is not None:
            self._popup.list.clear()
        self.update()

    def setSizeAdjustPolicy(self, *_args) -> None:
        """兼容 QComboBox.SizeAdjustPolicy 调用；自绘按内容自适应，忽略。"""

    def view(self) -> QListWidget:
        """弹层内部列表（history_view 用 setMinimumWidth 控制弹层最小宽）。"""
        self._ensure_popup()
        return self._popup.list

    # ---- 尺寸 / 绘制 ----

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        widest = max((fm.horizontalAdvance(t) for t, _ in self._items), default=0)
        return QSize(widest + _PAD_H * 2 + _CHEVRON_W, _HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return QSize(_PAD_H * 2 + _CHEVRON_W + 8, _HEIGHT)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pal = theme.current_palette()
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        background = QColor(pal["content"])
        if self._open or self.hasFocus():
            border = QColor(pal["accent_soft"])          # 打开/聚焦：强调边框
        else:
            border = QColor(pal["separator"])
            if self._hover:
                background = QColor(pal["search_bg"])    # 悬停：浅一档底
        painter.setPen(QPen(border, 1))
        painter.setBrush(background)
        painter.drawRoundedRect(rect, _RADIUS, _RADIUS)

        # 文本（过长省略号）
        fm = QFontMetrics(self.font())
        text_w = self.width() - _PAD_H * 2 - _CHEVRON_W
        elided = fm.elidedText(self.currentText(),
                               Qt.TextElideMode.ElideRight, max(0, text_w))
        painter.setPen(QColor(pal["text"]))
        painter.drawText(QRectF(_PAD_H, 0, text_w, self.height()),
                         int(Qt.AlignmentFlag.AlignVCenter
                             | Qt.AlignmentFlag.AlignLeft), elided)

        # 右侧下箭头（自绘，随主题取色）
        cx = self.width() - _PAD_H - 5
        cy = self.height() / 2
        path = QPainterPath()
        path.moveTo(cx - 4.5, cy - 2.2)
        path.lineTo(cx, cy + 2.2)
        path.lineTo(cx + 4.5, cy - 2.2)
        pen = QPen(QColor(pal["secondary"]), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()

    # ---- 交互 ----

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()

    def focusInEvent(self, event) -> None:
        self.update()

    def focusOutEvent(self, event) -> None:
        self.update()

    def mousePressEvent(self, event) -> None:
        """按下**不开**弹层，只记录；开弹层在 mouseReleaseEvent。

        为什么不能按下即开：Qt 对 `Qt.Popup` 有「弹层外按下 → 紧随的释放关闭
        该弹层」的机制，而按下那一刻弹层尚未显示，这次按下就被判为「弹层外」
        → 同一次点击的**释放会立刻把刚开的弹层关掉**，表现即「点不开/选不中」。
        （QTest.mouseClick 直投控件、绕过 QWidgetWindow 的这套判定，所以
        offscreen 能通过而真机复现——必须在释放时开。）

        顺带得到「按住拖开再松开 = 取消」的原生手感。
        """
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        inside = self.rect().contains(event.position().toPoint())
        self._pressed = inside
        if self._popup is not None and self._popup.isVisible():
            self._popup.close()            # 第二次点击：收起
            self._suppress_open = True     # 别让随后的释放又打开
        elif time.monotonic() < self._suppress_open_until:
            # Qt 判定「弹层外按下」会先关弹层、再把该次按下转发给底下的控件
            # （即本控件）。若不拦，这次点击的释放会立刻把弹层重新打开
            # ——表现为「点外面关掉又弹回来」。故弹层刚收起的一小段时间内
            # 不接受释放开弹层。
            self._suppress_open = True
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mouseReleaseEvent(event)
            return
        if self._suppress_open:
            self._suppress_open = False
        elif self._pressed and self.rect().contains(event.position().toPoint()):
            self.open_popup()              # 按在控件内、也在控件内松开才算点击
        self._pressed = False
        event.accept()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.open_popup()
            return
        super().keyPressEvent(event)

    # ---- 弹层 ----

    def _ensure_popup(self) -> None:
        if self._popup is None:
            self._popup = _ComboPopup(self)
            self._popup.chosen.connect(self._on_chosen)
            self._popup.dismissed.connect(self._on_dismissed)

    def open_popup(self) -> None:
        if not self._items:
            return
        self._ensure_popup()
        popup = self._popup
        popup.set_items([t for t, _ in self._items], self._index)

        # 弹层宽 = max(按钮宽, 最宽项 + 内边距, view().minimumWidth())
        fm = QFontMetrics(self.font())
        widest = max((fm.horizontalAdvance(t) for t, _ in self._items), default=0)
        width = max(self.width(),
                    widest + _PAD_H * 2 + _CHEVRON_W,
                    popup.list.minimumWidth())
        height = min(_MAX_POPUP_H,
                     len(self._items) * _ITEM_H + _POPUP_PAD * 2 + 2)

        anchor = self.mapToGlobal(QPoint(0, 0))
        screen = (QGuiApplication.screenAt(anchor)
                  or QGuiApplication.primaryScreen())
        geo = screen.availableGeometry()
        x = max(geo.left(), min(anchor.x(), geo.right() - width))
        y = anchor.y() + self.height() + 2
        if y + height > geo.bottom():                 # 下方不足 → 翻到上方
            y = max(geo.top(), anchor.y() - height - 2)
        popup.place(x, y, width, height)

        self._open = True
        self.update()
        popup.show()
        popup.raise_()
        # 注意：这里**故意不调用** register_native_panel()（原因见模块 docstring）
        from ui.animations import fade_in_window

        fade_in_window(popup, dy=0)
        popup.setFocus()
        popup.list.setFocus()

    def _on_chosen(self, index: int) -> None:
        if self._popup is not None:
            self._popup.close()
        # 这是「选中」而非「点外面」收起的，不必防重开：清掉时间窗，
        # 用户选完可以立刻再点开换一个。
        self._suppress_open_until = 0.0
        self.setCurrentIndex(index)

    def _on_dismissed(self) -> None:
        self._open = False
        self._suppress_open_until = time.monotonic() + _REOPEN_GUARD_S
        self.update()
