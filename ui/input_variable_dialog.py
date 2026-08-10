"""输入变量对话框（文档 §40-41）：收集模板 {{input:name}} 的值。

同一变量只问一次（§43 去重）；按模板中出现顺序依次排列。
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QHBoxLayout, QLineEdit, QPushButton

logger = logging.getLogger(__name__)


class InputVariableDialog(QDialog):
    def __init__(self, variables: list[str], parent=None):
        """variables：去重后的变量名列表（按首次出现顺序）。"""
        super().__init__(parent)
        self.setWindowTitle("模板输入")
        self.setModal(True)
        self.setMinimumWidth(320)
        self._edits: dict[str, QLineEdit] = {}
        form = QFormLayout(self)
        form.setContentsMargins(20, 16, 20, 16)
        form.setSpacing(10)
        for name in variables:
            edit = QLineEdit()
            edit.setPlaceholderText(f"请输入 {name}")
            self._edits[name] = edit
            form.addRow(name, edit)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        ok = QPushButton("插入")
        ok.setObjectName("primaryButton")
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        form.addRow(buttons)
        # 第一个输入框回车 = 确认
        if variables:
            first = self._edits[variables[0]]
            first.returnPressed.connect(self.accept)
            first.setFocus()

    def values(self) -> dict[str, str]:
        return {name: edit.text() for name, edit in self._edits.items()}

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)  # 对话框淡入（不做位移）
