"""模板解析器：模板字符串 → token 流（文档 §63-64/§66-67/§85）。

保存时验证（validate_template）：未知变量、{{input}} 缺 name、
重复 {{cursor}} 都会抛错——不允许静默删除。
"""
import re

from .errors import CursorLimitError, InputError, TemplateError, UnknownVariableError
from .registry import names as known_names
from .token import Token, TokenType

# {{variable:params}} —— 变量名 \w+，可选 :params（params 不含 }）
_VAR_RE = re.compile(r"\{\{(\w+)(?::([^}]*))?\}\}")

# 第一阶段已知变量（唯一事实源 = 变量注册表 registry.names()）
_KNOWN = known_names()


def parse(template: str) -> list[Token]:
    """解析模板为 token 流。失败抛 TemplateError 子类。"""
    # 先收集已声明的 input 变量（§43：{{name}} 可引用 {{input:name}}）
    declared = set(m.group(1) for m in
                   re.finditer(r"\{\{input:([^}:]*)\}\}", template))
    tokens: list[Token] = []
    pos = 0
    cursor_count = 0

    for m in _VAR_RE.finditer(template):
        if m.start() > pos:
            tokens.append(Token(TokenType.TEXT, template[pos:m.start()],
                                position=pos))
        name = m.group(1)
        params = m.group(2) or ""

        if name not in _KNOWN:
            if name in declared:
                # §43：{{name}} 引用已声明的 {{input:name}}——同一变量只问一次
                tokens.append(Token(TokenType.INPUT, params=name,
                                    position=m.start()))
                pos = m.end()
                continue
            raise UnknownVariableError(f"未知变量: {{{{ {name} }}}}", m.start())

        if name == "cursor":
            cursor_count += 1
            if cursor_count > 1:
                raise CursorLimitError(
                    "每个模板最多一个 {{cursor}}", m.start())
            tokens.append(Token(TokenType.CURSOR, position=m.start()))
        elif name == "input":
            if not params:
                raise InputError(
                    "{{input}} 需要 name 参数，如 {{input:name}}", m.start())
            tokens.append(Token(TokenType.INPUT, params=params,
                                position=m.start()))
        elif name == "clipboard":
            tokens.append(Token(TokenType.CLIPBOARD, position=m.start()))
        elif name == "selection":
            tokens.append(Token(TokenType.SELECTION, position=m.start()))
        elif name == "date":
            tokens.append(Token(TokenType.DATE, params=params, position=m.start()))
        elif name == "time":
            tokens.append(Token(TokenType.TIME, params=params, position=m.start()))
        elif name == "datetime":
            tokens.append(Token(TokenType.DATETIME, params=params,
                                position=m.start()))
        elif name == "uuid":
            tokens.append(Token(TokenType.UUID, position=m.start()))

        pos = m.end()

    if pos < len(template):
        tokens.append(Token(TokenType.TEXT, template[pos:], position=pos))

    return tokens


def validate_template(content: str) -> str | None:
    """保存时验证模板内容。返回 None=合法，否则返回用户可读错误消息。

    同时收集需要用户输入的变量名（去重，按出现顺序，文档 §43）。
    """
    try:
        tokens = parse(content)
    except TemplateError as e:
        return str(e)
    return None


def collect_inputs(tokens: list[Token]) -> list[str]:
    """模板中 {{input:name}} 的变量名列表（去重、按首次出现顺序，§43）。"""
    seen: list[str] = []
    for t in tokens:
        if t.type == TokenType.INPUT and t.params not in seen:
            seen.append(t.params)
    return seen
