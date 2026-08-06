"""Remove Duplicate Lines：去重并保持首次出现顺序。"""
from ._base import ClipboardAction


class RemoveDuplicateLinesAction(ClipboardAction):
    id = "remove_duplicate_lines"
    name = "去重行"
    icon = "dedupe"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and "\n" in clipboard_item.content

    def execute(self, clipboard_item) -> str | None:
        seen: set[str] = set()
        unique = [line for line in clipboard_item.content.splitlines()
                  if not (line in seen or seen.add(line))]
        return "\n".join(unique)


ACTION = RemoveDuplicateLinesAction()
