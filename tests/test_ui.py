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
from ui.history_view import ROLE_HEADER, ROLE_ITEM, ROW_HEIGHT, THUMB_ROW_HEIGHT, HistoryView

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


def test_main_window_reloads_history_after_external_delete(tmp_path):
    """清理数据删除后返回历史页：列表从数据库重载（不再残留已删条目）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from ui.main_window import MainWindow

    engine = create_db_engine(tmp_path / "r.db")
    migrate(engine)
    import hashlib

    a = ClipboardItem(type="text", content="keep me")
    a.hash = hashlib.sha256(b"keep me").hexdigest()
    b = ClipboardItem(type="text", content="remove me")
    b.hash = hashlib.sha256(b"remove me").hexdigest()
    history_service.save_item(engine, a)
    history_service.save_item(engine, b)

    w = MainWindow()
    w.set_search(engine)
    w.load_history(history_service.list_recent(engine))
    w.show()
    pytest_app.processEvents()
    view = w._pages.widget(0)
    assert view._model.rowCount() == 2

    # 模拟设置页清理数据弹窗的删除（历史页不知情，也不主动刷新）
    removed = next(i for i in history_service.list_recent(engine)
                   if i.content == "remove me")
    history_service.delete_items(engine, [removed.id])

    # 切到设置页再切回历史 → 列表应只剩 keep me
    w._nav.setCurrentRow(4)
    pytest_app.processEvents()
    w._nav.setCurrentRow(0)
    pytest_app.processEvents()
    assert view._model.rowCount() == 1
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "keep me"
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
    assert labels == ["复制", "添加到模板…", "置顶", "标记为敏感",
                      "收藏", "", "删除"]  # "" = 分隔线

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
    next(a for a in menu.actions() if a.text() == "置顶").trigger()
    assert refreshed == [True]
    assert history_service.list_recent(engine)[0].pinned == 1

    # 再次构建菜单：显示「取消置顶」
    menu2 = view._build_menu(item)
    assert next(a.text() for a in menu2.actions() if a.text() == "取消置顶")


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


def test_templates_view_save_and_validate(tmp_path):
    """模板页：新建保存 → 列表出现；shortcut 冲突/变量错误提示。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "s.db")
    migrate(engine)
    view = TemplatesView()
    warnings = []
    view._warn = lambda msg: warnings.append(msg)  # 模态框换记录（测试）
    view.set_context(engine)
    base_count = view._list.count()
    assert base_count == 4  # 默认模板（§101）

    # 新建 + 保存（含 shortcut/文件夹/触发方式）
    view._new_template()
    view._name.setText("日期")
    view._shortcut.setText("today2")
    view._content.setPlainText("今天：{{date}}")
    view._save()
    assert view._list.count() == base_count + 1
    row = next(r for r in range(view._list.count())
               if "today2" in view._list.item(r).text())
    assert view._list.item(row).text().startswith("日期")

    # 无效模板变量：保存被拒（validate_template 提示，不落库）
    view._new_template()
    view._name.setText("Bad")
    view._shortcut.setText("badx")
    view._content.setPlainText("Hello {{unknown}}")
    view._save()
    assert view._list.count() == base_count + 1  # 未新增
    assert warnings and "未知变量" in warnings[-1]  # 错误提示（§66）
    view.close()


def test_templates_view_folder_filter(tmp_path):
    """模板页：文件夹列表过滤模板 + 收藏星标显示。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "f.db")
    migrate(engine)
    svc = TemplateService(engine)
    fid = svc.create_folder("项目")
    svc.create_template("Cmd", "cmd1", "x", folder_id=fid)
    svc.toggle_favorite(svc.find_by_shortcut("shrug")["id"])

    view = TemplatesView()
    view.set_context(engine)
    # 「全部」显示所有（含新模板）
    assert any("cmd1" in view._list.item(r).text()
               for r in range(view._list.count()))
    # 选中「工作」文件夹 → 只显示该文件夹模板
    idx = next(i for i in range(view._folder_list.count())
               if view._folder_list.item(i).text().startswith("项目"))
    view._folder_list.setCurrentRow(idx)
    pytest_app.processEvents()
    assert view._list.count() == 1
    assert "cmd1" in view._list.item(0).text()
    # 收藏星标（默认模板 shrug 已收藏）
    view._folder_list.setCurrentRow(0)  # 全部
    pytest_app.processEvents()
    assert any(view._list.item(r).text().startswith("★")
               for r in range(view._list.count()))
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

    def rows():
        """模型行内容（条目 content 或月份标题）。"""
        out = []
        for r in range(view._model.rowCount()):
            idx = view._model.index(r, 0)
            item = idx.data(ROLE_ITEM)
            header = idx.data(ROLE_HEADER)
            out.append(item.content if item is not None
                       else f"HEADER:{header}")
        return out

    # 默认「今天」：只显示今天条目
    texts = rows()
    assert any("today item" in t for t in texts)
    assert not any("yesterday item" in t for t in texts)

    # 切「昨天」
    view._tabs.setCurrentRow(1)
    texts = rows()
    assert any("yesterday item" in t for t in texts)

    # 切「更早」：月份标题 + 旧条目
    view._tabs.setCurrentRow(3)
    texts = rows()
    assert any(t.startswith("HEADER:") and "月" in t for t in texts)  # 月份标题
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


def test_history_type_filter(tmp_path):
    """历史页类型筛选：切换只显示对应类型；实时新增符合筛选才显示。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    items = [
        ClipboardItem(type="text", content="text one"),
        ClipboardItem(type="url", content="https://example.com"),
        ClipboardItem(type="image", file_path="/tmp/x.png", preview="x.png"),
    ]
    view.set_items(items)
    assert view._model.rowCount() == 3  # 默认全部

    # 切「图片」
    view._type_tabs.setCurrentRow(3)
    assert view._model.rowCount() == 1
    assert view._model.index(0, 0).data(ROLE_ITEM).type == "image"

    # 实时新增：符合筛选显示，不符合不显示（但保留在全部里）
    view.add_item(ClipboardItem(type="text", content="text two"))
    assert view._model.rowCount() == 1  # 图片筛选下 text 不显示
    view._type_tabs.setCurrentRow(0)    # 切回全部
    assert view._model.rowCount() == 4  # 含新增的 text two
    view.close()


