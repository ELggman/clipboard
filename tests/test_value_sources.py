"""自定义变量值来源 provider 测试（固定值/外部命令/系统状态/用户输入）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.template import value_sources
from services.template.parser import parse
from services.template.registry import (
    SOURCE_COMMAND,
    SOURCE_FIXED,
    SOURCE_INPUT,
    SOURCE_STATE,
    CustomVariable,
)
from services.template.renderer import render
from services.template.token import TokenType
from services.template.variables import RenderContext


def _render_custom(content, custom_vars, **ctx_kwargs):
    tokens = parse(content, custom_names=set(custom_vars))
    ctx = RenderContext(custom_vars=custom_vars, **ctx_kwargs)
    return render(tokens, ctx)


def test_fixed_value_source():
    var = CustomVariable(name="email", source=SOURCE_FIXED,
                         config={"text": "a@b.c"})
    text, _ = _render_custom("{{email}}", {"email": var})
    assert text == "a@b.c"


def test_input_value_source():
    var = CustomVariable(name="who", source=SOURCE_INPUT)
    text, _ = _render_custom("你好 {{who}}", {"who": var},
                             input_values={"who": "张三"})
    assert text == "你好 张三"


def test_command_value_source_success():
    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "printf hello"})
    text, _ = _render_custom("{{d}}", {"d": var})
    assert text == "hello"


def test_command_value_source_nonzero_exit_empty():
    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "exit 3"})
    text, _ = _render_custom("{{d}}", {"d": var})
    assert text == ""


def test_command_failure_logs_stderr(caplog):
    """回归：stderr 此前被 capture 收走却从不记录——作者唯一线索被吞。

    用户分不清「功能坏了」还是「脚本写错了」，故失败必须把 stderr 落到日志。
    """
    import logging

    var = CustomVariable(name="bad", source=SOURCE_COMMAND,
                         config={"command": "echo 'no such file' >&2; exit 2"})
    with caplog.at_level(logging.WARNING,
                         logger="services.template.value_sources"):
        _render_custom("{{bad}}", {"bad": var})
    assert "no such file" in caplog.text     # stderr 内容进了日志
    assert "bad" in caplog.text              # 变量名（定位是哪个变量）
    assert "退出码 2" in caplog.text


def test_command_success_with_stderr_not_warning(caplog):
    """成功但有 stderr（工具告警）→ 只记 debug，不刷 warning。"""
    import logging

    var = CustomVariable(name="w", source=SOURCE_COMMAND,
                         config={"command": "echo warn >&2; printf ok"})
    with caplog.at_level(logging.DEBUG,
                         logger="services.template.value_sources"):
        text, _ = _render_custom("{{w}}", {"w": var})
    assert text == "ok"
    assert "warn" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


# ---- 命令执行原语（与失败策略分离，供编辑器「试运行」复用）----

def test_run_command_success():
    r = value_sources.run_command("printf hello", 5)
    assert r.ok and r.text == "hello" and r.returncode == 0
    assert r.duration_ms >= 0


def test_run_command_multiline():
    """多行命令经 sh -c 正常执行（编辑框已改多行，这是它成立的前提）。"""
    r = value_sources.run_command("a=1\nb=2\necho $((a+b))", 5)
    assert r.ok and r.text == "3"


def test_run_command_nonzero_reports_stderr_and_code():
    """失败要带退出码 + stderr 原文（作者定位问题的唯一线索）。"""
    r = value_sources.run_command("echo boom >&2; exit 7", 5)
    assert not r.ok
    assert r.returncode == 7
    assert "boom" in r.stderr
    assert "退出码 7" in r.error
    assert r.text == ""          # 失败不产文本（策略在 render 层决定插什么）


def test_run_command_timeout():
    r = value_sources.run_command("sleep 5", 0.1)
    assert not r.ok and "超时" in r.error


def test_run_command_preserves_stdout_on_failure():
    """非零退出但有 stdout → 两者都保留（试运行要能同时看到）。"""
    r = value_sources.run_command("echo partial; exit 1", 5)
    assert not r.ok and r.stdout.strip() == "partial"


# ---- 上下文注入：环境变量 / stdin / 参数（脚本「知道现在是什么情况」）----

def test_split_args_shell_habit():
    """参数按 shell 习惯切分；引号支持含空格的单参；引号不成对不报错。"""
    from services.template.value_sources import split_args

    assert split_args("") == []
    assert split_args("   ") == []
    assert split_args("1 2") == ["1", "2"]
    assert split_args('"你好 世界" 2') == ["你好 世界", "2"]
    assert split_args("'a b'") == ["a b"]
    # 引号没补全 → 整串当一个参数（模板里太容易写漏，不该整次插入失败）
    assert split_args('"未闭合') == ['"未闭合']


def test_command_receives_args_as_positional():
    """`{{name:参数}}` → 脚本的 $1/$2/$@（此前整个参数被静默丢弃）。"""
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": 'echo "$1-$2/$@"'})
    text, _ = _render_custom("{{c:甲 乙}}", {"c": var})
    assert text == "甲-乙/甲 乙"


def test_command_args_do_not_leak_into_dollar_zero():
    """$0 是占位名 cw——否则脚本第一个参数跑到 $0 上，「$1」恒为空。"""
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": 'echo "0=$0 1=$1"'})
    text, _ = _render_custom("{{c:甲}}", {"c": var})
    assert text == "0=cw 1=甲"


def test_command_without_args_has_empty_dollar_one():
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": 'echo "[$1]"'})
    assert _render_custom("{{c}}", {"c": var})[0] == "[]"


def test_command_env_carries_trigger_context():
    var = CustomVariable(name="ctx", source=SOURCE_COMMAND,
                         config={"command": 'echo "$CW_VAR|$CW_SELECTION|'
                                            '$CW_CLIPBOARD|$CW_APP"'})
    text, _ = _render_custom("{{ctx}}", {"ctx": var}, selection_text="选中",
                             clipboard_text="剪贴板")
    assert text == "ctx|选中|剪贴板|"


def test_command_env_app_name():
    """CW_APP 由调用方注入（触发瞬间捕获）——脚本自己读 frontmost 会读到本应用
    （picker 流程弹层/对话框已把前台让给我们）。"""
    var = CustomVariable(name="a", source=SOURCE_COMMAND,
                         config={"command": 'echo "$CW_APP"'})
    text, _ = _render_custom("{{a}}", {"a": var}, app_name="Safari")
    assert text == "Safari"


def test_command_env_template_and_now():
    import datetime

    var = CustomVariable(name="t", source=SOURCE_COMMAND,
                         config={"command": 'echo "$CW_TEMPLATE@$CW_NOW"'})
    text, _ = _render_custom("{{t}}", {"t": var}, template="正文 {{t}}",
                             now=datetime.datetime(2026, 9, 17, 10, 30, 0))
    assert text == "正文 {{t}}@2026-09-17T10:30:00"


def test_command_env_input_values():
    """CW_INPUT_<名>：脚本要读「用户刚输入的值」不必只靠 {{}} 插进正文。"""
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": 'echo "$CW_INPUT_WHO"'})
    text, _ = _render_custom("{{c}}", {"c": var}, input_values={"who": "张三"})
    assert text == "张三"


def test_command_env_args_raw():
    """CW_ARGS＝参数原文（不切分）——要整串自己解析的脚本用得上。"""
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": 'echo "$CW_ARGS"'})
    assert _render_custom('{{c:"a b" c}}', {"c": var})[0] == '"a b" c'


def test_command_env_keeps_os_environ():
    """环境变量是叠加而非替换——脚本仍该能用用户自己的 PATH/HOME。"""
    import os

    var = CustomVariable(name="h", source=SOURCE_COMMAND,
                         config={"command": 'echo "$HOME"'})
    text, _ = _render_custom("{{h}}", {"h": var})
    assert text == os.environ.get("HOME", "")


def test_command_stdin_is_selection():
    """stdin＝选中文本：脚本 `cat` 就读到选中的东西（最短的转换脚本形态）。"""
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": "tr a-z A-Z"})
    text, _ = _render_custom("{{c}}", {"c": var}, selection_text="hello",
                             clipboard_text="忽略我")
    assert text == "HELLO"


def test_command_stdin_falls_back_to_clipboard():
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": "tr a-z A-Z"})
    text, _ = _render_custom("{{c}}", {"c": var}, clipboard_text="clip")
    assert text == "CLIP"


def test_command_stdin_empty_does_not_hang():
    """无选中也无剪贴板 → 空 stdin（不是继承本进程 stdin，否则 cat 会挂住）。"""
    var = CustomVariable(name="c", source=SOURCE_COMMAND,
                         config={"command": "cat; echo done"})
    text, _ = _render_custom("{{c}}", {"c": var})
    assert text == "done"


def test_run_command_env_and_stdin_direct():
    """run_command 的两个通道（试运行链路直接用）。"""
    from services.template.value_sources import run_command

    r = run_command("cat; echo \"[$CW_VAR]\"", 5,
                    env={"PATH": "/usr/bin:/bin", "CW_VAR": "v"},
                    stdin_text="正文")
    # stdin 就是原文（不补换行）——选中文本没有尾换行，脚本自行处理
    assert r.ok and r.text == "正文[v]"


def test_run_command_env_is_not_polluted_by_default():
    """不传 env → 继承本进程环境（旧调用点行为不变）。"""
    from services.template.value_sources import run_command

    r = run_command("echo ok", 5)
    assert r.ok and r.text == "ok"


# ---- 失败策略（config.on_error）----

def test_on_error_text_inserts_fallback():
    """on_error=text → 不插半句话，插兜底文案（自定义文案）。"""
    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "exit 1",
                                 "on_error": value_sources.ERROR_TEXT,
                                 "on_error_text": "（取值失败）"})
    text, _ = _render_custom("前 {{d}} 后", {"d": var})
    assert text == "前 （取值失败） 后"


def test_on_error_text_default_when_blank():
    """选了兜底文案但没填 → 用内置默认文案（不落回空串）。"""
    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "exit 1",
                                 "on_error": value_sources.ERROR_TEXT})
    text, _ = _render_custom("{{d}}", {"d": var})
    assert text == value_sources.DEFAULT_ERROR_TEXT


def test_on_error_cancel_raises():
    """on_error=cancel → 抛 VariableValueError（调用方据此整次不插入）。"""
    from services.template.errors import VariableValueError

    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "exit 1",
                                 "on_error": value_sources.ERROR_CANCEL})
    with pytest.raises(VariableValueError) as ei:
        _render_custom("{{d}}", {"d": var})
    assert "d" in str(ei.value)  # 报错面向用户，须含变量名


def test_on_error_empty_is_default():
    """未配置 on_error → 旧行为（留空），不因新策略改变既有用户。"""
    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "exit 1"})
    assert _render_custom("x{{d}}y", {"d": var})[0] == "xy"


# ---- 失败可见通道（bootstrap 注入托盘通知）----

def test_error_reporter_called_on_failure():
    seen: list = []
    value_sources.set_error_reporter(lambda n, m: seen.append((n, m)))
    try:
        var = CustomVariable(name="d", source=SOURCE_COMMAND,
                             config={"command": "exit 1"})
        _render_custom("{{d}}", {"d": var})
        assert seen and seen[0][0] == "d"
    finally:
        value_sources.set_error_reporter(None)
        assert value_sources._error_reporter is None


def test_error_reporter_not_called_on_success():
    seen: list = []
    value_sources.set_error_reporter(lambda n, m: seen.append((n, m)))
    try:
        var = CustomVariable(name="d", source=SOURCE_COMMAND,
                             config={"command": "printf ok"})
        _render_custom("{{d}}", {"d": var})
        assert seen == []
    finally:
        value_sources.set_error_reporter(None)


def test_error_reporter_exception_does_not_break_render():
    """通知通道自身抛错绝不能影响渲染结果（托盘不可用等）。"""
    def _boom(name, message):
        raise RuntimeError("tray gone")

    value_sources.set_error_reporter(_boom)
    try:
        var = CustomVariable(name="d", source=SOURCE_COMMAND,
                             config={"command": "exit 1"})
        assert _render_custom("x{{d}}y", {"d": var})[0] == "xy"
    finally:
        value_sources.set_error_reporter(None)


# ---- 超时可配（config.timeout）----

def test_command_timeout_configurable(monkeypatch):
    monkeypatch.setattr(value_sources, "_COMMAND_TIMEOUT", 0.1)
    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "sleep 5", "timeout": 1})
    text, _ = _render_custom("{{d}}", {"d": var})
    assert text == ""


def test_timeout_clamped_and_fallback(monkeypatch):
    monkeypatch.setattr(value_sources, "_COMMAND_TIMEOUT", 5)
    t = value_sources.CommandValueSource._timeout
    assert t({"timeout": 999}) == 60      # 上限（防呆：卡死触发链路）
    assert t({"timeout": 0}) == 1         # 下限
    assert t({"timeout": "abc"}) == 5     # 非法 → 模块默认
    assert t({}) == 5                     # 未配置 → 模块默认


def test_command_value_source_timeout_empty(monkeypatch):
    monkeypatch.setattr(value_sources, "_COMMAND_TIMEOUT", 0.1)
    var = CustomVariable(name="d", source=SOURCE_COMMAND,
                         config={"command": "sleep 2"})
    text, _ = _render_custom("{{d}}", {"d": var})
    assert text == ""


def test_state_value_source_frontmost_app(monkeypatch):
    monkeypatch.setattr(value_sources, "_frontmost_app_name",
                        lambda: "Safari")
    var = CustomVariable(name="app", source=SOURCE_STATE,
                         config={"state": "frontmost_app"})
    text, _ = _render_custom("{{app}}", {"app": var})
    assert text == "Safari"


def test_state_value_source_unknown_state_empty():
    var = CustomVariable(name="app", source=SOURCE_STATE,
                         config={"state": "bogus"})
    text, _ = _render_custom("{{app}}", {"app": var})
    assert text == ""


def test_build_value_sources_registry():
    providers = value_sources.build_value_sources()
    assert set(providers) == {SOURCE_INPUT, SOURCE_FIXED,
                              SOURCE_COMMAND, SOURCE_STATE}


def test_custom_token_type():
    tokens = parse("{{email}}", custom_names={"email"})
    assert tokens[0].type == TokenType.CUSTOM
    assert tokens[0].params == "email"
