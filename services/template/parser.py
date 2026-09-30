"""模板解析器：模板字符串 → token 流（文档 §63-64/§66-67/§85）。

保存时验证（validate_template）：未知变量、{{input}} 缺 name、
重复 {{cursor}} 都会抛错——不允许静默删除。

自定义变量（registry.CustomVariable）不在内置关键字集里，靠调用方传入
custom_names 参与解析：`{{name}}` 命中自定义变量 → TokenType.CUSTOM
（由值源决定取值），否则 UnknownVariableError。§43 旧配对（{{name}}
引用 {{input:name}}）已移除——两者彻底解耦。
"""
import re
from dataclasses import dataclass

from .errors import CursorLimitError, InputError, TemplateError, UnknownVariableError
from .registry import SOURCE_COMMAND, SOURCE_INPUT, SOURCE_LABELS
from .registry import names as known_names
from .token import Token, TokenType

# {{variable:params}} —— 变量名 \w+，可选 :params（params 不含 }）
_VAR_RE = re.compile(r"\{\{(\w+)(?::([^}]*))?\}\}")

# 内置变量关键字集合（唯一事实源 = 变量注册表 registry.names()）
_KNOWN = known_names()


@dataclass(frozen=True)
class InputRequest:
    """渲染前需收集的一次输入：name 是 value key，token 是展示/替换文本。"""

    name: str
    token: str


def parse(template: str, custom_names: set[str] | None = None) -> list[Token]:
    """解析模板为 token 流。失败抛 TemplateError 子类。

    custom_names：当前已定义的自定义变量名集合（不含 `{{}}`）；命中即
    TokenType.CUSTOM，否则视为未知变量报错。
    """
    custom_names = custom_names or set()
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
            if name in custom_names:
                # params 存**变量名**（查表键），args 存 `:后面那串`原文。
                # 此前 params 只放 name、`:args` 直接丢弃——`{{weather:北京}}`
                # 静默变成 `{{weather}}`（见 validate_template 的保存期校验）。
                tokens.append(Token(TokenType.CUSTOM, params=name, args=params,
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


def validate_args(tokens: list[Token],
                  custom_vars: dict | None = None) -> str | None:
    """参数用法校验：`{{name:参数}}` 只对 command 来源有意义。

    custom_vars：name → CustomVariable。未知变量已由 parse 拦下，这里只管
    「参数会不会生效」——其余来源（input/fixed/state）无处可用，此前一律
    静默丢弃，用户写了 `{{邮件:张三}}` 却什么也没发生。
    """
    if not custom_vars:
        return None
    for t in tokens:
        if t.type != TokenType.CUSTOM or not t.args.strip():
            continue
        var = custom_vars.get(t.params)
        source = var.source if var is not None else ""
        if source != SOURCE_COMMAND:
            label = SOURCE_LABELS.get(source, source or "未知")
            return (f"变量「{t.params}」的值来源是「{label}」，"
                    f"不接受参数（`:{t.args}` 不会生效）——"
                    f"参数只用于外部命令来源的脚本")
    return None


def validate_template(content: str, custom_names: set[str] | None = None,
                      custom_vars: dict | None = None) -> str | None:
    """保存时验证模板内容。返回 None=合法，否则返回用户可读错误消息。

    只返回**消息**（不带异常类型），适合「保存时提示」；需要在解析失败时
    保留具体异常类型（UnknownVariableError 等）的调用方，改用
    `parse` + `validate_args`。
    """
    try:
        tokens = parse(content, custom_names=custom_names)
    except TemplateError as e:
        return str(e)
    return validate_args(tokens, custom_vars)


def collect_inputs(tokens: list[Token], custom_vars: dict | None = None) -> list[InputRequest]:
    """渲染前需用户输入的变量（去重、按首次出现顺序）。

    - {{input:name}} → 临时输入
    - {{name}}（自定义变量且 source=input）→ 用户输入来源
    其余自定义变量（fixed/command/state）无需询问，不出现在结果里。

    ⚠️ name 作为去重键：模板里同名 `{{name}}` 与 `{{input:name}}` 共用
    一次询问（边界情况，§变量-值源 已文档化）。
    """
    custom_vars = custom_vars or {}
    seen: list[str] = []
    out: list[InputRequest] = []
    for t in tokens:
        if t.type == TokenType.INPUT:
            name = t.params
            if name not in seen:
                seen.append(name)
                out.append(InputRequest(name, f"{{{{input:{name}}}}}"))
        elif t.type == TokenType.CUSTOM:
            var = custom_vars.get(t.params)
            if var is not None and getattr(var, "source", SOURCE_INPUT) == SOURCE_INPUT:
                name = t.params
                if name not in seen:
                    seen.append(name)
                    out.append(InputRequest(name, f"{{{{{name}}}}}"))
    return out
