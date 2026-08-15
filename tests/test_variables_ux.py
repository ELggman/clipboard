"""变量系统 UX 测试（自动补全候选过滤 + 编辑器 + 常用/变量库弹层）。

filter_candidates / 编辑器纯逻辑可测；弹层定位（show_at）依赖屏幕几何，
不在此断言。配置持久化测试把 CONFIG_DIR 指到临时目录，不触碰真实
settings.yaml。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

pytest_app = QApplication.instance() or QApplication([])


def _press(btn, x: int) -> None:
    """在按钮局部 (x, 10) 模拟左键按下（★/行区路由测试用）。"""
    local = QPointF(x, 10)
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, local,
                     btn.mapToGlobal(local.toPoint()),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    btn.mousePressEvent(ev)


def _isolate_config(tmp_path, monkeypatch):
    """把 config 目录指到临时目录（隔离持久化测试，不触碰真实配置）。"""
    import app.config

    (tmp_path / "defaults.yaml").write_text(
        "template:\n  favorite_variables: null\n  extra_variables: []\n",
        encoding="utf-8")
    monkeypatch.setattr(app.config, "CONFIG_DIR", tmp_path)


def test_filter_candidates_prefix_and_order():
    """前缀过滤 + 排序：常用在前，其余按来源类别。"""
    from services.template.registry import filter_candidates

    # 前缀 'd' → 只有 date/datetime 等以 {{d 开头的
    got = filter_candidates("d")
    assert "{{date}}" in got and "{{datetime}}" in got
    assert "{{time}}" not in got  # {{time 不以 {{d 开头

    # 前缀 'in' → input 变量
    got = filter_candidates("in")
    assert got == ["{{input:name}}"]  # 唯一以 {{in 开头的预设

    # 空前缀 → 全部；预设按类别序（系统最先）
    got = filter_candidates("")
    assert got[0] == "{{date}}"
    assert got[-1] == "{{cursor}}"  # 上下文类别在系统/用户输入之后


def test_filter_candidates_favorites_first():
    """常用变量在前（按 favorites 顺序）；自定义变量并入候选。"""
    from services.template.registry import filter_candidates

    favs = ["{{cursor}}", "{{date}}"]
    got = filter_candidates("", custom=["{{location}}"], favorites=favs)
    assert got[:2] == ["{{cursor}}", "{{date}}"]  # 常用在前、按 favorites 顺序
    assert "{{location}}" in got  # 自定义并入（类别末尾附近）
    assert got.index("{{location}}") > got.index("{{cursor}}")

    # stale favorite（已删除变量）自动忽略
    got = filter_candidates("", favorites=["{{ghost}}", "{{date}}"])
    assert "{{ghost}}" not in got
    assert got[0] == "{{date}}"


def test_filter_candidates_custom_prefix():
    """自定义变量按前缀过滤（中文变量名也支持）。"""
    from services.template.registry import filter_candidates

    got = filter_candidates("loc", custom=["{{location}}"])
    assert "{{location}}" in got
    got = filter_candidates("abc", custom=["{{location}}"])
    assert "{{location}}" not in got


def _editor_with(text: str, cursor_at_end: bool = True):
    from ui.variable_autocomplete import VariableAutocompleteEditor

    ed = VariableAutocompleteEditor()
    # 先 show + focus 再设文本：触发检查要求 isVisible+hasFocus（真实输入时
    # 文本变化发生在可见聚焦之后；先设文本则 _maybe_update 会因不可见而隐藏）
    ed.show()
    ed.setFocus()
    pytest_app.processEvents()
    ed.setPlainText(text)
    if cursor_at_end:
        cur = ed.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        ed.setTextCursor(cur)
    pytest_app.processEvents()
    return ed


def test_editor_current_prefix():
    """光标前 `{{` 前缀检测：`{{d` → 'd'；无 `{{` → None。"""
    from ui.variable_autocomplete import VariableAutocompleteEditor

    ed = VariableAutocompleteEditor()
    try:
        ed.setPlainText("你好 {{d")
        cur = ed.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        ed.setTextCursor(cur)
        assert ed._current_prefix() == "d"
        ed.setPlainText("{{}}")
        assert ed._current_prefix() is None
    finally:
        ed.close()


def test_editor_accept_replaces_trigger():
    """接受候选：把光标前 `{{` 替换为完整变量文本。"""
    ed = _editor_with("你好 {{")
    try:
        ed._accept("{{date}}")
        assert ed.toPlainText() == "你好 {{date}}"
    finally:
        ed.close()


def test_editor_accept_input_suffix():
    """input 变量接受走后缀规则：已有 {{input:name}} → 插 name2。"""
    ed = _editor_with("{{input:name}} 你好 {{")
    try:
        ed._accept("{{input:name}}")
        assert ed.toPlainText() == "{{input:name}} 你好 {{input:name2}}"
    finally:
        ed.close()


def test_editor_keyboard_navigation():
    """弹层可见时：↓ 移动选择、Enter 接受、Esc 关闭。"""
    ed = _editor_with("{{")
    try:
        # textChanged → _maybe_update 已触发弹层（isVisible+hasFocus）
        assert ed._popup.isVisible()
        # ↓ 选中下一项（初始在 0）→ Enter 接受当前
        QTest.keyClick(ed, Qt.Key_Down)
        QTest.keyClick(ed, Qt.Key_Return)
        text = ed.toPlainText()
        assert text.startswith("{{") and text.endswith("}}")
        assert not ed._popup.isVisible()  # 接受后关闭
        # Esc：输入 {{ 再按 Esc → 弹层关闭、内容不变
        ed.setPlainText("{{")
        cur = ed.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        ed.setTextCursor(cur)
        assert ed._popup.isVisible()
        QTest.keyClick(ed, Qt.Key_Escape)
        assert not ed._popup.isVisible()
        assert ed.toPlainText() == "{{"
    finally:
        ed.close()


def test_editor_no_popup_without_trigger():
    """无 `{{` 前缀（光标前普通文本）不弹候选。"""
    ed = _editor_with("hello ")
    try:
        assert not ed._popup.isVisible()
    finally:
        ed.close()


# ---- Phase 7：常用变量持久化 + 变量库弹层 ----

def test_favorites_round_trip(tmp_path, monkeypatch):
    """常用变量持久化 round-trip：null → 全部预设；保存 → 重读一致。"""
    _isolate_config(tmp_path, monkeypatch)
    from services.template.registry import PRESET_VARIABLES
    from ui.template_components import (load_favorite_variables,
                                        save_favorite_variables)

    favs = load_favorite_variables()
    assert "{{date}}" in favs and "{{selection}}" in favs  # null → 全部预设
    save_favorite_variables(["{{cursor}}", "{{date}}"])
    assert load_favorite_variables() == ["{{cursor}}", "{{date}}"]
    # 显式空 → 回退全部预设（胶囊区永不空置，靠「变量库」★ 管理）
    save_favorite_variables([])
    assert load_favorite_variables() == [m.insert for m in PRESET_VARIABLES]


def test_extra_variables_round_trip(tmp_path, monkeypatch):
    """自定义变量持久化 round-trip。"""
    _isolate_config(tmp_path, monkeypatch)
    from ui.template_components import (load_extra_variables,
                                        save_extra_variables)

    assert load_extra_variables() == []
    save_extra_variables(["{{location}}", "{{home}}"])
    assert load_extra_variables() == ["{{location}}", "{{home}}"]


def test_variable_library_popup_rebuild_and_star(tmp_path, monkeypatch):
    """变量库弹层：分组重建含自定义；★ 切换常用持久化 + favorites_changed。"""
    _isolate_config(tmp_path, monkeypatch)
    from services.template.registry import PRESET_VARIABLES
    from ui.template_components import (VariableLibraryPopup,
                                        load_favorite_variables)

    popup = VariableLibraryPopup()
    popup.set_custom_variables(["{{location}}"])
    toggled = []
    popup.favorites_changed.connect(lambda: toggled.append(1))
    try:
        popup.rebuild()
        rows = [ins for _btn, ins in popup._rows]
        assert "{{date}}" in rows and "{{location}}" in rows  # 内置+自定义
        # 类别分组标题（固定顺序：系统 → 用户输入 → 上下文 → 自定义）
        titles = []
        for i in range(popup._body_lay.count()):
            w = popup._body_lay.itemAt(i).widget()
            if isinstance(w, QLabel) and w.objectName() == "groupHeader":
                titles.append(w.text())
        assert titles == ["系统", "用户输入", "上下文", "自定义"]
        # 自定义变量排最后（类别序）
        assert rows[-1] == "{{location}}"
        # ★ 移除常用（默认全预设 → {{date}} 是常用）→ 持久化 + 信号
        popup._toggle_favorite("{{date}}")
        assert "{{date}}" not in load_favorite_variables()
        assert toggled  # favorites_changed 已发
        # 行 ★ 状态同步（{{date}} 变 ☆）
        text = dict((ins, btn.text()) for btn, ins in popup._rows)["{{date}}"]
        assert text.startswith("☆ ")
    finally:
        popup.close()


def test_var_tag_bar_set_variables():
    """胶囊区整体重建（常用变量变更后）。"""
    from ui.template_components import VariableTagBar

    bar = VariableTagBar(variables=["{{a}}", "{{b}}"])
    try:
        bar.set_variables(["{{x}}", "{{y}}", "{{z}}"])
        assert bar.variables() == ["{{x}}", "{{y}}", "{{z}}"]
    finally:
        bar.close()


def test_var_tag_bar_set_variables_relayouts():
    """胶囊区重建后强制重排：新胶囊不堆叠在默认几何 (0,0,640,480)。

    回归（问题4）：取消收藏触发 set_variables 后，新胶囊停在默认几何、
    全部叠在一起——_relayout 必须强制 _do_layout 立即重排。
    """
    from ui.template_components import VariableTagBar

    bar = VariableTagBar(variables=["{{date}}", "{{time}}", "{{datetime}}",
                                    "{{uuid}}", "{{clipboard}}"])
    try:
        bar.resize(280, 100)
        bar.show()
        pytest_app.processEvents()
        bar._flow.activate()  # offscreen 下强制初始布局（真实 show 已触发）
        bar.set_variables(["{{date}}", "{{time}}", "{{datetime}}"])
        # 每个胶囊都已被排布（自然宽 < 默认 640），且 x 互异（不堆叠）
        assert all(b.width() < 100 for b in bar._pills)
        xs = [b.x() for b in bar._pills]
        assert xs == sorted(set(xs))
    finally:
        bar.close()


def test_var_tag_pill_min_height_no_vertical_overlap():
    """回归（问题4）：胶囊行高须取 max(sizeHint, minimumSize)。

    macOS 上 varTag 的 sizeHint 高度（样式表 padding 不计入）小于固定高度
    24px，_FlowLayout 若按偏小 sizeHint 算行高，第二行会叠到第一行上
    （实测 macOS 第二行 y=11 压进第一行）。行高取最小高度后，折行的
    第二行 y 必须 ≥ 第一行胶囊底部（24px），不垂直重叠。
    """
    from ui.template_components import VariableTagBar

    bar = VariableTagBar(variables=["{{date}}", "{{time}}", "{{datetime}}"])
    try:
        bar.resize(160, 100)  # 窄到 3 个胶囊必然折行
        bar.show()
        pytest_app.processEvents()
        bar._relayout()
        visible = [b for b in bar._pills if b.isVisible()]
        rows = sorted({b.y() for b in visible})
        assert len(rows) >= 2  # 窄宽下必然折成多行
        # 相邻两行 y 间距 ≥ 24（行高 24px）——第二行不压进第一行
        for a, b in zip(rows, rows[1:]):
            assert b - a >= 24
    finally:
        bar.close()



def test_library_row_button_star_zone(tmp_path, monkeypatch):
    """变量库行按钮：★ 区点击切常用（不发插入）；行区点击插入。"""
    _isolate_config(tmp_path, monkeypatch)
    from ui.template_components import VariableLibraryPopup

    popup = VariableLibraryPopup()
    popup.set_custom_variables(["{{location}}"])
    inserted, toggled = [], []
    popup.insert_requested.connect(lambda s: inserted.append(s))
    popup.favorites_changed.connect(lambda: toggled.append(1))
    try:
        popup.rebuild()
        btn = next(b for b, ins in popup._rows if ins == "{{location}}")
        # ★ 区（x=5）→ 切常用（默认不在常用 → 加进 favorites），不发插入
        _press(btn, 5)
        assert not inserted
        assert toggled
        from ui.template_components import load_favorite_variables

        assert "{{location}}" in load_favorite_variables()
        # 重建后重新取按钮（★ 切换会 rebuild）
        btn = next(b for b, ins in popup._rows if ins == "{{location}}")
        # 行区（x=80）→ 插入
        _press(btn, 80)
        assert inserted == ["{{location}}"]
    finally:
        popup.close()
