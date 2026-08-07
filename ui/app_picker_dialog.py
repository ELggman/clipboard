"""已安装应用选择弹窗（隐私模式忽略列表，新增.md §9.5）。

从手动输入改为选择：扫描 /Applications、~/Applications、/System/Applications
的 .app bundle（读 Info.plist 显示名），并合并当前运行中的常规应用。
搜索框实时过滤；双击或 Enter 选择。
"""
import logging
import plistlib
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)

_APP_ROOTS = (Path("/Applications"), Path("/System/Applications"))


def list_installed_apps() -> list[str]:
    """已安装应用显示名（去重排序）：扫描 .app bundle + 运行中常规应用。"""
    names: set[str] = set()
    for root in _APP_ROOTS:
        try:
            if root.is_dir():
                for entry in root.iterdir():
                    if entry.suffix == ".app":
                        names.add(_display_name(entry))
        except OSError:
            logger.warning("扫描应用目录失败: %s", root)
    home_apps = Path.home() / "Applications"
    try:
        if home_apps.is_dir():
            for entry in home_apps.iterdir():
                if entry.suffix == ".app":
                    names.add(_display_name(entry))
    except OSError:
        pass
    # 运行中的常规应用（可能不在上述目录，如独立安装器装的）
    try:
        from AppKit import NSWorkspace

        regular = 0  # NSApplicationActivationPolicyRegular
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.activationPolicy() == regular and app.localizedName():
                names.add(app.localizedName())
    except Exception:
        logger.exception("读取运行中应用失败")
    return sorted(names)


def _display_name(app: Path) -> str:
    """Info.plist 的显示名（回退 bundle 名/目录名）。"""
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            info = plistlib.load(f)
        return (info.get("CFBundleDisplayName")
                or info.get("CFBundleName")
                or app.stem)
    except Exception:
        return app.stem


class AppPickerDialog(QDialog):
    """应用选择：搜索过滤 + 列表，双击/Enter/「添加」确认。"""

    def __init__(self, parent=None, selected: set[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("选择应用")
        self.setModal(True)
        self.setMinimumSize(360, 420)
        self._all = [name for name in list_installed_apps()
                     if not selected or name not in selected]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索应用…")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setObjectName("historyList")
        for name in self._all:
            self._list.addItem(QListWidgetItem(name))
        self._list.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self._list, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self._add_btn = QPushButton("添加")
        self._add_btn.setObjectName("primaryButton")
        self._add_btn.clicked.connect(self.accept)
        buttons.addWidget(self._add_btn)
        layout.addLayout(buttons)

        self._search.setFocus()
        self._filter("")

    # ---- 行为 ----

    def _filter(self, query: str) -> None:
        """按输入过滤列表；无结果时禁用「添加」。"""
        q = query.strip().lower()
        shown = 0
        for i in range(self._list.count()):
            item = self._list.item(i)
            match = (not q) or q in item.text().lower()
            item.setHidden(not match)
            shown += 1 if match else 0
        self._add_btn.setEnabled(shown > 0)

    def selected_app(self) -> str:
        """当前选中应用名（无选中返回空）。"""
        item = self._list.currentItem()
        return item.text() if item is not None else ""

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.selected_app():
                self.accept()
                return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)
