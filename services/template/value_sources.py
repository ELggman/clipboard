"""自定义变量值源 provider 注册表（扩展性设计，文档 §变量-值源）。

每次渲染时一个自定义变量的值只来自一个源头。四种来源：
- SOURCE_INPUT：用户输入（触发前已收集到 ctx.input_values）
- SOURCE_FIXED：固定值/默认值（config.text 原样插入，严格固定）
- SOURCE_COMMAND：外部命令/脚本（config.command 经 sh -c 执行，stdout
  作结果；失败按 config.on_error 处理 = 留空/兜底文案/放弃整次插入）
- SOURCE_STATE：系统状态（config.state；v1 仅前台应用名）

扩展新值源：新增一个 ValueSourceProvider 子类 + build_value_sources()
里注册一行即可。外部命令来源本身就是一个「脚本扩展」通道——不写 Python
也能接任意命令/脚本，与 provider 接口形成两层扩展。
"""
import logging
import os
import shlex
import subprocess
import time
from abc import ABC, abstractmethod

from . import scripts
from .errors import VariableValueError
from .registry import SOURCE_COMMAND, SOURCE_FIXED, SOURCE_INPUT, SOURCE_STATE
from .variables import RenderContext

logger = logging.getLogger(__name__)

# 外部命令超时（秒）：默认 5s，可被 config.timeout 覆盖（同步执行，v1 不做异步）
_COMMAND_TIMEOUT = 5
# 超时上限/下限（防呆）：用户填 999 会把触发链路卡死
_TIMEOUT_RANGE = (1, 60)
# stderr 记入日志时的截断长度（脚本报错常带整段堆栈，不截断会淹没日志）
_STDERR_LIMIT = 300

# 命令失败策略（自定义变量 config.on_error）
ERROR_EMPTY = "empty"    # 留空（默认，旧行为）
ERROR_TEXT = "text"      # 插入兜底文案（config.on_error_text）
ERROR_CANCEL = "cancel"  # 放弃整次插入（半句话插进正文比什么都不插更糟）
ERROR_LABELS = {
    ERROR_EMPTY: "留空",
    ERROR_TEXT: "插入兜底文案",
    ERROR_CANCEL: "放弃本次插入",
}
DEFAULT_ERROR_TEXT = "[变量取值失败]"

# ---- 失败可见通道（bootstrap 注入托盘通知；services 层不依赖 Qt）----
_error_reporter = None


def set_error_reporter(reporter) -> None:
    """注册变量取值失败的可见通道：reporter(变量名, 原因)。

    未注册时静默（仅日志）——services 保持无 GUI 依赖，测试也不必造 GUI。
    """
    global _error_reporter
    _error_reporter = reporter


def _report(name: str, message: str) -> None:
    if _error_reporter is None:
        return
    try:
        _error_reporter(name, message)
    except Exception:  # 通知失败绝不影响渲染结果
        logger.debug("变量取值失败通知回调异常", exc_info=True)


def _clip(text: str) -> str:
    """日志用截断（stderr 可能是一整段堆栈）。"""
    text = (text or "").strip()
    return text if len(text) <= _STDERR_LIMIT else text[:_STDERR_LIMIT] + "…"



class ValueSourceProvider(ABC):
    """值源渲染接口：变量定义 + 渲染上下文 → 文本片段。

    args：模板里 `{{name:参数}}` 的**参数原文**（只有 command 来源用它——
    shlex 切开后作脚本的 `$1..`；其余来源的 args 在保存期就被拒，见
    parser.validate_template）。
    """

    source_type: str = ""

    @abstractmethod
    def render(self, name: str, config: dict, ctx: RenderContext,
               args: str = "") -> str:
        raise NotImplementedError


class InputValueSource(ValueSourceProvider):
    """用户输入：值在渲染前已收集（ctx.input_values[name]）。"""

    source_type = SOURCE_INPUT

    def render(self, name: str, config: dict, ctx: RenderContext,
               args: str = "") -> str:
        return ctx.input_values.get(name, "")


class FixedValueSource(ValueSourceProvider):
    """固定值/默认值：config.text 原样插入（严格固定，不做任何替换）。"""

    source_type = SOURCE_FIXED

    def render(self, name: str, config: dict, ctx: RenderContext,
               args: str = "") -> str:
        return str(config.get("text", ""))


