"""Recycle deletion with intact directory moves and reversible file/SQL changes."""
from collections import defaultdict
from contextlib import ExitStack
from pathlib import Path
import json
import os
import shutil

from . import finder_alias
from .download import paper_download_lock
from .publication_jobs import MUTATION_LOCK


def lexical_path(value):
    """Normalize parents but never follow the final file or directory symlink."""
    path = Path(value).expanduser().absolute()
    return path.parent.resolve() / path.name


def exists(path):
    return os.path.lexists(path)


def within(path, directory):
    return path == directory or directory in path.parents


def _selection(storage, entries, recycle_id, empty):
    from . import ui_server as ui
    root = lexical_path(ui.local_copy_dir_for_library_folder(storage, recycle_id))
    if finder_alias.is_alias(root):
        raise ValueError("The Recycle directory is a shortcut. Restore its local folder before emptying it.")
    folder_ids, item_ids, directories = set(), set(), []
    if empty:
        entries = [{"type": "folder", "id": recycle_id}]
    for entry in entries:
        kind, identity = entry.get("type"), int(entry.get("id") or 0)
        if kind == "folder":
            if not ui.library_folder_is_within(storage, identity, recycle_id) or (identity == recycle_id and not empty):
                raise ValueError("Choose a folder inside Recycle.")
            tree = ui.library_folder_tree_ids(storage, identity)
            folder_ids.update(tree)
            for fid in tree:
                item_ids.update(r[0] for r in storage.conn.execute("SELECT id FROM library_items WHERE folder_id=?", (fid,)))
            directory = lexical_path(ui.local_copy_dir_for_library_folder(storage, identity))
            if not within(directory, root):
                raise ValueError("The selected folder is outside the local Recycle directory.")
            if empty:
                directories.extend(sorted(root.iterdir()) if root.is_dir() else [])
            elif exists(directory):
                directories.append(directory)
        elif kind == "item":
            item = storage.get_library_item(identity)
            if not item or not ui.library_folder_is_within(storage, item["folder_id"], recycle_id):
                raise ValueError("Choose an item inside Recycle.")
            item_ids.add(identity)
        else:
            raise ValueError("Choose a file or folder in Recycle.")
    items = [dict(storage.conn.execute("SELECT * FROM library_items WHERE id=?", (i,)).fetchone()) for i in sorted(item_ids)]
    paper_ids = {item["paper_id"] for item in items}
    deleting = set()
    for pid in paper_ids:
        remaining = {r[0] for r in storage.conn.execute("SELECT id FROM library_items WHERE paper_id=?", (pid,))} - item_ids
        if not remaining and not ui.paper_has_my_publication_reference(storage, pid):
            deleting.add(pid)
    folder_ids.discard(recycle_id)
    return {"root": root, "folders": folder_ids, "items": items, "papers": paper_ids,
            "deleting": deleting, "paths": directories}


def _references(storage):
    # Read only file pointers. Cache path resolution because paper/resource
    # projections and Library aliases often describe the same physical file.
    refs, cache = [], {}
    def add(table, row_id, pid, field, value, member=None):
        if not value:
            return
        value = str(value)
        if value not in cache:
            path = lexical_path(value)
            try:
                cache[value] = (path, path.resolve())
            except (OSError, RuntimeError):
                cache[value] = (path, path)
        raw, resolved = cache[value]
        refs.append((table, row_id, pid, field, value, member, raw, resolved))
    for row in storage.conn.execute("SELECT paper_id,main_pdf_path,merged_pdf_path,source_path,analysis_path,supplement_pdf_paths FROM papers"):
        pid = row["paper_id"]
        for field in ("main_pdf_path", "merged_pdf_path", "source_path", "analysis_path"):
            add("papers", pid, pid, field, row[field])
        try:
            for i, value in enumerate(json.loads(row["supplement_pdf_paths"] or "[]")):
                add("papers", pid, pid, "supplement_pdf_paths", value, i)
        except (ValueError, TypeError, AttributeError):
            pass
    for row in storage.conn.execute("SELECT id,paper_id,stored_path,source_path FROM resources"):
        for field in ("stored_path", "source_path"):
            add("resources", row["id"], row["paper_id"], field, row[field])
    return refs


def _minimal_paths(paths):
    result = []
    for path in sorted(set(paths), key=lambda p: (len(p.parts), str(p))):
        if exists(path) and not any(p.is_dir() and not finder_alias.is_alias(p) and within(path, p) for p in result):
            result.append(path)
    return result


