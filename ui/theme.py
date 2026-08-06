"""主题：浅色 / 深色 / 跟随系统（DEVELOPMENT.md §6 界面设计）。

TODO: 完整调色板与 qss（resources/theme/*.qss），此处为最小骨架。
"""
import logging

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)

_DARK_PALETTE = {
    "window": QColor("#1e1e1e"),
    "windowText": QColor("#e8e8e8"),
    "base": QColor("#252526"),
    "alternateBase": QColor("#2d2d30"),
    "text": QColor("#e8e8e8"),
    "button": QColor("#333337"),
    "buttonText": QColor("#e8e8e8"),
    "highlight": QColor("#0a84ff"),
    "highlightedText": QColor("#ffffff"),
}


def apply_theme(app: QApplication, mode: str = "system") -> None:
    """mode: system / light / dark。system 跟随系统外观。"""
    if mode == "system":
        scheme = app.styleHints().colorScheme()
        mode = "dark" if scheme == 1 else "light"  # Qt.ColorScheme.Dark == 1
        logger.info("跟随系统主题: %s", mode)

    if mode == "dark":
        palette = QPalette()
        for role_name, color in _DARK_PALETTE.items():
            role = getattr(QPalette.ColorRole, role_name.capitalize(), None)
            if role is not None:
                palette.setColor(role, color)
        app.setPalette(palette)
    else:
        app.setPalette(app.style().standardPalette())
    logger.info("主题已应用: %s", mode)
