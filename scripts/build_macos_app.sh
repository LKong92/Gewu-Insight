#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE="$PROJECT_DIR/scripts/PaperMonitorApp.m"
APP="$PROJECT_DIR/Gewu Insight.app"
OUTPUT="$APP/Contents/MacOS/Gewu Insight"
SIGN_WORKDIR="${TMPDIR:-/private/tmp}/paper-monitor-sign-$$"
SIGN_APP="$SIGN_WORKDIR/Gewu Insight.app"
BACKUP_APP="$SIGN_WORKDIR/Gewu Insight.previous.app"
trap 'rm -rf "$SIGN_WORKDIR"' EXIT

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/private/tmp/paper-monitor-clang-cache}" \
MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-14.0}" \
  xcrun clang \
    -fobjc-arc \
    -mmacosx-version-min="${MACOSX_DEPLOYMENT_TARGET:-14.0}" \
    -arch arm64 \
    -arch x86_64 \
    -framework Cocoa \
    -framework WebKit \
    "$SOURCE" \
    -o "$OUTPUT"

chmod +x "$OUTPUT"
mkdir -p "$SIGN_WORKDIR"
ditto "$APP" "$SIGN_APP"
xattr -cr "$SIGN_APP" 2>/dev/null || true
codesign --force --deep --sign - "$SIGN_APP"
codesign --verify --deep --strict "$SIGN_APP"
mv "$APP" "$BACKUP_APP"
ditto "$SIGN_APP" "$APP"
xattr -d com.apple.FinderInfo "$APP" 2>/dev/null || true
xattr -d 'com.apple.fileprovider.fpfs#P' "$APP" 2>/dev/null || true
if ! codesign --verify --deep --strict "$APP"; then
  rm -rf "$APP"
  mv "$BACKUP_APP" "$APP"
  exit 1
fi
file "$OUTPUT"
