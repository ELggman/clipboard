"""Clipboard Workspace 应用包。"""
from pathlib import Path

__version__ = "0.1.0"
APP_ID = "com.clipboardworkspace.app"  # 一经发布不可更改（改动会导致全部 TCC 授权失效）

ROOT_DIR = Path(__file__).resolve().parent.parent  # 项目根目录（dev 模式数据目录的基址）
