from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from pypdf import PdfReader

from ..config import DEFAULT_DB_PATH, DEFAULT_LIBRARY_IMPORT_DIR, ROOT
from ..storage import Storage
from ..text import clean_text, make_paper_id, normalize_doi, safe_slug, sha1_short


SUPPORTED_COPY_MODES = {"copy", "link"}
PAPER_CANDIDATE_KIND = "pdf"
PAPER_CANDIDATE_IMPORT_AS = "paper_candidate"
REPORT_DIR = ROOT / "reports" / "imports"
LIBRARY_IMPORT_DIR = DEFAULT_LIBRARY_IMPORT_DIR
SYSTEM_METADATA_FILENAMES = {".ds_store", "thumbs.db", "desktop.ini"}
DOCUMENT_EXTENSIONS = {".doc", ".docx", ".rtf", ".txt", ".md", ".tex"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp", ".heic", ".webp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".avi", ".m4v", ".mkv"}
PRESENTATION_EXTENSIONS = {".ppt", ".pptx", ".key"}
SPREADSHEET_EXTENSIONS = {".xls", ".xlsx", ".csv", ".tsv", ".numbers"}
ARCHIVE_EXTENSIONS = {".zip", ".tar", ".gz", ".bz2", ".7z", ".rar"}
DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)
ARXIV_PATTERN = re.compile(r"(?:arxiv[:_\s-]*)?(\d{4}\.\d{4,5})(?:v\d+)?", re.I)


