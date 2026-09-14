"""敏感信息检测器：本地正则识别潜在机密（新增.md §9.11-9.16）。

纯函数模块（零 Qt/DB 依赖）。三策略由调用方（bootstrap 隐私管线）执行：
- warn            → 保存但置 sensitive 标记，UI 遮蔽预览
- ignore          → 不保存
- save_temporarily → 保存并设置 expires_at

日志与日志无关：本模块不产生任何日志输出剪贴板内容。
"""
import re
from dataclasses import dataclass

# 敏感类型
API_KEY = "api_key"
TOKEN = "token"
JWT = "jwt"
PRIVATE_KEY = "private_key"
PASSWORD = "password"
BANK_CARD = "bank_card"
ID_CARD = "id_card"
MANUAL = "manual"      # 用户右键手动标记（无固定模式，整段遮蔽）

# 极高危类型（§9.15）：私钥一旦落库就再也收不回来——拿到即可冒充身份，
# 且不像口令那样能改。默认策略（warn）下这类内容自动升级为「不保存」，
# 用户可在设置页关掉（privacy.block_private_key）。
STRICT_TYPES = frozenset({PRIVATE_KEY})

# 值最小长度门槛已在各正则中体现（3/10/16/20 字符不等），避免短变量名误报

# 键名前的左边界：**不能**用 `\b`——`_` 与字母同属 \w，`DB_PASSWORD=` 里 `P` 前
# 没有词边界，于是 .env 的命名习惯（MYSQL_PASSWORD / MY_API_KEY /
# MY_ACCESS_TOKEN）整类漏检；汉字同理（Python 的 \w 含 CJK，`我的password=`
# 也判不出）。改成「前一个字符不是字母数字」：放行 `_`/`-`/汉字/行首，
# 仍然挡住词中命中（`tokenizer=`、`myapikey=` 这类）。
_KEY_BOUNDARY = r"(?<![A-Za-z0-9])"

# 厂商专属令牌前缀：前缀本身就是格式约定，后面跟一长串随机字符基本只有真令牌
# 一种可能，故**无需键名**也判定（从 .env 里剪一段裸拷出来同样认）。
# 故意不收录裸 `sk-`：太泛，`sk-2024-annual-report-final-v3` 这类文件名会误报；
# 用带厂商段的 `sk-proj-` / `sk_live_` 代替。
_VENDOR_TOKEN_PREFIX = (
    r"(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|"   # GitHub / GitLab
    r"xoxb-|xoxp-|xoxa-|xoxr-|xoxs-|"                    # Slack
    r"sk_live_|sk_test_|sk-proj-|"                       # Stripe / OpenAI
    r"AKIA|ASIA|AIza)")                                  # AWS / Google

