"""收藏夹页：悬浮收藏夹面板 + 条目区（DEVELOPMENT.md §4.4）。

- 收藏夹列表不常驻：📁 触发图标在主窗口搜索行（仅本页显示），
  悬停 → 浮层面板出现（选择/新建/重命名/右键删除），鼠标离开自动收回；
  主界面只显示收藏内容，条目区占满全宽
- 条目复用 HistoryDelegate 渲染（缩略图/两行布局），点击 → 详情弹层，
  右键：复制 / 从收藏夹移除 / Actions
"""
import logging

from PySide6.QtCore import QEvent, QModelIndex, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
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

_PANEL_WIDTH = 180       # 浮层面板宽度
_PANEL_HIDE_MS = 250     # 鼠标离开浮层后的收回延时（进入浮层内控件可取消）


class CollectionsView(QWidget):
    item_activated = Signal(object)  # 单击条目 → 详情弹层

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._engine = None
        self._collections: list[dict] = []
        self._image_service = None     # 删除条目时清理图片文件
        self._active_menus: list = []  # 防 GC（PySide 菜单包装器 Python 所有）
        self._build_ui()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_PANEL_HIDE_MS)
        self._hide_timer.timeout.connect(self._panel.hide)

    def set_context(self, engine, image_service=None) -> None:
        self._engine = engine
        self._image_service = image_service
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
        layout.setSpacing(6)

        # 条目区占满（收藏夹列表在浮层中；📁 触发图标在主窗口搜索行）
        self._model = QStandardItemModel(self)
        self._items = QListView()
        self._items.setObjectName("historyList")
        self._items.setMouseTracking(True)
        self._items.setModel(self._model)
        from ui.history_view import HistoryDelegate

        self._delegate = HistoryDelegate(self._items)
        self._items.setItemDelegate(self._delegate)
        self._items.clicked.connect(self._on_item_clicked)
        layout.addWidget(self._items, 1)

        # 浮层面板：覆盖在条目区上方（收藏夹列表 + 新建按钮）
        self._panel = QFrame(self)
        self._panel.setObjectName("collectionPanel")
        self._panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._panel.setFixedWidth(_PANEL_WIDTH)
        self._panel.installEventFilter(self)
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(6)
        self._list = QListWidget()
        self._list.setObjectName("sideList")
        self._list.currentRowChanged.connect(self._on_select)
        self._list.itemDoubleClicked.connect(self._rename)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_list_menu)
        panel_layout.addWidget(self._list, 1)
        new_btn = QPushButton("新建收藏夹")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._create)
        panel_layout.addWidget(new_btn)
        self._panel.hide()

    # ---- 悬浮面板显隐（主窗口 📁 图标驱动）----

    def eventFilter(self, obj, event) -> bool:
        """面板自身 hover：进入取消收回，离开延时收回。"""
        if obj is self._panel:
            if event.type() == QEvent.Type.Enter:
                self._hide_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                self._hide_timer.start()
        return super().eventFilter(obj, event)

    def show_collection_panel(self) -> None:
        """展开收藏夹面板（主窗口 📁 图标悬停调用）。"""
        self._hide_timer.stop()
        self._panel.move(0, 0)
        self._panel.setFixedHeight(self.height())
        self._panel.raise_()
        self._panel.show()

    def schedule_hide_panel(self) -> None:
        """延时收回（📁 图标移出；移入面板由 eventFilter 取消）。"""
        self._hide_timer.start()

    def resizeEvent(self, event) -> None:
        """面板高度跟随视图（悬浮覆盖，不占布局）。"""
        super().resizeEvent(event)
        if self._panel.isVisible():
            self._panel.setFixedHeight(self.height())

    # ---- 数据 ----

    def reload(self) -> None:
        if self._engine is None:
            return
        collection_service.ensure_favorites(self._engine)  # 内置 ★ 收藏始终可见
        current_id = self._current_id()
        self._collections = collection_service.list_collections(self._engine)
        self._list.blockSignals(True)
        self._list.clear()
        for c in self._collections:
            item = QListWidgetItem(f"{c['name']}（{c['count']}）")
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._collections:
            idx = next((i for i, c in enumerate(self._collections)
                        if c["id"] == current_id), 0)
            self._list.setCurrentRow(idx)
        else:
            self._model.clear()

    def _current_id(self) -> int:
        row = self._list.currentRow()
        if 0 <= row < len(self._collections):
            return self._collections[row]["id"]
        return -1

    def _on_select(self, row: int) -> None:
        self._model.clear()
        if self._engine is None or row < 0:
            return
        for item in collection_service.list_items(self._engine,
                                                  self._current_id()):
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
        coll = next((c for c in self._collections if c["id"] == cid), None)
        if coll is None or coll["name"] == collection_service.FAVORITES_NAME:
            return  # 内置「★ 收藏」不可重命名/删除
        menu = QMenu(self)
        self._active_menus.append(menu)
        menu.addAction("重命名").triggered.connect(lambda: self._rename(item))
        menu.addAction("删除").triggered.connect(
            lambda: self._delete_collection(cid))
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
        # 坐标转换：event.pos() 是视图坐标，indexAt 需要 viewport 坐标
        # （顶部边距导致原点偏移，底部条目会映射失效）
        pos = self._items.viewport().mapFromGlobal(event.globalPos())
        index = self._items.indexAt(pos)
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
        # 收藏内容独立于历史：移除即删除收藏快照，不影响历史
        menu.addAction("从收藏夹移除").triggered.connect(
            lambda: self._remove(item))
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

    def _remove(self, item) -> None:
        """从收藏夹移除条目（删除收藏快照，不影响历史）。"""
        if self._engine is not None:
            collection_service.remove_item(self._engine, item.id)
            self.reload()

    def _delete_collection(self, cid: int) -> None:
        """删除收藏夹（收藏夹右键菜单）。"""
        if self._engine is not None:
            collection_service.delete_collection(self._engine, cid)
            logger.info("收藏夹已删除: id=%s", cid)
            self.reload()