def build_inventory_from_folder(folder_path: str | Path, *, output_path: str | Path | None = None) -> dict[str, Any]:
    root = Path(folder_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Folder does not exist: {root}")
    directories: list[dict[str, str]] = []
    files: list[dict[str, Any]] = []
    for current, dirnames, filenames in os_walk_sorted(root):
        current_path = Path(current)
        relative_dir = "" if current_path == root else current_path.relative_to(root).as_posix()
        directories.append({"path": str(current_path), "relative_path": relative_dir})
        for filename in filenames:
            path = current_path / filename
            files.append(scan_inventory_file(path, root))
    summary = inventory_summary(root, directories, files)
    inventory = {"summary": summary, "directories": directories, "files": files}
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
    return inventory


def import_library_inventory(
    inventory_path: str | Path,
    *,
    copy_mode: str = "copy",
    preserve_folders: bool = False,
    dedupe_by: Iterable[str] = ("doi", "arxiv_id", "source_path"),
    dry_run: bool = True,
    storage: Storage | None = None,
    db_path: str | Path = DEFAULT_DB_PATH,
    report_path: str | Path | None = None,
    target_root: str | Path = LIBRARY_IMPORT_DIR,
    library_item_name: str = "default",
) -> dict[str, Any]:
    """Inspect or import an external inventory into Paper Monitor storage."""

    inventory_file = Path(inventory_path)
    dedupe_keys = normalize_dedupe_keys(dedupe_by)
    result = empty_result(
        inventory_path=inventory_file,
        copy_mode=copy_mode,
        preserve_folders=preserve_folders,
        dedupe_by=dedupe_keys,
        dry_run=dry_run,
    )

    if copy_mode == "move":
        result["errors"].append("copy_mode=move is not supported; it would mutate the original source folder.")
        return finalize_result(result, report_path)
    if copy_mode not in SUPPORTED_COPY_MODES:
        result["errors"].append(f"Unsupported copy_mode: {copy_mode}. Use copy or link.")
        return finalize_result(result, report_path)
    if not inventory_file.exists():
        result["errors"].append(f"Inventory file does not exist: {inventory_file}")
        return finalize_result(result, report_path)

    try:
        data = json.loads(inventory_file.read_text(encoding="utf-8"))
    except Exception as exc:
        result["errors"].append(f"Could not read inventory JSON: {exc}")
        return finalize_result(result, report_path)

    files = data.get("files")
    if not isinstance(files, list):
        result["errors"].append("Inventory JSON must contain a top-level files list.")
        return finalize_result(result, report_path)

    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    result["source_root"] = clean_text(summary.get("root"))
    result["inventory_summary"] = summary
    result["total_files"] = len(files)
    result["real_import_supported"] = True
    library_target_root = Path(target_root)
    result["copy_target_root"] = str(library_target_root)
    result["library_item_name"] = library_item_name

    owns_storage = storage is None
    active_storage = storage or Storage(Path(db_path))
    try:
        existing = build_existing_index(active_storage)
        if dry_run:
            evaluate_files(files, result, existing, dedupe_keys)
        else:
            execute_import(files, result, active_storage, existing, dedupe_keys, inventory_file, library_target_root, library_item_name)
    finally:
        if owns_storage:
            active_storage.close()

    return finalize_result(result, report_path)


def empty_result(
    *,
    inventory_path: Path,
    copy_mode: str,
    preserve_folders: bool,
    dedupe_by: list[str],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "real_import_supported": False,
        "inventory_path": str(inventory_path),
        "copy_mode": copy_mode,
        "preserve_folders": preserve_folders,
        "dedupe_by": dedupe_by,
        "source_root": "",
        "total_files": 0,
        "paper_candidates_seen": 0,
        "created_papers": 0,
        "updated_papers": 0,
        "pdf_attachments_to_import": 0,
        "created_resources": 0,
        "resources_or_attachments_to_import": 0,
        "skipped": 0,
        "skipped_system_metadata": 0,
        "mac_aliases_found": 0,
        "missing_source_files": 0,
        "doi_duplicates": 0,
        "arxiv_duplicates": 0,
        "path_duplicates": 0,
        "duplicate_paper_candidates": 0,
        "metadata_only_fields": [
            "source_path",
            "relative_path",
            "parent_relative_path",
            "filename",
            "doi_source",
            "parse_status",
            "parse_error",
            "page_count",
            "size_bytes",
            "modified_at",
            "import_kind",
            "import_as",
        ],
        "papers_to_create": [],
        "papers_to_update": [],
        "resources_to_import": [],
        "aliases": [],
        "missing_sources": [],
        "duplicate_dois": [],
        "duplicate_arxiv_ids": [],
        "duplicate_paths": [],
        "warnings": [],
        "errors": [],
    }


def evaluate_files(
    files: list[Any],
    result: dict[str, Any],
    existing: dict[str, dict[str, str]],
    dedupe_keys: list[str],
) -> None:
    seen_identities: set[tuple[str, str]] = set()
    seen_dois: set[str] = set()
    seen_arxiv_ids: set[str] = set()
    seen_paths: set[str] = set()

    for index, raw in enumerate(files):
        if not isinstance(raw, dict):
            result["skipped"] += 1
            result["warnings"].append(f"Skipping non-object file record at index {index}.")
            continue

        record = normalize_record(raw)
        source_path = record["source_path"]
        source_exists = Path(source_path).exists() if source_path else False
        if source_path and not source_exists:
            result["missing_source_files"] += 1
            append_limited(result["missing_sources"], compact_record(record), 200)
            result["warnings"].append(f"Missing source file: {source_path}")

        kind = record["kind"]
        import_as = record["import_as"]
        if kind == "system_metadata" or import_as == "ignore_candidate":
            result["skipped_system_metadata"] += 1 if kind == "system_metadata" else 0
            result["skipped"] += 1
            continue

        if kind == "mac_alias" or import_as == "alias_reference":
            result["mac_aliases_found"] += 1
            result["skipped"] += 1
            append_limited(result["aliases"], compact_record(record), 200)
            continue

        if is_paper_candidate(record):
            result["paper_candidates_seen"] += 1
            identity = paper_identity(record, dedupe_keys)
            if not identity:
                result["skipped"] += 1
                result["warnings"].append(f"Skipping PDF without usable identity: {source_path or record['filename']}")
                continue

            doi = record["doi"]
            arxiv_id = record["arxiv_id"]
            path_key = source_fingerprint(record)
            duplicate = False
            if doi and doi in seen_dois:
                result["doi_duplicates"] += 1
                duplicate = True
                append_limited(result["duplicate_dois"], {"doi": doi, **compact_record(record)}, 200)
            if arxiv_id and arxiv_id in seen_arxiv_ids:
                result["arxiv_duplicates"] += 1
                duplicate = True
                append_limited(result["duplicate_arxiv_ids"], {"arxiv_id": arxiv_id, **compact_record(record)}, 200)
            if path_key and path_key in seen_paths:
                result["path_duplicates"] += 1
                duplicate = True
                append_limited(result["duplicate_paths"], {"path_key": path_key, **compact_record(record)}, 200)
            if identity in seen_identities or duplicate:
                result["duplicate_paper_candidates"] += 1
                continue

            seen_identities.add(identity)
            if doi:
                seen_dois.add(doi)
            if arxiv_id:
                seen_arxiv_ids.add(arxiv_id)
            if path_key:
                seen_paths.add(path_key)

            matched_paper_id = existing_paper_id(record, existing, dedupe_keys)
            plan = paper_plan(record, paper_id=matched_paper_id or new_paper_id(record))
            if matched_paper_id:
                result["updated_papers"] += 1
                append_limited(result["papers_to_update"], plan, 500)
            else:
                result["created_papers"] += 1
                append_limited(result["papers_to_create"], plan, 500)
            if source_path and source_exists:
                result["pdf_attachments_to_import"] += 1
                result["resources_or_attachments_to_import"] += 1
            continue

        if import_as == "resource":
            if source_path and source_exists:
                result["created_resources"] += 1
                result["resources_or_attachments_to_import"] += 1
            append_limited(result["resources_to_import"], resource_plan(record), 500)
            continue

        result["skipped"] += 1
        result["warnings"].append(f"Skipping unsupported record kind={kind or 'unknown'} import_as={import_as or 'unknown'}: {source_path}")


def execute_import(
    files: list[Any],
    result: dict[str, Any],
    storage: Storage,
    existing: dict[str, dict[str, str]],
    dedupe_keys: list[str],
    inventory_file: Path,
    library_target_root: Path,
    library_item_name: str,
) -> None:
    batch_id = "inventory_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    target_root = library_target_root / batch_id
    result["import_batch_id"] = batch_id
    result["copy_target_root"] = str(target_root)
    ensure_import_batch(storage, batch_id=batch_id, result=result, inventory_file=inventory_file)

    seen_identities: set[tuple[str, str]] = set()
    seen_dois: set[str] = set()
    seen_arxiv_ids: set[str] = set()
    seen_paths: set[str] = set()
    folder_cache: dict[str, int] = {"": 1}

    try:
        for index, raw in enumerate(files):
            if not isinstance(raw, dict):
                result["skipped"] += 1
                result["warnings"].append(f"Skipping non-object file record at index {index}.")
                continue
            record = normalize_record(raw)
            source_path = record["source_path"]
            source = Path(source_path) if source_path else None
            source_exists = bool(source and source.exists())
            if source_path and not source_exists:
                result["missing_source_files"] += 1
                append_limited(result["missing_sources"], compact_record(record), 200)
                result["warnings"].append(f"Missing source file: {source_path}")

            kind = record["kind"]
            import_as = record["import_as"]
            if kind == "system_metadata" or import_as == "ignore_candidate":
                result["skipped_system_metadata"] += 1 if kind == "system_metadata" else 0
                result["skipped"] += 1
                continue
            if kind == "mac_alias" or import_as == "alias_reference":
                result["mac_aliases_found"] += 1
                result["skipped"] += 1
                append_limited(result["aliases"], compact_record(record), 200)
                continue

            if is_paper_candidate(record):
                result["paper_candidates_seen"] += 1
                identity = paper_identity(record, dedupe_keys)
                if not identity:
                    result["skipped"] += 1
                    result["warnings"].append(f"Skipping PDF without usable identity: {source_path or record['filename']}")
                    continue
                if is_duplicate_record(record, identity, seen_identities, seen_dois, seen_arxiv_ids, seen_paths, result):
                    continue
                remember_record_identity(record, identity, seen_identities, seen_dois, seen_arxiv_ids, seen_paths)

                matched_paper_id = existing_paper_id(record, existing, dedupe_keys)
                paper_id = matched_paper_id or new_paper_id(record)
                stored_path = ""
                if source_exists:
                    stored_path = copy_or_link_record(record, target_root=target_root, copy_mode=result["copy_mode"])
                    result["pdf_attachments_to_import"] += 1
                    result["resources_or_attachments_to_import"] += 1

                upsert_imported_paper(storage, record, paper_id=paper_id, batch_id=batch_id, stored_path=stored_path)
                if matched_paper_id:
                    result["updated_papers"] += 1
                    append_limited(result["papers_to_update"], paper_plan(record, paper_id=paper_id), 500)
                else:
                    result["created_papers"] += 1
                    append_limited(result["papers_to_create"], paper_plan(record, paper_id=paper_id), 500)
                    add_existing_index(existing, record, paper_id)
                if stored_path:
                    upsert_resource(storage, record, batch_id=batch_id, paper_id=paper_id, stored_path=stored_path)
                if result["preserve_folders"]:
                    folder_id = ensure_folder_path(storage, record["parent_relative_path"], folder_cache)
                    item = storage.add_library_item(paper_id=paper_id, folder_id=folder_id)
                    if library_item_name == "filename" and item and record["filename"]:
                        storage.rename_library_item(item_id=int(item["id"]), name=record["filename"])
                continue

            if import_as == "resource":
                stored_path = ""
                if source_exists:
                    stored_path = copy_or_link_record(record, target_root=target_root, copy_mode=result["copy_mode"])
                    result["created_resources"] += 1
                    result["resources_or_attachments_to_import"] += 1
                upsert_resource(storage, record, batch_id=batch_id, paper_id=None, stored_path=stored_path)
                append_limited(result["resources_to_import"], resource_plan(record), 500)
                continue

            result["skipped"] += 1
            result["warnings"].append(f"Skipping unsupported record kind={kind or 'unknown'} import_as={import_as or 'unknown'}: {source_path}")
        finish_import_batch(storage, batch_id=batch_id, result=result, status="completed")
    except Exception as exc:
        result["errors"].append(f"Import failed: {exc}")
        finish_import_batch(storage, batch_id=batch_id, result=result, status="failed")


def is_duplicate_record(
    record: dict[str, Any],
    identity: tuple[str, str],
    seen_identities: set[tuple[str, str]],
    seen_dois: set[str],
    seen_arxiv_ids: set[str],
    seen_paths: set[str],
    result: dict[str, Any],
) -> bool:
    doi = record["doi"]
    arxiv_id = record["arxiv_id"]
    path_key = source_fingerprint(record)
    duplicate = False
    if doi and doi in seen_dois:
        result["doi_duplicates"] += 1
        duplicate = True
        append_limited(result["duplicate_dois"], {"doi": doi, **compact_record(record)}, 200)
    if arxiv_id and arxiv_id in seen_arxiv_ids:
        result["arxiv_duplicates"] += 1
        duplicate = True
        append_limited(result["duplicate_arxiv_ids"], {"arxiv_id": arxiv_id, **compact_record(record)}, 200)
    if path_key and path_key in seen_paths:
        result["path_duplicates"] += 1
        duplicate = True
        append_limited(result["duplicate_paths"], {"path_key": path_key, **compact_record(record)}, 200)
    if identity in seen_identities or duplicate:
        result["duplicate_paper_candidates"] += 1
        return True
    return False


def remember_record_identity(
    record: dict[str, Any],
    identity: tuple[str, str],
    seen_identities: set[tuple[str, str]],
    seen_dois: set[str],
    seen_arxiv_ids: set[str],
    seen_paths: set[str],
) -> None:
    seen_identities.add(identity)
    if record["doi"]:
        seen_dois.add(record["doi"])
    if record["arxiv_id"]:
        seen_arxiv_ids.add(record["arxiv_id"])
    fingerprint = source_fingerprint(record)
    if fingerprint:
        seen_paths.add(fingerprint)


def normalize_record(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": clean_text(raw.get("path")),
        "relative_path": clean_text(raw.get("relative_path")),
        "parent_relative_path": clean_text(raw.get("parent_relative_path")),
        "filename": clean_text(raw.get("filename")),
        "extension": clean_text(raw.get("extension")).lower(),
        "kind": clean_text(raw.get("kind")).lower(),
        "mime_type": clean_text(raw.get("mime_type")),
        "import_as": clean_text(raw.get("import_as")).lower(),
        "size_bytes": int_or_none(raw.get("size_bytes")),
        "modified_at": clean_text(raw.get("modified_at")),
        "doi": normalize_doi(raw.get("doi")),
        "doi_source": clean_text(raw.get("doi_source")),
        "arxiv_id": normalize_arxiv_id(raw.get("arxiv_id")),
        "title": clean_text(raw.get("title")),
        "authors": raw.get("authors") if isinstance(raw.get("authors"), list) else [],
        "page_count": int_or_none(raw.get("page_count")),
        "parse_status": clean_text(raw.get("parse_status")),
        "parse_error": clean_text(raw.get("parse_error")),
    }


def os_walk_sorted(root: Path):
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(dirnames)
        yield current, dirnames, sorted(filenames)


def scan_inventory_file(path: Path, root: Path) -> dict[str, Any]:
    stat = path.stat()
    relative_path = path.relative_to(root).as_posix()
    parent_relative_path = "" if path.parent == root else path.parent.relative_to(root).as_posix()
    extension = path.suffix.lower()
    kind = file_kind(path)
    record: dict[str, Any] = {
        "path": str(path),
        "relative_path": relative_path,
        "parent_relative_path": parent_relative_path,
        "filename": path.name,
        "extension": extension,
        "kind": kind,
        "mime_type": mime_type_for_kind(kind, extension),
        "import_as": import_as_for_kind(kind),
        "status": "recorded",
        "size_bytes": int(stat.st_size),
        "modified_at": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
    }
    if kind == "pdf":
        record.update(pdf_metadata(path))
    return record


def file_kind(path: Path) -> str:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in SYSTEM_METADATA_FILENAMES or name.startswith("._"):
        return "system_metadata"
    if suffix == ".pdf":
        return "pdf"
    if is_probable_mac_alias(path):
        return "mac_alias"
    if suffix in DOCUMENT_EXTENSIONS:
        return "document"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in PRESENTATION_EXTENSIONS:
        return "presentation"
    if suffix in SPREADSHEET_EXTENSIONS:
        return "spreadsheet"
    if suffix in ARCHIVE_EXTENSIONS:
        return "archive"
    return "unknown"


def import_as_for_kind(kind: str) -> str:
    if kind == "pdf":
        return "paper_candidate"
    if kind == "system_metadata":
        return "ignore_candidate"
    if kind == "mac_alias":
        return "alias_reference"
    return "resource"


def mime_type_for_kind(kind: str, extension: str) -> str | None:
    if kind == "pdf":
        return "application/pdf"
    if kind == "system_metadata":
        return None
    return {
        ".ppt": "application/vnd.ms-powerpoint",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }.get(extension)


def is_probable_mac_alias(path: Path) -> bool:
    try:
        if path.is_symlink() or path.is_dir() or path.stat().st_size > 1024 * 1024:
            return False
        header = path.read_bytes()[:512]
    except OSError:
        return False
    return b"book" in header[:16] or b"alis" in header[:128]


def pdf_metadata(path: Path) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "doi": "",
        "doi_source": None,
        "arxiv_id": None,
        "title": "",
        "authors": [],
        "page_count": None,
        "parse_status": "parse_error",
        "parse_error": "",
    }
    text = ""
    try:
        reader = PdfReader(str(path))
        metadata["page_count"] = len(reader.pages)
        info = reader.metadata or {}
        title = clean_text(getattr(info, "title", "") or info.get("/Title", ""))
        author = clean_text(getattr(info, "author", "") or info.get("/Author", ""))
        metadata["title"] = title
        metadata["authors"] = split_pdf_authors(author)
        pieces = []
        for page in reader.pages[:3]:
            try:
                pieces.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n".join(pieces)
        metadata["parse_status"] = "parsed" if clean_text(text) else "no_text_found"
    except Exception as exc:
        metadata["parse_error"] = str(exc)
    doi = doi_from_text(text) or doi_from_filename(path.name)
    if doi:
        metadata["doi"] = doi
        metadata["doi_source"] = "pdf_text_pypdf" if doi_from_text(text) else "filename_rule"
    arxiv_id = normalize_arxiv_id(arxiv_from_text(text) or arxiv_from_text(path.name))
    if arxiv_id:
        metadata["arxiv_id"] = arxiv_id
    if not metadata["title"]:
        metadata["title"] = path.name
    return metadata


