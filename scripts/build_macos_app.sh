#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE="$PROJECT_DIR/scripts/PaperMonitorApp.m"
INSTALLED_APP="$PROJECT_DIR/Gewu Insight.app"
OUTPUT_APP="$INSTALLED_APP"
if [[ ! -d "$INSTALLED_APP" ]]; then
  OUTPUT_APP="$PROJECT_DIR/dist/Gewu Insight.app"
fi
SEED_WORKDIR=""
DEVELOPMENT_ADHOC=0
while (( $# )); do
  case "$1" in
    --output) OUTPUT_APP="${2:?--output requires an absolute path}"; shift 2 ;;
    --development-adhoc) DEVELOPMENT_ADHOC=1; shift ;;
    *) echo "Usage: $0 [--output /absolute/path/Gewu\ Insight.app] [--development-adhoc]" >&2; exit 2 ;;
  esac
done
[[ "$OUTPUT_APP" = /* ]] || { echo "--output must be an absolute path." >&2; exit 2; }
if [[ ! -d "$INSTALLED_APP" ]]; then
  [[ -f "$PROJECT_DIR/assets/macos-app-template.zip" ]] || { echo "Missing macOS App build template." >&2; exit 1; }
  SEED_WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/gewu-app-seed.XXXXXX")"
  trap '[[ -z "$SEED_WORKDIR" ]] || rm -rf "$SEED_WORKDIR"' EXIT
  ditto -x -k "$PROJECT_DIR/assets/macos-app-template.zip" "$SEED_WORKDIR"
  INSTALLED_APP="$SEED_WORKDIR/Gewu Insight.app"
fi
BUILD_PYTHON="${GEWU_BUILD_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
[[ -x "$BUILD_PYTHON" ]] || BUILD_PYTHON="$(command -v python3)"
SIGNING_HELPER="$PROJECT_DIR/scripts/macos_signing.py"
SIGNING_OPTIONS=()
if (( DEVELOPMENT_ADHOC )); then
  SIGNING_OPTIONS+=(--development-adhoc)
fi
# Local builds explicitly use ad-hoc signing; no certificate or keychain login.
SIGN_IDENTITY="$("$BUILD_PYTHON" "$SIGNING_HELPER" preflight --app "$INSTALLED_APP" \
  --output "$OUTPUT_APP" "${SIGNING_OPTIONS[@]}")"
INSTALLED_FINGERPRINT="$("$BUILD_PYTHON" "$SIGNING_HELPER" fingerprint --app "$INSTALLED_APP")"
mkdir -p "$(dirname "$OUTPUT_APP")"
# Keep the stage and destination on the same filesystem for rename installation.
SIGN_WORKDIR="$(mktemp -d "$(dirname "$OUTPUT_APP")/.gewu-app-build.XXXXXX")"
APP="$SIGN_WORKDIR/Gewu Insight.app"
BACKUP_APP="$SIGN_WORKDIR/Gewu Insight.previous.app"
SWAPPED_APP=0
cleanup() {
  local result=$?
  if (( result != 0 )) && { (( SWAPPED_APP )) || [[ -d "$BACKUP_APP" ]]; }; then
    if [[ -d "$OUTPUT_APP" ]]; then
      mv "$OUTPUT_APP" "$SIGN_WORKDIR/Gewu Insight.rejected.app" || return "$result"
    fi
    if [[ -d "$BACKUP_APP" ]]; then
      mv "$BACKUP_APP" "$OUTPUT_APP" || {
        echo "Restore failed. Original App retained at $BACKUP_APP" >&2
        return "$result"
      }
    fi
  fi
  rm -rf "$SIGN_WORKDIR"
  [[ -z "$SEED_WORKDIR" ]] || rm -rf "$SEED_WORKDIR"
  return "$result"
}
trap cleanup EXIT
ditto --rsrc --extattr "$INSTALLED_APP" "$APP"
OUTPUT="$APP/Contents/MacOS/Gewu Insight"
INFO_PLIST="$APP/Contents/Info.plist"
BRAND_ART_SOURCE="$PROJECT_DIR/assets/branding/GewuSealGlyphs.png"
BRAND_ART_DEST="$APP/Contents/Resources/GewuSealGlyphs.png"
ABOUT_CALLIGRAPHY_SOURCE="$PROJECT_DIR/assets/branding/GewuAboutCalligraphy.png"
ABOUT_CALLIGRAPHY_DEST="$APP/Contents/Resources/GewuAboutCalligraphy.png"
USER_GUIDE_PDF_SOURCE="$PROJECT_DIR/paper_monitor/Gewu_Insight_User_Guide.pdf"
USER_GUIDE_PDF_DEST="$APP/Contents/Resources/Gewu Insight User Guide.pdf"
APP_ICON_SOURCE="$PROJECT_DIR/assets/gewu-insight-app-icon.png"
# Product versions are independent of the icon cache key.
PRODUCT_VERSION="$(cd "$PROJECT_DIR" && "$BUILD_PYTHON" -c 'from paper_monitor import __version__; print(__version__)')"
PRODUCT_BUILD="$(cd "$PROJECT_DIR" && "$BUILD_PYTHON" -c 'from paper_monitor import __build__; print(__build__)')"
APP_ICON_CACHE_KEY="$(cksum "$APP_ICON_SOURCE" | awk '{print $1}')"
APP_ICON_BASENAME="GewuInsightAppIcon-$APP_ICON_CACHE_KEY"
APP_ICON_PNG_DEST="$APP/Contents/Resources/$APP_ICON_BASENAME.png"
STARTUP_ICON_PNG_DEST="$APP/Contents/Resources/GewuInsightAppIcon.png"
APP_ICONSET="$APP/Contents/Resources/PaperMonitor.iconset"
APP_ICON_ICNS_DEST="$APP/Contents/Resources/$APP_ICON_BASENAME.icns"
CLANG_MODULE_CACHE_PATH="${CLANG_MODULE_CACHE_PATH:-/private/tmp/paper-monitor-clang-cache}" \
MACOSX_DEPLOYMENT_TARGET="${MACOSX_DEPLOYMENT_TARGET:-14.0}" \
  xcrun clang \
    -fobjc-arc \
    -mmacosx-version-min="${MACOSX_DEPLOYMENT_TARGET:-14.0}" \
    -arch arm64 \
    -arch x86_64 \
    -framework Cocoa \
    -framework Quartz \
    -framework WebKit \
    -framework ImageIO \
    -framework UniformTypeIdentifiers \
    "$SOURCE" \
    "$PROJECT_DIR/scripts/GewuBrowserController.m" \
    "$PROJECT_DIR/scripts/GewuBrowserAutoFill.m" \
    "$PROJECT_DIR/scripts/GewuBrowserCapture.m" \
    "$PROJECT_DIR/scripts/GewuBrowserFavicons.m" \
    -o "$OUTPUT"

chmod +x "$OUTPUT"
cp "$PROJECT_DIR/scripts/GewuBrowserCaptureProbe.js" "$APP/Contents/Resources/GewuBrowserCaptureProbe.js"
cp "$PROJECT_DIR/scripts/GewuBrowserLoginProbe.js" "$APP/Contents/Resources/GewuBrowserLoginProbe.js"
cp "$PROJECT_DIR/scripts/GewuBrowserNavigationProbe.js" "$APP/Contents/Resources/GewuBrowserNavigationProbe.js"
mkdir -p "$(dirname "$BRAND_ART_DEST")"
cp "$BRAND_ART_SOURCE" "$BRAND_ART_DEST"
mkdir -p "$APP/Contents/Resources/assets/branding"
cp "$PROJECT_DIR/assets/branding/README.md" "$PROJECT_DIR/assets/branding/GewuSealGlyphs.provenance.json" \
  "$APP/Contents/Resources/assets/branding/"
cp "$ABOUT_CALLIGRAPHY_SOURCE" "$ABOUT_CALLIGRAPHY_DEST"
if [[ ! -s "$USER_GUIDE_PDF_SOURCE" ]]; then
  echo "The fixed-layout User Guide PDF is missing. Run scripts/build_user_guide_pdf.py first." >&2
  exit 1
fi
cp "$USER_GUIDE_PDF_SOURCE" "$USER_GUIDE_PDF_DEST"
cp "$PROJECT_DIR/LICENSE" "$APP/Contents/Resources/LICENSE.txt"
cp "$PROJECT_DIR/CONTRIBUTING.md" "$APP/Contents/Resources/CONTRIBUTING.md"
cp "$PROJECT_DIR/THIRD_PARTY_NOTICES.md" "$APP/Contents/Resources/THIRD_PARTY_NOTICES.md"
cp "$APP_ICON_SOURCE" "$APP_ICON_PNG_DEST"
cp "$APP_ICON_SOURCE" "$STARTUP_ICON_PNG_DEST"
mkdir -p "$APP_ICONSET"
for icon_spec in \
  "16 icon_16x16.png" \
  "32 icon_16x16@2x.png" \
  "32 icon_32x32.png" \
  "64 icon_32x32@2x.png" \
  "128 icon_128x128.png" \
  "256 icon_128x128@2x.png" \
  "256 icon_256x256.png" \
  "512 icon_256x256@2x.png" \
  "512 icon_512x512.png" \
  "1024 icon_512x512@2x.png"; do
  icon_size="${icon_spec%% *}"
  icon_name="${icon_spec#* }"
  sips -z "$icon_size" "$icon_size" "$APP_ICON_SOURCE" \
    --out "$APP_ICONSET/$icon_name" >/dev/null
done
if ! iconutil -c icns -o "$APP_ICON_ICNS_DEST" "$APP_ICONSET"; then
  if [[ ! -s "$APP_ICON_ICNS_DEST" ]]; then
    echo "Unable to build the app icon and no existing ICNS fallback is available." >&2
    exit 1
  fi
  echo "iconutil rejected the regenerated iconset; keeping the existing app icon." >&2
fi
cp "$APP_ICON_ICNS_DEST" "$APP/Contents/Resources/PaperMonitor.icns"
/usr/libexec/PlistBuddy -c "Set :CFBundleIconFile $APP_ICON_BASENAME" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $PRODUCT_VERSION" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $PRODUCT_BUILD" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :LSMinimumSystemVersion ${MACOSX_DEPLOYMENT_TARGET:-14.0}" "$INFO_PLIST"
/usr/libexec/PlistBuddy -c "Set :NSHumanReadableCopyright Copyright © 2026 Lingyuan Kong and Zhengran Wu. All rights reserved." "$INFO_PLIST" 2>/dev/null || \
  /usr/libexec/PlistBuddy -c "Add :NSHumanReadableCopyright string Copyright © 2026 Lingyuan Kong and Zhengran Wu. All rights reserved." "$INFO_PLIST"
xattr -cr "$APP"
TIMESTAMP_OPTION=--timestamp=none
# Sign nested executable code before the bundle. Do not erase signature xattrs
# after signing: the launcher script stores its signature in those attributes.
codesign --force --sign "$SIGN_IDENTITY" "$TIMESTAMP_OPTION" "$APP/Contents/MacOS/Gewu Insight Server"
codesign --force --sign "$SIGN_IDENTITY" "$TIMESTAMP_OPTION" "$APP"
"$BUILD_PYTHON" "$SIGNING_HELPER" verify --app "$APP" --previous "$INSTALLED_APP" "${SIGNING_OPTIONS[@]}"
# A concurrent update must not be silently overwritten by this build.
[[ "$INSTALLED_FINGERPRINT" = "$("$BUILD_PYTHON" "$SIGNING_HELPER" fingerprint --app "$INSTALLED_APP")" ]] || {
  echo "Installed App changed during the build; no installation performed." >&2; exit 1
}
if [[ "$OUTPUT_APP" = "$INSTALLED_APP" && "$INSTALLED_FINGERPRINT" = "$("$BUILD_PYTHON" "$SIGNING_HELPER" fingerprint --app "$APP")" ]] \
  && "$BUILD_PYTHON" "$SIGNING_HELPER" verify --app "$INSTALLED_APP" >/dev/null 2>&1; then
  echo "App content unchanged; keeping the installed signature and keychain identity."
  exit 0
fi
if [[ "$OUTPUT_APP" = "$INSTALLED_APP" ]]; then
  "$BUILD_PYTHON" "$SIGNING_HELPER" stopped --app "$INSTALLED_APP"
  mv "$INSTALLED_APP" "$BACKUP_APP"
elif [[ -e "$OUTPUT_APP" ]]; then
  echo "Output path appeared during the build; no installation performed." >&2; exit 1
fi
SWAPPED_APP=1
# Refresh the directory timestamp so Finder and Dock notice the new bundle.
touch "$APP"
mv "$APP" "$OUTPUT_APP"
"$BUILD_PYTHON" "$SIGNING_HELPER" verify --app "$OUTPUT_APP" "${SIGNING_OPTIONS[@]}"
SWAPPED_APP=0
file "$OUTPUT_APP/Contents/MacOS/Gewu Insight"
