"""Snippet 兼容层（v6 重构后）：代理到 TemplateService，旧 API 保持可用。

旧 API 语义差异：
- create_snippet(name, content, description) 无 shortcut → shortcut 取 name 小写
- render_snippet：仅 {{date}}/{{time}}/{{uuid}} 三个变量，
  **未知变量原样保留**（旧行为，与模板引擎的报错策略不同）
"""
import datetime
import logging
import re
import uuid

from sqlalchemy.engine import Engine

from services.template_service import TemplateService

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")

# 可用变量提示（页面展示用，兼容旧引用）
AVAILABLE_VARS = ("{{date}}", "{{time}}", "{{uuid}}")


# ---- CRUD（代理到 TemplateService，shortcut 兼容）----

def list_snippets(engine: Engine) -> list[dict]:
    """全部片段（最新创建在前）。返回含模板新字段的 dict。"""
    return TemplateService(engine).list_templates()


def create_snippet(engine: Engine, name: str, content: str,
                   description: str = "") -> int:
    """创建片段。旧 API 无 shortcut → 默认取 name 小写。"""
    sc = (name or "").strip().lower() or f"tmpl-{uuid.uuid4().hex[:6]}"
    try:
        return TemplateService(engine).create_template(
            name, sc, content, description=description)
    except ValueError:
        # shortcut 冲突（name 重复）：追加短后缀重试
        sc = f"{sc}-{uuid.uuid4().hex[:4]}"
        return TemplateService(engine).create_template(
            name, sc, content, description=description)


def update_snippet(engine: Engine, snippet_id: int, name: str, content: str,
                   description: str = "") -> bool:
    return TemplateService(engine).update_template(
        snippet_id, name=name, content=content, description=description)


def delete_snippet(engine: Engine, snippet_id: int) -> bool:
    return TemplateService(engine).delete_template(snippet_id)


def render_snippet(
    content: str,
    *,
    date_fmt: str = "%Y-%m-%d",
    time_fmt: str = "%H:%M:%S",
    now: datetime.datetime | None = None,
) -> str:
    """渲染 Snippet 变量（旧语义）：未知变量原样保留，不抛错。"""
    now = now or datetime.datetime.now()

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name == "date":
            return now.strftime(date_fmt)
        if name == "time":
            return now.strftime(time_fmt)
        if name == "uuid":
            return str(uuid.uuid4())
        return match.group(0)  # 未知变量原样保留

    return _VAR_RE.sub(_replace, content)
