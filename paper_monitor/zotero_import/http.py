"""Small authenticated integration endpoint; UI cannot supply attachment paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import parse_qs, urlparse

from ..storage import Storage
from ..library_destination import active_folders
from . import files, importer, store

_locks = {}
_locks_guard = threading.Lock()


def job_lock(db, job_id):
    with _locks_guard:
        return _locks.setdefault((str(Path(db).resolve()), job_id), threading.Lock())


def launch(storage, job, origin, support=None):
    if sys.platform != 'darwin':
        raise ValueError('This migration preview currently supports macOS with Zotero 10.')
    support = support or Path.home() / 'Library/Application Support/Gewu Insight'
    support.mkdir(parents=True, exist_ok=True)
    generation = secrets.token_hex(24)
    config = {'job_id': job['id'], 'workspace': str(storage.db_path.resolve().parent.parent),
              'origin': origin, 'generation': generation, 'requested_at': time.time()}
    path = support / 'zotero-import-connection.json'
    temporary = support / ('zotero-import-' + uuid.uuid4().hex)
    try:
        with temporary.open('x') as stream:
            os.chmod(temporary, 0o600)
            json.dump(config, stream)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    store.update(storage, job['id'], generation=generation, message='Waiting for the Gewu plugin in Zotero. Update the plugin if it does not connect.')
    subprocess.run(['/usr/bin/open', '-g', '-a', '/Applications/Zotero.app',
                    'zotero://gewu-insight/import?request=' + generation], check=True)


def entry_valid(entry):
    if not isinstance(entry, dict) or not isinstance(entry.get('data'), dict):
        raise ValueError('Invalid Zotero record.')
    if not re.fullmatch(r'[A-Z0-9]{8}', str(entry['data'].get('key', ''))):
        raise ValueError('Invalid Zotero item key.')
    if not isinstance(entry.get('attachments', []), list) or not isinstance(entry.get('notes', []), list):
        raise ValueError('Invalid Zotero attachments or notes.')
    if len(store.dumps(entry).encode()) > 24 * 1024 * 1024:
        raise ValueError('This Zotero record exceeds the migration size limit.')
    for attachment in entry.get('attachments', []):
        if not re.fullmatch(r'[A-Z0-9]{8}', str(attachment.get('key', ''))):
            raise ValueError('Invalid Zotero attachment key.')
        if attachment.get('path') and not Path(attachment['path']).is_absolute():
            raise ValueError('Zotero must resolve attachment paths before migration.')


def host(storage, args):
    job = store.get(storage, args.get('id'))
    job_id, action = job['id'], args.get('action')
    if not secrets.compare_digest(str(args.get('generation', '')), job['generation']) or not job['generation']:
        raise ValueError('This Zotero connection expired. Reconnect from Import from Zotero.')
    if action == 'ping':
        store.update(storage, job_id, adapter_seen=time.time())
        return {'ok': True}
    if action == 'hello':
        catalog = args.get('catalog', {})
        if catalog.get('protocol') != 1 or not isinstance(catalog.get('libraries'), list):
            raise ValueError('Update the Gewu plugin to use Zotero migration.')
        for library in catalog['libraries']:
            if not library.get('source_id') or len(str(library['source_id'])) > 300:
                raise ValueError('Zotero did not provide a stable library identity.')
        # Resuming a job on a different Zotero profile must not adopt other records.
        wanted = job['config'].get('source_id')
        if wanted and wanted not in {x['source_id'] for x in catalog['libraries']}:
            raise ValueError('Open the Zotero library used by this migration before resuming.')
        store.update(storage, job_id, catalog=catalog, adapter_seen=time.time(), state='connected' if job['state'] == 'connecting' else job['state'], message='Zotero connected. Its library and originals are read-only to this importer.')
        return {'ok': True}
    if action == 'next':
        if job['state'] == 'scan_requested':
            store.update(storage, job_id, state='scanning', message='Reading Zotero records and attachment locations…')
            return {'command': 'scan', 'config': job['config']}
        if job['state'] != 'running':
            return {'command': 'wait', 'state': job['state']}
        storage.conn.execute('BEGIN IMMEDIATE')
        row = storage.conn.execute("SELECT * FROM zotero_import_entries WHERE job_id=? AND state='pending' ORDER BY source_key LIMIT 1", (job_id,)).fetchone()
        if row:
            lease = uuid.uuid4().hex
            storage.conn.execute("UPDATE zotero_import_entries SET state='exporting',lease=? WHERE job_id=? AND source_key=?", (lease, job_id, row['source_key']))
            storage.conn.commit()
            path = storage.db_path.parent / 'zotero-import-staging' / job_id / 'exports'
            files.protect_destination(path, job['catalog'].get('protected_roots', []))
            path.mkdir(parents=True, exist_ok=True)
            return {'command': 'export', 'entry': json.loads(row['manifest']), 'lease': lease,
                    'config': job['config'], 'export_dir': str(path.resolve())}
        busy = storage.conn.execute("SELECT 1 FROM zotero_import_entries WHERE job_id=? AND state='exporting'", (job_id,)).fetchone()
        storage.conn.commit()
        if not busy:
            incomplete = storage.conn.execute("SELECT 1 FROM zotero_import_entries WHERE job_id=? AND state IN ('partial','failed')", (job_id,)).fetchone()
            store.update(storage, job_id, state='needs_attention' if incomplete else 'complete',
                         message='Import finished. Review the items below.' if incomplete else 'Import complete. Zotero originals were preserved.')
        return {'command': 'wait', 'state': store.get(storage, job_id)['state']}
    if action == 'entries':
        if job['state'] != 'scanning':
            return {'ok': True, 'stop': True}
        entries = args.get('entries')
        if not isinstance(entries, list) or len(entries) > 50:
            raise ValueError('Send at most 50 Zotero records at a time.')
        for entry in entries:
            entry_valid(entry)
            attachments = entry.get('attachments', [])
            originals = attachments + [image for note in entry.get('notes', []) for image in note.get('images', [])]
            originals += [item for attachment in attachments for item in attachment.get('snapshot_files', [])]
            storage.conn.executemany('INSERT OR IGNORE INTO zotero_import_sources VALUES(?,?)',
                                     [(job_id, str(Path(item['path']).resolve())) for item in originals if item.get('path')])
            available = [a for a in attachments if a.get('path')]
            storage.conn.execute('INSERT OR REPLACE INTO zotero_import_entries(job_id,source_key,manifest,title,file_count,file_bytes,missing) VALUES(?,?,?,?,?,?,?)',
                                 (job_id, entry['data']['key'], store.dumps(entry), entry['data'].get('title') or entry['data']['key'],
                                  len(available), sum(max(0, int(a.get('size', 0))) for a in available),
                                  store.dumps([a['missing'] for a in attachments if a.get('missing')])))
        storage.conn.commit()
        return {'ok': True}
    if action == 'scanned':
        if job['state'] != 'scanning':
            return {'ok': True, 'stop': True}
        # Check identities during preview; nothing is imported yet.
        for row in storage.conn.execute('SELECT source_key,manifest FROM zotero_import_entries WHERE job_id=?', (job_id,)).fetchall():
            try:
                paper, _ = importer.match(storage, job['config']['source_id'], json.loads(row['manifest']))
                result = {'existing': bool(paper)}
            except ValueError as exc:
                result = {'issues': [str(exc)], 'conflict': True}
            storage.conn.execute('UPDATE zotero_import_entries SET result=? WHERE job_id=? AND source_key=?',
                                 (store.dumps(result), job_id, row['source_key']))
        storage.conn.commit()
        store.update(storage, job_id, state='ready', message='Preview ready. No Zotero records or original files have been changed.')
        return {'ok': True}
    if action == 'scan_error':
        store.update(storage, job_id, state='scan_failed', message=str(args.get('message', 'Could not read Zotero.'))[:1500])
        return {'ok': True}
    if action in ('apply', 'item_error'):
        key, lease = str(args.get('key', '')), str(args.get('lease', ''))
        row = storage.conn.execute('SELECT * FROM zotero_import_entries WHERE job_id=? AND source_key=?', (job_id, key)).fetchone()
        if not row or row['state'] != 'exporting' or not lease or row['lease'] != lease or job['state'] != 'running':
            return {'ok': True, 'stop': True}
        lock = job_lock(storage.db_path, job_id)
        if not lock.acquire(blocking=False):
            raise ValueError('Another attachment is still being imported. Wait before retrying.')
        try:
            result = {'issues': []}
            state = 'failed'
            def check():
                fresh = store.get(storage, job_id)
                if fresh['state'] != 'running' or fresh['generation'] != job['generation']:
                    raise files.Paused('Import paused. Completed copies were kept.')
            try:
                if action == 'item_error':
                    raise ValueError(str(args.get('message', 'Could not export this item.'))[:1500])
                exported = args.get('exports', {})
                export_root = (storage.db_path.parent / 'zotero-import-staging' / job_id / 'exports').resolve()
                for attachment in exported.get('attachments', []):
                    p = Path(attachment['path'])
                    if p.is_symlink() or not p.resolve().is_relative_to(export_root):
                        raise ValueError('Zotero exports must be new files inside this migration’s staging folder.')
                result = importer.import_entry(storage, job, json.loads(row['manifest']), exported, check)
                state = 'partial' if result['issues'] else 'done'
            except files.Paused:
                state = 'pending'
            except Exception as exc:
                storage.conn.rollback()
                result['issues'].append(str(exc))
            storage.conn.execute('UPDATE zotero_import_entries SET state=?,result=?,lease=? WHERE job_id=? AND source_key=?',
                                 (state, store.dumps(result), '', job_id, key))
            storage.conn.commit()
            return {'ok': True, 'state': state}
        finally:
            lock.release()
    raise ValueError('Unsupported Zotero migration operation.')


def ui_action(storage, args, origin):
    action = args.get('action')
    if action == 'connect':
        job = store.get(storage, args['id']) if args.get('id') else store.create(storage)
        lock = job_lock(storage.db_path, job['id'])
        if not lock.acquire(blocking=False):
            raise ValueError('Wait for the current file copy to finish before reconnecting.')
        try:
            if job['state'] in ('running', 'scanning', 'scan_requested'):
                store.update(storage, job['id'], state='paused' if job['state']=='running' else 'scan_failed', message='Reconnect, then resume or prepare the preview again.')
            launch(storage, store.get(storage, job['id']), origin)
        finally:
            lock.release()
        return store.report(storage, job['id'])
    job = store.get(storage, args.get('id'))
    job_id = job['id']
    if action == 'scan':
        if job['state'] not in ('connected', 'ready', 'scan_failed', 'paused'):
            raise ValueError('Connect Zotero before preparing the preview.')
        if storage.conn.execute("SELECT 1 FROM zotero_import_entries WHERE job_id=? AND state IN ('done','partial')", (job_id,)).fetchone():
            raise ValueError('Start a new scan to change an import that already saved papers.')
        library = next((x for x in job['catalog'].get('libraries', []) if x['source_id'] == args.get('source_id')), None)
        if not library:
            raise ValueError('Choose a Zotero library.')
        target = int(args.get('target_id') or 1)
        importer.active(storage, target)
        chosen = set(args.get('collection_keys', []))
        collections = library.get('collections', [])
        if not chosen.issubset({c['key'] for c in collections}):
            raise ValueError('Choose available Zotero collections.')
        if chosen:
            descendants = set(chosen)
            while True:
                expanded = descendants | {c['key'] for c in collections if c.get('parent') in descendants}
                if expanded == descendants:
                    break
                descendants = expanded
            collections = [c for c in collections if c['key'] in descendants]
        else:
            descendants = set()
        config = {'source_id': library['source_id'], 'library_id': library['id'], 'target_id': target,
                  'root_name': str(args.get('root_name') or 'Zotero — ' + library['name'])[:150],
                  'collection_keys': sorted(descendants), 'collections': collections}
        storage.conn.execute('DELETE FROM zotero_import_entries WHERE job_id=?', (job_id,))
        storage.conn.execute('DELETE FROM zotero_import_sources WHERE job_id=?', (job_id,))
        storage.conn.commit()
        store.update(storage, job_id, config=config, state='scan_requested', message='Preparing migration preview…')
    elif action == 'start':
        if job['state'] not in ('ready', 'paused', 'needs_attention'):
            raise ValueError('Prepare the preview before importing.')
        if time.time() - job['adapter_seen'] >= 35:
            raise ValueError('Reconnect Zotero before resuming this import. Completed imports are kept.')
        lock = job_lock(storage.db_path, job_id)
        if not lock.acquire(blocking=False):
            raise ValueError('The current file is still stopping. Retry in a moment.')
        try:
            files.recover(storage, job_id)
            config = dict(job['config'])
            config['folder_map'] = importer.destinations(storage, job)
            storage.conn.execute("UPDATE zotero_import_entries SET state='pending',lease='' WHERE job_id=? AND state IN ('failed','partial','exporting')", (job_id,))
            storage.conn.commit()
            store.update(storage, job_id, config=config, state='running', message='Copying into Gewu. Zotero originals stay in place.')
        finally:
            lock.release()
    elif action == 'pause':
        if job['state'] in ('running', 'scanning', 'scan_requested'):
            state = 'paused' if job['state'] == 'running' else 'scan_failed'
            store.update(storage, job_id, state=state, message='Paused. Completed imports are kept; resume to continue.' if state=='paused' else 'Preview stopped. Prepare the preview again before importing.')
    else:
        raise ValueError('Unsupported migration action.')
    return store.report(storage, job_id)


def handle(handler):
    parsed = urlparse(handler.path)
    storage = Storage(handler.configured_db_path)
    try:
        store.initialize(storage)
        if handler.command == 'GET':
            job_id = parse_qs(parsed.query).get('id', [''])[0]
            if job_id:
                result = store.report(storage, job_id)
            else:
                history = [dict(row) for row in storage.conn.execute('SELECT id,state,created,updated,message FROM zotero_import_jobs ORDER BY created DESC LIMIT 20')]
                result = {'jobs': history, 'destinations': active_folders(storage)}
        else:
            if int(handler.headers.get('Content-Length') or 0) > 32 * 1024 * 1024:
                handler.close_connection = True
                handler.send_error_json(413, 'Zotero migration request exceeds 32 MB.')
                return
            if parsed.path.endswith('/host') and not handler.server.workspace_access.matches(handler.headers.get('X-Gewu-Workspace', '')):
                handler.send_error_json(403, 'Only the authenticated Zotero plugin may provide library records and file locations.')
                return
            args = handler.read_json_body()
            if not isinstance(args, dict):
                raise ValueError('Invalid migration request.')
            if parsed.path.endswith('/host'):
                result = host(storage, args)
            else:
                origin = 'http://127.0.0.1:' + str(handler.server.server_address[1])
                result = ui_action(storage, args, origin)
        handler.send_json(result)
    except (ValueError, OSError) as exc:
        storage.conn.rollback()
        handler.send_error_json(400, str(exc))
    finally:
        storage.close()
