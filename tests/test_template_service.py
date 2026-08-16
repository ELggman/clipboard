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
    assert [r.name for r in inputs] == ["name"]
    # 调用方流程：先取 inputs 弹输入框 → 二次渲染提供值
    text2, _, inputs2 = svc.render_template(
        "Hello {{input:name}}", input_values={"name": "Alice"})
    assert text2 == "Hello Alice"
    assert [r.name for r in inputs2] == ["name"]


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


# ---- 中文 shortcut 触发（AX 文本末尾匹配，AxShortcutMatcher 独立于英文缓冲）----

def test_ax_matcher_chinese_shortcut(tmp_path):
    """中文 shortcut：焦点文本末尾匹配即触发（输入法上屏的汉字无按键事件）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "zh.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append((t, n, c)))
    svc.create_template("问候", "问候", "你好！", trigger_mode="tab")

    # 输入「你好问候」后按 Tab → 末尾匹配「问候」→ 触发
    assert matcher.match_text("你好问候") is True
    assert triggered and triggered[-1][0]["shortcut"] == "问候"
    assert triggered[-1][1] == 2  # 删除 2 个字符（问候）
    assert triggered[-1][2] is False  # 中文已上屏，⌥⌫ 删除即可，无需取消组合


def test_ax_matcher_skips_english(tmp_path):
    """独立性契约：AxShortcutMatcher 只匹配中文——英文 shortcut 永不走 AX。

    英文触发完全由缓冲引擎（ShortcutMatcher.feed）负责；本类英文一律
    sc.isascii() 跳过，防止中文路径与英文路径抢同一文本。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "en.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append(t))
    svc.create_template("Sig", "sig", "S", trigger_mode="tab")

    assert matcher.match_text("hi sig") is False  # 英文 shortcut → 不触发
    assert matcher.match_text("sig") is False     # 行首也不行
    assert triggered == []


def test_ax_matcher_mode_tab_only(tmp_path):
    """Tab 路径仅匹配 tab 模式中文模板（automatic 由轮询触发）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "mode.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append(t))
    svc.create_template("问候", "问候", "你好！", trigger_mode="automatic")

    assert matcher.match_text("你好问候") is False  # automatic 不走文本 Tab 匹配
    assert triggered == []


def test_ax_matcher_automatic_mode(tmp_path):
    """焦点文本轮询：automatic 模式的中文 shortcut 末尾匹配。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "auto_zh.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append((t, n)))
    svc.create_template("问候", "问候", "你好！", trigger_mode="automatic")
    svc.create_template("你好", "你好", "H", trigger_mode="tab")

    assert matcher.match_text("你好问候", mode="automatic") is True
    assert triggered[-1][0]["shortcut"] == "问候"
    # automatic 轮询不匹配 tab 模式模板（即使文本以它结尾）
    assert matcher.match_text("你好", mode="automatic") is False


def test_ax_matcher_empty_or_miss(tmp_path):
    """空文本/无匹配：返回 False 不触发。"""
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "miss.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append(t))
    svc.create_template("问候", "问候", "你好！", trigger_mode="tab")

    assert matcher.match_text("") is False
    assert matcher.match_text("你好世界") is False  # 不以「问候」结尾
    assert triggered == []


