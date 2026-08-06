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
from PySide6.QtWidgets import QApplication, QDialog, QPushButton, QStyleOptionViewItem

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


def test_context_menu_copy_action(tmp_path):
    """右键菜单：复制动作把内容写回剪贴板（触发式测试，不 exec 菜单）。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString

    from ui.history_view import HistoryView

    view = HistoryView()
    item = ClipboardItem(type="text", content="menu copy target", id=1)
    view.add_item(item)
    menu = view._build_menu(item)

    labels = [a.text() for a in menu.actions()]
    assert labels == ["复制", "置顶", "收藏", "", "删除"]  # "" = 分隔线

    menu.actions()[0].trigger()  # 复制
    pb = NSPasteboard.generalPasteboard()
    assert pb.stringForType_(NSPasteboardTypeString) == "menu copy target"


def test_context_menu_pin_action(tmp_path):
    """右键菜单：置顶动作写库并触发刷新回调。"""
    from services import history_service
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "m.db")
    migrate(engine)
    item = ClipboardItem(type="text", content="pin me")
    import hashlib

    item.hash = hashlib.sha256(b"pin me").hexdigest()
    history_service.save_item(engine, item)

    refreshed = []
    view = HistoryView()
    view.add_item(item)
    view.set_menu_context(engine, None, lambda: refreshed.append(True))
    menu = view._build_menu(item)
    menu.actions()[1].trigger()  # 置顶
    assert refreshed == [True]
    assert history_service.list_recent(engine)[0].pinned == 1

    # 再次构建菜单：显示「取消置顶」
    menu2 = view._build_menu(item)
    assert menu2.actions()[1].text() == "取消置顶"


def test_context_menu_actions_submenu(tmp_path):
    """右键菜单：Actions 子菜单列出可用 Action，触发执行并写回剪贴板。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString

    from services.action_service import ActionService
    from ui.history_view import HistoryView

    view = HistoryView()
    view.set_menu_context(None, ActionService(), None)
    item = ClipboardItem(type="text", content='{"a": 1}')
    view.add_item(item)
    menu = view._build_menu(item)

    # 用 view 持有的子菜单引用（shiboken 对 QAction.menu() 重新包装会失效）
    submenu = view._active_menus[-1]
    names = [a.text() for a in submenu.actions()]
    assert "JSON 格式化" in names  # Actions 名称已中文化

    json_action = next(a for a in submenu.actions() if a.text() == "JSON 格式化")
    json_action.trigger()
    pb = NSPasteboard.generalPasteboard()
    assert pb.stringForType_(NSPasteboardTypeString) == '{\n  "a": 1\n}'


def test_detail_popup_text_select_and_copy():
    """详情弹层：全文显示 + 可选中部分复制 + 复制全部按钮。"""
    from PySide6.QtGui import QTextCursor

    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    content = "这是一个很长的文本，用于验证详情弹层的全文显示与部分复制功能。"
    item = ClipboardItem(type="text", content=content, source_app="微信",
                         created_at="08-06 18:00")
    popup.show_item(item)
    pytest_app.processEvents()

    assert popup.isVisible()
    assert popup._text.toPlainText() == content          # 全文显示
    assert "微信" in popup._meta.text()                   # 来源软件显示
    assert popup._image.isHidden()                        # 文本条目不显示图片

    # 选中部分内容：选择机制断言（offscreen 无法模拟 Cmd+C 复制，
    # 剪贴板回写行为留真实窗口 e2e 验证；QTextEdit 的选中复制是 Qt 原生能力）
    cursor = popup._text.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)  # 选中前 4 个字符
    popup._text.setTextCursor(cursor)
    assert popup._text.textCursor().selectedText() == content[:4]  # 选择生效
    assert popup._text.textCursor().hasSelection()

    # 复制全部按钮
    from AppKit import NSPasteboard, NSPasteboardTypeString

    popup._copy_all()
    assert NSPasteboard.generalPasteboard().stringForType_(
        NSPasteboardTypeString) == content
    popup.deleteLater()


def test_detail_popup_image(tmp_path):
    """图片条目：详情弹层显示大图 + 文件名。"""
    from io import BytesIO

    from PIL import Image as PILImage

    from ui.item_detail_popup import ItemDetailPopup

    buf = BytesIO()
    PILImage.new("RGB", (64, 64), "green").save(buf, "PNG")
    img_path = tmp_path / "big.png"
    img_path.write_bytes(buf.getvalue())

    popup = ItemDetailPopup()
    popup.show_item(ClipboardItem(type="image", file_path=str(img_path),
                                  preview="big.png", source_app="微信"))
    pytest_app.processEvents()
    assert popup._image.isVisible()
    assert not popup._image.pixmap().isNull()
    assert "big.png" in popup._meta.text()
    popup.deleteLater()


