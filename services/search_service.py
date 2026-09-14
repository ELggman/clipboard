"""搜索服务：FTS5 全文索引 + CJK 子串兜底 + 正则（DEVELOPMENT.md §3.4）。

性能目标：1 万条历史 <100ms。
- 普通搜索（ASCII）：FTS5（模糊/忽略大小写天然满足）
- 中文搜索：FTS5 unicode61 把连续中文当一个 token，子串匹配不上
  （实测「胶原」搜不出「最近胶原蛋白满满」）→ 改走 LIKE 子串扫描，
  10k 行全表扫描仅数毫秒，性能目标内
- 正则高级模式：内存过滤兜底
- 三条路径都排除「已过期的临时条目」与「敏感条目」——判据见
  services/item_filters.py（敏感内容若能搜到，遮蔽显示就形同虚设）
"""
import logging
import re
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine

from services import item_filters

logger = logging.getLogger(__name__)

# CJK 统一表意文字区间（含扩展区与兼容区）
_CJK_RANGES = (
    (0x3400, 0x4DBF),   # 扩展 A
    (0x4E00, 0x9FFF),   # 基本区
    (0xF900, 0xFAFF),   # 兼容区
)


def _contains_cjk(query: str) -> bool:
    """查询是否含 CJK 文字 → 需要 LIKE 子串路径。"""
    return any(
        start <= ord(ch) <= end
        for ch in query
        for start, end in _CJK_RANGES
    )


def _like_escape(term: str) -> str:
    """转义 LIKE 通配符（配合 ESCAPE '\\' 使用）。"""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fts_terms(query: str) -> str:
    """查询拆词并引号包裹，避免 FTS5 语法错误（如标点/AND/OR）。"""
    tokens = [t.strip('"') for t in query.split() if t.strip()]
    return " ".join(f'"{t}"' for t in tokens)


class SearchService:
    def __init__(self, engine: Engine):
        self._engine = engine

    # ---- 查询 ----

    def search(self, query: str, limit: int = 100, regex: bool = False,
               ignore_case: bool = True,
               session_id: int | None = None) -> list[int]:
        """返回命中的 clipboard_items.id 列表，最新优先。

        session_id=None 全局；指定则限定该会话。
        过期临时条目与敏感条目一律不返回（判据见 services/item_filters.py）。
        """
        if not query.strip():
            return []
        if regex:
            return self._search_regex(query, limit, ignore_case, session_id)
        if _contains_cjk(query):
            return self._search_like(query, limit, session_id)
        terms = _fts_terms(query)
        where = (" WHERE items_fts MATCH :q"
                 f" AND {item_filters.searchable_sql('i')}")
        params: dict = {"q": terms, "limit": limit, "now": datetime.now()}
        if session_id is not None:
            where += " AND i.session_id = :sid"
            params["sid"] = session_id
        sql = text(
            "SELECT i.id FROM items_fts f"
            " JOIN clipboard_items i ON i.id = f.rowid"
            + where +
            " ORDER BY i.created_at DESC, i.id DESC"
            " LIMIT :limit"
        )
        try:
            with self._engine.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except Exception:
            logger.exception("FTS5 查询失败: %r", query)
            return []
        return [row[0] for row in rows]

    def _search_like(self, query: str, limit: int,
                     session_id: int | None = None) -> list[int]:
        """CJK 子串搜索：每个空白分隔词做 LIKE '%词%'，AND 组合（10k 量级毫秒级）。"""
        terms = [t for t in query.split() if t.strip()]
        if not terms:
            return []
        where = " AND ".join(f"content LIKE :t{i} ESCAPE '\\'" for i in range(len(terms)))
        where += f" AND {item_filters.searchable_sql()}"
        params = {f"t{i}": f"%{_like_escape(t)}%" for i, t in enumerate(terms)}
        params["limit"] = limit
        params["now"] = datetime.now()
        if session_id is not None:
            where += " AND session_id = :sid"
            params["sid"] = session_id
        sql = text(
            f"SELECT id FROM clipboard_items WHERE {where}"
            " ORDER BY created_at DESC, id DESC LIMIT :limit"
        )
        with self._engine.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [row[0] for row in rows]

    def _search_regex(self, pattern: str, limit: int, ignore_case: bool,
                      session_id: int | None = None) -> list[int]:
        try:
            rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
        except re.error:
            logger.warning("无效正则: %r", pattern)
            return []
        where = f" WHERE ({item_filters.searchable_sql()}"
        if session_id is not None:
            where += " AND session_id = :sid"
        where += ")"
        params: dict = {"now": datetime.now()}
        if session_id is not None:
            params["sid"] = session_id
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, content FROM clipboard_items" + where +
                     " ORDER BY created_at DESC, id DESC"),
                params,
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
