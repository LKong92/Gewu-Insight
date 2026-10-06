"""Bounded, connection-owned binary staging. Committed imports consume staging."""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .ai_contract import UPLOAD_SCOPES
from .ai_store import authenticate, fail, utc_now

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
MAX_STAGED_BYTES = 512 * 1024 * 1024
MAX_STAGED_FILES = 16
LOCK = threading.RLock()
ACTIVE = set()


def filename(value):
    if (not isinstance(value, str) or not value.strip() or value in ('.', '..')
            or '/' in value or '\\' in value or any(ord(c) < 32 for c in value)
            or len(value.encode('utf-8')) > 220):
        fail(400, 'invalid_filename', 'Provide a filename of at most 220 UTF-8 bytes, without a directory.')
    return value


def request_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', value):
        fail(400, 'invalid_request_id', 'Use a stable request_id of 8–100 letters, digits, underscores or hyphens.')
    return value


def require_upload(grant):
    if not set(grant['scopes']).intersection(UPLOAD_SCOPES):
        fail(403, 'permission_required', 'File uploads require an import or Add Paper Files permission.')


def path_for(storage, upload_id):
    if not isinstance(upload_id, str) or not re.fullmatch(r'upload_[0-9a-f]{32}', upload_id):
        fail(400, 'invalid_upload', 'Use the upload_id returned by upload_file.')
    return storage.db_path.parent / '.ai-uploads' / (upload_id + '.bin')


def prune(storage):
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec='microseconds')
    for row in storage.conn.execute("SELECT * FROM ai_uploads WHERE status IN ('uploading','ready')").fetchall():
        active_key = (str(storage.db_path.resolve()), row['upload_id'])
        if active_key not in ACTIVE and (row['status'] == 'uploading' or row['created_at'] < cutoff):
            path_for(storage, row['upload_id']).unlink(missing_ok=True)
            storage.conn.execute("UPDATE ai_uploads SET status='released' WHERE upload_id=?", (row['upload_id'],))
    # Receipts for consumed uploads remain so interrupted responses can be retried.
    storage.conn.commit()


def quota(storage, grant):
    rows = storage.conn.execute("SELECT upload_id,size_bytes,filename,status FROM ai_uploads WHERE connection_id=? AND status IN ('uploading','ready')", (grant['id'],)).fetchall()
    size = sum(r['size_bytes'] for r in rows)
    return {'used_bytes': size, 'remaining_bytes': max(0, MAX_STAGED_BYTES-size),
            'used_files': len(rows), 'remaining_files': max(0, MAX_STAGED_FILES-len(rows)),
            'max_bytes': MAX_STAGED_BYTES, 'max_files': MAX_STAGED_FILES, 'max_file_bytes': MAX_UPLOAD_BYTES,
            'uploads': [dict(r) for r in rows]}


