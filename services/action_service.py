"""Action 服务：加载插件、筛选可用 Action、执行并写回剪贴板。

写回用 NSPasteboard 直接设置，避免 pyperclip 的子进程开销；
主程序只依赖本服务，不 import 任何具体 Action 实现（插件化约束）。
"""
import logging
from pathlib import Path

from AppKit import NSPasteboard, NSPasteboardTypeString

from actions import load_actions
from actions._base import ClipboardAction

logger = logging.getLogger(__name__)


def set_clipboard_text(text: str) -> None:
    """将文本写入系统剪贴板。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


class ActionService:
    def __init__(self, extra_dirs: tuple[Path, ...] = ()):
        # extra_dirs：用户插件目录（V3 开放扩展，见 DEVELOPMENT.md §10）
        self._actions: list[ClipboardAction] = load_actions(*extra_dirs)

    def actions_for(self, clipboard_item) -> list[ClipboardAction]:
        """返回可处理该剪贴板项的 Action 列表（右键菜单用）。"""
        return [a for a in self._actions if a.can_handle(clipboard_item)]

    def run(self, action: ClipboardAction, clipboard_item) -> bool:
        """执行 Action，结果写回剪贴板。返回是否成功。"""
        try:
            result = action.execute(clipboard_item)
        except NotImplementedError:
            logger.warning("Action %s 尚未实现", action.id)
            return False
        except Exception:
            logger.exception("Action %s 执行失败", action.id)
            return False
        if result is not None:
            set_clipboard_text(result)
            logger.info("Action %s 完成", action.id)
        return True
