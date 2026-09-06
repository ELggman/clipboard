"""主窗口：顶部导航 + 内容区 + 底部状态栏（DEVELOPMENT.md §6）。

导航（Raycast 风格，设计规范）：默认 14px 次要灰；选中 = 蓝胶囊
#007AFF 白字 9px 圆角；线性图标（ui/icons.py，取代 emoji——macOS
Qt 6.9 下 emoji/按钮图标渲染空白）。图标 + 中文标签，hover 轻过渡。
"""
import logging

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QRect,
    QSize,
    QTimer,
    Qt,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPainterPath,
)
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from ui.icons import icon as ui_icon

from .animations import HoverAnimator
from .collections_view import CollectionsView
from .history_view import HistoryView
from .settings_view import SettingsView
from .templates_view import TemplatesView
from .timeline_view import TimelineView

logger = logging.getLogger(__name__)

# 顶部导航：线性图标名 + 中文标签 → 页面视图类（420px 宽下 5 项完整显示）
_NAV_PAGES: list[tuple[str, str, type]] = [
    ("clock", "历史", HistoryView),
    ("star", "收藏夹", CollectionsView),
    ("clipboard", "模板", TemplatesView),
    ("chart", "时间线", TimelineView),
    ("gear", "设置", SettingsView),
]
_ROLE_NAV_ICON = Qt.ItemDataRole.UserRole + 1
_NAV_ITEM_H = 36          # 项高（胶囊 14px 文字 + 上下留白）
# 胶囊水平 padding：420px 窗口下 5 项（中文标签）完整显示需 ≤ 10px
# （22px 时总宽 ~578 溢出，实测）
_NAV_PAD_X = 10
_NAV_ICON_W = 16          # 图标框宽（绘制必须与 sizeHint 一致——
                          # 曾用 rect.height()=28 导致文字右移溢出胶囊）


class NavItemDelegate(QStyledItemDelegate):
    """导航项自绘：默认次要色文字 + 线性图标；hover 淡灰底（过渡）；
    选中 = 蓝胶囊（QPainter 路径，图标随选中变白）。"""

    animator = None  # HoverAnimator（MainWindow 装配）

    def sizeHint(self, option, index) -> QSize:
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        font = QFont(option.font)
        font.setPixelSize(14)
        fm = QFontMetrics(font)
        w = _NAV_PAD_X + _NAV_ICON_W + 4 + fm.horizontalAdvance(label) + _NAV_PAD_X
        return QSize(w, _NAV_ITEM_H)

    def paint(self, painter: QPainter, option, index) -> None:
        icon_name = index.data(_ROLE_NAV_ICON) or ""
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRect(option.rect).adjusted(2, 2, -2, -2)
        if selected:
            painter.setBrush(option.palette.link().color())
            painter.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.addRoundedRect(rect, 9, 9)
            painter.drawPath(path)
            color = "#FFFFFF"
        else:
            color = option.palette.placeholderText().color()
            hover_alpha = (self.animator.alpha(index.row())
                           if self.animator else
                           (1.0 if option.state & QStyle.StateFlag.State_MouseOver
                            else 0.0))
            if hover_alpha > 0:
                h = QColor(option.palette.placeholderText().color())
                h.setAlpha(round(16 * hover_alpha))  # ≈ rgba(0,0,0,0.05)
                painter.setBrush(h)
                painter.setPen(Qt.PenStyle.NoPen)
                path = QPainterPath()
                path.addRoundedRect(rect, 9, 9)
                painter.drawPath(path)
        # 线性图标（16px，颜色随状态：选中白 / 未选中次要灰）
        icon_rect = QRect(rect.left() + _NAV_PAD_X, rect.top(),
                          _NAV_ICON_W, rect.height())
        icon_color = QColor("#FFFFFF") if selected else color
        pix = ui_icon(icon_name, _NAV_ICON_W, icon_color)
        # 图标逻辑高恒 = _NAV_ICON_W（pix 物理含 dpr 倍率，pix.height() 是物理值）
        py = icon_rect.top() + (icon_rect.height() - _NAV_ICON_W) // 2
        # 显式目标逻辑尺寸：不依赖 pixmap 内部 devicePixelRatio 推断，
        # 真机 Retina（dpr=2）与普通屏渲染尺寸完全一致，杜绝放大/裁切
        painter.drawPixmap(icon_rect.left(), py, _NAV_ICON_W, _NAV_ICON_W, pix)
        # 标签：选中白 / 未选中次要灰
        font = QFont(option.font)
        font.setPixelSize(14)
        painter.setFont(font)
        painter.setPen(QColor("#FFFFFF" if selected else color.name()))
        label_rect = QRect(icon_rect.right() + 4, rect.top(),
                           rect.width() - _NAV_ICON_W - _NAV_PAD_X - 6,
                           rect.height())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, label)
        painter.restore()


