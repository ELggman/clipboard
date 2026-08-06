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
    from services import collection_service
    from sqlalchemy import text as _t

    cid = collection_service.create_collection(engine, "收藏")
    with engine.begin() as conn:
        conn.execute(_t(
            "INSERT INTO clipboard_items (type, content, preview, hash,"
            " favorite, pinned, created_at, updated_at) VALUES"
            " ('text', 'keep me', 'keep', 'hk', 0, 0, datetime('now'), datetime('now'))"))
        clip_id = conn.execute(_t("SELECT id FROM clipboard_items")).scalar()

    # 加入两次幂等
    assert collection_service.add_item(engine, cid, clip_id) is True
    assert collection_service.add_item(engine, cid, clip_id) is True
    items = collection_service.list_items(engine, cid)
    assert len(items) == 1
    assert items[0].content == "keep me"
    assert items[0].id == clip_id

    # 移除
    assert collection_service.remove_item(engine, cid, clip_id) is True
    assert collection_service.list_items(engine, cid) == []
    assert collection_service.remove_item(engine, cid, clip_id) is False

    # id=0 保护
    assert collection_service.add_item(engine, 0, 0) is False


def test_collection_delete_cascades(engine):
    """删除收藏夹级联清理关联（FK ON DELETE CASCADE）。"""
    from services import collection_service
    from sqlalchemy import text as _t

    cid = collection_service.create_collection(engine, "临时")
    with engine.begin() as conn:
        conn.execute(_t(
            "INSERT INTO clipboard_items (type, content, preview, hash,"
            " favorite, pinned, created_at, updated_at) VALUES"
            " ('text', 'x', 'x', 'hx', 0, 0, datetime('now'), datetime('now'))"))
        clip_id = conn.execute(_t("SELECT id FROM clipboard_items")).scalar()
    collection_service.add_item(engine, cid, clip_id)
    collection_service.delete_collection(engine, cid)
    with engine.connect() as conn:
        count = conn.execute(
            _t("SELECT COUNT(*) FROM collection_items")).scalar()
    assert count == 0  # 级联已清理


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
