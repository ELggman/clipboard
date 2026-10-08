"""切页卡顿 / 重复加载回归测试（offscreen）。

验收标准 → 用例一一对应（见 `ui/history_view.py` 的 `set_items`、`app/events.py`、
`ui/main_window.py` 的 `_reload_history` / `_fade_in_page`）：

- **内容没变就不重播入场**：原先每次 `set_items` 都无条件播 800ms 整表瀑布，
  快速在几个视图之间来回切时会反复重播 → 读起来就是卡
- **数据没变就不重查库**：四个页面原先每次显示都无条件 `reload()`（实测每次 4-5ms），
  快速切页时纯属白做
- **连点切页不重启淡入**：每次切页一次 140ms 整页离屏渲染，连点会叠起来
"""
import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app import events
from app.types import ClipboardItem
from ui.history_view import HistoryView

pytest_app = QApplication.instance() or QApplication([])


def _items(n: int, prefix: str = "条目") -> list:
    out = []
    for i in range(n):
        item = ClipboardItem(type="text", content=f"{prefix} {i}")
        item.id = i + 1
        item.hash = hashlib.sha256(f"{prefix}{i}".encode()).hexdigest()
        out.append(item)
    return out


@pytest.fixture()
def engine(tmp_path):
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "switch.db")
    migrate(eng)
    return eng


# ---- 内容没变 → 不重播入场 ----

def test_set_items_same_content_does_not_replay_entrance():
    """同样的内容再填一次：模型照建，但**不**重播 800ms 瀑布。

    回归：快速在几个视图之间来回切换时，每次回到历史页都要重播一遍整表入场动画。
    """
    view = HistoryView()
    view.set_items(_items(20))
    anim = view._delegate.enter_animator
    assert anim.active is True              # 首次填充照常播
    anim.stop()                             # 推到静止态（stop 会冻结）
    assert anim.active is False

    view.set_items(_items(20))              # 一模一样的内容
    assert anim.active is False, "内容没变不该重播入场"
    assert view._model.rowCount() == 20     # 但仍然照常重建（数据不能少）
    view.close()


def test_set_items_changed_content_replays_entrance():
    """内容真的变了 → 照常重播（别把入场动画改没了）。"""
    view = HistoryView()
    view.set_items(_items(20))
    anim = view._delegate.enter_animator
    anim.stop()

    view.set_items(_items(20, prefix="重建"))
    assert anim.active is True
    view.close()


def test_type_tab_click_still_animates():
    """用户真的点了类型 tab：动画是要的，不受「内容没变」这条影响。"""
    view = HistoryView()
    view.set_items(_items(20))
    anim = view._delegate.enter_animator
    anim.stop()
    assert anim.active is False

    view._type_tabs.setCurrentRow(1)        # 触发 _on_type_filter
    assert anim.active is True
    view.close()


# ---- 数据没变 → 不重查库 ----

def test_history_reload_skips_when_revision_unchanged(engine, monkeypatch):
    """切回历史页：数据修订号没变过就不查库、不重建。"""
    from services import history_service, session_service
    from ui.main_window import MainWindow

    session_service.ensure_default(engine)
    for item in _items(5):
        history_service.save_item(engine, item)

    w = MainWindow()
    w.set_search(engine)
    w.load_history(history_service.list_recent(engine))
    w.show()
    pytest_app.processEvents()

    calls = {"n": 0}
    real = history_service.list_recent

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(history_service, "list_recent", counting)

    # 先切走再切回：第一次必须真查（_history_rev 还是初始值）
    w._nav.setCurrentRow(1)
    w._nav.setCurrentRow(0)
    assert calls["n"] == 1

    # 再来一轮：数据一个字节都没变 → 不该再查
    w._nav.setCurrentRow(1)
    w._nav.setCurrentRow(0)
    assert calls["n"] == 1, "数据没变过就不该再查库"

    # 数据变了 → 必须重查
    extra = ClipboardItem(type="text", content="新复制的一条")
    extra.hash = hashlib.sha256(b"new").hexdigest()
    history_service.save_item(engine, extra)
    w._nav.setCurrentRow(1)
    w._nav.setCurrentRow(0)
    assert calls["n"] == 2
    w.close()


def test_page_show_skips_reload_when_revision_unchanged(engine):
    """时间线 / 收藏页同理：修订号没变就不重查。"""
    from ui.collections_view import CollectionsView
    from ui.timeline_view import TimelineView

    for cls in (TimelineView, CollectionsView):
        view = cls()
        view.set_context(engine)
        view.show()
        pytest_app.processEvents()

        calls = []
        view.reload = lambda: calls.append(1)   # 计数桩（替换实例方法）

        view.hide()
        view.show()
        pytest_app.processEvents()
        assert calls == [], f"{cls.__name__} 数据没变不该重查"

        events.bump()                            # 模拟一次数据写入
        view.hide()
        view.show()
        pytest_app.processEvents()
        assert len(calls) == 1, f"{cls.__name__} 数据变了必须重查"
        view.close()


# ---- 连点切页不重启淡入 ----

def test_rapid_page_switching_does_not_restart_fade(engine, monkeypatch):
    """连点切页只淡入一次：每次淡入都是 140ms 整页离屏渲染，叠起来就是卡。"""
    from ui import animations
    from ui.main_window import MainWindow

    calls = []
    monkeypatch.setattr(animations, "fade_in_widget", lambda w: calls.append(w))

    w = MainWindow()
    w.set_search(engine)
    w.show()
    pytest_app.processEvents()
    calls.clear()                           # 构造期 setCurrentRow(0) 的那次不算

    w._page_switch_clock.restart()          # 起一个干净的节流窗口
    for row in (1, 2, 3):
        w._nav.setCurrentRow(row)
    assert calls == [], "连点期间不该反复起淡入"

    QTest.qWait(320)                        # 过了节流窗口
    w._nav.setCurrentRow(4)
    assert len(calls) == 1, "隔开之后再切页应当照常淡入"
    w.close()


# ---- 修订号 ----

def test_revision_bumps_on_commit_not_on_read(engine):
    """任何提交都算数据变了；只读查询不算（否则「判脏」就永远为真）。"""
    from services import history_service, session_service

    session_service.ensure_default(engine)
    before = events.revision()
    history_service.list_recent(engine)
    assert events.revision() == before, "只读不该推进修订号"

    item = ClipboardItem(type="text", content="x")
    item.hash = hashlib.sha256(b"x").hexdigest()
    history_service.save_item(engine, item)
    assert events.revision() > before
