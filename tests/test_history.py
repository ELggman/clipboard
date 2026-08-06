"""历史服务测试：去重落库 / FTS 索引同步 / 数量上限裁剪。"""
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.types import ClipboardItem
from services import history_service


@pytest.fixture()
def engine(tmp_path):
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "test.db")
    migrate(eng)
    yield eng
    eng.dispose()


def _item(content: str, type_: str = "text") -> ClipboardItem:
    return ClipboardItem(
        type=type_,
        content=content,
        hash=hashlib.sha256(content.encode()).hexdigest(),
    )


def test_save_new_item(engine):
    assert history_service.save_item(engine, _item("hello world")) is True
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT type, content, preview, source_app FROM clipboard_items")
        ).fetchone()
    assert row.content == "hello world"
    assert row.preview == "hello world"
    assert row.type == "text"


def test_dedupe_by_hash(engine):
    item = _item("same content")
    assert history_service.save_item(engine, item) is True
    assert history_service.save_item(engine, item) is False  # 重复不新增
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM clipboard_items")).scalar()
    assert count == 1


def test_fts_index_synced(engine):
    assert history_service.save_item(engine, _item("mysql install notes")) is True
    from services.search_service import SearchService

    with engine.connect() as conn:
        rid = conn.execute(text("SELECT id FROM clipboard_items")).scalar()
    assert SearchService(engine).search("mysql") == [rid]


def test_max_items_trim(engine):
    for i in range(5):
        history_service.save_item(engine, _item(f"item {i}"))
    # 上限 3：最旧两条被裁剪（created_at 同毫秒时按 id 判定新旧）
    history_service.save_item(engine, _item("item 5"), max_items=3)
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT content FROM clipboard_items"
                 " ORDER BY created_at DESC, id DESC")
        ).fetchall()
    assert [r[0] for r in rows] == ["item 5", "item 4", "item 3"]
    # FTS 索引同步裁剪：被裁掉的记录搜不到
    from services.search_service import SearchService

    assert SearchService(engine).search("item 0") == []
    assert SearchService(engine).search("item 5") != []


def test_list_recent_newest_first(engine):
    history_service.save_item(engine, _item("older"))
    history_service.save_item(engine, _item("newer"))
    items = history_service.list_recent(engine, limit=10)
    assert [i.content for i in items] == ["newer", "older"]
    assert items[0].created_at  # 恢复用的展示时间戳已填充
    assert items[0].type == "text"
    assert len(history_service.list_recent(engine, limit=1)) == 1


def test_save_item_fills_display_fields(engine):
    """落库回填 created_at/preview：实时 UI 依赖（回归：当前进程内不显示时间/文件名）。"""
    item = _item("hello display")
    history_service.save_item(engine, item)
    assert item.created_at  # "%m-%d %H:%M"
    assert item.preview == "hello display"

    img = ClipboardItem(
        type="image", content="", file_path="/data/images/xyz.png", hash="y" * 64
    )
    history_service.save_item(engine, img)
    assert img.preview == "xyz.png"
    assert img.created_at


def test_preview_image_uses_filename():
    item = ClipboardItem(
        type="image", content="", file_path="/data/images/abc123.png",
        hash="x" * 64,
    )
    assert history_service.compute_preview(item) == "abc123.png"
