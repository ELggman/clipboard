"""应用入口与生命周期管理。

启动 <1s 目标的关键：这里只 import Qt 核心；UI 与业务模块在
app.bootstrap 里延迟加载（见 DEVELOPMENT.md §6.3）。
"""
import logging
import logging.handlers
import sys

from PySide6.QtNetwork import QLocalServer, QLocalSocket  # 单实例：QLocalServer 在 QtNetwork
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app import APP_ID, ROOT_DIR, __version__

LOG_DIR = ROOT_DIR / "logs"

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    """windowed 应用 stderr 不可见，日志必须落盘（按天滚动，留 7 天）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.TimedRotatingFileHandler(
        LOG_DIR / "clipboard.log", when="midnight", backupCount=7, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def _ensure_single_instance() -> bool:
    """返回 False 表示已有实例在运行（本进程应退出）。

    单实例机制：QLocalServer 独占 APP_ID 端口；新实例探测到占用即退出，
    后续可扩展为向旧实例发送「唤起 Quick Paste」信号。
    """
    probe = QLocalSocket()
    probe.connectToServer(APP_ID)
    if probe.waitForConnected(300):
        probe.dispose()
        logger.info("已有实例在运行，本进程退出")
        return False
    server = QLocalServer()
    server.removeServer(APP_ID)  # 清理上次异常退出的残留
    return server.listen(APP_ID)


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Clipboard Workspace")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)  # 常驻后台（菜单栏应用）

    # 应用图标（窗口标题栏 / dev 模式 Dock；打包后 .app 图标由 spec 的 icon.icns 决定）。
    # 用 resources/icon.png（由 packaging/gen_icons.py 从 icon.svg 生成），
    # 缺失时静默跳过（仅图标，不影响功能）。
    _icon = ROOT_DIR / "resources" / "icon.png"
    if _icon.exists():
        app.setWindowIcon(QIcon(str(_icon)))

    if not _ensure_single_instance():
        return 0

    logger.info("Clipboard Workspace %s 启动（Python %s）", __version__, sys.version.split()[0])

    # 延迟导入：业务/UI 装配（启动时间优化点，见 DEVELOPMENT.md §6.3）
    from app.bootstrap import start_workspace

    start_workspace(app)
    return app.exec()
