"""UI 动效工具（emil-design-eng / apple-design 原则落地）。

- 弹层出现：fade + 从触发方向轻微位移（origin-aware，OutCubic 近似 spring）
- 页面切换：淡入
- 列表行 hover 背景过渡（delegate 自绘背景，150-200ms）
- 列表逐项入场（只有首次填充播瀑布，滚动一律不动画，见 ListEnterAnimator）
- 滚动：鼠标滚轮缓动 + 滚动速度倍率（触控板走 macOS 原生惯性曲线，我们只缩放
  距离、不补动画，见 SmoothWheelScroller / set_scroll_speed）
- 滚动视觉装饰：悬浮滚动条 / 上下边缘渐隐 / 缩略图视差 / 卡片抬升阴影
  （见 ui/scroll_fx.py，开关在设置页「滚动效果」）
- 尊重系统「减少动效」设置（apple-design §14 accessibility）
- 动画可中断：QPropertyAnimation 新动画自动打断旧的（滚动缓动自算进度、同理可打断）
"""
import logging
import time

from PySide6.QtCore import (
    QEasingCurve,
    QElapsedTimer,
    QEvent,
    QObject,
    QPropertyAnimation,
    Qt,
    QTimer,
)
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QWidget

logger = logging.getLogger(__name__)

_FADE_MS = 160    # 弹层：快（响应优先，apple-design §1 kill latency）
_PAGE_MS = 140    # 页面切换：更快
_OFFSET = 8       # 弹层初始偏移（从触发方向生长）


