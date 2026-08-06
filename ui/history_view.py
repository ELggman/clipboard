"""历史列表视图。

TODO(V1 打磨): 换成 QListView + 自定义 delegate（分页加载、右键菜单：
Copy / Pin / Favorite / Add To Collection / Action 子菜单）。
缩略图已接入：image 条目由 ImageService 懒加载（DEVELOPMENT.md §3.5）。
"""
import logging

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)

THUMB_SIZE = 44  # 列表缩略图边长（image_service 缓存 256px 图源）


class HistoryView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setUniformItemSizes(True)
        self._list.setWordWrap(True)
        self._list.setIconSize(QSize(THUMB_SIZE, THUMB_SIZE))
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._thumbnail_provider = None  # ImageService，由 bootstrap 注入
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)

    def set_image_service(self, service) -> None:
        """注入图片服务：image 条目按需加载缩略图（内存 LRU 缓存）。"""
        self._thumbnail_provider = service

    def set_items(self, items: list) -> None:
        """整体替换列表（启动恢复 / 搜索结果），items 最新在前。"""
        self._list.clear()
        for item in items:
            self._list.addItem(self._make_row(item))

    @staticmethod
    def _item_text(item) -> str:
        """列表行文案：`时间 · 类型` + 内容（与需求示例一致）。"""
        prefix = f"{item.created_at} · " if item.created_at else ""
        return f"{prefix}{item.type}\n{item.display_text()}"

    def add_item(self, clipboard_item) -> None:
        """追加一条实时捕获（最新在上）。"""
        self._list.insertItem(0, self._make_row(clipboard_item))

    def _make_row(self, item) -> QListWidgetItem:
        """构建列表行：文本 +（图片条目的）缩略图。"""
        row = QListWidgetItem(self._item_text(item))
        icon = self._thumbnail(item)
        if icon is not None:
            row.setIcon(icon)
        return row

    def _thumbnail(self, item):
        """image 条目懒加载缩略图；失败/缺失时返回 None（仅显示文本）。"""
        if item.type != "image" or not item.file_path or self._thumbnail_provider is None:
            return None
        qimg = self._thumbnail_provider.thumbnail(item.file_path)
        if qimg is None:
            return None
        return QIcon(QPixmap.fromImage(qimg))

    def mark_duplicate(self, clipboard_item) -> None:
        """重复内容：不新增，仅刷新状态栏（列表不动）。"""
        logger.debug("去重: %s", clipboard_item.hash[:12])

    def set_query(self, query: str) -> None:
        """顶部搜索栏联动。TODO: 接入 SearchService（DEVELOPMENT.md §3.4）。"""
        logger.debug("搜索查询（待接入）: %s", query)
