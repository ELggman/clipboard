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

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # text/url/image/file
    content: Mapped[str | None] = mapped_column(Text)              # 文本；url 存 URL
    preview: Mapped[str | None] = mapped_column(Text)              # 列表预览文案
    file_path: Mapped[str | None] = mapped_column(Text)            # image/file 存储路径
    hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)  # 去重键
    source_app: Mapped[str | None] = mapped_column(String(255))
    favorite: Mapped[int] = mapped_column(Integer, default=0)
    pinned: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class Collection(Base):
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CollectionItem(Base):
    """收藏关系：collection → clipboard_item（多对多）。"""

    __tablename__ = "collection_items"
    __table_args__ = (UniqueConstraint("collection_id", "clipboard_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_id: Mapped[int] = mapped_column(
        ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    clipboard_id: Mapped[int] = mapped_column(
        ForeignKey("clipboard_items.id", ondelete="CASCADE"), nullable=False
    )


class Snippet(Base):
    __tablename__ = "snippets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