def _plan(storage, entries, recycle_id, empty):
    from . import ui_server as ui
    plan = _selection(storage, entries, recycle_id, empty)
    refs = _references(storage)
    owners = defaultdict(set)
    for ref in refs:
        owners[ref[-1]].add(ref[2])
    paths = plan["paths"][:]
    for pid in plan["deleting"]:
        paper = storage.get_paper(pid)
        for path in ui.library_file_paths_for_delete(storage, paper):
            # Shared bytes outside a selected directory stay in place.
            if not (owners[path.resolve()] - plan["deleting"]):
                paths.append(path)
    # Individual item deletion removes its local alias, not the alias target.
    for item in plan["items"]:
        if item["folder_id"] in plan["folders"] or empty:
            continue
        directory = lexical_path(ui.local_copy_dir_for_library_folder(storage, item["folder_id"]))
        paper_paths = {r[-1] for r in refs if r[2] == item["paper_id"]}
        if directory.is_dir() and not finder_alias.is_alias(directory):
            for path in directory.iterdir():
                if finder_alias.is_alias(path) and finder_alias.resolve(path) in paper_paths:
                    paths.append(path)
    plan.update(paths=_minimal_paths(paths), refs=refs)
    return plan


def _affected(ref, paths):
    raw, resolved = ref[-2:]
    for path in paths:
        if finder_alias.is_alias(path):
            if raw == path:
                return True
        elif raw == path or resolved == path or (path.is_dir() and (within(raw, path) or within(resolved, path))):
            return True
    return False


def preview_recycle_selection(storage, entries, *, recycle_id, empty=False):
    plan = _plan(storage, entries, recycle_id, empty)
    folders = [str(p) for p in plan["paths"] if p.is_dir() and not finder_alias.is_alias(p)]
    files = [str(p) for p in plan["paths"] if str(p) not in folders]
    return {"requires_confirmation": bool(plan["items"] or plan["folders"] or plan["paths"]),
            "metadata_paper_count": len(plan["deleting"]),
            "shortcut_only_paper_count": len(plan["papers"] - plan["deleting"]),
            "folder_paths": folders, "local_copy_paths": files, "local_copy_count": len(files),
            "item_count": len(plan["items"]), "folder_count": len(plan["folders"])}


