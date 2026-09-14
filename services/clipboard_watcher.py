"""剪贴板监听：NSPasteboard changeCount 轮询。

选型依据（DEVELOPMENT.md §3.1）：
- 进程内 API、无 TCC 权限需求（pasteboard 不受 TCC 保护）
- 不用 pyperclip 轮询（其走 pbpaste/pbcopy 子进程，不适合常驻）
解析顺序与需求一致：File → Image → URL → Text。
"""
import hashlib
import logging
from pathlib import Path
from urllib.parse import unquote, urlparse

# 注意：pasteboard 类型常量是 AppKit 模块级导出，不是 NSPasteboard 类属性
# （pyobjc 12.x 实测类属性访问为 None，会导致每次轮询 AttributeError）
from AppKit import (
    NSPasteboard,
    NSPasteboardTypeFileURL,
    NSPasteboardTypePNG,
    NSPasteboardTypeString,
    NSPasteboardTypeTIFF,
    NSPasteboardTypeURL,
    NSWorkspace,
)
from PySide6.QtCore import QObject, QTimer, Signal

from app.types import CODE, FILE, IMAGE, TEXT, URL, ClipboardItem

logger = logging.getLogger(__name__)


class ClipboardWatcher(QObject):
    """轮询剪贴板变化，解析类型后发出 changed 信号（携带 ClipboardItem，未入库）。"""

    changed = Signal(object)  # ClipboardItem

    def __init__(self, poll_interval: float = 0.2, parent: QObject | None = None):
        super().__init__(parent)
        self._last_change = NSPasteboard.generalPasteboard().changeCount()
        self._paused = False          # 隐私模式：暂停保存（§9.3）
        self._timer = QTimer(self)
        self._timer.setInterval(int(poll_interval * 1000))
        self._timer.timeout.connect(self._poll)

    def start(self) -> None:
        self._timer.start()
        logger.info("剪贴板监听启动（轮询 %.1fs）", self._timer.interval() / 1000)

    def stop(self) -> None:
        self._timer.stop()

    def set_paused(self, paused: bool) -> None:
        """暂停/恢复监听。暂停期间仍记录 changeCount（恢复时不爆发补抓）。"""
        self._paused = paused
        logger.info("剪贴板监听已%s", "暂停" if paused else "恢复")

    # ---- 内部 ----

    def _poll(self) -> None:
        pb = NSPasteboard.generalPasteboard()
        change = pb.changeCount()
        if change == self._last_change:
            return
        self._last_change = change
        if self._paused:
            logger.debug("剪贴板变化但监听已暂停，忽略")
            return
        item = self._parse(pb)
        if item is None:
            logger.debug("剪贴板变化，但无可解析内容")
            return
        logger.info("剪贴板变化: type=%s hash=%s", item.type, item.hash[:12])
        self.changed.emit(item)

    @staticmethod
    def _parse(pb: NSPasteboard) -> ClipboardItem | None:
        """解析剪贴板内容，并补上「来源应用」身份（§9.5 排除匹配用）。"""
        item = ClipboardWatcher._parse_payload(pb)
        if item is not None:
            (item.source_app,
             item.source_app_id) = ClipboardWatcher._frontmost_app()
        return item

    @staticmethod
    def _parse_payload(pb: NSPasteboard) -> ClipboardItem | None:
        """按类型解析（图片 → 文件 → URL → 文本/代码）；来源应用由 `_parse` 补。"""

        # 1) Image：PNG 优先，TIFF 兜底。
        #    必须放在 File 之前：应用内复制图片（截图/VS Code/Safari）时
        #    剪贴板常同时带 file-url 与图片数据，用户意图是图片内容
        #    → 存 images/；仅 file-url（无图片数据）才是文件复制。
        data = pb.dataForType_(NSPasteboardTypePNG)
        if data is None:
            data = pb.dataForType_(NSPasteboardTypeTIFF)
        if data is not None:
            return ClipboardItem(
                type=IMAGE,
                data=bytes(data),
                hash=ClipboardWatcher._digest(bytes(data)),
            )

        # 2) File：public.file-url 可能返回单个字符串或数组，兼容两者
        raw = pb.propertyListForType_(NSPasteboardTypeFileURL)
        urls = raw if isinstance(raw, list) else ([raw] if raw else [])
        if urls:
            # unquote：file-url 的路径是 percent-encoded（中文名显示为
            # %E6%96%B0...，实测复制中文名文档 UI 显示乱码）
            path = Path(unquote(urlparse(urls[0]).path))
            return ClipboardItem(
                type=FILE,
                content=path.name,
                file_path=str(path),
                hash=ClipboardWatcher._digest(str(path)),
            )

        # 3) URL / Text
        url = pb.stringForType_(NSPasteboardTypeURL)
        if url:
            return ClipboardItem(
                type=URL, content=url,
                hash=ClipboardWatcher._digest(url),
            )
        text = pb.stringForType_(NSPasteboardTypeString)
        if text is None or not text.strip():
            return None
        # 简化启发式：http(s) 开头视为 URL（完整判断可后续加强）
        if text.startswith(("http://", "https://")):
            return ClipboardItem(
                type=URL, content=text,
                hash=ClipboardWatcher._digest(text),
            )
        # Code Mode（§8）：启发式检测，置信度 >= 0.80 → type=code；
        # 否则保留语言作为辅助信息（§8.4.3）
        from services.code_detector import CODE_THRESHOLD, detect as detect_code

        result = detect_code(text)
        if result is not None and result.confidence >= CODE_THRESHOLD:
            return ClipboardItem(
                type=CODE, content=text,
                hash=ClipboardWatcher._digest(text),
                language=result.language,
                language_confidence=result.confidence,
                line_count=len(text.splitlines()),
                character_count=len(text),
                is_structured=1 if result.is_structured else 0,
            )
        return ClipboardItem(
            type=TEXT, content=text,
            hash=ClipboardWatcher._digest(text),
            language=result.language if result else "",
            language_confidence=result.confidence if result else 0.0,
        )

    @staticmethod
    def _frontmost_app() -> tuple[str, str]:
        """监听时刻的前台应用 (显示名, bundle id)，即复制动作的发起者；无需额外权限。

        两个都取：显示名用于界面展示，bundle id 用于忽略列表匹配——`localizedName()`
        随系统语言变（中文系统下微信是「微信」，英文系统是 "WeChat"），只存名字的话
        用户排除过的应用换个语言就漏记了（§9.5）。
        """
        try:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            return app.localizedName() or "", app.bundleIdentifier() or ""
        except Exception:
            logger.exception("获取前台应用失败")
            return "", ""

    @staticmethod
    def _digest(payload: str | bytes) -> str:
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
