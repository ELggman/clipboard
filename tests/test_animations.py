"""动效工具测试：reduce_motion 读取、弹层淡入、页面淡入（offscreen）。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

pytest_app = QApplication.instance() or QApplication([])


def test_reduce_motion_reads_without_error():
    from ui.animations import reduce_motion_enabled

    # 读取系统设置不抛异常（返回 bool）
    assert isinstance(reduce_motion_enabled(), bool)


def test_fade_in_window_completes():
    from ui.animations import fade_in_window

    w = QLabel("fade")
    w.setWindowOpacity(0.0)
    w.show()
    pytest_app.processEvents()
    fade_in_window(w)
    assert w.windowOpacity() < 1.0  # 动画开始（若系统减少动效则直接 1.0）
    QTest.qWait(300)  # 等动画结束（160ms）
    assert w.windowOpacity() == 1.0
    w.close()


def test_fade_in_widget_cleans_effect():
    from ui.animations import fade_in_widget

    w = QLabel("page")
    w.show()
    pytest_app.processEvents()
    fade_in_widget(w)
    QTest.qWait(300)
    # 动画结束后移除 QGraphicsOpacityEffect（避免渲染开销）
    assert w.graphicsEffect() is None
    w.close()
