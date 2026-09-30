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
    """同一变量只收集一次、按首次出现顺序；InputRequest 带 token。"""
    tokens = parse("{{input:name}} & {{input:topic}} & {{input:name}}")
    reqs = collect_inputs(tokens)
    assert [r.name for r in reqs] == ["name", "topic"]
    assert [r.token for r in reqs] == ["{{input:name}}", "{{input:topic}}"]


def test_collect_inputs_custom_source():
    """自定义变量只有 input 来源进收集；fixed/command/state 不进。"""
    from services.template.registry import (
        SOURCE_FIXED,
        SOURCE_INPUT,
        CustomVariable,
    )

    tokens = parse("{{loc}} {{fixed}}", custom_names={"loc", "fixed"})
    reqs = collect_inputs(tokens, {
        "loc": CustomVariable(name="loc", source=SOURCE_INPUT),
        "fixed": CustomVariable(name="fixed", source=SOURCE_FIXED),
    })
    assert [r.name for r in reqs] == ["loc"]  # 只有 input 来源的进收集
    assert reqs[0].token == "{{loc}}"


def test_parse_custom_variable():
    """自定义变量命中 custom_names → CUSTOM token（params=name）。"""
    tokens = parse("Hello {{location}}", custom_names={"location"})
    assert _types(tokens) == [TokenType.TEXT, TokenType.CUSTOM]
    assert tokens[1].params == "location"


def test_parse_custom_not_pairing():
    """§43 已移除：{{name}} 不再引用 {{input:name}}——未定义即未知变量。"""
    with pytest.raises(UnknownVariableError):
        parse("{{input:name}} {{name}}")


def test_validate_template_custom_names():
    """validate_template 透传 custom_names：自定义变量合法。"""
    assert validate_template("{{location}}", custom_names={"location"}) is None
    assert "未知变量" in validate_template("{{location}}")


# ---- 自定义变量的参数（{{name:参数}}）----

def test_parse_custom_args_carried():
    """`{{weather:北京 上海}}`：params 仍是查表用的变量名，args 是参数原文。

    此前 `:后面那串` 在解析期就被丢弃（token 只留 name）→ 命令来源的脚本
    收不到任何参数，且完全没有提示。
    """
    tokens = parse("{{weather:北京 上海}}", custom_names={"weather"})
    assert tokens[0].type == TokenType.CUSTOM
    assert tokens[0].params == "weather"
    assert tokens[0].args == "北京 上海"


def test_parse_custom_without_args():
    tokens = parse("{{weather}}", custom_names={"weather"})
    assert tokens[0].args == ""


def test_validate_args_rejects_non_command_source():
    """参数只对 command 来源有意义：其余来源写了参数 → 保存期报错（不静默丢）。"""
    from services.template.parser import validate_args
    from services.template.registry import (
        SOURCE_COMMAND,
        SOURCE_FIXED,
        SOURCE_INPUT,
        CustomVariable,
    )

    vars_ = {
        "who": CustomVariable(name="who", source=SOURCE_INPUT),
        "loc": CustomVariable(name="loc", source=SOURCE_FIXED,
                              config={"text": "北京"}),
        "sh": CustomVariable(name="sh", source=SOURCE_COMMAND,
                             config={"command": "echo hi"}),
    }
    tokens = parse("{{who:张三}}", custom_names=set(vars_))
    msg = validate_args(tokens, vars_)
    assert msg and "参数" in msg and "用户输入" in msg
    # command 来源：参数合法（它是脚本的 $1）
    assert validate_args(parse("{{sh:甲}}", custom_names=set(vars_)),
                         vars_) is None
    # 无参数：任何来源都合法
    assert validate_args(parse("{{who}}", custom_names=set(vars_)),
                         vars_) is None
    # 不知道变量定义（custom_vars 缺省）→ 不误报
    assert validate_args(tokens, None) is None


def test_validate_template_with_custom_vars():
    from services.template.registry import SOURCE_INPUT, CustomVariable

    vars_ = {"who": CustomVariable(name="who", source=SOURCE_INPUT)}
    assert validate_template("{{who:张三}}", custom_names={"who"},
                             custom_vars=vars_) is not None
    assert validate_template("{{who}}", custom_names={"who"},
                             custom_vars=vars_) is None


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


