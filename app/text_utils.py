"""文本工具：UI 与 Actions 共用的轻量纯函数（无 Qt/DB 依赖）。"""
import re

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
