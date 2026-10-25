#!/bin/zsh
# Local source adapter. Distributed standalone builds use macos_standalone_server.sh.
set -eu
umask 077
MACOS_DIR="$(cd "$(dirname "$0")" && pwd -P)"
RESOURCES="$(cd "$MACOS_DIR/../Resources" && pwd -P)"
SOURCE_DIR="$(/usr/bin/plutil -extract source_root raw -o - "$RESOURCES/local-source.json")"
export GEWU_APP_PATH="$(cd "$MACOS_DIR/../.." && pwd -P)"
export GEWU_STANDALONE=1
while (( $# )); do
    case "$1" in
        --database) export GEWU_WORKSPACE_ROOT="${2:?Missing database folder}"; export GEWU_REMEMBER_DATABASE=0; unset GEWU_CREATE_DATABASE; shift 2 ;;
        --host) export PAPER_MONITOR_HOST="${2:?Missing host}"; shift 2 ;;
        --port) export PAPER_MONITOR_PORT="${2:?Missing port}"; shift 2 ;;
        *) echo "Unsupported background startup argument." >&2; exit 2 ;;
    esac
done
export GEWU_LOG_ROOT="${GEWU_LOG_ROOT:-$HOME/Library/Logs/Gewu Insight}"
export GEWU_CACHE_ROOT="${GEWU_WORKSPACE_ROOT:?Database location is required}/data/cache"
mkdir -p "$GEWU_LOG_ROOT"
exec "$SOURCE_DIR/.venv/bin/python" -I -B \
    "$RESOURCES/macos_standalone_entry.py" ui \
    --host "${PAPER_MONITOR_HOST:-127.0.0.1}" \
    --port "${PAPER_MONITOR_PORT:-8765}" \
    >>"$GEWU_LOG_ROOT/paper_monitor_launcher.log" 2>&1
