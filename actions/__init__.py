"""Action 加载器：扫描内置 actions/ 与用户插件目录，运行时加载。

⚠️ PyInstaller 坑：运行时 importlib 加载的模块不会被静态分析收集。
内置 actions 打包时需在 spec 里 collect_submodules('actions')；
用户插件目录（V3 开放扩展）放在应用外部，天然不打包。
"""
import importlib.util
import logging
import sys
from pathlib import Path

from ._base import ClipboardAction

logger = logging.getLogger(__name__)

ACTIONS_DIR = Path(__file__).resolve().parent


def load_actions(*extra_dirs: Path) -> list[ClipboardAction]:
    """加载所有 Action。extra_dirs 为用户插件目录（V3 开放扩展）。

    id 重复时只保留第一个，冲突记 warning。
    """
    actions: list[ClipboardAction] = []
    seen: set[str] = set()

    for directory in (ACTIONS_DIR, *extra_dirs):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):  # 跳过 base/私有模块
                continue
            action = _load_action_module(path)
            if action is None:
                continue
            if action.id in seen:
                logger.warning("Action id 重复，忽略: %s（%s）", action.id, path.name)
                continue
            seen.add(action.id)
            actions.append(action)

    logger.info("已加载 %d 个 Action", len(actions))
    return actions


def _load_action_module(path: Path) -> ClipboardAction | None:
    """从单个 .py 文件加载模块，取其 ACTION 实例。失败不中断整体加载。

    模块名必须带 actions. 前缀注册，否则相对导入（from ._base import ...）
    报 "attempted relative import with no known parent package"。
    """
    module_name = f"{__name__}.{path.stem}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module.ACTION
    except Exception:
        logger.exception("Action 加载失败: %s", path)
        return None
