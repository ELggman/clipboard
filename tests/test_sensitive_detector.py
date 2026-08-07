"""敏感信息检测器测试：5 类模式、误报负例、mask、联动（§9.11-9.16）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from services.sensitive_detector import (
    API_KEY,
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


# ---- 联动（§10）：代码内容同时含机密 ----

def test_code_and_sensitive_coexist():
    from services.code_detector import detect as detect_code

    content = 'export OPENAI_API_KEY="sk-xxxxxxxxxxxxxxxx"\ndocker compose up -d'
    code = detect_code(content)
    secret = detect(content)
    assert code is not None and code.language == "shell"
    assert secret is not None and secret.sensitive_type == API_KEY
