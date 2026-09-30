"""发货脚本目录与 `cw:<名>` 解析（命令值源的脚本通道）。

隔离：两个脚本目录都 monkeypatch 到临时目录（不碰真实 config/scripts、
resources/scripts），因此用例在「还没放脚本」的仓库里也能跑。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.template import scripts, value_sources
from services.template.registry import SOURCE_COMMAND, CustomVariable
from services.template.renderer import render
from services.template.parser import parse
from services.template.variables import RenderContext


@pytest.fixture
def script_dirs(tmp_path, monkeypatch):
    """把用户/发货两个脚本目录都指到临时目录。返回 (用户, 发货)。"""
    user = tmp_path / "config" / "scripts"
    builtin = tmp_path / "resources" / "scripts"
    user.mkdir(parents=True)
    builtin.mkdir(parents=True)
    monkeypatch.setattr(scripts, "USER_SCRIPTS_DIR", user)
    monkeypatch.setattr(scripts, "BUILTIN_SCRIPTS_DIR", builtin)
    return user, builtin


def _write(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def _render(command: str, args: str = "", stdin_text: str = "",
            **ctx_kwargs) -> str:
    var = CustomVariable(name="v", source=SOURCE_COMMAND,
                         config={"command": command})
    tokens = parse("{{v" + (f":{args}" if args else "") + "}}",
                   custom_names={"v"})
    ctx = RenderContext(custom_vars={"v": var}, selection_text=stdin_text,
                        **ctx_kwargs)
    return render(tokens, ctx)[0]


# ---- 解析 ----

def test_resolve_prefers_user_dir(script_dirs):
    """用户目录优先：同名脚本用户那份赢（能覆盖内置行为）。"""
    user, builtin = script_dirs
    _write(user, "upper.py", "print('user')")
    _write(builtin, "upper.py", "print('builtin')")
    assert scripts.resolve("upper").parent == user


def test_resolve_extension_optional(script_dirs):
    """`cw:upper` 命中 `upper.py`；显式带后缀也命中。"""
    _user, builtin = script_dirs
    _write(builtin, "upper.py", "print('x')")
    assert scripts.resolve("upper").name == "upper.py"
    assert scripts.resolve("upper.py").name == "upper.py"


def test_resolve_missing_returns_none(script_dirs):
    assert scripts.resolve("nope") is None


def test_resolve_rejects_path_traversal(script_dirs):
    """只取文件名最后一段——`cw:../x` 不能读到目录外。"""
    user, _builtin = script_dirs
    outside = user.parent / "peek.py"
    outside.write_text("print('leak')", encoding="utf-8")
    assert scripts.resolve("../peek.py") is None
    assert scripts.resolve("..") is None
    assert scripts.resolve("") is None


def test_parse_ref_rejects_args_in_command(script_dirs):
    """`cw:extract url` 报错而不是静默丢参数（参数静默丢弃那一类坑）。"""
    _user, builtin = script_dirs
    _write(builtin, "extract.py", "print('x')")
    assert scripts.is_script_ref("cw:extract url")
    name, error = scripts.parse_ref("cw:extract url")
    assert name == ""
    assert "参数请写在模板里" in error
    # 渲染整条链路：报错走失败通道（默认留空），不静默当成 cw:extract
    assert _render("cw:extract url") == ""


def test_parse_ref_empty(script_dirs):
    name, error = scripts.parse_ref("cw:")
    assert name == "" and "脚本引用为空" in error


# ---- 执行 ----

def test_script_python_runs_with_app_interpreter(script_dirs):
    """`.py` 用应用自己的解释器跑（不依赖 PATH）。"""
    _user, builtin = script_dirs
    _write(builtin, "hello.py", "# cw: 打招呼\nprint('hi')")
    assert _render("cw:hello") == "hi"
    assert scripts.interpreter_for(builtin / "hello.py") == \
        [sys.executable]


def test_script_stdin_is_selection(script_dirs):
    """stdin 通道对脚本同样成立：`cw:` 脚本 `cat` 就读到选中文本。"""
    _user, builtin = script_dirs
    _write(builtin, "echo.py", "import sys\nprint(sys.stdin.read().upper())")
    assert _render("cw:echo", stdin_text="hello") == "HELLO"


def test_script_args_are_argv(script_dirs):
    """`{{v:甲 乙}}` → 脚本 `sys.argv[1:]`（比 sh -c 少一层，无 $0 占位）。"""
    _user, builtin = script_dirs
    _write(builtin, "join.py",
           "import sys\nprint(sys.argv[0].split('/')[-1] + ':' +"
           " '|'.join(sys.argv[1:]))")
    assert _render("cw:join", args="甲 乙") == "join.py:甲|乙"


def test_script_shell_runs_with_bin_sh(script_dirs):
    """非 .py 一律 /bin/sh（含无后缀）→ sh 的 $1.. ，没有 $0 占位问题。"""
    _user, builtin = script_dirs
    _write(builtin, "sum.sh", "echo \"$1-$2\"")
    _write(builtin, "bare", "echo bare")
    assert _render("cw:sum", args="1 2") == "1-2"
    assert _render("cw:bare") == "bare"


def test_script_cwd_is_script_dir(script_dirs):
    """cwd = 脚本所在目录：脚本可以带同目录的数据文件一起发货。"""
    _user, builtin = script_dirs
    _write(builtin, "data.txt", "内容")
    _write(builtin, "read.py", "print(open('data.txt').read())")
    assert _render("cw:read") == "内容"


def test_script_env_has_script_dir(script_dirs):
    """CW_SCRIPT_DIR：脚本互调的入口（用户目录在前）。"""
    user, builtin = script_dirs
    _write(builtin, "show.py",
           "import os\nprint(os.environ['CW_SCRIPT_DIR'])")
    got = _render("cw:show")
    assert got.split(os.pathsep) == [str(user), str(builtin)]


def test_script_missing_error_lists_available(script_dirs):
    """找不到脚本 → 明确错误 + 可用清单（走 on_error 通道）。"""
    _user, builtin = script_dirs
    _write(builtin, "upper.py", "print('x')")
    var = CustomVariable(name="v", source=SOURCE_COMMAND,
                         config={"command": "cw:nope",
                                 "on_error": value_sources.ERROR_TEXT,
                                 "on_error_text": "?"})
    tokens = parse("{{v}}", custom_names={"v"})
    ctx = RenderContext(custom_vars={"v": var})
    seen: list = []
    value_sources.set_error_reporter(lambda n, m: seen.append(m))
    try:
        assert render(tokens, ctx)[0] == "?"
    finally:
        value_sources.set_error_reporter(None)
    assert seen and "找不到脚本「nope」" in seen[0]
    assert "upper" in seen[0]


def test_available_scripts_merges_and_marks_builtin(script_dirs):
    """列表：两目录合并、同名用户赢、内置标记正确、按名排序。"""
    user, builtin = script_dirs
    _write(builtin, "b.py", "# cw: 内置的\nprint('b')")
    _write(user, "b.py", "# cw: 用户的\nprint('b')")
    _write(user, "a.py", "print('a')")
    _write(builtin, "a.py", "print('a')")
    got = scripts.available_scripts()
    assert [s.name for s in got] == ["a", "b"]
    assert got[0].builtin is False          # a 用户目录里有 → 用户版
    assert got[1].description == "用户的"   # b 同理，用户版描述
    assert got[0].ref == "cw:a"
    # 只有发货目录有的 → builtin
    _write(builtin, "c.py", "print('c')")
    info = {s.name: s for s in scripts.available_scripts()}["c"]
    assert info.builtin is True


def test_available_names_empty(script_dirs):
    assert scripts.available_names() == "（无）"


# ---- PATH 兜底 ----

def test_ensure_path_appends_missing_only():
    """PATH 补齐：只追加缺失目录，已有条目的顺序与优先级不变。"""
    env = {"PATH": os.pathsep.join(["/custom/bin", "/usr/bin"])}
    value_sources.ensure_path(env)
    parts = env["PATH"].split(os.pathsep)
    assert parts[:2] == ["/custom/bin", "/usr/bin"]   # 前缀原样
    assert "/opt/homebrew/bin" in parts               # 缺失的被补上
    assert parts.count("/usr/bin") == 1               # 不重复

    env = {"PATH": ""}
    value_sources.ensure_path(env)
    assert env["PATH"].split(os.pathsep)[0] == "/usr/local/bin"


def test_build_command_env_includes_path_and_script_dir(script_dirs):
    user, builtin = script_dirs
    env = value_sources.build_command_env("v", RenderContext())
    assert "/opt/homebrew/bin" in env["PATH"].split(os.pathsep)
    assert env["CW_SCRIPT_DIR"] == os.pathsep.join([str(user), str(builtin)])


# ---- 哪些文件算「脚本变量」----

def test_is_variable_file_filters(script_dirs):
    """后缀白名单 + 下划线/点开头排除：脚本可带同目录数据文件与辅助模块。"""
    ok = ["upper.py", "sum.sh", "bare"]
    for name in ok:
        assert scripts.is_variable_file(Path(name)), name
    for name in ["data.txt", "_common.py", ".hidden", "README.md",
                 "notes.json"]:
        assert not scripts.is_variable_file(Path(name)), name


def test_available_scripts_skips_non_variable_files(script_dirs):
    _user, builtin = script_dirs
    _write(builtin, "upper.py", "print('x')")
    _write(builtin, "data.txt", "不是脚本")
    _write(builtin, "_helper.py", "不是变量")
    assert [s.name for s in scripts.available_scripts()] == ["upper"]


# ---- 脚本自述元数据 ----

def test_read_meta_description_and_timeout(script_dirs):
    _user, builtin = script_dirs
    path = _write(builtin, "w.py",
                  "#!/usr/bin/env python3\n# cw: 取天气\n# cw-timeout: 9\n"
                  "print(1)\n")
    description, timeout = scripts.read_meta(path)
    assert description == "取天气"
    assert timeout == 9.0


def test_read_meta_absent_and_illegal(script_dirs):
    """没有自述 → ("", None)；超时值非法 → 只丢超时，不丢整个脚本。"""
    _user, builtin = script_dirs
    path = _write(builtin, "plain.py", "print(1)\n")
    assert scripts.read_meta(path) == ("", None)
    path = _write(builtin, "bad.py", "# cw: 说明\n# cw-timeout: soon\n")
    assert scripts.read_meta(path) == ("说明", None)


# ---- 脚本 → 模板变量 ----

def test_script_variables_become_command_vars(script_dirs):
    """`config/scripts/` 里丢一个文件 = 多一个模板变量（无需配设置页）。"""
    from services.template.custom_vars import script_variables

    _user, builtin = script_dirs
    _write(builtin, "translate.py", "# cw: 翻译\nprint('x')")
    _write(builtin, "slow.py", "# cw: 慢\n# cw-timeout: 12\nprint('x')")
    got = {v.name: v for v in script_variables()}
    assert set(got) == {"translate", "slow"}
    assert got["translate"].source == "command"
    assert got["translate"].config == {"command": "cw:translate"}
    assert got["translate"].description == "翻译"
    assert got["slow"].config["timeout"] == 12.0
    assert got["translate"].insert() == "{{translate}}"


def test_visible_script_variables_excludes_overridden(script_dirs, monkeypatch):
    """变量库展示用：「被同名自定义变量顶掉」的脚本不出现。

    与 load_custom_vars 同一条覆盖规则——展示与求值必须是同一份真相，
    否则库里会有两条同名行，而其中一条点了没效果。
    """
    import services.template.custom_vars as custom_vars
    from services.template.registry import SOURCE_FIXED, CustomVariable

    _user, builtin = script_dirs
    _write(builtin, "upper.py", "# cw: 内置大写\nprint('x')")
    _write(builtin, "extra.py", "# cw: 只有脚本\nprint('x')")
    monkeypatch.setattr(custom_vars, "load_extra_variables", lambda: [
        CustomVariable(name="upper", source=SOURCE_FIXED,
                       config={"text": "用户说了算"}),
    ])
    assert [v.name for v in custom_vars.visible_script_variables()] == ["extra"]
    # 全体脚本变量仍在（求值表用），只是展示时让位
    assert {v.name for v in custom_vars.script_variables()} == {
        "upper", "extra"}


def test_load_custom_vars_user_overrides_script(script_dirs, monkeypatch):
    """同名时用户变量赢——与「用户脚本覆盖内置脚本」同一条规则。"""
    import services.template.custom_vars as custom_vars
    from services.template.registry import SOURCE_FIXED, CustomVariable

    _user, builtin = script_dirs
    _write(builtin, "upper.py", "# cw: 转大写\nprint('x')")
    _write(builtin, "extra.py", "# cw: 只有脚本\nprint('x')")
    monkeypatch.setattr(custom_vars, "load_extra_variables", lambda: [
        CustomVariable(name="upper", source=SOURCE_FIXED,
                       config={"text": "用户说了算"}),
    ])
    got = custom_vars.load_custom_vars()
    assert got["upper"].source == SOURCE_FIXED          # 用户覆盖
    assert got["extra"].config["command"] == "cw:extra"  # 脚本垫在底下

