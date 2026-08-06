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
        # 唤起类工具：允许缩到较小尺寸，避免遮挡当前工作内容
        self.resize(900, 560)
        self.setMinimumSize(560, 360)
        self.statusBar().setSizeGripEnabled(False)
        self._build_ui()
        self.statusBar().showMessage("就绪")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 左导航（Apple 风格侧边栏，objectName 供 QSS 定位）
        self._nav = QListWidget()
        self._nav.setObjectName("sidebar")
        self._nav.setFixedWidth(170)
        self._nav.setFrameShape(QListWidget.Shape.NoFrame)

        # 右侧：搜索栏 + 页面栈
        right = QVBoxLayout()
        right.setContentsMargins(10, 10, 10, 0)
        right.setSpacing(6)
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
        self._nav.currentRowChanged.connect(self._pages.setCurrentIndex)
        self._nav.setCurrentRow(0)
        right.addWidget(self._pages, 1)

        layout.addWidget(self._nav)
        layout.addLayout(right, 1)

    def closeEvent(self, event) -> None:
        """关窗不退出：隐藏窗口、保持后台监听（菜单栏应用模式）。

        Dock 图标点击 → 应用激活 → 由 bootstrap 的 applicationStateChanged
        钩子重新显示（DEVELOPMENT.md §4.1 常驻设计）。
        """
        event.ignore()
        self.hide()
        logger.info("主窗口已隐藏（应用继续后台运行）")

    def _on_search(self, query: str) -> None:
        page = self._pages.currentWidget()
        if hasattr(page, "set_query"):
            page.set_query(query)

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

    def load_history(self, items: list) -> None:
        """启动恢复：把数据库已有历史填入列表。"""
        page = self._pages.widget(0)
        if isinstance(page, HistoryView):
            page.set_items(items)
        self.statusBar().showMessage(f"已恢复 {len(items)} 条历史")

    def refresh_history(self, clipboard_item, is_new: bool = True) -> None:
        """剪贴板条目回调：is_new=True 追加列表；状态栏区分新增/去重。"""
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
