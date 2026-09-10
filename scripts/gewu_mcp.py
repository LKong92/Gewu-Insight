"""Portable stdio entry point; does not initialize SQLite or start the UI."""
from pathlib import Path
import os
import sys

# Embedded Windows Python does not run site/pywin32 bootstrap. Keep the
# bundled DLL search handle alive for private delivery-directory permissions.
_dll_path = Path(sys.executable).resolve().parent / 'Lib' / 'site-packages' / 'pywin32_system32'
_dll_directory = os.add_dll_directory(str(_dll_path)) if sys.platform == 'win32' and _dll_path.is_dir() else None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paper_monitor.mcp_server import main

if __name__ == '__main__':
    raise SystemExit(main())
