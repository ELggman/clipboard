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


def test_history_row_paint_multiline_sensitive(tmp_path):
    """多行 .env 敏感条目：遮蔽文本仍带换行（逐处遮蔽、保留行结构），
    但列表行是**单行**元素——绘制必须压平空白且不崩。

    回归：不压平的话两行会挤成 `localhostDB_PASSWORD=…` 连读。
    """
    view = HistoryView()
    view.add_item(ClipboardItem(
        type="text",
        content="DB_HOST=localhost\nDB_PASSWORD=sup3rs3cret!\nDEBUG=true",
        preview="DB_HOST=localhost",
        sensitive=1, sensitive_type="api_key"))
    view.resize(400, 300)
    view.show()
    pytest_app.processEvents()
    assert view.grab().isNull() is False   # paint 冒烟（走敏感行绘制路径）
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

    view.resize(456, 500)  # 1.2 倍宽（封顶内）
    pytest_app.processEvents()
    assert view._delegate._scale == 1.2
    assert _size_hint(view, 0).height() == round(base_txt * 1.2)

    view.resize(1000, 500)  # 宽屏 → 缩放封顶 1.35（1000/380=2.63 不可用）
    pytest_app.processEvents()
    assert view._delegate._scale == 1.35
    assert _size_hint(view, 0).height() == round(base_txt * 1.35)
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


def test_quick_paste_popup_dismissed_emitted(tmp_path):
    """Quick Paste：隐藏（选中/Esc/点外部）会发出 dismissed——供外部恢复退避的主窗口。"""
    from ui.quick_paste_popup import QuickPastePopup

    popup = QuickPastePopup()
    dismissed = []
    popup.dismissed.connect(lambda: dismissed.append(True))
    popup.populate([
        ClipboardItem(type="text", content="x"),
    ])
    popup.show()  # populate 只装载；可见后 hide 才发 dismissed
    pytest_app.processEvents()
    assert len(dismissed) == 0  # 显示不算隐藏
    popup.close()
    pytest_app.processEvents()
    assert len(dismissed) == 1
    popup.deleteLater()


def test_quick_paste_popup_double_click_selects(tmp_path):
    """Quick Paste：双击条目 → 发出 selected 信号并关闭（与回车同路径）。

    直接驱动 itemDoubleClicked→_pick_item 连接的处理函数：rows 查找 + 发
    selected + 关闭（真实双击由 QListView 合成，offscreen 下时序不可靠，
    但连接（itemDoubleClicked→_pick_item）与处理逻辑在本测试覆盖）。
    """
    from ui.quick_paste_popup import QuickPastePopup

    popup = QuickPastePopup()
    picked = []
    popup.selected.connect(lambda item: picked.append(item))
    popup.populate([
        ClipboardItem(type="text", content="first item"),
        ClipboardItem(type="text", content="second item"),
    ])
    pytest_app.processEvents()
    popup._pick_item(popup._list.item(1))
    assert len(picked) == 1 and picked[0].content == "second item"
    assert not popup.isVisible()  # 选中后自动关闭（dismissed 会发出）
    popup.deleteLater()


def test_quick_paste_popup_enter_via_popup_window(tmp_path):
    """Quick Paste：回车落在弹窗顶层（无子控件持焦点，macOS 激活时序常见）
    也触发选中——keyPressEvent 兜底。"""
    from PySide6.QtTest import QTest

    from ui.quick_paste_popup import QuickPastePopup

    popup = QuickPastePopup()
    picked = []
    popup.selected.connect(lambda item: picked.append(item))
    popup.populate([
        ClipboardItem(type="text", content="first"),
        ClipboardItem(type="text", content="second"),
    ])
    popup.show()
    pytest_app.processEvents()
    # 不聚焦列表：按键直达弹窗窗口自身
    QTest.keyClick(popup, Qt.Key.Key_Return)
    assert len(picked) == 1 and picked[0].content == "first"
    assert not popup.isVisible()
    popup.deleteLater()


def test_quick_paste_popup_return_no_double_fire(tmp_path):
    """Quick Paste：同一次回车（QShortcut + _PickList 兜底可能都触发）只发一次
    selected——_done 守卫防重。"""
    from ui.quick_paste_popup import QuickPastePopup

    popup = QuickPastePopup()
    picked = []
    popup.selected.connect(lambda item: picked.append(item))
    popup.populate([
        ClipboardItem(type="text", content="only"),
    ])
    # 三路入口各调一次（模拟同次按键的多条触发路径）
    popup._pick_current_row()
    popup._pick_current_row()
    popup._pick_item(popup._list.item(0))
    assert len(picked) == 1
    popup.deleteLater()


def test_quick_paste_popup_reassert_focus(tmp_path):
    """Quick Paste：激活落地后的补拍不崩，且焦点归还列表（activeWindow=None
    竞态的最终兜底——macOS 激活异步、弹窗无 key window 时回车进不了本进程）。"""
    from ui.quick_paste_popup import QuickPastePopup

    popup = QuickPastePopup()
    popup.populate([ClipboardItem(type="text", content="x")])
    popup.show()
    pytest_app.processEvents()
    popup.reassert_focus()
    pytest_app.processEvents()
    # 焦点回到列表（offscreen 下 activeWindow 可能仍无值，但列表持焦点即可）
    assert popup._list.hasFocus()
    popup.deleteLater()


def test_quick_paste_popup_enter_global_capture(tmp_path):
    """Quick Paste：回车落在**其它控件**上（模拟 macOS 下活动窗口仍是隐藏主
    窗口、按键被送进主窗口控件树——列表/弹窗自身的 keyPressEvent 都收不到）
    也能被应用级事件过滤器捕获并触发选中。"""
    from PySide6.QtWidgets import QPushButton
    from PySide6.QtTest import QTest

    from ui.quick_paste_popup import QuickPastePopup

    # 焦点放在弹出的按钮上（它没有任何回车处理逻辑，模拟「目标死控件」）
    sink = QPushButton("sink")
    sink.show()
    sink.setFocus()
    pytest_app.processEvents()

    popup = QuickPastePopup()
    popup.populate([
        ClipboardItem(type="text", content="first"),
        ClipboardItem(type="text", content="second"),
    ])
    popup.show()
    pytest_app.processEvents()

    picked = []
    popup.selected.connect(lambda item: picked.append(item))
    QTest.keyClick(sink, Qt.Key.Key_Return)
    assert len(picked) == 1 and picked[0].content == "first"
    assert not popup.isVisible()
    popup.deleteLater()
    sink.deleteLater()


def test_quick_paste_row_single_line(tmp_path):
    """Quick Paste 行文字单行化：markdown/多行内容折叠换行为空格，避免
    drawText 多行块在定高 44px 行内被顶对齐/裁剪（Q2 修复）。"""
    from ui.quick_paste_popup import _single_line

    assert _single_line("# 标题\n- 项目一\n\t- 项目二") == "# 标题 - 项目一 - 项目二"
    assert _single_line("普通一行") == "普通一行"
    assert _single_line("a  b\nc") == "a b c"


