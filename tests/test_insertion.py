"""文本插入层测试。

delete_backspaces 依赖合成键盘事件 + AX 读焦点文本（真实前台应用），无法
稳定断言；只覆盖可纯逻辑验证的 _remaining_after_delete（⌥⌫ 失效后的退格
补删计数，微信 fix 的核心判定）。

insert_text 全链路（写剪贴板 → 合成 ⌘V → 还原）用**替身**覆盖：真实
CGEventPost 一个都不发、真实剪贴板一个字节都不动（约束：自动化验证绝不
触碰真实 ⌘V 插入路径），但把契约锁死——送出去的就是渲染结果本身、
watcher 插入期间暂停（§72）、无论成败都还原原剪贴板。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.template.insertion import _remaining_after_delete


def test_alt_backspace_worked_no_fallback():
    """⌥⌫ 已删尽 shortcut：after 不再以 shortcut 结尾 → 0 补删。

    before（去空白）6='问候托尔斯泰'，⌥⌫ 删整词后 after='问候'。
    """
    assert _remaining_after_delete(6, "托尔斯泰", "问候") == 0


def test_block_artifact_whitespace_preserved():
    """Typora 块伪影：⌥⌫ 删词成功、保留尾随 \\n\\n → 不得补删（回归主因）。

    旧实现按原样长度算剩余会误判 2 个 \\n 为残留 shortcut → 多删空白。
    after.rstrip()='问候' 不以 shortcut 结尾 → 0。
    """
    assert _remaining_after_delete(6, "托尔斯泰", "问候\n\n") == 0


def test_line_ending_newline_preserved():
    """VS Code 行尾符：⌥⌫ 删词成功、保留行尾 \\n → 不得补删（回归主因）。

    after.rstrip()='你好' 不以 shortcut 结尾 → 0。
    """
    assert _remaining_after_delete(7, "today", "你好\n") == 0


def test_alt_backspace_failed_wechat():
    """微信 ⌥⌫ 对中文整词无效：after 仍以 shortcut 结尾 → 补删。

    before（去空白）4='托尔斯泰'，⌥⌫ 后 after='托尔斯泰'；目标=0，
    剩余 = 4-0 = 4。
    """
    assert _remaining_after_delete(4, "托尔斯泰", "托尔斯泰") == 4


def test_alt_backspace_failed_with_trailing_tab():
    """微信含 Tab 插入的制表符：after 原样含 \\t（rstrip 后仍命中 shortcut）。

    目标=0，after 原样长 5（'托尔斯泰\\t'）→ 补删 5（含制表符）。
    """
    assert _remaining_after_delete(4, "托尔斯泰", "托尔斯泰\t") == 5


def test_preceding_text_target_respected():
    """shortcut 前有正文：目标 = before(去空白) - shortcut 长，前文保留。

    before 6='问候托尔斯泰'，⌥⌫ 无效 after 原样 6 → 补删 6-2=4 → 剩'问候'。
    """
    assert _remaining_after_delete(6, "托尔斯泰", "问候托尔斯泰") == 4


def test_none_reads_no_check():
    """读不到 AX 文本（None）：返回 0，不核对（保持原 ⌥⌫ 行为）。"""
    assert _remaining_after_delete(None, "托尔斯泰", "托尔斯泰") == 0
    assert _remaining_after_delete(4, "托尔斯泰", None) == 0
    assert _remaining_after_delete(None, "托尔斯泰", None) == 0


def test_cap_upper_bound():
    """上限保护：AX 读到无关大文本时剩余最多 len(shortcut)+10。"""
    after = "x" * 50 + "托尔斯泰"  # 大前文 + shortcut（⌥⌫ 无效残留）
    assert _remaining_after_delete(4, "托尔斯泰", after) == 14


def test_english_shortcut_wechat():
    """英文 shortcut 微信场景（⌥⌫ 无效）：按字符补删，含行尾。"""
    assert _remaining_after_delete(7, "today", "你好today\n") == 6


# ---- insert_text：全链路契约（系统面全部替身，不发真实 ⌘V）----

class _QuartzSpy:
    """Quartz 替身：记录 CGEventPost 调用，不碰真实系统事件流。"""

    kCGHIDEventTap = 0
    kCGEventFlagMaskCommand = 1 << 20

    def __init__(self):
        self.posted = []

    def CGEventCreateKeyboardEvent(self, src, key, down):
        return ("ev", key, down)

    def CGEventSetFlags(self, ev, flags):
        pass

    def CGEventPost(self, tap, ev):
        self.posted.append(ev)


class _WatcherSpy:
    """ClipboardWatcher 替身：只记录暂停/恢复时序。"""

    def __init__(self):
        self.states = []

    def set_paused(self, paused):
        self.states.append(paused)


def _stub_paste(monkeypatch):
    """把 insert_text 的三个系统出口换成替身。返回 (写入记录, Quartz 替身)。

    - 剪贴板写入：记录（真实 NSPasteboard 不动）
    - 读原剪贴板：固定返回「原内容」（真实剪贴板不读）
    - Quartz：替身（真实 CGEventPost 绝不调用）
    """
    import services.action_service as action_service
    import services.template.insertion as insertion

    written: list[str] = []
    monkeypatch.setattr(action_service, "set_clipboard_text",
                        lambda text: written.append(text))
    monkeypatch.setattr(insertion, "read_clipboard_text", lambda: "原内容")
    spy = _QuartzSpy()
    monkeypatch.setattr(insertion, "Quartz", spy)
    return written, spy


def test_insert_text_payload_and_restore(monkeypatch):
    """送进剪贴板的就是渲染结果本身（中文/emoji 原样），随后还原原文。

    这是模板→插入的最后一段：前面渲染得再对，这一段把文本写坏就白搭。
    """
    import services.template.insertion as insertion

    written, spy = _stub_paste(monkeypatch)
    w = _WatcherSpy()

    assert insertion.insert_text("HELLO 世界 🎉\n第二行", w) is True
    assert written == ["HELLO 世界 🎉\n第二行", "原内容"]  # 临时内容 → 还原
    assert len(spy.posted) == 2                          # ⌘V 按下 + 抬起
    assert w.states == [True, False]                     # §72 插入期间暂停监听


def test_insert_text_failure_still_restores(monkeypatch):
    """粘贴失败（返回 False）也必须还原原剪贴板，且恢复监听。"""
    import services.template.insertion as insertion

    written, _spy = _stub_paste(monkeypatch)

    def _boom():
        raise RuntimeError("合成事件失败")

    monkeypatch.setattr(insertion, "_simulate_paste", _boom)
    w = _WatcherSpy()

    assert insertion.insert_text("x", w) is False
    assert written[-1] == "原内容"   # 兜底还原
    assert w.states == [True, False]


def test_insert_text_no_watcher(monkeypatch):
    """watcher=None（无监听器场景）不崩，照常走完。"""
    import services.template.insertion as insertion

    written, spy = _stub_paste(monkeypatch)

    assert insertion.insert_text("无监听", None) is True
    assert written == ["无监听", "原内容"]
    assert len(spy.posted) == 2
