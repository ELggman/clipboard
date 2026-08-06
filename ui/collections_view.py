"""收藏夹页：左侧收藏夹列表，右侧条目（DEVELOPMENT.md §4.4）。

- 新建/双击重命名/右键删除收藏夹
- 条目复用 HistoryDelegate 渲染（缩略图/两行布局），点击 → 详情弹层，
  右键：复制 / 从收藏夹移除 / Actions
"""
import logging

from PySide6.QtCore import QModelIndex, QRect, Qt, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services import collection_service

logger = logging.getLogger(__name__)

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # 与 HistoryView 保持一致


class CollectionsView(QWidget):
    item_activated = Signal(object)  # 单击条目 → 详情弹层

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._engine = None
        self._collections: list[dict] = []
        self._active_menus: list = []  # 防 GC（PySide 菜单包装器 Python 所有）
        self._build_ui()

    def set_context(self, engine, image_service=None) -> None:
        self._engine = engine
        if image_service is not None:
            self._delegate.set_image_service(image_service)
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._engine is not None:
            self.reload()

    # ---- 构建 ----

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(6)
        self._list = QListWidget()
        self._list.setObjectName("sideList")
        self._list.currentRowChanged.connect(self._on_select)
        self._list.itemDoubleClicked.connect(self._rename)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_menu)
        left.addWidget(self._list, 1)
        new_btn = QPushButton("新建收藏夹")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._create)
        left.addWidget(new_btn)
        layout.addLayout(left, 2)

        self._model = QStandardItemModel(self)
        self._items = QListView()
        self._items.setObjectName("historyList")
        self._items.setMouseTracking(True)
        self._items.setModel(self._model)
        from ui.history_view import HistoryDelegate

        self._delegate = HistoryDelegate(self._items)
        self._items.setItemDelegate(self._delegate)
        self._items.clicked.connect(self._on_item_clicked)
        layout.addWidget(self._items, 3)

    # ---- 数据 ----

    # 「★ 收藏」虚拟项：显示所有 favorite=1 的条目（收藏后在这里能看到）
    FAVORITES_ID = 0

    def reload(self) -> None:
        if self._engine is None:
            return
        current_id = self._current_id()
        self._collections = collection_service.list_collections(self._engine)
        from services import history_service

        fav_count = len(history_service.list_favorites(self._engine, limit=1000))
        self._list.blockSignals(True)
        self._list.clear()
        fav_item = QListWidgetItem(f"★ 收藏（{fav_count}）")
        fav_item.setData(Qt.ItemDataRole.UserRole, self.FAVORITES_ID)
        self._list.addItem(fav_item)
        for c in self._collections:
            item = QListWidgetItem(f"{c['name']}（{c['count']}）")
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._list.count():
            idx = 0
            if current_id:
                idx = next((i for i, c in enumerate(self._collections)
                            if c["id"] == current_id), 0) + 1
            self._list.setCurrentRow(idx)
        else:
            self._model.clear()

    def _current_id(self) -> int:
        row = self._list.currentRow()
        if row == 0:
            return self.FAVORITES_ID  # 「★ 收藏」虚拟项
        if 0 < row <= len(self._collections):
            return self._collections[row - 1]["id"]
        return -1

    def _on_select(self, row: int) -> None:
        self._model.clear()
        if self._engine is None or row < 0:
            return
        cid = self._current_id()
        if cid == self.FAVORITES_ID:
            from services import history_service

            items = history_service.list_favorites(self._engine)
        else:
            items = collection_service.list_items(self._engine, cid)
        for item in items:
            row_item = QStandardItem()
            row_item.setData(item, ROLE_ITEM)
            row_item.setEditable(False)
            self._model.appendRow(row_item)

    # ---- 收藏夹操作 ----

    def _create(self) -> None:
        if self._engine is None:
            return
        from ui.dialogs import NameDialog

        dialog = NameDialog("新建收藏夹", "名称：", placeholder="如：工作 / Prompt",
                            confirm_text="创建")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.text():
            collection_service.create_collection(self._engine, dialog.text())
            self.reload()

    def _rename(self, item: QListWidgetItem) -> None:
        cid = item.data(Qt.ItemDataRole.UserRole)
        coll = next((c for c in self._collections if c["id"] == cid), None)
        if coll is None or self._engine is None:
            return
        from ui.dialogs import NameDialog

        dialog = NameDialog("重命名收藏夹", "名称：", initial=coll["name"],
                            confirm_text="保存")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.text():
            collection_service.rename_collection(self._engine, cid, dialog.text())
            self.reload()

    def _on_list_menu(self, pos) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid == self.FAVORITES_ID:
            return  # 虚拟项不可重命名/删除
        menu = QMenu(self)
        self._active_menus.append(menu)
        menu.addAction("重命名").triggered.connect(lambda: self._rename(item))
        menu.addAction("删除").triggered.connect(lambda: self._delete(cid))
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _delete(self, cid: int) -> None:
        if self._engine is not None:
            collection_service.delete_collection(self._engine, cid)
            logger.info("收藏夹已删除: id=%s", cid)
            self.reload()

    # ---- 条目操作 ----

    def _on_item_clicked(self, index: QModelIndex) -> None:
        item = index.data(ROLE_ITEM)
        if item is not None:
            self.item_activated.emit(item)

    def contextMenuEvent(self, event) -> None:
        index = self._items.indexAt(event.pos())
        if not index.isValid():
            return
        item = index.data(ROLE_ITEM)
        cid = self._current_id()
        if item is None or cid < 0:
            return

        menu = QMenu(self)
        self._active_menus.append(menu)
        menu.addAction("复制").triggered.connect(
            lambda: self._copy(item))
        if cid != self.FAVORITES_ID:  # 「★ 收藏」虚拟项无移除操作
            menu.addAction("从收藏夹移除").triggered.connect(
                lambda: self._remove(cid, item))
        submenu = menu.addMenu("Actions")
        self._active_menus.append(submenu)
        self._fill_actions_submenu(submenu, item)
        menu.exec(event.globalPos())

    def _fill_actions_submenu(self, submenu: QMenu, item) -> None:
        from services.action_service import ActionService

        service = ActionService()
        available = service.actions_for(item)
        if available:
            for action in available:
                submenu.addAction(action.name).triggered.connect(
                    lambda _=False, a=action: service.run(a, item))
        else:
            submenu.addAction("无可用 Action").setEnabled(False)

    def _copy(self, item) -> None:
        from services.action_service import set_clipboard_item

        set_clipboard_item(item)

    def _remove(self, cid: int, item) -> None:
        if self._engine is not None:
            collection_service.remove_item(self._engine, cid, item.id)
            self.reload()
