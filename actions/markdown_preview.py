"""Markdown Preview：渲染 Markdown 为 HTML 预览。

TODO: 引入 markdown 渲染库（mistune / markdown-it-py，需在 requirements 增补）
后替换 execute 实现；can_handle 已就绪。
"""
from ._base import ClipboardAction


class MarkdownPreviewAction(ClipboardAction):
    id = "markdown_preview"
    name = "Markdown 预览"
    icon = "markdown"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "text" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        raise NotImplementedError("等待 markdown 渲染库选型（见模块 docstring）")


ACTION = MarkdownPreviewAction()
