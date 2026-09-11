"""Durable folder/all-Library metadata jobs in SQLite settings.

The immutable candidate snapshot and small mutable checkpoint are stored
separately. No external JSON files, Library files or placements are changed.
"""
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from .storage import Storage
from . import metadata_refresh

PREFIX = 'metadata_job:'
_LOCK = threading.RLock()
_WORKERS = set()
_INITIALIZED = set()
COUNTERS = ('updated', 'unchanged', 'partial', 'failed', 'skipped_recent', 'missing_identifier', 'removed')


def stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def _read(storage, job_id):
    value = storage.get_setting(PREFIX + job_id, '')
    return json.loads(value) if value else None


def _save(storage, job):
    storage.set_setting(PREFIX + job['job_id'], json.dumps(job, ensure_ascii=False))


def initialize(storage):
    db = str(Path(storage.db_path).resolve())
    with _LOCK:
        if db in _INITIALIZED:
            return
        rows = storage.conn.execute('SELECT value FROM app_settings WHERE key LIKE ?', (PREFIX + '%',)).fetchall()
        for row in rows:
            job = json.loads(row[0])
            if job['status'] in {'queued', 'running', 'pausing'}:
                job.update(status='paused', stage='paused', current_paper='',
                           message='Paused after restart. Continue from the saved checkpoint.')
                _save(storage, job)
        _INITIALIZED.add(db)


SCOPE_SQL = '''
    WITH RECURSIVE excluded(id) AS (
      SELECT id FROM library_folders WHERE (name='Recycle' AND parent_id=1)
        OR COALESCE(trashed_at, '') <> ''
      UNION SELECT f.id FROM library_folders f JOIN excluded e ON f.parent_id=e.id
    ), subtree(id) AS (
      SELECT id FROM library_folders WHERE id=?
      UNION SELECT f.id FROM library_folders f JOIN subtree s ON f.parent_id=s.id
    )
    SELECT DISTINCT p.paper_id FROM papers p JOIN library_items i ON p.paper_id=i.paper_id
    JOIN library_folders f ON f.id=i.folder_id
    WHERE COALESCE(i.trashed_at, '')='' AND f.id NOT IN (SELECT id FROM excluded)
      AND (? IS NULL OR f.id IN (SELECT id FROM subtree))
      AND (? IS NULL OR p.paper_id=?)
    ORDER BY p.paper_id
'''


def candidates(storage, folder_id=None, paper_id=None):
    return [r[0] for r in storage.conn.execute(SCOPE_SQL, (folder_id, folder_id, paper_id, paper_id))]


def scope_label(storage, folder_id):
    if folder_id is None:
        return 'All active Library and Space papers'
    names, seen, current = [], set(), folder_id
    while current is not None:
        if current in seen:
            raise ValueError('Invalid folder hierarchy')
        seen.add(current)
        row = storage.conn.execute('SELECT name,parent_id,trashed_at FROM library_folders WHERE id=?', (current,)).fetchone()
        if not row:
            raise ValueError('Folder no longer exists')
        if row['trashed_at'] or (row['name'] == 'Recycle' and row['parent_id'] == 1):
            raise ValueError('Recycle and deleted folders cannot be refreshed')
        names.append(row['name'])
        current = row['parent_id']
    return ' / '.join(reversed(names)) + ' — including all subfolders'


def create(storage, *, mode='full', skip_days=3, folder_id=None, job_id=None,
           paper_ids=None, origin='batch'):
    initialize(storage)
    if mode not in {'quick', 'full'}:
        raise ValueError('Choose Quick or Full')
    label = scope_label(storage, folder_id) if paper_ids is None else 'Imported papers'
    ids = candidates(storage, folder_id) if paper_ids is None else list(dict.fromkeys(paper_ids))
    with _LOCK:
        # Repeated clicks on the same scope attach to the existing job.
        for previous in listing(storage):
            if paper_ids is None and previous.get('origin') != 'import' and previous['folder_id'] == folder_id and previous['metadata_mode'] == mode and previous['status'] in {'queued', 'running', 'pausing'}:
                return previous
        job_id = job_id or uuid.uuid4().hex[:12]
        job = {'job_id': job_id, 'job_type': 'metadata_refresh', 'metadata_mode': mode,
               'origin': origin,
               'folder_id': folder_id, 'scope_label': label, 'skip_days': skip_days,
               'status': 'queued', 'stage': 'queued', 'started_at': stamp(), 'finished_at': '',
               'current': 0, 'total': len(ids), 'percent': 0, 'current_paper': '',
               'counts': {name: 0 for name in COUNTERS}, 'changed_count': 0,
               'logs': [], 'result': None, 'error': '', 'library_ready': True}
        storage.set_setting('metadata_candidates:' + job_id, json.dumps(ids))
        _save(storage, job)
        return job


