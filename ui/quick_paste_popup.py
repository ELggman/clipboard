"""Quick Paste 弹出层（⌥⇧V / 托盘「快速粘贴」触发）：最近历史列表。

设计（apple-design skill）：
- 圆角毛玻璃卡片浮层：透明容器 + 自绘阴影，卡片 12px 圆角 + 1px 分隔线
- 行自绘 delegate：正文 15px（比旧 13px 更大），选中 = 浅蓝胶囊 + 左侧 accent 竖条
  （与应用 HistoryDelegate 选中态同一语言），图标 emoji 次要色
- 高度按条目数自适应（上限 10 行）——修复「底部大量留白」
- 顶栏：标题 + 行为提示（插入 or 复制，随焦点上下文切换）

回车选中：**不依赖焦点落在列表上**。QListWidget 会吞掉 Return 并发射
itemActivated，但这要求列表持有键盘焦点。macOS 下 activateIgnoringOtherApps_
异步生效，且 Quick Paste 弹窗是**唯一隐藏主窗口**的浮层——隐藏后 macOS 的
activeWindow 可能仍指向（已隐藏的）主窗口，按下回车的事件被送进主窗口的字
件树静默吞掉，弹窗触不到。因此用双确定性兜底 + 诊断日志：
1) 应用级事件过滤器 _KeyCapture：在 QApplication.notify 最先运行，只要回车
   到达本进程**必定**被捕获（与焦点/活动窗口无关），并记录当时目标与焦点
2) QShortcut(ApplicationShortcut)：应用激活即触发（不要求弹窗是活动窗口，
   覆盖「activeWindow 仍是隐藏主窗口」的坑）
3) 列表子类 _PickList 拦截（焦点在列表时）+ 弹窗 keyPressEvent 兜底
Esc / 点击外部关闭（Qt.Popup 自带）。dismissed 在窗口隐藏时发出（选中/Esc/
点外部），供外部恢复被退避的主窗口。
"""
import logging

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QCursor,
    QColor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ui.animations import enable_smooth_wheel
from ui.macos_patch import (  # 白名单覆写 + 注册/注销
    patch_qnspanel_can_become_key,
    register_native_panel,
    unregister_native_panel,
)

logger = logging.getLogger(__name__)

# 类型 → 行首图标（emoji 轻量替代 SF Symbols）
_TYPE_ICON = {"text": "📝", "url": "🔗", "image": "🖼️", "file": "📄"}

# 布局常量
_CARD_W = 420           # 卡片可见宽度（保持与主窗口一致，shadow 在外围）
_CARD_RADIUS = 12       # 卡片圆角
_ROW_H = 44             # 单行高（正文 15px 舒适行距）
_ROW_PX = 15            # 正文像素字号
_ICON_PX = 16           # 行首 emoji 字号
_HEADER_H = 32          # 顶栏高
_CARD_VPAD = 16         # 卡片上下内边距（margins 8+8）
_SIDE_GAP = 12          # 卡片左右内边距（行内容缩进）
_SHADOW_GAP = 24        # 窗口外沿比卡片多出的阴影留白
_RADIUS_SEL = 8         # 选中胶囊圆角
_MAX_ROWS = 10          # 最多显示条数（避免弹层超高）


def _single_line(text: str) -> str:
    """内容单行化：折叠换行/制表符/连续空白为单个空格。

    drawText 对含换行的多行块在定高行内会整体裁剪/顶对齐（markdown 等
    多行内容的行正文「跑到行首位置」——用户实测）。单行后再 elide 才能
    保证每行文字垂直居中一致。
    """
    return " ".join(text.split())


class _PickList(QListWidget):
    """吞掉 Return/Enter 并转发 selected 的路由（不依赖 itemActivated）。

    QListWidget 默认把 Return 转换成 itemActivated，但那只在列表持焦点时
    才可靠；这里直接接管 Return/Enter 发 pick 信号（列表持焦点时的首选路径），
    与 _KeyCapture / QShortcut / 弹窗 keyPressEvent 多路兜底。
    """
    pick = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.pick.emit()
            return
        super().keyPressEvent(event)


class _KeyCapture(QObject):
    """应用级回车捕获：弹窗可见时 Return/Enter 必定触发选中。

    QApplication.installEventFilter 的过滤器在 notify 最先运行，早于一切焦点
    路由与 QShortcut 判定——只要回车到达本进程就一定能截获（macOS 下活动窗口
    指向隐藏主窗口时，按键会被送进主窗口、弹窗路径全部错过；此过滤器是确定性
    兜底）。附带记录当时的目标类与焦点控件，供日志诊断。

    随弹窗销毁（parent 挂弹窗）；弹窗已销毁后短路返回 False（不拦截后续事件）。
    """

    def __init__(self, popup: QWidget):
        super().__init__(popup)
        self._popup = popup

    def forget(self):
        """弹窗销毁时清引用：避免事件过滤器指向已删除的 C++ 对象。"""
        self._popup = None

    def eventFilter(self, obj, event) -> bool:
        # getattr 而非直接取属性：解释器收尾时 Python 侧的 __dict__ 可能已清空，
        # 而 Qt 侧对象仍在收事件（本过滤器挂在 QApplication 上）——直接取会抛
        # AttributeError 刷屏，这里一律当作「已销毁」短路。
        popup = getattr(self, "_popup", None)
        if popup is None:
            return False  # 弹窗已销毁
        if event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key_Return, Qt.Key_Enter):
                try:
                    visible = popup.isVisible()
                except RuntimeError:
                    self._popup = None
                    return False  # C++ 对象已删（竞态），不再拦截
                if visible:
                    logger.info(
                        "Quick Paste：回车被应用级拦截（目标=%s, focus=%s）",
                        obj.metaObject().className(),
                        QApplication.focusWidget(),
                    )
                    popup._pick_current_row()
                    return True
        return False


