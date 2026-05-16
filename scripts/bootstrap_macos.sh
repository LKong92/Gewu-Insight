#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PORT="${PAPER_MONITOR_PORT:-8765}"
HOST="${PAPER_MONITOR_HOST:-127.0.0.1}"
URL="http://$HOST:$PORT"
LOG_DIR="$PROJECT_DIR/logs"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"
REQ_FILE="$PROJECT_DIR/requirements.txt"
REQ_STAMP="$VENV_DIR/.paper_monitor_requirements_installed"

mkdir -p "$LOG_DIR" "$PROJECT_DIR/data" "$PROJECT_DIR/reports"
cd "$PROJECT_DIR"

case "$PROJECT_DIR" in
  "$HOME/Desktop"|"$HOME/Desktop"/*|"$HOME/Documents"|"$HOME/Documents"/*|"$HOME/Downloads"|"$HOME/Downloads"/*)
    echo "This project is inside Desktop, Documents, or Downloads. macOS may block Finder-launched Python from reading these protected folders." >&2
    echo "Move the whole PaperMonitor folder to a regular folder such as $HOME/Applications or $HOME/PaperMonitor, then try again." >&2
    exit 1
    ;;
esac

if [ ! -x "$PYTHON_BIN" ]; then
  SYSTEM_PYTHON="$(/usr/bin/env which python3 || true)"
  if [ -z "$SYSTEM_PYTHON" ]; then
    echo "python3 was not found. Install Python 3 from https://www.python.org/downloads/macos/ or Homebrew, then open Paper Monitor again." >&2
    exit 1
  fi
  "$SYSTEM_PYTHON" -m venv "$VENV_DIR"
fi

if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
  "$PYTHON_BIN" -m ensurepip --upgrade
fi

if [ ! -f "$REQ_STAMP" ] || [ "$REQ_FILE" -nt "$REQ_STAMP" ]; then
  echo "Installing Paper Monitor dependencies..."
  "$PYTHON_BIN" -m pip install -r "$REQ_FILE"
  touch "$REQ_STAMP"
fi

if ! /usr/bin/curl -fsS "$URL" 2>/dev/null | /usr/bin/grep -q "Paper Monitor"; then
  echo "Starting Paper Monitor UI at $URL"
  exec "$PYTHON_BIN" -m paper_monitor ui --host "$HOST" --port "$PORT" --open
fi

/usr/bin/open "$URL"
