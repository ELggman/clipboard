"""Action 服务：加载插件、筛选可用 Action、执行并写回剪贴板。

写回用 NSPasteboard 直接设置，避免 pyperclip 的子进程开销；
主程序只依赖本服务，不 import 任何具体 Action 实现（插件化约束）。
本模块同时是剪贴板写入工具（Quick Paste / Action 回写共用）。
"""
import logging
from pathlib import Path

from AppKit import (
    NSPasteboard,
    NSPasteboardTypeFileURL,
    NSPasteboardTypePNG,
    NSPasteboardTypeString,
)

from actions import load_actions
from actions._base import ClipboardAction

logger = logging.getLogger(__name__)


def set_clipboard_text(text: str) -> None:
    """将文本写入系统剪贴板。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)


def set_clipboard_item(item) -> bool:
    """按类型把剪贴板项重新写回系统剪贴板（Quick Paste / 点击复制共用）。

    图片读回 PNG 字节；文件写 file-url + 文件路径（支持多类型粘贴）。
    返回是否成功。
    """
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    try:
        if item.type in ("text", "url", "code") and item.content:
            pb.setString_forType_(item.content, NSPasteboardTypeString)
        elif item.type == "image" and item.file_path:
            data = Path(item.file_path).read_bytes()
            pb.setData_forType_(data, NSPasteboardTypePNG)
            pb.setString_forType_(item.preview or item.file_path, NSPasteboardTypeString)
        elif item.type == "file" and item.file_path:
            pb.setString_forType_(Path(item.file_path).as_uri(), NSPasteboardTypeFileURL)
            pb.setPropertyList_forType_([item.file_path], "NSFilenamesPboardType")
        else:
            return False
        return True
    except OSError:
        logger.exception("剪贴板写入失败: %s", item.file_path or item.content)
        return False


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
