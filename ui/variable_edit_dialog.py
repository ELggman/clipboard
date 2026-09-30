"""自定义变量新增/编辑对话框（值来源重构核心 UI）。

字段：变量名 / 描述 / 值来源（下拉）/ 值源配置（按来源切换）。
值来源四种（registry.SOURCE_*）：
- 用户输入（input）：无配置，触发时弹窗询问
- 固定值（fixed）：固定值文本框 → config.text
- 外部命令（command）：命令文本框（**多行**）→ config.command（sh -c 执行）
  + 「试运行」就地看 stdout/退出码/stderr/耗时
  + 取值失败策略下拉 → config.on_error（留空/兜底文案/放弃本次插入）
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
    QWidget,
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
from services.template.value_sources import (
    DEFAULT_ERROR_TEXT,
    ERROR_CANCEL,
    ERROR_EMPTY,
    ERROR_LABELS,
    ERROR_TEXT,
)

from ui.fluent_combo import FluentComboBox

# 变量名合法性：与 parser 的 \w+ 一致（含中文，不含空格/标点）
_NAME_RE = re.compile(r"^\w+$")

# 值来源下拉顺序（固定：用户输入 → 固定值 → 外部命令 → 系统状态）
_SOURCE_ORDER = [SOURCE_INPUT, SOURCE_FIXED, SOURCE_COMMAND, SOURCE_STATE]

# 命令失败策略下拉顺序（留空 → 兜底文案 → 放弃本次插入）
_ERROR_ORDER = [ERROR_EMPTY, ERROR_TEXT, ERROR_CANCEL]

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
        # command：命令 + 失败策略（取值失败时怎么办）
        cmd_page = QWidget()
        cmd_lay = QVBoxLayout(cmd_page)
        cmd_lay.setContentsMargins(0, 0, 0, 0)
        cmd_lay.setSpacing(8)
        # 多行命令框：单行 QLineEdit 写不下多步脚本（pipelines/多行 python -c）
        self._command_edit = QPlainTextEdit(
            (variable.config.get("command", "") if variable else ""))
        self._command_edit.setPlaceholderText(
            "如 date +%Y-%m-%d（可多行；经 /bin/sh -c 执行）；"
            "写 cw:<脚本名> 则跑脚本目录里的脚本")
        self._command_edit.setFixedHeight(76)
        cmd_lay.addWidget(self._command_edit)
        # 上下文注入提示（与环境变量表 value_sources.ENV_HELP 呼应）：
        # 脚本「知道现在是什么情况」的三个通道，不写出来作者无从得知。
        cmd_hint = QLabel(
            "stdin＝选中文本（无选中则剪贴板）；`$1…` ＝ {{变量:参数}}；"
            "环境变量 CW_SELECTION / CW_CLIPBOARD / CW_APP / CW_NOW / "
            "CW_INPUT_<名> / CW_ARGS / CW_SCRIPT_DIR（脚本目录，用户在前）")
        cmd_hint.setObjectName("fieldLabel")
        cmd_hint.setWordWrap(True)
        cmd_lay.addWidget(cmd_hint)
        # 试运行：作者侧唯一的调试手段（触发链路上看不到中间结果）
        run_row = QHBoxLayout()
        self._run_btn = QPushButton("试运行")
        self._run_btn.setObjectName("secondaryButton")
        self._run_btn.setAutoDefault(False)
        self._run_btn.clicked.connect(self._try_run)
        run_row.addWidget(self._run_btn)
        self._run_status = QLabel("")
        self._run_status.setObjectName("fieldLabel")
        run_row.addWidget(self._run_status, 1)
        cmd_lay.addLayout(run_row)
        self._run_output = QPlainTextEdit()
        self._run_output.setObjectName("runOutput")
        self._run_output.setReadOnly(True)
        self._run_output.setFixedHeight(56)
        self._run_output.setVisible(False)
        cmd_lay.addWidget(self._run_output)
        err_label = QLabel("取值失败时")
        err_label.setObjectName("fieldLabel")
        cmd_lay.addWidget(err_label)
        self._error_policy = FluentComboBox()
        for policy in _ERROR_ORDER:
            self._error_policy.addItem(ERROR_LABELS[policy], policy)
        if variable is not None:
            idx = self._error_policy.findData(
                variable.config.get("on_error") or ERROR_EMPTY)
            self._error_policy.setCurrentIndex(max(0, idx))
        self._error_policy.currentIndexChanged.connect(
            self._on_error_policy_changed)
        cmd_lay.addWidget(self._error_policy)
        self._error_text = QLineEdit(
            (variable.config.get("on_error_text", "") if variable else ""))
        self._error_text.setPlaceholderText(DEFAULT_ERROR_TEXT)
        cmd_lay.addWidget(self._error_text)
        self._config_stack.addWidget(cmd_page)
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
        self._on_error_policy_changed()

    def _on_error_policy_changed(self) -> None:
        """仅「插入兜底文案」需要填文案——其余策略下隐藏该输入框。"""
        show_text = (self._source.currentData() == SOURCE_COMMAND
                     and self._error_policy.currentData() == ERROR_TEXT)
        self._error_text.setVisible(show_text)

    def _try_run(self) -> None:
        """试运行当前命令：就地显示 stdout/退出码/stderr/耗时。

        用**与触发链路同一条执行路径**（run_command）+ 同一个超时，所以看到
        的结果就是真触发时会拿到的结果；但不套 on_error 策略——作者要看到
        真实退出码与 stderr，而不是被策略替换后的兜底文案。

        上下文也要跟触发时一样喂：stdin 取当前剪贴板（对话框里没有「选中
        文本」这回事，故 selection 留空 → stdin_for 回落到剪贴板），环境
        变量照常注入。否则读 stdin/CW_* 的脚本试运行恒是空，作者会误判。
        """
        from services.template.value_sources import (CommandValueSource,
                                                     build_command_env,
                                                     run_command, stdin_for)
        from services.template.variables import RenderContext
        from services.template_service import TemplateService

        command = self._command_edit.toPlainText().strip()
        if not command:
            self._show_run_result(False, "命令为空", "")
            return
        name = self._name.text().strip() or "test"
        var = self.result_variable()
        ctx = RenderContext(clipboard_text=TemplateService._system_clipboard())
        timeout = CommandValueSource._timeout(var.config)
        self._run_status.setText("运行中…")
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()  # 先画出「运行中…」再阻塞
        run = run_command(command, timeout,
                          env=build_command_env(name, ctx),
                          stdin_text=stdin_for(ctx))
        body = run.stdout.rstrip("\n")
        if run.stderr.strip():
            body += f"\n[stderr] {run.stderr.strip()}"
        summary = (f"退出码 0 · {run.duration_ms}ms" if run.ok else run.error)
        self._show_run_result(run.ok, summary, body)

    def _show_run_result(self, ok: bool, summary: str, body: str) -> None:
        self._run_status.setText(summary)
        self._run_output.setPlainText(body)
        self._run_output.setVisible(bool(body))
        self.adjustSize()

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
            config["command"] = self._command_edit.toPlainText()
            policy = self._error_policy.currentData() or ERROR_EMPTY
            config["on_error"] = policy
            if policy == ERROR_TEXT:
                config["on_error_text"] = self._error_text.text()
        elif source == SOURCE_STATE:
            config["state"] = self._state_combo.currentData()
        return CustomVariable(
            name=name, description=self._desc.toPlainText().strip(),
            source=source, config=config)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)
