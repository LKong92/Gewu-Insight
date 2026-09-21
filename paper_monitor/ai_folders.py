"""Read-only logical collection browsing, projected through one current grant.

No filesystem paths, shared working directory or persisted cursor state. The
revision covers only the visible graph, never private siblings or global data.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re

from .ai_store import fail


OPERATIONS = ('list_folders', 'list_folder_papers')


def changed():
    fail(409, 'collection_changed', 'The authorized directory structure or membership changed. Restart the directory listing without cursor or revision.')


def projection(storage, grant):
    from .ai_service import ACTIVE_FOLDERS, require_scope, selection_sql, _read_selection_sql
    require_scope(grant, 'papers:read')
    require_scope(grant, 'folders:read')
    # One SQLite read snapshot covers both the tree and its memberships. Release
    # it before execute() reauthenticates and checks for concurrent changes.
    storage.conn.execute('SAVEPOINT ai_folder_read')
    try:
        folders = {r['id']: dict(r) for r in storage.conn.execute(ACTIVE_FOLDERS + '''
          SELECT f.id,f.name,f.parent_id FROM library_folders f
          JOIN active_folders a ON a.id=f.id ORDER BY f.id''')}
        clause, params = selection_sql(grant)
        members = [dict(r) for r in storage.conn.execute(ACTIVE_FOLDERS + '''
          SELECT i.id AS membership_id,i.folder_id,p.storage_key AS gewu_key
          FROM library_items i JOIN papers p ON p.paper_id=i.paper_id
          JOIN active_folders a ON a.id=i.folder_id
          WHERE COALESCE(i.trashed_at,'')='' AND ''' + clause + ' ORDER BY i.id', params)]
        read_clause, read_params = _read_selection_sql(grant)
        originally_readable = {r[0] for r in storage.conn.execute(ACTIVE_FOLDERS + '''
          SELECT p.storage_key FROM papers p WHERE ''' + read_clause, read_params)}
    finally:
        storage.conn.execute('RELEASE ai_folder_read')

    children = {}
    for f in folders.values():
        children.setdefault(f['parent_id'], []).append(f['id'])
    kind = grant['selection']['kind']
    if kind == 'folder':
        anchor = grant['selection']['folder_id']
        visible, pending = set(), [anchor] if anchor in folders else []
        while pending:
            current = pending.pop()
            visible.add(current)
            pending.extend(children.get(current, []))
    elif kind == 'papers':
        visible = set()
        for member in members:
            if member['gewu_key'] not in originally_readable:
                continue
            current = member['folder_id']
            while current in folders and current not in visible:
                visible.add(current)
                current = folders[current]['parent_id']
    else:
        visible = set(folders)
    from .ai_contract import WRITE_SCOPES
    if set(grant['scopes']).intersection(WRITE_SCOPES.values()):
        pending=[root for root in grant.get('write_folder_ids',[]) if root in folders]
        while pending:
            current=pending.pop()
            visible.add(current)
            pending.extend(children.get(current,[]))
    members = [m for m in members if m['folder_id'] in visible]
    projected = {}
    for folder_id in sorted(visible):
        f = folders[folder_id]
        projected[folder_id] = {
            'folder_id': folder_id, 'name': f['name'],
            'kind': 'library' if folder_id == 1 else 'space' if f['parent_id'] is None else 'folder',
            'parent_id': f['parent_id'] if f['parent_id'] in visible else None,
        }
    # The digest excludes inaccessible nodes, their counts and metadata refresh
    # timestamps. Renames/moves and placement/key changes invalidate a walk.
    payload = [grant['id'], grant['selection'], projected, members]
    revision = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    return projected, members, revision


def describe(folders, members, folder_id, relative):
    folder = folders[folder_id]
    path, current = [], folder
    while current:
        path.append({'folder_id': current['folder_id'], 'name': current['name']})
        current = folders.get(current['parent_id'])
    path.reverse()
    return {**folder, 'path': path, 'logical_path': ' / '.join(p['name'] for p in path),
            'path_is_relative_to_grant': relative,
            'child_folder_count': sum(f['parent_id'] == folder_id for f in folders.values()),
            'direct_paper_count': sum(m['folder_id'] == folder_id for m in members)}


def read_cursor(value, query, revision):
    if value is None:
        return 0
    if not isinstance(value, str) or not 1 <= len(value) <= 1024:
        fail(400, 'invalid_cursor', 'Use the next_cursor returned by this listing.')
    try:
        data = json.loads(base64.b64decode(value.encode('ascii'), altchars=b'-_', validate=True))
        if (not isinstance(data, dict) or set(data) != {'v', 'q', 'r', 'last'}
                or data['v'] != 1 or data['q'] != query
                or type(data['last']) is not int or not 0 < data['last'] < 2**63
                or not isinstance(data['r'], str) or not re.fullmatch('[0-9a-f]{64}', data['r'])):
            raise ValueError()
    except (ValueError, UnicodeError, TypeError):
        fail(400, 'invalid_cursor', 'Use the next_cursor from the same listing and options.')
    if data['r'] != revision:
        changed()
    return data['last']


def list_collection(storage, grant, operation, args):
    from .ai_service import integer, metadata, paper_for_key
    allowed = {'limit', 'cursor', 'revision'} | ({'parent_id'} if operation == 'list_folders' else {'folder_id', 'recursive'})
    if set(args) - allowed:
        fail(400, 'invalid_arguments', 'Use only the documented directory listing arguments.')
    limit = integer(args.get('limit'), 50, 1, 100)
    raw_id = args.get('parent_id' if operation == 'list_folders' else 'folder_id')
    if raw_id is None and operation == 'list_folder_papers':
        fail(400, 'invalid_arguments', 'Provide the folder_id returned by list_folders.')
    folder_id = integer(raw_id, None, 1, 2**63 - 1)
    recursive = args.get('recursive', False)
    if type(recursive) is not bool:
        fail(400, 'invalid_arguments', 'recursive must be true or false.')
    expected = args.get('revision')
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch('[0-9a-f]{64}', expected)):
        fail(400, 'invalid_revision', 'Use the revision returned by a directory listing.')
    folders, members, revision = projection(storage, grant)
    # Unknown and unauthorized IDs are indistinguishable, even with a cursor.
    if folder_id is not None and folder_id not in folders:
        fail(404, 'folder_unavailable', 'This folder was not found in the authorized collection.')
    if expected is not None and expected != revision:
        changed()
    query = [operation, folder_id, recursive]
    last = read_cursor(args.get('cursor'), query, revision)
    relative = grant['selection']['kind'] == 'folder'
    if operation == 'list_folders':
        eligible = [f for f in folders.values() if f['parent_id'] == folder_id and f['folder_id'] > last]
        page = eligible[:limit]
        result = {'parent_id': folder_id, 'folders': [describe(folders, members, f['folder_id'], relative) for f in page]}
        last_id = page[-1]['folder_id'] if page else 0
    else:
        descendants = {folder_id}
        if recursive:
            children = {}
            for f in folders.values():
                children.setdefault(f['parent_id'], []).append(f['folder_id'])
            pending = [folder_id]
            while pending:
                current = pending.pop()
                descendants.update(children.get(current, []))
                pending.extend(children.get(current, []))
        eligible = [m for m in members if m['folder_id'] in descendants and m['membership_id'] > last]
        page = eligible[:limit]
        entries = []
        for member in page:
            paper = metadata(paper_for_key(storage, grant, member['gewu_key']))
            entries.append({**member, 'paper': {k: paper[k] for k in (
                'gewu_key', 'title', 'doi', 'arxiv_id', 'journal', 'publication_date')}})
        result = {'folder': describe(folders, members, folder_id, relative), 'recursive': recursive,
                  'memberships': entries}
        last_id = page[-1]['membership_id'] if page else 0
    cursor = None
    if len(eligible) > limit:
        cursor = base64.urlsafe_b64encode(json.dumps({'v': 1, 'q': query, 'r': revision, 'last': last_id},
                                                   separators=(',', ':')).encode()).decode()
    return {**result, 'revision': revision, 'next_cursor': cursor}


def verify_result(storage, fresh_grant, result):
    # A revoked folders scope or concurrent move must take effect before data
    # leaves the service, including when there was no individual key argument.
    if projection(storage, fresh_grant)[2] != result['revision']:
        changed()
