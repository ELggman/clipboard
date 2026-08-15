"""输入变量对话框（文档 §40-41）：收集模板 {{input:name}} 的值。

v7 重设计（变量系统增强）：
- 顶部：模板原文实时预览——已填的 {{input:name}} 替换为值、未填保留
  原 token（便于定位每个输入落在原文哪处）；输入框改动即刷新
- 中部：每变量一行输入框（标签 = {{input:name}}，与预览 token 一致）
- 底部：取消 / 插入；「插入」仅**全部字段非空**时可点（all_filled）——
  缺一个值就不允许插入（用户决策：变量没都输入值不能插入）

同一变量只问一次（§43 去重），按模板中出现顺序排列。
预览只做 token 替换（preview_text 纯函数），不跑完整渲染流水线——
系统变量（{{date}} 等）保持原样展示，这正是「原文」的语义。
"""
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

_INPUT_RE = re.compile(r"\{\{input:([^}]*)\}\}")


def all_filled(values: dict[str, str]) -> bool:
    """全部输入变量都已填值（空白/纯空格视为未填）。"""
    return all(bool(v.strip()) for v in values.values())


def preview_text(content: str, values: dict[str, str]) -> str:
    """模板原文预览：已填的 {{input:name}} 替换为值；未填保留原 token。"""
    def repl(m) -> str:
        name = m.group(1)
        v = values.get(name, "")
        return v if v.strip() else m.group(0)

    return _INPUT_RE.sub(repl, content)


class InputVariableDialog(QDialog):
    def __init__(self, variables: list[str], content: str = "", parent=None):
        """variables：去重后的变量名列表（按首次出现顺序）。"""
        super().__init__(parent)
        self.setWindowTitle("模板输入")
        self.setModal(True)
        self.setMinimumWidth(380)
        self._variables = variables
        self._content = content
        self._edits: dict[str, QLineEdit] = {}

        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(20, 16, 20, 16)
        vbox.setSpacing(10)

        # 顶部：模板原文实时预览（只读；输入改动重绘）
        if content:
            vbox.addWidget(QLabel("模板预览"))
            preview = QPlainTextEdit()
            preview.setReadOnly(True)
            preview.setPlainText(content)
            preview.setMaximumHeight(96)
            vbox.addWidget(preview)
            self._preview = preview
        else:
            self._preview = None

        # 中部：每变量一行输入框（标签与预览 token 一致）
        form = QFormLayout()
        form.setSpacing(10)
        for name in variables:
            edit = QLineEdit()
            edit.setPlaceholderText(f"请输入 {name}")
            self._edits[name] = edit
            form.addRow(f"{{{{input:{name}}}}}", edit)
            edit.textChanged.connect(self._on_change)
            edit.returnPressed.connect(self._next_or_accept)
        vbox.addLayout(form)

        # 底部：取消 / 插入（全部填满才可点）
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        # ⚠️ QDialog 里 QPushButton 默认 autoDefault=True：输入框回车会冒泡
        # 触发默认按钮关框（实测：填一个变量按回车，对话框直接消失）。显式
        # 关掉，让回车只走 returnPressed → _next_or_accept（跳空字段/全填满
        # 才 accept）。
        cancel.setAutoDefault(False)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("插入")
        ok.setObjectName("primaryButton")
        ok.setAutoDefault(False)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        vbox.addLayout(buttons)
        self._insert_btn = ok
        self._on_change()  # 初始：未填 → 插入置灰

        # 焦点给第一个输入框
        if variables:
            self._edits[variables[0]].setFocus()

    # ---- 交互 ----

    def _on_change(self) -> None:
        values = self.values()
        self._insert_btn.setEnabled(all_filled(values))
        if self._preview is not None:
            self._preview.setPlainText(preview_text(self._content, values))

    def _next_or_accept(self) -> None:
        """回车：全部填满 → 插入；否则跳到下一个空字段。"""
        if all_filled(self.values()):
            self.accept()
            return
        for name in self._variables:
            if not self._edits[name].text().strip():
                self._edits[name].setFocus()
                return

    def values(self) -> dict[str, str]:
        return {name: edit.text() for name, edit in self._edits.items()}

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)  # 对话框淡入（不做位移）
