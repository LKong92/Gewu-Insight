"""Reference-aware My Publications deletion with reversible managed-file moves."""
from collections import defaultdict
from pathlib import Path
import shutil
import logging

from .publication_jobs import MUTATION_LOCK


def delete_publications(storage, publication_ids):
    from . import ui_server as ui
    moved = []
    pending = set()
    deleting = set()
    owners = None

    def path_owners():
        # Build once, lazily, only when this deletion actually has local files.
        # Resolving aliases also protects shared bytes referenced under a symlink.
        references = defaultdict(set)
        for row in storage.conn.execute('SELECT paper_id,main_pdf_path,merged_pdf_path,supplement_pdf_paths,source_path FROM papers'):
            paper = dict(row)
            paths = ui.paper_pdf_paths(paper)
            if paper.get('source_path'):
                paths.append(Path(paper['source_path']).expanduser().resolve())
            for path in paths:
                references[path].add(paper['paper_id'])
        for row in storage.conn.execute('SELECT paper_id,source_path,stored_path FROM resources'):
            for value in (row['source_path'], row['stored_path']):
                if value:
                    references[Path(value).expanduser().resolve()].add(row['paper_id'])
        return references

    def prepare(paper):
        nonlocal owners
        deleting.add(paper['paper_id'])
        pending.update(ui.library_file_paths_for_delete(storage, paper))
        if pending and owners is None:
            owners = path_owners()
        for path in list(pending):
            if owners[path] - deleting:
                continue
            if path.exists():
                destination = ui.move_path_to_macos_trash(path)
                moved.append((path, destination))
            pending.remove(path)

    with MUTATION_LOCK:
        try:
            result = storage.delete_my_publications(
                publication_ids=publication_ids, prepare_file_cleanup=prepare)
        except Exception:
            for original, destination in reversed(moved):
                if not original.exists() and destination.exists():
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(original))
            raise
    # SQL has committed. Alias housekeeping must not turn success into a retry
    # that could repeat a completed destructive action.
    for original, _ in moved:
        try:
            ui.remove_symlinks_to(original, ui.local_copy_roots(include_legacy=True))
        except OSError:
            logging.getLogger(__name__).warning('Could not remove obsolete publication aliases', exc_info=True)
    for paper_id in result['retained_paper_ids']:
        from .file_layout import reconcile_after_write
        reconcile_after_write(storage, paper_id)
        canonical = ui.canonical_file_path_for_paper(storage.get_paper(paper_id))
        if canonical:
            ui.remove_direct_symlinks_to(canonical, [ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT])
    result['trashed_file_count'] = len(moved)
    return result
