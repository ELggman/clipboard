"""模板页组件（组件化设计：模板变量系统 / 代码高亮扩展的挂载点）。

- TemplateCardDelegate：模板列表行——两行：名称+★（行尾 ★ 点击区=收藏
  切换）/ shortcut 钥匙片 + 触发方式；禁用降透明度；选中蓝柔和高亮
- FolderSourceDelegate：分类列 Finder source-list 行——名称左 + 计数
  右对齐（参考图风格）；选中蓝柔和高亮
- VariableTagBar：变量胶囊条（点击 → variable_clicked 信号 → 编辑器插入）
- TemplateHighlighter：CodeHighlighter 子类——Pygments 高亮 +
  {{变量}} 跨度 accent 色覆盖（Pygments 对 {{}} 误分词时兜底）
- STAR_ZONE：模板行 ★ 点击区宽度（视图层鼠标映射用）

⚠️ 绘制一律走 QPainter 文本字形（emoji/QPushButton 图标在 macOS Qt 6.9
渲染空白，本会话血泪史）；颜色取 option.palette（主题自适应）。
"""
import logging
import re

from PySide6.QtCore import QRect, QSize, Qt, QPoint, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QStyledItemDelegate,
    QStyle,
    QWidget,
)

from ui.code_highlighter import CodeHighlighter

logger = logging.getLogger(__name__)

# 模板行数据角色（QListWidget item 文本保留给测试/兼容，绘制读数据）
ROLE_TEMPLATE = Qt.ItemDataRole.UserRole + 1      # 完整模板 dict
ROLE_FOLDER_NAME = Qt.ItemDataRole.UserRole + 1   # 分类名
ROLE_FOLDER_COUNT = Qt.ItemDataRole.UserRole + 2  # 分类计数

# 模板行 ★ 点击区宽度（视图层把行尾点击映射为收藏切换）
STAR_ZONE = 32
# ★ 与左侧名称右端的间距（px，可手动调整——改这里即可控制星号与内容间隙）
_STAR_GAP = 0
# 行左右内缩（卡片式内嵌边距）。⚠️ 星标点击区必须用同一内缩值：
# Qt 绘制时的 option.rect 比 visualItemRect 右侧窄 8px（裁剪到可见区），
# 点击区若按 visualItemRect 原值算会把星标命中区右偏 8px → 点不到星标。
ROW_INSET = 8

_TEMPLATE_ROW_H = 58      # 模板行高（两行信息）
_FOLDER_ROW_H = 30        # 分类行高（source list）
_RADIUS = 8               # 行圆角

# 星标金（macOS 星标色，深浅主题通用）
_STAR_GOLD = QColor("#FFD60A")
_STAR_DIM = QColor("#B0B0B6")


def _rounded_path(rect: QRect, radius: int) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


# 行绘制字体缓存：QFont 构造（含 "Menlo" 字体匹配）在 macOS 上昂贵，
# 逐行逐 paint 新建会拖慢滚轮渲染。三件套按基准字体（toString）缓存。
_row_font_cache: dict[str, tuple] = {}


def _row_fonts(base: QFont):
    """模板行三件套字体 (名称14px中粗, shortcut Menlo12px, 触发12px)。"""
    key = base.toString()
    got = _row_font_cache.get(key)
    if got is not None:
        return got
    name = QFont(base)
    name.setPixelSize(14)
    name.setWeight(QFont.Weight.DemiBold)
    chip = QFont("Menlo")
    chip.setPixelSize(12)
    trig = QFont(base)
    trig.setPixelSize(12)
    _row_font_cache[key] = (name, chip, trig)
    return _row_font_cache[key]


