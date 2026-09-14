"""已安装应用选择弹窗（隐私模式忽略列表，新增.md §9.5）。

从手动输入改为选择：扫描 /Applications、~/Applications、/System/Applications
（含其下一层子目录，如 Utilities/）的 .app bundle，并合并当前运行中的常规应用。
搜索实时过滤（支持别名），列表项带应用图标，双击或 Enter 选择。

⚠️ 存进忽略列表的**必须是** `AppEntry.name`，它与
`services/clipboard_watcher.py::_frontmost_app()` 的
`NSWorkspace…localizedName()` 保持一致——`app/bootstrap.py` 用它对
`privacy["ignored_apps"]` 做**精确字符串比较**。

真实反例（本次修复的起因）：`/Applications/Visual Studio Code.app` 的
`CFBundleDisplayName`/`CFBundleName` 都是 "Code"，`localizedName()` 也返回
"Code"。所以列表里只能显示/存 "Code"，用户搜 "Visual Studio Code" 会一无所获。
故这里额外索引**别名**（目录名、bundle id、可执行名等）用于搜索，并把与名字不同
的目录名作为 `hint` 显示在列表项里（"Code — Visual Studio Code"）帮助辨认。
"""
import logging
import plistlib
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QFileInfo, QSize, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileIconProvider,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from services import app_identity

logger = logging.getLogger(__name__)

_APP_ROOTS = (Path("/Applications"), Path("/System/Applications"))


@dataclass(frozen=True)
class AppEntry:
    """一个可被忽略的应用。

    name      —— 存进忽略列表的显示名，与 clipboard_watcher 的 localizedName() 一致
    bundle_id —— 稳定标识（不随系统语言变），与 name 一起存、任一命中即排除
    path      —— .app 路径（取图标；仅运行中、拿不到路径时为 None）
    hint      —— 与 name 不同的目录名（如 "Visual Studio Code"），列表里附带显示
    aliases   —— 额外搜索词（小写，已归一化）
    """

    name: str
    bundle_id: str = ""
    path: Path | None = None
    hint: str = ""
    aliases: frozenset[str] = field(default_factory=frozenset)


def _norm(text: str) -> str:
    """归一化统一走 app_identity：搜索/去重与忽略匹配必须用同一套比较规则。"""
    return app_identity.normalize(text)


def _merge(old: AppEntry, new: AppEntry) -> AppEntry:
    """同名应用合并：优先保留带路径的，别名取并集，hint / bundle id 互补。"""
    hint = old.hint or new.hint
    extra = {_norm(hint)} - {""} - {_norm(old.name)}
    return replace(
        old if old.path else new,
        name=old.name,
        bundle_id=old.bundle_id or new.bundle_id,
        path=old.path or new.path,
        hint=hint,
        aliases=old.aliases | new.aliases | frozenset(extra),
    )


def _read_info(app: Path) -> dict:
    """Info.plist（读不到返回空 dict，不让单个坏 bundle 中断扫描）。"""
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            return plistlib.load(f)
    except Exception:  # noqa: BLE001
        logger.debug("读取 Info.plist 失败: %s", app)
        return {}


def _entry_from_bundle(app: Path, name: str | None = None,
                       bundle_id: str = "") -> AppEntry:
    """由 .app 路径构造 AppEntry；name 缺省时按显示名→bundle 名→目录名回退。

    name 给定时（运行中应用用 localizedName()）以它为准，其余名字形式全部
    转成搜索别名——因为匹配靠的是 localizedName()。bundle_id 同理优先用调用方
    给的（运行中应用直接问 NSRunningApplication，不必再读 plist）。
    """
    info = _read_info(app)
    display = info.get("CFBundleDisplayName") or info.get("CFBundleName") or app.stem
    canonical = name or display
    bundle_id = bundle_id or str(info.get("CFBundleIdentifier") or "")
    others = {
        app.stem,
        str(info.get("CFBundleName") or ""),
        str(info.get("CFBundleDisplayName") or ""),
        bundle_id,
        str(info.get("CFBundleExecutable") or ""),
    }
    aliases = frozenset(_norm(o) for o in others if o) - {_norm(canonical)}
    hint = app.stem if _norm(app.stem) != _norm(canonical) else ""
    return AppEntry(name=canonical, bundle_id=bundle_id, path=app,
                    hint=hint, aliases=aliases)


