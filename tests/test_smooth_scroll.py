"""滚轮/触控板滚动接管测试（offscreen）：分流判据、原生距离公式、速度倍率。

设计判据（见 ui/animations.SmoothWheelScroller 文档）：
- 触控板（带 phase）纵向：**只按倍率缩放距离**，不加动画——系统惯性曲线照旧；
  倍率 1.0（标准档）时完全不介入，原样放行
- 鼠标滚轮（NoScrollPhase）纵向：消费事件，用 QPropertyAnimation 驱动滚动条
- Shift+纵向 / 横向主导 / 无可滚范围 / 已在边界 / 减少动效  →  放行
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

import ui.animations as animations
from ui.animations import SmoothWheelScroller, enable_smooth_wheel

pytest_app = QApplication.instance() or QApplication([])

_TRACKPAD_PHASES = (Qt.ScrollPhase.ScrollBegin, Qt.ScrollPhase.ScrollUpdate,
                    Qt.ScrollPhase.ScrollMomentum, Qt.ScrollPhase.ScrollEnd)


def _wheel(dy: int, phase=Qt.ScrollPhase.NoScrollPhase, dx: int = 0,
           modifiers=Qt.KeyboardModifier.NoModifier) -> QWheelEvent:
    """构造滚轮事件（dy：一格 -120 = 向下滚；pixelDelta 给同向值）。"""
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(dx * 8, dy * 8), QPoint(dx, dy),
        Qt.MouseButton.NoButton, modifiers, phase, False)


def _filled_list(rows: int = 300, pixel: bool = True) -> QListWidget:
    w = QListWidget()
    if pixel:
        w.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
    for i in range(rows):
        w.addItem(f"row {i}")
    w.resize(300, 200)
    w.show()
    pytest_app.processEvents()
    return w


def _install(area, *, instant: bool = False) -> SmoothWheelScroller:
    """装缓动层；instant 控制构造时读到的「减少动效」（避免真机设置干扰断言）。"""
    original = animations.reduce_motion_enabled
    animations.reduce_motion_enabled = lambda: instant
    try:
        return enable_smooth_wheel(area)
    finally:
        animations.reduce_motion_enabled = original


class _Speed:
    """with 块内临时改滚动速度倍率，退出时还原。

    倍率是模块级全局状态（事件处理时现读），不还原会串味到后面的用例。
    """

    def __init__(self, value: float):
        self._value = value
        self._old = 1.0

    def __enter__(self) -> float:
        self._old = animations.scroll_speed()
        animations.set_scroll_speed(self._value)
        return animations.scroll_speed()

    def __exit__(self, *exc) -> bool:
        animations.set_scroll_speed(self._old)
        return False


def _native_px(bar) -> float:
    """Qt 原生一格的距离（wheelScrollLines × singleStep）。"""
    return QApplication.wheelScrollLines() * max(1, bar.singleStep())


def _advance(bar, angle: int, speed: float) -> float:
    """向下滚 angle（负值 = 向下）在倍率下应推进的像素数。

    独立复述一遍 Qt 的换算式 `angleDelta/120 × wheelScrollLines × singleStep`
    再乘倍率——断言才算真的验了公式，而不是把实现抄进期望值。
    """
    return -((angle / 120.0) * _native_px(bar) * speed)


# ---- 鼠标滚轮：消费 + 原生距离 ----

def test_mouse_wheel_one_notch_uses_native_distance():
    """一格距离 == wheelScrollLines × singleStep（不自己拍步长）。"""
    w = _filled_list(rows=200)
    sc = _install(w)
    bar = w.verticalScrollBar()
    bar.setValue(0)
    expected = (QApplication.wheelScrollLines()
                * max(1, bar.singleStep()))

    assert sc.eventFilter(w.viewport(), _wheel(-120)) is True  # 消费
    QTest.qWait(500)  # 等缓动走完（≤320ms）
    assert bar.value() == expected
    w.close()


def test_mouse_wheel_passes_through_intermediate_values():
    """一次输入后走完一段减速才到位（不是瞬移）——必须观测到中间值。"""
    w = _filled_list(rows=400)
    sc = _install(w)
    bar = w.verticalScrollBar()
    bar.setValue(0)
    samples: list[int] = []
    bar.valueChanged.connect(samples.append)

    assert sc.eventFilter(w.viewport(), _wheel(-120)) is True
    for _ in range(20):
        QTest.qWait(20)

    target = QApplication.wheelScrollLines() * max(1, bar.singleStep())
    assert bar.value() == target
    between = [v for v in samples if 0 < v < target]
    assert between, f"未观测到中间值（瞬移）：{samples}"
    assert samples == sorted(samples)  # 单向推进，无来回跳动
    w.close()


def test_continuous_notches_accumulate_coherently():
    """连续快拨：目标值累加，不会每格重置回当前位置。"""
    w = _filled_list(rows=400)
    sc = _install(w)
    bar = w.verticalScrollBar()
    bar.setValue(0)

    for _ in range(3):
        assert sc.eventFilter(w.viewport(), _wheel(-120)) is True
    for _ in range(30):
        QTest.qWait(20)
    assert bar.value() == 3 * QApplication.wheelScrollLines() * max(1, bar.singleStep())
    w.close()


# ---- 触控板（标准档）：放行，不启动动画 ----

def test_trackpad_phases_are_passed_through():
    """带 phase 的纵向事件（触控板）在**标准档**必须原样放行——系统惯性由
    macOS 提供，倍率 1.0 就是「一个字节都不改」。"""
    w = _filled_list()
    sc = _install(w)
    bar = w.verticalScrollBar()
    bar.setValue(0)

    for phase in _TRACKPAD_PHASES:
        assert sc.eventFilter(w.viewport(), _wheel(-30, phase=phase)) is False
    assert sc.animating() is False
    w.close()


def test_trackpad_never_uses_animation_even_at_no_focus_phase_boundary():
    """ScrollMomentum 也放行：我们补一层减速会和系统惯性打架。"""
    w = _filled_list()
    sc = _install(w)
    w.verticalScrollBar().setValue(0)

    for _ in range(5):
        assert sc.eventFilter(
            w.viewport(), _wheel(15, phase=Qt.ScrollPhase.ScrollMomentum)) is False
    assert sc.animating() is False
    w.close()


# ---- 其余放行条件 ----

def test_shift_vertical_wheel_not_consumed():
    """Shift+纵向另有用途（模板页横向平移），不能抢。"""
    w = _filled_list()
    sc = _install(w)
    assert sc.eventFilter(
        w.viewport(),
        _wheel(-120, modifiers=Qt.KeyboardModifier.ShiftModifier)) is False
    w.close()


def test_horizontal_dominant_wheel_not_consumed():
    """横向滚轮（触控板横滑 / 倾斜滚轮）交给横向平移机。"""
    w = _filled_list()
    sc = _install(w)
    assert sc.eventFilter(w.viewport(), _wheel(0, dx=-120)) is False
    assert sc.eventFilter(w.viewport(), _wheel(-60, dx=-120)) is False
    w.close()


def test_no_scrollable_range_not_consumed():
    """没东西可滚：让事件冒泡给父滚动区（弹层内嵌列表的场景）。"""
    w = _filled_list(rows=0)
    sc = _install(w)
    assert w.verticalScrollBar().maximum() == 0
    assert sc.eventFilter(w.viewport(), _wheel(-120)) is False
    w.close()


def test_at_boundary_without_motion_not_consumed():
    """已在边界且无位移：同样让出去，不空转动画。"""
    w = _filled_list()
    sc = _install(w)
    bar = w.verticalScrollBar()
    bar.setValue(bar.maximum())
    assert sc.eventFilter(w.viewport(), _wheel(-120)) is False  # 想继续向下
    w.close()


def test_reduce_motion_disables_intervention():
    """系统「减少动效」开启：完全不介入，退回原生瞬时滚动。"""
    w = _filled_list()
    sc = _install(w, instant=True)
    bar = w.verticalScrollBar()
    bar.setValue(0)
    assert sc.eventFilter(w.viewport(), _wheel(-120)) is False
    assert sc.animating() is False
    w.close()


def test_slider_press_stops_animation():
    """用户拖滚动条时不与动画争 value。"""
    w = _filled_list()
    sc = _install(w)
    w.verticalScrollBar().setValue(0)

    assert sc.eventFilter(w.viewport(), _wheel(-120)) is True
    sc._stop()
    assert sc.animating() is False
    w.close()


# ---- 端到端：真实事件投递 + 主列表装配 ----

def test_wheel_event_is_consumed_end_to_end():
    """经 QApplication.sendEvent 投递（走真实事件过滤器链）也被消费。"""
    w = _filled_list(rows=400)
    sc = _install(w)
    w.verticalScrollBar().setValue(0)
    assert QApplication.sendEvent(w.viewport(), _wheel(-120)) is True
    QTest.qWait(500)
    assert w.verticalScrollBar().value() == (
        QApplication.wheelScrollLines() * max(1, w.verticalScrollBar().singleStep()))
    assert sc is w._smooth_wheel  # 引用挂在控件上（防 GC）
    w.close()


def test_animation_runs_inside_popup_window():
    """顶层 Qt.Popup 内的列表缓动照常被驱动。

    与 fade_in_window 记录的坑（§9：macOS 上 Popup 顶层窗**自身的** pos /
    windowOpacity 动画不被事件循环驱动）不同——这里动的是 popup **内部子控件**
    的 QScrollBar.value，属常规控件树路径，不受该限制（模块内所有 QListWidget
    接入点都处在 popup 里，故显式回归）。
    """
    popup = QWidget(None, Qt.FramelessWindowHint | Qt.Popup)
    popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
    lay = QVBoxLayout(popup)
    lst = QListWidget(popup)
    for i in range(200):
        lst.addItem(f"opt {i}")
    lay.addWidget(lst)
    popup.resize(240, 260)
    popup.show()
    pytest_app.processEvents()

    sc = _install(lst)
    bar = lst.verticalScrollBar()
    bar.setValue(0)
    samples: list[int] = []
    bar.valueChanged.connect(samples.append)

    assert sc.eventFilter(lst.viewport(), _wheel(-120)) is True
    for _ in range(20):
        QTest.qWait(20)

    target = QApplication.wheelScrollLines() * max(1, bar.singleStep())
    assert bar.value() == target
    assert samples == sorted(samples) and samples  # 逐步推进（非瞬移）
    popup.close()


def test_main_lists_use_pixel_scroll_mode_and_scroller():
    """四个主列表：逐像素模式（触控板连续跟随）+ 缓动层（鼠标滚轮）。"""
    from ui.collections_view import CollectionsView
    from ui.history_view import HistoryView
    from ui.templates_view import TemplatesView
    from ui.timeline_view import TimelineView

    # CollectionsView 的主列表是 _items（_list 是左侧分类栏，非主列表）
    for view in (HistoryView(), TimelineView(), CollectionsView(), TemplatesView()):
        list_widget = view._items if hasattr(view, "_items") else view._list
        assert list_widget.verticalScrollMode() == (
            QAbstractItemView.ScrollMode.ScrollPerPixel), type(view).__name__
        assert isinstance(getattr(list_widget, "_smooth_wheel", None),
                          SmoothWheelScroller), type(view).__name__
        view.close()


def test_scroll_areas_and_popups_are_wired(tmp_path):
    """设置页 / 模板滚动区 + 各类浮层：每个滚动面都装上了缓动层。

    浮层这项同时守住属性名（`self.list` / `self.edit` / `_popup._list` …）——
    写错属性名会静默不装，只有滚一遍才能发现。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from ui.app_picker_dialog import AppPickerDialog
    from ui.clean_data_dialog import CleanDataDialog
    from ui.fluent_combo import FluentComboBox
    from ui.item_detail_popup import ItemDetailPopup, _CodeView
    from ui.quick_paste_popup import QuickPastePopup
    from ui.settings_view import SettingsView
    from ui.template_components import VariableLibraryPopup
    from ui.template_picker_popup import TemplatePickerPopup
    from ui.templates_view import TemplateEditorDialog
    from ui.variable_autocomplete import VariableAutocompleteEditor

    def installed(area) -> bool:
        return isinstance(getattr(area, "_smooth_wheel", None),
                          SmoothWheelScroller)

    # 设置页滚动区 + 忽略应用列表
    settings = SettingsView()
    assert installed(settings._ignored_list)

    # 模板编辑弹窗的变量条滚动区 + 变量库弹层
    assert installed(TemplateEditorDialog()._var_scroll)
    assert installed(VariableLibraryPopup()._scroll)

    # 浮层列表
    assert installed(QuickPastePopup()._list)
    assert installed(TemplatePickerPopup()._list)
    assert installed(VariableAutocompleteEditor()._popup._list)
    assert installed(_CodeView().edit)
    assert installed(ItemDetailPopup()._text)
    assert installed(AppPickerDialog()._list)

    combo = FluentComboBox()
    combo.addItem("a", 1)
    combo._ensure_popup()  # 弹层懒建：open 时才构造
    assert installed(combo._popup.list)

    engine = create_db_engine(tmp_path / "scroll.db")
    migrate(engine)
    assert installed(CleanDataDialog(engine)._list)