def split_pdf_authors(value: str) -> list[str]:
    if not value:
        return []
    return [clean_text(part) for part in re.split(r"\s*(?:,|;|\band\b)\s*", value) if clean_text(part)]


def doi_from_text(value: str) -> str:
    match = DOI_PATTERN.search(value or "")
    if not match:
        return ""
    return normalize_doi(match.group(0).rstrip(".,;)"))


def doi_from_filename(filename: str) -> str:
    text = filename.replace("_", "/")
    doi = doi_from_text(text)
    if doi:
        return doi
    normalized = filename.lower()
    physrev = re.search(r"(revmodphys|physrev[a-z]*|prxquantum)\.?\s*(\d+)\.([0-9a-z]+)", normalized, flags=re.I)
    if physrev:
        journal = physrev.group(1).replace("physrevlett", "physrevlett")
        return normalize_doi(f"10.1103/{journal}.{physrev.group(2)}.{physrev.group(3)}")
    science = re.search(r"(science|sciadv)\.([a-z]?\d{4,}|[a-z]+\d+)", normalized, flags=re.I)
    if science:
        return normalize_doi(f"10.1126/{science.group(1)}.{science.group(2)}")
    nature = re.search(r"(s\d{5}-\d{3}-\d{5}-\d)", normalized)
    if nature:
        return normalize_doi(f"10.1038/{nature.group(1)}")
    return ""


