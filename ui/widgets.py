"""公共控件。"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QWidget


class IconLabel(QWidget):
    """自绘图标标签：QPainter 绘制 emoji 文字。

    QPushButton/QToolButton 的 icon、QLabel 的 pixmap/文字在
    MainWindow 上下文中渲染空白（Qt 6.9 macOS 实测逐项验证）——
    自绘与列表 delegate 同一 QPainter 路径，渲染可靠。
    """

    def __init__(self, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._text = text
        self.setFixedSize(30, 28)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)
        painter.end()