class TemplateCardDelegate(QStyledItemDelegate):
    """模板列表行：两行卡片式（名称+★ / shortcut 钥匙片+触发方式）。

    view: TemplatesView 引用——绘制时读其 `_pan`（长条目横向平移偏移）。
    不能靠 self.parent()（那是 QListWidget，_pan 在 TemplatesView 上）。
    """

    def __init__(self, parent=None, view=None):
        super().__init__(parent)
        self._view = view

    def sizeHint(self, option, index) -> QSize:
        # 条目宽度 = 视口可见宽。⚠️ 不能再设 220 下限：中间栏已自适应到 ~200，
        # 220 会把条目撑得比视口宽 → Qt 绘制的 option.rect（裁剪到可见区）与
        # 点击用的 visualItemRect（未裁剪）不一致 → 星标点击区与可见星标错位、
        # 右缘内容被裁。option.rect.width() 在真实布局时为可见宽；构造期瞬时为 0，
        # 给个 120 小下限等 Qt 用真实宽重排（实测 show() 后会重新查询）。
        return QSize(max(option.rect.width(), 120), _TEMPLATE_ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        t = index.data(ROLE_TEMPLATE)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # ⚠️ 左右内缩 ROW_INSET：模板条目在面板内带左右内边距（卡片式内嵌，用户指定）。
        #    QListView 项填满整行，不改 rect 条目会贴满面板边缘。点击区域仍是
        #    整行（option.rect 不变），只是背景/文字块内缩。上下 2px 维持。
        #    ★ 绘制与视图层点击区共用同一 ROW_INSET（见文件头注释）。
        rect = QRect(option.rect).adjusted(ROW_INSET, 2, -ROW_INSET, -2)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setBrush(option.palette.highlight().color())
        elif hovered:
            h = QColor(option.palette.placeholderText().color())
            h.setAlpha(16)
            painter.setBrush(h)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(_rounded_path(rect, _RADIUS))

        if t is None:
            painter.restore()
            return
        dim = not bool(t.get("enabled", True))
        text_color = QColor(option.palette.windowText().color())
        if dim:
            text_color.setAlpha(120)

        # 长条目横向平移：内容（名称/钥匙片/触发）整体随 _pan 平移，★ 固定右缘。
        # 偏移来自视图 _pan（行号 → px）；按两行内容全宽算溢出并夹紧写回，
        # 拖拽续滑从夹紧值起算（避免拖动超出后粘滞）。
        view = self._view
        _pan = getattr(view, "_pan", None)
        offset = int((_pan or {}).get(index.row(), 0))

        # 内容 clip 区（名称行水平范围，右端给 ★ 让位）
        content_left = rect.left() + 12
        content_w = rect.width() - STAR_ZONE - (12 + _STAR_GAP)
        name_rect = QRect(content_left, rect.top() + 7, content_w, 22)

        # 行字体三件套缓存复用（QFont 构造昂贵，逐行新建会拖慢滚轮）
        name_font, chip_font, trig_font = _row_fonts(option.font)
        # 第一行：名称（14px 中粗）——按全宽绘制（不省略），随平移裁剪
        painter.setFont(name_font)
        full_name_w = painter.fontMetrics().horizontalAdvance(t.get("name", ""))

        # 第二行：shortcut 钥匙片 + 触发方式（整体平移）
        sc = t.get("shortcut", "")
        painter.setFont(chip_font)
        chip_w = painter.fontMetrics().horizontalAdvance(sc) + 14
        trig = "Tab 触发" if t.get("trigger_mode", "tab") == "tab" else "自动触发"
        painter.setFont(trig_font)
        trig_w = painter.fontMetrics().horizontalAdvance(trig)

        full_w = max(full_name_w, chip_w + 8 + trig_w)
        overflow = max(0, full_w - content_w)
        off = max(0, min(offset, overflow))
        if _pan is not None:
            _pan[index.row()] = off

        # 内容整体平移绘制（裁剪到内容区；★ 在裁剪区外，固定右缘）。
        # ⚠️ clip 高度必须用「行内相对 y」：name_rect.top() - rect.top() = 7px。
        # 误用绝对 name_rect.top() 会让 row≥1 的高度算成负数（54-71-2=-19）→
        # 空 clip → 除第一行外全部内容不绘制（只画出裁剪区外的 ★）。
        name_top = name_rect.top() - rect.top()
        # clip 四边放宽 2px：chip（shortcut 方框）左缘=content_left、底缘=
        # rect.top()+52 都正贴 clip 边界，圆角抗锯齿被齐边裁掉 → 左/底显示不全
        # （用户反馈）。放宽后圆角完整；底=行 rect 底，不越进下一条目。
        content_clip = QRect(content_left - 2, name_rect.top() - 2,
                             content_w + 2, rect.height() - name_top + 2)
        painter.save()
        painter.setClipRect(content_clip)
        painter.setFont(name_font)
        painter.setPen(text_color)
        painter.drawText(QRect(content_left - off, name_rect.top(),
                               max(full_name_w, content_w), name_rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, t.get("name", ""))
        chip_rect = QRect(content_left - off, rect.top() + 32, chip_w, 20)
        chip_bg = option.palette.alternateBase().color()
        painter.setBrush(chip_bg)
        painter.drawRoundedRect(chip_rect, 6, 6)  # 比建 QPainterPath 便宜
        painter.setFont(chip_font)
        painter.setPen(text_color)
        painter.drawText(chip_rect, Qt.AlignmentFlag.AlignCenter, sc)
        painter.setFont(trig_font)
        painter.setPen(QColor(option.palette.placeholderText().color()))
        painter.drawText(QRect(chip_rect.right() + 8, rect.top() + 32,
                               trig_w, 20),
                         Qt.AlignmentFlag.AlignVCenter, trig)
        painter.restore()

        # ★（固定右缘，不随内容平移）
        star_rect = QRect(rect.right() - STAR_ZONE, rect.top() + 4,
                          STAR_ZONE, 26)
        star = _STAR_GOLD if t.get("favorite") else _STAR_DIM
        if dim:
            star = QColor(star); star.setAlpha(110)
        painter.setPen(star)
        painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")

        # 禁用态右下角标识（用户要求横滑时不显示 ›/‹ 提示箭头，已移除）
        if dim:
            painter.setPen(QColor(option.palette.placeholderText().color()))
            painter.setFont(option.font)  # 直接用 option.font，不再新建 QFont
            painter.drawText(QRect(rect.left() + 12, rect.bottom() - 20,
                                   rect.width(), 16),
                             Qt.AlignmentFlag.AlignLeft, "已禁用")
        painter.restore()


class FolderSourceDelegate(QStyledItemDelegate):
    """分类列 source-list 行：名称左 + 计数右对齐（参考图风格）。"""

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(option.rect.width(), 120), _FOLDER_ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        name = index.data(ROLE_FOLDER_NAME) or index.data(Qt.ItemDataRole.DisplayRole) or ""
        count = index.data(ROLE_FOLDER_COUNT) or ""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRect(option.rect).adjusted(0, 2, 0, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.setBrush(option.palette.highlight().color())
        elif hovered:
            h = QColor(option.palette.placeholderText().color())
            h.setAlpha(16)
            painter.setBrush(h)
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(_rounded_path(rect, 7))

        font = QFont(option.font)
        font.setPixelSize(13)
        painter.setFont(font)
        name_color = QColor(option.palette.windowText().color())
        if selected:
            name_color = QColor(option.palette.highlightedText().color())
        painter.setPen(name_color)
        painter.drawText(QRect(rect.left() + 10, rect.top(), rect.width() - 40, rect.height()),
                         Qt.AlignmentFlag.AlignVCenter, name)
        if count:
            painter.setPen(QColor(option.palette.placeholderText().color()))
            painter.drawText(QRect(rect.right() - 34, rect.top(), 28, rect.height()),
                             Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, str(count))
        painter.restore()


class VariableTagBar(QWidget):
    """变量胶囊条（只含胶囊；「展开/收起」「＋ 新增」由外部对话框放在
    独立右列，不挤占变量显示区）。

    - 点击胶囊 → variable_clicked（插入编辑器光标处）
    - 右键胶囊 → remove_requested（外部只对用户自定义变量处理删除）
    - 超 _MAX_COLLAPSED 折叠显示前几个，set_expanded 控制展开
    - 外部持久化（config template.extra_variables）后调用
      add_variable()/remove_variable() 增删——组件无状态依赖，
      变量系统扩展在此挂载
    """

    variable_clicked = Signal(str)
    remove_requested = Signal(str)

    # 预设变量（按使用频率）
    DEFAULT_VARIABLES = ("{{date}}", "{{time}}", "{{datetime}}", "{{uuid}}",
                         "{{clipboard}}", "{{input:name}}", "{{cursor}}")
    # 折叠时最多显示的胶囊数（400px 弹窗胶囊区 ≈ 280px 放 3 个）
    _MAX_COLLAPSED = 3

    def __init__(self, parent: QWidget | None = None, variables=None):
        super().__init__(parent)
        self._expanded = False
        self._pills: list[QPushButton] = []
        self._flow = _FlowLayout(self, spacing=6)
        # HeightForWidth：布局按实际宽度查询包裹高度（滚动区依赖——
        # 展开多行时 minimumSizeHint 高于视口才出现滚动条）
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        for var in (variables or self.DEFAULT_VARIABLES):
            self._add_pill(var)
        self._apply_collapse()

    def minimumSizeHint(self) -> QSize:
        """折叠/展开后的实际包裹高度（含换行；滚动区按此出现滚动条）。"""
        h = self._flow.heightForWidth(max(self.width(), 200))
        return QSize(40, max(h, 30))

    def _add_pill(self, var: str) -> None:
        btn = QPushButton(var)
        btn.setObjectName("varTag")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        btn.customContextMenuRequested.connect(
            lambda _p, v=var: self.remove_requested.emit(v))
        btn.clicked.connect(
            lambda _=False, v=var: self.variable_clicked.emit(v))
        self._flow.addWidget(btn)
        self._pills.append(btn)

    def add_variable(self, var: str) -> None:
        """追加变量胶囊（外部持久化到 config 后调用）。"""
        self._add_pill(var)
        self._apply_collapse()

    def remove_variable(self, var: str) -> None:
        """移除变量胶囊（外部已从 config 删除后调用）。"""
        btn = next((b for b in self._pills if b.text() == var), None)
        if btn is not None:
            self._flow.removeWidget(btn)
            self._pills.remove(btn)
            btn.deleteLater()
        self._apply_collapse()

    def variables(self) -> list[str]:
        return [b.text() for b in self._pills]

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._apply_collapse()

    def is_expanded(self) -> bool:
        return self._expanded

    def needs_collapse(self) -> bool:
        """胶囊数超过折叠阈值（外部据此显示「展开全部」按钮）。"""
        return len(self._pills) > self._MAX_COLLAPSED

    def _apply_collapse(self) -> None:
        many = len(self._pills) > self._MAX_COLLAPSED
        for i, btn in enumerate(self._pills):
            # 折叠时隐藏超出部分的胶囊（隐藏控件不占布局空间）
            btn.setVisible(not (many and not self._expanded
                                and i >= self._MAX_COLLAPSED))


class TemplateHighlighter(CodeHighlighter):
    """Pygments 高亮 + {{变量}} 跨度 accent 覆盖（Pygments 误分词兜底）。

    语言在页面层检测（code_detector）后按需重建（内容变化防抖）。
    """

    _VAR_RE = re.compile(r"\{\{[^}]*\}\}")

    def __init__(self, document, language: str = ""):
        # ⚠️ _var_fmt 必须先建——父类构造在 lexer 存在时会立即 rehighlight，
        # 触发本类的 highlightBlock（引用 _var_fmt），晚设会 AttributeError
        self._var_fmt = QTextCharFormat()
        # accent 取应用调色板 Link 角色（深浅主题自适应）
        self._var_fmt.setForeground(QApplication.palette().link().color())
        self._var_fmt.setFontWeight(QFont.Weight.Bold)
        super().__init__(document, language)
        # 无条件重刷：无 Pygments lexer（纯文本模板）时变量高亮仍生效
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        super().highlightBlock(text)  # Pygments 先着色
        for m in self._VAR_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self._var_fmt)


class _FlowLayout(QLayout):
    """简易流式布局（控件放不下自动换行）——变量胶囊条用。"""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self.setSpacing(spacing)

    def addItem(self, item) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, i: int):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i: int):
        if 0 <= i < len(self._items):
            return self._items.pop(i)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        size += QSize(2 * self.contentsMargins().left(),
                      2 * self.contentsMargins().top())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x, y = rect.x(), rect.y()
        line_h = 0
        spacing = self.spacing()
        for item in self._items:
            # ⚠️ 隐藏控件必须跳过（折叠的变量胶囊）——否则 sizeHint 仍占位，
            # 把尾部按钮挤到下一行（实测：折叠 3 个却折行）
            w = item.widget()
            if w is not None and not w.isVisible():
                continue
            hint = item.sizeHint()
            if x + hint.width() > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()
