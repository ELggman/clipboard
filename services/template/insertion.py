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


def delete_backspaces(count: int, shortcut: str = "") -> None:
    """删除用户刚输入的 shortcut 文本（触发后移除）。

    count = shortcut 字符数；shortcut = 实际文本，用于 ⌥⌫ 失效后的核对兜底。
    count <= 0 时不做。注意：必须在弹出任何对话框**之前**调用——
    弹框会夺走输入焦点，退格会打到对话框里。

    实现：先 **⌥⌫（Option+Backspace 删整词）**——组合键合成事件可靠
    （用户环境实测：退格序列会被应用丢弃部分、内容保留；⌥⌫ 能完整
    替换）。⌥⌫ 后读焦点文本核对：**仅当文本末尾（rstrip 后）仍以
    shortcut 结尾**才逐个退格补删（微信实测：⌥⌫ 对中文整词无效，原词
    残留）——Typora/VS Code 的 ⌥⌫ 删词成功、仅保留尾随空白（块伪影/
    行尾符），此时**不得**再退格，否则多删空白（回归：vscode/typora
    自动/Tab 触发多删原词前内容）。补删带间隔防应用丢弃，最多两轮。
    读不到文本（无 AX）则不核对、保持原 ⌥⌫ 行为。
    """
    if count <= 0:
        return
    logger.info("模板触发：删除 shortcut 文本（%d 字符）", count)
    time.sleep(0.05)  # 等目标应用就绪
    before_text = _focused_text()
    if not shortcut or before_text is None:
        return  # 无 shortcut 文本或读不到文本：保持原 ⌥⌫ 行为
    before_len = len(before_text.rstrip())  # ⌥⌫ 前文本长度（去尾随空白）
    _post_delete_key(option=True)           # ⌥⌫ 删整词
    time.sleep(0.15)  # 等待删除完成，再继续粘贴
    remaining = _remaining_after_delete(before_len, shortcut, _focused_text())
    if remaining <= 0:
        return  # ⌥⌫ 已删尽 shortcut（或读不到）：无需补删
    logger.info("⌥⌫ 未删尽 shortcut，逐个退格补删 %d 字符", remaining)
    for _round in range(2):  # 最多两轮（退格可能被应用丢弃部分）
        for _ in range(remaining):
            _post_delete_key(option=False)
            time.sleep(0.04)
        time.sleep(0.1)  # 等待补删完成
        after = _focused_text()
        if after is None:
            return
        # 补删轮次用原样长度量到目标（进此循环 = ⌥⌫ 无效应用，尾随空白
        # 是用户输入的一部分，需一并删除；endswith 门不再适用）
        target = max(0, before_len - len(shortcut))
        remaining = min(max(0, len(after) - target), len(shortcut) + 10)
        if remaining <= 0:
            return


def _post_delete_key(option: bool) -> None:
    """合成 Delete 键（option=True 时 ⌥⌫ 删整词，否则退格删单字符）。"""
    key_down = Quartz.CGEventCreateKeyboardEvent(None, 51, True)   # Delete vk
    key_up = Quartz.CGEventCreateKeyboardEvent(None, 51, False)
    if option:
        Quartz.CGEventSetFlags(key_down, Quartz.kCGEventFlagMaskAlternate)
        Quartz.CGEventSetFlags(key_up, Quartz.kCGEventFlagMaskAlternate)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_down)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, key_up)


def _focused_text() -> str | None:
    """焦点文本框当前**原样**文本（含尾随空白）。读不到返回 None。

    ⌥⌫ 核对用：endswith 判定在 rstrip 后进行（shortcut 匹配语义），补删
    计数用原样长度（尾随空白也要删掉，如微信 Tab 插入的制表符）。
    """
    try:
        from services.template.ax_text import read_focused_text

        return read_focused_text()
    except Exception:
        return None


def _remaining_after_delete(before_len: int | None, shortcut: str,
                            after: str | None) -> int:
    """⌥⌫ 后还需退格删除的字符数。

    before_len = ⌥⌫ 前 rstrip 后长度（目标 = 删掉 shortcut 后应剩内容长）。
    after = ⌥⌫ 后焦点文本**原样**；None → 0（读不到不核对）。核心判定：
    after（rstrip 后）**仍以 shortcut 结尾**才需补删——⌥⌫ 删词成功时
    （Typora/VS Code）尾随空白是块伪影/行尾符，不得再退格（多删即本次
    回归）；微信 ⌥⌫ 对中文整词无效 → after 仍以 shortcut 结尾 → 补删到
    目标，尾随空白（如微信 Tab 插入的制表符）一并删除。上限保护
    len(shortcut)+10（防 AX 读到无关大文本时失控）。
    """
    if before_len is None or after is None:
        return 0
    if not after.rstrip().endswith(shortcut):
        return 0  # ⌥⌫ 已删尽 shortcut：无需补删
    target = max(0, before_len - len(shortcut))
    return min(max(0, len(after) - target), len(shortcut) + 10)


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
