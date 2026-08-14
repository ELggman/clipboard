"""模板引擎测试（文档 §115-121）：parser token 流 / renderer / 错误验证。"""
import sys
import uuid as uuid_mod
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.template.errors import (
    CursorLimitError,
    InputError,
    TemplateError,
    UnknownVariableError,
)
from services.template.parser import collect_inputs, parse, validate_template
from services.template.renderer import render
from services.template.token import TokenType
from services.template.variables import RenderContext

NOW = datetime(2026, 8, 7, 17, 40, 12)


def _types(tokens):
    return [t.type for t in tokens]


def _render(content, **ctx_kwargs):
    """解析 + 渲染（固定时间）。"""
    tokens = parse(content)
    ctx = RenderContext(now=NOW, **ctx_kwargs)
    return render(tokens, ctx)


# ---- Parser（§116）----

def test_parse_hello_date():
    tokens = parse("Hello {{date}}")
    assert _types(tokens) == [TokenType.TEXT, TokenType.DATE]
    assert tokens[0].value == "Hello "
    assert tokens[1].params == ""


def test_parse_uuid_only():
    tokens = parse("{{uuid}}")
    assert _types(tokens) == [TokenType.UUID]


def test_parse_input_variable():
    tokens = parse("Hello {{input:name}}")
    assert _types(tokens) == [TokenType.TEXT, TokenType.INPUT]
    assert tokens[1].params == "name"


def test_parse_date_with_format():
    tokens = parse("{{date:YYYY/MM/DD}}")
    assert _types(tokens) == [TokenType.DATE]
    assert tokens[0].params == "YYYY/MM/DD"


def test_parse_clipboard_and_cursor():
    tokens = parse("> {{clipboard}}\n{{cursor}}")
    assert _types(tokens) == [TokenType.TEXT, TokenType.CLIPBOARD,
                              TokenType.TEXT, TokenType.CURSOR]


def test_parse_trailing_text():
    tokens = parse("{{uuid}} done")
    assert _types(tokens) == [TokenType.UUID, TokenType.TEXT]
    assert tokens[1].value == " done"


def test_parse_multiple_mixed():
    tokens = parse("Hello {{input:name}}, today is {{date}}.")
    assert _types(tokens) == [TokenType.TEXT, TokenType.INPUT,
                              TokenType.TEXT, TokenType.DATE, TokenType.TEXT]


def test_parse_plain_text_no_variables():
    tokens = parse("plain text")
    assert _types(tokens) == [TokenType.TEXT]


# ---- 错误验证（§66-67/§121）----

def test_parse_unknown_variable_raises():
    with pytest.raises(UnknownVariableError):
        parse("Hello {{abc}}")


def test_parse_input_without_name_raises():
    with pytest.raises(InputError):
        parse("Hello {{input}}")


def test_parse_duplicate_cursor_raises():
    with pytest.raises(CursorLimitError):
        parse("{{cursor}} text {{cursor}}")


def test_validate_template_ok():
    assert validate_template("Hello {{input:name}}") is None


def test_validate_template_errors():
    assert "未知变量" in validate_template("{{unknown}}")
    assert "name" in validate_template("{{input}}")
    assert "cursor" in validate_template("{{cursor}}{{cursor}}")


def test_collect_inputs_dedup():
    """同一变量只收集一次、按首次出现顺序（§43）。"""
    tokens = parse("{{input:name}} & {{input:topic}} & {{name}}")
    assert collect_inputs(tokens) == ["name", "topic"]


# ---- Renderer（§117-120）----

def test_render_date_default():
    text, _ = _render("Today: {{date}}")
    assert text == "Today: 2026-08-07"


def test_render_datetime_default():
    text, _ = _render("Captured: {{datetime}}")
    assert text == "Captured: 2026-08-07 17:40:12"


def test_render_time_default():
    text, _ = _render("At {{time}}")
    assert text == "At 17:40"


