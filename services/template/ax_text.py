"""辅助功能（AX）读取前台应用焦点输入框文本 + 输入法组合状态检测。

用途：
- 中文 shortcut 触发：CGEventTap 只能看到拼音按键（wenhou），看不到输入法
  **上屏的汉字**（选字不产生按键事件）——通过 AX 读取焦点文本、从末尾匹配
  shortcut（中英文都行）。
- 组合守卫：输入法组合中（marked text 存在）不自动触发——按键尚未真正上屏，
  此时删除/粘贴会破坏组合（实测：sig 被改写成 siv）。

⚠️ 依赖 pyobjc-framework-ApplicationServices（HIServices 提供 AX C API）——
   requirements.txt 必须包含。没有它时 `Quartz.kAX*` 常量不存在，本模块的
   try/except 会让 read_focused_text 静默返回 None（曾经的坑：AX 路径全死）。

依赖「辅助功能」权限（与 CGEventTap 热键相同——已授权即可用）。
"""
import logging

logger = logging.getLogger(__name__)


def read_focused_text() -> str | None:
    """读取前台应用焦点输入框的当前文本。失败（无权限/不支持）返回 None。"""
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXFocusedUIElementAttribute,
            kAXValueAttribute,
        )
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None
        ax_app = AXUIElementCreateApplication(app.processIdentifier())
        err, focused = AXUIElementCopyAttributeValue(
            ax_app, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused is None:
            return None
        err, value = AXUIElementCopyAttributeValue(
            focused, kAXValueAttribute, None)
        if err != 0:
            return None
        return str(value) if value is not None else None
    except Exception:
        return None


def is_ime_composing() -> bool:
    """焦点输入框是否处于输入法组合（marked text）状态。失败返回 False。

    中文输入法下，打字时组合文本（拼音/候选）在输入框内以 marked text 存在，
    未上屏。AXTextInputMarkedRange 返回该范围（CFRange），length > 0 即组合中。
    英文输入法（或空闲）时 length == 0。不支持该属性的应用返回错误 → False。
    """
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            AXValueGetType,
            AXValueGetValue,
            kAXFocusedUIElementAttribute,
            kAXValueCFRangeType,
        )
        from AppKit import NSWorkspace, NSAccessibilityTextInputMarkedRangeAttribute

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return False
        ax_app = AXUIElementCreateApplication(app.processIdentifier())
        err, focused = AXUIElementCopyAttributeValue(
            ax_app, kAXFocusedUIElementAttribute, None)
        if err != 0 or focused is None:
            return False
        err, marked = AXUIElementCopyAttributeValue(
            focused, NSAccessibilityTextInputMarkedRangeAttribute, None)
        if err != 0 or marked is None:
            return False
        if AXValueGetType(marked) != kAXValueCFRangeType:
            return False
        ok, (_loc, length) = AXValueGetValue(marked, kAXValueCFRangeType, None)
        return bool(ok) and length > 0
    except Exception:
        return False
