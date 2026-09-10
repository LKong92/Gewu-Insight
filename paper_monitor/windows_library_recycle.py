"""Atomic Library Recycle deletion, without changing the macOS workflow."""
from collections import defaultdict
from pathlib import Path
import logging
import stat

from .publication_jobs import MUTATION_LOCK
from .windows_recycle import LibraryRemoval


def path_owners(storage):
    from . import ui_server as ui
    owners = defaultdict(set)
    for row in storage.conn.execute('SELECT paper_id,main_pdf_path,merged_pdf_path,supplement_pdf_paths,source_path FROM papers'):
        paper = dict(row)
        paths = ui.paper_pdf_paths(paper)
        if paper.get('source_path'):
            paths.append(Path(paper['source_path']).expanduser().resolve())
        for path in paths:
            owners[path].add(paper['paper_id'])
    for row in storage.conn.execute('SELECT paper_id,source_path,stored_path FROM resources'):
        for value in (row['source_path'], row['stored_path']):
            if value:
                owners[Path(value).expanduser().resolve()].add(row['paper_id'])
    return owners


def checked_file(path, roots):
    """Reject junction/symlink traversal; .lnk bytes are independent files."""
    path = Path(path).absolute()
    root = next((Path(root).absolute() for root in roots if path.is_relative_to(Path(root).absolute())), None)
    if root is None:
        raise PermissionError('Recycle file is outside managed storage: ' + str(path))
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError('Recycle does not follow a symlink or junction: ' + str(part))
        if part == root:
            break
    if not path.is_file():
        raise OSError('Recycle expected a regular file: ' + str(path))
    return path.resolve()


def delete_entries(storage, entries, *, confirmed=False, clear_folder_id=None):
    """Return None for ordinary (non-Recycle) moves; delete a Recycle selection.

    Files still referenced by another paper or placement keep their stored path.
    No folder tree is recursively deleted and no external original is recycled.
    """
    from . import ui_server as ui
    from .desktop_files import managed_link_target
    special = ui.ensure_library_special_folders(storage)
    recycle_id = int(special['recycle']['id'])
    if clear_folder_id is not None and int(clear_folder_id) != recycle_id:
        raise ValueError('Only Recycle can be cleared')
    selected = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Each entry must be an object')
        kind, identity = str(entry.get('type') or ''), int(entry.get('id') or 0)
        row = storage.get_library_item(identity) if kind == 'item' else storage.get_library_folder(identity) if kind == 'folder' else None
        if not row:
            raise ValueError('Library entry not found')
        folder_id = int(row['folder_id'] if kind == 'item' else row['id'])
        if not ui.library_folder_is_within(storage, folder_id, recycle_id):
            return None
        if kind == 'folder' and identity == recycle_id and clear_folder_id is None:
            raise ValueError('This folder cannot be deleted')
        selected.append((kind, identity))

    with MUTATION_LOCK:
        removal = LibraryRemoval(storage)
        try:
            storage.conn.execute('BEGIN IMMEDIATE')
            items, folders, selected_papers = {}, set(), set()
            for kind, identity in selected:
                if kind == 'folder':
                    tree = ui.library_folder_tree_ids(storage, identity)
                    if not tree or not ui.library_folder_is_within(storage, identity, recycle_id):
                        raise ValueError('Recycle selection changed; select it again')
                    folders.update(tree)
                    for folder in tree:
                        for row in storage.conn.execute('SELECT * FROM library_items WHERE folder_id = ?', (folder,)):
                            items[row['id']] = dict(row)
                else:
                    row = storage.get_library_item(identity)
                    if not row or not ui.library_folder_is_within(storage, row['folder_id'], recycle_id):
                        raise ValueError('Recycle selection changed; select it again')
                    items[identity] = row
            selected_papers.update(row['paper_id'] for row in items.values())
            deleting = {paper for paper in selected_papers if not ui.paper_has_reference_outside_recycle(storage, paper, recycle_id)}
            orphan_paths = ui.library_recycle_orphan_paths(storage, recycle_id) if clear_folder_id is not None else []
            if (deleting or orphan_paths) and not confirmed:
                raise ValueError('confirmation is required')
            owners = path_owners(storage)
            paths, retained = set(), set()
            for paper in deleting:
                for path in ui.library_file_paths_for_delete(storage, storage.get_paper(paper)):
                    if owners[path] - deleting:
                        retained.add(str(path))
                    else:
                        paths.add(path)
            # Only Gewu-managed direct shortcuts in removed placements qualify.
            folder_papers = defaultdict(set)
            for row in items.values():
                folder_papers[row['folder_id']].add(row['paper_id'])
            aliases = set()
            for folder, papers in folder_papers.items():
                directory = ui.local_copy_dir_for_library_folder(storage, folder)
                if directory.is_dir():
                    for candidate in directory.glob('*.lnk'):
                        target = managed_link_target(candidate)
                        if target and owners[target.resolve()] & papers and not owners[candidate.resolve()] - deleting:
                            aliases.add(candidate.absolute())
            # Clear may include unreferenced local copies, but never a shared file
            # omitted by a textual SQL path comparison (case/alias differences).
            orphans = {Path(path).absolute() for path in orphan_paths if not owners[Path(path).resolve()]}
            roots = ui.allowed_pdf_roots()
            prepared = sorted({checked_file(path, roots) for path in paths | aliases | orphans}, key=str)
            for path in prepared:
                removal.recycle(path)
            # Direct SQL keeps this entire selection under one commit. Shared
            # Storage helpers commit independently and must not be used here.
            for identity in items:
                storage.conn.execute('DELETE FROM library_items WHERE id = ?', (identity,))
            for identity in folders - {recycle_id}:
                storage.conn.execute('DELETE FROM library_folders WHERE id = ?', (identity,))
            for paper in deleting:
                storage.conn.execute('DELETE FROM resources WHERE paper_id = ?', (paper,))
                storage.conn.execute('DELETE FROM papers WHERE paper_id = ?', (paper,))
            removal.mark_committed()
            storage.conn.commit()
        except BaseException:
            storage.conn.rollback()
            removal.finish()
            raise
        # A cleanup failure after commit must not look like a retryable deletion.
        warning = ''
        try:
            removal.finish()
        except Exception as exc:
            warning = 'Removal completed. Recovery-copy cleanup will retry when the app starts.'
            logging.getLogger(__name__).warning('%s %s', warning, exc)
        cleanup = {'cleaned_papers': sorted(deleting), 'skipped_papers': sorted(selected_papers - deleting),
                   'trashed_files': sorted(str(path) for path in paths), 'trashed_orphan_files': sorted(str(path) for path in orphans),
                   'retained_shared_files': sorted(retained), 'deleted_files': [], 'recovery_warning': warning}
        deleted = [{'type': kind, 'id': identity, 'mode': 'removed', 'paper_ids': sorted(selected_papers), 'cleanup': cleanup} for kind, identity in selected]
        return {'deleted': deleted, 'cleanup': cleanup, 'removed': {'items': len(items), 'folders': len(folders - {recycle_id})}}
