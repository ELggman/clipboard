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

from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QCursor, QGuiApplication
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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from services.template.custom_vars import extra_insert_texts
from services.template.errors import TemplateError
from services.template.registry import custom_tooltip, is_preset
from services.template_service import TemplateService
from ui.template_components import (
    ROLE_FOLDER_COUNT,
    ROLE_FOLDER_NAME,
    ROLE_TEMPLATE,
    ROW_INSET,
    STAR_ZONE,
    FolderSourceDelegate,
    HoverButton,
    TemplateCardDelegate,
    TemplateHighlighter,
    VariableLibraryPopup,
    VariableTagBar,
    load_extra_variables,
    load_favorite_variables,
    save_extra_variables,
    save_favorite_variables,
)
from ui.variable_autocomplete import VariableAutocompleteEditor
from ui.variable_edit_dialog import VariableEditDialog

# ---- 模板页布局常量（手动调整模板条目宽度 = 中间栏宽度）----
# 中间栏不再硬编码（旧 setFixedWidth(280) 与左列 160 + 边距 恒 > 420 窗口，
# 右缘被裁掉 ~64px——怎么调都溢出）。现在由 _apply_middle_width 按窗口自适应：
#   - _PAGE_MARGIN 缩 → 中间栏变宽；_LEFT_WIDTH 改动 → 中间栏跟随；
#   - _ENTRY_WIDTH 设 >0 可手动固定条目宽（自动夹紧在窗口内，不会再溢出）。
_PAGE_MARGIN = 8      # 模板页左右页边距（仅本页，历史/收藏页不受影响）
_LEFT_WIDTH  = 160    # 左列「分类」固定宽（用户确认保持 160）
_ENTRY_WIDTH = 0      # 模板条目宽：0 = 随中间栏自适应（推荐）；>0 固定该值

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


