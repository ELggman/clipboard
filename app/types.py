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
    created_at: str = ""      # 展示用时间戳（"%m-%d %H:%M"，落库后由 list_recent 填充）
    id: int = 0               # 数据库主键（落库后回填，右键菜单操作需要）
    pinned: int = 0           # 置顶（列表排序优先）
    favorite: int = 0         # 收藏

    def display_text(self, max_len: int = 100) -> str:
        return self.preview or self.content[:max_len]
