"""Action 插件统一接口。

任何新功能（AI 总结、OCR、SQL 格式化、JSON 校验……）都是一个实现
ClipboardAction 的插件文件，放在 actions/ 或用户插件目录，
主程序无需修改 —— 这是整个项目最值得投入的设计（DEVELOPMENT.md §3.3）。
"""
from abc import ABC, abstractmethod


class ClipboardAction(ABC):
    """统一 Action 接口。"""

    id: str = ""
    name: str = ""
    icon: str = ""

    @abstractmethod
    def can_handle(self, clipboard_item) -> bool:
        """判断是否处理该剪贴板项（AppKit.ClipboardItem）。"""

    @abstractmethod
    def execute(self, clipboard_item) -> str | None:
        """执行并返回新文本；返回 None 表示不改写剪贴板。

        execute 只负责计算，不直接操作剪贴板 —— 写回由
        services/action_service.py 统一完成，保证可测试。
        """
