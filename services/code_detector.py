"""代码模式检测器：本地启发式识别代码与语言（DEVELOPMENT.md §8 / 新增.md §8）。

纯函数模块（零 Qt/DB 依赖，可独立单测）。调用方（watcher）在
confidence >= 0.80 时把条目标记为 type="code"；低于阈值但仍有语言
证据时，语言作为辅助信息保留（§8.4.3）。

性能：普通文本 < 20ms —— 长度上限截断、短内容快速退出、纯正则打分。
"""
import json
import re
from dataclasses import dataclass

# 检测置信度阈值：>= 该值才标记 type="code"（§8.4.3 建议 0.80）
CODE_THRESHOLD = 0.80
# 低于该分视为无代码证据（返回 None）
_WEAK_FLOOR = 0.35
# 分析截断长度（首段足够启发式判断）
_MAX_ANALYZE = 4096

# 支持的语言（§8.3 第一阶段）
LANGUAGES = [
    "python", "javascript", "typescript", "java", "c", "cpp", "csharp",
    "go", "rust", "swift", "kotlin", "sql", "shell", "html", "css",
    "json", "yaml", "markdown",
]

# 展示名 / 语言徽标 emoji（列表 meta 行用）
LANGUAGE_NAMES = {
    "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
    "java": "Java", "c": "C", "cpp": "C++", "csharp": "C#", "go": "Go",
    "rust": "Rust", "swift": "Swift", "kotlin": "Kotlin", "sql": "SQL",
    "shell": "Shell", "html": "HTML", "css": "CSS", "json": "JSON",
    "yaml": "YAML", "markdown": "Markdown",
}
LANGUAGE_EMOJI = {
    "python": "🐍", "javascript": "🟨", "typescript": "🔷", "java": "☕",
    "c": "🅲", "cpp": "🅲", "csharp": "🅲", "go": "🔵", "rust": "🦀",
    "swift": "🕊️", "kotlin": "🅺", "sql": "🗄️", "shell": "💲",
    "html": "🌐", "css": "🎨", "json": "🧾", "yaml": "📝", "markdown": "📝",
}
# 保存为文件的默认扩展名（§8.15）
EXTENSIONS = {
    "python": ".py", "javascript": ".js", "typescript": ".ts", "java": ".java",
    "c": ".c", "cpp": ".cpp", "csharp": ".cs", "go": ".go", "rust": ".rs",
    "swift": ".swift", "kotlin": ".kt", "sql": ".sql", "shell": ".sh",
    "html": ".html", "css": ".css", "json": ".json", "yaml": ".yaml",
    "markdown": ".md",
}
# Pygments lexer 别名（与 LANGUAGES 一致，Pygments 原生支持）
PYGMENTS_ALIASES = {
    "python": "python", "javascript": "javascript", "typescript": "typescript",
    "java": "java", "c": "c", "cpp": "cpp", "csharp": "csharp", "go": "go",
    "rust": "rust", "swift": "swift", "kotlin": "kotlin", "sql": "sql",
    "shell": "bash", "html": "html", "css": "css", "json": "json",
    "yaml": "yaml", "markdown": "markdown",
}

# 结构化数据语言（is_structured=1，§8.12/8.13/8.16）
_STRUCTURED = {"json", "yaml", "sql"}


@dataclass
class CodeResult:
    language: str            # 如 "python"
    confidence: float        # 0.0 - 1.0
    is_structured: bool = False  # json/yaml/sql


