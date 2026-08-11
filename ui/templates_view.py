"""模板页（v6 重构，原「片段」/ SnippetsView）：shortcut 触发的本地模板库。

布局（两栏卡片 + 编辑弹窗，macOS Sonoma/Raycast 风格，设计规范）：
- 左栏：分类导航（Finder source-list，计数右对齐，＋ 新建类型）
- 中栏：模板列表（搜索 + 两行卡片行：名称+★ / shortcut 钥匙片+触发方式，
  ★ 点击区切换收藏；点击行 → 编辑弹窗）
- 编辑弹窗 TemplateEditorDialog（不常驻）：名称/Shortcut/分类/触发方式
  分段控件/变量 Tag（预设+自定义，折叠+新增）/Pygments 高亮代码编辑器

保存时校验：shortcut 唯一（§8）、模板变量合法（§66）、名称/内容非空。
"""
import logging

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from services.template.errors import TemplateError
from services.template_service import TemplateService
from ui.template_components import (
    ROLE_FOLDER_COUNT,
    ROLE_FOLDER_NAME,
    ROLE_TEMPLATE,
    STAR_ZONE,
    FolderSourceDelegate,
    TemplateCardDelegate,
    TemplateHighlighter,
    VariableTagBar,
)

# 用户自定义变量持久化键（config template 段）
_CONFIG_VARS_KEY = "template"
_CONFIG_VARS_FIELD = "extra_variables"


def _load_extra_variables() -> list[str]:
    """用户自定义变量（config template.extra_variables）。"""
    try:
        from app.config import load_config

        config = load_config()
        return list(config.get("template", {}).get("extra_variables", []))
    except Exception:
        return []


def _save_extra_variables(vars_list: list[str]) -> None:
    """持久化用户自定义变量。"""
    try:
        from app.config import save_user_config

        save_user_config({_CONFIG_VARS_KEY: {_CONFIG_VARS_FIELD: vars_list}})
    except Exception:
        logger.exception("保存自定义变量失败")

logger = logging.getLogger(__name__)

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


