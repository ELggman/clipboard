"""变量注册表（元数据）：内置变量的**唯一事实源**。

每个变量带 类别 / 作用 / 用法 / 例子，驱动：
- parser 的合法性校验（`_KNOWN` ← registry.names()）
- UI 胶囊悬停 tooltip（VariableTagBar）
- 「变量库」全量弹层按来源类别分组
- `{{` 自动补全候选

**值源分类**（扩展性设计，见 DEVELOPMENT.md §变量）：
每次渲染时一个变量的值只能来自一个源头——`系统状态`（OS 给的）、
`用户输入`（弹窗问）、`上下文标记`（插入位置）、`外部计算`（命令/脚本，
未实现）。`VariableMeta.value_source` 记录该分类；用户自定义变量当前
只能走「用户输入」（见 custom_default_tooltip），未来可扩展 value_source
声明外部计算值源（接口已预留，执行未实现）。
"""
from dataclasses import dataclass, field

# 来源类别（分组/筛选用；顺序即 UI 展示顺序）
CAT_SYSTEM = "系统"
CAT_INPUT = "用户输入"
CAT_CONTEXT = "上下文"
CAT_CUSTOM = "自定义"

# 值源分类（文档化；与 category 对应但独立维度）
SRC_SYSTEM = "系统状态"
SRC_INPUT = "用户输入"
SRC_CONTEXT = "上下文标记"
SRC_EXTERNAL = "外部计算"

# 用户自定义变量的**值来源**类型（provider 注册表键；顺序即 UI 下拉顺序）
SOURCE_INPUT = "input"       # 用户输入：触发时弹窗询问（去重）
SOURCE_FIXED = "fixed"       # 固定值/默认值：config.text 原样插入
SOURCE_COMMAND = "command"   # 外部命令/脚本：config.command 经 sh -c 执行
SOURCE_STATE = "state"       # 系统状态：config.state（v1 仅前台应用名）

SOURCE_LABELS: dict[str, str] = {
    SOURCE_INPUT: "用户输入",
    SOURCE_FIXED: "固定值",
    SOURCE_COMMAND: "外部命令",
    SOURCE_STATE: "系统状态",
}


@dataclass(frozen=True)
class VariableMeta:
    """一个变量的完整元数据。"""

    insert: str            # 点击/补全插入的文本，如 "{{date}}"
    category: str          # 来源类别（CAT_*）
    description: str       # 作用（悬停 tooltip 第一行）
    usage: str             # 使用方法
    example: str           # 简单例子
    keyword: str = ""      # 解析关键字（date/input/...）；自定义变量为空
    value_source: str = ""  # 值源（SRC_*）；自定义可扩展
    builtin: bool = True   # 内置（不可删）或用户自定义

    def tooltip(self) -> str:
        """胶囊悬停多行说明：作用 + 用法 + 例子。"""
        return f"{self.description}\n\n用法：{self.usage}\n示例：{self.example}"


@dataclass
class CustomVariable:
    """一个用户自定义变量（持久化在 config template.extra_variables）。

    name 不含 `{{}}`（如 "location"）；insert() 还原插入文本 `{{location}}`。
    source 是值来源类型（SOURCE_*），config 是值源专属配置：
      - input:   无配置（触发时弹窗询问）
      - fixed:   {"text": "..."}（严格固定值）
      - command: {"command": "..."}（sh -c 执行，stdout 作结果）
      - state:   {"state": "frontmost_app"}（系统状态；框架预留更多）
    """

    name: str
    description: str = ""
    source: str = SOURCE_INPUT
    config: dict = field(default_factory=dict)

    def insert(self) -> str:
        return f"{{{{{self.name}}}}}"


def custom_tooltip(var: CustomVariable) -> str:
    """自定义变量悬停多行说明：描述 + 值来源 + （按来源）配置摘要。"""
    desc = var.description or "自定义变量"
    label = SOURCE_LABELS.get(var.source, var.source)
    lines = [desc, f"值来源：{label}"]
    if var.source == SOURCE_FIXED:
        lines.append(f"固定值：{var.config.get('text', '')}")
    elif var.source == SOURCE_COMMAND:
        lines.append(f"命令：{var.config.get('command', '')}")
    elif var.source == SOURCE_STATE:
        lines.append(f"状态：{var.config.get('state', '')}")
    return "\n".join(lines)


