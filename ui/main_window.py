"""主窗口：左导航 + 右侧内容区 + 顶部搜索栏 + 底部状态栏（DEVELOPMENT.md §6）。

页面全部占位视图，逐模块替换为真实实现。
"""
import logging

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
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

logger = logging.getLogger(__name__)

# 左导航：显示名 → 页面视图类
_NAV_PAGES: list[tuple[str, type]] = [
    ("History", HistoryView),
    ("Collections", CollectionsView),
    ("Snippet", SnippetsView),
    ("Settings", SettingsView),
]


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Clipboard Workspace")
        self.resize(1000, 640)
        self._build_ui()
        self.statusBar().showMessage("就绪")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左导航
        self._nav = QListWidget()
        self._nav.setFixedWidth(160)

        # 右侧：搜索栏 + 页面栈
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索历史…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search)
        right.addWidget(self._search)

        self._pages = QStackedWidget()
        for name, view_cls in _NAV_PAGES:
            self._nav.addItem(QListWidgetItem(name))
            self._pages.addWidget(view_cls())
        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._nav.setCurrentRow(0)
        right.addWidget(self._pages, 1)

        layout.addWidget(self._nav)
        layout.addLayout(right, 1)

    def _on_search(self, query: str) -> None:
        page = self._pages.currentWidget()
        if hasattr(page, "set_query"):
            page.set_query(query)

    def refresh_history(self, clipboard_item) -> None:
        """剪贴板新条目回调：刷新历史页与状态栏。"""
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.add_item(clipboard_item)
        self.statusBar().showMessage(
            f"已捕获 {clipboard_item.type} · {clipboard_item.hash[:8]}"
        )
