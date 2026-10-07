"""Windows database selection, identity, exclusive access and recovery boundaries.

The INI locator is a per-user pointer. Research state and database identity live
in SQLite. Importing this module never opens a database or creates directories.
"""
from __future__ import annotations

import argparse
import atexit
import configparser
from contextlib import contextmanager, closing
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid

IDENTITY_KEY = "gewu_database_uuid"
DB_RELATIVE = Path("data/paper_monitor.sqlite")
_leases = {}
_expected = {}


def locator_path():
    return Path.home() / ".gewu-insight" / "database-location.ini"


def read_locator(path=None):
    path = Path(path or locator_path())
    if not path.exists():
        return None
    config = configparser.ConfigParser(interpolation=None)
    try:
        content = path.read_bytes()
        config.read_string(content.decode("utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"))
        section = config["database"]
        root, identity = Path(section["path"]), section["identity"]
        if not root.is_absolute() or str(uuid.UUID(identity)) != identity:
            raise ValueError("Invalid database location or identity")
        return {"workspace": str(root), "identity": identity}
    except (KeyError, ValueError, configparser.Error) as error:
        raise ValueError(f"Invalid Gewu Database locator: {path}. Select your existing database again.") from error


def save_locator(root, identity, path=None):
    path = Path(path or locator_path())
    root = Path(root).resolve(strict=True)
    check_database(root, identity)
    config = configparser.ConfigParser(interpolation=None)
    config["database"] = {"path": str(root), "identity": identity}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        with temporary.open("x", encoding="utf-16") as output:
            config.write(output)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        # Once a real locator exists, retire the legacy pointer. Losing the INI
        # must show the chooser, not silently reopen a pre-migration database.
        legacy = path.parent / "preview-workspace.txt"
        if legacy.exists():
            legacy.rename(path.parent / ("preview-workspace-retired-" + uuid.uuid4().hex + ".txt"))
    finally:
        temporary.unlink(missing_ok=True)


class FileLease:
    """FileShare.None works across Python, .NET, drives and path spellings."""
    def __init__(self, path):
        self.path = Path(path)
        self.handle = None

    def __enter__(self):
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        self.handle = kernel.CreateFileW(str(self.path), 0xC0000000, 0, None, 4, 0x80, None)
        if self.handle == ctypes.c_void_p(-1).value:
            self.handle = None
            code = ctypes.get_last_error()
            if code in (32, 33):
                raise RuntimeError("This Gewu Database is already open in another instance. Close it before continuing.")
            raise OSError(code, f"Gewu Database is unavailable or not writable: {self.path.parent}")
        return self

    def __exit__(self, *_):
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


@contextmanager
def read_connection(db):
    connection = sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    try:
        yield connection
    finally:
        connection.close()


def check_database(root, expected_identity=""):
    from .storage import STORAGE_SCHEMA_VERSION
    db = Path(root) / DB_RELATIVE
    if (Path(root) / ".gewu-migration-incomplete").exists():
        raise ValueError("This migration is incomplete. Continue using the original Gewu Database.")
    if not db.is_file():
        raise FileNotFoundError(f"Gewu Database is unavailable: {db}. Reconnect the disk or select the existing database. No empty database was created.")
    with read_connection(db) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version > STORAGE_SCHEMA_VERSION:
            raise ValueError("This Gewu Database requires a newer version of Gewu Insight.")
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"papers", "resources", "app_settings"}.issubset(tables):
            raise ValueError("This folder does not contain a valid Gewu Database.")
        row = connection.execute("SELECT value FROM app_settings WHERE key=?", (IDENTITY_KEY,)).fetchone()
        identity = str(row[0]) if row else ""
        if identity:
            uuid.UUID(identity)
        if expected_identity and identity != expected_identity:
            raise ValueError("Gewu Database identity mismatch. Select the intended database; no data was changed.")
    return version, identity


def backup_database(db, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / ("before-schema-" + uuid.uuid4().hex + ".sqlite")
    with read_connection(db) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("Pre-upgrade database backup failed verification.")
    return backup


def runtime_root(root, identity=""):
    key = identity or hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode()).hexdigest()[:32]
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "Gewu Insight" / "Databases" / key


