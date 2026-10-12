"""收藏夹服务：collections + collection_items 内容快照（DEVELOPMENT.md §4.4）。

快照语义（v2）：收藏时把内容冗余存进 collection_items，与历史解耦——
删除/清空历史不影响收藏夹；收藏夹内容只在收藏夹内管理。
"""
import logging
from datetime import datetime

from sqlalchemy import case, func, select, text
from sqlalchemy.engine import Engine

from app.types import ClipboardItem
from database.engine import make_session_factory
from database.models import Collection, CollectionItem

logger = logging.getLogger(__name__)

# 内置「★ 收藏」收藏夹名（快速收藏的快照归属，删除历史不影响）
FAVORITES_NAME = "★ 收藏"


def ensure_favorites(engine: Engine) -> int:
    """确保内置「★ 收藏」收藏夹存在，返回其 id。

    首次创建时把既有 favorite=1 的历史条目批量快照迁入（幂等）。
    """
    with make_session_factory(engine)() as session:
        row = session.execute(
            select(Collection).where(Collection.name == FAVORITES_NAME)
        ).scalar_one_or_none()
        if row is not None:
            return row.id
        fav = Collection(name=FAVORITES_NAME, created_at=datetime.now())
        session.add(fav)
        session.commit()
        fav_id = fav.id
    # 迁移旧 favorite 标记的历史条目为快照
    from services import history_service

    migrated = history_service.list_favorites(engine)
    for item in migrated:
        add_item(engine, fav_id, item)
    logger.info("内置收藏夹「%s」已创建 (id=%s)，迁移 %d 条",
                FAVORITES_NAME, fav_id, len(migrated))
    return fav_id


def list_collections(engine: Engine) -> list[dict]:
    """全部收藏夹（含条目数，最新创建在前）。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(Collection, func.count(CollectionItem.id))
            .outerjoin(CollectionItem,
                       CollectionItem.collection_id == Collection.id)
            .group_by(Collection.id)
            .order_by(
                case((Collection.name == FAVORITES_NAME, 0), else_=1),  # ★ 收藏置顶
                Collection.created_at.desc(), Collection.id.desc())
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
    """删除收藏夹（条目快照由 FK ON DELETE CASCADE 级联清理）。"""
    with make_session_factory(engine)() as session:
        row = session.get(Collection, collection_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def is_file_path_referenced(engine: Engine, file_path: str) -> bool:
    """该路径是否被任一收藏夹快照引用（图片）。

    删除历史前的守卫：图片条目的 file_path 指向 images/ 下的受管文件，
    若被收藏快照引用则不能删（否则收藏粘贴失效，实测踩坑）。
    """
    if not file_path:
        return False
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT 1 FROM collection_items WHERE file_path = :p LIMIT 1"),
            {"p": file_path},
        ).fetchone()
    return row is not None


def add_item(engine: Engine, collection_id: int, item: ClipboardItem) -> bool:
    """把条目快照加入收藏夹（幂等：同 clipboard_id 不重复加入）。

    内容冗余存储：历史删除后收藏不受影响。
    """
    if not collection_id or not item:
        return False
    try:
        with make_session_factory(engine)() as session:
            session.add(CollectionItem(
                collection_id=collection_id,
                clipboard_id=item.id,
                type=item.type,
                content=item.content,
                preview=item.preview,
                file_path=item.file_path,
                # v10：渲染/操作用得到的一并快照下来，否则收藏夹里的代码条目
                # 没有 language → 详情高亮整段无色（用户实测报的）
                language=item.language or "",
                source_app=item.source_app or "",
                sensitive=item.sensitive or 0,
                sensitive_type=item.sensitive_type or "",
                created_at=datetime.now(),
            ))
            session.commit()
    except Exception:
        # 幂等：唯一约束冲突视为已存在
        logger.debug("加入收藏夹（可能已存在）: %s -> %s",
                     collection_id, item.id)
    return True


def remove_item(engine: Engine, item_id: int) -> bool:
    """从收藏夹移除条目（按 collection_items.id）。"""
    with make_session_factory(engine)() as session:
        row = session.get(CollectionItem, item_id)
        if row is None:
            return False
        session.delete(row)
        session.commit()
        return True


def list_items(engine: Engine, collection_id: int,
               limit: int = 500) -> list[ClipboardItem]:
    """收藏夹内条目快照（最新加入在前），独立于历史数据。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(CollectionItem)
            .where(CollectionItem.collection_id == collection_id)
            .order_by(CollectionItem.id.desc())
            .limit(limit)
        ).scalars().all()
    return [
        _row_to_item(row)
        for row in rows
    ]


def list_all_items(engine: Engine, limit: int = 500) -> list[ClipboardItem]:
    """全部收藏夹条目（并集，按 clipboard_id 去重，最新加入在前）。

    供收藏夹面板「全部」虚拟项使用——同一历史条目可被加入多个收藏夹，
    跨收藏夹并集时要按原条目去重。
    """
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(CollectionItem)
            .order_by(CollectionItem.id.desc())
        ).scalars().all()
    seen: set[int] = set()
    result: list[ClipboardItem] = []
    for row in rows:
        if row.clipboard_id in seen:
            continue
        seen.add(row.clipboard_id)
        result.append(_row_to_item(row))
        if len(result) >= limit:
            break
    return result


def _row_to_item(row) -> ClipboardItem:
    """CollectionItem 行 → ClipboardItem（与 list_items 同一构造）。

    元数据列（v10）在老库里可能是 NULL，一律 `or` 兜底——少了它们代码条目就没有
    高亮、敏感条目就不知该遮蔽。
    """
    return ClipboardItem(
        id=row.id,                     # collection_items.id（收藏条目自己的 id）
        type=row.type,
        content=row.content or "",
        preview=row.preview or "",
        file_path=row.file_path or "",
        language=row.language or "",
        source_app=row.source_app or "",
        sensitive=row.sensitive or 0,
        sensitive_type=row.sensitive_type or "",
        created_at=row.created_at.strftime("%m-%d %H:%M"),
    )
