"""滚动视觉装饰（设置页「滚动效果」可逐项开关）。

五件套，由 `enable_scroll_fx(area, delegate=None)` 装配：

1. **悬浮滚动条**（`OverlayScrollBar`）：原生 QScrollBar 一旦被 QSS 上样式就变成
   占位的（吃 10px 布局宽，见 `ui/theme.py` 注释）。这里把原生条设成
   `ScrollBarAlwaysOff`，自绘一条**浮在内容上方**的细条——滚动时淡入、闲置
   ~0.9s 后淡出，可直接拖拽。内容区因此宽了 10px，滚动条也不再压窄选中高亮。
2. **上下边缘渐隐**（`EdgeFade`）：还有内容的那个方向盖一条「列表底色 → 透明」的
   渐变。用**列表自己的背景色**，所以与背景逐像素接缝；渐隐高度随离端点的距离
   增长（滚到端点自然收成 0），不是硬切一条。
3. **缩略图视差**（`ScrollFx.parallax_for`）：滚动时缩略图相对行做一点反向位移，
   像内容分了层、边上的层跟不上。
4. **卡片抬升**（`ScrollFx.lift()` + delegate 里的 `_draw_lift`）：滚动时行像被
   抬起来，底下补一层近高斯阴影。
5. **卡片景深**（`ScrollFx.depth_for()`，移植自仓库根的 `demo_v.py`，按用户要求
   改了两处）：**只作用于视口中心以下**（顶部不要这个效果），且**只在往下翻列表
   时出现**（往回翻或停下 → 0，见 `_down_gate`）。按位置把下半屏的卡
   **缩放 + 向下推 + 向背景淡出**。另：5 开着时 3 自动让位（`parallax_for` 恒返回
   0），因为 3 本来就是 5 的弱化版，两个一起上会把缩略图推两次。

3/4/5 都是**只在滚动进行中**存在的（5 还多一个「方向必须是往下翻」的条件）。
所以静止时 delegate 走的是与没有装饰时**逐像素相同**的绘制路径——不会因为常驻
的非整数位移把图糊掉。

5 的闸门归零时 `depth_for()` 返回 `None`，delegate 直接走原路径、连一次
`save/restore` 都不做——「停下即恒等」是它自己的责任。

为什么 3/4/5 不整个放这里：它们要知道行矩形与缩放（`_s`），而那是 delegate 的事；
这里只提供 `activity()` / `lift()` / `parallax_for()` / `depth_for()`，绘制留在
`HistoryDelegate`。
"""

import logging
import re

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget

from ui.animations import apply_frame_rate, frame_interval_ms, reduce_motion_enabled
from ui.theme import current_palette

logger = logging.getLogger(__name__)

_BAR_W = 10               # 悬浮滚动条的浮层宽度（含左右各 _BAR_INSET 留白）
_BAR_INSET = 2
_BAR_MIN_H = 30
_BAR_IDLE_MS = 900        # 停止滚动后多久开始淡出
_BAR_IN_MS = 90           # 淡入时长
_BAR_OUT_MS = 300         # 淡出时长

_EDGE_H = 22              # 边缘渐隐的最大高度

_HOLD_MS = 90             # 滚动后 activity 保持 1.0 的时长
_DECAY_MS = 240           # activity 从 1 衰减到 0 的时长
_PARALLAX_PX = 6          # 缩略图视差的最大位移（逻辑像素）
LIFT_ALPHA = 44           # 卡片抬升阴影的不透明度上限（delegate 用）

