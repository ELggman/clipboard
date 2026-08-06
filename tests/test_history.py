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


def test_search_items_matches_and_orders(engine):
    """搜索栏接线：FTS5 命中并按相关度 id 顺序返回展示条目。"""
    from datetime import datetime as dt

    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', 'mysql install notes', 'mysql install', 'h1', 0, 0, :n, :n)"),
            {"n": dt.now()},
        )
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', 'postgres setup guide', 'postgres', 'h2', 0, 0, :n, :n)"),
            {"n": dt.now()},
        )
    with engine.connect() as conn:
        ids = [r[0] for r in conn.execute(
            text("SELECT id FROM clipboard_items ORDER BY id")).fetchall()]
    from services import history_service

    for i, content in [(ids[0], "mysql install notes"), (ids[1], "postgres setup guide")]:
        from services.search_service import SearchService

        SearchService(engine).reindex(i, content)

    results = history_service.search_items(engine, "mysql")
    assert [r.content for r in results] == ["mysql install notes"]
    assert results[0].created_at  # 展示字段已填充

    # 无命中返回空
    assert history_service.search_items(engine, "docker") == []


def test_search_cjk_substring(engine):
    """中文子串搜索：FTS5 unicode61 匹配不上连续中文，必须走 LIKE（回归测试）。"""
    from datetime import datetime as dt

    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', '最近胶原蛋白满满', '最近胶原蛋白满满', 'hc', 0, 0, :n, :n)"),
            {"n": dt.now()},
        )
        rid = conn.execute(text("SELECT id FROM clipboard_items LIMIT 1")).scalar()

    from services.search_service import SearchService

    svc = SearchService(engine)
    assert svc.search("胶原") == [rid]       # 2 字子串
    assert svc.search("胶原蛋白") == [rid]    # 4 字子串
    assert svc.search("蛋白满满") == [rid]    # 尾部子串
    assert svc.search("不是") == []           # 无命中
    assert svc.search("胶原 满满") == [rid]   # 多词 AND


def test_search_like_escapes_wildcards(engine):
    """LIKE 路径转义 % _ \\（用户查询里的通配符不当通配符用）。"""
    from datetime import datetime as dt

    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', '进度 50% 完成', '进度', 'hp', 0, 0, :n, :n)"),
            {"n": dt.now()},
        )
    from services.search_service import SearchService

    svc = SearchService(engine)
    # 含 CJK → 走 LIKE 路径（转义只作用于该路径）；字面 % 能搜到
    assert svc.search("进度 50%") != []
    # 字面 _ 不匹配（未转义时 _ 匹配任意单字符，会误命中）
    assert svc.search("进度 50_") == []


def test_save_item_backfills_id(engine):
    """save_item 回填主键 id（右键菜单置顶/收藏依赖）。"""
    item = _item("id backfill")
    assert history_service.save_item(engine, item) is True
    assert item.id > 0
    assert item.pinned == 0 and item.favorite == 0


def test_pin_favorite_toggle_and_ordering(engine):
    """置顶/收藏切换 + list_recent 置顶优先排序。"""
    older = _item("older")
    newer = _item("newer")
    history_service.save_item(engine, older)
    history_service.save_item(engine, newer)

    # 置顶旧的
    assert history_service.set_pinned(engine, older.id, True) is True
    assert history_service.set_favorite(engine, newer.id, True) is True

    items = history_service.list_recent(engine)
    assert items[0].id == older.id          # 置顶优先
    assert items[0].pinned == 1
    assert items[1].id == newer.id
    assert items[1].favorite == 1

    # 取消置顶后恢复时间序
    history_service.set_pinned(engine, older.id, False)
    items = history_service.list_recent(engine)
    assert items[0].id == newer.id

    # id=0 的未落库条目返回 False
    assert history_service.set_pinned(engine, 0, True) is False


def test_search_items_pinned_first(engine):
    """搜索结果的置顶优先排序。"""
    from datetime import datetime as dt

    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', 'mysql guide a', 'a', 'pa', 0, 1, :n, :n)"),
            {"n": dt.now()},
        )
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', 'mysql guide b', 'b', 'pb', 0, 0, :n, :n)"),
            {"n": dt.now()},
        )
    with engine.connect() as conn:
        ids = [r[0] for r in conn.execute(
            text("SELECT id FROM clipboard_items ORDER BY id")).fetchall()]
    from services.search_service import SearchService

    svc = SearchService(engine)
    for i, content in zip(ids, ("mysql guide a", "mysql guide b")):
        svc.reindex(i, content)

    from services import history_service

    results = history_service.search_items(engine, "mysql")
    assert [r.id for r in results] == [ids[0], ids[1]]  # 置顶的 a 在前


def test_preview_image_uses_filename():
    item = ClipboardItem(
        type="image", content="", file_path="/data/images/abc123.png",
        hash="x" * 64,
    )
    assert history_service.compute_preview(item) == "abc123.png"
