"""Trim Space（去空白）：去除每行行首行尾空白。

语义：每行 strip（含缩进——复制带缩进的文本时请注意；保留行结构，
尾部换行与空行不动，不再丢尾换行）。
"""
from ._base import ClipboardAction
from ._line_utils import split_keepends


class TrimSpaceAction(ClipboardAction):
    id = "trim_space"
    name = "去空白"
    icon = "trim"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        stripped = []
        for line in split_keepends(clipboard_item.content):
            has_newline = line.endswith("\n")
            content = line.rstrip("\n").strip()
            stripped.append(content + ("\n" if has_newline else ""))
        return "".join(stripped)


ACTION = TrimSpaceAction()
