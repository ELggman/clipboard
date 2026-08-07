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

# 值最小长度门槛已在各正则中体现（≥8/≥20 字符），避免短变量名误报

_PATTERNS: list[tuple[str, re.Pattern]] = [
    # API Key：api_key=/apikey=/api-key=/OPENAI_API_KEY=（sk- 前缀或任意长值）
    (API_KEY, re.compile(
        r"\b(?:api[_-]?key|apikey|openai_api_key|anthropic_api_key|"
        r"github_token|aws_access_key_id|stripe_secret_key)"
        r"\s*[=:]\s*['\"]?(?:sk-[A-Za-z0-9_\-]{10,}|[A-Za-z0-9_\-]{20,})['\"]?",
        re.IGNORECASE)),
    # Token：token=/access_token=/refresh_token=/bearer（§9.13 含裸 token=）
    (TOKEN, re.compile(
        r"\b(?:access[_-]?token|refresh[_-]?token|auth[_-]?token|"
        r"id[_-]?token|token|bearer\s+)\s*"
        r"[=:]\s*['\"]?[A-Za-z0-9._\-+/=]{20,}['\"]?",
        re.IGNORECASE)),
    # JWT：eyJ 开头三段 base64url
    (JWT, re.compile(
        r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")),
    # Private Key：PEM 块（跨行）
    (PRIVATE_KEY, re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{20,}?"
        r"-----END [A-Z ]*PRIVATE KEY-----")),
    # Password：password=/passwd=/pwd=（带引号或不带引号，值至少 3 字符，§9.16）
    (PASSWORD, re.compile(
        r"\b(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\"#;,]{3,}['\"]?",
        re.IGNORECASE)),
]

# mask 时保留的前缀长度（API key 如 sk-xxxx 保留 sk-）
_KEEP_PREFIX = 4


@dataclass
class SensitiveResult:
    sensitive_type: str     # api_key / token / jwt / private_key / password
    confidence: float       # 命中即 1.0（正则确定性匹配）


def detect(content: str) -> SensitiveResult | None:
    """检测内容是否含潜在机密。返回首个命中的类型或 None。"""
    if not content or not content.strip():
        return None
    for sensitive_type, pattern in _PATTERNS:
        if pattern.search(content):
            return SensitiveResult(sensitive_type, 1.0)
    return None


def mask(content: str, sensitive_type: str = "") -> str:
    """遮蔽展示：仅保留赋值键与值的前缀，机密部分替换为 ••••（§9.19）。

    warn 策略下数据库保存原文，遮蔽发生在显示层；
    本函数只作用于 UI 展示字符串。
    """
    if sensitive_type == PRIVATE_KEY:
        return "[PRIVATE KEY HIDDEN]"
    if sensitive_type == JWT:
        return content[:_KEEP_PREFIX + 2] + "••••••••"
    # api_key / token / password：遮蔽赋值符号后的值
    m = re.search(r"^(\s*\S+?\s*[=:]\s*['\"]?)([^\s'\"#;,]+)", content)
    if m:
        return m.group(1) + "••••••••"
    return content[:_KEEP_PREFIX] + "••••••••"