# ---- 滚动速度倍率（设置页「滚动速度」）----
#
# macOS 经 Qt 递上来的滚动距离偏快：Qt 把一次输入的位移再乘 wheelScrollLines
# （默认 3）行。倍率就是在这条式子外面再乘一个系数——只改「走多远」，不改
# 各控件的步长，也不给触控板加动画。

def test_speed_factor_scales_mouse_wheel_distance():
    """鼠标滚轮：距离 = 原生 × 倍率（同样走缓动）。"""
    with _Speed(0.5):
        w = _filled_list(rows=400)
        sc = _install(w)
        bar = w.verticalScrollBar()
        bar.setValue(0)
        assert sc.eventFilter(w.viewport(), _wheel(-120)) is True
        QTest.qWait(500)  # 等缓动走完（≤320ms）
        assert bar.value() == round(_advance(bar, -120, 0.5))
        w.close()


def test_trackpad_vertical_is_scaled_without_animation():
    """触控板纵向：按倍率缩放距离，且**不启动画**（惯性曲线仍归系统）。

    8 次 Update(-30) 恰好等于 8 × 原生一格 × 0.5，中间没有取整损耗
    （亚像素余量跨事件累计，见下一条）。
    """
    with _Speed(0.5):
        w = _filled_list(rows=400)
        sc = _install(w)
        bar = w.verticalScrollBar()
        bar.setValue(0)
        for _ in range(8):
            assert sc.eventFilter(
                w.viewport(),
                _wheel(-30, phase=Qt.ScrollPhase.ScrollUpdate)) is True
        assert bar.value() == round(8 * _advance(bar, -30, 0.5))
        assert sc.animating() is False
        w.close()


