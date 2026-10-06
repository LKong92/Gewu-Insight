#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
if [[ -f "$PROJECT_DIR/.gewu-development-only" ]]; then
  echo "Formal data has moved. Open /Applications/Gewu Insight.app for daily use." >&2
  echo "For development, use the explicit isolated workspace commands in docs/DEVELOPMENT.md." >&2
  exit 1
fi
PORT="${PAPER_MONITOR_PORT:-8765}"
HOST="${PAPER_MONITOR_HOST:-127.0.0.1}"
URL="http://$HOST:$PORT"
HEALTH_URL="$URL/api/health"
LOG_DIR="$PROJECT_DIR/logs"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
REQ_FILE="$PROJECT_DIR/requirements.txt"
REQ_STAMP="$VENV_DIR/.paper_monitor_requirements_installed"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data" "$PROJECT_DIR/reports"
cd "$PROJECT_DIR"

ACCESS_PROBE="$PROJECT_DIR/data/.paper_monitor_access_probe"
if ! touch "$ACCESS_PROBE" || ! rm -f "$ACCESS_PROBE"; then
  echo "This app cannot write to the project data folder. macOS may be blocking access to this location." >&2
  echo "Grant Files and Folders permission for Gewu Insight/Python in System Settings, or move the project to a regular folder such as $HOME/Applications or $HOME/PaperMonitor." >&2
  exit 1
fi

if [ ! -x "$PYTHON_BIN" ]; then
  SYSTEM_PYTHON="$(/usr/bin/env which python3 || true)"
  if [ -z "$SYSTEM_PYTHON" ]; then
    echo "python3 was not found. Install Python 3 from https://www.python.org/downloads/macos/ or Homebrew, then open Gewu Insight again." >&2
    exit 1
  fi
  "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
fi

if [ ! -f "$REQ_STAMP" ] || [ "$REQ_FILE" -nt "$REQ_STAMP" ]; then
  if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    "$PYTHON_BIN" -m ensurepip --upgrade
  fi
  echo "Installing Gewu Insight dependencies..."
  "$PYTHON_BIN" -m pip install -r "$REQ_FILE"
  touch "$REQ_STAMP"
fi

if ! /usr/bin/curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
  echo "Starting Gewu Insight UI at $URL"
  exec "$PYTHON_BIN" -m paper_monitor ui --host "$HOST" --port "$PORT" --open
fi

/usr/bin/open "$URL"