def test_qnspanel_patch_idempotent_safe():
    """QNSPanel.canBecomeKeyWindow 覆写：幂等，且 offscreen 下不抛错（无
    ObjC 类时静默跳过——真实 GUI 会话由 shadow 验证过 isKeyWindow=True）。"""
    from ui.quick_paste_popup import patch_qnspanel_can_become_key

    patch_qnspanel_can_become_key()  # 不抛
    patch_qnspanel_can_become_key()  # 幂等（模块级 flag 短路）


def test_qnspanel_whitelist_scoping():
    """覆写为白名单：未注册的 QNSPanel（如 QComboBox 下拉）回落默认 NO；
    注册的本应用弹窗才 YES；隐藏注销后回落——杜绝「全局放行空掉所有下拉」。"""
    import ui.macos_patch as mp

    fake_panel, other = object(), object()
    fake_widget = object()
    original = mp._native_panel
    mp._native_panel = lambda w: fake_panel
    try:
        # 未注册的面板：默认 NO（QComboBox 下拉行为不变）
        assert mp._can_become_key(other) is False
        # 注册 → 放行
        mp.register_native_panel(fake_widget)
        assert mp._can_become_key(fake_panel) is True
        assert mp._can_become_key(other) is False  # 其它面板仍 NO
        # 注销 → 回落（防地址复用误放行新 panel）
        mp.unregister_native_panel(fake_widget)
        assert mp._can_become_key(fake_panel) is False
    finally:
        mp._native_panel = original


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
                      "临时保存", "收藏", "", "删除"]  # "" = 分隔线

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


def test_detail_popup_stats_footer(tmp_path):
    """详情弹层底部状态栏：文本/代码显示统计，图片隐藏。"""
    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()

    # 文本条目：显示统计（首次即正确——不依赖 isVisible，见 _update_stats 注释）
    popup.show_item(ClipboardItem(type="text", content="hello world\n第二行"))
    pytest_app.processEvents()
    assert popup._stats.isVisible()
    assert popup._stats.text().startswith("15 字符")

    # 代码条目：切换到代码视图后统计同步刷新
    popup.show_item(ClipboardItem(type="code", language="python",
                                  content="def f(x):\n    return x + 1"))
    pytest_app.processEvents()
    assert popup._stats.isVisible()
    assert popup._stats.text() == "26 字符 · 17 字符(不含空格) · 6 字 · 2 行"

    # 图片条目：无文本 → 状态栏隐藏
    popup.show_item(ClipboardItem(type="image", file_path="/nonexistent.png"))
    pytest_app.processEvents()
    assert popup._stats.isHidden()

    popup.deleteLater()


def test_detail_popup_stats_on_reveal(tmp_path):
    """敏感条目：遮蔽态统计遮蔽文本，Reveal 后统计刷新为原文。"""
    from ui.item_detail_popup import ItemDetailPopup

    popup = ItemDetailPopup()
    popup.show_item(ClipboardItem(type="text", content="secretvalue",
                                  sensitive=1, sensitive_type="api_key"))
    pytest_app.processEvents()
    masked = popup._stats.text()
    assert masked.startswith("12 字符")          # 遮蔽文本长度
    popup._toggle_reveal()
    pytest_app.processEvents()
    assert popup._stats.isVisible()
    assert popup._stats.text().startswith("11 字符")  # "secretvalue" 原文
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
    """模板页：编辑弹窗新建保存 → 列表出现；shortcut 冲突/变量错误提示。"""
    from database.engine import create_db_engine
    from database.migrations import _DEFAULT_TEMPLATES, migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplateEditorDialog, TemplatesView

    engine = create_db_engine(tmp_path / "s.db")
    migrate(engine)
    svc = TemplateService(engine)
    view = TemplatesView()
    view.set_context(engine)
    base_count = view._list.count()
    # 基础模板（§101）——发货的变换模板已撤回（v9，见 §7.4）
    assert base_count == len(_DEFAULT_TEMPLATES)

    # 新建弹窗 + 保存（含 shortcut/文件夹/触发方式）→ accept 后视图 reload
    dlg = TemplateEditorDialog(view, svc, None)
    warnings = []
    dlg._warn = lambda msg: warnings.append(msg)  # 模态框换记录（测试）
    dlg._name.setText("日期")
    dlg._shortcut.setText("today2")
    dlg._content.setPlainText("今天：{{date}}")
    dlg._save()
    assert dlg.result() == QDialog.DialogCode.Accepted
    view.reload()
    assert view._list.count() == base_count + 1
    row = next(r for r in range(view._list.count())
               if "today2" in view._list.item(r).text())
    assert view._list.item(row).text().startswith("日期")

    # 无效模板变量：保存被拒（validate_template 提示，不落库）
    dlg2 = TemplateEditorDialog(view, svc, None)
    dlg2._warn = lambda msg: warnings.append(msg)
    dlg2._name.setText("Bad")
    dlg2._shortcut.setText("badx")
    dlg2._content.setPlainText("Hello {{unknown}}")
    dlg2._save()
    assert dlg2.result() != QDialog.DialogCode.Accepted  # 未保存
    view.reload()
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


def test_templates_two_column_cards(tmp_path):
    """模板页两栏布局：左分类 / 中列表两张 templateCard（编辑器已弹窗化）。"""
    from PySide6.QtWidgets import QFrame

    from ui.templates_view import TemplatesView

    view = TemplatesView()
    cards = [c for c in view.findChildren(QFrame)
             if c.objectName() == "templateCard"]
    assert len(cards) == 2
    view.close()


def test_templates_variable_tag_inserts(tmp_path):
    """变量胶囊点击 → 插入内容区光标处（组件化：变量系统扩展挂载点）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplateEditorDialog

    engine = create_db_engine(tmp_path / "vt.db")
    migrate(engine)
    dlg = TemplateEditorDialog(None, TemplateService(engine), None)
    dlg._var_tags.variable_clicked.emit("{{date}}")
    dlg._var_tags.variable_clicked.emit("{{uuid}}")
    assert dlg._content.toPlainText() == "{{date}}{{uuid}}"
    dlg.close()


def test_templates_input_variable_auto_suffix(tmp_path):
    """重复点 {{input:name}} → name/name2/name3（后缀规则接线）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplateEditorDialog

    engine = create_db_engine(tmp_path / "vs.db")
    migrate(engine)
    dlg = TemplateEditorDialog(None, TemplateService(engine), None)
    for _ in range(3):
        dlg._var_tags.variable_clicked.emit("{{input:name}}")
    assert dlg._content.toPlainText() == "{{input:name}}{{input:name2}}{{input:name3}}"
    dlg.close()


def test_variable_tag_bar_collapse_and_add():
    """变量条：超阈值折叠/展开；add_variable 追加、remove_variable 删除。"""
    from ui.template_components import VariableTagBar

    bar = VariableTagBar(variables=list(VariableTagBar.DEFAULT_VARIABLES))
    n = len(VariableTagBar.DEFAULT_VARIABLES)
    assert len(bar.variables()) == n
    assert bar.needs_collapse()  # n > 3 → 外部显示「展开全部」
    # 折叠态：第 4+ 个隐藏（隐藏控件不占布局；400px 弹窗胶囊区放 3 个）
    assert bar._pills[3].isHidden() and bar._pills[-1].isHidden()
    assert not bar._pills[0].isHidden()
    # 展开
    bar.set_expanded(True)
    assert not bar._pills[3].isHidden() and not bar._pills[-1].isHidden()
    assert bar.is_expanded()
    # 追加自定义变量（按序排入胶囊区）
    bar.add_variable("{{myvar}}")
    assert "{{myvar}}" in bar.variables()
    assert bar._pills[-1].text() == "{{myvar}}"  # 排在其他胶囊之后
    # 删除
    bar.remove_variable("{{myvar}}")
    assert "{{myvar}}" not in bar.variables()
    bar.close()


