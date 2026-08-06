#!/usr/bin/env bash
# ============================================================================
# build.sh — PyInstaller 打包管线（自签名证书签名）
# ============================================================================
# 用法：bash packaging/build.sh（需先运行 packaging/make_cert.sh 一次）
# 依赖 venv：确保 .venv 内已安装 requirements-dev.txt（pyinstaller）
# ============================================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGING_DIR="$PROJECT_ROOT/packaging"
DIST_DIR="$PROJECT_ROOT/dist"
BUILD_DIR="$PROJECT_ROOT/build"
SPEC_FILE="$PACKAGING_DIR/clipboard-workspace.spec"
VENV_PY="$PROJECT_ROOT/.venv/bin/pyinstaller"

APP_NAME="Clipboard Workspace"
APP_BUNDLE="$DIST_DIR/$APP_NAME.app"
CERT_NAME="Clipboard Workspace Signing"   # ★ 与 make_cert.sh 一致

if [ ! -x "$VENV_PY" ]; then
    echo "❌ 未找到 venv 内 PyInstaller: $VENV_PY"
    echo "请先: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt"
    exit 1
fi

echo "=== $APP_NAME 打包构建 ==="

# ---- Step 1: Clean（先退出运行中的应用，否则 dist 文件被占用 rm 会失败）----
echo "[1/5] 清理旧构建产物..."
pkill -f "$APP_NAME.app/Contents/MacOS/" 2>/dev/null || true
sleep 1
rm -rf "$BUILD_DIR" "$DIST_DIR"

# ---- Step 2: PyInstaller ----
echo "[2/5] 运行 PyInstaller (onedir)..."
cd "$PROJECT_ROOT"
"$VENV_PY" --clean --noconfirm "$SPEC_FILE" 2>&1 | tee "$PACKAGING_DIR/build.log"

# ---- Step 3: 自签名证书签名 ----
echo "[3/5] 自签名证书深度签名..."
if ! security find-certificate -c "$CERT_NAME" &>/dev/null; then
    echo "  ❌ 未找到签名证书 '$CERT_NAME'"
    echo "  请先运行: bash $PACKAGING_DIR/make_cert.sh"
    exit 1
fi

if [ -d "$APP_BUNDLE" ]; then
    codesign --force --deep --sign "$CERT_NAME" \
        --entitlements "$PACKAGING_DIR/entitlements.plist" \
        --options runtime \
        --timestamp=none \
        "$APP_BUNDLE"
    echo "  ✅ 签名完成"
fi

# ---- Step 4: 验证 ----
echo "[4/5] 验证输出..."
if [ ! -d "$APP_BUNDLE" ]; then
    echo "  ❌ App Bundle 未生成，请检查 build.log"
    exit 1
fi
echo "  ✅ $APP_BUNDLE ($(du -sh "$APP_BUNDLE" | cut -f1))"

# ---- Step 5: 签名稳定性验证 ----
echo "[5/5] 验证签名需求（应为 certificate 而非 cdhash）..."
codesign -d -r- "$APP_BUNDLE/Contents/MacOS/$APP_NAME" 2>&1 | tail -1 | grep -q "certificate" \
    && echo "  ✅ 证书身份签名确认" \
    || echo "  ⚠️  需求不是 certificate！检查签名身份"

echo "=== 完成 ==="
echo "启动: open '$APP_BUNDLE'"
echo "验收: 授权一次辅助功能 → 重建两次 → 权限仍有效（DEVELOPMENT.md §6.2）"
