"""共享对话框：Apple 风格命名输入框（替代 QInputDialog）。

QInputDialog 的 OK 按钮是系统英文样式且无法定制；此对话框用
主题 QSS（QLineEdit / QPushButton#primaryButton）+ 中文按钮。
"""
import logging

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

logger = logging.getLogger(__name__)


class ConfirmDialog(QDialog):
    """Apple 风格确认对话框：destructive 确认按钮为红色（macOS 惯例）。"""

    def __init__(self, title: str, message: str, confirm_text: str = "删除",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        msg = QLabel(message)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(confirm_text)
        confirm.setObjectName("destructiveButton")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)


class NameDialog(QDialog):
    """单行命名对话框（新建/重命名收藏夹等）。

    validate: 可选的 `validate(text) -> str | None` 回调——返回非空错误消息时，
    在输入框下方红字提示且**不关闭对话框**（用于查重等即时校验，实测：仅状态栏
    提示太弱，用户注意不到，必须停在对话框里报错）。
    """

    def __init__(self, title: str, label: str, initial: str = "",
                 placeholder: str = "", confirm_text: str = "确定",
                 validate=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)
        self._validate = validate

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel(label))
        self._edit = QLineEdit(initial)
        self._edit.setPlaceholderText(placeholder)
        self._edit.returnPressed.connect(self._on_confirm)  # 回车即确认（走校验）
        layout.addWidget(self._edit)

        # 校验错误红字（默认隐藏；validate 返回消息时显示并阻止关闭）
        self._error = QLabel("")
        self._error.setObjectName("dialogError")
        self._error.setWordWrap(True)
        self._error.hide()
        layout.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.setObjectName("secondaryButton")  # 灰底 + 主题文字色（与确认按钮同尺寸）
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(confirm_text)
        confirm.setObjectName("primaryButton")
        confirm.setDefault(True)  # 回车 = 确认：QDialog 默认按钮（取消先建会抢走默认
        #   按钮 → 回车触发 reject 关对话框而不创建，实测 macOS 踩坑）
        confirm.clicked.connect(self._on_confirm)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

        self._edit.setFocus()

    def _on_confirm(self) -> None:
        """确认：validate 通过则 accept，否则红字 + 输入框红框提示保持打开。"""
        if self._validate is not None:
            err = self._validate(self._edit.text().strip())
            if err:
                self._error.setText(err)
                self._error.show()
                # 输入框红框（QSS [error="true"] 属性选择器；重新 polish 生效）
                self._edit.setProperty("error", "true")
                self._edit.style().unpolish(self._edit)
                self._edit.style().polish(self._edit)
                self._edit.setFocus()
                return
        self._error.hide()
        self._edit.setProperty("error", "")
        self._edit.style().unpolish(self._edit)
        self._edit.style().polish(self._edit)
        self.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)  # 对话框淡入（不做位移，避免晃动）

    def text(self) -> str:
        return self._edit.text().strip()