# ---- 卡片景深（第 5 项，移植自 demo_v.py）----
# ⚠️ 与 demo 有**两处刻意不同**，改之前先读：
#   ① **只作用于视口中心以下**（用户要求「顶部不要这个效果」）。demo 是上下对称
#      的镜头：上半屏的卡也缩、也往上推。这里上半屏恒等，效果从中心往下逐渐增强
#      ——读起来是「下面还有内容、往后卷」。
#   ② **只在往下翻列表时出现**（用户要求「下滑才出现」）。demo 是常驻的。这里乘
#      一道方向闸门（`_down_gate`）：往回翻或停下 → 0。所以静止时它整体为 0，
#      `depth_for` 直接返回 None 走原路径——「静止帧与无装饰逐像素一致」这条
#      不变量对它同样成立。
# 另外 demo 的 `max_distance = 视口高 × 0.60` 也是个坑：屏内卡片中心离视口中心最多
# 只有视口高的一半，所以 t 的可见上界是 0.833 不是 1.0——`_EDGE_SCALE` 是**渐近值**
# 不是边界值（写 0.90 时实际最扁只有 0.917）。这里比 demo 调紧一档补回来。
_DEPTH_EDGE_SCALE = 0.88  # 底部缩到的比例（渐近值，见上）
_DEPTH_MAX_DIST = 0.60    # 视口高 × 此值 = 「完全到底」(t=1)
_DEPTH_PUSH_PX = 12       # 向下推的最大位移（demo 同值）
_DEPTH_DIM = 46           # 向列表背景淡出的最大 alpha（0-255）
# 景深**停手后的收尾**比视差/抬升快一倍（用户实测：停下之后缩回去等得有点久，
# 要求「恢复时间减半」）。为什么只有它要快：三个通道里景深是唯一**看得出来**的
# 收尾——缩放 + 变淡有明确的静止参照物（卡片自己的边界），而阴影淡出、缩略图
# 滑回 6px 都几乎看不见。所以同一段余韵只有景深读起来是「慢」。
# 合计 45+120 = 165ms（视差/抬升仍是 90+240 = 330ms）。
_DEPTH_HOLD_MS = 45
_DEPTH_DECAY_MS = 120

_RGBA_RE = re.compile(
    r"^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)"
    r"\s*(?:,\s*([\d.]+)\s*)?\)$")


def parse_color(value, fallback=(0, 0, 0, 56)) -> QColor:
    """调色板颜色串 → QColor（自绘控件取色用）。

    ⚠️ 调色板里的半透明项写的是 `"rgba(0, 0, 0, 0.22)"` 这种 QSS 函数串，而
    **QColor 不解析它**（§9：构造出来是无效色；8 位十六进制又是 AARRGGBB 顺序，
    当 RRGGBB 用会串位）。自绘控件要取 `scrollbar` 这类项，必须自己解一次。
    """
    s = str(value).strip()
    m = _RGBA_RE.match(s)
    if m:
        r, g, b = (int(round(float(m.group(i)))) for i in (1, 2, 3))
        a = int(round(255 * float(m.group(4)))) if m.group(4) is not None else 255
        return QColor(r, g, b, a)
    c = QColor(s)
    return c if c.isValid() else QColor(*fallback)


# ---- 生效的装饰项（设置页驱动；模块级，同 ui/animations 的滚动速度）----

_EFFECTS = {
    "scrollbar": True,     # 悬浮滚动条
    "edge_fade": True,     # 上下边缘渐隐
    "parallax": True,      # 缩略图视差
    "lift": True,          # 卡片抬升阴影
    "depth": True,          # 卡片景深（缩放 + 向外推 + 向背景淡出）
}
_INSTANCES: list = []      # 已装配的 ScrollFx（改设置时逐一生效）


def scroll_effects() -> dict:
    """当前启用的滚动装饰（副本；改它不影响生效值）。"""
    return dict(_EFFECTS)


def set_scroll_effects(values: dict) -> None:
    """更新启用的装饰；已装配的实例立刻生效（不必重启）。"""
    for key in _EFFECTS:
        if key in values:
            _EFFECTS[key] = bool(values[key])
    for fx in list(_INSTANCES):
        try:
            fx.apply_settings()
        except RuntimeError:          # 底层控件已销毁（进程退出时序）
            _INSTANCES.remove(fx)


def _motion_effects() -> bool:
    """3/4/5 是"动效"：系统开了「减少动效」就整体关掉（无障碍）。

    5（景深）严格说静止时也在，但它同样降低了边缘内容的清晰度，且带速度位移，
    所以一并归到这里——「减少动效」的用户不该看到一个常驻的镜头形变。
    """
    return ((_EFFECTS["parallax"] or _EFFECTS["lift"] or _EFFECTS["depth"])
            and not reduce_motion_enabled())


