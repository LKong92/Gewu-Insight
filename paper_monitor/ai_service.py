"""Bounded, grant-checked paper tools shared by HTTP and the stdio adapter.

No generic SQL, arbitrary paths, shell commands, deletion, or browser access is
part of this contract. Returned research content is data, never instructions.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

from .ai_store import APIError, audit, authenticate, fail, utc_now

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_NOTE_BYTES = 256 * 1024
READ_SLOTS = threading.BoundedSemaphore(2)
WRITE_LOCK = threading.RLock()
ACTIVE_FOLDERS = '''WITH RECURSIVE active_folders(id,path) AS (
 SELECT id,name FROM library_folders WHERE parent_id IS NULL AND COALESCE(trashed_at,'')=''
 UNION ALL SELECT f.id,a.path || ' / ' || f.name FROM library_folders f
 JOIN active_folders a ON f.parent_id=a.id WHERE COALESCE(f.trashed_at,'')=''
 AND NOT (f.parent_id=1 AND f.name='Recycle')
) '''


def integer(value, default, low, high):
    if value is None:
        return default
    if isinstance(value, bool):
        fail(400, 'invalid_argument', 'A numeric argument is invalid.')
    try:
        result = int(value)
    except (ValueError, TypeError):
        fail(400, 'invalid_argument', 'A numeric argument is invalid.')
    if str(result) != str(value) or not low <= result <= high:
        fail(400, 'invalid_argument', f'Use an integer between {low} and {high}.')
    return result


def require_scope(grant, scope):
    if scope not in grant['scopes']:
        fail(403, 'permission_required', f'This connection needs {scope} permission in AI Access.')


def _read_selection_sql(grant):
    selection = grant['selection']
    kind = selection['kind']
    if kind == 'papers':
        keys = selection['keys']
        return '(p.storage_key IN (' + ','.join('?' for _ in keys) + ') OR EXISTS (SELECT 1 FROM paper_aliases a WHERE a.paper_id=p.paper_id AND a.alias IN (' + ','.join('?' for _ in keys) + ')))', list(keys) * 2
    location = '''EXISTS (SELECT 1 FROM library_items i JOIN active_folders f ON i.folder_id=f.id
      WHERE i.paper_id=p.paper_id AND COALESCE(i.trashed_at,'')='')'''
    if kind == 'saved':
        return '(' + location + ' OR EXISTS (SELECT 1 FROM my_publications m WHERE m.paper_id=p.paper_id))', []
    # The grant follows its anchor's identity. Descendants moved outside that
    # anchor, or trashed/deleted folders, no longer grant access.
    return '''EXISTS (WITH RECURSIVE descendants(id) AS (
      SELECT id FROM active_folders WHERE id=? UNION ALL
      SELECT f.id FROM library_folders f JOIN descendants d ON f.parent_id=d.id
      JOIN active_folders a ON a.id=f.id)
      SELECT 1 FROM library_items i JOIN descendants d ON i.folder_id=d.id
      WHERE i.paper_id=p.paper_id AND COALESCE(i.trashed_at,'')='')''', [selection['folder_id']]


def selection_sql(grant):
    from .ai_contract import WRITE_SCOPES
    clause, params = _read_selection_sql(grant)
    roots = grant.get('write_folder_ids', []) if set(grant['scopes']) & set(WRITE_SCOPES.values()) else []
    if not roots:
        return clause, params
    marks = ','.join('?' for _ in roots)
    return '(' + clause + f''' OR EXISTS (
      WITH RECURSIVE writable(id) AS (
        SELECT id FROM active_folders WHERE id IN ({marks}) UNION
        SELECT f.id FROM library_folders f JOIN writable w ON f.parent_id=w.id
        JOIN active_folders a ON a.id=f.id)
      SELECT 1 FROM library_items i JOIN writable w ON i.folder_id=w.id
      WHERE i.paper_id=p.paper_id AND COALESCE(i.trashed_at,'')=''))''', params + roots


def paper_for_key(storage, grant, key):
    if not isinstance(key, str) or not re.fullmatch(r'gw_[0-9a-f]{10,64}', key):
        fail(400, 'invalid_key', 'Provide a Gewu Key in the form gw_ followed by its identifier.')
    clause, params = selection_sql(grant)
    row = storage.conn.execute(ACTIVE_FOLDERS + 'SELECT p.* FROM papers p WHERE (p.storage_key=? OR EXISTS (SELECT 1 FROM paper_aliases a WHERE a.paper_id=p.paper_id AND a.alias=?)) AND ' + clause,
                               [key, key] + params).fetchone()
    if not row:
        fail(404, 'paper_unavailable', 'This paper was not found in the authorized collection.')
    return dict(row)


def metadata(paper):
    from .ui_server import paper_to_api
    source = paper_to_api(paper)
    # Explicit projection: never serialize the raw record or private paths.
    result = {name: source.get(name) for name in ('title', 'doi', 'journal', 'publication_date', 'abstract')}
    result['arxiv_id'] = source.get('preprint_id') or ''
    result['authors'] = source.get('full_authors') or source.get('authors') or []
    result['gewu_key'] = paper['storage_key']
    return result


def file_metadata(resource, default_id=0):
    return {'file_id': resource['id'], 'name': resource.get('display_name') or Path(resource.get('stored_path') or '').name,
            'file_type': resource.get('file_type'), 'mime_type': resource.get('mime_type'),
            'size_bytes': resource.get('size_bytes'), 'exists': bool(resource.get('exists', Path(resource.get('stored_path') or resource.get('source_path') or '').is_file())),
            'sha256': resource.get('sha256') or '', 'is_default': resource['id'] == default_id,
            'annotation_state': resource.get('annotation_state'), 'file_source': resource.get('file_source'),
            'source_detail': resource.get('source_detail') or '', 'file_role': resource.get('file_role'),
            'kind': resource.get('kind'), 'added_via': resource.get('added_via'), 'created_at': resource.get('created_at')}


def paper_details(storage, paper):
    resources = storage.list_paper_resources(paper['paper_id'], ensure_primary=False)
    default = storage._select_default_paper_resource(paper, resources)
    result = metadata(paper)
    result['files'] = [file_metadata(r, (default or {}).get('id', 0)) for r in resources]
    result['default_file_id'] = (default or {}).get('id')
    from .publication_notices import for_paper
    result['publication_notices'] = for_paper(storage,paper['paper_id'])
    return result


def selected_file(storage, paper, value='default'):
    resources = storage.list_paper_resources(paper['paper_id'], ensure_primary=False)
    if value in (None, 'default'):
        resource = storage._select_default_paper_resource(paper, resources)
    else:
        file_id = integer(value, 0, 1, 2**63 - 1)
        resource = next((r for r in resources if r['id'] == file_id), None)
    if not resource or not resource.get('exists') or resource.get('file_type') == 'invalid_file':
        fail(404, 'file_unavailable', 'The requested file is unavailable. List this paper’s files first.')
    path = Path(storage.resource_local_path(resource)).expanduser().resolve()
    # Only a registered file attached to the authorized paper can reach here.
    if not path.is_file():
        fail(404, 'file_unavailable', 'The requested file is missing.')
    return resource, path


def read_bytes(path, maximum=MAX_FILE_BYTES):
    with path.open('rb') as stream:
        content = stream.read(maximum + 1)
    if len(content) > maximum:
        fail(413, 'file_too_large', 'This file exceeds the AI access size limit.')
    return content


def search(storage, grant, args):
    q = args.get('query', '')
    if not isinstance(q, str) or len(q) > 300:
        fail(400, 'invalid_query', 'Use a search query of up to 300 characters.')
    limit = integer(args.get('limit'), 20, 1, 100)
    offset = integer(args.get('offset'), 0, 0, 1000000)
    clause, params = selection_sql(grant)
    if q.strip():
        term = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        clause += " AND (p.title LIKE ? ESCAPE '\\' OR p.doi LIKE ? ESCAPE '\\' OR p.storage_key LIKE ? ESCAPE '\\' OR p.abstract LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM paper_aliases a WHERE a.paper_id=p.paper_id AND a.alias LIKE ? ESCAPE '\\'))"
        params += [term] * 5
    rows = storage.conn.execute(ACTIVE_FOLDERS + 'SELECT p.* FROM papers p WHERE ' + clause +
                                ' ORDER BY p.storage_key LIMIT ? OFFSET ?', params + [limit + 1, offset]).fetchall()
    return {'papers': [metadata(dict(row)) for row in rows[:limit]],
            'next_offset': offset + limit if len(rows) > limit else None}


def read_paper(storage, paper, args):
    resource, path = selected_file(storage, paper, args.get('file_id', 'default'))
    if not READ_SLOTS.acquire(blocking=False):
        fail(429, 'busy', 'Two file reads are already running. Retry shortly.')
    try:
        content = read_bytes(path)
        digest = hashlib.sha256(content).hexdigest()
        result = {'gewu_key': paper['storage_key'], 'file': file_metadata(resource), 'sha256': digest}
        if path.suffix.lower() == '.pdf':
            start = integer(args.get('start_page'), 1, 1, 100000)
            count = integer(args.get('page_count'), 5, 1, 10)
            # Parse a frozen copy in a disposable subprocess: complex PDFs
            # cannot stall the UI or leave an unbounded worker running.
            import tempfile
            with tempfile.TemporaryDirectory(prefix='gewu-ai-read-') as folder:
                frozen = Path(folder) / 'paper.pdf'
                frozen.write_bytes(content)
                try:
                    proc = subprocess.run([sys.executable, str(Path(__file__).with_name('ai_pdf.py')),
                        str(frozen), str(start), str(count)], capture_output=True, timeout=20)
                except subprocess.TimeoutExpired:
                    fail(422, 'pdf_unreadable', 'PDF text extraction timed out. Download the authorized file instead.')
            if proc.returncode or len(proc.stdout) > 1024 * 1024:
                fail(422, 'pdf_unreadable', 'Text could not be extracted from this PDF. It may be encrypted or require OCR.')
            extracted = json.loads(proc.stdout)
            if extracted.get('error'):
                fail(422, 'pdf_unreadable', extracted['error'])
            result.update(extracted)
        elif path.suffix.lower() in ('.md', '.markdown', '.mdown', '.mkd', '.txt', '.csv', '.json', '.rst'):
            offset = integer(args.get('offset'), 0, 0, MAX_FILE_BYTES)
            text = content.decode('utf-8', errors='replace')
            result.update({'text': text[offset:offset + 64000], 'offset': offset,
                           'next_offset': offset + 64000 if offset + 64000 < len(text) else None})
        else:
            fail(415, 'unsupported_text', 'This format is available through the authorized file download endpoint.')
        return result
    finally:
        READ_SLOTS.release()


def save_analysis(storage, grant, paper, args):
    from .ui_server import attach_file_to_paper
    if set(args) - {'gewu_key', 'markdown', 'request_id', 'title', 'source_file_id', 'source_sha256', 'pages'}:
        fail(400, 'invalid_arguments', 'save_analysis only appends a new Markdown file; file editing, deletion and classification overrides are not supported.')
    body = args.get('markdown')
    request_id = args.get('request_id')
    title = args.get('title', 'AI Analysis')
    if not isinstance(body, str) or not body.strip() or len(body.encode()) > MAX_NOTE_BYTES:
        fail(400, 'invalid_analysis', 'Provide Markdown text of up to 256 KiB.')
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', request_id):
        fail(400, 'invalid_request_id', 'Use a unique request_id of 8–100 letters, digits, underscores or hyphens; reuse it only for retries.')
    if not isinstance(title, str) or not title.strip() or len(title) > 120:
        fail(400, 'invalid_title', 'Use a title of 1–120 characters.')
    payload_hash = hashlib.sha256(json.dumps(args, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    receipt = storage.conn.execute('SELECT * FROM ai_analyses WHERE connection_id=? AND request_id=?', (grant['id'], request_id)).fetchone()
    if receipt and receipt['payload_hash'] != payload_hash:
        fail(409, 'request_conflict', 'This request_id belongs to different content. Use a new ID for a new analysis.')
    if receipt and receipt['completed'] and not receipt['resource_id']:
        fail(410, 'analysis_removed', 'The previously saved analysis has been removed. Use a new request ID to create another.')
    if receipt and receipt['resource_id']:
        resource = storage.get_paper_resource(receipt['resource_id'])
        if not resource or resource.get('paper_id') != paper['paper_id'] or not Path(storage.resource_local_path(resource)).is_file():
            fail(410, 'analysis_removed', 'The previously saved analysis has been moved or removed. Use a new request ID to create another.')
        return {'gewu_key': paper['storage_key'], 'file': file_metadata(resource), 'reused': True}
    source_id = args.get('source_file_id')
    source_hash = args.get('source_sha256', '')
    pages = args.get('pages', [])
    if not isinstance(pages, list) or len(pages) > 100 or any(isinstance(p, bool) or not isinstance(p, int) or not 1 <= p <= 100000 for p in pages):
        fail(400, 'invalid_pages', 'Source pages must be a list of positive page numbers.')
    if source_id is not None:
        require_scope(grant, 'files:read')
        source, source_path = selected_file(storage, paper, source_id)
        source_id = source['id']
        if not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', source_hash):
            fail(400, 'source_required', 'Include the source SHA-256 returned by read_paper.')
        if hashlib.sha256(read_bytes(source_path)).hexdigest() != source_hash:
            fail(409, 'source_changed', 'The source file changed. Read it again before saving the analysis.')
    elif source_hash or pages:
        fail(400, 'source_required', 'A source_file_id is required when recording a hash or page references.')
    if not receipt:
        storage.conn.execute('''INSERT INTO ai_analyses(connection_id,request_id,payload_hash,paper_id,gewu_key,
          source_resource_id,source_sha256,pages_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)''',
          (grant['id'], request_id, payload_hash, paper['paper_id'], paper['storage_key'], source_id, source_hash, json.dumps(pages), utc_now()))
        storage.conn.commit()
        receipt = storage.conn.execute('SELECT * FROM ai_analyses WHERE connection_id=? AND request_id=?', (grant['id'], request_id)).fetchone()
    provenance = {'gewu_key': paper['storage_key'], 'connection': grant['name'], 'connection_id': grant['id'],
                  'created_at': receipt['created_at'], 'request_id': request_id,
                  'source_file_id': source_id, 'source_sha256': source_hash, 'pages': pages}
    content = ('---\ngewu_ai: ' + json.dumps(provenance, ensure_ascii=False) + '\n---\n\n' + body.rstrip() + '\n').encode()
    resource = attach_file_to_paper(storage, paper_id=paper['paper_id'], filename=title.strip() + '.md',
        content=content, file_role='note', file_type='other', file_source='other',
        source_detail='AI analysis · ' + grant['name'], annotation_state='unannotated',
        added_via='ai_analysis', refresh_existing=False, mime_type='text/markdown')
    storage.conn.execute('UPDATE ai_analyses SET resource_id=?,completed=1 WHERE id=?', (resource['id'], receipt['id']))
    storage.conn.commit()
    return {'gewu_key': paper['storage_key'], 'file': file_metadata(resource), 'reused': bool(resource.get('duplicate'))}


def execute(storage, authorization, operation, args):
    if not isinstance(args, dict):
        fail(400, 'invalid_arguments', 'Tool arguments must be a JSON object.')
    grant = authenticate(storage, authorization)
    key = args.get('gewu_key', '')
    try:
        if operation == 'capabilities':
            return {'api_version': '1', 'connection': grant['name'], 'scopes': grant['scopes'],
                    'selection': grant['selection'], 'write_folder_ids': grant.get('write_folder_ids', []),
                    'expires_at': grant['expires_at']}
        require_scope(grant, 'papers:read')
        from .ai_contract import WRITE_SCOPES
        if operation in WRITE_SCOPES:
            from .ai_writes import execute_write
            result = execute_write(storage, authorization, operation, args)
        elif operation in ('get_upload_status', 'release_upload'):
            from .ai_uploads import manage_uploads
            result = manage_uploads(storage, grant, operation, args)
        elif operation == 'search_papers':
            result = search(storage, grant, args)
        elif operation in ('list_folders', 'list_folder_papers'):
            from .ai_folders import list_collection
            result = list_collection(storage, grant, operation, args)
        elif operation in ('get_paper', 'read_paper', 'save_analysis', 'download_file'):
            paper = paper_for_key(storage, grant, key)
            if operation == 'get_paper':
                result = paper_details(storage, paper)
            elif operation == 'read_paper':
                require_scope(grant, 'files:read')
                result = read_paper(storage, paper, args)
            elif operation == 'download_file':
                require_scope(grant, 'files:read')
                resource, path = selected_file(storage, paper, args.get('file_id', 'default'))
                if not READ_SLOTS.acquire(blocking=False):
                    fail(429, 'busy', 'Two file reads are already running. Retry shortly.')
                try:
                    result = (file_metadata(resource), read_bytes(path))
                finally:
                    READ_SLOTS.release()
            else:
                require_scope(grant, 'analysis:write')
                with WRITE_LOCK:
                    grant = authenticate(storage, authorization)
                    paper = paper_for_key(storage, grant, key)
                    result = save_analysis(storage, grant, paper, args)
        else:
            fail(404, 'unknown_tool', 'This API operation is not available.')
        # A revoke, disable or collection move during a long extraction takes
        # effect before any content is returned to the client.
        fresh = authenticate(storage, authorization)
        if operation in ('list_folders', 'list_folder_papers'):
            from .ai_folders import verify_result
            verify_result(storage, fresh, result)
        if key:
            paper_for_key(storage, fresh, key)
        audit(storage, grant, operation, key)
        return result
    except APIError as exc:
        audit(storage, grant, operation, '', exc.code)
        raise
