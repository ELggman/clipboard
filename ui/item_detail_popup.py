"""条目详情弹层：单击历史条目展开。

特性（契合剪贴板工具）：
- 文本/URL/文件：全文 QTextEdit（只读但可**选中部分复制**，Cmd+C 原生支持）
- 长文本：滚动查看全文，解决列表 elide 截断
- 图片：大图预览
- 元信息行：时间 · 类型 · 来源软件（source_app）
- 「复制全部」按钮；Esc/点击外部关闭（Qt.Popup）
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)

_MAX_WIDTH = 620      # 弹层最大宽度
_MAX_HEIGHT = 460     # 弹层最大高度


class ItemDetailPopup(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setObjectName("itemDetail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._item = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        self._meta = QLabel()
        self._meta.setObjectName("detailMeta")
        self._meta.setWordWrap(True)
        layout.addWidget(self._meta)

        self._text = QTextEdit()
        self._text.setReadOnly(True)          # 只读但可选中复制
        self._text.setFrameShape(QTextEdit.Shape.NoFrame)
        self._text.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self._text, 1)

        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setScaledContents(False)
        self._image.hide()
        layout.addWidget(self._image, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        copy_btn = QPushButton("复制全部")
        copy_btn.setObjectName("primaryButton")
        copy_btn.clicked.connect(self._copy_all)
        buttons.addWidget(copy_btn)
        layout.addLayout(buttons)

    def show_item(self, item, image_service=None) -> None:
        """展示条目详情。image_service 预留（缩略图服务，当前直接用文件加载）。"""
        self._item = item
        self._meta.setText(self._meta_text(item))
        self._image.hide()
        self._text.show()

        if item.type == "image" and item.file_path:
            self._text.hide()
            pix = QPixmap(item.file_path)
            if not pix.isNull():
                pix = pix.scaled(_MAX_WIDTH - 60, _MAX_HEIGHT - 120,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                self._image.setPixmap(pix)
                self._image.show()
        elif item.type == "file":
            self._text.setPlainText(item.file_path or item.content)
        else:
            self._text.setPlainText(item.content or item.preview)

        self._resize_to_content()
        self._show_near_cursor()

    # ---- 内部 ----

    def _meta_text(self, item) -> str:
        parts = []
        if item.created_at:
            parts.append(item.created_at)
        parts.append(item.type)
        if item.type in ("image", "file") and item.preview:
            parts.append(item.preview)  # 图片/文件显示名称
        if item.source_app:
            parts.append(f"来自 {item.source_app}")
        if item.type == "file" and item.content and item.content != item.preview:
            parts.append(item.content)
        return " · ".join(parts)

    def _copy_all(self) -> None:
        from services.action_service import set_clipboard_item

        if self._item is not None and set_clipboard_item(self._item):
            logger.info("详情弹层复制全部: %s", self._item.type)

    def _resize_to_content(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        width = min(_MAX_WIDTH, geo.width() - 80)
        # 文本高度按内容估算（每行约 20px），封顶 _MAX_HEIGHT
        if self._text.isVisible():
            lines = max(1, self._text.document().lineCount())
            height = min(_MAX_HEIGHT, max(160, 40 + lines * 22))
        else:
            height = min(_MAX_HEIGHT, self._image.height() + 90)
        self.resize(width, height)

    def _show_near_cursor(self) -> None:
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

        fade_in_window(self)  # 出现动画（origin-aware：从光标方向生长）
        self._text.setFocus()
