"""轻量迁移：Base.metadata.create_all + 版本化迁移（不引 Alembic）。

演进约定：新增迁移时在 migrate() 里按 user_version 分支处理，
完成后递增 _SCHEMA_VERSION。
"""
import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .models import Base

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 10

# 幂等扩展 DDL（FTS5 全文索引 + 常用索引）
_EXTRA_DDL = [
    # FTS5 外部内容表：items_fts 与 clipboard_items 同表同步，由 search_service 维护
    "CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5("
    "content, content='clipboard_items', content_rowid='id')",
    "CREATE INDEX IF NOT EXISTS ix_items_created ON clipboard_items (created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_items_type ON clipboard_items (type)",
]


def migrate(engine: Engine) -> None:
    with engine.connect() as conn:
        current = conn.execute(text("PRAGMA user_version")).scalar()
    logger.info("数据库 schema 版本: %s", current)

    Base.metadata.create_all(engine)  # ORM 表（新库按最新模型建）

    if current < 2:
        _upgrade_v2_collection_snapshot(engine)
    if current < 3:
        _upgrade_v3_code_privacy(engine)
    if current < 4:
        _upgrade_v4_sessions(engine)
    if current < 5:
        _upgrade_v5_dedupe_scope(engine)
    if current < 6:
        _upgrade_v6_snippets_to_templates(engine)
    if current < 7:
        _upgrade_v7_image_hash_normalize(engine)
    if current < 9:
        _upgrade_v9_withdraw_shipped_templates(engine)
    if current < 10:
        _upgrade_v10_collection_snapshot_metadata(engine)

    with engine.begin() as conn:
        for ddl in _EXTRA_DDL:
            conn.execute(text(ddl))
        conn.execute(text(f"PRAGMA user_version = {_SCHEMA_VERSION}"))
    logger.info("迁移完成，schema 版本 -> %s", _SCHEMA_VERSION)


def _upgrade_v10_collection_snapshot_metadata(engine: Engine) -> None:
    """v9 → v10：collection_items 补上渲染/操作用得到的元数据快照列。

    收藏是**内容快照**（与历史解耦），但早先只存了 type/content/preview/file_path
    ——`language` 没存，于是收藏夹里的代码条目打开详情时拿到空 language，高亮器
    选不出词法、整段没有颜色（用户实测报的）；列表里的语言徽标同理。`sensitive`
    也一样：详情弹窗会按它决定是否遮蔽。

    新列全部 nullable（SQLite ALTER TABLE ADD COLUMN 的限制），并顺手用
    clipboard_id 从历史回填一次——历史还在的收藏条目立刻就有语言。历史已清掉的
    只能等下次重新收藏：快照的语义就是「不依赖历史」，这里不该去猜。
    """
    new_cols = [
        ("language", "VARCHAR(32)"),
        ("source_app", "VARCHAR(255)"),
        ("sensitive", "INTEGER DEFAULT 0"),
        ("sensitive_type", "VARCHAR(32)"),
    ]
    with engine.begin() as conn:
        existing = {r[1] for r in conn.execute(
            text("PRAGMA table_info(collection_items)")).fetchall()}
        for col_name, col_type in new_cols:
            if col_name not in existing:
                conn.execute(text(
                    f"ALTER TABLE collection_items ADD COLUMN {col_name} {col_type}"))
        conn.execute(text(
            "UPDATE collection_items SET"
            " language = COALESCE(language, (SELECT i.language"
            "   FROM clipboard_items i WHERE i.id = collection_items.clipboard_id)),"
            " source_app = COALESCE(source_app, (SELECT i.source_app"
            "   FROM clipboard_items i WHERE i.id = collection_items.clipboard_id)),"
            " sensitive_type = COALESCE(sensitive_type, (SELECT i.sensitive_type"
            "   FROM clipboard_items i WHERE i.id = collection_items.clipboard_id)),"
            # sensitive 是 `DEFAULT 0` 加的列 → 老行拿到的是 0 不是 NULL，
            # COALESCE 取不到子查询，得显式区分「0 = 还没标过」
            " sensitive = CASE WHEN sensitive = 0 THEN COALESCE("
            "   (SELECT i.sensitive FROM clipboard_items i"
            "    WHERE i.id = collection_items.clipboard_id), 0)"
            "   ELSE sensitive END"))
    logger.info("v10 迁移：collection_items 补齐元数据快照列并回填")