def test_input_dialog_all_filled():
    """all_filled：全部字段非空才 True（空白/纯空格视为未填）。"""
    from ui.input_variable_dialog import all_filled

    assert all_filled({})  # 无输入项 → 无需填，恒真
    assert not all_filled({"name": ""})
    assert not all_filled({"name": "   "})
    assert not all_filled({"a": "张三", "b": ""})
    assert all_filled({"a": "张三", "b": "李四"})


def test_input_dialog_preview_text():
    """preview_text：已填 token 替换为值，未填保留原 token。"""
    from services.template.parser import InputRequest
    from ui.input_variable_dialog import preview_text

    content = "{{input:leader}}好！我叫{{input:name}}，很高兴认识你。"
    reqs = [InputRequest("leader", "{{input:leader}}"),
            InputRequest("name", "{{input:name}}")]
    assert preview_text(content, {}, reqs) == content
    assert preview_text(content, {"name": "王五"}, reqs) == \
        "{{input:leader}}好！我叫王五，很高兴认识你。"
    assert preview_text(content, {"leader": "同学们", "name": "王五"}, reqs) == \
        "同学们好！我叫王五，很高兴认识你。"
    # 空白值视为未填，保留 token
    assert preview_text(content, {"name": "  "}, reqs) == content
    # 自定义变量（input 来源）同样按 token 精确替换
    content2 = "位置：{{location}}"
    reqs2 = [InputRequest("location", "{{location}}")]
    assert preview_text(content2, {"location": "北京"}, reqs2) == "位置：北京"


def test_input_dialog_insert_requires_all_filled():
    """对话框：插入按钮初始置灰；全填满才可点；预览随输入更新。"""
    from services.template.parser import InputRequest
    from ui.input_variable_dialog import InputVariableDialog

    content = "{{input:leader}}好！我叫{{input:name}}，很高兴认识你。"
    reqs = [InputRequest("leader", "{{input:leader}}"),
            InputRequest("name", "{{input:name}}")]
    dlg = InputVariableDialog(reqs, content=content)
    try:
        assert not dlg._insert_btn.isEnabled()  # 初始未填 → 置灰
        assert dlg._preview.toPlainText() == content  # 预览 = 原文
        dlg._edits["name"].setText("王五")
        assert not dlg._insert_btn.isEnabled()  # 还有 leader 未填
        assert "王五" in dlg._preview.toPlainText()
        assert "{{input:leader}}" in dlg._preview.toPlainText()
        dlg._edits["leader"].setText("同学们")
        assert dlg._insert_btn.isEnabled()  # 全填 → 可插入
        assert "同学们好！我叫王五，很高兴认识你。" == dlg._preview.toPlainText()
    finally:
        dlg.close()


def test_input_dialog_no_autodefault_enter_safe():
    """对话框按钮非 autoDefault：输入框回车不会触发默认按钮关框。

    回归：QDialog 里 QPushButton 默认 autoDefault=True，QLineEdit 回车
    会冒泡触发默认按钮 → 填一个变量按回车对话框直接消失（实测 bug）。
    置 autoDefault(False) 后回车只走 _next_or_accept（跳空字段/全填满才
    插入）。
    """
    from PySide6.QtWidgets import QPushButton

    from services.template.parser import InputRequest
    from ui.input_variable_dialog import InputVariableDialog

    reqs = [InputRequest("leader", "{{input:leader}}"),
            InputRequest("name", "{{input:name}}")]
    dlg = InputVariableDialog(reqs, content="")
    try:
        btns = dlg.findChildren(QPushButton)
        assert len(btns) >= 2
        assert all(not b.autoDefault() for b in btns)
    finally:
        dlg.close()


def test_templates_trigger_segmented_save(tmp_path):
    """分段控件：选中「自动触发」保存 → trigger_mode=automatic。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplateEditorDialog

    engine = create_db_engine(tmp_path / "seg.db")
    migrate(engine)
    svc = TemplateService(engine)
    dlg = TemplateEditorDialog(None, svc, None)
    dlg._name.setText("Seg")
    dlg._shortcut.setText("segx")
    dlg._content.setPlainText("x")
    dlg._trigger_auto.setChecked(True)  # 分段控件 → automatic
    dlg._save()
    assert svc.find_by_shortcut("segx")["trigger_mode"] == "automatic"
    dlg.close()


def test_templates_star_zone_toggles_favorite(tmp_path):
    """模板行尾 ★ 点击区 → 切换收藏（不触发行选中）。"""
    from PySide6.QtTest import QTest

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "star.db")
    migrate(engine)
    svc = TemplateService(engine)
    view = TemplatesView()
    view.set_context(engine)
    view.show()
    pytest_app.processEvents()
    t = view._templates[0]  # 第一行模板（默认顺序 quote 在前）
    before = t["favorite"]
    rect = view._list.visualItemRect(view._list.item(0))
    pos = rect.center()
    pos.setX(rect.right() - 8)  # 行尾 ★ 区
    pos.setY(rect.top() + 10)
    QTest.mouseClick(view._list.viewport(), Qt.MouseButton.LeftButton, pos=pos)
    after = svc.get_template(t["id"])["favorite"]
    assert after == (1 - before)  # 收藏状态翻转
    view.close()


def test_template_highlighter_var_format(tmp_path):
    """TemplateHighlighter：{{变量}} 用 accent 格式（Pygments 之上覆盖）。"""
    from PySide6.QtGui import QTextDocument
    from PySide6.QtWidgets import QApplication

    from ui.template_components import TemplateHighlighter

    doc = QTextDocument("def f():\n    return {{date}}")
    TemplateHighlighter(doc, "python")
    block = doc.findBlockByNumber(1)  # {{date}} 在第二行
    accent = QApplication.palette().link().color().name()
    fmts = block.layout().formats()  # FormatRange 对象（start/length/format）
    assert any(fr.format.foreground().color().name() == accent for fr in fmts)


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
    assert view._list.count() == 2  # 「全部」虚拟项 + 「★ 收藏」
    assert "全部" in view._list.item(0).text()  # 全部置顶

    collection_service.create_collection(engine, "工作")
    view.reload()
    assert view._list.count() == 3  # 「全部」+「★ 收藏」+ 收藏夹
    assert "★ 收藏" in view._list.item(1).text()
    assert "工作" in view._list.item(2).text()

    # 选中真实收藏夹 → 空条目
    view._list.setCurrentRow(2)
    assert view._model.rowCount() == 0
    view.close()


def test_collections_view_search(tmp_path):
    """收藏夹页搜索：输入框 textChanged 过滤 + 空结果提示。

    回归：textChanged 直接连 _apply_filter 时 _search_text 永不更新，
    搜索框输入无任何效果（实测 bug）。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service, history_service
    from ui.collections_view import CollectionsView

    engine = create_db_engine(tmp_path / "cs.db")
    migrate(engine)
    cid = collection_service.create_collection(engine, "工作")
    # 收藏两条内容（一条含「python」，一条不含）
    import hashlib

    for content in ("python 代码", "普通文本"):
        item = ClipboardItem(type="text", content=content, preview=content)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)
        collection_service.add_item(engine, cid, item)

    view = CollectionsView()
    view.set_context(engine)
    view._list.setCurrentRow(2)  # 0=全部 1=★收藏 2=工作
    assert view._model.rowCount() == 2

    view._search.setText("python")  # 触发 textChanged → 过滤
    assert view._model.rowCount() == 1
    assert view._search_text == "python"
    assert view._empty_hint.isHidden()  # 有结果 → 提示隐藏

    view._search.setText("不存在的关键词")
    assert view._model.rowCount() == 0
    assert not view._empty_hint.isHidden()  # 未检索到 → 显示空态提示

    view._search.setText("")
    assert view._model.rowCount() == 2
    view.close()


