"""Backed-up exact-duplicate repair, before normal App workers start.

Never use annotation-insensitive hashes to discard versions. Saved AI analyses
and conflicting manual classifications are left for explicit review.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3

from .file_layout_journal import write_json
from .resource_dedup import local_path, remember_source
from .resource_fingerprint import sha256_for_file
from .time_utils import now_iso

SETTING = 'resource_exact_duplicate_repair_v1'


def duplicate_groups(storage):
    sizes = defaultdict(list)
    for row in storage.conn.execute('''SELECT * FROM resources WHERE paper_id IN
        (SELECT paper_id FROM resources GROUP BY paper_id HAVING count(*) > 1) ORDER BY id'''):
        resource = dict(row)
        if not local_path(resource):
            continue
        path = Path(local_path(resource))
        try:
            if path.is_file():
                sizes[(resource['paper_id'], path.stat().st_size)].append(resource)
        except OSError:
            continue
    for candidates in sizes.values():
        if len(candidates) < 2:
            continue
        hashes = defaultdict(list)
        for resource in candidates:
            try:
                hashes[sha256_for_file(Path(local_path(resource)))].append(resource)
            except OSError:
                continue
        for digest, resources in hashes.items():
            if len(resources) > 1:
                yield digest, resources


def merge_group(storage, digest, resources, directory):
    from . import ui_server as ui
    paper_id = resources[0]['paper_id']
    storage.conn.execute('BEGIN IMMEDIATE')
    try:
        for resource in resources:
            current = storage.get_paper_resource(resource['id'])
            if current != resource or sha256_for_file(Path(local_path(resource))) != digest:
                raise ValueError('Paper File changed during duplicate repair')
            if resource.get('added_via') == 'ai_analysis' or storage.conn.execute(
                'SELECT 1 FROM ai_analyses WHERE resource_id=? OR source_resource_id=?',
                (resource['id'], resource['id'])).fetchone():
                raise ValueError('AI analysis or analysis source retained for review')
        # Different positive classifications or explicit contradictory overrides
        # are meaningful user choices, even when bytes happen to be identical.
        for field in ('file_type', 'version_role', 'version_label', 'version_date', 'version_number'):
            values = {r.get(field) for r in resources} - {None, '', 'unknown', 'other', 'Imported PDF'}
            if len(values) > 1:
                raise ValueError(f'Conflicting {field}; retained for review')
        for flag, field in (('annotation_override', 'annotation_state'), ('file_type_override', 'file_type')):
            if len({r.get(field) for r in resources if r.get(flag)}) > 1:
                raise ValueError(f'Conflicting manual {field}; retained for review')
        paper = storage.get_paper(paper_id)
        preferred = paper.get('preferred_resource_id') if paper.get('preferred_resource_manual') else None
        primary = paper.get('primary_resource_id')
        keep = min(resources, key=lambda r: (r['id'] != preferred, r['id'] != primary, r['id']))
        remove = [r for r in resources if r['id'] != keep['id']]
        keeper_path = Path(local_path(keep)).resolve()
        report = {'paper_id': paper_id, 'survivor_id': keep['id'], 'sha256': digest,
                  'removed_ids': [r['id'] for r in remove], 'files': [], 'state': 'prepared'}
        roots = [p.resolve() for p in (ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT,
            ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT, ui.ASSOCIATED_FILES_ROOT, ui.DEFAULT_PDF_DIR)]
        seen = set()
        removed_ids = report['removed_ids']
        for resource in remove:
            path = Path(local_path(resource)).resolve()
            if path == keeper_path or path in seen:
                continue
            seen.add(path)
            if resource.get('storage_mode') == 'linked' or not any(path.is_relative_to(root) for root in roots):
                continue
            # A byte duplicate belonging to another work is not ours to remove.
            references = storage.conn.execute('''SELECT id FROM resources
                WHERE stored_path=? OR (COALESCE(stored_path,'')='' AND source_path=?)''', (str(path), str(path))).fetchall()
            if any(row['id'] not in removed_ids for row in references):
                continue
            if storage.conn.execute('''SELECT 1 FROM papers WHERE paper_id!=?
                AND (main_pdf_path=? OR merged_pdf_path=?)''', (paper_id, str(path), str(path))).fetchone():
                continue
            target = directory / 'files' / str(resource['id']) / path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if sha256_for_file(target) != digest:
                raise OSError('Duplicate backup verification failed')
            with target.open('rb') as saved:
                os.fsync(saved.fileno())
            report['files'].append({'source': str(path), 'backup': str(target)})
        report_path = directory / f"group-{keep['id']}.json"
        write_json(report_path, report)
        for resource in resources:
            remember_source(storage, keep['id'], resource, digest)
        for resource in remove:
            rid = resource['id']
            storage.conn.execute('''INSERT OR REPLACE INTO resource_duplicate_archive
                VALUES(?,?,?,?,?)''', (rid, keep['id'], json.dumps(resource, ensure_ascii=False), str(directory), now_iso()))
            storage.conn.execute('''INSERT OR IGNORE INTO resource_import_sources
                SELECT ?,source_path,size_bytes,kind,sha256,import_batch_id,record_json,created_at
                FROM resource_import_sources WHERE resource_id=?''', (keep['id'], rid))
            storage.conn.execute('''UPDATE resources SET supersedes_resource_id=
                CASE WHEN id=? THEN NULL ELSE ? END WHERE supersedes_resource_id=?''', (keep['id'], keep['id'], rid))
            for field in ('primary_resource_id', 'preferred_resource_id'):
                storage.conn.execute(f'UPDATE papers SET {field}=? WHERE paper_id=? AND {field}=?', (keep['id'], paper_id, rid))
            storage.conn.execute('DELETE FROM resources WHERE id=?', (rid,))
        # Preserve explicitly set metadata; fill unknowns from equivalent rows.
        merged = dict(keep)
        for resource in remove:
            for field in ('file_type', 'file_source', 'source_detail', 'version_role', 'version_label',
                          'version_date', 'version_number', 'source_url', 'annotation_state', 'content_sha256'):
                if merged.get(field) in (None, '', 'unknown', 'other', 'Imported PDF') and resource.get(field):
                    merged[field] = resource[field]
            for flag, field in (('annotation_override', 'annotation_state'), ('file_type_override', 'file_type')):
                if resource.get(flag):
                    merged[flag], merged[field] = 1, resource[field]
            merged['annotation_count'] = max(merged.get('annotation_count') or 0, resource.get('annotation_count') or 0)
            merged['is_annotated'] = max(merged.get('is_annotated') or 0, resource.get('is_annotated') or 0)
        if merged.get('annotation_override'):
            merged['is_annotated'] = int(merged.get('annotation_state') == 'annotated')
        merged['sha256'] = digest
        fields = [k for k in merged if merged[k] != keep[k]]
        if fields:
            storage.conn.execute('UPDATE resources SET '+','.join(f'{k}=?' for k in fields)+' WHERE id=?',
                                 [merged[k] for k in fields]+[keep['id']])
        raw = json.loads(paper.get('raw_json') or '{}')
        old_paths = {local_path(r) for r in remove}
        for field in ('main_pdf_path', 'merged_pdf_path'):
            if paper.get(field) in old_paths:
                storage.conn.execute(f'UPDATE papers SET {field}=? WHERE paper_id=?', (str(keeper_path), paper_id))
        for section, field in (('import', 'stored_path'), ('file_layout', 'canonical_path')):
            if raw.get(section, {}).get(field) in old_paths:
                raw[section][field] = str(keeper_path)
        if raw.get('file_layout', {}).get('default_resource_id') in removed_ids:
            raw['file_layout']['default_resource_id'] = keep['id']
        raw.setdefault('file_layout', {})['links_pending'] = True
        storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?', (json.dumps(raw, ensure_ascii=False), paper_id))
        storage.conn.commit()
    except Exception:
        storage.conn.rollback()
        raise
    finish_files(storage, report, report_path)
    return report


def finish_files(storage, report, report_path):
    # On restart, archive rows prove the database merge committed. Otherwise
    # retain the originals. Backup bytes are never deleted by this migration.
    if not all(storage.conn.execute('SELECT 1 FROM resource_duplicate_archive WHERE resource_id=? AND survivor_id=?',
                                   (rid, report['survivor_id'])).fetchone() for rid in report['removed_ids']):
        return
    for entry in report['files']:
        source, backup = Path(entry['source']), Path(entry['backup'])
        if not source.exists():
            continue
        if storage.conn.execute('SELECT 1 FROM resources WHERE stored_path=? OR source_path=?',
                                (str(source), str(source))).fetchone():
            continue
        if sha256_for_file(backup) != report['sha256'] or sha256_for_file(source) != report['sha256']:
            raise ValueError('File changed after duplicate merge; retained for review')
        source.unlink()
        from . import ui_server as ui
        if source.is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()):
            ui.cleanup_empty_parents([str(source)], ui.ASSOCIATED_FILES_ROOT.resolve())
    report['state'] = 'complete'
    write_json(report_path, report)


def migrate(storage):
    from . import ui_server as ui
    if storage.db_path.parent.resolve() != ui.LIBRARY_LOCAL_COPY_ROOT.resolve().parent:
        return {'skipped': 'custom database roots'}
    from .file_layout_journal import recover
    recover(storage)
    root = storage.db_path.parent / 'resource-dedup-backups'
    for path in sorted(root.glob('*/group-*.json')):
        report = json.loads(path.read_text())
        if report.get('state') != 'complete':
            try:
                finish_files(storage, report, path)
            except Exception as exc:
                report['cleanup_error'] = str(exc)
                write_json(path, report)
                logging.getLogger(__name__).exception('Duplicate cleanup deferred: %s', path)
    if storage.get_setting(SETTING, '') == '1':
        return {'skipped': 'already checked'}
    groups = list(duplicate_groups(storage))
    if not groups:
        storage.set_setting(SETTING, '1')
        return {'merged': [], 'deferred': []}
    directory = root / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    directory.mkdir(parents=True)
    with sqlite3.connect(directory / 'before.sqlite') as backup:
        storage.conn.backup(backup)
    report = {'backup_directory': str(directory), 'merged': [], 'deferred': []}
    for digest, resources in groups:
        try:
            report['merged'].append(merge_group(storage, digest, resources, directory))
        except Exception as exc:
            report['deferred'].append({'resource_ids': [r['id'] for r in resources], 'reason': str(exc)})
        write_json(directory / 'report.json', report)
    storage.set_setting(SETTING, '1')
    storage.set_setting(SETTING+'_report', str(directory / 'report.json'))
    return report
