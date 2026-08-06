"""剪贴板写入测试（真实系统剪贴板，注意会改写用户剪贴板）。

覆盖 Quick Paste 重新复制路径：text / url / image / file 四类回写。
"""
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image
from AppKit import NSPasteboard, NSPasteboardTypeFileURL, NSPasteboardTypePNG, NSPasteboardTypeString

from app.types import ClipboardItem
from services.action_service import set_clipboard_item


def test_set_text_roundtrip():
    item = ClipboardItem(type="text", content="hello quick paste")
    assert set_clipboard_item(item) is True
    pb = NSPasteboard.generalPasteboard()
    assert pb.stringForType_(NSPasteboardTypeString) == "hello quick paste"


def test_set_url_roundtrip():
    item = ClipboardItem(type="url", content="https://example.com")
    assert set_clipboard_item(item) is True
    pb = NSPasteboard.generalPasteboard()
    assert pb.stringForType_(NSPasteboardTypeString) == "https://example.com"


def test_set_image_roundtrip(tmp_path):
    buf = BytesIO()
    Image.new("RGB", (8, 8), "red").save(buf, "PNG")
    img_path = tmp_path / "pic.png"
    img_path.write_bytes(buf.getvalue())

    item = ClipboardItem(type="image", file_path=str(img_path), preview="pic.png")
    assert set_clipboard_item(item) is True
    pb = NSPasteboard.generalPasteboard()
    data = pb.dataForType_(NSPasteboardTypePNG)
    assert data is not None and len(bytes(data)) > 0


def test_set_file_roundtrip(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("content")
    item = ClipboardItem(type="file", file_path=str(f))
    assert set_clipboard_item(item) is True
    pb = NSPasteboard.generalPasteboard()
    uri = pb.stringForType_(NSPasteboardTypeFileURL)
    assert uri == f.as_uri()


def test_set_unsupported_returns_false():
    item = ClipboardItem(type="image")  # 无 file_path
    assert set_clipboard_item(item) is False
