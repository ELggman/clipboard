"""Base64 Decode：Base64 解码为文本。"""
import base64

from ._base import ClipboardAction


class Base64DecodeAction(ClipboardAction):
    id = "base64_decode"
    name = "Base64 Decode"
    icon = "base64"

    def can_handle(self, clipboard_item) -> bool:
        if clipboard_item.type != "text" or not clipboard_item.content:
            return False
        try:
            base64.b64decode(clipboard_item.content.encode("ascii"), validate=True)
        except Exception:
            return False
        return True

    def execute(self, clipboard_item) -> str | None:
        raw = base64.b64decode(clipboard_item.content.encode("ascii"))
        return raw.decode("utf-8", errors="replace")


ACTION = Base64DecodeAction()