def test_ax_matcher_strips_trailing_newlines(tmp_path):
    """编辑器块文本尾随换行剥离后再匹配（实测 Typora value='问候\\n\\n'）。

    回归：不剥离则 endswith 永远匹配不上——Typora 是块级模型，每个段落
    的 AXTextArea value 尾部固定带段落换行伪影。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "typora.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append((t, n)))
    svc.create_template("问候", "问候", "你好！", trigger_mode="automatic")

    # Typora 实测：value 尾部带两个换行
    assert matcher.match_text("问候\n\n", mode="automatic") is True
    assert triggered[-1][0]["shortcut"] == "问候"
    assert triggered[-1][1] == 2  # 删除 2 个字符（问候）

    # 段落中匹配 + 尾随换行；换行前的空格也可剥离
    assert matcher.match_text("今天天气好 问候\n", mode="automatic") is True
    assert triggered[-1][0]["shortcut"] == "问候"

    # 全空白文本：剥离后无可匹配 → False 不触发
    assert matcher.match_text("\n\n", mode="automatic") is False


def test_is_delete_reveal():
    """删除判定：只把「删尾部露出 shortcut」当非输入，追加/替换放行。

    回归 1：automatic 轮询实测「问候你」删掉「你」后文本变「问候」，
    末尾匹配会误触发——删除判定挡掉。
    回归 2：VS Code 读不到 marked range，组合守卫失效，轮询会读到拼音
    中间态（'wen h'）→ 上屏「问候」是**替换**不是追加——若按追加判定
    会误判为非输入导致无法触发（实测）。替换应放行给末尾匹配。
    """
    from services.template.ax_matcher import is_delete_reveal

    # 删除尾部露出 shortcut → True（应挡）
    assert is_delete_reveal("问候你", "问候") is True           # ⌫
    assert is_delete_reveal("问候你\n\n", "问候\n\n") is True   # Typora 块尾换行
    assert is_delete_reveal("abc问候你", "abc问候") is True     # 段中删尾

    # 追加/替换/改写/空 → False（放行匹配尝试）
    assert is_delete_reveal("", "问候\n\n") is False            # 空 → 输入
    assert is_delete_reveal("问候", "问候你") is False          # 追加字符
    assert is_delete_reveal("问候\n\n", "问候你\n\n") is False  # 追加（换行移位）
    assert is_delete_reveal("... wen h", "... 问候") is False   # 拼音→上屏（回归2）
    assert is_delete_reveal("abc问候", "xabc问候") is False     # 改写


def test_ax_matcher_no_delete_trigger(tmp_path):
    """automatic 轮询完整序列：删除使文本以 shortcut 结尾 → 不触发。

    模拟 _poll_focused_text 的状态迁移逻辑（缓存 + 删除判定 + 匹配）：
    「问候你」→ 删「你」→ 文本「问候」，末尾匹配会误触发；删除判定
    挡掉。同时验证正常输入仍触发、清行重置后可重新触发、拼音→上屏
    （VS Code 组合守卫失效的场景）也能触发、首次观测（切换上下文后
    的基线轮）既有文本不触发。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher
    from services.template.ax_matcher import is_delete_reveal

    eng = create_db_engine(tmp_path / "del.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append(t["shortcut"]))
    svc.create_template("问候", "问候", "你好！", trigger_mode="automatic")

    cache = None

    def poll(text):  # 与 bootstrap._poll_focused_text 同构
        nonlocal cache
        if text is None or text == cache:
            return
        if not text.strip():
            cache = ""
            return
        prev, cache = cache, text
        if prev is None:
            return  # 首次观测
        if is_delete_reveal(prev, text):
            return  # 删除尾部露出 shortcut
        matcher.match_text(text, mode="automatic")

    # 首次观测（切换上下文后的基线轮，prev=None）：既有文本不触发
    # （对应 bootstrap：前台 pid 变化 → 重置缓存，下一轮 prev=None 建立基线）
    poll("问候\n\n")
    assert triggered == []

    # 空行 → 输入「问候」→ 触发
    poll("")
    poll("问候\n\n")
    assert triggered == ["问候"]

    # 追加「你」→ 不触发（不是 shortcut）
    poll("问候你\n\n")
    assert triggered == ["问候"]

    # 删掉「你」→ 文本变「问候」，但是删除 → 不触发（回归1）
    poll("问候\n\n")
    assert triggered == ["问候"]

    # 清行重置 → 重输「问候」→ 重新触发（缓存不卡死）
    poll("")         # 清空 → 重置缓存
    poll("问候\n\n")  # 重输
    assert triggered == ["问候", "问候"]

    # 拼音中间态 → 上屏「问候」（VS Code 组合守卫失效）→ 触发（回归2）
    poll("问候 输入 wen h")   # 拼音，ASCII，不匹配
    poll("问候 输入 问候")     # 上屏：替换不是删除 → 放行 → 触发
    assert triggered == ["问候", "问候", "问候"]


# ---- has_chinese_shortcut（决定是否强制开启前台 AX 树）----

def test_has_chinese_shortcut(tmp_path):
    """有非 ASCII（中文）shortcut 才返回 True——决定是否强制开 AX。"""
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "zh_flag.db")
    migrate(eng)
    svc = TemplateService(eng)

    svc.create_template("Email", "email", "hello")  # 只有英文
    assert svc.has_chinese_shortcut() is False

    svc.create_template("问候", "问候", "你好！", trigger_mode="tab")  # 加中文
    assert svc.has_chinese_shortcut() is True


