"""时间线页：今天 / 昨天 / 本周 / 更早（按月）分段浏览（DEVELOPMENT.md §4.7）。

顶部横向分段选择器（复用顶部导航样式），选择后只显示该时间段；
「更早」内按月分组（带月份标题）。点击条目 → 详情弹层。

条目复用 HistoryDelegate 渲染（与历史/收藏夹一致：两行布局、卡片
底色、间隔、代码/敏感/缩略图）——之前用裸 QListWidget 文本行，
内容紧紧挨着显示（实测踩坑）。
"""
import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QModelIndex, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QLabel,
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

        # 时间段分段选择器（与历史页类型条同款：四周圆角 QSS）。
        # ⚠️ 必须整行铺满、不能缩到默认 sizeHint 256px：QSS 胶囊 4 个共
        # ~272px，容器若是 256px 会把尾部「更早」裁掉、需左右滑动（曾出此 bug）。
        # 计数标签叠加在透明区右端，不占用布局宽度。
        self._tabs = QListWidget()
        self._tabs.setObjectName("typeTabs")
        self._tabs.setFlow(QListView.Flow.LeftToRight)
        # ⚠️ 高度必须 40（与历史页 typeTabs 一致）：QSS item 高 30px + 上下
        # margin 4px = 38px，容器若 30px 会把选中蓝胶囊上下裁切（曾显示不全）。
        self._tabs.setFixedHeight(40)
        self._tabs.setSpacing(2)
        self._tabs.setFrameShape(QListWidget.Shape.NoFrame)
        self._tabs.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._tabs.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for label, _ in _BUCKETS:
            self._tabs.addItem(QListWidgetItem(label))
        self._tabs.currentRowChanged.connect(self._on_bucket_selected)
        self._tabs.installEventFilter(self)  # Resize → 重定位计数标签
        layout.addWidget(self._tabs)

        # 当前时间段条目计数（留白处用途）：切段更新，如「12 条」。
        # 作为 _tabs 子控件叠加在透明区右端（不挤占胶囊宽度），右缘贴容器边。
        self._count_label = QLabel("", self._tabs)
        self._count_label.setObjectName("timelineCount")
        self._count_label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self._count_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # 不挡点击
        self._position_count_label()

        # 条目列表：QListView + HistoryDelegate（与历史页一致的渲染）
        self._model = QStandardItemModel(self)
        self._list = QListView()
        self._list.setObjectName("historyList")
        self._list.setMouseTracking(True)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 逐像素滚动：默认 ScrollPerItem 会把触控板像素 delta 量化成整行
        # （与历史页一致，见 history_view）
        self._list.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
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

    def eventFilter(self, obj, event) -> bool:
        """_tabs 尺寸变化 → 计数标签保持贴右端（tabs 铺满页宽，宽恒定）。"""
        if obj is self._tabs and event.type() == QEvent.Type.Resize:
            self._position_count_label()
        return super().eventFilter(obj, event)

    def _position_count_label(self) -> None:
        """计数标签叠加定位：右缘贴 tabs 右缘（QSS padding-right 12px 留边）。"""
        self._count_label.adjustSize()
        w, h = self._count_label.width(), self._count_label.height()
        self._count_label.setGeometry(self._tabs.width() - w,
                                      (self._tabs.height() - h) // 2, w, h)

    def reload(self) -> None:
        """重载分组数据，保持当前时间段选择。"""
        if self._engine is None:
            return
        self._groups = history_service.list_grouped(self._engine)
        self._on_bucket_selected(self._tabs.currentRow())

    # ---- 渲染 ----

    def _bucket_counts(self) -> dict[str, int]:
        """各时间段条目数：今天/昨天/本周按桶名，月份桶全归「更早」。"""
        counts = {"今天": 0, "昨天": 0, "本周": 0, "更早": 0}
        for label, items in self._groups:
            if label in counts:
                counts[label] += len(items)
            else:  # 「YYYY年M月」月份桶 → 更早
                counts["更早"] += len(items)
        return counts

    def _on_bucket_selected(self, row: int) -> None:
        self._model.clear()
        if not (0 <= row < len(_BUCKETS)):
            return
        _, match = _BUCKETS[row]
        # 右侧计数随当前时间段更新（「更早」= 所有月份桶之和）
        counts = self._bucket_counts()
        self._count_label.setText(f"{counts[_BUCKETS[row][0]]} 条")
        self._position_count_label()  # QLabel 不随文本变宽，须重算并贴右
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
