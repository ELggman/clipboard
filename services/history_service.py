"""历史服务：去重落库、FTS 索引、数量上限裁剪（DEVELOPMENT.md §3.1 / §7）。

职责边界：watcher 负责解析，本服务负责持久化与去重；UI 只消费结果。
"""
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from app.types import ClipboardItem
from database.engine import make_session_factory
from database.models import ClipboardItem as ItemRow
from database.models import Session

logger = logging.getLogger(__name__)

_PREVIEW_LEN = 120  # 列表预览文案上限


def compute_preview(item: ClipboardItem) -> str:
    """生成列表预览：文本压平空白；image/file 用文件名。"""
    if item.type in ("image", "file"):
        return Path(item.file_path or item.content).name
    if item.type == "text":
        return " ".join(item.content.split())[:_PREVIEW_LEN]
    return item.content[:_PREVIEW_LEN]


def _parse_expires(expires_at: str) -> datetime | None:
    """临时条目的 expires_at 字符串 → datetime（空/非法返回 None）。"""
    if not expires_at:
        return None
    try:
        return datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        logger.warning("expires_at 格式无法解析，按不过期处理: %s", expires_at)
        return None


def list_recent(engine: Engine, limit: int = 500,
                session_id: int | None = None) -> list[ClipboardItem]:
    """加载最近 N 条（置顶优先，其余最新优先），启动恢复/分页/右键刷新共用。

    session_id=None 返回全部会话（旧调用兼容）；指定则只返回该会话。
    用 Session + ORM select（而非 raw SQL / Connection.scalars）：
    - raw text() 拿到的 created_at 是字符串，ORM 的 DateTime 会解析为 datetime
    - Connection.execute(select(实体)).scalars() 返回的是第一列(id)而非实体，
      必须走 Session（实测踩坑）
    """
    with make_session_factory(engine)() as session:
        stmt = select(ItemRow).order_by(
            ItemRow.pinned.desc(), ItemRow.created_at.desc(), ItemRow.id.desc())
        if session_id is not None:
            stmt = stmt.where(ItemRow.session_id == session_id)
        rows = session.execute(stmt.limit(limit)).scalars().all()
        names = dict(session.execute(
            select(Session.id, Session.name)).all())
    return [_to_item(row, names.get(row.session_id, "")) for row in rows]


def search_items(engine: Engine, query: str, limit: int = 200,
                 regex: bool = False,
                 session_id: int | None = None) -> list[ClipboardItem]:
    """FTS5 搜索并返回展示用条目（最新优先），搜索栏接线用。

    SearchService 只返回 id 列表，这里按 id 顺序取行映射回 ClipboardItem。
    session_id=None 全局搜索；指定则限定该会话。
    """
    from services.search_service import SearchService

    ids = SearchService(engine).search(query, limit=limit, regex=regex,
                                       session_id=session_id)
    if not ids:
        return []
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(ItemRow).where(ItemRow.id.in_(ids))
        ).scalars().all()
        names = dict(session.execute(
            select(Session.id, Session.name)).all())
    by_id = {row.id: row for row in rows}
    ordered = [by_id[i] for i in ids if i in by_id]
    # 置顶优先（稳定排序，组内保持 FTS 相关顺序）
    ordered.sort(key=lambda r: -r.pinned)
    return [_to_item(r, names.get(r.session_id, "")) for r in ordered]


def _session_names(engine: Engine) -> dict[int, str]:
    """会话 id → 名称（全局搜索结果展示来源用）。"""
    from database.models import Session

    with make_session_factory(engine)() as session:
        return dict(session.execute(select(Session.id, Session.name)).all())


def _to_item(row: ItemRow, session_name: str = "") -> ClipboardItem:
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
        session_id=row.session_id or 0,
        session_name=session_name,
        language=row.language or "",
        language_confidence=row.language_confidence or 0.0,
        line_count=row.line_count or 0,
        character_count=row.character_count or 0,
        is_structured=row.is_structured or 0,
        sensitive=row.sensitive or 0,
        sensitive_type=row.sensitive_type or "",
        expires_at=(row.expires_at.strftime("%Y-%m-%d %H:%M:%S")
                    if row.expires_at else ""),
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


def set_sensitive(engine: Engine, item_id: int, sensitive: bool) -> bool:
    """手动标记/取消敏感（右键菜单，§9.17 补充）。

    手动标记类型为 manual（无固定模式，整段遮蔽）；取消时清空类型。
    """
    if not item_id:
        return False
    from services.sensitive_detector import MANUAL

    with engine.begin() as conn:
        conn.execute(
            text("UPDATE clipboard_items SET sensitive = :s,"
                 " sensitive_type = :t WHERE id = :id"),
            {"s": 1 if sensitive else 0,
             "t": MANUAL if sensitive else None,
             "id": item_id},
        )
    return True