def detect(content: str) -> CodeResult | None:
    """检测内容是否为代码及语言。无任何代码证据返回 None。

    调用方自行按 CODE_THRESHOLD 决定是否标记 type="code"。
    """
    if not content or not content.strip():
        return None
    text = content.strip()
    if len(text) > _MAX_ANALYZE:
        text = text[:_MAX_ANALYZE]
    lines = text.splitlines()
    non_empty = [ln for ln in lines if ln.strip()]

    # 结构化优先：JSON 解析成功即 1.0（单行 JSON 也能命中）
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            json.loads(stripped)
            return CodeResult("json", 1.0, True)
        except ValueError:
            pass  # 不是合法 JSON，继续其它语言评分

    if len(lines) < 2:
        # 单行：强命令（§8.14 docker compose up -d）、SQL 关键字、yaml 键值
        if _looks_like_command(text):
            return CodeResult("shell", 0.9, False)
        sql = _score_sql(text, lines)
        if sql >= 0.8:
            return CodeResult("sql", sql, True)
        # 单行 rust：fn main() { println!("hi") }（fn 开头是 rust 专属签名）
        if stripped.startswith("fn ") and "{" in stripped:
            return CodeResult("rust", 0.9, False)
        yaml = _score_yaml(text, lines)
        if yaml >= 0.8:
            return CodeResult("yaml", yaml, True)
        return None

    scores = {
        "python": _score_python(text, lines),
        "javascript": _score_javascript(text, lines),
        "typescript": _score_typescript(text, lines),
        "java": _score_java(text, lines),
        "c": _score_c(text, lines),
        "cpp": _score_cpp(text, lines),
        "csharp": _score_csharp(text, lines),
        "go": _score_go(text, lines),
        "rust": _score_rust(text, lines),
        "swift": _score_swift(text, lines),
        "kotlin": _score_kotlin(text, lines),
        "sql": _score_sql(text, lines),
        "shell": _score_shell(text, lines),
        "html": _score_html(text, lines),
        "css": _score_css(text, lines),
        "yaml": _score_yaml(text, lines),
        "markdown": _score_markdown(text, lines),
    }
    lang = max(scores, key=scores.get)
    conf = scores[lang]
    # 文档型 Markdown 常内嵌 shell 命令代码块（README/需求文档），shell 分会
    # 反超；若 markdown 命中 ≥2 种结构信号（标题/列表/引用/表格/围栏/链接）
    # 且分数达阈值，整个文档按 markdown 处理（2026-08-08 用户实测误判）
    if lang == "shell" and scores["markdown"] >= CODE_THRESHOLD \
            and _md_distinct_types(lines) >= 2:
        lang = "markdown"
        conf = scores["markdown"]
    if conf < _WEAK_FLOOR:
        return None
    return CodeResult(lang, conf, lang in _STRUCTURED)


# ---- 通用打分工具 ----

def _hit_count(lines, *patterns: str) -> int:
    """统计命中任意模式的行数（每行计一次，去重行号）。"""
    hits = 0
    for line in lines:
        ls = line.strip()
        if any(ls.startswith(p) or p in line for p in patterns):
            hits += 1
    return hits


def _score_from(hits: int, per_hit: float = 0.09, base: float = 0.55) -> float:
    """hits 个强信号 → 分数（默认 3 个信号达 0.82 ≥ 0.80 阈值）。

    零命中返回 0.0：无信号的语言不得参与竞争（否则所有语言都有保底分）。
    """
    if hits == 0:
        return 0.0
    return min(1.0, base + per_hit * hits)


# ---- 各语言评分 ----

def _score_python(text: str, lines) -> float:
    strong = _hit_count(lines, "def ", "class ", "import ", "from ", "async ",
                        "@", "self.", "print(", "return ", "elif ", "except ",
                        "if __name__", ":=")
    # 缩进结构：≥2 空格缩进的行 ≥3 且强信号 ≥2 才加分
    # （单行 import + 缩进会把 Swift 结构体误判为 Python，实测踩坑）
    indented = sum(1 for ln in lines if len(ln) - len(ln.lstrip()) >= 2)
    score = _score_from(strong)
    if indented >= 3 and strong >= 2:
        score = min(1.0, score + 0.15)
    return score


def _score_javascript(text: str, lines) -> float:
    hits = _hit_count(lines, "function ", "const ", "let ", "var ",
                      "=>", "console.", "require(", "module.exports",
                      "import ", "export ", "=== ", "!== ", "document.",
                      "addEventListener")
    score = _score_from(hits)
    if "{" in text and "}" in text and ";" in text:
        score = min(1.0, score + 0.1)
    return score


