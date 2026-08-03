#!/bin/zsh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PORT="${PAPER_MONITOR_PORT:-8765}"
HOST="${PAPER_MONITOR_HOST:-127.0.0.1}"
URL="http://$HOST:$PORT"

echo "Gewu Insight diagnostics"
echo "Project: $PROJECT_DIR"
echo "URL: $URL"
echo ""

failures=0

check() {
  local label="$1"
  shift
  if "$@" >/dev/null 2>&1; then
    echo "OK   $label"
  else
    echo "FAIL $label"
    failures=$((failures + 1))
  fi
}

check "Gewu Insight app exists" test -d "$PROJECT_DIR/Gewu Insight.app"
check "bootstrap script exists" test -f "$PROJECT_DIR/scripts/bootstrap_macos.sh"
check "requirements.txt exists" test -f "$PROJECT_DIR/requirements.txt"
check "python3 is available" /usr/bin/env python3 --version

case "$PROJECT_DIR" in
  "$HOME/Desktop"|"$HOME/Desktop"/*|"$HOME/Documents"|"$HOME/Documents"/*|"$HOME/Downloads"|"$HOME/Downloads"/*)
    echo "WARN Project is inside a macOS protected folder; move it outside Desktop/Documents/Downloads for Finder launch."
    ;;
esac

if /usr/bin/env python3 --version >/dev/null 2>&1; then
  PYTHON_BIN="$(/usr/bin/env which python3)"
  echo "python3: $PYTHON_BIN"
  "$PYTHON_BIN" --version
  check "python3 can create venv" "$PYTHON_BIN" -m venv --help
fi

if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
  echo ".venv: present"
  "$PROJECT_DIR/.venv/bin/python" -m pip --version || true
else
  echo ".venv: not created yet"
fi

if /usr/bin/curl -fsS "$URL" >/dev/null 2>&1; then
  echo "UI server: running at $URL"
else
  echo "UI server: not running at $URL"
fi

echo ""
echo "Recent launcher log:"
if [ -f "$PROJECT_DIR/logs/paper_monitor_launcher.log" ]; then
  /usr/bin/tail -n 40 "$PROJECT_DIR/logs/paper_monitor_launcher.log"
else
  echo "No launcher log yet."
fi

echo ""
if [ "$failures" -eq 0 ]; then
  echo "Diagnostics finished: no basic setup failures found."
else
  echo "Diagnostics finished: $failures setup check(s) failed."
fi
