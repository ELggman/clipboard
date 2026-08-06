"""时间线视图：今天/昨天/本周 分组浏览（DEVELOPMENT.md §4.7）。"""
import logging

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class TimelineView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Timeline（TODO: 按今天/昨天/本周分组）")
        label.setObjectName("placeholder")
        layout.addWidget(label)
        layout.addStretch(1)
