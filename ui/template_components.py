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

from PySide6.QtCore import QRect, QSize, Qt, QPoint, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QTextCharFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QScrollArea,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ui.code_highlighter import CodeHighlighter
from services.template.custom_vars import (
    extra_insert_texts,
    load_custom_vars,
    load_extra_variables,
    save_extra_variables,
)
from services.template.registry import (
    CAT_CUSTOM,
    CAT_SCRIPT,
    PRESET_VARIABLES,
    CustomVariable,
    VariableMeta,
    custom_default_tooltip,
    custom_tooltip,
    group_by_category,
    is_preset,
    meta_for,
)

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


# ---- 变量配置持久化（config template 段；胶囊区/变量库/自动补全共用）----
# load_extra_variables / save_extra_variables 已迁到
# services.template.custom_vars（结构化 list[CustomVariable] + 旧格式迁移），
# 此处 re-export（顶部 import）供 UI 与既有调用方兼容。


def load_favorite_variables() -> list[str]:
    """常用变量（config template.favorite_variables）；null/空 → 全部预设。

    ⚠️ 返回值（预设列表）随注册表增长自动更新——null 语义 = 「全部预设」，
    不落盘硬编码副本。
    """
    try:
        from app.config import load_config

        config = load_config()
        favs = config.get("template", {}).get("favorite_variables")
        return list(favs) if favs else [m.insert for m in PRESET_VARIABLES]
    except Exception:
        return [m.insert for m in PRESET_VARIABLES]