def test_render_uuid():
    text, _ = _render("Request-ID: {{uuid}}")
    uid = text.removeprefix("Request-ID: ")
    uuid_mod.UUID(uid)  # 合法 UUID 格式


def test_render_date_custom_format():
    text, _ = _render("今天是 {{date:YYYY年MM月DD日}}")
    assert text == "今天是 2026年08月07日"


def test_render_clipboard():
    text, _ = _render("> {{clipboard}}", clipboard_text="Hello World")
    assert text == "> Hello World"


def test_render_clipboard_empty_ok():
    """剪贴板为空：允许输出空（§69）。"""
    text, _ = _render("> {{clipboard}}", clipboard_text="")
    assert text == "> "


def test_render_input():
    text, _ = _render("Hello {{input:name}}", input_values={"name": "Alice"})
    assert text == "Hello Alice"


def test_render_input_repeated_single_value():
    """同一 input 变量出现多次：同一值（§43）。"""
    text, _ = _render("Hello {{input:name}}.\nWelcome, {{input:name}}.",
                      input_values={"name": "Alice"})
    assert text == "Hello Alice.\nWelcome, Alice."


def test_render_cursor_position():
    text, cursor = _render("Hello {{cursor}}")
    assert text == "Hello "
    assert cursor == 6  # §118：'Hello ' 长度


def test_render_cursor_mid_template():
    text, cursor = _render("def f():\n    {{cursor}}\n")
    assert cursor == 13  # "def f():\n    " 长度


def test_render_no_cursor():
    text, cursor = _render("no cursor")
    assert cursor is None


def test_render_full_template():
    """文档 §28 综合示例：clipboard + datetime。"""
    text, _ = _render("## Reference\n\n> {{clipboard}}\n\nCaptured: {{datetime}}",
                      clipboard_text="Some copied content.")
    assert text == ("## Reference\n\n> Some copied content.\n\n"
                    "Captured: 2026-08-07 17:40:12")


# ---- Matcher（Tab Trigger，§7.2）----

class _FakeService:
    """find_by_shortcut 的替身：模拟 TemplateService。"""

    def __init__(self, templates):
        self._t = {t["shortcut"]: t for t in templates}

    def find_by_shortcut(self, sc):
        t = self._t.get(sc.lower())  # 模拟真实 service 的小写化
        return t if t and t["enabled"] else None

    def list_shortcuts(self):
        return [{"shortcut": t["shortcut"], "trigger_mode": t["trigger_mode"],
                 "id": 0} for t in self._t.values() if t["enabled"]]


def _mk_tmpl(sc, mode="tab", enabled=True):
    return {"shortcut": sc, "trigger_mode": mode, "enabled": enabled}


def test_matcher_tab_trigger():
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("pyfunc")]))
    for ch in "pyfunc":
        assert matcher.feed(ch) is False
    assert matcher.feed("\t") is True  # Tab 触发


def test_matcher_mid_word_tab_trigger():
    """输入 abpyfunc+Tab：从缓冲末尾扫描到 pyfunc（§7.1 单词边界语义）。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("pyfunc")]))
    for ch in "abpyfunc":
        matcher.feed(ch)
    assert matcher.feed("\t") is True


def test_matcher_no_match_clears_buffer():
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("pyfunc")]))
    for ch in "pyfuncx":  # 不是完整词（§7.1：shrugging 不触发 shrug）
        matcher.feed(ch)
    assert matcher.feed("\t") is False  # 不触发
    # 缓冲已清：再来一次 pyfunc+Tab 正常触发
    for ch in "pyfunc":
        matcher.feed(ch)
    assert matcher.feed("\t") is True


def test_matcher_backspace_retry():
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("pyfunc")]))
    for ch in "pyfuc":
        matcher.feed(ch)
    matcher.feed("\x7f")  # Backspace 删 'c'
    matcher.feed("n")
    matcher.feed("c")
    assert matcher.feed("\t") is True


def test_matcher_disabled_not_triggered():
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("off", enabled=False)]))
    for ch in "off":
        matcher.feed(ch)
    assert matcher.feed("\t") is False


def test_matcher_case_insensitive():
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("email")]))
    for ch in "EMAIL":
        matcher.feed(ch)
    assert matcher.feed("\t") is True  # find_by_shortcut 内部小写化


def test_matcher_automatic_trigger():
    """automatic 模式：输完最后一个字符挂起，延迟确认（200ms/词边界）触发。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("addr", mode="automatic")]))
    for ch in "add":  # 未输完不触发
        assert matcher.feed(ch) is False
    assert matcher.feed("r") is False   # 输完 → 挂起 pending（防 prefix 误触）
    assert matcher.has_pending() is True
    assert matcher.confirm_pending() is True  # 200ms 超时确认 → 触发
    assert matcher.has_pending() is False


