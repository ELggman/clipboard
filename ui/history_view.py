"""历史列表视图：QListView + 自定义 delegate（DEVELOPMENT.md §3.4 性能/§3.5 缩略图）。

布局：
- 文本/URL/文件条目：两行（时间·类型 / 内容预览，超出 elide）
- 图片条目：64px 缩略图水平居中，文件名显示在缩略图**下方**
  （show_image_filename=False 时改为显示「时间 · image」）
选中/hover 圆角由 delegate 自绘，配色取自调色板（自动适配深浅主题）。

TODO: 右键菜单（Copy / Pin / Favorite / Add To Collection / Action 子菜单）。
"""
import logging

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPixmap,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QListView,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # QStandardItem 里存 ClipboardItem

THUMB_SIZE = 64             # 图片条目缩略图边长
ROW_HEIGHT = 44             # 文本条目行高（两行）
THUMB_ROW_HEIGHT = 108      # 图片条目行高（缩略图 10+64+6+16+10 + 文件名行）
_MARGIN_X = 12              # 文本左/右留白
_RADIUS = 8                 # 选中/hover 圆角


class HistoryDelegate(QStyledItemDelegate):
    """自绘历史行：圆角选中态、两行文本、图片缩略图 + 下方文件名。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider = None        # ImageService（缩略图来源，懒加载）
        self.show_image_filename = True  # 配置开关（DEVELOPMENT.md 设置项）
        self._pixmap_cache: dict[str, QPixmap] = {}

    def set_image_service(self, service) -> None:
        self._provider = service
        self._pixmap_cache.clear()

    def set_show_image_filename(self, show: bool) -> None:
        self.show_image_filename = show

    # ---- 尺寸 ----

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        item = index.data(ROLE_ITEM)
        width = max(option.rect.width(), 200)
        if item is not None and item.type == "image" and self._provider is not None:
            return QSize(width, THUMB_ROW_HEIGHT)
        return QSize(width, ROW_HEIGHT)

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
        path.addRoundedRect(rect, _RADIUS, _RADIUS)
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
        # 第一行：时间 · 类型（小号次要色）
        painter.setPen(secondary)
        self._paint_line(painter, f"{item.created_at} · {item.type}" if item.created_at else item.type,
                         rect, y_top=rect.top() + 7, point_delta=-1)
        # 第二行：内容预览（主色，elide）
        painter.setPen(text_color)
        self._paint_line(painter, item.display_text(),
                         rect, y_top=rect.top() + 24, point_delta=0)

    def _draw_image_row(self, painter, rect, option, item) -> None:
        # 缩略图水平居中
        pix = self._thumbnail(item.file_path)
        x = rect.center().x() - THUMB_SIZE // 2
        y = rect.top() + 10
        if pix is not None:
            painter.drawPixmap(x, y, THUMB_SIZE, THUMB_SIZE, pix)

        # 缩略图下方：文件名（开）或 时间·类型（关），水平居中于图片
        caption = item.preview if self.show_image_filename else (
            f"{item.created_at} · image" if item.created_at else "image")
        color = (option.palette.highlightedText().color() if
                 option.state & QStyle.StateFlag.State_Selected
                 else option.palette.placeholderText().color())
        painter.setPen(color)
        font = QFont(painter.font())
        font.setPointSizeF(max(9.0, font.pointSizeF() - 1))
        painter.setFont(font)
        adv = QFontMetrics(font).horizontalAdvance(caption)
        caption_x = max(rect.left() + _MARGIN_X,
                        rect.center().x() - adv // 2)
        painter.drawText(caption_x, y + THUMB_SIZE + 18, caption)

    def _paint_line(self, painter, text: str, rect: QRect, y_top: int, point_delta: int) -> None:
        font = QFont(painter.font())
        if point_delta:
            font.setPointSizeF(max(9.0, font.pointSizeF() + point_delta))
        metrics = QFontMetrics(font)
        elided = metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                    rect.width() - _MARGIN_X * 2)
        painter.setFont(font)
        painter.drawText(rect.left() + _MARGIN_X, y_top, elided)

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
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._list = QListView()
        self._list.setObjectName("historyList")
        self._list.setMouseTracking(True)  # hover 态需要
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setWordWrap(False)

        self._model = QStandardItemModel(self._list)
        self._list.setModel(self._model)
        self._delegate = HistoryDelegate(self._list)
        self._list.setItemDelegate(self._delegate)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._list)

    # ---- 注入 ----

    def set_image_service(self, service) -> None:
        """注入图片服务：image 条目懒加载缩略图（内存 LRU 缓存）。"""
        self._delegate.set_image_service(service)

    def set_show_image_filename(self, show: bool) -> None:
        """配置：图片条目是否显示文件名（False 时显示「时间 · image」）。"""
        self._delegate.set_show_image_filename(show)

    # ---- 数据 ----

    def set_items(self, items: list) -> None:
        """整体替换列表（启动恢复 / 搜索结果），items 最新在前。"""
        self._model.clear()
        for item in items:
            self._model.appendRow(self._make_row(item))

    def add_item(self, clipboard_item) -> None:
        """追加一条实时捕获（最新在上）。"""
        self._model.insertRow(0, self._make_row(clipboard_item))

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
