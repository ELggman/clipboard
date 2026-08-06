"""历史列表视图：QListView + 自定义 delegate（DEVELOPMENT.md §3.4/§3.5）。

布局（所有几何 = 基准 × scale，随窗口宽度等比例放大）：
- 文本/URL/文件条目：两行（时间·类型 / 内容预览，内容超出 elide）
- 图片条目：缩略图水平居中，文件名在缩略图**正下方**，
  放不下时自动换行（按可用宽度计算行数，行高自适应）；
  窗口放大后一行放得下 → 自然不换行
选中/hover 圆角由 delegate 自绘，配色取自调色板（自动适配深浅主题）。

TODO: 右键菜单（Copy / Pin / Favorite / Add To Collection / Action 子菜单）。
"""
import logging

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QContextMenuEvent,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QDialog,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # QStandardItem 里存 ClipboardItem

# 类型筛选：("", 全部) / 具体类型
TYPE_FILTERS = [("", "全部"), ("text", "文本"), ("url", "URL"),
                ("image", "图片"), ("file", "文件")]

# ---- 基准尺寸（scale=1，即窗口宽度 380px 初始/最小档）----
# 所有几何值 = 基准 × scale，随窗口宽度等比例放大（HistoryView.resizeEvent 驱动）
BASE_WIDTH = 380            # 基准宽度（与 main_window 初始/最小宽度一致）
BASE_FONT_PX = 14           # 主文字像素（13 → 14，初始档更大）
BASE_FONT_SMALL_PX = 12     # 次要文字像素（时间/类型/文件名）
ROW_HEIGHT_BASE = 44        # 文本条目行高（两行，收紧原 48 的底部空白）
THUMB_SIZE_BASE = 68        # 图片条目缩略图边长
_CAPTION_LINE_H = 18        # 文件名行高（换行按行数累加）
_TOP_PAD = 10               # 缩略图顶部间距
_TIME_GAP = 4               # 缩略图与时间·类型行间距
_TIME_LINE_H = 16           # 时间·类型行高
_NAME_GAP = 2               # 时间行与文件名间距
_BOTTOM_PAD = 8             # 底部间距
_MARGIN_X = 12              # 文本左/右留白
_RADIUS = 8                 # 选中/hover 圆角

# 导出（scale=1 时的行高，测试用）
ROW_HEIGHT = ROW_HEIGHT_BASE
# 图片条目 = 10 + 68 + 4 + 16 + 2 + 文件名行数×18 + 8；单行文件名 = 126
THUMB_ROW_HEIGHT = (_TOP_PAD + THUMB_SIZE_BASE + _TIME_GAP + _TIME_LINE_H
                    + _NAME_GAP + _CAPTION_LINE_H + _BOTTOM_PAD)