def _score_typescript(text: str, lines) -> float:
    hits = _hit_count(lines, "interface ", "type ", "readonly ", "enum ",
                      ": string", ": number", ": boolean", ": void", "as ",
                      "export interface", "const ")
    score = _score_from(hits)
    if re.search(r"<[A-Z][A-Za-z0-9_, ]+>", text):
        score = min(1.0, score + 0.1)  # 泛型
    return score


def _score_java(text: str, lines) -> float:
    # 与 C# 区分：public/class 为公共弱信号，System.out/void main/String[]
    # 是 Java 强专属信号（C# 的 public static void Main 结构另有加分）
    hits = _hit_count(lines, "System.out", "import java", "@Override",
                      "void main", "String[]", "public class")
    score = _score_from(hits)
    if re.search(r"public static void main", text):
        score = min(1.0, score + 0.1)
    if re.search(r"new [A-Z][A-Za-z0-9]*\(", text):
        score = min(1.0, score + 0.08)
    return score


def _score_c(text: str, lines) -> float:
    hits = _hit_count(lines, "#include", "int main", "printf(", "scanf(",
                      "malloc", "struct ", "#define", "NULL", "void ")
    score = _score_from(hits)
    if "->" in text or re.search(r"\*\w+", text):
        score = min(1.0, score + 0.1)  # 指针
    return score


def _score_cpp(text: str, lines) -> float:
    hits = _hit_count(lines, "std::", "cout", "cin", "#include <", "int main",
                      "using namespace", "namespace ", "template<", "class ",
                      "public:", "private:", "push_back")
    score = _score_from(hits)
    if re.search(r"::", text):
        score = min(1.0, score + 0.1)
    return score


def _score_csharp(text: str, lines) -> float:
    hits = _hit_count(lines, "using System", "namespace ", "Console.",
                      "public ", "private ", "async Task", "List<", "var ",
                      "string ", "int ")
    score = _score_from(hits)
    if re.search(r"class \w+", text):
        score = min(1.0, score + 0.1)
    return score


def _score_go(text: str, lines) -> float:
    hits = _hit_count(lines, "package ", "func ", "import (", "defer ",
                      "go func", "err != nil", "fmt.", "chan ", "make(",
                      ":= ")
    score = _score_from(hits)
    return score


def _score_rust(text: str, lines) -> float:
    hits = _hit_count(lines, "fn ", "fn main", "let mut", "impl ", "pub ",
                      "use ", "match ", "println!", "struct ", "enum ",
                      "vec!", "unwrap")
    score = _score_from(hits)
    if "::" in text or re.search(r"Option<|Result<", text):
        score = min(1.0, score + 0.1)
    return score


def _score_swift(text: str, lines) -> float:
    hits = _hit_count(lines, "func ", "let ", "var ", "import ", "guard ",
                      "if let", "class ", "struct ", "override func",
                      "return ", "print(", "some View")
    score = _score_from(hits)
    if re.search(r"->\s*\w", text):  # 返回类型箭头
        score = min(1.0, score + 0.08)
    return score


def _score_kotlin(text: str, lines) -> float:
    hits = _hit_count(lines, "fun ", "val ", "var ", "import ", "override fun",
                      "data class", "object ", "when ", "class ")
    score = _score_from(hits)
    if re.search(r"\bprintln\(", text):  # Kotlin 惯用输出
        score = min(1.0, score + 0.1)
    if "?." in text or "?:" in text:
        score = min(1.0, score + 0.1)
    return score


_SQL_KEYWORDS = re.compile(
    r"\b(SELECT|FROM|WHERE|INSERT|INTO|UPDATE|DELETE|CREATE|TABLE|ALTER|"
    r"DROP|JOIN|LEFT|RIGHT|INNER|OUTER|GROUP|BY|ORDER|HAVING|VALUES|"
    r"UNION|AS|ON|LIMIT|PRIMARY|FOREIGN|KEY|INDEX|DISTINCT|COUNT|SUM|"
    r"AVG|MAX|MIN|BEGIN|COMMIT|TRANSACTION)\b",
    re.IGNORECASE,
)


