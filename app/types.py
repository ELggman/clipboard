"""轻量数据结构：UI/服务/Action 与 ORM 解耦，不直接依赖数据库模型。"""
from dataclasses import dataclass, field

# 剪贴板内容类型（与 DEVELOPMENT.md §3.1 一致）
TEXT = "text"
URL = "url"
IMAGE = "image"
FILE = "file"
CODE = "code"          # 代码模式：启发式检测置信度 ≥0.80 时标记（§8）

# 临时条目的可选时长（分钟，§9.9）：设置页「临时保存时长」与历史页右键菜单共用，
# 两处给出的选项必须一致——否则同一句「5 分钟」在两边含义不同。
TEMP_MINUTE_OPTIONS = (1, 5, 10, 30)


@dataclass
class ClipboardItem:
    """一条待处理/已解析的剪贴板内容。"""

    type: str = TEXT          # text / url / image / file / code
    content: str = ""         # 文本内容；url 存 URL
    preview: str = ""         # 列表预览文案
    file_path: str = ""       # image/file 的存储路径
    source_app: str = ""      # 来源应用（监听时刻前台应用）
    source_app_id: str = ""   # 来源应用 bundle id（不随系统语言变，§9.5 排除匹配用）
    hash: str = ""            # sha256，去重键
    data: bytes = b""         # 图片原始字节（落库前临时持有）
    created_at: str = ""      # 展示用时间戳（"%m-%d %H:%M"，落库后由 list_recent 填充）
    id: int = 0               # 数据库主键（落库后回填，右键菜单操作需要）
    pinned: int = 0           # 置顶（列表排序优先）
    favorite: int = 0         # 收藏
    # 会话（v4）：所属会话 id 与展示名（_to_item LEFT JOIN 填充）
    session_id: int = 0
    session_name: str = ""
    # Code Mode 元数据（§8.16；text 条目也可能带辅助语言信息，§8.4.3）
    language: str = ""            # 检测语言：python / javascript / ...
    language_confidence: float = 0.0   # 0.0 - 1.0
    line_count: int = 0         # 代码行数
    character_count: int = 0    # 字符数
    is_structured: int = 0      # json/yaml/sql 结构化数据
    # Privacy Mode（§9）
    sensitive: int = 0          # 敏感标记（warn 策略保存后置 1）
    sensitive_type: str = ""    # api_key / token / jwt / private_key / password
    expires_at: str = ""        # 临时条目到期时间（save_temporarily）

    def display_text(self, max_len: int = 100) -> str:
        return self.preview or self.content[:max_len]
