"""Explicit DOI-conflict review from Paper Details only.

No import, extraction, fetch or automatic reconciliation entry point calls
resolve_conflict. A review is read-only; confirmation rechecks both records,
their placements/resources and file identities under the writer lock. Reuse
the existing identity merger and recoverable file-move journal, without
changing their automatic policies or moving external originals.
"""
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path

from . import finder_alias, identifier_correction, metadata_refresh, paper_identity
from .download import paper_download_lock
from .file_layout import bundle_path
from .folder_rename import RenameJournal
from .publication_jobs import MUTATION_LOCK


def _ui():
    from . import ui_server
    return ui_server


def _resources(storage, pid):
    # Review must not backfill registrations or commit anything.
    return storage.list_paper_resources(pid, ensure_primary=False)


def _owner(storage, pid, doi):
    rows = storage.conn.execute(
        'SELECT paper_id FROM papers WHERE lower(trim(doi))=? AND paper_id<>? ORDER BY paper_id',
        (doi, pid)).fetchall()
    if len(rows) > 1:
        raise ValueError('More than two records use this DOI. No records were changed; review these records separately.')
    return storage.get_paper(rows[0]['paper_id']) if rows else None


def _placement(storage, paper, item_id):
    ui = _ui()
    if item_id:
        item = storage.get_library_item(int(item_id))
        if not item or item['paper_id'] != paper['paper_id'] or item.get('trashed_at'):
            raise ValueError('The selected Library location changed. Reopen Paper Details and try again.')
        directory = ui.local_copy_dir_for_library_folder(storage, item['folder_id']).resolve()
        if directory not in ui.active_directories(storage, [paper['paper_id']]):
            raise ValueError('Restore this paper from Recycle before merging.')
        return directory
    directories = ui.active_directories(storage, [paper['paper_id']])
    current = ui.canonical_file_path_for_paper(paper)
    return current.parent if current and current.parent in directories else (directories[0] if directories else None)


