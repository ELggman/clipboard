"""Detect Language：重新运行代码检测，结果写回剪贴板（新增.md §8.9）。"""
from ._base import ClipboardAction


class DetectLanguageAction(ClipboardAction):
    id = "detect_language"
    name = "检测语言"
    icon = "lang"

    def can_handle(self, clipboard_item) -> bool:
        return clipboard_item.type == "code" and bool(clipboard_item.content)

    def execute(self, clipboard_item) -> str | None:
        from services.code_detector import LANGUAGE_NAMES, detect

        result = detect(clipboard_item.content)
        if result is None:
            return "未检测到语言"
        name = LANGUAGE_NAMES.get(result.language, result.language)
        return f"{name} ({result.confidence:.2f})"


ACTION = DetectLanguageAction()