# ---- 上下文注入（命令值源的三个输入通道，文档 §变量-值源）----
# 环境变量前缀：CW_ = Clipboard Workspace
ENV_PREFIX = "CW_"

# 环境变量名 → 说明（「变量库」/编辑器提示与文档共用一份事实源）
ENV_HELP: dict[str, str] = {
    "CW_VAR": "当前变量名",
    "CW_TEMPLATE": "模板原文",
    "CW_CLIPBOARD": "剪贴板内容",
    "CW_SELECTION": "选中文本（无选中时为空串）",
    "CW_APP": "目标应用名",
    "CW_NOW": "触发时间（ISO 8601）",
    "CW_ARGS": "{{变量:参数}} 的参数原文",
    "CW_INPUT_<名>": "每个输入变量的值（名大写，如 {{input:who}} → CW_INPUT_WHO）",
    "CW_SCRIPT_DIR": "脚本目录（config/scripts 与 resources/scripts，用户目录在前）",
}

# PATH 兜底补目录：开机自启时 launchd 给的 PATH 极小，脚本里调 /usr/local/bin、
# /opt/homebrew/bin 下的工具会「找不到」。**追加而非覆盖**——PATH 里已有的条目
# 优先级不变，只是补齐完全缺失的目录。
_FALLBACK_PATH_DIRS = ("/usr/local/bin", "/opt/homebrew/bin",
                       "/usr/bin", "/bin", "/usr/sbin", "/sbin")


def split_args(raw: str) -> list[str]:
    """`{{name:参数}}` 原文 → 参数列表（脚本的 $1..）。

    按 shell 习惯切分：`{{sum:1 2}}` → ['1','2']，`{{say:"你好 世界"}}` →
    ['你好 世界']（引号成对时保留空格）。引号不成对（shlex 报错）不报错、
    整串当一个参数——模板里写参数没补全引号太容易，不该因此整次插入失败。
    """
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return [raw]


def ensure_path(env: dict) -> None:
    """补齐 PATH 里缺失的标准目录（就地修改）。

    只追加、不重排：用户 PATH 里已有的条目优先级完全不变，所以这不会让某个
    命令从「用户想用的那个」变成「系统的那个」；它只把「完全找不到」变成
    「找得到」。开机自启是这条存在的理由（launchd 的 PATH 只有
    /usr/bin:/bin:/usr/sbin:/sbin，见 DEVELOPMENT.md §4.2）。
    """
    parts = [p for p in (env.get("PATH") or "").split(os.pathsep) if p]
    for directory in _FALLBACK_PATH_DIRS:
        if directory not in parts:
            parts.append(directory)
    env["PATH"] = os.pathsep.join(parts)


def build_command_env(name: str, ctx: RenderContext, args: str = "") -> dict:
    """命令值源的环境变量：os.environ 基础上叠加 CW_*（见 ENV_HELP）。

    继承 os.environ 是刻意的——脚本该能用到用户自己的 PATH/HOME 等。
    """
    env = dict(os.environ)
    env[f"{ENV_PREFIX}VAR"] = name
    env[f"{ENV_PREFIX}TEMPLATE"] = ctx.template or ""
    env[f"{ENV_PREFIX}CLIPBOARD"] = ctx.clipboard_text or ""
    env[f"{ENV_PREFIX}SELECTION"] = ctx.selection_text or ""
    env[f"{ENV_PREFIX}APP"] = ctx.app_name or ""
    env[f"{ENV_PREFIX}NOW"] = ctx.now.isoformat(timespec="seconds")
    env[f"{ENV_PREFIX}ARGS"] = args or ""
    for key, value in (ctx.input_values or {}).items():
        # 中文变量名大写化没有意义（str.upper 对汉字是恒等），原样保留
        env[f"{ENV_PREFIX}INPUT_{str(key).upper()}"] = str(value)
    env.update(scripts.script_env())
    ensure_path(env)
    return env


def stdin_for(ctx: RenderContext) -> str:
    """命令值源的 stdin：选中文本，无选中则剪贴板（都没有 → 空）。

    这是「把选中的东西交给脚本处理」的最短路径——脚本 `cat` 就读到了，
    不必先想清楚该读哪个环境变量。
    """
    return ctx.selection_text or ctx.clipboard_text or ""


