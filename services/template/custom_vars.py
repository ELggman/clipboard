"""自定义变量持久化（config template.extra_variables）+ 旧格式迁移。

extra_variables 从早期 `list[str]`（如 ["{{location}}"]）迁移到结构化
`list[dict]`（{name, description, source, config}）。读取时对旧字符串项
自动迁移（剥 {{}}、默认 input 来源），首次保存落盘为新格式——旧用户数据
零丢失。模块不依赖 PySide6（service 层可安全导入）。
"""
import logging

from .registry import CustomVariable, SOURCE_INPUT

logger = logging.getLogger(__name__)


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
    """name → CustomVariable 映射（parser/renderer 用）。"""
    return {v.name: v for v in load_extra_variables()}


def extra_insert_texts() -> list[str]:
    """自定义变量插入文本列表（胶囊区/自动补全/变量库行用）。"""
    return [v.insert() for v in load_extra_variables()]
