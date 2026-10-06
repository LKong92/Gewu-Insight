"""UI file ownership transitions with coordinated SQLite and filesystem moves."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from .storage import Storage
from .text import clean_text
from .time_utils import now_iso
from . import finder_alias


def reassign_paper_file(storage: Storage, paper_id: str, resource_id: int, *,
                        target_key: str = "", new_title: str = "", folder_id: int = 0,
                        target_paper_id: str = "", validate=None, before_commit=None, validate_paths=None) -> dict:
    return _transfer_files(storage, paper_id, [int(resource_id)], target_key=target_key,
                           target_paper_id=target_paper_id, new_title=new_title, folder_id=folder_id,
                           validate=validate, before_commit=before_commit, validate_paths=validate_paths)


def attach_library_item(storage: Storage, source_item_id: int, target_paper_id: str, *, validate=None, before_commit=None, validate_paths=None) -> dict:
    item = storage.get_library_item(source_item_id)
    if not item or not storage.get_paper(target_paper_id):
        raise KeyError(source_item_id)
    result = _transfer_files(storage, item["paper_id"], None, target_paper_id=target_paper_id,
                             validate=validate, before_commit=before_commit, validate_paths=validate_paths)
    return {**result, "source_item_id": source_item_id, "attached_count": len(result["resource_ids"])}


def _transfer_files(storage, paper_id, resource_ids, *, target_key="", target_paper_id="",
                    new_title="", folder_id=0, validate=None, before_commit=None, validate_paths=None):
    from . import ui_server as ui

    if sum(bool(v) for v in (target_key, target_paper_id, new_title)) != 1:
        raise ValueError("Choose a target paper or a title for a new paper.")
    paper_id = storage.resolve_paper_id(paper_id)
    operations, alias_changes = [], []
    created_dirs = []

    def ensure_directory(directory):
        missing = []
        current = directory
        while not current.exists():
            missing.append(current)
            current = current.parent
        directory.mkdir(parents=True, exist_ok=True)
        created_dirs.extend(reversed(missing))

    storage.conn.execute("BEGIN IMMEDIATE")
    try:
        if validate:
            validate()
        source = storage.get_paper(paper_id)
        if not source:
            raise ValueError("The selected file no longer belongs to this paper. Refresh Paper Files.")
        all_files = ui.refresh_paper_resource_fingerprints(storage, paper_id, commit=False)
        selected = all_files if resource_ids is None else [r for r in all_files if int(r["id"]) in resource_ids]
        if not selected or (resource_ids is not None and len(selected) != len(set(resource_ids))):
            raise ValueError("The selected file no longer belongs to this paper. Refresh Paper Files.")
        remaining = [r for r in all_files if r not in selected]
        # A conflict file was attached to a pre-existing bibliography record;
        # detaching it must not delete that unrelated article's identity.
        retire_source = not remaining and (resource_ids is None or any(r.get("added_via") != "inventory_conflict" for r in selected))
        placements = [dict(r) for r in storage.conn.execute("SELECT * FROM library_items WHERE paper_id=?", (paper_id,))]
        if retire_source and len(placements) > 1:
            raise ValueError("This work has other Library locations. Remove those copies before converting it to an attachment.")
        if retire_source and storage.conn.execute("SELECT 1 FROM my_publications WHERE paper_id=?", (paper_id,)).fetchone():
            raise ValueError("This work is also in My Publications and cannot be converted to an attachment.")

        if new_title:
            title = clean_text(new_title)
            if not title or len(title) > 500:
                raise ValueError("Use a paper title of 1 to 500 characters.")
            if len(selected) != 1:
                raise ValueError("Choose one file to make independent.")
            if not folder_id:
                folder_id = next((int(p["folder_id"]) for p in placements if not p.get("trashed_at")), 1)
            chain = ui.library_folder_chain(storage, folder_id)
            if not chain or any(f.get("trashed_at") or f.get("name") == ui.LIBRARY_RECYCLE_FOLDER_NAME for f in chain):
                raise ValueError("Choose an active Library folder.")
            target_id = "file_" + uuid.uuid4().hex
            storage.upsert_paper({"paper_id": target_id, "title": title, "doi": "",
                "journal": "Imported File", "publication_date": "", "abstract": "",
                "source": "manual_file", "type": "imported_file"}, commit=False)
        else:
            target = storage.paper_for_key(target_key) if target_key else storage.get_paper(storage.resolve_paper_id(target_paper_id))
            if not target:
                raise ValueError("No paper matches that Gewu Key.")
            target_id = target["paper_id"]
            if target_id == paper_id:
                raise ValueError("A paper cannot be attached to itself")
        target = storage.get_paper(target_id)
        stamp = now_iso()
        managed_roots = [p.resolve() for p in (ui.LIBRARY_LOCAL_COPY_ROOT, ui.SPACES_LOCAL_COPY_ROOT,
            ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT, ui.ASSOCIATED_FILES_ROOT, ui.DEFAULT_PDF_DIR, storage.db_path.parent)]
        source_dirs = [ui.local_copy_dir_for_library_folder(storage, int(p["folder_id"])) for p in placements]
        source_dirs.append(ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT)
        attachment_directory = ui.associated_work_dir_for_paper(storage, target_id) if not new_title else None
        seen = set()
        for resource in selected:
            original = Path(storage.resource_local_path(resource)).expanduser().absolute()
            if not str(storage.resource_local_path(resource)) or not original.is_file():
                raise ValueError("The selected file is unavailable.")
            physical = original.resolve()
            if physical in seen:
                raise ValueError("This work contains duplicate local file records and cannot be converted safely")
            seen.add(physical)
            managed = any(physical.is_relative_to(root) for root in managed_roots)
            # Never break another record that uses the same bytes, or quietly
            # duplicate them as if an ownership move had succeeded.
            for row in storage.conn.execute("SELECT id,stored_path,source_path FROM resources WHERE id!=?", (resource["id"],)):
                other_path = row["stored_path"] or row["source_path"]
                if other_path and Path(other_path).expanduser().resolve() == physical:
                    raise ValueError("This file is shared by another file record. Resolve that shared ownership before moving it.")
            owners = set(ui.paper_ids_referencing_pdf_path(storage, physical, include_resources=True)) - {paper_id}
            if owners:
                raise ValueError("This file is shared by another paper. Resolve that shared ownership before moving it.")
            directory = (ui.local_copy_dir_for_library_folder(storage, folder_id) if new_title else
                         attachment_directory / ui.associated_resource_subdir(resource.get("file_role") or "other"))
            ensure_directory(directory)
            name = Path(resource.get("display_name") or resource.get("original_filename") or physical.name).name
            destination = ui.unique_path_in_dir(directory / ui.finder_safe_name(name, physical.name))
            # Capture aliases before moving their target; restore on any failure.
            for directory_with_alias in dict.fromkeys([*source_dirs, original.parent]):
                if not directory_with_alias.is_dir() or not any(directory_with_alias.resolve().is_relative_to(root) for root in managed_roots):
                    continue
                for candidate in directory_with_alias.iterdir():
                    if finder_alias.points_to(candidate, physical) and not any(c[0] == candidate for c in alias_changes):
                        alias_changes.append((candidate, finder_alias.snapshot(candidate)))
            operation = {"source": physical, "destination": destination, "move": managed, "done": False}
            if validate_paths:
                validate_paths([destination, *([physical] if managed else []), *(p for p, _ in alias_changes)])
            operations.append(operation)
            if managed:
                shutil.move(str(physical), str(destination))
            else:
                # Linked external originals are outside Gewu's managed tree.
                shutil.copy2(str(physical), str(destination))
            operation["done"] = True
            storage.conn.execute("""UPDATE resources SET paper_id=?, stored_path=?, storage_mode='managed',
                display_name=?, status='reassigned', import_batch_id=NULL, missing_status='',
                added_via=CASE WHEN added_via='inventory_conflict' THEN 'manual_reassignment' ELSE added_via END,
                updated_at=? WHERE id=?""", (target_id, str(destination), name, stamp, resource["id"]))
            _repair_source_pointers(storage, storage.get_paper(paper_id), resource)
            event = {"resource_id": resource["id"], "from_key": source["storage_key"], "to_key": target["storage_key"],
                "at": stamp, "original_import_batch_id": resource.get("import_batch_id"), "original_added_via": resource.get("added_via")}
            for owner_id in (paper_id, target_id):
                raw = json.loads(storage.get_paper(owner_id).get("raw_json") or "{}")
                raw.setdefault("file_reassignments", []).append(event)
                storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id=?", (json.dumps(raw, ensure_ascii=False), owner_id))
        if new_title:
            resource, destination = selected[0], operations[0]["destination"]
            pdf_path = str(destination) if storage.resource_is_pdf(resource) else ""
            raw = json.loads(storage.get_paper(target_id).get("raw_json") or "{}")
            raw.update({"import": {"stored_path": str(destination), "copy_mode": "copy"},
                        "file": {"kind": destination.suffix.lstrip("."), "extension": destination.suffix, "mime_type": resource.get("mime_type")}})
            storage.conn.execute("""UPDATE papers SET primary_resource_id=?, preferred_resource_id=?,
                preferred_resource_manual=1, main_pdf_path=?, merged_pdf_path=?, source_path=?,
                original_filename=?, raw_json=?, download_status='success' WHERE paper_id=?""",
                (resource["id"] if pdf_path else None, resource["id"], pdf_path, pdf_path, str(destination),
                 destination.name, json.dumps(raw, ensure_ascii=False), target_id))
            storage.conn.execute("""INSERT INTO library_items(folder_id,paper_id,display_name,created_at,sort_order)
                VALUES(?,?,?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM library_items WHERE folder_id=?))""",
                (folder_id, target_id, destination.name, stamp, folder_id))
        if retire_source:
            # The former work's attachment-folder projections retire with its
            # last file. Store their bookmark bytes for transaction rollback.
            for value in json.loads(source.get("raw_json") or "{}").get("file_layout", {}).get("associated_aliases", []):
                alias = Path(value)
                if finder_alias.is_alias(alias) and alias not in [a for a, _ in alias_changes]:
                    alias_changes.append((alias, finder_alias.snapshot(alias)))
            if validate_paths:
                validate_paths([p for p, _ in alias_changes])
            storage.conn.execute("DELETE FROM papers WHERE paper_id=?", (paper_id,))
        # An emptied standalone source leaves no folder row or Finder alias.
        # If other files remain, aliases follow that source's remaining Default.
        replacement = None
        if not retire_source:
            resources = storage.list_paper_resources(paper_id, ensure_primary=False)
            replacement = storage._select_default_paper_resource(storage.get_paper(paper_id), resources)
        replacement_path = storage.resource_local_path(replacement) if replacement else ""
        for alias, _old in alias_changes:
            alias.unlink(missing_ok=True)
            if replacement_path:
                finder_alias.create(Path(replacement_path), alias)
        result = {"resource_id": selected[0]["id"], "resource_ids": [r["id"] for r in selected],
                  "source_paper_id": paper_id, "target_paper_id": target_id,
                  "source_removed": retire_source, "removed_item_ids": [p["id"] for p in placements] if retire_source else [],
                  "target_gewu_key": target["storage_key"], "created_paper": bool(new_title), "folder_id": folder_id}
        if before_commit:
            before_commit(result)
        storage.conn.commit()
    except Exception:
        storage.conn.rollback()
        for alias, old in reversed(alias_changes):
            if finder_alias.is_alias(alias):
                alias.unlink()
            if not alias.exists():
                finder_alias.restore(alias, old)
        for operation in reversed(operations):
            source_path, destination = operation["source"], operation["destination"]
            if operation["move"] and destination.exists() and not source_path.exists():
                shutil.move(str(destination), str(source_path))
            elif destination.exists():
                destination.unlink()
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise
    from .file_layout import reconcile_after_write
    for pid in ([target_id] if retire_source else [paper_id, target_id]):
        reconcile_after_write(storage, pid)
    return {**result,
            "files": [storage.resource_local_path(storage.get_paper_resource(r["id"])) for r in selected]}


def _repair_source_pointers(storage, source, resource):
    resource_id = int(resource["id"])
    removed_paths = {str(resource.get(k) or "") for k in ("stored_path", "source_path")} - {""}
    updates = {}
    if int(source.get("preferred_resource_id") or 0) == resource_id:
        updates.update(preferred_resource_id=None, preferred_resource_manual=0)
    current_removed = (int(source.get("primary_resource_id") or 0) == resource_id
                       or source.get("main_pdf_path") in removed_paths or source.get("merged_pdf_path") in removed_paths)
    if current_removed:
        remaining = storage.list_paper_resources(source["paper_id"], ensure_primary=False)
        eligible = [r for r in remaining if r.get("exists") and storage.resource_is_pdf(r)
                    and r.get("file_type") != "invalid_file"
                    and (r.get("added_via") != "inventory_conflict" or r.get("file_type_override"))]
        preferred = storage._select_default_paper_resource({**source, **updates}, eligible)
        replacement = preferred or (eligible[0] if eligible else None)
        path = storage.resource_local_path(replacement) if replacement else ""
        updates.update(primary_resource_id=int(replacement["id"]) if replacement else None,
                       main_pdf_path=path, merged_pdf_path=path,
                       download_status="success" if path else "pending")
    if source.get("source_path") in removed_paths:
        updates["source_path"] = ""
    raw = json.loads(source.get("raw_json") or "{}")
    if raw.get("file_layout", {}).get("canonical_path") in removed_paths:
        raw["file_layout"].pop("canonical_path", None)
        raw["file_layout"].pop("default_resource_id", None)
        updates["raw_json"] = json.dumps(raw, ensure_ascii=False)
    imported = raw.get("import") or {}
    if imported.get("stored_path") in removed_paths or source.get("source_path") in removed_paths:
        remaining = storage.list_paper_resources(source["paper_id"], ensure_primary=False)
        replacement = storage._select_default_paper_resource({**source, **updates}, remaining)
        replacement = replacement or next((r for r in remaining if r.get("exists") and r.get("added_via") != "inventory_conflict"), None)
        path = storage.resource_local_path(replacement) if replacement else ""
        if imported:
            imported["stored_path"] = path
        updates.update(raw_json=json.dumps(raw, ensure_ascii=False), source_path=path)
        if path:
            updates["original_filename"] = Path(path).name
    if source.get("analysis_path") in removed_paths:
        updates.update(analysis_path=None, analysis_status="not_started", analyzed_at=None)
    # Remove the detached file from any cached supplement-path projection.
    supplements = json.loads(source.get("supplement_pdf_paths") or "[]")
    if any(p in removed_paths for p in supplements):
        updates["supplement_pdf_paths"] = json.dumps([p for p in supplements if p not in removed_paths])
    if updates:
        storage.conn.execute("UPDATE papers SET " + ",".join(k + "=?" for k in updates) + " WHERE paper_id=?",
                             (*updates.values(), source["paper_id"]))
