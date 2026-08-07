"""主窗口：顶部导航 + 搜索栏 + 内容区 + 底部状态栏（DEVELOPMENT.md §6）。

页面全部占位视图，逐模块替换为真实实现。
"""
import logging

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .collections_view import CollectionsView
from .history_view import HistoryView
from .settings_view import SettingsView
from .snippets_view import SnippetsView
from .timeline_view import TimelineView

logger = logging.getLogger(__name__)

# 顶部导航：显示名 → 页面视图类
_NAV_PAGES: list[tuple[str, type]] = [
    ("历史", HistoryView),
    ("收藏夹", CollectionsView),
    ("片段", SnippetsView),
    ("时间线", TimelineView),
    ("设置", SettingsView),
]


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Clipboard Workspace")
        # 唤起类工具：初始尺寸即最小尺寸（380 宽为内容缩放的基准档，
        # 放大后列表内容等比例放大，见 history_view.BASE_WIDTH）。
        self.resize(380, 560)
        self.setMinimumSize(380, 560)
        self.statusBar().setSizeGripEnabled(False)
        self._engine = None          # FTS5 搜索（bootstrap 注入）
        self._full_items: list = []  # 完整历史缓存（清空搜索时恢复）
        # 隐私模式状态指示（§9.4）：右侧永久控件 📋 监控中 / 🔒 监控已暂停
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

        # 顶部导航：水平分段式（Apple 工具栏风格，objectName 供 QSS 定位）
        self._nav = QListWidget()
        self._nav.setObjectName("topnav")
        self._nav.setFlow(QListView.Flow.LeftToRight)
        self._nav.setFixedHeight(38)
        self._nav.setSpacing(2)
        self._nav.setFrameShape(QListWidget.Shape.NoFrame)
        self._nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._nav)

        # 内容区：搜索栏 + 页面栈（spacing 8 拉开搜索框与列表的视觉距离）
        right = QVBoxLayout()
        right.setContentsMargins(10, 8, 10, 0)
        right.setSpacing(8)
        self._search = QLineEdit()
        self._search.setObjectName("searchBox")
        self._search.setFixedHeight(30)
        self._search.setPlaceholderText("搜索历史…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        right.addWidget(self._search)

        self._pages = QStackedWidget()
        for name, view_cls in _NAV_PAGES:
            self._nav.addItem(QListWidgetItem(name))
            self._pages.addWidget(view_cls())
        self._nav.currentRowChanged.connect(self._on_page_changed)
        self._nav.setCurrentRow(0)
        right.addWidget(self._pages, 1)

        layout.addLayout(right, 1)

        # 搜索防抖：停止输入 150ms 后才查询（FTS5 查询不频繁触发）
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._apply_search)

    def _on_page_changed(self, row: int) -> None:
        """页面切换：即时切换 + 淡入（响应优先，OutCubic 140ms）。

        返回历史页时从数据库重载：清理数据弹窗等外部删除后列表保持同步
        （收藏夹/时间线页自带 showEvent 重载，历史页数据由主窗口注入，
        故在此按搜索状态刷新——有搜索词重跑查询，否则重载完整历史）。
        """
        self._pages.setCurrentIndex(row)
        if row == 0:
            if self._search.text().strip():
                self._apply_search()  # 有搜索词：重新执行查询（结果同样可能过期）
            else:
                self._reload_history()
        from ui.animations import fade_in_widget

        fade_in_widget(self._pages.currentWidget())

    def closeEvent(self, event) -> None:
        """关窗不退出：隐藏窗口、保持后台监听（菜单栏应用模式）。

        Dock 图标点击 → 应用激活 → 由 bootstrap 的 applicationStateChanged
        钩子重新显示（DEVELOPMENT.md §4.1 常驻设计）。
        """
        event.ignore()
        self.hide()
        logger.info("主窗口已隐藏（应用继续后台运行）")

    def _on_search(self, query: str) -> None:
        """输入即防抖重启，停止输入 150ms 后执行查询。"""
        self._search_timer.start()

    def _apply_search(self) -> None:
        """执行查询：非空 → FTS5 搜索回填；清空 → 恢复完整历史。"""
        page = self._pages.widget(0)
        if not isinstance(page, HistoryView):
            return
        query = self._search.text().strip()
        if not query:
            page.set_items(getattr(self, "_full_items", []))
            return
        if self._engine is None:
            return
        from services import history_service

        results = history_service.search_items(self._engine, query)
        page.set_items(results)
        self.statusBar().showMessage(f"搜索「{query}」：{len(results)} 条")

    def set_search(self, engine) -> None:
        """注入数据库引擎（FTS5 搜索用，bootstrap 装配时调用）。"""
        self._engine = engine

    def set_image_service(self, service) -> None:
        """注入图片服务（历史列表缩略图用）。"""
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_image_service(service)

    def set_show_image_filename(self, show: bool) -> None:
        """配置：图片条目文件名显示开关（透传历史列表）。"""
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_show_image_filename(show)

    def set_font_size(self, main_px: int) -> None:
        """配置：基准字号（透传历史列表，设置页改动即时生效）。"""
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_font_size(main_px)

    def load_history(self, items: list, limit: int | None = None) -> None:
        """启动恢复：把数据库已有历史填入列表（同时缓存为完整列表）。"""
        self._full_items = list(items)
        if limit is not None:
            self._history_limit = limit
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_items(items)
        self.statusBar().showMessage(f"已恢复 {len(items)} 条历史")

    def _reload_history(self) -> None:
        """从数据库重载列表（置顶/收藏等菜单操作后刷新）。"""
        if self._engine is None:
            return
        from services import history_service

        self.load_history(
            history_service.list_recent(self._engine,
                                        limit=getattr(self, "_history_limit", 500)))

    def set_menu_context(self, engine, action_service) -> None:
        """注入右键菜单依赖（透传历史列表）。"""
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_menu_context(engine, action_service, self._reload_history)

    def set_item_activated_handler(self, handler) -> None:
        """各列表页（历史/收藏夹/时间线）单击条目 → 详情弹层。"""
        for idx in range(self._pages.count()):
            page = self._pages.widget(idx)
            if hasattr(page, "item_activated"):
                page.item_activated.connect(handler)

    def set_data_context(self, engine, image_service=None) -> None:
        """数据页注入引擎（收藏夹/片段/时间线，打开页面时自动刷新）。"""
        for idx in range(self._pages.count()):
            page = self._pages.widget(idx)
            if isinstance(page, (CollectionsView, SnippetsView, TimelineView)):
                if isinstance(page, CollectionsView):
                    page.set_context(engine, image_service)
                else:
                    page.set_context(engine)

    def _bind_feedback(self) -> None:
        """历史页菜单操作反馈 → 状态栏。"""
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.feedback.connect(self.statusBar().showMessage)

    def set_settings_context(self, config, appliers, config_path=None,
                             engine=None, privacy_state=None) -> None:
        """设置页注入：当前配置 + 生效回调 + 引擎 + 隐私状态（bootstrap 装配）。"""
        page = next((self._pages.widget(i) for i in range(self._pages.count())
                     if isinstance(self._pages.widget(i), SettingsView)), None)
        if page is not None:
            page.set_context(config, appliers, config_path, engine, privacy_state)

    def set_privacy_status(self, paused: bool) -> None:
        """隐私模式状态栏指示（bootstrap 的 PrivacyState.changed 驱动）。"""
        if paused:
            self._privacy_label.setText("🔒 监控已暂停")
            self._privacy_label.setProperty("paused", True)
        else:
            self._privacy_label.setText("📋 监控中")
            self._privacy_label.setProperty("paused", False)

    def refresh_history(self, clipboard_item, is_new: bool = True) -> None:
        """剪贴板条目回调：is_new=True 追加列表；状态栏区分新增/去重。"""
        if is_new:
            self._full_items.insert(0, clipboard_item)
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            if is_new:
                page.add_item(clipboard_item)
            else:
                page.mark_duplicate(clipboard_item)
        verb = "捕获" if is_new else "去重"
        self.statusBar().showMessage(
            f"{verb} {clipboard_item.type} · {clipboard_item.hash[:8]}"
        )