def scan_installed_apps() -> list[AppEntry]:
    """已安装应用（含运行中的），按名字排序去重。

    扫描各根目录及其**下一层**子目录（Utilities/ 等常见嵌套位置也在内；
    不递归进 .app 内部，避免把 Xcode 里几十个内置工具当成独立应用）。
    """
    found: dict[str, AppEntry] = {}

    def add(entry: AppEntry) -> None:
        prev = found.get(entry.name)
        found[entry.name] = entry if prev is None else _merge(prev, entry)

    def scan_dir(directory: Path) -> None:
        for entry in sorted(directory.iterdir()):
            if entry.suffix == ".app":
                add(_entry_from_bundle(entry))
            elif entry.is_dir() and not entry.name.startswith("."):
                try:
                    for nested in sorted(entry.iterdir()):
                        if nested.suffix == ".app":
                            add(_entry_from_bundle(nested))
                except OSError:
                    pass

    roots = [*_APP_ROOTS, Path.home() / "Applications"]
    for root in roots:
        try:
            if root.is_dir():
                scan_dir(root)
        except OSError:
            logger.warning("扫描应用目录失败: %s", root)

    # 运行中的常规应用：可能装在别处；其 localizedName() 正是匹配所用的名字
    try:
        from AppKit import NSWorkspace

        regular = 0  # NSApplicationActivationPolicyRegular
        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if app.activationPolicy() != regular or not app.localizedName():
                continue
            name = app.localizedName()
            bundle_id = app.bundleIdentifier() or ""
            url = app.bundleURL()
            path = Path(url.path()) if url is not None else None
            if path is not None and path.suffix == ".app":
                add(_entry_from_bundle(path, name=name, bundle_id=bundle_id))
            else:
                add(AppEntry(name=name, bundle_id=bundle_id))
    except Exception:
        logger.exception("读取运行中应用失败")

    return sorted(found.values(), key=lambda e: _norm(e.name))


def list_installed_apps() -> list[str]:
    """已安装应用**显示名**列表（`scan_installed_apps()` 的轻量视图）。"""
    return [entry.name for entry in scan_installed_apps()]


class AppPickerDialog(QDialog):
    """应用选择：搜索过滤（含别名）+ 图标列表，双击/Enter/「添加」确认。"""

    def __init__(self, parent=None, selected: set[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("选择应用")
        self.setModal(True)
        self.setMinimumSize(400, 480)
        # selected 是已忽略应用的匹配键（名字 / bundle id 均已归一化）：
        # 名字或 bundle id 任一已在列表里，就不再列出，避免同一应用被加两次
        chosen = {_norm(s) for s in (selected or ())}
        self._entries = {
            e.name: e for e in scan_installed_apps()
            if not (chosen & {_norm(e.name), _norm(e.bundle_id)})
        }
        self._all = sorted(self._entries.values(), key=lambda e: _norm(e.name))
        self._icons = QFileIconProvider()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索应用…（可按名称、目录名、bundle id）")
        self._search.textChanged.connect(self._filter)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setIconSize(QSize(20, 20))
        self._list.setSpacing(1)
        for entry in self._all:
            self._list.addItem(self._make_item(entry))
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

    def _make_item(self, entry: AppEntry) -> QListWidgetItem:
        """列表项：图标 + 名字（目录名不同则附在后面）+ 路径提示。"""
        item = QListWidgetItem()
        # 存名字而非读 item.text()：显示文本可能带 hint 后缀
        item.setData(Qt.ItemDataRole.UserRole, entry.name)
        item.setText(f"{entry.name} — {entry.hint}" if entry.hint else entry.name)
        if entry.path is not None:
            icon = self._icons.icon(QFileInfo(str(entry.path)))
            if not icon.isNull():
                item.setIcon(icon)
            item.setToolTip(str(entry.path))
        return item

    # ---- 行为 ----

    def _haystack(self, item: QListWidgetItem) -> str:
        """搜索文本：名字 + 显示文本 + 全部别名。"""
        name = item.data(Qt.ItemDataRole.UserRole) or ""
        entry = self._entries.get(name)
        aliases = " ".join(entry.aliases) if entry else ""
        return _norm(f"{name} {item.text()} {aliases}")

    def _filter(self, query: str) -> None:
        """按输入过滤列表（空格分词，全部命中才显示）；无结果时禁用「添加」。"""
        tokens = _norm(query).split()
        shown = 0
        first_visible = -1
        for i in range(self._list.count()):
            item = self._list.item(i)
            match = all(tok in self._haystack(item) for tok in tokens)
            item.setHidden(not match)
            if match:
                shown += 1
                if first_visible < 0:
                    first_visible = i
        self._add_btn.setEnabled(shown > 0)
        # 自动选中首个命中项：搜完直接回车即可添加
        self._list.setCurrentRow(first_visible)

    def selected_app(self) -> str:
        """当前选中应用名（无选中返回空）。"""
        entry = self.selected_entry()
        return entry.name if entry is not None else ""

    def selected_entry(self) -> AppEntry | None:
        """当前选中项（含 bundle id，供忽略列表按稳定标识存储）。"""
        item = self._list.currentItem()
        if item is None or item.isHidden():
            return None
        return self._entries.get(item.data(Qt.ItemDataRole.UserRole) or "")

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