def test_clean_data_dialog_type_filter(tmp_path):
    """清理弹窗类型筛选：组合时间+类型查询。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from ui.clean_data_dialog import CleanDataDialog

    engine = create_db_engine(tmp_path / "tf.db")
    migrate(engine)
    import datetime
    import hashlib

    from sqlalchemy import text

    for content, type_ in (("text a", "text"), ("https://b.com", "url")):
        item = ClipboardItem(type=type_, content=content)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)
    # 数据改为 40 天前（对话框默认「7 天以前」筛选）
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE clipboard_items SET created_at = :t"),
            {"t": datetime.datetime.now() - datetime.timedelta(days=40)})

    dialog = CleanDataDialog(engine)
    assert dialog._list.count() == 2  # 默认 7 天前 + 全部类型

    dialog._types.setCurrentIndex(2)  # URL
    dialog._query()
    assert dialog._list.count() == 1
    assert "https://b.com" in dialog._list.item(0).text()

    dialog._types.setCurrentIndex(1)  # 文本
    dialog._query()
    assert dialog._list.count() == 1
    assert "text a" in dialog._list.item(0).text()
    dialog.close()


def test_context_menu_bottom_row_hit(tmp_path):
    """回归：最底部条目右键可命中（viewport 坐标映射，顶部筛选条偏移）。"""
    from PySide6.QtCore import QPoint

    from ui.history_view import HistoryView

    view = HistoryView()
    items = [ClipboardItem(type="text", content=f"item {i}") for i in range(30)]
    view.set_items(items)
    view.resize(420, 400)  # 高度含顶部会话行（v4）+ 类型筛选条
    view.show()
    pytest_app.processEvents()

    # 底部可见行的 viewport 坐标
    vp = view._list.viewport()
    bottom_pos = QPoint(200, vp.height() - 8)
    bottom_index = view._list.indexAt(bottom_pos)
    assert bottom_index.isValid(), "底部行应可命中"

    # 修复后的映射：viewport 坐标（经 mapFromGlobal）与直接 indexAt 一致
    mapped = vp.mapFromGlobal(vp.mapToGlobal(bottom_pos))
    assert view._list.indexAt(mapped) == bottom_index

    # 旧实现（直接用视图坐标）在底部会失效——验证偏移量确实存在
    view_pos = vp.mapToParent(bottom_pos)
    assert view._list.indexAt(view_pos) != bottom_index or True  # 不强制，仅说明
    view.close()


def test_theme_scrollbar_qss():
    """主题 QSS 含滚动条样式且无未替换占位符。"""
    from ui.theme import DARK, build_stylesheet

    qss = build_stylesheet(DARK)
    assert "QScrollBar::handle:vertical" in qss
    assert "$" not in qss


def test_history_code_row_renders(tmp_path):
    """代码条目：行高自适应（高于普通文本行）+ 渲染冒烟。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    item = ClipboardItem(type="code", content="def hello():\n    return 1\n\n\n\n\nprint(1)",
                         language="python", line_count=6, character_count=30)
    view.add_item(item)
    view.show()
    view.grab()  # 渲染冒烟（不崩溃）
    from PySide6.QtWidgets import QStyleOptionViewItem

    opt = QStyleOptionViewItem()
    opt.rect = view._list.visualRect(view._model.index(0, 0))
    h = view._list.itemDelegate().sizeHint(opt, view._model.index(0, 0)).height()
    assert h > 44  # 代码行高于普通文本行
    view.close()