def _score_sql(text: str, lines) -> float:
    kw_lines = sum(1 for ln in non_empty(lines)
                   if _SQL_KEYWORDS.search(ln))
    ratio = kw_lines / max(1, len(non_empty(lines)))
    score = min(1.0, ratio * 1.25)
    if ";" in text:
        score = min(1.0, score + 0.08)
    return score


# 常见 shell 命令（行首匹配用，末尾带空格避免误命中 prose 词）
_SHELL_CMDS = ("docker ", "git ", "brew ", "apt ", "apt-get", "sudo ", "cd ",
               "curl ", "wget ", "npm ", "pip ", "pip3", "echo ", "export ",
               "chmod ", "chown ", "rm ", "cp ", "mv ", "mkdir ", "grep ",
               "ssh ", "scp ", "ps ", "kill ", "make ", "cargo ", "pnpm ",
               "yarn ", "kubectl ", "terraform ", "env ", "unset ")
# 单行强命令判定（§8.14 docker compose up -d）：低歧义的命令动词
_SINGLE_LINE_CMDS = ("docker ", "git ", "brew ", "apt ", "apt-get", "curl ",
                     "wget ", "npm ", "pip ", "pip3", "cargo ", "pnpm ",
                     "yarn ", "kubectl ", "ssh ", "scp ", "chmod ", "chown ",
                     "make ", "export ", "echo ")


def _looks_like_command(text: str) -> bool:
    """单行字符串是否像 shell 命令（命令动词 + 参数，≤200 字符）。"""
    if len(text) > 200 or not re.search(r"\s", text.strip()):
        return False
    ls = text.strip()
    if ls.startswith("$ "):
        return True
    if ls.startswith("export ") and "=" in ls:
        return True
    return ls.startswith(_SINGLE_LINE_CMDS)


# 预处理器指令：不是 shell 注释（#include/#define/#if 等，实测把 C++ 误判为 shell）
_PREPROCESSOR = ("#include", "#define", "#if", "#ifdef", "#ifndef", "#endif",
                 "#elif", "#pragma", "#error", "#undef")
# markdown 标题（# 开头 + 空格）：不是 shell 注释。
# 需求/说明文档里满屏 "# 标题"，曾被计为注释把整份 md 误判成 shell（2026-08-08）
_MD_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+\S")
# 重定向：> 前不能是 < 或单词字符（避免 <int> 泛型被当作重定向）
_REDIRECT = re.compile(r"(?<![<\w])>\s*[\w./-]+")


def _score_shell(text: str, lines) -> float:
    strong = 0
    for line in lines:
        ls = line.strip()
        if ls.startswith("$ ") or ls.startswith("#!/") or ls.startswith("#!"):
            strong += 2
        elif ls.startswith("export ") and "=" in ls:
            strong += 2  # 环境变量赋值是强 shell 信号
        elif ls.startswith(_SHELL_CMDS):
            strong += 1
        elif re.search(r"\$\{?\w+\}?", ls):  # $VAR 引用
            strong += 1
        elif ls.startswith("#") and not ls.startswith(_PREPROCESSOR) \
                and not _MD_HEADING.match(ls):
            strong += 1  # 注释行（排除预处理器指令与 markdown 标题形行）
    if re.search(r"(&&|\|\|)", text):
        strong += 1
    if "|" in text or _REDIRECT.search(text):
        strong += 1
    if strong == 0:
        # 零信号返回 0.0：shell 原来有 0.45 保底分，任何纯文本/表格
        # 都会以最低分胜出被标成 shell（2026-08-08 用户实测误判）
        return 0.0
    return min(1.0, 0.45 + 0.18 * strong)


_HTML_TAG = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*)>")


