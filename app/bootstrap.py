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

    # 主题（浅/深/跟随系统；跟随系统时监听系统外观变化动态切换）
    from ui.theme import apply_theme

    theme = config["app"]["theme"]
    apply_theme(app, theme)
    if theme == "system":
        app.styleHints().colorSchemeChanged.connect(
            lambda _scheme: apply_theme(app, "system")
        )

    # 数据库
    from database.engine import create_db_engine
    from database.migrations import migrate

    engine = create_db_engine(DB_PATH)
    migrate(engine)

    # 服务
    from services import history_service
    from services.action_service import set_clipboard_item
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
    from ui.quick_paste_popup import QuickPastePopup

    window = MainWindow()
    window.set_image_service(image_service)  # 历史列表图片缩略图
    window.set_show_image_filename(bool(config["history"]["show_image_filename"]))
    window.set_search(engine)
    window.show()

    # 关窗后（窗口隐藏）点 Dock 图标 → 应用激活 → 重新显示窗口
    from PySide6.QtCore import Qt

    def on_app_state(state) -> None:
        if state == Qt.ApplicationState.ApplicationActive and not window.isVisible():
            window.show()
            window.raise_()
            logger.info("主窗口已重新显示")

    app.applicationStateChanged.connect(on_app_state)

    # 启动恢复：历史在 SQLite 持久化，重启后从数据库回填列表
    max_items = int(config["history"]["max_items"])
    restore_limit = 1000 if max_items < 0 else max_items
    window.load_history(history_service.list_recent(engine, limit=restore_limit))

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

    # Quick Paste（⌘⇧V）：最近 10 条 → 弹出层 → Enter 重新复制
    popup = QuickPastePopup()

    def on_quick_paste() -> None:
        items = history_service.list_recent(engine, limit=10)
        if not items:
            logger.info("Quick Paste：暂无历史")
            return
        logger.info("Quick Paste：弹出 %d 条", len(items))
        popup.populate(items)
        popup.show_near_cursor()

    def on_picked(item) -> None:
        if set_clipboard_item(item):
            logger.info("Quick Paste：已重新复制 %s", item.type)
        popup.close()

    popup.selected.connect(on_picked)
    hotkey.activated.connect(on_quick_paste)
    hotkey.permission_required.connect(_on_permission_required)
    if config["hotkey"]["enabled"]:
        hotkey.start()

    # 测试/调试钩子（不对外暴露 API）
    app._quick_paste_popup = popup
    app._on_quick_paste = on_quick_paste

    logger.info("启动完成")


# ---- 回调 ----

def _on_permission_required() -> None:
    """辅助功能未授权：提示引导，不弹窗打断（V1.5 做引导对话框）。"""
    logger.warning("需要「辅助功能」授权 ⌘⇧V 才能生效：系统设置 → 隐私与安全性 → 辅助功能")