class CommandRun:
    """一次命令执行的结果（渲染取 stdout；编辑器「试运行」取全部字段）。"""

    def __init__(self, ok: bool, stdout: str = "", stderr: str = "",
                 error: str = "", returncode: int | None = None,
                 duration_ms: int = 0):
        self.ok = ok
        self.stdout = stdout
        self.stderr = stderr
        self.error = error            # 失败原因（超时/异常/非零退出），面向用户
        self.returncode = returncode
        self.duration_ms = duration_ms

    @property
    def text(self) -> str:
        """渲染用的值：成功 = stdout 去首尾空白；失败 = 空串（策略另定）。"""
        return self.stdout.strip() if self.ok else ""


def run_command(command: str, timeout: float, env: dict | None = None,
                stdin_text: str = "", args: list[str] | None = None) -> CommandRun:
    """/bin/sh -c 执行一次命令（**只执行、不套失败策略**）。

    与策略分离是为了「试运行」：编辑器要看到退出码/stderr/耗时，而渲染
    只需按 on_error 决定插什么。这里不写日志、不上报——调用方决定。

    `command` 写成 `cw:<脚本名>` 时改走 `run_script`（发货脚本通道）。

    args：附加参数。经 `sh -c 'cmd' <$0> arg1 arg2…` 传入 → 脚本里是
    `$1`、`$2`、`$@`（$0 用占位名 `cw`，避免脚本第一条参数跑到 $0 上）。
    stdin：恒以管道喂入（默认空串）——**不继承本进程 stdin**，否则脚本里
    一个 `cat` 就会挂在终端上等输入，触发链路整个卡住。
    """
    if scripts.is_script_ref(command):
        name, error = scripts.parse_ref(command)
        if error:
            return CommandRun(False, error=error)
        return run_script(name, timeout, env=env, stdin_text=stdin_text,
                          args=args)

    argv = ["/bin/sh", "-c", command]
    extra = [str(a) for a in (args or [])]
    if extra:
        argv.append("cw")
        argv.extend(extra)
    return _execute(argv, timeout, env=env, stdin_text=stdin_text)


def run_script(name: str, timeout: float, env: dict | None = None,
               stdin_text: str = "", args: list[str] | None = None) -> CommandRun:
    """按名执行一个脚本（发货或用户），解释器由后缀决定。

    `.py` → 应用自己的解释器；其余（含无后缀、带 shebang）→ `/bin/sh`。
    参数直接跟在脚本路径后面 → `.py` 里是 `sys.argv[1:]`、sh 里是 `$1..`
    （比 `/bin/sh -c` 少一层，所以**不需要** `$0` 占位）。
    cwd 设成脚本所在目录：脚本可以带同目录的数据文件一起发货。
    """
    path = scripts.resolve(name)
    if path is None:
        return CommandRun(
            False, error=f"找不到脚本「{name}」"
                         f"（可用：{scripts.available_names()}）")
    argv = [*scripts.interpreter_for(path), str(path)]
    argv.extend(str(a) for a in (args or []))
    base = dict(os.environ) if env is None else dict(env)
    base.update(scripts.script_env())
    return _execute(argv, timeout, env=base, stdin_text=stdin_text,
                    cwd=str(path.parent))


def _execute(argv: list[str], timeout: float, env: dict | None = None,
             stdin_text: str = "", cwd: str | None = None) -> CommandRun:
    """真正跑子进程（argv 已成型）。`/bin/sh -c` 与 `cw:` 脚本共用。"""
    started = time.monotonic()

    def _elapsed() -> int:
        return int((time.monotonic() - started) * 1000)

    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, timeout=timeout,
            env=env, input=stdin_text, cwd=cwd)
    except subprocess.TimeoutExpired:
        return CommandRun(False, error=f"命令超时（>{timeout}s）",
                          duration_ms=_elapsed())
    except Exception as exc:
        return CommandRun(False, error=f"执行异常: {exc!r}",
                          duration_ms=_elapsed())
    if result.returncode != 0:
        detail = _clip(result.stderr) or "无 stderr"
        return CommandRun(False, stdout=result.stdout, stderr=result.stderr,
                          error=f"退出码 {result.returncode}：{detail}",
                          returncode=result.returncode, duration_ms=_elapsed())
    return CommandRun(True, stdout=result.stdout, stderr=result.stderr,
                      returncode=0, duration_ms=_elapsed())


