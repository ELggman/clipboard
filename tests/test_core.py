"""核心服务测试（pytest）：配置 / Actions 插件 / Snippet 变量 / FTS5 搜索。

UI 层暂走人工验收（DEVELOPMENT.md §8 开发规范第 6 条）。
运行：.venv/bin/python -m pytest
"""
import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture()
def engine(tmp_path):
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "test.db")
    migrate(eng)
    yield eng
    eng.dispose()


# ---- 配置 ----

def test_config_defaults():
    from app.config import load_config

    cfg = load_config()
    assert cfg["history"]["max_items"] == 500
    assert cfg["history"]["poll_interval"] == 0.2
    assert cfg["hotkey"]["keycode"] == 9


# ---- Actions 插件体系 ----

def test_actions_loaded():
    from actions import load_actions

    acts = load_actions()
    ids = {a.id for a in acts}
    assert len(acts) == 11
    assert {"json_pretty", "base64_encode", "base64_decode",
            "url_encode", "url_decode", "markdown_preview", "sort_lines",
            "remove_duplicate_lines", "upper_case", "lower_case", "trim_space"} == ids


def test_json_pretty_action():
    from actions import load_actions
    from app.types import ClipboardItem, TEXT

    item = ClipboardItem(type=TEXT, content='{"a":1}')
    action = next(a for a in load_actions() if a.id == "json_pretty")
    assert action.can_handle(item)
    assert action.execute(item) == '{\n  "a": 1\n}'


def test_action_service_executes_and_filters():
    from actions import load_actions
    from app.types import ClipboardItem, IMAGE
    from services.action_service import ActionService

    service = ActionService()
    item = ClipboardItem(type=IMAGE, data=b"x")
    assert service.actions_for(item) == []  # 无图片 Action，不应出现文本 Action
    text_item = ClipboardItem(type="text", content="hello")
    assert {a.id for a in service.actions_for(text_item)} >= {"upper_case", "lower_case"}


# ---- Snippet 变量 ----

def test_snippet_variables():
    from services.snippet_service import render_snippet

    now = datetime.datetime(2026, 8, 6, 14, 30)
    assert render_snippet("Today: {{date}}", now=now) == "Today: 2026-08-06"
    assert render_snippet("{{foo}}") == "{{foo}}"  # 未知变量原样保留
    assert render_snippet("{{uuid}}").count("-") == 4


# ---- FTS5 搜索 ----

def test_search_fts5(engine):
    from datetime import datetime as dt

    from sqlalchemy import text

    from services.search_service import SearchService

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items "
                 "(type, content, preview, hash, favorite, pinned, created_at, updated_at) "
                 "VALUES ('text', 'mysql install notes', 'mysql install', 'h1', 0, 0, :now, :now)"),
            {"now": dt.now()},
        )
        rid = conn.execute(text("SELECT id FROM clipboard_items LIMIT 1")).scalar()

    svc = SearchService(engine)
    svc.reindex(rid, "mysql install notes")
    assert svc.search("mysql") == [rid]
    assert svc.search("docker") == []
    assert svc.search("") == []


def test_search_regex(engine):
    from datetime import datetime as dt

    from sqlalchemy import text

    from services.search_service import SearchService

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items "
                 "(type, content, preview, hash, favorite, pinned, created_at, updated_at) "
                 "VALUES ('text', 'Hello World', 'hw', 'h2', 0, 0, :now, :now)"),
            {"now": dt.now()},
        )

    svc = SearchService(engine)
    hits = svc.search(r"^hello", regex=True, ignore_case=True)
    assert len(hits) == 1
    assert svc.search("[invalid", regex=True) == []  # 无效正则不崩
