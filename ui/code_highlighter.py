"""代码语法高亮：Pygments token 流 → QTextCharFormat（新增.md §8.7）。

- Pygments 懒导入（首次打开代码详情的一次性开销 ~100ms，不拖累启动）
- 至少区分 8 类：Keyword / Function / String / Number / Comment /
  Variable(默认正文色) / Operator / Type
- 颜色按当前主题（浅/深）选取：取自 QApplication 调色板亮度判断
"""
import logging

from PySide6.QtGui import QColor, QFont, QFontDatabase, QSyntaxHighlighter, QTextCharFormat

logger = logging.getLogger(__name__)

# 浅色 / 深色代码配色（GitHub 系）
_LIGHT_COLORS = {
    "keyword": "#CF222E", "string": "#0A3069", "number": "#0550AE",
    "comment": "#6E7781", "function": "#8250DF", "operator": "#CF222E",
    "type": "#953800",
}
_DARK_COLORS = {
    "keyword": "#FF7B72", "string": "#A5D6FF", "number": "#79C0FF",
    "comment": "#8B949E", "function": "#D2A8FF", "operator": "#FF7B72",
    "type": "#FFA657",
}


class CodeHighlighter(QSyntaxHighlighter):
    """Pygments 驱动的 QSyntaxHighlighter（懒加载 lexer，换内容时重建）。"""

    def __init__(self, document, language: str):
        super().__init__(document)
        self._lexer = None
        if language:
            from pygments.lexers import get_lexer_by_name

            from services.code_detector import PYGMENTS_ALIASES

            alias = PYGMENTS_ALIASES.get(language)
            if alias:
                try:
                    self._lexer = get_lexer_by_name(alias, stripnl=False)
                except Exception:
                    logger.warning("Pygments 无 %s 的 lexer，降级为无高亮", language)
        self._formats = self._build_formats()
        if self._lexer is not None:
            self.rehighlight()

    # ---- 高亮 ----

    def highlightBlock(self, text: str) -> None:
        if self._lexer is None or not text:
            return
        from pygments import lex

        try:
            pos = 0
            for token, value in lex(text, self._lexer):
                key = _token_key(token, self._formats)
                if key is not None and value:
                    self.setFormat(pos, len(value), self._formats[key])
                pos += len(value)
        except Exception:
            logger.warning("Pygments 高亮失败，降级为无高亮", exc_info=True)

    # ---- 内部 ----

    @classmethod
    def _build_formats(cls) -> dict:
        """pygments token 类 → QTextCharFormat（8 类语义，其余用正文默认色）。"""
        from pygments.token import Comment, Keyword, Name, Number, Operator, String

        category = {
            Keyword: "keyword", Keyword.Constant: "keyword",
            Keyword.Type: "type", Name.Function: "function",
            Name.Class: "type", Name.Decorator: "keyword",
            String: "string", String.Doc: "comment",
            Number: "number", Comment: "comment", Comment.Special: "comment",
            Operator: "operator", Operator.Word: "keyword",
        }
        palette = _DARK_COLORS if cls._is_dark() else _LIGHT_COLORS
        formats = {}
        for token, category_name in category.items():
            color = palette.get(category_name)
            if color is None:
                continue
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            if category_name in ("keyword", "operator", "type"):
                fmt.setFontWeight(600)  # 关键字加粗
            formats[token] = fmt
        return formats

    @staticmethod
    def _is_dark() -> bool:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return False
        return app.palette().window().color().lightness() < 128


def _token_key(token, formats: dict):
    """Pygments token → formats 表键（沿类型继承链找最近匹配，如
    Keyword.Constant → Keyword）。无匹配返回 None（用正文默认色）。"""
    for cls in type(token).__mro__[1:]:
        if cls in formats:
            return cls
    return None


def mono_font(pixel_size: int = 12) -> QFont:
    """等宽字体（macOS 字体栈：SF Mono → Menlo → Monaco → 兜底）。"""
    for family in ("SF Mono", "Menlo", "Monaco", "Courier New"):
        if QFontDatabase.hasFamily(family):
            font = QFont(family)
            font.setPixelSize(pixel_size)
            return font
    font = QFont("monospace")
    font.setPixelSize(pixel_size)
    return font