def _upgrade_v2_collection_snapshot(engine: Engine) -> None:
    """v1 → v2：collection_items 增加内容快照列（收藏与历史解耦）。

    旧表仅有 collection_id/clipboard_id 引用且 FK 级联删除历史；
    重建为快照结构（内容冗余），并回填已有收藏的内容。
    """
    with engine.begin() as conn:
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(collection_items)")).fetchall()}
        if "content" in cols:
            return  # 已是快照结构
        conn.execute(text(
            "ALTER TABLE collection_items RENAME TO collection_items_old"))
        conn.execute(text(
            "CREATE TABLE collection_items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " collection_id INTEGER NOT NULL"
            "   REFERENCES collections(id) ON DELETE CASCADE,"
            " clipboard_id INTEGER NOT NULL DEFAULT 0,"
            " type VARCHAR(16) NOT NULL DEFAULT 'text',"
            " content TEXT, preview TEXT, file_path TEXT,"
            " created_at DATETIME NOT NULL,"
            " UNIQUE (collection_id, clipboard_id))"))
        conn.execute(text(
            "INSERT INTO collection_items"
            " (collection_id, clipboard_id, type, content, preview, file_path,"
            "  created_at)"
            " SELECT o.collection_id, o.clipboard_id, COALESCE(i.type, 'text'),"
            "        i.content, i.preview, i.file_path,"
            "        COALESCE(i.created_at, datetime('now'))"
            " FROM collection_items_old o"
            " LEFT JOIN clipboard_items i ON i.id = o.clipboard_id"))
        conn.execute(text("DROP TABLE collection_items_old"))
        logger.info("v2 迁移：collection_items 已快照化并回填")


def _upgrade_v3_code_privacy(engine: Engine) -> None:
    """v2 → v3：clipboard_items 增加 Code Mode / Privacy Mode 元数据列。

    全部 nullable 或带 DEFAULT（SQLite ALTER TABLE ADD COLUMN 限制），
    PRAGMA table_info 防重（新库由 create_all 已建好全部列）。
    """
    new_cols = [
        ("language", "VARCHAR(32)"),
        ("language_confidence", "REAL"),
        ("line_count", "INTEGER DEFAULT 0"),
        ("character_count", "INTEGER DEFAULT 0"),
        ("is_structured", "INTEGER DEFAULT 0"),
        ("sensitive", "INTEGER DEFAULT 0"),
        ("sensitive_type", "VARCHAR(32)"),
        ("expires_at", "DATETIME"),
    ]
    with engine.begin() as conn:
        existing = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        for col_name, col_type in new_cols:
            if col_name not in existing:
                conn.execute(text(
                    f"ALTER TABLE clipboard_items ADD COLUMN {col_name} {col_type}"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_items_expires "
            "ON clipboard_items (expires_at)"))
    logger.info("v3 迁移：code/privacy 元数据列已添加")


def _upgrade_v4_sessions(engine: Engine) -> None:
    """v3 → v4：会话机制——sessions 表 + clipboard_items.session_id。

    默认会话固定 id=1（普通）；历史数据全部归入。删除会话时内容
    移回普通会话（session_service.delete_session）。
    """
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS sessions ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name VARCHAR(128) NOT NULL,"
            " is_default INTEGER DEFAULT 0,"
            " created_at DATETIME NOT NULL)"))
        # 幂等插入默认会话（id=1 固定）
        row = conn.execute(text(
            "SELECT id FROM sessions WHERE id = 1")).fetchone()
        if row is None:
            conn.execute(text(
                "INSERT INTO sessions (id, name, is_default, created_at)"
                " VALUES (1, '普通', 1, datetime('now'))"))
        else:
            conn.execute(text(
                "UPDATE sessions SET is_default = 1 WHERE id = 1"))
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        if "session_id" not in cols:
            conn.execute(text(
                "ALTER TABLE clipboard_items ADD COLUMN session_id"
                " INTEGER NOT NULL DEFAULT 1"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_items_session"
            " ON clipboard_items (session_id)"))
    logger.info("v4 迁移：会话机制已建立（默认「普通」id=1）")


