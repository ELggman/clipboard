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
    me = next(i for i in items if i["id"] == s_id)  # 列表含 4 个默认模板
    assert me["name"] == "email"
    assert me["description"] == "常用邮箱"
    assert me["shortcut"] == "email"  # 兼容层：shortcut 默认取 name 小写

    assert snippet_service.update_snippet(engine, s_id, "email2", "{{uuid}}@x.com", "新") is True
    me = next(i for i in snippet_service.list_snippets(engine) if i["id"] == s_id)
    assert me["name"] == "email2" and me["content"] == "{{uuid}}@x.com"

    assert snippet_service.delete_snippet(engine, s_id) is True
    assert s_id not in [i["id"] for i in snippet_service.list_snippets(engine)]
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
    # 「本周」桶只在周起点早于昨天时才有非今天/昨天的条目（周一周二周三
    # 的 3 天前条目已落上一周 → 无本周条目，周一测不到该桶）
    if now.weekday() >= 3:
        assert "本周" in labels
    # 40 天前归入「更早」的月份桶
    assert any("月" in l for l in labels)
    assert groups[0][1][0].content == "today"  # 组内最新在前


# ---- Code/Privacy v3 字段与迁移 ----

def test_save_item_roundtrips_v3_fields(engine):
    """v3 字段 save/load round-trip（language/sensitive/expires_at）。"""
    import datetime
    import hashlib

    from app.types import ClipboardItem
    from services import history_service

    item = ClipboardItem(
        type="code", content="def f():\n    pass",
        language="python", language_confidence=0.94,
        line_count=2, character_count=14, is_structured=0,
        sensitive=1, sensitive_type="api_key",
        expires_at=(datetime.datetime.now()
                    + datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S"))
    item.hash = hashlib.sha256(b"code sample").hexdigest()
    history_service.save_item(engine, item)

    loaded = history_service.list_recent(engine)[0]
    assert loaded.type == "code"
    assert loaded.language == "python"
    assert loaded.language_confidence == pytest.approx(0.94)
    assert loaded.line_count == 2
    assert loaded.character_count == 14
    assert loaded.sensitive == 1
    assert loaded.sensitive_type == "api_key"
    assert loaded.expires_at.startswith("202")


def test_migration_v3_from_v2(tmp_path):
    """v2 老库迁移 v3：新列存在、旧数据保留、user_version=3。"""
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "old.db")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE clipboard_items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " type VARCHAR(16) NOT NULL, content TEXT, preview TEXT,"
            " file_path TEXT, hash VARCHAR(64) UNIQUE NOT NULL,"
            " source_app VARCHAR(255), favorite INTEGER DEFAULT 0,"
            " pinned INTEGER DEFAULT 0,"
            " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
        conn.execute(text(
            "INSERT INTO clipboard_items (type, content, hash,"
            " created_at, updated_at) VALUES ('text', 'old row', 'abc123',"
            " datetime('now'), datetime('now'))"))
        conn.execute(text("PRAGMA user_version = 2"))

    migrate(eng)
    with eng.connect() as conn:
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        assert {"language", "language_confidence", "line_count", "sensitive",
                "sensitive_type", "expires_at", "session_id"} <= cols
        row = conn.execute(text("SELECT content FROM clipboard_items")).fetchone()
        assert row[0] == "old row"
        from database.migrations import _SCHEMA_VERSION

        assert conn.execute(text("PRAGMA user_version")).scalar() == _SCHEMA_VERSION
    eng.dispose()


def test_delete_expired(tmp_path):
    """临时条目过期删除；未过期保留（§9.9）。"""
    import datetime
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import history_service
    from app.types import ClipboardItem

    eng = create_db_engine(tmp_path / "exp.db")
    migrate(eng)
    expired = ClipboardItem(type="text", content="temp secret")
    expired.hash = hashlib.sha256(b"temp secret").hexdigest()
    future = ClipboardItem(type="text", content="still valid")
    future.hash = hashlib.sha256(b"still valid").hexdigest()
    history_service.save_item(eng, expired)
    history_service.save_item(eng, future)
    with eng.begin() as conn:
        conn.execute(text(
            "UPDATE clipboard_items SET expires_at = :t WHERE content = 'temp secret'"),
            {"t": datetime.datetime.now() - datetime.timedelta(minutes=10)})
        conn.execute(text(
            "UPDATE clipboard_items SET expires_at = :t WHERE content = 'still valid'"),
            {"t": datetime.datetime.now() + datetime.timedelta(minutes=30)})

    removed_files, deleted = history_service.delete_expired(eng)
    assert (removed_files, deleted) == ([], 1)  # 文本条目没有文件路径，但过期那条确实删了
    with eng.connect() as conn:
        remaining = [r[0] for r in conn.execute(
            text("SELECT content FROM clipboard_items")).fetchall()]
    assert remaining == ["still valid"]
    eng.dispose()


def test_collection_image_survives_history_delete(tmp_path):
    """收藏图片不因历史删除而失效：被引用的图片文件保留（回归）。

    场景：复制图片 → 加入收藏 → 删除历史图片条目 → 收藏快照仍可粘贴。
    """
    import hashlib

    from database.engine import create_db_engine
    from database.migrations import migrate
    from services import collection_service, history_service
    from services.image_service import ImageService
    from app.types import ClipboardItem

    eng = create_db_engine(tmp_path / "ci.db")
    migrate(eng)
    svc = ImageService(tmp_path / "images")
    from io import BytesIO
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (16, 16), "red").save(buf, "PNG")
    img_path = svc.save(buf.getvalue())

    item = ClipboardItem(type="image", file_path=str(img_path),
                         preview="img.png")
    item.hash = hashlib.sha256(b"img data").hexdigest()
    history_service.save_item(eng, item)
    cid = collection_service.create_collection(eng, "图集")
    collection_service.add_item(eng, cid, item)

    # 删除历史图片条目 → 文件应保留（被收藏引用）
    files = history_service.delete_item(eng, item.id)
    assert img_path.exists()  # 收藏引用保护
    # 无引用时正常删除（对照）
    orphan = svc._dir / "orphan.png"
    orphan.write_bytes(b"x")
    history_service.delete_item(eng, item.id)  # 行已删，无副作用
    assert not collection_service.is_file_path_referenced(eng, str(orphan))
    eng.dispose()