class MainWindow(QMainWindow):
    # X 关闭 → 隐藏到托盘（bootstrap 订阅后收起 Dock 图标；仅窗口 UI 意图，
    # 不触发任何业务/数据结构变更）
    hidden_to_tray = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Clipboard Workspace")
        # 模板列固定 300px 后窗口进一步收窄（设计决策）
        self.resize(420, 700)
        self.setMinimumSize(420, 700)
        self.statusBar().setSizeGripEnabled(False)
        self._engine = None
        self._full_items: list = []
        self._active_session_id = 1
        self._scope_current = None
        self._privacy_label = QLabel("● 监控中")
        self._privacy_label.setObjectName("privacyStatus")
        self._privacy_label.setProperty("paused", False)
        self.statusBar().addPermanentWidget(self._privacy_label)
        self._build_ui()
        self._bind_feedback()
        self.statusBar().showMessage("就绪")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 导航（Raycast 风格胶囊标签；品牌行已按用户要求移除）
        self._nav = QListWidget()
        self._nav.setObjectName("topnav")
        self._nav.setFlow(QListView.Flow.LeftToRight)
        self._nav.setFixedHeight(42)
        self._nav.setSpacing(4)
        self._nav.setMouseTracking(True)  # hover 过渡需要
        self._nav.setFrameShape(QListWidget.Shape.NoFrame)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ignored：nav 的 sizeHint（≈5 项总宽）不得把窗口撑过 420（实测 476）
        self._nav.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Fixed)
        self._nav_delegate = NavItemDelegate(self._nav)
        self._nav.setItemDelegate(self._nav_delegate)
        self._nav_anim = HoverAnimator(self._nav, self._nav_delegate)
        self._nav_delegate.animator = self._nav_anim
        layout.addWidget(self._nav)

        # 内容区（顶部 margins 5：导航栏与内容贴合，不留空白带）
        right = QVBoxLayout()
        right.setContentsMargins(10, 5, 10, 0)
        right.setSpacing(0)
        # 搜索行：仅历史页显示（搜索框 + 搜索范围分段控件——与模板页
        # 触发方式同款 segGroup/segBtn；去掉标注，搜索框获得更多宽度）
        self._search_row = QHBoxLayout()
        self._search_row.setSpacing(6)
        self._search = QLineEdit()
        self._search.setObjectName("searchBox")
        self._search.setFixedHeight(40)
        self._search.setPlaceholderText("搜索历史…")
        self._search.setClearButtonEnabled(True)
        # 搜索图标（线性；QLineEdit action 图标实测渲染可靠，不走 emoji）
        self._search.addAction(QIcon(ui_icon("search", 15, QColor("#8E8E93"))),
                               QLineEdit.ActionPosition.LeadingPosition)
        self._search.textChanged.connect(self._on_search)
        # 聚焦蓝光 ring：QSS :focus 只画 1px 边框，光晕用 QGraphicsDropShadowEffect
        #（QSS 不支持 box-shadow；FocusIn/Out 经 eventFilter 驱动 160ms 过渡）
        self._search_ring = QGraphicsDropShadowEffect(self._search)
        self._search_ring.setBlurRadius(12)
        self._search_ring.setOffset(0, 0)
        self._search_ring.setColor(QColor(0, 122, 255, 0))
        self._search.setGraphicsEffect(self._search_ring)
        self._search.installEventFilter(self)
        self._search_row.addWidget(self._search, 1)
        # 搜索范围：Apple 风格 segmented（外层灰底 + 选中白块，QSS scopeSeg）
        seg = QFrame()
        seg.setObjectName("scopeSeg")
        seg.setFixedHeight(36)
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        self._scope_group = QButtonGroup(self)
        self._scope_all_btn = QPushButton("全部会话")
        self._scope_current_btn = QPushButton("本会话")
        for btn in (self._scope_all_btn, self._scope_current_btn):
            btn.setObjectName("scopeSegBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._scope_group.addButton(btn)
            sh.addWidget(btn)
        self._scope_all_btn.setChecked(True)
        self._scope_group.idClicked.connect(self._on_scope_changed)
        self._search_row.addWidget(seg)
        right.addLayout(self._search_row)


        self._pages = QStackedWidget()
        # QStackedWidget 继承 QFrame——默认边框在 macOS 下产生 ~8px 顶部
        # 偏移（实测页面 y=46 而非 38），必须去掉
        self._pages.setFrameShape(QFrame.Shape.NoFrame)
        for icon, name, view_cls in _NAV_PAGES:
            item = QListWidgetItem(name)
            item.setData(_ROLE_NAV_ICON, icon)
            self._nav.addItem(item)
            self._pages.addWidget(view_cls())
        self._nav.currentRowChanged.connect(self._on_page_changed)
        self._nav.setCurrentRow(0)
        right.addWidget(self._pages, 1)

        layout.addLayout(right, 1)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_search)

    def _on_page_changed(self, row: int) -> None:
        self._pages.setCurrentIndex(row)
        for i in range(self._search_row.count()):
            w = self._search_row.itemAt(i).widget()
            if w is not None:
                w.setVisible(row == 0)
        if row == 0:
            if self._search.text().strip():
                self._apply_search()
            else:
                self._reload_history()
        from ui.animations import fade_in_widget

        fade_in_widget(self._pages.currentWidget())

    def eventFilter(self, obj, event) -> bool:
        """搜索框 FocusIn/Out → 蓝光 ring 过渡（其余事件放行）。"""
        if obj is self._search:
            if event.type() == QEvent.Type.FocusIn:
                self._animate_search_ring(True)
            elif event.type() == QEvent.Type.FocusOut:
                self._animate_search_ring(False)
        return super().eventFilter(obj, event)

    def _animate_search_ring(self, focused: bool) -> None:
        """搜索框聚焦蓝光淡入/淡出（160ms，QVariantAnimation 驱动 QColor）。"""
        target = (QColor(0, 122, 255, 110) if focused
                  else QColor(0, 122, 255, 0))
        anim = QVariantAnimation(self)
        anim.setDuration(160)
        anim.setStartValue(self._search_ring.color())
        anim.setEndValue(target)
        anim.valueChanged.connect(self._search_ring.setColor)
        anim.start()
        self._search_ring_anim = anim  # 持有引用防 GC

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
        logger.info("主窗口已隐藏（应用继续后台运行）")
        self.hidden_to_tray.emit()

    # ---- 搜索 ----

    def _on_search(self, query: str) -> None:
        self._search_timer.start()

    def _apply_search(self) -> None:
        page = self._pages.widget(0)
        if not isinstance(page, HistoryView):
            return
        query = self._search.text().strip()
        if not query:
            # ⚠️ 清除搜索不能用 _full_items 缓存：combo 切换会话 / 重命名后
            #    缓存不刷新，会显示另一个会话的旧数据旧名（实测 bug）。
            #    必须重新加载当前激活会话的最新数据。
            if self._engine is not None:
                self._reload_history()
            else:
                page.set_view_session_id(self._active_session_id)
                page.set_items(getattr(self, "_full_items", []))
            return
        if self._engine is None:
            self.statusBar().showMessage("搜索暂不可用（引擎未就绪）")
            return
        try:
            from services import history_service

            sid = (self._active_session_id if self._scope_current else None)
            results = history_service.search_items(self._engine, query,
                                                   session_id=sid)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("搜索失败: %r", query)
            self.statusBar().showMessage("搜索出错，请重试")
            return
        page.set_global_view()
        page.set_search_query(query)  # 空态「未匹配到…」文案
        page.set_items(results)
        scope = "本会话" if sid is not None else "全部会话"
        self.statusBar().showMessage(
            f"搜索「{query}」（{scope}）：{len(results)} 条")

    def _on_scope_changed(self, _btn_id: int) -> None:
        """搜索范围分段控件：本会话（选中）↔ 全部会话。"""
        self._scope_current = ("current" if self._scope_current_btn.isChecked()
                               else None)
        if self._search.text().strip():
            self._apply_search()

    def _reload_history(self) -> None:
        page = self._pages.widget(0)
        if not isinstance(page, HistoryView) or self._engine is None:
            return
        from services import history_service

        self._full_items = history_service.list_recent(
            self._engine, session_id=self._active_session_id)
        page.set_view_session_id(self._active_session_id)
        page.set_items(self._full_items)

    # ---- 注入 ----

    def set_search(self, engine) -> None:
        self._engine = engine

    def set_image_service(self, service) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_image_service(service)

    def set_show_image_filename(self, show: bool) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_show_image_filename(show)

    def set_font_size(self, main_px: int) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_font_size(main_px)

    def set_menu_context(self, engine, action_service, refresh_cb=None) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_menu_context(engine, action_service,
                                  refresh_cb or self._reload_history)

    def set_data_context(self, engine, image_service=None) -> None:
        for idx in range(self._pages.count()):
            page = self._pages.widget(idx)
            if isinstance(page, (CollectionsView, TimelineView)):
                page.set_context(engine, image_service)
            elif isinstance(page, TemplatesView):
                page.set_context(engine)

    def set_item_activated_handler(self, handler) -> None:
        for idx in range(self._pages.count()):
            page = self._pages.widget(idx)
            if hasattr(page, "item_activated"):
                page.item_activated.connect(handler)

    # ---- 会话（v4）----

    def set_session_context(self, engine, session_service,
                            on_active_changed=None) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_session_context(engine, session_service,
                                     on_active_changed=on_active_changed)

    def set_delete_policy(self, policy: str) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_delete_policy(policy)

    def reload_sessions(self, active_id: int) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.reload_sessions(active_id)

    def set_active_session(self, sid: int) -> None:
        self._active_session_id = sid
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.load_session(sid)

    def refresh_session_counts(self) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.refresh_session_counts()

    # ---- 历史 ----

    def load_history(self, items: list, limit: int = 1000) -> None:
        self._full_items = items
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_view_session_id(self._active_session_id)
            page.set_items(items)
        self.statusBar().showMessage(f"已恢复 {len(items)} 条历史")

    def refresh_history(self, clipboard_item, is_new: bool = True) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            if is_new:
                page.add_item(clipboard_item)
            else:
                page.mark_duplicate(clipboard_item)
        verb = "捕获" if is_new else "去重"
        self.statusBar().showMessage(
            f"{verb} {clipboard_item.type} · {clipboard_item.hash[:8]}")

    def set_privacy_status(self, paused: bool) -> None:
        """隐私状态：● 绿点监控中 / ● 灰点已暂停（QSS [paused] 着色）。"""
        self._privacy_label.setText("● 监控已暂停" if paused else "● 监控中")
        self._privacy_label.setProperty("paused", paused)
        style = self._privacy_label.style()  # property 变化需重刷样式
        style.unpolish(self._privacy_label)
        style.polish(self._privacy_label)

    def set_settings_context(self, config, appliers, engine=None,
                             privacy_state=None) -> None:
        page = self._pages.widget(4)
        if isinstance(page, SettingsView):
            page.set_context(config, appliers, engine=engine,
                             privacy_state=privacy_state)

    # ---- 反馈 ----

    def _bind_feedback(self) -> None:
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.feedback.connect(self.statusBar().showMessage)
