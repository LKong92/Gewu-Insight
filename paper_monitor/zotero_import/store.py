"""Durable migration manifests and receipts, separate from existing importers."""
from __future__ import annotations

import json
import re
import time
import uuid


SCHEMA = '''
CREATE TABLE IF NOT EXISTS zotero_import_jobs (
 id TEXT PRIMARY KEY, state TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
 config TEXT NOT NULL DEFAULT '{}', catalog TEXT NOT NULL DEFAULT '{}', message TEXT NOT NULL DEFAULT '',
 generation TEXT NOT NULL DEFAULT '', adapter_seen REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS zotero_import_entries (
 job_id TEXT NOT NULL, source_key TEXT NOT NULL, manifest TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'pending', result TEXT NOT NULL DEFAULT '{}', lease TEXT NOT NULL DEFAULT '',
 title TEXT NOT NULL DEFAULT '', file_count INTEGER NOT NULL DEFAULT 0, file_bytes INTEGER NOT NULL DEFAULT 0,
 missing TEXT NOT NULL DEFAULT '[]',
 PRIMARY KEY(job_id, source_key)
);
CREATE TABLE IF NOT EXISTS zotero_import_papers (
 source_id TEXT NOT NULL, source_key TEXT NOT NULL, paper_id TEXT NOT NULL,
 PRIMARY KEY(source_id, source_key)
);
CREATE TABLE IF NOT EXISTS zotero_import_folders (
 source_id TEXT NOT NULL, target_id INTEGER NOT NULL, source_key TEXT NOT NULL, folder_id INTEGER NOT NULL,
 PRIMARY KEY(source_id, target_id, source_key)
);
CREATE TABLE IF NOT EXISTS zotero_import_files (
 source_id TEXT NOT NULL, source_key TEXT NOT NULL, digest TEXT NOT NULL,
 paper_id TEXT NOT NULL, resource_id INTEGER NOT NULL,
 PRIMARY KEY(source_id, source_key, digest, paper_id)
);
CREATE TABLE IF NOT EXISTS zotero_import_copies (
 id TEXT PRIMARY KEY, job_id TEXT NOT NULL, path TEXT NOT NULL,
 device INTEGER NOT NULL, inode INTEGER NOT NULL, digest TEXT NOT NULL DEFAULT '',
 resource_id INTEGER, created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS zotero_import_sources (
 job_id TEXT NOT NULL, path TEXT NOT NULL,
 PRIMARY KEY(job_id, path)
);
'''


def initialize(storage):
    # Deliberately called only by the migration endpoint, not Storage/startup.
    storage.conn.executescript(SCHEMA)
    if 'adapter_seen' not in {row['name'] for row in storage.conn.execute('PRAGMA table_info(zotero_import_jobs)')}:
        storage.conn.execute('ALTER TABLE zotero_import_jobs ADD COLUMN adapter_seen REAL NOT NULL DEFAULT 0')
        storage.conn.commit()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('Invalid migration job.')
    return value


def create(storage):
    job_id = uuid.uuid4().hex
    storage.conn.execute('INSERT INTO zotero_import_jobs(id,state,created,updated) VALUES(?,?,?,?)',
                         (job_id, 'connecting', time.time(), time.time()))
    storage.conn.commit()
    return get(storage, job_id)


def get(storage, job_id):
    row = storage.conn.execute('SELECT * FROM zotero_import_jobs WHERE id=?', (identifier(job_id),)).fetchone()
    if not row:
        raise ValueError('This migration no longer exists.')
    result = dict(row)
    for name in ('config', 'catalog'):
        result[name] = json.loads(result[name])
    return result


def update(storage, job_id, **fields):
    if set(fields) - {'state', 'config', 'catalog', 'message', 'generation', 'adapter_seen'}:
        raise ValueError('Invalid job update.')
    fields['updated'] = time.time()
    values = [dumps(v) if k in ('config', 'catalog') else v for k, v in fields.items()]
    storage.conn.execute('UPDATE zotero_import_jobs SET ' + ','.join(k+'=?' for k in fields) + ' WHERE id=?',
                         (*values, identifier(job_id)))
    storage.conn.commit()


def report(storage, job_id):
    job = get(storage, job_id)
    counts = {}
    for row in storage.conn.execute('SELECT state,count(*) n FROM zotero_import_entries WHERE job_id=? GROUP BY state', (job_id,)):
        counts[row['state']] = row['n']
    issues = []
    totals = storage.conn.execute('SELECT COALESCE(sum(file_count),0),COALESCE(sum(file_bytes),0) FROM zotero_import_entries WHERE job_id=?', (job_id,)).fetchone()
    for row in storage.conn.execute("SELECT title,missing,result,state FROM zotero_import_entries WHERE job_id=? AND (missing!='[]' OR result!='{}')", (job_id,)):
        result, title = json.loads(row['result']), row['title']
        if row['state'] == 'pending':
            issues.extend({'title': title, 'message': message} for message in json.loads(row['missing']))
        for message in result.get('issues', []):
            issues.append({'title': title, 'message': message})
    return {'id': job_id, 'state': job['state'], 'created': job['created'], 'message': job['message'], 'config': job['config'],
            'catalog': job['catalog'], 'counts': counts, 'total': sum(counts.values()),
            'files': totals[0], 'bytes': totals[1], 'issue_count': len(issues), 'issues': issues[:200],
            'updated': job['updated'], 'connected': time.time() - job['adapter_seen'] < 35}