def preserve_browser_profile(root, runtime):
    """Preserve login storage byte-for-byte, separately from disposable caches."""
    source, target = Path(root) / "webview", Path(runtime) / "Browser"
    if target.exists() or not source.exists():
        return
    # The embedded interpreter may lack the developer Python's long-path
    # manifest. Extended Win32 paths work without changing Windows settings.
    def extended(path):
        text = str(Path(path).absolute())
        if sys.platform != "win32" or text.startswith("\\\\?\\"):
            return Path(text)
        return Path("\\\\?\\UNC\\" + text[2:] if text.startswith("\\\\") else "\\\\?\\" + text)
    source = extended(source)
    target = extended(target)
    temporary = target.with_name("Browser-copy-" + uuid.uuid4().hex[:12])
    shutil.copytree(source, temporary)
    for original in source.rglob("*"):
        if original.is_file():
            copied = temporary / original.relative_to(source)
            with original.open("rb") as a, copied.open("rb") as b:
                if hashlib.file_digest(a, "sha256").digest() != hashlib.file_digest(b, "sha256").digest():
                    raise ValueError("Browser profile copy failed verification; the original is retained.")
    temporary.rename(target)


def prepare(root, *, create=False, expected_identity="", select=False, desktop_owned=False):
    root = Path(root).expanduser().resolve()
    if create:
        if root.exists() and any(root.iterdir()):
            raise ValueError("New Gewu Database requires a new or empty directory; existing files are never overwritten.")
        root.mkdir(parents=True, exist_ok=True)
    else:
        check_database(root, expected_identity)
    from contextlib import ExitStack
    with ExitStack() as stack:
        if not desktop_owned:
            stack.enter_context(FileLease(root / ".workspace.lock"))
        stack.enter_context(FileLease(root / ".gewu-database.lock"))
        from .storage import Storage, STORAGE_SCHEMA_VERSION
        db = root / DB_RELATIVE
        if not create:
            version, _ = check_database(root, expected_identity)
            with db.open("rb+"):
                pass
            if version < STORAGE_SCHEMA_VERSION:
                backup_database(db, root / "backups")
        for name in ("data", "reports", "config", "backups"):
            (root / name).mkdir(exist_ok=True)
            with tempfile.TemporaryFile(dir=root / name):
                pass
        config = root / "config/journals.json"
        if not config.exists():
            with config.open("xb") as output:
                output.write((Path(__file__).resolve().parents[1] / "config/journals.json").read_bytes())
        storage = Storage(db)
        try:
            identity = storage.get_setting(IDENTITY_KEY, "")
            if not identity:
                identity = str(uuid.uuid4())
                storage.set_setting(IDENTITY_KEY, identity)
        finally:
            storage.close()
        runtime = runtime_root(root, identity)
        runtime.mkdir(parents=True, exist_ok=True)
        stack.enter_context(FileLease(runtime / ".database-session.lock"))
        preserve_browser_profile(root, runtime)
        if select:
            save_locator(root, identity)
        return {"workspace": str(root), "identity": identity, "runtime": str(runtime)}


def acquire_session(db, expected_identity=""):
    """Own the database for the process lifetime; never create a missing DB."""
    db = Path(db).resolve()
    if db in _leases:
        return
    root = db.parent.parent
    _, identity = check_database(root, expected_identity)
    from contextlib import ExitStack
    leases = ExitStack()
    try:
        if not os.environ.get("GEWU_DESKTOP_HOST"):
            leases.enter_context(FileLease(root / ".workspace.lock"))
        leases.enter_context(FileLease(root / ".gewu-database.lock"))
        runtime = runtime_root(root, identity)
        runtime.mkdir(parents=True, exist_ok=True)
        leases.enter_context(FileLease(runtime / ".database-session.lock"))
        version, _ = check_database(root, expected_identity)
        from .storage import STORAGE_SCHEMA_VERSION
        if version < STORAGE_SCHEMA_VERSION:
            backup_database(db, root / "backups")
    except Exception:
        leases.close()
        raise
    _leases[db] = leases
    _expected[db] = identity
    atexit.register(leases.close)


def guard_storage(db):
    db = Path(db).resolve()
    if db in _expected:
        check_database(db.parent.parent, _expected[db])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "locate"])
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--identity", default="")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--desktop-owned", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.operation == "locate":
            result = read_locator()
        else:
            if not args.workspace or not args.workspace.is_absolute():
                raise ValueError("Select an absolute Gewu Database directory.")
            os.environ["GEWU_WORKSPACE_ROOT"] = str(args.workspace)
            os.environ["GEWU_DATA_ROOT"] = str(args.workspace / "data")
            result = prepare(args.workspace, create=args.create, expected_identity=args.identity,
                             select=args.select, desktop_owned=args.desktop_owned)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
