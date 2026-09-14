"""忽略应用的条目格式与匹配（§9.5 应用排除）。

**为什么不能只按名字匹配**：忽略列表原本拿 `localizedName()` 做精确字符串比较。
`localizedName()` 随**系统语言**变——中文系统下微信返回「微信」，英文系统返回
"WeChat"，用户当年存下的那个名字此后就再也匹配不上，被排除的应用会悄悄开始
被记录（隐私模式最不能出的错：静默失效）。反过来，两个不同应用重名时会一起被
误排除。故条目现在同时记 `bundle_id`（不随语言变、不随重名混），**名称或
bundle id 任一命中即算排除**；纯字符串的旧条目继续按名称匹配，配置无需迁移。

（VS Code 是另一个方向的坑：它的 `localizedName()` 就是 "Code"，用户按直觉搜
"Visual Studio Code" 搜不到、列表里也认不出——那是搜索与显示问题，见
`ui/app_picker_dialog.py`。）
"""
from typing import Any


def normalize(text: str) -> str:
    """比较用归一化：去首尾空白 + 大小写折叠。

    macOS 的应用名大小写不敏感（"Code" / "code" 是同一个应用），用户手改配置时
    也难免多打个空格，故匹配前统一归一化。
    """
    return (text or "").strip().casefold()


def normalize_entries(raw: Any) -> list[dict[str, str]]:
    """配置里的 `ignored_apps` → `[{"name": …, "bundle_id": …}]`。

    兼容三种历史形态：纯字符串（旧格式）、含 name/bundle_id 的映射、
    以及 YAML 反序列化出的其它标量。空条目直接丢弃。
    """
    entries: list[dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            bundle_id = str(item.get("bundle_id") or "")
        else:
            name, bundle_id = str(item or ""), ""
        if name or bundle_id:
            entries.append({"name": name, "bundle_id": bundle_id})
    return entries


def entry_key(entry: dict[str, str]) -> str:
    """条目的稳定标识（去重/判同在列表里是否有用）：优先 bundle id。"""
    return normalize(entry.get("bundle_id") or entry.get("name") or "")


def display_name(entry: dict[str, str]) -> str:
    """列表里给用户看的名字（拿不到名字时退化成 bundle id）。"""
    return entry.get("name") or entry.get("bundle_id") or ""


def matches(raw: Any, app_name: str, bundle_id: str = "") -> bool:
    """来源应用是否命中忽略列表（名称或 bundle id 任一相等）。

    两侧都无法识别（名字与 bundle id 都空，如前台应用获取失败）时返回 False：
    宁可保存也不误判——漏保存是静默丢数据，多保存用户看得见还能删。
    """
    keys = {normalize(app_name), normalize(bundle_id)} - {""}
    if not keys:
        return False
    for entry in normalize_entries(raw):
        if normalize(entry["name"]) in keys or normalize(entry["bundle_id"]) in keys:
            return True
    return False
