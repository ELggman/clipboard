"""模板引擎（原「片段」，文档 §63-68/§83-89）：解析 → 渲染 → 匹配。

分层：
- errors.py     模板错误类型
- token.py      Token 数据类
- parser.py     模板 → token 流（保存时验证）
- variables.py  变量 Provider（Date/Time/UUID/Clipboard/Input/Cursor）
- renderer.py   token 流 → 最终文本 + 光标位置
- matcher.py    输入缓冲 → shortcut 匹配（Tab Trigger）
"""
from .errors import (
    CursorLimitError,
    InputError,
    RenderError,
    TemplateError,
    UnknownVariableError,
)
from .parser import parse, validate_template
from .renderer import render
from .token import Token, TokenType

__all__ = [
    "CursorLimitError",
    "InputError",
    "RenderError",
    "TemplateError",
    "Token",
    "TokenType",
    "UnknownVariableError",
    "parse",
    "render",
    "validate_template",
]
