"""Sort Lines：多行文本按行排序。"""
from .base import ClipboardAction


class SortLinesAction(ClipboardAction):
    id = "sort_lines"
    name = "Sort Lines"
    icon = "sort"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and "\n" in clipboard_item.content

    def execute(self, clipboard_item) -> str | None:
        lines = clipboard_item.content.splitlines()
        return "\n".join(sorted(lines, key=str.casefold))


ACTION = SortLinesAction()