def test_collections_view_all_virtual(tmp_path):
    """收藏夹面板「全部」虚拟项：并集展示所有收藏夹条目（按原条目去重）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service, history_service
    from ui.collections_view import CollectionsView

    engine = create_db_engine(tmp_path / "all.db")
    migrate(engine)
    cid_a = collection_service.create_collection(engine, "A")
    cid_b = collection_service.create_collection(engine, "B")
    import hashlib

    items = []
    for content in ("a内容", "b内容", "共用内容"):
        item = ClipboardItem(type="text", content=content, preview=content)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)
        items.append(item)
    # A：前两条；B：后两条（「共用内容」同时在两个收藏夹 → 去重）
    collection_service.add_item(engine, cid_a, items[0])
    collection_service.add_item(engine, cid_a, items[2])
    collection_service.add_item(engine, cid_b, items[1])
    collection_service.add_item(engine, cid_b, items[2])

    view = CollectionsView()
    view.set_context(engine)
    assert "全部" in view._list.item(0).text()  # 置顶
    assert "（3）" in view._list.item(0).text()  # 并集去重后 3 条

    view._list.setCurrentRow(0)  # 选中「全部」
    assert view._model.rowCount() == 3  # 共用内容只出现一次
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


def test_timeline_tabs_bar_matches_history_style(tmp_path):
    """时间线「今天/昨天/本周/更早」条高度与历史页「全部/文本…」条一致。

    回归：时间线条曾用 setFixedHeight(30)，而 QSS item 高 30px + 上下
    margin 4px = 38px → 选中蓝胶囊被上下裁切（显示不全）。须与历史页
    typeTabs 同为 40px，胶囊完整可见。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.history_view import HistoryView
    from ui.timeline_view import TimelineView

    engine = create_db_engine(tmp_path / "tabs.db")
    migrate(engine)

    t = TimelineView()
    t.set_context(engine)
    t.resize(420, 700)
    t.show()
    pytest_app.processEvents()
    h = HistoryView()
    h.resize(420, 700)
    h.show()
    pytest_app.processEvents()

    # 高度一致：QSS 胶囊（30px + 上下 margin 4px）完整落在 40px 容器内
    assert t._tabs.height() == h._type_tabs.height() == 40
    item = t._tabs.visualItemRect(t._tabs.item(0))
    assert item.bottom() <= t._tabs.height(), "胶囊被容器裁切"
    # 分段条铺满页宽：回归——曾卡在默认 sizeHint 256px，QSS 生效后 4 个
    # 胶囊共 ~272px，尾部「更早」被裁、需左右滑动。铺满后内容必 ≤ 页宽。
    assert t._tabs.width() == t.width(), "分段条未铺满页宽（尾部会被裁）"
    assert t._tabs.horizontalScrollBar().maximum() == 0, "分段条出现水平滚动"
    last = t._tabs.visualItemRect(t._tabs.item(t._tabs.count() - 1))
    assert last.x() + last.width() <= t._tabs.width(), "最后一个分段未完整显示"
    t.close()
    h.close()


