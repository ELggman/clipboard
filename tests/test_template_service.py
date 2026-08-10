"""模板服务测试：CRUD / shortcut 唯一 / 文件夹 / 搜索排序 / 使用统计。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.template.errors import TemplateError, UnknownVariableError
from services.template_service import TemplateService


@pytest.fixture()
def svc(tmp_path):
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "t.db")
    migrate(eng)
    yield TemplateService(eng)
    eng.dispose()


# ---- CRUD ----

def test_create_and_get(svc):
    tid = svc.create_template("Email", "email", "hello@example.com")
    t = svc.get_template(tid)
    assert t["name"] == "Email"
    assert t["shortcut"] == "email"
    assert t["enabled"] is True
    assert t["trigger_mode"] == "tab"
    assert t["usage_count"] == 0


def test_create_shortcut_normalized_lower(svc):
    tid = svc.create_template("Hey", "HEY", "hello")
    assert svc.get_template(tid)["shortcut"] == "hey"


def test_shortcut_conflict_raises(svc):
    svc.create_template("A", "dup2", "x")
    with pytest.raises(ValueError):
        svc.create_template("B", "dup2", "y")  # §8：不允许静默覆盖


def test_update_shortcut_conflict(svc):
    svc.create_template("A", "one2", "x")
    tid = svc.create_template("B", "two2", "y")
    with pytest.raises(ValueError):
        svc.update_template(tid, shortcut="one2")
    # 更新自身 shortcut 不变（排除自身）允许
    assert svc.update_template(tid, shortcut="two2") is True
    # 改为未占用
    assert svc.update_template(tid, shortcut="three2") is True


def test_invalid_content_raises(svc):
    with pytest.raises(UnknownVariableError):
        svc.create_template("Bad", "bad", "Hello {{abc}}")
    with pytest.raises(TemplateError):
        svc.create_template("Bad2", "bad2", "{{cursor}}{{cursor}}")


def test_update_and_delete(svc):
    tid = svc.create_template("A", "a1", "content")
    assert svc.update_template(tid, name="A2", content="new {{date}}") is True
    t = svc.get_template(tid)
    assert t["name"] == "A2"
    assert svc.delete_template(tid) is True
    assert svc.get_template(tid) is None
    assert svc.delete_template(tid) is False  # 不存在


# ---- 文件夹 ----

def test_folder_crud(svc):
    fid = svc.create_folder("Git")
    import sqlalchemy.exc

    with pytest.raises(sqlalchemy.exc.IntegrityError):
        svc.create_folder("Git")  # folder name UNIQUE
    folders = svc.list_folders()
    names = [f["name"] for f in folders]
    assert "Git" in names
    assert "个人" in names  # 默认文件夹（迁移插入）
    assert svc.rename_folder(fid, "GitHub") is True
    assert svc.rename_folder(9999, "x") is False


def test_delete_folder_moves_to_unfiled(svc):
    fid = svc.create_folder("Work")
    tid = svc.create_template("T", "t1", "x", folder_id=fid)
    assert svc.delete_folder(fid) is True
    assert svc.get_template(tid)["folder_id"] is None  # §14 默认移入未分类


def test_folder_filter(svc):
    fid = svc.create_folder("Work")
    svc.create_template("A", "a1", "x", folder_id=fid)
    svc.create_template("B", "b1x", "y")
    assert len(svc.list_templates(folder_id=fid)) == 1
    # 全部 = 2 个新建 + 4 个默认模板
    scs = {t["shortcut"] for t in svc.list_templates()}
    assert scs >= {"a1", "b1x", "shrug", "today", "uuid", "quote"}


# ---- 搜索排序（§19）----

def test_search_scoring_order(svc):
    svc.create_template("dockerlogs", "dockerlogs", "docker compose logs")
    svc.create_template("Git", "git", "git status")
    svc.create_template("docker-compose", "dc", "docker compose up")
    svc.create_template("Gitignore", "gi", "ignore docker files")
    results = svc.search_templates("docker")
    scs = [r["shortcut"] for r in results]
    assert scs[0] == "dockerlogs"  # shortcut 前缀 > name 前缀 > content


def test_search_exact_shortcut_first(svc):
    svc.create_template("A", "git", "x")
    svc.create_template("Git Branch", "gitb", "git checkout")
    results = svc.search_templates("git")
    assert results[0]["shortcut"] == "git"  # shortcut 精确 > 前缀


def test_search_favorite_and_recent_first(svc):
    svc.create_template("A", "aa", "x")
    svc.create_template("B", "ab", "x")
    svc.create_template("C", "ac", "x")
    svc.toggle_favorite(svc.get_template("x")["id"] if False else
                        svc.find_by_shortcut("aa")["id"])
    results = svc.search_templates("a")
    assert results[0]["shortcut"] == "aa"  # 收藏优先


def test_search_empty_query_returns_all(svc):
    svc.create_template("A", "a1x", "x")
    assert len(svc.search_templates("")) == 5  # 1 新建 + 4 默认


# ---- 快捷操作 ----

def test_find_by_shortcut_only_enabled(svc):
    svc.create_template("A", "onx", "x")
    tid = svc.create_template("B", "offx", "y")
    assert svc.find_by_shortcut("onx") is not None
    assert svc.find_by_shortcut("OFFX") is not None  # 大小写不敏感
    svc.toggle_enabled(tid)
    assert svc.find_by_shortcut("offx") is None  # 禁用不参与匹配（§15）


def test_record_usage(svc):
    tid = svc.create_template("A", "u1x", "x")
    svc.record_usage(tid)
    svc.record_usage(tid)
    t = svc.get_template(tid)
    assert t["usage_count"] == 2
    assert t["last_used_at"] is not None


def test_toggle_favorite(svc):
    tid = svc.create_template("A", "f1x", "x")
    assert svc.toggle_favorite(tid) is True
    assert svc.get_template(tid)["favorite"] is True
    assert svc.toggle_favorite(tid) is True
    assert svc.get_template(tid)["favorite"] is False


# ---- 渲染流水线 ----

def test_render_template_pipeline(svc):
    svc._read_clipboard = lambda: "Hello World"
    text, cursor, inputs = svc.render_template(
        "> {{clipboard}}\n\n{{cursor}}", now=__import__("datetime").datetime(2026, 8, 7))
    assert text == "> Hello World\n\n"
    assert cursor == 15
    assert inputs == []


def test_render_template_collects_inputs(svc):
    text, cursor, inputs = svc.render_template("Hello {{input:name}}")
    assert inputs == ["name"]
    # 调用方流程：先取 inputs 弹输入框 → 二次渲染提供值
    text2, _, inputs2 = svc.render_template(
        "Hello {{input:name}}", input_values={"name": "Alice"})
    assert text2 == "Hello Alice"
    assert inputs2 == ["name"]


def test_default_templates_seeded(svc):
    """迁移插入的默认模板（§101/§127）。"""
    scs = {t["shortcut"] for t in svc.list_templates()}
    assert {"shrug", "today", "uuid", "quote"} <= scs


# ---- 触发回归：混合 tab/boundary 模板互不干扰（用户实测全部失效）----

def test_matcher_mixed_modes_no_interference(tmp_path):
    """tab 模板与 automatic 模板共存：各按自己的方式触发，互不影响。

    回归：把某模板改为自动触发后，曾出现所有模板都无法触发。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.matcher import ShortcutMatcher

    eng = create_db_engine(tmp_path / "mix.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = ShortcutMatcher(svc, on_trigger=lambda t, n, c: triggered.append((t, n)))

    # 创建 tab 模板（today 已存在默认，用新词）
    svc.create_template("Greet", "greet", "Hello", trigger_mode="tab")
    # 把 quote 改为 automatic
    quote = svc.find_by_shortcut("quote")
    svc.update_template(quote["id"], trigger_mode="automatic")

    # 1) tab 模板：greet + Tab → 触发
    for ch in "greet":
        matcher.feed(ch)
    assert matcher.feed("\t") is True
    assert triggered and triggered[-1][0]["shortcut"] == "greet"

    # 2) automatic 模板：输完挂起 → 确认触发
    for ch in "quot":
        matcher.feed(ch)
    assert matcher.feed("e") is False  # 输完 → 挂起
    assert matcher.confirm_pending() is True
    assert triggered and triggered[-1][0]["shortcut"] == "quote"

    # 3) automatic 模板按 Tab → 不触发（模式不匹配）
    for ch in "quote":
        matcher.feed(ch)  # 输完挂起，reset 清掉
    matcher.reset()
    assert matcher.feed("\t") is False

    # 4) 之后 tab 模板仍然正常
    for ch in "greet":
        matcher.feed(ch)
    assert matcher.feed("\t") is True

    # 5) 之后 automatic 模板仍然正常
    for ch in "quot":
        matcher.feed(ch)
    assert matcher.feed("e") is False  # 输完 → 挂起
    assert matcher.confirm_pending() is True


def test_matcher_tab_after_boundary_miss_ok(tmp_path):
    """tab 模板不受 automatic 干扰；自动触发需词边界（防误触）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.matcher import ShortcutMatcher

    eng = create_db_engine(tmp_path / "mix2.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = ShortcutMatcher(svc, on_trigger=lambda t, n, c: triggered.append(t))
    quote = svc.find_by_shortcut("quote")
    svc.update_template(quote["id"], trigger_mode="automatic")

    # 普通单词：不触发（hello 不匹配任何 shortcut）
    for ch in "hello":
        matcher.feed(ch)
    assert triggered == []

    # design 中间的 sig：自动触发要求词边界 → 不触发
    svc.create_template("Sig", "sig", "x", trigger_mode="automatic")
    for ch in "design":
        matcher.feed(ch)
    assert triggered == []

    # 行首 quote：输完挂起 → 确认触发
    matcher.reset()
    for ch in "quot":
        matcher.feed(ch)
    assert matcher.feed("e") is False
    assert matcher.confirm_pending() is True
    assert triggered and triggered[-1]["shortcut"] == "quote"


# ---- 中文 shortcut 触发（AX 文本末尾匹配）----

def test_matcher_match_text_chinese_shortcut(tmp_path):
    """中文 shortcut：焦点文本末尾匹配即触发（输入法上屏的汉字无按键事件）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.matcher import ShortcutMatcher

    eng = create_db_engine(tmp_path / "zh.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = ShortcutMatcher(svc, on_trigger=lambda t, n, c: triggered.append((t, n)))
    svc.create_template("问候", "问候", "你好！", trigger_mode="tab")

    # 输入「你好问候」后按 Tab → 末尾匹配「问候」→ 触发
    assert matcher.match_text("你好问候") is True
    assert triggered and triggered[-1][0]["shortcut"] == "问候"
    assert triggered[-1][1] == 2  # 删除 2 个字符（问候）


def test_matcher_match_text_english_word_boundary(tmp_path):
    """英文 shortcut：文本末尾匹配要求词边界（防 design 中间的 sig）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.matcher import ShortcutMatcher

    eng = create_db_engine(tmp_path / "en.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = ShortcutMatcher(svc, on_trigger=lambda t, n, c: triggered.append(t))
    svc.create_template("Sig", "sig", "S", trigger_mode="tab")

    assert matcher.match_text("design") is False  # sig 前是 n → 不触发
    assert matcher.match_text("hi sig") is True   # 空格后独立词 → 触发
    assert matcher.match_text("sig") is True      # 行首 → 触发
    assert triggered and triggered[-1]["shortcut"] == "sig"


def test_matcher_match_text_only_tab_mode(tmp_path):
    """文本匹配仅对 tab 模式模板生效（automatic 由输完自动触发）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.matcher import ShortcutMatcher

    eng = create_db_engine(tmp_path / "mode.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = ShortcutMatcher(svc, on_trigger=lambda t, n, c: triggered.append(t))
    svc.create_template("Auto", "auto", "A", trigger_mode="automatic")

    assert matcher.match_text("xauto") is False  # automatic 不走文本 Tab 匹配
    assert triggered == []


def test_matcher_match_text_automatic_mode(tmp_path):
    """焦点文本轮询：automatic 模式的中文/英文 shortcut 匹配（轮询路径）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.matcher import ShortcutMatcher

    eng = create_db_engine(tmp_path / "auto_zh.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = ShortcutMatcher(svc, on_trigger=lambda t, n, c: triggered.append((t, n)))
    svc.create_template("问候", "问候", "你好！", trigger_mode="automatic")
    svc.create_template("Q2", "q2", "Q", trigger_mode="automatic")

    # automatic 模式：文本末尾匹配
    assert matcher.match_text("你好问候", mode="automatic") is True
    assert triggered[-1][0]["shortcut"] == "问候"
    # tab 模式不走 automatic 轮询
    matcher.reset()
    assert matcher.match_text("xq2", mode="automatic") is False


def test_matcher_match_text_skip_ascii(tmp_path):
    """轮询 skip_ascii=True：只匹配中文 shortcut（英文由按键路径覆盖）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.matcher import ShortcutMatcher

    eng = create_db_engine(tmp_path / "skip_ascii.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = ShortcutMatcher(svc, on_trigger=lambda t, n, c: triggered.append(t))
    svc.create_template("问候", "问候", "你好！", trigger_mode="automatic")
    svc.create_template("Q2", "q2", "Q", trigger_mode="automatic")

    # 中文 shortcut：skip_ascii 下仍匹配
    assert matcher.match_text("你好问候", mode="automatic", skip_ascii=True) is True
    assert triggered[-1]["shortcut"] == "问候"
    # 英文 shortcut：skip_ascii 下不匹配（组合中拼音/prefix 误触来源）
    assert matcher.match_text("hi q2", mode="automatic", skip_ascii=True) is False
