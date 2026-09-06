"""QNSPanel.canBecomeKeyWindow 白名单覆写（macOS 键盘路由根因修复）。

Qt.Popup 在 macOS 是 QNSPanel（无边框 NSPanel）；默认 canBecomeKeyWindow=NO
→ 永远不能成为 key window，macOS 不把键盘发给它——Quick Paste / 模板 Picker 的
回车无反应/beep、以及「应用未激活时首次弹出即被 Qt 秒关」，都源于此。

早期版本把 canBecomeKeyWindow **全局**覆写为「恒 YES」，结果殃及两类本不该动
的 QNSPanel：QComboBox 下拉（同为 QNSPanel，默认 NO）出现空白+桌面残留；
**模态 QDialog（macOS 上也实现为 QNSPanel 子类，默认 YES）丢失 canBecomeKey，
文本框全部无法输入**（用户实测严重 bug：触发模板/隐私搜索框打不了字）。

因此这里**委托原实现 + 白名单**：先保存 QNSPanel 原 canBecomeKeyWindow 的 IMP；
新覆写对被白名单登记的本应用弹窗返回 YES，其余窗口**调用原 IMP**——QDialog
恢复默认 YES、Qt.Popup/QComboBox 下拉恢复默认 NO，行为与不 patch 完全一致。

macOS 在窗口试图成为 key window 时询问 `canBecomeKeyWindow:`，回调的 self 即该
NSWindow。PyObjC 每次 objc_object(指针).window() 可能返回**不同的 Python 包装**
（同一 OS 对象），但两者 PyObjC `==` 会转发到原生 isEqual:（NSWindow 即指针相等）
→ 按 `==` 匹配即可跨包装判同。offscreen 无 ObjC 类 → 静默跳过，不抛错。
"""
import logging

logger = logging.getLogger(__name__)

_PATCHED = False
# 白名单：允许成为 key window 的原生 QNSPanel（强引用防 GC；跨包装按 == 判同）
_KEY_PANELS = set()
_ORIG_IMPL = None  # 保存的原 canBecomeKeyWindow IMP，供非白名单窗口委托


def register_native_panel(widget) -> None:
    """把 widget 的原生面板加入白名单（show 之后调用；幂等）。

    show 后原生 NSWindow 才存在，此刻登记；回调 canBecomeKeyWindow 时按
    PyObjC 相等（原生 isEqual:）匹配放行。重复调用无害。
    """
    panel = _native_panel(widget)
    if panel is not None:
        _KEY_PANELS.add(panel)


def unregister_native_panel(widget) -> None:
    """widget 隐藏时移出白名单：防止地址复用把新 panel 误判为白名单面板。"""
    target = _native_panel(widget)
    if target is None:
        return
    for p in list(_KEY_PANELS):
        if p == target:
            _KEY_PANELS.discard(p)


def _native_panel(widget) -> object | None:
    """widget 的顶层原生 QNSPanel（无原生窗口/非 macOS → None）。"""
    from PySide6.QtGui import QGuiApplication

    # offscreen 的 winId 是 Qt 句柄而非 NSView，对其发 ObjC 消息会崩 → 先挡
    if QGuiApplication.platformName() not in ("cocoa", "macos"):
        return None
    from ctypes import c_void_p

    ww = widget.windowHandle()
    if ww is None:
        widget.winId()  # 强制创建原生窗口
        ww = widget.windowHandle()
    if ww is None or not ww.winId():
        return None
    try:
        import objc

        return objc.objc_object(c_void_p=ww.winId()).window()
    except Exception:
        return None


def _can_become_key(self):
    if any(self == p for p in _KEY_PANELS):
        return True
    if _ORIG_IMPL is not None:
        try:
            return _ORIG_IMPL(self)
        except Exception:
            logger.debug("委托原 IMP 失败，回落 False", exc_info=True)
    return False


def patch_qnspanel_can_become_key() -> None:
    """在 QNSPanel 上覆写 canBecomeKeyWindow → 白名单 YES，其余委托原实现。

    幂等；offscreen（无 ObjC 类）或已打过 → 静默跳过，不抛错。
    """
    global _PATCHED, _ORIG_IMPL
    if _PATCHED:
        return
    _PATCHED = True
    try:
        import objc

        cls = objc.lookUpClass("QNSPanel")
        if cls is None:
            return
        # 先保存原 IMP（委托用），再覆写
        sel = objc.selector(None, selector=b"canBecomeKeyWindow",
                            signature=b"B16@0:8")
        _ORIG_IMPL = cls.instanceMethodForSelector_(sel)
        imp = objc.selector(_can_become_key, selector=b"canBecomeKeyWindow",
                            signature=b"B16@0:8")
        objc.classAddMethods(cls, [imp])
        logger.info("macOS：已覆写 QNSPanel.canBecomeKeyWindow（白名单+委托原实现）")
    except Exception:
        logger.debug("覆写 QNSPanel.canBecomeKeyWindow 跳过（非 macOS GUI）",
                     exc_info=True)