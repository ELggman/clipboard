"""历史服务：去重落库、FTS 索引、数量上限裁剪（DEVELOPMENT.md §3.1 / §7）。

职责边界：watcher 负责解析，本服务负责持久化与去重；UI 只消费结果。
"""
import logging
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.types import ClipboardItem

logger = logging.getLogger(__name__)

_PREVIEW_LEN = 120  # 列表预览文案上限


def compute_preview(item: ClipboardItem) -> str:
    """生成列表预览：文本压平空白；image/file 用文件名。"""
    if item.type in ("image", "file"):
        return Path(item.file_path or item.content).name
    if item.type == "text":
        return " ".join(item.content.split())[:_PREVIEW_LEN]
    return item.content[:_PREVIEW_LEN]


def save_item(engine: Engine, item: ClipboardItem, max_items: int = 500) -> bool:
    """去重落库 + FTS 索引。返回 True=新增；False=重复（仅刷新 updated_at）。

    重复判定用 hash（sha256）；图片重复时会复用已落盘的图片文件。
    """
    now = datetime.now()
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