def delete_recycle_selection(storage, entries, *, recycle_id, empty=False, confirmed=False):
    from . import ui_server as ui
    moved, copied, relinked, created_dirs = [], [], [], []
    with MUTATION_LOCK, ExitStack() as locks:
        plan = _plan(storage, entries, recycle_id, empty)
        affected_papers = plan["papers"] | {r[2] for r in plan["refs"] if _affected(r, plan["paths"])}
        for pid in sorted(affected_papers):
            locks.enter_context(paper_download_lock(storage.db_path, pid))
        storage.conn.execute("BEGIN IMMEDIATE")
        try:
            plan = _plan(storage, entries, recycle_id, empty)
            if (plan["items"] or plan["folders"] or plan["paths"]) and not confirmed:
                raise ValueError("confirmation is required")
            replacements, updates = {}, {}
            preserved = [r for r in plan["refs"] if r[2] not in plan["deleting"] and _affected(r, plan["paths"])]
            for ref in preserved:
                table, identity, pid, field, old, member, raw, source = ref
                if not source.is_file():
                    continue  # An already missing file cannot be restored by deleting an alias.
                if source not in replacements:
                    physically_removed = any(not finder_alias.is_alias(p) and (source == p or (p.is_dir() and within(source, p))) for p in plan["paths"])
                    if not physically_removed:
                        replacements[source] = source
                    else:
                        survivor = next((dict(r) for r in storage.conn.execute("SELECT * FROM library_items WHERE paper_id=? ORDER BY id", (pid,))
                                         if r["id"] not in {i["id"] for i in plan["items"]}), None)
                        target_dir = ui.local_copy_dir_for_library_folder(storage, survivor["folder_id"]) if survivor else (
                            ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT if ui.paper_has_my_publication_reference(storage, pid) else ui.DEFAULT_PDF_DIR / pid)
                        target_dir = target_dir.resolve()
                        if any(p == target_dir or (p.is_dir() and within(target_dir, p)) for p in plan["paths"]):
                            target_dir = ui.DEFAULT_PDF_DIR.resolve() / pid
                        absent = []
                        parent = target_dir
                        while not parent.exists():
                            absent.append(parent); parent = parent.parent
                        target_dir.mkdir(parents=True, exist_ok=True)
                        created_dirs.extend(reversed(absent))
                        target = ui.unique_path_in_dir(target_dir / source.name)
                        # Never overwrite a retained file, even if a concurrent external writer appears.
                        with target.open("xb") as output, source.open("rb") as input_file:
                            copied.append(target)
                            shutil.copyfileobj(input_file, output)
                        shutil.copystat(source, target)
                        replacements[source] = target
                key = (table, identity, field)
                target = str(replacements[source])
                if member is None:
                    updates[key] = target
                else:
                    if key not in updates:
                        row_id = "paper_id" if table == "papers" else "id"
                        updates[key] = json.loads(storage.conn.execute(f"SELECT {field} FROM {table} WHERE {row_id}=?", (identity,)).fetchone()[0])
                    if member == "import":
                        updates[key]["import"]["stored_path"] = target
                    else:
                        updates[key][member] = target
            # Keep surviving Library aliases usable without changing the folder being trashed.
            survivor_dirs = set()
            for pid in {r[2] for r in preserved}:
                for row in storage.conn.execute("SELECT id,folder_id FROM library_items WHERE paper_id=?", (pid,)):
                    if row["id"] not in {i["id"] for i in plan["items"]}:
                        survivor_dirs.add(ui.local_copy_dir_for_library_folder(storage, row["folder_id"]).resolve())
            for directory in survivor_dirs:
                if not directory.is_dir():
                    continue
                for path in directory.iterdir():
                    if finder_alias.is_alias(path) and finder_alias.resolve(path) in replacements and finder_alias.resolve(path) != replacements[finder_alias.resolve(path)]:
                        old_link, target = finder_alias.snapshot(path), replacements[finder_alias.resolve(path)]
                        path.unlink(); relinked.append((path, old_link)); finder_alias.create(target, path)
            for (table, identity, field), value in updates.items():
                row_id = "paper_id" if table == "papers" else "id"
                storage.conn.execute(f"UPDATE {table} SET {field}=? WHERE {row_id}=?", (json.dumps(value) if isinstance(value, (dict, list)) else value, identity))
            for pid in {r[2] for r in preserved}:
                raw = json.loads(storage.conn.execute("SELECT raw_json FROM papers WHERE paper_id=?", (pid,)).fetchone()[0] or "{}")
                imported = raw.get("import", {})
                value = imported.get("stored_path") if isinstance(imported, dict) else None
                if value and Path(value).expanduser().resolve() in replacements:
                    imported["stored_path"] = str(replacements[Path(value).expanduser().resolve()])
                    storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id=?", (json.dumps(raw), pid))
            for path in plan["paths"]:
                if not exists(path):
                    continue  # A missing historical file must not block the rest of Recycle.
                destination = ui.move_path_to_macos_trash(path)
                moved.append((path, destination))
                if exists(path) or not exists(destination) or destination == path:
                    raise OSError("macOS did not confirm the Trash location. Recycle was not cleared.")
            for item in plan["items"]:
                storage.conn.execute("DELETE FROM library_items WHERE id=?", (item["id"],))
            # Delete children before parents, without intermediate commits.
            for fid in sorted(plan["folders"], key=lambda f: len(ui.library_folder_chain(storage, f)), reverse=True):
                storage.conn.execute("DELETE FROM library_folders WHERE id=?", (fid,))
            for pid in plan["deleting"]:
                storage.conn.execute("DELETE FROM resources WHERE paper_id=?", (pid,))
                storage.conn.execute("DELETE FROM papers WHERE paper_id=?", (pid,))
            # Build authoritative UI snapshots before commit, without rescanning
            # or creating resources. Any serialization failure can still roll back.
            snapshots = []
            for pid in sorted({r[2] for r in preserved}):
                paper = storage.get_paper(pid)
                resources = storage.list_paper_resources(pid, ensure_primary=False)
                default = storage._select_default_paper_resource(paper, resources) or {}
                snapshots.append({"paper_id": pid, "storage_key": paper["storage_key"],
                    "primary_resource_id": int(paper.get("primary_resource_id") or 0),
                    "preferred_resource_id": int(paper.get("preferred_resource_id") or 0),
                    "preferred_resource_manual": bool(paper.get("preferred_resource_manual")),
                    "default_resource_id": int(default.get("id") or 0),
                    "resolved_resource_id": int(default.get("id") or 0),
                    "files": ui.paper_resources_to_api(resources), "paper": ui.paper_to_api(paper)})
            storage.conn.commit()
        except Exception:
            storage.conn.rollback()
            for original, destination in reversed(moved):
                if not exists(original) and exists(destination):
                    original.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(destination), str(original))
            for path, old_link in reversed(relinked):
                if finder_alias.is_alias(path):
                    path.unlink()
                if not exists(path):
                    finder_alias.restore(path, old_link)
            for path in reversed(copied):
                path.unlink(missing_ok=True)
            for directory in reversed(created_dirs):
                try:
                    directory.rmdir()
                except OSError:
                    pass
            raise
    return {"removed": {"items": len(plan["items"]), "folders": len(plan["folders"])},
            "paper_ids": sorted(plan["papers"]),
            "retained_paper_ids": sorted({r[2] for r in preserved}),
            "paper_files": snapshots,
            "cleanup": {"cleaned_papers": sorted(plan["deleting"]),
                        "skipped_papers": sorted(plan["papers"] - plan["deleting"]),
                        "trashed_files": [str(p) for p, _ in moved]}}
