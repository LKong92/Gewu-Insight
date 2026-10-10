#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
# Historical folder-based macOS packaging; official macOS releases use main.
APP_SOURCE="$PROJECT_DIR/dist/Gewu Insight.app"
[[ -d "$APP_SOURCE" ]] || { echo "Build the legacy macOS fixture first, or use main for current macOS packaging." >&2; exit 1; }
VERSION="${1:-$(date +%Y%m%d)}"
DIST_DIR="$PROJECT_DIR/dist"
BUILD_DIR="$DIST_DIR/GewuInsight-$VERSION"
ZIP_PATH="$DIST_DIR/GewuInsight-$VERSION.zip"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

copy_item() {
  local item="$1"
  if [ -e "$PROJECT_DIR/$item" ]; then
    /bin/cp -R "$PROJECT_DIR/$item" "$BUILD_DIR/$item"
  fi
}

/bin/cp -R "$APP_SOURCE" "$BUILD_DIR/Gewu Insight.app"
copy_item "AGENTS.md"
copy_item "README.md"
copy_item "DISTRIBUTION.md"
copy_item "LICENSE"
copy_item "CONTRIBUTING.md"
copy_item "THIRD_PARTY_NOTICES.md"
copy_item "docs"
copy_item "requirements.txt"
copy_item "config"
copy_item "assets"
copy_item "paper_monitor"
copy_item "scripts"

mkdir -p "$BUILD_DIR/data" "$BUILD_DIR/reports"

find "$BUILD_DIR" -name ".DS_Store" -delete
find "$BUILD_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$BUILD_DIR" -name "*.pyc" -delete
xattr -cr "$BUILD_DIR" 2>/dev/null || true
/bin/chmod +x "$BUILD_DIR/Gewu Insight.app/Contents/MacOS/Gewu Insight" 2>/dev/null || true
/bin/chmod +x "$BUILD_DIR/scripts/"*.sh 2>/dev/null || true

rm -f "$ZIP_PATH"
(
  cd "$DIST_DIR"
  ditto -c -k --sequesterRsrc --keepParent "GewuInsight-$VERSION" "$ZIP_PATH"
)

echo "$ZIP_PATH"
