"""敏感信息检测器测试：5 类模式、误报负例、mask、联动（§9.11-9.16）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.sensitive_detector import (
    API_KEY,
    BANK_CARD,
    ID_CARD,
    JWT,
    PASSWORD,
    PRIVATE_KEY,
    TOKEN,
    detect,
    mask,
)


# ---- 正例 ----

def test_api_key_detection():
    r = detect("OPENAI_API_KEY=sk-1234567890abcdef")
    assert r is not None and r.sensitive_type == API_KEY
    r = detect("api_key = 'ghp_abcdefghijklmnopqrstuvwxyz123456'")
    assert r is not None and r.sensitive_type == API_KEY
    r = detect('export ANTHROPIC_API_KEY="sk-ant-abcdefghijklmnop"')
    assert r is not None and r.sensitive_type == API_KEY


def test_token_detection():
    r = detect("access_token=abcdefghijklmnop1234567890")
    assert r is not None and r.sensitive_type == TOKEN
    r = detect("refresh_token: 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abc123'")
    assert r is not None and r.sensitive_type == TOKEN


def test_jwt_detection():
    jwt = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
           "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
           "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
    r = detect(jwt)
    assert r is not None and r.sensitive_type == JWT


def test_private_key_detection():
    pem = ("-----BEGIN PRIVATE KEY-----\n"
           "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQ\n"
           "-----END PRIVATE KEY-----")
    r = detect(pem)
    assert r is not None and r.sensitive_type == PRIVATE_KEY


def test_password_detection():
    r = detect('password="MySecret123"')
    assert r is not None and r.sensitive_type == PASSWORD
    r = detect("passwd = 'qwerty12345'")
    assert r is not None and r.sensitive_type == PASSWORD
    r = detect("pwd=letmein99")
    assert r is not None and r.sensitive_type == PASSWORD


# ---- 证件号（§9.1 银行卡 / 个人信息）：候选正则 + 校验位两步判定 ----

# Luhn 通过的测试卡号（公开的支付测试号，非真实账户）
_VALID_CARD = "4111 1111 1111 1111"
# 校验位正确的示例身份证（GB 11643-1999 算法）
_VALID_ID = "11010519491231002X"


def test_bank_card_detection():
    r = detect(f"card number: {_VALID_CARD}")
    assert r is not None and r.sensitive_type == BANK_CARD
    r = detect("卡号 4111111111111111")
    assert r is not None and r.sensitive_type == BANK_CARD


def test_id_card_detection():
    r = detect(f"身份证 {_VALID_ID}")
    assert r is not None and r.sensitive_type == ID_CARD


def test_id_card_beats_bank_card():
    """18 位身份证也落在银行卡的候选长度里，必须先判身份证（校验位不同）。"""
    r = detect(_VALID_ID)
    assert r is not None and r.sensitive_type == ID_CARD


def test_no_false_positive_for_random_digits():
    """无校验的纯数字串不能命中：订单号/时间戳/常量否则全被标成敏感。"""
    assert detect("order 1234567890123456 shipped") is None      # Luhn 不过
    assert detect("timestamp 1757000000000") is None
    assert detect("build 20240101120000000") is None
    assert detect("12345678901234567890") is None                # 20 位超长


def test_no_false_positive_for_invalid_id_checksum():
    """校验位错的 18 位数字不是身份证。"""
    assert detect("110105194912310021") is None


# ---- 负例：不应误报 ----

def test_no_false_positive_for_plain_text():
    assert detect("hello world, how are you doing today?") is None
    assert detect("") is None
    assert detect("会议室预定在明天下午三点") is None


def test_no_false_positive_for_variable_name_without_value():
    """变量名提到 api_key 但没有机密值 → 不误报。"""
    assert detect("the api_key field is required") is None
    assert detect("password reset link: https://example.com/r/abc") is None


def test_no_false_positive_short_values():
    assert detect("api_key=x") is None  # 值太短
    assert detect("token=abc") is None


# ---- mask（§9.19）----

def test_mask_api_key_keeps_prefix():
    out = mask("OPENAI_API_KEY=sk-1234567890abcdef", API_KEY)
    assert "sk-1234567890abcdef" not in out
    assert "OPENAI_API_KEY=" in out
    assert "••••" in out


def test_mask_private_key_hidden():
    out = mask("-----BEGIN PRIVATE KEY-----\nMIIE...", PRIVATE_KEY)
    assert out == "[PRIVATE KEY HIDDEN]"


def test_mask_jwt_keeps_header_prefix():
    jwt = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
           "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c")
    out = mask(jwt, JWT)
    assert jwt not in out
    assert out.startswith("eyJh")


def test_mask_password():
    out = mask('password="MySecret123"', PASSWORD)
    assert "MySecret123" not in out


def test_mask_multiline_masks_every_secret_and_keeps_context():
    """多行 .env：每一处机密都要遮蔽，其余文本原样保留。

    旧实现只处理「第一处键=值」并把后面整段丢掉 → 预览退化成
    `DB_HOST=••••••••`：既丢了上下文，又遮蔽了不相关的第一行。
    """
    text = ("DB_HOST=localhost\n"
            "DB_PASSWORD=sup3rs3cret!\n"
            "API_KEY=3f9a2b7c8d1e4f5a6b7c8d9e0f1a\n"
            "DEBUG=true")
    out = mask(text, API_KEY)
    assert "sup3rs3cret!" not in out
    assert "3f9a2b7c8d1e4f5a6b7c8d9e0f1a" not in out
    assert "DB_HOST=localhost" in out          # 非机密行原样保留
    assert "DEBUG=true" in out
    assert out.count("••••••••") == 2


def test_mask_single_line_multiple_secrets():
    """同一行多处机密也要逐处遮蔽（不能只处理第一处）。"""
    out = mask("token=abcdefghijklmnopqrstuvwx password=hunter2secret", TOKEN)
    assert "abcdefghijklmnopqrstuvwx" not in out
    assert "hunter2secret" not in out


def test_mask_fallback_hides_everything_after_prefix():
    """没有「键=值」结构（裸厂商令牌）时兜底：只留前 4 字符，尾部一律不留。"""
    out = mask("ghp_1234567890abcdefghijklmnopqrstuvwx", TOKEN)
    assert out == "ghp_••••••••"


def test_mask_card_and_id_fully_hidden():
    """纯数字证件号没有「键=值」结构，前 4 位也是机密（卡号段/地区码）。"""
    for kind, content in ((BANK_CARD, _VALID_CARD), (ID_CARD, _VALID_ID)):
        out = mask(content, kind)
        assert content[:4] not in out
        assert "••••" in out


# ---- 漏检修复回归（真机实测发现的三处，2026-09）----

def test_bearer_token_detected():
    """`Authorization: Bearer <值>` 是**空格**分隔，不是「键=值」结构。

    原先把 bearer 混在键名分支里（该分支后面强制要 `[=:]`）→ 分支永不命中，
    只有 `bearer = xxx` 能过。而这是 token 最常见的出现形态（curl/HTTP 头/文档）。
    """
    r = detect("Authorization: Bearer 8f3a9b2c7d1e4f5a6b7c8d9e0f1a2b3c4d5e6f7a")
    assert r is not None and r.sensitive_type == TOKEN
    r = detect('curl -H "Authorization: Bearer '
               'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123def456ghi"')
    assert r is not None and r.sensitive_type == TOKEN
    r = detect("bearer = 8f3a9b2c7d1e4f5a6b7c8d9e0f1a2b3c")   # 旧的等号写法仍要认
    assert r is not None and r.sensitive_type == TOKEN


def test_bearer_mask_hides_token_not_the_word():
    """遮蔽必须落在令牌上，不能只遮蔽 "Bearer" 这个词——那等于把真令牌留在屏幕上。"""
    token = "8f3a9b2c7d1e4f5a6b7c8d9e0f1a2b3c4d5e6f7a"
    out = mask(f"Authorization: Bearer {token}", TOKEN)
    assert token not in out
    assert "Bearer ••••••••" in out
    # 等号写法同样不能泄露：这里若走 Bearer 那条分支，`\\S+` 只会咬到 `=`，
    # 反而把令牌原样留下（已踩过）
    out = mask(f"bearer = {token}", TOKEN)
    assert token not in out


def test_underscore_prefixed_keys_detected():
    """.env 命名习惯（MYSQL_PASSWORD= / MY_API_KEY= / MY_ACCESS_TOKEN=）曾整类漏检。

    根因：键名前的 `\\b` 在 `_` 与字母之间不成立（两者同属 \\w）。
    改用「前一字符不是字母数字」后放行，同时仍挡住词中命中。
    """
    for text, kind in (
        ("MYSQL_PASSWORD=sup3rs3cret!", PASSWORD),
        ("SMTP_PASSWORD=hunter2xyz", PASSWORD),
        ("MY_API_KEY=3f9a2b7c8d1e4f5a6b7c8d9e0f1a", API_KEY),
        ("MY_ACCESS_TOKEN=xoxb-1234567890-abcdefgh", TOKEN),
        ("我的password=sup3rs3cret!", PASSWORD),      # 汉字相邻同理（\\w 含 CJK）
    ):
        r = detect(text)
        assert r is not None and r.sensitive_type == kind, text
    assert detect("tokenizer=abcdefghijklmnopqrstuvwx") is None   # 词中不算


def test_aws_secret_access_key_detected():
    """真正的密钥是 secret_access_key；原先只列了 aws_access_key_id（那是标识）。

    且 AWS secret 是 40 位 base64，值里含 `/`——不放行 `/` 就一个字也匹配不到。
    """
    r = detect("aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    assert r is not None and r.sensitive_type == API_KEY
    r = detect("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCY")
    assert r is not None and r.sensitive_type == API_KEY


def test_bare_vendor_tokens_detected():
    """厂商前缀本身就是格式约定，裸拷一段（没有键名）也必须判定。"""
    for text in ("ghp_1234567890abcdefghijklmnopqrstuvwx",
                 "glpat-AbCdEfGhIjKlMnOpQrSt",
                 "AKIAIOSFODNN7EXAMPLE",
                 "sk-proj-abcdefghijklmnopqrstuvwxyz1234"):
        r = detect(text)
        assert r is not None and r.sensitive_type == TOKEN, text


def test_vendor_prefix_matching_is_case_sensitive():
    """AKIA/ASIA 是大写号段；忽略大小写的话 asia… 这种普通词会误报。"""
    assert detect("asiaregion-sales-report-2024-final") is None
    assert detect("akia-something-long-enough-here") is None
    assert detect("sk-2024-annual-report-final-v3.pdf") is None   # 故意不收录裸 sk-


def test_no_false_positive_for_url_valued_key():
    """`api_key=https://…` 的值其实是个 URL（放行 `/` 之后的回归）。"""
    assert detect("api_key=https://example.com/path/that/is/quite/long") is None


# ---- 联动（§10）：代码内容同时含机密 ----

def test_code_and_sensitive_coexist():
    from services.code_detector import detect as detect_code

    content = 'export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxx"\ndocker compose up -d'
    code = detect_code(content)
    secret = detect(content)
    assert code is not None and code.language == "shell"
    assert secret is not None and secret.sensitive_type == API_KEY
