"""Quick Paste 弹出层（⌘⇧V 触发）：最近历史列表。

方向键上下、Enter 重新复制、Esc/点击外部关闭（Qt.Popup 自带）。
TODO: 定位策略（光标附近/屏幕中央）；accessory 应用需先激活再显示
（DEVELOPMENT.md §4.3，否则打包版窗口不渲染）。
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QListWidget, QWidget

logger = logging.getLogger(__name__)


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
        """填充最近历史并定位。items 最新在前。"""
        self._items = items
        self._list.clear()
        for item in items:
            self._list.addItem(item.display_text(max_len=200))
        self._list.setCurrentRow(0)
        self.adjustSize()
        self.show()
        self._list.setFocus()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            row = self._list.currentRow()
            if 0 <= row < len(self._items):
                self.selected.emit(self._items[row])
            self.close()
            return
        super().keyPressEvent(event)
