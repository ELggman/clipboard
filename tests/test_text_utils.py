"""text_stats 单元测试：Word 口径的字符/字数/行数统计。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from app.text_utils import TextStats, strip_markdown, text_stats


def test_empty_text():
    assert text_stats("") == TextStats(0, 0, 0, 0)
    assert text_stats("").label() == "0 字符 · 0 字符(不含空格) · 0 字 · 0 行"


def test_chars_counts_spaces():
    s = text_stats("a b c")
    assert s.chars == 5
    assert s.chars_no_space == 3


def test_chars_no_space_strips_newlines_and_tabs():
    s = text_stats("a\n\tb ")
    assert s.chars == 5
    assert s.chars_no_space == 2


def test_words_latin():
    # 拉丁/数字按词块计；标点不算词
    assert text_stats("hello world, foo 42").words == 4


def test_words_cjk_counted_per_char():
    assert text_stats("你好世界").words == 4


def test_words_mixed_cjk_latin():
    # 「你好 world」→ 2 个汉字 + 1 个英文词
    assert text_stats("你好 world").words == 3


def test_lines_single_line():
    assert text_stats("one line").lines == 1


def test_lines_multiple():
    assert text_stats("a\nb\nc").lines == 3


def test_lines_trailing_newline_matches_editor():
    # 末尾换行 → 与 QPlainTextEdit.lineCount 一致（多一个空行）
    assert text_stats("a\n").lines == 2


def test_label_format():
    s = text_stats("hi!")           # 3 字符，无空格，1 词，1 行
    assert s.label() == "3 字符 · 3 字符(不含空格) · 1 字 · 1 行"


def test_stats_frozen():
    import dataclasses

    s = text_stats("x")
    assert isinstance(s, TextStats)
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.chars = 9  # type: ignore[misc]


def test_strip_markdown_still_works():
    # 回归：新增统计未破坏既有 Markdown 剥离
    assert strip_markdown("**bold** and `code`") == "bold and code"