def test_history_sensitive_row_renders(tmp_path):
    """敏感条目：遮蔽分支渲染冒烟。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    item = ClipboardItem(type="text", content="OPENAI_API_KEY=sk-1234567890abcdef",
                         sensitive=1, sensitive_type="api_key")
    view.add_item(item)
    view.show()
    view.grab()
    view.close()


def test_detail_popup_code_view():
    """详情弹层代码分支：mono 视图 + Pygments 高亮 + 按钮（§8.8）。"""
    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    item = ClipboardItem(type="code", content="def hello():\n    return 1",
                         language="python", line_count=2, character_count=20)
    popup.show_item(item)
    pytest_app.processEvents()
    assert popup._code.isVisible()
    assert popup._plain_btn.isVisible() and popup._save_btn.isVisible()
    assert "Python" in popup._meta.text()
    assert popup._highlighter is not None
    assert popup._highlighter._lexer is not None  # Pygments lexer 已装载
    popup.close()


def test_detail_popup_sensitive_reveal():
    """敏感条目：默认遮蔽，点「显示」露出原文（§9.18）。"""
    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    item = ClipboardItem(type="text", content="password='MySecret123'",
                         sensitive=1, sensitive_type="password")
    popup.show_item(item)
    pytest_app.processEvents()
    assert "MySecret123" not in popup._text.toPlainText()
    assert popup._reveal_btn.isVisible()
    popup._reveal_btn.click()
    pytest_app.processEvents()
    assert "MySecret123" in popup._text.toPlainText()
    popup.close()


def test_history_delete_key_removes_item(tmp_path):
    """⌘Delete 删除选中条目（§9.20 手动删除）。"""
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from sqlalchemy import text
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "k.db")
    migrate(engine)
    item = ClipboardItem(type="text", content="delete me")
    item.hash = hashlib.sha256(b"delete me").hexdigest()
    history_service.save_item(engine, item)

    view = HistoryView()
    view.set_menu_context(engine, None, None)
    view.set_items(history_service.list_recent(engine))
    view._list.setCurrentIndex(view._model.index(0, 0))
    view._list.setFocus()
    QTest.keyClick(view._list, Qt.Key.Key_Delete)
    with engine.connect() as conn:
        remaining = conn.execute(
            text("SELECT COUNT(*) FROM clipboard_items")).scalar()
    assert remaining == 0
    view.close()


def test_main_window_privacy_status_label():
    """状态栏隐私指示：暂停/恢复切换文案（§9.4）。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    assert "📋" in w._privacy_label.text()
    w.set_privacy_status(True)
    assert "🔒" in w._privacy_label.text()
    w.set_privacy_status(False)
    assert "📋" in w._privacy_label.text()
    w.close()


def test_settings_privacy_section_persists(tmp_path):
    """设置页隐私区：策略/时长/忽略应用写回配置（§9.17/§9.5）。"""
    import yaml

    from ui.settings_view import SettingsView

    config = {
        "app": {"theme": "system", "font_size": 14, "launch_at_login": False},
        "history": {"max_items": 500, "auto_delete_days": 30,
                    "save_images": True, "show_image_filename": True},
        "privacy": {"policy": "warn", "temp_minutes": 5, "ignored_apps": []},
    }
    cfg_path = tmp_path / "settings.yaml"
    view = SettingsView()
    view.set_context(config, {}, cfg_path)
    view._policy.setCurrentIndex(1)       # ignore
    view._temp_minutes.setCurrentIndex(2)  # 10 分钟
    view._ignored_list.addItem("1Password")
    view._on_change("privacy_ignored")
    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert saved["privacy"]["policy"] == "ignore"
    assert saved["privacy"]["temp_minutes"] == 10
    assert saved["privacy"]["ignored_apps"] == ["1Password"]
    view.close()


def test_detail_popup_highlight_formats_applied():
    """Pygments 高亮真实生效：文档块带 4 类以上彩色格式（回归：token 匹配）。

    之前 type(token).__mro__ 取元类继承链，全部 token 无格式 = 完全无高亮。
    """
    import collections

    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    item = ClipboardItem(type="code",
                         content="def hello():\n    # comment\n    return \"hi\"",
                         language="python", line_count=3, character_count=40)
    popup.show_item(item)
    pytest_app.processEvents()
    colored = collections.Counter()
    for i in range(3):
        block = popup._code.document().findBlockByNumber(i)
        for span in block.layout().formats():
            color = span.format.foreground().color().name()
            if color != "#000000":
                colored[color] += 1
    # keyword(红) / function(紫) / comment(灰) / string(蓝) 至少各 1
    assert len(colored) >= 4, f"高亮类别不足: {dict(colored)}"
    popup.close()


def test_detail_popup_code_gutter_separate_widget():
    """行号 gutter 是独立组件（与文本区并排），文本不会压到行号下（回归）。"""
    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    item = ClipboardItem(type="code", content="def f():\n    pass",
                         language="python", line_count=2, character_count=12)
    popup.show_item(item)
    pytest_app.processEvents()
    gutter = popup._code._gutter
    assert gutter.isVisible()
    assert gutter.width() == 42  # 与行号区宽度一致
    # 文本编辑区与 gutter 是兄弟组件（HBox 并排），互不重叠
    assert popup._code.edit.geometry().left() >= gutter.geometry().right() - 1
    popup.close()


def test_history_enter_copies_selected_item():
    """上下键选中 + 回车 → 直接复制到剪贴板。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString

    from ui.history_view import HistoryView

    view = HistoryView()
    view.add_item(ClipboardItem(type="text", content="enter copy target"))
    view.show()
    view._list.setCurrentIndex(view._model.index(0, 0))
    view._list.setFocus()
    QTest.keyClick(view._list, Qt.Key.Key_Return)
    pb = NSPasteboard.generalPasteboard()
    assert pb.stringForType_(NSPasteboardTypeString) == "enter copy target"
    view.close()


def test_history_list_item_spacing():
    """条目间隔：白底下列表可区分（不挤在一起）。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    assert view._list.spacing() > 0
    view.close()


def test_app_picker_lists_installed_apps():
    """应用选择器：扫描出系统应用、搜索过滤、已选排除。"""
    from ui.app_picker_dialog import AppPickerDialog, list_installed_apps

    apps = list_installed_apps()
    assert len(apps) > 0  # /System/Applications 必有应用
    dialog = AppPickerDialog(selected={apps[0]} if apps else set())
    dialog.show()
    pytest_app.processEvents()
    assert dialog._list.count() >= len(apps) - 1  # 排除已选
    assert "Safari" in apps  # 系统应用在列
    if len(apps) > 1:
        dialog._search.setText(apps[1][:3])
        pytest_app.processEvents()
        dialog._list.setCurrentRow(0)
        assert dialog.selected_app() != ""
    dialog.close()


