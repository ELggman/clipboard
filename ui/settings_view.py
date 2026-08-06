"""设置视图：主题/字体/历史数量/图片/自动删除/开机启动。

改动即生效：控件变化 → 调用对应 applier（bootstrap 注入，如主题重应用、
字号刷新）+ 合并写回 settings.yaml（save_user_config）。
"""
import logging
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
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

from ui.dialogs import ConfirmDialog

logger = logging.getLogger(__name__)

_THEME_OPTIONS = [("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")]
_FONT_OPTIONS = [12, 13, 14, 15, 16]
_MAX_ITEMS_OPTIONS = [(100, "100"), (500, "500"), (1000, "1000"), (-1, "无限")]
_AUTO_DELETE_OPTIONS = [(7, "7 天"), (30, "30 天"), (90, "90 天"), (-1, "永不")]
# 清理数据：时间筛选条件（days, 文案）
_CLEAN_OPTIONS = [(7, "7 天以前"), (30, "30 天以前"), (90, "90 天以前"), (0, "全部历史")]


class SettingsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._config: dict[str, Any] = {}
        self._appliers: dict[str, Callable] = {}
        self._config_path: Path | None = None
        self._engine = None           # 清理数据（bootstrap 注入）
        self._clean_items: list = []  # 当前筛选结果
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

        # 清理数据（不影响收藏夹——收藏内容为独立快照）
        layout.addRow(QLabel("清理数据"))
        clean = QWidget()
        clean_layout = QVBoxLayout(clean)
        clean_layout.setContentsMargins(0, 0, 0, 0)
        clean_layout.setSpacing(6)
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self._clean_days = QComboBox()
        for value, label in _CLEAN_OPTIONS:
            self._clean_days.addItem(label, value)
        filter_row.addWidget(self._clean_days)
        query_btn = QPushButton("查询")
        query_btn.setObjectName("secondaryButton")
        query_btn.clicked.connect(self._clean_query)
        filter_row.addWidget(query_btn)
        filter_row.addStretch(1)
        clean_layout.addLayout(filter_row)
        self._clean_list = QListWidget()
        self._clean_list.setFixedHeight(140)
        clean_layout.addWidget(self._clean_list)
        clean_buttons = QHBoxLayout()
        clean_buttons.addStretch(1)
        del_selected = QPushButton("删除选中")
        del_selected.setObjectName("destructiveButton")
        del_selected.clicked.connect(self._clean_delete_selected)
        clean_buttons.addWidget(del_selected)
        del_all = QPushButton("删除全部匹配")
        del_all.setObjectName("destructiveButton")
        del_all.clicked.connect(self._clean_delete_all)
        clean_buttons.addWidget(del_all)
        clean_layout.addLayout(clean_buttons)
        note = QLabel("删除历史不影响收藏夹内容；收藏快照仅在收藏夹内管理。")
        note.setObjectName("placeholder")
        clean_layout.addWidget(note)
        layout.addRow(clean)

        # 改动即生效
        self._theme.currentIndexChanged.connect(lambda _: self._on_change("theme"))
        self._font.currentIndexChanged.connect(lambda _: self._on_change("font"))
        self._max_items.currentIndexChanged.connect(lambda _: self._on_change("max_items"))
        self._auto_delete.currentIndexChanged.connect(lambda _: self._on_change("auto_delete"))
        self._save_images.toggled.connect(lambda _: self._on_change("save_images"))
        self._show_filename.toggled.connect(lambda _: self._on_change("show_filename"))
        self._autostart.toggled.connect(lambda _: self._on_change("autostart"))

    # ---- 清理数据 ----

    def _clean_query(self) -> None:
        """按时间条件查询匹配条目（可勾选，默认全选）。"""
        if self._engine is None:
            return
        from services import history_service

        days = self._clean_days.currentData()
        self._clean_items = history_service.list_older_than(self._engine, days)
        self._clean_list.clear()
        for item in self._clean_items:
            row = QListWidgetItem(
                f"{item.created_at} · {item.type}  {item.display_text(max_len=60)}")
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)  # 默认全选
            self._clean_list.addItem(row)
        logger.info("清理数据查询: %d 条匹配", len(self._clean_items))

    def _clean_delete_selected(self) -> None:
        """删除勾选条目（红色确认）。"""
        ids = [self._clean_items[i].id
               for i in range(self._clean_list.count())
               if self._clean_list.item(i).checkState() == Qt.CheckState.Checked]
        self._clean_delete(ids)

    def _clean_delete_all(self) -> None:
        """删除全部匹配条目（红色确认）。"""
        self._clean_delete([item.id for item in self._clean_items])

    def _clean_delete(self, ids: list[int]) -> None:
        if self._engine is None or not ids:
            return
        from services import history_service

        dialog = ConfirmDialog(
            "清理数据",
            f"将删除 {len(ids)} 条历史记录（图片文件同步清理），"
            "不影响收藏夹内容。确定继续？",
            confirm_text="删除")
        if dialog.exec() != ConfirmDialog.DialogCode.Accepted:
            return
        files = history_service.delete_items(self._engine, ids)
        from services.image_service import ImageService

        svc = ImageService(Path(__file__).resolve().parent.parent / "images")
        for path in files:
            svc.delete(path)
        logger.info("清理数据完成: %d 条（图片 %d 个）", len(ids), len(files))
        self._clean_query()  # 刷新预览

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