def test_trackpad_momentum_is_scaled_too():
    """惯性段（ScrollMomentum）同样缩放：减速是系统那条，只是整体变短。"""
    with _Speed(0.5):
        w = _filled_list(rows=400)
        sc = _install(w)
        bar = w.verticalScrollBar()
        bar.setValue(0)
        for _ in range(8):
            assert sc.eventFilter(
                w.viewport(),
                _wheel(-30, phase=Qt.ScrollPhase.ScrollMomentum)) is True
        assert bar.value() == round(8 * _advance(bar, -30, 0.5))
        w.close()


def test_trackpad_subpixel_deltas_accumulate_instead_of_rounding_away():
    """慢速档下单次位移可能不足 1px：余量要攒着，不能每次四舍五入抹平。"""
    with _Speed(0.5):
        w = _filled_list(rows=400)
        sc = _install(w)
        bar = w.verticalScrollBar()
        bar.setValue(0)
        # 单次 ≈ -2/120 × 3 × 17 × 0.5 ≈ -0.43px：先消费但不动
        assert sc.eventFilter(
            w.viewport(), _wheel(-2, phase=Qt.ScrollPhase.ScrollUpdate)) is True
        assert bar.value() == 0
        for _ in range(10):
            sc.eventFilter(w.viewport(),
                           _wheel(-2, phase=Qt.ScrollPhase.ScrollUpdate))
        assert bar.value() > 0, "亚像素余量被抹平：慢速档下滑不动"
        assert abs(bar.value() - 11 * _advance(bar, -2, 0.5)) < 1
        w.close()