class _VarButtonColumn(QWidget):
    """右侧按钮列：手动排布固定高按钮，绕开 QVBoxLayout 高度估算。

    macOS 上 QSS 样式表 padding 不计入 sizeHint，QWidgetItem.sizeHint()/
    minimumSize() 偏小（实测 QVBoxLayout 汇总后 sizeHint=68px，实际需
    84px），会把三个 setFixedHeight(24) 的按钮压到互相重叠（问题2）。
    这里完全手排、不做任何高度估算：按钮固定 24px、间距 6px，从容器顶部
    往下排，隐藏按钮（展开全部）不占位、其余上移。
    """

    BTN_H = 24
    GAP = 6

    def __init__(self, buttons, parent=None):
        super().__init__(parent)
        self._buttons = list(buttons)
        for b in self._buttons:
            b.setParent(self)
            b.setFixedHeight(self.BTN_H)
        self.setFixedHeight(self.BTN_H * 3 + self.GAP * 2)

    def sizeHint(self) -> QSize:
        # 无布局的 QWidget sizeHint 默认不包含子控件——vrow 会把它当 0 宽。
        # 返回最宽按钮的 sizeHint 宽，保证按钮列能拿到自然宽度。
        w = max((b.sizeHint().width() for b in self._buttons), default=0)
        return QSize(w, self.minimumHeight())

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place()

    def _place(self) -> None:
        w = self.width()
        y = 0
        for b in self._buttons:
            # 用 isHidden() 而非 isVisible()：resizeEvent 在弹窗 show 前就会
            # 触发，此时所有按钮 isVisible() 都是 False，会把全部跳过、按钮
            # 停在自然几何叠在 (0,0)。isHidden() 只反映显式 hide()，正是要
            # 排除「展开全部」隐藏按钮的语义。
            if not b.isHidden():
                b.setGeometry(0, y, w, self.BTN_H)
                y += self.BTN_H + self.GAP


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
        self._menus: list = []             # 右键菜单引用防 GC
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

        # 变量区：左侧胶囊（只显常用变量，折叠/展开）+ 右侧按钮列
        # （展开全部、变量库悬停弹层、＋ 新增）；标注在胶囊上方
        l5 = QLabel("变量")
        l5.setObjectName("fieldLabel")
        vbox.addWidget(l5)
        vrow = QHBoxLayout()
        vrow.setSpacing(8)
        # 胶囊创建时即注入自定义变量悬停说明（否则 tooltips 为空，自定义
        # 变量胶囊会回退到默认「触发时弹窗询问值」——与「变量库」里正确的
        # 值来源说明不一致，实测 bug）。
        self._var_tags = VariableTagBar(
            variables=load_favorite_variables(),
            tooltips=self._custom_tooltip_map())
        self._var_tags.variable_clicked.connect(self._insert_variable)
        self._var_tags.remove_requested.connect(self._on_variable_context)
        # 变量区滚动：展开多行时固定高度内滚动（设计反馈：展开显示不完全）
        self._var_scroll = QScrollArea()
        self._var_scroll.setObjectName("varScroll")
        self._var_scroll.setWidgetResizable(True)
        # 高度须与右侧按钮列（3×24+2×6=84px）一致：vrow 的 QHBoxLayout 高度
        # 取 max(滚动区, 按钮列)，滚动区若 72px 会压着按钮列（按钮实际 24px
        # 高、3 个共 84px）→ 新增/变量库按钮重叠（问题2）。改 84px 后二者
        # 同高，vrow=84px，按钮不再互相压。
        self._var_scroll.setFixedHeight(84)
        self._var_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._var_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._var_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._var_scroll.setWidget(self._var_tags)
        vrow.addWidget(self._var_scroll, 1)
        # 按钮列手动排布（_VarButtonColumn）：macOS 上裸 QVBoxLayout 的
        # sizeHint/minimumSize 偏小（实测 68px），会把三个 24px 固定高按钮
        # 压到互相重叠（问题2）。手排容器固定 84px，绕开高度估算。
        n_vars = len(self._var_tags.variables())
        self._more_btn = QPushButton(f"展开全部（{n_vars}）")
        self._more_btn.setObjectName("ghostBtn")
        self._more_btn.setVisible(self._var_tags.needs_collapse())
        self._more_btn.clicked.connect(self._toggle_vars)
        self._lib_btn = HoverButton("变量库")
        self._lib_btn.setObjectName("ghostBtn")
        self._lib_btn.setToolTip("全部变量（按来源类别分组；★ 管理常用）")
        self._add_btn = QPushButton("＋ 新增")
        self._add_btn.setObjectName("ghostBtn")
        self._add_btn.setToolTip("新增自定义变量")
        self._add_btn.clicked.connect(self._add_variable)
        self._var_col_wrap = _VarButtonColumn(
            [self._more_btn, self._lib_btn, self._add_btn])
        vrow.addWidget(self._var_col_wrap)
        vbox.addLayout(vrow)
        self._vrow = vrow

        # 「变量库」弹层（Qt.Popup）：点击切换展开；点击外部/Esc 由
        # Popup 自带关闭（macOS 悬停计时器方案不可靠，退回点击切换）。
        self._lib_popup = VariableLibraryPopup(self)
        self._lib_popup.set_custom_variables(load_extra_variables())
        self._lib_popup.insert_requested.connect(self._insert_variable)
        self._lib_popup.favorites_changed.connect(self._refresh_var_tags)
        self._lib_btn.clicked.connect(self._toggle_library)

        # 内容（Pygments + {{变量}} 高亮；输入 `{{` 弹变量补全）
        self._content = VariableAutocompleteEditor()
        self._content.setObjectName("templateEditor")
        self._content.setPlaceholderText("模板内容…（{{date}} 等变量自动高亮，{{ 自动补全）")
        self._content.textChanged.connect(self._schedule_highlight)
        self._content.set_custom_variables(extra_insert_texts())
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

    def showEvent(self, event) -> None:
        """弹窗显示后延迟一轮日志右侧三按钮几何（诊断问题2「按钮重叠」）。

        macOS 上用户报告「新增/变量库」按钮重叠，但离屏验证两者在
        QVBoxLayout 里恒不重叠——show 后延迟到布局完成再记录，若真重叠
        这里能看到三者 y 撞一起。
        """
        super().showEvent(event)
        # 兜底重排按钮列：resizeEvent 已排，但首次 show 时序可能早于布局定宽，
        # 延迟一轮再排一次确保按钮落在正确位置。
        QTimer.singleShot(0, self._var_col_wrap._place)
        QTimer.singleShot(0, self._log_button_geometry)

    def _log_button_geometry(self) -> None:
        rows = []
        for name in ("_more_btn", "_lib_btn", "_add_btn"):
            b = getattr(self, name)
            g = b.geometry()
            rows.append((name, b.isVisible(), g.x(), g.y(),
                         g.width(), g.height(),
                         b.sizeHint().height(),
                         b.minimumSizeHint().height(),
                         b.minimumHeight(), b.maximumHeight()))
        sc = self._var_scroll.geometry()
        ed = self._content.geometry()
        vw = self._vrow.geometry()
        wrap = self._var_col_wrap.geometry()
        logger.info(
            "变量区诊断: 对话框=%sx%s 按钮=(name,vis,x,y,w,h,sh,msh,minH,maxH)=%s "
            "滚动区=y%s h%s 编辑器=y%s h%s minH=%s vrow=y%s h%s wrap=y%s h%s",
            self.width(), self.height(), rows,
            sc.y(), sc.height(),
            ed.y(), ed.height(), self._content.minimumSizeHint().height(),
            vw.y(), vw.height(),
            wrap.y(), wrap.height())

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
        """变量胶囊点击：插入内容区光标处。

        input 变量走后缀规则（registry.next_input_insert）：内容已含
        `{{input:name}}` 再点同名胶囊 → 插 `{{input:name2}}`（每次独立输入）。
        """
        if var.startswith("{{input:") and var.endswith("}}"):
            base = var[len("{{input:"):-len("}}")]
            from services.template.registry import next_input_insert

            var = next_input_insert(self._content.toPlainText(), base)
        self._content.insertPlainText(var)
        self._content.setFocus()

    def _add_variable(self) -> None:
        """「＋ 新增」：填 变量名/描述/值来源 → 持久化（extra_variables +
        常用）→ 刷新胶囊区。新自定义默认进常用（胶囊区要显示；「变量库」
        ★ 可移除）。"""
        dlg = VariableEditDialog(parent=self)
        if not dlg.exec():
            return
        var = dlg.result_variable()
        extras = load_extra_variables()
        if any(v.name == var.name for v in extras):
            self._warn(f"变量「{var.name}」已存在")
            return
        extras.append(var)
        save_extra_variables(extras)
        favs = load_favorite_variables()
        if var.insert() not in favs:
            favs.append(var.insert())
            save_favorite_variables(favs)
        self._sync_custom_variables()
        self._refresh_var_tags()

    def _on_variable_context(self, var: str) -> None:
        """右键胶囊 → 菜单：预设显示禁用项「不可编辑」，自定义显示编辑/删除。

        ⚠️ 关键：整条链路只用**非阻塞** QMenu.popup()，绝不在右键处理器里
        弹模态框（QMessageBox / QMenu.exec）。macOS 上右键弹模态框会在关闭后
        残留鼠标 grab，整页按钮（展开/变量库/新增/取消/保存）点击无反应
        （问题2）。singleShot(0) 再把 popup 移出鼠标按下事件处理器。
        """
        QTimer.singleShot(0, lambda: self._show_variable_menu(var))

    def _show_variable_menu(self, var: str) -> None:
        menu = QMenu(self)
        self._menus.append(menu)  # 保持引用防 GC（同 TemplatesView._active_menus）
        if is_preset(var):
            act = menu.addAction("预设变量不可编辑")
            act.setEnabled(False)
        else:
            menu.addAction("编辑变量…").triggered.connect(
                lambda: self._edit_variable(var))
            menu.addAction("删除变量…").triggered.connect(
                lambda: self._remove_variable(var))
        menu.popup(QCursor.pos())

    def _edit_variable(self, var: str) -> None:
        """编辑自定义变量（改名/描述/值来源）；改名扫描引用但**不自动替换**。"""
        extras = load_extra_variables()
        current = next((v for v in extras if v.insert() == var), None)
        if current is None:
            return
        dlg = VariableEditDialog(parent=self, variable=current)
        if not dlg.exec():
            return
        updated = dlg.result_variable()
        # 改名：扫描模板引用，警告但不自动替换（避免静默改坏历史模板）
        if updated.name != current.name:
            refs = self._count_references(current.name)
            if refs:
                self._warn(
                    f"有 {refs} 个模板引用了「{current.name}」，"
                    "改名后不会自动更新这些引用")
        if any(v.name == updated.name for v in extras if v.insert() != var):
            self._warn(f"变量「{updated.name}」已存在")
            return
        extras = [updated if v.insert() == var else v for v in extras]
        save_extra_variables(extras)
        # 改名同步常用（favorites 存插入文本 {{old}} → {{new}}）
        favs = load_favorite_variables()
        if var in favs:
            favs.remove(var)
            if updated.insert() not in favs:
                favs.append(updated.insert())
            save_favorite_variables(favs)
        self._sync_custom_variables()
        self._refresh_var_tags()

    def _count_references(self, name: str) -> int:
        """扫描模板内容引用 {{name}} 的数量（改名警告用）。"""
        if self._svc is None:
            return 0
        token = f"{{{{{name}}}}}"
        return sum(1 for t in self._svc.list_templates()
                   if token in t["content"])

    def _remove_variable(self, var: str) -> None:
        """删除自定义变量（预设不可删）；同时移出常用。"""
        extras = load_extra_variables()
        if not any(v.insert() == var for v in extras):
            self._warn(f"预设变量「{var}」不可删除")
            return
        extras = [v for v in extras if v.insert() != var]
        save_extra_variables(extras)
        favs = load_favorite_variables()
        if var in favs:
            favs.remove(var)
            save_favorite_variables(favs)
        self._sync_custom_variables()
        self._refresh_var_tags()

    def _sync_custom_variables(self) -> None:
        """自定义变量变更 → 同步到补全编辑器与变量库弹层。"""
        extras = load_extra_variables()
        self._content.set_custom_variables(extra_insert_texts())
        self._lib_popup.set_custom_variables(extras)

    def _refresh_var_tags(self) -> None:
        """常用变量变更 → 胶囊区整体重建（只显常用）+ 按钮同步。"""
        self._var_tags.set_tooltips(self._custom_tooltip_map())
        self._var_tags.set_variables(load_favorite_variables())
        self._sync_var_buttons()

    def _custom_tooltip_map(self) -> dict[str, str]:
        """自定义变量 insert → 悬停说明（描述 + 值来源）。"""
        return {v.insert(): custom_tooltip(v) for v in load_extra_variables()}

    # ---- 「变量库」弹层开关（点击切换；Qt.Popup 点击外部/Esc 自带关闭）----

    def _open_library(self) -> None:
        self._lib_popup.set_custom_variables(load_extra_variables())
        self._lib_popup.rebuild()
        # 下拉式定位：右缘贴「＋ 新增」按钮列右缘、顶部在按钮列下方——
        # 彻底不遮挡右侧任一按钮（旧定位贴「变量库」按钮左侧，300px 高
        # 弹层往下延伸仍压到「＋ 新增」按钮，用户报告「按钮重叠」）。
        btn_global = self._add_btn.mapToGlobal(QPoint(0, 0))
        x = btn_global.x() + self._add_btn.width() - self._lib_popup.width()
        y = btn_global.y() + self._add_btn.height() + 6
        # 屏幕边缘夹紧（窗口贴边时弹层不能被推出屏外）
        screen = (QGuiApplication.screenAt(QCursor.pos())
                  or QGuiApplication.primaryScreen())
        if screen is not None:
            geo = screen.availableGeometry()
            x = max(geo.left(), min(x, geo.right() - self._lib_popup.width()))
            y = max(geo.top(), min(y, geo.bottom() - self._lib_popup.height()))
        self._lib_popup.show()
        # show() 之后再 move()：macOS 上 Qt.Popup 显示时可能被系统按光标
        # 位置重定位，show 前的 move() 会被覆盖 → 弹层压到「＋ 新增」按钮
        # （用户报告「按钮重叠」）。show 后 move 保证落在按钮列下方。
        self._lib_popup.move(x, y)
        self._lib_popup.raise_()

    def _toggle_library(self) -> None:
        if self._lib_popup.isVisible():
            self._lib_popup.hide()
        else:
            self._open_library()

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
        # 手排容器：可见性变化后重排（隐藏「展开全部」时 lib/add 上移）
        self._var_col_wrap._place()
        self._log_button_geometry()

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

    def _warn(self, message: str) -> None:
        # parent=self：警告框挂在编辑面板上（而非顶层），关闭后焦点/模态
        # 能正确归还给编辑面板，配合 singleShot 延后避免 macOS grab 残留
        QMessageBox.warning(self, "模板", message)