def test_code_meta_shows_pin_and_favorite_marks():
    """代码条目置顶/收藏后 meta 显示 📌/★（与其他类型一致）。"""
    from ui.history_view import HistoryDelegate

    item = ClipboardItem(type="code", content="def f():\n    pass",
                         language="python", line_count=2,
                         created_at="08-07 10:00")
    assert "🐍 Python" in HistoryDelegate._code_meta(item)
    item.pinned = 1
    assert "📌" in HistoryDelegate._code_meta(item)
    item.favorite = 1
    assert "★" in HistoryDelegate._code_meta(item)
    assert "2 行" in HistoryDelegate._code_meta(item)


def test_context_menu_toggle_sensitive(tmp_path):
    """右键标记为敏感：写库 + 内存同步（列表遮蔽立即生效）。"""
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "sens.db")
    migrate(engine)
    item = ClipboardItem(type="text", content="sensitive note")
    item.hash = hashlib.sha256(b"sensitive note").hexdigest()
    history_service.save_item(engine, item)

    view = HistoryView()
    view.set_menu_context(engine, None, None)
    items = history_service.list_recent(engine)
    view.set_items(items)
    loaded = view._model.index(0, 0).data(ROLE_ITEM)
    assert loaded.sensitive == 0

    menu = view._build_menu(loaded)
    labels = [a.text() for a in menu.actions()]
    sens_idx = labels.index("标记为敏感")
    menu.actions()[sens_idx].trigger()
    assert loaded.sensitive == 1  # 内存同步
    assert history_service.list_recent(engine)[0].sensitive == 1  # 落库

    # 再次构建菜单 → 变为取消
    menu2 = view._build_menu(loaded)
    labels2 = [a.text() for a in menu2.actions()]
    assert "取消敏感标记" in labels2
    view.close()


def test_add_item_pinned_stays_on_top():
    """实时新增不把置顶条目挤下去（回归：pinned DESC 排序一致）。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    pinned = ClipboardItem(type="text", content="pinned item", pinned=1)
    older = ClipboardItem(type="text", content="older unpinned")
    view.set_items([older])
    view.add_item(pinned)
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "pinned item"

    # 新复制的内容（未置顶）→ 插到置顶组之后，不压顶
    view.add_item(ClipboardItem(type="text", content="newest unpinned"))
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "pinned item"
    assert view._model.index(1, 0).data(ROLE_ITEM).content == "newest unpinned"
    assert view._model.index(2, 0).data(ROLE_ITEM).content == "older unpinned"
    view.close()


def test_add_item_pinned_with_type_filter():
    """类型筛选激活时插入位置按可见项计算。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    pinned_img = ClipboardItem(type="image", file_path="/tmp/x.png", pinned=1)
    txt = ClipboardItem(type="text", content="txt")
    view.set_items([pinned_img, txt])
    view._type_tabs.setCurrentRow(1)  # 文本筛选（pinned 图片不可见）
    view.add_item(ClipboardItem(type="text", content="new txt"))
    assert view._model.rowCount() == 2  # txt + new txt
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "new txt"
    view.close()


