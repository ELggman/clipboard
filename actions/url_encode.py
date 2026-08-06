"""URL Encode：文本做 URL 百分号编码（保留常见安全字符）。"""
from urllib.parse import quote

from ._base import ClipboardAction


class UrlEncodeAction(ClipboardAction):
    id = "url_encode"
    name = "URL Encode"
    icon = "url"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        return quote(clipboard_item.content, safe=":/?&=#%+@!$'()*,-._~")


ACTION = UrlEncodeAction()
