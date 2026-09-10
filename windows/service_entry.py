"""Embedded service entry point; all writable state belongs to the workspace."""
import os
from pathlib import Path

# Keep the DLL search handle alive for pywin32; never use the user's Python path.
_dll_path = Path(__file__).parent / "Lib" / "site-packages" / "pywin32_system32"
_dll_directory = os.add_dll_directory(str(_dll_path)) if _dll_path.is_dir() else None

from paper_monitor.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