def test_matcher_automatic_no_mid_word():
    """自动触发要求 shortcut 前是词边界：design 中间的 sig 不触发。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("sig", mode="automatic")]))
    for ch in "design":
        assert matcher.feed(ch) is False  # sig 前是 n（词字符）→ 不触发
    # 行首输入 sig → 挂起后确认触发
    matcher2 = ShortcutMatcher(_FakeService([_mk_tmpl("sig", mode="automatic")]))
    for ch in "si":
        matcher2.feed(ch)
    assert matcher2.feed("g") is False  # 输完 → 挂起
    assert matcher2.confirm_pending() is True


def test_matcher_boundary_data_compat():
    """旧 boundary 数据按自动触发兼容（输完挂起，确认触发）。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("quote", mode="boundary")]))
    for ch in "quot":
        matcher.feed(ch)
    assert matcher.feed("e") is False  # 输完 → 挂起（兼容旧数据）
    assert matcher.confirm_pending() is True


def test_matcher_auto_prefix_abort():
    """prefix 防误触：signature 的 sig 不触发——继续输入缓冲变化 → 取消。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("sig", mode="automatic")]))
    for ch in "sig":
        matcher.feed(ch)
    assert matcher.has_pending() is True
    for ch in "nature":  # 继续输入更长的词
        matcher.feed(ch)
    assert matcher.has_pending() is False  # 缓冲变化 → 取消
    assert matcher.confirm_pending() is False  # 超时确认 → 不触发


def test_matcher_auto_boundary_confirm():
    """词边界键（空格）确认挂起的自动触发："sig"+空格 → 立即触发。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("sig", mode="automatic")]),
                              on_trigger=lambda t, n, c: triggered.append(n))
    for ch in "sig":
        matcher.feed(ch)
    assert matcher.feed(" ") is True  # 空格 = 词完整 → 确认触发
    assert triggered == [3]


def test_matcher_composing_blocks_auto_trigger():
    """输入法组合中不自动触发——按键未真正上屏，删除会破坏组合（sig→siv）。

    用户要求：无论哪种输入法状态，必须完整 shortcut 彻底输入文本框后才触发。
    """
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("sig", mode="automatic")]),
        composing_check=lambda: True)
    for ch in "sig":
        assert matcher.feed(ch) is False  # 组合中：输完最后一个字符也不触发


def test_matcher_composing_release_then_trigger():
    """组合结束后（composing_check 变 False）输完才触发。"""
    from services.template.matcher import ShortcutMatcher

    state = {"composing": True}
    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("addr", mode="automatic")]),
        composing_check=lambda: state["composing"])
    for ch in "add":
        matcher.feed(ch)
    state["composing"] = False  # 输入法上屏完成
    assert matcher.feed("r") is False  # 上屏后的按键 → 挂起
    assert matcher.confirm_pending() is True  # 确认触发