def _upgrade_v5_dedupe_scope(engine: Engine) -> None:
    """v4 → v5：去重范围可配置——唯一约束 hash → (hash, session_id)。

    SQLite 无法删除/修改唯一约束（ALTER TABLE 限制）→ 重建表：
    - 保留全部列与 id（collection_items.clipboard_id 悬空引用仍有效）
    - 唯一键改为 UNIQUE(hash, session_id)：同一内容可在不同会话各存一份
      （scope=session 去重的前提）；scope=all 时由 save_item 查重逻辑
      维持全局去重语义（DB 约束放宽不影响）
    - 重建 items_fts 索引（外部内容表 rowid 对应 id 不变）
    """
    cols = [
        "id", "type", "content", "preview", "file_path", "hash", "source_app",
        "favorite", "pinned", "created_at", "updated_at", "session_id",
        "language", "language_confidence", "line_count", "character_count",
        "is_structured", "sensitive", "sensitive_type", "expires_at",
    ]
    with engine.begin() as conn:
        existing = {r[1] for r in conn.execute(
            text("PRAGMA table_info(clipboard_items)")).fetchall()}
        if "session_id" not in existing:
            # 理论不可达（v4 已加），防御
            return
        conn.execute(text(
            "ALTER TABLE clipboard_items RENAME TO clipboard_items_v4"))
        conn.execute(text(
            "CREATE TABLE clipboard_items ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " type VARCHAR(16) NOT NULL, content TEXT, preview TEXT,"
            " file_path TEXT, hash VARCHAR(64) NOT NULL,"
            " source_app VARCHAR(255), favorite INTEGER DEFAULT 0,"
            " pinned INTEGER DEFAULT 0,"
            " created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,"
            " session_id INTEGER NOT NULL DEFAULT 1,"
            " language VARCHAR(32), language_confidence REAL,"
            " line_count INTEGER DEFAULT 0, character_count INTEGER DEFAULT 0,"
            " is_structured INTEGER DEFAULT 0, sensitive INTEGER DEFAULT 0,"
            " sensitive_type VARCHAR(32), expires_at DATETIME,"
            " UNIQUE (hash, session_id))"))
        conn.execute(text(
            "INSERT INTO clipboard_items (" + ", ".join(cols) + ")"
            " SELECT " + ", ".join(cols) + " FROM clipboard_items_v4"))
        conn.execute(text("DROP TABLE clipboard_items_v4"))
        for ddl in (
            "CREATE INDEX IF NOT EXISTS ix_items_created"
            " ON clipboard_items (created_at DESC)",
            "CREATE INDEX IF NOT EXISTS ix_items_type ON clipboard_items (type)",
            "CREATE INDEX IF NOT EXISTS ix_items_expires"
            " ON clipboard_items (expires_at)",
            "CREATE INDEX IF NOT EXISTS ix_items_session"
            " ON clipboard_items (session_id)",
        ):
            conn.execute(text(ddl))
        # items_fts 由 _EXTRA_DDL 在迁移后创建：旧库存在才 rebuild，
        # 新库（迁移链从头跑）此时尚无 FTS 表，跳过由 create 空表
        tables = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        if "items_fts" in tables:
            conn.execute(text(
                "INSERT INTO items_fts(items_fts) VALUES('rebuild')"))
    logger.info("v5 迁移：唯一约束改为 (hash, session_id)（去重范围可配置）")