def _score_html(text: str, lines) -> float:
    tags = _HTML_TAG.findall(text)
    if not tags:
        return 0.0
    tag_lines = sum(1 for ln in lines if "<" in ln and ">" in ln)
    ratio = tag_lines / max(1, len(non_empty(lines)))
    score = min(1.0, 0.35 + 0.35 * ratio + 0.05 * min(8, len(tags)))
    if re.search(r"<!DOCTYPE|<html|</html>|<body|</body>|<head|<div", text,
                 re.IGNORECASE):
        score = max(score, 0.85)
    return score


_CSS_PROP = re.compile(r"^\s*[\w-]+\s*:\s*[^;{}]+;?\s*$")


def _score_css(text: str, lines) -> float:
    if "{" not in text or "}" not in text:
        return 0.0
    prop_lines = sum(1 for ln in lines if _CSS_PROP.match(ln))
    score = _score_from(prop_lines, per_hit=0.12)
    if re.search(r"@media|@import|:root|:hover|:focus|!important", text):
        score = min(1.0, score + 0.15)
    return score


_YAML_KEY = re.compile(r'^\s*[\w.\-"]+\s*:\s*(.*)$')
_YAML_LIST = re.compile(r"^\s*-\s+")


def _score_yaml(text: str, lines) -> float:
    keys = sum(1 for ln in non_empty(lines) if _YAML_KEY.match(ln))
    lists = sum(1 for ln in non_empty(lines) if _YAML_LIST.match(ln))
    total = max(1, len(non_empty(lines)))
    structure_ratio = (keys + lists) / total
    # 解析前先过结构门槛：PyYAML 会把不少 Python 代码解析成 dict
    # （'def foo():' 是合法 YAML 键），必须保证键值结构占主导才采信解析结果
    if structure_ratio >= 0.5:
        try:
            import yaml  # PyYAML（可选，仅增强判断）

            parsed = yaml.safe_load(text)
            if isinstance(parsed, (dict, list)):
                return 1.0
        except Exception:
            pass
    if structure_ratio == 0:
        # 零结构信号不得参与竞争（原 0.45 保底分把纯文本识别为 yaml）
        return 0.0
    score = min(1.0, 0.45 + 0.5 * structure_ratio)
    if lists >= 2:
        score = min(1.0, score + 0.1)
    return score


_MD_SIGNALS = (
    _MD_HEADING,                                # 标题
    re.compile(r"^\s*([-*+]|\d+\.)\s+"),       # 列表
    re.compile(r"^\s*```"),                     # 代码围栏
    re.compile(r"\[[^\]]+\]\([^)]+\)"),         # 链接
    re.compile(r"\*\*[^*]+\*\*|__[^_]+__"),     # 加粗
    re.compile(r"^\s*>\s+"),                    # 引用
    re.compile(r"^\s*\|.*\|"),                  # 表格
)


def _score_markdown(text: str, lines) -> float:
    hits = 0
    for ln in non_empty(lines):
        if any(pat.search(ln) for pat in _MD_SIGNALS):
            hits += 1
    if hits == 0:
        return 0.0  # 零信号不得参与竞争（原 0.4 保底分把纯文本识别为 markdown）
    score = min(1.0, 0.4 + 0.13 * hits)
    if re.search(r"^#{1,6}\s", text, re.MULTILINE) and "```" in text:
        score = max(score, 0.85)  # 标题+代码块 = 明显 Markdown 文档
    return score


def _md_distinct_types(lines) -> int:
    """命中的 markdown 结构信号种类数（标题/列表/围栏/链接/加粗/引用/表格）。

    shell↔markdown 裁决用：shell 脚本的注释行最多形似标题（1 种），
    真正的 md 文档通常同时具备列表/引用/表格等 ≥2 种结构。
    """
    kinds = 0
    for pat in _MD_SIGNALS:
        if any(pat.search(ln) for ln in non_empty(lines)):
            kinds += 1
    return kinds


def non_empty(lines) -> list:
    return [ln for ln in lines if ln.strip()]
