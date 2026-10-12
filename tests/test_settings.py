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

    removed_files, deleted = history_service.delete_older_than(engine, days=30)
    with engine.connect() as conn:
        remaining = [r[0] for r in conn.execute(
            text("SELECT content FROM clipboard_items")).fetchall()]
    assert (removed_files, deleted) == ([], 1)  # 文本条目没有文件，但确实删了 1 条
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
    removed_files, deleted = history_service.delete_older_than(engine, days=30)
    assert removed_files == [str(img)]  # 返回图片路径供清理
    assert deleted == 1


def test_trim_history(engine_factory):
    """设置页立即裁剪：**每个会话独立**裁剪到上限（v5 语义）。"""
    import hashlib

    from app.types import ClipboardItem
    from services import history_service, session_service
    from sqlalchemy import text

    engine = engine_factory()
    session_service.ensure_default(engine)
    sid = session_service.create_session(engine, "任务")
    for i in range(5):
        conn_item = ClipboardItem(type="text", content=f"item {i}",
                                  session_id=1)
        conn_item.hash = hashlib.sha256(f"item {i}".encode()).hexdigest()
        history_service.save_item(engine, conn_item)
    for i in range(5):
        conn_item = ClipboardItem(type="text", content=f"task {i}",
                                  session_id=sid)
        conn_item.hash = hashlib.sha256(f"task {i}".encode()).hexdigest()
        history_service.save_item(engine, conn_item)

    deleted = history_service.trim_history(engine, 3)
    assert deleted == 4  # 两个会话各裁 2 条
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM clipboard_items")).scalar()
    assert count == 6  # 每会话各留 3 条
    assert len(history_service.list_recent(engine, session_id=1)) == 3
    assert len(history_service.list_recent(engine, session_id=sid)) == 3


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

def test_settings_view_load_does_not_write_config(tmp_path):
    """装载配置必须屏蔽控件信号：否则打开一次设置页就把当前值钉进 settings.yaml，
    以后改 defaults.yaml 的默认值对老用户再也不生效（回归）。"""
    from ui.settings_view import SettingsView

    config = {
        "app": {"theme": "system", "font_size": 14, "launch_at_login": False},
        "history": {"max_items": 500, "auto_delete_days": 30,
                    "save_images": True, "show_image_filename": True},
        "privacy": {"policy": "warn", "temp_minutes": 5, "block_private_key": True,
                    "ignored_apps": []},
    }
    applied = {}
    appliers = {k: (lambda o, k=k: applied.__setitem__(k, o)) for k in
                ("theme", "font", "show_filename", "autostart", "max_items",
                 "privacy_block_private_key", "privacy_policy", "privacy_temp")}
    cfg_path = tmp_path / "settings.yaml"

    view = SettingsView()
    view.set_context(config, appliers, cfg_path)
    assert not cfg_path.exists()  # 装载不写盘
    assert applied == {}          # 也不回调 applier

    # 用户真的改一下 → 才写盘
    view._block_private_key.setChecked(False)
    assert applied["privacy_block_private_key"]["privacy"]["block_private_key"] is False
    assert "block_private_key: false" in cfg_path.read_text(encoding="utf-8")
    view.close()


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


# ---- 暂停监控状态的持久化（§9.3）----

def test_privacy_state_restores_paused():
    """暂停状态可按配置恢复，toggle 时广播（重启后不能悄悄恢复记录）。"""
    from app.bootstrap import PrivacyState

    assert PrivacyState().paused is False          # 缺省仍是「监控中」
    state = PrivacyState(paused=True)
    assert state.paused is True
    seen = []
    state.changed.connect(seen.append)
    state.toggle()
    assert state.paused is False and seen == [False]


def test_defaults_have_privacy_flags():
    """defaults.yaml 提供 privacy.paused 与 block_private_key 默认值。"""
    import yaml

    from app.config import CONFIG_DIR

    data = yaml.safe_load(
        (CONFIG_DIR / "defaults.yaml").read_text(encoding="utf-8"))
    assert data["privacy"]["paused"] is False
    assert data["privacy"]["block_private_key"] is True


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


def test_privacy_exclusion_matches_bundle_id():
    """忽略条目带 bundle id 时，按 bundle id 命中——localizedName() 随系统语言变，
    只存名字的话中文系统下（微信 = 「微信」）排除会静默失效（§9.5）。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    ignored = [{"name": "WeChat", "bundle_id": "com.tencent.xinWeChat"}]
    cfg = _privacy_config(ignored_apps=ignored)

    # 系统语言变了：名字对不上，但 bundle id 对得上 → 仍然排除
    item = ClipboardItem(type="text", content="x", source_app="微信",
                         source_app_id="com.tencent.xinWeChat")
    item.hash = hashlib.sha256(b"x").hexdigest()
    assert apply_privacy_policy(item, cfg) == "excluded"

    # 名字命中（bundle id 拿不到）也要排除
    item2 = ClipboardItem(type="text", content="y", source_app="WeChat")
    item2.hash = hashlib.sha256(b"y").hexdigest()
    assert apply_privacy_policy(item2, cfg) == "excluded"

    # 大小写/空白差异照样命中
    item3 = ClipboardItem(type="text", content="z", source_app=" wechat ")
    item3.hash = hashlib.sha256(b"z").hexdigest()
    assert apply_privacy_policy(item3, cfg) == "excluded"


def test_privacy_exclusion_unknown_app_saves():
    """身份取不到（前台应用获取失败）时宁可保存：漏保存是静默丢数据。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    item = ClipboardItem(type="text", content="plain note")
    item.hash = hashlib.sha256(b"n").hexdigest()
    assert apply_privacy_policy(
        item, _privacy_config(ignored_apps=["1Password"])) == "save"


