"""模板服务：CRUD / 文件夹 / 搜索 / 渲染流水线（文档 §88-89）。

- create/update 做 shortcut 唯一校验（冲突抛 ValueError，不静默覆盖 §8）
  + 模板内容验证（validate_template，§66）
- 搜索评分排序（§19）：shortcut 精确 > name 精确 > shortcut 前缀 >
  name 前缀 > content/folder LIKE；同分收藏优先 + 最近使用
- render_template 返回 (text, cursor_pos, input_names)（§43 去重）
"""
import datetime
import logging

from sqlalchemy import func, or_, select
from sqlalchemy.engine import Engine

from database.engine import make_session_factory
from database.models import Snippet, SnippetFolder
from services.template.custom_vars import load_custom_vars
from services.template.parser import (collect_inputs, parse, validate_args,
                                      validate_template)
from services.template.renderer import render
from services.template.variables import RenderContext

logger = logging.getLogger(__name__)


def _row_to_dict(row: Snippet) -> dict:
    return {
        "id": row.id, "name": row.name, "shortcut": row.shortcut,
        "content": row.content, "description": row.description or "",
        "folder_id": row.folder_id,
        "enabled": bool(row.enabled), "favorite": bool(row.favorite),
        "trigger_mode": row.trigger_mode,
        "usage_count": row.usage_count,
        "last_used_at": row.last_used_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


# config 键 → 变量关键字（template.date_format 等）
_CONFIG_FORMAT_KEYS = (
    ("date_format", "date"),
    ("time_format", "time"),
    ("datetime_format", "datetime"),
)


def _default_date_formats() -> dict[str, str]:
    """config `template.date_format/time_format/datetime_format` → 变量默认格式。

    这三个键此前是**死配置**（defaults.yaml 里有、全仓无人读，渲染走
    `variables._DEFAULT_FORMATS` 硬编码）。现接上：`{{date}}` 等**无参数**时
    用它们作全局默认；带参数（`{{date:YYYY年}}`）仍逐次覆盖。

    值按 strftime 解释（与 defaults.yaml 内置值同格式）；读失败/缺键/空值
    → 不放进结果，provider 回落到内置默认。
    """
    try:
        from app.config import load_config

        tpl = load_config().get("template", {}) or {}
    except Exception:
        logger.debug("读取模板默认日期格式失败，用内置默认", exc_info=True)
        return {}
    out: dict[str, str] = {}
    for key, keyword in _CONFIG_FORMAT_KEYS:
        value = str(tpl.get(key, "") or "").strip()
        if value:
            out[keyword] = value
    return out


class TemplateService:
    """模板模块服务（bootstrap 实例化注入 engine）。"""

    def __init__(self, engine: Engine, clipboard_reader=None,
                 selection_reader=None):
        self._engine = engine
        # 剪贴板读取器可注入（测试替换）；默认读系统剪贴板
        self._read_clipboard = clipboard_reader or self._system_clipboard
        # 选中文本读取器可注入（测试替换）；默认读前台应用选中文本（AX）
        self._read_selection = selection_reader or self._system_selection

    # ---- 剪贴板 / 选中文本 ----

    @staticmethod
    def _system_clipboard() -> str:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString

            pb = NSPasteboard.generalPasteboard()
            return pb.stringForType_(NSPasteboardTypeString) or ""
        except Exception:
            return ""

    @staticmethod
    def _system_selection() -> str:
        """前台应用当前选中文本（{{selection}} 值源）。失败/无选中 → ""。"""
        try:
            from services.template.ax_text import read_focused_selection

            return read_focused_selection() or ""
        except Exception:
            return ""

    # ---- 模板 CRUD ----

    def list_templates(self, folder_id: int | None = None) -> list[dict]:
        """全部模板（收藏优先 + 最新创建在前），可按文件夹过滤（None=全部）。"""
        with make_session_factory(self._engine)() as session:
            q = select(Snippet).order_by(
                Snippet.favorite.desc(),
                Snippet.created_at.desc(), Snippet.id.desc())
            if folder_id is not None:
                q = q.where(Snippet.folder_id == folder_id)
            rows = session.execute(q).scalars().all()
        return [_row_to_dict(r) for r in rows]

    def get_template(self, template_id: int) -> dict | None:
        with make_session_factory(self._engine)() as session:
            row = session.get(Snippet, template_id)
            return _row_to_dict(row) if row else None

    def create_template(self, name: str, shortcut: str, content: str,
                        description: str = "", folder_id: int | None = None,
                        trigger_mode: str = "tab") -> int:
        """创建模板。shortcut 冲突抛 ValueError；内容非法抛 TemplateError 子类。"""
        self._validate_new_shortcut(shortcut)
        custom_vars = load_custom_vars()
        # 结构校验用 parse（失败保留具体异常类型，如 UnknownVariableError）；
        # 参数用法校验用 validate_args（只给消息）。
        tokens = parse(content, custom_names=set(custom_vars))
        error = validate_args(tokens, custom_vars)
        if error:
            from services.template.errors import TemplateError

            raise TemplateError(error)
        now = datetime.datetime.now()
        with make_session_factory(self._engine)() as session:
            sc = shortcut.strip().lower()
            self._check_shortcut_available(session, sc)
            row = Snippet(name=name, shortcut=sc,
                          content=content, description=description,
                          folder_id=folder_id, trigger_mode=trigger_mode,
                          created_at=now, updated_at=now)
            session.add(row)
            session.commit()
            return row.id

    def update_template(self, template_id: int, *, name: str | None = None,
                        shortcut: str | None = None, content: str | None = None,
                        description: str | None = None,
                        folder_id=None, trigger_mode: str | None = None) -> bool:
        """更新模板。shortcut 冲突（他人占用）抛 ValueError；内容非法抛错。"""
        with make_session_factory(self._engine)() as session:
            row = session.get(Snippet, template_id)
            if row is None:
                return False
            if shortcut is not None:
                sc = shortcut.strip().lower()
                self._check_shortcut_available(session, sc, exclude_id=template_id)
                row.shortcut = sc
            if name is not None:
                row.name = name
            if content is not None:
                custom_vars = load_custom_vars()
                error = validate_template(
                    content, custom_names=set(custom_vars),
                    custom_vars=custom_vars)
                if error:
                    from services.template.errors import TemplateError

                    raise TemplateError(error)
                row.content = content
            if description is not None:
                row.description = description
            if folder_id is not None:
                row.folder_id = folder_id
            if trigger_mode is not None:
                row.trigger_mode = trigger_mode
            row.updated_at = datetime.datetime.now()
            session.commit()
            return True

    def delete_template(self, template_id: int) -> bool:
        with make_session_factory(self._engine)() as session:
            row = session.get(Snippet, template_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    # ---- 快捷操作 ----

    def find_by_shortcut(self, shortcut: str) -> dict | None:
        """按 shortcut 精确查找（仅 enabled，Tab 触发用）。"""
        sc = shortcut.strip().lower()
        with make_session_factory(self._engine)() as session:
            row = session.execute(
                select(Snippet).where(
                    Snippet.shortcut == sc, Snippet.enabled == 1)
            ).scalars().first()
            return _row_to_dict(row) if row else None

    def list_shortcuts(self) -> list[dict]:
        """全部已启用模板的 shortcut 列表（文本末尾匹配用，含中文）。

        返回 [{"shortcut": ..., "trigger_mode": ..., "id": ...}, ...]
        """
        with make_session_factory(self._engine)() as session:
            rows = session.execute(
                select(Snippet).where(Snippet.enabled == 1)
            ).scalars().all()
        return [{"shortcut": r.shortcut, "trigger_mode": r.trigger_mode,
                 "id": r.id} for r in rows]

    def has_chinese_shortcut(self) -> bool:
        """是否存在非 ASCII（中文）shortcut。

        决定是否强制开启前台应用的 AX 树（bootstrap 调用）：中文 shortcut
        触发依赖 AX 读取上屏汉字；纯英文 shortcut 走键盘缓冲不需要 AX——
        不强制开，避免给用户的编辑器（Electron 应用）带来 Chromium AX 开销。
        """
        return any(not item["shortcut"].isascii()
                   for item in self.list_shortcuts())

    def toggle_enabled(self, template_id: int) -> bool:
        with make_session_factory(self._engine)() as session:
            row = session.get(Snippet, template_id)
            if row is None:
                return False
            row.enabled = 0 if row.enabled else 1
            row.updated_at = datetime.datetime.now()
            session.commit()
            return True

    def toggle_favorite(self, template_id: int) -> bool:
        with make_session_factory(self._engine)() as session:
            row = session.get(Snippet, template_id)
            if row is None:
                return False
            row.favorite = 0 if row.favorite else 1
            row.updated_at = datetime.datetime.now()
            session.commit()
            return True

    def record_usage(self, template_id: int) -> None:
        """使用统计：usage_count+1、last_used_at 更新（§20/§94）。"""
        with make_session_factory(self._engine)() as session:
            row = session.get(Snippet, template_id)
            if row is not None:
                row.usage_count += 1
                row.last_used_at = datetime.datetime.now()
                session.commit()

    # ---- 搜索（§18-19）----

    def search_templates(self, query: str) -> list[dict]:
        """搜索 Name/Shortcut/Content/Folder，评分排序（§19）。

        评分：shortcut 精确 100 > name 精确 80 > shortcut 前缀 60 >
        name 前缀 40 > content/folder LIKE 20；同分收藏优先 + 最近使用。
        """
        q = query.strip().lower()
        if not q:
            return self.list_templates()
        with make_session_factory(self._engine)() as session:
            rows = session.execute(
                select(Snippet, SnippetFolder.name)
                .outerjoin(SnippetFolder, Snippet.folder_id == SnippetFolder.id)
            ).all()
        results = []
        for row, folder_name in rows:
            sc = row.shortcut.lower()
            name = (row.name or "").lower()
            score = 0
            if sc == q:
                score = 100
            elif name == q:
                score = 80
            elif sc.startswith(q):
                score = 60
            elif name.startswith(q):
                score = 40
            elif q in (row.content or "").lower() or \
                    q in (folder_name or "").lower():
                score = 20
            if score == 0:
                continue
            d = _row_to_dict(row)
            d["score"] = score
            d["folder_name"] = folder_name or ""
            results.append(d)
        # 排序：评分降序 → 收藏优先 → 最近使用降序
        results.sort(key=lambda d: (
            -d["score"], 0 if d["favorite"] else 1,
            -(d["last_used_at"].timestamp() if d["last_used_at"] else 0)))
        return results

    # ---- 渲染流水线 ----

    def collect_inputs_for(self, content: str,
                           custom_vars: dict | None = None) -> list:
        """只收集渲染所需输入，**不渲染**（触发链路第一次调用，§43）。

        渲染有副作用：自定义变量的 command 值源会真的执行外部命令（甚至
        有写文件/发通知这类副作用）。触发链路此前先渲染一次「只为拿
        input_requests」、拿到用户输入后再渲染第二次——命令因此每次触发
        执行两遍。而 input_requests 只依赖 token 流，与渲染结果无关，故
        第一次调用改为纯解析：全程恰好渲染一次。

        返回 list[InputRequest]（与 render_template 第三项同源同序）。
        """
        if custom_vars is None:
            custom_vars = load_custom_vars()
        tokens = parse(content, custom_names=set(custom_vars))
        return collect_inputs(tokens, custom_vars)

    def render_template(self, content: str,
                        input_values: dict[str, str] | None = None,
                        clipboard_text: str | None = None,
                        selection_text: str | None = None,
                        now: datetime.datetime | None = None,
                        custom_vars: dict | None = None,
                        app_name: str = "",
                        ) -> tuple[str, int | None, list]:
        """完整渲染：parse → 收集 input → 渲染。

        返回 (text, cursor_pos|None, input_requests)。input_requests 是
        list[InputRequest]（{{input:name}} + 用户输入来源的自定义变量），
        input_values 未提供时供调用方收集用户输入后二次调用。
        custom_vars：name → CustomVariable；None 时读 config。
        默认日期格式读 config（_default_date_formats）；日期输出靠 now= 注入。
        app_name：触发瞬间捕获的目标应用名（命令值源的 CW_APP）——本应用
        会因弹层/对话框夺走前台，渲染时现读 frontmostApplication() 不可靠。
        """
        if custom_vars is None:
            custom_vars = load_custom_vars()
        tokens = parse(content, custom_names=set(custom_vars))
        inputs = collect_inputs(tokens, custom_vars)
        ctx = RenderContext(
            now=now or datetime.datetime.now(),
            clipboard_text=(clipboard_text if clipboard_text is not None
                            else self._read_clipboard()),
            selection_text=(selection_text if selection_text is not None
                            else self._read_selection()),
            input_values=input_values or {},
            custom_vars=custom_vars,
            date_formats=_default_date_formats(),
            template=content,
            app_name=app_name,
        )
        text, cursor_pos = render(tokens, ctx)
        return text, cursor_pos, inputs

    # ---- 文件夹 ----

    def list_folders(self) -> list[dict]:
        """文件夹列表（含模板计数）。"""
        with make_session_factory(self._engine)() as session:
            rows = session.execute(
                select(SnippetFolder, func.count(Snippet.id))
                .outerjoin(Snippet, Snippet.folder_id == SnippetFolder.id)
                .group_by(SnippetFolder.id)
                .order_by(SnippetFolder.id)
            ).all()
        return [{"id": r.id, "name": r.name, "count": c} for r, c in rows]

    def create_folder(self, name: str) -> int:
        now = datetime.datetime.now()
        with make_session_factory(self._engine)() as session:
            row = SnippetFolder(name=name.strip(), created_at=now, updated_at=now)
            session.add(row)
            session.commit()
            return row.id

    def rename_folder(self, folder_id: int, name: str) -> bool:
        with make_session_factory(self._engine)() as session:
            row = session.get(SnippetFolder, folder_id)
            if row is None:
                return False
            row.name = name.strip()
            row.updated_at = datetime.datetime.now()
            session.commit()
            return True

    def delete_folder(self, folder_id: int) -> bool:
        """删除文件夹：模板移入未分类（folder_id=NULL，§14 默认策略）。"""
        with make_session_factory(self._engine)() as session:
            row = session.get(SnippetFolder, folder_id)
            if row is None:
                return False
            session.execute(
                Snippet.__table__.update()
                .where(Snippet.folder_id == folder_id)
                .values(folder_id=None))
            session.delete(row)
            session.commit()
            return True

    # ---- 校验 ----

    @staticmethod
    def _validate_new_shortcut(shortcut: str) -> None:
        sc = shortcut.strip().lower()
        if not sc:
            raise ValueError("Shortcut 不能为空")
        if len(sc) < 2:
            raise ValueError("不建议使用单字符 Shortcut（§6.1）")

    def _check_shortcut_available(self, session, sc: str,
                                  exclude_id: int | None = None) -> None:
        q = select(Snippet.id).where(Snippet.shortcut == sc)
        if exclude_id is not None:
            q = q.where(Snippet.id != exclude_id)
        exists = session.execute(q).scalars().first()
        if exists is not None:
            raise ValueError(f"Shortcut「{sc}」已存在，请换一个")
