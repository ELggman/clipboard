"""UI 层测试（offscreen）：历史列表 delegate 布局、主题滚动条。"""
import os
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtCore import QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from app.types import ClipboardItem
from ui.history_view import ROLE_ITEM, ROW_HEIGHT, THUMB_ROW_HEIGHT, HistoryView

pytest_app = QApplication.instance() or QApplication([])


def _png_bytes(color: str = "red", size: int = 64) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (size, size), color).save(buf, "PNG")
    return buf.getvalue()


def _size_hint(view: HistoryView, row: int) -> QRect:
    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 400, 40)
    return view._list.itemDelegate().sizeHint(opt, view._model.index(row, 0))


def test_history_row_layouts(tmp_path):
    """图片条目行高 > 文本条目；缩略图渲染不崩。"""
    from services.image_service import ImageService

    service = ImageService(tmp_path / "img")
    path = service.save(_png_bytes("blue", 32))
    view = HistoryView()
    view.set_image_service(service)
    view.add_item(ClipboardItem(type="image", file_path=str(path), preview="thumb.png"))
    view.add_item(ClipboardItem(type="text", content="hello"))

    # add_item 两次都插在行 0：后加的文本在行 0，图片在行 1
    img_h = _size_hint(view, 1).height()
    txt_h = _size_hint(view, 0).height()
    assert img_h == THUMB_ROW_HEIGHT
    assert txt_h == ROW_HEIGHT
    assert img_h > txt_h

    # paint 冒烟：真实渲染一遍（含缩略图绘制路径）
    view.resize(400, 300)
    view.show()
    pytest_app.processEvents()
    assert view.grab().isNull() is False
    view.close()


def test_history_show_filename_toggle(tmp_path):
    """开关关闭时不崩，布局仍按图片条目走。"""
    from services.image_service import ImageService

    service = ImageService(tmp_path / "img")
    path = service.save(_png_bytes("blue", 32))
    view = HistoryView()
    view.set_image_service(service)
    view.set_show_image_filename(False)
    view.add_item(ClipboardItem(type="image", file_path=str(path), preview="thumb.png"))
    assert _size_hint(view, 0).height() == THUMB_ROW_HEIGHT


def test_history_missing_image_file(tmp_path):
    """文件缺失（缩略图为 None）时优雅降级：布局不变、渲染不崩。"""
    view = HistoryView()
    view.add_item(ClipboardItem(
        type="image", file_path=str(tmp_path / "gone.png"), preview="gone.png"))
    view.resize(400, 200)
    view.show()
    pytest_app.processEvents()
    view.grab()
    assert view._model.rowCount() == 1
    view.close()


def test_history_scale_responsive(tmp_path):
    """窗口放大 → 行高等比例放大（基准 380 宽，scale=宽/380）。"""
    from services.image_service import ImageService

    service = ImageService(tmp_path / "img")
    path = service.save(_png_bytes("blue", 32))
    view = HistoryView()
    view.set_image_service(service)
    view.add_item(ClipboardItem(type="image", file_path=str(path), preview="thumb.png"))
    view.add_item(ClipboardItem(type="text", content="hello"))

    view.resize(380, 500)  # 基准档（隐藏控件 resize 事件延迟到 show，须先 show）
    view.show()
    pytest_app.processEvents()
    assert view._delegate._scale == 1.0
    base_img = _size_hint(view, 1).height()  # 图片在行 1（text 后加）
    base_txt = _size_hint(view, 0).height()

    view.resize(760, 500)  # 2 倍宽
    pytest_app.processEvents()
    assert view._delegate._scale == 2.0
    assert _size_hint(view, 1).height() == base_img * 2
    assert _size_hint(view, 0).height() == base_txt * 2
    view.close()


def test_history_caption_wraps_long_filename(tmp_path):
    """文件名放不下时换行：行高随行数增高（放大后一行放得下则不换行）。"""
    from services.image_service import ImageService

    service = ImageService(tmp_path / "img")
    path = service.save(_png_bytes("blue", 32))
    long_name = "very_long_screenshot_filename_2026_08_06_10_30_am_from_ide_export.png"
    view = HistoryView()
    view.set_image_service(service)
    view.add_item(ClipboardItem(type="image", file_path=str(path), preview=long_name))
    assert _size_hint(view, 0).height() > THUMB_ROW_HEIGHT  # 两行文件名 → 更高

    # 放大后可用宽度翻倍 → 一行放得下 → 回到基准行高
    view.resize(900, 500)
    view.show()
    pytest_app.processEvents()
    assert view._delegate._scale > 1.0
    assert _size_hint(view, 0).height() >= THUMB_ROW_HEIGHT
    view.close()


def test_history_set_items_restores():
    """set_items 整体回填（启动恢复路径）。"""
    view = HistoryView()
    items = [ClipboardItem(type="text", content=f"item {i}") for i in range(3)]
    view.set_items(items)
    assert view._model.rowCount() == 3
    first = view._model.index(0, 0).data(ROLE_ITEM)
    assert first.content == "item 0"  # 列表第一行 = items[0]（最新在前）


def test_quick_paste_popup_enter_selects(tmp_path):
    """Quick Paste：populate 后按 Enter 发出 selected 信号并关闭。"""
    from PySide6.QtTest import QTest

    from ui.quick_paste_popup import QuickPastePopup

    popup = QuickPastePopup()
    picked = []
    popup.selected.connect(lambda item: picked.append(item))
    items = [
        ClipboardItem(type="text", content="first item"),
        ClipboardItem(type="url", content="https://example.com"),
    ]
    popup.populate(items)
    pytest_app.processEvents()
    assert popup._list.count() == 2
    assert popup._list.currentRow() == 0

    QTest.keyClick(popup._list, Qt.Key.Key_Return)
    assert len(picked) == 1
    assert picked[0].content == "first item"
    assert not popup.isVisible()  # 选择后自动关闭
    popup.deleteLater()


def test_main_window_search_filters(tmp_path):
    """搜索栏接线：输入过滤列表，清空恢复完整历史。"""
    from services import history_service
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.main_window import MainWindow

    engine = create_db_engine(tmp_path / "s.db")
    migrate(engine)
    for content in ("mysql install", "postgres guide", "docker compose"):
        item = ClipboardItem(type="text", content=content)
        import hashlib
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)

    w = MainWindow()
    w.set_search(engine)
    w.load_history(history_service.list_recent(engine))
    w.show()
    pytest_app.processEvents()
    view = w._pages.widget(0)
    assert view._model.rowCount() == 3

    # 输入 "mysql" → 防抖 150ms 后过滤
    w._search.setText("mysql")
    QTest.qWait(250)  # 等待防抖定时器触发
    assert view._model.rowCount() == 1
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "mysql install"

    # 清空 → 恢复
    w._search.clear()
    QTest.qWait(250)
    assert view._model.rowCount() == 3
    w.close()


def test_theme_scrollbar_qss():
    """主题 QSS 含滚动条样式且无未替换占位符。"""
    from ui.theme import DARK, build_stylesheet

    qss = build_stylesheet(DARK)
    assert "QScrollBar::handle:vertical" in qss
    assert "$" not in qss