def test_privacy_private_key_not_saved_by_default():
    """§9.15：私钥默认不保存——默认策略下自动升级为 ignore。"""
    import hashlib

    from app.bootstrap import apply_privacy_policy
    from app.types import ClipboardItem

    pem = ("-----BEGIN PRIVATE KEY-----\n"
           "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ\n"
           "-----END PRIVATE KEY-----")
    item = ClipboardItem(type="text", content=pem)
    item.hash = hashlib.sha256(b"k").hexdigest()
    assert apply_privacy_policy(item, _privacy_config()) == "sensitive_ignore"

    # 关掉「私钥不保存」开关 → 回到 warn 语义：保存但标记遮蔽
    item2 = ClipboardItem(type="text", content=pem)
    item2.hash = hashlib.sha256(b"k").hexdigest()
    assert apply_privacy_policy(
        item2, _privacy_config(block_private_key=False)) == "save"
    assert item2.sensitive == 1
    assert item2.sensitive_type == "private_key"

    # 用户显式选 save_temporarily 时以用户选择为准（只升级默认的 warn）
    item3 = ClipboardItem(type="text", content=pem)
    item3.hash = hashlib.sha256(b"k").hexdigest()
    assert apply_privacy_policy(
        item3, _privacy_config(policy="save_temporarily")) == "save"
    assert item3.expires_at != ""


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


def test_settings_scroll_speed_persists_and_applies(tmp_path):
    """滚动速度：装载不误写、改动写回配置、applier 收到回调（改动即生效）。"""
    import yaml

    from ui.settings_view import SettingsView

    config = {
        "app": {"theme": "system", "font_size": 14, "launch_at_login": False,
                "scroll_speed": 0.5},
        "history": {"max_items": 500, "auto_delete_days": 30},
        "privacy": {"policy": "warn", "temp_minutes": 5, "ignored_apps": []},
    }
    cfg_path = tmp_path / "settings.yaml"
    applied: list[dict] = []
    view = SettingsView()
    view.set_context(config, {"scroll_speed": applied.append}, cfg_path)
    assert view._scroll_speed.currentData() == 0.5  # 按配置选中
    assert not applied  # 装载不触发回调（否则打开设置页就把默认值钉死）

    view._scroll_speed.setCurrentIndex(view._scroll_speed.findData(1.0))
    assert applied and applied[-1]["app"]["scroll_speed"] == 1.0
    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert saved["app"]["scroll_speed"] == 1.0
    view.close()


def test_defaults_provide_scroll_speed():
    """defaults.yaml 必须带 app.scroll_speed——缺了它老用户会静默按原生跑。"""
    import yaml

    from app.config import CONFIG_DIR

    data = yaml.safe_load(
        (CONFIG_DIR / "defaults.yaml").read_text(encoding="utf-8"))
    assert data["app"]["scroll_speed"] == 0.5


def test_settings_scroll_effects_persist_and_apply(tmp_path):
    """滚动装饰：逐项开关写回配置、applier 收到回调（改动即生效）。"""
    import yaml

    from ui.settings_view import SettingsView

    config = {
        "app": {"theme": "system", "font_size": 14, "launch_at_login": False,
                "scroll_speed": 0.5,
                "scroll_effects": {"scrollbar": True, "edge_fade": False,
                                   "parallax": True, "depth": True, "lift": True}},
        "history": {"max_items": 500, "auto_delete_days": 30},
        "privacy": {"policy": "warn", "temp_minutes": 5, "ignored_apps": []},
    }
    cfg_path = tmp_path / "settings.yaml"
    applied: list[dict] = []
    view = SettingsView()
    view.set_context(config, {"scroll_effects": applied.append}, cfg_path)
    # 装载按配置回显，且不触发回调
    assert view._scroll_fx["scrollbar"].isChecked()
    assert not view._scroll_fx["edge_fade"].isChecked()
    assert not applied

    view._scroll_fx["edge_fade"].setChecked(True)
    assert applied and applied[-1]["app"]["scroll_effects"]["edge_fade"] is True
    saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    assert saved["app"]["scroll_effects"] == {
        "scrollbar": True, "edge_fade": True, "parallax": True,
        "depth": True, "lift": True}
    view.close()


def test_defaults_provide_scroll_effects():
    """defaults.yaml 必须带全部五项——缺项会按「默认开」回显，但配置里没写，
    用户关掉一项后 defaults 再加新项就永远读不到。"""
    import yaml

    from app.config import CONFIG_DIR

    data = yaml.safe_load(
        (CONFIG_DIR / "defaults.yaml").read_text(encoding="utf-8"))
    assert data["app"]["scroll_effects"] == {
        "scrollbar": True, "edge_fade": True, "parallax": True,
        "depth": True, "lift": True}


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


def test_thumbnail_retries_after_file_appears(tmp_path):
    """缩略图失败不缓存：文件随后出现时重试成功（回归）。

    之前 @lru_cache 缓存 None 返回值：文件缺失的失败被永久缓存，
    文件重建后历史/收藏全部缩略图消失，重启才恢复。
    """
    from io import BytesIO

    from PIL import Image

    from services.image_service import ImageService

    svc = ImageService(tmp_path / "img")
    target = svc._dir / "later.png"
    assert svc.thumbnail(str(target)) is None  # 文件缺失 → 失败

    buf = BytesIO()
    Image.new("RGB", (32, 32), "red").save(buf, "PNG")
    target.write_bytes(buf.getvalue())
    qimg = svc.thumbnail(str(target))
    assert qimg is not None and not qimg.isNull()  # 重试成功（未毒化）
