"""主窗口：品牌行 + 顶部导航 + 内容区 + 底部状态栏（DEVELOPMENT.md §6）。

导航（Raycast 风格，设计规范）：默认 16px #666；选中 = 蓝胶囊
#007AFF 白字 10px 圆角 padding 8px 22px；图标时钟/星标/剪贴板/时间线/齿轮。
"""
import logging

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, QTimer, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPainterPath
from PySide6.QtWidgets import QSizePolicy
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
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

from .collections_view import CollectionsView
from .history_view import HistoryView
from .settings_view import SettingsView
from .templates_view import TemplatesView
from .timeline_view import TimelineView

logger = logging.getLogger(__name__)

# 顶部导航：图标 + 中文标签 → 页面视图类（460px 宽下 5 项完整显示）
_NAV_PAGES: list[tuple[str, str, type]] = [
    ("🕐", "历史", HistoryView),
    ("⭐", "收藏夹", CollectionsView),
    ("📋", "模板", TemplatesView),
    ("📈", "时间线", TimelineView),
    ("⚙️", "设置", SettingsView),
]
_ROLE_NAV_ICON = Qt.ItemDataRole.UserRole + 1
_NAV_ITEM_H = 34          # 项高（胶囊 16px 文字 + 8px 上下 padding）
# 胶囊水平 padding：420px 窗口下 5 项（中文标签）完整显示需 ≤ 10px
# （22px 时总宽 ~578 溢出，实测）
_NAV_PAD_X = 10
_NAV_ICON_W = 18          # 图标框宽（绘制必须与 sizeHint 一致——
                          # 曾用 rect.height()=28 导致文字右移溢出胶囊）


class NavItemDelegate(QStyledItemDelegate):
    """导航项自绘：默认次要色文字；选中 = 蓝胶囊（QPainter 路径——
    图标 emoji + 胶囊背景，避免 QPushButton/QLabel 的 emoji 渲染坑）。"""

    def sizeHint(self, option, index) -> QSize:
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        fm = QFontMetrics(option.font)
        w = _NAV_PAD_X + 18 + 4 + fm.horizontalAdvance(label) + _NAV_PAD_X
        return QSize(w, _NAV_ITEM_H)

    def paint(self, painter: QPainter, option, index) -> None:
        icon = index.data(_ROLE_NAV_ICON) or ""
        label = index.data(Qt.ItemDataRole.DisplayRole) or ""
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRect(option.rect).adjusted(2, 3, -2, -3)
        font = QFont(option.font)
        font.setPixelSize(16)
        painter.setFont(font)
        if selected:
            # 蓝胶囊：accent（palette Link 角色，深浅主题自适应）
            painter.setBrush(option.palette.link().color())
            painter.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.addRoundedRect(rect, 10, 10)
            painter.drawPath(path)
            color = "#FFFFFF"
        else:
            color = option.palette.placeholderText().color().name()
        # 图标（emoji 字形） + 标签——图标框宽必须与 sizeHint 一致，
        # 否则标签右移溢出胶囊（实测：右侧高亮覆盖不全）
        icon_rect = QRect(rect.left() + _NAV_PAD_X, rect.top(),
                          _NAV_ICON_W, rect.height())
        painter.setPen(option.palette.windowText().color())
        painter.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, icon)
        painter.setPen(color)
        label_rect = QRect(icon_rect.right() + 4, rect.top(),
                           rect.width() - _NAV_ICON_W - _NAV_PAD_X - 6, rect.height())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignVCenter, label)
        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Clipboard Workspace")
        # 模板列固定 300px 后窗口进一步收窄（设计决策）
        self.resize(420, 700)
        # self.setMinimumSize(560, 560)
        self.statusBar().setSizeGripEnabled(False)
        self._engine = None
        self._full_items: list = []
        self._active_session_id = 1
        self._scope_current = None
        self._privacy_label = QLabel("📋 监控中")
        self._privacy_label.setObjectName("privacyStatus")
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
        self._nav.setFixedHeight(44)
        self._nav.setSpacing(4)
        self._nav.setFrameShape(QListWidget.Shape.NoFrame)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Ignored：nav 的 sizeHint（≈5 项总宽）不得把窗口撑过 420（实测 476）
        self._nav.setSizePolicy(QSizePolicy.Policy.Ignored,
                                QSizePolicy.Policy.Fixed)
        self._nav.setItemDelegate(NavItemDelegate(self._nav))
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
        self._search.setFixedHeight(30)
        self._search.setPlaceholderText("搜索历史…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        self._search_row.addWidget(self._search, 1)
        seg = QFrame()
        seg.setObjectName("segGroup")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        self._scope_group = QButtonGroup(self)
        self._scope_all_btn = QPushButton("全部会话")
        self._scope_current_btn = QPushButton("本会话")
        for btn in (self._scope_all_btn, self._scope_current_btn):
            btn.setObjectName("segBtn")
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

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
        logger.info("主窗口已隐藏（应用继续后台运行）")

    # ---- 搜索 ----

    def _on_search(self, query: str) -> None:
        self._search_timer.start()

    def _apply_search(self) -> None:
        page = self._pages.widget(0)
        if not isinstance(page, HistoryView):
            return
        query = self._search.text().strip()
        if not query:
            page.set_view_session_id(self._active_session_id)
            page.set_items(getattr(self, "_full_items", []))
            return
        if self._engine is None:
            return
        from services import history_service

        sid = (self._active_session_id if self._scope_current else None)
        results = history_service.search_items(self._engine, query,
                                               session_id=sid)
        page.set_global_view()
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
        self._privacy_label.setText("🔒 监控已暂停" if paused else "📋 监控中")

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
