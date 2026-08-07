"""Validate JSON：校验 JSON 合法性，结果写回剪贴板（新增.md §8.12.3）。"""
import json

from ._base import ClipboardAction
from .json_minify import _is_json


class JsonValidateAction(ClipboardAction):
    id = "json_validate"
    name = "JSON 校验"
    icon = "json"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type in ("text", "code") and bool(
            clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        content = clipboard_item.content
        try:
            json.loads(content)
            return "✓ Valid JSON"
        except (ValueError, TypeError) as exc:
            return f"✗ Invalid JSON: {exc}"


ACTION = JsonValidateAction()
