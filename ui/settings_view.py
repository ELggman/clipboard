"""设置视图：主题/字体/历史数量/图片/自动删除/开机启动/隐私模式。

改动即生效：控件变化 → 调用对应 applier（bootstrap 注入，如主题重应用、
字号刷新）+ 合并写回 settings.yaml（save_user_config）。
"""
import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_THEME_OPTIONS = [("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")]
_FONT_OPTIONS = [12, 13, 14, 15, 16]
_MAX_ITEMS_OPTIONS = [(100, "100"), (500, "500"), (1000, "1000"), (-1, "无限")]
# §9.10：Never / 1 / 7 / 30 / 90 / 365 天
_AUTO_DELETE_OPTIONS = [(1, "1 天"), (7, "7 天"), (30, "30 天"),
                        (90, "90 天"), (365, "365 天"), (-1, "永不")]
# 敏感内容策略（§9.17）：warn 默认
_POLICY_OPTIONS = [("warn", "提醒（保存并遮蔽显示）"),
                   ("ignore", "忽略（不保存）"),
                   ("save_temporarily", "临时保存（自动过期）")]
_TEMP_OPTIONS = [(1, "1 分钟"), (5, "5 分钟"), (10, "10 分钟"), (30, "30 分钟")]


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
        layout = QFormLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(16)
        layout.setVerticalSpacing(10)

        self._theme = QComboBox()
        for value, label in _THEME_OPTIONS:
            self._theme.addItem(label, value)
        layout.addRow("主题", self._theme)

        self._font = QComboBox()
        for size in _FONT_OPTIONS:
            self._font.addItem(f"{size} pt", size)
        layout.addRow("字体大小", self._font)

        self._max_items = QComboBox()
        for value, label in _MAX_ITEMS_OPTIONS:
            self._max_items.addItem(label, value)
        layout.addRow("历史数量上限", self._max_items)

        self._auto_delete = QComboBox()
        for value, label in _AUTO_DELETE_OPTIONS:
            self._auto_delete.addItem(label, value)
        layout.addRow("自动删除", self._auto_delete)

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

        self._policy = QComboBox()
        for value, label in _POLICY_OPTIONS:
            self._policy.addItem(label, value)
        layout.addRow("敏感内容策略", self._policy)

        self._temp_minutes = QComboBox()
        for value, label in _TEMP_OPTIONS:
            self._temp_minutes.addItem(label, value)
        layout.addRow("临时保存时长", self._temp_minutes)

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
        self._save_images.setChecked(bool(hist_cfg.get("save_images", True)))
        self._show_filename.setChecked(bool(hist_cfg.get("show_image_filename", True)))
        self._autostart.setChecked(bool(app_cfg.get("launch_at_login", False)))
        self._set_combo_value(self._policy, priv_cfg.get("policy", "warn"))
        self._set_combo_value(self._temp_minutes, priv_cfg.get("temp_minutes", 5))
        self._ignored_list.clear()
        for app_name in priv_cfg.get("ignored_apps", []):
            self._ignored_list.addItem(QListWidgetItem(app_name))
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
                "save_images": self._save_images.isChecked(),
                "show_image_filename": self._show_filename.isChecked(),
            },
            "privacy": {
                "policy": self._policy.currentData(),
                "temp_minutes": self._temp_minutes.currentData(),
                "ignored_apps": self._ignored_apps(),
            },
        }

    # ---- 隐私操作 ----

    def _ignored_apps(self) -> list[str]:
        return [self._ignored_list.item(i).text()
                for i in range(self._ignored_list.count())]

    def _add_ignored_app(self) -> None:
        from PySide6.QtWidgets import QDialog

        from ui.dialogs import NameDialog

        dialog = NameDialog("添加忽略的应用", "应用名称：",
                            placeholder="如：1Password / Bitwarden",
                            confirm_text="添加")
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.text():
            name = dialog.text()
            if name not in self._ignored_apps():
                self._ignored_list.addItem(QListWidgetItem(name))
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
    def _set_combo_value(combo: QComboBox, value) -> None:
        idx = combo.findData(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _block_signals(self, blocked: bool) -> None:
        for w in (self._theme, self._font, self._max_items, self._auto_delete,
                  self._save_images, self._show_filename, self._autostart,
                  self._policy, self._temp_minutes):
            w.blockSignals(blocked)
