"""Shortcut 匹配器（**英文**缓冲引擎）：输入缓冲 → shortcut 触发（文档 §7/§84）。

⚠️ 本模块只处理**英文（ASCII）shortcut 的键盘缓冲触发**。中文 shortcut
触发完全独立在 ax_matcher.py（AxShortcutMatcher，AX 文本匹配）——中英
彻底分离（用户决策）：英文走按键缓冲不依赖 AX；中文走焦点文本匹配。
改中文触发逻辑不要动这里，改这里也不影响中文。

主线程维护输入缓冲（滑动窗口），按 trigger_mode 响应：
- tab 模式：缓冲末尾完整词 + Tab 键触发
- automatic（含旧 boundary）模式：输完最后一个字符立即自动触发——
  但**中文输入法下不按键触发**（组合未上屏，碰文本会破坏组合，
  实测 sig→siv），改为**提交键**（空格/回车/标点，输入法正在提交组合）
  keyDown 时触发；Tab 触发在中文输入法下由插入层 Escape 取消组合

用户要求：无论哪种输入法，必须完整 shortcut 彻底输入文本框后才触发。
匹配从缓冲末尾向前扫描最长后缀（如输入 "abpyfunc"+Tab 命中 pyfunc），
匹配后清缓冲。Backspace 回退。连续输入超长时丢弃最旧字符。
"""
import logging

logger = logging.getLogger(__name__)

_WINDOW = 64
# Backspace（macOS delete 键经 UnicodeString 多为 \x7f 或 \x08）
_BACKSPACES = ("\x7f", "\x08", "\b")


