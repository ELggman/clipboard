"""配置加载：defaults.yaml 合并用户 settings.yaml，缺失字段回退默认值。"""
import copy
import logging
from pathlib import Path
from typing import Any

import yaml

from app import ROOT_DIR

CONFIG_DIR = ROOT_DIR / "config"

logger = logging.getLogger(__name__)


def save_user_config(overrides: dict[str, Any], path: Path | None = None) -> None:
    """把用户设置合并写回 settings.yaml（设置页改动即存）。

    与既有用户配置深度合并，不覆盖 defaults.yaml；path 供测试注入临时目录。
    """
    target = path or CONFIG_DIR / "settings.yaml"
    existing = _load_yaml(target) if target.exists() else {}
    merged = _deep_merge(existing, overrides)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
    logger.info("用户配置已保存: %s", target)


def load_config() -> dict[str, Any]:
    defaults = _load_yaml(CONFIG_DIR / "defaults.yaml")
    user_path = CONFIG_DIR / "settings.yaml"
    user = _load_yaml(user_path) if user_path.exists() else {}
    merged = _deep_merge(defaults, user)
    logger.info("配置已加载（%s）", "含用户覆盖" if user else "仅默认值")
    return merged


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except OSError:
        logger.exception("读取配置失败: %s", path)
        return {}
    return data if isinstance(data, dict) else {}
