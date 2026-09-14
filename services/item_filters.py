"""历史条目「可见/可搜」判据（§9.9 过期临时条目 / §9.17 敏感遮蔽）。

**为什么需要这一层**：`services.history_service.delete_expired()` 由 24 小时
清扫定时器驱动（见 `app/bootstrap.py::sweep_old_history`），过期条目在那之前
仍然留在 SQLite 里。只靠删除的话，「临时保存 1 分钟」的内容最长 24 小时
照旧可见、可搜——所以每条读取路径都必须**自己**过滤，不能等清扫。

**敏感条目为什么不能参与检索**：遮蔽显示（§9.17）的目的是「看历史时看不到
正文」。但如果正文仍在索引里，在搜索框输入候选口令、看是否命中，就能反推被
遮蔽的内容——遮蔽等于白做。故搜索路径整体排除 `sensitive = 1` 的行。

**过滤为什么必须在查询层、而不是索引层**：`items_fts` 是 external-content
表（`content='clipboard_items'`），且所有删除路径都靠
`INSERT INTO items_fts(items_fts) VALUES('rebuild')` 从内容表重建索引
（原因见 `history_service._delete_rows_and_rebuild` 的说明）。只要发生过
一次 rebuild，任何「从索引里剔掉某行」的努力都会原样回来。索引层剔不掉，
查询层才拦得住。
"""
from datetime import datetime

from sqlalchemy import or_

from database.models import ClipboardItem as ItemRow


def _prefix(alias: str) -> str:
    return f"{alias}." if alias else ""


def alive_sql(alias: str = "") -> str:
    """未过期的 raw SQL 条件（需配套传入 `:now` 参数）。

    用 `>` 而非 `>=`：与 `delete_expired` 的 `<` 互补，边界不重叠。
    """
    p = _prefix(alias)
    return f"({p}expires_at IS NULL OR {p}expires_at > :now)"


def searchable_sql(alias: str = "") -> str:
    """可检索的 raw SQL 条件：未过期 **且** 非敏感（需配套 `:now`）。"""
    p = _prefix(alias)
    return f"{alive_sql(alias)} AND ({p}sensitive IS NULL OR {p}sensitive = 0)"


def alive_orm(now: datetime | None = None):
    """未过期的 ORM 条件（列表类查询用）。"""
    now = now or datetime.now()
    return or_(ItemRow.expires_at.is_(None), ItemRow.expires_at > now)
