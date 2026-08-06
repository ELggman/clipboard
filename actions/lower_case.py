"""Lower Case：文本转小写。"""
from ._base import ClipboardAction


class LowerCaseAction(ClipboardAction):
    id = "lower_case"
    name = "转小写"
    icon = "case"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        return clipboard_item.content.lower()


ACTION = LowerCaseAction()
