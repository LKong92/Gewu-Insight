#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE="$PROJECT_DIR/scripts/PaperMonitorApp.m"
OUTPUT="$PROJECT_DIR/Daico.app/Contents/MacOS/Paper Monitor"

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/private/tmp/paper-monitor-clang-cache}" \
MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-14.0}" \
  xcrun clang \
    -fobjc-arc \
    -mmacosx-version-min="${MACOSX_DEPLOYMENT_TARGET:-14.0}" \
    -arch arm64 \
    -arch x86_64 \
    -framework Cocoa \
    -framework PDFKit \
    -framework WebKit \
    "$SOURCE" \
    -o "$OUTPUT"

chmod +x "$OUTPUT"
file "$OUTPUT"