def reduce_motion_enabled() -> bool:
    """系统「减少动效」开启时跳过动画（无障碍）。"""
    try:
        from AppKit import NSWorkspace

        return bool(
            NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:
        return False


def fade_in_window(widget: QWidget, dy: int = _OFFSET) -> None:
    """顶层弹层出现动画：透明度 0→1 + 从 y 偏移移入（OutCubic）。

    只对顶层窗口有效（windowOpacity）；普通控件用 fade_in_widget。

    macOS 坑（实测 2026-08-08）：Qt.Popup 顶层窗口上 QPropertyAnimation
    不被事件循环驱动（pos 动画 state 卡在 Running、valueChanged 从不发射），
    `widget.move(y+8)` 的初始偏移会永久保留——弹窗比目标位置低 8px，
    视觉上「内容不是从第一行开始」。因此必须用 QTimer 强制校正最终位置，
    不依赖动画信号（finished 同样可能不触发）。
    """
    if reduce_motion_enabled():
        widget.setWindowOpacity(1.0)
        return
    target = widget.pos()

    # 之前的校正定时器必须取消：弹窗复用（快速重开）时旧 timer 会把
    # 弹窗 move 回旧目标位置，造成短暂错位
    old_timer = getattr(widget, "_fade_timer", None)
    if old_timer is not None:
        old_timer.stop()

    def _finalize() -> None:
        widget.setWindowOpacity(1.0)
        widget.move(target)

    opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
    opacity.setDuration(_FADE_MS)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
    opacity.finished.connect(_finalize)
    opacity.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._fade_anim = opacity  # 持有引用防 GC

    if dy:
        widget.move(target.x(), target.y() + dy)
        move = QPropertyAnimation(widget, b"pos", widget)
        move.setDuration(_FADE_MS)
        move.setStartValue(widget.pos())
        move.setEndValue(target)
        move.setEasingCurve(QEasingCurve.Type.OutCubic)
        move.finished.connect(_finalize)
        move.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        widget._move_anim = move

    # 双保险：动画信号可能永远不触发（macOS Qt.Popup），定时器兜底校正
    timer = QTimer(widget)
    timer.setSingleShot(True)
    timer.timeout.connect(_finalize)
    timer.start(_FADE_MS + 30)
    widget._fade_timer = timer


def fade_in_widget(widget: QWidget) -> None:
    """普通控件淡入（页面切换用）。动画结束移除 effect，避免渲染开销。"""
    if reduce_motion_enabled():
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(_PAGE_MS)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._page_anim = anim


class HoverAnimator(QObject):
    """delegate 行 hover 背景过渡（QTimer 步进逼近，≈180ms 完成）。

    用法：`anim = HoverAnimator(listview, delegate)`；delegate.paint 里用
    `anim.alpha(index.row())` 取 0.0-1.0 当前值（非当前行返回 0）。

    - 尊重系统「减少动效」：直接跳到目标（0/1），无过渡
    - 不吞事件（eventFilter 返回 False）：列表键盘/右键等逻辑不受影响
    """

    def __init__(self, view, delegate):
        super().__init__(view)
        self._view = view
        self._delegate = delegate
        self._row = -1
        self._alpha = 0.0
        self._target = 0.0
        view.viewport().setMouseTracking(True)
        view.viewport().installEventFilter(self)
        self._timer = QTimer(view)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._instant = reduce_motion_enabled()

    def eventFilter(self, obj, event) -> bool:
        try:
            vp = self._view.viewport()
        except RuntimeError:  # view 已销毁（进程退出时序）
            return False
        if obj is vp:
            if event.type() == QEvent.Type.MouseMove:
                self._set_target(self._view.indexAt(
                    event.position().toPoint()).row())
            elif event.type() == QEvent.Type.Leave:
                self._set_target(-1)
        return False  # 放行所有事件

    def _set_target(self, row: int) -> None:
        if row == self._row and self._alpha == self._target:
            return
        self._row = row
        self._target = 1.0 if row >= 0 else 0.0
        if self._instant:
            self._alpha = self._target
            try:
                self._view.viewport().update()
            except RuntimeError:
                pass
            return
        if not self._timer.isActive():
            apply_frame_rate(self._timer)   # 按当前屏幕刷新率步进
            self._timer.start()

    def _tick(self) -> None:
        try:
            vp = self._view.viewport()
        except RuntimeError:
            self._timer.stop()
            return
        # 指数逼近（每次 25% 余量）≈ 180ms 完成，非线性更接近原生
        self._alpha += (self._target - self._alpha) * 0.25
        if abs(self._alpha - self._target) < 0.01:
            self._alpha = self._target
            self._timer.stop()
        vp.update()

    def alpha(self, row: int) -> float:
        return self._alpha if row == self._row else 0.0


class ListEnterAnimator(QObject):
    """列表逐项入场：**只播首次填充**的整表瀑布，滚动一律不动画。

    用法（与 `HoverAnimator` 同款装配）：

        anim = ListEnterAnimator(listview)
        delegate.enter_animator = anim
        anim.play(view.model().rowCount())   # 数据填充/刷新后播一次
        # delegate.paint 里：先 anim.observe(index.row())，再取 v = anim.local(row)
        #   → 下移 (1-v)*offset_for(row)px、alpha = v

    设计要点（对齐 iOS / Flutter AnimatedList 的默认观感）：

    - **一条时间轴，零逐项对象**：只维护 `{行号: (起始时刻, 时长, 位移)}` 一张表
      + 一个 16ms QTimer；时间基准是构造时启动、**永不重启**的单调时钟。每行进度
      = `clamp((现在 - 该行起始) / 该行时长)` 过 OutCubic。上千项也不建 per-item
      动画对象、不用 QGraphicsEffect。
    - **首次填充**（`play(rows)`）：整表瀑布——相邻行按下标错峰 `STAGGER_MS`，
      末行延迟封顶 `MAX_DELAY_MS`，故整段 ≤800ms，与行数无关。位移用
      `OFFSET_PX`（= 一个行高：行从槽位下方升起，一眼能看出是瀑布）。
      **只有这一屏参与**：`observe(row)` 由 delegate 在绘制时上报，而首个绘制
      批次里的就是视口里那几行；因此瀑布的错峰延迟只对**内容刚装载时可见的行**
      有意义，其余一律静止。错峰基准是**本轮首个绘制的行**（视口顶行），不是
      行号 0——列表停在中间时可见行都在 30 号开外，按绝对行号算会全部撞上
      `MAX_DELAY_MS`，整屏白等半秒。
    - **滚动不播入场**（重要，别再加回来）：滚动时几乎每一行都是「初次露面」，
      逐条播就是让**整个视口常驻中间态**——实测连续滚动时 100% 的可见行
      `alpha < 0.9`、中位仅 0.37、位移中位 15px，读起来就是「掉帧、不丝滑」
      （用户实测报的就是这个）。所以 `observe` 只在**首次填充尚未结束**
      （`_active and _waterfall`）时为行排入场，其余情况直接返回——没记录的行
      `local()` 恒为 1.0、`offset_for()` 恒为 0，delegate 走原路径，逐像素干净。
      **用户一滚动（真实滚轮/按键输入，见 `__init__`）瀑布立即收摊**：否则装载后
      头 800ms 内滚到
      的行仍会按 `MAX_DELAY_MS` 排队，白白隐身半秒。
    - 已经露过面的行不再重播，滚出屏幕再滚回来保持静止。
    - `stop()` 显式归零并**冻结**：所有行立即回到最终位置，且在下一次 `play()`
      之前不再入场。刷新时 `play()` 先 `stop()`——旧动画不叠加、不残留。
    - 尊重系统「减少动效」：不播，行始终处于静止态（`local()` 恒为 1.0）。
    """

    ROW_MS = 300          # 首次填充：单行入场时长
    STAGGER_MS = 50       # 首次填充：相邻行错峰间隔
    MAX_DELAY_MS = 500    # 首次填充：末行延迟封顶（千项列表总时长仍压在 800ms）
    OFFSET_PX = 64        # 首次填充：起始位移（= 一个文本行高，行从槽位下方升起）
    # 会 scrolling 的按键（见 eventFilter；列表是 StrongFocus，这些键真能滚）
    _SCROLL_KEYS = frozenset((
        Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
        Qt.Key.Key_Home, Qt.Key.Key_End,
    ))

    def __init__(self, view, parent: QObject | None = None) -> None:
        super().__init__(parent if parent is not None else view)
        self._view = view
        # 行号 → (起始时刻 ms, 时长 ms, 起始位移 px)
        self._starts: dict[int, tuple[float, float, float]] = {}
        self._max_end = 0.0        # 表中最大的「结束时刻」——定时器的停靠点
        self._active = False
        self._waterfall = False    # 首次填充还没播完：期间露面的行才排入场
        self._frozen = False       # stop() 之后冻结：下一次 play() 前不再入场
        self._base_row = None      # 本轮瀑布的错峰基准行（= 首个绘制的可见行）
        # 无障碍：构造时读一次「减少动效」（与 HoverAnimator 一致），`play()` 时
        # 再刷新——`observe` 每帧每行都调用，不能每次都去过 ObjC
        self._instant = reduce_motion_enabled()
        self._clock = QElapsedTimer()
        self._clock.start()
        self._curve = QEasingCurve(QEasingCurve.Type.OutCubic)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        # 「人滚了」的判据必须是**真实输入**（滚轮 / 按键），不能盯 `valueChanged`
        # ——回归，用户实测报的「正在滑动时切到别的视图，就没有加载动画了」：
        # 整表重建（`clear()` + `appendRows`）时新的滚动范围会把当前值**夹小**，
        # 于是 valueChanged 发出来；而且它是**延后一帧**才发的——`play()` 已经把
        # 瀑布打开，它随后又把 `_waterfall` 关掉，入场动画当场消失。
        # 停在顶部时值不变（0 → 0）所以一直没暴露，滚到中间必现。
        # 早先那句「重建只改 range 不改 value、不会误触发」只在**新范围装得下旧
        # 值时**成立，别照着它改回去。
        #
        # ⚠️ 过滤器必须装得**比会吃掉滚轮事件的那位早**：`SmoothWheelScroller`
        # 处理鼠标滚轮时 return True，排在它后面的过滤器就再也看不到事件了。
        # Qt 的 eventFilter 是「后装的先跑」，所以这里要早装——历史页当前的顺序
        # （本动画器 → scroll_fx）正好满足。
        self._targets = [t for t in (view, getattr(view, "viewport", None)
                                     and view.viewport()) if t is not None]
        for target in self._targets:
            target.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        """只认**真实纵向滚动**；一律放行（见 `__init__` 的说明）。

        ⚠️ 滚轮必须**判方向**：历史页的「双指横滑切类型标签」（§4.0）也是 Wheel
        事件，只是只有 x 分量、纵向滚动条一动都不动；若只按事件类型就当成「人滚
        了」，切类型标签的入场动画会当场消失（用户实测报的「静止状态下切换到文本
        等视图，数据也没有加载动画了」）。判据与 `SmoothWheelScroller` 一致：
        纵向分量非零且不弱于横向。
        """
        t = event.type()
        if t == QEvent.Type.Wheel:
            angle = event.angleDelta()
            dy, dx = ((angle.y(), angle.x()) if (angle.y() or angle.x())
                      else (event.pixelDelta().y(), event.pixelDelta().x()))
            if dy and abs(dy) >= abs(dx):
                self._on_scrolled()
        elif t == QEvent.Type.KeyPress and event.key() in self._SCROLL_KEYS:
            self._on_scrolled()      # 列表是 StrongFocus，方向键/翻页键也能滚
        return False

    def _on_scrolled(self, _value: int = 0) -> None:
        """滚动一旦发生，首次填充的瀑布就此结束：之后露面的行一律静止。"""
        self._waterfall = False
        if self._active and not self._starts:
            # 首帧还没画就先滚了：一行都没排上，定时器也就还没起来（它的启动
            # 在 observe 里）——这里直接回静止态，免得 `_active` 永远挂着。
            self._active = False
            self._repaint()

    @property
    def active(self) -> bool:
        """是否正在入场（delegate 据此决定走不走偏移/透明度分支）。"""
        return self._active

    def total_ms(self, rows: int) -> int:
        """首次填充的整段时长 = 末行延迟（封顶）+ 单行时长；rows ≤ 0 时为 0。"""
        if rows <= 0:
            return 0
        return (min((rows - 1) * self.STAGGER_MS, self.MAX_DELAY_MS)
                + self.ROW_MS)

    def play(self, rows: int) -> None:
        """数据填充/刷新后播一次瀑布。旧动画先停止归零（不叠加、不残留）。"""
        self.stop()
        self._instant = reduce_motion_enabled()
        if rows <= 0 or self._instant:
            return  # 空列表 / 「减少动效」：保持静止（`stop()` 的冻结也保持）
        self._frozen = False
        self._waterfall = True
        self._active = True
        # 刷新率在这里定，**不在 observe()**：`refresh_rate()` 的首次调用要付
        # `import AppKit`（实测 78ms + 首查 18ms），而 observe() 是**绘制驱动**
        # 的——把它放那儿等于第一次瀑布的第一帧卡 96ms。`play()` 是数据装载时
        # 走的（不在绘制路径上），而且与上面 `reduce_motion_enabled()` 的刷新是
        # 同一个节奏：**每次动画起步刷一次探测值**。启动期还会 `prewarm_refresh_rate()`
        # 再提前付一次，真到这儿就只剩缓存命中。
        apply_frame_rate(self._timer)
        # 这里**不**起定时器：起始时刻由首帧绘制时的 observe() 记入。视口一直
        # 没绘制（窗口还没显示）时也就不会有空转的定时器；一旦绘制，observe
        # 会启动它。`_active` 先置真，让此刻的 local() 走进度分支（表还空）——
        # 表里没有的行一律 1.0，即静止态。
        self._repaint()

    def observe(self, row: int) -> None:
        """delegate 绘制某行时上报「这一行此刻可见」。只有首次填充的可见行才排入场。

        其余情况**直接返回**：没在表里的行 `local()` 返回 1.0、`offset_for()`
        返回 0，delegate 的 `_enter_fx` 因此返回 None，绘制完全走原路径。
        """
        if not self._active or self._frozen or self._instant or row < 0:
            return  # 没在播 / 已冻结 / 减少动效：静止态
        if not self._waterfall or row in self._starts:
            return  # 用户已滚动过，或这一行已排过：静止（滚动一律不播入场）
        # 错峰以**本轮首个绘制的可见行**为基准，不是行号 0（回归，用户实测报的
        # 「切到另一视图先白屏半秒再出数据」）：绘制顺序自上而下，首个 observe
        # 就是视口最上面那行。停在顶部时基准 = 0（与行号 0 起算等价）；停在列表
        # 中间时可见行都是 30 号开外，若按绝对行号算会全部撞上 MAX_DELAY_MS 封顶
        # ——整屏 alpha=0 白等半秒。基准行起算则永远是「视口顶行立即入场」。
        if self._base_row is None:
            self._base_row = row
        delay = min(max(0, row - self._base_row) * self.STAGGER_MS,
                    self.MAX_DELAY_MS)
        start = self._clock.elapsed() + delay
        self._starts[row] = (start, self.ROW_MS, self.OFFSET_PX)
        self._max_end = max(self._max_end, start + self.ROW_MS)
        if not self._timer.isActive():
            # ⚠️ 只起步，**不**在这里刷刷新率：这个方法是绘制路径（delegate.paint
            # 每行每帧都调），而 `refresh_rate()` 的首调用要付 `import AppKit`
            # ~96ms——放在这儿就是第一帧卡一下，还会把各行的起始时刻拉开（实测
            # 把 `_starts[5]-_starts[0]` 顶到 274ms，比期望的 250 多出 24ms）。
            # 间隔已由 `play()` 刷好，见那里的注释。
            self._timer.start()

    def rows_inserted(self, at: int) -> None:
        """模型在 `at` 行前插入一行（`add_item` 实时捕获）。

        行号整体后移，记录跟着挪；**新行记为「已经露过面」**——实时捕获不播
        入场（入场只有整表填充一条触发路径，见类文档）。
        """
        if not self._starts:
            return
        self._starts = {(r + 1 if r >= at else r): t
                        for r, t in self._starts.items()}
        self._starts[at] = (self._clock.elapsed() - 1.0, 0.0, 0.0)  # 已就位

    def stop(self) -> None:
        """显式归零并冻结：所有行回到最终位置，下一次 `play()` 前不再入场。"""
        self._timer.stop()
        self._starts.clear()
        self._max_end = 0.0
        self._base_row = None
        self._waterfall = False
        self._frozen = True
        if self._active:
            self._active = False
            self._repaint()

    def local(self, row: int) -> float:
        """该行的行内进度 0..1（1 = 已就位）。静止 / 尚未露面的行恒为 1。"""
        if not self._active:
            return 1.0
        rec = self._starts.get(row)
        if rec is None:
            return 1.0            # 还没露过面（在视口外）：静止态
        start, dur, _ = rec
        span = self._clock.elapsed() - start
        if span <= 0:
            return 0.0            # 还没轮到这一行
        if dur <= 0 or span >= dur:
            return 1.0            # 已就位
        return float(self._curve.valueForProgress(span / dur))

    def offset_for(self, row: int) -> float:
        """该行的入场起始位移（px）；静止 / 未露面 / 已就位时为 0。"""
        rec = self._starts.get(row)
        return 0.0 if rec is None else rec[2]

    def _tick(self) -> None:
        try:
            self._view.viewport()
        except RuntimeError:  # view 已销毁（进程退出时序）
            self._timer.stop()
            return
        if self._clock.elapsed() >= self._max_end:
            self._timer.stop()
            self._active = False      # 播完即静止：observe 从此不再排入场
            self._waterfall = False
            self._repaint()           # 收尾即回到静止态：末帧与无动画时逐像素一致
            return                    # （记录保留 → 已露面的行不会重播）
        self._repaint()

    def _repaint(self) -> None:
        try:
            self._view.viewport().update()
        except RuntimeError:
            pass


# 滚轮缓动时长：随距离缩放并封顶（近处不拖沓、快拨也不脱节）
_WHEEL_MIN_MS = 140
_WHEEL_MAX_MS = 320


# 刷新率缓存：屏幕几乎不会变，但这两个函数在**绘制/滚动热路径**上被调用
# （每次动画起步一次），所以值要缓存、TTL 要粗。见 `refresh_rate`。
_RATE_CACHE: dict = {"rate": 0.0, "at": -1e9}
_RATE_TTL = 5.0      # 秒：换显示器/ProMotion 切档最多滞后这么久被发现


def _mac_screen_rate() -> float:
    """macOS 原生刷新率（取不到返回 0）。懒导入 AppKit，非 macOS 直接退化。

    ⚠️ 为什么要绕开 Qt：`QScreen.refreshRate()` 在 macOS 上报的是**当前显示模式
    的标称速率**，ProMotion 屏（14/16 吋 MacBook Pro、Pro Display XDR）常年报
    60，而面板能跑 120。我们所有自绘动画（滚动缓动、悬浮条、边缘渐隐、景深、
    抬升、逐项入场）都按这个间隔步进——报 60 就等于**只用了一半刷新率**，而
    系统合成的内容是 120，两者错拍，读起来正是「帧率低、不丝滑」。
    `NSScreen.maximumFramesPerSecond` 才是那块屏实际能吃多少帧。

    只用**主屏**（菜单栏那块）。想按窗口在哪块屏算得先知道窗口的屏幕，而
    `QWidget.screen()` 是条会段错误的路（见 `apply_frame_rate`），不值得为这点
    精度去踩它——多显示器的取舍记在 DEVELOPMENT.md §16.1。
    """
    try:
        import AppKit
    except Exception:                      # 非 macOS / 未装 pyobjc
        return 0.0
    try:
        screens = list(AppKit.NSScreen.screens() or [])
        target = AppKit.NSScreen.mainScreen() or (screens[0] if screens else None)
        rate = float(target.maximumFramesPerSecond()) if target is not None else 0.0
    except Exception:
        logger.debug("读 NSScreen.maximumFramesPerSecond 失败", exc_info=True)
        return 0.0
    return rate if rate >= 1.0 else 0.0


def refresh_rate_cache_clear() -> None:
    """立刻丢弃刷新率缓存（换显示器后不等 TTL）。"""
    _RATE_CACHE.update(rate=0.0, at=-1e9)


def prewarm_refresh_rate() -> float:
    """启动期把 `refresh_rate()` 的首调用成本提前付掉，返回采用的刷新率。

    ⚠️ 这笔钱必须提前付：首次调用包含 `import AppKit` **78ms** + 首次 NSScreen
    查询 **18ms**（实测）。如果留到运行中付，付账的地方就是**第一次动画起步**——
    第一次滚动、第一次进页面，正好是一次肉眼可见的卡顿。放在窗口还没显示时的
    启动阶段则完全无感。

    调用点：`main.py` 建好 QApplication、显示主窗口之前（见那里的注释）。只调
    一次即可（之后都在 TTL 缓存里，热调用 0.005ms）。
    """
    t0 = time.monotonic()
    rate = refresh_rate()
    cost_ms = (time.monotonic() - t0) * 1000.0
    if cost_ms > 10.0:
        logger.debug("刷新率探测耗时 %.1f ms（首调用含 AppKit 导入）", cost_ms)
    return rate


def refresh_rate() -> float:
    """屏幕刷新率（Hz）：优先 macOS 原生，退化到 Qt，再退化到 60。

    带 **TTL 缓存**（`_RATE_TTL` 秒）。这是必须的，但原因**不是**怕 AppKit 慢，
    而是因为这个函数在**每次动画起步**都调一次，而它要去问 `AppKit.NSScreen`
    ——每帧一次 ObjC 往返没必要。缓存后最坏也就是换显示器最多 5 秒后才跟上。

    ⚠️ ProMotion 上这里给的是**上限**（120），不是此刻那一档的速率——这是有意
    的：我们的定时器只在动画进行中跑（静止就停表），而用户一开始滚动，系统本来
    就会把面板升到 120。按上限步进才不会再错拍。
    """
    now = time.monotonic()
    cached = _RATE_CACHE["rate"]
    if cached > 0.0 and now - _RATE_CACHE["at"] < _RATE_TTL:
        return cached
    rate = _mac_screen_rate()
    if rate <= 0.0:
        s = QApplication.primaryScreen()
        rate = s.refreshRate() if s is not None else 0.0
    if rate < 1.0:
        rate = 60.0
    _RATE_CACHE.update(rate=rate, at=now)
    return rate


def frame_interval_ms() -> int:
    """动画步进间隔 = 一块屏幕刷新周期（60Hz → **16**ms，120Hz ProMotion → 8ms）。

    ⚠️ **向下取整，不是四舍五入**（实测调过，别改回去）：60Hz 的真实周期是
    16.67ms，四舍五入成 17ms 就比屏幕**慢** 0.33ms，两者周期性地错拍——屏幕该
    刷新时这一帧还没画完，于是同一帧被显示两次。实测就是这样：中位 17.11ms、
    **58.5fps**，帧率统计看着挺稳（σ 0.62ms、零长帧）却仍然"不丝滑"，因为
    卡的是"重复帧"而不是"掉帧"。取 16ms 让我们**略快于**屏幕：每个刷新周期里
    必定已经画好一帧，宁可有帧没被显示，也不能有刷新没帧可显示。

    Qt 默认的动画时钟固定 16ms 且不跟 vsync —— 高刷屏上等于只用了一半刷新率。
    """
    return max(4, int(1000.0 / refresh_rate()))


def apply_frame_rate(timer: QTimer) -> int:
    """把 timer 的间隔刷成**当前**屏幕的刷新周期，返回刷上去的值。

    每次动画起步时重刷一次（屏幕换了能跟上，靠 `refresh_rate` 的 TTL）。

    ⚠️ **故意不接收控件参数**（别好心加回来）：曾经写成
    `apply_frame_rate(timer, widget)` 再从 `widget.screen()` 取屏幕，结果全套
    测试跑到一半**段错误**（macOS 崩溃报告指到
    `QWidget::screen() → QGuiApplication::screenAt()`）。原因是没 `show()` 过的
    控件没有 windowHandle，`QWidget::screen()` 会退化成
    `screenAt(mapToGlobal(中心点))` 这个兜底路径，在那条路径上调用是非确定性的
    ——同样的控件、同样的调用，单独跑没事、连跑上百个用例就崩（时序/堆布局相
    关）。屏幕刷新率这点收益不值得把一条会踩内存的调用放进热路径，所以改成
    `refresh_rate()` 自己问主屏 + `NSScreen`。
    """
    interval = frame_interval_ms()
    if timer.interval() != interval:
        timer.setInterval(interval)
    return interval

# 滚动速度倍率（设置页「滚动速度」）。1.0 = Qt 原生距离，触控板与鼠标滚轮共用
# 同一根旋钮——两者都只是「一次输入走多远」，没有理由分成两个设置。
_SCROLL_SPEED = 1.0
_SPEED_MIN = 0.2
_SPEED_MAX = 3.0


def scroll_speed() -> float:
    """当前滚动速度倍率（1.0 = Qt 原生距离）。"""
    return _SCROLL_SPEED


def set_scroll_speed(factor: float) -> None:
    """设置滚动速度倍率，立刻对**所有**已接入的滚动面生效（设置页改动即生效）。

    值域钳制到 0.2–3.0；非法值忽略并保持原值。1.0 是「一个字节都不改」：
    该档下触控板事件照旧原样放行，滚动与 Qt / macOS 原生逐像素相同。
    """
    global _SCROLL_SPEED
    try:
        value = float(factor)
    except (TypeError, ValueError):
        logger.warning("滚动速度取值非法，忽略：%r", factor)
        return
    _SCROLL_SPEED = min(_SPEED_MAX, max(_SPEED_MIN, value))


class SmoothWheelScroller(QObject):
    """滚轮/触控板滚动接管：鼠标滚轮补缓动，两者都按倍率缩放距离。

    分流判据是 `QWheelEvent.phase()`，两类输入的处理必须分开：

    - **鼠标滚轮**（`NoScrollPhase`）→ 消费事件，动 `QScrollBar.value` 补缓动。
      一格 ±120 是纯离散输入，没有任何惯性可言，不补就是瞬间跳一整段。
    - **触控板**（`Begin`/`Update`/`Momentum`/`End`）→ **只缩放距离，不加动画**。
      macOS 自己带惯性和减速曲线（`ScrollMomentum` 是系统持续送来的独立事件），
      逐事件把幅度乘上倍率立即落到滚动条上，减速形状仍是系统那条、只是整体变短。
      自己再叠一层动画会和系统惯性打架，手感发糊。倍率 1.0 时**完全不介入**，
      原样放行走 Qt 原生路径。

    滚动**距离**用 Qt 自己的公式还原（`angleDelta/120 × wheelScrollLines ×
    singleStep`，实测 QListView / QScrollArea / QPlainTextEdit / QTextEdit 四类
    控件都符合，且**一律只看 angleDelta、pixelDelta 被完全忽略**），所以各控件
    保持它原本的步长——我们只补时间轴、按倍率缩放走多远，不自己拍一个步长。
    其余情况一律放行：横向滚轮、Shift+纵向（模板页借此横向平移）、无可滚内容、
    已到边界（让事件冒泡给父滚动区，设置页里嵌的列表就靠这条）、系统「减少动效」。

    ⚠️ **缓动不用 `QPropertyAnimation`**（2026-09-30 实测，别改回去）：Qt 的动画
    驱动时钟是粗粒度 16ms 且不锁 vsync，一次 140ms 滚动里会**整整掉两帧**
    （实测 7 帧 / 128ms，中间一个 48ms 的洞，间隔抖动 σ≈12ms）——读起来就是
    「不丝滑」。换成自己按**单调时钟**算进度、用 `Qt.PreciseTimer` 步进同一段
    OutCubic，同样距离同样时长是 **7 帧 / max 间隔 17.4ms / σ=0.8ms，零掉帧**；
    间隔再按屏幕刷新率取（120Hz 屏 → 8ms）能出 18 帧。绘制本身不是瓶颈
    （实测 dpr=2 下一帧 delegate 绘制中位 1.2ms，16.7ms 预算的 1/14）。

    接入：`SmoothWheelScroller(area)` 或直接 `enable_smooth_wheel(area)`，area 为
    任意 `QAbstractScrollArea`（QListView / QListWidget / QScrollArea / QPlainTextEdit
    / QTextEdit 皆可）。滚轮事件落在 viewport 上，故过滤器装 viewport（§3.4）。

    ⚠️ 与自带手势机的页面（历史页横滑切类型、模板页横滑平移）同装 viewport 时，
    **手势机的过滤器必须后装**——Qt 的多个 eventFilter 是「后装的先跑」，手势机
    得先看到原始事件才能正确锁定纵向；我们跑在后面只接管它放行的纵向事件。
    """

    def __init__(self, area, parent: QObject | None = None) -> None:
        super().__init__(parent if parent is not None else area)
        self._area = area
        self._bar = area.verticalScrollBar()
        # 无障碍：构造时读一次「减少动效」（与 HoverAnimator 一致，避免每事件调 ObjC）
        self._instant = reduce_motion_enabled()
        self._target = self._bar.value()
        self._frac = 0.0  # 亚像素余量：慢速档下一格可能不足 1px，四舍五入会整段吃掉
        # 缓动驱动：自算进度 + 单调时钟（**不用 QPropertyAnimation**，见类文档）
        self._clock = QElapsedTimer()
        self._from = 0        # 本段起点（滚动条值）
        self._to = 0          # 本段终点
        self._span_ms = _WHEEL_MIN_MS
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(frame_interval_ms())
        self._timer.timeout.connect(self._tick)
        # 用户拖滚动条时停掉缓动，免得和手里那根条争 value
        self._bar.sliderPressed.connect(self._stop)
        area.viewport().installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        if event.type() != QEvent.Type.Wheel:
            return False  # 非滚轮事件一律透传（点击/拖拽等逻辑不受影响）
        if self._instant:
            return False  # 「减少动效」：完全不介入，走原生瞬时滚动
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            return False  # Shift+纵向另有用途（模板页横向平移），不能抢
        dy, dx = self._raw_delta(event)
        if dy == 0 or abs(dx) > abs(dy):
            return False  # 横向滚轮（模板页的横滑平移机接管）
        if self._bar.maximum() <= self._bar.minimum():
            return False  # 没东西可滚：让事件冒泡给父滚动区
        if event.phase() != Qt.ScrollPhase.NoScrollPhase:
            if _SCROLL_SPEED == 1.0:
                return False  # 「标准」档：触控板一个字节都不动，走原生
            return self._scroll_trackpad(event)
        return self._scroll_wheel(event)

    @staticmethod
    def _raw_delta(event) -> tuple[float, float]:
        """事件的原始 (dy, dx)——优先 angleDelta，其次 pixelDelta。

        分流判据（横向/纵向）必须与 Qt 实际采用的量一致，否则会出现「Qt 按纵向
        滚、我们按横向放行」的错位。实测 Qt 各类滚动面积只看 `angleDelta`
        （pixelDelta 被完全忽略），故 angleDelta 只要有分量就以它为准。
        """
        angle = event.angleDelta()
        if angle.y() or angle.x():
            return angle.y(), angle.x()
        pd = event.pixelDelta()
        return pd.y(), pd.x()

    def _pixel_distance(self, event) -> float:
        """一次滚轮事件折算成的像素位移——与 Qt 自己的换算逐字一致。

        `angleDelta/120 × wheelScrollLines × singleStep` 就是 Qt 的公式（实测
        四类控件都符合），照抄才能保证倍率 1.0 时距离与原生分毫不差、各控件保持
        各自步长。pixelDelta 兜底时它本身就是像素单位，直接取用。
        """
        angle = event.angleDelta()
        if angle.y():
            return ((angle.y() / 120.0) * QApplication.wheelScrollLines()
                    * max(1, self._bar.singleStep()))
        return float(event.pixelDelta().y())

    def _scroll_wheel(self, event) -> bool:
        """鼠标滚轮：一格 ±120 是纯离散输入，按倍率缩放后补一层 OutCubic 减速。"""
        bar = self._bar
        running = self._timer.isActive()
        if not running:
            self._target = bar.value()  # 空闲时以当前位置为基准重新累加
        px = self._pixel_distance(event) * _SCROLL_SPEED
        self._target = max(bar.minimum(),
                           min(bar.maximum(), self._target - px))
        if not running and self._target == bar.value():
            return False  # 已在边界且无位移：让出去
        # 从「当前值」起步重设，连续快拨时运动连贯而不是每格重置
        self._from = bar.value()
        self._to = int(round(self._target))
        self._span_ms = self._duration(abs(self._to - self._from))
        self._clock.restart()
        if not self._timer.isActive():
            apply_frame_rate(self._timer)   # 起步重刷（屏幕可能换了）
            self._timer.start()
        return True  # 消费：缓动是这次滚动的唯一驱动，避免与原生各滚一半

    def _tick(self) -> None:
        """按单调时钟推进 OutCubic（不用 QPropertyAnimation，见类文档）。"""
        elapsed = self._clock.elapsed()
        if elapsed >= self._span_ms:
            self._bar.setValue(self._to)
            self._timer.stop()
            return
        p = elapsed / self._span_ms
        inv = 1.0 - p
        eased = 1.0 - inv * inv * inv          # OutCubic
        self._bar.setValue(int(round(self._from + (self._to - self._from) * eased)))

    def _scroll_trackpad(self, event) -> bool:
        """触控板纵向：按倍率缩放**距离**后消费，系统的惯性曲线原样保留。

        只改幅度、不加缓动——手指段与随后的惯性段都是系统连续送来的，逐事件缩放
        立即落到滚动条上，减速形状还是 macOS 那条、只是整体变短。已到边界（含往
        边界外推）时放行，让事件冒泡给父滚动区。
        """
        bar = self._bar
        phase = event.phase()
        if phase == Qt.ScrollPhase.ScrollBegin:
            self._frac = 0.0  # 新手势：丢掉上一段的亚像素余量
        raw = self._pixel_distance(event) * _SCROLL_SPEED
        total = raw + self._frac
        step = int(total)  # 向零取整（余量留到下一次，慢速档下不会被抹平）
        self._frac = total - step
        target = max(bar.minimum(), min(bar.maximum(), bar.value() - step))
        if target == bar.value():
            # 没动：余量还没攒够 1px（正常，继续消费）或顶在边界（放行给父级）
            at_edge = ((raw > 0 and bar.value() <= bar.minimum())
                       or (raw < 0 and bar.value() >= bar.maximum()))
            return not at_edge
        bar.setValue(target)
        return True

    @staticmethod
    def _duration(distance: float) -> int:
        return int(min(_WHEEL_MAX_MS, max(_WHEEL_MIN_MS, distance * 0.9)))

    def _stop(self) -> None:
        self._timer.stop()
        self._target = self._bar.value()

    def animating(self) -> bool:
        """缓动是否正在跑（触控板路径必须恒为 False——只缩放距离、不补动画）。"""
        return self._timer.isActive()


def enable_smooth_wheel(area) -> SmoothWheelScroller:
    """给任意 QAbstractScrollArea 装鼠标滚轮缓动（一行接入）。

    返回 scroller；同时在 area 上挂一份引用防 GC（PySide 包装器所有权）。
    """
    scroller = SmoothWheelScroller(area)
    area._smooth_wheel = scroller
    return scroller
