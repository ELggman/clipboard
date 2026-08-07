"""轻量迁移：Base.metadata.create_all + 版本化迁移（不引 Alembic）。

演进约定：新增迁移时在 migrate() 里按 user_version 分支处理，
完成后递增 _SCHEMA_VERSION。
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import Base

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 5

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

    Base.metadata.create_all(engine)  # ORM 表（新库按最新模型建）

    if current < 2:
        _upgrade_v2_collection_snapshot(engine)
    if current < 3:
        _upgrade_v3_code_privacy(engine)
    if current < 4:
        _upgrade_v4_sessions(engine)
    if current < 5:
        _upgrade_v5_dedupe_scope(engine)

    with engine.begin() as conn:
        for ddl in _EXTRA_DDL:
            conn.execute(text(ddl))
        conn.execute(text(f"PRAGMA user_version = {_SCHEMA_VERSION}"))
    logger.info("迁移完成，schema 版本 -> %s", _SCHEMA_VERSION)


def _upgrade_v2_collection_snapshot(engine: Engine) -> None:
    """v1 → v2：collection_items 增加内容快照列（收藏与历史解耦）。

    旧表仅有 collection_id/clipboard_id 引用且 FK 级联删除历史；
    重建为快照结构（内容冗余），并回填已有收藏的内容。
    """
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(collection_items)")).fetchall()}
        if "content" in cols:
            return  # 已是快照结构
        conn.execute(text(
            "ALTER TABLE collection_items RENAME TO collection_items_old"))
        conn.execute(text(
            "CREATE TABLE collection_items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " collection_id INTEGER NOT NULL"
            "   REFERENCES collections(id) ON DELETE CASCADE,"
            " clipboard_id INTEGER NOT NULL DEFAULT 0,"
            " type VARCHAR(16) NOT NULL DEFAULT 'text',"
            " content TEXT, preview TEXT, file_path TEXT,"
            " created_at DATETIME NOT NULL,"
            " UNIQUE (collection_id, clipboard_id))"))
        conn.execute(text(
            "INSERT INTO collection_items"
            " (collection_id, clipboard_id, type, content, preview, file_path,"
            "  created_at)"
            " SELECT o.collection_id, o.clipboard_id, COALESCE(i.type, 'text'),"
            "        i.content, i.preview, i.file_path,"
            "        COALESCE(i.created_at, datetime('now'))"
            " FROM collection_items_old o"
            " LEFT JOIN clipboard_items i ON i.id = o.clipboard_id"))
        conn.execute(text("DROP TABLE collection_items_old"))
        logger.info("v2 迁移：collection_items 已快照化并回填")


def _upgrade_v3_code_privacy(engine: Engine) -> None:
    """v2 → v3：clipboard_items 增加 Code Mode / Privacy Mode 元数据列。

    全部 nullable 或带 DEFAULT（SQLite ALTER TABLE ADD COLUMN 限制），
    PRAGMA table_info 防重（新库由 create_all 已建好全部列）。
    """
    new_cols = [
        ("language", "VARCHAR(32)"),
        ("language_confidence", "REAL"),
        ("line_count", "INTEGER DEFAULT 0"),
        ("character_count", "INTEGER DEFAULT 0"),
        ("is_structured", "INTEGER DEFAULT 0"),
        ("sensitive", "INTEGER DEFAULT 0"),
        ("sensitive_type", "VARCHAR(32)"),
        ("expires_at", "DATETIME"),
    ]
    with engine.begin() as conn:
        existing = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        for col_name, col_type in new_cols:
            if col_name not in existing:
                conn.execute(text(
                    f"ALTER TABLE clipboard_items ADD COLUMN {col_name} {col_type}"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_items_expires "
            "ON clipboard_items (expires_at)"))
    logger.info("v3 迁移：code/privacy 元数据列已添加")


def _upgrade_v4_sessions(engine: Engine) -> None:
    """v3 → v4：会话机制——sessions 表 + clipboard_items.session_id。

    默认会话固定 id=1（普通）；历史数据全部归入。删除会话时内容
    移回普通会话（session_service.delete_session）。
    """
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS sessions ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name VARCHAR(128) NOT NULL,"
            " is_default INTEGER DEFAULT 0,"
            " created_at DATETIME NOT NULL)"))
        # 幂等插入默认会话（id=1 固定）
        row = conn.execute(text(
            "SELECT id FROM sessions WHERE id = 1")).fetchone()
        if row is None:
            conn.execute(text(
                "INSERT INTO sessions (id, name, is_default, created_at)"
                " VALUES (1, '普通', 1, datetime('now'))"))
        else:
            conn.execute(text(
                "UPDATE sessions SET is_default = 1 WHERE id = 1"))
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        if "session_id" not in cols:
            conn.execute(text(
                "ALTER TABLE clipboard_items ADD COLUMN session_id"
                " INTEGER NOT NULL DEFAULT 1"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_items_session"
            " ON clipboard_items (session_id)"))
    logger.info("v4 迁移：会话机制已建立（默认「普通」id=1）")


def _upgrade_v5_dedupe_scope(engine: Engine) -> None:
    """v4 → v5：去重范围可配置——唯一约束 hash → (hash, session_id)。

    SQLite 无法删除/修改唯一约束（ALTER TABLE 限制）→ 重建表：
    - 保留全部列与 id（collection_items.clipboard_id 悬空引用仍有效）
    - 唯一键改为 UNIQUE(hash, session_id)：同一内容可在不同会话各存一份
      （scope=session 去重的前提）；scope=all 时由 save_item 查重逻辑
      维持全局去重语义（DB 约束放宽不影响）
    - 重建 items_fts 索引（外部内容表 rowid 对应 id 不变）
    """
    cols = [
        "id", "type", "content", "preview", "file_path", "hash", "source_app",
        "favorite", "pinned", "created_at", "updated_at", "session_id",
        "language", "language_confidence", "line_count", "character_count",
        "is_structured", "sensitive", "sensitive_type", "expires_at",
    ]
    with engine.begin() as conn:
        existing = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        if "session_id" not in existing:
            # 理论不可达（v4 已加），防御
            return
        conn.execute(text(
            "ALTER TABLE clipboard_items RENAME TO clipboard_items_v4"))
        conn.execute(text(
            "CREATE TABLE clipboard_items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " type VARCHAR(16) NOT NULL, content TEXT, preview TEXT,"
            " file_path TEXT, hash VARCHAR(64) NOT NULL,"
            " source_app VARCHAR(255), favorite INTEGER DEFAULT 0,"
            " pinned INTEGER DEFAULT 0,"
            " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,"
            " session_id INTEGER NOT NULL DEFAULT 1,"
            " language VARCHAR(32), language_confidence REAL,"
            " line_count INTEGER DEFAULT 0, character_count INTEGER DEFAULT 0,"
            " is_structured INTEGER DEFAULT 0, sensitive INTEGER DEFAULT 0,"
            " sensitive_type VARCHAR(32), expires_at DATETIME,"
            " UNIQUE (hash, session_id))"))
        conn.execute(text(
            "INSERT INTO clipboard_items (" + ", ".join(cols) + ")"
            " SELECT " + ", ".join(cols) + " FROM clipboard_items_v4"))
        conn.execute(text("DROP TABLE clipboard_items_v4"))
        for ddl in (
            "CREATE INDEX IF NOT EXISTS ix_items_created"
            " ON clipboard_items (created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_items_type ON clipboard_items (type)",
            "CREATE INDEX IF NOT EXISTS ix_items_expires"
            " ON clipboard_items (expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_items_session"
            " ON clipboard_items (session_id)",
        ):
            conn.execute(text(ddl))
        # items_fts 由 _EXTRA_DDL 在迁移后创建：旧库存在才 rebuild，
        # 新库（迁移链从头跑）此时尚无 FTS 表，跳过由 create 空表
        tables = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        if "items_fts" in tables:
            conn.execute(text(
                "INSERT INTO items_fts(items_fts) VALUES('rebuild')"))
    logger.info("v5 迁移：唯一约束改为 (hash, session_id)（去重范围可配置）")
