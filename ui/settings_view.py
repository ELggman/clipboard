"""设置视图：主题/字体/历史数量/图片/自动删除/开机启动/隐私模式。

改动即生效：控件变化 → 调用对应 applier（bootstrap 注入，如主题重应用、
字号刷新）+ 合并写回 settings.yaml（save_user_config）。
"""
import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ui.fluent_combo import FluentComboBox

logger = logging.getLogger(__name__)

from app import __version__
from app.types import TEMP_MINUTE_OPTIONS
from services import app_identity

_THEME_OPTIONS = [("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")]
_FONT_OPTIONS = [12, 13, 14, 15, 16]
_MAX_ITEMS_OPTIONS = [(100, "100"), (500, "500"), (1000, "1000"), (-1, "无限")]
# §9.10：Never / 1 / 7 / 30 / 90 / 365 天
_AUTO_DELETE_OPTIONS = [(1, "1 天"), (7, "7 天"), (30, "30 天"),
                        (90, "90 天"), (365, "365 天"), (-1, "永不")]
# 复制文档大小上限（MB；0 = 不限制）
_FILE_SIZE_OPTIONS = [(10, "10 MB"), (20, "20 MB"), (50, "50 MB"), (200, "200 MB"),
                      (1024, "1 GB"), (0, "不限制")]
# 去重范围（v5）：跨会话 / 仅本会话
_DEDUPE_OPTIONS = [("all", "全部会话"), ("session", "仅本会话")]
# 删除会话策略（v5）：内容移回普通（合并去重）/ 直接删除
_DELETE_POLICY_OPTIONS = [("move", "移回普通会话"), ("delete", "直接删除")]
# 敏感内容策略（§9.17）：warn 默认
_POLICY_OPTIONS = [("warn", "提醒（保存并遮蔽显示）"),
                   ("ignore", "忽略（不保存）"),
                   ("save_temporarily", "临时保存（自动过期）")]
_TEMP_OPTIONS = [(m, f"{m} 分钟") for m in TEMP_MINUTE_OPTIONS]


class SettingsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._config: dict[str, Any] = {}
        self._appliers: dict[str, Callable] = {}
        self._config_path: Path | None = None
        self._engine = None           # 清理数据弹窗（bootstrap 注入）
        self._privacy_state = None    # 暂停监控运行时状态（bootstrap 注入）
        self._build_ui()

    def set_context(self, config: dict, appliers: dict,
                    config_path: Path | None = None,
                    engine=None, privacy_state=None) -> None:
        """注入当前配置 + 各设置项的生效回调（bootstrap 装配）。"""
        self._config = config
        self._appliers = appliers
        self._config_path = config_path
        self._engine = engine
        self._privacy_state = privacy_state
        if privacy_state is not None:
            privacy_state.changed.connect(self._sync_pause_button)
            self._sync_pause_button(privacy_state.paused)
        self._load_from_config()

    # ---- 构建 ----

    def _build_ui(self) -> None:
        # 内容包进 QScrollArea：窗口高度有限（初始 560px），设置项多时
        # 可滚动查看而非挤压在一起
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        container.setObjectName("settingsContainer")
        layout = QFormLayout(container)
        layout.setContentsMargins(16, 6, 16, 14)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(10)
        scroll.setWidget(container)
        outer.addWidget(scroll)

        self._theme = FluentComboBox()
        for value, label in _THEME_OPTIONS:
            self._theme.addItem(label, value)
        layout.addRow("主题", self._theme)

        self._font = FluentComboBox()
        for size in _FONT_OPTIONS:
            self._font.addItem(f"{size} pt", size)
        layout.addRow("字体大小", self._font)

        self._max_items = FluentComboBox()
        for value, label in _MAX_ITEMS_OPTIONS:
            self._max_items.addItem(label, value)
        layout.addRow("每会话历史数量上限", self._max_items)

        self._auto_delete = FluentComboBox()
        for value, label in _AUTO_DELETE_OPTIONS:
            self._auto_delete.addItem(label, value)
        layout.addRow("自动删除", self._auto_delete)

        self._file_size = FluentComboBox()
        for value, label in _FILE_SIZE_OPTIONS:
            self._file_size.addItem(label, value)
        layout.addRow("文件大小上限", self._file_size)

        self._dedupe_scope = FluentComboBox()
        for value, label in _DEDUPE_OPTIONS:
            self._dedupe_scope.addItem(label, value)
        layout.addRow("去重范围", self._dedupe_scope)

        self._delete_policy = FluentComboBox()
        for value, label in _DELETE_POLICY_OPTIONS:
            self._delete_policy.addItem(label, value)
        layout.addRow("删除会话时", self._delete_policy)

        self._save_images = QCheckBox("保存复制图片到本地")
        layout.addRow("图片保存", self._save_images)

        self._show_filename = QCheckBox("图片条目显示文件名")
        layout.addRow("图片文件名", self._show_filename)

        self._autostart = QCheckBox("登录时自动启动")
        layout.addRow("开机启动", self._autostart)

        hotkey = QLabel("⌘⇧V（暂不可改，V1.5 支持自定义）")
        layout.addRow("快捷键", hotkey)

        # 清理数据入口（详细交互在弹窗中，不影响收藏夹——快照独立）
        clean_btn = QPushButton("打开清理数据…")
        clean_btn.setObjectName("secondaryButton")
        clean_btn.clicked.connect(self._open_clean_dialog)
        layout.addRow("清理数据", clean_btn)

        # ---- 隐私模式（新增.md §9）----
        section = QLabel("隐私模式")
        section.setObjectName("sectionTitle")
        layout.addRow(section)

        self._policy = FluentComboBox()
        for value, label in _POLICY_OPTIONS:
            self._policy.addItem(label, value)
        layout.addRow("敏感内容策略", self._policy)

        self._temp_minutes = FluentComboBox()
        for value, label in _TEMP_OPTIONS:
            self._temp_minutes.addItem(label, value)
        layout.addRow("临时保存时长", self._temp_minutes)

        # §9.15：私钥类内容默认不保存（拿到即可冒充身份，且不像口令能改）
        self._block_private_key = QCheckBox("私钥内容不保存（推荐）")
        self._block_private_key.setToolTip(
            "开启后，检测到 PRIVATE KEY 内容时不论上面选了哪种策略都不保存")
        layout.addRow("私钥处理", self._block_private_key)

        # 忽略的应用（§9.5）：来源应用 ∈ 列表 → 不保存
        self._ignored_list = QListWidget()
        self._ignored_list.setObjectName("sideList")
        self._ignored_list.setFixedHeight(90)
        ignored_box = QVBoxLayout()
        ignored_box.setSpacing(4)
        ignored_box.addWidget(self._ignored_list)
        ignored_btns = QHBoxLayout()
        ignored_btns.setSpacing(6)
        add_btn = QPushButton("添加")
        add_btn.setObjectName("secondaryButton")
        add_btn.clicked.connect(self._add_ignored_app)
        remove_btn = QPushButton("移除")
        remove_btn.setObjectName("secondaryButton")
        remove_btn.clicked.connect(self._remove_ignored_app)
        ignored_btns.addWidget(add_btn)
        ignored_btns.addWidget(remove_btn)
        ignored_btns.addStretch(1)
        ignored_box.addLayout(ignored_btns)
        layout.addRow("忽略的应用", ignored_box)

        

        # 暂停/恢复监控（运行时状态，不持久化）
        self._pause_btn = QPushButton("暂停监控")
        self._pause_btn.setObjectName("secondaryButton")
        self._pause_btn.clicked.connect(self._toggle_pause)
        layout.addRow("监控", self._pause_btn)

        # ---- 关于（版权标注）----
        section = QLabel("关于")
        section.setObjectName("sectionTitle")
        layout.addRow(section)

        about_app = QLabel("Clipboard Workspace")
        layout.addRow("应用", about_app)

        about_version = QLabel(__version__)
        layout.addRow("版本", about_version)

        about_copyright = QLabel("© 2026 Elgg")
        layout.addRow("Copyright", about_copyright)

        # 改动即生效
        self._theme.currentIndexChanged.connect(lambda _: self._on_change("theme"))
        self._font.currentIndexChanged.connect(lambda _: self._on_change("font"))
        self._max_items.currentIndexChanged.connect(lambda _: self._on_change("max_items"))
        self._auto_delete.currentIndexChanged.connect(lambda _: self._on_change("auto_delete"))
        self._save_images.toggled.connect(lambda _: self._on_change("save_images"))
        self._show_filename.toggled.connect(lambda _: self._on_change("show_filename"))
        self._autostart.toggled.connect(lambda _: self._on_change("autostart"))
        self._policy.currentIndexChanged.connect(lambda _: self._on_change("privacy_policy"))
        self._temp_minutes.currentIndexChanged.connect(lambda _: self._on_change("privacy_temp"))
        self._block_private_key.toggled.connect(
            lambda _: self._on_change("privacy_block_private_key"))
        self._file_size.currentIndexChanged.connect(lambda _: self._on_change("max_file_size"))
        self._dedupe_scope.currentIndexChanged.connect(lambda _: self._on_change("dedupe_scope"))
        self._delete_policy.currentIndexChanged.connect(lambda _: self._on_change("session_delete_policy"))

    # ---- 清理数据 ----

    def _open_clean_dialog(self) -> None:
        """打开清理数据弹窗（详细交互在弹窗内）。"""
        if self._engine is None:
            return
        from ui.clean_data_dialog import CleanDataDialog

        CleanDataDialog(self._engine, self).exec()

    # ---- 数据 ----

    def _load_from_config(self) -> None:
        cfg = self._config
        app_cfg = cfg.get("app", {})
        hist_cfg = cfg.get("history", {})
        priv_cfg = cfg.get("privacy", {})
        self._block_signals(True)
        self._set_combo_value(self._theme, app_cfg.get("theme", "system"))
        self._set_combo_value(self._font, app_cfg.get("font_size", 14))
        self._set_combo_value(self._max_items, hist_cfg.get("max_items", 500))
        self._set_combo_value(self._auto_delete, hist_cfg.get("auto_delete_days", 30))
        self._set_combo_value(self._file_size,
                              hist_cfg.get("max_file_size_mb", 50))
        self._set_combo_value(self._dedupe_scope,
                              hist_cfg.get("dedupe_scope", "all"))
        self._set_combo_value(self._delete_policy,
                              cfg.get("session", {}).get("delete_policy", "move"))
        self._save_images.setChecked(bool(hist_cfg.get("save_images", True)))
        self._show_filename.setChecked(bool(hist_cfg.get("show_image_filename", True)))
        self._autostart.setChecked(bool(app_cfg.get("launch_at_login", False)))
        self._set_combo_value(self._policy, priv_cfg.get("policy", "warn"))
        self._set_combo_value(self._temp_minutes, priv_cfg.get("temp_minutes", 5))
        self._block_private_key.setChecked(
            bool(priv_cfg.get("block_private_key", True)))
        self._ignored_list.clear()
        for entry in app_identity.normalize_entries(priv_cfg.get("ignored_apps", [])):
            self._append_ignored(entry)
        self._block_signals(False)

    def _collect_overrides(self) -> dict[str, Any]:
        """收集控件当前值 → 配置结构（app.* / history.* / privacy.*）。"""
        return {
            "app": {
                "theme": self._theme.currentData(),
                "font_size": self._font.currentData(),
                "launch_at_login": self._autostart.isChecked(),
            },
            "history": {
                "max_items": self._max_items.currentData(),
                "auto_delete_days": self._auto_delete.currentData(),
                "max_file_size_mb": self._file_size.currentData(),
                "dedupe_scope": self._dedupe_scope.currentData(),
                "save_images": self._save_images.isChecked(),
                "show_image_filename": self._show_filename.isChecked(),
            },
            "privacy": {
                "policy": self._policy.currentData(),
                "temp_minutes": self._temp_minutes.currentData(),
                "ignored_apps": self._ignored_apps(),
                "block_private_key": self._block_private_key.isChecked(),
            },
            "session": {
                "delete_policy": self._delete_policy.currentData(),
            },
        }

    # ---- 隐私操作 ----

    def _ignored_apps(self) -> list[dict[str, str]]:
        """忽略列表（配置格式）：`[{name, bundle_id}]`。

        旧格式（纯字符串）在 `_load_from_config` 里已被归一成同一种形态，
        故这里给出去的永远是映射——匹配逻辑见 `services/app_identity.py`。
        兜底：没有附带条目的列表项（外部直接 addItem 的纯文本）按旧格式
        当作「只有名字」，避免把空条目写进配置文件。
        """
        result: list[dict[str, str]] = []
        for i in range(self._ignored_list.count()):
            item = self._ignored_list.item(i)
            entry = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(entry, dict):
                result.append(entry)
            elif item.text():
                result.append({"name": item.text(), "bundle_id": ""})
        return result

    def _ignored_keys(self) -> set[str]:
        """已在列表里的应用的匹配键（名字/bundle id 归一化），供选择器去重。"""
        return {key for key in (app_identity.entry_key(e) for e in self._ignored_apps())
                if key}

    def _append_ignored(self, entry: dict[str, str]) -> None:
        """列表项显示名字，完整条目（含 bundle id）挂在 UserRole 上。"""
        item = QListWidgetItem(app_identity.display_name(entry))
        item.setData(Qt.ItemDataRole.UserRole, entry)
        if entry.get("bundle_id"):
            item.setToolTip(entry["bundle_id"])
        self._ignored_list.addItem(item)

    def _add_ignored_app(self) -> None:
        """从已安装应用列表选择（不再手动输入，新增.md §9.5）。"""
        from PySide6.QtWidgets import QDialog

        from ui.app_picker_dialog import AppPickerDialog

        dialog = AppPickerDialog(self, selected=self._ignored_keys())
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.selected_entry()
            if entry is None:
                return
            stored = {"name": entry.name, "bundle_id": entry.bundle_id}
            if app_identity.entry_key(stored) in self._ignored_keys():
                return
            self._append_ignored(stored)
            self._on_change("privacy_ignored")

    def _remove_ignored_app(self) -> None:
        row = self._ignored_list.currentRow()
        if row >= 0:
            self._ignored_list.takeItem(row)
            self._on_change("privacy_ignored")

    def _toggle_pause(self) -> None:
        if self._privacy_state is not None:
            self._privacy_state.toggle()

    def _sync_pause_button(self, paused: bool) -> None:
        self._pause_btn.setText("恢复监控" if paused else "暂停监控")

    def _on_change(self, key: str) -> None:
        overrides = self._collect_overrides()
        applier = self._appliers.get(key)
        if applier is not None:
            try:
                applier(overrides)
            except Exception:
                logger.exception("设置项 %s 生效失败", key)
        from app.config import save_user_config

        save_user_config(overrides, path=self._config_path)

    # ---- 工具 ----

    @staticmethod
    def _set_combo_value(combo: FluentComboBox, value) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _block_signals(self, blocked: bool) -> None:
        # 装载配置时必须屏蔽：这些控件一旦发信号就会走 _on_change →
        # 把「刚从配置读出来的值」又写回 settings.yaml。等于打开一次设置页
        # 就把当前默认值钉死成用户配置，以后改 defaults.yaml 再也不生效。
        for w in (self._theme, self._font, self._max_items, self._auto_delete,
                  self._file_size, self._dedupe_scope, self._delete_policy,
                  self._save_images, self._show_filename,
                  self._autostart, self._policy, self._temp_minutes,
                  self._block_private_key):
            w.blockSignals(blocked)
