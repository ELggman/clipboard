"""滚动视觉装饰测试（offscreen）：四种装饰都能装、能开关、静止时零残留。

验收标准（见 ui/scroll_fx.py 模块文档）：
- 悬浮滚动条：原生条转 AlwaysOff、浮层条几何跟随视口、能拖拽
- 上下边缘渐隐：只在**还有内容**的那一侧画，滚到端点收成 0
- 视差 / 抬升：只在滚动进行中非零，停下约 330ms 内衰减到 0
- 设置页那几项能逐项开关，已装配的滚动区立刻生效
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QImage, QRegion, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QWidget

import ui.scroll_fx as scroll_fx
from app.types import ClipboardItem
from ui.history_view import HistoryView
from ui.scroll_fx import enable_scroll_fx, parse_color

pytest_app = QApplication.instance() or QApplication([])


def _view(rows: int = 60) -> HistoryView:
    view = HistoryView()
    view.set_items([ClipboardItem(type="text", content=f"条目 {i} 的内容")
                    for i in range(rows)])
    view.resize(420, 460)
    view.show()
    pytest_app.processEvents()
    return view


def _settle(fx, ticks: int = 40) -> None:
    """把装饰推到静止态（activity 归零）。"""
    for _ in range(ticks):
        fx._tick()
    pytest_app.processEvents()


def _wheel(dy: int = -120) -> QWheelEvent:
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(0, dy * 8), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False)


# ---- 调色板颜色解析 ----

def test_parse_color_handles_rgba_and_hex():
    """调色板里 scrollbar 是 QSS 函数串，QColor 不认——自己解一次（§9）。"""
    c = parse_color("rgba(0, 0, 0, 0.22)")
    assert c.isValid()
    assert (c.red(), c.green(), c.blue()) == (0, 0, 0)
    assert c.alpha() == round(255 * 0.22)

    h = parse_color("#1E1E1E")
    assert h.isValid() and h.alpha() == 255 and h.red() == 0x1E

    # 完全解析不了时退回兜底色，绝不返回无效 QColor（画出来是黑块）
    bad = parse_color("not-a-color")
    assert bad.isValid()


# ---- 悬浮滚动条 ----

def test_overlay_scrollbar_replaces_native_one():
    view = _view()
    lst = view._list
    assert lst.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    fx = lst._scroll_fx
    assert fx.overlay.parent() is lst.viewport()
    assert fx.edges.parent() is lst.viewport()
    view.close()


def test_enable_scroll_fx_is_idempotent():
    """重复装配只补挂 delegate，不会叠出第二条浮层条。"""
    w = QListWidget()
    for i in range(50):
        w.addItem(f"row {i}")
    w.resize(200, 150)
    w.show()
    pytest_app.processEvents()
    first = enable_scroll_fx(w)
    second = enable_scroll_fx(w)
    assert first is second
    assert w.findChildren(scroll_fx.OverlayScrollBar) == [first.overlay]
    w.close()


def test_overlay_geometry_follows_viewport():
    view = _view()
    fx = view._list._scroll_fx
    vp = view._list.viewport().rect()
    assert fx.overlay.geometry().right() == vp.right()
    assert fx.overlay.height() == vp.height()
    view.close()


def test_overlay_handle_moves_with_value():
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    bar = lst.verticalScrollBar()
    assert bar.maximum() > 0, "60 行放不进 460px 视口"

    bar.setValue(bar.minimum())
    top = fx.overlay._handle_rect().top()
    bar.setValue(bar.maximum())
    bottom = fx.overlay._handle_rect().top()
    assert bottom > top
    # 滑块高度落在 [最小值, 轨道高] 内，且滚到底时不越出轨道
    h = fx.overlay._handle_rect().height()
    assert scroll_fx._BAR_MIN_H <= h <= fx.overlay.height()
    assert bottom + h <= fx.overlay.height() + 0.5
    view.close()


def test_overlay_drag_sets_value():
    """点住滑块往下拖 → 滚动条值跟着走（不是只能看不能动）。"""
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    bar = lst.verticalScrollBar()
    bar.setValue(bar.minimum())
    fx.overlay._grab_dy = 0
    fx.set_drag(True)
    fx.overlay._set_value_at(fx.overlay.height() * 0.5)
    fx.set_drag(False)
    assert bar.value() > bar.minimum()
    view.close()


def test_overlay_is_mouse_transparent_when_hidden():
    """闲置淡出后必须不吃鼠标，否则右侧 10px 的条目永远点不到。"""
    view = _view()
    fx = view._list._scroll_fx
    _settle(fx)
    assert fx.bar_alpha() == 0.0
    assert fx.overlay.testAttribute(
        Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    view.close()


def test_overlay_fade_completes_before_timer_stops():
    """回归：activity（~330ms）比滚动条淡出（~1.2s）先归零，静止判据必须连
    淡出一起等——只判 activity 会在浮层条还是 1.0 时就停表，条卡在画面上。"""
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    lst.verticalScrollBar().setValue(lst.verticalScrollBar().maximum() // 2)
    QTest.qWait(1700)
    assert fx._timer.isActive() is False, "静止后不该还在跑计时器"
    assert fx.bar_alpha() == 0.0
    view.close()


# ---- 边缘渐隐 ----

def _alpha_at(widget, x: int, y: int) -> int:
    """读控件某点的 alpha。

    两条都得注意：不能用 `grab()`（它会把调色板底色垫在下面，透明处读出来也是
    255），`render()` 也不能带默认的 `DrawWindowBackground`——同样会先铺一层不透明
    底色。只画控件自己的 paintEvent，没画到的地方才留得住透明。
    """
    img = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    widget.render(img, QPoint(), QRegion(), QWidget.RenderFlag.DrawChildren)
    return img.pixelColor(x, y).alpha()


def test_edge_fade_only_paints_where_more_content():
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    bar = lst.verticalScrollBar()
    edges = fx.edges

    bar.setValue(bar.minimum())
    _settle(fx)
    assert _alpha_at(edges, 5, 1) == 0, "已在顶部，上边缘不该有渐隐"
    assert _alpha_at(edges, 5, edges.height() - 2) > 0, "下方还有内容"

    mid = (bar.minimum() + bar.maximum()) // 2
    bar.setValue(mid)
    _settle(fx)
    assert _alpha_at(edges, 5, 1) > 0
    assert _alpha_at(edges, 5, edges.height() - 2) > 0

    bar.setValue(bar.maximum())
    _settle(fx)
    assert _alpha_at(edges, 5, 1) > 0, "上方还有内容"
    assert _alpha_at(edges, 5, edges.height() - 2) == 0, "已在底部"
    view.close()


# ---- 视差 / 抬升的 activity ----

def test_activity_starts_and_ends_at_zero():
    """静止时 activity 恒为 0——delegate 因此走**与没有装饰时逐像素相同**的
    绘制路径（test_list_enter 的收尾帧用例就是靠这条）。"""
    view = _view()
    fx = view._list._scroll_fx
    _settle(fx)
    assert fx.activity() == 0.0
    assert fx.parallax_for(QRect(0, 0, 400, 100)) == 0
    view.close()


def test_wheel_marks_activity_then_decays():
    """滚一下 activity → 1，停下后由**真实的**计时器衰减回 0（余韵约 330ms）。

    这里刻意走真实等待而不是手动 `_tick`：滚轮事件同时会启动缓动层，缓动会
    不断 `setValue` → 反复把 activity 拉回 1，手动步进的时序因此不可靠。
    """
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    _settle(fx)
    assert fx.activity() == 0.0

    QApplication.sendEvent(lst.viewport(), _wheel())
    assert fx.activity() == 1.0

    QTest.qWait(1200)          # 缓动跑完 + 余韵衰减干净
    assert fx.activity() == 0.0
    view.close()


def test_parallax_sign_flips_across_center():
    """越靠边的行让得越多，方向关于视口中心对称。"""
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    _settle(fx)
    try:
        # 景深开着时视差自动让位（见 test_depth_supersedes_legacy_parallax），
        # 这里要单独验旧通道，先把景深关掉
        scroll_fx.set_scroll_effects({"depth": False})
        fx._mark_active()

        vp = lst.viewport().rect()
        top = fx.parallax_for(QRect(0, vp.top(), 400, 90))
        bottom = fx.parallax_for(QRect(0, vp.bottom() - 90, 400, 90))
        assert top > 0 > bottom, "上边的行往下让、下边的行往上让"
        assert abs(top) <= scroll_fx._PARALLAX_PX
        assert abs(bottom) <= scroll_fx._PARALLAX_PX
    finally:
        scroll_fx.set_scroll_effects(dict.fromkeys(
            ("scrollbar", "edge_fade", "parallax", "depth", "lift"), True))
    view.close()


# ---- 设置开关 ----

def test_set_scroll_effects_applies_live():
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    try:
        scroll_fx.set_scroll_effects({"scrollbar": False, "parallax": False})
        assert not fx.overlay.isVisible()
        assert lst.verticalScrollBarPolicy() == \
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        # 关掉视差后即使正在滚动也不位移
        fx._mark_active()
        assert fx.parallax_for(QRect(0, 0, 400, 100)) == 0

        scroll_fx.set_scroll_effects({"scrollbar": True, "parallax": True,
                                      "edge_fade": False})
        assert lst.verticalScrollBarPolicy() == \
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        assert not fx.edges.isVisible()
    finally:  # 模块级状态是全局的，别污染后面的用例
        scroll_fx.set_scroll_effects(dict.fromkeys(
            ("scrollbar", "edge_fade", "parallax", "depth", "lift"), True))
    view.close()


def test_lift_toggle_actually_disables_lift():
    """回归：只关「卡片抬升」时 activity 仍是 1.0（视差还开着），若 delegate
    直接读 `activity()` 就永远不会停——勾选框等于没接上（用户实测报的
    「开关不明显」）。强度必须走 `lift()`。"""
    view = _view()
    fx = view._list._scroll_fx
    vp = view._list.viewport()
    # 先把逐项入场推到静止：它由绘制驱动、随时间推进，否则两次 shot 之间
    # 那一屏还在淡入，像素本来就不同（与抬升无关）
    view._delegate.enter_animator.stop()
    pytest_app.processEvents()

    def shot() -> QImage:
        fx._timer.stop()          # 钉住 activity，隔绝衰减
        fx._activity = 1.0
        vp.repaint()
        pytest_app.processEvents()
        return vp.grab().toImage()

    try:
        scroll_fx.set_scroll_effects({"lift": False, "parallax": True})
        fx._mark_active()
        assert fx.activity() == 1.0, "视差还开着，activity 照旧是 1"
        assert fx.lift() == 0.0, "但抬升强度必须归零"
        off = shot()

        scroll_fx.set_scroll_effects({"lift": True})
        on = shot()
        assert on != off, "勾上「卡片抬升」画面必须真的变（回归：曾经完全没接上）"

        # 取消勾选要回到关闭态的像素——不留半点阴影
        scroll_fx.set_scroll_effects({"lift": False})
        assert shot() == off
    finally:
        scroll_fx.set_scroll_effects(dict.fromkeys(
            ("scrollbar", "edge_fade", "parallax", "depth", "lift"), True))
    view.close()


def test_scroll_effects_default_all_on():
    assert scroll_fx.scroll_effects() == {
        "scrollbar": True, "edge_fade": True, "parallax": True,
        "depth": True, "lift": True}


# ---- 卡片景深（第 5 项，移植自 demo_v.py）----

def test_depth_is_bottom_only_and_down_scroll_only():
    """景深的两条硬约束（用户明确要求，别改回去）：

    ① **只作用于视口中心以下**——上半屏恒等，顶部不能有任何形变；
    ② **只在往下翻列表时出现**——往回翻或停下都要完全消失。

    ⚠️ 与 demo_v.py 不同：demo 是「上下对称 + 常驻」，我们按用户要求改成了
    「只在下半屏 + 只在往下翻」。所以这两个断言是**刻意的偏离**，不是 bug。
    """
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    fx._timer.stop()
    try:
        vp = lst.viewport().rect()
        top = QRect(0, vp.top(), 400, 90)
        bottom = QRect(0, vp.bottom() - 90, 400, 90)
        lower_mid = QRect(0, vp.center().y() + 10, 400, 90)

        # ① 停下（activity 归零）→ 整体为 0，直接回原路径
        fx._down = 1.0
        fx._activity = 0.0
        assert fx.depth_for(top) is None
        assert fx.depth_for(bottom) is None, "停下就不该还留着形变"

        # ② 往下翻列表（闸门开）→ 下半屏有效果，上半屏恒等
        fx._down = 1.0
        fx._activity = 1.0
        assert fx.depth_for(top) is None, "顶部不该有任何效果"
        d = fx.depth_for(bottom)
        assert d is not None
        scale, push, dim = d
        assert scale < 1.0, "下半屏要缩小"
        assert push > 0, "且向下推（向外）"
        assert dim > 0, "且向背景淡出"
        assert abs(push) <= scroll_fx._DEPTH_PUSH_PX + 0.01

        # 越靠下缩得越多（渐变，不是硬切）
        d_lower = fx.depth_for(lower_mid)
        assert d_lower is not None and d_lower[0] > scale

        # ③ 往回翻（方向闩锁翻到 0）→ 立刻没有效果
        fx._down = 0.0
        fx._activity = 1.0
        assert fx.depth_for(bottom) is None, "往回翻不该有效果"

        # ④ 开关关掉 → 同样 None
        scroll_fx.set_scroll_effects({"depth": False})
        fx._down = 1.0
        assert fx.depth_for(bottom) is None
    finally:
        scroll_fx.set_scroll_effects(dict.fromkeys(
            ("scrollbar", "edge_fade", "parallax", "depth", "lift"), True))
    view.close()


def test_depth_supersedes_legacy_parallax():
    """两个都开会把缩略图推两次——景深开着时视差自动让位。"""
    view = _view()
    fx = view._list._scroll_fx
    rect = QRect(0, 0, 400, 100)
    try:
        scroll_fx.set_scroll_effects({"depth": True, "parallax": True})
        fx._mark_active()
        assert fx.parallax_for(rect) == 0

        scroll_fx.set_scroll_effects({"depth": False})
        fx._mark_active()
        assert fx.parallax_for(rect) != 0, "景深关掉后视差要回来"
    finally:
        scroll_fx.set_scroll_effects(dict.fromkeys(
            ("scrollbar", "edge_fade", "parallax", "depth", "lift"), True))
    view.close()


def test_down_gate_latches_through_momentum_decay():
    """回归：闸门只看**方向**，不看速度——一段滚动的惯性衰减不该让它掉下去。

    早先这里算的是「瞬时速度 / 参考速度」，于是每段轻扫衰到阈值以下时整块下半屏
    缩回去、下一次轻扫再缩回来，连扫几下就是不停放大缩小 —— 用户实测报的
    「动画效果不错，就是滑动着看着有点卡顿」就是它。用旧公式的话，下面这段惯性
    尾巴（末帧只走 1px ≈ 59px/s）会把闸门打到 0.24 左右。
    """
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    fx._timer.stop()
    try:
        bar = lst.verticalScrollBar()
        bar.setValue(bar.minimum() + 300)
        fx._down = 0.0
        fx._last_bar_value = bar.value()

        # 一次甩动的尾巴：每帧位移递减到 0（末三帧「本帧没动」）
        for dv in (24, 20, 16, 12, 8, 5, 3, 1, 1, 1, 0, 0, 0):
            if dv:
                bar.setValue(bar.value() + dv)     # 会经 valueChanged 刷新 activity
            fx._tick()
        assert fx._down_gate() > 0.9, "惯性尾巴上闸门不能掉下去"

        # 反向：闩锁要翻过去
        for _ in range(6):
            bar.setValue(bar.value() - 20)
            fx._tick()
        assert fx._down_gate() < 0.2, "反向要翻转"
    finally:
        scroll_fx.set_scroll_effects(dict.fromkeys(
            ("scrollbar", "edge_fade", "parallax", "depth", "lift"), True))
    view.close()


def test_depth_off_is_pixel_identical():
    """关掉景深后，同一帧与「从没开过」逐像素一致（不残留半个 save/restore）。

    ⚠️ 景深现在**只在往下翻列表时非零**，所以要把闸门手动推上去——否则开关两种
    状态都是恒等，`on != off` 会假通过（这条用例曾经因为改了门槛而失去意义）。
    """
    view = _view()
    fx = view._list._scroll_fx
    vp = view._list.viewport()
    view._delegate.enter_animator.stop()   # 入场动画会随时间推进，先推到静止
    pytest_app.processEvents()

    def shot() -> QImage:
        fx._timer.stop()
        fx._activity = 1.0
        fx._down = 1.0                          # 打开「正在往下翻」的闸门
        vp.repaint()
        pytest_app.processEvents()
        return vp.grab().toImage()

    try:
        scroll_fx.set_scroll_effects({"depth": False})
        off = shot()
        scroll_fx.set_scroll_effects({"depth": True})
        on = shot()
        assert on != off, "开着景深画面必须真的变（否则等于没接上）"
        scroll_fx.set_scroll_effects({"depth": False})
        assert shot() == off
    finally:
        scroll_fx.set_scroll_effects(dict.fromkeys(
            ("scrollbar", "edge_fade", "parallax", "depth", "lift"), True))
    view.close()


def test_reduce_motion_turns_off_parallax_and_lift(monkeypatch):
    """系统「减少动效」→ 视差/抬升/景深不播（悬浮条与渐隐是静态装饰，保留）。"""
    monkeypatch.setattr(scroll_fx, "reduce_motion_enabled", lambda: True)
    assert scroll_fx._motion_effects() is False
    view = _view()
    fx = view._list._scroll_fx
    fx._mark_active()
    assert fx.activity() == 0.0
    assert fx.parallax_for(QRect(0, 0, 400, 100)) == 0
    # 景深严格说静止时也在，但「减少动效」下同样要整个关掉
    assert fx.depth_for(QRect(0, 0, 400, 100)) is None
    view.close()


# ---- 收尾：装饰不留下静态残留 ----

def test_frame_identical_after_scroll_settles():
    """滚一屏再停稳，视口与「从没滚过」逐像素一致（装饰全归零）。"""
    view = _view()
    lst = view._list
    fx = lst._scroll_fx
    bar = lst.verticalScrollBar()
    view._delegate.enter_animator.stop()   # 先让逐项入场归位，否则基准帧是中间态
    QTest.qWait(1100)
    before = lst.viewport().grab().toImage()

    QApplication.sendEvent(lst.viewport(), _wheel())
    QTest.qWait(60)
    mid = lst.viewport().grab().toImage()
    assert mid != before, "滚动中应有视差/抬升（否则装饰没生效）"

    QTest.qWait(1500)          # 缓动 + 装饰余韵归零
    bar.setValue(bar.minimum())
    QTest.qWait(1500)          # 回顶后再等浮层条淡出
    assert fx.activity() == 0.0
    assert fx.bar_alpha() == 0.0
    lst.viewport().repaint()
    pytest_app.processEvents()
    assert lst.viewport().grab().toImage() == before
    view.close()
