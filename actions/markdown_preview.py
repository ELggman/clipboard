"""Markdown Preview：渲染 Markdown 为 HTML 预览。

TODO: 引入 markdown 渲染库（mistune / markdown-it-py，需在 requirements 增补）
后实现。当前 can_handle 恒 False：未就绪的 Action 从右键菜单隐藏，
避免点了报 NotImplementedError（这是插件接口的约定——不出现好过报错）。
"""
from ._base import ClipboardAction


class MarkdownPreviewAction(ClipboardAction):
    id = "markdown_preview"
    name = "Markdown 预览"
    icon = "markdown"

    def can_handle(self, clipboard_item) -> bool:
        return False  # 待渲染库选型后实现（见模块 docstring）

    def execute(self, clipboard_item) -> str | None:
        raise NotImplementedError("等待 markdown 渲染库选型（见模块 docstring）")


ACTION = MarkdownPreviewAction()
