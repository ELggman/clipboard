"""自定义变量持久化（config template.extra_variables）+ 旧格式迁移。

extra_variables 从早期 `list[str]`（如 ["{{location}}"]）迁移到结构化
`list[dict]`（{name, description, source, config}）。读取时对旧字符串项
自动迁移（剥 {{}}、默认 input 来源），首次保存落盘为新格式——旧用户数据
零丢失。模块不依赖 PySide6（service 层可安全导入）。

另有一条**不落用户配置**的来源：`config/scripts/` 与 `resources/scripts/`
里的脚本自动成为变量（`{{名}}` → `cw:名`，见 scripts.py）。脚本变量不进
extra_variables —— 于是随版本更新自动生效，用户删过的脚本也不会被配置
「复活」。它们照常出现在变量库/胶囊区（`visible_script_variables()`，
带 `# cw:` 描述），只是**不能在应用里编辑删除**——那要改文件。
"""
import logging

from .registry import CustomVariable, SOURCE_COMMAND, SOURCE_INPUT
from .scripts import available_scripts

logger = logging.getLogger(__name__)


def script_variables() -> list[CustomVariable]:
    """脚本目录 → 变量表项（外部命令来源，命令就是 `cw:<名>`）。

    用户自己丢进 `config/scripts/` 的脚本同样在这里出现——「加一个脚本」
    等于「多一个模板变量」，不必再进设置页配一遍。脚本头部的 `# cw:` 注释
    作描述、`# cw-timeout:` 作超时（活数据脚本要联网）。
    """
    out: list[CustomVariable] = []
    for info in available_scripts():
        config: dict = {"command": info.ref}
        if info.timeout:
            config["timeout"] = info.timeout
        out.append(CustomVariable(name=info.name, description=info.description,
                                  source=SOURCE_COMMAND, config=config))
    return out


def script_insert_texts() -> list[str]:
    """脚本变量的插入文本（模板编辑器自动补全用）。"""
    return [v.insert() for v in script_variables()]


def visible_script_variables() -> list[CustomVariable]:
    """脚本变量里**没被用户同名变量顶掉**的那些（变量库/胶囊区展示用）。

    与 load_custom_vars() 同一条覆盖规则（用户赢），否则会出现两个同名
    条目、而其中一个求值时根本不生效——展示与求值必须是同一份真相。
    """
    taken = {v.name for v in load_extra_variables()}
    return [v for v in script_variables() if v.name not in taken]


def load_extra_variables() -> list[CustomVariable]:
    """读 config → 结构化自定义变量列表（旧 list[str] 自动迁移）。"""
    try:
        from app.config import load_config

        raw = load_config().get("template", {}).get("extra_variables", []) or []
    except Exception:
        return []
    out: list[CustomVariable] = []
    for item in raw:
        var = _coerce(item)
        if var is not None:
            out.append(var)
    return out


def _coerce(item) -> CustomVariable | None:
    """单项 → CustomVariable（旧字符串 / 新 dict 都支持）；非法返回 None。"""
    if isinstance(item, str):
        name = item.strip()
        if not name:
            return None
        if name.startswith("{{") and name.endswith("}}"):
            name = name[2:-2]
        return CustomVariable(name=name, source=SOURCE_INPUT)
    if isinstance(item, dict):
        name = str(item.get("name", "")).strip()
        if not name:
            return None
        return CustomVariable(
            name=name,
            description=str(item.get("description", "")),
            source=str(item.get("source", SOURCE_INPUT)),
            config=dict(item.get("config") or {}),
        )
    return None


def save_extra_variables(vars_list: list[CustomVariable]) -> None:
    """持久化自定义变量（结构化 dict 落盘）。"""
    try:
        from app.config import save_user_config

        payload = [{
            "name": v.name,
            "description": v.description,
            "source": v.source,
            "config": v.config,
        } for v in vars_list]
        save_user_config({"template": {"extra_variables": payload}})
    except Exception:
        logger.exception("保存自定义变量失败")


def load_custom_vars() -> dict[str, CustomVariable]:
    """name → CustomVariable 映射（parser/renderer 用）。

    脚本变量垫在底下，**用户同名变量覆盖它们**——与「用户脚本同名覆盖内置
    脚本」（scripts.resolve）同一条规则，两个方向都指向"用户的定义赢"。
    """
    merged = {v.name: v for v in script_variables()}
    merged.update({v.name: v for v in load_extra_variables()})
    return merged


def extra_insert_texts() -> list[str]:
    """自定义变量插入文本列表（胶囊区/自动补全/变量库行用）。"""
    return [v.insert() for v in load_extra_variables()]
