"""Conservative offline relocation of a Windows workspace, never an in-place move.

Only verified, scalar operational paths are rewritten. Unknown embedded paths,
reparse points, missing managed files and unrecognized shortcuts stop the copy.
This is not the macOS Library importer. The caller switches the saved selection
only after this function returns, and retains the source for rollback.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys

from . import desktop_files


PATH_COLUMNS = {
    ("papers", "main_pdf_path"), ("papers", "merged_pdf_path"),
    ("papers", "analysis_path"), ("resources", "stored_path"),
    ("author_monitors", "avatar_override_path"),
}
DB_RELATIVE = Path("data/paper_monitor.sqlite")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def workspace_lock(root: Path):
    """Share the desktop's exclusive lock; fail if the application is open."""
    if sys.platform != "win32":
        raise OSError("Workspace relocation currently requires Windows.")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateFileW(str(root / ".workspace.lock"), 0xC0000000, 0, None, 4, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "Close Gewu Insight before relocating its Library.")
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def contains_root(value: object, root: Path) -> bool:
    if isinstance(value, dict):
        return any(contains_root(item, root) for item in [*value.keys(), *value.values()])
    if isinstance(value, list):
        return any(contains_root(item, root) for item in value)
    if not isinstance(value, str):
        return False
    # Detect both scalar paths and escaped paths inside JSON, but never mutate
    # arbitrary text/JSON/provenance. Unhandled references need an explicit plan.
    normalized = value.replace("\\\\", "\\").replace("\\", "/").casefold()
    if str(root).replace("\\", "/").casefold() in normalized:
        return True
    if value.lstrip().startswith(("[", "{", '"')):
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            return False
        return parsed != value and contains_root(parsed, root)
    return False


def relocated_path(value: str, source: Path, destination: Path) -> Path:
    old = Path(value)
    if not old.is_absolute():
        raise ValueError("Managed path must be absolute.")
    relative = old.resolve(strict=True).relative_to(source)
    if not old.is_file():
        raise ValueError("Managed path does not identify a file.")
    return destination / relative


