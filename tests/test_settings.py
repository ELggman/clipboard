"""设置相关测试：配置写回、自动删除、开机启动、设置页控件。"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

pytest_app = QApplication.instance() or QApplication([])


@pytest.fixture()
def engine_factory(tmp_path):
    """每个用例独立的临时数据库引擎工厂。"""
    counter = {"n": 0}

    def _make():
        from database.engine import create_db_engine
        from database.migrations import migrate

        counter["n"] += 1
        eng = create_db_engine(tmp_path / f"t{counter['n']}.db")
        migrate(eng)
        return eng

    return _make


# ---- 配置写回 ----

def test_save_user_config_merges(tmp_path):
    from app.config import save_user_config

    cfg_path = tmp_path / "settings.yaml"
    save_user_config({"app": {"theme": "dark"}}, path=cfg_path)
    save_user_config({"history": {"max_items": 1000}}, path=cfg_path)
    text = cfg_path.read_text(encoding="utf-8")
    assert "dark" in text and "1000" in text  # 两次保存深度合并，不互相覆盖
    # 不覆盖 defaults 结构：load_config 可读
    from app.config import load_config

    # 直接验证 YAML 可加载
    import yaml

    loaded = yaml.safe_load(text)
    assert loaded["app"]["theme"] == "dark"
    assert loaded["history"]["max_items"] == 1000


# ---- 自动删除 ----

def test_delete_older_than(engine_factory):
    import datetime

    from services import history_service

    engine = engine_factory()
    # 用 raw insert 控制 created_at
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', 'old', 'old', 'ho', 0, 0, :t, :t)"),
            {"t": datetime.datetime.now() - datetime.timedelta(days=40)},
        )
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', 'old pinned', 'p', 'hp', 0, 1, :t, :t)"),
            {"t": datetime.datetime.now() - datetime.timedelta(days=40)},
        )
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at) VALUES"
                 " ('text', 'new', 'n', 'hn', 0, 0, :t, :t)"),
            {"t": datetime.datetime.now()},
        )
    with engine.connect() as conn:
        total = conn.execute(text("SELECT COUNT(*) FROM clipboard_items")).scalar()
    assert total == 3

    removed_files = history_service.delete_older_than(engine, days=30)
    with engine.connect() as conn:
        remaining = [r[0] for r in conn.execute(
            text("SELECT content FROM clipboard_items")).fetchall()]
    assert removed_files == []
    assert remaining == ["old pinned", "new"]  # 旧未置顶删除，置顶豁免，新保留


def test_delete_older_than_returns_image_paths(engine_factory, tmp_path):
    import datetime

    from services import history_service
    from sqlalchemy import text

    engine = engine_factory()
    img = tmp_path / "old.png"
    img.write_bytes(b"x")
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO clipboard_items (type, content, preview, hash,"
                 " favorite, pinned, created_at, updated_at, file_path) VALUES"
                 " ('image', '', 'old.png', 'hi', 0, 0, :t, :t, :f)"),
            {"t": datetime.datetime.now() - datetime.timedelta(days=40), "f": str(img)},
        )
    removed = history_service.delete_older_than(engine, days=30)
    assert removed == [str(img)]  # 返回图片路径供清理


def test_trim_history(engine_factory):
    from services import history_service
    from sqlalchemy import text

    engine = engine_factory()
    with engine.begin() as conn:
        for i in range(5):
            conn.execute(
                text("INSERT INTO clipboard_items (type, content, preview, hash,"
                     " favorite, pinned, created_at, updated_at) VALUES"
                     " ('text', :c, :c, :h, 0, 0, datetime('now'), datetime('now'))"),
                {"c": f"item {i}", "h": f"h{i}"},
            )
    deleted = history_service.trim_history(engine, 3)
    assert deleted == 2
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM clipboard_items")).scalar()
    assert count == 3


# ---- 开机启动 ----

def test_autostart_plist(tmp_path):
    from services import autostart

    plist = tmp_path / "com.clipboardworkspace.app.plist"
    assert autostart.is_enabled(plist) is False
    assert autostart.set_enabled(True, plist_path=plist, python=Path("/bin/echo"),
                                 script=Path("/tmp/main.py")) is True
    assert plist.exists()
    assert autostart.is_enabled(plist) is True
    import plistlib

    payload = plistlib.loads(plist.read_bytes())
    assert payload["Label"] == "com.clipboardworkspace.app"
    assert payload["RunAtLoad"] is True

    assert autostart.set_enabled(False, plist_path=plist) is True
    assert not plist.exists()
    assert autostart.is_enabled(plist) is False


# ---- 设置页控件 ----

def test_settings_view_apply_and_persist(tmp_path):
    from ui.settings_view import SettingsView

    config = {
        "app": {"theme": "system", "font_size": 14, "launch_at_login": False},
        "history": {"max_items": 500, "auto_delete_days": 30,
                    "save_images": True, "show_image_filename": True},
    }
    applied = {}
    appliers = {k: (lambda o, k=k: applied.__setitem__(k, o)) for k in
                ("theme", "font", "show_filename", "autostart", "max_items")}
    cfg_path = tmp_path / "settings.yaml"

    view = SettingsView()
    view.set_context(config, appliers, cfg_path)
    assert view._theme.currentData() == "system"
    assert view._max_items.currentData() == 500

    # 切换主题 → applier 触发 + 写回配置
    view._theme.setCurrentIndex(2)  # dark
    assert applied.get("theme", {}).get("app", {}).get("theme") == "dark"
    assert "dark" in cfg_path.read_text(encoding="utf-8")

    # 切换历史上限
    view._max_items.setCurrentIndex(2)  # 1000
    assert applied.get("max_items", {}).get("history", {}).get("max_items") == 1000
