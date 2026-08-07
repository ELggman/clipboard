"""Remove Line Numbers：移除行首行号（新增.md §8.11）。"""
import re

from ._base import ClipboardAction


class RemoveLineNumbersAction(ClipboardAction):
    id = "remove_line_numbers"
    name = "移除行号"
    icon = "line"

    # 注意尾部用 [ \t]? 而非 \s?：\s 会吃掉换行导致空行丢失（实测）
    _LINE_NUM = re.compile(r"^\s*\d+\s*\|[ \t]?")

    def can_handle(self, clipboard_item) -> bool:
        if clipboard_item.type != "code" or not clipboard_item.content:
            return False
        return any(self._LINE_NUM.match(line)
                   for line in clipboard_item.content.splitlines())

    def execute(self, clipboard_item) -> str | None:
        lines = []
        for line in clipboard_item.content.splitlines(keepends=True):
            lines.append(self._LINE_NUM.sub("", line))
        return "".join(lines)


ACTION = RemoveLineNumbersAction()