def database_plan(connection, source: Path, destination: Path):
    changes = []
    snapshots = {}
    for (table,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        columns = [row[1] for row in connection.execute(f"PRAGMA table_info({quoted(table)})")]
        rows = connection.execute(f"SELECT rowid, * FROM {quoted(table)} ORDER BY rowid").fetchall()
        expected = []
        for row in rows:
            revised = list(row[1:])
            for index, column in enumerate(columns):
                value = revised[index]
                if not contains_root(value, source):
                    continue
                if (table, column) not in PATH_COLUMNS:
                    raise ValueError(f"Unplanned workspace reference in {table}.{column}; source unchanged.")
                new = str(relocated_path(value, source, destination))
                revised[index] = new
                changes.append((table, column, row[0], value, new))
            expected.append(tuple(revised))
        snapshots[table] = expected
    return changes, snapshots


def relocate(source: Path, destination: Path) -> dict:
    """Copy and verify an offline workspace. Never delete source or select copy.

    A failed destination is deliberately retained for diagnosis, and cannot be
    reused on retry. Only a successful return is permission to select the copy.
    """
    source = source.resolve(strict=True)
    destination = destination.absolute()
    if destination.exists():
        raise FileExistsError("Destination must not exist; no existing files will be overwritten.")
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and destination must be separate directories.")
    # Reject destination-parent junctions, avoiding another logical/physical root.
    if destination.parent.resolve(strict=True) != destination.parent:
        raise ValueError("Destination parent must be its physical directory.")
    db_source = source / DB_RELATIVE
    with workspace_lock(source):
        # Prevent CLI/service database writes as well as another desktop start.
        guard = sqlite3.connect(db_source.as_uri() + "?mode=rw", uri=True, timeout=1)
        read = sqlite3.connect(db_source.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            guard.execute("BEGIN IMMEDIATE")
            if read.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise ValueError("Source database failed integrity_check.")
            original_fk = read.execute("PRAGMA foreign_key_check").fetchall()
            changes, expected = database_plan(read, source, destination)
            paths = sorted(source.rglob("*"))
            files = []
            links = {}
            excluded = {DB_RELATIVE, Path(str(DB_RELATIVE) + "-wal"),
                        Path(str(DB_RELATIVE) + "-shm"), Path(str(DB_RELATIVE) + "-journal"),
                        Path(".workspace.lock")}
            for path in paths:
                relative = path.relative_to(source)
                if relative in excluded:
                    continue
                if path.is_symlink() or path.is_junction():
                    raise ValueError(f"Reparse entry requires a separate plan: {relative}")
                if path.is_file():
                    if path.suffix.lower() == ".lnk":
                        target = desktop_files.managed_link_target(path)
                        if target is None:
                            raise ValueError(f"Unrecognized shortcut: {relative}")
                        if not target.is_file():
                            raise FileNotFoundError(f"Missing shortcut target: {relative}")
                        target = target.resolve(strict=True)
                        mapped = destination / target.relative_to(source) if target.is_relative_to(source) else target
                        links[relative] = (target, mapped)
                    files.append((relative, digest(path)))
            destination.mkdir()  # Exclusive creation; no overwrite/merge.
            with workspace_lock(destination):
                for path in paths:
                    relative = path.relative_to(source)
                    if relative not in excluded and path.is_dir():
                        (destination / relative).mkdir(parents=True, exist_ok=True)
                for relative, _ in files:
                    shutil.copy2(source / relative, destination / relative)
                copy = sqlite3.connect(destination / DB_RELATIVE)
                try:
                    read.backup(copy)
                    # The byte-preserving backup retains schema, rowids, all
                    # identities and all associations. Update just planned cells.
                    # Relocation is not a paper edit: suppress edit-trigger side
                    # effects on this connection only, preserving cache revisions
                    # and trigger definitions. Re-enable even on rollback.
                    copy.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, False)
                    try:
                        with copy:
                            for table, column, rowid, old, new in changes:
                                cursor = copy.execute(f"UPDATE {quoted(table)} SET {quoted(column)}=? WHERE rowid=? AND {quoted(column)}=?", (new, rowid, old))
                                if cursor.rowcount != 1:
                                    raise ValueError("Database changed during relocation.")
                    finally:
                        copy.setconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER, True)
                    for relative, (old, new) in links.items():
                        if old == new:
                            continue
                        import pythoncom
                        with desktop_files.shell_link() as link:
                            persist = link.QueryInterface(pythoncom.IID_IPersistFile)
                            persist.Load(str(destination / relative), 0)
                            link.SetPath(str(new))
                            link.SetWorkingDirectory(str(new.parent))
                            persist.Save(str(destination / relative), 1)
                    desktop_files._link_target.cache_clear()
                    for relative, expected_hash in files:
                        if digest(source / relative) != expected_hash:
                            raise ValueError(f"Source file changed: {relative}")
                        if relative in links:
                            old, new = links[relative]
                            if desktop_files.managed_link_target(destination / relative) != new or not new.is_file():
                                raise ValueError(f"Shortcut verification failed: {relative}")
                            if digest(old) != digest(new):
                                raise ValueError(f"Shortcut target content changed: {relative}")
                            if old != new:
                                continue
                        if digest(destination / relative) != expected_hash:
                            raise ValueError(f"Copied content changed: {relative}")
                    for table, rows in expected.items():
                        actual = copy.execute(f"SELECT * FROM {quoted(table)} ORDER BY rowid").fetchall()
                        if actual != rows:
                            raise ValueError(f"Unexpected database changes in {table}.")
                    if copy.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                        raise ValueError("Copied database failed integrity_check.")
                    if Counter(copy.execute("PRAGMA foreign_key_check").fetchall()) != Counter(original_fk):
                        raise ValueError("Foreign key violations changed.")
                    for _, _, _, old, new in changes:
                        if digest(Path(old)) != digest(Path(new)):
                            raise ValueError("Managed resource hash mismatch.")
                    schema_sql = "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name"
                    if copy.execute(schema_sql).fetchall() != read.execute(schema_sql).fetchall():
                        raise ValueError("Database schema changed.")
                    copy.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    copy.close()
            return {"source": str(source), "destination": str(destination),
                    "files_verified": len(files), "shortcuts_verified": len(links),
                    "shortcuts_retargeted": sum(old != new for old, new in links.values()),
                    "path_cells_updated": len(changes), "tables_compared": len(expected),
                    "counts": {t: len(rows) for t, rows in expected.items()},
                    "existing_foreign_key_violations": len(original_fk),
                    "integrity_check": "ok", "source_retained": True,
                    "selection_changed": False}
        finally:
            read.close()
            guard.rollback()
            guard.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path,
                        help="New diagnostic report file; never used as Library data.")
    args = parser.parse_args()
    if args.report.exists():
        parser.error("Report already exists; choose a new path.")
    result = relocate(args.source, args.destination)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False, indent=2))
