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


def test_parse_fills_source_app_identity():
    """解析结果带来源应用身份（显示名 + bundle id），供忽略列表匹配（§9.5）。"""
    pb = _set_text("identity probe")
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    # 前台应用在无窗口的测试环境下可能取不到，但字段必须存在且与取值函数一致
    assert (item.source_app, item.source_app_id) == ClipboardWatcher._frontmost_app()
    assert isinstance(item.source_app, str) and isinstance(item.source_app_id, str)


def test_frontmost_app_returns_pair():
    """(_frontmost_app 返回二元组)：bundle id 不随系统语言变，是匹配的稳定标识。"""
    result = ClipboardWatcher._frontmost_app()
    assert isinstance(result, tuple) and len(result) == 2


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


# ---- 表格复制：细长位图不该当图片存 ----

def _strip_png(w: int = 54, h: int = 8192, rows: int = 5) -> bytes:
    """Excel 整列复制那张位图的形状（尺寸取自实测载荷）。

    实测：Excel 选中一整列复制时，位图 **54×8192**、墨迹只占 0.09%、内容只占
    高度 0.8%（其余是空白 + 网格线）。这里按同样比例造一张。
    """
    from PIL import ImageDraw

    im = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(im)
    for r in range(rows):
        y = 8 + r * 15
        draw.rectangle([6, y, w - 6, y + 9], fill=(40, 40, 40))
    buf = BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _set_png_and_text(data: bytes, text: str | None) -> NSPasteboard:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setData_forType_(data, NSPasteboardTypePNG)
    if text is not None:
        pb.setString_forType_(text, NSPasteboardTypeString)
    return pb


def test_parse_table_strip_stores_text_not_image():
    """回归：Excel 整列复制（细长位图 + TSV 文本）→ 存**文本**，不存那条白条。

    用户实测：复制一列（前几行有数据、后面全空）后，历史里是一条细长白条，
    啥也看不到。根因是位图按整个选区渲染（54×8192），而列表缩略图框高固定
    68px、宽度按原图比例算 → 缩略图只有 **1px 宽**。那张位图里 99.5% 是空白
    + 网格线，真正的内容就是剪贴板上那份 TSV，存文本才是有意义的。
    """
    tsv = "张三\n李四\n王五\n赵六\n钱七"
    pb = _set_png_and_text(_strip_png(), tsv)
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "text", "细长表格位图不该被当成图片存"
    assert item.content == tsv
    assert not item.data, "不该再把位图交给 image_service 落盘"


def test_parse_tall_image_with_single_line_text_keeps_image():
    """浏览器右键「拷贝图像」也是「图片 + 文本」，但那份文本是**单行 URL**。

    这是上一条的护栏：判据若只看「细长」就会把网页上的细长图误判成表格。
    """
    pb = _set_png_and_text(_strip_png(), "https://example.com/banner.png")
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "image"
    assert item.data


def test_parse_tall_image_without_text_keeps_image():
    """没有文本可退时，再细长的位图也照存图片——不能静默丢掉复制内容。"""
    pb = _set_png_and_text(_strip_png(), None)
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "image"
    assert item.data


def test_parse_normal_aspect_image_with_text_keeps_image():
    """普通比例的图片 + 多行文本 → 仍是图片（细长才是表格渲染的特征）。"""
    pb = _set_png_and_text(_png_bytes(), "第一行\n第二行")
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


# ---- Code Mode 解析（新增.md §8）----

def test_parse_code_python():
    pb = _set_text("def hello(name):\n    return f\"Hi {name}\"\n\nprint(hello('x'))")
    item = ClipboardWatcher._parse(pb)
    assert item.type == "code"
    assert item.language == "python"
    assert item.line_count == 4
    assert item.character_count > 0


def test_parse_code_json_structured():
    pb = _set_text('{"name": "Alice", "age": 20}')
    item = ClipboardWatcher._parse(pb)
    assert item.type == "code"
    assert item.language == "json"
    assert item.is_structured == 1


def test_parse_code_shell_single_line():
    """§8.14 单行命令：docker compose up -d → shell。"""
    pb = _set_text("docker compose up -d")
    item = ClipboardWatcher._parse(pb)
    assert item.type == "code"
    assert item.language == "shell"


def test_parse_short_text_not_code():
    pb = _set_text("hi there")
    item = ClipboardWatcher._parse(pb)
    assert item.type == "text"
    assert item.language == ""


def test_parse_text_keeps_auxiliary_language():
    """弱证据：仍是 text，但保留语言辅助字段（§8.4.3）。"""
    pb = _set_text("def a():\n    pass\n\ndef b():\n    pass")
    item = ClipboardWatcher._parse(pb)
    assert item.type == "text"
    assert item.language == "python"


# ---- 暂停监控（§9.3）----

def test_watcher_paused_skips_emit_and_no_burst_on_resume():
    watcher = ClipboardWatcher()
    seen = []
    watcher.changed.connect(seen.append)
    _set_text("paused content")

    watcher.set_paused(True)
    watcher._last_change = 0  # 强制视为变化
    watcher._poll()
    assert seen == []  # 暂停：不解析不 emit

    watcher.set_paused(False)
    watcher._last_change = 0  # 恢复后新变化正常 emit
    watcher._poll()
    assert len(seen) == 1 and seen[0].content == "paused content"

    watcher._poll()  # changeCount 未再变 → 不重复
    assert len(seen) == 1


def test_parse_file_url_chinese_name():
    """file-url 的 percent-encoding 必须解码：中文文件名显示正常（回归）。"""
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(
        "file:///Users/tester/Documents/%E6%96%B0%E5%BB%BA%20%E6%96%87%E6%A1%A3.pdf",
        NSPasteboardTypeFileURL)
    item = ClipboardWatcher._parse(pb)
    assert item is not None
    assert item.type == "file"
    assert item.content == "新建 文档.pdf"  # %E6%96%B0... 已解码
    assert item.file_path == "/Users/tester/Documents/新建 文档.pdf"