def test_wechat_url_not_sensitive():
    """微信分享链接的 token= 查询参数不应误判为敏感（回归）。"""
    from services.sensitive_detector import detect

    url = ("https://mp.weixin.qq.com/s?__biz=MzIxNjkzMDA0NQ==&mid=2650000000"
           "&idx=1&sn=abcdef1234567890&token=9876543210abcdef")
    assert detect(url) is None
    assert detect("https://example.com/article?id=42&key=abcdefghijklmnopqrst") is None
    # 非 URL 的 token= 赋值仍然检测
    from services.sensitive_detector import TOKEN

    r = detect("token=abcdefghijklmnopqrstuvwxyz123")
    assert r is not None and r.sensitive_type == TOKEN


def test_set_sensitive_manual_roundtrip(engine):
    """手动标记敏感：set_sensitive 写库 + manual 类型遮蔽。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service
    from services.sensitive_detector import MANUAL, mask

    item = ClipboardItem(type="text", content="my private note")
    item.hash = hashlib.sha256(b"my private note").hexdigest()
    history_service.save_item(engine, item)

    assert history_service.set_sensitive(engine, item.id, True) is True
    loaded = history_service.list_recent(engine)[0]
    assert loaded.sensitive == 1
    assert loaded.sensitive_type == MANUAL
    assert "private note" not in mask(loaded.content, loaded.sensitive_type)

    assert history_service.set_sensitive(engine, item.id, False) is True
    loaded = history_service.list_recent(engine)[0]
    assert loaded.sensitive == 0 and loaded.sensitive_type == ""


# ---- v6 迁移：模板模块（原片段）----

def test_migration_v6_snippets_to_templates(tmp_path):
    """v5 → v6：snippets 表重建（shortcut 回填）+ snippet_folders + 默认模板。"""
    from database.engine import create_db_engine
    from database.migrations import _SCHEMA_VERSION, migrate

    eng = create_db_engine(tmp_path / "old.db")
    with eng.begin() as conn:
        # 老版本 snippets 表（v5：无 shortcut/folder/enabled 等列）
        conn.execute(text(
            "CREATE TABLE snippets ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name VARCHAR(128) NOT NULL, content TEXT NOT NULL,"
            " description TEXT, created_at DATETIME NOT NULL)"))
        conn.execute(text(
            "INSERT INTO snippets (name, content, description, created_at)"
            " VALUES ('邮箱签名', 'Best regards', '工作用', '2026-01-01 10:00:00')"))
        conn.execute(text(
            "INSERT INTO snippets (name, content, created_at)"
            " VALUES ('邮箱签名', '重复名', '2026-01-02 10:00:00')"))
        conn.execute(text("PRAGMA user_version = 5"))

    migrate(eng)
    with eng.connect() as conn:
        assert conn.execute(text("PRAGMA user_version")).scalar() == _SCHEMA_VERSION
        # 旧数据保留 + shortcut 回填（冲突加 _id 后缀）
        rows = conn.execute(text(
            "SELECT name, shortcut, content, description FROM snippets"
            " WHERE name LIKE '邮箱签名%' ORDER BY id")).fetchall()
        assert len(rows) == 2
        assert rows[0].shortcut == "邮箱签名"
        assert rows[1].shortcut.startswith("邮箱签名_")
        assert rows[0].description == "工作用"  # description 保留
        # 新列默认值
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(snippets)")).fetchall()}
        for c in ("enabled", "favorite", "trigger_mode", "usage_count",
                  "last_used_at", "updated_at", "folder_id"):
            assert c in cols
        # 默认文件夹
        folders = conn.execute(text(
            "SELECT name FROM snippet_folders ORDER BY id")).fetchall()
        assert "个人" in [f[0] for f in folders]
        # 默认示例模板
        scs = conn.execute(text(
            "SELECT shortcut FROM snippets WHERE shortcut IN"
            " ('shrug','today','uuid','quote')")).fetchall()
        assert len(scs) == 4
    eng.dispose()


def test_migration_v6_idempotent(tmp_path):
    """v6 迁移幂等：重复运行不崩、数据不重复。"""
    from database.engine import create_db_engine
    from database.migrations import _SCHEMA_VERSION, migrate

    eng = create_db_engine(tmp_path / "idem.db")
    migrate(eng)
    migrate(eng)  # 第二次
    with eng.connect() as conn:
        # 默认模板不重复（shortcut 唯一保护）
        count = conn.execute(text(
            "SELECT COUNT(*) FROM snippets WHERE shortcut='shrug'")).scalar()
        assert count == 1
        assert conn.execute(text(
            "PRAGMA user_version")).scalar() == _SCHEMA_VERSION
    eng.dispose()


# ---- v9 迁移：撤回发货的变换模板 ----

def _seed_v8_shipped(eng) -> int:
    """造出「库里已经有 v8 那批发货变换模板」的状态，返回「变换」文件夹 id。

    迁移链里**已经不会**再种这批模板了（v8 那一步整个删掉），所以想测 v9 的
    撤回行为只能手工把它摆回来——真实用户库正是这个状态。
    """
    from database.migrations import (WITHDRAWN_TEMPLATES_FOLDER,
                                     _WITHDRAWN_TEMPLATES)

    with eng.begin() as conn:
        conn.execute(text(
            "INSERT INTO snippet_folders (name, created_at, updated_at)"
            " VALUES (:n, datetime('now'), datetime('now'))"),
            {"n": WITHDRAWN_TEMPLATES_FOLDER})
        fid = conn.execute(text(
            "SELECT id FROM snippet_folders WHERE name = :n"),
            {"n": WITHDRAWN_TEMPLATES_FOLDER}).scalar()
        for name, sc, content, desc in _WITHDRAWN_TEMPLATES:
            conn.execute(text(
                "INSERT INTO snippets (name, shortcut, content, description,"
                " folder_id, enabled, favorite, trigger_mode, usage_count,"
                " last_used_at, created_at, updated_at)"
                " VALUES (:n, :sc, :c, :d, :f, 1, 0, 'tab', 0, NULL,"
                " datetime('now'), datetime('now'))"),
                {"n": name, "sc": sc, "c": content, "d": desc, "f": fid})
        conn.execute(text("PRAGMA user_version = 8"))
    return fid


def test_migration_fresh_db_has_no_shipped_templates(tmp_path):
    """全新库只有默认模板：发货变换模板不再种入（v8 那一步已整个删掉）。"""
    from database.engine import create_db_engine
    from database.migrations import (WITHDRAWN_TEMPLATES_FOLDER,
                                     _DEFAULT_TEMPLATES, _SCHEMA_VERSION,
                                     migrate)

    eng = create_db_engine(tmp_path / "fresh.db")
    migrate(eng)
    with eng.connect() as conn:
        assert conn.execute(text(
            "PRAGMA user_version")).scalar() == _SCHEMA_VERSION
        assert conn.execute(text(
            "SELECT COUNT(*) FROM snippet_folders WHERE name = :n"),
            {"n": WITHDRAWN_TEMPLATES_FOLDER}).scalar() == 0
        got = {r[0] for r in conn.execute(
            text("SELECT shortcut FROM snippets")).fetchall()}
        assert got == {t[1] for t in _DEFAULT_TEMPLATES}
    eng.dispose()


def test_migration_v9_withdraws_shipped_templates(tmp_path):
    """v8 → v9：整批撤回（连「变换」文件夹一起删），且可重复跑。"""
    from database.engine import create_db_engine
    from database.migrations import (WITHDRAWN_TEMPLATES_FOLDER,
                                     _DEFAULT_TEMPLATES, _SCHEMA_VERSION,
                                     _WITHDRAWN_TEMPLATES, migrate)

    eng = create_db_engine(tmp_path / "v9.db")
    migrate(eng)
    fid = _seed_v8_shipped(eng)
    with eng.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM snippets WHERE folder_id = :f"),
            {"f": fid}).scalar() == len(_WITHDRAWN_TEMPLATES)

    migrate(eng)
    migrate(eng)   # 第二遍：找不到文件夹，直接返回（幂等）
    with eng.connect() as conn:
        assert conn.execute(text(
            "PRAGMA user_version")).scalar() == _SCHEMA_VERSION
        assert conn.execute(text(
            "SELECT COUNT(*) FROM snippet_folders WHERE name = :n"),
            {"n": WITHDRAWN_TEMPLATES_FOLDER}).scalar() == 0
        got = {r[0] for r in conn.execute(
            text("SELECT shortcut FROM snippets")).fetchall()}
        assert got == {t[1] for t in _DEFAULT_TEMPLATES}
    eng.dispose()


def test_migration_v9_keeps_user_edits_and_own_rows(tmp_path):
    """只删「原样没动过」的行——用户改过的、自己在「变换」里加的都留下。

    迁移的整洁不该覆盖用户的工作：判据是 name/shortcut/content 三项都与当初
    一致才删（改过一个字就留），文件夹里还有东西就不删文件夹。
    """
    from database.engine import create_db_engine
    from database.migrations import (
        _SCHEMA_VERSION, _WITHDRAWN_TEMPLATES, migrate)

    eng = create_db_engine(tmp_path / "v9keep.db")
    migrate(eng)
    fid = _seed_v8_shipped(eng)
    taken = _WITHDRAWN_TEMPLATES[0][1]          # 第一个发货模板的 shortcut
    edited = _WITHDRAWN_TEMPLATES[1][1]         # 第二个：留着改成用户自己的
    with eng.begin() as conn:
        # ① 用户改过一个发货模板（改名字）
        conn.execute(text(
            "UPDATE snippets SET name = '我的小写' WHERE folder_id = :f"
            " AND shortcut = :sc"), {"f": fid, "sc": edited})
        # ② 用户在「变换」文件夹里自建了一个
        conn.execute(text(
            "INSERT INTO snippets (name, shortcut, content, folder_id,"
            " created_at, updated_at) VALUES ('我加的', 'mine', '内容', :f,"
            " datetime('now'), datetime('now'))"), {"f": fid})
        # ③ 用户早占了这个 shortcut（v8 当年就得让位），且不在「变换」里
        conn.execute(text("DELETE FROM snippets WHERE shortcut = :sc"),
                     {"sc": taken})
        conn.execute(text(
            "INSERT INTO snippets (name, shortcut, content, created_at,"
            " updated_at) VALUES ('我的 up', :sc, '用户内容',"
            " datetime('now'), datetime('now'))"), {"sc": taken})

    migrate(eng)
    with eng.connect() as conn:
        assert conn.execute(text(
            "PRAGMA user_version")).scalar() == _SCHEMA_VERSION
        # ①②：文件夹还在，里面剩两行
        assert conn.execute(text(
            "SELECT COUNT(*) FROM snippet_folders WHERE id = :f"),
            {"f": fid}).scalar() == 1
        left = {r[0] for r in conn.execute(text(
            "SELECT shortcut FROM snippets WHERE folder_id = :f"),
            {"f": fid}).fetchall()}
        assert left == {edited, "mine"}
        # ③：用户的 up 一个字符没动
        row = conn.execute(text(
            "SELECT name, content FROM snippets WHERE shortcut = :sc"),
            {"sc": taken}).fetchone()
        assert row[0] == "我的 up" and row[1] == "用户内容"
    eng.dispose()



def test_migration_v7_image_hash_normalize(tmp_path):
    """v7 迁移：TIFF 来源图片 hash 归一化——修正遗留 hash、折叠重复条目。

    复现用户场景：同一图片落盘到同一 PNG 文件，但存在两条记录——旧条目
    hash=digest(原始 TIFF 字节)、新条目 hash=digest(PNG 文件内容)。v7 应
    把旧条目修正为 canonical，或（一旦与同会话已存在行冲突）删除重复行。
    """
    import hashlib
    from io import BytesIO

    from PIL import Image

    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "img.db")
    migrate(eng)  # 建到 v7

    # 构造一张图：PNG 落盘文件（内容 = canonical digest 来源）
    buf = BytesIO()
    Image.new("RGB", (4, 4), (255, 0, 0)).save(buf, "PNG")
    png = buf.getvalue()
    canonical = hashlib.sha256(png).hexdigest()
    images = tmp_path / "images"
    images.mkdir(exist_ok=True)
    fpath = images / f"{canonical}.png"
    fpath.write_bytes(png)

    def _insert(hash_: str) -> None:
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO clipboard_items (type, file_path, hash,"
                " created_at, updated_at, session_id) VALUES"
                " ('image', :f, :h, datetime('now'), datetime('now'), 1)"),
                {"f": str(fpath), "h": hash_})

    # 旧条目：hash=digest(原始 TIFF 字节)（≠ canonical，模拟旧实现）
    old_hash = hashlib.sha256(b"fake-tiff-bytes").hexdigest()
    _insert(old_hash)
    # 新重复条：hash=canonical（Quick Paste 重复制已产生的重复）
    _insert(canonical)

    # 回退版本号使 v7 迁移重跑
    with eng.begin() as conn:
        conn.execute(text("PRAGMA user_version = 6"))
    migrate(eng)

    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT hash FROM clipboard_items WHERE type='image' ORDER BY id"
        )).fetchall()
        # 两条同图记录应折叠为 1 条，且 hash 归一到 canonical（PNG 内容 digest）
        assert len(rows) == 1, f"应折叠为 1 条 image，实得 {len(rows)}"
        assert rows[0][0] == canonical
        # 被删除行的 FTS 索引同步清理（外部内容表保持一致）
        fts = conn.execute(text(
            "SELECT COUNT(*) FROM items_fts WHERE rowid NOT IN"
            " (SELECT id FROM clipboard_items)")).scalar()
        assert fts == 0
    eng.dispose()


def test_image_service_save_canonical_png_name(tmp_path):
    """image_service.save：名 = **PNG 内容** digest——TIFF 来源与重复制闭环
    hash 一致（Q1 修复的前提）。"""
    import hashlib
    from io import BytesIO

    from PIL import Image

    from services.image_service import ImageService

    svc = ImageService(tmp_path / "images")
    img = Image.new("RGB", (3, 3), (0, 90, 200))
    tiff_buf, png_buf = BytesIO(), BytesIO()
    img.save(tiff_buf, "TIFF")
    img.save(png_buf, "PNG")
    tiff, png = tiff_buf.getvalue(), png_buf.getvalue()

    path = svc.save(tiff)  # TIFF 输入
    assert path.name == f"{hashlib.sha256(png).hexdigest()}.png"
    assert path.read_bytes() == png
    # 幂等：同一图像字节再存，复用同路径
    assert svc.save(tiff) == path
    assert svc.save(png) == path  # PNG 直存也归一为同一份
