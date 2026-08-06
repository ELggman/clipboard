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

    def set_items(self, items: list) -> None:
        """整体替换列表（启动恢复 / 搜索结果），items 最新在前。"""
        self._list.clear()
        for item in items:
            self._list.addItem(self._item_text(item))

    @staticmethod
    def _item_text(item) -> str:
        """列表行文案：`时间 · 类型` + 内容（与需求示例一致）。"""
        prefix = f"{item.created_at} · " if item.created_at else ""
        return f"{prefix}{item.type}\n{item.display_text()}"

    def add_item(self, clipboard_item) -> None:
        """追加一条实时捕获（最新在上）。"""
        self._list.insertItem(0, self._item_text(clipboard_item))

    def mark_duplicate(self, clipboard_item) -> None:
        """重复内容：不新增，仅刷新状态栏（列表不动）。"""
        logger.debug("去重: %s", clipboard_item.hash[:12])

    def set_query(self, query: str) -> None:
        """顶部搜索栏联动。TODO: 接入 SearchService（DEVELOPMENT.md §3.4）。"""
        logger.debug("搜索查询（待接入）: %s", query)
