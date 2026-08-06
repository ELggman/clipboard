"""搜索服务：FTS5 全文索引 + 正则兜底（DEVELOPMENT.md §3.4）。

性能目标：1 万条历史 <100ms。普通搜索走 FTS5（模糊/忽略大小写天然满足），
正则高级模式对最新 2k 条内存过滤（量级下同样 <100ms）。
"""
import logging
import re

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)


def _fts_terms(query: str) -> str:
    """查询拆词并引号包裹，避免 FTS5 语法错误（如标点/AND/OR）。"""
    tokens = [t.strip('"') for t in query.split() if t.strip()]
    return " ".join(f'"{t}"' for t in tokens)


class SearchService:
    def __init__(self, engine: Engine):
        self._engine = engine

    # ---- 查询 ----

    def search(self, query: str, limit: int = 100, regex: bool = False,
               ignore_case: bool = True) -> list[int]:
        """返回命中的 clipboard_items.id 列表，最新优先。"""
        if not query.strip():
            return []
        if regex:
            return self._search_regex(query, limit, ignore_case)
        terms = _fts_terms(query)
        sql = text(
            "SELECT i.id FROM items_fts f"
            " JOIN clipboard_items i ON i.id = f.rowid"
            " WHERE items_fts MATCH :q"
            " ORDER BY i.created_at DESC, i.id DESC"
            " LIMIT :limit"
        )
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(sql, {"q": terms, "limit": limit}).fetchall()
        except Exception:
            logger.exception("FTS5 查询失败: %r", query)
            return []
        return [row[0] for row in rows]

    def _search_regex(self, pattern: str, limit: int, ignore_case: bool) -> list[int]:
        try:
            rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error:
            logger.warning("无效正则: %r", pattern)
            return []
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, content FROM clipboard_items"
                     " ORDER BY created_at DESC, id DESC")
            ).fetchall()
        return [row[0] for row in rows if row[1] and rx.search(row[1])][:limit]

    # ---- 索引维护（应用层同步，量级足够，不引触发器）----

    def reindex(self, item_id: int, content: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("INSERT INTO items_fts(rowid, content) VALUES (:id, :content)"),
                {"id": item_id, "content": content},
            )

    def delete_index(self, item_id: int) -> None:
        with self._engine.begin() as conn:
            conn.execute(text("DELETE FROM items_fts WHERE rowid = :id"), {"id": item_id})
