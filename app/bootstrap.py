"""启动装配：配置 → 数据库 → 服务 → UI（全部延迟导入，保证启动 <1s）。

V1 核心闭环已打通：ClipboardWatcher 解析 → history_service 去重落库
→ MainWindow.refresh_history 刷新列表与状态栏。
"""
import logging

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
    from services import history_service
    from services.clipboard_watcher import ClipboardWatcher
    from services.hotkey_manager import HotkeyManager
    from services.image_service import ImageService

    image_service = ImageService(IMAGES_DIR)
    # parent=app：QObject 挂到应用对象上，防止 start_workspace 返回后
    # 局部引用被 GC 回收导致定时器/监听静默失效（实测踩坑）
    watcher = ClipboardWatcher(float(config["history"]["poll_interval"]), parent=app)
    hotkey = HotkeyManager(parent=app)

    # UI（装配完成前不弹窗）
    from ui.main_window import MainWindow

    window = MainWindow()
    window.show()

    # 闭环：监听 → 图片落盘 → 去重落库 → UI 刷新
    def on_clipboard_changed(item: ClipboardItem) -> None:
        if item.type == "image" and item.data:
            try:
                item.file_path = str(image_service.save(item.data))
                item.data = b""  # 释放内存
            except Exception:
                logger.exception("图片保存失败，放弃本条")
                return
        is_new = history_service.save_item(
            engine, item, max_items=int(config["history"]["max_items"])
        )
        window.refresh_history(item, is_new)
        logger.info("已%s: type=%s hash=%s", "新增" if is_new else "去重更新", item.type, item.hash[:12])

    watcher.changed.connect(on_clipboard_changed)
    watcher.start()

    hotkey.activated.connect(_on_quick_paste)
    hotkey.permission_required.connect(_on_permission_required)
    if config["hotkey"]["enabled"]:
        hotkey.start()

    logger.info("启动完成")


# ---- 回调 ----

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
