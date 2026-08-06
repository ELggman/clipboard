"""Snippet 片段页：用户维护的代码片段（与 History 独立，DEVELOPMENT.md §4.5）。

左侧列表（选择即载入表单），右侧编辑区（名称/描述/内容 + 保存/复制/删除）。
复制时渲染 {{date}} {{time}} {{uuid}} 变量（snippet_service.render_snippet）。
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from services import snippet_service

logger = logging.getLogger(__name__)


class SnippetsView(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._engine = None
        self._snippets: list[dict] = []
        self._build_ui()

    def set_context(self, engine) -> None:
        """注入数据库引擎（bootstrap 装配），打开页面时自动刷新。"""
        self._engine = engine
        self.reload()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._engine is not None:
            self.reload()

    # ---- 构建 ----

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 左：列表 + 新建
        left = QVBoxLayout()
        left.setSpacing(6)
        self._list = QListWidget()
        self._list.setObjectName("sideList")
        self._list.currentRowChanged.connect(self._on_select)
        left.addWidget(self._list, 1)
        new_btn = QPushButton("新建片段")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_snippet)
        left.addWidget(new_btn)
        layout.addLayout(left, 2)

        # 右：表单
        form = QVBoxLayout()
        form.setSpacing(6)
        self._name = QLineEdit()
        self._name.setPlaceholderText("名称（如 email）")
        form.addWidget(self._name)
        self._desc = QLineEdit()
        self._desc.setPlaceholderText("描述（可选）")
        form.addWidget(self._desc)
        vars_hint = QLabel("可用变量：" + "  ".join(snippet_service.AVAILABLE_VARS)
                           + "  复制时自动替换")
        vars_hint.setObjectName("placeholder")
        form.addWidget(vars_hint)
        self._content = QPlainTextEdit()
        self._content.setPlaceholderText("片段内容…")
        form.addWidget(self._content, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._copy_btn = QPushButton("复制")
        self._copy_btn.setObjectName("primaryButton")
        self._copy_btn.clicked.connect(self._copy)
        buttons.addWidget(self._copy_btn)
        self._save_btn = QPushButton("保存")
        self._save_btn.clicked.connect(self._save)
        buttons.addWidget(self._save_btn)
        self._delete_btn = QPushButton("删除")
        self._delete_btn.clicked.connect(self._delete)
        buttons.addWidget(self._delete_btn)
        form.addLayout(buttons)
        layout.addLayout(form, 3)

    # ---- 数据 ----

    def reload(self) -> None:
        """从数据库重载列表（保留当前选择）。"""
        if self._engine is None:
            return
        current_id = self._current_id()
        self._snippets = snippet_service.list_snippets(self._engine)
        self._list.blockSignals(True)
        self._list.clear()
        for s in self._snippets:
            item = QListWidgetItem(f"{s['name']}  {s['description']}".rstrip())
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)
        if self._snippets:
            idx = next((i for i, s in enumerate(self._snippets)
                        if s["id"] == current_id), 0)
            self._list.setCurrentRow(idx)
        else:
            self._clear_form()

    def _current_id(self) -> int:
        row = self._list.currentRow()
        if 0 <= row < len(self._snippets):
            return self._snippets[row]["id"]
        return 0

    def _on_select(self, row: int) -> None:
        if 0 <= row < len(self._snippets):
            s = self._snippets[row]
            self._name.setText(s["name"])
            self._desc.setText(s["description"])
            self._content.setPlainText(s["content"])

    def _clear_form(self) -> None:
        self._name.clear()
        self._desc.clear()
        self._content.clear()

    # ---- 操作 ----

    def _new_snippet(self) -> None:
        self._list.setCurrentRow(-1)
        self._clear_form()
        self._name.setFocus()

    def _save(self) -> None:
        if self._engine is None:
            return
        name = self._name.text().strip()
        content = self._content.toPlainText()
        if not name or not content:
            logger.warning("片段保存失败：名称与内容必填")
            return
        s_id = self._current_id()
        if s_id:
            snippet_service.update_snippet(self._engine, s_id, name, content,
                                           self._desc.text().strip())
        else:
            snippet_service.create_snippet(self._engine, name, content,
                                           self._desc.text().strip())
        logger.info("片段已保存: %s", name)
        self.reload()

    def _copy(self) -> None:
        from services.action_service import set_clipboard_text

        content = self._content.toPlainText()
        if not content:
            return
        rendered = snippet_service.render_snippet(content)
        set_clipboard_text(rendered)
        logger.info("片段已复制（含变量渲染）")

    def _delete(self) -> None:
        s_id = self._current_id()
        if s_id and self._engine is not None:
            snippet_service.delete_snippet(self._engine, s_id)
            logger.info("片段已删除: id=%s", s_id)
            self.reload()
