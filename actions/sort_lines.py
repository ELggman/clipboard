"""Sort Lines（行排序）：按行内容排序。

语义：
- 保留行结构（尾部换行不丢失）
- 空行沉底（空行是分隔符不是内容，排到末尾）
- 忽略大小写排序
"""
from ._base import ClipboardAction
from ._line_utils import join_lines, split_keepends


class SortLinesAction(ClipboardAction):
    id = "sort_lines"
    name = "行排序"
    icon = "sort"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and "\n" in clipboard_item.content

    def execute(self, clipboard_item) -> str | None:
        lines = split_keepends(clipboard_item.content)
        blanks = [line for line in lines if not line.strip()]
        content_lines = [line for line in lines if line.strip()]
        content_lines.sort(key=lambda line: line.rstrip("\r\n").casefold())
        return join_lines(content_lines + blanks)


ACTION = SortLinesAction()