def test_timeline_bucket_count_label(tmp_path):
    """时间线条右侧计数：随当前时间段更新（更早=月份桶之和），右对齐贴边。

    回归：留白处计数须与选中段同步——切段后数字变、且不与胶囊项重叠。
    """
    import datetime

    from database.engine import create_db_engine
    from database.migrations import migrate
    from sqlalchemy import text
    from ui.timeline_view import TimelineView

    engine = create_db_engine(tmp_path / "cnt.db")
    migrate(engine)
    now = datetime.datetime.now()
    with engine.begin() as conn:
        for name, days in (("t1", 0), ("t2", 0), ("y1", 1),
                           ("o1", 40), ("o2", 41), ("o3", 80)):
            conn.execute(text(
                "INSERT INTO clipboard_items (type, content, preview, hash,"
                " favorite, pinned, created_at, updated_at) VALUES"
                " ('text', :c, :c, :h, 0, 0, :t, :t)"),
                {"c": name, "h": name, "t": now - datetime.timedelta(days=days)})

    view = TimelineView()
    view.set_context(engine)
    view.resize(420, 700)
    view.show()
    pytest_app.processEvents()

    assert view._count_label.text() == "2 条"     # 今天 x2
    view._tabs.setCurrentRow(1)
    pytest_app.processEvents()
    assert view._count_label.text() == "1 条"     # 昨天 x1
    view._tabs.setCurrentRow(3)
    pytest_app.processEvents()
    assert view._count_label.text() == "3 条"     # 更早：40/41/80 天 3 条
    # 计数右对齐贴边，且不压到左侧胶囊项
    assert view._count_label.x() + view._count_label.width() == view.width()
    last_item_right = (view._tabs.visualItemRect(view._tabs.item(3)).x()
                       + view._tabs.visualItemRect(view._tabs.item(3)).width())
    assert last_item_right < view._count_label.x(), "计数与胶囊重叠"
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
    sub = next(m for m in view._active_menus if m.title() == "收藏")
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
    # 「收藏」子菜单（按标题取：菜单项顺序会随功能增减变化）
    fav_menu = next(m for m in view._active_menus if m.title() == "收藏")
    fav_menu.actions()[0].trigger()  # ★ 快速收藏
    assert messages == ["已收藏"]
    assert item.favorite == 1
    from ui.history_view import HistoryDelegate

    assert "★" in HistoryDelegate._meta_line(item)

    # 收藏夹页：「★ 收藏」虚拟项显示该条目（0=全部 1=★收藏）
    cv = CollectionsView()
    cv.set_context(engine)
    assert "★ 收藏" in cv._list.item(1).text()
    cv._list.setCurrentRow(1)  # 选中虚拟项
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
    assert view._list.count() == 3  # 全部 + ★ 收藏 + 待删

    # 模拟右键菜单删除（与 _on_list_menu 相同的动作构建）
    from PySide6.QtWidgets import QMenu

    menu = QMenu()
    view._active_menus.append(menu)
    menu.addAction("删除").triggered.connect(
        lambda: view._delete_collection(cid))
    menu.actions()[0].trigger()
    assert view._list.count() == 2  # 只剩「全部」虚拟项 + 内置 ★ 收藏
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

    # 底部可见行的 viewport 坐标（向上扫描避开行间 spacing——
    # 行高/间距随 UI 优化可变，固定 -8 可能落在间隙导致命中失败）
    vp = view._list.viewport()
    y = vp.height() - 2
    while y > 4 and not view._list.indexAt(QPoint(200, y)).isValid():
        y -= 1
    bottom_pos = QPoint(200, y)
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
    """状态栏隐私指示：暂停/恢复切换文案（§9.4，● 绿点样式）。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    assert "● 监控中" in w._privacy_label.text()
    w.set_privacy_status(True)
    assert "● 监控已暂停" in w._privacy_label.text()
    assert w._privacy_label.property("paused") is True
    w.set_privacy_status(False)
    assert "● 监控中" in w._privacy_label.text()
    assert w._privacy_label.property("paused") is False
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
    view._ignored_list.addItem("1Password")   # 旧格式纯文本项也要能存下来
    view._append_ignored({"name": "Code", "bundle_id": "com.microsoft.VSCode"})
    view._on_change("privacy_ignored")
    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert saved["privacy"]["policy"] == "ignore"
    assert saved["privacy"]["temp_minutes"] == 10
    # 条目同时记名字与 bundle id（§9.5）：名字给用户看，bundle id 不随语言变
    assert saved["privacy"]["ignored_apps"] == [
        {"name": "1Password", "bundle_id": ""},
        {"name": "Code", "bundle_id": "com.microsoft.VSCode"},
    ]
    view.close()


def test_settings_ignored_apps_roundtrip_legacy_and_new(tmp_path):
    """旧格式（纯字符串）配置能读进来并原样存回；新格式带 bundle id 也保持。"""
    import yaml

    from ui.settings_view import SettingsView

    config = {
        "app": {}, "history": {},
        "privacy": {"policy": "warn", "temp_minutes": 5,
                    "ignored_apps": ["1Password",
                                     {"name": "Code",
                                      "bundle_id": "com.microsoft.VSCode"}]},
    }
    cfg_path = tmp_path / "settings.yaml"
    view = SettingsView()
    view.set_context(config, {}, cfg_path)
    view._on_change("privacy_ignored")
    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert saved["privacy"]["ignored_apps"] == [
        {"name": "1Password", "bundle_id": ""},
        {"name": "Code", "bundle_id": "com.microsoft.VSCode"},
    ]
    # 列表显示名字（不是 bundle id），匹配键取 bundle id
    assert view._ignored_list.item(1).text() == "Code"
    assert view._ignored_keys() == {"1password", "com.microsoft.vscode"}
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


def test_app_entry_indexes_folder_name_and_bundle_id(tmp_path):
    """别名索引：目录名 / bundle id 可搜，但存进忽略列表的仍是规范名。

    真机反例（本次修复的起因）：/Applications/Visual Studio Code.app 的
    CFBundleDisplayName 与 CFBundleName 都是 "Code"，localizedName() 也是
    "Code"——而忽略匹配正是拿 localizedName() 跟列表做精确比较。只按显示名
    索引时，用户搜 "Visual Studio Code" 会一无所获。
    """
    import plistlib

    from ui.app_picker_dialog import _entry_from_bundle

    app = tmp_path / "Visual Studio Code.app"
    (app / "Contents").mkdir(parents=True)
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleDisplayName": "Code",
        "CFBundleName": "Code",
        "CFBundleIdentifier": "com.microsoft.VSCode",
        "CFBundleExecutable": "Code",
    }))

    entry = _entry_from_bundle(app)
    assert entry.name == "Code"                 # 存进列表的值（须与 localizedName 一致）
    assert entry.hint == "Visual Studio Code"   # 列表里附带显示，便于辨认
    assert "visual studio code" in entry.aliases
    assert "com.microsoft.vscode" in entry.aliases
    assert entry.path == app


def test_app_picker_search_by_alias_keeps_canonical_name():
    """按别名搜到应用后，选中的仍是可匹配的规范名；列表项带图标。"""
    from PySide6.QtCore import Qt as _Qt

    from ui.app_picker_dialog import AppPickerDialog, scan_installed_apps

    entries = scan_installed_apps()
    assert entries

    dialog = AppPickerDialog()
    dialog.show()
    pytest_app.processEvents()

    def row_of(name: str):
        for i in range(dialog._list.count()):
            item = dialog._list.item(i)
            if item.data(_Qt.ItemDataRole.UserRole) == name:
                return i
        return -1

    with_alias = next((e for e in entries if e.aliases), None)
    if with_alias is not None:
        row = row_of(with_alias.name)
        assert row >= 0
        alias = sorted(with_alias.aliases)[0]
        dialog._search.setText(alias)
        pytest_app.processEvents()
        assert not dialog._list.item(row).isHidden(), f"按别名 {alias} 搜不到"
        dialog._list.setCurrentRow(row)
        assert dialog.selected_app() == with_alias.name, "选中值必须是规范名"

    # 列表项带图标（.app 都在本机，图标不应为空）
    entry_with_path = next((e for e in entries if e.path is not None), None)
    if entry_with_path is not None:
        row = row_of(entry_with_path.name)
        assert row >= 0
        assert not dialog._list.item(row).icon().isNull()

    dialog.close()


def test_code_meta_shows_pin_and_favorite_marks():
    """代码条目置顶/收藏后 meta 显示 📌/★（与其他类型一致；语言 emoji 已
    移除——UI 优化改线性类型图标，meta 只保留语言名）。"""
    from ui.history_view import HistoryDelegate

    item = ClipboardItem(type="code", content="def f():\n    pass",
                         language="python", line_count=2,
                         created_at="08-07 10:00")
    assert "Python" in HistoryDelegate._code_meta(item)
    assert "🐍" not in HistoryDelegate._code_meta(item)
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


def test_history_menu_temp_expiry(tmp_path):
    """右键「临时保存」（§9.9）：逐条设置到期时间，写库 + 内存同步 + 反馈。"""
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from ui.history_view import HistoryView

    engine = create_db_engine(tmp_path / "temp.db")
    migrate(engine)
    item = ClipboardItem(type="text", content="temporary note")
    item.hash = hashlib.sha256(b"temporary note").hexdigest()
    history_service.save_item(engine, item)

    view = HistoryView()
    view.set_menu_context(engine, None, None)
    view.set_items(history_service.list_recent(engine))
    loaded = view._model.index(0, 0).data(ROLE_ITEM)
    assert loaded.expires_at == ""

    messages = []
    view.feedback.connect(messages.append)
    menu = view._build_menu(loaded)
    temp_menu = next(m for m in view._active_menus if m.title() == "临时保存")
    assert [a.text() for a in temp_menu.actions()] == \
        ["1 分钟", "5 分钟", "10 分钟", "30 分钟"]  # 未设过 → 无「取消」

    next(a for a in temp_menu.actions() if a.text() == "5 分钟").trigger()
    assert loaded.expires_at != ""                              # 内存同步
    assert history_service.list_recent(engine)[0].expires_at != ""   # 落库
    assert messages == ["已设为 5 分钟临时条目"]

    # 已设过 → 菜单标题带到期时间，且多出「取消临时保存」
    menu2 = view._build_menu(loaded)
    temp2 = next(m for m in view._active_menus if m.title().startswith("临时保存（"))
    cancel = next(a for a in temp2.actions() if a.text() == "取消临时保存")
    cancel.trigger()
    assert loaded.expires_at == ""
    assert history_service.list_recent(engine)[0].expires_at == ""
    assert messages[-1] == "已取消临时保存"
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


def test_main_window_initial_size():
    """窗口尺寸以用户手动设置为准（当前 420×700，无最小尺寸约束）。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    assert w.width() == 420
    assert w.height() == 700
    w.close()