def get(storage, job_id):
    initialize(storage)
    with _LOCK:
        return _read(storage, job_id)


def listing(storage):
    initialize(storage)
    with _LOCK:
        rows = storage.conn.execute('SELECT value FROM app_settings WHERE key LIKE ?', (PREFIX + '%',)).fetchall()
        return sorted((json.loads(row[0]) for row in rows), key=lambda j: j['started_at'], reverse=True)


def control(storage, job_id, action):
    initialize(storage)
    with _LOCK:
        job = _read(storage, job_id)
        if not job:
            raise KeyError('Refresh job not found')
        if action == 'pause' and job['status'] in {'queued', 'running'}:
            job.update(status='pausing' if job['status'] == 'running' else 'paused')
            job['stage'] = job['status']
        elif action == 'resume' and job['status'] in {'paused', 'failed'}:
            job.update(status='queued', stage='queued', error='')
        else:
            if action not in {'pause', 'resume'}:
                raise ValueError('Unknown refresh control')
        _save(storage, job)
    return job


def run_job(storage, job_id, progress=None):
    with _LOCK:
        job = _read(storage, job_id)
        if not job or job['status'] != 'queued':
            return
        job.update(status='running', stage='metadata')
        _save(storage, job)
    ids = json.loads(storage.get_setting('metadata_candidates:' + job_id, '[]'))
    try:
        for index in range(job['current'], len(ids)):
            if progress:
                progress(job)
            with _LOCK:
                job = _read(storage, job_id)
                if job['status'] == 'pausing':
                    job.update(status='paused', stage='paused', current_paper='')
                    _save(storage, job)
                    return
                paper_id = ids[index]
                paper = storage.get_paper(paper_id)
                job['current_paper'] = (paper or {}).get('title') or paper_id
                _save(storage, job)
            changed = False
            if not paper or not candidates(storage, job['folder_id'], paper_id):
                status, message = 'removed', 'No longer in the selected active scope.'
            elif not any(metadata_refresh.identifiers(paper)):
                status, message = 'missing_identifier', 'Missing DOI/arXiv. Use Find Missing Identifiers.'
            else:
                try:
                    outcome = metadata_refresh.refresh(storage, paper_id, mode=job['metadata_mode'],
                        origin=job.get('origin', 'batch'), skip_days=job['skip_days'])['metadata_refresh']
                    status, message = outcome['status'], outcome['message']
                    changed = bool(outcome.get('changed_fields'))
                    if status == 'partial' and not any(v == 'found' for v in outcome.get('sources', {}).values()):
                        status = 'failed'
                except Exception as exc:
                    status, message = 'failed', str(exc)
            with _LOCK:
                job = _read(storage, job_id)  # Preserve a pause requested during I/O.
                job['counts'][status] += 1
                job['changed_count'] += int(changed)
                job['current'] = index + 1
                job['percent'] = round(100 * (index + 1) / max(1, len(ids)))
                job['logs'].append({'time': stamp(), 'level': 'warn' if status in {'partial', 'failed'} else 'info',
                                    'message': f'{index+1}/{len(ids)} · {job["current_paper"]} · {status.replace("_", " ")}: {message}'})
                job['logs'] = job['logs'][-200:]
                _save(storage, job)
        with _LOCK:
            job = _read(storage, job_id)
            counts = job['counts']
            job.update(status='completed', stage='complete', percent=100, finished_at=stamp(), current_paper='',
                result={'job_type': 'metadata_refresh', 'metadata_mode': job['metadata_mode'],
                        'scope_label': job['scope_label'], 'total_candidates': job['total'],
                        'metadata_refreshed': job['changed_count'], 'skip_days': job['skip_days'], **counts})
            _save(storage, job)
    except Exception as exc:
        with _LOCK:
            job = _read(storage, job_id)
            job.update(status='failed', stage='failed', error=str(exc))
            _save(storage, job)


def start(db_path):
    db = str(Path(db_path).resolve())
    with _LOCK:
        if db in _WORKERS:
            return
        _WORKERS.add(db)
    def worker():
        storage = None
        try:
            storage = Storage(Path(db))
            while True:
                with _LOCK:
                    queued = [j for j in listing(storage) if j['status'] == 'queued']
                    if not queued:
                        break
                    selected = min(queued, key=lambda j: j['started_at'])
                run_job(storage, selected['job_id'])
        finally:
            with _LOCK:
                _WORKERS.discard(db)
                pending = storage is not None and any(j['status'] == 'queued' for j in listing(storage))
                if storage is not None:
                    storage.close()
                if pending:
                    start(db_path)
    threading.Thread(target=worker, name='metadata-refresh', daemon=True).start()