def test_trackpad_at_boundary_passes_through_when_scaling():
    """缩放档下已在边界且往边界外推：让出去，父滚动区接（设置页内嵌列表）。"""
    with _Speed(0.5):
        w = _filled_list(rows=200)
        sc = _install(w)
        bar = w.verticalScrollBar()
        bar.setValue(bar.maximum())
        assert sc.eventFilter(
            w.viewport(), _wheel(-30, phase=Qt.ScrollPhase.ScrollUpdate)) is False
        bar.setValue(bar.minimum())
        assert sc.eventFilter(
            w.viewport(), _wheel(30, phase=Qt.ScrollPhase.ScrollUpdate)) is False
        w.close()


def test_trackpad_horizontal_still_passes_through_when_scaled():
    """横向手势（历史页横滑切类型 / 模板页横滑平移）不受倍率影响。"""
    with _Speed(0.5):
        w = _filled_list(rows=400)
        sc = _install(w)
        assert sc.eventFilter(
            w.viewport(), _wheel(0, dx=-120,
                                 phase=Qt.ScrollPhase.ScrollUpdate)) is False
        w.close()


def test_speed_change_applies_to_already_installed_scroller():
    """倍率是事件处理时现读：改设置立刻对已装好的滚动面生效，无需重建控件。"""
    w = _filled_list(rows=400)
    sc = _install(w)
    bar = w.verticalScrollBar()
    bar.setValue(0)
    # 标准档：触控板原样放行
    assert sc.eventFilter(
        w.viewport(), _wheel(-30, phase=Qt.ScrollPhase.ScrollUpdate)) is False
    with _Speed(0.5):
        assert sc.eventFilter(
            w.viewport(), _wheel(-30, phase=Qt.ScrollPhase.ScrollUpdate)) is True
    assert bar.value() > 0
    w.close()


def test_set_scroll_speed_clamps_and_ignores_garbage():
    """值域钳制到 0.2–3.0；非法值忽略并保持原值（设置页写入前先过这一关）。"""
    old = animations.scroll_speed()
    try:
        animations.set_scroll_speed(99)
        assert animations.scroll_speed() == 3.0
        animations.set_scroll_speed(0.0)
        assert animations.scroll_speed() == 0.2
        animations.set_scroll_speed("不是数字")
        assert animations.scroll_speed() == 0.2
        animations.set_scroll_speed(None)
        assert animations.scroll_speed() == 0.2
    finally:
        animations.set_scroll_speed(old)


def test_trackpad_scaling_end_to_end():
    """经 QApplication.sendEvent 投递（真实过滤器链）也被缩放消费。"""
    with _Speed(0.5):
        w = _filled_list(rows=400)
        sc = _install(w)
        bar = w.verticalScrollBar()
        bar.setValue(0)
        for _ in range(8):
            QApplication.sendEvent(
                w.viewport(), _wheel(-30, phase=Qt.ScrollPhase.ScrollUpdate))
        assert bar.value() == round(8 * _advance(bar, -30, 0.5))
        assert sc.animating() is False
        w.close()
