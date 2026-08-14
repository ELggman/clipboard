"""文本插入层纯逻辑测试。

delete_backspaces 依赖合成键盘事件 + AX 读焦点文本（真实前台应用），无法
稳定断言；只覆盖可纯逻辑验证的 _remaining_after_delete（⌥⌫ 失效后的退格
补删计数，微信 fix 的核心判定）。
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
