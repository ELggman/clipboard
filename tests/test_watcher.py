"""剪贴板监听解析测试（使用真实系统剪贴板 —— 注意会改写用户剪贴板）。

覆盖 16:56 修复的回归点：pasteboard 类型常量必须用 AppKit 模块级导出
（pyobjc 12.x 中 NSPasteboard.NSPasteboardTypeString 类属性访问为 None）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from io import BytesIO

from PIL import Image
from AppKit import NSPasteboard, NSPasteboardTypeFileURL, NSPasteboardTypePNG, NSPasteboardTypeString

from services.clipboard_watcher import ClipboardWatcher


def _set_text(text: str) -> NSPasteboard:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSPasteboardTypeString)
    return pb


def test_parse_text():
    pb = _set_text("hello clipboard smoke")
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "text"
    assert item.content == "hello clipboard smoke"
    assert len(item.hash) == 64


def test_parse_url_heuristic():
    pb = _set_text("https://github.com")
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "url"
    assert item.content == "https://github.com"


def test_parse_file_url():
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_("file:///tmp/note.txt", NSPasteboardTypeFileURL)
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "file"
    assert item.file_path == "/tmp/note.txt"
    assert item.content == "note.txt"


def test_parse_blank_ignored():
    pb = _set_text("   ")
    assert ClipboardWatcher._parse(pb) is None


def _png_bytes(color: str = "red") -> bytes:
    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, "PNG")
    return buf.getvalue()


def test_parse_image_with_file_url_prefers_image():
    """应用内复制图片（截图等）同时带 file-url 与图片数据 → 应判为 image。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setData_forType_(_png_bytes(), NSPasteboardTypePNG)
    pb.setString_forType_("file:///tmp/shot.png", NSPasteboardTypeFileURL)
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "image"
    assert item.data  # 原始字节交给 image_service 落盘


def test_parse_image_only_data():
    """纯截图复制（无 file-url）→ image。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setData_forType_(_png_bytes("blue"), NSPasteboardTypePNG)
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "image"


def test_parse_priority_url_over_text():
    """同时存在 URL 与普通文本时（部分应用会双写），URL 优先。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_("https://example.com/a", NSPasteboardTypeString)
    pb.setString_forType_("https://example.com/a", "public.url")
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "url"
