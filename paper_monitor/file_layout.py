"""Normalize a work's managed originals without changing identity or provenance.

Each paper is a transaction; a failed move or database update restores its
files. External linked originals and bytes shared by different works are not
relocated. No content is deduplicated or discarded by this operation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import logging

from . import finder_alias, desktop_files
from .file_layout_journal import MoveJournal


def bundle_path(ui, canonical, key):
    scope = ui.associated_scope_for_path(canonical)
    if not scope:
        return None
    label, relative = scope
    # Keep the identity suffix intact even for long filenames.
    name = bundle_name(ui.finder_safe_name(Path(desktop_files.placement_name(canonical)).stem), key)
    return ui.ASSOCIATED_FILES_ROOT.resolve() / label / relative.parent / name


def bundle_name(stem, key):
    # APFS limits a single component by UTF-8 bytes, not Python characters.
    return f"{stem.encode('utf-8')[:180].decode('utf-8', errors='ignore')} [{key}]"


def normalize_files(storage, paper_id):
    from . import ui_server as ui
    if ui.ASSOCIATED_FILES_ROOT.resolve().parent != ui.LIBRARY_LOCAL_COPY_ROOT.resolve().parent:
        return {"skipped": "inconsistent managed roots"}
    paper_id = storage.resolve_paper_id(paper_id)
    resources = storage.list_paper_resources(paper_id)
    paper = storage.get_paper(paper_id)
    if not paper:
        return {}
    default = storage._select_default_paper_resource(paper, resources)
    if not default:
        return {}
    roots = [p.resolve() for p in (ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT,
             ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT, ui.ASSOCIATED_FILES_ROOT, ui.DEFAULT_PDF_DIR)]
    def managed(path):
        return any(path == root or root in path.parents for root in roots)
    default_path = Path(storage.resource_local_path(default)).expanduser().resolve()
    current = ui.canonical_file_path_for_paper(paper)
    directories = ui.active_directories(storage, [paper_id])
    if not directories:
        # Recycle-only and monitor-only works keep their existing semantics.
        return {}
    if not managed(default_path) or default.get("storage_mode") == "linked":
        return {}
    if ui.paper_resource_path_is_shared(storage, default_path, paper_id, int(default["id"])):
        return {"skipped_shared": True}
    parent = (current.parent if current and current.parent in directories else
              default_path.parent if default_path.parent in directories else directories[0])
    canonical = default_path if default_path.parent == parent else parent / ui.finder_safe_name(default_path.name)
    if canonical != default_path and os.path.lexists(canonical) and not finder_alias.points_to(canonical, default_path):
        canonical = ui.unique_path_in_dir(canonical)
    bundle = bundle_path(ui, canonical, paper["storage_key"])
    if not bundle:
        return {}
    old_bundle = ui.existing_associated_work_dir(storage, paper_id)
    # A secondary bundle alias may occupy the new primary's mirrored path.
    if os.path.lexists(bundle) and finder_alias.is_alias(bundle):
        if not old_bundle or not finder_alias.points_to(bundle, old_bundle):
            raise FileExistsError(str(bundle))
    moves, displaced, created_dirs = [], [], []
    journal = MoveJournal(storage, paper_id)
    storage.conn.execute("BEGIN IMMEDIATE")
    try:
        fresh = storage.get_paper(paper_id)
        registered = storage.list_paper_resources(paper_id, ensure_primary=False)
        if ([(r["id"], storage.resource_local_path(r), r.get("file_type")) for r in registered]
                != [(r["id"], storage.resource_local_path(r), r.get("file_type")) for r in resources]
                or any(fresh.get(k) != paper.get(k) for k in
                       ("primary_resource_id", "preferred_resource_id", "preferred_resource_manual"))):
            raise ValueError("Paper Files changed during this operation. Please retry.")
        def mkdir(directory):
            missing, path = [], directory
            while not path.exists():
                missing.append(path)
                path = path.parent
            directory.mkdir(parents=True, exist_ok=True)
            created_dirs.extend(reversed(missing))

        def displace(path):
            displaced.append((path, finder_alias.snapshot(path)))
            path.unlink()

        if finder_alias.is_alias(bundle):
            displace(bundle)
        if canonical != default_path and finder_alias.points_to(canonical, default_path):
            displace(canonical)
        seen = set()
        for resource in resources:
            value = storage.resource_local_path(resource)
            if not value:
                continue
            source = Path(value).expanduser().resolve()
            if source in seen or not source.is_file() or not managed(source) or resource.get("storage_mode") == "linked":
                continue
            seen.add(source)
            if ui.paper_resource_path_is_shared(storage, source, paper_id, int(resource["id"])):
                continue
            if int(resource["id"]) == int(default["id"]):
                destination = canonical
            elif old_bundle and source.is_relative_to(old_bundle.resolve()):
                destination = bundle / source.relative_to(old_bundle.resolve())
            else:
                destination = bundle / ui.associated_resource_subdir(resource.get("file_role") or "other") / source.name
            if destination == source:
                continue
            mkdir(destination.parent)
            destination = ui.unique_path_in_dir(destination)
            # The SQLite writer lock protects registration; an exclusive link
            # also rejects filesystem collisions. Never coalesce file contents.
            journal.move(source, destination, int(resource["id"]))
            moves.append((source, destination))
            ui.update_paper_file_path_references(storage, paper_id, source, destination, commit=False)
        raw = ui.parse_raw_json(storage.get_paper(paper_id))
        raw["file_layout"] = {**raw.get("file_layout", {}), "canonical_path": str(canonical),
                              "default_resource_id": int(default["id"]), "version": 1, "links_pending": True}
        pdf = storage.resource_is_pdf(default)
        storage.conn.execute("""UPDATE papers SET primary_resource_id=?, main_pdf_path=?, merged_pdf_path=?, raw_json=?
                                WHERE paper_id=?""",
                             (int(default["id"]) if pdf else None, str(canonical) if pdf else "",
                              str(canonical) if pdf else "", json.dumps(raw, ensure_ascii=False), paper_id))
        storage.conn.commit()
    except Exception:
        storage.conn.rollback()
        for source, destination in reversed(moves):
            if destination.exists() and not os.path.lexists(source):
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(destination), str(source))
        for path, saved in reversed(displaced):
            if not os.path.lexists(path):
                finder_alias.restore(path, saved)
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        journal.finish()
        raise
    journal.finish()
    if old_bundle and old_bundle != bundle:
        ui.cleanup_empty_parents([str(p) for p, _ in moves], ui.ASSOCIATED_FILES_ROOT.resolve())
    return {"old_target": current if current != canonical else None, "moves": moves, "canonical": canonical}


def sync_associated_aliases(storage, paper_id):
    """Mirror the bundle at every placement, with only one real directory."""
    from . import ui_server as ui
    paper = storage.get_paper(paper_id)
    if not paper:
        return
    canonical = ui.canonical_file_path_for_paper(paper)
    if not canonical:
        return
    key = paper["storage_key"]
    raw = ui.parse_raw_json(paper)
    layout = raw.get("file_layout", {})
    previous = {Path(p) for p in layout.get("associated_aliases", [])}
    bundle = ui.existing_associated_work_dir(storage, paper_id)
    if bundle is None:
        for path in previous:
            if desktop_files.placement_name(path).endswith(f"[{key}]") and finder_alias.is_alias(path):
                path.unlink()
        if previous:
            raw["file_layout"] = {**layout, "associated_aliases": []}
            storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id=?", (json.dumps(raw, ensure_ascii=False), paper_id))
            storage.conn.commit()
        return  # Do not manufacture empty attachment directories.
    expected = set()
    for row in storage.conn.execute("SELECT * FROM library_items WHERE paper_id=? ORDER BY id", (paper_id,)):
        item = dict(row)
        directory = ui.local_copy_dir_for_library_folder(storage, item["folder_id"])
        filename = ui.library_item_pdf_filename(item, paper, canonical)
        path = bundle_path(ui, directory / filename, key)
        if path and path != bundle:
            expected.add(desktop_files.placement_path(path))
    if ui.paper_has_my_publication_reference(storage, paper_id):
        path = bundle_path(ui, ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT / canonical.name, key)
        if path and path != bundle:
            expected.add(desktop_files.placement_path(path))
    for path in expected:
        # Moving the last registered file can leave empty role directories at
        # a former placement. Remove only empty directories, never file bytes.
        if path.is_dir() and not finder_alias.is_alias(path):
            for directory, _, _ in os.walk(path, topdown=False, followlinks=False):
                try:
                    Path(directory).rmdir()
                except OSError:
                    pass
        if finder_alias.points_to(path, bundle):
            finder_alias.ensure(bundle, path)
        elif path in previous and finder_alias.is_alias(path):
            finder_alias.retarget(bundle, path)
        elif not os.path.lexists(path):
            finder_alias.create(bundle, path)
        else:
            # Do not overwrite a real folder containing unregistered files.
            raise FileExistsError(f"Associated Files location is occupied: {path}")
    # Only paths previously projected for this work; never scan the whole tree
    # for every single-paper update.
    for path in previous - expected:
        if desktop_files.placement_name(path).endswith(f"[{key}]") and finder_alias.is_alias(path):
            path.unlink()
    values = sorted(str(p) for p in expected)
    if layout.get("associated_aliases") != values:
        raw["file_layout"] = {**layout, "associated_aliases": values}
        storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id=?", (json.dumps(raw, ensure_ascii=False), paper_id))
        storage.conn.commit()


def reconcile(storage, paper_id):
    from . import ui_server as ui
    from .download import paper_download_lock
    # Download callers may already hold this reentrant lock. Do not then take
    # MUTATION_LOCK: Recycle takes the global lock before waiting for downloads.
    with paper_download_lock(storage.db_path, paper_id):
        return ui.sync_all_pdf_aliases_for_paper(storage, paper_id, preserve_canonical_name=True)


def finish_aliases(storage, paper_id):
    from . import ui_server as ui
    raw = ui.parse_raw_json(storage.get_paper(paper_id))
    if raw.get("file_layout", {}).get("links_pending"):
        raw["file_layout"]["links_pending"] = False
        storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id=?", (json.dumps(raw, ensure_ascii=False), paper_id))
        storage.conn.commit()


def reconcile_after_write(storage, paper_id):
    """A saved attachment must never be deleted due to a later alias failure."""
    try:
        reconcile(storage, paper_id)
    except Exception:
        storage.conn.rollback()
        logging.getLogger(__name__).exception("File saved; layout needs attention for %s", paper_id)
        storage.conn.execute("UPDATE papers SET download_message=? WHERE paper_id=?",
                             ("File saved; some folder links could not be updated.", paper_id))
        storage.conn.commit()
