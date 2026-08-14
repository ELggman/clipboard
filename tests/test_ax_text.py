"""AX 文本读取 + 强制开启辅助功能树 测试。

ensure_ax_enabled 会触碰真实前台应用——测试一律 monkeypatch
ax_text._frontmost_pid / ApplicationServices.AXUIElement*，不产生真实副作用。
read_focused_text / is_ime_composing 依赖真实前台应用与辅助功能权限，无法在
测试里稳定断言，这里只覆盖能纯逻辑验证的部分（无前台返回 False、pid 缓存、
SET 调用）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.template import ax_text


def _reset_cache():
    ax_text._ax_enabled_pid = None


def test_ensure_ax_enabled_no_frontmost(monkeypatch):
    """无前台应用：返回 False，不抛异常。"""
    _reset_cache()
    monkeypatch.setattr(ax_text, "_frontmost_pid", lambda: None)
    assert ax_text.ensure_ax_enabled() is False


def test_ensure_ax_enabled_pid_cached_no_reset(monkeypatch):
    """同 pid 只 SET 一次（缓存）——避免反复给前台应用发增强请求。"""
    _reset_cache()
    monkeypatch.setattr(ax_text, "_frontmost_pid", lambda: 12345)
    # 预置缓存为同一 pid → 直接返回 True，不调用 SET
    ax_text._ax_enabled_pid = 12345
    import ApplicationServices as _as

    calls = []
    monkeypatch.setattr(_as, "AXUIElementSetAttributeValue",
                        lambda *a, **k: calls.append(a))
    assert ax_text.ensure_ax_enabled() is True
    assert calls == []


def test_ensure_ax_enabled_new_pid_sets(monkeypatch):
    """新前台 pid：调用 SET 开启 AX 树并缓存 pid（不再重复 SET）。"""
    _reset_cache()
    monkeypatch.setattr(ax_text, "_frontmost_pid", lambda: 777)
    import ApplicationServices as _as

    calls = []
    monkeypatch.setattr(_as, "AXUIElementCreateApplication",
                        lambda pid: ("AX", pid))
    monkeypatch.setattr(_as, "AXUIElementSetAttributeValue",
                        lambda el, attr, val: calls.append((el, attr, val)))
    assert ax_text.ensure_ax_enabled() is True
    assert ax_text._ax_enabled_pid == 777
    assert len(calls) == 1
    assert calls[0][1] == "AXEnhancedUserInterface"
    assert calls[0][2] is True  # NSNumber.numberWithBool_(True) 桥接为 Python bool

    # 同一 pid 再次调用 → 命中缓存，不再 SET
    assert ax_text.ensure_ax_enabled() is True
    assert len(calls) == 1
