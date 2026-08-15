"""模板 token 模型（文档 §63-64）。"""

from dataclasses import dataclass, field
from enum import Enum, auto


class TokenType(Enum):
    TEXT = auto()
    DATE = auto()
    TIME = auto()
    DATETIME = auto()
    UUID = auto()
    CLIPBOARD = auto()
    SELECTION = auto()
    CURSOR = auto()
    INPUT = auto()


@dataclass
class Token:
    type: TokenType
    value: str = ""                # TEXT 的文本内容
    params: str = ""               # INPUT 的 name / DATE 等的格式
    position: int = 0              # 在原模板中的起始位置（错误定位）
    _extra: dict = field(default_factory=dict, repr=False)
