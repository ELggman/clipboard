#!/usr/bin/env bash
# ============================================================================
# make_cert.sh — 创建自签名代码签名证书（无需 Apple Developer 账号）
# ============================================================================
# 作用：生成带 codeSigning EKU 的自签名证书并导入登录钥匙串。
#   用它签名的 app，TCC 授权绑定证书身份（certificate leaf），跨重建稳定
#   —— 解决 ad-hoc 签名（cdhash 每次重建都变）导致权限反复失效的根因。
#
# 用法：bash make_cert.sh
# 幂等：证书已存在时直接跳过。每台机器运行一次即可；有效期 10 年。
# ============================================================================

set -euo pipefail

# ★ 与 build.sh 的 CERT_NAME 保持一致；发布后不可更改（否则已授权限作废）
CERT_COMMON_NAME="Clipboard Workspace Signing"
CERT_VALIDITY_DAYS=3650
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
# p12 传输密码（仅用于导入；openssl 3.x 空密码 p12 与 security 不兼容）
P12_PASSWORD="clipboard-workspace-signing-2026"

echo "=== 自签名代码签名证书创建 ==="

# ---- 幂等检查 ----
if security find-certificate -c "$CERT_COMMON_NAME" "$KEYCHAIN" &>/dev/null; then
    echo "证书 '$CERT_COMMON_NAME' 已存在，跳过创建。"
    security find-certificate -c "$CERT_COMMON_NAME" -p "$KEYCHAIN" | \
        openssl x509 -noout -subject -dates 2>/dev/null || true
    exit 0
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

CERT_PEM="$TMPDIR/code_sign_cert.pem"
KEY_PEM="$TMPDIR/code_sign_key.pem"
P12="$TMPDIR/code_sign.p12"

# ---- 生成自签名证书（codeSigning EKU）----
openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$KEY_PEM" \
    -out "$CERT_PEM" \
    -days "$CERT_VALIDITY_DAYS" \
    -subj "/CN=$CERT_COMMON_NAME/O=ClipboardWorkspace/OU=Development" \
    -addext "extendedKeyUsage=codeSigning" \
    -addext "basicConstraints=critical,CA:FALSE" \
    -addext "keyUsage=critical,digitalSignature"

echo ""
echo "证书已生成:"
openssl x509 -in "$CERT_PEM" -noout -subject -dates

# ---- 打包为 p12 并导入登录钥匙串（含私钥）----
# -legacy 必需：openssl 3.x 默认 PBES2 格式会导致 security import
# 报 "MAC verification failed"（实测）
openssl pkcs12 -export -legacy \
    -in "$CERT_PEM" \
    -inkey "$KEY_PEM" \
    -out "$P12" \
    -passout pass:"$P12_PASSWORD"

security import "$P12" \
    -k "$KEYCHAIN" \
    -P "$P12_PASSWORD" \
    -T /usr/bin/codesign \
    -T /usr/bin/security

# ---- 用户级 codeSign 信任（失败容忍：codesign 与 TCC 不依赖信任）----
security add-trusted-cert \
    -p codeSign \
    -k "$KEYCHAIN" \
    "$CERT_PEM" || echo "  ⚠️  信任设置失败（可忽略，不影响签名与 TCC 授权）"

echo ""
echo "=== 证书安装完成 ==="
echo "Common Name: $CERT_COMMON_NAME"
echo "有效期至:   $(openssl x509 -in "$CERT_PEM" -noout -enddate | cut -d= -f2)"
echo ""
echo "验证:"
echo "  security find-identity -p codesigning"
echo "  codesign -d -r- /path/to/app.app   # 应显示 certificate 而非 cdhash"