def test_has_chinese_shortcut_disabled_ignored(tmp_path):
    """只统计已启用 shortcut（禁用的中文不算——触发不了无需开 AX）。"""
    from database.engine import create_db_engine
    from database.migrations import migrate

    eng = create_db_engine(tmp_path / "zh_flag2.db")
    migrate(eng)
    svc = TemplateService(eng)

    tid = svc.create_template("问候", "问候", "你好！", trigger_mode="tab")
    assert svc.has_chinese_shortcut() is True
    svc.toggle_enabled(tid)  # 禁用
    assert svc.has_chinese_shortcut() is False


# ---- Tab 兜底：中文输入法提交键清缓冲后，从已上屏文本末尾匹配英文 ----

def test_ax_matcher_ascii_tab_fallback(tmp_path):
    """include_ascii=True：匹配英文 tab shortcut；默认（False）仍跳过英文。

    回归场景（用户实测）：中文输入法下输英文 shortcut 必须先按提交键
    （回车/空格）上屏，提交键清掉英文缓冲（tab 模式不自动触发，缓冲被
    清），随后 Tab 时缓冲为空——只能从**已上屏的焦点文本末尾**匹配英文
    tab shortcut（bootstrap._on_raw_key 的 AX 兜底）。命中 cancel_ime
    恒 False（文本已上屏，⌥⌫ 删即可）。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "en_tab.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append((t, n, c)))
    svc.create_template("Now", "now", "此刻", trigger_mode="tab")
    svc.create_template("Auto", "auto1", "X", trigger_mode="automatic")

    # 默认 include_ascii=False：英文被跳过（主路径契约不变）
    assert matcher.match_text("hello now") is False
    assert triggered == []

    # include_ascii=True：匹配英文 tab shortcut
    assert matcher.match_text("hello now", include_ascii=True) is True
    assert triggered[-1][0]["shortcut"] == "now"
    assert triggered[-1][1] == 3
    assert triggered[-1][2] is False  # 已上屏 → ⌥⌫，无需取消组合

    # 模式过滤：automatic 不参与 Tab 兜底（Tab 只触发 tab 模式）
    assert matcher.match_text("x auto1", include_ascii=True) is False
    assert len(triggered) == 1


def test_ax_matcher_include_ascii_still_matches_chinese(tmp_path):
    """include_ascii=True 是「中文+英文」合一次扫描：中文仍匹配。

    Tab 兜底覆盖中英两套——中文输入法下无论中英文 shortcut，提交上屏后
    Tab 都能从文本末尾触发。
    """
    from database.engine import create_db_engine
    from database.migrations import migrate
    from services.template.ax_matcher import AxShortcutMatcher

    eng = create_db_engine(tmp_path / "mix_tab.db")
    migrate(eng)
    svc = TemplateService(eng)
    triggered = []
    matcher = AxShortcutMatcher(
        svc, on_trigger=lambda t, n, c: triggered.append(t["shortcut"]))
    svc.create_template("问候", "问候", "你好！", trigger_mode="tab")
    svc.create_template("Now", "now", "此刻", trigger_mode="tab")

    assert matcher.match_text("你好问候", include_ascii=True) is True
    assert triggered[-1] == "问候"
    assert matcher.match_text("hello now", include_ascii=True) is True
    assert triggered[-1] == "now"