# ---- 全局默认格式（config template.date_format 等，经 ctx.date_formats 注入）----

def test_render_uses_context_default_formats():
    """ctx.date_formats 作**无参数**时的全局默认（config 接线路径）。"""
    text, _ = _render("{{date}} / {{time}} / {{datetime}}",
                      date_formats={"date": "%d.%m.%Y",
                                    "time": "%H时%M分",
                                    "datetime": "%Y%m%d-%H%M"})
    assert text == "07.08.2026 / 17时40分 / 20260807-1740"


def test_token_params_override_context_default_formats():
    """带参数逐次覆盖全局默认（{{date:YYYY/MM}} 无视 config 的 date_format）。"""
    text, _ = _render("{{date:YYYY/MM}} vs {{date}}",
                      date_formats={"date": "%d.%m.%Y"})
    assert text == "2026/08 vs 07.08.2026"


def test_context_default_formats_fall_back_when_empty():
    """缺键/空串/None → 回落内置默认（不传 ctx.date_formats 的行为不回归）。

    纯空白的值由调用方负责过滤（template_service._default_date_formats
    会 strip 后跳过空值），provider 只认「假值」。
    """
    for formats in ({}, {"date": ""}, {"time": None}):
        text, _ = _render("{{date}}", date_formats=formats)
        assert text == "2026-08-07", formats


def test_context_format_is_strftime_not_template_syntax():
    """config 值按 **strftime** 解释，不过 map_format——`%a`/`%p` 不被改写。

    若误走 map_format，「a」会被替换成「%P」→ 输出字面量「%P」而非周几缩写。
    期望值现算（%a/%p 随系统 locale 变，不能写死 "Fri PM"）。
    """
    text, _ = _render("{{date}}", date_formats={"date": "%a %p"})
    assert text == NOW.strftime("%a %p")


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


# ---- 变量注册表（registry，元数据唯一事实源）----

def test_registry_all_presets_complete():
    """内置变量元数据必填：insert 唯一、description/usage/example 非空。"""
    from services.template.registry import PRESET_VARIABLES

    inserts = [m.insert for m in PRESET_VARIABLES]
    assert len(inserts) == len(set(inserts)), "insert 文本必须唯一"
    for m in PRESET_VARIABLES:
        assert m.description.strip(), f"{m.insert} 缺 description"
        assert m.usage.strip(), f"{m.insert} 缺 usage"
        assert m.example.strip(), f"{m.insert} 缺 example"
        assert m.category, f"{m.insert} 缺 category"


def test_registry_covers_known_variables():
    """注册表关键字集 == parser 已知集（parser._KNOWN 由注册表驱动）。"""
    from services.template import parser
    from services.template.registry import names

    assert parser._KNOWN == names()


def test_parse_selection():
    """{{selection}} 是已知变量 → SELECTION token。"""
    tokens = parse("Hello {{selection}}")
    assert _types(tokens) == [TokenType.TEXT, TokenType.SELECTION]


def test_meta_for_and_is_preset():
    from services.template.registry import is_preset, meta_for

    assert is_preset("{{date}}") is True
    assert is_preset("{{myvar}}") is False          # 用户自定义
    assert meta_for("{{date}}").category == "系统"
    assert meta_for("{{input:name}}").category == "用户输入"
    assert meta_for("{{cursor}}").category == "上下文"
    assert meta_for("{{myvar}}") is None


def test_tooltip_format():
    """tooltip 组装：作用 + 用法 + 例子三行。"""
    from services.template.registry import meta_for

    m = meta_for("{{date}}")
    tip = m.tooltip()
    assert m.description in tip
    assert "用法：" in tip and m.usage in tip
    assert "示例：" in tip and m.example in tip


def test_custom_default_tooltip():
    """兜底 tooltip 不得写死「用户输入」——自定义变量有四种值来源（v8）。

    旧文案「触发时弹窗询问值」只对 input 来源成立，fixed/command/state
    三种来源下是错的（该文案在 v8 值源重构后过期）。
    """
    from services.template.registry import custom_default_tooltip

    text = custom_default_tooltip()
    assert "自定义变量" in text
    assert "弹窗" not in text
    assert "用户输入" not in text


