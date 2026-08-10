"""变量 Provider（文档 §33-34/§87）：date/time/datetime/uuid/clipboard/input/cursor。

渲染依赖注入（provider 可替换，测试注入固定 now/clipboard）。
"""
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from .token import Token, TokenType

# 模板格式 → Python strftime（文档 §33-34：YYYY-MM-DD / HH:mm / A 等）
_FORMAT_MAP = [
    # 长 token 先替换（YYYY 优先于 YY）
    ("YYYY", "%Y"), ("YY", "%y"), ("MM", "%m"), ("DD", "%d"),
    ("HH", "%H"), ("hh", "%I"), ("mm", "%M"), ("ss", "%S"),
    ("A", "%p"), ("a", "%P"),
]

_DEFAULT_FORMATS = {
    TokenType.DATE: "%Y-%m-%d",
    TokenType.TIME: "%H:%M",
    TokenType.DATETIME: "%Y-%m-%d %H:%M:%S",
}


def map_format(fmt: str) -> str:
    """模板格式 → strftime：'YYYY年MM月DD日' → '%Y年%m月%d日'。"""
    result = fmt
    for template_fmt, strftime_fmt in _FORMAT_MAP:
        result = result.replace(template_fmt, strftime_fmt)
    return result


@dataclass
class RenderContext:
    """一次渲染的上下文（provider 数据源）。"""

    now: datetime = field(default_factory=datetime.now)
    clipboard_text: str = ""
    input_values: dict[str, str] = field(default_factory=dict)


class VariableProvider(ABC):
    """变量渲染接口：token → 文本片段。"""

    @abstractmethod
    def render(self, token: Token, ctx: RenderContext) -> str:
        raise NotImplementedError


class DateTimeProvider(VariableProvider):
    """{{date}}/{{time}}/{{datetime}}，支持 {{date:YYYY-MM-DD}} 格式（§33-34）。"""

    def __init__(self, token_type: TokenType):
        self._type = token_type

    def render(self, token: Token, ctx: RenderContext) -> str:
        fmt = map_format(token.params or _DEFAULT_FORMATS[self._type])
        return ctx.now.strftime(fmt)


class UUIDProvider(VariableProvider):
    """{{uuid}}：每次渲染生成新 UUID（标准库，§36）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return str(uuid.uuid4())


class ClipboardProvider(VariableProvider):
    """{{clipboard}}：当前系统剪贴板内容（允许为空，§69/§25）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return ctx.clipboard_text


class InputProvider(VariableProvider):
    """{{input:name}}：用户输入值（渲染前已收集，§40-41）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return ctx.input_values.get(token.params, "")


class CursorProvider(VariableProvider):
    """{{cursor}}：不产生文本，由 renderer 记录位置（§37-38）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return ""


def build_providers() -> dict[TokenType, VariableProvider]:
    """第一阶段 provider 注册表（文档 §64）。"""
    return {
        TokenType.DATE: DateTimeProvider(TokenType.DATE),
        TokenType.TIME: DateTimeProvider(TokenType.TIME),
        TokenType.DATETIME: DateTimeProvider(TokenType.DATETIME),
        TokenType.UUID: UUIDProvider(),
        TokenType.CLIPBOARD: ClipboardProvider(),
        TokenType.INPUT: InputProvider(),
        TokenType.CURSOR: CursorProvider(),
    }