def delete_older_than(engine: Engine, days: int) -> list[str]:
    """删除 N 天前且未置顶的记录（自动删除策略，置顶条目豁免）。

    返回被删图片的文件路径，供调用方清理磁盘文件。
    """
    if days <= 0:
        return []
    from datetime import timedelta

    cutoff = datetime.now() - timedelta(days=days)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, file_path FROM clipboard_items"
                 " WHERE created_at < :cut AND pinned = 0"),
            {"cut": cutoff},
        ).fetchall()
        ids = [row[0] for row in rows]
        if not ids:
            return []
    with engine.begin() as conn:
        _delete_rows_and_rebuild(conn, ids)
    logger.info("自动删除 %d 条旧历史（%d 天前）", len(ids), days)
    return [row[1] for row in rows if row[1]]


def delete_expired(engine: Engine) -> list[str]:
    """删除已过期的临时条目（save_temporarily 策略，§9.9）。

    返回图片文件路径供调用方清理磁盘文件。
    """
    now = datetime.now()
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, file_path FROM clipboard_items"
                 " WHERE expires_at IS NOT NULL AND expires_at < :now"),
            {"now": now},
        ).fetchall()
        ids = [row[0] for row in rows]
        if not ids:
            return []
    with engine.begin() as conn:
        _delete_rows_and_rebuild(conn, ids)
    logger.info("已删除 %d 条过期临时条目", len(ids))
    return [row[1] for row in rows if row[1]]


def trim_history(engine: Engine, max_items: int) -> int:
    """立即按数量上限裁剪（设置页改上限即时生效）。返回删除条数。"""
    if max_items <= 0:
        return 0
    with engine.begin() as conn:
        overflow = conn.execute(
            text("SELECT id FROM clipboard_items"
                 " ORDER BY pinned DESC, created_at DESC, id DESC LIMIT -1 OFFSET :m"),
            {"m": max_items},
        ).fetchall()
        ids = [row[0] for row in overflow]
        _delete_rows_and_rebuild(conn, ids)
    if ids:
        logger.info("历史数量裁剪 %d 条（上限 %d）", len(ids), max_items)
    return len(ids)


def list_favorites(engine: Engine, limit: int = 500) -> list[ClipboardItem]:
    """收藏（favorite=1）的条目，最新在前——收藏夹页「★ 收藏」虚拟项。"""
    with make_session_factory(engine)() as session:
        rows = session.execute(
            select(ItemRow)
            .where(ItemRow.favorite == 1)
            .order_by(ItemRow.created_at.desc(), ItemRow.id.desc())
            .limit(limit)
        ).scalars().all()
    return [_to_item(row) for row in rows]


def list_grouped(engine: Engine, limit: int = 500,
                 session_id: int | None = None) -> list[tuple[str, list[ClipboardItem]]]:
    """按时间分组：今天 / 昨天 / 本周 / 更早（按月）——Timeline 页（DEVELOPMENT.md §4.7）。

    session_id=None 全部会话（时间线保持全局）；指定则限定会话。
    """
    from datetime import date, timedelta

    today = date.today()
    monday = today - timedelta(days=today.weekday())

    def bucket_label(dt: datetime) -> str:
        d = dt.date()
        if d == today:
            return "今天"
        if d == today - timedelta(days=1):
            return "昨天"
        if d >= monday:
            return "本周"
        return f"{dt.year}年{dt.month}月"

    with make_session_factory(engine)() as session:
        stmt = select(ItemRow).order_by(
            ItemRow.created_at.desc(), ItemRow.id.desc())
        if session_id is not None:
            stmt = stmt.where(ItemRow.session_id == session_id)
        rows = session.execute(stmt.limit(limit)).scalars().all()
        names = dict(session.execute(
            select(Session.id, Session.name)).all())

    groups: list[tuple[str, list[ClipboardItem]]] = []
    for row in rows:
        label = bucket_label(row.created_at)
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(_to_item(row, names.get(row.session_id, "")))
    return groups


def delete_item(engine: Engine, item_id: int) -> list[str]:
    """删除单条历史（含 FTS 索引重建），返回图片文件路径供清理。"""
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT file_path FROM clipboard_items WHERE id = :id"),
            {"id": item_id},
        ).fetchone()
        if row is None:
            return []
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM clipboard_items WHERE id = :id"), {"id": item_id}
        )
        conn.execute(text("INSERT INTO items_fts(items_fts) VALUES('rebuild')"))
    logger.info("已删除历史: id=%s", item_id)
    return [row[0]] if row[0] else []


