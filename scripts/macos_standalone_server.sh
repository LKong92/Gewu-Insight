#!/bin/zsh
set -eu
umask 077
MACOS_DIR="$(cd "$(dirname "$0")" && pwd -P)"
RESOURCES="$(cd "$MACOS_DIR/../Resources" && pwd -P)"
export GEWU_APP_PATH="$(cd "$MACOS_DIR/../.." && pwd -P)"
export GEWU_STANDALONE=1
export GEWU_LOG_ROOT="${GEWU_LOG_ROOT:-$HOME/Library/Logs/Gewu Insight}"
mkdir -p "$GEWU_LOG_ROOT"
ARCH="$(/usr/bin/uname -m)"
case "$ARCH" in
    arm64|x86_64) ;;
    *) echo "Unsupported Mac architecture: $ARCH" >&2; exit 1 ;;
esac
exec "$RESOURCES/runtime/$ARCH/bin/python3" -I -B \
    "$RESOURCES/macos_standalone_entry.py" ui \
    --host "${PAPER_MONITOR_HOST:-127.0.0.1}" \
    --port "${PAPER_MONITOR_PORT:-8765}" \
    >>"$GEWU_LOG_ROOT/paper_monitor_launcher.log" 2>&1
