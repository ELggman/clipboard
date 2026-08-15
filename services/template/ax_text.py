"""辅助功能（AX）读取前台应用焦点输入框文本 + 输入法组合状态检测。

用途：
- 中文 shortcut 触发：CGEventTap 只能看到拼音按键（wenhou），看不到输入法
  **上屏的汉字**（选字不产生按键事件）——通过 AX 读取焦点文本、从末尾匹配
  shortcut（中英文都行）。
- 组合守卫：输入法组合中（marked text 存在）不自动触发——按键尚未真正上屏，
  此时删除/粘贴会破坏组合（实测：sig 被改写成 siv）。
- ensure_ax_enabled：强制 Electron/Chromium 应用（VS Code 等）开启 AX 树——
  它们默认不构建 accessibility 树，read_focused_text 恒为 None（实测）。

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


def read_focused_selection() -> str | None:
    """读取前台应用焦点输入框当前**选中的文本**。失败/无选中返回 None。

    {{selection}} 变量值源（§值源-系统状态）：触发时取前台应用里选中的
    文字。依赖辅助功能权限 + 应用暴露 kAXSelectedTextAttribute（多数
    编辑器支持；不支持/无选中 → None → 渲染空串，与 {{clipboard}} 允许
    为空同语义）。
    """
    try:
        from ApplicationServices import (
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
            kAXFocusedUIElementAttribute,
            kAXSelectedTextAttribute,
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
            focused, kAXSelectedTextAttribute, None)
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


# 已强制开启 AX 的前台应用 pid（同 pid 只 SET 一次：Chromium 会话内不会
# 自行关闭 accessibility 树，无需反复设置）
_ax_enabled_pid: int | None = None


def _frontmost_pid() -> int | None:
    """前台应用 pid（无则 None）。独立出来便于测试替换。"""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.processIdentifier() if app is not None else None
    except Exception:
        return None


def ensure_ax_enabled() -> bool:
    """强制前台应用开启 AX 树（中文 shortcut 触发的前提）。

    背景（实测）：Electron/Chromium 应用（VS Code 等）默认**不构建**
    accessibility 树——AXUIElementCopyAttributeValue 查 focused 元素返回
    kAXErrorNoValue，read_focused_text 恒为 None → 中文 shortcut（依赖 AX
    读取上屏汉字）触发路径全死；英文 shortcut 走键盘缓冲不依赖 AX，正常。
    设 kAXEnhancedUserInterface=true 强制开启（Chromium 探测到 AX 客户端即
    构建树；SET 返回 kAXErrorNotImplemented 也有效——实测 focused 查询从
    NoValue → 成功读到编辑器文本）。

    同一前台 pid 只 SET 一次（缓存）；前台应用切换后对新 pid 再 SET。
    失败（无前台应用/无权限/非 AX 应用）返回 False，调用方无害忽略。

    调用方需自行判断是否需要：仅当存在中文 shortcut 时才调用（见
    template_service.has_chinese_shortcut）——避免给纯英文用户的编辑器
    强开 Chromium AX 的额外开销。
    """
    global _ax_enabled_pid
    pid = _frontmost_pid()
    if pid is None:
        return False
    if pid == _ax_enabled_pid:
        return True  # 已增强（无前台切换）
    try:
        from ApplicationServices import (
            AXUIElementCreateApplication,
            AXUIElementSetAttributeValue,
        )
        from Foundation import NSNumber

        ax_app = AXUIElementCreateApplication(pid)
        AXUIElementSetAttributeValue(
            ax_app, "AXEnhancedUserInterface",
            NSNumber.numberWithBool_(True))
        _ax_enabled_pid = pid
        logger.info("已为前台应用强制开启 AX 树 (pid=%s)", pid)
        return True
    except Exception:
        return False