def _fingerprint(storage, papers, item_id):
    ids = [p['paper_id'] for p in papers]
    files = []
    for pid in ids:
        for r in _resources(storage, pid):
            value = storage.resource_local_path(r)
            try:
                st = Path(value).stat() if value else None
            except FileNotFoundError:
                st = None
            files.append((r['id'], value, (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) if st else None))
    state = [paper_identity.fingerprint(storage, ids), files, item_id, _import_receipts(storage, ids),
             [str(p) for pid in ids for p in _ui().active_directories(storage, [pid])]]
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def _import_receipts(storage, ids):
    tables = {r[0] for r in storage.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {table: [dict(r) for r in storage.conn.execute(
        'SELECT * FROM '+table+' WHERE paper_id IN ('+','.join('?' for _ in ids)+') ORDER BY rowid', ids)]
        for table in ('zotero_import_papers', 'zotero_import_files') if table in tables}


def _card(storage, paper):
    ui = _ui()
    raw = ui.parse_raw_json(paper)
    pubmed = raw.get('pubmed') if isinstance(raw.get('pubmed'), dict) else {}
    authors = ui.full_author_names(paper) or pubmed.get('authors') or raw.get('authors') or []
    resources = _resources(storage, paper['paper_id'])
    default = storage._select_default_paper_resource(paper, resources)
    monitors = []
    for table, label in (('journal_monitor_papers', 'Journal Monitor'), ('theme_results', 'Subject Monitor'),
                         ('author_monitor_papers', 'Author Monitor')):
        if storage.conn.execute('SELECT 1 FROM '+table+' WHERE paper_id=? LIMIT 1', (paper['paper_id'],)).fetchone():
            monitors.append(label)
    return {k: paper.get(k) or '' for k in ('paper_id', 'storage_key', 'title', 'journal', 'publication_date', 'doi')} | {
        'authors': ', '.join(name for name in authors if isinstance(name, str)), 'monitors': monitors,
        'locations': [str(p) for p in ui.active_directories(storage, [paper['paper_id']])],
        'default_file': Path(storage.resource_local_path(default)).name if default else '',
        'file_count': len(resources)}


def review(storage, paper_id, value, *, item_id=0):
    current = storage.get_paper(storage.resolve_paper_id(paper_id))
    if not current:
        raise KeyError('Paper not found')
    doi = metadata_refresh.valid_doi(value)
    if not doi or doi == metadata_refresh.valid_doi(current.get('doi')):
        return None  # Existing normal save/validation path remains authoritative.
    other = _owner(storage, current['paper_id'], doi)
    if not other:
        return None
    directory = _placement(storage, current, item_id)
    return {'doi': doi, 'current': _card(storage, current), 'existing': _card(storage, other),
            'item_id': int(item_id or 0), 'main_location': str(directory or ''),
            'fingerprint': _fingerprint(storage, [current, other], int(item_id or 0))}


def _set_doi(storage, paper, doi, *, retired=False):
    """Transaction-local form of a manual edit; never commits independently."""
    ui = _ui()
    raw = ui.parse_raw_json(paper)
    old = metadata_refresh.valid_doi(paper.get('doi'))
    timestamp = datetime.now().astimezone().isoformat(timespec='microseconds')
    raw.update(manual_doi_identifier_override=True, manual_doi_identifier=doi,
               manual_doi_identifier_updated_at=timestamp)
    identifier_correction.mark(raw, 'doi', doi, old, timestamp)
    updates = {'doi': doi or None, 'last_seen_at': timestamp}
    urls = {k: paper[k] for k in ('url', 'landing_url', 'pdf_url')
            if old and storage._identity_url_doi(paper.get(k)) == old}
    if urls:
        raw.setdefault('manual_identifier_history', []).append({'doi': old, 'urls': urls, 'updated_at': timestamp})
        updates.update({k: None for k in urls})
    if retired:
        # Preserve the entire pre-correction record in identity history below.
        # These cached DOI projections must not keep displaying the wrong work.
        for key in ('DOI', 'doi', 'crossref', 'openalex', 'openalex_id', 'semantic_scholar',
                    'citation_versions', 'cited_by_count', 'is-referenced-by-count', 'counts_by_year'):
            raw.pop(key, None)
        raw['manual_doi_reassignments'] = list(dict.fromkeys([*raw.get('manual_doi_reassignments', []), old]))
        updates.update(semantic_scholar_json=None, semantic_scholar_enriched_at=None)
    updates['raw_json'] = json.dumps(raw, ensure_ascii=False)
    storage.conn.execute('UPDATE papers SET '+','.join(k+'=?' for k in updates)+' WHERE paper_id=?',
                         (*updates.values(), paper['paper_id']))
    paper_identity.register(storage, storage.get_paper(paper['paper_id']))


def reject_retired_doi(storage, current, incoming):
    """Only protect records explicitly separated by this confirmation flow."""
    retired = storage._paper_raw_dict(current).get('manual_doi_reassignments') or []
    value = metadata_refresh.valid_doi(incoming.get('doi'))
    if value in retired and value != metadata_refresh.valid_doi(current.get('doi')):
        raise paper_identity.IdentityReviewRequired(current, incoming, ['manually_reassigned_doi'])


def _file_plan(storage, current, other, item_id):
    ui = _ui()
    roots = [p.resolve() for p in (ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT,
             ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT, ui.ASSOCIATED_FILES_ROOT, ui.DEFAULT_PDF_DIR)]
    if storage.db_path.parent.resolve() != roots[0].parent:
        raise ValueError('The selected database and managed file locations do not match.')
    resources = _resources(storage, current['paper_id']) + _resources(storage, other['paper_id'])
    default = storage._select_default_paper_resource(current, _resources(storage, current['paper_id']))
    if not default:
        default = storage._select_default_paper_resource(other, _resources(storage, other['paper_id']))
    directory = _placement(storage, current, item_id)
    if not default:
        if any(r.get('stored_path') for r in resources):
            raise ValueError('No available Default file. Restore or select a Default file before merging.')
        return None, None, [], {}, resources
    source_main = Path(storage.resource_local_path(default)).resolve()
    if not directory:
        # A manual conflict can also be reviewed in Monitor Paper Details.
        # Use an existing placement; never invent a Library membership.
        directory = _placement(storage, other, 0)
    if not directory:
        if resources:
            raise ValueError('Save the current paper to Library before merging its files.')
        return default, source_main, [], {}, resources
    if default.get('storage_mode') == 'linked' or not any(source_main.is_relative_to(r) for r in roots):
        raise ValueError('The current Default is an external linked file. Copy it into Gewu before merging; the original was not moved.')
    canonical = source_main if source_main.parent == directory else directory / source_main.name
    aliases = {}
    if canonical != source_main and finder_alias.points_to(canonical, source_main):
        aliases[canonical] = (None, source_main)
    elif canonical != source_main and os.path.lexists(canonical):
        raise FileExistsError('The selected main file location is occupied. No files were changed.')
    bundle = bundle_path(ui, canonical, current['storage_key'])
    if not bundle:
        raise ValueError('No managed Associated Files location is available.')
    old_bundles = [ui.existing_associated_work_dir(storage, p['paper_id']) for p in (current, other)]
    if finder_alias.is_alias(bundle):
        if not any(b and finder_alias.points_to(bundle, b) for b in old_bundles):
            raise FileExistsError('The Associated Files location is occupied.')
        aliases[bundle] = (None, finder_alias.resolve(bundle))
    pairs, destinations, seen = [], {canonical}, set()
    ids = {current['paper_id'], other['paper_id']}
    for r in resources:
        value = storage.resource_local_path(r)
        if not value:
            continue
        old = Path(value).resolve()
        if r.get('storage_mode') == 'linked' or not any(old.is_relative_to(root) for root in roots):
            continue  # External linked originals retain their references.
        if not old.is_file():
            raise ValueError('A managed Paper File is missing. Restore it before merging.')
        if old in seen:
            raise ValueError('Multiple file registrations share one path. Review Paper Files before merging.')
        seen.add(old)
        if set(ui.paper_ids_referencing_pdf_path(storage, old, include_resources=True)) - ids:
            raise ValueError('A file is shared with another paper. No records or files were changed.')
        if r['id'] == default['id']:
            new = canonical
        else:
            old_bundle = next((b for b in old_bundles if b and old.is_relative_to(b)), None)
            new = bundle / (old.relative_to(old_bundle) if old_bundle else
                            Path(ui.associated_resource_subdir(r.get('file_role') or 'other')) / old.name)
            if new != old:
                base = new
                index = 2
                while new in destinations or os.path.lexists(new):
                    new = base.with_name(f'{base.stem} {index}{base.suffix}')
                    index += 1
            destinations.add(new)
        if new != old:
            pairs.append((old, new))
    # Only existing shortcuts in these two records' known placements. Never
    # scan other Library trees or touch unregistered files.
    for paper, old_bundle in zip((current, other), old_bundles):
        old_main = ui.canonical_file_path_for_paper(paper)
        for folder in ui.active_directories(storage, [paper['paper_id']]):
            if folder.is_dir():
                for alias in folder.iterdir():
                    if alias not in aliases and old_main and finder_alias.points_to(alias, old_main):
                        aliases[alias] = (alias, canonical)
        for value in ui.parse_raw_json(paper).get('file_layout', {}).get('associated_aliases', []):
            alias = Path(value)
            if alias not in aliases and old_bundle and finder_alias.points_to(alias, old_bundle):
                # Old key-named folder projections are rebuilt for the survivor.
                aliases[alias] = (None, old_bundle)
    return default, canonical, pairs, aliases, resources


def resolve_conflict(storage, paper_id, value, *, action, fingerprint, item_id=0):
    if action not in {'merge', 'reassign'}:
        raise ValueError('Choose Merge Records or Correct DOI Assignment.')
    ui = _ui()
    pid = storage.resolve_paper_id(paper_id)
    doi = metadata_refresh.valid_doi(value)
    other = _owner(storage, pid, doi)
    if not other:
        raise ValueError('The DOI conflict changed. Reopen Paper Details and review it again.')
    journal = None
    with MUTATION_LOCK, ExitStack() as locks:
        for key in sorted({pid, other['paper_id']}):
            locks.enter_context(paper_download_lock(storage.db_path, key, blocking=False))
        storage.conn.execute('BEGIN IMMEDIATE')
        try:
            checked = review(storage, pid, doi, item_id=item_id)
            if not checked or not fingerprint or checked['fingerprint'] != fingerprint:
                raise ValueError('These records or files changed. Cancel and review the DOI conflict again.')
            current = storage.get_paper(pid)
            other = storage.get_paper(checked['existing']['paper_id'])
            snapshot = {'current': current, 'existing': other, 'review': checked}
            snapshot['import_receipts'] = _import_receipts(storage, [pid, other['paper_id']])
            if action == 'reassign':
                _set_doi(storage, other, '', retired=True)
                _set_doi(storage, current, doi)
            else:
                default, canonical, pairs, aliases, resources = _file_plan(storage, current, other, item_id)
                # Explicitly reviewed choices only. The generic merger's guards
                # continue to apply to every automatic invocation.
                source_raw = ui.parse_raw_json(other)
                source_raw.pop('manual_doi_identifier_override', None)
                storage.conn.execute('UPDATE papers SET preferred_resource_manual=0,raw_json=? WHERE paper_id=?',
                                     (json.dumps(source_raw, ensure_ascii=False), other['paper_id']))
                if default:
                    storage.conn.execute('UPDATE papers SET preferred_resource_id=?,preferred_resource_manual=1 WHERE paper_id=?',
                                         (default['id'], pid))
                paper_identity._merge_locked(storage, pid, other['paper_id'], reason='manual_doi_merge', evidence=current)
                _set_doi(storage, storage.get_paper(pid), doi)
                if current.get('journal') in {'Imported Library', 'Imported Publications'} and other.get('journal'):
                    storage.conn.execute('UPDATE papers SET journal=? WHERE paper_id=?', (other['journal'], pid))
                if pairs or aliases:
                    journal = RenameJournal(storage, pairs, [old for old, _ in pairs], [], aliases, create_root=False)
                    journal.apply()
                    for old, new in pairs:
                        ui.update_paper_file_path_references(storage, pid, old, new, commit=False)
                    storage.conn.execute('INSERT INTO app_settings(key,value,updated_at) VALUES(?,?,?)', (journal.key, '1', ui.now_iso()))
                if default:
                    raw = ui.parse_raw_json(storage.get_paper(pid))
                    raw['file_layout'] = {**raw.get('file_layout', {}), 'canonical_path': str(canonical),
                        'default_resource_id': default['id'], 'associated_aliases': [], 'version': 1, 'links_pending': True}
                    pdf = storage.resource_is_pdf(default)
                    storage.conn.execute('UPDATE papers SET preferred_resource_id=?,preferred_resource_manual=1,primary_resource_id=?,main_pdf_path=?,merged_pdf_path=?,raw_json=? WHERE paper_id=?',
                        (default['id'], default['id'] if pdf else None, str(canonical) if pdf else '',
                         str(canonical) if pdf else '', json.dumps(raw, ensure_ascii=False), pid))
                # Keep copy-only migration idempotent after this explicit merge.
                # Original receipts remain in the review history; no source data
                # or registered file bytes are removed on a receipt collision.
                if 'zotero_import_papers' in snapshot['import_receipts']:
                    storage.conn.execute('UPDATE zotero_import_papers SET paper_id=? WHERE paper_id=?', (pid, other['paper_id']))
                if 'zotero_import_files' in snapshot['import_receipts']:
                    storage.conn.execute('INSERT OR IGNORE INTO zotero_import_files SELECT source_id,source_key,digest,?,resource_id FROM zotero_import_files WHERE paper_id=?', (pid, other['paper_id']))
                    storage.conn.execute('DELETE FROM zotero_import_files WHERE paper_id=?', (other['paper_id'],))
            storage.conn.execute('INSERT INTO paper_identity_history(target_paper_id,source_paper_id,source_key,reason,snapshot_json,created_at) VALUES(?,?,?,?,?,?)',
                (pid, other['paper_id'], other['storage_key'], 'manual_doi_'+action+'_review', json.dumps(snapshot, ensure_ascii=False), ui.now_iso()))
            storage.conn.execute('DELETE FROM author_monitor_card_cache WHERE paper_id IN (?,?)', (pid, other['paper_id']))
            storage.conn.commit()
        except Exception:
            storage.conn.rollback()
            if journal:
                journal.rollback()  # Keep the recovery journal if rollback itself cannot finish.
            raise
        warning = ''
        if journal:
            try:
                journal.finish(storage)
            except OSError:
                logging.getLogger(__name__).exception('DOI merge committed; journal cleanup deferred')
        if action == 'merge':
            try:
                ui.sync_all_pdf_aliases_for_paper(storage, pid, preserve_canonical_name=True)
            except Exception:
                storage.conn.rollback()
                logging.getLogger(__name__).exception('DOI merge committed; folder shortcut refresh needs attention')
                warning = 'Records and files were merged. Some folder shortcuts could not be refreshed.'
        papers = [storage.get_paper(pid)]
        if action == 'reassign':
            papers.append(storage.get_paper(other['paper_id']))
        return {'paper': papers[0], 'changed_papers': papers,
                'merged_paper_id': other['paper_id'] if action == 'merge' else '', 'warning': warning}
