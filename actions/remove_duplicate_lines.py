"""Remove Duplicate Lines（去重行）：按内容去重并保持首次出现顺序。

语义：
- 保留行结构（尾部换行、空行全部保留，空行不参与去重）
- 内容比较忽略行首尾空白（" a " 与 "a" 视为重复），保留第一次出现的原始行
"""
from ._base import ClipboardAction
from ._line_utils import join_lines, split_keepends


class RemoveDuplicateLinesAction(ClipboardAction):
    id = "remove_duplicate_lines"
    name = "去重行"
    icon = "dedupe"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and "\n" in clipboard_item.content

    def execute(self, clipboard_item) -> str | None:
        seen: set[str] = set()
        out: list[str] = []
        for line in split_keepends(clipboard_item.content):
            key = line.rstrip("\r\n").strip()
            if not key:  # 空行保留（分隔符），不参与去重
                out.append(line)
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(line)
        return join_lines(out)


ACTION = RemoveDuplicateLinesAction()
