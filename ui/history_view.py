"""历史列表视图。

TODO(V1 打磨): 换成 QListView + 自定义 delegate（分页加载、缩略图、类型图标、
右键菜单：Copy / Pin / Favorite / Add To Collection / Action 子菜单）。
"""
import logging

from PySide6.QtWidgets import QListWidget, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class HistoryView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._list = QListWidget()
        self._list.setUniformItemSizes(True)
        self._list.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)

    def add_item(self, clipboard_item) -> None:
        """追加一条历史（最新在上）。"""
        text = f"{clipboard_item.display_text()}\n{clipboard_item.type}"
        self._list.insertItem(0, text)

    def mark_duplicate(self, clipboard_item) -> None:
        """重复内容：不新增，仅刷新状态栏（列表不动）。"""
        logger.debug("去重: %s", clipboard_item.hash[:12])

    def set_query(self, query: str) -> None:
        """顶部搜索栏联动。TODO: 接入 SearchService（DEVELOPMENT.md §3.4）。"""
        logger.debug("搜索查询（待接入）: %s", query)