class HistoryDelegate(QStyledItemDelegate):
    """自绘历史行：圆角选中态、两行文本、缩略图 + 下方文件名（可换行）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider = None        # ImageService（缩略图来源，懒加载）
        self.show_image_filename = True  # 配置开关（DEVELOPMENT.md 设置项）
        self._scale = 1.0            # 响应式缩放（窗口宽度 / BASE_WIDTH）
        self._pixmap_cache: dict[str, QPixmap] = {}
        self._main_font_px = BASE_FONT_PX        # 基准字号（设置页可调）
        self._small_font_px = BASE_FONT_SMALL_PX

    def set_image_service(self, service) -> None:
        self._provider = service
        self._pixmap_cache.clear()

    def set_show_image_filename(self, show: bool) -> None:
        self.show_image_filename = show

    def set_font_sizes(self, main_px: int, small_px: int | None = None) -> None:
        """设置页字体大小：主文字 + 次要文字（默认主-2），随 scale 等比例放大。"""
        self._main_font_px = max(10, main_px)
        self._small_font_px = max(9, small_px if small_px is not None else main_px - 2)

    def set_scale(self, scale: float) -> None:
        """窗口放大时等比例放大所有几何（字号/缩略图/行高/间距）。"""
        self._scale = max(1.0, scale)

    # ---- 尺寸 ----

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        item = index.data(ROLE_ITEM)
        width = max(option.rect.width(), 200)
        if item is not None and item.type == "image" and self._provider is not None:
            caption = item.preview if self.show_image_filename else ""
            avail = width - 2 * self._s(_MARGIN_X)
            lines = self._caption_lines(caption, self._font(small=True), avail)
            height = (self._s(_TOP_PAD) + self._s(THUMB_SIZE_BASE)
                      + self._s(_TIME_GAP) + self._s(_TIME_LINE_H)
                      + self._s(_NAME_GAP) + lines * self._s(_CAPTION_LINE_H)
                      + self._s(_BOTTOM_PAD))
            return QSize(width, height)
        return QSize(width, self._s(ROW_HEIGHT_BASE))

    # ---- 绘制 ----

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        item = index.data(ROLE_ITEM)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRect(option.rect).adjusted(1, 1, -1, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        self._draw_background(painter, rect, option, selected, hovered)

        if item is not None and item.type == "image" and self._provider is not None:
            self._draw_image_row(painter, rect, option, item)
        else:
            self._draw_text_row(painter, rect, option, item)

        painter.restore()

    def _draw_background(self, painter, rect, option, selected, hovered) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, self._s(_RADIUS), self._s(_RADIUS))
        if selected:
            painter.fillPath(path, option.palette.highlight())
        elif hovered:
            painter.fillPath(path, option.palette.alternateBase())

    def _draw_text_row(self, painter, rect, option, item) -> None:
        # QPalette 颜色取值返回 QBrush，setPen 只收 QColor → 统一 .color()
        text_color = (option.palette.highlightedText().color() if
                      option.state & QStyle.StateFlag.State_Selected
                      else option.palette.text().color())
        secondary = option.palette.placeholderText().color()

        if item is None:
            return
        # 注意：drawText 的 y 是基线，字形会向上延伸 ascent 像素。
        # 基线 = top+15（12px 字 ascent≈10）→ 字形顶 ≈ top+5，完整落在
        # 高亮框（top+1）内——之前 top+7 时字形顶 ≈ top-3，超出高亮 3px
        # （ASCII 像素可视化实测：时间·类型顶部被高亮框截断）
        # 第一行：📌(置顶) 时间 · 类型 · 来源软件（小号次要色）
        painter.setPen(secondary)
        meta = self._meta_line(item)
        self._draw_line(painter, meta,
                        rect.left() + self._s(_MARGIN_X),
                        rect.top() + self._s(15), small=True,
                        avail=rect.width() - 2 * self._s(_MARGIN_X))
        # 第二行：内容预览（主色，超出 elide）
        painter.setPen(text_color)
        self._draw_line(painter, item.display_text(),
                        rect.left() + self._s(_MARGIN_X),
                        rect.top() + self._s(33), small=False,
                        avail=rect.width() - 2 * self._s(_MARGIN_X))

    def _draw_image_row(self, painter, rect, option, item) -> None:
        # 缩略图水平居中
        pix = self._thumbnail(item.file_path)
        size = self._s(THUMB_SIZE_BASE)
        x = rect.center().x() - size // 2
        y = rect.top() + self._s(_TOP_PAD)
        if pix is not None:
            painter.drawPixmap(x, y, size, size, pix)

        font = self._font(small=True)
        painter.setFont(font)
        avail = rect.width() - 2 * self._s(_MARGIN_X)
        center_x = rect.center().x() - avail // 2
        main_color = (option.palette.highlightedText().color() if
                      option.state & QStyle.StateFlag.State_Selected
                      else option.palette.text().color())
        secondary = option.palette.placeholderText().color()

        # 第一行：📌(置顶) ★(收藏) 时间 · image · 来源（次要色，居中）
        painter.setPen(secondary)
        marks = ("📌 " if item.pinned else "") + ("★ " if item.favorite else "")
        time_text = (f"{marks}"
                     f"{item.created_at} · image"
                     f"{' · ' + item.source_app if item.source_app else ''}"
                     if item.created_at else "image")
        painter.drawText(QRect(center_x, y + size + self._s(_TIME_GAP),
                               avail, self._s(_TIME_LINE_H)),
                         Qt.AlignmentFlag.AlignHCenter, time_text)

        # 第二行+：文件名（主色，居中；放不下按字符换行）
        caption = item.preview if self.show_image_filename else ""
        if caption:
            painter.setPen(main_color)
            lines = self._caption_lines(caption, font, avail)
            caption_rect = QRect(center_x,
                                 y + size + self._s(_TIME_GAP) + self._s(_TIME_LINE_H)
                                 + self._s(_NAME_GAP),
                                 avail, lines * self._s(_CAPTION_LINE_H))
            painter.drawText(caption_rect,
                             Qt.AlignmentFlag.AlignHCenter
                             | Qt.TextFlag.TextWrapAnywhere,
                             caption)

    # ---- 工具 ----

    def _s(self, value: int) -> int:
        """基准值 × scale 取整（最小 1）。"""
        return max(1, round(value * self._scale))

    def _font(self, small: bool = False) -> QFont:
        font = QFont()
        font.setPixelSize(self._s(self._small_font_px if small else self._main_font_px))
        return font

    def _draw_line(self, painter, text: str, x: int, baseline_y: int,
                   small: bool, avail: int) -> None:
        font = self._font(small=small)
        painter.setFont(font)
        elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, avail)
        painter.drawText(x, baseline_y, elided)

    @staticmethod
    def _meta_line(item) -> str:
        """元信息行：📌(置顶) ★(收藏) 时间 · 类型 · 来源软件。"""
        base = f"{item.created_at} · {item.type}" if item.created_at else item.type
        if item.source_app:
            base += f" · {item.source_app}"
        marks = ("📌 " if item.pinned else "") + ("★ " if item.favorite else "")
        return f"{marks}{base}"

    @staticmethod
    def _caption_lines(text: str, font: QFont, avail_width: int) -> int:
        """按可用宽度计算文件名换行行数（字符级贪心，无空格文件名同样支持）。"""
        fm = QFontMetrics(font)
        if fm.horizontalAdvance(text) <= avail_width:
            return 1
        lines = 1
        width = 0
        for ch in text:
            w = fm.horizontalAdvance(ch)
            if width + w > avail_width and width > 0:
                lines += 1
                width = 0
            width += w
        return lines

    def _thumbnail(self, file_path: str) -> QPixmap | None:
        if file_path in self._pixmap_cache:
            return self._pixmap_cache[file_path]
        qimg = self._provider.thumbnail(file_path)
        if qimg is None:
            return None
        pix = QPixmap.fromImage(qimg)
        self._pixmap_cache[file_path] = pix
        return pix


class HistoryView(QWidget):
    item_activated = Signal(object)  # 单击条目（详情弹层）
    feedback = Signal(str)           # 状态栏提示（置顶/收藏等菜单操作反馈）

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._list = QListView()
        self._list.setObjectName("historyList")
        self._list.setMouseTracking(True)  # hover 态需要
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setWordWrap(False)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)

        self._model = QStandardItemModel(self._list)
        self._list.setModel(self._model)
        self._delegate = HistoryDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        self._list.clicked.connect(self._on_item_clicked)  # 单击展开详情

        # 顶部类型筛选条（全部 / 文本 / URL / 图片 / 文件）
        self._type_tabs = QListWidget()
        self._type_tabs.setObjectName("topnav")
        self._type_tabs.setFlow(QListView.Flow.LeftToRight)
        self._type_tabs.setFixedHeight(30)
        self._type_tabs.setSpacing(2)
        self._type_tabs.setFrameShape(QListWidget.Shape.NoFrame)
        self._type_tabs.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._type_tabs.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        for _type, label in TYPE_FILTERS:
            self._type_tabs.addItem(QListWidgetItem(label))
        self._type_tabs.currentRowChanged.connect(self._on_type_filter)
        self._filter_type = ""  # 当前类型筛选
        self._all_items: list = []  # set_items 传入的完整数据（筛选前）

        # 右键菜单依赖（bootstrap 注入）
        self._engine = None              # 置顶/收藏写库
        self._actions = None             # ActionService（Actions 子菜单）
        self._refresh_cb = None          # 菜单操作后重载列表
        self._active_menus: list = []    # 持有菜单引用防 GC（PySide 包装器 Python 所有）

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._type_tabs)
        layout.addWidget(self._list)

    def resizeEvent(self, event) -> None:
        """窗口放大 → 内容等比例放大（基准宽度 BASE_WIDTH）。"""
        super().resizeEvent(event)
        self._delegate.set_scale(event.size().width() / BASE_WIDTH)
        self._list.doItemsLayout()  # 行高随 scale 变化，重新布局

    # ---- 注入 ----

    def set_image_service(self, service) -> None:
        """注入图片服务：image 条目懒加载缩略图（内存 LRU 缓存）。"""
        self._delegate.set_image_service(service)

    def set_show_image_filename(self, show: bool) -> None:
        """配置：图片条目是否显示文件名（False 时显示「时间 · image」）。"""
        self._delegate.set_show_image_filename(show)

    def set_font_size(self, main_px: int) -> None:
        """设置页字体大小：更新 delegate 基准字号并重排。"""
        self._delegate.set_font_sizes(main_px)
        self._list.doItemsLayout()
        self._list.viewport().update()

    def set_menu_context(self, engine, action_service, refresh_cb) -> None:
        """注入右键菜单依赖：数据库引擎（置顶/收藏）、ActionService、刷新回调。"""
        self._engine = engine
        self._actions = action_service
        self._refresh_cb = refresh_cb

    # ---- 点击 ----

    def _on_item_clicked(self, index: QModelIndex) -> None:
        item = index.data(ROLE_ITEM)
        if item is not None:
            self.item_activated.emit(item)

    # ---- 右键菜单 ----

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        # 坐标转换：event.pos() 是本视图坐标，indexAt 需要 viewport 坐标
        # （顶部类型筛选条导致原点偏移，直接用 event.pos() 时最底部
        #   条目映射到列表外 → indexAt 无效 → 菜单不弹出，实测踩坑）
        pos = self._list.viewport().mapFromGlobal(event.globalPos())
        index = self._list.indexAt(pos)
        if not index.isValid():
            return
        item = index.data(ROLE_ITEM)
        if item is None:
            return
        self._build_menu(item).exec(event.globalPos())

    def _build_menu(self, item) -> QMenu:
        """构建右键菜单（复制 / 置顶 / 收藏 / Actions 子菜单）。

        动作直接 connect triggered，可编程触发（测试友好），exec 仅用于展示。
        self._active_menu 持有引用：防止菜单对象被 Python GC 提前回收
        （QMenu 无 Python 引用时 C++ 对象被删除，子菜单访问报
        'Internal C++ object already deleted'）。
        """
        menu = QMenu(self)
        self._active_menus.append(menu)
        menu.addAction("复制").triggered.connect(
            lambda: self._run_copy(item))
        pin_label = "取消置顶" if item.pinned else "置顶"
        menu.addAction(pin_label).triggered.connect(
            lambda: self._toggle_flag(item, "pinned"))

        # 收藏：单一入口（快速收藏 ★ / 具体收藏夹 / 新建收藏夹）
        fav_menu = menu.addMenu("收藏")
        self._active_menus.append(fav_menu)
        quick_label = "★ 取消收藏" if item.favorite else "★ 快速收藏"
        fav_menu.addAction(quick_label).triggered.connect(
            lambda: self._toggle_flag(item, "favorite"))
        if self._engine is not None:
            fav_menu.addSeparator()
            from services import collection_service

            collections = collection_service.list_collections(self._engine)
            if collections:
                for coll in collections:
                    fav_menu.addAction(coll["name"]).triggered.connect(
                        lambda _=False, c=coll: self._add_to_collection(c, item))
            else:
                fav_menu.addAction("暂无收藏夹").setEnabled(False)
            fav_menu.addAction("新建收藏夹…").triggered.connect(
                lambda: self._create_collection_and_add(item))

        if self._actions is not None:
            submenu = menu.addMenu("Actions")
            self._active_menus.append(submenu)  # 子菜单包装器 Python 所有，须持有
            available = self._actions.actions_for(item)
            if available:
                for action in available:
                    submenu.addAction(action.name).triggered.connect(
                        lambda _=False, a=action: self._run_action(a, item))
            else:
                submenu.addAction("无可用 Action").setEnabled(False)

        menu.addSeparator()
        menu.addAction("删除").triggered.connect(
            lambda: self._delete_item(item))
        return menu

    def _run_copy(self, item) -> None:
        from services.action_service import set_clipboard_item

        if set_clipboard_item(item):
            logger.info("右键复制: %s", item.type)
        else:
            logger.warning("右键复制失败: %s", item.type)

    def _toggle_flag(self, item, flag: str) -> None:
        if not self._engine or not item.id:
            logger.warning("条目未落库，无法%s: id=%s", flag, item.id)
            return
        from services import history_service

        if flag == "pinned":
            history_service.set_pinned(self._engine, item.id, not item.pinned)
            item.pinned = 1 - item.pinned  # 同步内存对象（菜单重建/绘制 📌 依赖）
            label = "已置顶" if item.pinned else "已取消置顶"
        else:
            # 快速收藏 = 加入内置「★ 收藏」收藏夹（内容快照，删历史不影响）
            from services import collection_service

            fav_id = collection_service.ensure_favorites(self._engine)
            if not item.favorite:
                collection_service.add_item(self._engine, fav_id, item)
                item.favorite = 1
                label = "已收藏"
            else:
                history_service.set_favorite(self._engine, item.id, 0)
                item.favorite = 0
                label = "已取消收藏"
        logger.info("已切换%s: id=%s", flag, item.id)
        if self._refresh_cb:
            self._refresh_cb()  # 先刷新（会重置状态栏），再给反馈
        self.feedback.emit(label)  # 状态栏即时反馈（收藏后可见可感）

    def _run_action(self, action, item) -> None:
        if self._actions.run(action, item):
            logger.info("Action 执行完成: %s", action.id)
        # 结果已写回剪贴板，watcher 会捕获为一条新历史（去重防重复）

    def _add_to_collection(self, coll: dict, item) -> None:
        from services import collection_service

        if item.id and collection_service.add_item(self._engine, coll["id"], item):
            logger.info("已加入收藏夹「%s」: item=%s", coll["name"], item.id)
            self.feedback.emit(f"已收藏到「{coll['name']}」")

    def _delete_item(self, item) -> None:
        """删除单条历史（图片文件同步清理，状态栏反馈）。"""
        if not self._engine or not item.id:
            logger.warning("条目未落库，无法删除: id=%s", item.id)
            return
        from services import history_service

        files = history_service.delete_item(self._engine, item.id)
        provider = self._delegate._provider  # ImageService：清理图片文件
        for path in files:
            if provider is not None:
                provider.delete(path)
        self.feedback.emit("已删除")
        if self._refresh_cb:
            self._refresh_cb()

    def _create_collection_and_add(self, item) -> None:
        """新建收藏夹并立即把当前条目加入。"""
        from services import collection_service
        from ui.dialogs import NameDialog

        dialog = NameDialog("新建收藏夹", "名称：", confirm_text="创建")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.text():
            cid = collection_service.create_collection(self._engine, dialog.text())
            collection_service.add_item(self._engine, cid, item)
            logger.info("新建收藏夹并加入: %s (item=%s)", dialog.text(), item.id)
            self.feedback.emit(f"已收藏到「{dialog.text()}」")

    # ---- 数据 ----

    def set_items(self, items: list) -> None:
        """整体替换列表（启动恢复 / 搜索结果），items 最新在前。"""
        self._all_items = list(items)
        self._apply_type_filter()

    def add_item(self, clipboard_item) -> None:
        """追加一条实时捕获（最新在上；符合当前类型筛选才显示）。"""
        self._all_items.insert(0, clipboard_item)
        if not self._filter_type or clipboard_item.type == self._filter_type:
            self._model.insertRow(0, self._make_row(clipboard_item))

    # ---- 类型筛选 ----

    def _on_type_filter(self, row: int) -> None:
        if 0 <= row < len(TYPE_FILTERS):
            self._filter_type = TYPE_FILTERS[row][0]
            self._apply_type_filter()

    def _apply_type_filter(self) -> None:
        self._model.clear()
        for item in self._all_items:
            if not self._filter_type or item.type == self._filter_type:
                self._model.appendRow(self._make_row(item))

    def mark_duplicate(self, clipboard_item) -> None:
        """重复内容：不新增，仅刷新状态栏（列表不动）。"""
        logger.debug("去重: %s", clipboard_item.hash[:12])

    @staticmethod
    def _make_row(item) -> QStandardItem:
        row = QStandardItem()
        row.setData(item, ROLE_ITEM)
        row.setEditable(False)
        return row

    def set_query(self, query: str) -> None:
        """顶部搜索栏联动。TODO: 接入 SearchService（DEVELOPMENT.md §3.4）。"""
        logger.debug("搜索查询（待接入）: %s", query)