def list_older_than(engine: Engine, days: int = 0,
                    item_type: str = "",
                    session_id: int | None = None) -> list[ClipboardItem]:
    """筛选条件查询（清理数据预览用）：时间（N 天前，0=全部）+ 类型 + 会话，最新在前。"""
    from datetime import timedelta

    stmt = select(ItemRow).order_by(
        ItemRow.created_at.desc(), ItemRow.id.desc())
    if days > 0:
        cutoff = datetime.now() - timedelta(days=days)
        stmt = stmt.where(ItemRow.created_at < cutoff)
    if item_type:
        stmt = stmt.where(ItemRow.type == item_type)
    if session_id is not None:
        stmt = stmt.where(ItemRow.session_id == session_id)
    with make_session_factory(engine)() as session:
        rows = session.execute(stmt).scalars().all()
    return [_to_item(row) for row in rows]


def delete_items(engine: Engine, item_ids: list[int]) -> list[str]:
    """批量删除指定条目（一次 FTS rebuild），返回图片文件路径供清理。

    不影响收藏夹（快照独立）。
    """
    if not item_ids:
        return []
    from sqlalchemy import bindparam

    stmt = text(
        "SELECT file_path FROM clipboard_items WHERE id IN :ids"
    ).bindparams(bindparam("ids", expanding=True))
    with engine.connect() as conn:
        rows = conn.execute(stmt, {"ids": item_ids}).fetchall()
        files = [row[0] for row in rows if row[0]]
    with engine.begin() as conn:
        for item_id in item_ids:
            conn.execute(
                text("DELETE FROM clipboard_items WHERE id = :id"),
                {"id": item_id},
            )
        conn.execute(text("INSERT INTO items_fts(items_fts) VALUES('rebuild')"))
    logger.info("批量删除 %d 条历史（图片 %d 个）", len(item_ids), len(files))
    return files


def clear_history(engine: Engine) -> list[str]:
    """清空全部历史（含 FTS 索引重建），返回图片文件路径供清理。

    收藏关系由外键 ON DELETE CASCADE 级联清除（PRAGMA foreign_keys=ON）。
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT file_path FROM clipboard_items")).fetchall()
        files = [row[0] for row in rows if row[0]]
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM clipboard_items"))
        conn.execute(text("INSERT INTO items_fts(items_fts) VALUES('rebuild')"))
    logger.info("已清空全部历史（%d 条，图片 %d 个）", len(rows), len(files))
    return files


def _delete_rows_and_rebuild(conn, ids: list[int]) -> None:
    """删除内容行后重建 FTS 索引。

    对外部内容表逐行 DELETE 在索引与内容不同步时会报
    'database disk image is malformed'（实测）——统一用 rebuild
    从内容表重建索引，永远一致，10k 行毫秒级。
    """
    for item_id in ids:
        conn.execute(
            text("DELETE FROM clipboard_items WHERE id = :id"), {"id": item_id}
        )
    if ids:
        conn.execute(text("INSERT INTO items_fts(items_fts) VALUES('rebuild')"))


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

        try:
            result = conn.execute(
                text(
                    "INSERT INTO clipboard_items"
                    " (type, content, preview, file_path, hash, source_app,"
                    "  favorite, pinned, created_at, updated_at, session_id,"
                    "  language, language_confidence, line_count, character_count,"
                    "  is_structured, sensitive, sensitive_type, expires_at)"
                    " VALUES (:t, :c, :p, :f, :h, :s, 0, 0, :now, :now, :sid,"
                    "  :lang, :lang_conf, :lines, :chars, :structured,"
                    "  :sens, :sens_type, :expires)"
                ),
                {
                    "t": item.type,
                    "c": item.content,
                    "p": compute_preview(item),
                    "f": item.file_path,
                    "h": item.hash,
                    "s": item.source_app,
                    "now": now,
                    "sid": item.session_id or 1,  # 默认归「普通」会话
                    "lang": item.language or None,
                    "lang_conf": item.language_confidence or None,
                    "lines": item.line_count or 0,
                    "chars": item.character_count or 0,
                    "structured": item.is_structured or 0,
                    "sens": item.sensitive or 0,
                    "sens_type": item.sensitive_type or None,
                    "expires": _parse_expires(item.expires_at),
                },
            )
        except IntegrityError:
            # 并发写入同 hash（查重 SELECT 与 INSERT 之间的窗口）→ 视为重复
            logger.debug("INSERT 冲突（并发同类内容），按去重处理: %s", item.hash[:12])
            return False
        item_id = result.lastrowid
        item.id = item_id  # 回填主键（右键菜单置顶/收藏需要）
        conn.execute(
            text("INSERT INTO items_fts(rowid, content) VALUES (:id, :content)"),
            {"id": item_id, "content": item.content},
        )

        # 数量上限裁剪：删除第 max_items 新之后的所有旧记录（同步删 FTS 索引）
        # 置顶优先豁免（§9.22：pinned 不参与自动删除，与 trim_history 一致）
        # LIMIT -1 = 不限行数，从 OFFSET :m 位置取到末尾
        if max_items > 0:
            overflow = conn.execute(
                text("SELECT id FROM clipboard_items"
                     " ORDER BY pinned DESC, created_at DESC, id DESC"
                     " LIMIT -1 OFFSET :m"),
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
