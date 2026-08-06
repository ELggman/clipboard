"""行操作工具：拆分/合并时保留行结构（含尾部换行、空行）。

⚠️ 不要用 text.splitlines() 再 "\n".join()——会丢失尾部换行
（"a\\nb\\n" → "a\\nb"），多行代码复制场景用户能明显感知。
统一用 splitlines(keepends=True) + "".join()。
"""


def split_keepends(text: str) -> list[str]:
    """按行拆分并保留换行符（含末尾换行与空行）。"""
    return text.splitlines(keepends=True)


def join_lines(lines: list[str]) -> str:
    """把带换行符的行列表还原为原文本（结构与拆分前一致）。"""
    return "".join(lines)