class TemplateEditorDialog(QDialog):
    """编辑模板弹窗（设计决策：不常驻——点击模板/新建模板时弹出）。

    字段：名称 / Shortcut / 分类 / 触发方式（分段控件）/ 变量 Tag 条
    （预设 + 用户自定义，超量折叠 + 新增按钮）/ 内容（Pygments + {{变量}}
    高亮）/ 启用 + 删除·保存·取消。保存/删除成功后 accept()（父页面重载）。
    """

    def __init__(self, parent=None, svc=None, template=None):
        super().__init__(parent)
        self._svc = svc
        self._template = template          # dict | None（None = 新建）
        is_new = template is None
        self.setWindowTitle("新建模板" if is_new else "编辑模板")
        self.setModal(True)
        # 400 窄 + 高（设计反馈：面板高度要高一点）
        self.setMinimumWidth(400)
        self.setMinimumHeight(560)
        self._build_form()
        if template is not None:
            self._load(template)
        self._schedule_highlight()

    # ---- 构建 ----

    def _build_form(self) -> None:
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(20, 18, 20, 16)
        vbox.setSpacing(12)
        title = QLabel("新建模板" if self._template is None else "编辑模板")
        title.setObjectName("cardTitle")
        vbox.addWidget(title)

        # 名称 / Shortcut
        row1 = QHBoxLayout()
        row1.setSpacing(8)
        l1 = QLabel("名称")
        l1.setObjectName("fieldLabel")
        row1.addWidget(l1)
        self._name = QLineEdit()
        self._name.setPlaceholderText("如 Email 签名")
        row1.addWidget(self._name, 1)
        l2 = QLabel("Shortcut")
        l2.setObjectName("fieldLabel")
        row1.addWidget(l2)
        self._shortcut = QLineEdit()
        self._shortcut.setPlaceholderText("如 email")
        row1.addWidget(self._shortcut, 1)
        vbox.addLayout(row1)

        # 分类 / 触发方式（分段控件）
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        l3 = QLabel("分类")
        l3.setObjectName("fieldLabel")
        row2.addWidget(l3)
        self._folder_combo = QComboBox()
        self._folder_combo.addItem("未分类", None)
        if self._svc is not None:
            for f in self._svc.list_folders():
                self._folder_combo.addItem(f["name"], f["id"])
        row2.addWidget(self._folder_combo, 1)
        l4 = QLabel("触发")
        l4.setObjectName("fieldLabel")
        row2.addWidget(l4)
        seg = QFrame()
        seg.setObjectName("segGroup")
        sh = QHBoxLayout(seg)
        sh.setContentsMargins(3, 3, 3, 3)
        sh.setSpacing(2)
        self._trigger_tab = QPushButton("Tab 触发")
        self._trigger_auto = QPushButton("自动触发")
        self._trigger_group = QButtonGroup(self)
        for btn in (self._trigger_tab, self._trigger_auto):
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._trigger_group.addButton(btn)
            sh.addWidget(btn)
        self._trigger_tab.setChecked(True)
        row2.addWidget(seg)
        vbox.addLayout(row2)

        # 变量区：左侧胶囊（折叠/展开）+ 右侧独立两按钮（展开、新增），
        # 按钮不挤占变量显示区（设计反馈）；标注在胶囊上方
        l5 = QLabel("变量")
        l5.setObjectName("fieldLabel")
        vbox.addWidget(l5)
        vrow = QHBoxLayout()
        vrow.setSpacing(8)
        variables = list(VariableTagBar.DEFAULT_VARIABLES)
        variables += _load_extra_variables()
        self._var_tags = VariableTagBar(variables=variables)
        self._var_tags.variable_clicked.connect(self._insert_variable)
        self._var_tags.remove_requested.connect(self._remove_variable)
        # 变量区滚动：展开多行时固定高度内滚动（设计反馈：展开显示不完全）
        self._var_scroll = QScrollArea()
        self._var_scroll.setObjectName("varScroll")
        self._var_scroll.setWidgetResizable(True)
        self._var_scroll.setFixedHeight(72)
        self._var_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._var_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._var_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._var_scroll.setWidget(self._var_tags)
        vrow.addWidget(self._var_scroll, 1)
        var_col = QVBoxLayout()
        var_col.setSpacing(6)
        n_vars = len(self._var_tags.variables())
        self._more_btn = QPushButton(f"展开全部（{n_vars}）")
        self._more_btn.setObjectName("ghostBtn")
        self._more_btn.setVisible(self._var_tags.needs_collapse())
        self._more_btn.clicked.connect(self._toggle_vars)
        var_col.addWidget(self._more_btn)
        self._add_btn = QPushButton("＋ 新增")
        self._add_btn.setObjectName("ghostBtn")
        self._add_btn.setToolTip("新增自定义变量")
        self._add_btn.clicked.connect(self._add_variable)
        var_col.addWidget(self._add_btn)
        vrow.addLayout(var_col)
        vbox.addLayout(vrow)

        # 内容（Pygments + {{变量}} 高亮）
        self._content = QPlainTextEdit()
        self._content.setObjectName("templateEditor")
        self._content.setPlaceholderText("模板内容…（{{date}} 等变量自动高亮）")
        self._content.textChanged.connect(self._schedule_highlight)
        vbox.addWidget(self._content, 1)

        # 启用 + 删除 / 保存 / 取消
        row3 = QHBoxLayout()
        row3.setSpacing(10)
        self._enabled = QCheckBox("启用")
        self._enabled.setChecked(True)
        row3.addWidget(self._enabled)
        row3.addStretch(1)
        self._delete_btn = QPushButton("删除")
        self._delete_btn.setObjectName("dangerBtn")
        self._delete_btn.setEnabled(self._template is not None)
        self._delete_btn.clicked.connect(self._delete)
        row3.addWidget(self._delete_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        row3.addWidget(cancel_btn)
        self._save_btn = QPushButton("保存")
        self._save_btn.setObjectName("primaryButton")
        self._save_btn.clicked.connect(self._save)
        row3.addWidget(self._save_btn)
        vbox.addLayout(row3)

        # 代码高亮语言检测防抖
        self._highlighter: TemplateHighlighter | None = None
        self._hl_timer = QTimer(self)
        self._hl_timer.setSingleShot(True)
        self._hl_timer.setInterval(400)
        self._hl_timer.timeout.connect(self._update_highlighter)

    def _load(self, t: dict) -> None:
        self._name.setText(t["name"])
        self._shortcut.setText(t["shortcut"])
        idx = self._folder_combo.findData(t["folder_id"])
        self._folder_combo.setCurrentIndex(max(0, idx))
        self._trigger_tab.setChecked(t["trigger_mode"] != "automatic")
        self._trigger_auto.setChecked(t["trigger_mode"] == "automatic")
        self._content.setPlainText(t["content"])
        self._enabled.setChecked(t["enabled"])

    # ---- 交互 ----

    def _insert_variable(self, var: str) -> None:
        """变量胶囊点击：插入内容区光标处。"""
        self._content.insertPlainText(var)
        self._content.setFocus()

    def _add_variable(self) -> None:
        """「＋ 新增」：输入变量名 → 持久化 → 追加胶囊（新胶囊按序排在
        已有胶囊之后、右列按钮之前——胶囊区与按钮区分离）。"""
        from ui.dialogs import NameDialog

        dlg = NameDialog("新增变量", "变量名（如 myvar 或 {{myvar}}）：",
                         placeholder="myvar", confirm_text="添加", parent=self)
        if not dlg.exec():
            return
        raw = dlg.text().strip()
        if not raw:
            return
        var = raw if raw.startswith("{{") else f"{{{{{raw}}}}}"
        if var in self._var_tags.variables():
            self._warn("变量已存在")
            return
        current = _load_extra_variables()
        current.append(var)
        _save_extra_variables(current)
        self._var_tags.add_variable(var)
        self._sync_var_buttons()

    def _remove_variable(self, var: str) -> None:
        """右键变量胶囊删除：仅用户自定义变量（预设不可删）。"""
        extras = _load_extra_variables()
        if var not in extras:
            self._warn(f"预设变量「{var}」不可删除")
            return
        extras.remove(var)
        _save_extra_variables(extras)
        self._var_tags.remove_variable(var)
        self._sync_var_buttons()

    def _toggle_vars(self) -> None:
        """「展开全部（N）/收起」切换胶囊展开状态。"""
        self._var_tags.set_expanded(not self._var_tags.is_expanded())
        self._sync_var_buttons()

    def _sync_var_buttons(self) -> None:
        """同步右侧按钮：展开文本（含数量）/ 可见性（超出阈值才显示）。"""
        n = len(self._var_tags.variables())
        self._more_btn.setText(
            "收起" if self._var_tags.is_expanded() else f"展开全部（{n}）")
        self._more_btn.setVisible(self._var_tags.needs_collapse())

    def _schedule_highlight(self) -> None:
        self._hl_timer.start()

    def _update_highlighter(self) -> None:
        """检测内容语言 → 重建 TemplateHighlighter（Pygments + {{变量}}）。"""
        content = self._content.toPlainText()
        language = ""
        if content.strip():
            try:
                from services.code_detector import detect as detect_lang

                result = detect_lang(content)
                language = result.language if result else ""
            except Exception:
                language = ""
        self._highlighter = TemplateHighlighter(
            self._content.document(), language)

    # ---- 保存 / 删除 ----

    def _save(self) -> None:
        if self._svc is None:
            return
        name = self._name.text().strip()
        shortcut = self._shortcut.text().strip()
        content = self._content.toPlainText()
        if not name or not shortcut or not content:
            self._warn("名称、Shortcut 与内容必填")
            return
        trigger_mode = ("tab" if self._trigger_tab.isChecked()
                        else "automatic")
        try:
            if self._template is not None:
                self._svc.update_template(
                    self._template["id"], name=name, shortcut=shortcut,
                    content=content,
                    folder_id=self._folder_combo.currentData(),
                    trigger_mode=trigger_mode)
            else:
                self._svc.create_template(
                    name, shortcut, content,
                    folder_id=self._folder_combo.currentData(),
                    trigger_mode=trigger_mode)
        except ValueError as e:
            self._warn(str(e))  # §8：shortcut 冲突不静默覆盖
            return
        except TemplateError as e:
            self._warn(str(e))  # §66：模板变量非法
            return
        if self._template is not None:
            current = self._svc.get_template(self._template["id"])
            if current["enabled"] != self._enabled.isChecked():
                self._svc.toggle_enabled(self._template["id"])
        logger.info("模板已保存: %s [%s]", name, shortcut)
        self.accept()

    def _delete(self) -> None:
        if self._template is None:
            return
        from ui.dialogs import ConfirmDialog

        dlg = ConfirmDialog(self, f"删除模板「{self._template['name']}」？",
                            "删除后不可恢复", "删除")
        if dlg.exec():
            self._svc.delete_template(self._template["id"])
            logger.info("模板已删除: id=%s", self._template["id"])
            self.accept()

    @staticmethod
    def _warn(message: str) -> None:
        QMessageBox.warning(None, "模板", message)


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
        """三栏卡片布局（设计规范：白色卡片 16px 圆角、大量留白、蓝色强调）。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 12, 12)
        outer.setSpacing(12)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        # ---- 左栏：分类导航（source-list，计数右对齐）----
        left = QFrame()
        left.setObjectName("templateCard")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 12, 12)
        lv.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(6)
        ltitle = QLabel("分类")
        ltitle.setObjectName("cardTitle")
        head.addWidget(ltitle)
        head.addStretch(1)
        self._new_folder_btn = QPushButton("＋ 新建类型")
        self._new_folder_btn.setObjectName("ghostBtn")
        # 按钮必须有文字（回归：纯符号按钮不可识别）
        self._new_folder_btn.clicked.connect(self._add_folder)
        head.addWidget(self._new_folder_btn)
        lv.addLayout(head)
        self._folder_list = QListWidget()
        self._folder_list.setObjectName("sourceList")
        self._folder_list.setFrameShape(QListWidget.Shape.NoFrame)
        self._folder_list.setSpacing(1)
        self._folder_list.setItemDelegate(FolderSourceDelegate(self._folder_list))
        self._folder_list.currentRowChanged.connect(self._on_folder_select)
        self._folder_list.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._folder_list.customContextMenuRequested.connect(
            self._folder_context_menu)
        lv.addWidget(self._folder_list, 1)
        left.setFixedWidth(160)  # 分类列固定宽（source-list）
        cards.addWidget(left)

        # ---- 中栏：模板列表（搜索 + 两行卡片行）----
        middle = QFrame()
        middle.setObjectName("templateCard")
        mv = QVBoxLayout(middle)
        mv.setContentsMargins(12, 12, 12, 12)
        mv.setSpacing(8)
        mhead = QHBoxLayout()
        mtitle = QLabel("模板")
        mtitle.setObjectName("cardTitle")
        mhead.addWidget(mtitle)
        mhead.addStretch(1)
        self._new_btn = QPushButton("＋ 新建")
        self._new_btn.setObjectName("ghostBtn")
        self._new_btn.clicked.connect(self._new_template)
        mhead.addWidget(self._new_btn)
        mv.addLayout(mhead)
        self._search = QLineEdit()
        self._search.setObjectName("searchBox")
        self._search.setPlaceholderText("搜索模板…")
        self._search.textChanged.connect(self._on_search)
        mv.addWidget(self._search)
        self._list = QListWidget()
        self._list.setObjectName("templateList")
        self._list.setFrameShape(QListWidget.Shape.NoFrame)
        self._list.setSpacing(4)
        self._list.setItemDelegate(TemplateCardDelegate(self._list))
        # 模板右键：收藏 / 移动到类型 / 删除（§15/§21）
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(
            self._template_context_menu)
        self._list.viewport().installEventFilter(self)  # ★ 行尾点击区
        self._list.itemClicked.connect(self._on_template_clicked)  # 点击 → 编辑弹窗
        mv.addWidget(self._list, 1)
        self._list_empty = QLabel("还没有模板——点「＋ 新建」创建第一个")
        self._list_empty.setObjectName("emptyHint")
        self._list_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._list_empty.setWordWrap(True)
        self._list_empty.setParent(self._list.viewport())
        self._list_empty.hide()
        middle.setFixedWidth(260)  # 模板列固定宽（约为旧三栏的 2/3，整体更窄）
        cards.addWidget(middle)

        # 右栏编辑器已改为弹窗（TemplateEditorDialog）：点击模板/新建时弹出，
        # 页面不再常驻编辑面板（设计决策：整体更窄）

        cards.addStretch(1)  # 剩余空间留白（Raycast 风格，内容不撑满窗口）
        outer.addLayout(cards, 1)

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
        total = len(self._svc.list_templates())  # 「全部」计数（source-list 右对齐）
        self._folder_list.blockSignals(True)
        self._folder_list.clear()
        all_item = QListWidgetItem("全部")
        all_item.setData(ROLE_FOLDER_NAME, "全部")
        all_item.setData(ROLE_FOLDER_COUNT, str(total))
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self._folder_list.addItem(all_item)
        for f in self._folders:
            item = QListWidgetItem(f"{f['name']} ({f['count']})")
            item.setData(ROLE_FOLDER_NAME, f["name"])
            item.setData(ROLE_FOLDER_COUNT, str(f["count"]))
            item.setData(Qt.ItemDataRole.UserRole, f["id"])
            self._folder_list.addItem(item)
        self._folder_list.blockSignals(False)
        idx = next((i for i, f in enumerate(self._folders)
                    if f["id"] == current), -1)
        self._folder_list.setCurrentRow(idx + 1 if idx >= 0 else 0)
        # 分类下拉在编辑弹窗内（打开时按 list_folders 现取，无需同步）

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
            item.setData(ROLE_TEMPLATE, t)  # delegate 绘制数据（文本留给测试兼容）
            item.setData(Qt.ItemDataRole.UserRole, t["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._templates:
            idx = next((i for i, t in enumerate(self._templates)
                        if t["id"] == preserve_id), 0)
            self._list.setCurrentRow(idx)
        self._update_list_empty()

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

    # ---- 编辑弹窗（设计决策：编辑器不常驻，点击模板/新建时弹出）----

    def _on_template_clicked(self, item) -> None:
        """点击模板行 → 打开编辑弹窗。"""
        row = self._list.row(item)
        if 0 <= row < len(self._templates):
            self._open_editor(self._templates[row])

    def _new_template(self) -> None:
        """「＋ 新建」→ 打开新建弹窗。"""
        self._open_editor(None)

    def _open_editor(self, template=None) -> None:
        if self._svc is None:
            return
        dlg = TemplateEditorDialog(self, self._svc, template)
        # 400 宽 × 640 高（居中显示；高度更高，代码编辑区更舒展）
        dlg.resize(400, 640)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def _update_list_empty(self) -> None:
        """中栏空态：无模板（未搜索）/ 搜索无匹配。"""
        if self._templates:
            self._list_empty.hide()
            return
        if self._search.text().strip():
            self._list_empty.setText(f"未找到匹配「{self._search.text().strip()}」的模板")
        else:
            self._list_empty.setText("还没有模板——点「＋ 新建」创建第一个")
        self._list_empty.setGeometry(self._list.viewport().rect())
        self._list_empty.show()

    def eventFilter(self, obj, event) -> bool:
        """模板行尾 ★ 点击区 → 切换收藏（不触发行选中/编辑弹窗）。"""
        if obj is self._list.viewport() \
                and event.type() == QEvent.Type.MouseButtonPress:
            pos = event.position().toPoint()
            item = self._list.itemAt(pos)
            row = self._list.row(item) if item is not None else -1
            if 0 <= row < len(self._templates):
                rect = self._list.visualItemRect(item)
                if pos.x() > rect.right() - STAR_ZONE \
                        and pos.y() < rect.top() + 30:
                    self._toggle_favorite(self._templates[row])
                    return True  # 消费点击，不选中行
        return super().eventFilter(obj, event)

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
        self._reload_folders()  # 移动改变了两侧文件夹计数，需同步刷新

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