def arxiv_from_text(value: str) -> str:
    match = ARXIV_PATTERN.search(value or "")
    return match.group(1) if match else ""


def inventory_summary(root: Path, directories: list[dict[str, str]], files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "root": str(root),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "directory_count": len(directories),
        "file_count": len(files),
        "pdf_count": sum(1 for item in files if item.get("kind") == "pdf"),
        "doi_count": sum(1 for item in files if item.get("doi")),
        "arxiv_count": sum(1 for item in files if item.get("arxiv_id")),
        "alias_count": sum(1 for item in files if item.get("kind") == "mac_alias"),
        "recorded_only_count": sum(1 for item in files if item.get("import_as") != "paper_candidate"),
    }


def upsert_imported_paper(
    storage: Storage,
    record: dict[str, Any],
    *,
    paper_id: str,
    batch_id: str,
    stored_path: str,
) -> None:
    title = record["title"] or record["filename"] or "(Untitled imported PDF)"
    journal = "arXiv" if record["arxiv_id"] and not record["doi"] else "Imported Library"
    raw = {
        "import": import_metadata(record, batch_id=batch_id, stored_path=stored_path),
        "authors": record["authors"],
    }
    if record["arxiv_id"]:
        raw["arxiv_id"] = record["arxiv_id"]
    storage.upsert_paper(
        {
            "paper_id": paper_id,
            "doi": record["doi"],
            "title": title,
            "journal": journal,
            "publication_date": "",
            "abstract": "",
            "abstract_source": "inventory",
            "url": f"https://arxiv.org/abs/{record['arxiv_id']}" if record["arxiv_id"] else "",
            "landing_url": f"https://arxiv.org/abs/{record['arxiv_id']}" if record["arxiv_id"] else "",
            "pdf_url": "",
            "source": "inventory",
            "type": "imported_pdf",
            "type_crossref": "",
            "publisher_section": "imported",
            "section_allowed": True,
            "raw": raw,
        }
    )
    storage.conn.execute(
        """
        UPDATE papers
        SET source_path = ?,
            original_relative_path = ?,
            original_parent_relative_path = ?,
            original_filename = ?,
            import_batch_id = ?,
            import_kind = ?,
            import_as = ?,
            doi_source = ?,
            parse_status = ?,
            parse_error = ?,
            size_bytes = ?,
            modified_at = ?,
            page_count = ?,
            download_status = CASE WHEN ? != '' THEN 'success' ELSE download_status END,
            download_message = CASE WHEN ? != '' THEN ? ELSE download_message END,
            main_pdf_path = CASE WHEN ? != '' THEN ? ELSE main_pdf_path END,
            merged_pdf_path = CASE WHEN ? != '' THEN ? ELSE merged_pdf_path END,
            downloaded_at = CASE WHEN ? != '' THEN ? ELSE downloaded_at END
        WHERE paper_id = ?
        """,
        (
            record["source_path"],
            record["relative_path"],
            record["parent_relative_path"],
            record["filename"],
            batch_id,
            record["kind"],
            record["import_as"],
            record["doi_source"],
            record["parse_status"],
            record["parse_error"],
            record["size_bytes"],
            record["modified_at"],
            record["page_count"],
            stored_path,
            stored_path,
            f"imported from inventory ({'copied' if stored_path != record['source_path'] else 'linked'})",
            stored_path,
            stored_path,
            stored_path,
            stored_path,
            stored_path,
            now_text(),
            paper_id,
        ),
    )
    storage.conn.commit()