class ShortcutMatcher:
    """英文（ASCII）shortcut 缓冲匹配器。中文 shortcut 见 AxShortcutMatcher。"""

    def __init__(self, template_service, on_trigger=None, composing_check=None,
                 chinese_ime_check=None):
        """on_trigger(template, delete_count, cancel_ime)：匹配命中后的回调。

        composing_check：() -> bool，True = 焦点输入框输入法组合中
        （AX marked range，仅对 AX 健全的应用有效——VS Code 等不可用）。
        chinese_ime_check：() -> bool，True = 当前输入法是中文（TIS 检测，
        不依赖被聚焦应用，全 App 有效）。**中文输入法下所有字母输入都进
        组合**，这是主要的组合守卫来源。

        触发时机（用户要求：无论哪种输入法，必须完整 shortcut 彻底输入
        文本框后才触发）：
        - 英文输入法：输完最后一个字符立即触发（无组合，按键即上屏）
        - 中文输入法：按键路径不触发（组合未上屏，碰文本会破坏组合，
          实测 sig 被改写为 siv）；**提交键**（空格/回车/标点，输入法
          此时正在提交组合）keyDown 时触发——事件顺序保证 ⌥⌫ 落在已
          提交的文本上；Tab 触发用 cancel_ime=True（Escape 取消组合）
        - cancel_ime=True：插入层发送 Escape 取消组合而非 ⌥⌫ 删除

        中文输入法下的这些分支是为了**安全触发英文 shortcut**（何时触发），
        不含任何中文 shortcut 匹配逻辑（匹配的是缓冲里的英文字母）。
        """
        self._service = template_service
        self._on_trigger = on_trigger
        self._composing_check = composing_check
        self._chinese_ime_check = chinese_ime_check
        self._buffer: list[str] = []
        # 自动触发延迟确认：英文输入法下输完 shortcut 不立即触发——挂起
        # (template, delete_count, 缓冲快照)，200ms 内缓冲变化（还在输更长
        # 的词，如 signature 的 sig）则取消；词边界键（空格/标点）或超时
        # 确认触发。防 prefix 误触（用户实测：想打 signature，输到 sig 就
        # 被替换，后面的字打不了）。
        self._pending: tuple | None = None

    def feed(self, char: str) -> bool:
        """输入一个字符。返回 True = 命中并触发（缓冲已清）。

        触发方式（用户明确期望）：
        - **automatic**（含旧 boundary 数据）：输完 shortcut 的最后一个
          字符**立即自动展开**，不需要额外按键（§7.3 Automatic）——
          要求 shortcut 前是词边界（空格/行首），防 design 中间误触发 sig
        - **tab**：Tab 键触发

        回调签名 on_trigger(template, delete_count, cancel_ime)：delete_count
        是需要从输入框中**删除的字符数**（用户输入的 shortcut 文本，
        触发后要移除，见 §5.1 示例 shrug<Tab> → ¯\\_(ツ)_/¯）；
        cancel_ime=True 时插入层发 Escape 取消组合而非 ⌥⌫（中文输入法
        Tab 触发）。
        """
        if char == "\t":
            self._pending = None  # Tab 覆盖挂起的自动触发
            return self._try_match(via_tab=True, clear_on_miss=True)
        if char in _BACKSPACES:
            if self._buffer:
                self._buffer.pop()
            return False
        if char.isalnum() or char in ("_", "-"):
            self._buffer.append(char)
            if len(self._buffer) > _WINDOW:
                self._buffer.pop(0)
            # 英文输入法：输完最后一个字符即匹配，但**延迟确认**（挂起
            # pending，200ms 内缓冲未变/词边界确认才触发——防 prefix
            # 误触：signature 的 sig 不触发）。**无匹配时不清缓冲**。
            # 中文输入法/组合中：不匹配——字符尚未真正上屏，删除/粘贴会
            # 破坏组合（实测 sig 被改写为 siv）。等提交键触发。
            if self._auto_match_pending():
                if self._is_chinese_ime() or self._is_composing():
                    return False
                if self._try_match(via_tab=False, clear_on_miss=False,
                                   defer=True):
                    return True
        else:
            # 非词字符（空格/回车/标点）：
            # - 英文输入法：词边界 = 词已完整 → **确认挂起的自动触发**
            #   （"sig"+空格 立即触发）；无挂起 → 清空缓冲
            # - 中文输入法：**提交键**——输入法正在提交组合（事件顺序：
            #   提交键先到输入法，⌥⌫ 后到，落在已提交文本上，安全）。
            #   缓冲末尾命中自动 shortcut → 触发
            if self.confirm_pending():
                return True
            if self._is_chinese_ime():
                if self._try_match(via_tab=False, clear_on_miss=False):
                    return True
            self._buffer.clear()
        return False

    def reset(self) -> None:
        self._buffer.clear()
        self._pending = None

    # ---- 自动触发延迟确认 ----

    def buffer_text(self) -> str:
        """当前缓冲文本（延迟确认快照比对用）。"""
        return "".join(self._buffer)

    def has_pending(self) -> bool:
        """是否有**有效**挂起的自动触发（缓冲未变，等待确认）。

        缓冲已变化（用户继续输入更长的词）→ 不算有效挂起（bootstrap 据此
        决定是否重启确认定时器；确认时仍会二次校验快照）。
        """
        if self._pending is None:
            return False
        return self.buffer_text() == self._pending[2]

    def confirm_pending(self) -> bool:
        """确认挂起的自动触发：缓冲未变（词已完整）→ 触发；否则取消。

        返回 True = 已触发。由词边界键（feed 内）或 200ms 定时器（bootstrap）
        调用。缓冲变化（用户继续输入了更长的词）→ 取消不触发。
        """
        if self._pending is None:
            return False
        template, delete_count, snapshot = self._pending
        self._pending = None
        if self.buffer_text() != snapshot:
            return False  # 缓冲已变：正在输更长的词，取消
        if self._on_trigger is not None:
            self._on_trigger(template, delete_count, False)
        return True

    # ---- 输入法组合守卫 ----

    def _is_chinese_ime(self) -> bool:
        """当前输入法是否中文（TIS，不依赖被聚焦应用）。失败按英文处理。"""
        if self._chinese_ime_check is None:
            return False
        try:
            return bool(self._chinese_ime_check())
        except Exception:
            return False

    def _is_composing(self) -> bool:
        """焦点输入框是否输入法组合中（未上屏）。无守卫配置时按非组合处理。"""
        if self._composing_check is None:
            return False
        try:
            return bool(self._composing_check())
        except Exception:
            return False

    def _auto_match_pending(self) -> bool:
        """缓冲末尾是否可能命中 automatic/boundary shortcut（廉价预检）。

        只扫描后缀（_try_match 的候选 = 缓冲任意后缀），避免每键都做 AX
        调用。无 automatic/boundary 候选时无需检测组合状态。
        """
        text = "".join(self._buffer).lower()  # 匹配大小写不敏感（find_by_shortcut）
        for item in self._service.list_shortcuts():
            if item["trigger_mode"] not in ("automatic", "boundary"):
                continue
            if item["shortcut"] and text.endswith(item["shortcut"].lower()):
                return True
        return False

    # ---- 内部 ----

    def _try_match(self, via_tab: bool, clear_on_miss: bool = True,
                   defer: bool = False) -> bool:
        """从缓冲末尾向前扫描最长 shortcut 后缀（§7 Tab Trigger 语义）。

        触发方式匹配（用户明确期望）：
        - Tab 键 → 仅匹配 tab 模式模板
        - 自动触发（输完即展开）→ 仅匹配 automatic/boundary 模式模板，
          且要求 shortcut 前是词边界（防误触：design 中间的 sig 不触发）；
          defer=True（英文输入法按键路径）→ 命中后**挂起延迟确认**
          （pending，防 prefix 误触：signature 的 sig），不立即触发
        命中触发（回调携带需删除的字符数 = 缓冲中匹配部分长度）；
        命中但模式不匹配 → 清缓冲不触发。
        """
        for start in range(len(self._buffer)):
            candidate = "".join(self._buffer[start:])
            template = self._service.find_by_shortcut(candidate)
            if template is None:
                continue
            delete_count = len(self._buffer) - start  # 先算（清缓冲前）
            mode = template["trigger_mode"]
            if via_tab:
                if mode != "tab":
                    self._buffer.clear()
                    logger.info("触发匹配: %s 是 %s 模式，Tab 不触发",
                                candidate, mode)
                    return False
            else:
                # 自动触发：仅 automatic/boundary（旧数据兼容）
                if mode not in ("automatic", "boundary"):
                    # tab 模式模板：自动触发不处理，但**保留缓冲**
                    # （用户可能随后按 Tab——清空会让 Tab 匹配失败，实测）
                    return False
                # 词边界检查：shortcut 前必须是词边界（空格/行首/标点）
                if start > 0:
                    prev = self._buffer[start - 1]
                    if prev.isalnum() or prev in ("_", "-"):
                        continue  # 前一个字符是词字符 → 不是独立词，不触发
            if defer:
                # 英文输入法自动触发：挂起延迟确认（缓冲保留）——
                # 词边界键/200ms 超时确认后触发；缓冲变化（继续输更长
                # 的词）取消。防 prefix 误触：signature 的 sig 不触发
                self._pending = (template, delete_count, self.buffer_text())
                return False
            self._buffer.clear()
            if self._on_trigger is not None:
                # 中文输入法 Tab 触发：shortcut 还在组合里未上屏 → 插入层
                # 发送 Escape 取消组合（字母消失，直接粘贴）；其余路径
                # （提交键触发）⌥⌫ 删除已上屏文本即可
                cancel_ime = via_tab and self._is_chinese_ime()
                self._on_trigger(template, delete_count, cancel_ime)
            return True
        if clear_on_miss:
            self._buffer.clear()
        return False
