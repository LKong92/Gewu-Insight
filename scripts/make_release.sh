#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
VERSION="${1:-$(date +%Y%m%d)}"
DIST_DIR="$PROJECT_DIR/dist"
FINAL_BUILD_DIR="$DIST_DIR/GewuInsight-$VERSION"
ZIP_PATH="$DIST_DIR/GewuInsight-$VERSION.zip"
BUILD_PYTHON="${GEWU_BUILD_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
[[ -x "$BUILD_PYTHON" ]] || BUILD_PYTHON="$(command -v python3)"
SIGNING_HELPER="$PROJECT_DIR/scripts/macos_signing.py"
if [[ ! "$VERSION" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Version must be a plain version label, not a path." >&2; exit 2
fi
# Verify the local ad-hoc App before touching an earlier package.
"$BUILD_PYTHON" "$SIGNING_HELPER" verify --app "$PROJECT_DIR/Gewu Insight.app"
SOURCE_FINGERPRINT="$("$BUILD_PYTHON" "$SIGNING_HELPER" fingerprint --app "$PROJECT_DIR/Gewu Insight.app")"
mkdir -p "$DIST_DIR"
WORK_DIR="$(mktemp -d "$DIST_DIR/.gewu-release.XXXXXX")"
BUILD_PUBLISHED=0
ZIP_PUBLISHED=0
cleanup() {
  local result=$?
  if (( result != 0 )); then
    if (( ZIP_PUBLISHED )); then
      mv "$ZIP_PATH" "$WORK_DIR/rejected.zip" || return "$result"
    fi
    if [[ -e "$WORK_DIR/previous.zip" ]]; then
      mv "$WORK_DIR/previous.zip" "$ZIP_PATH" || {
        echo "Restore failed. Previous release retained at $WORK_DIR" >&2
        return "$result"
      }
    fi
    if (( BUILD_PUBLISHED )); then
      mv "$FINAL_BUILD_DIR" "$WORK_DIR/rejected-build" || return "$result"
    fi
    if [[ -d "$WORK_DIR/previous-build" ]]; then
      mv "$WORK_DIR/previous-build" "$FINAL_BUILD_DIR" || {
        echo "Restore failed. Previous release retained at $WORK_DIR" >&2
        return "$result"
      }
    fi
  fi
  rm -rf "$WORK_DIR"
  return "$result"
}
trap cleanup EXIT
BUILD_DIR="$WORK_DIR/GewuInsight-$VERSION"
STAGED_ZIP="$WORK_DIR/GewuInsight-$VERSION.zip"

mkdir -p "$BUILD_DIR"

copy_item() {
  local item="$1"
  if [ -e "$PROJECT_DIR/$item" ]; then
    /usr/bin/ditto --rsrc --extattr "$PROJECT_DIR/$item" "$BUILD_DIR/$item"
  fi
}

copy_item "Gewu Insight.app"
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
# Remove only Finder display metadata. Recursive xattr clearing would destroy
# the launcher's embedded code signature and silently invalidate the release.
xattr -dr com.apple.FinderInfo "$BUILD_DIR" 2>/dev/null || true
xattr -dr 'com.apple.fileprovider.fpfs#P' "$BUILD_DIR" 2>/dev/null || true
/bin/chmod +x "$BUILD_DIR/Gewu Insight.app/Contents/MacOS/Gewu Insight" 2>/dev/null || true
/bin/chmod +x "$BUILD_DIR/scripts/"*.sh 2>/dev/null || true

"$BUILD_PYTHON" "$SIGNING_HELPER" verify --app "$BUILD_DIR/Gewu Insight.app" \
  --previous "$PROJECT_DIR/Gewu Insight.app"
(
  cd "$WORK_DIR"
  ditto -c -k --sequesterRsrc --keepParent "GewuInsight-$VERSION" "$STAGED_ZIP"
)
# Test the actual recipient artifact, including the script's signing xattrs.
ditto -x -k "$STAGED_ZIP" "$WORK_DIR/extracted"
"$BUILD_PYTHON" "$SIGNING_HELPER" verify \
  --app "$WORK_DIR/extracted/GewuInsight-$VERSION/Gewu Insight.app" \
  --previous "$PROJECT_DIR/Gewu Insight.app"
[[ "$SOURCE_FINGERPRINT" = "$("$BUILD_PYTHON" "$SIGNING_HELPER" fingerprint --app "$PROJECT_DIR/Gewu Insight.app")" ]] || {
  echo "Source App changed during packaging; previous release retained." >&2; exit 1
}
[[ ! -e "$FINAL_BUILD_DIR" ]] || mv "$FINAL_BUILD_DIR" "$WORK_DIR/previous-build"
[[ ! -e "$ZIP_PATH" ]] || mv "$ZIP_PATH" "$WORK_DIR/previous.zip"
mv "$BUILD_DIR" "$FINAL_BUILD_DIR"
BUILD_PUBLISHED=1
mv "$STAGED_ZIP" "$ZIP_PATH"
ZIP_PUBLISHED=1

echo "$ZIP_PATH"
