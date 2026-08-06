"""V1 页面服务测试：Snippet CRUD、Collection CRUD/关联、Timeline 分组。"""
import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text


@pytest.fixture()
def engine(tmp_path):
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "v1.db")
    migrate(eng)
    yield eng
    eng.dispose()


# ---- Snippet ----

def test_snippet_crud(engine):
    from services import snippet_service

    s_id = snippet_service.create_snippet(engine, "email", "hello@{{date}}", "常用邮箱")
    items = snippet_service.list_snippets(engine)
    assert len(items) == 1
    assert items[0]["name"] == "email"
    assert items[0]["description"] == "常用邮箱"

    assert snippet_service.update_snippet(engine, s_id, "email2", "{{uuid}}@x.com", "新") is True
    items = snippet_service.list_snippets(engine)
    assert items[0]["name"] == "email2" and items[0]["content"] == "{{uuid}}@x.com"

    assert snippet_service.delete_snippet(engine, s_id) is True
    assert snippet_service.list_snippets(engine) == []
    assert snippet_service.update_snippet(engine, 999, "x", "y") is False


def test_snippet_render_on_copy(engine):
    """复制时渲染变量（页面 _copy 的语义）。"""
    from services import snippet_service

    assert snippet_service.render_snippet("Today: {{date}}") != "Today: {{date}}"
    assert "{{" not in snippet_service.render_snippet("{{time}} {{uuid}}")


# ---- Collection ----

def test_collection_crud(engine):
    from services import collection_service

    cid = collection_service.create_collection(engine, "工作")
    assert cid > 0
    colls = collection_service.list_collections(engine)
    assert colls[0]["name"] == "工作" and colls[0]["count"] == 0

    assert collection_service.rename_collection(engine, cid, "工作资料") is True
    assert collection_service.list_collections(engine)[0]["name"] == "工作资料"

    assert collection_service.delete_collection(engine, cid) is True
    assert collection_service.list_collections(engine) == []


def test_collection_items_add_remove_idempotent(engine):
    """收藏快照：加/移/幂等；list_items 返回收藏条目自己的 id。"""
    import hashlib

    from app.types import ClipboardItem
    from services import collection_service, history_service

    cid = collection_service.create_collection(engine, "收藏")
    item = ClipboardItem(type="text", content="keep me", preview="keep",
                         file_path="")
    item.hash = hashlib.sha256(b"keep me").hexdigest()
    history_service.save_item(engine, item)
    item.id = history_service.list_recent(engine, limit=1)[0].id

    # 加入两次幂等（同 clipboard_id）
    assert collection_service.add_item(engine, cid, item) is True
    assert collection_service.add_item(engine, cid, item) is True
    items = collection_service.list_items(engine, cid)
    assert len(items) == 1
    assert items[0].content == "keep me"

    # 移除（按收藏条目 id）
    coll_item_id = items[0].id
    assert collection_service.remove_item(engine, coll_item_id) is True
    assert collection_service.list_items(engine, cid) == []
    assert collection_service.remove_item(engine, coll_item_id) is False

    # 空收藏夹/空条目保护
    assert collection_service.add_item(engine, 0, item) is False
    assert collection_service.add_item(engine, cid, None) is False


def test_collection_snapshot_survives_history_delete(engine):
    """快照核心语义：删除/清空历史不影响收藏夹内容。"""
    import hashlib

    from app.types import ClipboardItem
    from services import collection_service, history_service

    item = ClipboardItem(type="text", content="收藏不删")
    item.hash = hashlib.sha256("收藏不删".encode()).hexdigest()
    history_service.save_item(engine, item)
    cid = collection_service.create_collection(engine, "保留")
    collection_service.add_item(engine, cid, item)

    # 删除历史条目
    history_service.delete_item(engine, item.id)
    assert collection_service.list_items(engine, cid)[0].content == "收藏不删"

    # 清空历史
    collection_service.add_item(engine, cid, item)  # 重新收藏一次（内容仍在历史）
    history_service.clear_history(engine)
    items = collection_service.list_items(engine, cid)
    assert len(items) == 1
    assert items[0].content == "收藏不删"


