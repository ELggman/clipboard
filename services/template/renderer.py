"""模板渲染器：token 流 → 最终文本 + 光标位置（文档 §65/§86）。

render() 返回 (text, cursor_pos|None)：{{cursor}} 不产文本、
记录渲染文本中的位置（§118）。
"""
from .token import Token, TokenType
from .variables import RenderContext, build_providers


def render(
    tokens: list[Token],
    ctx: RenderContext | None = None,
    providers: dict[TokenType, object] | None = None,
) -> tuple[str, int | None]:
    """渲染 token 流。返回 (最终文本, 光标位置或 None)。"""
    ctx = ctx or RenderContext()
    providers = providers or build_providers()
    parts: list[str] = []
    cursor_pos: int | None = None

    for token in tokens:
        if token.type == TokenType.TEXT:
            parts.append(token.value)
        elif token.type == TokenType.CURSOR:
            cursor_pos = len("".join(parts))
        else:
            provider = providers.get(token.type)
            if provider is not None:
                parts.append(provider.render(token, ctx))

    return "".join(parts), cursor_pos
