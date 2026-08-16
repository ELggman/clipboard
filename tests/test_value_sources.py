"""自定义变量值来源 provider 测试（固定值/外部命令/系统状态/用户输入）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