def receive(storage, authorization, stream, *, name, length, digest, retry_id):
    grant = authenticate(storage, authorization); require_upload(grant)
    name = filename(name); retry_id = request_id(retry_id)
    if type(length) is not int or not 0 < length <= MAX_UPLOAD_BYTES:
        fail(413, 'file_too_large', f'Upload one nonempty file of at most {MAX_UPLOAD_BYTES // 1024**2} MiB.')
    if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest):
        fail(400, 'invalid_hash', 'Provide the file SHA-256 before uploading.')
    with LOCK:
        prune(storage)
        prior = storage.conn.execute('SELECT * FROM ai_uploads WHERE connection_id=? AND request_id=?', (grant['id'], retry_id)).fetchone()
        if prior:
            if (prior['filename'], prior['size_bytes'], prior['sha256']) != (name, length, digest):
                fail(409, 'request_conflict', 'This upload request_id belongs to different file bytes or a different filename.')
            if prior['status'] in ('ready', 'consumed'):
                # Drain the retried body without retaining it; content hash is checked below.
                upload_id = prior['upload_id']; destination = None
            elif prior['status'] == 'uploading':
                fail(409, 'upload_busy', 'This upload is still running. Retry the same request later.')
            else:
                storage.conn.execute('DELETE FROM ai_uploads WHERE upload_id=?', (prior['upload_id'],)); storage.conn.commit()
                prior = None
        if not prior:
            available = quota(storage, grant)
            if available['remaining_bytes'] < length or available['remaining_files'] < 1:
                fail(429, 'upload_capacity', 'Temporary uploads are full. Import ready uploads or release unused uploads, then retry; no reconnect is needed.')
            upload_id = 'upload_' + secrets.token_hex(16)
            destination = path_for(storage, upload_id)
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            from .local_access import protect_directory
            protect_directory(destination.parent)
            storage.conn.execute('INSERT INTO ai_uploads VALUES(?,?,?,?,?,?,?,?)',
                (upload_id, grant['id'], retry_id, name, length, digest, 'uploading', utc_now()))
            storage.conn.commit()
        active_key = (str(storage.db_path.resolve()), upload_id); ACTIVE.add(active_key)
    output = None
    try:
        if destination:
            output = destination.open('xb'); destination.chmod(0o600)
        actual = hashlib.sha256(); remaining = length
        while remaining:
            chunk = stream.read(min(256 * 1024, remaining))
            if not chunk:
                fail(400, 'incomplete_upload', 'Upload interrupted. Retry with the same request_id.')
            actual.update(chunk); remaining -= len(chunk)
            if output: output.write(chunk)
        if output: output.close(); output = None
        if actual.hexdigest() != digest:
            fail(409, 'file_changed', 'The file changed during upload. Read its current hash and retry.')
        fresh = authenticate(storage, authorization); require_upload(fresh)
        with LOCK:
            if destination:
                storage.conn.execute("UPDATE ai_uploads SET status='ready' WHERE upload_id=?", (upload_id,)); storage.conn.commit()
            return {'upload_id': upload_id, 'name': name, 'size_bytes': length, 'sha256': digest,
                    'status': prior['status'] if prior else 'ready', 'quota': quota(storage, fresh),
                    'usage': 'Import/register this ONE upload now before uploading the next file. Its staging is released immediately on successful import; do not wait for the whole collection. Use release_upload if unused. Ready uploads expire after 24 hours; active transfers are never evicted.'}
    except BaseException:
        if output: output.close()
        if destination:
            destination.unlink(missing_ok=True)
            storage.conn.execute("UPDATE ai_uploads SET status='released' WHERE upload_id=?", (upload_id,)); storage.conn.commit()
        raise
    finally:
        with LOCK: ACTIVE.discard(active_key)


def get_upload(storage, grant, upload_id):
    path = path_for(storage, upload_id)
    row = storage.conn.execute("SELECT * FROM ai_uploads WHERE upload_id=? AND connection_id=? AND status='ready'", (upload_id, grant['id'])).fetchone()
    if not row or not path.is_file():
        fail(404, 'upload_unavailable', 'This upload is unavailable. Upload again, or retry the original completed import with its original request_id.')
    return dict(row), path


def consume(storage, upload_id):
    path_for(storage, upload_id).unlink(missing_ok=True)
    storage.conn.execute("UPDATE ai_uploads SET status='consumed' WHERE upload_id=?", (upload_id,))
    storage.conn.commit()


def manage_uploads(storage, grant, operation, args):
    require_upload(grant)
    with LOCK:
        prune(storage)
        if operation == 'release_upload':
            if set(args) != {'upload_id'}: fail(400, 'invalid_arguments', 'Provide only upload_id.')
            path = path_for(storage, args['upload_id'])
            row = storage.conn.execute('SELECT * FROM ai_uploads WHERE upload_id=? AND connection_id=?', (args['upload_id'], grant['id'])).fetchone()
            if row and row['status'] == 'uploading': fail(409, 'upload_busy', 'Do not release a transfer still in progress.')
            released = bool(row and row['status'] == 'ready')
            if released:
                path.unlink(missing_ok=True)
                storage.conn.execute("UPDATE ai_uploads SET status='released' WHERE upload_id=?", (args['upload_id'],)); storage.conn.commit()
            return {'released': released, 'quota': quota(storage, grant)}
        if args: fail(400, 'invalid_arguments', 'get_upload_status takes no arguments.')
        return {'quota': quota(storage, grant)}