def save_favorite_variables(favs: list[str]) -> None:
    """持久化常用变量。"""
    try:
        from app.config import save_user_config

        save_user_config({"template": {"favorite_variables": list(favs)}})
    except Exception:
        pass


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

    # 预设变量（唯一事实源 = 变量注册表 registry；顺序同注册表：
    # date/time/datetime/uuid/clipboard/selection/input/cursor）
    DEFAULT_VARIABLES = tuple(m.insert for m in PRESET_VARIABLES)
    # 折叠时最多显示的胶囊数（400px 弹窗胶囊区 ≈ 280px 放 3 个）
    _MAX_COLLAPSED = 3

    def __init__(self, parent: QWidget | None = None, variables=None,
                 tooltips=None):
        super().__init__(parent)
        self._expanded = False
        self._pills: list[QPushButton] = []
        self._tooltips: dict[str, str] = dict(tooltips or {})
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
        # macOS 上 varTag 的 sizeHint 高度（样式表 padding 不计入，实测 ~5px）
        # 远小于实际渲染高度（原生按钮最小值 ~24px）。_FlowLayout 按偏小的
        # sizeHint 计算行高，第二行胶囊叠到第一行上（问题4「取消收藏后堆叠」）。
        # 固定高度让 sizeHint == 实际高度，行高才正确（与右侧按钮同值 24px）。
        btn.setFixedHeight(24)
        # 悬停说明（可发现性）：内置变量查注册表（作用/用法/例子），
        # 自定义变量用注入的 tooltip（描述 + 值来源；缺省回退默认说明）
        meta = meta_for(var)
        btn.setToolTip(meta.tooltip() if meta
                       else (self._tooltips.get(var) or custom_default_tooltip()))
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
        self._relayout()

    def remove_variable(self, var: str) -> None:
        """移除变量胶囊（外部已从 config 删除后调用）。"""
        btn = next((b for b in self._pills if b.text() == var), None)
        if btn is not None:
            self._flow.removeWidget(btn)
            self._pills.remove(btn)
            self._detach_pill(btn)
        self._apply_collapse()
        self._relayout()

    def _detach_pill(self, btn) -> None:
        """立即从胶囊条分离旧胶囊（隐藏 + 脱离父级 + 延迟删除）。

        deleteLater 是延迟删除，只 setVisible(False) 的话，旧胶囊在下一轮
        事件循环前仍是胶囊条子控件、仍占着旧几何——macOS 上会把新胶囊
        挤回默认 (0,0,640,480)，叠在一起（问题4「取消收藏后堆叠」）。
        setParent(None) 立即解除父子关系，旧胶囊不再参与任何重绘/布局。
        """
        btn.hide()
        btn.setParent(None)
        btn.deleteLater()

    def variables(self) -> list[str]:
        return [b.text() for b in self._pills]

    def set_tooltips(self, tooltips: dict[str, str]) -> None:
        """更新自定义变量悬停说明（描述/值来源变更后由外部注入）。

        须在 set_variables 之前调用（后者重建胶囊时读取）。
        """
        self._tooltips = dict(tooltips or {})

    def set_variables(self, variables: list[str]) -> None:
        """整体替换胶囊（常用变量在「变量库」★ 变更后重建）。"""
        for btn in self._pills:
            self._flow.removeWidget(btn)
            self._detach_pill(btn)
        self._pills.clear()
        for var in variables:
            self._add_pill(var)
        self._apply_collapse()
        self._relayout()

    def _relayout(self) -> None:
        """强制流式布局立即重排（胶囊增/删/重建后）。

        ⚠️ 胶囊区在 QScrollArea 里，控件尺寸不变时 Qt 不会重跑布局——新加
        胶囊会停在默认几何 (0,0,640,480)，与旧胶囊堆叠（实测：取消收藏后
        全部叠在一起）。

        不依赖 QLayout.activate()（macOS 上 activate 的 topLevel 检查可能
        提前 return、不同步重排）——直接调 _do_layout 用当前内容矩形排，
        再 repaint()（同步）强制重绘清掉旧胶囊残留像素。
        """
        self._flow.invalidate()
        self._flow._do_layout(self.contentsRect(), False)
        self.updateGeometry()
        self.repaint()
        # 兜底：deleteLater 的旧胶囊在下一轮事件循环才真正删除，此轮过后
        # Qt 可能再跑一次布局把新胶囊打回默认几何——延迟一轮再排一次，
        # 确保删除完成后的布局是干净的（macOS 上单次 _do_layout 不够）。
        QTimer.singleShot(0, self._relayout_after_delete)

    def _relayout_after_delete(self) -> None:
        self._flow._do_layout(self.contentsRect(), False)
        self.updateGeometry()
        self.repaint()
        pos = [(b.text(), b.geometry().x(), b.geometry().y(),
                b.height(), b.minimumHeight(), b.sizeHint().height(),
                b.minimumSizeHint().height())
               for b in self._pills if b.isVisible()]
        logger.info("胶囊重排完成: 容器宽=%s spacing=%s 可见=(text,x,y,h,minH,sh,msh)=%s",
                    self.contentsRect().width(), self._flow.spacing(), pos)

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
            # 行高必须按「实际渲染高度」算：macOS 上样式表 padding 不计入
            # sizeHint（sizeHint 偏小，实测胶囊 ~8px），且 setFixedHeight 不
            # 可靠地反映到 minimumSize——用三者最大值兜底（w.height() 是上一
            # 轮 setGeometry 夹到固定高度后的真实高度，最接近实际渲染值）。
            # 否则第二行胶囊叠到第一行上（问题4「堆叠」）。
            eff_h = max(hint.height(),
                        w.minimumHeight() if w is not None else 0,
                        w.height() if w is not None else 0)
            hint.setHeight(eff_h)
            if x + hint.width() > rect.right() and line_h > 0:
                x = rect.x()
                y += line_h + spacing
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + spacing
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


# 「变量库」弹层行 ★ 点击区宽度（行首星标切换常用）
LIB_STAR_ZONE = 30


class _LibraryRowButton(QPushButton):
    """变量库行按钮：按下时按 x 区分 ★ 区点击 vs 行点击。

    ⚠️ 不能靠弹层级 mousePressEvent 检测（QPushButton 会消费按下事件，
    事件不冒泡到父级）——在按钮自身记录按下位置并按 x 分流。不调
    super().mousePressEvent（避免默认按下态/clicked 干扰，自发光信号）。
    """

    star_clicked = Signal(str)  # insert：★ 切换常用
    row_clicked = Signal(str)   # insert：点击插入

    def __init__(self, text: str, insert: str, parent=None):
        super().__init__(text, parent)
        self._insert = insert

    def mousePressEvent(self, event) -> None:
        if event.position().x() < LIB_STAR_ZONE:
            self.star_clicked.emit(self._insert)
        else:
            self.row_clicked.emit(self._insert)


class HoverButton(QPushButton):
    """悬停按钮：enter/leave 事件转发（「变量库」悬停展开用）。

    鼠标移到按钮上 → entered；移出 → left。外部据此 + 弹层的 entered/left
    用定时器控制开关：鼠标在按钮**或**弹层上都保持打开。
    """

    entered = Signal()
    left = Signal()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.entered.emit()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.left.emit()


