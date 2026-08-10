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
from services.template.parser import collect_inputs, parse, validate_template
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


class TemplateService:
    """模板模块服务（bootstrap 实例化注入 engine）。"""

    def __init__(self, engine: Engine, clipboard_reader=None):
        self._engine = engine
        # 剪贴板读取器可注入（测试替换）；默认读系统剪贴板
        self._read_clipboard = clipboard_reader or self._system_clipboard

    # ---- 剪贴板 ----

    @staticmethod
    def _system_clipboard() -> str:
        try:
            from AppKit import NSPasteboard, NSPasteboardTypeString

            pb = NSPasteboard.generalPasteboard()
            return pb.stringForType_(NSPasteboardTypeString) or ""
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
        parse(content)  # 内容验证：抛具体异常（UnknownVariableError 等）
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
                error = validate_template(content)
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

    def render_template(self, content: str,
                        input_values: dict[str, str] | None = None,
                        clipboard_text: str | None = None,
                        now: datetime.datetime | None = None,
                        ) -> tuple[str, int | None, list[str]]:
        """完整渲染：parse → 收集 input → 渲染。

        返回 (text, cursor_pos|None, input_names 去重列表)。
        input_values 未提供时 input_names 供调用方收集用户输入后二次调用。
        """
        tokens = parse(content)
        input_names = collect_inputs(tokens)
        ctx = RenderContext(
            now=now or datetime.datetime.now(),
            clipboard_text=(clipboard_text if clipboard_text is not None
                            else self._read_clipboard()),
            input_values=input_values or {},
        )
        text, cursor_pos = render(tokens, ctx)
        return text, cursor_pos, input_names

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
