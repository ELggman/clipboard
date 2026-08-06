"""Actions 行为测试：每个内置 Action 的输入 → 输出语义断言。

重点回归：行操作保留行结构（尾换行不丢）、空行处理、缩进处理、多行 Base64。
"""
import base64
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from actions import load_actions
from app.types import ClipboardItem, TEXT


@pytest.fixture(scope="module")
def actions():
    return {a.id: a for a in load_actions()}


def _text(content: str) -> ClipboardItem:
    return ClipboardItem(type=TEXT, content=content)


# ---- 行操作类：保留行结构 ----

def test_sort_lines_keeps_trailing_newline(actions):
    """尾换行保留（回归：splitlines+join 会丢尾换行）。"""
    a = actions["sort_lines"]
    assert a.can_handle(_text("c\nb\na\n"))
    assert a.execute(_text("c\nb\na\n")) == "a\nb\nc\n"


def test_sort_lines_blank_lines_to_bottom(actions):
    """空行沉底（分隔符不参与排序）。"""
    a = actions["sort_lines"]
    assert a.execute(_text("b\n\na\n\n")) == "a\nb\n\n\n"


def test_sort_lines_ignore_case(actions):
    a = actions["sort_lines"]
    assert a.execute(_text("Banana\napple\nCherry\n")) == "apple\nBanana\nCherry\n"


def test_sort_lines_single_line_not_handled(actions):
    assert actions["sort_lines"].can_handle(_text("single")) is False


def test_trim_space_keeps_structure(actions):
    """去空白：每行去首尾 + 保留尾换行（回归：旧实现丢尾换行/多 strip）。"""
    a = actions["trim_space"]
    assert a.execute(_text("  hello  \n  world  \n")) == "hello\nworld\n"


def test_trim_space_keeps_blank_lines(actions):
    a = actions["trim_space"]
    assert a.execute(_text("a\n\n  b  \n")) == "a\n\nb\n"


def test_remove_duplicate_lines_keeps_trailing_newline(actions):
    """去重行：保留尾换行与空行，内容去重保序。"""
    a = actions["remove_duplicate_lines"]
    assert a.execute(_text("a\nb\na\nb\n")) == "a\nb\n"
    assert a.execute(_text("x\n\ny\nx\n\n")) == "x\n\ny\n\n"


def test_remove_duplicate_lines_ignores_leading_ws(actions):
    """内容比较忽略行首尾空白，保留首次出现的原始行。"""
    a = actions["remove_duplicate_lines"]
    assert a.execute(_text("  a  \na\n")) == "  a  \n"


# ---- 文本转换类 ----

def test_upper_lower_case(actions):
    assert actions["upper_case"].execute(_text("hello")) == "HELLO"
    assert actions["lower_case"].execute(_text("HeLLo")) == "hello"


def test_json_pretty(actions):
    assert actions["json_pretty"].execute(_text('{"a":1}')) == '{\n  "a": 1\n}'


def test_base64_roundtrip(actions):
    enc = actions["base64_encode"].execute(_text("你好 world"))
    assert actions["base64_decode"].execute(_text(enc)) == "你好 world"


def test_base64_decode_multiline(actions):
    """多行 Base64（MIME 格式含换行）可解码（回归：validate=True 直接失败）。"""
    a = actions["base64_decode"]
    payload = "你好 base64"
    wrapped = "\n".join(
        base64.b64encode(payload.encode()).decode("ascii")[i:i + 4]
        for i in range(0, len(base64.b64encode(payload.encode()).decode("ascii")), 4)
    ) + "\n"
    assert a.can_handle(_text(wrapped))
    assert a.execute(_text(wrapped)) == payload


def test_url_roundtrip(actions):
    enc = actions["url_encode"].execute(_text("a b&c=1/中"))
    assert actions["url_decode"].execute(_text(enc)) == "a b&c=1/中"


# ---- 未就绪的 Action 隐藏 ----

def test_markdown_preview_hidden(actions):
    """未实现的 Action can_handle 恒 False（右键菜单不出现）。"""
    assert actions["markdown_preview"].can_handle(_text("# title")) is False