# ---- v6：模板模块（原「片段」，文档 §80-82）----

# 默认文件夹（文档 §9）：模板分组
_DEFAULT_FOLDERS = ("个人", "工作", "开发", "模板")
# 默认示例模板（文档 §101/§127）：INSERT OR IGNORE（shortcut 唯一保护幂等）
_DEFAULT_TEMPLATES = [
    ("Shrug", "shrug", "¯\\_(ツ)_/¯"),
    ("Today", "today", "Today: {{date}}"),
    ("UUID", "uuid", "{{uuid}}"),
    ("Markdown Quote", "quote", "> {{clipboard}}"),
]

# v8 曾铺过、v9 撤回的变换模板（配 resources/scripts/ 里的脚本，见 §7.4）
# (name, shortcut, content, description)
#
# ⚠️ 这段数据现在**只给 v9 清理用**，不要再拿去种模板。这批模板的输入是
# 「选中的文本」，触发方式却是「在输入框里打 shortcut 词 + Tab」——第一个
# 字母就会把选中的文本覆盖掉，输入从来拿不到；且结果又插回原处，原文没了
# 也没法对照验证。形态本身不成立，变换类要重做成「对剪贴板条目执行」。
WITHDRAWN_TEMPLATES_FOLDER = "变换"
_WITHDRAWN_TEMPLATES = [
    ("转大写", "up", "{{upper}}", "整段字母转大写"),
    ("转小写", "lo", "{{lower}}", "整段字母转小写"),
    ("标题化", "ti", "{{title}}", "每词首字母大写"),
    ("清理空白", "cl", "{{trim}}", "去掉每行首尾空白与空行"),
    ("去重行", "dd", "{{dedupe}}", "删掉重复行（保留首次出现的顺序）"),
    ("行排序", "so", "{{sort}}",
     "行排序；参数 desc 逆序 / num 按数值 / uniq 去重"),
    ("加引号列表", "qt", "{{quote}}",
     '每行变成 "a", "b"——拼 SQL IN / 代码数组用'),
    ("CSV 转表格", "tb", "{{csv_table}}",
     "逗号分隔转 Markdown 表格；参数 tab 用于制表符分隔"),
    ("JSON 美化", "jp", "{{json_pretty}}", "2 空格缩进，中文不转义"),
    ("JSON 抽字段", "jk", "{{json_pick:data.id}}",
     "把参数 data.id 换成你的路径（如 items.0.name）"),
    ("字符串转义", "es", "{{escape}}",
     "转成能粘进 JSON/代码的形式；参数 unescape 反向还原"),
    ("抽邮箱", "em", "{{extract}}", "把文本里的邮箱提取成列表"),
    ("抽网址", "lu", "{{extract:url}}", "把文本里的 http(s) 链接提取成列表"),
    ("抽数字", "nm", "{{extract:num}}", "把文本里的数字提取成列表"),
    ("抽 IP", "ip", "{{extract:ip}}", "把文本里的 IPv4 提取成列表"),
    ("天气", "wt", "{{weather}}",
     "按 IP 定位的天气；参数写城市名，如 {{weather:北京}}"),
    ("正在播放", "np", "{{now_playing}}",
     "Spotify / 音乐 App 的当前曲目（首次会请求「自动化」权限）"),
]


