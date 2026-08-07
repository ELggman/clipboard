"""启动装配：配置 → 数据库 → 服务 → UI（全部延迟导入，保证启动 <1s）。

V1 核心闭环已打通：ClipboardWatcher 解析 → history_service 去重落库
→ MainWindow.refresh_history 刷新列表与状态栏。
"""
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from app import ROOT_DIR
from app.config import load_config
from app.types import ClipboardItem

logger = logging.getLogger(__name__)

DB_PATH = ROOT_DIR / "data" / "clipboard.db"
IMAGES_DIR = ROOT_DIR / "images"


class PrivacyState(QObject):
    """隐私模式运行时状态：暂停监控开关（⌘⇧P / 设置页按钮共用）。

    不是持久化配置——仅本次运行的暂停/恢复（新增.md §9.3/§9.8）。
    """

    changed = Signal(bool)  # 是否已暂停

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    def toggle(self) -> None:
        self._paused = not self._paused
        logger.info("隐私模式已%s", "暂停" if self._paused else "恢复")
        self.changed.emit(self._paused)


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
    from services.action_service import ActionService, set_clipboard_item
    from services.clipboard_watcher import ClipboardWatcher
    from services.hotkey_manager import HotkeyManager
    from services.image_service import ImageService

    action_service = ActionService()  # 右键 Actions 子菜单

    image_service = ImageService(IMAGES_DIR)
    # parent=app：QObject 挂到应用对象上，防止 start_workspace 返回后
    # 局部引用被 GC 回收导致定时器/监听静默失效（实测踩坑）
    watcher = ClipboardWatcher(float(config["history"]["poll_interval"]), parent=app)
    hotkey = HotkeyManager(parent=app)

    # UI（装配完成前不弹窗）
    from ui.item_detail_popup import ItemDetailPopup
    from ui.main_window import MainWindow
    from ui.quick_paste_popup import QuickPastePopup

    window = MainWindow()
    detail_popup = ItemDetailPopup()

    window.set_image_service(image_service)  # 历史列表图片缩略图
    window.set_show_image_filename(bool(config["history"]["show_image_filename"]))
    window.set_search(engine)
    window.set_menu_context(engine, action_service)  # 右键菜单
    window.set_data_context(engine, image_service)  # 收藏夹/片段/时间线页
    window.set_item_activated_handler(  # 各列表页单击 → 详情弹层（可选中部分复制）
        lambda item: detail_popup.show_item(item, image_service))
    window.show()

    # 隐私模式：⌘⇧P 暂停/恢复监听 → watcher 停止保存 + 状态栏指示（§9.3/§9.4）
    privacy_state = PrivacyState(app)

    def on_privacy_changed(paused: bool) -> None:
        watcher.set_paused(paused)
        window.set_privacy_status(paused)

    privacy_state.changed.connect(on_privacy_changed)
    window.set_privacy_status(False)  # 初始「📋 监控中」

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
    window.load_history(history_service.list_recent(engine, limit=restore_limit),
                        limit=restore_limit)

    # 设置页：改动即生效的回调
    from ui.theme import apply_theme

    def apply_setting(key: str):
        def _apply(overrides: dict) -> None:
            if key == "theme":
                apply_theme(app, overrides["app"]["theme"])
            elif key == "font":
                window.set_font_size(int(overrides["app"]["font_size"]))
            elif key == "show_filename":
                window.set_show_image_filename(
                    bool(overrides["history"]["show_image_filename"]))
            elif key == "autostart":
                from services.autostart import set_enabled

                set_enabled(bool(overrides["app"]["launch_at_login"]))
            elif key == "max_items":
                n = int(overrides["history"]["max_items"])
                if history_service.trim_history(engine, n) and window.isVisible():
                    window._reload_history()
            elif key == "privacy_policy":
                # 敏感策略即时生效（on_clipboard_changed 读内存 config）
                config["privacy"]["policy"] = overrides["privacy"]["policy"]
            elif key == "privacy_temp":
                config["privacy"]["temp_minutes"] = int(
                    overrides["privacy"]["temp_minutes"])
            elif key == "privacy_ignored":
                config["privacy"]["ignored_apps"] = list(
                    overrides["privacy"]["ignored_apps"])
            elif key == "max_file_size":
                # 文档大小上限即时生效（on_clipboard_changed 读内存 config）
                config["history"]["max_file_size_mb"] = int(
                    overrides["history"]["max_file_size_mb"])
            # save_images / auto_delete 下次插入或清扫时生效
        return _apply

    window.set_settings_context(
        config,
        {k: apply_setting(k) for k in ("theme", "font", "show_filename",
                                       "autostart", "max_items",
                                       "privacy_policy", "privacy_temp",
                                       "privacy_ignored", "max_file_size")},
        engine=engine,
        privacy_state=privacy_state,
    )

    # 自动删除：每日清扫一次（启动 1 分钟后首扫）
    from PySide6.QtCore import QTimer

    def sweep_old_history() -> None:
        # 按保留天数清扫（置顶豁免，§9.10/§9.22）+ 过期临时条目（§9.9）
        removed_files: list[str] = []
        days = int(config["history"]["auto_delete_days"])
        if days > 0:
            removed_files += history_service.delete_older_than(engine, days)
        removed_files += history_service.delete_expired(engine)
        for path in removed_files:
            # 被收藏夹快照引用的图片保留（否则收藏粘贴失效）
            from services import collection_service

            if not collection_service.is_file_path_referenced(engine, path):
                image_service.delete(path)
        if removed_files:
            window._reload_history()

    sweep_timer = QTimer(app)
    sweep_timer.setInterval(24 * 3600 * 1000)
    sweep_timer.timeout.connect(sweep_old_history)
    sweep_timer.start()
    QTimer.singleShot(60_000, sweep_old_history)

    # 闭环：监听 → 隐私管线（排除/敏感策略）→ 图片落盘 → 去重落库 → UI 刷新
    def on_clipboard_changed(item: ClipboardItem) -> None:
        decision = apply_privacy_policy(item, config["privacy"])
        if decision != "save":
            # 跳过原因（不含内容，§9.23）→ 状态栏 3 秒反馈
            window.statusBar().showMessage(
                "已忽略来自 %s 的剪贴板" % item.source_app
                if decision == "excluded"
                else "检测到潜在机密，已忽略", 3000)
            return

        # 文档大小上限（设置可调）：超限不加入历史
        max_mb = int(config["history"].get("max_file_size_mb", 50))
        if file_too_large(item, max_mb):
            logger.info("Clipboard item ignored reason=file_too_large")
            window.statusBar().showMessage(
                f"已忽略超过 {max_mb}MB 的文件", 3000)
            return

        # 图片落盘
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
    # 隐私模式热键 ⌘⇧P（§9.4）：同一 CGEventTap 多绑定
    from services.hotkey_manager import KEY_P, MASK_HOTKEY

    hotkey.add_binding(KEY_P, MASK_HOTKEY, hotkey.privacy_toggle)
    hotkey.privacy_toggle.connect(privacy_state.toggle)
    hotkey.permission_required.connect(_on_permission_required)
    if config["hotkey"]["enabled"]:
        hotkey.start()

    # 测试/调试钩子（不对外暴露 API）
    app._quick_paste_popup = popup
    app._on_quick_paste = on_quick_paste

    logger.info("启动完成")


