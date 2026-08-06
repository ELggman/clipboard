"""Upper Case：文本转大写。"""
from .base import ClipboardAction


class UpperCaseAction(ClipboardAction):
    id = "upper_case"
    name = "Upper Case"
    icon = "case"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        return clipboard_item.content.upper()


ACTION = UpperCaseAction()
