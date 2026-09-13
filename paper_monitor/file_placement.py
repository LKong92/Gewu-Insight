"""Keep managed originals outside Recycle while an active placement uses them."""
from pathlib import Path
import os
import shutil


def in_recycle(path):
    from . import ui_server as ui
    root = (ui.LIBRARY_LOCAL_COPY_ROOT / ui.LIBRARY_RECYCLE_FOLDER_NAME).resolve()
    path = Path(path).expanduser().resolve()
    return path == root or root in path.parents


def active_directories(storage, paper_ids, *, exclude_item_id=0):
    from . import ui_server as ui
    from .library_destination import active_folders
    folders = {int(folder["id"]) for folder in active_folders(storage)}
    directories = []
    for pid in paper_ids:
        for item in storage.conn.execute(
            "SELECT id, folder_id, trashed_at FROM library_items WHERE paper_id=? ORDER BY id", (pid,),
        ):
            if item["id"] == exclude_item_id or item["trashed_at"] or item["folder_id"] not in folders:
                continue
            directories.append(ui.local_copy_dir_for_library_folder(storage, item["folder_id"]).resolve())
        if ui.paper_has_my_publication_reference(storage, pid):
            directories.append(ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT.resolve())
    return list(dict.fromkeys(directories))


def move_original(storage, paper_id, source, target_dir, *, filename=None, exclude_item_id=0):
    """Move bytes and every registered pointer together, preserving resource identity.

    The destination is checked inside the write transaction. Recycle targets
    yield to any remaining active Library, Space or My Publications placement,
    including a different paper sharing these bytes. A failed path update puts
    both the file and any displaced target alias back before reporting failure.
    Alias regeneration belongs to the caller, after its logical placement move.
    """
    from . import ui_server as ui
    source = Path(source).expanduser().resolve()
    target_dir = Path(target_dir).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(str(source))
    if not ui.is_allowed_file(source, ui.allowed_pdf_roots()):
        raise ValueError("Only managed local copies can be relocated")
    moved = False
    displaced_alias = None
    destination = source
    storage.conn.execute("SAVEPOINT gewu_original_placement")
    try:
        # Acquire SQLite's writer lock before checking current ownership.
        storage.conn.execute("UPDATE papers SET paper_id=paper_id WHERE paper_id=?", (paper_id,))
        owners = ui.paper_ids_referencing_pdf_path(storage, source, include_resources=True)
        owners = list(dict.fromkeys([str(paper_id), *owners]))
        if in_recycle(target_dir):
            active = active_directories(storage, owners, exclude_item_id=exclude_item_id)
            if active:
                target_dir = source.parent if source.parent in active else active[0]
        if source.parent == target_dir:
            storage.conn.execute("RELEASE gewu_original_placement")
            return source
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / ui.finder_safe_name(filename or source.name, source.name)
        if destination.is_symlink() and destination.resolve() == source:
            displaced_alias = (destination, os.readlink(destination))
            destination.unlink()
        destination = ui.unique_path_in_dir(destination)
        shutil.move(str(source), str(destination))
        moved = True
        for pid in owners:
            ui.update_paper_file_path_references(storage, pid, source, destination, commit=False)
        storage.conn.execute("RELEASE gewu_original_placement")
        storage._relocated_paper_ids = getattr(storage, "_relocated_paper_ids", set()) | set(owners)
    except Exception:
        storage.conn.execute("ROLLBACK TO gewu_original_placement")
        storage.conn.execute("RELEASE gewu_original_placement")
        if moved and destination.exists() and not source.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(destination), str(source))
        if displaced_alias and not os.path.lexists(displaced_alias[0]):
            os.symlink(displaced_alias[1], displaced_alias[0])
        raise
    return destination.resolve()


def rescue_active_original(storage, paper_id):
    """Repair only this touched paper; ordinary alias copies remain a fast path.

    Return its former path when moved. The caller then reconciles the aliases
    and Associated Files without changing Key, resource IDs or Default.
    """
    from . import ui_server as ui
    source = ui.canonical_pdf_path_for_paper(storage.get_paper(paper_id))
    if not source or not in_recycle(source):
        return None
    # Passing the existing Recycle directory invokes the same ownership rule
    # used by deletion and drag; without an active reference this is a no-op.
    destination = move_original(storage, paper_id, source, source.parent)
    return source if destination != source else None
