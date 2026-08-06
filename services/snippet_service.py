"""Snippet 服务：CRUD + 变量渲染（DEVELOPMENT.md §4.5 / §7.3）。

复制时渲染 {{date}} {{time}} {{uuid}} 为最终文本；未知变量原样保留。
"""
import datetime
import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.engine import Engine

from database.engine import make_session_factory
from database.models import Snippet

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")

# 可用变量提示（页面展示用）
AVAILABLE_VARS = ("{{date}}", "{{time}}", "{{uuid}}")


# ---- CRUD ----

def list_snippets(engine: Engine) -> list[dict]:
    """全部片段（最新创建在前）。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(Snippet).order_by(Snippet.created_at.desc(), Snippet.id.desc())
        ).scalars().all()
    return [
        {"id": r.id, "name": r.name, "content": r.content,
         "description": r.description or ""}
        for r in rows
    ]


def create_snippet(engine: Engine, name: str, content: str,
                   description: str = "") -> int:
    with make_session_factory(engine)() as session:
        row = Snippet(name=name, content=content, description=description,
                      created_at=datetime.datetime.now())
        session.add(row)
        session.commit()
        return row.id


def update_snippet(engine: Engine, snippet_id: int, name: str, content: str,
                   description: str = "") -> bool:
    with make_session_factory(engine)() as session:
        row = session.get(Snippet, snippet_id)
        if row is None:
            return False
        row.name, row.content, row.description = name, content, description
        session.commit()
        return True


def delete_snippet(engine: Engine, snippet_id: int) -> bool:
    with make_session_factory(engine)() as session:
        row = session.get(Snippet, snippet_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


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