def upsert_resource(
    storage: Storage,
    record: dict[str, Any],
    *,
    batch_id: str,
    paper_id: str | None,
    stored_path: str,
) -> None:
    timestamp = now_text()
    storage.conn.execute(
        """
        INSERT INTO resources (
          paper_id, source_path, stored_path, original_relative_path,
          original_parent_relative_path, original_filename, kind, mime_type,
          import_as, import_batch_id, size_bytes, modified_at, parse_status,
          parse_error, page_count, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_path, size_bytes, kind) DO UPDATE SET
          paper_id = COALESCE(excluded.paper_id, resources.paper_id),
          stored_path = COALESCE(NULLIF(excluded.stored_path, ''), resources.stored_path),
          original_relative_path = excluded.original_relative_path,
          original_parent_relative_path = excluded.original_parent_relative_path,
          original_filename = excluded.original_filename,
          mime_type = excluded.mime_type,
          import_as = excluded.import_as,
          import_batch_id = excluded.import_batch_id,
          modified_at = excluded.modified_at,
          parse_status = excluded.parse_status,
          parse_error = excluded.parse_error,
          page_count = excluded.page_count,
          status = excluded.status,
          updated_at = excluded.updated_at
        """,
        (
            paper_id,
            record["source_path"],
            stored_path,
            record["relative_path"],
            record["parent_relative_path"],
            record["filename"],
            record["kind"],
            record["mime_type"],
            record["import_as"],
            batch_id,
            record["size_bytes"],
            record["modified_at"],
            record["parse_status"],
            record["parse_error"],
            record["page_count"],
            "imported" if stored_path else "missing_source",
            timestamp,
            timestamp,
        ),
    )
    storage.conn.commit()