def test_history_item_clicked_signal(tmp_path):
    """单击历史条目发出 item_activated（详情弹层入口）。"""
    from services.image_service import ImageService

    service = ImageService(tmp_path / "img")
    view = HistoryView()
    view.set_image_service(service)
    item = ClipboardItem(type="text", content="click me", preview="click me")
    view.add_item(item)
    view.show()
    pytest_app.processEvents()

    activated = []
    view.item_activated.connect(lambda it: activated.append(it))
    view.resize(400, 200)
    pytest_app.processEvents()
    # 点击行 0 中部（viewport 坐标）
    QTest.mouseClick(view._list.viewport(), Qt.MouseButton.LeftButton,
                     pos=view._list.visualRect(view._model.index(0, 0)).center())
    assert len(activated) == 1
    assert activated[0].content == "click me"
    view.close()


def test_snippets_view_save_and_copy(tmp_path):
    """片段页：新建保存 → 列表出现；复制渲染变量到剪贴板。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString

    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.snippets_view import SnippetsView

    engine = create_db_engine(tmp_path / "s.db")
    migrate(engine)
    view = SnippetsView()
    view.set_context(engine)
    assert view._list.count() == 0

    # 新建 + 保存
    view._new_snippet()
    view._name.setText("日期")
    view._content.setPlainText("今天：{{date}}")
    view._save()
    assert view._list.count() == 1

    # 复制（渲染变量）
    view._copy()
    clip = NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)
    assert clip.startswith("今天：") and "{{" not in clip
    view.close()


def test_collections_view_create_and_items(tmp_path):
    """收藏夹页：创建收藏夹 → 条目列表加载。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service
    from ui.collections_view import CollectionsView

    engine = create_db_engine(tmp_path / "c.db")
    migrate(engine)
    view = CollectionsView()
    view.set_context(engine)
    assert view._list.count() == 1  # 只有「★ 收藏」虚拟项

    collection_service.create_collection(engine, "工作")
    view.reload()
    assert view._list.count() == 2  # 「★ 收藏」虚拟项 + 收藏夹
    assert "★ 收藏" in view._list.item(0).text()
    assert "工作" in view._list.item(1).text()

    # 选中真实收藏夹 → 空条目
    view._list.setCurrentRow(1)
    assert view._model.rowCount() == 0
    view.close()


def test_timeline_view_grouped(tmp_path):
    """时间线页：分段选择器 + 按时间段过滤 + 更早按月分组。"""
    import datetime

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from sqlalchemy import text
    from ui.timeline_view import TimelineView

    engine = create_db_engine(tmp_path / "t.db")
    migrate(engine)
    now = datetime.datetime.now()
    with engine.begin() as conn:
        for label, days, h in (("today item", 0, "ht"),
                               ("yesterday item", 1, "hy"),
                               ("old item", 40, "ho")):
            conn.execute(text(
                "INSERT INTO clipboard_items (type, content, preview, hash,"
                " favorite, pinned, created_at, updated_at) VALUES"
                " ('text', :c, :c, :h, 0, 0, :t, :t)"),
                {"c": label, "h": h, "t": now - datetime.timedelta(days=days)})

    view = TimelineView()
    view.set_context(engine)
    assert [view._tabs.item(i).text() for i in range(view._tabs.count())] \
        == ["今天", "昨天", "本周", "更早"]

    # 默认「今天」：只显示今天条目
    texts = [view._list.item(i).text() for i in range(view._list.count())]
    assert any("today item" in t for t in texts)
    assert not any("yesterday item" in t for t in texts)

    # 切「昨天」
    view._tabs.setCurrentRow(1)
    texts = [view._list.item(i).text() for i in range(view._list.count())]
    assert any("yesterday item" in t for t in texts)

    # 切「更早」：月份标题 + 旧条目
    view._tabs.setCurrentRow(3)
    texts = [view._list.item(i).text() for i in range(view._list.count())]
    assert any("月" in t for t in texts)          # 月份分组标题
    assert any("old item" in t for t in texts)
    assert not any("today item" in t for t in texts)
    view.close()


