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
    selection_text: str = ""
    input_values: dict[str, str] = field(default_factory=dict)
    custom_vars: dict = field(default_factory=dict)  # name → CustomVariable
    # 全局默认日期格式：关键字（date/time/datetime）→ **strftime** 串，来自
    # config `template.date_format` 等（template_service 注入）。留空/缺键 →
    # provider 回落到 _DEFAULT_FORMATS，故不传即旧行为。
    date_formats: dict[str, str] = field(default_factory=dict)
    # 触发时正在编辑的模板原文 / 目标应用名（命令值源的 CW_TEMPLATE/CW_APP）。
    # app_name 必须由**触发瞬间**捕获：picker 流程弹出弹层/对话框后本应用会
    # 夺走前台，此时再读 frontmostApplication() 拿到的是我们自己（见
    # bootstrap._capture_trigger_context 的同源注释）。
    template: str = ""
    app_name: str = ""


class VariableProvider(ABC):
    """变量渲染接口：token → 文本片段。"""

    @abstractmethod
    def render(self, token: Token, ctx: RenderContext) -> str:
        raise NotImplementedError


class DateTimeProvider(VariableProvider):
    """{{date}}/{{time}}/{{datetime}}，支持 {{date:YYYY-MM-DD}} 格式（§33-34）。

    格式取值三级：token 参数（逐次覆盖）> `ctx.date_formats[关键字]`（config
    全局默认）> `_DEFAULT_FORMATS`（内置兜底）。

    config 里的值按 **strftime** 解释（defaults.yaml 里就是 `"%Y-%m-%d"`），
    因此**不过 map_format**——用户的 `%a`/`%p` 不会被「模板格式」规则改写；
    参数形态（`{{date:YYYY年MM月}}`）才走 map_format。
    """

    def __init__(self, token_type: TokenType, keyword: str):
        self._type = token_type
        self._keyword = keyword

    def render(self, token: Token, ctx: RenderContext) -> str:
        if token.params:
            fmt = map_format(token.params)
        else:
            fmt = (ctx.date_formats.get(self._keyword)
                   or _DEFAULT_FORMATS[self._type])
        return ctx.now.strftime(fmt)


class UUIDProvider(VariableProvider):
    """{{uuid}}：每次渲染生成新 UUID（标准库，§36）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return str(uuid.uuid4())


class ClipboardProvider(VariableProvider):
    """{{clipboard}}：当前系统剪贴板内容（允许为空，§69/§25）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return ctx.clipboard_text


class SelectionProvider(VariableProvider):
    """{{selection}}：当前选中文本（允许为空，与 {{clipboard}} 同语义）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return ctx.selection_text


class InputProvider(VariableProvider):
    """{{input:name}}：用户输入值（渲染前已收集，§40-41）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return ctx.input_values.get(token.params, "")


class CursorProvider(VariableProvider):
    """{{cursor}}：不产生文本，由 renderer 记录位置（§37-38）。"""

    def render(self, token: Token, ctx: RenderContext) -> str:
        return ""


class CustomProvider(VariableProvider):
    """{{name}}（自定义变量）：按变量值来源分发到 value_sources provider。

    变量定义从 ctx.custom_vars[token.params] 取（缺省 → 空串），再按
    var.source 查 value_sources 注册表求值。

    token.args（`{{name:参数}}`）原样透传——此前解析期就被丢弃，命令来源
    的脚本因此收不到参数（见 parser.validate_template 的保存期校验）。
    """

    def render(self, token: Token, ctx: RenderContext) -> str:
        from .value_sources import build_value_sources

        var = ctx.custom_vars.get(token.params)
        if var is None:
            return ""
        provider = build_value_sources().get(getattr(var, "source", ""))
        if provider is None:
            return ""
        return provider.render(var.name, var.config, ctx, args=token.args)


def build_providers() -> dict[TokenType, VariableProvider]:
    """provider 注册表（文档 §64）。keyword 与 registry 的解析关键字一致。"""
    return {
        TokenType.DATE: DateTimeProvider(TokenType.DATE, "date"),
        TokenType.TIME: DateTimeProvider(TokenType.TIME, "time"),
        TokenType.DATETIME: DateTimeProvider(TokenType.DATETIME, "datetime"),
        TokenType.UUID: UUIDProvider(),
        TokenType.CLIPBOARD: ClipboardProvider(),
        TokenType.SELECTION: SelectionProvider(),
        TokenType.INPUT: InputProvider(),
        TokenType.CURSOR: CursorProvider(),
        TokenType.CUSTOM: CustomProvider(),
    }
