"""Transactional, file-preserving Library/Space renames.

Moves and renames preserve registered files and Default selection. Alias
discovery is one pass per operation; callers may save a receipt in the same
transaction as the placement/path changes.
"""
from contextlib import ExitStack
import json
import logging
import os
from pathlib import Path
import shutil
import uuid

from . import finder_alias
from .download import paper_download_lock
from .file_layout_journal import write_json
from .publication_jobs import MUTATION_LOCK


def _path(value):
    # Resolve parent spellings (/var vs /private/var), not the final alias.
    path = Path(value).expanduser().absolute()
    return path.parent.resolve() / path.name


def _within(path, root):
    return path == root or root in path.parents


def _remap(path, pairs):
    for old, new in pairs:
        if _within(path, old):
            return new / path.relative_to(old)
    return path


def _walk(root):
    """Do not descend through symbolic links or Finder directory aliases."""
    if not root.is_dir() or finder_alias.is_alias(root):
        return
    for parent, dirs, files in os.walk(root, followlinks=False):
        for name in dirs[:]:
            path = Path(parent) / name
            if finder_alias.is_alias(path):
                dirs.remove(name)
            yield path
        for name in files:
            yield Path(parent) / name


def _identity(path):
    info = path.lstat()
    return [info.st_dev, info.st_ino]


def _move(source, destination):
    # Renaming within a managed root stays on the same filesystem. Exclusive
    # links preserve inode/bytes/xattrs and cannot overwrite a Finder save.
    os.link(source, destination, follow_symlinks=False)
    source.unlink()


def _spellings(path):
    value = str(path)
    yield value
    if value.startswith(('/private/var/', '/private/tmp/')):
        yield value[len('/private'):]
    elif value.startswith(('/var/', '/tmp/')):
        yield '/private' + value


def _references(storage, pairs):
    """Read current pointers once; copied source provenance is not a pointer."""
    result = set()
    def add(pid, value):
        if not value:
            return
        old = _path(value)
        new = _remap(old, pairs)
        if old != new:
            result.add((pid, old, new))
    prefixes = [value + '/' for old, _ in pairs for value in _spellings(old)]
    # Range predicates use the existing path indexes where available.
    for table, field, extra in [
        ('papers', 'main_pdf_path', ''), ('papers', 'merged_pdf_path', ''),
        ('papers', 'source_path', ''), ('papers', 'analysis_path', ''),
        ('resources', 'stored_path', ''),
        ('resources', 'source_path', " AND COALESCE(stored_path, '') = ''"),
    ]:
        for prefix in prefixes:
            for row in storage.conn.execute(
                f'SELECT paper_id, {field} AS path FROM {table} WHERE ({field} = ? OR ({field} >= ? AND {field} < ?)){extra}',
                (prefix[:-1], prefix, prefix[:-1] + '0'),
            ):
                add(row['paper_id'], row['path'])
    # Legacy supplement pointers need a single pass, never one pass per file.
    for row in storage.conn.execute("SELECT paper_id, supplement_pdf_paths FROM papers WHERE supplement_pdf_paths NOT IN ('', '[]')"):
        try:
            values = json.loads(row['supplement_pdf_paths'])
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, str):
                        add(row['paper_id'], value)
        except (ValueError, TypeError):
            continue
    return sorted(result)


def _roots(ui, directory):
    scope = ui.associated_scope_for_path(directory)
    if not scope:
        raise ValueError('The folder is outside the managed Library or Spaces.')
    label, relative = scope
    return [directory, _path(ui.ASSOCIATED_FILES_ROOT / label / relative)]


def _plan(storage, pairs):
    from . import ui_server as ui
    files, directories, aliases = [], set(), {}
    # One traversal covers both moved trees and aliases elsewhere. No persistent
    # cache can go stale between separate renames/imports/downloads.
    for root in [ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT,
                 ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT, ui.ASSOCIATED_FILES_ROOT]:
        root = Path(root).expanduser().resolve()
        for path in _walk(root):
            destination = _remap(path, pairs)
            if finder_alias.is_alias(path):
                target = finder_alias.resolve(path)
                mapped_target = _remap(target, pairs)
                if destination != path or mapped_target != target:
                    aliases[path] = (destination, mapped_target)
            elif path.is_dir():
                if destination != path:
                    directories.add(path)
            elif destination != path:
                files.append(path)
    for old, _ in pairs:
        if old.is_dir():
            directories.add(old)
    return files, directories, aliases


