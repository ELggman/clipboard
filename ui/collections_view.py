"""收藏夹视图：左侧收藏列表 + 右侧条目（拖入/右键 Add To Collection 在 V1.5）。"""
import logging

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class CollectionsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Collections（TODO: 创建/删除/重命名收藏夹）")
        label.setStyleSheet("color: gray;")
        layout.addWidget(label)
        layout.addStretch(1)