class OverlayScrollBar(QWidget):
    """悬浮滚动条：浮在内容右侧，滚动时出现、闲置后淡出，可直接拖拽。

    完全透明时置 `WA_TransparentForMouseEvents`——否则右侧 10px 的条目永远点不到。
    """

    def __init__(self, fx: "ScrollFx"):
        super().__init__(fx.viewport())
        self._fx = fx
        self._bar = fx.scrollbar()
        self._grab_dy = 0.0
        # refresh() 的状态镜像：只在真的变了时才去动属性/光标/重绘（见 refresh）
        self._transparent = True
        self._cursor = None
        self._sig = None
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setMouseTracking(True)

    # ---- 几何 ----

    def _metrics(self) -> tuple[float, float, float]:
        """→ (滑块高, 可移动距离, 位置比例 0-1)。"""
        b = self._bar
        rng = b.maximum() - b.minimum()
        span = max(1, rng + b.pageStep())
        h = self.height() * b.pageStep() / span
        h = max(float(_BAR_MIN_H), min(float(self.height()), h))
        track = max(1.0, self.height() - h)
        denom = max(1, span - b.pageStep())
        pos = (b.value() - b.minimum()) / denom
        return h, track, max(0.0, min(1.0, pos))

    def _handle_rect(self) -> QRectF:
        h, track, pos = self._metrics()
        return QRectF(_BAR_INSET, pos * track,
                      max(1.0, self.width() - 2 * _BAR_INSET), h)

    def _set_value_at(self, y: float) -> None:
        b = self._bar
        _, track, _ = self._metrics()
        p = (y - self._grab_dy) / track
        p = max(0.0, min(1.0, p))
        b.setValue(int(round(b.minimum() + p * (b.maximum() - b.minimum()))))

    # ---- 交互 ----

    def enterEvent(self, event) -> None:
        self._fx.set_hover(True)

    def leaveEvent(self, event) -> None:
        self._fx.set_hover(False)

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._fx.set_drag(True)
        rect = self._handle_rect()
        y = event.position().y()
        if rect.contains(event.position()):
            self._grab_dy = y - rect.top()      # 抓住滑块：保持抓取点
        else:
            self._grab_dy = rect.height() / 2   # 点轨道：光标落到滑块中心
            self._set_value_at(y)
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._fx.dragging():
            self._set_value_at(event.position().y())

    def mouseReleaseEvent(self, event) -> None:
        self._fx.set_drag(False)

    # ---- 绘制 ----

    def refresh(self) -> None:
        """按当前 alpha 决定是否吃鼠标 + 重绘（`ScrollFx._tick` 里调）。

        **只在真的变了时动**：本函数每帧都被调一次，而 `setAttribute` /
        `setCursor` / `update()` 都会惊动 Qt 的属性与重绘系统，闲置时没必要每帧
        做一遍。
        """
        a = self._fx.bar_alpha()
        transparent = a <= 0.02 and not self._fx.dragging()
        if transparent != self._transparent:
            self._transparent = transparent
            self.setAttribute(
                Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)

        if self._fx.dragging():
            cursor = Qt.CursorShape.ClosedHandCursor
        elif self._fx.hovered():
            cursor = Qt.CursorShape.OpenHandCursor
        else:
            cursor = None
        if cursor != self._cursor:
            self._cursor = cursor
            if cursor is None:
                self.unsetCursor()
            else:
                self.setCursor(cursor)

        # alpha 或滚动位置变了才需要重画（拖住不动 / 闲置时省掉每帧一次绘制）
        sig = (round(a, 3), self._bar.value(), self._bar.maximum())
        if sig != self._sig:
            self._sig = sig
            self.update()

    def paintEvent(self, event) -> None:
        alpha = self._fx.bar_alpha()
        if alpha <= 0.02:
            return
        c = parse_color(current_palette().get("scrollbar", "rgba(0, 0, 0, 0.22)"))
        c.setAlpha(int(round(c.alpha() * alpha)))
        r = self._handle_rect()
        path = QPainterPath()
        path.addRoundedRect(r, r.width() / 2, r.width() / 2)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillPath(path, c)


class EdgeFade(QWidget):
    """上下边缘渐隐：只在**还有内容**的那一侧画，滚到端点自然收成 0。"""

    def __init__(self, fx: "ScrollFx"):
        super().__init__(fx.viewport())
        self._bar = fx.scrollbar()
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._bar.valueChanged.connect(self._retouch)
        self._bar.rangeChanged.connect(self._retouch)

    def _retouch(self, *_args) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        b = self._bar
        top = min(_EDGE_H, b.value() - b.minimum())
        bottom = min(_EDGE_H, b.maximum() - b.value())
        if top <= 0 and bottom <= 0:
            return
        base = parse_color(current_palette().get("content", "#FFFFFF"))
        clear = QColor(base)
        clear.setAlpha(0)
        w, h = float(self.width()), float(self.height())
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        if top > 0:
            g = QLinearGradient(QPointF(0, 0), QPointF(0, top))
            g.setColorAt(0.0, base)
            g.setColorAt(1.0, clear)
            painter.fillRect(QRectF(0, 0, w, top), g)
        if bottom > 0:
            g = QLinearGradient(QPointF(0, h - bottom), QPointF(0, h))
            g.setColorAt(0.0, clear)
            g.setColorAt(1.0, base)
            painter.fillRect(QRectF(0, h - bottom, w, bottom), g)


