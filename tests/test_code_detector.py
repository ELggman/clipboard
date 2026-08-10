"""Code Detector 单元测试：18 语言识别、置信度、负例、性能。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.code_detector import CODE_THRESHOLD, CodeResult, detect


# ---- 正例：每种语言一个典型片段 ----

SAMPLES = [
    ("python", "def hello(name):\n    return f\"Hello {name}\"\n\n"
               "if __name__ == '__main__':\n    print(hello('world'))"),
    ("javascript", "function add(a, b) {\n    return a + b;\n}\n"
                   "const result = add(1, 2);\nconsole.log(result);"),
    ("typescript", "interface User {\n    id: number;\n    name: string;\n}\n"
                   "const u: User = { id: 1, name: 'a' };\nconsole.log(u);"),
    ("java", "public class Hello {\n    public static void main(String[] args) {\n"
             "        System.out.println(\"hi\");\n    }\n}"),
    ("c", "#include <stdio.h>\nint main() {\n    printf(\"hi\\n\");\n"
          "    return 0;\n}"),
    ("cpp", "#include <iostream>\nint main() {\n    std::cout << \"hi\";\n"
            "    return 0;\n}"),
    ("csharp", "using System;\npublic class Program {\n"
               "    public static void Main() {\n"
               "        Console.WriteLine(\"hi\");\n    }\n}"),
    ("go", "package main\n\nimport \"fmt\"\n\nfunc main() {\n"
           "    fmt.Println(\"hi\")\n}"),
    ("rust", "fn main() {\n    let msg = String::from(\"hi\");\n"
             "    println!(\"{}\", msg);\n}"),
    ("swift", "import Foundation\nfunc greet(name: String) -> String {\n"
              "    return \"Hello \\(name)\"\n}\nlet g = greet(name: \"a\")"),
    ("kotlin", "fun main() {\n    val msg = \"hi\"\n    println(msg)\n}"),
    ("sql", "SELECT name, age\nFROM users\nWHERE age > 18\n"
            "ORDER BY age DESC;"),
    ("shell", "#!/bin/bash\nexport APP_ENV=production\n"
              "docker compose up -d && docker ps"),
    ("html", "<!DOCTYPE html>\n<html>\n<head><title>Page</title></head>\n"
             "<body>\n  <div class=\"main\">Hello</div>\n</body>\n</html>"),
    ("css", ".btn {\n    color: #fff;\n    background: #007aff;\n"
            "    border-radius: 8px;\n}\n@media (max-width: 600px) {\n"
            "    .btn { font-size: 12px; }\n}"),
    ("json", '{"name": "Alice", "age": 20, "skills": ["Python", "SQL"]}'),
    ("yaml", "server:\n  host: localhost\n  ports:\n    - 8080\n    - 9090\n"
             "name: test"),
    ("markdown", "# 标题\n\n- 列表项一\n- 列表项二\n\n```python\nprint(1)\n```"),
]


@pytest.mark.parametrize("expected,content", SAMPLES,
                         ids=[s[0] for s in SAMPLES])
def test_detect_known_languages(expected, content):
    result = detect(content)
    assert result is not None, f"{expected} 应被检测到"
    assert result.language == expected, f"期望 {expected}，实际 {result.language}"
    assert result.confidence >= CODE_THRESHOLD, (
        f"{expected} 置信度 {result.confidence} 应 >= {CODE_THRESHOLD}")


def test_detect_none_for_plain_text():
    assert detect("Hello, how are you?") is None
    assert detect("") is None
    assert detect("   \n  ") is None
    assert detect("今天天气不错，我们去公园散步吧") is None


def test_detect_short_text_is_not_code():
    """短内容（<2 行且无强信号）不算代码。"""
    assert detect("hi") is None
    assert detect("a b c") is None


def test_python_scores_highest_than_js():
    py = "def hello():\n    return 1\n\nprint(hello())"
    r = detect(py)
    assert r.language == "python"
    # 直接对比 python 与 javascript 的原始分
    from services import code_detector as cd

    scores = {
        "python": cd._score_python(py, py.splitlines()),
        "javascript": cd._score_javascript(py, py.splitlines()),
    }
    assert scores["python"] > scores["javascript"]


def test_json_structured_flag():
    r = detect('{"a": 1, "b": [2, 3]}')
    assert r is not None and r.is_structured and r.language == "json"
    r = detect("SELECT * FROM t WHERE x = 1;")
    assert r is not None and r.is_structured and r.language == "sql"


def test_low_confidence_keeps_language_auxiliary():
    """弱证据：仍有语言信息但置信度低于阈值（调用方保留为辅助字段）。"""
    # 仅两处 'def '，结构证据弱 → 0.73 < 0.80
    r = detect("def a():\n    pass\n\ndef b():\n    pass")
    assert r is not None
    assert r.language == "python"
    assert r.confidence < CODE_THRESHOLD


def test_shell_export_detected():
    """联动场景：shell 导出环境变量（§10 示例）。"""
    r = detect('export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxx"')
    assert r is not None and r.language == "shell"


def test_performance_under_20ms():
    """§11.2：代码检测 < 20ms（含最坏情况长文本）。"""
    snippet = "def f(a):\n    return a * 2\n\nprint(f(21))\n"
    long_text = snippet * 200  # ~4400 字符，触发截断路径
    start = time.perf_counter()
    for _ in range(100):
        detect(long_text)
    elapsed_ms = (time.perf_counter() - start) * 1000 / 100
    assert elapsed_ms < 20, f"检测耗时 {elapsed_ms:.1f}ms，超出 20ms 限制"


def test_metadata_maps_available():
    from services.code_detector import EXTENSIONS, LANGUAGE_EMOJI, LANGUAGE_NAMES

    assert EXTENSIONS["python"] == ".py"
    assert EXTENSIONS["markdown"] == ".md"
    assert LANGUAGE_NAMES["csharp"] == "C#"
    assert LANGUAGE_EMOJI["python"] == "🐍"


# ---- 回归：C++/Swift/Rust 误判（2026-08-07 用户实测）----

REGRESSION_SAMPLES = [
    # C++：using namespace + vector 泛型曾误判为 shell（#include 计为注释、
    # <int> 计为重定向）
    ("cpp", "#include <vector>\nusing namespace std;\nint main() {\n"
            "    vector<int> v;\n    v.push_back(1);\n    return 0;\n}"),
    # Swift：SwiftUI 结构体曾误判为 python（import+缩进加分）
    ("swift", "import SwiftUI\nstruct ContentView: View {\n"
              "    var body: some View {\n        Text(\"Hello\")\n    }\n}"),
    # Rust 单行：fn 开头
    ("rust", 'fn main() { println!("hello"); }'),
    # Shell：echo 重定向单行
    ("shell", "echo done > log.txt"),
]


@pytest.mark.parametrize("expected,content", REGRESSION_SAMPLES,
                         ids=[s[0] + f"-{i}" for i, s in enumerate(REGRESSION_SAMPLES)])
def test_detect_regression_misclassifications(expected, content):
    r = detect(content)
    assert r is not None, f"{expected} 应被检测到"
    assert r.language == expected, f"期望 {expected}，实际 {r.language}"
    assert r.confidence >= CODE_THRESHOLD


# ---- 回归：Markdown 文档 / 纯文本误判为 shell（2026-08-08 用户实测）----

# 复刻用户复制的「Snippet 模块开发功能需求文档」：标题 + 引用 + 列表 +
# 表格 + shell 代码围栏。原文档 3747 行，173 个 # 标题行 + 围栏命令 +
# 表格 | → shell 1.0 与 markdown 1.0 平局，shell 靠字典序胜出
MD_DOC = ("# Snippet 模块开发功能需求文档\n"
          "\n"
          "> 项目：Clipboard Workspace\n"
          "> 模块：Snippet\n"
          "> 文档版本：v1.0\n"
          "\n"
          "## 功能列表\n"
          "\n"
          "- 新建片段\n"
          "- 复制时渲染变量 {{date}} {{time}} {{uuid}}\n"
          "\n"
          "| 变量 | 说明 |\n"
          "|------|------|\n"
          "| {{date}} | 当日日期 |\n"
          "\n"
          "```bash\n"
          "pip install PySide6\n"
          "docker compose up -d\n"
          "```")


def test_markdown_doc_with_shell_fence_is_markdown():
    """需求文档（标题+引用+列表+表格+shell 代码块）识别为 markdown 而非 shell。"""
    r = detect(MD_DOC)
    assert r is not None
    assert r.language == "markdown", f"期望 markdown，实际 {r.language}"
    assert r.confidence >= CODE_THRESHOLD


def test_plain_text_no_shell_base_floor():
    """纯文本不再因 shell 0.45 保底分被识别为 shell（回归）。

    原行为：任何多行文本零信号也以 0.45 分胜出，type=text 却带 shell 语言。
    """
    assert detect("Hello, World!\nThis is just a normal sentence.\n"
                  "I am testing the clipboard history application.") is None
    assert detect("第五部分：Snippet\n其实已经接近 Raycast Snippet。\n"
                  "例如：\nshrug\n自动：\n¯\\_(ツ)_/¯") is None
    assert detect("Language\tExtension\nPython\t.py\nJavaScript\t.js") is None


def test_shell_script_with_comment_headers_still_shell():
    """带标题形注释的真 shell 脚本仍识别为 shell（不被 markdown 覆盖）。

    '# Set the port' 这类注释符合 markdown 标题形，但只有 1 种结构信号，
    distinct-type 守卫保证不误覆盖。
    """
    r = detect("#!/bin/bash\n"
               "# Set the port\n# Start the service\n"
               "# Stop the service\n# Reload the config\n"
               "echo done")
    assert r is not None
    assert r.language == "shell"


def test_headers_only_doc_is_markdown():
    """只有标题的文档：标题行不计入 shell 注释 → 纯标题文档是 markdown。"""
    r = detect("# 标题一\n\n# 标题二\n\n# 标题三\n\n# 标题四\n\n正文内容")
    assert r is not None
    assert r.language == "markdown"