class TemplatesView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._svc: TemplateService | None = None
        self._templates: list[dict] = []
        self._folders: list[dict] = []
        self._active_menus: list = []  # 右键菜单引用防 GC
        self._pan: dict[int, int] = {}  # 长条目横向平移偏移（行号 → px）
        self._pan_state: dict | None = None  # 拖拽平移暂存
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

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_middle_width()

    def _apply_middle_width(self) -> None:
        """中间栏宽：_ENTRY_WIDTH=0 随窗口自适应填满；>0 手动固定（夹紧防溢出）。

        公式：窗口宽 − 左右页边距 − 左列 160 − cards 间距 12 = 中间栏宽。
        """
        if not hasattr(self, "_middle"):
            return
        avail = self.width() - 2 * _PAGE_MARGIN - _LEFT_WIDTH - 12
        if _ENTRY_WIDTH > 0:
            avail = min(_ENTRY_WIDTH, avail)
        self._middle.setFixedWidth(max(0, avail))

    # ---- 构建 ----

    def _build_ui(self) -> None:
        """三栏卡片布局（设计规范：白色卡片 16px 圆角、大量留白、蓝色强调）。"""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_PAGE_MARGIN, 8, _PAGE_MARGIN, 12)
        outer.setSpacing(12)

        cards = QHBoxLayout()
        cards.setSpacing(12)

        # ---- 左栏：分类导航（source-list，计数右对齐）----
        left = QFrame()
        left.setObjectName("templateCard")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(12, 12, 6, 12)
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
        left.setFixedWidth(_LEFT_WIDTH)  # 分类列固定宽（用户确认保持 160）
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
        self._list.setUniformItemSizes(True)  # 行高恒定 58px：跳过逐行布局计算，滚轮更流畅
        self._list.setItemDelegate(TemplateCardDelegate(self._list, self))
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
        # 中间栏宽不硬编码：resizeEvent → _apply_middle_width 按窗口自适应填满
        # （_ENTRY_WIDTH=0 自适应；>0 手动固定并夹紧，面板永不出窗口、无横滚条）
        middle.setMinimumWidth(0)
        middle.setSizePolicy(QSizePolicy.Policy.Expanding,
                             QSizePolicy.Policy.Preferred)
        self._middle = middle
        cards.addWidget(middle)

        # 右栏编辑器已改为弹窗（TemplateEditorDialog）：点击模板/新建时弹出，
        # 页面不再常驻编辑面板（设计决策：整体更窄）
        outer.addLayout(cards, 1)

        # 长条目平移用鼠标/触摸板，列表本身不出横向滚轮条（用户要求）
        self._list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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
        self._pan.clear()  # 列表重建：平移偏移作废
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
        """模板行 ★ 点击区 → 收藏切换；长条目横向平移（横滑/拖动）。

        平移只影响内容，★ 固定右缘；拖拽超过 4px 视为平移、吃掉释放事件，
        避免误触发「点击打开编辑」。列表不出横向滚轮条（用户要求）。
        """
        if obj is not self._list.viewport():
            return super().eventFilter(obj, event)
        et = event.type()
        vp = self._list.viewport()

        # 触摸板双指横滑 / 横向滚轮 / Shift+滚轮 → 平移鼠标下条目
        if et == QEvent.Type.Wheel:
            pos = event.position().toPoint()
            dx = event.angleDelta().x()
            dy = event.angleDelta().y()
            # 横滑判定：明显横向（|dx|≥|dy|）或 Shift+纵向。纵向滑动常混入
            # 微小横向分量（dx=±1~2），旧判定 dx!=0 会逐个吞掉并整视口重绘
            # → 上下滚轮明显卡顿（用户反馈）。
            horiz = (dx != 0 and abs(dx) >= abs(dy)) or (
                bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                and dy != 0)
            if horiz:
                return self._pan_step(pos, dx if dx else dy)
            return False  # 纵向滚动照常交给列表

        # 鼠标按下：★ 点击区切收藏；条目区记录拖拽起点（4px 内视为点击）
        if et == QEvent.Type.MouseButtonPress \
                and event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            item = self._list.itemAt(pos)
            row = self._list.row(item) if item is not None else -1
            if 0 <= row < len(self._templates):
                rect = self._list.visualItemRect(item)
                # ★ 点击区 = delegate 绘制星标的实际位置（右缘减 ROW_INSET）。
                # 直接用 visualRect 原右缘会把命中区右偏 8px，点不到星标。
                star_right = rect.right() - ROW_INSET
                if pos.x() > star_right - STAR_ZONE \
                        and pos.x() <= star_right \
                        and pos.y() < rect.top() + 30:
                    self._toggle_favorite(self._templates[row])
                    return True  # 消费点击，不选中行
                self._pan_state = {
                    "row": row, "press_x": pos.x(),
                    "start": self._pan.get(row, 0), "dragging": False,
                }
            return False  # 放行：列表处理选中，释放时若未拖动 → 打开编辑

        # 鼠标按住拖动 → 横向平移（内容跟随鼠标），超过阈值才进拖拽态
        if et == QEvent.Type.MouseMove:
            if event.buttons() & Qt.MouseButton.LeftButton:
                st = self._pan_state
                if st is not None:
                    pos = event.position().toPoint()
                    dx = pos.x() - st["press_x"]
                    if st["dragging"] or abs(dx) > 4:
                        if not st["dragging"]:
                            st["dragging"] = True
                            vp.setCursor(Qt.CursorShape.SizeHorCursor)
                        self._set_pan(
                            st["row"], st["start"] + (st["press_x"] - pos.x()))
                        return True  # 拖拽中吃掉移动，避免列表做选区
                    return False  # 未过阈值：放行，不影响点击
                return False
            vp.setCursor(Qt.CursorShape.ArrowCursor)  # 无按钮移动：兜底复位光标
            return False

        # 鼠标释放：拖拽结束吃事件（不触发点击/编辑）；普通点击放行
        if et == QEvent.Type.MouseButtonRelease \
                and event.button() == Qt.MouseButton.LeftButton:
            st = self._pan_state
            self._pan_state = None
            vp.setCursor(Qt.CursorShape.ArrowCursor)
            if st is not None and st["dragging"]:
                return True
            return False

        return super().eventFilter(obj, event)

    def _pan_step(self, pos, delta: int) -> bool:
        """横滑一步：鼠标/触摸板横滚下条目内容左右平移（不显示滚轮）。"""
        item = self._list.itemAt(pos)
        row = self._list.row(item) if item is not None else -1
        if 0 <= row < len(self._templates):
            self._set_pan(row, self._pan.get(row, 0) - delta / 120.0 * 40)
        return True  # 吃掉横滚事件

    def _set_pan(self, row, offset) -> None:
        """写入平移偏移并重绘（精确夹紧由 delegate 绘制时按内容宽计算）。

        偏移未变时不触发重绘：纵向滚轮混入的微小横向分量（dx=±1）经
        _pan_step 算成 0，若每次都 update() 整视口 → 滚轮明显卡顿。
        """
        off = int(offset)
        if self._pan.get(row, 0) == off:
            return
        self._pan[row] = off
        self._list.viewport().update()

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
