"""Minify JSON：压缩 JSON 文本（新增.md §8.12.2）。"""
import json

from ._base import ClipboardAction


def _is_json(content: str) -> bool:
    try:
        json.loads(content)
    except (ValueError, TypeError):
        return False
    return True


class JsonMinifyAction(ClipboardAction):
    id = "json_minify"
    name = "JSON 压缩"
    icon = "json"

    def can_handle(self, clipboard_item) -> bool:
        # JSON 现在分类为 type=code（language=json）；兼容 v3 前的 text
        return clipboard_item.type in ("text", "code") and _is_json(
            clipboard_item.content or "")

    def execute(self, clipboard_item) -> str | None:
        return json.dumps(
            json.loads(clipboard_item.content), separators=(",", ":"),
            ensure_ascii=False,
        )


ACTION = JsonMinifyAction()
