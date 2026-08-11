"""UI 动效工具（emil-design-eng / apple-design 原则落地）。

- 弹层出现：fade + 从触发方向轻微位移（origin-aware，OutCubic 近似 spring）
- 页面切换：淡入
- 列表行 hover 背景过渡（delegate 自绘背景，150-200ms）
- 尊重系统「减少动效」设置（apple-design §14 accessibility）
- 动画可中断：QPropertyAnimation 新动画自动打断旧的
"""
import logging

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QTimer,
)
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

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