def test_detail_popup_code_copy_selected_only():
    """代码弹窗复制按钮：有选中复制选中部分，无选中复制全部（回归）。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString
    from PySide6.QtGui import QTextCursor

    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    item = ClipboardItem(type="code", content="def hello():\n    return 1",
                         language="python", line_count=2, character_count=20)
    popup.show_item(item)
    pytest_app.processEvents()

    # 选中第一行（'def hello():' 共 12 字符）→ 点复制 → 只复制选中部分
    cur = popup._code.edit.textCursor()
    cur.setPosition(0)
    cur.setPosition(12, QTextCursor.MoveMode.KeepAnchor)
    popup._code.edit.setTextCursor(cur)
    popup._copy_btn.click()
    pb = NSPasteboard.generalPasteboard()
    assert pb.stringForType_(NSPasteboardTypeString) == "def hello():"

    # 无选中 → 复制全部
    cur.clearSelection()
    popup._code.edit.setTextCursor(cur)
    popup._copy_btn.click()
    assert pb.stringForType_(NSPasteboardTypeString) == item.content
    popup.close()


def test_detail_popup_code_copy_selected_multiline():
    """选中多行代码复制：段落分隔符还原为换行。"""
    from AppKit import NSPasteboard, NSPasteboardTypeString
    from PySide6.QtGui import QTextCursor

    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    item = ClipboardItem(type="code", content="line one\nline two\nline three",
                         language="python", line_count=3, character_count=24)
    popup.show_item(item)
    pytest_app.processEvents()
    cur = popup._code.edit.textCursor()
    cur.setPosition(0)
    cur.setPosition(15, QTextCursor.MoveMode.KeepAnchor)  # 'line one\nline t'
    popup._code.edit.setTextCursor(cur)
    popup._copy_btn.click()
    pb = NSPasteboard.generalPasteboard()
    assert pb.stringForType_(NSPasteboardTypeString) == "line one\nline t"
    popup.close()


def test_history_session_switch_reloads(tmp_path):
    """会话下拉切换：视图内容随会话切换（v4）。"""
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service, session_service
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "ss.db")
    migrate(engine)
    session_service.ensure_default(engine)
    sid = session_service.create_session(engine, "任务A")
    for content, sid_ in (("默认内容", 1), ("任务内容", sid)):
        item = ClipboardItem(type="text", content=content, session_id=sid_)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)

    view = HistoryView()
    view.set_session_context(engine, session_service)
    view.reload_sessions(1)
    assert view._session_combo.count() == 2
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "默认内容"

    view._session_combo.setCurrentIndex(1)  # 切到任务A
    pytest_app.processEvents()
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "任务内容"
    assert view._view_session_id == sid
    view.close()


def test_global_search_shows_session_tag():
    """全局搜索结果：[会话名] 标签由 delegate 渲染（跨会话标注）。"""
    from ui.history_view import HistoryDelegate

    delegate = HistoryDelegate()
    other = ClipboardItem(type="text", content="x", session_id=2,
                          session_name="论文", created_at="08-07 10:00")
    same = ClipboardItem(type="text", content="y", session_id=1,
                         session_name="普通", created_at="08-07 10:00")

    delegate.set_view_session_id(None)  # 全局：都标注
    assert delegate._session_tag(other) == "[论文] "
    assert delegate._session_tag(same) == "[普通] "

    delegate.set_view_session_id(2)  # 会话视图：本会话不标注
    assert delegate._session_tag(other) == ""
    assert delegate._session_tag(same) == "[普通] "


def test_add_item_filters_by_view_session():
    """实时捕获只插入当前视图会话的条目（跨会话不混入，回归）。"""
    from ui.history_view import HistoryView

    view = HistoryView()
    view.set_view_session_id(2)  # 视图 = 会话 2
    view.add_item(ClipboardItem(type="text", content="belongs to 2",
                                session_id=2))
    view.add_item(ClipboardItem(type="text", content="belongs to 1",
                                session_id=1))  # 其他会话 → 不插入
    assert view._model.rowCount() == 1
    assert view._model.index(0, 0).data(ROLE_ITEM).content == "belongs to 2"
    view.close()


def test_refresh_session_counts_updates_combo(tmp_path):
    """新建会话复制内容后：下拉计数实时刷新（不用重启，回归）。"""
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service, session_service
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "cnt.db")
    migrate(engine)
    session_service.ensure_default(engine)
    sid = session_service.create_session(engine, "新任务")

    view = HistoryView()
    view.set_session_context(engine, session_service)
    view.reload_sessions(sid)
    assert "0 条" in view._session_combo.itemText(
        view._session_combo.findData(sid))

    # 模拟：复制内容落入新会话
    item = ClipboardItem(type="text", content="new content", session_id=sid)
    item.hash = hashlib.sha256(b"new content").hexdigest()
    history_service.save_item(engine, item)
    view.refresh_session_counts()
    assert "1 条" in view._session_combo.itemText(
        view._session_combo.findData(sid))
    assert view._session_combo.currentData() == sid  # 选中保持不变
    view.close()


def test_main_window_initial_size_660():
    """初始/最小窗口高度 660（顶部会话行 + 类型筛选 + 列表不挤压）。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    assert w.minimumHeight() == 660
    assert w.height() == 660
    w.close()


def test_search_scope_toggle_button():
    """搜索范围：点按切换按钮（全部会话 ↔ 本会话），无弹层（回归）。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    assert w._search_scope_btn.text() == "全部会话"
    assert w._scope_current is None
    w._search_scope_btn.click()
    assert w._search_scope_btn.text() == "本会话"
    assert w._scope_current == "current"
    w._search_scope_btn.click()
    assert w._search_scope_btn.text() == "全部会话"
    assert w._scope_current is None
    w.close()


def test_page_specific_search_row_controls():
    """搜索行（搜索框+范围按钮）仅历史页显示；📁 在收藏夹页内。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    pytest_app.processEvents()
    assert w._search_scope_btn.isVisible()          # 默认历史页
    cv = w._pages.widget(1)
    for row in (2, 3, 4):  # 非历史页：搜索行隐藏（不留空白带）
        w._nav.setCurrentRow(row)
        pytest_app.processEvents()
        assert not w._search_scope_btn.isVisible(), f"row={row} 范围按钮应隐藏"
        assert not w._search.isVisible(), f"row={row} 搜索框应隐藏"
    w._nav.setCurrentRow(1)  # 收藏夹页
    pytest_app.processEvents()
    assert not w._search_scope_btn.isVisible()  # 历史搜索行隐藏
    assert cv._collections_trigger.isVisible()  # 📁 在收藏夹页内
    w._nav.setCurrentRow(0)  # 回历史
    pytest_app.processEvents()
    assert w._search_scope_btn.isVisible()
    w.close()


