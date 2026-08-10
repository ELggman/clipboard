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

from PySide6.QtCore import QEvent, QModelIndex, QRect, QSize, Qt, Signal
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
    QAbstractScrollArea,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

ROLE_ITEM = Qt.ItemDataRole.UserRole + 1  # QStandardItem 里存 ClipboardItem
ROLE_HEADER = Qt.ItemDataRole.UserRole + 2  # 时间线月份标题（无条目数据）

# 类型筛选：("", 全部) / 具体类型（code = 代码模式，新增.md §8）
TYPE_FILTERS = [("", "全部"), ("text", "文本"), ("url", "URL"),
                ("image", "图片"), ("file", "文件"), ("code", "代码")]

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
# 代码条目（§8.6）：meta 行 + 预览行数（最多 6 行）+ "+N more lines" 行
_CODE_LINE_H = 18           # 代码预览行高
_CODE_PREVIEW_MAX = 6       # 列表最多显示的代码行数
# 首行代码基线 = 33（与文本行内容基线一致）——之前 26 时字形顶 ≈ meta 基线
# 附近，内容紧贴时间·类型行（实测踩坑：看起来很靠上）
_CODE_TOP_GAP = 33
_HEADER_H = 26               # 时间线月份标题行高

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
        self._view_session_id: int | None = None  # 当前视图会话（None=全局搜索）

    def set_image_service(self, service) -> None:
        self._provider = service
        self._pixmap_cache.clear()

    def set_show_image_filename(self, show: bool) -> None:
        self.show_image_filename = show

    def set_font_sizes(self, main_px: int, small_px: int | None = None) -> None:
        """设置页字体大小：主文字 + 次要文字（默认主-2），随 scale 等比例放大。"""
        self._main_font_px = max(10, main_px)
        self._small_font_px = max(9, small_px if small_px is not None else main_px - 2)

    def set_view_session_id(self, session_id: int | None) -> None:
        """设置当前视图会话：None=全局搜索（所有条目显示 [会话名] 标签）；
        指定会话 → 非本会话条目才显示标签（本会话视图内不冗余标注）。"""
        self._view_session_id = session_id

    def _session_tag(self, item) -> str:
        """会话来源标签（全局搜索/跨会话视图用）。"""
        if item.session_name and (
                self._view_session_id is None
                or item.session_id != self._view_session_id):
            return f"[{item.session_name}] "
        return ""

    def set_scale(self, scale: float) -> None:
        """窗口放大时等比例放大所有几何（字号/缩略图/行高/间距）。"""
        self._scale = max(1.0, scale)

    # ---- 尺寸 ----

    def sizeHint(self, option, index: QModelIndex) -> QSize:
        if index.data(ROLE_HEADER) is not None:
            return QSize(max(option.rect.width(), 200), self._s(_HEADER_H))
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
        if item is not None and item.type == "code":
            # 敏感代码条目按敏感行渲染（遮蔽单行），高度一致
            if item.sensitive:
                return QSize(width, self._s(ROW_HEIGHT_BASE))
            shown, has_more, _ = self._code_preview(item)
            height = (self._s(_CODE_TOP_GAP)
                      + len(shown) * self._s(_CODE_LINE_H)
                      + (self._s(_CODE_LINE_H) if has_more else 0)
                      + self._s(_BOTTOM_PAD))
            return QSize(width, height)
        return QSize(width, self._s(ROW_HEIGHT_BASE))

    # ---- 绘制 ----

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        header = index.data(ROLE_HEADER)
        if header is not None:
            # 月份标题：加粗次要色，无卡片底色
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRect(option.rect).adjusted(1, 1, -1, -1)
            self._draw_header(painter, rect, option, header)
            painter.restore()
            return

        item = index.data(ROLE_ITEM)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        rect = QRect(option.rect).adjusted(1, 1, -1, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        self._draw_background(painter, rect, option, selected, hovered)

        if item is None:
            painter.restore()
            return
        # 敏感优先：即使代码条目也按遮蔽单行渲染（新增.md §10 联动 mock）
        if item.sensitive:
            self._draw_sensitive_row(painter, rect, option, item)
        elif item.type == "image" and self._provider is not None:
            self._draw_image_row(painter, rect, option, item)
        elif item.type == "code":
            self._draw_code_row(painter, rect, option, item)
        else:
            self._draw_text_row(painter, rect, option, item)

        painter.restore()

    def _draw_header(self, painter, rect, option, label: str) -> None:
        """时间线月份标题：加粗次要色文字，不画卡片底色。"""
        painter.setPen(option.palette.placeholderText().color())
        font = self._font(small=True)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rect.left() + self._s(_MARGIN_X),
                         rect.top() + self._s(_HEADER_H - 8), label)

    def _draw_background(self, painter, rect, option, selected, hovered) -> None:
        path = QPainterPath()
        path.addRoundedRect(rect, self._s(_RADIUS), self._s(_RADIUS))
        if selected:
            painter.fillPath(path, option.palette.highlight())
        elif hovered:
            painter.fillPath(path, option.palette.midlight())
        else:
            # 常态浅色卡片底色：白底上与间隔配合，条目区分度更高
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
        # 第一行：[会话名] 📌(置顶) 时间 · 类型 · 来源软件（小号次要色）
        painter.setPen(secondary)
        meta = self._session_tag(item) + self._meta_line(item)
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

    def _font(self, small: bool = False, mono: bool = False) -> QFont:
        if mono:
            from ui.code_highlighter import mono_font

            return mono_font(self._s(self._small_font_px if small
                                     else self._main_font_px))
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

    # ---- 代码行（§8.6）----

    def _code_preview(self, item, max_lines: int = _CODE_PREVIEW_MAX):
        """代码预览：前 N 行 + 是否截断 + 总行数。"""
        lines = (item.content or "").splitlines()
        total = item.line_count or len(lines)
        shown = lines[:max_lines]
        has_more = total > len(shown)
        return shown, has_more, total

    @staticmethod
    def _code_meta(item) -> str:
        """代码条目 meta：📌(置顶) ★(收藏) 🐍 Python · 时间 · N 行 · 来源。"""
        from services.code_detector import LANGUAGE_EMOJI, LANGUAGE_NAMES

        lang = item.language or "code"
        name = LANGUAGE_NAMES.get(lang, lang)
        marks = ("📌 " if item.pinned else "") + ("★ " if item.favorite else "")
        meta = (f"{marks}{LANGUAGE_EMOJI.get(lang, '🧾')} {name}"
                f"{' · ' + item.created_at if item.created_at else ''}"
                f" · {item.line_count or len((item.content or '').splitlines())} 行"
                f"{' · ' + item.source_app if item.source_app else ''}")
        return meta

    def _draw_code_row(self, painter, rect, option, item) -> None:
        text_color = (option.palette.highlightedText().color() if
                      option.state & QStyle.StateFlag.State_Selected
                      else option.palette.text().color())
        secondary = option.palette.placeholderText().color()

        # meta：[会话名] 📌 ★ 🐍 Python · 08-06 18:00 · 8 行 · 来源
        painter.setPen(secondary)
        self._draw_line(painter, self._session_tag(item) + self._code_meta(item),
                        rect.left() + self._s(_MARGIN_X), rect.top() + self._s(15),
                        small=True, avail=rect.width() - 2 * self._s(_MARGIN_X))

        # 代码预览（mono，前 6 行，超出显示 "+N more lines"）
        shown, has_more, total = self._code_preview(item)
        font = self._font(small=True, mono=True)
        painter.setFont(font)
        y = rect.top() + self._s(_CODE_TOP_GAP)
        for line in shown:
            elided = QFontMetrics(font).elidedText(
                line, Qt.TextElideMode.ElideRight,
                rect.width() - 2 * self._s(_MARGIN_X))
            painter.setPen(text_color)
            painter.drawText(rect.left() + self._s(_MARGIN_X), y, elided)
            y += self._s(_CODE_LINE_H)
        if has_more:
            painter.setPen(secondary)
            painter.drawText(rect.left() + self._s(_MARGIN_X), y,
                             f"+ {total - len(shown)} more lines")

    # ---- 敏感行（§9.18/§9.19）----

    def _draw_sensitive_row(self, painter, rect, option, item) -> None:
        """🔐 遮蔽预览：meta 前缀锁标，内容行显示 mask 后的文本。"""
        text_color = (option.palette.highlightedText().color() if
                      option.state & QStyle.StateFlag.State_Selected
                      else option.palette.text().color())
        secondary = option.palette.placeholderText().color()

        base = (f"{item.created_at} · {item.type}"
                if item.created_at else item.type)
        if item.source_app:
            base += f" · {item.source_app}"
        marks = ("📌 " if item.pinned else "") + ("★ " if item.favorite else "")
        painter.setPen(secondary)
        self._draw_line(painter, f"🔐 {self._session_tag(item)}{marks}{base}",
                        rect.left() + self._s(_MARGIN_X), rect.top() + self._s(15),
                        small=True, avail=rect.width() - 2 * self._s(_MARGIN_X))

        from services.sensitive_detector import mask

        painter.setPen(text_color)
        self._draw_line(painter, mask(item.content or item.preview,
                                      item.sensitive_type),
                        rect.left() + self._s(_MARGIN_X), rect.top() + self._s(33),
                        small=False, avail=rect.width() - 2 * self._s(_MARGIN_X))

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
        # 条目间隔：白底下列表更易区分（随窗口缩放，见 resizeEvent）
        self._list.setSpacing(4)
        # ⌘Delete 删除 / 回车复制 / ←→ 切换类型：键盘事件经 eventFilter 处理；
        # 触控板双指横滑是 viewport 上的 Wheel 事件，需对 viewport 也安装过滤器
        self._list.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._list.installEventFilter(self)
        self._list.viewport().installEventFilter(self)
        # 触控板手势状态机：以 ScrollEnd 为手势边界（一次滑动可能多个 Begin）
        self._gesture_ended = True     # 上次手势已结束（允许下一次 Begin 切换）
        self._gesture_switched = False  # 当前手势是否已切换类型

        self._model = QStandardItemModel(self._list)
        self._list.setModel(self._model)
        self._delegate = HistoryDelegate(self._list)
        self._list.setItemDelegate(self._delegate)
        self._list.clicked.connect(self._on_item_clicked)  # 单击展开详情

        # 顶部类型筛选条（全部 / 文本 / URL / 图片 / 文件）
        # 状态先于控件初始化：setCurrentRow(0) 会同步触发 _on_type_filter
        # → _apply_type_filter，需 _filter_type/_all_items 已存在（实测崩）
        self._filter_type = ""  # 当前类型筛选
        self._all_items: list = []  # set_items 传入的完整数据（筛选前）
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
        for _, label in TYPE_FILTERS:
            self._type_tabs.addItem(QListWidgetItem(label))
        self._type_tabs.currentRowChanged.connect(self._on_type_filter)
        # 默认选中「全部」：否则 currentRow=-1 无选中态，←/→ 切换
        # 第一次会落在 0（全部）而非直觉的相邻项（实测）
        self._type_tabs.setCurrentRow(0)

        # 右键菜单依赖（bootstrap 注入）
        self._engine = None              # 置顶/收藏写库
        self._actions = None             # ActionService（Actions 子菜单）
        self._refresh_cb = None          # 菜单操作后重载列表
        self._active_menus: list = []    # 持有菜单引用防 GC（PySide 包装器 Python 所有）

        # 会话（v4）：下拉切换 + 管理菜单；bootstrap 注入
        self._session_service = None
        self._on_active_changed = None   # 切换会话 → 持久化激活（bootstrap 闭包）
        self._delete_policy = "move"     # 删除会话策略（move/delete，设置页可配）
        self._view_session_id: int | None = 1  # 当前视图会话（None=全局搜索）

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 会话行：下拉（显示名 · 条数）+ ⋯ 管理菜单
        # 独立区域：底部留 8px 与类型筛选条分隔（靠太近视觉粘连，实测）
        session_row = QHBoxLayout()
        session_row.setContentsMargins(8, 0, 8, 6)
        session_row.setSpacing(4)
        self._session_combo = QComboBox()
        self._session_combo.setObjectName("sessionCombo")
        # 弹出列表宽度由内容自适应：会话名可能较长（「论文写作优化 · 123 条」），
        # 默认跟随按钮会裁切，固定 min-width 又过宽（实测）
        self._session_combo.view().setSizeAdjustPolicy(
            QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self._session_combo.currentIndexChanged.connect(self._on_session_changed)
        session_row.addWidget(self._session_combo, 1)
        self._session_menu_btn = QPushButton("⋯")
        self._session_menu_btn.setObjectName("sessionMenuBtn")
        self._session_menu_btn.setFixedWidth(28)
        self._session_menu_btn.clicked.connect(self._show_session_menu)
        session_row.addWidget(self._session_menu_btn)
        layout.addLayout(session_row)

        layout.addWidget(self._type_tabs)
        layout.addWidget(self._list)

    def resizeEvent(self, event) -> None:
        """窗口放大 → 内容等比例放大（基准宽度 BASE_WIDTH）。"""
        super().resizeEvent(event)
        scale = event.size().width() / BASE_WIDTH
        self._delegate.set_scale(scale)
        self._list.setSpacing(max(2, round(4 * scale)))  # 条目间隔随缩放
        self._list.doItemsLayout()  # 行高随 scale 变化，重新布局

    def eventFilter(self, obj, event) -> bool:
        """键盘/手势快捷键（列表获得焦点时生效）：

        - ⌘Delete 删除选中条目（§9.20）
        - Enter/Return 直接复制选中条目
        - ←/→ 切换类型筛选（全部/文本/URL/图片/文件/代码，循环）
        - 触控板双指左右滑：Wheel 事件 x 分量主导时同方向切换类型
        """
        if obj is self._list and event.type() == QEvent.Type.KeyPress:
            # ⌘⌫（macOS 主删除键）或 ⌦ 前向删除 → 删除选中条目（§9.20）；
            # 普通 ⌫ 不删，防误触
            if event.key() == Qt.Key.Key_Delete or (
                    event.key() == Qt.Key.Key_Backspace
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                index = self._list.currentIndex()
                if index.isValid():
                    item = index.data(ROLE_ITEM)
                    if item is not None:
                        self._delete_item(item)
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                # 上下键选中后回车 = 复制（与 Quick Paste 的 Enter 语义一致）
                index = self._list.currentIndex()
                if index.isValid():
                    item = index.data(ROLE_ITEM)
                    if item is not None:
                        self._run_copy(item)
                        self.feedback.emit("已复制到剪贴板")
                return True
            # ←/→ 切换类型筛选（上下键保持列表内选择，左右键无默认行为）
            if event.key() == Qt.Key.Key_Left:
                self._step_type_filter(-1)
                return True
            if event.key() == Qt.Key.Key_Right:
                self._step_type_filter(1)
                return True
        # 触控板双指横滑：事件目标是 viewport（QAbstractScrollArea 滚轮语义）
        if obj is self._list.viewport() and event.type() == QEvent.Type.Wheel:
            return self._on_swipe_wheel(event)
        return super().eventFilter(obj, event)

    # ---- 类型切换手势 ----

    def _step_type_filter(self, delta: int) -> None:
        """←/→ 键：类型筛选循环切换（全部 ↔ 代码）。"""
        total = self._type_tabs.count()
        if total == 0:
            return
        row = self._type_tabs.currentRow()
        if row < 0:
            row = 0  # 防御：理论上默认已选中「全部」
        # setCurrentRow 触发 currentRowChanged → _on_type_filter 刷新列表
        self._type_tabs.setCurrentRow((row + delta) % total)

    def _on_swipe_wheel(self, event) -> bool:
        """触控板双指横滑 → 切换类型筛选；纵向滚动放行。

        macOS 事件流（2026-08-08 探针实测 458 事件）：
        一次物理滑动 = **手指段** `Begin→Update×N→End`
        + **动量段** `Begin→Momentum×N→End`（动量开始也被系统标成
        ScrollBegin，段间 End→Begin 间隔 <65ms——无法用时间区分）。
        可靠判定 = **Begin 后第一个非 Begin 事件**：
        - `Update` → 手指段（用户滑动）→ 切 1 格
        - `Momentum` → 动量段 → 不切（锁死）
        连续 Begin（实测 `Begin(-16)→Begin(0)→Update(-34)`）吞；
        Begin dx=0 由首个非零 Update 补切。无阶段信息（鼠标滚轮等）放行。
        """
        pd = event.pixelDelta()
        dx = pd.x() if not pd.isNull() else 0
        if dx == 0:
            dx = event.angleDelta().x()
        dy = pd.y() if not pd.isNull() else 0
        if dy == 0:
            dy = event.angleDelta().y()
        phase = event.phase()
        if phase == Qt.ScrollPhase.NoScrollPhase:
            return False  # 鼠标滚轮等：放行
        if phase == Qt.ScrollPhase.ScrollBegin:
            if not self._gesture_ended:
                return True  # 连续 Begin（同一次滑动）：吞
            if abs(dx) <= abs(dy) and (dx != 0 or dy != 0):
                return False  # 纵向主导：放行，不改变手势状态
            # 横向手势开始（含 dx=dy=0）：等待首个 Update（手指段）或
            # Momentum（动量段）判定
            self._gesture_ended = False
            self._gesture_switched = False
            return True
        if phase == Qt.ScrollPhase.ScrollUpdate:
            if not self._gesture_switched:
                if abs(dx) <= abs(dy):
                    return False  # 纵向主导：放行
                if dx != 0:
                    # 手指段：双指向左滑（dx<0）→ 下一类型；向右滑 → 上一类型
                    self._gesture_switched = True
                    self._step_type_filter(-(1 if dx > 0 else -1))
            return True
        if phase == Qt.ScrollPhase.ScrollMomentum:
            if abs(dx) <= abs(dy):
                # 纵向动量：放行——惯性滚动必须交给列表（曾无条件吞掉，
                # 手指一停列表就停，下滑变成「一格一格」）
                return False
            if not self._gesture_switched:
                self._gesture_switched = True  # 横向动量段：不切，锁死本次滑动
            return True
        if phase == Qt.ScrollPhase.ScrollEnd:
            self._gesture_ended = True  # 手势边界：允许下一次 Begin 判定
            return False  # 放行（End 无 delta，对滚动无害）
        return True

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

    # ---- 会话（v4）----

    def set_session_context(self, engine, session_service,
                            on_active_changed=None) -> None:
        """注入会话服务 + 激活切换回调（bootstrap 装配）。"""
        self._engine = engine
        self._session_service = session_service
        self._on_active_changed = on_active_changed

    def set_delete_policy(self, policy: str) -> None:
        """删除会话策略：move=内容移回普通（合并去重）/ delete=直接删除。"""
        self._delete_policy = policy

    def reload_sessions(self, active_id: int) -> None:
        """填充会话下拉（显示名 · 条数），并激活 active_id 刷新视图。"""
        if self._session_service is None or self._engine is None:
            return
        sessions = self._session_service.list_sessions(self._engine)
        self._session_combo.blockSignals(True)
        self._session_combo.clear()
        for s in sessions:
            self._session_combo.addItem(f"{s['name']} · {s['count']} 条", s["id"])
        idx = self._session_combo.findData(active_id)
        self._session_combo.setCurrentIndex(max(0, idx))
        self._session_combo.blockSignals(False)
        self.load_session(active_id)

    def load_session(self, session_id: int) -> None:
        """切换到指定会话视图（delegate 标签状态 + 从数据库加载）。"""
        self._view_session_id = session_id
        self._delegate.set_view_session_id(session_id)
        if self._engine is not None:
            from services import history_service

            self.set_items(history_service.list_recent(
                self._engine,
                limit=getattr(self, "_history_limit", 500),
                session_id=session_id))

    def set_global_view(self) -> None:
        """全局搜索视图：显示所有会话条目并标注 [会话名] 标签。"""
        self._view_session_id = None
        self._delegate.set_view_session_id(None)

    def refresh_session_counts(self) -> None:
        """实时刷新会话下拉计数（保留当前选中，不重载列表）。

        新建会话后复制内容：计数若不刷新，下拉一直显示 0 条直到重启
        （实测踩坑）。bootstrap 在保存成功后调用。
        """
        if self._session_service is None or self._engine is None:
            return
        current_id = self._session_combo.currentData()
        sessions = self._session_service.list_sessions(self._engine)
        self._session_combo.blockSignals(True)
        self._session_combo.clear()
        for s in sessions:
            self._session_combo.addItem(f"{s['name']} · {s['count']} 条", s["id"])
        idx = self._session_combo.findData(current_id)
        self._session_combo.setCurrentIndex(max(0, idx))
        self._session_combo.blockSignals(False)

    def set_view_session_id(self, session_id: int | None) -> None:
        """设置视图会话（不影响数据，只控制 [会话名] 标签显示）。"""
        self._view_session_id = session_id
        self._delegate.set_view_session_id(session_id)

    def _on_session_changed(self, row: int) -> None:
        sid = self._session_combo.itemData(row)
        if sid is None or sid == self._view_session_id:
            return
        self.load_session(sid)
        if self._on_active_changed is not None:
            self._on_active_changed(sid)  # bootstrap：持久化 + 主窗口同步
        self.feedback.emit("已切换到会话")

    def _show_session_menu(self) -> None:
        """会话管理菜单：新建 / 重命名当前 / 删除当前。"""
        menu = QMenu(self)
        self._active_menus.append(menu)
        menu.addAction("新建会话…").triggered.connect(self._create_session)
        current = self._session_combo.currentData()
        if current is not None and current != 1:
            menu.addAction("重命名当前会话…").triggered.connect(
                lambda: self._rename_session(current))
            menu.addAction("删除当前会话").triggered.connect(
                lambda: self._delete_session(current))
        else:
            menu.addAction("重命名/删除仅对非默认会话可用").setEnabled(False)
        menu.exec(self._session_menu_btn.mapToGlobal(
            self._session_menu_btn.rect().bottomLeft()))

    def _create_session(self) -> None:
        if self._session_service is None:
            return
        from ui.dialogs import NameDialog

        dialog = NameDialog("新建会话", "名称：", placeholder="如：论文写作优化",
                            confirm_text="创建")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.text():
            sid = self._session_service.create_session(self._engine, dialog.text())
            if sid:
                self.reload_sessions(sid)  # 新建后自动激活
                if self._on_active_changed is not None:
                    self._on_active_changed(sid)
                self.feedback.emit(f"已切换到「{dialog.text()}」")

    def _rename_session(self, session_id: int) -> None:
        if self._session_service is None:
            return
        from ui.dialogs import NameDialog

        dialog = NameDialog("重命名会话", "名称：", confirm_text="保存")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.text():
            self._session_service.rename_session(self._engine, session_id,
                                                 dialog.text())
            self.reload_sessions(self._view_session_id or 1)

    def _delete_session(self, session_id: int) -> None:
        if self._session_service is None:
            return
        from services import history_service
        from ui.dialogs import ConfirmDialog

        if self._delete_policy == "delete":
            message = ("删除会话后，其中的内容将**一并删除**（图片文件同步"
                       "清理，仍被其他会话/收藏引用的保留）。确定删除？")
            ok_label = "删除会话及其内容"
        else:
            message = ("删除会话后，其中的内容将全部移回「普通」会话"
                       "（与普通已有相同内容自动合并去重，不丢数据）。确定删除？")
            ok_label = "删除"
        dialog = ConfirmDialog("删除会话", message, confirm_text=ok_label)
        if dialog.exec() == ConfirmDialog.DialogCode.Accepted:
            ok, files = self._session_service.delete_session(
                self._engine, session_id, self._delete_policy)
            if ok:
                if self._delete_policy == "delete" and files:
                    provider = self._delegate._provider
                    for path in files:
                        if (provider is not None
                                and not history_service.is_path_still_referenced(
                                    self._engine, path)):
                            provider.delete(path)
                self.reload_sessions(1)  # 回到普通会话
                if self._on_active_changed is not None:
                    self._on_active_changed(1)
                self.feedback.emit(
                    "会话已删除" + ("，内容已移回「普通」"
                                  if self._delete_policy == "move" else ""))

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
        menu.addAction("添加到模板…").triggered.connect(
            lambda: self._add_to_template(item))  # §22-24：Clipboard → Snippet
        pin_label = "取消置顶" if item.pinned else "置顶"
        menu.addAction(pin_label).triggered.connect(
            lambda: self._toggle_flag(item, "pinned"))
        # 手动标记/取消敏感（§9.17）：自动检测之外的兜底
        sens_label = "取消敏感标记" if item.sensitive else "标记为敏感"
        menu.addAction(sens_label).triggered.connect(
            lambda: self._toggle_sensitive(item))

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

    def _toggle_sensitive(self, item) -> None:
        """手动标记/取消敏感：写库 + 内存同步（列表遮蔽立即生效）。"""
        if not self._engine or not item.id:
            logger.warning("条目未落库，无法标记敏感: id=%s", item.id)
            return
        from services import history_service
        from services.sensitive_detector import MANUAL

        new_val = 0 if item.sensitive else 1
        history_service.set_sensitive(self._engine, item.id, bool(new_val))
        item.sensitive = new_val
        item.sensitive_type = MANUAL if new_val else ""
        label = "已标记为敏感" if new_val else "已取消敏感标记"
        logger.info("已切换敏感标记: id=%s -> %s", item.id, new_val)
        if self._refresh_cb:
            self._refresh_cb()  # 先刷新（会重置状态栏），再给反馈
        self.feedback.emit(label)

    def _run_action(self, action, item) -> None:
        if self._actions.run(action, item):
            logger.info("Action 执行完成: %s", action.id)
        # 结果已写回剪贴板，watcher 会捕获为一条新历史（去重防重复）

    def _add_to_collection(self, coll: dict, item) -> None:
        from services import collection_service

        if item.id and collection_service.add_item(self._engine, coll["id"], item):
            logger.info("已加入收藏夹「%s」: item=%s", coll["name"], item.id)
            self.feedback.emit(f"已收藏到「{coll['name']}」")

    def _add_to_template(self, item) -> None:
        """历史内容 → 模板（§22-24）：内容预填，名称/Shortcut 用户确认。

        第一阶段不自动推导名称/shortcut（§23 建议功能第二阶段），
        用户填写后创建，shortcut 冲突由 service 校验提示。
        """
        if self._engine is None:
            return
        from ui.templates_view import TemplateCreateDialog

        dlg = TemplateCreateDialog(self, initial_content=item.content or "")
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        from services.template_service import TemplateService

        svc = TemplateService(self._engine)
        try:
            svc.create_template(dlg.name(), dlg.shortcut(), dlg.content(),
                                description=dlg.description())
        except (ValueError, Exception) as e:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "模板", str(e))
            return
        logger.info("历史内容已添加到模板: shortcut=%s", dlg.shortcut())
        self.feedback.emit("已添加到模板")

    def _delete_item(self, item) -> None:
        """删除单条历史（图片文件同步清理，状态栏反馈）。"""
        if not self._engine or not item.id:
            logger.warning("条目未落库，无法删除: id=%s", item.id)
            return
        from services import history_service

        files = history_service.delete_item(self._engine, item.id)
        provider = self._delegate._provider  # ImageService：清理图片文件
        if provider is not None:
            for path in files:
                # 仍被引用（其他会话行/收藏快照）的图片保留
                if not history_service.is_path_still_referenced(self._engine,
                                                                path):
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
        """追加一条实时捕获（置顶优先：插到置顶组之后，最新在上）。

        与 list_recent 的 pinned DESC 排序一致——新条目（未置顶）不得
        把置顶条目挤下去（实测踩坑：复制新文本后置顶跑到列表底部）。
        只插入**属于当前视图会话**的条目：视图是具体会话时，其他会话的
        新条目不得混入（否则显示在错误会话，切走再切回才正常，实测）。
        """
        if (self._view_session_id is not None
                and clipboard_item.session_id
                and clipboard_item.session_id != self._view_session_id):
            return  # 属于其他会话：切换到该会话自然可见
        pos = sum(1 for it in self._all_items if it.pinned)  # 置顶组大小
        self._all_items.insert(pos, clipboard_item)
        if not self._filter_type or clipboard_item.type == self._filter_type:
            # 模型行号 = 新条目之前**可见**（符合筛选）的条目数
            visible_before = sum(
                1 for it in self._all_items[:pos]
                if not self._filter_type or it.type == self._filter_type)
            self._model.insertRow(visible_before, self._make_row(clipboard_item))

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
