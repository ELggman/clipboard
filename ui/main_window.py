"""主窗口：顶部导航 + 搜索栏 + 内容区 + 底部状态栏（DEVELOPMENT.md §6）。

页面全部占位视图，逐模块替换为真实实现。
"""
import logging

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt
from PySide6.QtWidgets import (
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
    QVBoxLayout,
    QWidget,
)

from .collections_view import CollectionsView
from .history_view import HistoryView
from .settings_view import SettingsView
from .templates_view import TemplatesView
from .timeline_view import TimelineView

logger = logging.getLogger(__name__)

# 顶部导航：显示名 → 页面视图类
_NAV_PAGES: list[tuple[str, type]] = [
    ("历史", HistoryView),
    ("收藏夹", CollectionsView),
    ("模板", TemplatesView),
    ("时间线", TimelineView),
    ("设置", SettingsView),
]


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Clipboard Workspace")
        self.resize(380, 660)
        self.setMinimumSize(380, 660)
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

        self._nav = QListWidget()
        self._nav.setObjectName("topnav")
        self._nav.setFlow(QListView.Flow.LeftToRight)
        self._nav.setFixedHeight(38)
        self._nav.setSpacing(2)
        self._nav.setFrameShape(QListWidget.Shape.NoFrame)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._nav)

        # 内容区（顶部 margins 5：导航栏与内容贴合，不留空白带）
        right = QVBoxLayout()
        right.setContentsMargins(10, 5, 10, 0)
        right.setSpacing(0)
        # 搜索行：仅历史页显示（搜索框 + 搜索范围按钮）
        self._search_row = QHBoxLayout()
        self._search_row.setSpacing(6)
        self._search = QLineEdit()
        self._search.setObjectName("searchBox")
        self._search.setFixedHeight(30)
        self._search.setPlaceholderText("搜索历史…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        self._search_row.addWidget(self._search, 1)
        # 「会话：」标注（带背景——无背景控件渲染空白）+ 窄范围按钮
        self._search_scope_tag = QLabel("搜索范围：")
        # self._search_scope_tag.setStyleSheet(
        #     "QLabel { background: #E9E9EB; border-radius: 8px;"
        #     " padding: 0 6px; color: #6E6E73; font-size: 13px; }")
        self._search_scope_tag.setFixedHeight(30)
        self._search_row.addWidget(self._search_scope_tag)
        self._search_scope_btn = QPushButton("全部会话")
        self._search_scope_btn.setObjectName("searchScopeBtn")
        self._search_scope_btn.setFixedSize(52, 30)
        self._search_scope_btn.clicked.connect(self._toggle_search_scope)
        self._search_row.addWidget(self._search_scope_btn)
        right.addLayout(self._search_row)


        self._pages = QStackedWidget()
        # QStackedWidget 继承 QFrame——默认边框在 macOS 下产生 ~8px 顶部
        # 偏移（实测页面 y=46 而非 38），必须去掉
        self._pages.setFrameShape(QFrame.Shape.NoFrame)
        for name, view_cls in _NAV_PAGES:
            self._nav.addItem(QListWidgetItem(name))
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

    def _toggle_search_scope(self) -> None:
        self._scope_current = None if self._scope_current else "current"
        self._search_scope_btn.setText(
            "本会话" if self._scope_current else "全部会话")
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
