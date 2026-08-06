"""Base64 Decode：Base64 解码为文本。

支持多行 Base64（MIME 格式含换行/空白）：校验与解码前先剥离空白。
"""
import base64
import re

from ._base import ClipboardAction


class Base64DecodeAction(ClipboardAction):
    id = "base64_decode"
    name = "Base64 解码"
    icon = "base64"

    def can_handle(self, clipboard_item) -> bool:
        if clipboard_item.type != "text" or not clipboard_item.content:
            return False
        try:
            base64.b64decode(self._strip_ws(clipboard_item.content).encode("ascii"),
                             validate=True)
        except Exception:
            return False
        return True

    def execute(self, clipboard_item) -> str | None:
        compact = self._strip_ws(clipboard_item.content)
        raw = base64.b64decode(compact.encode("ascii"))
        return raw.decode("utf-8", errors="replace")

    @staticmethod
    def _strip_ws(text: str) -> str:
        """剥离 Base64 中的换行/空白（MIME 多行格式）。"""
        return re.sub(r"\s+", "", text)


ACTION = Base64DecodeAction()
