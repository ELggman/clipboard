"""文本插入（文档 §70-72）：模拟粘贴 + 剪贴板恢复。

流程：保存原剪贴板 → 暂停 ClipboardWatcher（临时内容不进历史，§72）
→ 写入最终文本 → CGEventPost 合成 ⌘V 粘贴到前台应用 → 恢复原剪贴板
→ 恢复监听。

{{cursor}} 光标定位：第一阶段不做（跨应用方向键定位不可靠），
渲染文本中已移除标记，光标停在粘贴文本末尾（§5.3 简化决策）。
"""
import logging
import time

import Quartz

logger = logging.getLogger(__name__)

# ⌘V：V 的物理 vk 码 = 9（与热键一致）
_KEY_V = 9
_PASTE_DELAY = 0.05  # 粘贴完成后恢复剪贴板的等待秒数


def read_clipboard_text() -> str:
    """当前系统剪贴板文本（插入前保存原内容用）。"""
    try:
        from AppKit import NSPasteboard, NSPasteboardTypeString

        pb = NSPasteboard.generalPasteboard()
        return pb.stringForType_(NSPasteboardTypeString) or ""
    except Exception:
        return ""


def delete_backspaces(count: int) -> None:
    """删除用户刚输入的 shortcut 文本（触发后移除）。

    count <= 0 时不做。注意：必须在弹出任何对话框**之前**调用——
    弹框会夺走输入焦点，退格会打到对话框里。

    实现：**⌥⌫（Option+Backspace 删整词）**——组合键合成事件可靠
    （用户环境实测：退格序列会被应用丢弃部分、内容保留；⌥⌫ 能完整
    替换）。中文 shortcut 连续词场景会多删——中文触发成功后权衡。
    """
    if count <= 0:
        return
    logger.info("模板触发：⌥⌫ 删除用户输入的 shortcut（%d 字符）", count)
    time.sleep(0.05)  # 等目标应用就绪
    key_down = Quartz.CGEventCreateKeyboardEvent(None, 51, True)   # Delete vk
    key_up = Quartz.CGEventCreateKeyboardEvent(None, 51, False)
    Quartz.CGEventSetFlags(key_down, Quartz.kCGEventFlagMaskAlternate)
    Quartz.CGEventSetFlags(key_up, Quartz.kCGEventFlagMaskAlternate)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_up)
    time.sleep(0.15)  # 等待删除完成，再继续粘贴


def cancel_composition() -> None:
    """发送 Escape 取消输入法组合（中文输入法 Tab 触发时用）。

    中文输入法下按 Tab 时，用户输入的 shortcut 还在**组合**里（未上屏，
    SCIM 会把所有字母都缓进组合）——Escape 取消组合后字母消失，直接
    粘贴即可；**不能 ⌥⌫**（会破坏活动组合，实测 sig 被改写为 siv）。
    必须在弹任何对话框之前调用（弹框夺焦后 Escape 打错位置）。
    """
    logger.info("模板触发：Escape 取消输入法组合")
    time.sleep(0.05)  # 等目标应用就绪
    esc_down = Quartz.CGEventCreateKeyboardEvent(None, 53, True)   # Escape vk
    esc_up = Quartz.CGEventCreateKeyboardEvent(None, 53, False)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, esc_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, esc_up)
    time.sleep(0.15)  # 等待组合取消完成，再继续粘贴


def insert_text(text: str, watcher=None) -> bool:
    """模拟粘贴插入文本，完成后恢复原剪贴板。

    watcher：ClipboardWatcher（临时内容不得记入历史，§72）；None 时跳过暂停。
    失败返回 False（原剪贴板已尽力恢复）。
    """
    original = read_clipboard_text()
    try:
        if watcher is not None:
            watcher.set_paused(True)
        from services.action_service import set_clipboard_text

        set_clipboard_text(text)
        _simulate_paste()
        time.sleep(_PASTE_DELAY)
        # 恢复原剪贴板（粘贴完成后；watcher 仍在暂停，不会记入历史）
        if original:
            set_clipboard_text(original)
        else:
            from AppKit import NSPasteboard

            NSPasteboard.generalPasteboard().clearContents()
        return True
    except Exception:
        logger.exception("模板插入失败")
        try:
            if original:
                from services.action_service import set_clipboard_text

                set_clipboard_text(original)
        except Exception:
            pass
        return False
    finally:
        if watcher is not None:
            watcher.set_paused(False)


def _simulate_paste() -> None:
    """CGEventPost 合成 ⌘V（系统级事件流，粘贴到前台应用）。"""
    v_down = Quartz.CGEventCreateKeyboardEvent(None, _KEY_V, True)
    v_up = Quartz.CGEventCreateKeyboardEvent(None, _KEY_V, False)
    Quartz.CGEventSetFlags(v_down, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventSetFlags(v_up, Quartz.kCGEventFlagMaskCommand)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, v_up)
