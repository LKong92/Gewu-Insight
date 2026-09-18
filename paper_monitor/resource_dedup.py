"""Exact-file reuse within one paper; provenance is separate from file identity."""
from __future__ import annotations

import json
from functools import wraps
from pathlib import Path

from .resource_fingerprint import sha256_for_file
from .time_utils import now_iso


def serialize_writes(function):
    @wraps(function)
    def locked(storage, *args, **kwargs):
        from .download import paper_download_lock
        paper_id = storage.resolve_paper_id(kwargs.get('paper_id') or '')
        with paper_download_lock(storage.db_path, paper_id):
            return function(storage, *args, **kwargs)
    return locked


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS resource_import_sources (
        resource_id INTEGER NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
        source_path TEXT NOT NULL, size_bytes INTEGER, kind TEXT,
        sha256 TEXT NOT NULL, import_batch_id TEXT, record_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY(resource_id, source_path, sha256))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_resource_import_source ON resource_import_sources(source_path, size_bytes, kind)")
    conn.execute("""CREATE TABLE IF NOT EXISTS resource_duplicate_archive (
        resource_id INTEGER PRIMARY KEY, survivor_id INTEGER NOT NULL,
        record_json TEXT NOT NULL, backup_directory TEXT NOT NULL, merged_at TEXT NOT NULL)""")
    # Existing legacy duplicates are repaired separately with a backup. These
    # guards prevent new exact-path duplicates without rewriting old rows.
    for action in ("INSERT", "UPDATE OF paper_id, stored_path"):
        name = "insert" if action == "INSERT" else "update"
        exclusion = "" if name == "insert" else "AND id != NEW.id"
        changed = "" if name == "insert" else "AND (NEW.paper_id IS NOT OLD.paper_id OR NEW.stored_path IS NOT OLD.stored_path)"
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS resource_path_unique_{name}
            BEFORE {action} ON resources
            WHEN NEW.paper_id IS NOT NULL AND COALESCE(NEW.stored_path, '') != ''
              {changed}
              AND EXISTS (SELECT 1 FROM resources WHERE paper_id=NEW.paper_id
                  AND stored_path=NEW.stored_path {exclusion})
            BEGIN SELECT RAISE(ABORT, 'Duplicate Paper File path'); END""")


def local_path(resource):
    return str(resource.get("stored_path") or resource.get("source_path") or "")


def find_existing(storage, paper_id, path, *, exact_content=True):
    """Verify current bytes, never trust an old digest after edits in Preview."""
    path = Path(path).expanduser()
    if not path.is_file():
        return None
    stat = path.stat()
    digest = None
    rows = storage.conn.execute("SELECT * FROM resources WHERE paper_id=? ORDER BY id", (paper_id,))
    for row in rows:
        resource = dict(row)
        if not local_path(resource):
            continue
        candidate = Path(local_path(resource)).expanduser()
        try:
            if not candidate.is_file():
                continue
            if candidate.samefile(path):
                return resource
            if not exact_content or candidate.stat().st_size != stat.st_size:
                continue
            digest = digest or sha256_for_file(path)
            if sha256_for_file(candidate) == digest:
                return resource
        except OSError:
            continue
    return None


def find_content(storage, paper_id, digest, size):
    for row in storage.conn.execute('SELECT * FROM resources WHERE paper_id=? ORDER BY id', (paper_id,)):
        resource = dict(row)
        if not local_path(resource):
            continue
        path = Path(local_path(resource)).expanduser()
        try:
            if path.is_file() and path.stat().st_size == size and sha256_for_file(path) == digest:
                return resource
        except OSError:
            continue
    return None


def remember_source(storage, resource_id, record, digest, batch_id=""):
    source = str(record.get("source_path") or "")
    if not source:
        return
    storage.conn.execute("""INSERT OR IGNORE INTO resource_import_sources
        (resource_id, source_path, size_bytes, kind, sha256, import_batch_id, record_json, created_at)
        VALUES(?,?,?,?,?,?,?,?)""", (resource_id, source, record.get("size_bytes"),
        record.get("kind"), digest or "", batch_id or record.get("import_batch_id"),
        json.dumps(record, ensure_ascii=False), now_iso()))


def source_resources(storage, record):
    """Include earlier source locations after a file was reused or reassigned."""
    return [dict(row) for row in storage.conn.execute("""SELECT DISTINCT r.* FROM resources r
        LEFT JOIN resource_import_sources s ON s.resource_id=r.id
        WHERE (r.source_path=? AND r.size_bytes=? AND r.kind=?)
           OR (s.source_path=? AND s.size_bytes=? AND s.kind=?)
        ORDER BY r.id DESC""", (record['source_path'], record['size_bytes'], record['kind']) * 2)]
