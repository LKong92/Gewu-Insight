"""Database location and startup checks, independent of the App's location.

The locator is a machine preference. SQLite remains authoritative for identity
and research state. Importing this module never creates or opens a database.
"""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import sqlite3
import uuid

SUPPORT_ROOT = Path.home() / "Library/Application Support/Gewu Insight"
LOCATOR_PATH = SUPPORT_ROOT / "database-location.plist"
IDENTITY_KEY = "gewu_database_uuid"
_locks = {}


def read_locator(path=LOCATOR_PATH):
    if not Path(path).exists():
        return {}
    with Path(path).open("rb") as stream:
        value = plistlib.load(stream)
    if not isinstance(value, dict) or not isinstance(value.get("workspace"), str):
        raise ValueError("Invalid database location. Open Gewu Insight and locate your database again.")
    return value


def save_locator(workspace, identity, path=LOCATOR_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            os.chmod(temporary, 0o600)
            plistlib.dump({"workspace": str(Path(workspace).resolve()), "database_uuid": identity}, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def database_identity(db):
    if not Path(db).is_file():
        return ""
    with sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='app_settings'").fetchone():
            return ""
        row = connection.execute("SELECT value FROM app_settings WHERE key=?", (IDENTITY_KEY,)).fetchone()
        return row[0] if row else ""


def check_database(db, *, expected_identity=""):
    from .storage import STORAGE_SCHEMA_VERSION
    db = Path(db)
    if not db.is_file():
        raise FileNotFoundError("The selected database is unavailable. Reconnect its disk or locate it again; no empty database was created.")
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"papers", "resources", "app_settings"}.issubset(tables):
            raise ValueError("This folder does not contain a Gewu database.")
        if version > STORAGE_SCHEMA_VERSION:
            raise ValueError("This database needs a newer version of Gewu Insight.")
    if expected_identity and database_identity(db) != expected_identity:
        raise ValueError("The database at this location has a different identity. Locate the intended database again.")
    return version


def acquire_database_lock(db):
    """Hold an advisory lock for the entire CLI/server lifetime."""
    db = Path(db).resolve()
    if db in _locks:
        return
    db.parent.mkdir(parents=True, exist_ok=True)
    stream = (db.parent / ".gewu-database.lock").open("a+")
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0)
            if not stream.read(1):
                stream.write("0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError("This database is already open in another Gewu process. Quit it before continuing.")
    _locks[db] = stream


def prepare_workspace(workspace, code_root, *, create=False, expected_identity=""):
    from .storage import Storage, STORAGE_SCHEMA_VERSION
    workspace, code_root = Path(workspace).resolve(), Path(code_root).resolve()
    db = workspace / "data/paper_monitor.sqlite"
    if create:
        if workspace.exists() and any(workspace.iterdir()):
            raise ValueError("Create New Database requires an empty folder.")
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    else:
        version = check_database(db, expected_identity=expected_identity)
    acquire_database_lock(db)
    if not create and version < STORAGE_SCHEMA_VERSION:
        backup = workspace / "backups" / ("before-schema-" + str(STORAGE_SCHEMA_VERSION) + "-" + uuid.uuid4().hex + ".sqlite")
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as source, sqlite3.connect(backup) as target:
            source.backup(target)
    for name in ("config", "reports", "backups"):
        (workspace / name).mkdir(exist_ok=True, mode=0o700)
    target = workspace / "config/journals.json"
    try:
        with target.open("xb") as stream:
            stream.write((code_root / "config/journals.json").read_bytes())
    except FileExistsError:
        pass
    storage = Storage(db)
    try:
        identity = storage.get_setting(IDENTITY_KEY, "")
        if not identity:
            identity = str(uuid.uuid4())
            storage.set_setting(IDENTITY_KEY, identity)
    finally:
        storage.close()
    return identity


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Create an isolated development database. Does not change the installed App location.')
    parser.add_argument('operation', choices=['create'])
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    root = args.directory.expanduser().resolve()
    os.environ['GEWU_WORKSPACE_ROOT'] = str(root)
    os.environ['GEWU_DATA_ROOT'] = str(root / 'data')
    identity = prepare_workspace(root, Path(__file__).resolve().parents[1], create=True)
    print('Created Gewu Database:', root)
    print('Database identity:', identity)


if __name__ == '__main__':
    main()
