"""收藏夹页：悬浮收藏夹面板 + 条目区（DEVELOPMENT.md §4.4）。

- 收藏夹列表不常驻：📁 触发图标在主窗口搜索行（仅本页显示），
  悬停 → 浮层面板出现（选择/新建/重命名/右键删除），鼠标离开自动收回；
  主界面只显示收藏内容，条目区占满全宽
- 条目复用 HistoryDelegate 渲染（缩略图/两行布局），点击 → 详情弹层，
  右键：复制 / 从收藏夹移除 / Actions
"""
import logging

from PySide6.QtCore import QEvent, QModelIndex, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QPainter, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget)

class _IconLabel(QLabel):
    """自绘图标标签：QPainter 绘制 emoji 文字，背景/圆角/hover 交给 QSS。

    QPushButton 的 emoji 文本在 macOS 渲染空白（Qt 6.9 实测，页面内也
    一样）——自绘与列表 delegate 同一 QPainter 路径，渲染可靠（delegate
    的 📌 ★ 等 emoji 在行内正常显示）。继承 QLabel 让
    `QLabel#collectionTrigger` QSS（背景/圆角/hover）照常生效，
    paintEvent 先画 QSS 背景（super 调用，本类不设 QLabel 文本），
    再用 QPainter 画 emoji 文字。
    """

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        # 固定尺寸（QLabel 空文本自动宽度会算成 0+padding，实测）
        self.setFixedSize(66, 28)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)  # QSS 背景/圆角/hover 状态
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()


def _sf_symbol_icon(name: str, size: int = 18):
    """SF Symbol 系统图标 → QIcon。

    QPushButton 的 emoji 文本在 macOS 渲染异常（实测空白）——
    改用系统矢量图标（Apple 官方方案）。
    """
    from AppKit import NSImage
    from PySide6.QtGui import QIcon, QPixmap

    try:
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(
            name, None)
        if img is None:
            return QIcon()
        img.setSize_((size, size))
        tiff = img.TIFFRepresentation()
        pix = QPixmap()
        pix.loadFromData(bytes(tiff))
        return QIcon(pix)
    except Exception:
        return QIcon()


from app import events
from services import collection_service
from ui.animations import enable_smooth_wheel
from ui.scroll_fx import enable_scroll_fx

logger = logging.getLogger(__name__)

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # 与 HistoryView 保持一致

_PANEL_WIDTH = 180       # 浮层面板宽度
# 面板里收藏夹名字的可用宽度：面板 180 − 左右边距 10×2 − 列表内边距/纵向条余量
_PANEL_TEXT_W = _PANEL_WIDTH - 2 * 10 - 16
_PANEL_HIDE_MS = 250     # 鼠标离开浮层后的收回延时（进入浮层内控件可取消）