def test_matcher_composing_tab_still_works():
    """组合中自动触发被拦，但 Tab 触发路径不受影响（缓冲保留）。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("quote")]),
        on_trigger=lambda t, n, c: triggered.append(n),
        composing_check=lambda: True)
    for ch in "quote":
        assert matcher.feed(ch) is False  # 自动路径被组合拦截
    assert matcher.feed("\t") is True  # Tab 仍触发（用户实测 Tab 无改写问题）
    assert triggered == [5]


# ---- 中文输入法（TIS）触发策略：不按键触发，提交键触发 ----

def test_matcher_chinese_ime_no_instant_trigger():
    """中文输入法：按键路径不自动触发（组合未上屏，碰文本会破坏组合）。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("sig", mode="automatic")]),
        chinese_ime_check=lambda: True)
    for ch in "sig":
        assert matcher.feed(ch) is False  # 输完最后一个字符也不触发


def test_matcher_chinese_ime_commit_key_triggers():
    """中文输入法：提交键（空格）按下时触发——输入法正在提交组合，
    ⌥⌫ 落在已提交文本上安全。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("sig", mode="automatic")]),
        on_trigger=lambda t, n, c: triggered.append((n, c)),
        chinese_ime_check=lambda: True)
    for ch in "sig":
        matcher.feed(ch)
    assert matcher.feed(" ") is True  # 空格提交 → 触发
    assert triggered == [(3, False)]  # 删除 3 字符；组合已提交无需取消


def test_matcher_chinese_ime_commit_after_chinese_word():
    """缓冲模型：前词提交后缓冲已清，下一词输完提交键仍能触发。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("addr", mode="automatic")]),
        on_trigger=lambda t, n, c: triggered.append(n),
        chinese_ime_check=lambda: True)
    for ch in "nihao":  # 打汉字拼音「你好」
        matcher.feed(ch)
    assert matcher.feed(" ") is False  # 提交「你好」：无 shortcut → 缓冲清空
    for ch in "add":
        matcher.feed(ch)
    assert matcher.feed("r") is False  # 中文输入法：输完也不触发
    assert matcher.feed(" ") is True   # 空格提交 → 触发
    assert triggered == [4]


def test_matcher_chinese_ime_commit_no_match_clears():
    """中文输入法：提交键无匹配时清空缓冲（后续输入不受污染）。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("sig", mode="automatic")]),
        chinese_ime_check=lambda: True)
    for ch in "xyz":
        matcher.feed(ch)
    assert matcher.feed(" ") is False  # 无匹配 → 清缓冲
    for ch in "sig":
        matcher.feed(ch)
    assert matcher.feed(" ") is True   # 缓冲干净，提交键触发


def test_matcher_chinese_ime_tab_cancel_flag():
    """中文输入法 Tab 触发：cancel_ime=True（插入层发 Escape 取消组合）。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("quote")]),
        on_trigger=lambda t, n, c: triggered.append((n, c)),
        chinese_ime_check=lambda: True)
    for ch in "quote":
        assert matcher.feed(ch) is False
    assert matcher.feed("\t") is True
    assert triggered == [(5, True)]


def test_matcher_english_space_not_commit_trigger():
    """英文输入法：空格只是词边界——不触发（中文才是提交键）。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(
        _FakeService([_mk_tmpl("sig", mode="automatic")]),
        on_trigger=lambda t, n, c: triggered.append(n),
        chinese_ime_check=lambda: False)
    for ch in "si":
        matcher.feed(ch)
    assert matcher.feed(" ") is False  # 英文空格不触发
    assert triggered == []


def test_matcher_on_trigger_callback():
    """回调携带 (template, delete_count)——需删除的 shortcut 字符数。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("quote")]),
                              on_trigger=lambda t, n, c: triggered.append((t, n)))
    for ch in "quote":
        matcher.feed(ch)
    matcher.feed("\t")
    assert triggered and triggered[0][0]["shortcut"] == "quote"
    assert triggered[0][1] == 5  # 删除整个 shortcut


