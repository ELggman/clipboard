"""自定义变量新增/编辑对话框（值来源重构核心 UI）。

字段：变量名 / 描述 / 值来源（下拉）/ 值源配置（按来源切换）。
值来源四种（registry.SOURCE_*）：
- 用户输入（input）：无配置，触发时弹窗询问
- 固定值（fixed）：固定值文本框 → config.text
- 外部命令（command）：命令文本框 → config.command（sh -c 执行）
- 系统状态（state）：状态下拉 → config.state（v1 仅前台应用名）

编辑模式预填现有变量；result_variable() 返回构建的 CustomVariable。
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
)

from services.template.registry import (
    SOURCE_COMMAND,
    SOURCE_FIXED,
    SOURCE_INPUT,
    SOURCE_LABELS,
    SOURCE_STATE,
    CustomVariable,
    names as known_names,
)

from ui.fluent_combo import FluentComboBox

# 变量名合法性：与 parser 的 \w+ 一致（含中文，不含空格/标点）
_NAME_RE = re.compile(r"^\w+$")

# 值来源下拉顺序（固定：用户输入 → 固定值 → 外部命令 → 系统状态）
_SOURCE_ORDER = [SOURCE_INPUT, SOURCE_FIXED, SOURCE_COMMAND, SOURCE_STATE]

# 系统状态选项（v1 仅前台应用名；未来在此追加）
_STATE_OPTIONS = [("前台应用名", "frontmost_app")]


class VariableEditDialog(QDialog):
    def __init__(self, parent=None, variable: CustomVariable | None = None):
        super().__init__(parent)
        self._variable = variable
        self.setWindowTitle("编辑变量" if variable else "新增变量")
        self.setModal(True)
        self.setMinimumWidth(360)
        # 加高面板：字段少但给足纵向呼吸空间（宽度保持不变）
        self.setMinimumHeight(400)

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(20, 20, 20, 16)
        vbox.setSpacing(14)

        form = QFormLayout(self)
        form.setSpacing(12)
        # 字段横向填满面板宽度（配置文本框/下拉不再缩在 sizeHint 宽度）
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._name = QLineEdit(variable.name if variable else "")
        self._name.setPlaceholderText("myvar（不含 {{}}，如 location）")
        form.addRow("变量名", self._name)

        self._desc = QPlainTextEdit(variable.description if variable else "")
        self._desc.setPlaceholderText("描述（悬停变量时显示，可留空）")
        # 多行描述框：比单行输入框稍高，给足编辑空间（设计反馈）
        self._desc.setFixedHeight(64)
        form.addRow("描述", self._desc)

        self._source = FluentComboBox()
        for src in _SOURCE_ORDER:
            self._source.addItem(SOURCE_LABELS[src], src)
        if variable is not None:
            idx = self._source.findData(variable.source)
            self._source.setCurrentIndex(max(0, idx))
        self._source.currentIndexChanged.connect(self._on_source_changed)
        form.addRow("值来源", self._source)

        # 配置区（按值来源切换）
        self._config_stack = QStackedWidget()
        # 横向扩展：让固定值/命令文本框随面板宽度拉伸（不缩成默认窄框）
        self._config_stack.setSizePolicy(QSizePolicy.Policy.Expanding,
                                         QSizePolicy.Policy.Preferred)
        # input：无配置，仅提示
        input_hint = QLabel("触发时弹窗询问值")
        input_hint.setObjectName("fieldLabel")
        input_hint.setWordWrap(True)
        self._config_stack.addWidget(input_hint)
        # fixed：固定值
        self._fixed_edit = QLineEdit(
            (variable.config.get("text", "") if variable else ""))
        self._fixed_edit.setPlaceholderText("如 a@b.com")
        self._config_stack.addWidget(self._fixed_edit)
        # command：命令
        self._command_edit = QLineEdit(
            (variable.config.get("command", "") if variable else ""))
        self._command_edit.setPlaceholderText("如 date +%Y-%m-%d")
        self._config_stack.addWidget(self._command_edit)
        # state：状态下拉
        self._state_combo = FluentComboBox()
        for label, val in _STATE_OPTIONS:
            self._state_combo.addItem(label, val)
        if variable and variable.source == SOURCE_STATE:
            idx = self._state_combo.findData(variable.config.get("state", ""))
            self._state_combo.setCurrentIndex(max(0, idx))
        self._config_stack.addWidget(self._state_combo)
        form.addRow("配置", self._config_stack)

        vbox.addLayout(form)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("保存")
        ok.setObjectName("primaryButton")
        ok.clicked.connect(self._accept_if_valid)
        buttons.addWidget(ok)
        vbox.addLayout(buttons)

        self._name.returnPressed.connect(self._accept_if_valid)
        self._on_source_changed()

    def _on_source_changed(self) -> None:
        """值来源切换 → 显示对应配置页。"""
        src = self._source.currentData()
        page = _SOURCE_ORDER.index(src) if src in _SOURCE_ORDER else 0
        self._config_stack.setCurrentIndex(page)

    def _accept_if_valid(self) -> None:
        name = self._name.text().strip()
        if not name:
            QMessageBox.warning(self, "变量", "变量名不能为空")
            return
        if not _NAME_RE.match(name):
            QMessageBox.warning(
                self, "变量", "变量名只能含字母/数字/下划线/中文（不含空格标点）")
            return
        if name in known_names():
            QMessageBox.warning(self, "变量", f"「{name}」是内置变量名，请换一个")
            return
        self.accept()

    def result_variable(self) -> CustomVariable:
        """构建 CustomVariable（调用方在校验通过后调用）。"""
        name = self._name.text().strip()
        source = self._source.currentData()
        config: dict = {}
        if source == SOURCE_FIXED:
            config["text"] = self._fixed_edit.text()
        elif source == SOURCE_COMMAND:
            config["command"] = self._command_edit.text()
        elif source == SOURCE_STATE:
            config["state"] = self._state_combo.currentData()
        return CustomVariable(
            name=name, description=self._desc.toPlainText().strip(),
            source=source, config=config)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)