class RenameJournal:
    def __init__(self, storage, pairs, files, directories, aliases, *, create_root=True):
        self.root = storage.db_path.parent / 'folder-rename-recovery' / uuid.uuid4().hex
        self.path = self.root / 'operation.json'
        self.key = 'folder_rename_committed:' + self.root.name
        self.data = {'key': self.key, 'moves': [], 'aliases': [], 'stages': [],
                     'created_dirs': [], 'old_dirs': []}
        # Case-only names on a case-insensitive filesystem need an intermediate
        # sibling. All other renames keep the conservative individual-file path.
        stages = []
        for old, new in pairs:
            if os.path.lexists(new):
                if new in aliases and aliases[new][0] is None:
                    continue  # An owned projection yields to its real original.
                if old.exists() and os.path.samefile(old, new):
                    temporary = old.with_name('.gewu-rename-' + uuid.uuid4().hex)
                    stages.append((old, temporary))
                    self.data['stages'].append({'source': str(old), 'destination': str(temporary),
                                                'target': str(new), 'identity': _identity(old), 'directory': old.is_dir()})
                else:
                    raise FileExistsError(f'The destination folder already exists: {new}')
        def source(path):
            return _remap(path, stages)
        needed = {_remap(p, pairs) for p in directories}
        # Also create a real empty directory for a logical folder with no files.
        if create_root:
            needed.add(pairs[0][1])
        for old in files:
            new = _remap(old, pairs)
            self.data['moves'].append({'source': str(source(old)), 'destination': str(new),
                                       'identity': _identity(old)})
            needed.add(new.parent)
        for i, (old, (new, target)) in enumerate(aliases.items()):
            self.data['aliases'].append({'source': str(source(old)), 'destination': str(new) if new else None,
                'target': str(target), 'backup': str(self.root / f'alias-{i}'),
                'prepared': str(self.root / f'new-alias-{i}'), 'identity': _identity(old)})
            if new:
                needed.add(new.parent)
        for directory in list(needed):
            needed.update(directory.parents)
        staged_sources = {old for old, _ in stages}
        staged_targets = [new for old, new in pairs if old in staged_sources]
        displaced = {old for old, (new, _) in aliases.items() if new is None}
        self.data['created_dirs'] = [str(p) for p in sorted(needed, key=lambda p: len(p.parts))
                                    if not p.exists() or p in displaced or any(_within(p, new) for new in staged_targets)]
        self.data['old_dirs'] = [str(source(p)) for p in sorted(directories, key=lambda p: len(p.parts), reverse=True)]
        write_json(self.path, self.data)

    def apply(self):
        for stage in self.data['stages']:
            Path(stage['source']).rename(stage['destination'])
        # Keep original alias bytes/inodes until the complete DB transaction
        # commits. No rollback needs to infer or rebuild the former bookmark.
        for alias in self.data['aliases']:
            if _identity(Path(alias['source'])) != alias['identity']:
                raise ValueError('A shortcut changed during rename. Please retry.')
            _move(Path(alias['source']), Path(alias['backup']))
        for directory in self.data['created_dirs']:
            Path(directory).mkdir(exist_ok=True)
        for move in self.data['moves']:
            if _identity(Path(move['source'])) != move['identity']:
                raise ValueError('A file changed during rename. Please retry.')
            _move(Path(move['source']), Path(move['destination']))
        for alias in self.data['aliases']:
            if alias['destination'] is None:
                continue
            target, destination = Path(alias['target']), Path(alias['destination'])
            backup = Path(alias['backup'])
            prepared = Path(alias['prepared'])
            if backup.is_symlink():
                os.symlink(target, prepared)
            elif target.exists():
                finder_alias.create(target, prepared)
            else:
                # A pre-existing missing target remains missing; preserve the
                # bookmark and update its managed fallback, never invent bytes.
                finder_alias.restore(prepared, finder_alias.snapshot(backup))
                finder_alias.set_attribute(prepared, finder_alias.TARGET_ATTRIBUTE, os.fsencode(target))
            os.link(prepared, destination, follow_symlinks=False)

    def rollback(self):
        # A case-only staging rename can itself fail, or already have been
        # undone before recovery was interrupted. Those files never reside at
        # the temporary prefix; in particular, do not unlink their same-file
        # destination spelling on a case-insensitive volume.
        # A staged file (unlike a directory) disappears when its final move
        # completes. Restore it through the move entry before undoing staging.
        inactive = [stage for stage in self.data['stages']
                    if stage.get('directory', True) and not Path(stage['destination']).exists()]
        for stage in inactive:
            if not Path(stage['source']).exists() or _identity(Path(stage['source'])) != stage['identity']:
                raise FileNotFoundError(f"Rename recovery needs the original folder: {stage['source']}")
        def unstaged(value):
            return any(_within(Path(value), Path(stage['destination'])) for stage in inactive)
        for alias in reversed(self.data['aliases']):
            if alias['destination'] is None:
                continue
            backup, destination = Path(alias['backup']), Path(alias['destination'])
            if not os.path.lexists(backup):
                continue
            if os.path.lexists(destination):
                if _identity(destination) == alias['identity']:
                    continue  # Interrupted between linking and unlinking backup.
                prepared = Path(alias['prepared'])
                if not os.path.lexists(prepared) or _identity(destination) != _identity(prepared):
                    raise FileExistsError(f'A file changed during rename recovery: {destination}')
                destination.unlink()
        for move in reversed(self.data['moves']):
            if not unstaged(move['source']):
                _undo_move(move)
        _remove_empty([directory for directory in self.data['created_dirs'][::-1]
                       if not any(_within(Path(directory), Path(stage['target'])) for stage in inactive)])
        for alias in reversed(self.data['aliases']):
            if not unstaged(alias['source']):
                _undo_move({**alias, 'destination': alias['backup']})
        for stage in reversed(self.data['stages']):
            source, destination = Path(stage['source']), Path(stage['destination'])
            if destination.exists():
                if _identity(destination) != stage['identity'] or os.path.lexists(source):
                    raise FileExistsError(f'A folder changed during rename recovery: {source}')
                destination.rename(source)
        shutil.rmtree(self.root)

    def finish(self, storage):
        _remove_empty(self.data['old_dirs'])
        shutil.rmtree(self.root)
        storage.conn.execute('DELETE FROM app_settings WHERE key=?', (self.key,))
        storage.conn.commit()