def test_collection_delete_cascades(engine):
    """删除收藏夹级联清理条目快照（FK ON DELETE CASCADE）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import collection_service, history_service

    cid = collection_service.create_collection(engine, "临时")
    item = ClipboardItem(type="text", content="x")
    item.hash = hashlib.sha256(b"x").hexdigest()
    history_service.save_item(engine, item)
    collection_service.add_item(engine, cid, item)
    collection_service.delete_collection(engine, cid)
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM collection_items")).scalar()
    assert count == 0  # 级联已清理


def test_list_favorites(engine):
    """收藏条目查询（收藏夹页「★ 收藏」虚拟项数据源）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service

    fav = ClipboardItem(type="text", content="fav item")
    fav.hash = hashlib.sha256(b"fav item").hexdigest()
    plain = ClipboardItem(type="text", content="plain item")
    plain.hash = hashlib.sha256(b"plain item").hexdigest()
    history_service.save_item(engine, fav)
    history_service.save_item(engine, plain)
    history_service.set_favorite(engine, fav.id, True)

    items = history_service.list_favorites(engine)
    assert [i.content for i in items] == ["fav item"]
    assert items[0].favorite == 1


def test_delete_item(engine):
    """删除单条历史：行删除 + FTS 重建 + 图片路径返回。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service
    from services.search_service import SearchService

    item = ClipboardItem(type="text", content="to delete")
    item.hash = hashlib.sha256(b"to delete").hexdigest()
    history_service.save_item(engine, item)
    rid = item.id
    assert history_service.delete_item(engine, rid) == []
    with engine.connect() as conn:
        remaining = conn.execute(text(
            "SELECT COUNT(*) FROM clipboard_items WHERE id = :id"),
            {"id": rid}).scalar()
    assert remaining == 0
    # FTS 索引已重建：搜索不到
    assert SearchService(engine).search("to delete") == []

    # 图片条目返回路径
    img = ClipboardItem(type="image", file_path="/tmp/x.png", content="")
    img.hash = hashlib.sha256(b"img x").hexdigest()
    history_service.save_item(engine, img)
    assert history_service.delete_item(engine, img.id) == ["/tmp/x.png"]

    # 不存在返回空
    assert history_service.delete_item(engine, 99999) == []


def test_clear_history(engine):
    """清空全部历史：行清空 + FTS 重建 + 图片路径返回 + 收藏级联。"""
    import hashlib

    from app.types import ClipboardItem
    from services import collection_service, history_service
    from services.search_service import SearchService

    a = ClipboardItem(type="text", content="a")
    a.hash = hashlib.sha256(b"a").hexdigest()
    b = ClipboardItem(type="image", file_path="/tmp/pic.png", content="")
    b.hash = hashlib.sha256(b"b").hexdigest()
    history_service.save_item(engine, a)
    history_service.save_item(engine, b)
    cid = collection_service.create_collection(engine, "c")
    collection_service.add_item(engine, cid, a)

    files = history_service.clear_history(engine)
    assert files == ["/tmp/pic.png"]
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM clipboard_items")).scalar() == 0
    assert SearchService(engine).search("a") == []  # FTS 已重建


def test_list_older_than_type_filter(engine):
    """清理数据查询支持类型筛选。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service

    t = ClipboardItem(type="text", content="txt")
    t.hash = hashlib.sha256(b"txt").hexdigest()
    u = ClipboardItem(type="url", content="https://x.com")
    u.hash = hashlib.sha256(b"url").hexdigest()
    history_service.save_item(engine, t)
    history_service.save_item(engine, u)

    all_items = history_service.list_older_than(engine, 0)
    assert len(all_items) == 2
    urls = history_service.list_older_than(engine, 0, item_type="url")
    assert [i.content for i in urls] == ["https://x.com"]
    imgs = history_service.list_older_than(engine, 0, item_type="image")
    assert imgs == []


# ---- Timeline 分组 ----

def test_list_grouped_buckets(engine):
    from services import history_service
    from sqlalchemy import text as _t

    now = datetime.datetime.now()
    with engine.begin() as conn:
        for label, delta, h in (("today", 0, "ht"),
                                ("yesterday", 1, "hy"),
                                ("this_week", 3, "hw"),
                                ("older", 40, "ho")):
            conn.execute(_t(
                "INSERT INTO clipboard_items (type, content, preview, hash,"
                " favorite, pinned, created_at, updated_at) VALUES"
                " ('text', :c, :c, :h, 0, 0, :t, :t)"),
                {"c": label, "h": h,
                 "t": now - datetime.timedelta(days=delta)})

    groups = history_service.list_grouped(engine)
    labels = [g[0] for g in groups]
    assert labels[0] == "今天"
    assert labels[1] == "昨天"
    assert "本周" in labels
    # 40 天前归入「更早」的月份桶
    assert any("月" in l for l in labels)
    assert groups[0][1][0].content == "today"  # 组内最新在前
