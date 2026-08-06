"""Snippet 视图：用户维护的代码片段（与 History 独立）。

TODO: 列表 + 新建/编辑对话框；复制时经 snippet_service.render_snippet 渲染变量。
"""
import logging

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class SnippetsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Snippets（TODO: 增删改 + {{date}}/{{time}}/{{uuid}} 变量）")
        label.setStyleSheet("color: gray;")
        layout.addWidget(label)
        layout.addStretch(1)
