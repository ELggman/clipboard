"""历史服务：去重落库、FTS 索引、数量上限裁剪（DEVELOPMENT.md §3.1 / §7）。

职责边界：watcher 负责解析，本服务负责持久化与去重；UI 只消费结果。
"""
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import Engine

from app.types import ClipboardItem
from database.engine import make_session_factory
from database.models import ClipboardItem as ItemRow

logger = logging.getLogger(__name__)

_PREVIEW_LEN = 120  # 列表预览文案上限


def compute_preview(item: ClipboardItem) -> str:
    """生成列表预览：文本压平空白；image/file 用文件名。"""
    if item.type in ("image", "file"):
        return Path(item.file_path or item.content).name
    if item.type == "text":
        return " ".join(item.content.split())[:_PREVIEW_LEN]
    return item.content[:_PREVIEW_LEN]


def list_recent(engine: Engine, limit: int = 500) -> list[ClipboardItem]:
    """加载最近 N 条（置顶优先，其余最新优先），启动恢复/分页/右键刷新共用。

    用 Session + ORM select（而非 raw SQL / Connection.scalars）：
    - raw text() 拿到的 created_at 是字符串，ORM 的 DateTime 会解析为 datetime
    - Connection.execute(select(实体)).scalars() 返回的是第一列(id)而非实体，
      必须走 Session（实测踩坑）
    """
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(ItemRow)
            .order_by(ItemRow.pinned.desc(), ItemRow.created_at.desc(),
                      ItemRow.id.desc())
            .limit(limit)
        ).scalars().all()
    return [_to_item(row) for row in rows]


def search_items(engine: Engine, query: str, limit: int = 200,
                 regex: bool = False) -> list[ClipboardItem]:
    """FTS5 搜索并返回展示用条目（最新优先），搜索栏接线用。

    SearchService 只返回 id 列表，这里按 id 顺序取行映射回 ClipboardItem。
    """
    from services.search_service import SearchService

    ids = SearchService(engine).search(query, limit=limit, regex=regex)
    if not ids:
        return []
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(ItemRow).where(ItemRow.id.in_(ids))
        ).scalars().all()
    by_id = {row.id: row for row in rows}
    ordered = [by_id[i] for i in ids if i in by_id]
    # 置顶优先（稳定排序，组内保持 FTS 相关顺序）
    ordered.sort(key=lambda r: -r.pinned)
    return [_to_item(r) for r in ordered]


def _to_item(row: ItemRow) -> ClipboardItem:
    """ORM 行 → 展示用 ClipboardItem（created_at 格式化为 %m-%d %H:%M）。"""
    return ClipboardItem(
        type=row.type,
        content=row.content or "",
        preview=row.preview or "",
        file_path=row.file_path or "",
        source_app=row.source_app or "",
        created_at=row.created_at.strftime("%m-%d %H:%M"),
        id=row.id,
        pinned=row.pinned,
        favorite=row.favorite,
    )


def set_pinned(engine: Engine, item_id: int, pinned: bool) -> bool:
    """置顶/取消置顶。返回是否成功（id=0 的未落库条目跳过）。"""
    if not item_id:
        return False
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE clipboard_items SET pinned = :p WHERE id = :id"),
            {"p": 1 if pinned else 0, "id": item_id},
        )
    return True


def set_favorite(engine: Engine, item_id: int, favorite: bool) -> bool:
    """收藏/取消收藏。返回是否成功。"""
    if not item_id:
        return False
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE clipboard_items SET favorite = :f WHERE id = :id"),
            {"f": 1 if favorite else 0, "id": item_id},
        )
    return True


def save_item(engine: Engine, item: ClipboardItem, max_items: int = 500) -> bool:
    """去重落库 + FTS 索引。返回 True=新增；False=重复（仅刷新 updated_at）。

    重复判定用 hash（sha256）；图片重复时会复用已落盘的图片文件。
    副作用：回填 item.created_at / item.preview —— 实时 UI 刷新依赖这两个
    展示字段（否则当前进程内列表不显示时间/文件名，重启恢复才有）。
    """
    now = datetime.now()
    item.created_at = now.strftime("%m-%d %H:%M")
    item.preview = compute_preview(item)
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT id FROM clipboard_items WHERE hash = :h"), {"h": item.hash}
        ).fetchone()
        if row:
            conn.execute(
                text("UPDATE clipboard_items SET updated_at = :now WHERE id = :id"),
                {"id": row[0], "now": now},
            )
            return False

        result = conn.execute(
            text(
                "INSERT INTO clipboard_items"
                " (type, content, preview, file_path, hash, source_app,"
                "  favorite, pinned, created_at, updated_at)"
                " VALUES (:t, :c, :p, :f, :h, :s, 0, 0, :now, :now)"
            ),
            {
                "t": item.type,
                "c": item.content,
                "p": compute_preview(item),
                "f": item.file_path,
                "h": item.hash,
                "s": item.source_app,
                "now": now,
            },
        )
        item_id = result.lastrowid
        item.id = item_id  # 回填主键（右键菜单置顶/收藏需要）
        conn.execute(
            text("INSERT INTO items_fts(rowid, content) VALUES (:id, :content)"),
            {"id": item_id, "content": item.content},
        )

        # 数量上限裁剪：删除第 max_items 新之后的所有旧记录（同步删 FTS 索引）
        # LIMIT -1 = 不限行数，从 OFFSET :m 位置取到末尾
        if max_items > 0:
            overflow = conn.execute(
                text("SELECT id FROM clipboard_items"
                     " ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET :m"),
                {"m": max_items},
            ).fetchall()
            for (old_id,) in overflow:
                conn.execute(
                    text("DELETE FROM items_fts WHERE rowid = :id"), {"id": old_id}
                )
                conn.execute(
                    text("DELETE FROM clipboard_items WHERE id = :id"), {"id": old_id}
                )
    return True
