"""全局热键：自写 Quartz CGEventTap（DEVELOPMENT.md §3.2）。

为什么不用 pynput/keyboard：macOS 下 pynput 调 HIToolbox 会在监听线程
触发主线程断言崩溃（EXC_BREAKPOINT），且 keyboard 依赖 root/授权。
本方案按物理 vk 码 + 修饰键掩码匹配，不碰键盘布局、零第三方依赖。

依赖权限：「辅助功能」或「输入监控」（无程序化申请 API，只能引导用户）。
"""
import ctypes
import logging
import threading

import Quartz
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

# ⌘⇧V：V 的物理 vk 码 = 9（不依赖键盘布局）
KEY_V = 9
# ⌘⇧P：P 的物理 vk 码 = 35（隐私模式开关，新增.md §9.4）
KEY_P = 35
MASK_HOTKEY = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift

_INSTANCE: "HotkeyManager | None" = None


def ax_is_trusted() -> bool:
    """实时检测「辅助功能」授权。无申请 API，只能引导用户去系统设置。"""
    try:
        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework"
            "/ApplicationServices"
        )
        return bool(lib.AXIsProcessTrusted())
    except OSError:
        logger.exception("加载 ApplicationServices 失败")
        return False


def _tap_callback(_proxy, _event_type, event, _refcon):
    """CGEventTap 回调（非 Qt 线程）。返回 None 表示消费事件。"""
    mgr = _INSTANCE
    if mgr is None:
        return event
    if mgr.handle_event(event):
        return None
    return event


class HotkeyManager(QObject):
    """全局热键监听（多绑定）。回调内只做轻量匹配；跨线程用 Qt signal 派发到主线程。

    绑定：构造函数注册默认 ⌘⇧V → activated；add_binding() 可追加其它热键
    （如 ⌘⇧P → privacy_toggle）。所有绑定共享一个 CGEventTap。
    """

    activated = Signal()           # ⌘⇧V Quick Paste（主线程接收）
    privacy_toggle = Signal()      # ⌘⇧P 隐私模式开关（新增.md §9.4）
    permission_required = Signal()  # 未授权/创建失败

    def __init__(self, keycode: int = KEY_V, mask: int = MASK_HOTKEY, parent: QObject | None = None):
        super().__init__(parent)
        self._bindings: list[tuple[int, int, Signal]] = [(keycode, mask, self.activated)]
        self._tap = None
        self._thread: threading.Thread | None = None

    def add_binding(self, keycode: int, mask: int, signal: Signal) -> None:
        """追加热键绑定（start() 前调用）。"""
        self._bindings.append((keycode, mask, signal))

    def start(self) -> bool:
        global _INSTANCE
        if not ax_is_trusted():
            logger.warning("未获「辅助功能」授权，热键不可用")
            self.permission_required.emit()
            return False
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGHIDEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown),
            _tap_callback,
            None,
        )
        if self._tap is None:
            # 沙箱环境（如 Claude Code Bash）会拦截 CGEventTapCreate；app 内正常运行
            logger.error("CGEventTapCreate 失败（未授权或系统拒绝）")
            self.permission_required.emit()
            return False
        _INSTANCE = self
        self._thread = threading.Thread(
            target=self._run_loop, name="hotkey-tap", daemon=True
        )
        self._thread.start()
        logger.info("全局热键启动 (%d 个绑定)", len(self._bindings))
        return True

    def stop(self) -> None:
        if self._tap is not None:
            Quartz.CGEventTapEnable(self._tap, False)
        self._tap = None
        _INSTANCE = None
        logger.info("全局热键已停止")

    def handle_event(self, event) -> bool:
        """匹配热键（遍历所有绑定）。返回 True 表示已消费事件。回调内不得做重活。"""
        if Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventAutorepeat):
            return True  # 自动重复直接吞掉，不重复触发
        flags = Quartz.CGEventGetFlags(event)
        keycode = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
        for kc, mask, signal in self._bindings:
            if keycode == kc and flags & mask == mask:
                signal.emit()
                return True
        return False

    # ---- 内部 ----

    def _run_loop(self) -> None:
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        runloop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(runloop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CFRunLoopRun()