def test_custom_tooltip_by_source():
    """自定义变量 tooltip：描述 + 值来源 + 按来源的配置摘要。"""
    from services.template.registry import (
        SOURCE_FIXED,
        CustomVariable,
        custom_tooltip,
    )

    var = CustomVariable(name="email", description="工作邮箱",
                         source=SOURCE_FIXED, config={"text": "a@b.c"})
    tip = custom_tooltip(var)
    assert "工作邮箱" in tip
    assert "值来源：固定值" in tip
    assert "a@b.c" in tip
    # 无描述回退「自定义变量」
    assert "自定义变量" in custom_tooltip(CustomVariable(name="x"))


def test_custom_tooltip_script_command():
    """`cw:<名>` 的 tooltip 说「脚本」而不是「命令」——它指一个文件。

    文案错了用户会去别处找一个叫 `cw` 的命令（§7.4 脚本通道）。
    """
    from services.template.registry import (SOURCE_COMMAND, CustomVariable,
                                            custom_tooltip)

    script = CustomVariable(name="upper", description="整段字母转大写",
                            source=SOURCE_COMMAND,
                            config={"command": "cw:upper"})
    tip = custom_tooltip(script)
    assert "整段字母转大写" in tip
    assert "值来源：脚本" in tip
    assert "脚本：cw:upper" in tip
    # 普通 shell 命令仍是「命令」文案（来源没变，仍是 command）
    shell = CustomVariable(name="d", source=SOURCE_COMMAND,
                           config={"command": "date +%F"})
    assert "值来源：外部命令" in custom_tooltip(shell)
    assert "命令：date +%F" in custom_tooltip(shell)


def test_group_by_category_order():
    """分组顺序固定：系统 → 用户输入 → 上下文 → 脚本 → 自定义；空组不出现。"""
    from services.template.registry import (
        CAT_CUSTOM,
        CAT_SCRIPT,
        PRESET_VARIABLES,
        VariableMeta,
        group_by_category,
    )

    custom = VariableMeta(insert="{{loc}}", category=CAT_CUSTOM,
                          description="", usage="", example="", builtin=False)
    script = VariableMeta(insert="{{upper}}", category=CAT_SCRIPT,
                          description="", usage="", example="", builtin=True)
    groups = group_by_category(list(PRESET_VARIABLES) + [custom, script])
    cats = [c for c, _ in groups]
    assert cats == ["系统", "用户输入", "上下文", "脚本", "自定义"]
    # 系统组包含 selection（新增），脚本组含 upper，自定义组含 loc
    sys_vars = [m.insert for m in dict(groups)["系统"]]
    assert "{{selection}}" in sys_vars
    assert dict(groups)["脚本"] == [script]
    assert dict(groups)["自定义"] == [custom]
    # 只给预设 → 空组（脚本/自定义）不出现
    assert [c for c, _ in group_by_category(list(PRESET_VARIABLES))] == [
        "系统", "用户输入", "上下文"]


def test_next_input_insert_auto_suffix():
    """重复插入同名 input：自动编号 base → base2 → base3。"""
    from services.template.registry import next_input_insert

    assert next_input_insert("", "name") == "{{input:name}}"
    assert next_input_insert("a {{input:name}} b", "name") == "{{input:name2}}"
    content = "{{input:name}}{{input:name2}}"
    assert next_input_insert(content, "name") == "{{input:name3}}"
    # 不同标签互不影响
    assert next_input_insert("{{input:name}}", "标题") == "{{input:标题}}"


# ---- {{selection}} 系统变量（§值源-系统状态）----

def test_render_selection():
    """注入 selection_text：{{selection}} 替换为选中文本。"""
    text, _ = _render("选中内容：{{selection}}", selection_text="你好")
    assert text == "选中内容：你好"


def test_render_selection_empty():
    """无选中（空）：{{selection}} 渲染为空串（允许为空）。"""
    text, _ = _render("【{{selection}}】", selection_text="")
    assert text == "【】"


def test_render_selection_default_reader(tmp_path):
    """默认 selection_reader：走 ax_text.read_focused_selection（注入替换）。"""
    from services.template_service import TemplateService

    svc = TemplateService(None, selection_reader=lambda: "选中")
    text, _, _ = svc.render_template("a{{selection}}b")
    assert text == "a选中b"