# 内置变量（第一阶段：date/time/datetime/uuid/clipboard/selection/input/cursor）。
# 每项 description/usage/example **必填**（悬停 tooltip 依赖）。
PRESET_VARIABLES: list[VariableMeta] = [
    VariableMeta(
        insert="{{date}}", category=CAT_SYSTEM, value_source=SRC_SYSTEM,
        description="插入当前日期",
        usage="可带格式参数：{{date:YYYY-MM-DD}}（YY/MM/DD/HH/hh/mm/ss/A/a）",
        example="{{date}} → 2026-08-15",
        keyword="date"),
    VariableMeta(
        insert="{{time}}", category=CAT_SYSTEM, value_source=SRC_SYSTEM,
        description="插入当前时间",
        usage="可带格式参数：{{time:HH:mm}}",
        example="{{time}} → 14:30",
        keyword="time"),
    VariableMeta(
        insert="{{datetime}}", category=CAT_SYSTEM, value_source=SRC_SYSTEM,
        description="插入当前日期与时间",
        usage="可带格式参数：{{datetime:YYYY年MM月DD日 HH:mm}}",
        example="{{datetime}} → 2026-08-15 14:30:00",
        keyword="datetime"),
    VariableMeta(
        insert="{{uuid}}", category=CAT_SYSTEM, value_source=SRC_SYSTEM,
        description="插入一个新生成的 UUID",
        usage="每次触发生成不同的随机标识",
        example="{{uuid}} → 3f9c1a2b-...",
        keyword="uuid"),
    VariableMeta(
        insert="{{clipboard}}", category=CAT_SYSTEM, value_source=SRC_SYSTEM,
        description="插入当前剪贴板内容",
        usage="触发时读取剪贴板里复制的内容（允许为空）",
        example="剪贴板里有「你好」→ 插入「你好」",
        keyword="clipboard"),
    VariableMeta(
        insert="{{selection}}", category=CAT_SYSTEM, value_source=SRC_SYSTEM,
        description="插入触发前选中的文本",
        usage="仅 ⌘⇧S 全局触发可用——Tab/自动触发会先输入 shortcut 替换掉选中文字，恒读到空",
        example="⌘⇧S 前在目标应用选中「你好」→ 插入「你好」",
        keyword="selection"),
    VariableMeta(
        insert="{{input:name}}", category=CAT_INPUT, value_source=SRC_INPUT,
        description="触发时弹窗询问，插入你输入的内容",
        usage="{{input:标签}}，标签是提示语；同标签重复插入自动编号 name2",
        example="{{input:标题}} → 弹窗填「周报」→ 插入「周报」",
        keyword="input"),
    VariableMeta(
        insert="{{cursor}}", category=CAT_CONTEXT, value_source=SRC_CONTEXT,
        description="插入完成后光标停在此处",
        usage="每个模板最多一个；当前版本不移动光标（停在末尾）",
        example="问候{{cursor}}朋友 → 期望光标停在中间",
        keyword="cursor"),
]

_BY_INSERT = {m.insert: m for m in PRESET_VARIABLES}


def meta_for(insert: str) -> VariableMeta | None:
    """按插入文本查内置变量元数据（自定义变量返回 None）。"""
    return _BY_INSERT.get(insert)


def is_preset(insert: str) -> bool:
    """是否为内置变量（非用户自定义）。"""
    return insert in _BY_INSERT


def names() -> set[str]:
    """parser 合法性校验用的关键字集合（含新增 selection）。"""
    return {m.keyword for m in PRESET_VARIABLES if m.keyword}


def all_insert_texts() -> list[str]:
    """所有内置变量的插入文本（自动补全/常用默认值）。"""
    return [m.insert for m in PRESET_VARIABLES]


def group_by_category(
        metas: list[VariableMeta]) -> list[tuple[str, list[VariableMeta]]]:
    """按来源类别分组，保持固定顺序：系统 → 用户输入 → 上下文 → 自定义。

    「变量库」弹层按此渲染分组标题。空组不出现。
    """
    order = [CAT_SYSTEM, CAT_INPUT, CAT_CONTEXT, CAT_CUSTOM]
    buckets: dict[str, list[VariableMeta]] = {c: [] for c in order}
    for m in metas:
        buckets.setdefault(m.category, []).append(m)
    return [(c, buckets[c]) for c in order if buckets[c]]


def custom_default_tooltip() -> str:
    """用户自定义变量的默认 tooltip（当前值源只能「用户输入」）。"""
    return "自定义变量：触发时弹窗询问值"


def next_input_insert(content: str, base: str) -> str:
    """内容已含 `{{input:base}}` 时返回 `{{input:base2}}`…（重复 input 自动编号）。

    点击胶囊/自动补全插入 input 变量时调用：同一标签在模板里出现多次，
    每次都是独立输入（base → base2 → base3…），避免去重只问一次
    （用户决策：都是输名字，应各问一遍）。
    """
    text = f"{{{{input:{base}}}}}"
    if text not in content:
        return text
    i = 2
    while f"{{{{input:{base}{i}}}}}" in content:
        i += 1
    return f"{{{{input:{base}{i}}}}}"


def filter_candidates(prefix: str, custom: list[str] | None = None,
                      favorites: list[str] | None = None) -> list[str]:
    """变量候选（`{{` 自动补全用）：内置 + 自定义，按前缀过滤。

    prefix：`{{` 后已输入的前缀；空字符串匹配全部。返回排序后的插入文本：
    常用（favorites，默认 = 全部预设）在前、其余按来源类别。stale
    favorites（已删除变量）自动忽略。
    """
    custom = custom or []
    metas = list(PRESET_VARIABLES) + [
        VariableMeta(insert=c, category=CAT_CUSTOM, description="",
                     usage="", example="", builtin=False)
        for c in custom if c not in _BY_INSERT
    ]
    q = "{{" + prefix
    matched = [m for m in metas if m.insert.startswith(q)]
    matched_inserts = {m.insert for m in matched}
    favs = list(favorites) if favorites else all_insert_texts()
    fav_set = set(favs)
    # 常用在前（按 favorites 顺序），其余按来源类别（系统→用户输入→…）
    head = [f for f in favs if f in matched_inserts]
    rest: list[str] = []
    for _cat, group in group_by_category(matched):
        for m in group:
            if m.insert not in fav_set and m.insert not in rest:
                rest.append(m.insert)
    return head + rest