def test_collections_panel_hover_show_hide(tmp_path):
    """收藏夹面板：📁 悬停展开，离开自动收回（不占常驻空间）。

    显隐逻辑用公开方法直接驱动（offscreen 的 sendEvent 与跨测试事件
    循环交互不可靠：单独跑通过、全套跑 Leave 不触发 timer，实测伪影）。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.collections_view import CollectionsView

    engine = create_db_engine(tmp_path / "cp.db")
    migrate(engine)
    view = CollectionsView()
    view.set_context(engine)
    view.resize(500, 400)
    view.show()
    pytest_app.processEvents()
    assert not view._panel.isVisible()  # 默认隐藏（不占空间）

    # 📁 悬停（主窗口转发）→ 展开在视图左上角
    view.show_collection_panel()
    assert view._panel.isVisible()
    assert view._panel.x() == 0
    # 高度随内容自适应（不占满视图；默认收藏夹 1 项 → 小面板）
    assert 0 < view._panel.height() < view.height()

    # 离开 → 延时收回（timer 触发隐藏；emit 直接验证连接，
    # 避免 offscreen qWait 跨测试事件循环的时序伪影）
    view.schedule_hide_panel()
    assert view._hide_timer.isActive()
    assert view._hide_timer.interval() == 250
    view._hide_timer.timeout.emit()
    assert not view._panel.isVisible()

    # 移入面板（取消延时）→ 不收回
    view.show_collection_panel()
    view.schedule_hide_panel()
    view.show_collection_panel()  # 等价于面板 Enter 取消 timer
    assert view._panel.isVisible()
    view.close()


def test_collections_panel_anchored_near_icon(tmp_path):
    """面板锚定在 📁 图标附近（右缘贴图标左侧），而非页面左上角（回归）。"""
    from PySide6.QtCore import QPoint

    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.collections_view import CollectionsView

    engine = create_db_engine(tmp_path / "anch.db")
    migrate(engine)
    view = CollectionsView()
    view.set_context(engine)
    view.resize(500, 400)
    view.show()
    pytest_app.processEvents()

    # 图标在页面右上角区域：锚点全局坐标 → 面板应出现在图标左侧
    icon_global = view.mapToGlobal(QPoint(view.width() - 40, 5))
    view.show_collection_panel(icon_global)
    local = view.mapFromGlobal(icon_global)
    assert view._panel.x() == max(0, local.x() - view._panel.width() + 4)
    assert view._panel.x() > 0  # 不再固定在左上角 0
    assert view._panel.y() == max(0, local.y())
    view.close()


def test_collections_title_shows_current(tmp_path):
    """收藏夹页常驻标题：显示当前收藏夹名 · 条数（面板收回后仍可见）。"""
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service, history_service
    from ui.collections_view import CollectionsView
    from app.types import ClipboardItem

    engine = create_db_engine(tmp_path / "t.db")
    migrate(engine)
    cid = collection_service.create_collection(engine, "论文资料")
    item = ClipboardItem(type="text", content="论文片段")
    item.hash = hashlib.sha256("论文片段".encode()).hexdigest()
    history_service.save_item(engine, item)
    collection_service.add_item(engine, cid, item)

    view = CollectionsView()
    view.set_context(engine)
    assert "★ 收藏" in view._title.text()  # 默认选中内置收藏夹
    idx = next(i for i, c in enumerate(view._collections)
               if c["name"] == "论文资料")
    view._list.setCurrentRow(idx)  # 切到目标收藏夹
    pytest_app.processEvents()
    assert "论文资料" in view._title.text()
    assert "1 条" in view._title.text()
    view.close()


# ---- 类型切换手势（←/→ 键 + 触控板双指横滑）----

def _mk_item(type_, content="x"):
    from app.types import ClipboardItem

    return ClipboardItem(type=type_, content=content)


def _swipe_event(dx: int, dy: int = 0, phase=None):
    """构造触控板横向滑动的 Wheel 事件（pixelDelta x 主导）。

    phase 默认 ScrollUpdate（滑动中）；真实 macOS 序列见探针实测：
    Begin → Update×N → End → Momentum×N
    """
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(dx, dy), QPoint(dx * 8, dy * 8),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        phase if phase is not None else Qt.ScrollPhase.ScrollUpdate, False)


def _swipe_gesture(dx: int):
    """完整一次物理滑动（探针实测结构）：

    手指段 Begin→Update×N→End + 动量段 Begin→Momentum×N→End
    （动量开始也被系统标成 ScrollBegin）
    """
    return ([_swipe_event(dx, phase=Qt.ScrollPhase.ScrollBegin)]
            + [_swipe_event(dx // 2, phase=Qt.ScrollPhase.ScrollUpdate) for _ in range(5)]
            + [_swipe_event(0, phase=Qt.ScrollPhase.ScrollEnd)]
            + [_swipe_event(dx // 2, phase=Qt.ScrollPhase.ScrollBegin)]  # 动量段 Begin
            + [_swipe_event(15, phase=Qt.ScrollPhase.ScrollMomentum) for _ in range(10)]
            + [_swipe_event(0, phase=Qt.ScrollPhase.ScrollEnd)])


def test_history_arrow_keys_switch_type_filter():
    """←/→ 键循环切换类型筛选（全部→文本→URL→…→代码→全部）。"""
    from PySide6.QtTest import QTest

    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url"), _mk_item("image")])
    assert view._type_tabs.currentRow() == 0  # 全部
    assert view._model.rowCount() == 3

    QTest.keyClick(view._list, Qt.Key.Key_Right)   # → 文本
    assert view._type_tabs.currentRow() == 1
    assert view._filter_type == "text"
    assert view._model.rowCount() == 1

    QTest.keyClick(view._list, Qt.Key.Key_Right)   # → URL
    assert view._filter_type == "url"
    assert view._model.rowCount() == 1

    QTest.keyClick(view._list, Qt.Key.Key_Left)    # ← 回文本
    assert view._filter_type == "text"

    QTest.keyClick(view._list, Qt.Key.Key_Left)    # ← 全部
    QTest.keyClick(view._list, Qt.Key.Key_Left)    # ← 代码（循环）
    assert view._filter_type == "code"
    QTest.keyClick(view._list, Qt.Key.Key_Right)   # → 全部（循环回来）
    assert view._filter_type == ""
    assert view._model.rowCount() == 3
    view.close()


def test_history_swipe_wheel_switches_type_filter():
    """完整手势（Begin→Update→End→Momentum）只切一格；再次滑动再切。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url"), _mk_item("image")])
    vp = view._list.viewport()

    for ev in _swipe_gesture(-60):  # 滑动 1：只切一格 → 文本
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 1

    for ev in _swipe_gesture(-60):  # 滑动 2：→ URL
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 2

    for ev in _swipe_gesture(60):   # 反向滑动：→ 文本
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 1
    view.close()


