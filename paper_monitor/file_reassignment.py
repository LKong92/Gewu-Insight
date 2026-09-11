"""Explicit UI-only Paper Files reassignment; file bytes and IDs stay intact."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from .storage import Storage
from .text import clean_text
from .time_utils import now_iso


def reassign_paper_file(storage: Storage, paper_id: str, resource_id: int, *,
                        target_key: str = "", new_title: str = "", folder_id: int = 0) -> dict:
    if bool(target_key) == bool(new_title):
        raise ValueError("Choose a target Gewu Key or a title for a new paper.")
    paper_id = storage.resolve_paper_id(paper_id)
    storage.conn.execute("BEGIN IMMEDIATE")
    try:
        source = storage.get_paper(paper_id)
        resource = storage.get_paper_resource(resource_id)
        if not source or not resource or resource.get("paper_id") != paper_id:
            raise ValueError("The selected file no longer belongs to this paper. Refresh Paper Files.")
        path = storage.resource_local_path(resource)
        if not path or not Path(path).is_file():
            raise ValueError("The selected file is unavailable.")
        if target_key:
            row = storage.paper_for_key(target_key)
            if not row:
                raise ValueError("No paper matches that Gewu Key.")
            target_id = row["paper_id"]
            if target_id == paper_id:
                raise ValueError("Choose a different paper.")
        else:
            title = clean_text(new_title)
            if not title or len(title) > 500:
                raise ValueError("Use a paper title of 1 to 500 characters.")
            target_id = "file_" + uuid.uuid4().hex
            storage.upsert_paper({"paper_id": target_id, "title": title, "doi": "",
                                  "journal": "Imported Library", "publication_date": "", "abstract": "",
                                  "source": "manual_file", "type": "imported_file"}, commit=False)
        target = storage.get_paper(target_id)
        if not folder_id:
            row = storage.conn.execute("SELECT folder_id FROM library_items WHERE paper_id=? AND trashed_at IS NULL ORDER BY id LIMIT 1", (paper_id,)).fetchone()
            folder_id = int(row["folder_id"]) if row else 1
        folder = storage.get_library_folder(folder_id)
        if not folder or folder.get("trashed_at"):
            raise ValueError("Choose an active Library folder.")
        stamp = now_iso()
        event = {"resource_id": resource_id, "from_key": source["storage_key"], "to_key": target["storage_key"],
                 "at": stamp, "original_import_batch_id": resource.get("import_batch_id"), "original_added_via": resource.get("added_via")}
        # Keep historical note provenance and source_file_id references unchanged.
        for paper in (source, target):
            raw = json.loads(paper.get("raw_json") or "{}")
            raw.setdefault("file_reassignments", []).append(event)
            storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id=?", (json.dumps(raw, ensure_ascii=False), paper["paper_id"]))
        storage.conn.execute("UPDATE resources SET paper_id=?, status='reassigned', import_batch_id=NULL, added_via=CASE WHEN added_via='inventory_conflict' THEN 'manual_reassignment' ELSE added_via END, updated_at=? WHERE id=?", (target_id, stamp, resource_id))
        _repair_source_pointers(storage, source, resource)
        if new_title:
            pdf_path = path if storage.resource_is_pdf(resource) else ""
            storage.conn.execute("""UPDATE papers SET primary_resource_id=?, preferred_resource_id=?,
                preferred_resource_manual=1, main_pdf_path=?, merged_pdf_path=?, download_status='success'
                WHERE paper_id=?""", (resource_id if pdf_path else None, resource_id, pdf_path, pdf_path, target_id))
        storage.conn.execute("""INSERT INTO library_items(folder_id,paper_id,display_name,created_at,sort_order)
            VALUES(?,?,?,?,(SELECT COALESCE(MAX(sort_order),0)+1 FROM library_items WHERE folder_id=?))
            ON CONFLICT(folder_id,paper_id) DO UPDATE SET trashed_at=NULL, original_folder_id=NULL""",
            (folder_id, target_id, (resource.get("display_name") or resource.get("original_filename")) if new_title else None, stamp, folder_id))
        storage.conn.commit()
        return {"resource_id": resource_id, "source_paper_id": paper_id, "target_paper_id": target_id,
                "target_gewu_key": target["storage_key"], "created_paper": bool(new_title), "folder_id": folder_id}
    except Exception:
        storage.conn.rollback()
        raise


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
    if source.get("analysis_path") in removed_paths:
        updates.update(analysis_path=None, analysis_status="not_started", analyzed_at=None)
    # Remove the detached file from any cached supplement-path projection.
    supplements = json.loads(source.get("supplement_pdf_paths") or "[]")
    if any(p in removed_paths for p in supplements):
        updates["supplement_pdf_paths"] = json.dumps([p for p in supplements if p not in removed_paths])
    if updates:
        storage.conn.execute("UPDATE papers SET " + ",".join(k + "=?" for k in updates) + " WHERE paper_id=?",
                             (*updates.values(), source["paper_id"]))
