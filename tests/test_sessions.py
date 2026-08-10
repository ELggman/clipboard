"""会话机制测试（v4）：默认会话、CRUD、删除移回普通、按会话隔离、搜索范围。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from sqlalchemy import text


@pytest.fixture()
def engine(tmp_path):
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "s.db")
    migrate(eng)
    yield eng
    eng.dispose()


# ---- 会话 CRUD ----

def test_ensure_default_idempotent(engine):
    from services import session_service

    sid = session_service.ensure_default(engine)
    assert sid == 1
    assert session_service.ensure_default(engine) == 1  # 幂等
    sessions = session_service.list_sessions(engine)
    assert sessions[0]["name"] == "普通"
    assert sessions[0]["is_default"] is True
    assert sessions[0]["count"] == 0


def test_session_crud(engine):
    from services import session_service

    sid = session_service.create_session(engine, "论文写作优化")
    assert sid > 1
    assert session_service.create_session(engine, "  ") == 0  # 空名拒绝
    sessions = {s["name"]: s for s in session_service.list_sessions(engine)}
    assert "论文写作优化" in sessions

    assert session_service.rename_session(engine, sid, "论文翻译") is True
    assert session_service.rename_session(engine, 1, "改名默认") is False  # 默认禁改名
    assert "论文翻译" in {s["name"] for s in session_service.list_sessions(engine)}

    assert session_service.delete_session(engine, sid)[0] is True
    assert session_service.delete_session(engine, 1)[0] is False  # 默认禁删
    assert "论文翻译" not in {s["name"] for s in session_service.list_sessions(engine)}


def test_delete_session_moves_items_to_default(engine):
    """删除会话：内容移回普通会话（不丢数据）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "任务")
    item = ClipboardItem(type="text", content="task content", session_id=sid)
    item.hash = hashlib.sha256(b"task content").hexdigest()
    history_service.save_item(engine, item)

    assert session_service.delete_session(engine, sid)[0] is True
    moved = history_service.list_recent(engine, session_id=1)
    assert [i.content for i in moved] == ["task content"]  # 移回普通
    assert history_service.list_recent(engine, session_id=sid) == []


def test_session_counts(engine):
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "A")
    for i in range(3):
        item = ClipboardItem(type="text", content=f"a{i}", session_id=sid)
        item.hash = hashlib.sha256(f"a{i}".encode()).hexdigest()
        history_service.save_item(engine, item)
    counts = {s["name"]: s["count"] for s in session_service.list_sessions(engine)}
    assert counts["A"] == 3
    assert counts["普通"] == 0


# ---- 按会话隔离 ----

def test_save_and_list_by_session(engine):
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "隔离测试")
    for content, sid_ in (("in default", 1), ("in task", sid)):
        item = ClipboardItem(type="text", content=content, session_id=sid_)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)

    assert [i.content for i in history_service.list_recent(engine, session_id=1)] \
        == ["in default"]
    assert [i.content for i in history_service.list_recent(engine, session_id=sid)] \
        == ["in task"]
    # None = 全部（旧调用兼容）
    assert len(history_service.list_recent(engine)) == 2

    # _to_item 携带 session_name（标签显示用）
    task_item = history_service.list_recent(engine, session_id=sid)[0]
    assert task_item.session_id == sid
    assert task_item.session_name == "隔离测试"


def test_search_scope_session(engine):
    """搜索范围：本会话 / 全局（FTS + CJK 两条路径）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "论文")
    for content, sid_ in (("mysql install", 1), ("mysql setup", sid),
                          ("数据库配置", 1), ("数据库迁移", sid)):
        item = ClipboardItem(type="text", content=content, session_id=sid_)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)

    # FTS 路径（ASCII）
    assert len(history_service.search_items(engine, "mysql")) == 2
    assert len(history_service.search_items(engine, "mysql",
                                            session_id=sid)) == 1
    # CJK 路径
    assert len(history_service.search_items(engine, "数据库")) == 2
    assert len(history_service.search_items(engine, "数据库",
                                            session_id=1)) == 1
    # 全局结果带 session_name
    global_results = history_service.search_items(engine, "mysql")
    names = {r.session_name for r in global_results}
    assert "论文" in names


def test_clean_data_by_session(engine):
    """清理数据按会话筛选。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "临时")
    for content, sid_ in (("keep", 1), ("temp", sid)):
        item = ClipboardItem(type="text", content=content, session_id=sid_)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)

    matched = history_service.list_older_than(engine, 0, session_id=sid)
    assert [i.content for i in matched] == ["temp"]
    assert len(history_service.list_older_than(engine, 0)) == 2


