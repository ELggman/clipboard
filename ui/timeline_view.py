"""时间线页：今天 / 昨天 / 本周 / 更早（按月）分段浏览（DEVELOPMENT.md §4.7）。

顶部横向分段选择器（复用顶部导航样式），选择后只显示该时间段；
「更早」内按月分组（带月份标题）。点击条目 → 详情弹层。
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services import history_service

logger = logging.getLogger(__name__)

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # 条目 item 存 ClipboardItem

# 分段选择：label → 分组匹配（None 表示「更早」= 所有月份桶）
_BUCKETS = [("今天", "今天"), ("昨天", "昨天"), ("本周", "本周"), ("更早", None)]


class TimelineView(QWidget):
    item_activated = Signal(object)  # 点击条目 → 详情弹层

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._engine = None
        self._groups: list[tuple[str, list]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 时间段分段选择器（复用顶部导航 QSS）
        self._tabs = QListWidget()
        self._tabs.setObjectName("topnav")
        self._tabs.setFlow(QListView.Flow.LeftToRight)
        self._tabs.setFixedHeight(34)
        self._tabs.setSpacing(2)
        self._tabs.setFrameShape(QListWidget.Shape.NoFrame)
        self._tabs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tabs.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label, _ in _BUCKETS:
            self._tabs.addItem(QListWidgetItem(label))
        self._tabs.currentRowChanged.connect(self._on_bucket_selected)
        layout.addWidget(self._tabs)

        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setUniformItemSizes(False)
        self._list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

        self._tabs.setCurrentRow(0)

    def set_context(self, engine) -> None:
        """注入数据库引擎（bootstrap 装配），打开页面时自动刷新。"""
        self._engine = engine
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._engine is not None:
            self.reload()

    def reload(self) -> None:
        """重载分组数据，保持当前时间段选择。"""
        if self._engine is None:
            return
        self._groups = history_service.list_grouped(self._engine)
        self._on_bucket_selected(self._tabs.currentRow())

    # ---- 渲染 ----

    def _on_bucket_selected(self, row: int) -> None:
        self._list.clear()
        if not (0 <= row < len(_BUCKETS)):
            return
        _, match = _BUCKETS[row]
        if match is None:
            # 更早：所有月份桶，带月份标题
            for label, items in self._groups:
                if "月" in label:
                    self._list.addItem(self._make_header(label))
                    for item in items:
                        self._list.addItem(self._make_row(item))
        else:
            for label, items in self._groups:
                if label == match:
                    for item in items:
                        self._list.addItem(self._make_row(item))

    @staticmethod
    def _make_header(label: str) -> QListWidgetItem:
        header = QListWidgetItem(label)
        header.setFlags(Qt.ItemFlag.NoItemFlags)  # 不可选中不可交互
        font = QFont()
        font.setBold(True)
        header.setFont(font)
        return header

    @staticmethod
    def _make_row(item) -> QListWidgetItem:
        row = QListWidgetItem(
            f"{item.created_at} · {item.type}\n{item.display_text()}")
        row.setData(ROLE_ITEM, item)
        return row

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        entry = item.data(ROLE_ITEM)
        if entry is not None:
            self.item_activated.emit(entry)
