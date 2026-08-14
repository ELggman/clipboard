"""中文 shortcut 触发引擎（AX 文本末尾匹配，独立于英文缓冲引擎）。

中英彻底分离（用户决策）：英文触发完全走键盘缓冲（ShortcutMatcher，
matcher.py），不依赖 AX；中文触发走本模块——输入法**上屏的汉字不产生
按键事件**（CGEventTap 只能看到拼音），只能从焦点文本框末尾读文本匹配
（AX）。本模块**零英文逻辑**：只匹配非 ASCII（中文）shortcut。

匹配语义：
- 文本末尾命中非 ASCII shortcut 即触发（中文词即完整词，无需词边界检查）
- mode="tab"：仅 tab 模式模板（Tab 触发路径）
- mode="automatic"：仅 automatic/boundary 模式（焦点文本轮询路径）
命中触发（delete_count = 匹配的 shortcut 字符数；⌥⌫ 删整词，见 insertion）。

前置依赖：焦点文本框的 AX 树可用（Electron 应用默认无，需
ax_text.ensure_ax_enabled 强制开启）。
"""
import logging

logger = logging.getLogger(__name__)


class AxShortcutMatcher:
    """AX 文本末尾匹配器：默认只匹配中文（非 ASCII）shortcut。

    include_ascii=True 时也匹配英文——仅用于 Tab 兜底（中文输入法提交键
    清缓冲后，从已上屏文本末尾匹配英文 tab shortcut），主路径英文仍由
    缓冲引擎（matcher.py）负责。

    无内部缓冲——文本由调用方从 AX 读取（read_focused_text）。触发后由
    bootstrap 负责清空英文缓冲（防拼音残留后续误匹配），本类不感知。
    """

    def __init__(self, template_service, on_trigger=None):
        """on_trigger(template, delete_count, cancel_ime)：命中后的回调。

        cancel_ime 恒为 False：中文 shortcut 已上屏（完整输入文本框后才
        触发），⌥⌫ 删除即可，无需 Escape 取消组合。
        """
        self._service = template_service
        self._on_trigger = on_trigger

    def match_text(self, text: str, mode: str = "tab",
                   include_ascii: bool = False) -> bool:
        """从文本末尾匹配 shortcut。命中触发，返回 True。

        默认（include_ascii=False）**只匹配中文**：英文 shortcut 由缓冲引擎
        ShortcutMatcher.feed 处理，防止中文路径与英文路径抢同一文本
        （独立性契约）。

        include_ascii=True 是 **Tab 兜底**：中文输入法下输入英文 shortcut
        必须先按提交键（回车/空格）上屏，提交键清掉英文缓冲（tab 模式不
        自动触发），随后 Tab 时缓冲为空，只能从**已上屏的焦点文本末尾**
        匹配英文 tab shortcut（bootstrap._on_raw_key 调用）。命中时
        cancel_ime 恒 False——文本已上屏，⌥⌫ 删除即可。

        尾随空白（换行等）先剥离再匹配：编辑器块文本常带段落尾随换行
        （实测 Typora focused value = '问候\\n\\n'），不剥离则 endswith
        永远匹配不上。尾随换行是块模型伪影，非用户内容，剥离不影响匹配
        语义（shortcut 是最后一个词，其后再无有意义字符）。
        """
        if not text:
            return False
        text = text.rstrip()
        if not text:
            return False  # 全空白文本无可匹配
        for item in self._service.list_shortcuts():
            sc = item["shortcut"]
            # 默认只匹配非 ASCII（中文）；include_ascii=True 时英文也匹配
            # （Tab 兜底，见 docstring）
            if sc.isascii() and not include_ascii:
                continue
            trigger_mode = item["trigger_mode"]
            if mode == "tab" and trigger_mode != "tab":
                continue
            if mode == "automatic" and trigger_mode not in (
                    "automatic", "boundary"):
                continue
            if not text.endswith(sc):
                continue
            template = self._service.find_by_shortcut(sc)
            if template is None:
                continue
            if self._on_trigger is not None:
                self._on_trigger(template, len(sc), False)
            return True
        return False


def is_delete_reveal(prev: str | None, new: str) -> bool:
    """new 是否为「删除尾部」从 prev 演变而来（露出 shortcut 的纯删除）。

    中文 automatic 触发走轮询观察文本状态，**只看状态变化会误判**：
    删除把文本变成以 shortcut 结尾（「问候你」删「你」→「问候」）会误
    触发。英文缓冲引擎无此问题（删除键只是弹缓冲，不匹配），轮询必须
    显式区分。

    判定只挡**尾部删除**：new（rstrip 后）是 prev（rstrip 后）的严格
    前缀 = 新文本只是删掉了旧文本的尾部 → 不触发。其余一律放行匹配
    尝试（是否命中由末尾匹配决定）：
    - 追加输入（新文本是旧文本的扩展）
    - **拼音 → 上屏的替换**：VS Code 读不到 marked range，组合守卫
      失效，轮询会读到拼音中间态（'wen h'）→ 上屏「问候」是替换不是
      追加——若按追加判定会误判为非输入导致无法触发（实测回归）。
      替换不是尾部删除，应放行。
    - 改写（中段插入/替换）

    prev=None（应用启动后首次观测到既有文本）→ 非删除，返回 False；
    调用方自行决定是否触发（首次观测不应因既有文本触发）。

    两侧先 rstrip() 尾部空白再比较（与 match_text 同处理）：编辑器块
    文本带段落尾随换行伪影（Typora value='问候\\n\\n'）。
    """
    if prev is None:
        return False
    prev = prev.rstrip()
    new = new.rstrip()
    if not new:
        return False  # 全空白：无可匹配内容
    return prev.startswith(new) and len(new) < len(prev)
