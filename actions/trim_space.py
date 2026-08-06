"""Trim Space：去除每行首尾空白。"""
from ._base import ClipboardAction


class TrimSpaceAction(ClipboardAction):
    id = "trim_space"
    name = "去空白"
    icon = "trim"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        lines = clipboard_item.content.splitlines()
        stripped = [line.strip() for line in lines]
        return "\n".join(stripped).strip()


ACTION = TrimSpaceAction()
