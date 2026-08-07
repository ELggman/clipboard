"""JSON Pretty：格式化 JSON 文本。"""
import json

from ._base import ClipboardAction


class JsonPrettyAction(ClipboardAction):
    id = "json_pretty"
    name = "JSON 格式化"
    icon = "json"

    def can_handle(self, clipboard_item) -> bool:
        # JSON 现在分类为 type=code（language=json）；兼容 v3 前的 text
        if clipboard_item.type not in ("text", "code"):
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