def import_metadata(record: dict[str, Any], *, batch_id: str, stored_path: str) -> dict[str, Any]:
    return {
        "batch_id": batch_id,
        "source_path": record["source_path"],
        "stored_path": stored_path,
        "relative_path": record["relative_path"],
        "parent_relative_path": record["parent_relative_path"],
        "filename": record["filename"],
        "kind": record["kind"],
        "import_as": record["import_as"],
        "doi_source": record["doi_source"],
        "parse_status": record["parse_status"],
        "parse_error": record["parse_error"],
        "page_count": record["page_count"],
        "size_bytes": record["size_bytes"],
        "modified_at": record["modified_at"],
    }


def copy_or_link_record(record: dict[str, Any], *, target_root: Path, copy_mode: str) -> str:
    source = Path(record["source_path"])
    if copy_mode == "link":
        return str(source)
    relative_path = safe_inventory_relative_path(record["relative_path"] or record["filename"])
    target = unique_target_path(target_root / relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return str(target)


def safe_inventory_relative_path(value: str) -> Path:
    parts = []
    for part in Path(value).parts:
        if part in {"", ".", ".."}:
            continue
        parts.append(part)
    if not parts:
        parts = ["unnamed-resource"]
    return Path(*parts)


def unique_target_path(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    parent = target.parent
    for index in range(1, 10000):
        candidate = parent / f"{stem}__{index}{suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not find unique import target for {target}")


def ensure_folder_path(storage: Storage, relative_parent_path: str, folder_cache: dict[str, int]) -> int:
    clean_path = relative_parent_path.strip("/")
    if clean_path in folder_cache:
        return folder_cache[clean_path]
    current = 1
    current_path = ""
    for part in Path(clean_path).parts if clean_path else []:
        name = clean_text(part) or "Untitled Folder"
        current_path = f"{current_path}/{name}" if current_path else name
        if current_path not in folder_cache:
            folder = storage.ensure_library_folder(parent_id=current, name=name)
            folder_cache[current_path] = int(folder["id"])
        current = folder_cache[current_path]
    folder_cache[clean_path] = current
    return current


def ensure_import_batch(storage: Storage, *, batch_id: str, result: dict[str, Any], inventory_file: Path) -> None:
    storage.conn.execute(
        """
        INSERT INTO inventory_import_batches (
          id, inventory_path, source_root, copy_mode, preserve_folders, dedupe_by,
          dry_run, status, started_at, errors_json, warnings_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            batch_id,
            str(inventory_file),
            result.get("source_root") or "",
            result.get("copy_mode") or "",
            1 if result.get("preserve_folders") else 0,
            ",".join(result.get("dedupe_by") or []),
            0,
            "running",
            now_text(),
            "[]",
            "[]",
        ),
    )
    storage.conn.commit()


def finish_import_batch(storage: Storage, *, batch_id: str, result: dict[str, Any], status: str) -> None:
    storage.conn.execute(
        """
        UPDATE inventory_import_batches
        SET status = ?,
            report_path = ?,
            finished_at = ?,
            created_papers = ?,
            updated_papers = ?,
            created_resources = ?,
            skipped = ?,
            errors_json = ?,
            warnings_json = ?
        WHERE id = ?
        """,
        (
            status,
            result.get("report_path") or "",
            now_text(),
            int(result.get("created_papers") or 0),
            int(result.get("updated_papers") or 0),
            int(result.get("created_resources") or 0),
            int(result.get("skipped") or 0),
            json.dumps(result.get("errors") or [], ensure_ascii=False),
            json.dumps(result.get("warnings") or [], ensure_ascii=False),
            batch_id,
        ),
    )
    storage.conn.commit()


def add_existing_index(existing: dict[str, dict[str, str]], record: dict[str, Any], paper_id: str) -> None:
    if record["doi"]:
        existing["doi"].setdefault(record["doi"], paper_id)
    if record["arxiv_id"]:
        existing["arxiv_id"].setdefault(record["arxiv_id"], paper_id)
    fingerprint = source_fingerprint(record)
    if fingerprint:
        existing["source_path"].setdefault(fingerprint, paper_id)


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def is_paper_candidate(record: dict[str, Any]) -> bool:
    return record["kind"] == PAPER_CANDIDATE_KIND and record["import_as"] == PAPER_CANDIDATE_IMPORT_AS


def paper_identity(record: dict[str, Any], dedupe_keys: list[str]) -> tuple[str, str] | None:
    for key in dedupe_keys:
        if key == "doi" and record["doi"]:
            return ("doi", record["doi"])
        if key == "arxiv_id" and record["arxiv_id"]:
            return ("arxiv_id", record["arxiv_id"])
        if key == "source_path":
            fingerprint = source_fingerprint(record)
            if fingerprint:
                return ("source_path", fingerprint)
    return None


def source_fingerprint(record: dict[str, Any]) -> str:
    path = record.get("source_path") or ""
    size = record.get("size_bytes")
    if not path:
        return ""
    return f"{path}|{size}" if size is not None else path


def existing_paper_id(record: dict[str, Any], existing: dict[str, dict[str, str]], dedupe_keys: list[str]) -> str:
    for key in dedupe_keys:
        if key == "doi" and record["doi"]:
            paper_id = existing["doi"].get(record["doi"])
            if paper_id:
                return paper_id
        if key == "arxiv_id" and record["arxiv_id"]:
            paper_id = existing["arxiv_id"].get(record["arxiv_id"])
            if paper_id:
                return paper_id
        if key == "source_path":
            fingerprint = source_fingerprint(record)
            paper_id = existing["source_path"].get(fingerprint)
            if paper_id:
                return paper_id
    return ""


def build_existing_index(storage: Storage) -> dict[str, dict[str, str]]:
    rows = storage.conn.execute("SELECT paper_id, doi, raw_json FROM papers").fetchall()
    index: dict[str, dict[str, str]] = {"doi": {}, "arxiv_id": {}, "source_path": {}}
    for row in rows:
        paper_id = str(row["paper_id"] or "")
        doi = normalize_doi(row["doi"])
        if paper_id and doi:
            index["doi"].setdefault(doi, paper_id)
        raw = parse_json(row["raw_json"])
        for value in [raw.get("arxiv_id"), raw.get("versioned_arxiv_id")]:
            arxiv_id = normalize_arxiv_id(value)
            if paper_id and arxiv_id:
                index["arxiv_id"].setdefault(arxiv_id, paper_id)
        imported = raw.get("import") if isinstance(raw.get("import"), dict) else {}
        source_path = clean_text(imported.get("source_path") or raw.get("source_path"))
        size = int_or_none(imported.get("size_bytes", raw.get("size_bytes")))
        if paper_id and source_path:
            fingerprint = f"{source_path}|{size}" if size is not None else source_path
            index["source_path"].setdefault(fingerprint, paper_id)
    return index


def new_paper_id(record: dict[str, Any]) -> str:
    if record["doi"]:
        return make_paper_id(record["doi"], record["title"], "Imported Library", "")
    if record["arxiv_id"]:
        return "arxiv_" + safe_slug(record["arxiv_id"], 90)
    fingerprint = source_fingerprint(record) or record["relative_path"] or record["filename"] or "imported-paper"
    return "import_" + sha1_short(fingerprint, 16)


def paper_plan(record: dict[str, Any], *, paper_id: str) -> dict[str, Any]:
    return {
        "paper_id": paper_id,
        "doi": record["doi"],
        "arxiv_id": record["arxiv_id"],
        "title": record["title"] or record["filename"] or "(Untitled imported PDF)",
        "source_path": record["source_path"],
        "relative_path": record["relative_path"],
        "parent_relative_path": record["parent_relative_path"],
        "filename": record["filename"],
        "size_bytes": record["size_bytes"],
        "page_count": record["page_count"],
        "doi_source": record["doi_source"],
        "parse_status": record["parse_status"],
        "parse_error": record["parse_error"],
    }


def resource_plan(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": record["source_path"],
        "relative_path": record["relative_path"],
        "parent_relative_path": record["parent_relative_path"],
        "filename": record["filename"],
        "kind": record["kind"],
        "mime_type": record["mime_type"],
        "size_bytes": record["size_bytes"],
        "modified_at": record["modified_at"],
    }


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_path": record["source_path"],
        "relative_path": record["relative_path"],
        "filename": record["filename"],
        "kind": record["kind"],
        "import_as": record["import_as"],
        "size_bytes": record["size_bytes"],
    }


def normalize_dedupe_keys(values: Iterable[str]) -> list[str]:
    aliases = {
        "arxiv": "arxiv_id",
        "arxiv_id": "arxiv_id",
        "path": "source_path",
        "source_path": "source_path",
        "doi": "doi",
    }
    keys: list[str] = []
    for value in values:
        for part in str(value).split(","):
            normalized = aliases.get(part.strip().lower())
            if normalized and normalized not in keys:
                keys.append(normalized)
    return keys or ["doi", "arxiv_id", "source_path"]


def finalize_result(result: dict[str, Any], report_path: str | Path | None) -> dict[str, Any]:
    if report_path:
        path = Path(report_path)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        suffix = "dry-run" if result.get("dry_run") else "import"
        path = REPORT_DIR / f"inventory-{suffix}-{stamp}.json"
    result["report_path"] = str(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        result["warnings"].append(f"Could not write import report JSON: {exc}")
    return result


def parse_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value or "{}")
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def normalize_arxiv_id(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = re.sub(r"^arxiv:", "", text, flags=re.I)
    text = text.removeprefix("https://arxiv.org/abs/")
    text = text.removeprefix("http://arxiv.org/abs/")
    text = text.removeprefix("https://arxiv.org/pdf/")
    text = text.removeprefix("http://arxiv.org/pdf/")
    text = text.removesuffix(".pdf")
    return re.sub(r"v\d+$", "", text.strip()).lower()


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def append_limited(target: list[Any], value: Any, limit: int) -> None:
    if len(target) < limit:
        target.append(value)
