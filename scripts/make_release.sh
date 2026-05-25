#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
VERSION="${1:-$(date +%Y%m%d)}"
DIST_DIR="$PROJECT_DIR/dist"
BUILD_DIR="$DIST_DIR/PaperMonitor-$VERSION"
ZIP_PATH="$DIST_DIR/PaperMonitor-$VERSION.zip"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

copy_item() {
  local item="$1"
  if [ -e "$PROJECT_DIR/$item" ]; then
    /bin/cp -R "$PROJECT_DIR/$item" "$BUILD_DIR/$item"
  fi
}

copy_item "Daiqo.app"
copy_item "AGENTS.md"
copy_item "README.md"
copy_item "DISTRIBUTION.md"
copy_item "requirements.txt"
copy_item "config"
copy_item "deep_survey"
copy_item "paper_monitor"
copy_item "scripts"
copy_item "skills"

mkdir -p "$BUILD_DIR/data" "$BUILD_DIR/reports"

find "$BUILD_DIR" -name ".DS_Store" -delete
find "$BUILD_DIR" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "$BUILD_DIR" -name "*.pyc" -delete
xattr -cr "$BUILD_DIR" 2>/dev/null || true
/bin/chmod +x "$BUILD_DIR/Daiqo.app/Contents/MacOS/Paper Monitor" 2>/dev/null || true
/bin/chmod +x "$BUILD_DIR/scripts/"*.sh 2>/dev/null || true

rm -f "$ZIP_PATH"
(
  cd "$DIST_DIR"
  ditto -c -k --sequesterRsrc --keepParent "PaperMonitor-$VERSION" "$ZIP_PATH"
)

echo "$ZIP_PATH"