def _upgrade_v6_snippets_to_templates(engine: Engine) -> None:
    """v5 → v6：模板模块——snippets 表重建 + snippet_folders 新表。

    新结构（文档 §81）：shortcut UNIQUE / folder_id / enabled / favorite /
    trigger_mode / usage_count / last_used_at / updated_at。
    SQLite 无法添加 UNIQUE 约束 → RENAME→CREATE→INSERT→DROP（v5 同模式）。
    旧数据：shortcut 取 name 小写（冲突追加 _<id>），description 保留。
    """
    with engine.begin() as conn:
        # 1) snippet_folders 表 + 默认文件夹（新库由 create_all 建表，
        #    但表存在不代表默认文件夹已插入——INSERT OR IGNORE 幂等）
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS snippet_folders ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " name TEXT NOT NULL UNIQUE,"
            " created_at DATETIME NOT NULL,"
            " updated_at DATETIME NOT NULL)"))
        for name in _DEFAULT_FOLDERS:
            conn.execute(text(
                "INSERT OR IGNORE INTO snippet_folders"
                " (name, created_at, updated_at)"
                " VALUES (:n, datetime('now'), datetime('now'))"),
                {"n": name})
        # 2) snippets 已是新结构则跳过（新库由 create_all 建好）
        cols = {r[1] for r in conn.execute(
            text("PRAGMA table_info(snippets)")).fetchall()}
        if "shortcut" not in cols:
            # 3) 重建表
            conn.execute(text("ALTER TABLE snippets RENAME TO snippets_v5"))
            conn.execute(text(
                "CREATE TABLE snippets ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " name VARCHAR(128) NOT NULL,"
                " shortcut VARCHAR(128) NOT NULL UNIQUE,"
                " content TEXT NOT NULL, description TEXT,"
                " folder_id INTEGER"
                "   REFERENCES snippet_folders(id) ON DELETE SET NULL,"
                " enabled INTEGER NOT NULL DEFAULT 1,"
                " favorite INTEGER NOT NULL DEFAULT 0,"
                " trigger_mode VARCHAR(16) NOT NULL DEFAULT 'tab',"
                " usage_count INTEGER NOT NULL DEFAULT 0,"
                " last_used_at DATETIME,"
                " created_at DATETIME NOT NULL,"
                " updated_at DATETIME NOT NULL)"))
            old = conn.execute(text(
                "SELECT id, name, content, description, created_at"
                " FROM snippets_v5 ORDER BY id")).fetchall()
            used: set[str] = set()
            for row in old:
                base = (row[1] or "").strip().lower()
                sc = base if base else f"tmpl{row[0]}"
                if sc in used:
                    sc = f"{sc}_{row[0]}"
                used.add(sc)
                conn.execute(text(
                    "INSERT INTO snippets"
                    " (id, name, shortcut, content, description, folder_id,"
                    "  enabled, favorite, trigger_mode, usage_count,"
                    "  last_used_at, created_at, updated_at)"
                    " VALUES (:id, :name, :sc, :content, :desc, NULL,"
                    "  1, 0, 'tab', 0, NULL, :created, :created)"),
                    {"id": row[0], "name": row[1], "sc": sc,
                     "content": row[2], "desc": row[3], "created": row[4]})
            conn.execute(text("DROP TABLE snippets_v5"))
        # 4) 索引
        for idx in (
            "CREATE INDEX IF NOT EXISTS idx_snippets_shortcut"
            " ON snippets (shortcut)",
            "CREATE INDEX IF NOT EXISTS idx_snippets_folder"
            " ON snippets (folder_id)",
            "CREATE INDEX IF NOT EXISTS idx_snippets_last_used"
            " ON snippets (last_used_at)",
        ):
            conn.execute(text(idx))
        # 5) 默认示例模板（文档 §101）
        for name, sc, content in _DEFAULT_TEMPLATES:
            conn.execute(text(
                "INSERT OR IGNORE INTO snippets"
                " (name, shortcut, content, created_at, updated_at)"
                " VALUES (:n, :sc, :c, datetime('now'), datetime('now'))"),
                {"n": name, "sc": sc, "c": content})
    logger.info("v6 迁移：模板模块（snippets 重建 + snippet_folders + 默认模板）")


