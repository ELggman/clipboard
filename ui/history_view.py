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

# ---- 基准尺寸（scale=1，即窗口宽度 380px 初始/最小档）----
# 所有几何值 = 基准 × scale，随窗口宽度等比例放大（HistoryView.resizeEvent 驱动）
BASE_WIDTH = 380            # 基准宽度（与 main_window 初始/最小宽度一致）
BASE_FONT_PX = 14           # 主文字像素（13 → 14，初始档更大）
BASE_FONT_SMALL_PX = 12     # 次要文字像素（时间/类型/文件名）
ROW_HEIGHT_BASE = 48        # 文本条目行高（两行）
THUMB_SIZE_BASE = 68        # 图片条目缩略图边长
_CAPTION_LINE_H = 18        # 文件名行高（换行按行数累加）
_TOP_PAD = 10               # 缩略图顶部间距
_CAPTION_GAP = 6            # 缩略图与文件名间距
_BOTTOM_PAD = 8             # 底部间距
_MARGIN_X = 12              # 文本左/右留白
_RADIUS = 8                 # 选中/hover 圆角

# 导出（scale=1 时的行高，测试用）
ROW_HEIGHT = ROW_HEIGHT_BASE
THUMB_ROW_HEIGHT = _TOP_PAD + THUMB_SIZE_BASE + _CAPTION_GAP + _CAPTION_LINE_H + _BOTTOM_PAD  # 110（单行文件名）


class HistoryDelegate(QStyledItemDelegate):
    """自绘历史行：圆角选中态、两行文本、缩略图 + 下方文件名（可换行）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider = None        # ImageService（缩略图来源，懒加载）
        self.show_image_filename = True  # 配置开关（DEVELOPMENT.md 设置项）
        self._scale = 1.0            # 响应式缩放（窗口宽度 / BASE_WIDTH）
        self._pixmap_cache: dict[str, QPixmap] = {}

    def set_image_service(self, service) -> None:
        self._provider = service
        self._pixmap_cache.clear()

    def set_show_image_filename(self, show: bool) -> None:
        self.show_image_filename = show

    def set_scale(self, scale: float) -> None:
        """窗口放大时等比例放大所有几何（字号/缩略图/行高/间距）。"""
        self._scale = max(1.0, scale)

    # ---- 尺寸 ----

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        item = index.data(ROLE_ITEM)
        width = max(option.rect.width(), 200)
        if item is not None and item.type == "image" and self._provider is not None:
            caption = item.preview if self.show_image_filename else (
                f"{item.created_at} · image" if item.created_at else "image")
            avail = width - 2 * self._s(_MARGIN_X)
            lines = self._caption_lines(caption, self._font(small=True), avail)
            height = (self._s(_TOP_PAD) + self._s(THUMB_SIZE_BASE)
                      + self._s(_CAPTION_GAP) + lines * self._s(_CAPTION_LINE_H)
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
        # 第一行：时间 · 类型（小号次要色）
        painter.setPen(secondary)
        self._draw_line(painter,
                        f"{item.created_at} · {item.type}" if item.created_at else item.type,
                        rect.left() + self._s(_MARGIN_X),
                        rect.top() + self._s(7), small=True,
                        avail=rect.width() - 2 * self._s(_MARGIN_X))
        # 第二行：内容预览（主色，超出 elide）
        painter.setPen(text_color)
        self._draw_line(painter, item.display_text(),
                        rect.left() + self._s(_MARGIN_X),
                        rect.top() + self._s(25), small=False,
                        avail=rect.width() - 2 * self._s(_MARGIN_X))

    def _draw_image_row(self, painter, rect, option, item) -> None:
        # 缩略图水平居中
        pix = self._thumbnail(item.file_path)
        size = self._s(THUMB_SIZE_BASE)
        x = rect.center().x() - size // 2
        y = rect.top() + self._s(_TOP_PAD)
        if pix is not None:
            painter.drawPixmap(x, y, size, size, pix)

        # 缩略图下方：文件名（开）或 时间·类型（关），水平居中，放不下换行
        caption = item.preview if self.show_image_filename else (
            f"{item.created_at} · image" if item.created_at else "image")
        color = (option.palette.highlightedText().color() if
                 option.state & QStyle.StateFlag.State_Selected
                 else option.palette.placeholderText().color())
        painter.setPen(color)
        font = self._font(small=True)
        painter.setFont(font)
        avail = rect.width() - 2 * self._s(_MARGIN_X)
        caption_rect = QRect(rect.center().x() - avail // 2,
                             y + size + self._s(_CAPTION_GAP),
                             avail, self._caption_lines(caption, font, avail)
                             * self._s(_CAPTION_LINE_H))
        painter.drawText(caption_rect,
                         Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap,
                         caption)

    # ---- 工具 ----

    def _s(self, value: int) -> int:
        """基准值 × scale 取整（最小 1）。"""
        return max(1, round(value * self._scale))

    def _font(self, small: bool = False) -> QFont:
        font = QFont()
        font.setPixelSize(self._s(BASE_FONT_SMALL_PX if small else BASE_FONT_PX))
        return font

    def _draw_line(self, painter, text: str, x: int, baseline_y: int,
                   small: bool, avail: int) -> None:
        font = self._font(small=small)
        painter.setFont(font)
        elided = QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, avail)
        painter.drawText(x, baseline_y, elided)

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
