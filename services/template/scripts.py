"""随应用发货的脚本目录与解析（命令值源的 `cw:<名>` 形式，文档 §变量-值源）。

命令值源的 `config.command` 支持一个显式短形式 `cw:<脚本名>`：把「跑一个文件」
从「手写绝对路径 + 自己挑解释器」变成「写个名字」，于是脚本可以**随应用发货**。

两个目录（**用户优先 → 同名覆盖内置**）：

- ``config/scripts/``    用户可写。drop-in：把文件丢进这个目录就能用
- ``resources/scripts/`` 随应用发货、只读、随版本更新

发货脚本一律**只用 Python 标准库**，用**应用自己的解释器**跑。理由是实测的：
`jq` 这类工具既不在 `/usr/bin`、也不在 launchd 给自启进程的极小 PATH 里；而
应用自己一定是一个 Python 进程，取它的解释器 = 零外部依赖、零 PATH 问题。
打包版（PyInstaller）的 `sys.executable` 是应用二进制、**不能**执行 .py，
故退到系统 python3（发货脚本只用标准库，3.9+ 都能跑）。
"""
import logging
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from app import ROOT_DIR

logger = logging.getLogger(__name__)

# 命令里引用脚本的前缀。显式前缀是刻意的：裸名解析会让自定义变量悄悄顶掉
# 真实命令（名叫 date 的脚本会盖住 /bin/date），排查起来极其费解。
SCRIPT_PREFIX = "cw:"
USER_SCRIPTS_DIR = ROOT_DIR / "config" / "scripts"
BUILTIN_SCRIPTS_DIR = ROOT_DIR / "resources" / "scripts"
# 脚本互调的入口：目录列表（os.pathsep 分隔），脚本里 `"$CW_SCRIPT_DIR/foo.py"`
SCRIPT_DIR_ENV = "CW_SCRIPT_DIR"
# 脚本元数据：首行注释 `# cw: <一句话说明>`（「脚本列表/错误提示」用）
DESC_PREFIX = "# cw:"
# 可选：`# cw-timeout: 8` 覆盖命令默认超时（活数据脚本要联网，5s 不够）
TIMEOUT_PREFIX = "# cw-timeout:"
# 会注册成模板变量的文件后缀。其余文件不进变量表——脚本可以带同目录数据文件
# （`data.txt`），下划线开头的（`_common.py`）视为被别的脚本 import 的辅助模块。
VARIABLE_SUFFIXES = (".py", ".sh", "")
# 打包版的解释器候选（按顺序取第一个存在的）
_FROZEN_PYTHON = ("/usr/bin/python3", "/opt/homebrew/bin/python3",
                  "/usr/local/bin/python3")
# 用应用自己的解释器跑的后缀；其余按 /bin/sh 跑（含无后缀、带 shebang 的）
_PY_SUFFIXES = (".py",)
_READ_FIRST_LINES = 5          # 元数据只扫开头几行，避免读整个大脚本


@dataclass(frozen=True)
class ScriptInfo:
    """一个可用脚本（发货或用户）。"""

    name: str            # 引用名（文件名去掉后缀）
    path: Path
    description: str = ""
    timeout: float | None = None   # 脚本自报的超时（`# cw-timeout:`），无则 None
    builtin: bool = False   # True = 随应用发货（用户目录里没有同名文件）

    @property
    def ref(self) -> str:
        """在 `config.command` 里写的引用文本。"""
        return f"{SCRIPT_PREFIX}{self.name}"


def is_variable_file(path: Path) -> bool:
    """这个文件是否注册成模板变量（后缀白名单 + 非下划线开头）。"""
    if path.name.startswith(".") or path.stem.startswith("_"):
        return False
    return path.suffix in VARIABLE_SUFFIXES


def script_dirs() -> list[Path]:
    """脚本搜索目录：用户目录在前（同名时用户脚本赢）。"""
    return [USER_SCRIPTS_DIR, BUILTIN_SCRIPTS_DIR]


def is_script_ref(command: str) -> bool:
    return (command or "").strip().startswith(SCRIPT_PREFIX)


