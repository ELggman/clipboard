"""Add Line Numbers：为代码/文本添加行号（新增.md §8.10）。"""
from ._base import ClipboardAction
from ._line_utils import split_keepends


class AddLineNumbersAction(ClipboardAction):
    id = "add_line_numbers"
    name = "添加行号"
    icon = "line"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "code" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        out = []
        for i, line in enumerate(split_keepends(clipboard_item.content), 1):
            out.append(f"{i} | {line}")
        return "".join(out)


ACTION = AddLineNumbersAction()