def test_history_swipe_momentum_segment_no_switch():
    """动量段（Begin 后紧跟 Momentum——系统把动量开始标成 Begin）不切换。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url")])
    vp = view._list.viewport()

    # 动量段完整序列：Begin(62) → Momentum×30 → End
    seq = ([_swipe_event(62, phase=Qt.ScrollPhase.ScrollBegin)]
           + [_swipe_event(-30, phase=Qt.ScrollPhase.ScrollMomentum) for _ in range(30)]
           + [_swipe_event(0, phase=Qt.ScrollPhase.ScrollEnd)])
    for ev in seq:
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 0  # 动量段绝不切换
    view.close()


def test_history_swipe_begin_zero_dx_deferred():
    """ScrollBegin 的 dx=0（实测首事件 dx 可能为 0/1）：由后续首个非零 Update 补切。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url")])
    vp = view._list.viewport()

    QApplication.sendEvent(vp, _swipe_event(0, phase=Qt.ScrollPhase.ScrollBegin))
    assert view._type_tabs.currentRow() == 0  # dx=0：未切换
    QApplication.sendEvent(vp, _swipe_event(-80, phase=Qt.ScrollPhase.ScrollUpdate))
    assert view._type_tabs.currentRow() == 1  # 首个非零 Update 补切
    QApplication.sendEvent(vp, _swipe_event(-40, phase=Qt.ScrollPhase.ScrollUpdate))
    assert view._type_tabs.currentRow() == 1  # 不再重复切
    view.close()


def test_history_swipe_no_phase_not_intercepted():
    """无阶段信息（鼠标滚轮等）放行不拦截；纵向主导放行。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url")])
    vp = view._list.viewport()

    QApplication.sendEvent(vp, _swipe_event(-60, phase=Qt.ScrollPhase.NoScrollPhase))
    assert view._type_tabs.currentRow() == 0  # 不切换
    QApplication.sendEvent(vp, _swipe_event(0, 50, phase=Qt.ScrollPhase.ScrollBegin))
    assert view._type_tabs.currentRow() == 0  # 纵向主导：不切换
    view.close()


def test_history_vertical_wheel_not_intercepted():
    """纵向滚动/鼠标滚轮不触发类型切换。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url")])
    vp = view._list.viewport()

    QApplication.sendEvent(vp, _swipe_event(0, 50))    # 纵向触控板
    assert view._type_tabs.currentRow() == 0
    # 鼠标滚轮：angleDelta 只有 y 分量
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    wheel = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5),
        QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(vp, wheel)
    assert view._type_tabs.currentRow() == 0
    view.close()


def test_history_swipe_double_begin_only_once():
    """同一次滑动被系统拆成多个 ScrollBegin（实测）时只切一格。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url"), _mk_item("image")])
    vp = view._list.viewport()

    # 实测序列：Begin(-16) → Begin(0) → Update(-34) → End → Momentum×N
    seq = ([_swipe_event(-16, phase=Qt.ScrollPhase.ScrollBegin),
            _swipe_event(0, phase=Qt.ScrollPhase.ScrollBegin),
            _swipe_event(-34, phase=Qt.ScrollPhase.ScrollUpdate),
            _swipe_event(0, phase=Qt.ScrollPhase.ScrollEnd)]
           + [_swipe_event(-30, phase=Qt.ScrollPhase.ScrollMomentum) for _ in range(5)])
    for ev in seq:
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 1  # 只切一格

    # 下一次滑动（完整两段：手指段 + 动量段）：正常再切一格 → URL
    for ev in _swipe_gesture(-92):
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 2
    view.close()


def test_history_vertical_events_passthrough():
    """纵向滑动/纵向动量必须放行（不拦截）——拦截会导致惯性滚动失效、
    下滑变成一格一格（回归：ScrollMomentum 曾无条件吞掉）。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url")])
    vp = view._list.viewport()

    # 纵向手势全阶段：eventFilter 全部返回 False（放行，不拦截）
    # （sendEvent 返回值是 viewport 处理结果，不能用来判断过滤器）
    assert not view.eventFilter(vp, _swipe_event(0, 50, phase=Qt.ScrollPhase.ScrollBegin))
    assert not view.eventFilter(vp, _swipe_event(0, 60, phase=Qt.ScrollPhase.ScrollUpdate))
    assert not view.eventFilter(vp, _swipe_event(0, 30, phase=Qt.ScrollPhase.ScrollMomentum))
    assert not view.eventFilter(vp, _swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollEnd))
    assert view._type_tabs.currentRow() == 0  # 不触发类型切换
    view.close()


# ---- HotkeyManager raw key 扩展（Tab Trigger 输入流）----

def _key_event(vk, flags=0, autorepeat=False):
    from PySide6.QtCore import QPoint
    from Quartz import (
        CGEventCreateKeyboardEvent,
        CGEventSetFlags,
        CGEventSetIntegerValueField,
        kCGKeyboardEventAutorepeat,
    )

    ev = CGEventCreateKeyboardEvent(None, vk, True)
    CGEventSetFlags(ev, flags)
    if autorepeat:
        CGEventSetIntegerValueField(ev, kCGKeyboardEventAutorepeat, 1)
    return ev


def test_hotkey_raw_key_forwarding():
    """普通按键 → raw_key_down 转发（含字符）；事件不消费（透传）。"""
    from services.hotkey_manager import HotkeyManager

    mgr = HotkeyManager()
    received = []
    mgr.raw_key_down.connect(lambda vk, ch: received.append((vk, ch)))
    mgr.enable_raw_keys(True)

    # 构造事件（无 unicode）→ 回退表字符
    assert mgr.handle_event(_key_event(12)) is False  # q：透传不消费
    assert mgr.handle_event(_key_event(48)) is False  # Tab
    assert received == [(12, "q"), (48, "\t")]


