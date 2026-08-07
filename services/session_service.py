"""会话服务：任务型内容分组（v4）。

- 默认「普通」会话（id=1，is_default=1）不可删除
- 删除会话时内容**移回普通会话**（不丢数据）
- 激活会话持久化在 config（session.active_id），重启恢复
"""
import logging
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine

from database.engine import make_session_factory
from database.models import ClipboardItem as ItemRow
from database.models import Session

logger = logging.getLogger(__name__)

DEFAULT_SESSION_ID = 1
DEFAULT_SESSION_NAME = "普通"


def ensure_default(engine: Engine) -> int:
    """幂等创建默认会话（id=1「普通」），返回其 id。启动时调用。"""
    with make_session_factory(engine)() as session:
        row = session.get(Session, DEFAULT_SESSION_ID)
        if row is None:
            session.add(Session(id=DEFAULT_SESSION_ID, name=DEFAULT_SESSION_NAME,
                                is_default=1, created_at=datetime.now()))
            session.commit()
            logger.info("已创建默认会话「普通」")
        elif not row.is_default:
            row.is_default = 1
            session.commit()
        return DEFAULT_SESSION_ID


def list_sessions(engine: Engine) -> list[dict]:
    """会话列表（默认置顶）：{id, name, is_default, count}。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(Session.id, Session.name, Session.is_default,
                   func.count(ItemRow.id))
            .outerjoin(ItemRow, ItemRow.session_id == Session.id)
            .group_by(Session.id)
            .order_by(Session.is_default.desc(), Session.id)
        ).all()
    return [{"id": sid, "name": name, "is_default": bool(is_default),
             "count": count or 0}
            for sid, name, is_default, count in rows]


def create_session(engine: Engine, name: str) -> int:
    """新建会话，返回 id。"""
    name = (name or "").strip()
    if not name:
        return 0
    with make_session_factory(engine)() as session:
        row = Session(name=name, created_at=datetime.now())
        session.add(row)
        session.commit()
        session.refresh(row)
    logger.info("已新建会话「%s」(id=%s)", name, row.id)
    return row.id


def rename_session(engine: Engine, session_id: int, name: str) -> bool:
    """重命名会话（默认会话允许重命名，不可删除）。"""
    name = (name or "").strip()
    if not name or session_id == DEFAULT_SESSION_ID:
        return False
    with make_session_factory(engine)() as session:
        row = session.get(Session, session_id)
        if row is None:
            return False
        row.name = name
        session.commit()
    logger.info("会话重命名: id=%s -> %s", session_id, name)
    return True


def delete_session(engine: Engine, session_id: int) -> bool:
    """删除会话：内容**移回普通会话**（id=1），默认会话拒绝。"""
    if session_id == DEFAULT_SESSION_ID:
        logger.warning("默认会话不可删除")
        return False
    with engine.begin() as conn:
        moved = conn.execute(
            text("UPDATE clipboard_items SET session_id = :default_sid"
                 " WHERE session_id = :sid"),
            {"default_sid": DEFAULT_SESSION_ID, "sid": session_id},
        ).rowcount
        conn.execute(text("DELETE FROM sessions WHERE id = :sid"),
                     {"sid": session_id})
    logger.info("会话已删除: id=%s（%d 条内容移回「普通」）",
                session_id, moved)
    return True