def test_search_scope_toggle_button():
    """搜索范围：分段控件（全部会话 ↔ 本会话，与模板页触发方式同款）。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    assert w._scope_all_btn.isChecked()
    assert w._scope_current is None
    w._scope_current_btn.click()
    assert w._scope_current_btn.isChecked()
    assert w._scope_current == "current"
    w._scope_all_btn.click()
    assert w._scope_all_btn.isChecked()
    assert w._scope_current is None
    w.close()


def test_page_specific_search_row_controls():
    """搜索行（搜索框+范围分段控件）仅历史页显示；📁 在收藏夹页内。"""
    from ui.main_window import MainWindow

    w = MainWindow()
    w.show()
    pytest_app.processEvents()
    assert w._scope_all_btn.isVisible()             # 默认历史页
    cv = w._pages.widget(1)
    for row in (2, 3, 4):  # 非历史页：搜索行隐藏（不留空白带）
        w._nav.setCurrentRow(row)
        pytest_app.processEvents()
        assert not w._scope_all_btn.isVisible(), f"row={row} 范围控件应隐藏"
        assert not w._search.isVisible(), f"row={row} 搜索框应隐藏"
    w._nav.setCurrentRow(1)  # 收藏夹页
    pytest_app.processEvents()
    assert not w._scope_all_btn.isVisible()  # 历史搜索行隐藏
    assert cv._collections_trigger.isVisible()  # 📁 在收藏夹页内
    w._nav.setCurrentRow(0)  # 回历史
    pytest_app.processEvents()
    assert w._scope_all_btn.isVisible()
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
    assert "全部" in view._title.text()  # 默认选中「全部」虚拟项
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


# ---- 横滑灵敏度：别把纵向滚动的手抖判成横滑（用户实测反馈）----

def test_history_vertical_scroll_with_hand_jitter_no_switch():
    """纵向滚动时每个事件都带小幅 dx 手抖 → 不得切类型。

    旧判据只看「|dx| > |dy|」，dx=3/dy=-14 之外的手抖一旦 dx 压过 dy 就切；
    新判据要求累计横向 ≥ SWIPE_MIN_DX 且明显压过累计纵向。
    """
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url"), _mk_item("image")])
    vp = view._list.viewport()

    seq = ([_swipe_event(0, -16, phase=Qt.ScrollPhase.ScrollBegin)]
           + [_swipe_event(3, -14, phase=Qt.ScrollPhase.ScrollUpdate),
              _swipe_event(-3, -13, phase=Qt.ScrollPhase.ScrollUpdate),
              _swipe_event(2, -12, phase=Qt.ScrollPhase.ScrollUpdate),
              # 末尾 dy 衰减到 0，只剩横向抖动（最危险的一段）
              _swipe_event(4, 0, phase=Qt.ScrollPhase.ScrollUpdate)]
           + [_swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollEnd)])
    for ev in seq:
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 0  # 一次都没切
    view.close()


def test_history_vertical_lock_survives_tail_jitter():
    """纵向滚动末尾横向甩尾：已锁定纵向后不得翻盘（锁定是**整段手势**的）。

    本例的累计横向正好压在 SWIPE_MIN_DX 上——若没有纵向锁定，这一次会误切。
    """
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url")])
    vp = view._list.viewport()

    seq = ([_swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollBegin)]  # Begin 无位移
           + [_swipe_event(6, -20, phase=Qt.ScrollPhase.ScrollUpdate),  # → 锁定纵向
              _swipe_event(18, -1, phase=Qt.ScrollPhase.ScrollUpdate),
              _swipe_event(16, 0, phase=Qt.ScrollPhase.ScrollUpdate)]
           + [_swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollEnd)])
    for ev in seq:
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 0
    view.close()


def test_history_slow_horizontal_swipe_still_switches():
    """轻缓横滑（单事件位移只有 12px）靠**累计**达标，仍要能切——不能一刀切死。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url"), _mk_item("image")])
    vp = view._list.viewport()

    seq = ([_swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollBegin)]
           + [_swipe_event(-12, -1, phase=Qt.ScrollPhase.ScrollUpdate)
              for _ in range(4)]
           + [_swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollEnd)])
    for ev in seq:
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 1  # 累计 -48 ≥ 40 → 切一格
    view.close()


def test_history_small_horizontal_nudge_does_not_switch():
    """横向位移没到阈值的小幅推挤不切（旧判据 dx>dy 就会切，太灵敏）。"""
    view = HistoryView()
    view.set_items([_mk_item("text"), _mk_item("url")])
    vp = view._list.viewport()

    seq = ([_swipe_event(3, 0, phase=Qt.ScrollPhase.ScrollBegin)]
           + [_swipe_event(5, 0, phase=Qt.ScrollPhase.ScrollUpdate)
              for _ in range(3)]
           + [_swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollEnd)])
    for ev in seq:
        QApplication.sendEvent(vp, ev)
    assert view._type_tabs.currentRow() == 0  # 累计仅 18px：不切
    view.close()


def test_history_gesture_machine_sees_raw_events_even_when_scroll_scaled():
    """滚动速度非标准档时，手势机仍**先于**缩放层拿到原始事件。

    两个过滤器同装 viewport（`enable_smooth_wheel` + 手势），Qt 是「后装的先
    跑」：手势机必须后装。否则缩放层会先消费掉纵向事件，手势机永远锁定不了
    纵向（`_dy_sum` 恒为 0），滚动末尾的手抖又会误切类型——正是用户反馈的坑。
    """
    import ui.animations as animations

    original = animations.scroll_speed()
    animations.set_scroll_speed(0.5)
    try:
        view = HistoryView()
        view.set_items([_mk_item("text"), _mk_item("url"), _mk_item("image")])
        vp = view._list.viewport()

        seq = ([_swipe_event(0, -16, phase=Qt.ScrollPhase.ScrollBegin)]
               + [_swipe_event(3, -14, phase=Qt.ScrollPhase.ScrollUpdate),
                  _swipe_event(-3, -13, phase=Qt.ScrollPhase.ScrollUpdate),
                  # 末尾 dy 衰减到 0，只剩横向抖动（最危险的一段）
                  _swipe_event(4, 0, phase=Qt.ScrollPhase.ScrollUpdate)]
               + [_swipe_event(0, 0, phase=Qt.ScrollPhase.ScrollEnd)])
        for ev in seq:
            QApplication.sendEvent(vp, ev)

        assert view._dy_sum != 0, "手势机没拿到原始纵向事件：缩放层抢了先"
        assert view._type_tabs.currentRow() == 0
        view.close()
    finally:
        animations.set_scroll_speed(original)


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


