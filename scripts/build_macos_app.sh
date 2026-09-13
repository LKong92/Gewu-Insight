#!/bin/zsh
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
SOURCE="$PROJECT_DIR/scripts/PaperMonitorApp.m"
APP="$PROJECT_DIR/Gewu Insight.app"
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
PRODUCT_VERSION="$(cd "$PROJECT_DIR" && python3 -c 'from paper_monitor import __version__; print(__version__)')"
PRODUCT_BUILD="$(cd "$PROJECT_DIR" && python3 -c 'from paper_monitor import __build__; print(__build__)')"
APP_ICON_CACHE_KEY="$(cksum "$APP_ICON_SOURCE" | awk '{print $1}')"
APP_ICON_BASENAME="GewuInsightAppIcon-$APP_ICON_CACHE_KEY"
APP_ICON_PNG_DEST="$APP/Contents/Resources/$APP_ICON_BASENAME.png"
STARTUP_ICON_PNG_DEST="$APP/Contents/Resources/GewuInsightAppIcon.png"
APP_ICONSET="$APP/Contents/Resources/PaperMonitor.iconset"
APP_ICON_ICNS_DEST="$APP/Contents/Resources/$APP_ICON_BASENAME.icns"
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
cp "$ABOUT_CALLIGRAPHY_SOURCE" "$ABOUT_CALLIGRAPHY_DEST"
if [[ ! -s "$USER_GUIDE_PDF_SOURCE" ]]; then
  echo "The fixed-layout User Guide PDF is missing. Run scripts/build_user_guide_pdf.py first." >&2
  exit 1
fi
cp "$USER_GUIDE_PDF_SOURCE" "$USER_GUIDE_PDF_DEST"
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
# ditto preserves the old bundle directory timestamp. Touch the bundle so
# Finder, Launch Services, and pinned Dock tiles can detect icon changes.
touch "$APP"
file "$OUTPUT"
