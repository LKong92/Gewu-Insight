#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE="$PROJECT_DIR/scripts/PaperMonitorApp.m"
OUTPUT="$PROJECT_DIR/Paper Monitor.app/Contents/MacOS/Paper Monitor"

CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/private/tmp/paper-monitor-clang-cache}" \
  xcrun clang \
    -fobjc-arc \
    -arch arm64 \
    -arch x86_64 \
    -framework Cocoa \
    -framework WebKit \
    "$SOURCE" \
    -o "$OUTPUT"

chmod +x "$OUTPUT"
file "$OUTPUT"