def parse_ref(command: str) -> tuple[str, str]:
    """`cw:<名>` → (脚本名, 错误消息)。合法时错误消息为空串。

    名称里**不允许空格**：`cw:extract url` 里的 `url` 会被当成参数——那正是
    参数静默丢弃那一类坑（见 parser.validate_args），宁可报错。
    """
    rest = (command or "").strip()[len(SCRIPT_PREFIX):].strip()
    if not rest:
        return "", f"脚本引用为空——请写 {SCRIPT_PREFIX}<脚本名>"
    if len(rest.split()) > 1:
        return "", (f"脚本引用只接脚本名（收到 {rest!r}）；"
                    f"参数请写在模板里 `{{{{变量名:参数}}}}`")
    return rest, ""


def resolve(name: str) -> Path | None:
    """脚本名 → 文件路径。找不到返回 None。

    只取文件名的最后一段（`cw:../../etc/passwd` 不成立）；允许省略后缀
    （`cw:upper` 命中 `upper.py`）。
    """
    stem = Path(name).name
    if stem in ("", ".", ".."):
        return None
    for directory in script_dirs():
        candidate = directory / stem
        if candidate.is_file():
            return candidate
        if not Path(stem).suffix:
            for suffix in (".py", ".sh"):
                candidate = directory / f"{stem}{suffix}"
                if candidate.is_file():
                    return candidate
    return None


def interpreter_for(path: Path) -> list[str]:
    """脚本文件 → 启动它的 argv 前缀（参数由调用方追加在后面）。"""
    if path.suffix in _PY_SUFFIXES:
        return [python_interpreter()]
    return ["/bin/sh"]


def python_interpreter() -> str:
    """跑发货脚本用的解释器（绝对路径优先，避免依赖 PATH）。"""
    if not getattr(sys, "frozen", False):
        return sys.executable or "python3"
    for candidate in _FROZEN_PYTHON:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("python3") or "python3"


def script_env() -> dict[str, str]:
    """脚本进程该多拿的环境变量（叠加在 CW_* 之上，见 value_sources）。

    两个变量，都是为了「脚本目录可以是只读的」：
    - `CW_SCRIPT_DIR`：脚本互相调用的入口（`"$CW_SCRIPT_DIR/other.py"`）
    - `PYTHONDONTWRITEBYTECODE`：cwd 就在脚本目录里（见 run_script），
      Python 默认会往那儿写 `__pycache__/` —— 发货目录是只读的（打包后在
      .app 里），不该往里写东西。
    """
    env = {"PYTHONDONTWRITEBYTECODE": "1"}
    dirs = [str(d) for d in script_dirs() if d.is_dir()]
    if dirs:
        env[SCRIPT_DIR_ENV] = os.pathsep.join(dirs)
    return env


def read_meta(path: Path) -> tuple[str, float | None]:
    """脚本头部的自述：`# cw: 说明` + `# cw-timeout: 秒`。

    元数据写在脚本自己身上（而不是另开一份清单），于是「加一个脚本」真的
    只是加一个文件。缺项返回 ("", None)。
    """
    description = ""
    timeout: float | None = None
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for _ in range(_READ_FIRST_LINES):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if not description and stripped.startswith(DESC_PREFIX):
                    description = stripped[len(DESC_PREFIX):].strip()
                elif timeout is None and stripped.startswith(TIMEOUT_PREFIX):
                    try:
                        timeout = float(stripped[len(TIMEOUT_PREFIX):].strip())
                    except ValueError:
                        logger.warning("脚本超时值非法，忽略: %s", path)
    except OSError:
        logger.debug("读取脚本元数据失败: %s", path, exc_info=True)
    return description, timeout


def available_scripts() -> list[ScriptInfo]:
    """两个目录里可注册为变量的脚本（同名时只留用户那份），按名排序。"""
    found: dict[str, ScriptInfo] = {}
    for directory, builtin in ((BUILTIN_SCRIPTS_DIR, True),
                               (USER_SCRIPTS_DIR, False)):
        if not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if not path.is_file() or not is_variable_file(path):
                continue
            description, timeout = read_meta(path)
            # 同名时用户目录覆盖内置（先收内置、后收用户 → 用户赢）
            found[path.stem] = ScriptInfo(name=path.stem, path=path,
                                          description=description,
                                          timeout=timeout, builtin=builtin)
    return [found[k] for k in sorted(found)]


def available_names() -> str:
    """可用脚本名的逗号列表（拼「找不到脚本」的错误消息用）。"""
    names = [s.name for s in available_scripts()]
    return "、".join(names) if names else "（无）"