def _upgrade_v7_image_hash_normalize(engine: Engine) -> None:
    """v6 → v7：图片去重键归一化为「落盘 PNG 内容」的 sha256。

    起因（用户实测）：TIFF/其它格式来源的图片在 save 时已重编码为 PNG，
    但 DB hash 记的是**原始剪贴板字节** digest。Quick Paste 重复制该图 → 系统
    剪贴板拿到的是 PNG 字节 → 生成不同 hash → save_item 去重查询不命中 →
    产生重复条目。v7 把现存图片行的 hash 统一重算为文件内容 digest；若与
    同会话已有行冲突（即本轮已产生的重复），保留较新行（id 更大）、删除
    旧行及其 FTS 行。文件缺失的行跳过（保持原状，不入库区域不可恢复）。
    """
    import hashlib
    from pathlib import Path

    logger.info("v7 迁移：图片 hash 归一化（TIFF 来源去重修复）")
    with engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT id, session_id, file_path, hash FROM clipboard_items"
            " WHERE type = 'image'")).fetchall()
        fixed = dropped = 0
        for rid, sid, fpath, cur_hash in rows:
            try:
                digest = hashlib.sha256(Path(fpath).read_bytes()).hexdigest()
            except OSError:
                continue  # 文件缺失：无法重算，跳过
            if digest == cur_hash:
                continue
            dup = conn.execute(text(
                "SELECT id FROM clipboard_items"
                " WHERE hash = :h AND session_id = :s AND id != :rid"),
                {"h": digest, "s": sid, "rid": rid}).fetchone()
            if dup:
                # 该行是重复 → 删除（FTS5 外部内容表不支持按行 DELETE，
                # 末尾统一 rebuild 保持索引一致）
                conn.execute(text("DELETE FROM clipboard_items WHERE id = :id"),
                             {"id": rid})
                dropped += 1
            else:
                conn.execute(text(
                    "UPDATE clipboard_items SET hash = :h WHERE id = :rid"),
                    {"h": digest, "rid": rid})
                fixed += 1
        if dropped:
            conn.execute(text("INSERT INTO items_fts(items_fts) VALUES('rebuild')"))
        if fixed or dropped:
            logger.info("v7：图片 hash 修正 %d 行，清理重复 %d 行", fixed, dropped)


def _upgrade_v9_withdraw_shipped_templates(engine: Engine) -> None:
    """v8 → v9：撤回发货的变换模板（形态不成立，见 §7.4）。

    v8 曾把 17 个「内容变换」模板铺进「变换」文件夹，但它们拿不到输入：
    触发靠打字，而打字的第一个字母就把要变换的选中文本覆盖掉了。改触发方式
    也救不了（换成「抢在按键送达前读一次选中」只是让一个不合理的交互勉强
    跑通），所以整批撤掉，变换类以后按「对剪贴板条目执行」重做。

    **只删 v8 原样铺进去、之后没被动过的行**——name/shortcut/content 三项都
    与当初一致才删。用户改过任何一个字，那一行就留下：迁移的整洁不该覆盖
    用户的工作。同理，文件夹里若还有别的内容（用户自己往里加的）就保留文件
    夹，清空了才删。

    幂等：删干净后第二次跑找不到文件夹，直接返回。
    """
    removed = 0
    left = 0
    with engine.begin() as conn:
        folder_id = conn.execute(text(
            "SELECT id FROM snippet_folders WHERE name = :n"),
            {"n": WITHDRAWN_TEMPLATES_FOLDER}).scalar()
        if folder_id is None:
            return
        for name, shortcut, content, _description in _WITHDRAWN_TEMPLATES:
            result = conn.execute(text(
                "DELETE FROM snippets WHERE folder_id = :f AND shortcut = :sc"
                " AND name = :n AND content = :c"),
                {"f": folder_id, "sc": shortcut, "n": name, "c": content})
            removed += result.rowcount or 0
        left = conn.execute(text(
            "SELECT COUNT(*) FROM snippets WHERE folder_id = :f"),
            {"f": folder_id}).scalar() or 0
        if not left:
            conn.execute(text("DELETE FROM snippet_folders WHERE id = :f"),
                         {"f": folder_id})
    logger.info("v9 迁移：撤回发货变换模板（删除 %d 个，文件夹「%s」%s）",
                removed, WITHDRAWN_TEMPLATES_FOLDER,
                "一并删除" if not left else f"保留（里面还有 {left} 个模板）")
