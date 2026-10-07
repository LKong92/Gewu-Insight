"""Open a compatible Windows desktop shell with the local Python/web source."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHELL_VERSION = (0, 1, 21)


def workspace_path(explicit: Path | None, *, create: bool = False) -> Path:
    if explicit is not None:
        workspace = explicit.expanduser().resolve()
        if not create and not (workspace / "data/paper_monitor.sqlite").is_file():
            raise ValueError("Library not found. Use --new-workspace only to create a new Library.")
        if create and workspace.exists() and any(workspace.iterdir()):
            raise ValueError("A new workspace must be an empty directory.")
        return workspace
    # Development never reads the installed application's database locator.
    import hashlib
    key = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Gewu Insight" / "Development" / key



class WorkspaceLock:
    """Share the native launcher's FileShare.None lock, including across processes."""

    def __init__(self, workspace: Path):
        self.path = workspace / ".workspace.lock"
        self.handle = None
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                           ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                           wintypes.HANDLE]
        self.kernel.CreateFileW.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL

    def __enter__(self):
        # GENERIC_READ | GENERIC_WRITE, no sharing, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL.
        handle = self.kernel.CreateFileW(str(self.path), 0xC0000000, 0, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            code = ctypes.get_last_error()
            if code == 32:
                raise RuntimeError("This Library is already open. Close the desktop App or stop the Source Web service first.")
            raise ctypes.WinError(code)
        self.handle = handle
        return self

    def __exit__(self, *_):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def desktop_executable(explicit: Path | None = None) -> Path:
    version = ".".join(map(str, SOURCE_SHELL_VERSION))
    local = ROOT / f"dist/windows-preview-{version}/Gewu Insight.exe"
    installed = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Gewu Insight Preview/Gewu Insight.exe"
    executable = (explicit or (local if local.is_file() else installed)).resolve()
    if not executable.is_file():
        raise FileNotFoundError("The Gewu Insight desktop shell was not found. Use --desktop-exe to select a complete existing desktop build.")
    import win32api
    info = win32api.GetFileVersionInfo(str(executable.with_suffix(".dll")), "\\")
    actual = (info["FileVersionMS"] >> 16, info["FileVersionMS"] & 0xffff, info["FileVersionLS"] >> 16)
    if actual < SOURCE_SHELL_VERSION:
        raise RuntimeError(f"This source needs desktop shell {version} or later; found {'.'.join(map(str, actual))}. No older shell or browser fallback was started.")
    return executable


def desktop_launch(workspace: Path, executable: Path | None = None) -> int:
    executable = desktop_executable(executable)
    # The shell resolves Help files relative to --source. Python imports the
    # checkout itself through PYTHONPATH; no source or runtime is copied.
    working = ROOT / "windows"
    for required in (ROOT / "paper_monitor/__main__.py", working / "Windows_Preview_Guide.html",
                     working / "Windows_Preview_Guide.pdf", working / "PREVIEW.txt"):
        if not required.is_file():
            raise FileNotFoundError(f"Required source file is missing: {required}")
    if (working / "service/python.exe").exists():
        raise RuntimeError("A bundled service inside windows/ would override the source interpreter. Use a clean source checkout.")
    # Give a useful error before creating another window. The native shell then
    # acquires this same lock for its entire lifetime, including racing launches.
    with WorkspaceLock(workspace):
        pass
    environment = os.environ.copy()
    environment.pop("PYTHONHOME", None)
    environment.update(PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    command = [str(executable), "--source", str(working), "--python", sys.executable,
               "--workspace", str(workspace)]
    process = subprocess.Popen(command, cwd=working, env=environment,
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    print(f"Opened Gewu Insight desktop (PID {process.pid}).\nSource: {ROOT}\nLibrary: {workspace}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, help="Existing Library root (contains data/paper_monitor.sqlite).")
    parser.add_argument("--new-workspace", action="store_true", help="Create an empty Library at --workspace.")
    parser.add_argument("--desktop-exe", type=Path, help="Existing desktop shell; prefers local 0.1.21, then the installed Preview (minimum 0.1.21).")
    parser.add_argument("--web", action="store_true", help="Use the optional external-browser interface instead of the desktop shell.")
    parser.add_argument("--port", type=int, default=0, help="Loopback port; 0 chooses an available port.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the default browser (diagnostics).")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        parser.error("This launcher is for Windows. Use python -m paper_monitor ui --open on other systems.")
    if args.new_workspace and args.workspace is None:
        parser.error("--new-workspace requires --workspace.")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535.")
    if not args.web and (args.no_open or args.port):
        parser.error("--no-open and --port are available only with --web.")
    if args.web and args.desktop_exe:
        parser.error("--desktop-exe cannot be combined with --web.")
    try:
        workspace = workspace_path(args.workspace, create=args.new_workspace)
        sys.path.insert(0, str(ROOT))
        from paper_monitor.windows_database import prepare
        os.environ["GEWU_WORKSPACE_ROOT"] = str(workspace)
        os.environ["GEWU_DATA_ROOT"] = str(workspace / "data")
        prepared = prepare(workspace, create=args.new_workspace or (args.workspace is None and not workspace.exists()))
        os.environ["GEWU_DATABASE_IDENTITY"] = prepared["identity"]
        os.environ["GEWU_RUNTIME_ROOT"] = prepared["runtime"]
        if not args.web:
            return desktop_launch(workspace, args.desktop_exe)
        from paper_monitor.windows_database import acquire_session
        acquire_session(workspace / "data/paper_monitor.sqlite", prepared["identity"])
        if args.web:
            # Set these before importing product modules, whose defaults are computed on import.
            os.environ["GEWU_WORKSPACE_ROOT"] = str(workspace)
            os.environ["GEWU_DATA_ROOT"] = str(workspace / "data")
            sys.path.insert(0, str(ROOT))
            os.chdir(ROOT)
            print("Gewu Insight - Source Web", flush=True)
            print(f"Source: {ROOT}\nLibrary: {workspace}", flush=True)
            print("Keep this window open. Press Ctrl+C to stop before updating source or opening the desktop App.", flush=True)
            from paper_monitor.ui_server import run_ui_server
            run_ui_server(host="127.0.0.1", port=args.port,
                          db_path=workspace / "data/paper_monitor.sqlite",
                          open_browser=not args.no_open)
    except KeyboardInterrupt:
        print("\nSource Web stopped.")
        return 0
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"Gewu Insight could not start: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