class ScrollFx(QObject):
    """一个滚动区的装饰集合（见模块文档）。`enable_scroll_fx(area)` 装配。"""

    def __init__(self, area, delegate=None):
        super().__init__(area)
        self._area = area
        self._vp = area.viewport()
        self._bar = area.verticalScrollBar()
        self._activity = 0.0
        self._idle_ms = _BAR_IDLE_MS     # 一开始就当已闲置：不显示滚动条
        self._bar_alpha = 0.0
        self._hover = False
        self._drag = False
        self._dirty = False              # 上一 tick 还有 activity（归零时要补一帧）
        self._motion = _motion_effects()
        # 景深要用的「正在往下翻」闩锁（0..1，见 `_down_gate`）。只看**方向**，
        # 不看速度大小——早先按速度算，结果每段轻扫的惯性衰减都会让整块下半屏
        # 缩回去、下一次轻扫再缩回来，连扫几下就是不停放大缩小（用户实测报的
        # 「滑动着看着卡顿」）。
        self._down = 0.0
        # 景深的收尾强度（0..1）。**和 `_activity` 分开**：它有自己的
        # `_DEPTH_HOLD_MS`/`_DEPTH_DECAY_MS`（停手后收得比视差/抬升快一倍），
        # 两条曲线只在 `_mark_active` 里一起复位到 1.0，之后各走各的。
        self._depth_activity = 0.0
        self._last_bar_value = self._bar.value()

        self.overlay = OverlayScrollBar(self)
        self.edges = EdgeFade(self)

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(frame_interval_ms())
        self._timer.timeout.connect(self._tick)

        self._bar.valueChanged.connect(self._mark_active)
        self._vp.installEventFilter(self)
        if delegate is not None:
            delegate.scroll_fx = self
        _INSTANCES.append(self)
        self.apply_settings()

    # ---- 装配 ----

    def apply_settings(self) -> None:
        """让当前设置生效（装配时与设置变化时各调一次）。"""
        self._motion = _motion_effects()
        self.overlay.setVisible(_EFFECTS["scrollbar"])
        self.edges.setVisible(_EFFECTS["edge_fade"])
        self._area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            if _EFFECTS["scrollbar"]
            else Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._place()
        try:
            self._vp.update()
        except RuntimeError:
            pass

    def attach_delegate(self, delegate) -> None:
        """把本装饰挂到 delegate 上（3/4 两项由 delegate 绘制时读取）。"""
        delegate.scroll_fx = self

    def _place(self) -> None:
        r = self._vp.rect()
        self.edges.setGeometry(0, 0, r.width(), r.height())
        self.overlay.setGeometry(r.width() - _BAR_W, 0, _BAR_W, r.height())
        # 先抬渐隐再抬滚动条：滚动条压在最上层（渐隐中间是透明的，只在这
        # 10px × 22px 的角上重叠）
        self.edges.raise_()
        self.overlay.raise_()

    # ---- 对 delegate 的接口 ----

    def viewport(self):
        return self._vp

    def scrollbar(self):
        return self._bar

    def activity(self) -> float:
        """滚动活动度 0.0-1.0（滚动事件后 1.0，停下约 330ms 内衰减到 0）。"""
        return self._activity

    def lift(self) -> float:
        """卡片抬升的强度 0.0-1.0（= `activity()`，但该项关闭时恒为 0）。

        ⚠️ delegate 必须用**这个**而不是 `activity()`：`activity` 只由
        `_motion_effects()`（视差**或**抬升任一开着）驱动，所以「只开视差、
        关掉抬升」时 activity 仍是 1.0——早先 `_draw_lift` 直接读 activity，
        于是取消勾选「卡片抬升」什么都不会变（用户实测报的「开关不明显」）。
        """
        return self._activity if _EFFECTS["lift"] else 0.0

    def parallax_for(self, rect) -> int:
        """行内缩略图的反向位移（整数像素）。

        就是**离视口中心的距离**：越靠边的行让得越多、中间几乎不动，读起来像
        内容分了层、边上的层跟不上。幅度只有 ±6px，且只在滚动中生效；静止时
        恒为 0，不会因为常驻的非整数位移把图糊掉。

        **景深开着时返回 0**：景深（第 5 项）是同一个想法的完整版，而且它推的是
        整张卡。两个一起上会把缩略图推两次，所以让景深接管。
        """
        if (self._activity <= 0.001 or not _EFFECTS["parallax"]
                or _EFFECTS["depth"]):
            return 0
        vp = self._vp.rect()
        half = max(1.0, vp.height() / 2)
        rel = (rect.center().y() - vp.center().y()) / half
        rel = max(-1.0, min(1.0, rel))
        return int(round(-rel * _PARALLAX_PX * self._activity))

    def _down_gate(self) -> float:
        """「正在往下翻列表」的强度 0..1（往回翻 / 停下 → 0）。

        ⚠️ **只看方向，不看速度大小**（改过一版，别改回去）：早先这里算的是
        `瞬时速度 / 参考速度`，于是**每一段滚动的惯性衰减**都会让闸门掉下去、
        整块下半屏缩回原样，下一次轻扫再缩回去——连扫几下就是不停地放大缩小，
        读起来就是「卡顿」。方向闩锁只在真的反向时才翻。

        乘 `_depth_activity` 是为了让「停手」有个收尾；不乘的话手一停 `_down`
        还挂着 1，效果不会消失。⚠️ 用的是**景深自己**的那条衰减（165ms），不是
        `activity()`（330ms）——停手后缩回去等得有点久，用户要求减半（见
        `_DEPTH_HOLD_MS`）。
        """
        return self._down * self._depth_activity

    def depth_for(self, rect):
        """卡片景深：→ `(缩放, 额外位移 px, 淡出 alpha 0.._DEPTH_DIM)`；未开启 → `None`。

        由**位置 + 下滑方向**共同决定，两项都是刻意的取舍：
        - **位置**：只看视口中心**以下**，上半屏恒等（用户要求「顶部不要这个效果」）
        - **方向**：只在**往下翻列表**时出现（`_down_gate()`），往回翻或停下 → 0

        所以静止时它整体为 0、直接返回 `None`，delegate 连一次 `save/restore` 都不
        做——「静止帧与无装饰逐像素一致」这条不变量对它同样成立（与早期的常驻版本
        不同，那时是有意让静止帧也带形变）。

        三个通道里真正让人「看见」的是**缩放和淡出**，不是位移：连续平滑的位移没有
        静止参照物，人眼读不出来（旧视差 ±6px 看不出效果就是栽在这儿）。
        """
        if not (_EFFECTS["depth"] and self._motion):
            return None
        gate = self._down_gate()
        if gate <= 0.004:
            return None
        vp = self._vp.rect()
        # 只看中心以下：上半屏直接返回 None（不是返回恒等值）——这样 delegate 对
        # 顶部每一行都走**完全原始**的绘制路径，连一次 translate 都没有
        below = ((rect.center().y() - vp.center().y())
                 / (vp.height() * _DEPTH_MAX_DIST))
        if below <= 0.0:
            return None
        below = min(1.0, below)
        t = below * below * (3.0 - 2.0 * below)      # smoothstep：两端导数为 0
        t *= gate
        if t <= 1e-6:
            return None
        scale = 1.0 - (1.0 - _DEPTH_EDGE_SCALE) * t
        push = _DEPTH_PUSH_PX * t                    # 一律向下（向外）
        return scale, push, t * _DEPTH_DIM

    # ---- 状态（OverlayScrollBar 读写）----

    def bar_alpha(self) -> float:
        return self._bar_alpha

    def hovered(self) -> bool:
        return self._hover

    def dragging(self) -> bool:
        return self._drag

    def set_hover(self, on: bool) -> None:
        self._hover = on
        self._ensure_timer()

    def set_drag(self, on: bool) -> None:
        self._drag = on
        self._ensure_timer()

    # ---- 驱动 ----

    def eventFilter(self, obj, event) -> bool:
        try:
            vp = self._vp
        except RuntimeError:          # 控件已销毁
            return False
        if obj is vp:
            t = event.type()
            if t == QEvent.Type.Resize:
                self._place()
            elif t == QEvent.Type.Wheel:
                self._mark_active()
            elif t == QEvent.Type.Enter:
                self.set_hover(True)
            elif t == QEvent.Type.Leave:
                self.set_hover(False)
        return False                  # 放行：滚轮缓动/右键菜单还在这条链上

    def _mark_active(self, *_args) -> None:
        self._idle_ms = 0
        if self._motion:
            self._activity = 1.0
            self._depth_activity = 1.0
        self._ensure_timer()

    def _ensure_timer(self) -> None:
        if not self._timer.isActive():
            # 停表期间滚动条可能已经动过（缓动的尾巴、程序化 setValue），起步时
            # 把基准点归位，免得把那段陈旧位移当成第一帧的方向。
            # `_down` **不**重置：它是方向闩锁，留着上一次的方向，这样紧接着的
            # 同向滚动一上来就是满效果，不会每段手势都重新涨一次（那也是一种
            # 「呼吸」）。
            self._last_bar_value = self._bar.value()
            apply_frame_rate(self._timer)   # 屏幕可能换了
            self._timer.start()

    def _tick(self) -> None:
        step = self._timer.interval()
        self._idle_ms += step

        # activity：滚动停止 _HOLD_MS 后线性衰减（视差/抬升的"余韵"）
        if self._activity > 0.0 and self._idle_ms > _HOLD_MS:
            self._activity = max(0.0, self._activity - step / _DECAY_MS)

        # 景深的收尾单独一条曲线：同样从 1.0 线性衰减，但更早开始、更快走完
        # （`_DEPTH_HOLD_MS`/`_DEPTH_DECAY_MS`，合计是上面的一半）
        if self._depth_activity > 0.0 and self._idle_ms > _DEPTH_HOLD_MS:
            self._depth_activity = max(
                0.0, self._depth_activity - step / _DEPTH_DECAY_MS)

        # 「正在往下翻」的方向闩锁（景深用）：本帧滚动条往上走（内容前移 = 在看
        # 更靠后的条目）就朝 1 靠，反向朝 0 靠；**本帧没动就保持**——惯性衰减的
        # 空隙里 dv 经常是 0，那时若让闸门掉下去，就是前面 `_down_gate` 说的
        # 「呼吸式卡顿」。
        cur = self._bar.value()
        dv = cur - self._last_bar_value
        self._last_bar_value = cur
        if dv > 0:
            self._down += (1.0 - self._down) * 0.25
        elif dv < 0:
            self._down *= 0.75

        # 滚动条：鼠标在上面 / 正在拖 / 刚滚过 → 1，否则 0
        target = 1.0 if (self._hover or self._drag
                         or self._idle_ms < _BAR_IDLE_MS) else 0.0
        span = _BAR_IN_MS if target > self._bar_alpha else _BAR_OUT_MS
        delta = step / span
        if self._bar_alpha < target:
            self._bar_alpha = min(target, self._bar_alpha + delta)
        elif self._bar_alpha > target:
            self._bar_alpha = max(target, self._bar_alpha - delta)

        self.overlay.refresh()
        # 视差/抬升画在条目上 → 要重绘视口；归零那一帧也得补一次，
        # 否则最后一次的位移会留在画面上
        if self._activity > 0.0:
            self._dirty = True
            self._vp.update()
        elif self._dirty:
            self._dirty = False
            self._vp.update()

        # 静止判据要连**淡出也走完**：activity 比滚动条先归零（330ms vs 900ms），
        # 只看 activity 会在滚动条还是 1.0 时就停表，浮层条就此卡在画面上
        settled = (self._activity <= 0.0 and not self._hover
                   and not self._drag and self._idle_ms >= _BAR_IDLE_MS
                   and self._bar_alpha == 0.0)
        if settled:
            self._timer.stop()        # 静止时零开销


def enable_scroll_fx(area, delegate=None) -> ScrollFx:
    """给滚动区装上装饰（同一个区域只装一次；重复调用只补挂 delegate）。"""
    existing = getattr(area, "_scroll_fx", None)
    if existing is not None:
        if delegate is not None:
            existing.attach_delegate(delegate)
        return existing
    fx = ScrollFx(area, delegate)
    area._scroll_fx = fx
    return fx
