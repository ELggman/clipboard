"""UI 层测试（offscreen）：历史列表缩略图、主题滚动条。"""
import os
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from app.types import ClipboardItem

pytest_app = QApplication.instance() or QApplication([])


def _png_bytes(color: str = "red", size: int = 64) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


def test_history_view_image_thumbnail(tmp_path):
    """image 条目在列表里渲染出缩略图（懒加载经 ImageService）。"""
    from services.image_service import ImageService
    from ui.history_view import HistoryView

    service = ImageService(tmp_path / "img")
    path = service.save(_png_bytes("blue", 32))
    view = HistoryView()
    view.set_image_service(service)

    item = ClipboardItem(type="image", file_path=str(path), preview="thumb.png")
    view.add_item(item)
    row = view._list.item(0)
    assert row.icon().isNull() is False, "image 条目应有缩略图图标"

    # 文本条目无图标
    view.add_item(ClipboardItem(type="text", content="hello"))
    assert view._list.item(0).icon().isNull() is True


def test_history_view_thumbnail_missing_file(tmp_path):
    """文件缺失时优雅降级：无图标不崩溃。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    view.add_item(ClipboardItem(
        type="image", file_path=str(tmp_path / "gone.png"), preview="gone.png"))
    assert view._list.item(0).icon().isNull() is True


def test_theme_scrollbar_qss():
    """主题 QSS 含滚动条样式且无未替换占位符。"""
    from ui.theme import DARK, build_stylesheet

    qss = build_stylesheet(DARK)
    assert "QScrollBar::handle:vertical" in qss
    assert "$" not in qss
