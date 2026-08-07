"""ORM 模型：对应 DEVELOPMENT.md §7.2 表结构。

说明：
- FTS5 全文索引表不是 ORM 模型，由 migrations.py 创建、search_service 维护。
- collection_items 采用代理主键 id（SQLite 下 ORM 组合主键繁琐），
  原 DDL 的 (collection_id, clipboard_id) 唯一约束以 UniqueConstraint 保留。
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .engine import Base


class ClipboardItem(Base):
    __tablename__ = "clipboard_items"
    __table_args__ = (UniqueConstraint("hash", "session_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # text/url/image/file/code
    content: Mapped[str | None] = mapped_column(Text)              # 文本；url 存 URL
    preview: Mapped[str | None] = mapped_column(Text)              # 列表预览文案
    file_path: Mapped[str | None] = mapped_column(Text)            # image/file 存储路径
    # v5：去重键从 hash 唯一改为 (hash, session_id) 联合唯一（去重范围可配置）
    hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_app: Mapped[str | None] = mapped_column(String(255))
    favorite: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # v4：所属会话（默认 1 = 普通会话；server_default 兼容裸 SQL 插入）
    session_id: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    # Code Mode 元数据（§8.16）
    # server_default：裸 SQL INSERT（测试/迁移回填）不提供这些列时也不违反约束
    language: Mapped[str | None] = mapped_column(String(32))
    language_confidence: Mapped[float | None] = mapped_column()
    line_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    character_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_structured: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Privacy Mode（§9）
    sensitive: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sensitive_type: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime)


class Session(Base):
    """会话：任务型内容分组（v4）。默认「普通」会话不可删除。"""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    is_default: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CollectionItem(Base):
    """收藏条目：内容快照（与历史解耦，删除历史不影响收藏）。

    clipboard_id 仅作来源引用（无 FK，可能悬空）；内容字段冗余存储，
    收藏夹独立管理自己的数据（DEVELOPMENT.md §4.4）。
    """

    __tablename__ = "collection_items"
    __table_args__ = (UniqueConstraint("collection_id", "clipboard_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    clipboard_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    content: Mapped[str | None] = mapped_column(Text)
    preview: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Snippet(Base):
    __tablename__ = "snippets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
