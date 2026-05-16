#!/bin/bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"

cd "$PROJECT_DIR"

if [ -f ".venv/bin/python" ]; then
  PYTHON_BIN="$(pwd)/.venv/bin/python"
else
  PYTHON_BIN="$(/usr/bin/env which python3)"
fi

"$PYTHON_BIN" -m paper_monitor journal
