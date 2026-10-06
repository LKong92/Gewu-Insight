"""Copy a closed Gewu workspace and rebase managed references without changing originals.

An existing destination is never merged or replaced. Source metadata/provenance,
external links, paper identities, classifications and file contents are preserved.
The caller switches the App's locator only after reviewing the verification.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from . import finder_alias

PATH_COLUMNS = {
    'papers': ('main_pdf_path', 'merged_pdf_path', 'source_path', 'analysis_path'),
    'resources': ('source_path', 'stored_path'),
    'inventory_import_batches': ('inventory_path', 'source_root', 'report_path'),
    'author_monitors': ('avatar_override_path',),
    'resource_duplicate_archive': ('backup_directory',),
}
JSON_COLUMNS = {
    'papers': ('supplement_pdf_paths', 'raw_json'),
    'app_settings': ('value',),
    'author_monitor_card_cache': ('payload_json',),
    'theme_results': ('hits_json',),
    'ai_write_requests': ('result_json',),
    'paper_identity_history': ('snapshot_json',),
}
MANAGED_DIRS = ('Library', 'Spaces', 'My Publications', 'Associated Files')


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def copy_path(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == 'darwin':
        subprocess.run(['/usr/bin/ditto', '--rsrc', '--extattr', str(source), str(target)], check=True)
    elif source.is_dir():
        shutil.copytree(source, target, symlinks=True)
    else:
        shutil.copy2(source, target, follow_symlinks=False)


def path_mappings(source, destination):
    # Longest prefixes first: archive previous backups outside the active data.
    mappings = []
    for child in (source / 'data').iterdir():
        if child.name in ('backups', 'recovery_backups') or 'migration_backup_' in child.name or child.name.startswith('path_rebase_backup_'):
            mappings.append((str(child), str(destination / 'backups/legacy' / child.name)))
    for name in ('data', 'reports'):
        mappings.append((str(source / name), str(destination / name)))
    return sorted(mappings, key=lambda pair: -len(pair[0]))


def rebase(value, mappings):
    if not isinstance(value, str):
        return value
    for before, after in mappings:
        if value == before or value.startswith(before + '/'):
            return after + value[len(before):]
    return value


def rebase_json(value, mappings):
    def walk(item):
        if isinstance(item, list):
            return [walk(v) for v in item]
        if isinstance(item, dict):
            return {k: walk(v) for k, v in item.items()}
        return rebase(item, mappings)
    if not isinstance(value, str):
        return value
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return rebase(value, mappings)
    updated = walk(parsed)
    return json.dumps(updated, ensure_ascii=False) if updated != parsed else value


def rebase_raw(value, mappings):
    """Only rewrite live layout pointers; retain imported source provenance."""
    try:
        raw = json.loads(value)
    except (ValueError, TypeError):
        return value
    before = json.dumps(raw, ensure_ascii=False)
    def update(raw):
        if not isinstance(raw, dict):
            return
        imported = raw.get('import')
        if isinstance(imported, dict) and 'stored_path' in imported:
            imported['stored_path'] = rebase(imported['stored_path'], mappings)
        layout = raw.get('file_layout')
        if isinstance(layout, dict):
            for key in ('canonical_path', 'associated_aliases'):
                if key in layout:
                    layout[key] = json.loads(rebase_json(json.dumps(layout[key]), mappings))
        for item in raw.get('manual_identifier_metadata_history', []):
            if isinstance(item, dict):
                update(item.get('raw'))
    update(raw)
    after = json.dumps(raw, ensure_ascii=False)
    return after if after != before else value


def migrated_value(table, column, value, mappings, stored_path=''):
    if table == 'resources' and column == 'source_path' and stored_path:
        return value  # Original import provenance; stored_path is the live copy.
    if table == 'papers' and column == 'raw_json':
        return rebase_raw(value, mappings)
    if column in JSON_COLUMNS.get(table, ()):
        return rebase_json(value, mappings)
    if column in PATH_COLUMNS.get(table, ()):
        return rebase(value, mappings)
    return value


def migrate(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists() or source == destination or source in destination.parents or destination in source.parents:
        raise ValueError('Use a new destination outside the source workspace.')
    db = source / 'data/paper_monitor.sqlite'
    from .workspace import check_database, acquire_database_lock
    check_database(db)
    # Also detect old product versions that predate the advisory process lock.
    if sys.platform == 'darwin':
        opened = subprocess.run(['/usr/sbin/lsof', '-t', str(db)], capture_output=True, text=True)
        if opened.stdout.strip():
            raise RuntimeError('Quit every App and server using the source database before migrating.')
    acquire_database_lock(db)
    for directory in ('file-layout-recovery', 'folder-rename-recovery', 'ai-import-recovery'):
        if any((source / 'data' / directory).rglob('*.json')):
            raise RuntimeError('Complete interrupted file operations in the original App before migrating.')
    mappings = path_mappings(source, destination)
    destination.mkdir(parents=True, mode=0o700)
    report = {'source': str(source), 'destination': str(destination), 'mappings': mappings,
              'changed_columns': {}, 'verified_files': 0, 'verified_bytes': 0,
              'retargeted_aliases': 0, 'preexisting_missing_aliases': 0,
              'preexisting_missing_file_references': 0}
    pairs = []
    for name in ('data', 'reports'):
        root = source / name
        (destination / name).mkdir(exist_ok=True)
        if not root.exists():
            continue
        for child in sorted(root.iterdir()):
            if name == 'data' and (child.name.startswith('paper_monitor.sqlite') or child.name == '.gewu-database.lock'):
                # Preserve old numbered sidecars only as opaque legacy artifacts.
                if child.name.startswith('paper_monitor.sqlite-shm '):
                    target = destination / 'backups/legacy/sqlite-sidecar-copies' / child.name
                    copy_path(child, target)
                    pairs.append((child, target))
                continue
            if name == 'reports' and child.is_file() and '开发' in child.name:
                continue
            target = Path(rebase(str(child), mappings))
            copy_path(child, target)
            pairs.append((child, target))
    (destination / 'config').mkdir()
    if (source / 'config').exists():
        for child in (source / 'config').iterdir():
            if child.is_file() and not child.name.endswith('.example.json'):
                target = destination / 'config' / child.name
                copy_path(child, target)
                pairs.append((child, target))
    target_db = destination / 'data/paper_monitor.sqlite'
    original = sqlite3.connect(db.as_uri() + '?mode=ro', uri=True)
    target = sqlite3.connect(target_db)
    try:
        original.backup(target)
        tables = [r[0] for r in target.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            columns = [r[1] for r in target.execute('PRAGMA table_info("' + table + '")')]
            for column in PATH_COLUMNS.get(table, ()) + JSON_COLUMNS.get(table, ()):
                if column not in columns:
                    continue
                extra = ',stored_path' if table == 'resources' else ",''"
                rows = target.execute('SELECT rowid,"' + column + '"' + extra + ' FROM "' + table + '"').fetchall()
                changes = []
                for rowid, value, stored_path in rows:
                    updated = migrated_value(table, column, value, mappings, stored_path)
                    if updated != value:
                        changes.append((updated, rowid))
                if changes:
                    target.executemany('UPDATE "' + table + '" SET "' + column + '"=? WHERE rowid=?', changes)
                    report['changed_columns'][table + '.' + column] = len(changes)
        target.commit()
        # Updates can fire cache-dirty triggers: restore the original cache-dirty
        # table exactly. The cached payload itself has been rebased above.
        if 'author_monitor_card_cache_dirty' in tables:
            target.execute('DELETE FROM author_monitor_card_cache_dirty')
            rows = original.execute('SELECT * FROM author_monitor_card_cache_dirty').fetchall()
            if rows:
                target.executemany('INSERT INTO author_monitor_card_cache_dirty VALUES (' + ','.join('?' for _ in rows[0]) + ')', rows)
            target.commit()
        report['table_counts'] = {}
        for table in tables:
            columns = [r[1] for r in original.execute('PRAGMA table_info("' + table + '")')]
            before = original.execute('SELECT * FROM "' + table + '" ORDER BY rowid').fetchall()
            after = target.execute('SELECT * FROM "' + table + '" ORDER BY rowid').fetchall()
            expected = []
            for row in before:
                values = []
                stored_path = row[columns.index('stored_path')] if table == 'resources' else ''
                for column, value in zip(columns, row):
                    value = migrated_value(table, column, value, mappings, stored_path)
                    values.append(value)
                expected.append(tuple(values))
            if after != expected:
                raise RuntimeError('Unexpected database change in ' + table)
            report['table_counts'][table] = len(before)
        old_fk = original.execute('PRAGMA foreign_key_check').fetchall()
        new_fk = target.execute('PRAGMA foreign_key_check').fetchall()
        if new_fk != old_fk:
            raise RuntimeError('Migration introduced foreign key errors.')
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Destination database integrity check failed.')
        report['foreign_key_errors'] = len(new_fk)
        # Check active registered paths without requiring preexisting missing
        # files or linked external originals to be repaired by this migration.
        for table in ('papers', 'resources'):
            for column in PATH_COLUMNS[table]:
                for (value,) in original.execute('SELECT "' + column + '" FROM "' + table + '" WHERE "' + column + '"<>\'\''):
                    if not value or not Path(value).is_absolute():
                        continue
                    updated = rebase(value, mappings)
                    if updated == value:
                        continue
                    if Path(value).is_file():
                        if not Path(updated).is_file() or digest(value) != digest(updated):
                            raise RuntimeError('Registered file verification failed: ' + updated)
                    elif not Path(value).exists():
                        report['preexisting_missing_file_references'] += 1
    finally:
        original.close()
        target.close()
    # Verify every copied regular file, including unregistered research files.
    for before, after in pairs:
        files = before.rglob('*') if before.is_dir() else [before]
        for item in files:
            counterpart = after / item.relative_to(before) if before.is_dir() else after
            if item.is_symlink():
                if not counterpart.is_symlink() or os.readlink(item) != os.readlink(counterpart):
                    raise RuntimeError('Symlink copy differs: ' + str(item))
            elif item.is_file():
                if digest(item) != digest(counterpart):
                    raise RuntimeError('Copied file bytes differ: ' + str(item))
                report['verified_files'] += 1
                report['verified_bytes'] += item.stat().st_size
    for name in MANAGED_DIRS:
        for alias in finder_alias.iter_aliases(destination / 'data' / name):
            old = finder_alias.recorded_target(alias) or finder_alias.resolve(alias)
            new = Path(rebase(str(old), mappings))
            if new == old:
                continue
            if new.exists():
                finder_alias.retarget(new, alias)
                if not finder_alias.points_to(alias, new):
                    raise RuntimeError('Alias verification failed: ' + str(alias))
                report['retargeted_aliases'] += 1
            else:
                # The original shortcut was already dangling. Keep its bytes,
                # record the new fallback target, and report it without inventing
                # a missing file or silently sending it back to the old workspace.
                if alias.is_symlink():
                    alias.unlink()
                    os.symlink(new, alias)
                else:
                    finder_alias.set_attribute(alias, finder_alias.TARGET_ATTRIBUTE, os.fsencode(new))
                report['preexisting_missing_aliases'] += 1
    backup = destination / 'backups'
    backup.mkdir(exist_ok=True)
    report['verified'] = True
    (backup / 'workspace-migration.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(migrate(args.source, args.destination), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
