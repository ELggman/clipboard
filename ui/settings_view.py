"""设置视图：历史数量/图片保存/自动删除/开机启动/快捷键/字体/主题。

TODO: 读 load_config() 渲染，变更时写回 settings.yaml（+ LaunchAgent 开关）。
"""
import logging

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

logger = logging.getLogger(__name__)


class SettingsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QFormLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addRow("Settings", QLabel("TODO: 历史数量 / 图片保存 / 自动删除 / 开机启动 / 快捷键 / 字体 / 主题"))
