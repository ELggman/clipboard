"""URL Decode：百分号编码解码为原文。"""
from urllib.parse import unquote

from ._base import ClipboardAction


class UrlDecodeAction(ClipboardAction):
    id = "url_decode"
    name = "URL Decode"
    icon = "url"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        return unquote(clipboard_item.content)


ACTION = UrlDecodeAction()
