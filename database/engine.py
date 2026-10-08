"""SQLite 引擎：WAL 模式、外键、busy_timeout。

DEVELOPMENT.md §7.1：WAL 提升并发读写；外键保证 collection_items 级联删除。
"""
import datetime
import logging
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)


# Python 3.12+ 弃用内置 datetime 适配器，注册等价的显式适配（格式不变）
def _datetime_adapter(value: datetime.datetime) -> str:
    return value.isoformat(sep=" ")


sqlite3.register_adapter(datetime.datetime, _datetime_adapter)

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""


def create_db_engine(db_path: Path) -> Engine:
    """创建引擎并设置连接级 PRAGMA。db_path 目录不存在时自动创建。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    @event.listens_for(engine, "commit")
    def _bump_revision(_conn):  # noqa: ANN001
        """任何提交都算「数据变了」→ 页面下次显示时重查（见 app/events.py）。

        挂在 commit 事件上而不是逐个写函数手动调用：服务层有十几个写函数
        （save/delete/pin/favorite/trim/clear/session/collection…），逐个加
        `bump()` 一定会漏，而漏掉的表现是「页面显示旧数据」这种难查的 bug。
        提交是唯一的事实来源，只读查询不提交、也就不会误 bump。
        """
        from app.events import bump

        bump()

    logger.info("SQLite 引擎就绪: %s", db_path)
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