# ---- 回调 ----

def file_too_large(item: ClipboardItem, max_mb: int) -> bool:
    """文档大小超限检查（0 = 不限制；文件不可读按不超限处理）。"""
    if max_mb <= 0 or item.type != "file" or not item.file_path:
        return False
    try:
        return Path(item.file_path).stat().st_size > max_mb * 1024 * 1024
    except OSError:
        logger.debug("文件不可读，跳过大小检查: %s", item.file_path)
        return False


def apply_privacy_policy(item: ClipboardItem, privacy: dict) -> str:
    """隐私管线决策（新增.md §9.5-9.17），返回 "save" 或跳过原因。

    - "excluded"：来源应用在忽略列表（§9.6）——不落库、不进 FTS
    - "sensitive_ignore"：敏感策略 ignore（§9.17）
    - "save"：继续保存（warn 置 sensitive 标记；save_temporarily 设 expires_at）

    副作用：按策略修改 item.sensitive / sensitive_type / expires_at。
    日志一律不含剪贴板原文（§9.23）。
    """
    if item.source_app and item.source_app in privacy["ignored_apps"]:
        logger.info("Clipboard item ignored source_app=%s"
                    " reason=application_exclusion", item.source_app)
        return "excluded"

    # url 跳过：微信等分享链接的 token=/key= 查询参数是常态（误判修复）；
    # detect() 内还有 http(s) 兜底
    if item.type in ("text", "code") and item.content:
        from services.sensitive_detector import detect as detect_sensitive

        result = detect_sensitive(item.content)
        if result is not None:
            item.sensitive = 1
            item.sensitive_type = result.sensitive_type
            policy = privacy.get("policy", "warn")
            if policy == "ignore":
                logger.info("Sensitive clipboard detected type=%s"
                            " action=ignore", result.sensitive_type)
                return "sensitive_ignore"
            if policy == "save_temporarily":
                from datetime import datetime, timedelta

                item.expires_at = (datetime.now() + timedelta(
                    minutes=int(privacy.get("temp_minutes", 5))
                )).strftime("%Y-%m-%d %H:%M:%S")
                logger.info("Sensitive clipboard detected type=%s"
                            " action=save_temporarily expires_at=%s",
                            result.sensitive_type, item.expires_at)
            else:
                logger.info("Sensitive clipboard detected type=%s"
                            " action=warn", result.sensitive_type)
    return "save"


def _on_permission_required() -> None:
    """辅助功能未授权：提示引导，不弹窗打断（V1.5 做引导对话框）。"""
    logger.warning("需要「辅助功能」授权 ⌘⇧V 才能生效：系统设置 → 隐私与安全性 → 辅助功能")
