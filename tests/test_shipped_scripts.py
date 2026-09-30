"""随应用发货的脚本内容（resources/scripts/）——内容也是要防回归的代码。

转换脚本走**真实渲染链路**（`{{名:参数}}` → parse → render → cw: → 脚本），
与用户按模板触发时完全同一条路。活数据脚本（weather / now_playing）依赖
网络与本机 App，只断言「已注册、有说明」，不在这里跑。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.template import scripts
from services.template.custom_vars import script_variables
from services.template.parser import parse
from services.template.renderer import render
from services.template.variables import RenderContext

# 联网 / 需授权，不进断言
LIVE = {"weather", "now_playing"}


def _vars():
    return {v.name: v for v in script_variables()}


def _render(token: str, stdin_text: str = "") -> str:
    variables = _vars()
    ctx = RenderContext(custom_vars=variables, selection_text=stdin_text)
    text, _cursor = render(parse(token, custom_names=set(variables)), ctx)
    return text


def test_shipped_scripts_all_have_description():
    """每个发货脚本都带 `# cw:` 说明——它会变成变量描述/模板 tooltip。"""
    infos = scripts.available_scripts()
    assert len(infos) >= 14
    missing = [s.name for s in infos if not s.description]
    assert missing == []
    assert all(s.builtin for s in infos)   # 全部来自 resources/scripts/


def test_shipped_scripts_are_unique_names():
    names = [s.name for s in scripts.available_scripts()]
    assert len(names) == len(set(names))


def test_shipped_scripts_avoid_stdlib_name_shadowing():
    """脚本名不能与标准库模块同名。

    回归：`csv.py` 因为 `sys.path[0]` = 脚本所在目录（`run_script` 的 cwd
    设定），`import csv` 会导入**它自己**，整个脚本崩在 import 上。名字带
    前缀（csv_table.py）就绕开了。
    """
    import importlib.util

    bad = []
    for info in scripts.available_scripts():
        if info.path.suffix != ".py":
            continue
        if importlib.util.find_spec(info.name) is not None:
            bad.append(info.name)
    assert bad == []


def test_shipped_variables_are_command_source_with_ref():
    """脚本 → 变量：外部命令来源 + 命令就是 `cw:<名>`。"""
    for var in script_variables():
        assert var.source == "command"
        assert var.config["command"] == f"cw:{var.name}"
    live = {v.name: v for v in script_variables()}
    assert live["weather"].config.get("timeout")      # 联网要放宽超时
    assert live["now_playing"].config.get("timeout")


@pytest.mark.parametrize("token,stdin_text,expect", [
    # ---- 大小写 ----
    ("{{upper}}", "hello 世界", "HELLO 世界"),
    ("{{lower}}", "HELLO 世界", "hello 世界"),
    ("{{title}}", "hello world 你好", "Hello World 你好"),
    # ---- 清理 ----
    ("{{trim}}", "  a  \n\n\n   b\t\n\n", "a\nb"),
    ("{{dedupe}}", "b\na\nb\nc\na", "b\na\nc"),
    # ---- 排序（参数组合）----
    ("{{sort}}", "b\nc\na", "a\nb\nc"),
    ("{{sort:num}}", "10\n9\n100", "9\n10\n100"),
    ("{{sort:desc}}", "a\nc\nb", "c\nb\na"),
    ("{{sort:uniq}}", "b\na\nb", "a\nb"),
    # ---- 引号列表 / CSV 表格 ----
    ("{{quote}}", 'a\nb"c', '"a", "b\\"c"'),
    ("{{csv_table}}", "a,b\n1,2", "| a | b |\n| --- | --- |\n| 1 | 2 |"),
    ("{{csv_table:tab}}", "a\tb\n1\t2",
     "| a | b |\n| --- | --- |\n| 1 | 2 |"),
    ("{{csv_table}}", "a,b,c\n1,2",
     "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |  |"),
    # ---- JSON ----
    ("{{json_pretty}}", '{"b":1,"a":[1,2]}',
     '{\n  "b": 1,\n  "a": [\n    1,\n    2\n  ]\n}'),
    ("{{json_pick:data.items.1.name}}",
     '{"data":{"items":[{"name":"甲"},{"name":"乙"}]}}', "乙"),
    ("{{json_pick:data.items[0].name}}",
     '{"data":{"items":[{"name":"甲"},{"name":"乙"}]}}', "甲"),
    ("{{json_pick:data.n}}", '{"data":{"n":3}}', "3"),
    ("{{json_pick:data.ok}}", '{"data":{"ok":true}}', "true"),
    # ---- 转义 ----
    ("{{escape}}", 'a"b\nc', 'a\\"b\\nc'),
    ("{{escape:unescape}}", 'a\\"b\\nc', 'a"b\nc'),
    # ---- 抽取 ----
    ("{{extract}}", "联系 a@b.com 或 c@d.cn", "a@b.com\nc@d.cn"),
    ("{{extract:url}}", "见 https://x.com/a 和 http://y.cn",
     "https://x.com/a\nhttp://y.cn"),
    ("{{extract:num}}", "甲乙 3.5 和 -2", "3.5\n-2"),
    ("{{extract:ip}}", "1.2.3.4 与 999.1.1.1 与 8.8.8.8", "1.2.3.4\n8.8.8.8"),
])
def test_shipped_transform(token, stdin_text, expect):
    assert _render(token, stdin_text) == expect


@pytest.mark.parametrize("token,stdin_text", [
    ("{{json_pretty}}", "{不是 json"),          # 输入不是 JSON
    ("{{json_pick:data.nope}}", '{"data":{}}'),  # 路径取不到
    ("{{json_pick}}", "{}"),                     # 缺路径参数
    ("{{extract:bogus}}", "x"),                  # 参数不认识
    ("{{escape:unescape}}", "未闭合\\"),          # 不是合法转义串
])
def test_shipped_transform_failure_is_empty(token, stdin_text):
    """失败 → 默认策略留空（原因进 stderr → 日志 + 托盘通知），不插半句话。"""
    assert _render(token, stdin_text) == ""


def test_shipped_transform_preserves_chinese_and_emoji():
    """UTF-8 进出无损（这是中文用户的主场景）。"""
    assert _render("{{upper}}", "中文 emoji 🎉 混排") == "中文 EMOJI 🎉 混排"
    assert _render("{{trim}}", "  中文  \n  第二行  ") == "中文\n第二行"


def test_live_scripts_registered():
    """活数据脚本已注册（内容不可断言：要联网 / 要有 App 在放歌）。"""
    names = {v.name for v in script_variables()}
    assert LIVE <= names
