"""历史列表逐项入场动画测试（offscreen）。

验收标准 → 用例一一对应（见 ui/animations.ListEnterAnimator 文档）：
- 首次填充：错峰 50ms、单行 300ms、末行延迟封顶 500ms（整段 ≤800ms，与行数无关）
- **只有首次填充那一屏入场**：滚动露面的行一律静止（回归：滚动中每行都是
  「初次露面」，逐条播会让整个视口常驻半透明中间态 → 用户实测报「帧率低、
  不丝滑」）；用户一滚动，瀑布立即收摊（否则装载后 800ms 内滚到的行会按
  500ms 延迟隐身半秒）
- 统一进度驱动：静止态 delegate 完全走原路径，收尾帧与无动画逐像素一致
- 刷新时旧动画停止并重置（不叠加、不残留）；单条插入不播
- 不建 per-item 动画对象、不用 QGraphicsEffect
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget

import ui.animations as animations
from app.types import ClipboardItem
from ui.animations import ListEnterAnimator
from ui.history_view import TYPE_FILTERS, HistoryView

pytest_app = QApplication.instance() or QApplication([])


def _wheel(dy: int = -120, dx: int = 0) -> QWheelEvent:
    """真实滚轮事件——「人滚了」的判据只认真实输入，程序化 setValue 不算
    （见 `ListEnterAnimator.__init__`）。`dx` 用来模拟触控板横滑（只有 x 分量）。"""
    return QWheelEvent(
        QPointF(10, 10), QPointF(10, 10),
        QPoint(dx * 8, dy * 8), QPoint(dx, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False)


def _bare_animator() -> ListEnterAnimator:
    """不起视图的动画器（只验时间线数学与记录表；可见性由 observe 手工上报）。"""
    return ListEnterAnimator(QListWidget())


def _view(rows: int = 20) -> HistoryView:
    view = HistoryView()
    view.set_items([ClipboardItem(type="text", content=f"条目 {i} 的内容")
                    for i in range(rows)])
    view.resize(420, 460)
    view.show()
    pytest_app.processEvents()
    return view


def _animator(view: HistoryView) -> ListEnterAnimator:
    return view._delegate.enter_animator


def _settle(view: HistoryView) -> None:
    """把动画推到静止态并等一帧重绘落地。"""
    _animator(view).stop()
    pytest_app.processEvents()


# ---- 时间线：错峰 / 单行时长 / 末行封顶 ----

def test_timeline_stagger_and_last_row_cap():
    """错峰 50ms、单行 300ms；末行延迟封顶 500ms（千项列表也 ≤800ms）。"""
    a = _bare_animator()
    assert ListEnterAnimator.ROW_MS == 300
    assert ListEnterAnimator.STAGGER_MS == 50
    assert ListEnterAnimator.MAX_DELAY_MS == 500
    assert ListEnterAnimator.OFFSET_PX == 64

    assert a.total_ms(0) == 0
    assert a.total_ms(1) == 300                 # 单行
    # 延迟 = (rows-1)*STAGGER，到 MAX_DELAY 就封顶：从这一行起整段恒为 800
    capped_from = ListEnterAnimator.MAX_DELAY_MS // ListEnterAnimator.STAGGER_MS + 1
    assert a.total_ms(capped_from - 1) == (
        (capped_from - 2) * ListEnterAnimator.STAGGER_MS + 300)   # 未触顶
    assert a.total_ms(capped_from) == 800       # 刚好触顶
    assert a.total_ms(1000) == 800              # 上千项一样


def test_first_fill_staggers_by_row_index_and_caps_delay():
    """首次填充：行按下标错峰，第 cap_row 行起延迟封顶 500ms（不再增长）。"""
    a = _bare_animator()
    a.play(20)
    for row in (0, 5, 12, 13, 19):
        a.observe(row)
    base = a._starts[0][0]
    stagger = ListEnterAnimator.STAGGER_MS
    cap = ListEnterAnimator.MAX_DELAY_MS
    # ±20ms 容忍：每次 observe 各读一次时钟，走字可能差 1ms
    assert abs(a._starts[5][0] - base - 5 * stagger) <= 20
    assert abs(a._starts[12][0] - base - min(12 * stagger, cap)) <= 20
    assert abs(a._starts[13][0] - base - min(13 * stagger, cap)) <= 20
    assert abs(a._starts[19][0] - base - cap) <= 20   # 封顶后不再增长
    a.stop()


def test_first_fill_waterfall_runs_front_to_back():
    """前排先动、后排按错峰跟上（时间线整体向前，不回头）。"""
    a = _bare_animator()
    a.play(6)
    for row in range(6):
        a.observe(row)

    assert a.local(0) < 0.05
    assert a.local(5) == 0.0          # 延迟 200ms：还没轮到（精确 0）

    QTest.qWait(100)                  # row0 已过半；row5 还没轮到
    assert 0.0 < a.local(0) < 1.0
    assert a.local(5) == 0.0

    QTest.qWait(600)                  # row5 = 200ms 延迟 + 300ms
    assert a.local(0) == 1.0
    assert a.local(5) == 1.0
    a.stop()


def test_easing_is_fast_first_then_decelerating():
    """缓动「先快后慢」：前半程走完的距离多于后半程。"""
    a = _bare_animator()
    a.play(1)
    a.observe(0)
    QTest.qWait(150)           # 过半
    half = a.local(0)
    QTest.qWait(150)           # 收尾
    end = a.local(0)
    assert half > 0.5, half                       # 前 150ms 已走过一半
    assert (half - 0.0) > (end - half)            # 且比后 150ms 走得多
    a.stop()


# ---- 记录表：行号位移与「新行不播」 ----

def test_scroll_never_schedules_entrance():
    """用户一滚动，瀑布收摊：之后露面的行不排入场（`_starts` 不再增长）。

    回归：滚动中几乎每一行都是「初次露面」，若继续按 `MAX_DELAY_MS` 给它排队，
    整个视口会常驻半透明 + 位移的中间态——实测 100% 可见行 alpha < 0.9、
    中位仅 0.37，读起来就是掉帧。
    """
    a = _bare_animator()
    a.play(50)
    for row in range(4):
        a.observe(row)                 # 首批可见行（瀑布档）
    assert len(a._starts) == 4

    a._on_scrolled(300)                # 滚动条动了
    assert a._waterfall is False
    a.observe(4)                       # 滚动露面的行
    a.observe(37)
    assert len(a._starts) == 4, "滚动露面的行不该进记录表"
    assert a.local(4) == 1.0           # 立即可见、无位移
    assert a.offset_for(4) == 0.0
    a.stop()


def test_scroll_before_first_paint_settles_immediately():
    """首帧还没画就先滚动：一行都没排上，直接回静止态（别让 `_active` 挂着）。

    `play()` 只置 `_active`，定时器由首帧绘制时的 `observe` 启动——若滚动抢在
    首次绘制之前，没有 observe 会再排入场，定时器就没机会起来收尾。
    """
    a = _bare_animator()
    a.play(50)
    assert a.active is True and not a._starts
    a._on_scrolled(120)
    assert a.active is False
    assert a.local(0) == 1.0
    a.stop()


def test_first_fill_lands_and_then_observe_is_a_no_op():
    """瀑布播完后 `observe` 完全不动（`_active` 为假即返回）——记录表不再增长，
    上千行滚过去也不占内存、`rows_inserted` 的重排也就一直是几行。"""
    a = _bare_animator()
    a.play(3)
    for row in range(3):
        a.observe(row)
    QTest.qWait(600)                   # 末行 100ms 延迟 + 300ms
    assert a.active is False
    before = dict(a._starts)

    for row in range(3, 2000):
        a.observe(row)
    assert a._starts == before
    assert all(a.local(r) == 1.0 for r in (3, 500, 1999))
    a.stop()


def test_insert_shifts_row_records_and_settles_the_new_row():
    """实时捕获插入一行：后面的记录跟着后移，新行按「已露过面」处理。"""
    a = _bare_animator()
    a.play(20)
    for row in range(5):
        a.observe(row)
    before = dict(a._starts)

    a.rows_inserted(2)                # 在第 2 行前插入一行

    assert a._starts[0] == before[0]
    assert a._starts[1] == before[1]
    assert a._starts[3] == before[2]  # 2..4 整体后移一位
    assert a._starts[4] == before[3]
    assert a.local(2) == 1.0          # 新行已就位（不播入场）
    a.stop()


# ---- 静止态：delegate 完全走原路径 ----

def test_idle_state_is_identity():
    """未播放时 local 恒为 1、delegate 不做任何形变（保证与旧行为一致）。"""
    view = _view()
    _settle(view)  # set_items 本身会播一次，先推到静止态
    anim = _animator(view)
    assert anim.active is False
    assert [anim.local(r) for r in (0, 5, 19)] == [1.0, 1.0, 1.0]
    assert view._delegate._enter_fx(0) is None
    assert view._delegate._enter_fx(19) is None
    view.close()


def test_play_then_settle_returns_to_identity():
    """播完自动回静止态：所有行 local=1、delegate 回到原路径。"""
    view = _view(rows=6)
    anim = _animator(view)
    anim.play(6)
    assert anim.active is True
    QTest.qWait(900)  # 6 项：末行延迟 200ms + 300ms = 500ms
    assert anim.active is False
    assert all(anim.local(r) == 1.0 for r in range(6))
    assert view._delegate._enter_fx(0) is None
    view.close()


# ---- 逐项入场：偏移 + 透明度 ----

def test_rows_enter_from_below_with_alpha():
    """行从下方 40px 滑入、透明度 0→1；位移与透明度同源。"""
    view = _view(rows=6)
    anim = _animator(view)
    anim.play(6)
    pytest_app.processEvents()  # 首帧绘制把可见行记入（入场由绘制驱动）

    enter = view._delegate._enter_fx(0)
    assert enter is not None
    dy, alpha = enter
    assert 0.0 <= alpha < 0.2, alpha
    assert dy == pytest.approx(anim.OFFSET_PX * (1.0 - alpha))  # 同源：dy 由 alpha 推出

    QTest.qWait(600)
    assert view._delegate._enter_fx(0) is None   # 收尾后回归原路径
    view.close()


# ---- 滚动（核心：滚动一律不动画） ----

def test_first_fill_only_records_visible_rows():
    """整表填充只为**可见**的行记起始时刻——屏幕外的行不参与瀑布。"""
    view = _view(rows=200)
    anim = _animator(view)
    assert 0 < len(anim._starts) < 100      # 只有视口里那几行
    assert max(anim._starts) < 100
    view.close()


def test_scrolling_reveals_rows_without_entrance():
    """滚到底：新露面的行**直接以最终形态出现**——不排入场、不改透明度。

    这是「滑动不丝滑」的正解：入场只属于内容刚装载时那一屏，滚动时行要跟着
    手指走，任何叠加的位移/淡入都会读成卡顿。
    """
    view = _view(rows=200)
    anim = _animator(view)
    QTest.qWait(900)                        # 首批瀑布播完
    assert anim.active is False
    seen = set(anim._starts)

    bar = view._list.verticalScrollBar()
    bar.setValue(bar.maximum())             # 滚到底：一批从未露面的行首次可见
    pytest_app.processEvents()

    assert anim.active is False, "滚动不该启动入场动画"
    assert set(anim._starts) == seen, "滚动露面的行不该进记录表"
    fresh = [r for r in range(anim._view.model().rowCount())
             if r not in seen]
    assert fresh
    sample = fresh[-1]
    assert anim.local(sample) == 1.0
    assert anim.offset_for(sample) == 0.0
    assert view._delegate._enter_fx(sample) is None   # delegate 走原路径
    view.close()


def test_scrolling_during_fill_window_keeps_rows_crisp():
    """装载后立刻滚动：新露面的行不能按瀑布延迟排队（回归）。

    之前 `_waterfall` 要等首批播完（~800ms）才翻假，其间滚到的行会拿到
    `min(行号×50, 500)` 的延迟 → 位移一整行高、alpha 0，**隐身半秒**。
    实测：这就是「一 tab 切过去就滑」时整个视口发虚的来源。
    """
    view = _view(rows=200)
    anim = _animator(view)
    assert anim.active is True              # 首批瀑布正在播（还没到 800ms）
    assert anim._waterfall is True

    bar = view._list.verticalScrollBar()
    assert bar.maximum() > 0
    QApplication.sendEvent(view._list.viewport(), _wheel())   # 立刻滚动
    pytest_app.processEvents()

    assert anim._waterfall is False         # 瀑布立刻收摊
    last = anim._view.model().rowCount() - 1
    assert anim.local(last) == 1.0          # 新行立即就位，不是 alpha 0
    assert anim.offset_for(last) == 0.0
    assert view._delegate._enter_fx(last) is None
    view.close()


def test_rebuild_while_scrolled_anchors_waterfall_at_top_visible_row():
    """停在列表中间时整表重建：错峰基准是**视口顶行**，不是行号 0（回归）。

    用户实测报的：「滚动条切到中间再切换视图 → 先出现明显白屏，然后才加载出
    数据」。模型重建（`clear()` + `appendRows`）只改 range 不改 value，滚动位置
    被保留；可见行在 30 号开外，按绝对行号算延迟会**全部撞上 MAX_DELAY_MS 封顶**
    → 整屏 alpha=0，白等半秒。
    """
    view = _view(rows=60)
    anim = _animator(view)
    QTest.qWait(900)                        # 首批瀑布播完，动画器回静止态

    bar = view._list.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)        # 滚到中间
    pytest_app.processEvents()
    anim._starts.clear()

    view.set_items([ClipboardItem(type="text", content=f"重建 {i}")
                    for i in range(60)])    # 换内容 → animate=True
    pytest_app.processEvents()              # 首帧绘制把可见行排入场

    assert anim.active is True and anim._starts
    first = min(anim._starts)
    assert first > 10, "本用例要的是「停在中间」，可见行不该从 0 号开始"
    assert anim._base_row == first
    base = anim._starts[first][0]
    # 顶行**立即**入场——回归前这里是 +500ms（整屏白等半秒）
    assert base - anim._clock.elapsed() <= 20, "视口顶行必须马上入场"
    # 其余可见行按错峰跟上，没有一个等满 MAX_DELAY_MS
    for row, (start, _, _) in anim._starts.items():
        assert start - base <= (row - first) * anim.STAGGER_MS + 20
        assert start - base < anim.MAX_DELAY_MS

    QTest.qWait(150)
    assert anim.local(first) > 0.3, "顶行应在 150ms 内明显淡入，而不是还没轮到"
    view.close()


def test_horizontal_swipe_does_not_stop_entrance():
    """回归：触控板**双指横滑切类型标签**也是 Wheel 事件，不能当成「人滚了」。

    横滑只有 x 分量、纵向滚动条一动都不动。若只按事件类型判定，切类型标签时
    瀑布被误收摊，入场动画当场消失（用户实测报的「静止状态下切换到文本等视图，
    数据也没有加载动画了」）。判据必须判方向，与 `SmoothWheelScroller` 一致：
    纵向分量非零且不弱于横向。
    """
    view = _view(rows=60)
    anim = _animator(view)
    anim.play(view._model.rowCount())
    pytest_app.processEvents()
    assert anim._waterfall is True

    QApplication.sendEvent(view._list.viewport(), _wheel(dx=-60, dy=0))  # 纯横滑
    pytest_app.processEvents()
    assert anim._waterfall is True, "横滑不该被当成「人滚了」"
    assert anim.active is True

    QApplication.sendEvent(view._list.viewport(), _wheel(dy=-120))       # 真·纵向滚
    pytest_app.processEvents()
    assert anim._waterfall is False, "纵向滚动才该收摊"
    view.close()


def test_rebuild_while_scrolled_keeps_entrance_animation():
    """回归（用户实测报的）：停在列表中间时切类型标签 / 切视图，入场动画必须照播。

    触发条件是**重建后行数变少**：新的滚动范围把当前值**夹小** → `valueChanged`
    发出（且是**延后一帧**才发：`play()` 已把瀑布打开，它随后又关掉 `_waterfall`，
    `_active` 也被复位，动画当场消失）。停在顶部时值不变（0 → 0）所以一直没暴露。
    现在只认真实输入（滚轮/按键），程序化的 valueChanged 一律不算「人滚了」。
    """
    view = HistoryView()
    view.set_items([ClipboardItem(type="text" if i % 2 == 0 else "code",
                                  content=f"条目 {i}")
                    for i in range(60)])
    view.resize(420, 460)
    view.show()
    pytest_app.processEvents()
    anim = view._delegate.enter_animator
    QTest.qWait(900)                        # 首批瀑布播完

    bar = view._list.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)        # 滚到中间
    pytest_app.processEvents()
    anim.stop()
    pytest_app.processEvents()

    idx = [i for i, t in enumerate(TYPE_FILTERS) if t[0] == "text"][0]
    view._on_type_filter(idx)               # 只留文本 → 行数减半、范围变小
    pytest_app.processEvents()
    assert anim.active is True, "重建带出的 valueChanged 不该被当成「人滚了」"
    assert anim._starts, "应该已经为可见行排上入场"
    view.close()


def test_scrolled_back_rows_do_not_replay():
    """滚出屏幕再滚回来：这些行保持静止（不重播）。"""
    view = _view(rows=200)
    anim = _animator(view)
    QTest.qWait(900)

    bar = view._list.verticalScrollBar()
    bar.setValue(bar.maximum())
    pytest_app.processEvents()
    QTest.qWait(600)
    assert anim.active is False

    bar.setValue(0)                         # 回到顶部：这些行都露过面
    pytest_app.processEvents()
    assert anim.active is False
    view.close()


def test_plain_repaint_does_not_restart_seen_rows():
    """普通重绘（hover / 选中 / update）不重播。"""
    view = _view(rows=20)
    anim = _animator(view)
    QTest.qWait(900)
    for _ in range(3):
        view._list.viewport().update()
        pytest_app.processEvents()
    assert anim.active is False
    view.close()


# ---- 刷新：停止 + 重置，不叠加不残留 ----

def test_refresh_stops_and_resets_previous_animation():
    """刷新时旧动画立即归零：行回到起点重播，不是从半途叠加。"""
    view = _view(rows=20)
    anim = _animator(view)
    QTest.qWait(200)
    assert anim.local(0) < 1.0

    view.set_items([ClipboardItem(type="text", content=f"重建 {i}")
                    for i in range(20)])       # 刷新
    assert anim.active is True
    pytest_app.processEvents()
    assert anim.local(0) < 0.2                 # 归零重播
    assert view._delegate._enter_fx(0) is not None
    view.close()


def test_stop_midway_lands_on_final_state_immediately():
    """中途 stop（如销毁/取消）：行立刻回到最终位置，不留半途形变。"""
    view = _view(rows=10)
    anim = _animator(view)
    anim.play(10)
    QTest.qWait(120)
    assert view._delegate._enter_fx(0) is not None
    anim.stop()
    pytest_app.processEvents()
    assert anim.active is False
    assert view._delegate._enter_fx(0) is None
    assert anim.local(0) == 1.0
    view.close()


def test_add_item_does_not_replay():
    """实时捕获单条插入：不播入场（否则每复制一次列表就抖一下）。"""
    view = _view(rows=20)
    anim = _animator(view)
    QTest.qWait(900)
    assert anim.active is False

    view.add_item(ClipboardItem(type="text", content="新复制的一条"))
    pytest_app.processEvents()
    assert anim.active is False
    assert view._delegate._enter_fx(0) is None
    view.close()


# ---- 无障碍 ----

def test_reduce_motion_skips_entrance():
    """系统「减少动效」开启：完全不播，行始终静止。"""
    original = animations.reduce_motion_enabled
    animations.reduce_motion_enabled = lambda: True
    try:
        view = _view(rows=8)
        anim = _animator(view)
        anim.play(8)
        assert anim.active is False
        assert view._delegate._enter_fx(0) is None
        view.close()
    finally:
        animations.reduce_motion_enabled = original


# ---- 开销与逐像素一致性（核心验收） ----

def test_no_per_item_objects_or_effect():
    """上千项也不建 per-item 动画对象、不用 QGraphicsEffect。"""
    view = _view(rows=1200)
    anim = _animator(view)
    assert len(anim.children()) <= 2   # 只有内部定时器，与行数无关
    assert len(anim._starts) < 100     # 记录表也只有可见行那么大
    # delegate 靠 painter.setOpacity 做半透明，不挂 QGraphicsEffect
    assert view._list.graphicsEffect() is None
    assert view._list.viewport().graphicsEffect() is None
    anim.play(1200)
    assert anim.total_ms(1200) == 800  # 整段仍压在 800ms
    anim.stop()
    view.close()


def test_final_frame_identical_to_no_animation():
    """收尾帧与「从不播放」逐像素一致（位置 + 透明度完全归位）。"""
    view = _view(rows=8)
    anim = _animator(view)
    _settle(view)
    before = view._list.viewport().grab().toImage()

    anim.play(8)
    QTest.qWait(80)
    mid = view._list.viewport().grab().toImage()
    assert mid != before, "动画进行中的帧应与静止帧不同（否则没在动）"

    QTest.qWait(1000)
    pytest_app.processEvents()
    after = view._list.viewport().grab().toImage()
    assert after == before, "动画结束后必须与无动画时逐像素一致"
    view.close()