def test_history_menu_add_to_collection(tmp_path):
    """右键菜单「加入收藏夹」：收藏夹列表 + 触发加入。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service, history_service
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "m.db")
    migrate(engine)
    cid = collection_service.create_collection(engine, "收藏夹A")
    item = ClipboardItem(type="text", content="collect me")
    import hashlib

    item.hash = hashlib.sha256(b"collect me").hexdigest()
    history_service.save_item(engine, item)

    view = HistoryView()
    view.add_item(item)
    view.set_menu_context(engine, None, None)
    menu = view._build_menu(item)

    # 「收藏」子菜单：★ 快速收藏 + 收藏夹列表 + 新建收藏夹…
    # （用 view 持有的引用，shiboken 对 QAction.menu() 重新包装会失效）
    sub = view._active_menus[1]
    names = [a.text() for a in sub.actions()]
    assert names[0] == "★ 快速收藏"
    assert "收藏夹A" in names
    assert names[-1] == "新建收藏夹…"

    # 触发收藏夹 A（跳过首项快速收藏与分隔符）
    coll_action = next(a for a in sub.actions() if a.text() == "收藏夹A")
    coll_action.trigger()
    assert collection_service.list_items(engine, cid)[0].content == "collect me"


def test_favorite_feedback_and_virtual_collection(tmp_path):
    """收藏反馈链路：★ 标记 + feedback 信号 + 收藏夹页「★ 收藏」可见。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from ui.collections_view import CollectionsView
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "f.db")
    migrate(engine)
    item = ClipboardItem(type="text", content="fav target")
    import hashlib

    item.hash = hashlib.sha256(b"fav target").hexdigest()
    history_service.save_item(engine, item)

    # 历史页：收藏子菜单「★ 快速收藏」→ feedback 信号 + 条目 ★ 标记
    view = HistoryView()
    view.add_item(item)
    view.set_menu_context(engine, None, None)
    messages = []
    view.feedback.connect(messages.append)
    menu = view._build_menu(item)
    fav_menu = view._active_menus[1]  # 「收藏」子菜单（持有引用）
    fav_menu.actions()[0].trigger()  # ★ 快速收藏
    assert messages == ["已收藏"]
    assert item.favorite == 1
    from ui.history_view import HistoryDelegate

    assert "★" in HistoryDelegate._meta_line(item)

    # 收藏夹页：「★ 收藏」虚拟项显示该条目
    cv = CollectionsView()
    cv.set_context(engine)
    assert "★ 收藏" in cv._list.item(0).text()
    cv._list.setCurrentRow(0)  # 选中虚拟项
    assert cv._model.rowCount() == 1
    assert cv._model.index(0, 0).data(ROLE_ITEM).content == "fav target"
    cv.close()


def test_name_dialog_chinese_buttons_and_return():
    """Apple 风格命名对话框：中文按钮、回车确认、text() 取值。"""
    from PySide6.QtTest import QTest

    from ui.dialogs import NameDialog

    dlg = NameDialog("新建收藏夹", "名称：", confirm_text="创建")
    dlg.show()
    pytest_app.processEvents()
    btn_texts = [b.text() for b in dlg.findChildren(QPushButton)]
    assert "取消" in btn_texts and "创建" in btn_texts  # 无英文 OK

    dlg._edit.setText("工作")
    QTest.keyClick(dlg._edit, Qt.Key.Key_Return)  # 回车确认
    assert dlg.result() == QDialog.DialogCode.Accepted
    assert dlg.text() == "工作"
    dlg.deleteLater()


def test_history_menu_delete(tmp_path):
    """右键「删除」：菜单含删除项，触发后 DB 删除 + 反馈 + 刷新。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from sqlalchemy import text
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "d.db")
    migrate(engine)
    item = ClipboardItem(type="text", content="delete me")
    import hashlib

    item.hash = hashlib.sha256(b"delete me").hexdigest()
    history_service.save_item(engine, item)

    refreshed = []
    messages = []
    view = HistoryView()
    view.add_item(item)
    view.set_menu_context(engine, None, lambda: refreshed.append(True))
    view.feedback.connect(messages.append)
    menu = view._build_menu(item)
    assert menu.actions()[-1].text() == "删除"  # 分隔线后最后一项

    menu.actions()[-1].trigger()
    assert messages == ["已删除"]
    assert refreshed == [True]
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM clipboard_items WHERE id = :id"),
            {"id": item.id}).scalar()
    assert count == 0


def test_collection_context_menu_delete(tmp_path):
    """收藏夹右键删除（回归：此前误调条目删除方法导致 AttributeError）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service
    from ui.collections_view import CollectionsView

    engine = create_db_engine(tmp_path / "cd.db")
    migrate(engine)
    cid = collection_service.create_collection(engine, "待删")
    view = CollectionsView()
    view.set_context(engine)
    assert view._list.count() == 2  # ★ 收藏 + 待删

    # 模拟右键菜单删除（与 _on_list_menu 相同的动作构建）
    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    view._active_menus.append(menu)
    menu.addAction("删除").triggered.connect(
        lambda: view._delete_collection(cid))
    menu.actions()[0].trigger()
    assert view._list.count() == 1  # 只剩内置 ★ 收藏
    remaining = collection_service.list_collections(engine)
    assert len(remaining) == 1
    assert remaining[0]["name"] == collection_service.FAVORITES_NAME
    view.close()


