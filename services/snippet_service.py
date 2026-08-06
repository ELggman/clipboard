"""Snippet 变量渲染：{{date}} {{time}} {{uuid}}（DEVELOPMENT.md §7.3）。

复制时渲染成最终文本；未知变量原样保留。
"""
import datetime
import logging
import re
import uuid

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def render_snippet(
    content: str,
    *,
    date_fmt: str = "%Y-%m-%d",
    time_fmt: str = "%H:%M:%S",
    now: datetime.datetime | None = None,
) -> str:
    """渲染 Snippet 变量。now 参数便于测试固定时间。"""
    now = now or datetime.datetime.now()

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name == "date":
            return now.strftime(date_fmt)
        if name == "time":
            return now.strftime(time_fmt)
        if name == "uuid":
            return str(uuid.uuid4())
        return match.group(0)  # 未知变量原样保留

    return _VAR_RE.sub(_replace, content)
