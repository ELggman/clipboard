"""条目详情弹层：单击历史条目展开。

特性（契合剪贴板工具）：
- 文本/URL/文件：全文 QTextEdit（只读但可**选中部分复制**，Cmd+C 原生支持）
- 代码：mono 等宽 + 行号 gutter + Pygments 语法高亮（§8.7/§8.8）
- 敏感内容：默认遮蔽显示，点「显示」才 Reveal（§9.18/§9.19）
- 长文本：滚动查看全文，解决列表 elide 截断
- 元信息行：时间 · 类型 · 来源软件（source_app）
- 复制/复制纯文本/保存为文件 按钮；Esc/点击外部关闭（Qt.Popup）
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QCursor,
    QGuiApplication,
    QPainter,
    QPalette,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ui.code_highlighter import CodeHighlighter, mono_font

logger = logging.getLogger(__name__)

_MAX_WIDTH = 620      # 弹层最大宽度
_MAX_HEIGHT = 460     # 弹层最大高度


class _CodeEdit(QPlainTextEdit):
    """只读代码视图：mono 字体 + 左侧行号 gutter（随滚动同步）。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("codeView")
        self.setReadOnly(True)
        self.setFrameShape(QPlainTextEdit.Shape.NoFrame)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._gutter = 42
        self.setViewportMargins(self._gutter, 0, 0, 0)
        self.setFont(mono_font(12))

    def paintEvent(self, event) -> None:
        painter = QPainter(self.viewport())
        bg = self.palette().color(QPalette.ColorRole.AlternateBase)
        fg = self.palette().color(QPalette.ColorRole.PlaceholderText)
        painter.fillRect(0, 0, self._gutter, self.viewport().height(), bg)
        painter.setPen(fg)
        block = self.firstVisibleBlock()
        number = block.blockNumber()
        top = round(self.blockBoundingGeometry(block)
                    .translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        fm = self.fontMetrics()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.drawText(0, top, self._gutter - 8, fm.height(),
                                 Qt.AlignmentFlag.AlignRight, str(number + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            number += 1
        painter.end()
        super().paintEvent(event)


class ItemDetailPopup(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Popup)
        self.setObjectName("itemDetail")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._item = None
        self._revealed = False       # 敏感内容是否已显示原文（§9.18）
        self._highlighter = None     # Pygments 高亮器（随 document 生命周期）

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

        self._code = _CodeEdit()
        self._code.hide()
        layout.addWidget(self._code, 1)

        self._image = QLabel()
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image.setScaledContents(False)
        self._image.hide()
        layout.addWidget(self._image, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._reveal_btn = QPushButton("显示")
        self._reveal_btn.setObjectName("secondaryButton")
        self._reveal_btn.clicked.connect(self._toggle_reveal)
        self._reveal_btn.hide()
        buttons.addWidget(self._reveal_btn)
        self._plain_btn = QPushButton("复制纯文本")
        self._plain_btn.setObjectName("secondaryButton")
        self._plain_btn.clicked.connect(self._copy_plain)
        self._plain_btn.hide()
        buttons.addWidget(self._plain_btn)
        self._save_btn = QPushButton("保存为文件…")
        self._save_btn.setObjectName("secondaryButton")
        self._save_btn.clicked.connect(self._save_as_file)
        self._save_btn.hide()
        buttons.addWidget(self._save_btn)
        self._copy_btn = QPushButton("复制全部")
        self._copy_btn.setObjectName("primaryButton")
        self._copy_btn.clicked.connect(self._copy_all)
        buttons.addWidget(self._copy_btn)
        layout.addLayout(buttons)

    def show_item(self, item, image_service=None) -> None:
        """展示条目详情。image_service 预留（缩略图服务，当前直接用文件加载）。"""
        self._item = item
        self._revealed = False
        self._highlighter = None
        self._meta.setText(self._meta_text(item))
        self._apply_view()
        self._resize_to_content()
        self._show_near_cursor()

    # ---- 视图派发 ----

    def _apply_view(self) -> None:
        """按 (类型, 敏感, 是否 Reveal) 切换内容视图与按钮。"""
        item = self._item
        self._image.hide()
        self._text.hide()
        self._code.hide()
        self._highlighter = None

        # 敏感内容：Reveal 前一律文本视图 + 遮蔽（§9.19），代码条目同样遮蔽
        if item.sensitive and not self._revealed:
            self._text.setPlainText(self._mask_content(item))
            self._text.show()
            self._reveal_btn.setText("显示")
        elif item.type == "image" and item.file_path:
            pix = QPixmap(item.file_path)
            if not pix.isNull():
                pix = pix.scaled(_MAX_WIDTH - 60, _MAX_HEIGHT - 120,
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
                self._image.setPixmap(pix)
                self._image.show()
        elif item.type == "file":
            self._text.setPlainText(item.file_path or item.content)
            self._text.show()
        elif item.type == "code":
            self._code.setPlainText(item.content or "")
            self._code.setFont(mono_font(12))
            from ui.code_highlighter import CodeHighlighter as _HL

            self._highlighter = _HL(self._code.document(), item.language)
            self._code.show()
            self._reveal_btn.setText("隐藏")
        else:
            self._text.setPlainText(item.content or item.preview)
            self._text.show()

        is_code = item.type == "code" and (not item.sensitive or self._revealed)
        self._plain_btn.setVisible(is_code)
        self._save_btn.setVisible(is_code)
        self._reveal_btn.setVisible(bool(item.sensitive))
        self._copy_btn.setText("复制" if is_code else "复制全部")

    def _mask_content(self, item) -> str:
        from services.sensitive_detector import mask

        return mask(item.content or item.preview, item.sensitive_type)

    def _toggle_reveal(self) -> None:
        self._revealed = not self._revealed
        self._apply_view()
        self._resize_to_content()

    # ---- 操作 ----

    def _copy_all(self) -> None:
        from services.action_service import set_clipboard_item

        if self._item is not None and set_clipboard_item(self._item):
            logger.info("详情弹层复制: %s", self._item.type)

    def _copy_plain(self) -> None:
        from app.text_utils import strip_markdown
        from services.action_service import set_clipboard_text

        item = self._item
        if item is None:
            return
        content = (strip_markdown(item.content)
                   if item.language == "markdown" else item.content)
        if set_clipboard_text(content):
            logger.info("详情弹层复制纯文本: %s", item.type)

    def _save_as_file(self) -> None:
        """保存代码为文件：默认文件名按语言扩展名（§8.15），可修改。"""
        item = self._item
        if item is None or not item.content:
            return
        from services.code_detector import EXTENSIONS

        ext = EXTENSIONS.get(item.language, ".txt")
        default_name = f"untitled{ext}"
        path, _ = QFileDialog.getSaveFileName(
            self, "保存为文件", default_name,
            f"代码文件 (*{ext});;所有文件 (*)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(item.content)
            logger.info("代码已保存: %s", path)
        except OSError:
            logger.exception("保存代码失败: %s", path)

    # ---- 内部 ----

    def _meta_text(self, item) -> str:
        parts = []
        if item.sensitive:
            parts.append("🔐 敏感内容")  # §9.18
        if item.type == "code":
            from services.code_detector import LANGUAGE_EMOJI, LANGUAGE_NAMES

            lang = item.language or "code"
            name = LANGUAGE_NAMES.get(lang, lang)
            parts.append(f"{LANGUAGE_EMOJI.get(lang, '🧾')} {name}")
            if item.line_count:
                parts.append(f"{item.line_count} 行")
            if item.character_count:
                parts.append(f"{item.character_count} 字符")
        if item.created_at:
            parts.append(item.created_at)
        if item.type != "code":
            parts.append(item.type)  # code 已由语言徽标说明，避免「Python · code」冗余
        if item.type in ("image", "file") and item.preview:
            parts.append(item.preview)  # 图片/文件显示名称
        if item.source_app:
            parts.append(f"来自 {item.source_app}")
        if item.type == "file" and item.content and item.content != item.preview:
            parts.append(item.content)
        return " · ".join(parts)

    def _resize_to_content(self) -> None:
        screen = QGuiApplication.primaryScreen()
        geo = screen.availableGeometry()
        width = min(_MAX_WIDTH, geo.width() - 80)
        # 文本高度按内容估算（每行约 20px），封顶 _MAX_HEIGHT
        if self._code.isVisible():
            lines = max(1, self._code.document().lineCount())
            height = min(_MAX_HEIGHT, max(160, 40 + lines * 18 + 20))
        elif self._text.isVisible():
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
        (self._code if self._code.isVisible() else self._text).setFocus()
