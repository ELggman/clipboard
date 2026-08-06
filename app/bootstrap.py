"""启动装配：配置 → 数据库 → 服务 → UI（全部延迟导入，保证启动 <1s）。

TODO: 落库/去重逻辑提取为 services/history_service.py（V1 打磨项）。
"""
import logging
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app import ROOT_DIR
from app.config import load_config
from app.types import ClipboardItem

logger = logging.getLogger(__name__)

DB_PATH = ROOT_DIR / "data" / "clipboard.db"
IMAGES_DIR = ROOT_DIR / "images"


def start_workspace(app: QApplication) -> None:
    config = load_config()

    # 数据库
    from database.engine import create_db_engine
    from database.migrations import migrate

    engine = create_db_engine(DB_PATH)
    migrate(engine)

    # 服务
    from services.clipboard_watcher import ClipboardWatcher
    from services.hotkey_manager import HotkeyManager
    from services.image_service import ImageService

    watcher = ClipboardWatcher(float(config["history"]["poll_interval"]))
    watcher.changed.connect(lambda item: _on_clipboard_changed(item, engine))
    watcher.start()

    hotkey = HotkeyManager()
    hotkey.activated.connect(_on_quick_paste)
    hotkey.permission_required.connect(_on_permission_required)
    if config["hotkey"]["enabled"]:
        hotkey.start()

    # UI（最后加载，成功装配前不弹窗）
    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()
    app._clipboard_window = window  # noqa: SLF001  # 供服务回调引用（临时接线）
    logger.info("启动完成")


# ---- 回调 ----

def _on_clipboard_changed(item: ClipboardItem, engine) -> None:
    """监听回调：图片先落盘，去重落库待实现。

    TODO(history_service):
      1. 按 hash 查重 → 已存在只更新 updated_at
      2. 落库 + items_fts 索引（search_service.reindex）
      3. 历史数量上限裁剪（max_items）
    """
    from services.image_service import ImageService

    if item.type == "image" and item.data:
        try:
            item.file_path = str(ImageService(IMAGES_DIR).save(item.data))
            item.data = b""  # 释放内存
        except Exception:
            logger.exception("图片保存失败，放弃本条")
            return
    # TODO: 持久化与 UI 刷新
    logger.info("待落库: type=%s hash=%s", item.type, item.hash[:12])


def _on_quick_paste() -> None:
    """⌘⇧V：弹出最近历史。

    TODO: 查最近 N 条（去重后）→ QuickPastePopup.populate()；
    selected 信号 → set_clipboard_text 重新复制。
    accessory 激活策略见 DEVELOPMENT.md §4.3。
    """
    logger.info("Quick Paste 触发（实现中）")


def _on_permission_required() -> None:
    """辅助功能未授权：提示引导，不弹窗打断（V1.5 做引导对话框）。"""
    logger.warning("需要「辅助功能」授权 ⌘⇧V 才能生效：系统设置 → 隐私与安全性 → 辅助功能")
