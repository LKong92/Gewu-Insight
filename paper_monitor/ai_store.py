"""SQLite grants and provenance for the opt-in local AI API."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

SCOPES = ('papers:read', 'files:read', 'analysis:write')


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def ensure_ai_schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS ai_connections (
      id INTEGER PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE,
      scopes_json TEXT NOT NULL, selection_json TEXT NOT NULL,
      created_at TEXT NOT NULL, expires_at TEXT, revoked_at TEXT, last_used_at TEXT
    );
    CREATE TABLE IF NOT EXISTS ai_audit (
      id INTEGER PRIMARY KEY, connection_id INTEGER REFERENCES ai_connections(id),
      operation TEXT NOT NULL, gewu_key TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_ai_audit_connection ON ai_audit(connection_id,id);
    CREATE TABLE IF NOT EXISTS ai_analyses (
      id INTEGER PRIMARY KEY, connection_id INTEGER NOT NULL REFERENCES ai_connections(id),
      request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
      paper_id TEXT REFERENCES papers(paper_id) ON DELETE SET NULL,
      gewu_key TEXT NOT NULL, resource_id INTEGER REFERENCES resources(id) ON DELETE SET NULL,
      source_resource_id INTEGER, source_sha256 TEXT NOT NULL DEFAULT '',
      pages_json TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL,
      completed INTEGER NOT NULL DEFAULT 0,
      UNIQUE(connection_id, request_id)
    );
    ''')


class APIError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def fail(status, code, message):
    raise APIError(status, code, message)


def enabled(storage):
    return storage.get_setting('ai_access_enabled', 'false') == 'true'


def grant_payload(row):
    return {key: row[key] for key in ('id', 'name', 'created_at', 'expires_at', 'revoked_at', 'last_used_at')} | {
        'scopes': json.loads(row['scopes_json']), 'selection': json.loads(row['selection_json'])}


def create_connection(storage, payload):
    name = str(payload.get('name') or '').strip()
    scopes = payload.get('scopes', ['papers:read'])
    selection = payload.get('selection', {'kind': 'saved'})
    if not name or len(name) > 80 or any(ord(c) < 32 for c in name):
        fail(400, 'invalid_name', 'Enter a connection name of 1–80 characters.')
    if not isinstance(scopes, list) or not scopes or any(scope not in SCOPES for scope in scopes):
        fail(400, 'invalid_scopes', 'Choose the supported permissions.')
    scopes = sorted(set(scopes + ['papers:read']))
    if not isinstance(selection, dict) or selection.get('kind') not in ('saved', 'folder', 'papers'):
        fail(400, 'invalid_selection', 'Choose saved papers, a folder, or specific Gewu Keys.')
    kind = selection['kind']
    if kind == 'papers':
        keys = selection.get('keys')
        if not isinstance(keys, list) or not 1 <= len(keys) <= 200 or any(not isinstance(k, str) for k in keys):
            fail(400, 'invalid_selection', 'Choose between 1 and 200 Gewu Keys.')
        keys = list(dict.fromkeys(k.strip() for k in keys))
        for key in keys:
            if not storage.paper_for_key(key):
                fail(400, 'invalid_selection', 'One of the Gewu Keys was not found.')
        selection = {'kind': kind, 'keys': keys}
    elif kind == 'folder':
        try:
            folder_id = int(selection['folder_id'])
        except (KeyError, ValueError, TypeError):
            fail(400, 'invalid_selection', 'Choose a Library or Space folder.')
        from .ai_service import ACTIVE_FOLDERS
        if not storage.conn.execute(ACTIVE_FOLDERS + 'SELECT 1 FROM active_folders WHERE id=?', (folder_id,)).fetchone():
            fail(400, 'invalid_selection', 'The selected folder is unavailable.')
        selection = {'kind': kind, 'folder_id': folder_id}
    else:
        selection = {'kind': kind}
    days = payload.get('expires_days', 30)
    if isinstance(days, bool) or not isinstance(days, int) or days not in (7, 30, 90, 365):
        fail(400, 'invalid_expiry', 'Choose 7, 30, 90 or 365 days.')
    token = 'gewu_ai_' + secrets.token_urlsafe(32)
    now = utc_now()
    expiry = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(timespec='microseconds')
    cursor = storage.conn.execute('''INSERT INTO ai_connections
      (name,token_hash,scopes_json,selection_json,created_at,expires_at) VALUES(?,?,?,?,?,?)''',
      (name, hashlib.sha256(token.encode()).hexdigest(), json.dumps(scopes), json.dumps(selection), now, expiry))
    storage.conn.commit()
    row = storage.conn.execute('SELECT * FROM ai_connections WHERE id=?', (cursor.lastrowid,)).fetchone()
    return {'connection': grant_payload(row), 'token': token}


def authenticate(storage, authorization):
    if not isinstance(authorization, str) or not authorization.startswith('Bearer gewu_ai_') or len(authorization) > 160:
        fail(401, 'unauthorized', 'A valid Gewu AI access token is required.')
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    row = storage.conn.execute('SELECT * FROM ai_connections WHERE token_hash=?', (digest,)).fetchone()
    if not row or row['revoked_at'] or (row['expires_at'] and row['expires_at'] <= utc_now()):
        fail(401, 'unauthorized', 'This connection is invalid, expired or revoked. Check AI Access in Gewu Insight.')
    if not enabled(storage):
        fail(403, 'disabled', 'AI access is disabled in Gewu Insight.')
    return grant_payload(row)


def audit(storage, grant, operation, key='', outcome='ok'):
    now = utc_now()
    storage.conn.execute('INSERT INTO ai_audit(connection_id,operation,gewu_key,outcome,created_at) VALUES(?,?,?,?,?)',
                         (grant['id'], operation, key, outcome, now))
    storage.conn.execute('UPDATE ai_connections SET last_used_at=? WHERE id=?', (now, grant['id']))
    # Activity is bounded and contains no tokens, file contents or prompts.
    storage.conn.execute('DELETE FROM ai_audit WHERE id <= (SELECT MAX(id)-5000 FROM ai_audit)')
    storage.conn.commit()


def settings_snapshot(storage):
    from .ai_service import ACTIVE_FOLDERS
    return {'enabled': enabled(storage),
            'connections': [grant_payload(row) for row in storage.conn.execute('SELECT * FROM ai_connections ORDER BY id DESC')],
            'folders': [dict(row) for row in storage.conn.execute(ACTIVE_FOLDERS + 'SELECT id,path FROM active_folders ORDER BY path')],
            'activity': [dict(row) for row in storage.conn.execute('''SELECT a.id,c.name,a.operation,a.gewu_key,a.outcome,a.created_at
              FROM ai_audit a LEFT JOIN ai_connections c ON a.connection_id=c.id ORDER BY a.id DESC LIMIT 50''')]}
