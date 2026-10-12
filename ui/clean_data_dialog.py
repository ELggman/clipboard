"""清理数据弹窗：筛选历史并删除（不影响收藏夹快照）。

设置页只保留入口按钮，详细交互（时间筛选/勾选预览/部分删除）在此弹窗完成。

**筛选项改动即刷新**（用户要求：不要「查询」按钮）。带一个短防抖——见
`_REFRESH_DEBOUNCE_MS` 的说明。
"""
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from ui.animations import enable_smooth_wheel
from ui.dialogs import ConfirmDialog
from ui.fluent_combo import FluentComboBox

logger = logging.getLogger(__name__)

# 清理数据：时间筛选条件（days, 文案）
_CLEAN_OPTIONS = [(7, "7 天以前"), (30, "30 天以前"), (90, "90 天以前"), (0, "全部历史")]
# 类型筛选（"", 全部）
_TYPE_OPTIONS = [("", "全部类型"), ("text", "文本"), ("url", "URL"),
                 ("image", "图片"), ("file", "文件"), ("code", "代码")]

# 筛选项改动后延迟这么久才真查（防抖）。为什么需要：`list_older_than` 没有
# LIMIT，「全部历史」在大库上实测 ~44ms（5000 行，SQL + 构造 ClipboardItem），
# 加上重建整张预览表（含 processEvents）实测单次 ~170ms。用户拨筛选时常常连着
# 拨几个下拉（7 天→30 天→全部历史），不防抖就是连着卡几次。
# 150ms 是「察觉不到」和「能合并连拨」之间的位置——单次改动仍像立刻生效。
_REFRESH_DEBOUNCE_MS = 150


class CleanDataDialog(QDialog):
    def __init__(self, engine, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._items: list = []  # 当前筛选结果
        self.setWindowTitle("清理数据")
        self.setModal(True)
        self.setMinimumSize(520, 460)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        # 筛选行：时间 + 类型 + 会话。**没有「查询」按钮**——改动即刷新
        # （见 `_schedule_query`），省掉「选了条件还得再点一下」那步。
        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self._days = FluentComboBox()
        for value, label in _CLEAN_OPTIONS:
            self._days.addItem(label, value)
        filter_row.addWidget(self._days)
        self._types = FluentComboBox()
        for value, label in _TYPE_OPTIONS:
            self._types.addItem(label, value)
        filter_row.addWidget(self._types)
        self._sessions = FluentComboBox()
        from services import session_service

        self._sessions.addItem("全部会话", None)
        for s in session_service.list_sessions(engine):
            self._sessions.addItem(s["name"], s["id"])
        filter_row.addWidget(self._sessions)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        # 预览列表（可勾选，默认全选）
        self._list = QListWidget()
        self._list.setObjectName("historyList")
        enable_smooth_wheel(self._list)  # 清理结果多时列表内滚动缓动
        layout.addWidget(self._list, 1)

        # 操作按钮
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        del_selected = QPushButton("删除选中")
        del_selected.setObjectName("destructiveButton")
        del_selected.clicked.connect(self._delete_selected)
        buttons.addWidget(del_selected)
        del_all = QPushButton("删除全部匹配")
        del_all.setObjectName("destructiveButton")
        del_all.clicked.connect(self._delete_all)
        buttons.addWidget(del_all)
        layout.addLayout(buttons)

        note = QLabel("删除历史不影响收藏夹内容；收藏快照仅在收藏夹内管理。")
        note.setObjectName("placeholder")
        layout.addWidget(note)

        # 三个下拉改动 → 自动刷新预览（带防抖）。连接放在**填充之后**：
        # `addItem` 不 emit（见 FluentComboBox.addItem），所以填充期不会误触，
        # 但顺序上先建后连更不容易在将来踩坑。
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_REFRESH_DEBOUNCE_MS)
        self._refresh_timer.timeout.connect(self._query)
        for combo in (self._days, self._types, self._sessions):
            combo.currentIndexChanged.connect(self._schedule_query)

        self._query()   # 首屏立即出结果（不走防抖）

    # ---- 查询与删除 ----

    def _schedule_query(self, *_args) -> None:
        """筛选项变了 → 稍后自动刷新。连拨几个下拉只查最后一次。"""
        self._refresh_timer.start()

    def _query(self) -> None:
        """按时间 + 类型条件查询匹配条目（可勾选，默认全选）。"""
        if self._engine is None:
            return
        from services import history_service

        days = self._days.currentData()
        item_type = self._types.currentData()
        session_id = self._sessions.currentData()
        self._items = history_service.list_older_than(
            self._engine, days, item_type, session_id)
        self._list.clear()
        for item in self._items:
            row = QListWidgetItem(
                f"{item.created_at} · {item.type}  {item.display_text(max_len=60)}")
            row.setData(Qt.ItemDataRole.UserRole, item.id)
            row.setFlags(row.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            row.setCheckState(Qt.CheckState.Checked)  # 默认全选
            self._list.addItem(row)
        logger.info("清理数据查询: %d 条匹配", len(self._items))

    def _delete_selected(self) -> None:
        """删除勾选条目（红色确认）。"""
        ids = [self._items[i].id
               for i in range(self._list.count())
               if self._list.item(i).checkState() == Qt.CheckState.Checked]
        self._delete(ids)

    def _delete_all(self) -> None:
        """删除全部匹配条目（红色确认）。"""
        self._delete([item.id for item in self._items])

    def _delete(self, ids: list[int]) -> None:
        if self._engine is None or not ids:
            return
        from services import history_service

        dialog = ConfirmDialog(
            "清理数据",
            f"将删除 {len(ids)} 条历史记录（图片文件同步清理），"
            "不影响收藏夹内容。确定继续？",
            confirm_text="删除")
        if dialog.exec() != ConfirmDialog.DialogCode.Accepted:
            return
        files = history_service.delete_items(self._engine, ids)
        from services.image_service import ImageService

        svc = ImageService(Path(__file__).resolve().parent.parent / "images")
        for path in files:
            # 仍被引用（其他会话行/收藏快照）的图片保留
            if not history_service.is_path_still_referenced(self._engine, path):
                svc.delete(path)
        logger.info("清理数据完成: %d 条（图片 %d 个）", len(ids), len(files))
        self._query()  # 刷新预览
