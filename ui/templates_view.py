"""模板页（v6 重构，原「片段」/ SnippetsView）：shortcut 触发的本地模板库。

布局：
- 顶部：搜索框 + 新建模板按钮
- 中部：左侧文件夹列表（全部/个人/工作/开发/模板 + 管理）+ 模板列表
- 底部：编辑表单（名称/Shortcut/文件夹/内容/触发方式/启用/收藏 + 保存/删除）

保存时校验：shortcut 唯一（§8）、模板变量合法（§66）、名称/内容非空。
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services.template.errors import TemplateError
from services.template_service import TemplateService

logger = logging.getLogger(__name__)

# 模板列表变量提示（§64 第一阶段）
VARS_HINT = ("可用变量：{{date}} {{time}} {{datetime}} {{uuid}} "
             "{{clipboard}} {{cursor}} {{input:name}}")

# 触发方式（用户明确期望）：tab=按 Tab 展开 / automatic=输完自动展开
_TRIGGER_MODES = [("tab", "Tab 触发"), ("automatic", "自动触发")]

_ALL_FOLDER = -1  # 文件夹列表「全部」虚拟项


class TemplateCreateDialog(QDialog):
    """从历史内容创建模板（§22-24）：内容预填，Name/Shortcut/描述用户确认。

    不自动推导名称/shortcut（§23 建议第二阶段），shortcut 冲突由
    TemplateService 校验（保存时提示）。
    """

    def __init__(self, parent=None, initial_content: str = ""):
        super().__init__(parent)
        self.setWindowTitle("添加到模板")
        self.setModal(True)
        self.setMinimumWidth(360)
        form = QFormLayout(self)
        form.setContentsMargins(20, 16, 20, 16)
        form.setSpacing(10)
        self._name = QLineEdit()
        self._name.setPlaceholderText("如 Email 签名")
        form.addRow("名称", self._name)
        self._shortcut = QLineEdit()
        self._shortcut.setPlaceholderText("如 email（触发词）")
        form.addRow("Shortcut", self._shortcut)
        self._desc = QLineEdit()
        self._desc.setPlaceholderText("描述（可选）")
        form.addRow("描述", self._desc)
        self._content = QPlainTextEdit()
        self._content.setPlainText(initial_content)
        self._content.setFixedHeight(120)
        form.addRow("内容", self._content)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("创建")
        ok.setObjectName("primaryButton")
        ok.clicked.connect(self._accept_if_valid)
        buttons.addWidget(ok)
        form.addRow(buttons)
        self._shortcut.returnPressed.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self._name.text().strip() and self._shortcut.text().strip():
            self.accept()

    def name(self) -> str:
        return self._name.text().strip()

    def shortcut(self) -> str:
        return self._shortcut.text().strip()

    def description(self) -> str:
        return self._desc.text().strip()

    def content(self) -> str:
        return self._content.toPlainText()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)


class TemplatesView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._svc: TemplateService | None = None
        self._templates: list[dict] = []
        self._folders: list[dict] = []
        self._active_menus: list = []  # 右键菜单引用防 GC
        self._build_ui()

    # ---- 注入 ----

    def set_context(self, engine) -> None:
        """注入数据库引擎（bootstrap 装配），打开页面时自动刷新。"""
        self._svc = TemplateService(engine)
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._svc is not None:
            self.reload()

    # ---- 构建 ----

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        # 顶边距必须为 0——主窗口内容区已自带 5px（main_window right 布局），
        # 页面再加任何值都会叠加（实测：设 2 后间距 8 > 历史页搜索框的 6）
        outer.setContentsMargins(10, 0, 10, 10)
        outer.setSpacing(8)

        # 顶部：搜索 + 新建
        top = QHBoxLayout()
        top.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索模板（名称 / Shortcut / 内容）")
        self._search.textChanged.connect(self._on_search)
        top.addWidget(self._search, 1)
        new_btn = QPushButton("新建模板")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_template)
        top.addWidget(new_btn)
        outer.addLayout(top)

        # 中部：左侧类型列（常驻）+ 模板列表
        middle = QHBoxLayout()
        middle.setSpacing(6)
        left = QVBoxLayout()
        left.setSpacing(4)
        type_title = QLabel("类型")
        type_title.setObjectName("placeholder")
        left.addWidget(type_title)
        self._folder_list = QListWidget()
        self._folder_list.setObjectName("sideList")
        self._folder_list.currentRowChanged.connect(self._on_folder_select)
        self._folder_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._folder_list.customContextMenuRequested.connect(
            self._folder_context_menu)
        left.addWidget(self._folder_list, 1)
        add_folder_btn = QPushButton("＋ 新建类型")
        add_folder_btn.setObjectName("secondaryButton")
        add_folder_btn.clicked.connect(self._add_folder)
        left.addWidget(add_folder_btn)
        middle.addLayout(left, 1)

        self._list = QListWidget()
        self._list.setObjectName("sideList")
        self._list.currentRowChanged.connect(self._on_select)
        # 模板右键：收藏 / 移动到类型 / 删除（§15/§21）
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(
            self._template_context_menu)
        middle.addWidget(self._list, 2)
        outer.addLayout(middle, 3)

        # 底部：编辑表单（用户反馈：名称/Shortcut 等高一行、类型/触发方式
        # 等高一行；文本框宽度受控，初始 380px 内不溢出）
        form = QVBoxLayout()
        form.setSpacing(6)
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        name_label = QLabel("名称：")
        row1.addWidget(name_label)
        self._name = QLineEdit()
        self._name.setPlaceholderText("如 Email 签名")
        row1.addWidget(self._name, 3)
        sc_label = QLabel("Shortcut：")
        row1.addWidget(sc_label)
        self._shortcut = QLineEdit()
        self._shortcut.setPlaceholderText("如 email")
        row1.addWidget(self._shortcut, 2)
        form.addLayout(row1)
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        type_label = QLabel("类型：")
        row2.addWidget(type_label)
        self._folder_combo = QComboBox()
        self._folder_combo.addItem("未分类", None)
        row2.addWidget(self._folder_combo, 1)
        trig_label = QLabel("触发方式：")
        row2.addWidget(trig_label)
        self._trigger_combo = QComboBox()
        for value, label in _TRIGGER_MODES:
            self._trigger_combo.addItem(label, value)
        row2.addWidget(self._trigger_combo, 1)
        form.addLayout(row2)
        hint = QLabel(VARS_HINT)
        hint.setObjectName("placeholder")
        hint.setWordWrap(True)
        form.addWidget(hint)
        self._content = QPlainTextEdit()
        self._content.setPlaceholderText("模板内容…")
        form.addWidget(self._content, 1)

        row3 = QHBoxLayout()
        row3.setSpacing(10)
        self._enabled = QCheckBox("启用")
        self._enabled.setChecked(True)
        row3.addWidget(self._enabled)
        row3.addStretch(1)
        form.addLayout(row3)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._save_btn = QPushButton("保存")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.clicked.connect(self._save)
        buttons.addWidget(self._save_btn)
        self._delete_btn = QPushButton("删除")
        self._delete_btn.clicked.connect(self._delete_selected)
        buttons.addWidget(self._delete_btn)
        form.addLayout(buttons)
        outer.addLayout(form, 2)

    # ---- 数据 ----

    def reload(self) -> None:
        """重载文件夹 + 模板列表（保留选择）。"""
        if self._svc is None:
            return
        self._reload_folders()
        self._reload_templates()

    def _reload_folders(self) -> None:
        current = self._current_folder_id()
        self._folders = self._svc.list_folders()
        self._folder_list.blockSignals(True)
        self._folder_list.clear()
        self._folder_list.addItem(QListWidgetItem("全部"))
        for f in self._folders:
            item = QListWidgetItem(f"{f['name']} ({f['count']})")
            item.setData(Qt.ItemDataRole.UserRole, f["id"])
            self._folder_list.addItem(item)
        self._folder_list.blockSignals(False)
        idx = next((i for i, f in enumerate(self._folders)
                    if f["id"] == current), -1)
        self._folder_list.setCurrentRow(idx + 1 if idx >= 0 else 0)

        # 表单的文件夹下拉同步
        self._folder_combo.blockSignals(True)
        current_fid = self._folder_combo.currentData()
        self._folder_combo.clear()
        self._folder_combo.addItem("未分类", None)
        for f in self._folders:
            self._folder_combo.addItem(f["name"], f["id"])
        idx = self._folder_combo.findData(current_fid)
        self._folder_combo.setCurrentIndex(max(0, idx))
        self._folder_combo.blockSignals(False)

    def _reload_templates(self, preserve_id: int = 0) -> None:
        folder_id = self._current_folder_id()
        if self._search.text().strip():
            self._templates = self._svc.search_templates(self._search.text())
        else:
            self._templates = self._svc.list_templates(folder_id=folder_id)
        if not preserve_id:
            preserve_id = self._current_id()
        self._list.blockSignals(True)
        self._list.clear()
        for t in self._templates:
            star = "★ " if t["favorite"] else ""
            state = "" if t["enabled"] else "（已禁用）"
            item = QListWidgetItem(f"{star}{t['name']}  [{t['shortcut']}]{state}")
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._templates:
            idx = next((i for i, t in enumerate(self._templates)
                        if t["id"] == preserve_id), 0)
            self._list.setCurrentRow(idx)
        else:
            self._clear_form()

    def _current_folder_id(self):
        row = self._folder_list.currentRow()
        if row <= 0:
            return None  # 「全部」或未选中
        item = self._folder_list.item(row)
        return item.data(Qt.ItemDataRole.UserRole)

    def _current_id(self) -> int:
        row = self._list.currentRow()
        if 0 <= row < len(self._templates):
            return self._templates[row]["id"]
        return 0

    # ---- 选择 ----

    def _on_folder_select(self, row: int) -> None:
        self._reload_templates()

    def _on_search(self, text: str) -> None:
        self._reload_templates()

    def _on_select(self, row: int) -> None:
        if 0 <= row < len(self._templates):
            t = self._templates[row]
            self._name.setText(t["name"])
            self._shortcut.setText(t["shortcut"])
            idx = self._folder_combo.findData(t["folder_id"])
            self._folder_combo.setCurrentIndex(max(0, idx))
            ti = self._trigger_combo.findData(t["trigger_mode"])
            self._trigger_combo.setCurrentIndex(max(0, ti))
            self._content.setPlainText(t["content"])
            self._enabled.setChecked(t["enabled"])

    def _clear_form(self) -> None:
        self._name.clear()
        self._shortcut.clear()
        self._folder_combo.setCurrentIndex(0)
        self._trigger_combo.setCurrentIndex(0)
        self._content.clear()
        self._enabled.setChecked(True)

    # ---- 操作 ----

    def _new_template(self) -> None:
        self._list.setCurrentRow(-1)
        self._clear_form()
        self._name.setFocus()

    def _save(self) -> None:
        if self._svc is None:
            return
        name = self._name.text().strip()
        shortcut = self._shortcut.text().strip()
        content = self._content.toPlainText()
        if not name or not shortcut or not content:
            self._warn("名称、Shortcut 与内容必填")
            return
        try:
            t_id = self._current_id()
            if t_id:
                self._svc.update_template(
                    t_id, name=name, shortcut=shortcut, content=content,
                    folder_id=self._folder_combo.currentData(),
                    trigger_mode=self._trigger_combo.currentData())
            else:
                self._svc.create_template(
                    name, shortcut, content,
                    folder_id=self._folder_combo.currentData(),
                    trigger_mode=self._trigger_combo.currentData())
        except ValueError as e:
            self._warn(str(e))  # §8：shortcut 冲突不静默覆盖
            return
        except TemplateError as e:
            self._warn(str(e))  # §66：模板变量非法
            return
        # 启用状态单独更新（保存后；收藏走右键菜单）
        if t_id:
            current = self._svc.get_template(t_id)
            if current["enabled"] != self._enabled.isChecked():
                self._svc.toggle_enabled(t_id)
        logger.info("模板已保存: %s [%s]", name, shortcut)
        self.reload()

    # ---- 模板右键菜单 ----

    def _template_context_menu(self, pos) -> None:
        """模板列表右键：收藏/取消收藏 · 移动到类型 · 复制 · 删除。"""
        item = self._list.itemAt(pos)
        row = self._list.row(item) if item is not None else -1
        if row < 0 or row >= len(self._templates):
            return
        t = self._templates[row]
        self._list.setCurrentRow(row)
        menu = QMenu(self)
        self._active_menus.append(menu)
        fav_label = "取消收藏" if t["favorite"] else "收藏"
        menu.addAction(fav_label).triggered.connect(
            lambda: self._toggle_favorite(t))
        move_menu = menu.addMenu("移动到类型")
        self._active_menus.append(move_menu)
        for f in self._folders:
            checked = "✓ " if f["id"] == t["folder_id"] else ""
            move_menu.addAction(f"{checked}{f['name']}").triggered.connect(
                lambda _=False, fid=f["id"]: self._move_template(t, fid))
        menu.addSeparator()
        menu.addAction("删除…").triggered.connect(lambda: self._delete_template(t))
        menu.exec(self._list.viewport().mapToGlobal(pos))

    def _toggle_favorite(self, t: dict) -> None:
        if self._svc is None:
            return
        self._svc.toggle_favorite(t["id"])
        logger.info("模板收藏切换: id=%s", t["id"])
        self._reload_templates(preserve_id=t["id"])

    def _move_template(self, t: dict, folder_id) -> None:
        if self._svc is None:
            return
        self._svc.update_template(t["id"], folder_id=folder_id)
        logger.info("模板移动: id=%s → folder=%s", t["id"], folder_id)
        self._reload_templates(preserve_id=t["id"])

    def _delete_selected(self) -> None:
        """表单「删除」按钮：删除当前选中模板。"""
        t_id = self._current_id()
        if not t_id:
            return
        t = next((x for x in self._templates if x["id"] == t_id), None)
        if t is not None:
            self._delete_template(t)

    def _delete_template(self, t: dict) -> None:
        if self._svc is None:
            return
        from ui.dialogs import ConfirmDialog

        dlg = ConfirmDialog(self, f"删除模板「{t['name']}」？",
                            "删除后不可恢复", "删除")
        if dlg.exec():
            self._svc.delete_template(t["id"])
            logger.info("模板已删除: id=%s", t["id"])
            self.reload()

    # ---- 文件夹管理 ----

    def _folder_context_menu(self, pos) -> None:
        """文件夹列表右键：新建 / 重命名 / 删除。"""
        menu = QMenu(self)
        self._active_menus.append(menu)
        menu.addAction("新建类型…").triggered.connect(self._add_folder)
        menu.addSeparator()
        item = self._folder_list.itemAt(pos)
        row = self._folder_list.row(item) if item is not None else -1
        if row > 0:  # 非「全部」项
            menu.addAction("重命名类型…").triggered.connect(self._rename_folder)
            menu.addAction("删除类型…").triggered.connect(
                self._delete_folder)
        else:
            menu.addAction("重命名类型").setEnabled(False)
            menu.addAction("删除类型").setEnabled(False)
        menu.exec(self._folder_list.viewport().mapToGlobal(pos))

    def _add_folder(self) -> None:
        if self._svc is None:
            return
        from ui.dialogs import NameDialog

        dlg = NameDialog("新建类型", "类型名称：", confirm_text="创建",
                         parent=self)
        if dlg.exec() and dlg.text().strip():
            try:
                self._svc.create_folder(dlg.text().strip())
            except Exception:
                self._warn("文件夹已存在")
                return
            self.reload()

    def _rename_folder(self) -> None:
        if self._svc is None:
            return
        fid = self._current_folder_id()
        if fid is None:
            self._warn("请先选择要重命名的文件夹")
            return
        name = next(f["name"] for f in self._folders if f["id"] == fid)
        from ui.dialogs import NameDialog

        dlg = NameDialog("重命名类型", "类型名称：", initial=name,
                         confirm_text="保存", parent=self)
        if dlg.exec() and dlg.text().strip():
            self._svc.rename_folder(fid, dlg.text().strip())
            self.reload()

    def _delete_folder(self) -> None:
        if self._svc is None:
            return
        fid = self._current_folder_id()
        if fid is None:
            self._warn("请先选择要删除的文件夹")
            return
        name = next(f["name"] for f in self._folders if f["id"] == fid)
        from ui.dialogs import ConfirmDialog

        dlg = ConfirmDialog(self, f"删除类型「{name}」？",
                            "其中的模板将移入未分类（§14 默认策略）", "删除")
        if dlg.exec():
            self._svc.delete_folder(fid)
            self.reload()

    @staticmethod
    def _warn(message: str) -> None:
        QMessageBox.warning(None, "模板", message)
