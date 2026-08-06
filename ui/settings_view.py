"""设置视图：主题/字体/历史数量/图片/自动删除/开机启动。

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
    QLabel,
    QPushButton,
    QWidget,
)

logger = logging.getLogger(__name__)

_THEME_OPTIONS = [("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")]
_FONT_OPTIONS = [12, 13, 14, 15, 16]
_MAX_ITEMS_OPTIONS = [(100, "100"), (500, "500"), (1000, "1000"), (-1, "无限")]
_AUTO_DELETE_OPTIONS = [(7, "7 天"), (30, "30 天"), (90, "90 天"), (-1, "永不")]


class SettingsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._config: dict[str, Any] = {}
        self._appliers: dict[str, Callable] = {}
        self._config_path: Path | None = None
        self._engine = None           # 清理数据弹窗（bootstrap 注入）
        self._build_ui()

    def set_context(self, config: dict, appliers: dict,
                    config_path: Path | None = None,
                    engine=None) -> None:
        """注入当前配置 + 各设置项的生效回调（bootstrap 装配）。"""
        self._config = config
        self._appliers = appliers
        self._config_path = config_path
        self._engine = engine
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

        # 改动即生效
        self._theme.currentIndexChanged.connect(lambda _: self._on_change("theme"))
        self._font.currentIndexChanged.connect(lambda _: self._on_change("font"))
        self._max_items.currentIndexChanged.connect(lambda _: self._on_change("max_items"))
        self._auto_delete.currentIndexChanged.connect(lambda _: self._on_change("auto_delete"))
        self._save_images.toggled.connect(lambda _: self._on_change("save_images"))
        self._show_filename.toggled.connect(lambda _: self._on_change("show_filename"))
        self._autostart.toggled.connect(lambda _: self._on_change("autostart"))

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
        self._block_signals(True)
        self._set_combo_value(self._theme, app_cfg.get("theme", "system"))
        self._set_combo_value(self._font, app_cfg.get("font_size", 14))
        self._set_combo_value(self._max_items, hist_cfg.get("max_items", 500))
        self._set_combo_value(self._auto_delete, hist_cfg.get("auto_delete_days", 30))
        self._save_images.setChecked(bool(hist_cfg.get("save_images", True)))
        self._show_filename.setChecked(bool(hist_cfg.get("show_image_filename", True)))
        self._autostart.setChecked(bool(app_cfg.get("launch_at_login", False)))
        self._block_signals(False)

    def _collect_overrides(self) -> dict[str, Any]:
        """收集控件当前值 → 配置结构（app.* / history.*）。"""
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
        }

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
                  self._save_images, self._show_filename, self._autostart):
            w.blockSignals(blocked)