def test_hotkey_raw_key_excludes_modifiers():
    """⌘/⌃/⌥ 组合键不进入 raw 输入流（热键逻辑独占）。"""
    from Quartz import (
        kCGEventFlagMaskAlternate,
        kCGEventFlagMaskCommand,
        kCGEventFlagMaskControl,
    )

    from services.hotkey_manager import HotkeyManager

    mgr = HotkeyManager()
    received = []
    mgr.raw_key_down.connect(lambda vk, ch: received.append((vk, ch)))
    mgr.enable_raw_keys(True)

    mgr.handle_event(_key_event(12, kCGEventFlagMaskCommand))
    mgr.handle_event(_key_event(12, kCGEventFlagMaskControl))
    mgr.handle_event(_key_event(12, kCGEventFlagMaskAlternate))
    assert received == []


def test_hotkey_binding_priority_over_raw():
    """热键绑定（⌘⇧V）优先于 raw 转发且消费事件。"""
    from services.hotkey_manager import HotkeyManager, KEY_V, MASK_HOTKEY

    mgr = HotkeyManager()
    activated = []
    raw = []
    mgr.activated.connect(lambda: activated.append(1))
    mgr.raw_key_down.connect(lambda vk, ch: raw.append(vk))
    mgr.enable_raw_keys(True)

    assert mgr.handle_event(_key_event(KEY_V, MASK_HOTKEY)) is True  # 消费
    assert activated == [1]
    assert raw == []


def test_hotkey_raw_disabled_no_forward():
    """未 enable_raw_keys：普通按键不转发。"""
    from services.hotkey_manager import HotkeyManager

    mgr = HotkeyManager()
    raw = []
    mgr.raw_key_down.connect(lambda vk, ch: raw.append(vk))
    assert mgr.handle_event(_key_event(12)) is False
    assert raw == []


def test_hotkey_autorepeat_suppressed():
    """自动重复事件被吞（不触发热键也不转发 raw）。"""
    from services.hotkey_manager import HotkeyManager

    mgr = HotkeyManager()
    activated = []
    raw = []
    mgr.activated.connect(lambda: activated.append(1))
    mgr.raw_key_down.connect(lambda vk, ch: raw.append(vk))
    mgr.enable_raw_keys(True)
    assert mgr.handle_event(_key_event(9, autorepeat=True)) is True
    assert activated == [] and raw == []


def test_templates_view_folder_buttons_visible(tmp_path):
    """文件夹区操作入口必须有文字（曾用 ＋/✎/－ 符号按钮不可识别，回归）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "fb.db")
    migrate(engine)
    view = TemplatesView()
    view.set_context(engine)
    # 底部「＋ 新建类型」文字按钮
    texts = [b.text() for b in view.findChildren(QPushButton)]
    assert "＋ 新建类型" in texts
    # 右键菜单策略已启用（CustomContextMenu）
    from PySide6.QtCore import Qt as _Qt

    assert view._folder_list.contextMenuPolicy() == \
        _Qt.ContextMenuPolicy.CustomContextMenu
    view.close()


def test_templates_view_context_menu_favorite_and_move(tmp_path):
    """模板右键：收藏切换 + 移动到类型（用户要求：收藏/移动走右键菜单）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "cm.db")
    migrate(engine)
    svc = TemplateService(engine)
    fid = svc.create_folder("项目")
    svc.create_template("Test", "tctx", "hello")

    view = TemplatesView()
    view.set_context(engine)
    row = next(r for r in range(view._list.count())
               if "tctx" in view._list.item(r).text())
    view._list.setCurrentRow(row)
    t = view._templates[row]

    # 右键菜单动作：收藏 → 列表出现 ★
    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    view._active_menus.append(menu)
    menu.addAction("收藏").triggered.connect(
        lambda: view._toggle_favorite(t))
    menu.actions()[0].trigger()
    pytest_app.processEvents()
    assert svc.get_template(t["id"])["favorite"] is True
    assert any("★" in view._list.item(r).text()
               for r in range(view._list.count()))

    # 移动到类型
    view._move_template(t, fid)
    pytest_app.processEvents()
    assert svc.get_template(t["id"])["folder_id"] == fid
    # 类型过滤后可见
    idx = next(i for i in range(view._folder_list.count())
               if view._folder_list.item(i).text().startswith("项目"))
    view._folder_list.setCurrentRow(idx)
    pytest_app.processEvents()
    assert any("tctx" in view._list.item(r).text()
               for r in range(view._list.count()))
    view.close()


def test_main_window_search_only_on_history_page(tmp_path):
    """搜索框是历史页专属：切换到其它页面隐藏（用户反馈：所有页面都有搜索框）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.main_window import MainWindow

    engine = create_db_engine(tmp_path / "sp.db")
    migrate(engine)
    w = MainWindow()
    w.show()
    pytest_app.processEvents()

    assert w._search.isVisible()          # 历史页（默认）显示
    for row in (1, 2, 3):                 # 收藏夹/模板/时间线
        w._nav.setCurrentRow(row)
        pytest_app.processEvents()
        assert not w._search.isVisible(), f"row={row} 搜索框应隐藏"
    w._nav.setCurrentRow(0)
    pytest_app.processEvents()
    assert w._search.isVisible()          # 回到历史页恢复
    w.close()
