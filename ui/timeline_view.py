"""时间线页：今天 / 昨天 / 本周 / 更早（按月）分段浏览（DEVELOPMENT.md §4.7）。

顶部横向分段选择器（复用顶部导航样式），选择后只显示该时间段；
「更早」内按月分组（带月份标题）。点击条目 → 详情弹层。

条目复用 HistoryDelegate 渲染（与历史/收藏夹一致：两行布局、卡片
底色、间隔、代码/敏感/缩略图）——之前用裸 QListWidget 文本行，
内容紧紧挨着显示（实测踩坑）。
"""
import logging
from pathlib import Path

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QListView,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from services import history_service
from ui.history_view import (
    BASE_WIDTH,
    ROLE_HEADER,
    ROLE_ITEM,
    HistoryDelegate,
)

logger = logging.getLogger(__name__)

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
        self._tabs.setFixedHeight(30)
        self._tabs.setSpacing(2)
        self._tabs.setFrameShape(QListWidget.Shape.NoFrame)
        self._tabs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tabs.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label, _ in _BUCKETS:
            self._tabs.addItem(QListWidgetItem(label))
        self._tabs.currentRowChanged.connect(self._on_bucket_selected)
        layout.addWidget(self._tabs)

        # 条目列表：QListView + HistoryDelegate（与历史页一致的渲染）
        self._model = QStandardItemModel(self)
        self._list = QListView()
        self._list.setObjectName("historyList")
        self._list.setMouseTracking(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setSpacing(4)  # 条目间隔（与历史页一致）
        self._list.setModel(self._model)
        self._delegate = HistoryDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        self._list.clicked.connect(self._on_item_clicked)
        layout.addWidget(self._list, 1)

        self._tabs.setCurrentRow(0)

    def set_context(self, engine, image_service=None) -> None:
        """注入数据库引擎（bootstrap 装配），打开页面时自动刷新。"""
        self._engine = engine
        if image_service is not None:
            self._delegate.set_image_service(image_service)
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._engine is not None:
            self.reload()

    def resizeEvent(self, event) -> None:
        """窗口放大 → 内容等比例放大（与历史页一致）。"""
        super().resizeEvent(event)
        scale = event.size().width() / BASE_WIDTH
        self._delegate.set_scale(scale)
        self._list.setSpacing(max(2, round(4 * scale)))
        self._list.doItemsLayout()

    def reload(self) -> None:
        """重载分组数据，保持当前时间段选择。"""
        if self._engine is None:
            return
        self._groups = history_service.list_grouped(self._engine)
        self._on_bucket_selected(self._tabs.currentRow())

    # ---- 渲染 ----

    def _on_bucket_selected(self, row: int) -> None:
        self._model.clear()
        if not (0 <= row < len(_BUCKETS)):
            return
        _, match = _BUCKETS[row]
        if match is None:
            # 更早：所有月份桶，带月份标题
            for label, items in self._groups:
                if "月" in label:
                    self._model.appendRow(self._make_header(label))
                    for item in items:
                        self._model.appendRow(self._make_row(item))
        else:
            for label, items in self._groups:
                if label == match:
                    for item in items:
                        self._model.appendRow(self._make_row(item))

    @staticmethod
    def _make_header(label: str) -> QStandardItem:
        header = QStandardItem()
        header.setData(label, ROLE_HEADER)
        header.setEditable(False)
        return header

    @staticmethod
    def _make_row(item) -> QStandardItem:
        row = QStandardItem()
        row.setData(item, ROLE_ITEM)
        row.setEditable(False)
        return row

    def _on_item_clicked(self, index: QModelIndex) -> None:
        item = index.data(ROLE_ITEM)
        if item is not None:
            self.item_activated.emit(item)
