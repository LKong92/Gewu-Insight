"""Narrow import permission for uncollected provider/Monitor identities.

This is not a read grant. Call only after exact DOI/arXiv matching, destination
authorization, and while holding the paper lock and SQLite writer transaction.
"""
from pathlib import Path

from .ai_store import APIError, fail


def reusable_paper(storage, grant, candidate):
    from .ai_service import paper_for_key
    try:
        return paper_for_key(storage, grant, candidate['storage_key'])
    except APIError as exc:
        if exc.code != 'paper_unavailable':
            raise
    paper = storage.get_paper(candidate['paper_id'])
    try:
        if paper and is_uncollected_cache(storage, paper):
            return paper
    except (OSError, ValueError, TypeError, RuntimeError):
        # Unreadable/malformed path evidence (including symlink loops) cannot
        # establish this narrowly defined import permission.
        pass
    # Do not disclose an inaccessible record's Key, title, paths or contents.
    fail(403, 'import_access_required',
         'The supplied identity cannot be imported with this connection’s access. '
         'Review the collection permissions in AI Access or add the paper through '
         'the App, then retry. Existing records and files were preserved; the upload is still available.')


def is_uncollected_cache(storage, paper):
    from . import ui_server as ui
    from .resource_fingerprint import sha256_for_file
    pid = paper['paper_id']
    # Include trashed placements: import must not resurrect private/recycled work.
    for table in ('library_items', 'my_publications', 'ai_analyses'):
        if storage.conn.execute(f'SELECT 1 FROM {table} WHERE paper_id=? LIMIT 1', (pid,)).fetchone():
            return False
    if any(paper.get(k) for k in ('source_path', 'import_batch_id', 'import_kind', 'import_as', 'analysis_path')):
        return False
    raw = ui.parse_raw_json(paper)
    if any(raw.get(k) for k in ('ai_metadata', 'ai_metadata_updates', 'file', 'file_reassignment')):
        return False
    # Old provider records may predate explicit Monitor membership tracking.
    # Provider provenance is necessary, but by itself is not permission to files.
    if not storage.conn.execute("""SELECT 1 FROM paper_source_observations
            WHERE paper_id=? AND source_kind IN ('provider','monitor') LIMIT 1""", (pid,)).fetchone():
        return False
    paths = set(ui.paper_pdf_paths(paper))
    layout = raw.get('file_layout') or {}
    if not isinstance(layout, dict):
        return False
    layout_path = layout.get('canonical_path')
    if layout_path:
        paths.add(Path(layout_path).expanduser().resolve())
    resources = storage.list_paper_resources(pid, ensure_primary=False)
    download_origins = {'download_initial', 'download_refresh', 'arxiv_version_sync',
                        'publisher_browser_download', 'aaas-main-pdf', 'aaas-supplement-pdf',
                        'publisher-main-pdf', 'publisher-supplement-file', 'legacy_backfill'}
    for resource in resources:
        if (resource.get('storage_mode') != 'managed'
                or not storage.resource_is_pdf(resource)
                or resource.get('added_via') not in download_origins
                or resource.get('file_role') not in ('publication_version', 'supplement')
                or resource.get('is_annotated') or resource.get('annotation_count')
                or resource.get('annotation_state') == 'annotated'):
            return False
        value = storage.resource_local_path(resource)
        if not value:
            return False
        path = Path(value).expanduser().resolve()
        # A locally edited cached PDF is no longer demonstrably the original
        # download, even if an old annotation flag still says "unannotated".
        if resource.get('sha256') and path.is_file() and sha256_for_file(path) != resource['sha256']:
            return False
        paths.add(path)
    if paths and paper.get('download_status') not in ('success', 'partial', 'skipped'):
        return False
    # Only the App's download cache is eligible, not Library/Associated Files,
    # linked external files or another work's shared bytes. Resolve symlinks first.
    download_root = ui.DEFAULT_PDF_DIR.expanduser().resolve()
    for path in paths:
        if not path.is_relative_to(download_root) or path == download_root:
            return False
        if any(owner != pid for owner in ui.paper_ids_referencing_pdf_path(storage, path, include_resources=True)):
            return False
    return True
