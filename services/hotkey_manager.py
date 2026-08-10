"""全局热键：自写 Quartz CGEventTap（DEVELOPMENT.md §3.2）。

为什么不用 pynput/keyboard：macOS 下 pynput 调 HIToolbox 会在监听线程
触发主线程断言崩溃（EXC_BREAKPOINT），且 keyboard 依赖 root/授权。
本方案按物理 vk 码 + 修饰键掩码匹配，不碰键盘布局、零第三方依赖。

依赖权限：「辅助功能」或「输入监控」（无程序化申请 API，只能引导用户）。

Tab Trigger（模板模块 §7.2）：enable_raw_keys() 后把无 ⌘⌃⌥ 修饰的
普通按键转发到主线程（raw_key_down 信号），事件本身**透传不消费**
（用户正常打字不受影响）。字符用 CGEventKeyboardGetUnicodeString 获取
（跟随当前键盘布局，避免硬编码 vk→字符映射表）。
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
# ⌘⇧S：S 的物理 vk 码 = 1（模板 Picker，§16）
KEY_S = 1
MASK_HOTKEY = Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift

# Tab Trigger 排除的修饰键（⌘/⌃/⌥ 组合键不参与输入流）
_RAW_EXCLUDE_MODS = (Quartz.kCGEventFlagMaskCommand
                     | Quartz.kCGEventFlagMaskControl
                     | Quartz.kCGEventFlagMaskAlternate)

# vk → 字符回退表（US/ANSI 布局）：CGEventKeyboardGetUnicodeString 只对
# 真实硬件事件返回字符（程序化构造的事件无 unicode 字段）——真实输入走
# API（跟随布局），构造事件/异常时回退本表
_VK_FALLBACK = {
    0: "a", 11: "b", 8: "c", 2: "d", 14: "e", 3: "f", 5: "g", 4: "h",
    34: "i", 38: "j", 40: "k", 37: "l", 46: "m", 45: "n", 31: "o",
    35: "p", 12: "q", 15: "r", 1: "s", 17: "t", 32: "u", 9: "v",
    13: "w", 7: "x", 16: "y", 6: "z",
    29: "0", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5",
    22: "6", 26: "7", 28: "8", 25: "9",
    49: " ", 36: "\n", 51: "\x7f", 48: "\t",  # Space/Return/Delete/Tab
}

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
    raw_key_down = Signal(int, str)  # (vk, char) 普通按键输入流（Tab Trigger）

    def __init__(self, keycode: int = KEY_V, mask: int = MASK_HOTKEY, parent: QObject | None = None):
        super().__init__(parent)
        self._bindings: list[tuple[int, int, Signal]] = [(keycode, mask, self.activated)]
        self._tap = None
        self._thread: threading.Thread | None = None
        self._raw_key_enabled = False  # Tab Trigger 输入流（enable_raw_keys 开启）

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

    def enable_raw_keys(self, enabled: bool = True) -> None:
        """开启/关闭普通按键输入流转发（Tab Trigger 用）。"""
        self._raw_key_enabled = enabled

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
        # Tab Trigger：无 ⌘⌃⌥ 修饰的普通按键 → 转发到主线程匹配 shortcut
        # （返回 False 透传，用户的正常打字/制表符切换不受影响）
        if self._raw_key_enabled and not (flags & _RAW_EXCLUDE_MODS):
            char = self._unicode_char(event, keycode)
            if char is not None:
                self.raw_key_down.emit(keycode, char)
        return False

    @staticmethod
    def _unicode_char(event, keycode: int) -> str | None:
        """取按键的实际字符（跟随键盘布局）。

        优先 CGEventKeyboardGetUnicodeString（真实硬件事件有效）；
        无字符/构造事件/异常时回退 vk 映射表（US 布局）。
        """
        try:
            from ctypes import byref, c_uint16

            max_len = 8
            actual = c_uint16(0)
            chars = (c_uint16 * max_len)()
            Quartz.CGEventKeyboardGetUnicodeString(
                event, max_len, byref(actual), chars)
            n = min(actual.value, max_len)
            if n > 0:
                return "".join(chr(chars[i]) for i in range(n))
        except Exception:
            pass
        return _VK_FALLBACK.get(keycode)

    # ---- 内部 ----

    def _run_loop(self) -> None:
        source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        runloop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(runloop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CFRunLoopRun()