def test_migration_v4_defaults(engine):
    """v4 迁移：默认会话存在、session_id 列默认 1。"""
    from database.migrations import migrate

    # 已由 fixture migrate；验证表结构与默认值
    with engine.connect() as conn:
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        assert "session_id" in cols
        tables = {r[0] for r in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        assert "sessions" in tables
        name = conn.execute(text("SELECT name FROM sessions WHERE id = 1")).scalar()
        assert name == "普通"
        from database.migrations import _SCHEMA_VERSION

        assert conn.execute(text("PRAGMA user_version")).scalar() == _SCHEMA_VERSION


# ---- 去重范围（v5）与删除策略 ----

def test_dedupe_scope_all_cross_session(engine):
    """scope=all：跨会话同内容全局去重（默认语义，现状不变）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "A")
    item = ClipboardItem(type="text", content="same text", session_id=sid)
    item.hash = hashlib.sha256(b"same text").hexdigest()
    assert history_service.save_item(engine, item) is True
    item2 = ClipboardItem(type="text", content="same text", session_id=1)
    item2.hash = hashlib.sha256(b"same text").hexdigest()
    assert history_service.save_item(engine, item2, dedupe_scope="all") is False
    assert history_service.list_recent(engine, session_id=1) == []


def test_dedupe_scope_session_cross_session(engine):
    """scope=session：跨会话同内容可各存一份（新会话不再被全局去重吞掉）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "新任务")
    item = ClipboardItem(type="text", content="same image note", session_id=1)
    item.hash = hashlib.sha256(b"same image note").hexdigest()
    history_service.save_item(engine, item)

    item2 = ClipboardItem(type="text", content="same image note", session_id=sid)
    item2.hash = hashlib.sha256(b"same image note").hexdigest()
    assert history_service.save_item(engine, item2, dedupe_scope="session") is True
    assert len(history_service.list_recent(engine, session_id=sid)) == 1
    # 本会话内同内容仍去重
    item3 = ClipboardItem(type="text", content="same image note", session_id=sid)
    item3.hash = hashlib.sha256(b"same image note").hexdigest()
    assert history_service.save_item(engine, item3, dedupe_scope="session") is False


def test_delete_session_policy_delete(engine):
    """删除策略 delete：内容直接删除，返回待清理图片路径。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "临时")
    item = ClipboardItem(type="text", content="gone", session_id=sid)
    item.hash = hashlib.sha256(b"gone").hexdigest()
    history_service.save_item(engine, item)

    ok, files = session_service.delete_session(engine, sid, policy="delete")
    assert ok is True
    assert history_service.list_recent(engine, session_id=sid) == []
    assert history_service.list_recent(engine) == []


def test_delete_session_move_merges_duplicates(engine):
    """删除策略 move：与普通已有相同内容自动合并去重（不产生重复）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "合并")
    for content, sid_ in (("shared", 1), ("shared", sid), ("unique", sid)):
        item = ClipboardItem(type="text", content=content, session_id=sid_)
        item.hash = hashlib.sha256(content.encode()).hexdigest()
        history_service.save_item(engine, item)

    ok, _ = session_service.delete_session(engine, sid)
    assert ok is True
    contents = [i.content for i in history_service.list_recent(engine,
                                                               session_id=1)]
    assert sorted(contents) == ["shared", "unique"]  # shared 只保留一份


def test_image_reference_protection_across_sessions(tmp_path):
    """跨会话引用：删除一个会话的图片行，其他会话引用的文件保留。"""
    import hashlib
    from io import BytesIO

    from PIL import Image

    from app.types import ClipboardItem
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service, session_service
    from services.image_service import ImageService

    eng = create_db_engine(tmp_path / "img.db")
    migrate(eng)
    svc = ImageService(tmp_path / "images")
    buf = BytesIO()
    Image.new("RGB", (16, 16), "green").save(buf, "PNG")
    img_path = svc.save(buf.getvalue())

    sid = session_service.create_session(eng, "图")
    a = ClipboardItem(type="image", file_path=str(img_path), session_id=1)
    a.hash = hashlib.sha256(b"img a").hexdigest()
    b = ClipboardItem(type="image", file_path=str(img_path), session_id=sid)
    b.hash = hashlib.sha256(b"img b").hexdigest()
    history_service.save_item(eng, a)
    history_service.save_item(eng, b)

    # 删除普通会话的图片行 → 会话 sid 仍引用 → 文件保留
    history_service.delete_item(eng, a.id)
    assert not history_service.is_path_still_referenced(eng, str(img_path)) is False
    assert img_path.exists()
    # 删除会话 sid 的图片行 → 无引用 → 可清理
    history_service.delete_item(eng, b.id)
    assert history_service.is_path_still_referenced(eng, str(img_path)) is False
    eng.dispose()


def test_migration_v5_unique_hash_session(engine):
    """v5 迁移：唯一约束为 (hash, session_id)，跨会话同 hash 可共存。"""
    from sqlalchemy import text as _t

    with engine.connect() as conn:
        idx = conn.execute(_t("PRAGMA index_list(clipboard_items)")).fetchall()
        uniques = [r for r in idx if r[1].startswith("sqlite_autoindex")]
        assert len(uniques) == 1  # 仅 (hash, session_id) 联合唯一
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service

    sid = session_service.create_session(engine, "B")
    for sid_ in (1, sid):
        item = ClipboardItem(type="text", content="cross", session_id=sid_)
        item.hash = hashlib.sha256(b"cross").hexdigest()
        history_service.save_item(engine, item, dedupe_scope="session")
    assert len(history_service.list_recent(engine)) == 2  # 跨会话共存
