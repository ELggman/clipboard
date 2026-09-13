"""文本工具：UI 与 Actions 共用的轻量纯函数（无 Qt/DB 依赖）。"""
import re
from dataclasses import dataclass

# Markdown 行级语法（Copy Without Formatting 用，新增.md §8.8）
_MD_STRIP = [
    (re.compile(r"^\s{0,3}#{1,6}\s+"), ""),           # 标题
    (re.compile(r"^\s*([-*+]|\d+\.)\s+"), ""),        # 列表符号
    (re.compile(r"^\s*>\s?"), ""),                    # 引用
    (re.compile(r"^\s*```.*$"), ""),                  # 代码围栏行
    (re.compile(r"^\s*\|.*\|$"), ""),                 # 表格行
    (re.compile(r"\*\*([^*]+)\*\*"), r"\1"),          # 加粗
    (re.compile(r"__([^_]+)__"), r"\1"),              # 加粗 alt
    (re.compile(r"`([^`]+)`"), r"\1"),                # 行内代码
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),    # 链接 → 文字
    (re.compile(r"!\[([^\]]*)\]\([^)]+\)"), r"\1"),   # 图片 → alt 文字
    (re.compile(r"(?<!\*)\*(?!\*)([^*\n]+)\*(?!\*)"), r"\1"),  # 斜体
]


def strip_markdown(content: str) -> str:
    """去除 Markdown 语法标记，保留纯文本（Copy Without Formatting）。"""
    lines = []
    for line in content.splitlines():
        for pattern, repl in _MD_STRIP:
            line = pattern.sub(repl, line)
        lines.append(line)
    return "\n".join(lines).strip()


# ---- 文本统计（详情弹层状态栏用，Word 口径） ----
# 中日韩表意文字（扩展 A + 基本区 + 兼容区）与假名，逐字计数
_CJK_RE = re.compile(
    "[㐀-䶿一-鿿豈-﫿぀-ヿ]")
_WORD_RE = re.compile(r"[A-Za-z0-9_']+")


@dataclass(frozen=True)
class TextStats:
    """一段文本的统计口径（对齐 Office Word 状态栏）。"""

    chars: int           # 字符数（含空格）
    chars_no_space: int  # 字符数（不含空格/换行等空白）
    words: int           # 字数：CJK 逐字计 1，拉丁/数字按词计
    lines: int           # 行数（空文本记 0）

    def label(self) -> str:
        return (f"{self.chars} 字符 · {self.chars_no_space} 字符(不含空格)"
                f" · {self.words} 字 · {self.lines} 行")


def text_stats(text: str) -> TextStats:
    """统计文本（纯函数，无 Qt 依赖）。

    - 字符数：`len(text)`，含空格
    - 不含空格：剔除所有空白字符（空格/制表/换行）后计数
    - 字数：CJK（中日韩）逐字计 1；其余按 `[A-Za-z0-9_']+` 词块计 1
    - 行数：`\\n` 计数 + 1（与 QPlainTextEdit 显示行数一致）；空文本为 0
    """
    if not text:
        return TextStats(0, 0, 0, 0)
    chars = len(text)
    chars_no_space = len(re.sub(r"\s", "", text))
    words = (len(_CJK_RE.findall(text))
             + len(_WORD_RE.findall(_CJK_RE.sub(" ", text))))
    lines = text.count("\n") + 1
    return TextStats(chars, chars_no_space, words, lines)