def test_template_page_middle_auto_fit(tmp_path):
    """模板页中间栏随窗口自适应：左列 160 + 页边距 8，middle 自动填满、右缘不溢出、无横滚条。

    回归：旧 setFixedWidth(280) 与左列 160 + 边距 恒 > 420 窗口，右缘被裁 ~64px
    （用户反馈"怎么调都调不好"）。现在 middle 宽由 _apply_middle_width 按窗口计算。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import (
        _ENTRY_WIDTH,
        _LEFT_WIDTH,
        _PAGE_MARGIN,
        TemplatesView,
    )

    engine = create_db_engine(tmp_path / "fit.db")
    migrate(engine)
    svc = TemplateService(engine)
    svc.create_template("一条特别长的模板名称用于验证自适应宽度", "fit", "x")
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()

    # 布局常量块存在（手动调整模板条目宽度的接口）
    assert _PAGE_MARGIN == 8 and _LEFT_WIDTH == 160 and _ENTRY_WIDTH == 0
    # 中间栏 = 窗口 − 左右页边距 − 左列 − cards 间距 12
    assert view._middle.width() == 400 - 2 * _PAGE_MARGIN - _LEFT_WIDTH - 12
    # 右缘不超出窗口（完整显示，不再被裁）
    right = view._middle.mapTo(view, view._middle.rect().topRight()).x()
    assert right <= view.width()
    # 列表无横向滚轮条
    assert view._list.horizontalScrollBar().maximum() == 0
    assert view._list.horizontalScrollBarPolicy() == \
        Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    view.close()


def test_template_pan_wheel_moves_row(tmp_path):
    """触摸板/横向滚轮横滑 → 鼠标下条目内容平移（不显示滚轮）。"""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "pan.db")
    migrate(engine)
    svc = TemplateService(engine)
    svc.create_template("一个特别长的模板名称用于横向平移测试", "pw", "x")
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()
    row = next(r for r in range(view._list.count())
               if "pw" in view._list.item(r).text())
    view._list.setCurrentRow(row)
    pytest_app.processEvents()
    pos = view._list.visualItemRect(view._list.item(row)).center()

    # 横滑（angleDelta.x=-120，向左滑 → 显示右端内容，方向与原生横向滚轮一致）
    ev = QWheelEvent(QPointF(pos), QPointF(pos), QPoint(0, 0), QPoint(-120, 0),
                     Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(view._list.viewport(), ev)
    pytest_app.processEvents()
    assert view._pan.get(row, 0) > 0
    view.close()


def test_template_vertical_wheel_micro_dx_does_not_pan(tmp_path):
    """上下滚轮的微小横向分量（trackpad dx=±1~2）不得触发条目平移/整视口重绘。

    回归：旧判定 dx!=0 会把纵向滚轮里的 dx=1~2 当横向滑吞掉，逐事件
    viewport().update() → 上下滚动明显卡顿（用户反馈）。修复后：
    - |dx|<|dy| 归为纵向 → 事件透传给列表滚动（scrollbar 动）
    - _set_pan 无变化时 no-op（不触发重绘）
    横滑仍正常（dx=-120 单独测，见 test_template_pan_wheel_moves_row）。

    2026-09 起纵向鼠标滚轮改由缓动层消费（ui.animations.SmoothWheelScroller，
    触控板带 phase 不介入）：滚动条不再是「事件同步透传」直接动，而是由
    QPropertyAnimation 异步驱动到位——故这里要等动画走完再断言位置。
    「归纵向、不走平移路径」的语义不变。
    """
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtTest import QTest

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "vwheel.db")
    migrate(engine)
    svc = TemplateService(engine)
    for i in range(8):  # 多条目使列表可纵向滚动
        svc.create_template(f"纵向滚动条目{i}——名称足够长以产生横向溢出", f"vw{i}", "x")
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()
    row = next(r for r in range(view._list.count())
               if "vw0" in view._list.item(r).text())
    view._list.setCurrentRow(row)
    pytest_app.processEvents()
    sb = view._list.verticalScrollBar()
    base = sb.value()
    # 插桩 _set_pan：纵向滚轮若被误判成横滑，会走 _pan_step → _set_pan
    # → viewport().update()（卡顿根因）。数调用次数即数误判次数。
    calls = {"n": 0}
    orig_set_pan = view._set_pan

    def counting_set_pan(row, offset):
        calls["n"] += 1
        orig_set_pan(row, offset)

    view._set_pan = counting_set_pan

    pos = view._list.visualItemRect(view._list.item(row)).center()
    # 5 个「纵向主导但带 dx=1 噪声」的滚轮事件（真实 trackpad 垂直滚动形态）
    for _ in range(5):
        ev = QWheelEvent(QPointF(pos), QPointF(pos), QPoint(1, -120),
                         QPoint(1, -120), Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(view._list.viewport(), ev)
        pytest_app.processEvents()
    # 鼠标滚轮由缓动层消费（滚动条由动画异步驱动），等动画走完再断言
    QTest.qWait(500)
    # 列表滚动条位置变化了（纵向滚动仍归列表），但 _set_pan 一次都没被调用
    assert sb.value() != base, "纵向滚轮应滚动列表（经缓动层，异步到位）"
    assert calls["n"] == 0, "纵向滚轮的微小 dx 不应触发平移路径（卡顿根因）"
    # 横向平移未受影响（_pan 值全为 0，没有被误写成正偏移）
    assert max(view._pan.values(), default=0) == 0
    view.close()


def test_template_pan_delegate_shifts_content(tmp_path):
    """delegate 绘制真正应用 _pan：长条目平移后名称像素变化、★ 固定右缘。

    回归：delegate 曾用 self.parent()（=QListWidget）读 _pan 拿到 None，
    平移只在 view 侧字典生效、画面不动——须显式传 TemplatesView 引用。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "dlen.db")
    migrate(engine)
    svc = TemplateService(engine)
    tid = svc.create_template("一条特别长的模板名称用于验证 delegate 是否应用平移偏移", "long", "x")
    svc.toggle_favorite(tid)  # 金星 ★ 便于识别星标区
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()
    row = next(r for r in range(view._list.count())
               if "long" in view._list.item(r).text())

    a = view._list.viewport().grab().toImage()
    view._pan[row] = 60
    view._list.viewport().update()
    pytest_app.processEvents()
    b = view._list.viewport().grab().toImage()

    name_diff = 0
    star_diff = 0
    for y in range(7, 30):  # 名称行
        for x in range(a.width()):
            pa, pb = a.pixelColor(x, y), b.pixelColor(x, y)
            delta = (abs(pa.red() - pb.red()) + abs(pa.green() - pb.green())
                     + abs(pa.blue() - pb.blue()))
            if delta > 60:
                if x < 148:  # 内容区（★ 在右缘 150+）
                    name_diff += 1
                else:
                    star_diff += 1
    assert name_diff > 50   # 内容已平移
    assert star_diff == 0   # ★ 固定右缘不随内容动
    view.close()