def _undo_move(move):
    source, destination = Path(move['source']), Path(move['destination'])
    if not os.path.lexists(destination):
        if not os.path.lexists(source) or _identity(source) != move['identity']:
            raise FileNotFoundError(f'Rename recovery needs the original file: {source}')
        return
    if _identity(destination) != move['identity']:
        # An exclusive move may have failed on a file saved by another process.
        if os.path.lexists(source) and _identity(source) == move['identity']:
            return
        raise FileExistsError(f'A file changed during rename recovery: {destination}')
    if os.path.lexists(source):
        if _identity(source) != move['identity']:
            raise FileExistsError(f'Rename recovery would overwrite a file: {source}')
    else:
        source.parent.mkdir(parents=True, exist_ok=True)
        os.link(destination, source, follow_symlinks=False)
    destination.unlink()


def _remove_empty(directories):
    for directory in directories:
        try:
            Path(directory).rmdir()
        except OSError:
            pass  # Never delete new/unregistered contents to remove a directory.


def recover(storage):
    """Only interrupted operations, before workers start; no Library scan."""
    for path in sorted((storage.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')):
        journal = object.__new__(RenameJournal)
        journal.path, journal.root = path, path.parent
        journal.data = json.loads(path.read_text())
        journal.key = journal.data['key']
        committed = storage.conn.execute('SELECT 1 FROM app_settings WHERE key=?', (journal.key,)).fetchone()
        if committed:
            journal.finish(storage)
        else:
            journal.rollback()


def rename(storage, folder_id, name, *, workspace_tabs=None, validate=None, before_commit=None):
    return relocate(storage, folder_id, name=name, workspace_tabs=workspace_tabs,
                    validate=validate, before_commit=before_commit)


def relocate(storage, folder_id, *, name=None, parent_id=None, workspace_tabs=None,
             validate=None, before_commit=None, validate_paths=None):
    from . import ui_server as ui
    with MUTATION_LOCK, ExitStack() as locks:
        if any((storage.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')):
            raise ValueError('An interrupted folder rename needs recovery. Restart Gewu Insight before retrying.')
        old_folder = storage.get_library_folder(folder_id)
        if not old_folder or folder_id == 1:
            raise ValueError('Folder not found or root Library cannot be renamed')
        old_directory = _path(ui.local_copy_dir_for_library_folder(storage, folder_id))
        old_roots = _roots(ui, old_directory)
        # Hold download locks before SQLite's writer lock, as Recycle does.
        # Busy downloads produce a retry message instead of blocking on network.
        preliminary = _references(storage, [(p, p.with_name('.rename-target')) for p in old_roots])
        paper_ids = {pid for pid, _, _ in preliminary}
        paper_ids.update(item['paper_id'] for item in ui.library_items_in_folder_tree(storage, folder_id))
        for pid in sorted(paper_ids):
            locks.enter_context(paper_download_lock(storage.db_path, pid, blocking=False))
        journal = None
        storage.conn.execute('BEGIN IMMEDIATE')
        try:
            if storage.get_library_folder(folder_id) != old_folder:
                raise ValueError('The folder changed. Please retry the rename.')
            if validate:
                validate(paper_ids)
            folder = (storage.move_library_folder(folder_id=folder_id, parent_id=parent_id, commit=False)
                      if parent_id is not None else
                      storage.rename_library_folder(folder_id=folder_id, name=name, commit=False))
            new_directory = _path(ui.local_copy_dir_for_library_folder(storage, folder_id))
            pairs = [(old, new) for old, new in zip(old_roots, _roots(ui, new_directory)) if old != new]
            if pairs:
                # Distinct logical names can collapse to the same Finder name.
                siblings = storage.conn.execute('SELECT * FROM library_folders WHERE parent_id IS ? AND id != ?',
                                                (folder['parent_id'], folder_id))
                for sibling in siblings:
                    directory = _path(ui.local_copy_dir_for_library_folder(storage, sibling['id']))
                    if directory in (old_directory, new_directory):
                        raise ValueError('Another folder uses the same Finder name. Choose a different name.')
                for old, _ in pairs:
                    if finder_alias.is_alias(old):
                        raise ValueError('The folder location is a shortcut. Restore its real directory before renaming.')
                references = _references(storage, pairs)
                if {pid for pid, _, _ in references} - paper_ids:
                    raise ValueError('Folder contents changed. Please retry the rename.')
                files, directories, aliases = _plan(storage, pairs)
                if validate_paths:
                    validate_paths(pairs, files, directories, aliases)
                journal = RenameJournal(storage, pairs, files, directories, aliases)
                journal.apply()
                for pid, old, new in references:
                    ui.update_paper_file_path_references(storage, pid, old, new, commit=False)
                def remap_value(value):
                    path = _path(value)
                    mapped = _remap(path, pairs)
                    return str(mapped) if mapped != path else value
                for pid in sorted(paper_ids):
                    paper = storage.get_paper(pid)
                    raw = ui.parse_raw_json(paper)
                    before = json.dumps(raw, ensure_ascii=False)
                    layout = raw.get('file_layout')
                    if isinstance(layout, dict):
                        if layout.get('canonical_path'):
                            layout['canonical_path'] = remap_value(layout['canonical_path'])
                        if isinstance(layout.get('associated_aliases'), list):
                            layout['associated_aliases'] = [remap_value(p) for p in layout['associated_aliases']]
                    imported = raw.get('import')
                    if isinstance(imported, dict) and imported.get('stored_path'):
                        imported['stored_path'] = remap_value(imported['stored_path'])
                    after = json.dumps(raw, ensure_ascii=False)
                    if before != after:
                        storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?', (after, pid))
                storage.conn.execute('INSERT INTO app_settings(key, value, updated_at) VALUES (?, ?, ?)',
                                     (journal.key, '1', folder['updated_at']))
            if workspace_tabs is not None:
                if parent_id is not None:
                    workspace_tabs = [tab for tab in workspace_tabs if int(tab.get('root_folder_id') or 0) != folder_id]
                for tab in workspace_tabs:
                    if int(tab.get('root_folder_id') or 0) == folder_id:
                        tab['label'] = folder['name'][:80]
                value = json.dumps(ui.workspace_tabs_to_setting(workspace_tabs), ensure_ascii=False)
                storage.conn.execute("INSERT INTO app_settings(key,value,updated_at) VALUES ('library_workspace_tabs',?,?) "
                                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at',
                                     (value, folder['updated_at']))
            if before_commit:
                before_commit(folder)
            storage.conn.commit()
        except Exception:
            storage.conn.rollback()
            if journal:
                try:
                    journal.rollback()
                except Exception as recovery_error:
                    raise RuntimeError('Rename stopped; recovery is pending. Original files were retained. '
                                       'Restart Gewu Insight to retry recovery.') from recovery_error
            raise
        if journal:
            try:
                journal.finish(storage)
            except Exception:
                storage.conn.rollback()
                logging.getLogger(__name__).exception('Folder renamed; journal cleanup will resume at startup')
        return folder, {'renamed_paper_ids': sorted(paper_ids),
                        'renamed_paths': [{'old': spelling, 'new': str(new)}
                                          for old, new in pairs for spelling in _spellings(old)]}
