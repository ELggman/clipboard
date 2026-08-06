"""Base64 Encode：文本编码为 Base64。"""
import base64

from ._base import ClipboardAction


class Base64EncodeAction(ClipboardAction):
    id = "base64_encode"
    name = "Base64 编码"
    icon = "base64"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        return base64.b64encode(clipboard_item.content.encode("utf-8")).decode("ascii")


ACTION = Base64EncodeAction()