class CommandValueSource(ValueSourceProvider):
    """外部命令/脚本：config.command 经 /bin/sh -c 执行。

    stdout 去首尾空白作结果。失败（空命令 / 非零退出 / 超时 / 异常）按
    **config.on_error** 处理（见 ERROR_*）：留空（默认）/ 兜底文案 / 抛
    VariableValueError 放弃整次插入。

    失败一律先上报（日志 + 注入的可见通道）——此前 stderr 被 capture 收走
    却从不记录，用户分不清「功能坏了」还是「脚本写错了」。

    `command` 写成 `cw:<脚本名>` → 走 `run_script`：在
    `config/scripts/`（用户）与 `resources/scripts/`（随应用发货）里按名找
    文件，`.py` 用应用自己的解释器跑（见 services/template/scripts.py）。

    三个上下文输入通道（脚本据此「知道现在是什么情况」）：
    - 环境变量 CW_*（见 ENV_HELP）
    - stdin = 选中文本（无选中则剪贴板）→ 脚本 `cat` 即可
    - `$1..$@` = 模板里 `{{变量:参数}}` 的参数（见 split_args）
    """

    source_type = SOURCE_COMMAND

    def render(self, name: str, config: dict, ctx: RenderContext,
               args: str = "") -> str:
        command = str(config.get("command", "")).strip()
        if not command:
            return self._fail(name, config, "命令为空")
        run = run_command(command, self._timeout(config),
                          env=build_command_env(name, ctx, args),
                          stdin_text=stdin_for(ctx),
                          args=split_args(args))
        if not run.ok:
            return self._fail(name, config, run.error, command)
        if run.stderr.strip():
            # 成功但有 stderr（工具的告警）：记 debug，不打扰
            logger.debug("自定义变量 %s stderr: %s", name, _clip(run.stderr))
        return run.text

    @staticmethod
    def _timeout(config: dict) -> float:
        """超时秒数：config.timeout（夹到 _TIMEOUT_RANGE）或模块默认。

        模块默认不夹（测试会把它调到 0.1 级别以缩短用例）；用户填的值才夹
        ——有人填 999 会把触发链路卡死。
        """
        raw = config.get("timeout")
        if raw in (None, ""):
            return _COMMAND_TIMEOUT
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return _COMMAND_TIMEOUT
        low, high = _TIMEOUT_RANGE
        return max(low, min(high, value))

    def _fail(self, name: str, config: dict, reason: str,
              command: str = "") -> str:
        """失败处理：记日志 + 上报 + 按 on_error 决定「留空/兜底/放弃」。"""
        logger.warning("自定义变量 %s 取值失败：%s%s", name, reason,
                       f"（命令：{command}）" if command else "")
        _report(name, reason)
        policy = str(config.get("on_error") or ERROR_EMPTY)
        if policy == ERROR_CANCEL:
            raise VariableValueError(f"变量「{name}」取值失败：{reason}")
        if policy == ERROR_TEXT:
            text = str(config.get("on_error_text") or "").strip()
            return text or DEFAULT_ERROR_TEXT
        return ""


class StateValueSource(ValueSourceProvider):
    """系统状态：config.state 指定读哪个系统状态（框架预留，v1 仅前台应用）。

    读取函数可注入（_frontmost_app_name 模块级可 monkeypatch 替换测试）；
    未知 state → 空串 + 警告。
    """

    source_type = SOURCE_STATE

    def render(self, name: str, config: dict, ctx: RenderContext,
               args: str = "") -> str:
        state = str(config.get("state", ""))
        if state == "frontmost_app":
            return _frontmost_app_name()
        logger.warning("自定义变量 %s 未知系统状态: %s", name, state)
        return ""


def _frontmost_app_name() -> str:
    """前台应用名（localizedName）。失败/无前台返回空串。"""
    try:
        from AppKit import NSWorkspace

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return app.localizedName() or "" if app is not None else ""
    except Exception:
        return ""


def build_value_sources() -> dict[str, ValueSourceProvider]:
    """值源 provider 注册表（新值源在此登记）。"""
    return {
        SOURCE_INPUT: InputValueSource(),
        SOURCE_FIXED: FixedValueSource(),
        SOURCE_COMMAND: CommandValueSource(),
        SOURCE_STATE: StateValueSource(),
    }