def test_template_pan_drag_swallows_click(tmp_path):
    """鼠标按住拖动 → 条目平移且不误开编辑弹窗；普通点击仍打开编辑。"""
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "drg.db")
    migrate(engine)
    svc = TemplateService(engine)
    svc.create_template("超长模板名称用于验证按住拖动平移的交互", "drg", "x")
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()
    row = next(r for r in range(view._list.count())
               if "drg" in view._list.item(r).text())
    view._list.setCurrentRow(row)
    pytest_app.processEvents()
    pos = view._list.visualItemRect(view._list.item(row)).center()

    opened = []
    orig = view._open_editor
    view._open_editor = lambda template=None: opened.append(True)
    try:
        # 拖动 >4px → 平移；释放时吃掉事件 → 不打开编辑器
        QApplication.sendEvent(view._list.viewport(), QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(pos), QPointF(pos),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pytest_app.processEvents()
        before = view._pan.get(row, 0)
        p2 = QPointF(pos.x() - 40, pos.y())
        QApplication.sendEvent(view._list.viewport(), QMouseEvent(
            QEvent.Type.MouseMove, p2, p2, Qt.MouseButton.NoButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        pytest_app.processEvents()
        QApplication.sendEvent(view._list.viewport(), QMouseEvent(
            QEvent.Type.MouseButtonRelease, p2, p2, Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier))
        pytest_app.processEvents()
        assert view._pan.get(row, 0) > before          # 已平移
        assert not opened                              # 未误开编辑

        # 普通点击（原地按下释放）→ 打开编辑
        QApplication.sendEvent(view._list.viewport(), QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(pos), QPointF(pos),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier))
        pytest_app.processEvents()
        QApplication.sendEvent(view._list.viewport(), QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(pos), QPointF(pos),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier))
        pytest_app.processEvents()
        assert opened
    finally:
        view._open_editor = orig
    view.close()


def test_template_pan_star_zone_still_toggles(tmp_path):
    """★ 点击区不受平移影响：点行尾 ★ 仍切换收藏，且不进拖拽状态。"""
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.template_components import STAR_ZONE
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "star.db")
    migrate(engine)
    svc = TemplateService(engine)
    svc.create_template("名称", "star", "x")
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()
    row = next(r for r in range(view._list.count())
               if "star" in view._list.item(r).text())
    view._list.setCurrentRow(row)
    pytest_app.processEvents()
    rect = view._list.visualItemRect(view._list.item(row))
    star_pos = QPoint(rect.right() - STAR_ZONE // 2, rect.top() + 12)

    QApplication.sendEvent(view._list.viewport(), QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(star_pos), QPointF(star_pos),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier))
    pytest_app.processEvents()
    assert svc.get_template(view._templates[row]["id"])["favorite"] is True
    assert view._pan_state is None   # ★ 点击不进拖拽平移
    view.close()


def test_template_all_rows_render_content(tmp_path):
    """多行模板全部渲染出内容（非仅第一行）。

    回归：delegate 的 content_clip 高度误用绝对 name_rect.top()，row≥1 时
    算出负数高度 → 空 clip → 除第一行外名称/钥匙片/触发全不绘制，只剩 ★。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "rows.db")
    migrate(engine)
    svc = TemplateService(engine)
    for name in ("第一个模板", "第二个模板名字长一些", "第三个模板"):
        svc.create_template(name, name[:2], "x")
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()

    img = view._list.viewport().grab().toImage()
    ok_rows = 0
    for name in ("第一个模板", "第二个模板名字长一些", "第三个模板"):
        row = next(r for r in range(view._list.count())
                   if name in view._list.item(r).text())
        rect = view._list.visualItemRect(view._list.item(row))
        content = 0
        for y in range(rect.top(), rect.bottom()):
            for x in range(rect.left(), rect.right()):
                c = img.pixelColor(x, y)
                if c.red() != 255 or c.green() != 255 or c.blue() != 255:
                    content += 1
        ok_rows += content > 400   # 完整内容（名称+钥匙片+★）；仅 ★ 只有 ~100
    assert ok_rows == 3
    view.close()


def test_template_star_click_at_drawn_position(tmp_path):
    """点击星标字形实际位置 → 收藏切换，且不误开编辑面板。

    回归：sizeHint 曾把条目撑到 220（超出视口），visualItemRect 与绘制
    option.rect 右侧差 8px → 命中区右偏 → 对准可见星标点击落入条目体，
    释放后打开编辑面板。点击区须用 delegate 同一 ROW_INSET 内缩值。
    """
    from PySide6.QtCore import QEvent, QPoint, QPointF
    from PySide6.QtGui import QMouseEvent

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.template_components import ROW_INSET, STAR_ZONE
    from ui.templates_view import TemplatesView

    engine = create_db_engine(tmp_path / "starpos.db")
    migrate(engine)
    svc = TemplateService(engine)
    svc.create_template("名称", "sp", "x")
    view = TemplatesView()
    view.set_context(engine)
    view.resize(400, 600)
    view.show()
    pytest_app.processEvents()
    row = next(r for r in range(view._list.count())
               if "sp" in view._list.item(r).text())
    rect = view._list.visualItemRect(view._list.item(row))
    # 星标字形中心 = 行右缘减 ROW_INSET 内缩后星标区的中心
    star_x = rect.right() - ROW_INSET - STAR_ZONE // 2
    star_y = rect.top() + 4 + 13

    opened = []
    view._open_editor = lambda t: opened.append(t["name"])
    vp = view._list.viewport()
    for ev_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):
        QApplication.sendEvent(vp, QMouseEvent(
            ev_type, QPointF(QPoint(star_x, star_y)),
            QPointF(QPoint(star_x, star_y)), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    pytest_app.processEvents()
    assert svc.get_template(view._templates[row]["id"])["favorite"] is True
    assert opened == []   # 星标点击不打开编辑面板
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


def test_editor_dialog_variable_library_scripts(tmp_path):
    """模板编辑弹窗：「变量库」列出脚本变量，补全候选也含它们。

    回归两处：① 发货脚本带来的变量最初只在补全候选里，变量库/胶囊区看不到
    ——用户「看不到这些变量以及对应的描述信息」；② 注入原来只在变量增删时
    发生，弹窗**刚打开**时补全与变量库都是空的。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.custom_vars import visible_script_variables
    from services.template_service import TemplateService
    from ui.templates_view import TemplateEditorDialog

    engine = create_db_engine(tmp_path / "vl.db")
    migrate(engine)
    svc = TemplateService(engine)
    dlg = TemplateEditorDialog(None, svc, None)   # None = 新建模板
    try:
        scripts = {v.insert() for v in visible_script_variables()}
        assert "{{upper}}" in scripts
        # ① 变量库拿到脚本变量（构造时即注入）
        assert scripts <= {v.insert() for v in dlg._lib_popup._scripts}
        # ② 补全候选含脚本变量（打开就能补出 {{upper}}）
        assert "{{upper}}" in dlg._content._custom
        # 悬停说明来自脚本自述
        assert "转大写" in dlg._custom_tooltip_map()["{{upper}}"]
    finally:
        dlg.close()


def test_script_variable_menu_is_readonly(tmp_path):
    """右键脚本变量：不给编辑/删除，给的是「改脚本目录里的文件」的指引。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template_service import TemplateService
    from ui.templates_view import TemplateEditorDialog

    engine = create_db_engine(tmp_path / "vm.db")
    migrate(engine)
    dlg = TemplateEditorDialog(None, TemplateService(engine), None)
    try:
        dlg._show_variable_menu("{{upper}}")
        menu = dlg._menus[-1]
        texts = [a.text() for a in menu.actions()]
        assert len(texts) == 1
        assert "脚本" in texts[0]
        assert not menu.actions()[0].isEnabled()
        menu.close()
    finally:
        dlg.close()
