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


class NameDialog(QDialog):
    """单行命名对话框（新建/重命名收藏夹等）。"""

    def __init__(self, title: str, label: str, initial: str = "",
                 placeholder: str = "", confirm_text: str = "确定",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel(label))
        self._edit = QLineEdit(initial)
        self._edit.setPlaceholderText(placeholder)
        self._edit.returnPressed.connect(self.accept)  # 回车即确认
        layout.addWidget(self._edit)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton(confirm_text)
        confirm.setObjectName("primaryButton")
        confirm.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        layout.addLayout(buttons)

        self._edit.setFocus()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        from ui.animations import fade_in_window

        fade_in_window(self, dy=0)  # 对话框淡入（不做位移，避免晃动）

    def text(self) -> str:
        return self._edit.text().strip()
