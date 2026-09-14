"""FluentComboBox 单元测试（offscreen）：API 对等 + 弹层交互 + 键盘。

该组件是 QComboBox 的自绘替代（见 ui/fluent_combo.py 顶部说明），
调用点只依赖下列 API 子集，故这里逐项锁定行为对等。
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

pytest_app = QApplication.instance() or QApplication([])

from ui.fluent_combo import FluentComboBox


def _combo():
    c = FluentComboBox()
    c.addItem("跟随系统", "system")
    c.addItem("浅色", "light")
    c.addItem("深色", "dark")
    return c


def test_add_and_read_items():
    c = _combo()
    assert c.count() == 3
    assert c.itemText(1) == "浅色"
    assert c.itemData(1) == "light"
    assert c.itemText(99) == ""       # 越界安全
    assert c.itemData(99) is None


def test_first_item_auto_selected_without_emit():
    emitted = []
    c = FluentComboBox()
    c.currentIndexChanged.connect(emitted.append)
    c.addItem("a", 1)
    assert c.currentIndex() == 0
    assert c.currentData() == 1
    assert emitted == []              # 填充期不误触槽


def test_find_data_hit_and_miss():
    c = _combo()
    assert c.findData("light") == 1
    assert c.findData("nope") == -1   # 未命中 -1（调用方 max(0, idx) 兜底）


def test_set_current_index_emits_and_updates():
    c = _combo()
    got = []
    c.currentIndexChanged.connect(got.append)
    c.setCurrentIndex(2)
    assert c.currentData() == "dark"
    assert got == [2]


def test_set_same_index_does_not_emit():
    c = _combo()
    got = []
    c.currentIndexChanged.connect(got.append)
    c.setCurrentIndex(c.currentIndex())   # 不变
    assert got == []


def test_block_signals_suppresses_but_updates_state():
    c = _combo()
    got = []
    c.currentIndexChanged.connect(got.append)
    c.blockSignals(True)
    c.setCurrentIndex(2)
    c.blockSignals(False)
    assert got == []
    assert c.currentData() == "dark"      # 状态照常更新


def test_out_of_range_ignored():
    c = _combo()
    c.setCurrentIndex(99)
    assert c.currentIndex() == 0
    c.setCurrentIndex(-5)
    assert c.currentIndex() == 0


def test_empty_combo_safe():
    c = FluentComboBox()
    assert c.count() == 0
    assert c.currentData() is None
    assert c.currentText() == ""
    c.open_popup()                        # 空列表不弹
    assert c._popup is None


def test_clear_resets():
    c = _combo()
    c.clear()
    assert c.count() == 0
    assert c.currentIndex() == -1
    assert c.currentData() is None


def test_set_size_adjust_policy_is_noop():
    c = _combo()
    c.setSizeAdjustPolicy(object())       # 兼容 QComboBox 枚举调用，收下即忽略
    assert c.count() == 3


def test_size_hint_grows_with_text():
    c = FluentComboBox()
    c.addItem("短", 1)
    narrow = c.sizeHint().width()
    c.addItem("一个非常非常长的选项文本", 2)
    assert c.sizeHint().width() > narrow


def test_view_minimum_width_honored_in_popup():
    c = _combo()
    c.show()
    c.view().setMinimumWidth(240)         # history_view._update_popup_width 用法
    c.open_popup()
    assert c._popup.isVisible()
    assert c._popup.width() >= 240


def test_popup_choose_updates_and_closes():
    c = _combo()
    c.show()
    got = []
    c.currentIndexChanged.connect(got.append)
    c.open_popup()
    assert c._popup.list.count() == 3
    c._on_chosen(1)                       # 模拟点击/回车选中
    assert c.currentData() == "light"
    assert got == [1]
    assert not c._popup.isVisible()       # 选中后关闭


def test_popup_keyboard_navigation_and_enter():
    c = _combo()
    c.show()
    c.setCurrentIndex(2)                  # 从末项出发，向上真正产生变化
    got = []
    c.currentIndexChanged.connect(got.append)
    c.open_popup()
    popup = c._popup
    assert popup.list.currentRow() == 2   # 打开时定位到当前项

    from PySide6.QtGui import QKeyEvent

    def press(key):
        popup.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, key,
                                      Qt.KeyboardModifier.NoModifier))

    press(Qt.Key.Key_Up)
    assert popup.list.currentRow() == 1
    press(Qt.Key.Key_Up)
    assert popup.list.currentRow() == 0
    press(Qt.Key.Key_Up)                  # 顶部不再越界
    assert popup.list.currentRow() == 0
    press(Qt.Key.Key_Return)
    assert c.currentIndex() == 0
    assert got == [0]


def test_popup_escape_closes_without_change():
    c = _combo()
    c.show()
    c.setCurrentIndex(1)
    got = []
    c.currentIndexChanged.connect(got.append)
    c.open_popup()

    from PySide6.QtGui import QKeyEvent

    c._popup.keyPressEvent(QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                     Qt.KeyboardModifier.NoModifier))
    assert not c._popup.isVisible()
    assert c.currentData() == "light"     # 未改变
    assert got == []


def test_refill_repopulates_popup():
    c = _combo()
    c.show()
    c.open_popup()
    c._popup.close()
    c.clear()
    c.addItem("新 A", "a")
    c.addItem("新 B", "b")
    c.open_popup()
    assert c._popup.list.count() == 2
    assert c._popup.list.item(0).text() == "新 A"


# ---- 点击时序：按下不开、释放才开 ----
# 真机上 Qt 对 Qt.Popup 有「弹层外按下 → 紧随释放关闭弹层」机制；若在按下时
# 开弹层，这次按下会被判为「弹层外」，同一次点击的释放就把刚开的弹层关掉。
# QTest 直投控件绕过该判定，故这组用例锁的是**我们自己的**按下/释放时序。

def _press(combo, pos=None):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    QTest.mousePress(combo, Qt.MouseButton.LeftButton,
                     pos=pos or combo.rect().center())


def _release(combo, pos=None):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest

    QTest.mouseRelease(combo, Qt.MouseButton.LeftButton,
                       pos=pos or combo.rect().center())


def test_press_alone_does_not_open():
    c = _combo()
    c.show()
    _press(c)
    assert c._popup is None or not c._popup.isVisible()   # 按下不弹
    assert not c._open


def test_release_opens_popup():
    c = _combo()
    c.show()
    _press(c)
    _release(c)
    assert c._popup.isVisible()
    assert c._open


def test_second_click_closes_and_does_not_reopen():
    """弹层开着时再点一次：收起，且**不能被同一次点击的释放又打开**。"""
    c = _combo()
    c.show()
    _press(c)
    _release(c)
    assert c._popup.isVisible()
    _press(c)
    assert not c._popup.isVisible()     # 按下即收起
    _release(c)
    assert not c._popup.isVisible()     # 释放不得重新打开
    assert c._popup.isHidden()


def test_press_inside_release_outside_does_not_open():
    """按下后拖到控件外再松开 = 取消（原生手感），不弹层。"""
    from PySide6.QtCore import QPoint

    c = _combo()
    c.show()
    _press(c, QPoint(10, 10))
    _release(c, QPoint(c.width() + 40, c.height() + 40))
    assert c._popup is None or not c._popup.isVisible()


def test_popup_click_selects_after_release_open():
    """释放开弹层后，点击弹层内的另一项能真正切换（端到端时序）。"""
    from PySide6.QtTest import QTest

    c = _combo()
    c.show()
    _press(c)
    _release(c)
    got = []
    c.currentIndexChanged.connect(got.append)
    item = c._popup.list.item(2)
    QTest.mouseClick(c._popup.list.viewport(), Qt.MouseButton.LeftButton,
                     pos=c._popup.list.visualItemRect(item).center())
    assert c.currentData() == "dark"
    assert got == [2]
    assert not c._popup.isVisible()


def test_click_outside_dismiss_then_click_does_not_reopen():
    """「点外面」收起后，同一次点击的释放不得把弹层又弹回来。

    真机上 Qt 先关弹层、再把这次按下转发给本控件；故收起后短时间内
    按下要压住释放（否则表现为「关掉又弹回」）。
    """
    c = _combo()
    c.show()
    _press(c)
    _release(c)
    assert c._popup.isVisible()
    c._popup.close()                    # 模拟 Qt 的「点外面」关闭
    assert not c._popup.isVisible()
    _press(c)                           # 转发的按下（弹层已不在）
    _release(c)
    assert not c._popup.isVisible(), "关掉后又被同一次点击的释放弹回来了"


def test_choose_then_click_reopens_immediately():
    """选中收起不算「点外面」：选完可以立刻再点开换一个。"""
    c = _combo()
    c.show()
    _press(c)
    _release(c)
    c._on_chosen(1)
    assert c.currentData() == "light"
    _press(c)
    _release(c)
    assert c._popup.isVisible()


def test_popup_never_registers_native_panel():
    """回归护栏（真机 bug，offscreen 完全测不出，只能用源码护栏挡住）。

    弹层一旦把自己登记进 QNSPanel 的 key 白名单（macos_patch），macOS 上它会去
    抢 key window，抢到后 Qt/macOS 因窗口激活变化把它 hide()（弹层自行消失），
    且此后它的窗口收不到鼠标事件——点击直接穿透到下面的组件，表现为「下拉打不开
    /选不中」。四组真机对照实测：登记的必挂，不登记的必好；「取焦点」是无关变量。

    这里用 AST 检查调用与导入，避免注释/文档字符串里的同名字样造成误判。
    """
    import ast
    import inspect
    import textwrap

    import ui.fluent_combo as mod

    tree = ast.parse(textwrap.dedent(inspect.getsource(mod)))
    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for name in ("register_native_panel", "unregister_native_panel",
                 "patch_qnspanel_can_become_key"):
        assert name not in called, (
            f"弹层不得调用 {name}()——会抢 key window 导致弹层自关 + 点击穿透")

    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not (imported & {"register_native_panel", "unregister_native_panel",
                            "patch_qnspanel_can_become_key"}), \
        "弹层不得从 macos_patch 导入 key 白名单相关接口"