class VariableLibraryPopup(QWidget):
    """「变量库」弹层：按来源类别分组列出全部变量（内置 + 自定义）。

    - Qt.Popup（代码库已验证的可交互弹层模式，同 template_picker/item_detail）：
      自带 NSPanel 外观阴影 + 点击外部/Esc 关闭——悬停计时器方案在 macOS 上
      不可靠（移向弹层时 250ms 关窗先触发，点击永远来不及，实测 bug），
      改由外部「点击切换」（_toggle_library）+ Popup 自带外部点击关闭。
    - 行 = ★ + 变量插入文本：★ 区点击切换常用（favorites_changed →
      外部刷新胶囊区），其余区点击 → insert_requested（input 走后缀规则，
      外部处理）
    - 只读数据从 config 读（load_favorite_variables）；外部增删自定义
      变量后调 set_custom_variables 再 rebuild
    - **脚本变量**（`cw:` 值源，§7.4）由 set_script_variables 注入，单独
      成组排在最前（内置在前、用户自建在后）；与自定义变量同名时以自定义
      为准（同 load_custom_vars 的覆盖规则），不重复出现两条
    """

    insert_requested = Signal(str)
    favorites_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setObjectName("variableLibrary")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._custom: list[CustomVariable] = []
        self._scripts: list[CustomVariable] = []
        self._rows: list[tuple[QPushButton, str]] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setObjectName("varLibraryScroll")
        lay.addWidget(self._scroll)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(2)
        self._scroll.setWidget(self._body)
        self.resize(260, 300)

    def set_custom_variables(self, custom: list[CustomVariable]) -> None:
        """外部注入用户自定义变量（编辑弹窗增删时同步）。"""
        self._custom = list(custom)

    def set_script_variables(self, scripts: list[CustomVariable]) -> None:
        """外部注入脚本变量（`config/scripts` + `resources/scripts`）。

        调用方应传**未被自定义变量顶掉**的那些（visible_script_variables）；
        这里再兜一层同名去重，保证「展示的 = 求值生效的」。
        """
        self._scripts = list(scripts)

    # ---- 内容构建 ----

    def rebuild(self) -> None:
        """按来源类别重排全部变量（内置 + 脚本 + 自定义），刷新 ★ 状态。"""
        while self._body_lay.count():
            item = self._body_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._rows.clear()
        tooltips: dict[str, str] = {}
        metas = list(PRESET_VARIABLES)
        for c in self._custom:
            if is_preset(c.insert()):
                continue
            metas.append(VariableMeta(insert=c.insert(), category=CAT_CUSTOM,
                                      description="", usage="", example="",
                                      builtin=False))
            tooltips[c.insert()] = custom_tooltip(c)
        custom_names = {c.insert() for c in self._custom}
        for s in self._scripts:
            # 同名自定义变量赢（load_custom_vars 的覆盖规则）——否则库里会
            # 出现两条同名行，而其中一条求值时根本不生效
            if is_preset(s.insert()) or s.insert() in custom_names:
                continue
            metas.append(VariableMeta(insert=s.insert(), category=CAT_SCRIPT,
                                      description=s.description, usage="",
                                      example="", builtin=True))
            tooltips[s.insert()] = custom_tooltip(s)
        favs = set(load_favorite_variables())
        for cat, group in group_by_category(metas):
            title = QLabel(cat)
            title.setObjectName("groupHeader")
            self._body_lay.addWidget(title)
            for m in group:
                btn = _LibraryRowButton(
                    ("★ " if m.insert in favs else "☆ ") + m.insert,
                    m.insert)
                btn.setObjectName("varLibRow")
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                meta = meta_for(m.insert)
                btn.setToolTip(meta.tooltip() if meta
                               else (tooltips.get(m.insert)
                                     or custom_default_tooltip()))
                btn.star_clicked.connect(self._toggle_favorite)
                btn.row_clicked.connect(self._emit_insert)
                self._body_lay.addWidget(btn)
                self._rows.append((btn, m.insert))
        self._body_lay.addStretch(1)

    def _toggle_favorite(self, insert: str) -> None:
        favs = load_favorite_variables()
        if insert in favs:
            favs.remove(insert)
        else:
            favs.append(insert)
        save_favorite_variables(favs)
        self.rebuild()
        self.favorites_changed.emit()

    def _emit_insert(self, insert: str) -> None:
        self.insert_requested.emit(insert)
        self.hide()
