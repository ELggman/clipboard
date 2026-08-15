"""启动装配：配置 → 数据库 → 服务 → UI（全部延迟导入，保证启动 <1s）。

V1 核心闭环已打通：ClipboardWatcher 解析 → history_service 去重落库
→ MainWindow.refresh_history 刷新列表与状态栏。
"""
import logging
import os
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

    # 会话（v4）：默认会话 + 恢复上次激活的会话（第二天继续任务的场景）
    from services import session_service

    session_service.ensure_default(engine)
    active_id = int(config["session"].get("active_id", 1))
    session_ids = {s["id"] for s in session_service.list_sessions(engine)}
    if active_id not in session_ids:
        active_id = 1  # 配置指向已删除会话 → 回退默认

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

    # 会话：激活状态注入历史页 + 切换持久化（重启恢复）
    def set_active_session(sid: int) -> None:
        config["session"]["active_id"] = sid
        from app.config import save_user_config

        save_user_config({"session": {"active_id": sid}})
        window.set_active_session(sid)
        logger.info("已切换激活会话: id=%s", sid)

    window.set_active_session(active_id)
    window.set_session_context(engine, session_service,
                               on_active_changed=set_active_session)
    window.set_delete_policy(config["session"].get("delete_policy", "move"))
    window.reload_sessions(active_id)  # 填充会话下拉 + 加载激活会话视图
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
    # （仅恢复**激活会话**的内容；其余会话通过下拉切换查看）
    max_items = int(config["history"]["max_items"])
    restore_limit = 1000 if max_items < 0 else max_items
    window.load_history(history_service.list_recent(
        engine, limit=restore_limit, session_id=active_id),
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
            elif key == "dedupe_scope":
                # 去重范围即时生效（save_item 读内存 config）
                config["history"]["dedupe_scope"] = \
                    overrides["history"]["dedupe_scope"]
            elif key == "session_delete_policy":
                # 删除会话策略即时生效（历史页读内存 config）
                config["session"]["delete_policy"] = \
                    overrides["session"]["delete_policy"]
                window.set_delete_policy(overrides["session"]["delete_policy"])
            # save_images / auto_delete 下次插入或清扫时生效
        return _apply

    window.set_settings_context(
        config,
        {k: apply_setting(k) for k in ("theme", "font", "show_filename",
                                       "autostart", "max_items",
                                       "privacy_policy", "privacy_temp",
                                       "privacy_ignored", "max_file_size",
                                       "dedupe_scope",
                                       "session_delete_policy")},
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
            # 仍被引用（其他会话行/收藏快照）的图片保留
            if not history_service.is_path_still_referenced(engine, path):
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
        # 保存到当前激活会话（任务型内容分组，v4）
        item.session_id = int(config["session"].get("active_id", 1))
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
            engine, item, max_items=int(config["history"]["max_items"]),
            dedupe_scope=config["history"].get("dedupe_scope", "all"),
        )
        window.refresh_history(item, is_new)
        if is_new:
            window.refresh_session_counts()  # 会话下拉计数实时更新
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
    from services.hotkey_manager import KEY_P, KEY_S, MASK_HOTKEY

    hotkey.add_binding(KEY_P, MASK_HOTKEY, hotkey.privacy_toggle)
    hotkey.privacy_toggle.connect(privacy_state.toggle)

    # 模板模块（v6）：Tab Trigger + 全局 Picker（文档 §7/§16）
    from services.template.insertion import delete_backspaces, insert_text
    from services.template.matcher import ShortcutMatcher
    from services.template_service import TemplateService
    from ui.input_variable_dialog import InputVariableDialog
    from ui.template_picker_popup import TemplatePickerPopup

    template_service = TemplateService(engine)

    import time

    from AppKit import (NSApplication, NSApplicationActivateIgnoringOtherApps,
                        NSWorkspace)
    from PySide6.QtWidgets import QDialog

    # 触发上下文（问题1「插入无反应」+ 问题3「selection 读到空」的共同根因）：
    # 全局 Picker（⌘⇧S）弹出时本应用会夺走前台——弹层显示中再读
    # frontmostApplication() 拿到的是自己，导致粘贴打进本应用（插入无反应）
    # 且 {{selection}} 读到本应用自己的空选中。故在**热键触发瞬间**（本应用
    # 尚未激活）捕获目标应用 + 其选中文本，随选中回调传给渲染。
    _trigger_ctx = {"app": None, "selection": None}

    def _capture_trigger_context() -> None:
        """热键触发瞬间捕获前台目标应用 + 其选中文本（弹层夺焦点之前）。"""
        from services.template.ax_text import read_focused_selection

        _trigger_ctx["app"] = NSWorkspace.sharedWorkspace().frontmostApplication()
        try:
            _trigger_ctx["selection"] = read_focused_selection()
        except Exception:
            _trigger_ctx["selection"] = None

    def _activate_target(target) -> None:
        """把焦点还给目标应用并轮询确认（粘贴前必须到位，否则 ⌘V 打偏）。

        ⚠️ 不能用固定 sleep：应用激活耗时不定，过早发 ⌘V 会打进本应用
        自己（「点击插入无反应」v7 修复不彻底）。轮询前台 PID 到位再粘贴。

        ⚠️ 轮询里必须 processEvents()：本应用从前台让位要处理 deactivate
        事件，time.sleep 阻塞主线程会让让位卡住——目标应用永远上不了前台，
        ⌘V 恒打回本应用（问题1「点击插入无反应」根因）。激活到位后其
        输入框焦点恢复也是异步的，再等一拍才粘贴。
        """
        if target is None:
            return
        try:
            # NSRunningApplication 没有 isRunning()，用 isTerminated() 判断
            # 是否已退出（isRunning 会抛 AttributeError，此前被 Qt 吞掉 →
            # 目标应用从未被激活 → ⌘V 恒打回本应用 = 问题1 根因）。
            if target.isTerminated():
                return
            from PySide6.QtWidgets import QApplication

            target.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            target_pid = target.processIdentifier()
            deadline = time.monotonic() + 1.5
            reached = False
            while time.monotonic() < deadline:
                QApplication.processEvents()  # 泵事件：让 deactivate 完成
                front = NSWorkspace.sharedWorkspace().frontmostApplication()
                if front is not None and front.processIdentifier() == target_pid:
                    reached = True
                    break
                time.sleep(0.02)
            logger.info("目标应用前台恢复 %s (pid=%s)",
                        "成功" if reached else "超时未到位", target_pid)
            # 目标应用已前台，但其文本框焦点恢复是异步的——再等一拍
            # （⌘V 打到「已前台但焦点未就位」窗口也会插入无反应）。
            time.sleep(0.15)
        except Exception:
            logger.exception("激活目标应用失败（继续尝试粘贴）")

    def _render_and_insert_impl(template: dict, delete_count: int = 0,
                                cancel_ime: bool = False) -> None:
        """模板渲染 → （输入变量对话框）→ 模拟粘贴插入。

        delete_count > 0：先删除用户输入的 shortcut 文本
        （§5.1：shrug<Tab> → ¯\\_(ツ)_/¯，原始输入不残留）——
        必须在弹输入框**之前**删除（弹框夺焦后退格会打错位置）。
        cancel_ime=True（中文输入法 Tab 触发）：shortcut 还在输入法组合里
        未上屏 → 发 Escape 取消组合（字母随之消失），不能 ⌥⌫（会破坏
        组合，实测 sig 被改写为 siv）。
        """
        if delete_count > 0:
            if cancel_ime:
                from services.template.insertion import cancel_composition

                cancel_composition()
            else:
                delete_backspaces(delete_count, template["shortcut"])
        content = template["content"]
        # 触发上下文：picker 流程在热键时捕获（目标应用 + 选中文本）；tab
        # 流程未捕获（None）→ 前台即目标应用。读后即清，防下次 tab 触发
        # 误用上次 picker 的陈旧值。
        trigger_app = _trigger_ctx["app"]
        selection = _trigger_ctx["selection"]
        _trigger_ctx["app"] = None
        _trigger_ctx["selection"] = None

        text, _cursor, inputs = template_service.render_template(
            content, selection_text=selection)
        if inputs:
            # 全局触发：应用可能未激活，先激活再弹输入框（§40-41）。
            # ⚠️ 弹框会把前台让给本应用（对话框要可见），关框后必须把
            # 焦点还给目标应用再粘贴——否则 ⌘V 打进本应用自己。目标应用
            # 优先用触发时捕获的（picker 流程）；tab 流程前台就是目标。
            target = (trigger_app
                      or NSWorkspace.sharedWorkspace().frontmostApplication())
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
            dlg = InputVariableDialog(inputs, content=content)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                logger.info("模板输入取消: shortcut=%s", template["shortcut"])
                return
            # 先把值取出来再 _activate_target：其内部 processEvents() 可能
            # 处理对话框的延迟销毁，之后 dlg 可能已失效（C++ 对象已删）。
            values = dlg.values()
            _activate_target(target)
            text, _, _ = template_service.render_template(
                content, input_values=values, selection_text=selection)
        elif trigger_app is not None:
            # 无 input 变量的 picker 流程：弹层关闭后前台可能仍是本应用 →
            # 粘贴前先把焦点还给目标应用（tab 流程无需——前台本就是目标）。
            _activate_target(trigger_app)
        template_service.record_usage(template["id"])
        # §95 日志安全：只记 id/shortcut，不记展开内容
        logger.info("模板触发: id=%s shortcut=%s",
                    template["id"], template["shortcut"])
        if not insert_text(text, watcher):
            logger.error("模板插入失败: shortcut=%s", template["shortcut"])

    def render_and_insert(template: dict, delete_count: int = 0,
                          cancel_ime: bool = False) -> None:
        """渲染插入的统一入口（on_trigger / picker.selected / 测试钩子）。

        包一层 try/except：渲染/激活/粘贴任一步抛异常，此前会被 Qt 信号
        分发吞掉（windowed 应用 stderr 不可见）——静默失败、日志里只看到
        「删除 shortcut」却看不到「模板触发: id=」。落盘堆栈才好定位。
        """
        try:
            _render_and_insert_impl(template, delete_count, cancel_ime)
        except Exception:
            logger.exception("模板渲染插入异常: shortcut=%s",
                             template.get("shortcut"))

    from services.template.ax_text import is_ime_composing
    from services.template.ax_text import ensure_ax_enabled
    from services.template.ax_text import _frontmost_pid
    from services.template.ime import is_chinese_ime

    # 中英触发彻底分离（用户决策）：英文走缓冲引擎 ShortcutMatcher
    # （feed，不依赖 AX）；中文走 AX 引擎 AxShortcutMatcher（match_text，
    # 读焦点文本）。改动互不牵连。
    matcher = ShortcutMatcher(template_service, on_trigger=render_and_insert,
                              composing_check=is_ime_composing,
                              chinese_ime_check=is_chinese_ime)

    def _text_trigger(template, delete_count, cancel_ime) -> None:
        """AX 焦点文本末尾匹配命中（中文，或英文 tab 兜底）：先清空英文
        缓冲，再走统一渲染插入。

        清缓冲：文本匹配前的按键还留在缓冲里（缓冲引擎不感知 AX 文本匹
        配），不清会让残留字母在后续 Tab/自动触发时误匹配英文 shortcut。
        """
        matcher.reset()
        render_and_insert(template, delete_count, cancel_ime)

    from services.template.ax_matcher import AxShortcutMatcher
    from services.template.ax_matcher import is_delete_reveal

    chinese_matcher = AxShortcutMatcher(template_service,
                                        on_trigger=_text_trigger)

    def _has_english_tab_shortcut() -> bool:
        """是否存在已启用的英文 tab 模式 shortcut（Tab 兜底需要）。

        Tab 兜底（_on_raw_key）：中文输入法下英文 shortcut 需提交键上屏，
        提交键清掉英文缓冲，随后 Tab 只能从已上屏文本末尾匹配——需要 AX。
        """
        return any(item["shortcut"].isascii() and item["trigger_mode"] == "tab"
                   for item in template_service.list_shortcuts())

    def _ensure_ax_if_needed() -> bool:
        """需要 AX 文本匹配时才为前台应用强制开启 AX 树（Electron 默认无
        AX 树，read_focused_text 恒 None → 文本匹配全死，实测）。

        场景：
        1. 有中文 shortcut（任意模式）：中文 AX 匹配（轮询/Tab）依赖读文本
        2. 中文输入法激活且有英文 tab shortcut：Tab 兜底——中文输入法下
           英文 shortcut 必须先按提交键（回车/空格）上屏，提交键清掉英文
           缓冲（tab 模式不自动触发），随后 Tab 只能从已上屏文本末尾匹配
        纯英文输入法下英文走键盘缓冲即可，不需要 AX——不强制开，避免给
        用户的编辑器（Chromium 应用）带来 accessibility 树的额外开销。
        ensure_ax_enabled 内部按前台 pid 缓存，同 pid 只 SET 一次。
        返回是否需要 AX 文本匹配。
        """
        if template_service.has_chinese_shortcut():
            ensure_ax_enabled()
            return True
        if is_chinese_ime() and _has_english_tab_shortcut():
            ensure_ax_enabled()
            return True
        return False

    # 自动触发延迟确认（防 prefix 误触：signature 的 sig 不触发）：
    # matcher 命中 automatic shortcut 后挂起 pending（缓冲保留），
    # 200ms 内缓冲未变 → 确认触发；继续输入更长的词 → 缓冲变化取消。
    # 词边界键（空格/标点）在 feed 内同步确认（"sig"+空格 立即触发）。
    from PySide6.QtCore import QTimer

    _auto_timer = QTimer(app)
    _auto_timer.setInterval(200)
    _auto_timer.setSingleShot(True)
    _auto_timer.timeout.connect(matcher.confirm_pending)

    def _on_raw_key(vk: int, ch: str) -> None:
        # 前台是自己的进程：模板触发只服务其他应用，app 自己 UI 里的按键
        # （搜索框/编辑面板输入）不喂缓冲、不匹配——否则在搜索框打英文
        # shortcut 会误触发（实测搜「id」触发 automatic 模板，搜索词被删）。
        # reset 同时清掉可能残留的英文缓冲/挂起触发（切回 app 后不应在
        # 自己的 UI 里展开）。
        if _frontmost_pid() == os.getpid():
            matcher.reset()
            return
        if ch == "\t":
            # Tab 触发：英文走缓冲（matcher.feed），中文走 AX 焦点文本
            # 末尾匹配（chinese_matcher——输入法上屏的汉字无按键事件，
            # CGEventTap 只能看到拼音，必须在文本层匹配）。
            # 英文缓冲未命中时（**中文输入法下提交键会清掉缓冲**，实测：
            # 输英文 shortcut 需回车/空格先上屏，提交键走 feed 的 else 分支
            # 清空缓冲，随后 Tab 缓冲为空）→ AX 兜底：从**已上屏的焦点
            # 文本末尾**匹配英文 tab shortcut（include_ascii=True）。
            from services.template.ax_text import read_focused_text

            if matcher.feed(ch):
                return
            try:
                # AX 兜底依赖读焦点文本：Electron 应用默认无 AX 树，需先
                # 强制开启（有中文 shortcut，或中文输入法下有英文 tab
                # shortcut 时才需要；见 _ensure_ax_if_needed）
                if not _ensure_ax_if_needed():
                    return
                text = read_focused_text()
                if chinese_matcher.match_text(text):
                    logger.info("Tab 触发：AX 焦点文本末尾匹配中文 shortcut")
                elif chinese_matcher.match_text(text, include_ascii=True):
                    logger.info("Tab 触发：AX 焦点文本末尾匹配英文 tab"
                                " shortcut（提交键清缓冲后的兜底）")
            except Exception:
                pass
        else:
            matcher.feed(ch)
            if matcher.has_pending():
                _auto_timer.start()  # 重启 = 重新计时 200ms

    hotkey.raw_key_down.connect(_on_raw_key)
    hotkey.enable_raw_keys(True)



    # 焦点文本轮询（中文 shortcut 触发）：输入法上屏的汉字不产生按键
    # 事件，且中文 IME 下 Tab 可能被输入法吞掉——定时读焦点文本、
    # 末尾匹配 automatic 模式中文 shortcut，文本变化才匹配。
    #
    # **只匹配中文（AxShortcutMatcher 内 sc.isascii() 直接跳过）**：英文
    # shortcut 一律由缓冲引擎覆盖（英文输入法：延迟确认；中文输入法：
    # 提交键）——轮询里的英文 shortcut 有两个问题：1) 组合中 AX 值可能
    # 含未上屏拼音（部分应用读不到 marked range），会提前触发（用户实测：
    # uuid 未按回车就触发）；2) prefix 误触风险（signature 的 sig）。
    # 中文 shortcut 组合中显示的是拼音，天然不会误匹配。
    #
    # 组合守卫：输入法组合中跳过匹配，**且不更新缓存**——组合上屏后
    # 文本变化才能触发（否则组合文本被缓存，上屏后文本未变，永不触发）。
    # ⚠️ VS Code 等读不到 marked range，组合守卫失效——轮询会读到拼音
    # 中间态（'wen h'）→ 上屏「问候」是替换。判定只能挡**尾部删除**
    # （新文本是旧文本严格前缀），替换/追加都放行给末尾匹配决定。
    #
    # **删除判定（防删除误触发）**：轮询只看文本状态变化，删除也能把
    # 文本变成以 shortcut 结尾（实测「问候你」删「你」→「问候」→ 误触
    # 发）。只挡 is_delete_reveal（尾部纯删除）；文本被清空/全空白时
    # 重置缓存为空串（否则清行后重输 shortcut 会被判非输入而不触发）。
    #
    # **上下文守卫（防既有文本误触发）**：自动触发只在用户**输入**时
    # 有意义——切到已有 shortcut 文本的上下文不该触发（实测：切到
    # Typora 光标落在「问候」后误触发；编辑面板名称「问候」被误删；
    # 搜索框搜英文 shortcut「id」触发 automatic 模板、搜索词被删）。
    # 触发只服务其他应用，且**上下文切换即重置触发状态**（中英两套）：
    # 1. 前台是自己的进程 → 永不触发（_on_raw_key 也同规则，英文缓冲
    #    不喂自己的键）——搜索框/编辑面板等 UI 一律不展开模板
    # 2. 前台应用 pid 变化 → 中文文本缓存置 None + 英文缓冲 reset：
    #    新上下文的既有文本不是用户输入，切换后继续输入才可能触发
    from PySide6.QtCore import QTimer

    from services.template.ax_text import read_focused_text

    _focused_last = {"text": None, "pid": None}

    def _poll_focused_text() -> None:
        try:
            # 中文 shortcut 依赖 AX 读文本：确保前台应用 AX 树已开启
            # （Electron 应用默认无）。无中文 shortcut → 轮询无意义
            # （AxShortcutMatcher 只匹配中文），直接跳过。
            if not _ensure_ax_if_needed():
                return
            if is_ime_composing():
                return  # 组合未上屏：跳过且不更新缓存
            # 前台是自己的进程：模板触发只服务其他应用，自己 UI（编辑面板
            # 名称/搜索框等）永不触发——实测编辑面板名称「问候」被误触发删掉；
            # 同时清掉英文缓冲/挂起触发（切回 app 后不应在 UI 里展开）。
            pid = _frontmost_pid()
            if pid is None:
                return
            if pid == os.getpid():
                matcher.reset()
                return
            # 前台应用切换：重置触发基线——中文文本缓存置 None（新上下文的
            # 既有文本不是用户输入，实测切到 Typora 光标落在「问候」后误触
            # 发），英文缓冲同样清空（防跨应用残留缓冲/挂起触发在错误应用
            # 触发）。切换后继续输入的文本变化才可能触发（下一轮 prev=None
            # 建立中文基线）。
            if pid != _focused_last["pid"]:
                _focused_last["pid"] = pid
                _focused_last["text"] = None
                matcher.reset()
                return
            text = read_focused_text()
            if text is None or text == _focused_last["text"]:
                return  # 文本未变化（防重复触发）
            if not text.strip():
                _focused_last["text"] = ""  # 清空/全空白：重置缓存
                return
            prev, _focused_last["text"] = _focused_last["text"], text
            if prev is None:
                return  # 首次观测（切换后的基线轮）：不触发既有文本
            if is_delete_reveal(prev, text):
                return  # 删除尾部露出 shortcut：不是用户输入，不触发
            if chinese_matcher.match_text(text, mode="automatic"):
                logger.info("焦点文本轮询触发：末尾匹配中文 shortcut")
        except Exception:
            pass

    _focus_timer = QTimer(app)
    _focus_timer.setInterval(400)
    _focus_timer.timeout.connect(_poll_focused_text)
    _focus_timer.start()

    # 全局 Picker（⌘⇧S）：搜索 → Enter 走同一渲染+插入流程
    picker = TemplatePickerPopup()
    picker.set_service(template_service)
    picker.selected.connect(render_and_insert)
    # Esc/点外部取消而未选中时清掉捕获的上下文，防下次 Tab 触发误用陈旧值
    picker.hidden.connect(
        lambda: _trigger_ctx.update({"app": None, "selection": None}))

    def on_picker() -> None:
        logger.info("模板 Picker：打开")
        # 弹层会夺走前台：先捕获目标应用 + 选中文本（{{selection}} 依赖），
        # 否则 render_and_insert 读到的是本应用自己。
        _capture_trigger_context()
        picker.show_near_cursor()

    from PySide6.QtCore import QObject, Signal as _Signal

    class _PickerSignals(QObject):
        opened = _Signal()

    _picker_sig = _PickerSignals()
    _picker_sig.opened.connect(on_picker)
    hotkey.add_binding(KEY_S, MASK_HOTKEY, _picker_sig.opened)

    hotkey.permission_required.connect(_on_permission_required)
    if config["hotkey"]["enabled"]:
        hotkey.start()

    # 测试/调试钩子（不对外暴露 API）
    app._quick_paste_popup = popup
    app._on_quick_paste = on_quick_paste
    app._template_picker = picker
    app._template_matcher = matcher
    app._template_service = template_service
    app._render_and_insert = render_and_insert

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
