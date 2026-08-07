"""Copy Without Formatting：复制纯文本（新增.md §8.8）。

Markdown 剥离语法标记；其它代码原样复制（无富文本格式可去）。
"""
from ._base import ClipboardAction


class CopyWithoutFormattingAction(ClipboardAction):
    id = "copy_without_formatting"
    name = "复制纯文本"
    icon = "copy"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "code" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        if clipboard_item.language == "markdown":
            from app.text_utils import strip_markdown

            return strip_markdown(clipboard_item.content)
        return clipboard_item.content


ACTION = CopyWithoutFormattingAction()
