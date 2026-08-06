"""时间线页：今天 / 昨天 / 本周 / 更早（按月）分组浏览（DEVELOPMENT.md §4.7）。

分组标题行（不可选中、次要色加粗），条目两行文本；点击条目 → 详情弹层。
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from services import history_service

logger = logging.getLogger(__name__)

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # 条目 item 存 ClipboardItem


class TimelineView(QWidget):
    item_activated = Signal(object)  # 点击条目 → 详情弹层

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._engine = None
        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setUniformItemSizes(False)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)

    def set_context(self, engine) -> None:
        """注入数据库引擎（bootstrap 装配），打开页面时自动刷新。"""
        self._engine = engine
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._engine is not None:
            self.reload()

    def reload(self) -> None:
        if self._engine is None:
            return
        self._list.clear()
        for label, items in history_service.list_grouped(self._engine):
            self._list.addItem(self._make_header(label))
            for item in items:
                row = QListWidgetItem(
                    f"{item.created_at} · {item.type}\n{item.display_text()}")
                row.setData(ROLE_ITEM, item)
                self._list.addItem(row)

    @staticmethod
    def _make_header(label: str) -> QListWidgetItem:
        header = QListWidgetItem(label)
        header.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选中不可交互
        font = QFont()
        font.setBold(True)
        header.setFont(font)
        return header

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(ROLE_ITEM)
        if entry is not None:
            self.item_activated.emit(entry)
