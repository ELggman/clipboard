"""UI 动效工具（emil-design-eng / apple-design 原则落地）。

- 弹层出现：fade + 从触发方向轻微位移（origin-aware，OutCubic 近似 spring）
- 页面切换：淡入
- 尊重系统「减少动效」设置（apple-design §14 accessibility）
- 动画可中断：QPropertyAnimation 新动画自动打断旧的
"""
import logging

from PySide6.QtCore import QEasingCurve, QPropertyAnimation
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
    """
    if reduce_motion_enabled():
        widget.setWindowOpacity(1.0)
        return
    target = widget.pos()

    opacity = QPropertyAnimation(widget, b"windowOpacity", widget)
    opacity.setDuration(_FADE_MS)
    opacity.setStartValue(0.0)
    opacity.setEndValue(1.0)
    opacity.setEasingCurve(QEasingCurve.Type.OutCubic)
    opacity.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
    widget._fade_anim = opacity  # 持有引用防 GC

    if dy:
        widget.move(target.x(), target.y() + dy)
        move = QPropertyAnimation(widget, b"pos", widget)
        move.setDuration(_FADE_MS)
        move.setStartValue(widget.pos())
        move.setEndValue(target)
        move.setEasingCurve(QEasingCurve.Type.OutCubic)
        move.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        widget._move_anim = move


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
