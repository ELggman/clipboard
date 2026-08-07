"""Save as File：按语言扩展名保存代码为文件（新增.md §8.15）。

默认文件名 untitled.<ext>，用户可修改；仅写盘，不修改剪贴板。
"""
import logging

from ._base import ClipboardAction

logger = logging.getLogger(__name__)


class SaveAsFileAction(ClipboardAction):
    id = "save_as_file"
    name = "保存为文件…"
    icon = "save"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "code" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        from PySide6.QtWidgets import QFileDialog

        from services.code_detector import EXTENSIONS

        ext = EXTENSIONS.get(clipboard_item.language, ".txt")
        path, _ = QFileDialog.getSaveFileName(
            None, "保存为文件", f"untitled{ext}",
            f"代码文件 (*{ext});;所有文件 (*)")
        if not path:
            return None  # 用户取消：不写剪贴板
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(clipboard_item.content)
        except OSError:
            logger.exception("保存代码失败: %s", path)
            return None
        logger.info("代码已保存为文件: %s", path)
        return None


ACTION = SaveAsFileAction()
