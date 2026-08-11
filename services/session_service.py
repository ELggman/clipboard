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
    """会话列表（默认置顶）：{id, name, is_default, created_at, count}。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(Session.id, Session.name, Session.is_default,
                   Session.created_at,
                   func.count(ItemRow.id))
            .outerjoin(ItemRow, ItemRow.session_id == Session.id)
            .group_by(Session.id)
            .order_by(Session.is_default.desc(), Session.id)
        ).all()
    return [{"id": sid, "name": name, "is_default": bool(is_default),
             "created_at": created_at,
             "count": count or 0}
            for sid, name, is_default, created_at, count in rows]


def create_session(engine: Engine, name: str) -> int:
    """新建会话，返回 id；**同名已存在返回 0**（用户反馈：不应允许重复名）。"""
    name = (name or "").strip()
    if not name:
        return 0
    with make_session_factory(engine)() as session:
        exists = session.execute(
            select(Session.id).where(Session.name == name)).first()
        if exists:
            logger.warning("会话名已存在，拒绝创建: %s", name)
            return 0
        row = Session(name=name, created_at=datetime.now())
        session.add(row)
        session.commit()
        session.refresh(row)
    logger.info("已新建会话「%s」(id=%s)", name, row.id)
    return row.id


def rename_session(engine: Engine, session_id: int, name: str) -> bool:
    """重命名会话（默认会话允许重命名，不可删除）。
    与其他会话重名返回 False（默认会话原名除外——只查其他会话）。"""
    name = (name or "").strip()
    if not name or session_id == DEFAULT_SESSION_ID:
        return False
    with make_session_factory(engine)() as session:
        row = session.get(Session, session_id)
        if row is None:
            return False
        exists = session.execute(
            select(Session.id).where(Session.name == name,
                                     Session.id != session_id)).first()
        if exists:
            logger.warning("重命名冲突，已存在同名会话: %s", name)
            return False
        row.name = name
        session.commit()
    logger.info("会话重命名: id=%s -> %s", session_id, name)
    return True


def delete_session(engine: Engine, session_id: int,
                   policy: str = "move") -> tuple[bool, int, list[str]]:
    """删除会话。返回 (是否成功, 受影响条数, 待清理图片路径)。

    policy：
    - "move"（默认）：内容**移回普通会话**并**合并去重**——普通会话
      已有同 hash 的内容跳过（用户决策：不产生跨会话重复）
    - "delete"：内容直接删除（图片文件由调用方按引用保护清理）
    默认会话拒绝删除。
    """
    if session_id == DEFAULT_SESSION_ID:
        logger.warning("默认会话不可删除")
        return False, 0, []

    cols = [
        "id", "type", "content", "preview", "file_path", "hash", "source_app",
        "favorite", "pinned", "created_at", "updated_at", "session_id",
        "language", "language_confidence", "line_count", "character_count",
        "is_structured", "sensitive", "sensitive_type", "expires_at",
    ]
    with engine.begin() as conn:
        if policy == "delete":
            # 内容直接删除：图片路径交调用方按引用保护清理
            files = [r[0] for r in conn.execute(
                text("SELECT file_path FROM clipboard_items"
                     " WHERE session_id = :sid AND file_path IS NOT NULL"),
                {"sid": session_id}).fetchall()]
            conn.execute(
                text("DELETE FROM clipboard_items WHERE session_id = :sid"),
                {"sid": session_id})
        else:  # move + 合并去重：普通已有同 hash 的跳过
            # 行只是移动（仍在普通会话），文件仍被引用 → 无待清理路径。
            # 先取数据再删再插（同事务）：INSERT SELECT 同一张表时源行
            # 仍在 → id 唯一约束冲突（实测踩坑）
            files = []
            rows = conn.execute(text(
                "SELECT " + ", ".join(cols) + " FROM clipboard_items"
                " WHERE session_id = :sid AND hash NOT IN"
                " (SELECT hash FROM clipboard_items"
                "  WHERE session_id = :default_sid)"),
                {"sid": session_id, "default_sid": DEFAULT_SESSION_ID}
            ).fetchall()
            conn.execute(text(
                "DELETE FROM clipboard_items WHERE session_id = :sid"),
                {"sid": session_id})
            if rows:
                placeholders = ", ".join(":" + c for c in cols)
                conn.execute(
                    text("INSERT INTO clipboard_items ("
                         + ", ".join(cols) + ") VALUES (" + placeholders + ")"),
                    # 移入普通：session_id 覆盖为 1（SELECT 带出原值会成孤儿）
                    [{**dict(zip(cols, row)),
                      "session_id": DEFAULT_SESSION_ID} for row in rows],
                )
        conn.execute(text("INSERT INTO items_fts(items_fts) VALUES('rebuild')"))
        conn.execute(text("DELETE FROM sessions WHERE id = :sid"),
                     {"sid": session_id})
    logger.info("会话已删除: id=%s（policy=%s）", session_id, policy)
    return True, files
