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


# ---- 隐私管线决策（新增.md §9.5-9.17）----

def _privacy_config(**overrides) -> dict:
    cfg = {"policy": "warn", "temp_minutes": 5, "ignored_apps": []}
    cfg.update(overrides)
    return cfg


def test_privacy_pipeline_excluded_app():
    """来源应用在忽略列表 → 不保存（§9.6）。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    item = ClipboardItem(type="text", content="secret from app",
                         source_app="1Password")
    item.hash = hashlib.sha256(b"x").hexdigest()
    decision = apply_privacy_policy(item, _privacy_config(ignored_apps=["1Password"]))
    assert decision == "excluded"
    assert item.sensitive == 0  # 未进入检测


def test_privacy_pipeline_warn_marks_sensitive():
    """warn（默认）：保存但置 sensitive 标记（§9.17）。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    item = ClipboardItem(type="text", content="OPENAI_API_KEY=sk-1234567890abcdef")
    item.hash = hashlib.sha256(b"x").hexdigest()
    assert apply_privacy_policy(item, _privacy_config()) == "save"
    assert item.sensitive == 1
    assert item.sensitive_type == "api_key"
    assert item.expires_at == ""  # warn 不过期


def test_privacy_pipeline_ignore_skips():
    """ignore：不保存（§9.17）。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    item = ClipboardItem(type="text", content="password='hunter2secret'")
    item.hash = hashlib.sha256(b"x").hexdigest()
    decision = apply_privacy_policy(item, _privacy_config(policy="ignore"))
    assert decision == "sensitive_ignore"


def test_privacy_pipeline_save_temporarily_sets_expiry():
    """save_temporarily：保存并设置 expires_at（§9.9/§9.17）。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    item = ClipboardItem(type="text", content="token=abcdefghijklmnopqrstuvwxyz123")
    item.hash = hashlib.sha256(b"x").hexdigest()
    decision = apply_privacy_policy(
        item, _privacy_config(policy="save_temporarily", temp_minutes=10))
    assert decision == "save"
    assert item.sensitive == 1
    assert item.expires_at != ""


def test_privacy_pipeline_plain_content_passes():
    """普通内容不受影响（§9.7：无法判断来源也不丢弃）。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    item = ClipboardItem(type="text", content="hello world")
    item.hash = hashlib.sha256(b"x").hexdigest()
    assert apply_privacy_policy(item, _privacy_config()) == "save"
    assert item.sensitive == 0


# ---- 文档大小上限（设置可调）----

def test_file_too_large_check(tmp_path):
    """超过上限的文件跳过；未超/不限制/不可读不跳过。"""
    from app.bootstrap import file_too_large
    from app.types import ClipboardItem

    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * (5 * 1024 * 1024))  # 5MB
    small = tmp_path / "small.pdf"
    small.write_bytes(b"pdf content")
    missing = tmp_path / "gone.bin"

    assert file_too_large(ClipboardItem(type="file", file_path=str(big)), 1) is True
    assert file_too_large(ClipboardItem(type="file", file_path=str(small)), 1) is False
    assert file_too_large(ClipboardItem(type="file", file_path=str(big)), 0) is False  # 不限制
    assert file_too_large(ClipboardItem(type="file", file_path=str(missing)), 1) is False  # 不可读
    assert file_too_large(ClipboardItem(type="text", content="x" * 100), 1) is False  # 仅文件


def test_settings_view_has_scroll_area(tmp_path):
    """设置页内容包在 QScrollArea 中：小窗口下可滚动而非挤压。"""
    from PySide6.QtWidgets import QScrollArea

    from ui.settings_view import SettingsView

    view = SettingsView()
    view.resize(380, 500)
    view.show()
    assert isinstance(view.findChild(QScrollArea), QScrollArea)
    # 所有表单行都在滚动容器内
    assert view._file_size.isVisible()
    assert view._pause_btn.isVisible()
    view.close()


def test_settings_file_size_persists(tmp_path):
    """文件大小上限设置写回配置。"""
    import yaml

    from ui.settings_view import SettingsView

    config = {
        "app": {"theme": "system", "font_size": 14, "launch_at_login": False},
        "history": {"max_items": 500, "auto_delete_days": 30,
                    "save_images": True, "show_image_filename": True,
                    "max_file_size_mb": 50},
        "privacy": {"policy": "warn", "temp_minutes": 5, "ignored_apps": []},
    }
    cfg_path = tmp_path / "settings.yaml"
    view = SettingsView()
    view.set_context(config, {}, cfg_path)
    view._file_size.setCurrentIndex(view._file_size.findData(200))  # 200 MB
    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert saved["history"]["max_file_size_mb"] == 200
    view.close()


# ---- 删除保护（数据丢失回归）----

def test_image_service_delete_protects_user_files(tmp_path):
    """删除历史只清理受管图片，绝不删用户原文档。

    回归：FILE 条目的 file_path 指向用户原始文档，清数据/右键删/
    自动清扫曾把它 unlink 掉 → 收藏快照指向空路径，粘贴失败。
    """
    from services.image_service import ImageService

    svc = ImageService(tmp_path / "images")
    managed = svc._dir / "abc.png"
    managed.write_bytes(b"img")
    user_file = tmp_path / "用户文档.pdf"
    user_file.write_bytes(b"pdf")

    svc.delete(str(managed))
    assert not managed.exists()  # 受管图片正常删除
    svc.delete(str(user_file))
    assert user_file.exists()    # 用户原文档被保护
    svc.delete_many([str(user_file)])
    assert user_file.exists()    # 批量删除同样保护
    assert svc.is_managed(str(managed)) and not svc.is_managed(str(user_file))
