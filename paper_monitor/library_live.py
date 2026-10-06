"""Workspace-only, bounded change checks for writes made by external AI clients.

Reuse the existing capped audit journal: no schema, background job, literature
fetch, global paper snapshot or persistent client cursor is needed.
"""
from .ai_contract import WRITE_SCOPES

MUTATIONS = tuple(sorted((set(WRITE_SCOPES) - {'get_resolve_status'}) | {'save_analysis'}))


def changes(storage, *, since=None, folder_ids=(), paper_id=''):
    if since is not None and (not str(since).isdigit() or not 0 <= int(since) < 2**63):
        raise ValueError('Invalid Library change cursor')
    if len(folder_ids) > 64 or any(not str(n).isdigit() or not 0 < int(n) < 2**63 for n in folder_ids):
        raise ValueError('Request at most 64 visible folders')
    if len(paper_id) > 300:
        raise ValueError('Invalid selected paper')
    oldest, latest = storage.conn.execute('SELECT MIN(id), MAX(id) FROM ai_audit').fetchone()
    oldest, latest = int(oldest or 0), int(latest or 0)
    cursor = int(since or 0)
    reset = since is None or cursor > latest or (oldest > 0 and cursor < oldest - 1)
    changed = reset or bool(storage.conn.execute(
        'SELECT 1 FROM ai_audit WHERE id>? AND outcome=? AND operation IN (' +
        ','.join('?' for _ in MUTATIONS) + ') LIMIT 1', (cursor, 'ok', *MUTATIONS)).fetchone())
    result = {'cursor': str(latest), 'changed': changed}
    if not changed:
        return result
    from . import ui_server as ui
    # Only folder metadata and currently visible memberships/resources. Other
    # cached folders are invalidated by the client and loaded on demand.
    result.update(ui.library_navigation_snapshot(storage))
    result['folders'] = [ui.library_folder_to_api(f, storage, include_native_path=False)
                         for f in storage.list_library_folders()]
    result['children'] = [ui.library_folder_children_snapshot(storage, int(n))
                          for n in dict.fromkeys(folder_ids) if storage.get_library_folder(int(n))]
    result['paper_files'] = [ui.paper_files_state_payload(storage, paper_id)] if paper_id else []
    return result
