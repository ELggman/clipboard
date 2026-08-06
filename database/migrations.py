"""轻量迁移：Base.metadata.create_all + 幂等 SQL（不引 Alembic）。

演进约定：schema 变更时追加幂等 DDL 到 _EXTRA_DDL 并递增 _SCHEMA_VERSION；
PRAGMA user_version 仅用于记录版本，不自动回滚。
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import Base

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1

# 幂等扩展 DDL（FTS5 全文索引 + 常用索引）
_EXTRA_DDL = [
    # FTS5 外部内容表：items_fts 与 clipboard_items 同表同步，由 search_service 维护
    "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5("
    "content, content='clipboard_items', content_rowid='id')",
    "CREATE INDEX IF NOT EXISTS ix_items_created ON clipboard_items (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_items_type ON clipboard_items (type)",
]


def migrate(engine: Engine) -> None:
    with engine.connect() as conn:
        current = conn.execute(text("PRAGMA user_version")).scalar()
    logger.info("数据库 schema 版本: %s", current)

    Base.metadata.create_all(engine)  # ORM 表

    with engine.begin() as conn:
        for ddl in _EXTRA_DDL:
            conn.execute(text(ddl))
        conn.execute(text(f"PRAGMA user_version = {_SCHEMA_VERSION}"))
    logger.info("迁移完成，schema 版本 -> %s", _SCHEMA_VERSION)
