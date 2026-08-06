"""开机启动：LaunchAgent plist 管理（DEVELOPMENT.md §4.2）。

标准做法：~/Library/LaunchAgents/com.clipboardworkspace.app.plist
+ `launchctl load -w`。dev 模式指向当前 python + main.py；
打包版由 build 管线替换为 .app 路径。
"""
import logging
import plistlib
import subprocess
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

LABEL = "com.clipboardworkspace.app"
DEFAULT_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
# dev 模式的启动命令（打包版替换为 .app）
_DEV_PYTHON = Path(sys.executable)
_DEV_SCRIPT = Path(__file__).resolve().parent.parent / "main.py"


def is_enabled(plist_path: Path = DEFAULT_PATH) -> bool:
    return plist_path.exists()


def set_enabled(enabled: bool, plist_path: Path = DEFAULT_PATH,
                python: Path = _DEV_PYTHON, script: Path = _DEV_SCRIPT) -> bool:
    """开启/关闭开机启动。返回是否成功（launchctl 失败不阻断文件写入）。"""
    try:
        if enabled:
            payload = {
                "Label": LABEL,
                "ProgramArguments": [str(python), str(script)],
                "RunAtLoad": True,
                "KeepAlive": False,
                "ProcessType": "Interactive",
            }
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            with open(plist_path, "wb") as f:
                plistlib.dump(payload, f)
            subprocess.run(["launchctl", "load", "-w", str(plist_path)],
                           capture_output=True, check=False)
            logger.info("开机启动已开启: %s", plist_path)
        else:
            if plist_path.exists():
                subprocess.run(["launchctl", "unload", str(plist_path)],
                               capture_output=True, check=False)
                plist_path.unlink()
            logger.info("开机启动已关闭")
        return True
    except OSError:
        logger.exception("开机启动设置失败")
        return False
