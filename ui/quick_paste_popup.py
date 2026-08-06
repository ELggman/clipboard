"""Quick Paste 弹出层（⌘⇧V 触发）：最近历史列表。

方向键上下、Enter 重新复制、Esc/点击外部关闭（Qt.Popup 自带）。
TODO(V1.5): accessory 激活策略（打包为 LSUIElement 后弹窗需先激活再显示）。
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QListWidget, QWidget

logger = logging.getLogger(__name__)

# 类型 → 行首图标（emoji 轻量替代 SF Symbols）
_TYPE_ICON = {"text": "📝", "url": "🔗", "image": "🖼️", "file": "📄"}


class QuickPastePopup(QWidget):
    selected = Signal(object)  # ClipboardItem

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setObjectName("quickPaste")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._items: list = []
        self._list = QListWidget(self)
        self._list.setObjectName("historyList")
        self._list.setUniformItemSizes(True)
        self.resize(420, 320)

    def populate(self, items: list) -> None:
        """填充最近历史。items 最新在前。"""
        self._items = items
        self._list.clear()
        for item in items:
            self._list.addItem(self._row_text(item))
        self._list.setCurrentRow(0)
        self.adjustSize()
        self.show()
        self._list.setFocus()

    def show_near_cursor(self) -> None:
        """定位在光标上方（避免遮住正在查看的内容），边界钳制到屏幕内。"""
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = max(geo.left(), min(cursor.x() - 8, geo.right() - self.width() - 8))
        y = max(geo.top(), min(cursor.y() - self.height() - 8,
                               geo.bottom() - self.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()
        self._list.setFocus()

    @staticmethod
    def _row_text(item) -> str:
        icon = _TYPE_ICON.get(item.type, "•")
        return f"{icon}  {item.display_text(max_len=200)}"

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            row = self._list.currentRow()
            if 0 <= row < len(self._items):
                self.selected.emit(self._items[row])
            self.close()
            return
        super().keyPressEvent(event)
