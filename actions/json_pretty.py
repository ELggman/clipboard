"""JSON Pretty：格式化 JSON 文本。"""
import json

from .base import ClipboardAction


class JsonPrettyAction(ClipboardAction):
    id = "json_pretty"
    name = "JSON Pretty"
    icon = "json"

    def can_handle(self, clipboard_item) -> bool:
        if clipboard_item.type != "text":
            return False
        try:
            json.loads(clipboard_item.content)
        except (ValueError, TypeError):
            return False
        return True

    def execute(self, clipboard_item) -> str | None:
        return json.dumps(
            json.loads(clipboard_item.content), indent=2, ensure_ascii=False
        )


ACTION = JsonPrettyAction()
