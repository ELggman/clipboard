"""自定义变量值源 provider 注册表（扩展性设计，文档 §变量-值源）。

每次渲染时一个自定义变量的值只来自一个源头。四种来源：
- SOURCE_INPUT：用户输入（触发前已收集到 ctx.input_values）
- SOURCE_FIXED：固定值/默认值（config.text 原样插入，严格固定）
- SOURCE_COMMAND：外部命令/脚本（config.command 经 sh -c 执行，stdout
  作结果，非零退出 → 空串 + 日志警告）
- SOURCE_STATE：系统状态（config.state；v1 仅前台应用名）

扩展新值源：新增一个 ValueSourceProvider 子类 + build_value_sources()
里注册一行即可。外部命令来源本身就是一个「脚本扩展」通道——不写 Python
也能接任意命令/脚本，与 provider 接口形成两层扩展。
"""
import logging
import subprocess
from abc import ABC, abstractmethod

from .registry import SOURCE_COMMAND, SOURCE_FIXED, SOURCE_INPUT, SOURCE_STATE
from .variables import RenderContext

logger = logging.getLogger(__name__)

# 外部命令超时（秒）：超过即放弃、返回空串（同步执行，v1 不做异步）
_COMMAND_TIMEOUT = 5


class ValueSourceProvider(ABC):
    """值源渲染接口：变量定义 + 渲染上下文 → 文本片段。"""

    source_type: str = ""

    @abstractmethod
    def render(self, name: str, config: dict, ctx: RenderContext) -> str:
        raise NotImplementedError


class InputValueSource(ValueSourceProvider):
    """用户输入：值在渲染前已收集（ctx.input_values[name]）。"""

    source_type = SOURCE_INPUT

    def render(self, name: str, config: dict, ctx: RenderContext) -> str:
        return ctx.input_values.get(name, "")


class FixedValueSource(ValueSourceProvider):
    """固定值/默认值：config.text 原样插入（严格固定，不做任何替换）。"""

    source_type = SOURCE_FIXED

    def render(self, name: str, config: dict, ctx: RenderContext) -> str:
        return str(config.get("text", ""))


class CommandValueSource(ValueSourceProvider):
    """外部命令/脚本：config.command 经 /bin/sh -c 执行。

    stdout 去首尾空白作结果；非零退出码 / 超时 / 异常 → 空串 + 日志警告
    （不抛异常——渲染失败不该让整次插入崩溃）。
    """

    source_type = SOURCE_COMMAND

    def render(self, name: str, config: dict, ctx: RenderContext) -> str:
        command = str(config.get("command", "")).strip()
        if not command:
            logger.warning("自定义变量 %s 命令为空", name)
            return ""
        try:
            result = subprocess.run(
                ["/bin/sh", "-c", command],
                capture_output=True, text=True, timeout=_COMMAND_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.warning("自定义变量 %s 命令超时（>%ss）: %s",
                           name, _COMMAND_TIMEOUT, command)
            return ""
        except Exception:
            logger.exception("自定义变量 %s 命令执行异常: %s", name, command)
            return ""
        if result.returncode != 0:
            logger.warning("自定义变量 %s 命令退出码 %s: %s",
                           name, result.returncode, command)
            return ""
        return result.stdout.strip()


class StateValueSource(ValueSourceProvider):
    """系统状态：config.state 指定读哪个系统状态（框架预留，v1 仅前台应用）。

    读取函数可注入（_frontmost_app_name 模块级可 monkeypatch 替换测试）；
    未知 state → 空串 + 警告。
    """

    source_type = SOURCE_STATE

    def render(self, name: str, config: dict, ctx: RenderContext) -> str:
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
