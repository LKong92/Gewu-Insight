"""Portable stdio entry point; does not initialize SQLite or start the UI."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_monitor.mcp_server import main

if __name__ == '__main__':
    raise SystemExit(main())
