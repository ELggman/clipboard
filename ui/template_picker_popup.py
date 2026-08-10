"""模板 Picker 弹出层（⌘⇧S 触发，文档 §16-17）：搜索 + 列表选择。

- 输入即搜索（Name/Shortcut/Content/Folder，评分排序 §19）
- ↑↓ 选择、Enter 插入（selected 信号）、Esc 关闭（Qt.Popup 自带）
"""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QLineEdit, QListWidget, QVBoxLayout, QWidget

logger = logging.getLogger(__name__)


class TemplatePickerPopup(QWidget):
    selected = Signal(object)  # 模板 dict

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setObjectName("templatePicker")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._svc = None
        self._templates: list[dict] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("搜索模板…")
        self._search.textChanged.connect(self._on_search)
        layout.addWidget(self._search)
        self._list = QListWidget()
        self._list.setObjectName("historyList")
        self._list.setUniformItemSizes(True)
        layout.addWidget(self._list, 1)
        self.resize(420, 320)

    def set_service(self, service) -> None:
        """注入 TemplateService（bootstrap 装配）。"""
        self._svc = service

    def show_near_cursor(self) -> None:
        """清空搜索、列出全部模板，定位在光标上方。"""
        if self._svc is None:
            return
        self._search.clear()
        self.populate(self._svc.list_templates())
        cursor = QCursor.pos()
        screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        x = max(geo.left(), min(cursor.x() - 8, geo.right() - self.width() - 8))
        y = max(geo.top(), min(cursor.y() - self.height() - 8,
                               geo.bottom() - self.height() - 8))
        self.move(x, y)
        self.show()
        self.raise_()
        from ui.animations import fade_in_window

        fade_in_window(self)
        self._search.setFocus()

    def populate(self, templates: list[dict]) -> None:
        self._templates = templates
        self._list.clear()
        for t in templates:
            star = "★ " if t["favorite"] else ""
            self._list.addItem(f"{star}{t['name']}  [{t['shortcut']}]")
        self._list.setCurrentRow(0)
        self.adjustSize()

    def _on_search(self, text: str) -> None:
        if self._svc is None:
            return
        self.populate(self._svc.search_templates(text.strip()))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            row = self._list.currentRow()
            if 0 <= row < len(self._templates):
                self.selected.emit(self._templates[row])
            self.close()
            return
        if event.key() == Qt.Key_Escape:
            self.close()
            return
        super().keyPressEvent(event)