class CollectionsView(QWidget):
    item_activated = Signal(object)  # 单击条目 → 详情弹层

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._engine = None
        self._loaded_rev = -1  # 上次装载的数据修订号（showEvent 判脏用，见 app/events.py）
        self._collections: list[dict] = []
        self._all_items: list = []  # 当前收藏夹全部条目（搜索过滤前）
        self._image_service = None     # 删除条目时清理图片文件
        self._active_menus: list = []  # 防 GC（PySide 菜单包装器 Python 所有）
        self._build_ui()
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_PANEL_HIDE_MS)
        self._hide_timer.timeout.connect(self._panel.hide)
        self._menu_open = False  # 右键菜单模态期间屏蔽面板收回（实测收回 bug）

    def set_context(self, engine, image_service=None) -> None:
        self._engine = engine
        self._image_service = image_service
        if image_service is not None:
            self._delegate.set_image_service(image_service)
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # 只在数据真的变过时重查：原先每次显示都无条件 reload()（实测 4.3ms），
        # 快速在几个视图之间来回切换时纯属白做。见 app/events.py。
        if self._engine is not None and self._loaded_rev != events.revision():
            self.reload()

    # ---- 构建 ----

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 0)
        layout.setSpacing(6)

        # 当前收藏夹标题：面板收回后仍常驻显示（知道在看哪个收藏夹）
        self._title = QLabel("")
        self._title.setObjectName("collectionTitle")
        layout.addWidget(self._title)

        # 搜索行：📁 触发 + 搜索框（📁 emoji 用自绘 _IconLabel——QPushButton
        # 的 emoji 文本在 macOS 渲染空白，Qt 6.9 实测；自绘与列表 delegate
        # 同一 QPainter 路径可靠；背景/圆角由 QLabel#collectionTrigger QSS 提供）
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self._collections_trigger = _IconLabel("📁 收藏")
        self._collections_trigger.setObjectName("collectionTrigger")
        self._collections_trigger.setToolTip("收藏夹（悬停展开）")
        self._collections_trigger.installEventFilter(self)
        search_row.addWidget(self._collections_trigger)
        self._search = QLineEdit()
        self._search.setObjectName("searchBox")
        self._search.setFixedHeight(28)
        self._search.setPlaceholderText("搜索收藏内容…")
        self._search.setClearButtonEnabled(True)
        # ⚠️ 必须先把 text 存进 _search_text 再过滤——_apply_filter 读的是
        # _search_text，直接连 _apply_filter 时它永远为空（实测搜索无效）
        self._search.textChanged.connect(self._on_search_text)
        search_row.addWidget(self._search, 1)
        layout.addLayout(search_row)
        self._search_text = ""

        # 条目区占满（收藏夹列表在浮层中；📁 触发图标在主窗口搜索行）
        self._model = QStandardItemModel(self)
        self._items = QListView()
        self._items.setObjectName("historyList")
        self._items.setMouseTracking(True)
        # 逐像素滚动（与历史页一致，见 history_view）：默认整行模式会把
        # 触控板像素 delta 量化成整行，滑动一格一格
        self._items.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._items.setModel(self._model)
        from ui.history_view import HistoryDelegate

        self._delegate = HistoryDelegate(self._items)
        self._items.setItemDelegate(self._delegate)
        # 横向滚动条一律关掉（与历史页一致）：这些列表只有纵向语义，
        # 一旦哪档 delegate 报出比视口宽的尺寸就会凭空冒出一条横条
        self._items.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_smooth_wheel(self._items)  # 鼠标滚轮缓动（触控板不介入）
        enable_scroll_fx(self._items, self._delegate)  # 滚动装饰
        self._items.clicked.connect(self._on_item_clicked)
        layout.addWidget(self._items, 1)
        # 空态提示：覆盖在列表 viewport 上（搜索无匹配 / 收藏夹为空）
        self._empty_hint = QLabel("", self._items.viewport())
        self._empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_hint.setStyleSheet(
            "color: #9A9AA0; font-size: 13px; background: transparent;")
        self._empty_hint.hide()

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
        # ⚠️ 必须关掉横向条：收藏夹名字长一点就会把这一列撑宽，凭空冒出一条
        # 横向滚动条（用户实测报的「收藏夹页面出现左右滑动的滚轮」）。列表只有
        # 纵向语义，名字改成按面板宽度做省略号（见 `_load_collections`），
        # 全名挂在 tooltip 上。
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_smooth_wheel(self._list)  # 收藏夹多时面板内滚动同样缓动
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
        """📁 触发：悬停展开面板；面板自身 hover 取消收回。

        ⚠️ 只消费 Enter/Leave——其余事件（尤其 Paint）必须透传返回 False，
        否则触发图标永远不重绘（实测：paintEvent 被吞，图标纯白 N 轮）。
        """
        if obj is self._collections_trigger:
            if event.type() == QEvent.Type.Enter:
                self.show_collection_panel(
                    self._collections_trigger.mapToGlobal(QPoint(0, 0)))
                return True
            if event.type() == QEvent.Type.Leave:
                self.schedule_hide_panel()
                return True
            return False
        if obj is self._panel:
            if event.type() == QEvent.Type.Enter:
                self._hide_timer.stop()
            elif event.type() == QEvent.Type.Leave:
                # 右键菜单模态打开时鼠标被菜单 grab → 面板收到 Leave，
                # 若此时启动收回，菜单还没关面板就没了（实测 bug）
                if not self._menu_open:
                    self._hide_timer.start()
        return super().eventFilter(obj, event)


    def show_collection_panel(self, anchor_global=None) -> None:
        """展开收藏夹面板（主窗口 📁 图标悬停调用）。

        anchor_global = 📁 图标左上角全局坐标 → 面板出现在**图标附近**
        （右缘贴图标左侧、顶部对齐图标），而非页面左上角——从图标
        悬停后鼠标直接向左下方移动操作，符合操作习惯（实测反馈）。
        """
        self._hide_timer.stop()
        # 面板高度随内容自适应（行数×行高 + 按钮/边距/余量），上限 320 后滚动
        content_h = self._list.count() * 28 + 64
        panel_h = max(60, min(320, content_h))
        if anchor_global is not None:
            local = self.mapFromGlobal(anchor_global)
            x = local.x() - self._panel.width() + 4   # 面板右缘贴图标左侧
            y = max(0, local.y())                     # 顶部对齐图标
            self._panel.move(max(0, x), y)
        else:
            self._panel.move(0, 0)
        self._panel.setFixedHeight(panel_h)
        self._panel.raise_()
        self._panel.show()

    def schedule_hide_panel(self) -> None:
        """延时收回（📁 图标移出；移入面板由 eventFilter 取消）。"""
        self._hide_timer.start()

    def resizeEvent(self, event) -> None:
        """窗口缩放时仅跟随视图尺寸（面板高度已按内容自适应）。"""
        super().resizeEvent(event)
        if self._empty_hint.isVisible():
            self._empty_hint.setGeometry(self._items.viewport().rect())

    # ---- 数据 ----

    def reload(self) -> None:
        if self._engine is None:
            return
        collection_service.ensure_favorites(self._engine)  # 内置 ★ 收藏始终可见
        current_id = self._current_id()
        self._collections = collection_service.list_collections(self._engine)
        # 「全部」虚拟项（id=0）置顶：并集展示所有收藏夹条目
        all_count = len(collection_service.list_all_items(self._engine))
        self._collections = [
            {"id": 0, "name": "全部", "count": all_count},
            *self._collections,
        ]
        self._list.blockSignals(True)
        self._list.clear()
        fm = self._list.fontMetrics()
        for c in self._collections:
            label = f"{c['name']}（{c['count']}）"
            # 按面板宽度截断：横条已关掉，不截就会直接被切掉半个字
            item = QListWidgetItem(
                fm.elidedText(label, Qt.TextElideMode.ElideRight,
                              _PANEL_TEXT_W))
            item.setToolTip(label)      # 省略号截掉的部分看 tooltip
            item.setData(Qt.ItemDataRole.UserRole, c["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._collections:
            idx = next((i for i, c in enumerate(self._collections)
                        if c["id"] == current_id), 0)
            self._list.setCurrentRow(idx)
        else:
            self._model.clear()
            self._update_empty_hint("")
        self._update_title()
        self._loaded_rev = events.revision()  # 在装载**之后**记（ensure_favorites 可能刚提交）

    def _current_id(self) -> int:
        row = self._list.currentRow()
        if 0 <= row < len(self._collections):
            return self._collections[row]["id"]
        return -1

    def _update_title(self) -> None:
        """常驻标题：当前收藏夹名 · 条数（面板收回后仍可见）。"""
        row = self._list.currentRow()
        if 0 <= row < len(self._collections):
            c = self._collections[row]
            self._title.setText(f"{c['name']} · {c['count']} 条")
        else:
            self._title.setText("")

    def _on_select(self, row: int) -> None:
        self._all_items = []
        if self._engine is not None and row >= 0:
            cid = self._current_id()
            if cid == 0:
                # 「全部」虚拟项：并集展示所有收藏夹条目（按原条目去重）
                self._all_items = collection_service.list_all_items(
                    self._engine)
            else:
                self._all_items = collection_service.list_items(
                    self._engine, cid)
        self._apply_filter()
        self._update_title()
        self._prefetch_images()

    def _prefetch_images(self) -> None:
        """后台预热当前收藏夹里图片条目的缩略图（老条目首次解码别落在绘制路径上）。"""
        if self._image_service is None:
            return
        paths = [it.file_path for it in self._all_items
                 if it.type == "image" and it.file_path]
        if paths:
            self._image_service.prefetch(paths)

    def _on_search_text(self, text: str) -> None:
        """输入框 textChanged：存文本 → 过滤（直接连 _apply_filter 无效）。"""
        self._search_text = text
        self._apply_filter()

    def apply_search_filter(self, text: str) -> None:
        """主窗口转发：按文本过滤当前收藏夹条目。"""
        self._search_text = text
        self._apply_filter()

    def _apply_filter(self) -> None:
        """搜索过滤当前收藏夹条目（内容/预览匹配，清空恢复）。"""
        self._model.clear()
        query = self._search_text.strip().lower()
        for item in self._all_items:
            if query and query not in (item.content or "").lower() \
                    and query not in (item.preview or "").lower():
                continue
            row_item = QStandardItem()
            row_item.setData(item, ROLE_ITEM)
            row_item.setEditable(False)
            self._model.appendRow(row_item)
        self._update_empty_hint(query)

    def _update_empty_hint(self, query: str) -> None:
        """空态提示：无条目（收藏夹为空）/ 搜索无匹配。"""
        if self._model.rowCount() > 0:
            self._empty_hint.hide()
            return
        if query:
            self._empty_hint.setText(f"未找到匹配「{self._search_text.strip()}」的内容")
        elif not self._all_items:
            self._empty_hint.setText("收藏夹暂无内容")
        else:
            self._empty_hint.hide()
            return
        self._empty_hint.setGeometry(self._items.viewport().rect())
        self._empty_hint.show()

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
        if coll is None or cid == 0 \
                or coll["name"] == collection_service.FAVORITES_NAME:
            return  # 「全部」虚拟项/内置「★ 收藏」不可重命名/删除
        menu = QMenu(self)
        self._active_menus.append(menu)
        menu.addAction("重命名").triggered.connect(lambda: self._rename(item))
        menu.addAction("删除").triggered.connect(
            lambda: self._delete_collection(cid))
        self._hide_timer.stop()
        self._menu_open = True  # 菜单模态期间：面板 Leave 不启动收回
        try:
            menu.exec(self._list.viewport().mapToGlobal(pos))
        finally:
            self._menu_open = False
        # 菜单关闭后：鼠标仍在面板上 → 保持展开；移出 → 正常延时收回
        if self._panel.isVisible() and not self._panel.geometry().contains(
                self.mapFromGlobal(QCursor.pos())):
            self.schedule_hide_panel()

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