def test_name_dialog_buttons_same_size():
    """弹窗两个按钮同尺寸（同 padding 同文本长度），取消为灰色次要样式。"""
    from ui.dialogs import NameDialog

    dlg = NameDialog("测试", "名称：", confirm_text="创建")
    dlg.show()
    pytest_app.processEvents()
    buttons = dlg.findChildren(QPushButton)
    cancel = next(b for b in buttons if b.text() == "取消")
    confirm = next(b for b in buttons if b.text() == "创建")
    assert cancel.objectName() == "secondaryButton"
    assert confirm.objectName() == "primaryButton"
    # 同 padding → sizeHint 宽度一致（同字号同文本长）
    assert cancel.sizeHint().width() == confirm.sizeHint().width()
    dlg.deleteLater()


def test_confirm_dialog_destructive_button():
    """确认对话框：红色 destructive 按钮 + 取消灰按钮。"""
    from ui.dialogs import ConfirmDialog

    dlg = ConfirmDialog("清空历史", "确定？", confirm_text="清空")
    dlg.show()
    pytest_app.processEvents()
    buttons = dlg.findChildren(QPushButton)
    confirm = next(b for b in buttons if b.text() == "清空")
    cancel = next(b for b in buttons if b.text() == "取消")
    assert confirm.objectName() == "destructiveButton"
    assert cancel.objectName() == "secondaryButton"
    dlg.deleteLater()


def test_clean_data_dialog_query_and_delete(tmp_path):
    """清理数据弹窗：筛选查询 + 删除（不影响收藏夹快照）。"""
    import datetime

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service, history_service
    from sqlalchemy import text
    from ui.clean_data_dialog import CleanDataDialog

    engine = create_db_engine(tmp_path / "cl.db")
    migrate(engine)
    import hashlib

    # 40 天前的旧条目 + 今天的新条目
    old = ClipboardItem(type="text", content="old entry")
    old.hash = hashlib.sha256(b"old entry").hexdigest()
    new = ClipboardItem(type="text", content="new entry")
    new.hash = hashlib.sha256(b"new entry").hexdigest()
    history_service.save_item(engine, old)
    history_service.save_item(engine, new)
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE clipboard_items SET created_at = :t WHERE content = 'old entry'"),
            {"t": datetime.datetime.now() - datetime.timedelta(days=40)})
    # 收藏 old（验证清理不影响收藏快照）
    cid = collection_service.create_collection(engine, "保留")
    collection_service.add_item(engine, cid, old)

    dialog = CleanDataDialog(engine)
    dialog.show()
    pytest_app.processEvents()
    # 默认查询（7 天前）→ 只有 old
    assert dialog._list.count() == 1
    assert "old entry" in dialog._list.item(0).text()

    # 切「全部历史」→ 两条都在
    dialog._days.setCurrentIndex(3)
    dialog._query()
    assert dialog._list.count() == 2

    # 删除 old（_delete 内有模态确认框，测试直接调服务 + 刷新预览）
    old_id = next(i.id for i in dialog._items if i.content == "old entry")
    history_service.delete_items(engine, [old_id])
    dialog._query()
    assert dialog._list.count() == 1  # 全部历史只剩 new
    assert "new entry" in dialog._list.item(0).text()
    with engine.connect() as conn:
        remaining = [r[0] for r in conn.execute(text(
            "SELECT content FROM clipboard_items")).fetchall()]
    assert remaining == ["new entry"]
    # 收藏快照不受影响
    assert collection_service.list_items(engine, cid)[0].content == "old entry"
    dialog.close()


def test_theme_scrollbar_qss():
    """主题 QSS 含滚动条样式且无未替换占位符。"""
    from ui.theme import DARK, build_stylesheet

    qss = build_stylesheet(DARK)
    assert "QScrollBar::handle:vertical" in qss
    assert "$" not in qss
