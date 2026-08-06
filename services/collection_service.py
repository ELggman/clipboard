"""收藏夹服务：collections + collection_items（DEVELOPMENT.md §4.4）。

历史是临时的，收藏夹永久保存；同一剪贴板项可加入多个收藏夹。
"""
import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from database.engine import make_session_factory
from database.models import ClipboardItem as ItemRow
from database.models import Collection, CollectionItem
from services.history_service import _to_item

logger = logging.getLogger(__name__)


def list_collections(engine: Engine) -> list[dict]:
    """全部收藏夹（含条目数，最新创建在前）。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(Collection, func.count(CollectionItem.id))
            .outerjoin(CollectionItem,
                       CollectionItem.collection_id == Collection.id)
            .group_by(Collection.id)
            .order_by(Collection.created_at.desc(), Collection.id.desc())
        ).all()
    return [
        {"id": c.id, "name": c.name, "icon": c.icon or "",
         "count": n, "created_at": c.created_at.strftime("%m-%d %H:%M")}
        for c, n in rows
    ]


def create_collection(engine: Engine, name: str) -> int:
    with make_session_factory(engine)() as session:
        row = Collection(name=name, created_at=datetime.now())
        session.add(row)
        session.commit()
        return row.id


def rename_collection(engine: Engine, collection_id: int, name: str) -> bool:
    with make_session_factory(engine)() as session:
        row = session.get(Collection, collection_id)
        if row is None:
            return False
        row.name = name
        session.commit()
        return True


def delete_collection(engine: Engine, collection_id: int) -> bool:
    """删除收藏夹（collection_items 由外键 ON DELETE CASCADE 级联清理）。"""
    with make_session_factory(engine)() as session:
        row = session.get(Collection, collection_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def add_item(engine: Engine, collection_id: int, clipboard_id: int) -> bool:
    """把剪贴板项加入收藏夹（幂等：重复加入不报错）。"""
    if not collection_id or not clipboard_id:
        return False
    try:
        with make_session_factory(engine)() as session:
            session.add(CollectionItem(collection_id=collection_id,
                                       clipboard_id=clipboard_id))
            session.commit()
    except Exception:
        # 幂等：唯一约束冲突视为已存在
        logger.debug("加入收藏夹（可能已存在）: %s -> %s",
                     collection_id, clipboard_id)
    return True


def remove_item(engine: Engine, collection_id: int, clipboard_id: int) -> bool:
    with make_session_factory(engine)() as session:
        row = session.execute(
            select(CollectionItem).where(
                CollectionItem.collection_id == collection_id,
                CollectionItem.clipboard_id == clipboard_id,
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def list_items(engine: Engine, collection_id: int,
               limit: int = 500) -> list:
    """收藏夹内条目（最新在前），复用 history 的展示映射。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(ItemRow)
            .join(CollectionItem, CollectionItem.clipboard_id == ItemRow.id)
            .where(CollectionItem.collection_id == collection_id)
            .order_by(CollectionItem.id.desc())
            .limit(limit)
        ).scalars().all()
    return [_to_item(r) for r in rows]