class _RowDelegate(QStyledItemDelegate):
    """单行自绘：图标(次要色) + 正文(主色)，选中 = 浅蓝胶囊 + accent 竖条。

    与应用 HistoryDelegate 选中态同一视觉语言（palette.highlight 淡蓝底 +
    palette.link accent 竖条），避免弹窗列表割裂。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._font = QFont()
        self._font.setPixelSize(_ROW_PX)
        self._icon_font = QFont()
        self._icon_font.setPixelSize(_ICON_PX)

    def sizeHint(self, option, index) -> QSize:
        return QSize(max(option.rect.width(), 200), _ROW_H)

    def paint(self, painter: QPainter, option, index) -> None:
        item = index.data(Qt.UserRole)
        if item is None:
            return
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRect(option.rect)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        avail = rect.width() - 2 * _SIDE_GAP
        mx = rect.left() + _SIDE_GAP

        if selected:
            pill = QRect(rect).adjusted(_SIDE_GAP - 8, 3, -(_SIDE_GAP - 8), -3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(option.palette.highlight().color()))
            painter.drawRoundedRect(pill, _RADIUS_SEL, _RADIUS_SEL)
            # 左侧 3px accent 竖条（HistoryDelegate 选中态同款）
            painter.save()
            bar = QRect(pill)
            bar.setWidth(3)
            painter.setClipRect(pill)
            painter.fillRect(bar, option.palette.link().color())
            painter.restore()

        # 图标（次要色）
        painter.setPen(option.palette.placeholderText().color())
        painter.setFont(self._icon_font)
        icon = _TYPE_ICON.get(item.type, "•")
        icon_rect = QRect(mx, rect.top(), _ICON_PX + 10, rect.height())
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, icon)

        # 正文（主色/选中文字色，单行化 + 超出 elide）
        text_color = (option.palette.highlightedText().color() if selected
                      else option.palette.text().color())
        painter.setPen(text_color)
        painter.setFont(self._font)
        content = _single_line(item.display_text(max_len=200))
        elided = QFontMetrics(self._font).elidedText(
            content, Qt.TextElideMode.ElideRight, avail - _ICON_PX - 14)
        text_rect = QRect(mx + _ICON_PX + 14, rect.top(),
                          avail - _ICON_PX - 14, rect.height())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft
                         | Qt.AlignmentFlag.AlignVCenter, elided)
        painter.restore()


class QuickPastePopup(QWidget):
    selected = Signal(object)  # ClipboardItem
    dismissed = Signal()       # 弹窗隐藏（关闭/Esc/点外部）

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        patch_qnspanel_can_become_key()  # macOS 键盘路由根因修复（白名单，幂等）
        self.setObjectName("quickPaste")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._items: list = []
        self._done = False  # 已选中（防三路回车路径同一次按键触发多次 selected）

        # 透明容器 + 外围阴影留白 → 圆角毛玻璃卡片（shadow 画在留白区）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW_GAP, _SHADOW_GAP, _SHADOW_GAP, _SHADOW_GAP)
        outer.setSpacing(0)

        self._card = QFrame(self)
        self._card.setObjectName("quickPasteCard")
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 70))
        self._card.setGraphicsEffect(shadow)
        outer.addWidget(self._card)

        card = QVBoxLayout(self._card)
        card.setContentsMargins(0, 8, 0, 8)
        card.setSpacing(0)

        # 顶栏：标题 + 行为提示（随焦点上下文切换插入/复制）
        self._header = QWidget(self._card)
        self._header.setObjectName("quickPasteHeader")
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(_SIDE_GAP, 0, _SIDE_GAP, 0)
        self._title = QLabel("最近剪贴板", self._header)
        self._title.setObjectName("quickPasteTitle")
        self._hint = QLabel("", self._header)
        self._hint.setObjectName("quickPasteHint")
        header_layout.addWidget(self._title)
        header_layout.addStretch(1)
        header_layout.addWidget(self._hint)
        self._header.setFixedHeight(_HEADER_H)
        card.addWidget(self._header)

        # 列表：delegate 自绘行（大正文 + 选中胶囊）
        self._list = _PickList(self._card)
        self._list.setObjectName("quickPasteList")
        self._list.setFrameShape(QFrame.Shape.NoFrame)  # 去掉 1px 边框
        self._list.setUniformItemSizes(True)
        # 水平滚动条必关：否则它挤占行高（viewport 变矮 → 行被裁/触发纵向滚动），
        # 且多条长文本会让 content 超宽弹出横向条。文本由 delegate elide。
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setItemDelegate(_RowDelegate(self._list))
        enable_smooth_wheel(self._list)  # 超 10 条时列表内滚动缓动
        self._list.itemDoubleClicked.connect(self._pick_item)
        self._list.itemActivated.connect(self._pick_item)
        self._list.pick.connect(self._pick_current_row)
        card.addWidget(self._list)

        # 回车/Enter——确定性两路：
        # 1) 应用级事件过滤器（_KeyCapture）：notify 最先运行，回车到达本进程
        #    必定触发，与焦点/活动窗口无关。
        # 2) QShortcut(ApplicationShortcut)：应用激活即触发。不能用
        #    WindowShortcut——Quick Paste 隐藏主窗口后 macOS 可能仍把隐藏的
        #    主窗口当成 activeWindow，WindowShortcut 不满足上下文。
        #    ApplicationShortcut 只要求「应用有键盘焦点」，绕开该坑。
        self._key_capture = _KeyCapture(self)
        QApplication.instance().installEventFilter(self._key_capture)
        self.destroyed.connect(self._key_capture.forget)  # 避免指向已删 C++ 对象
        for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
            sc.setAutoRepeat(False)
            sc.activated.connect(self._pick_current_row)

    def set_hint(self, in_text: bool) -> None:
        """行为提示：焦点在文本框 → 插入；否则 → 复制。"""
        self._hint.setText("⏎ 插入" if in_text else "⏎ 复制")

    def reassert_focus(self) -> None:
        """激活异步落地后的补拍：弹窗设为 key window + 焦点归位到列表。

        macOS 下只有激活完成后才分配 key window，回车才会路由到本进程；而
        activateIgnoringOtherApps_ 是异步的，show 后立刻拍一拍可消除
        activeWindow=None 竞态（这是「回车无反应」的最终根因之一）。
        """
        register_native_panel(self)  # 确保 +120ms 复拍时面板已在白名单
        self.activateWindow()
        self.raise_()
        self._list.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        logger.info(
            "Quick Paste：补充焦点（activeWindow=%s, focus=%s）",
            QApplication.activeWindow(), QApplication.focusWidget(),
        )

    def populate(self, items: list) -> None:
        """填充最近历史。items 最新在前。"""
        self._items = items
        self._done = False
        self._list.clear()
        for item in items:
            li = QListWidgetItem()
            li.setData(Qt.UserRole, item)
            li.setText(item.display_text(max_len=200))  # 供 a11y/无 delegate 场景
            self._list.addItem(li)
        self._list.setCurrentRow(0)
        self._resize_for_items()

    def _resize_for_items(self) -> None:
        """按条目数自适应高度（≤ _MAX_ROWS），不出现底部留白。"""
        rows = min(len(self._items), _MAX_ROWS) if self._items else 1
        list_h = rows * _ROW_H
        card_h = _HEADER_H + list_h + _CARD_VPAD
        self._list.setFixedHeight(list_h)
        self.resize(_CARD_W + 2 * _SHADOW_GAP, card_h + 2 * _SHADOW_GAP)

    def show_near_cursor(self) -> None:
        """定位在光标上方（避免遮住正在查看的内容），边界钳制到屏幕内。"""
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = max(geo.left(), min(cursor.x() - 8, geo.right() - self.width() - 8))
        y = max(geo.top(), min(cursor.y() - self.height() - 8,
                               geo.bottom() - self.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()
        register_native_panel(self)  # show 后原生 NSWindow 才存在，此刻入白名单
        from ui.animations import fade_in_window

        fade_in_window(self)  # 出现动画（origin-aware：从光标方向生长）
        self._list.setFocus()
        logger.info(
            "Quick Paste：弹窗显示（focus=%s, activeWindow=%s）",
            QApplication.focusWidget(),
            QApplication.activeWindow(),
        )

    def hideEvent(self, event) -> None:
        """隐藏（选中/Esc/点击外部）→ 移出白名单 + 通知外部（恢复退避主窗）。"""
        unregister_native_panel(self)  # 隐藏后不能再成为 key（防地址复用误伤）
        self.dismissed.emit()
        super().hideEvent(event)

    def _pick_current_row(self) -> None:
        """选中当前行（QShortcut / _PickList 共用入口）。"""
        if self._done:
            return
        row = self._list.currentRow()
        if 0 <= row < len(self._items):
            self._done = True
            self.selected.emit(self._items[row])
            self.close()

    def _pick_item(self, list_item) -> None:
        """双击/激活条目 → 发出 selected（外部决定插入/复制）。"""
        if self._done:
            return
        row = self._list.row(list_item)
        if 0 <= row < len(self._items):
            self._done = True
            self.selected.emit(self._items[row])
            self.close()

    def keyPressEvent(self, event) -> None:
        # 兜底回车（列表聚焦态下行由 _PickList 拦截；QShortcut 处理其余）：
        # Esc 交给 Qt.Popup
        if isinstance(event, QKeyEvent) and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._pick_current_row()
            return
        super().keyPressEvent(event)