_PATTERNS: list[tuple[str, re.Pattern]] = [
    # API Key：api_key=/apikey=/api-key=/OPENAI_API_KEY=（sk- 前缀或任意长值）。
    # 键名允许带前缀（MY_API_KEY=）；补上 secret_access_key——它才是真正的密钥，
    # 原先只列了 aws_access_key_id（那只是密钥标识，泄露危害小得多）→ 正好反了。
    # 值里放行 `/`：AWS secret 是 40 位 base64（`wJalrX.../K7MDENG/bPxRfiCY`），
    # 不含 `/` 的话这一类根本匹配不到。仍然排除 `:`，故 `api_key=https://…`
    # （值其实是个 URL）不会误报。
    (API_KEY, re.compile(
        _KEY_BOUNDARY +
        r"(?:api[_-]?key|apikey|openai_api_key|anthropic_api_key|"
        r"github_token|secret[_-]?access[_-]?key|aws_access_key_id|"
        r"stripe_secret_key)"
        r"\s*[=:]\s*['\"]?(?:sk-[A-Za-z0-9_\-]{10,}|[A-Za-z0-9_\-+/]{20,})['\"]?",
        re.IGNORECASE)),
    # 裸厂商令牌（无键名）：ghp_xxx / glpat-xxx / AKIAxxx。
    # **大小写敏感**（本式未加 IGNORECASE）：AKIA/ASIA 若忽略大小写，
    # `asiaregion-sales-2024` 这类普通词就会误报。
    (TOKEN, re.compile(
        _KEY_BOUNDARY + _VENDOR_TOKEN_PREFIX + r"[A-Za-z0-9_\-]{16,}")),
    # Token：token=/access_token=/refresh_token=/bearer <值>（§9.13 含裸 token=）
    (TOKEN, re.compile(
        _KEY_BOUNDARY + r"(?:"
        r"(?:access[_-]?token|refresh[_-]?token|auth[_-]?token|"
        r"id[_-]?token|token|bearer)"
        r"\s*[=:]\s*['\"]?[A-Za-z0-9._\-+/=]{20,}['\"]?"
        # `Authorization: Bearer <值>` 是**空格**分隔，不是「键=值」结构：上面
        # 那条分支在 bearer 后面强制要 [=:]，而这里跟的是空格 → 永远落到这条。
        # 原先只写了上面那条 → 这种最最常见的形态一直没被判定。
        r"|bearer\s+['\"]?[A-Za-z0-9._\-+/=]{20,}"
        r")",
        re.IGNORECASE)),
    # JWT：eyJ 开头三段 base64url
    (JWT, re.compile(
        _KEY_BOUNDARY + r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
    # Private Key：PEM 块（跨行）
    (PRIVATE_KEY, re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{20,}?"
        r"-----END [A-Z ]*PRIVATE KEY-----")),
    # Password：password=/passwd=/pwd=（带引号或不带引号，值至少 3 字符，§9.16）
    (PASSWORD, re.compile(
        _KEY_BOUNDARY +
        r"(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\"#;,]{3,}['\"]?",
        re.IGNORECASE)),
]

# 纯数字类证件（§9.1 银行卡 / 个人信息）：候选正则 + 校验位，两步才判定。
# 没有校验的话「16 位纯数字」会命中订单号、时间戳、编译产物里的常量。
_ID_CARD_RE = re.compile(r"(?<!\d)(\d{17}[\dXx]|\d{15})(?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")

# 身份证校验位（GB 11643-1999）：前 17 位加权和 % 11 → 查表
_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECK_CHARS = "10X98765432"

# mask 时保留的前缀长度（API key 如 sk-xxxx 保留 sk-）
_KEEP_PREFIX = 4

# mask 用的键名表：与 _PATTERNS 里的检测键名保持一致。漏一个的后果不是「不遮蔽」
# ——detect 判定敏感、mask 却匹配不到值时会落到兜底分支（只留前 4 字符 + 圆点），
# 仍然是遮蔽，只是预览丢了上下文。新增检测键名时记得同步这里。
_MASK_KEY_NAMES = (
    r"(?:api[_-]?key|apikey|openai_api_key|anthropic_api_key|github_token|"
    r"secret[_-]?access[_-]?key|aws_access_key_id|stripe_secret_key|"
    r"access[_-]?token|refresh[_-]?token|auth[_-]?token|id[_-]?token|token|"
    r"bearer|password|passwd|pwd)")

# 「键=值」：group(1) 是键名与赋值符号（保留），group(2) 是值（遮蔽）
_MASK_KV_RE = re.compile(
    _KEY_BOUNDARY + r"(" + _MASK_KEY_NAMES + r"\s*[=:]\s*['\"]?)([^\s'\"#;,]+)",
    re.IGNORECASE)

# Bearer 的**空格**分隔形态：group(1) 含 "Bearer " 与前导边界（保留），
# group(2) 是令牌本身（遮蔽）
_MASK_BEARER_RE = re.compile(
    _KEY_BOUNDARY + r"(bearer\s+(?!\s*[=:]))(\S+)", re.IGNORECASE)


@dataclass
class SensitiveResult:
    sensitive_type: str     # api_key / token / jwt / private_key / password / ...
    confidence: float       # 命中即 1.0（正则确定性匹配）


def _luhn_ok(digits: str) -> bool:
    """Luhn 校验（银行卡/信用卡）：13-19 位随机数字的误报降到约 1/10。"""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def _valid_birth_date(text: str) -> bool:
    """出生日期是否像合法日期：YYYYMMDD（18 位）或 YYMMDD（15 位旧式）。

    15 位旧式身份证没有校验位，只能靠它兜住误报；18 位在校验位之外再验一次，
    把「凑巧校验通过的随机 18 位数」也筛掉。
    """
    if len(text) == 8:
        year, month, day = int(text[:4]), int(text[4:6]), int(text[6:8])
        return 1900 <= year <= 2100 and 1 <= month <= 12 and 1 <= day <= 31
    if len(text) == 6:
        month, day = int(text[2:4]), int(text[4:6])
        return 1 <= month <= 12 and 1 <= day <= 31
    return False


def _id_card_ok(candidate: str) -> bool:
    """身份证校验：18 位验校验位 + 出生日期；15 位旧式只验出生日期。

    不验的话「18 位纯数字」这种最常见的编号形态会全被标成敏感。
    注意两种长度的日期字段偏移不同：18 位是 6..13 的 YYYYMMDD，
    15 位是 6..11 的 YYMMDD。
    """
    if len(candidate) == 18:
        total = sum(int(c) * w for c, w in zip(candidate[:17], _ID_WEIGHTS))
        if _ID_CHECK_CHARS[total % 11] != candidate[17].upper():
            return False
        return _valid_birth_date(candidate[6:14])
    return _valid_birth_date(candidate[6:12])


def _bank_card_ok(candidate: str) -> bool:
    """银行卡号：13-19 位 + Luhn 通过 + 首位落在支付卡号段（2-6）。

    首位限制来自 ISO/IEC 7812 的 MII：1/7/8/9 分别是航空、石油、电信、
    国家专用号段，个人支付卡只在 2-6（Visa 4、MasterCard 2/5、Amex 3、
    Discover/UnionPay 6）。只靠 Luhn 的话随机 16 位数字有 1/10 会通过——
    订单号、流水号会被成片误标；加上首位限制后降到约 1/25。
    """
    digits = re.sub(r"[^0-9]", "", candidate)
    if not 13 <= len(digits) <= 19 or digits[0] not in "23456":
        return False
    return _luhn_ok(digits)


def _search_validated(pattern: re.Pattern, content: str, validator) -> bool:
    """候选正则 + 校验函数：任一处候选通过校验即算命中。"""
    return any(validator(m.group(0)) for m in pattern.finditer(content))


def detect(content: str) -> SensitiveResult | None:
    """检测内容是否含潜在机密。返回首个命中的类型或 None。

    URL 一律跳过：微信分享链接等携带 token=/key= 查询参数是常态
    （mp.weixin.qq.com/s?...&token=xxx），误判噪声远大于收益
    （实测踩坑：微信复制的 URL 被标为敏感）。

    顺序有意义：证件号放在凭据之后、且身份证先于银行卡——18 位身份证也能
    凑出「19 位以内的数字串」，靠校验位区分，先判身份证才不会认错类型。
    """
    if not content or not content.strip():
        return None
    stripped = content.lstrip()
    if stripped.startswith(("http://", "https://")):
        return None
    for sensitive_type, pattern in _PATTERNS:
        if pattern.search(content):
            return SensitiveResult(sensitive_type, 1.0)
    if _search_validated(_ID_CARD_RE, content, _id_card_ok):
        return SensitiveResult(ID_CARD, 1.0)
    if _search_validated(_BANK_CARD_RE, content, _bank_card_ok):
        return SensitiveResult(BANK_CARD, 1.0)
    return None


def mask(content: str, sensitive_type: str = "") -> str:
    """遮蔽展示：保留键名/句式与其余文本，只把机密部分替换为 ••••（§9.19）。

    warn 策略下数据库保存原文，遮蔽发生在显示层；
    本函数只作用于 UI 展示字符串。多行文本里每一处机密都会遮蔽，其余内容原样保留。
    """
    if sensitive_type == PRIVATE_KEY:
        return "[PRIVATE KEY HIDDEN]"
    if sensitive_type == JWT:
        return content[:_KEEP_PREFIX + 2] + "••••••••"
    if sensitive_type in (MANUAL, BANK_CARD, ID_CARD):
        # 整串都是机密本身，没有「键=值」结构可留——留前 4 位等于泄露卡号/证件号段
        return "••••••••"
    # api_key / token / password：遮蔽赋值符号后的值。
    #
    # **逐处**替换、保留其余文本：多行 .env（DB_HOST=… / DB_PASSWORD=…）只处理
    # 第一处的话，后面的密钥要么被整段丢弃（预览没了上下文）、要么原样留在屏幕上。
    #
    # Bearer 是**空格**分隔（`Authorization: Bearer <值>`），不走「键=值」结构：
    # 硬套的话只会遮蔽到 "Bearer" 这个词，真令牌照旧显示（等于泄露）。
    # `(?!\s*[=:])` 把 `bearer = 值` 排除在外——那里 `\S+` 只会咬到 `=`，同样
    # 会泄露；那种形态交给下面的键值式处理。
    out = _MASK_BEARER_RE.sub(r"\1••••••••", content)
    out = _MASK_KV_RE.sub(lambda m: m.group(1) + "••••••••", out)
    if out != content:
        return out
    # 兜底（内容里没有「键=值」结构，如裸厂商令牌 ghp_xxx）：只留前 4 个字符。
    # 宁可多遮蔽不可少遮蔽，故不留原文任何尾部。
    return content[:_KEEP_PREFIX] + "••••••••"
