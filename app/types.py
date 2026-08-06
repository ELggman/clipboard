"""轻量数据结构：UI/服务/Action 与 ORM 解耦，不直接依赖数据库模型。"""
from dataclasses import dataclass, field

# 剪贴板内容类型（与 DEVELOPMENT.md §3.1 一致）
TEXT = "text"
URL = "url"
IMAGE = "image"
FILE = "file"


@dataclass
class ClipboardItem:
    """一条待处理/已解析的剪贴板内容。"""

    type: str = TEXT          # text / url / image / file
    content: str = ""         # 文本内容；url 存 URL
    preview: str = ""         # 列表预览文案
    file_path: str = ""       # image/file 的存储路径
    source_app: str = ""      # 来源应用（监听时刻前台应用）
    hash: str = ""            # sha256，去重键
    data: bytes = b""         # 图片原始字节（落库前临时持有）

    def display_text(self, max_len: int = 100) -> str:
        return self.preview or self.content[:max_len]