def test_matcher_delete_count_mid_word():
    """abquote+Tab：delete_count = 匹配部分长度（5），'ab' 保留。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("quote")]),
                              on_trigger=lambda t, n, c: triggered.append(n))
    for ch in "abquote":
        matcher.feed(ch)
    matcher.feed("\t")
    assert triggered == [5]


def test_matcher_delete_count_boundary():
    """自动触发：delete_count=4（整个 shortcut）。"""
    from services.template.matcher import ShortcutMatcher

    triggered = []
    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("addr", mode="boundary")]),
                              on_trigger=lambda t, n, c: triggered.append(n))
    for ch in "add":
        matcher.feed(ch)
    assert matcher.feed("r") is False  # 挂起
    assert matcher.confirm_pending() is True
    assert triggered == [4]


def test_matcher_word_boundary_clears():
    """普通单词后的空格不触发（缓冲被清空）；自动模板输完即触发。"""
    from services.template.matcher import ShortcutMatcher

    matcher = ShortcutMatcher(_FakeService([_mk_tmpl("addr", mode="boundary"),
                                            _mk_tmpl("addr2")]))
    for ch in "hello":
        matcher.feed(ch)
    assert matcher.feed(" ") is False  # hello 无匹配，空格清缓冲
    for ch in "add":
        matcher.feed(ch)
    assert matcher.feed("r") is False  # boundary（兼容自动）：输完挂起
    assert matcher.confirm_pending() is True  # 确认触发


# ---- AxShortcutMatcher（中文 AX 文本匹配，独立于英文缓冲引擎）----

def test_ax_matcher_chinese_tab():
    """中文 shortcut：文本末尾匹配即触发（tab 模式）。"""
    from services.template.ax_matcher import AxShortcutMatcher

    triggered = []
    matcher = AxShortcutMatcher(
        _FakeService([_mk_tmpl("问候")]),
        on_trigger=lambda t, n, c: triggered.append((n, c)))
    assert matcher.match_text("你好问候") is True
    assert triggered == [(2, False)]  # 删除 2 字符；中文已上屏无需取消组合


def test_ax_matcher_english_never_matches():
    """独立性契约：英文 shortcut 永不被 AX 文本路径匹配（只走缓冲）。"""
    from services.template.ax_matcher import AxShortcutMatcher

    triggered = []
    matcher = AxShortcutMatcher(
        _FakeService([_mk_tmpl("sig")]),
        on_trigger=lambda t, n, c: triggered.append(n))
    assert matcher.match_text("hi sig") is False
    assert matcher.match_text("sig") is False
    assert triggered == []


def test_ax_matcher_mode_filter():
    """mode 过滤：tab 路径只匹配 tab 模板，automatic 路径只匹配 automatic。"""
    from services.template.ax_matcher import AxShortcutMatcher

    triggered = []
    matcher = AxShortcutMatcher(
        _FakeService([_mk_tmpl("问候", mode="automatic"), _mk_tmpl("你好")]),
        on_trigger=lambda t, n, c: triggered.append(t["shortcut"]))
    # tab 路径：只匹配 tab 模板「你好」
    assert matcher.match_text("abc你好") is True
    assert triggered == ["你好"]
    # automatic 路径：只匹配 automatic 模板「问候」；tab 模板不匹配
    assert matcher.match_text("abc问候", mode="automatic") is True
    assert triggered == ["你好", "问候"]
    assert matcher.match_text("abc你好", mode="automatic") is False
    assert triggered == ["你好", "问候"]


def test_ax_matcher_empty_text():
    """空文本：返回 False 不触发。"""
    from services.template.ax_matcher import AxShortcutMatcher

    matcher = AxShortcutMatcher(_FakeService([_mk_tmpl("问候")]))
    assert matcher.match_text("") is False


def test_ax_matcher_miss_no_trigger():
    """文本不以 shortcut 结尾：返回 False 不触发。"""
    from services.template.ax_matcher import AxShortcutMatcher

    triggered = []
    matcher = AxShortcutMatcher(
        _FakeService([_mk_tmpl("问候")]),
        on_trigger=lambda t, n, c: triggered.append(n))
    assert matcher.match_text("问候你") is False  # 不以「问候」结尾
    assert triggered == []
