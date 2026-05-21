from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as email_policy
import hashlib
from io import BytesIO
import json
import mimetypes
import re
import subprocess
import threading
import uuid
import webbrowser
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter

from .analysis import queue_codex_analysis
from .config import (
    AppConfig,
    DEFAULT_ANALYSIS_DIR,
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_LIBRARY_IMPORT_DIR,
    DEFAULT_PDF_DIR,
    ROOT,
    load_config,
)
from .download import download_paper
from .http import request_with_retries
from .importers.inventory import build_inventory_from_folder, import_library_inventory
from .monitor import fetch_one_arxiv_preprint_source, run_journal_monitor
from .reporting import section_badge_background, section_color
from .sources.arxiv import ARXIV_DEFAULT_CATEGORIES, ARXIV_JOURNAL_NAME
from .sources.crossref import normalize_crossref_item
from .sources.publisher import enrich_image_from_landing_page
from .storage import Storage
from .text import clean_text, safe_slug
from .time_utils import today_jst


FETCH_PROGRESS: dict[str, dict[str, Any]] = {}
FETCH_PROGRESS_LOCK = threading.Lock()
LIBRARY_IMPORT_JOBS: dict[str, dict[str, Any]] = {}
LIBRARY_IMPORT_JOBS_LOCK = threading.Lock()
ACTIVE_FETCH_DATES: set[str] = set()
JOURNAL_LOGO_CACHE: dict[str, str] = {}
PREPRINT_JOURNALS = [ARXIV_JOURNAL_NAME]
LIBRARY_UNSORTED_FOLDER_NAME = "unsorted"
LIBRARY_RECYCLE_FOLDER_NAME = "Recycle"
LIBRARY_SHORTCUT_TAB_COUNT = 5
LIBRARY_WORKSPACE_TAB_COUNT = 3
QUICK_LOOK_LOCK = threading.Lock()
QUICK_LOOK_PROCESS: Any = None
PDF_THUMB_CACHE_DIR = Path("/private/tmp/paper_monitor_pdf_thumbs")
RECENT_FETCH_REFRESH_DAYS = 14
RECENT_FETCH_REFRESH_AFTER = timedelta(hours=6)
ERROR_FETCH_RETRY_AFTER = timedelta(minutes=30)


def activate_native_app_later(delay: float = 0.25) -> None:
    def activate() -> None:
        try:
            subprocess.Popen(
                ["osascript", "-e", 'tell application id "local.paper-monitor" to activate'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            return

    threading.Timer(delay, activate).start()


def open_single_quick_look(path: Path) -> None:
    global QUICK_LOOK_PROCESS
    with QUICK_LOOK_LOCK:
        if QUICK_LOOK_PROCESS and QUICK_LOOK_PROCESS.poll() is None:
            QUICK_LOOK_PROCESS.terminate()
        QUICK_LOOK_PROCESS = subprocess.Popen(
            ["qlmanage", "-p", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def run_ui_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Path = DEFAULT_DB_PATH,
    open_browser: bool = False,
) -> None:
    config = load_config()
    journals = configured_source_names(config)

    class Handler(PaperMonitorUiHandler):
        configured_db_path = db_path
        configured_journals = journals

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_port}"
    print(f"Journal Monitor UI: {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    server.serve_forever()


class PaperMonitorUiHandler(BaseHTTPRequestHandler):
    configured_db_path: Path = DEFAULT_DB_PATH
    configured_journals: list[str] = []

    server_version = "PaperMonitorUI/0.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/":
                self.send_text(INDEX_HTML, content_type="text/html; charset=utf-8")
                return
            if parsed.path == "/api/month":
                self.handle_month(parse_qs(parsed.query))
                return
            if parsed.path == "/api/report":
                self.handle_report(parse_qs(parsed.query))
                return
            if parsed.path == "/api/fetch-progress":
                self.handle_fetch_progress(parse_qs(parsed.query))
                return
            if parsed.path == "/api/library/import-folder/progress":
                self.handle_library_import_folder_progress(parse_qs(parsed.query))
                return
            if parsed.path == "/api/paper":
                self.handle_paper(parse_qs(parsed.query))
                return
            if parsed.path == "/api/pdf-info":
                self.handle_pdf_info(parse_qs(parsed.query))
                return
            if parsed.path == "/api/pdf-page":
                self.handle_pdf_page(parse_qs(parsed.query))
                return
            if parsed.path == "/api/pdf-thumb":
                self.handle_pdf_thumb(parse_qs(parsed.query))
                return
            if parsed.path == "/api/analysis":
                self.handle_analysis(parse_qs(parsed.query))
                return
            if parsed.path == "/api/journals":
                self.handle_journals()
                return
            if parsed.path == "/api/journal-logo":
                self.handle_journal_logo(parse_qs(parsed.query))
                return
            if parsed.path == "/api/paper-figure":
                self.handle_paper_figure(parse_qs(parsed.query))
                return
            if parsed.path == "/api/page-proxy":
                self.handle_page_proxy(parse_qs(parsed.query))
                return
            if parsed.path == "/api/library":
                self.handle_library(parse_qs(parsed.query))
                return
            if parsed.path == "/api/my-publications":
                self.handle_my_publications(parse_qs(parsed.query))
                return
            if parsed.path == "/api/publication-search":
                self.handle_publication_search(parse_qs(parsed.query))
                return
            if parsed.path == "/files":
                self.handle_file(parse_qs(parsed.query))
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown route")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/manual-pdf":
                self.handle_manual_pdf()
                return
            payload = self.read_json_body()
            if parsed.path == "/api/download":
                self.handle_download(payload)
                return
            if parsed.path == "/api/analyze":
                self.handle_analyze(payload)
                return
            if parsed.path == "/api/delete-pdf":
                self.handle_delete_pdf(payload)
                return
            if parsed.path == "/api/delete-analysis":
                self.handle_delete_analysis(payload)
                return
            if parsed.path == "/api/open-pdf":
                self.handle_open_pdf(payload)
                return
            if parsed.path == "/api/quick-look":
                self.handle_quick_look(payload)
                return
            if parsed.path == "/api/open-url":
                self.handle_open_url(payload)
                return
            if parsed.path == "/api/reveal-path":
                self.handle_reveal_path(payload)
                return
            if parsed.path == "/api/journals/add":
                self.handle_add_journal(payload)
                return
            if parsed.path == "/api/journals/remove":
                self.handle_remove_journal(payload)
                return
            if parsed.path == "/api/library/folders":
                self.handle_create_library_folder(payload)
                return
            if parsed.path == "/api/library/folders/rename":
                self.handle_rename_library_folder(payload)
                return
            if parsed.path == "/api/library/folders/color":
                self.handle_color_library_folder(payload)
                return
            if parsed.path == "/api/library/items":
                self.handle_add_library_item(payload)
                return
            if parsed.path == "/api/library/items/rename":
                self.handle_rename_library_item(payload)
                return
            if parsed.path == "/api/library/move":
                self.handle_move_library_entry(payload)
                return
            if parsed.path == "/api/library/reorder":
                self.handle_reorder_library_entry(payload)
                return
            if parsed.path == "/api/library/delete":
                self.handle_delete_library_entry(payload)
                return
            if parsed.path == "/api/library/recover":
                self.handle_recover_library_entry(payload)
                return
            if parsed.path == "/api/library/remove-paper":
                self.handle_remove_paper_from_library(payload)
                return
            if parsed.path == "/api/library/paste":
                self.handle_paste_library_entry(payload)
                return
            if parsed.path == "/api/my-publications/add":
                self.handle_add_my_publication(payload)
                return
            if parsed.path == "/api/my-publications/star":
                self.handle_star_my_publication(payload)
                return
            if parsed.path == "/api/my-publications/delete":
                self.handle_delete_my_publication(payload)
                return
            if parsed.path == "/api/my-publications/name":
                self.handle_set_my_publication_name(payload)
                return
            if parsed.path == "/api/library/shortcut-tabs":
                self.handle_set_library_shortcut_tabs(payload)
                return
            if parsed.path == "/api/library/workspace-tabs/rename":
                self.handle_rename_library_workspace_tab(payload)
                return
            if parsed.path == "/api/library/workspace-tabs/add-doi":
                self.handle_add_library_workspace_doi(payload)
                return
            if parsed.path == "/api/library/import-folder/choose":
                self.handle_choose_library_import_folder()
                return
            if parsed.path == "/api/library/import-folder/start":
                self.handle_start_library_import_folder(payload)
                return
            if parsed.path == "/api/library/import-folder":
                self.handle_library_import_folder(payload)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown route")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, format: str, *args: Any) -> None:
        return

    def handle_month(self, query: dict[str, list[str]]) -> None:
        self.refresh_journals()
        year = int(first(query, "year") or today_jst().year)
        month = int(first(query, "month") or today_jst().month)
        prefix = f"{year:04d}-{month:02d}-"
        storage = Storage(self.configured_db_path)
        try:
            rows = storage.conn.execute(
                """
                SELECT publication_date, journal, COUNT(*) AS count
                FROM papers
                WHERE publication_date LIKE ?
                  AND (section_allowed IS NULL OR section_allowed != 0)
                GROUP BY publication_date, journal
                ORDER BY publication_date ASC, journal ASC
                """,
                (prefix + "%",),
            ).fetchall()
        finally:
            storage.close()

        counts: dict[str, dict[str, int]] = {}
        for row in rows:
            day = row["publication_date"]
            counts.setdefault(day, {})[row["journal"]] = int(row["count"] or 0)

        self.send_json(
            {
                "year": year,
                "month": month,
                "journals": self.configured_journals,
                "counts": counts,
            }
        )

    def handle_report(self, query: dict[str, list[str]]) -> None:
        self.refresh_journals()
        selected = first(query, "date") or today_jst().isoformat()
        auto_fetch = first(query, "auto_fetch") != "0"
        fetched = False
        missing_journals: list[str] = []
        storage = Storage(self.configured_db_path)
        try:
            selected_date = date.fromisoformat(selected)
            missing_journals = missing_fetch_journals_for_date(storage, selected, self.configured_journals)
            if auto_fetch and selected_date <= today_jst() and missing_journals and try_start_fetch(selected):
                storage.close()
                fetch_storage = None
                try:
                    config = load_config()
                    fetch_storage = Storage(self.configured_db_path)
                    start_fetch_progress(selected, missing_journals)
                    fetch_missing_sources_for_date(
                        config=config,
                        storage=fetch_storage,
                        selected=selected,
                        selected_date=selected_date,
                        missing_sources=missing_journals,
                    )
                    fetched = True
                finally:
                    finish_fetch_progress(selected)
                    finish_active_fetch(selected)
                    if fetch_storage:
                        fetch_storage.close()
                storage = Storage(self.configured_db_path)
                self.configured_journals = configured_source_names(config)
                missing_journals = missing_fetch_journals_for_date(storage, selected, self.configured_journals)
            papers = storage.list_papers(
                start_date=selected,
                end_date=selected,
                journals=self.configured_journals,
            )
        finally:
            storage.close()
        papers = [paper for paper in papers if paper.get("section_allowed") != 0]
        self.send_json(
            {
                "date": selected,
                "journals": self.configured_journals,
                "papers": [paper_to_api(paper) for paper in papers],
                "journalCounts": count_by_journal(papers),
                "fetched": fetched,
                "missingJournals": missing_journals,
                "fetchActive": is_fetch_active(selected),
            }
        )

    def handle_fetch_progress(self, query: dict[str, list[str]]) -> None:
        selected = first(query, "date") or today_jst().isoformat()
        self.send_json({"date": selected, "progress": get_fetch_progress(selected)})

    def handle_paper(self, query: dict[str, list[str]]) -> None:
        paper_id = first(query, "paper_id")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            paper = storage.get_paper(paper_id)
        finally:
            storage.close()
        if not paper:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
            return
        self.send_json({"paper": paper_to_api(paper)})

    def handle_download(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            result = download_paper(storage=storage, paper_id=paper_id, force=bool(payload.get("force")))
            paper = storage.get_paper(paper_id)
        finally:
            storage.close()
        self.send_json({"result": result, "paper": paper_to_api(paper) if paper else None})

    def handle_manual_pdf(self) -> None:
        fields, files = self.read_multipart_body()
        paper_id = str(fields.get("paper_id") or "")
        upload = files.get("pdf")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        if not upload:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "PDF file is required")
            return
        filename = upload.get("filename") or ""
        data = upload.get("content") or b""
        if not filename.lower().endswith(".pdf") or b"%PDF-" not in data[:1024]:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Uploaded file must be a PDF")
            return

        storage = Storage(self.configured_db_path)
        try:
            paper = storage.get_paper(paper_id)
            if not paper:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
                return
            target_dir = DEFAULT_PDF_DIR / paper_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / f"{safe_slug(paper.get('title') or paper_id, 80)}_manual.pdf"
            target_path.write_bytes(data)
            storage.update_download_status(
                paper_id,
                status="success",
                message=f"manual PDF uploaded: {filename}",
                main_pdf_path=str(target_path),
                supplement_pdf_paths=[],
                merged_pdf_path=str(target_path),
            )
            paper = storage.get_paper(paper_id)
        finally:
            storage.close()
        self.send_json({"result": {"status": "success", "merged_pdf_path": str(target_path)}, "paper": paper_to_api(paper) if paper else None})

    def handle_analyze(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            job_path = queue_codex_analysis(storage=storage, paper_id=paper_id)
            paper = storage.get_paper(paper_id)
        finally:
            storage.close()
        self.send_json(
            {
                "job_path": str(job_path),
                "analysis_content": "",
                "paper": paper_to_api(paper) if paper else None,
            }
        )

    def handle_library(self, query: dict[str, list[str]]) -> None:
        storage = Storage(self.configured_db_path)
        try:
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json(snapshot)

    def handle_my_publications(self, query: dict[str, list[str]]) -> None:
        storage = Storage(self.configured_db_path)
        try:
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
            my_name = storage.get_setting("my_publications_name", "")
        finally:
            storage.close()
        self.send_json({"publications": publications, "myName": my_name})

    def handle_publication_search(self, query: dict[str, list[str]]) -> None:
        search_text = (first(query, "q") or "").strip()
        kind = (first(query, "kind") or "auto").strip().lower()
        if not search_text:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "q is required")
            return
        try:
            results = search_crossref_publications(search_text, kind=kind)
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Publication lookup failed: {exc}")
            return
        self.send_json({"results": [publication_candidate_to_api(paper) for paper in results]})

    def handle_add_my_publication(self, payload: dict[str, Any]) -> None:
        candidate = payload.get("paper")
        paper_id = str(payload.get("paper_id") or "")
        storage = Storage(self.configured_db_path)
        try:
            paper: dict[str, Any] | None = None
            if isinstance(candidate, dict):
                normalized = paper_from_publication_candidate(candidate)
                storage.upsert_paper(normalized)
                paper = storage.get_paper(normalized["paper_id"])
                paper_id = normalized["paper_id"]
            elif paper_id:
                paper = storage.get_paper(paper_id)
            if not paper_id or not paper:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "A publication candidate or paper_id is required")
                return
            publication = storage.add_my_publication(paper_id=paper_id)
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_star_my_publication(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.set_my_publication_starred(publication_id=publication_id, starred=bool(payload.get("starred")))
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_delete_my_publication(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            storage.delete_my_publication(publication_id=publication_id)
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publications": publications})

    def handle_set_my_publication_name(self, payload: dict[str, Any]) -> None:
        my_name = " ".join(str(payload.get("name") or "").split())
        storage = Storage(self.configured_db_path)
        try:
            storage.set_setting("my_publications_name", my_name)
        finally:
            storage.close()
        self.send_json({"myName": my_name})

    def handle_set_library_shortcut_tabs(self, payload: dict[str, Any]) -> None:
        index = int(payload.get("index") or 0)
        folder_id = int(payload.get("folder_id") or 0)
        if index < 0 or index >= LIBRARY_SHORTCUT_TAB_COUNT:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "shortcut index is out of range")
            return
        storage = Storage(self.configured_db_path)
        try:
            folder = storage.get_library_folder(folder_id) if folder_id else None
            if folder_id and (not folder or int(folder.get("id") or 0) == 1):
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Drop a Library folder onto this shortcut")
                return
            shortcuts = library_shortcut_tabs(storage)
            shortcuts[index] = {"folder_id": folder_id, "label": str(folder.get("name") or "") if folder else ""}
            storage.set_setting("library_shortcut_tabs", json.dumps(shortcuts, ensure_ascii=False))
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json(snapshot)

    def handle_rename_library_workspace_tab(self, payload: dict[str, Any]) -> None:
        index = int(payload.get("index") or 0)
        if index < 0 or index >= LIBRARY_WORKSPACE_TAB_COUNT:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "space index is out of range")
            return
        label = " ".join(str(payload.get("label") or "").split()) or f"Space {index + 1}"
        storage = Storage(self.configured_db_path)
        try:
            tabs = library_workspace_tabs(storage)
            tabs[index]["label"] = label[:80]
            root_folder_id = int(tabs[index].get("root_folder_id") or 0)
            if root_folder_id:
                folder = storage.rename_library_folder(folder_id=root_folder_id, name=label[:80])
                tabs[index]["root_folder_id"] = int(folder.get("id") or root_folder_id)
                tabs[index]["label"] = str(folder.get("name") or label)[:80]
            storage.set_setting("library_workspace_tabs", json.dumps(workspace_tabs_to_setting(tabs), ensure_ascii=False))
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json(snapshot)

    def handle_add_library_workspace_doi(self, payload: dict[str, Any]) -> None:
        index = int(payload.get("index") or 0)
        if index < 0 or index >= LIBRARY_WORKSPACE_TAB_COUNT:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "space index is out of range")
            return
        doi = normalize_publication_doi(str(payload.get("doi") or ""))
        if not doi:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "DOI is required")
            return
        try:
            candidates = search_crossref_publications(doi, kind="doi")
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"DOI lookup failed: {exc}")
            return
        if not candidates:
            self.send_error_json(HTTPStatus.NOT_FOUND, "No publication found for this DOI")
            return
        storage = Storage(self.configured_db_path)
        try:
            paper = paper_from_publication_candidate(candidates[0])
            storage.upsert_paper(paper)
            paper_id = str(paper.get("paper_id") or "")
            tabs = library_workspace_tabs(storage)
            root_folder_id = int(tabs[index].get("root_folder_id") or 0)
            if not root_folder_id:
                raise ValueError("Space root folder not found")
            if paper_id:
                storage.add_library_item(paper_id=paper_id, folder_id=root_folder_id)
            storage.set_setting("library_workspace_tabs", json.dumps(workspace_tabs_to_setting(tabs), ensure_ascii=False))
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"paper_id": paper_id, **snapshot})

    def handle_choose_library_import_folder(self) -> None:
        try:
            script = (
                'POSIX path of (choose folder with prompt '
                '"Choose a folder to import into Journal Monitor. The source folder will be read only.")'
            )
            result = subprocess.run(
                ["osascript", "-e", script],
                check=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as exc:
            message = (exc.stderr or "").strip() or "Folder selection was cancelled"
            self.send_error_json(HTTPStatus.BAD_REQUEST, message)
            return
        folder_path = result.stdout.strip().rstrip("/")
        self.send_json({"path": folder_path})

    def handle_start_library_import_folder(self, payload: dict[str, Any]) -> None:
        folder_path = Path(str(payload.get("folder_path") or "")).expanduser()
        if not str(folder_path):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Folder path is required")
            return
        try:
            folder_path = folder_path.resolve()
        except OSError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, f"Could not resolve folder path: {exc}")
            return
        if not folder_path.exists() or not folder_path.is_dir():
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Folder path is not a readable directory")
            return
        copy_mode = str(payload.get("copy_mode") or "copy")
        if copy_mode not in {"copy", "link"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "copy_mode must be copy or link")
            return
        dry_run = bool(payload.get("dry_run"))
        job_id = create_library_import_job(folder_path=folder_path, copy_mode=copy_mode, dry_run=dry_run)
        thread = threading.Thread(
            target=run_library_import_job,
            kwargs={
                "job_id": job_id,
                "folder_path": folder_path,
                "copy_mode": copy_mode,
                "dry_run": dry_run,
                "db_path": self.configured_db_path,
            },
            daemon=True,
        )
        thread.start()
        self.send_json({"job_id": job_id, "job": get_library_import_job(job_id)})

    def handle_library_import_folder_progress(self, query: dict[str, list[str]]) -> None:
        job_id = first(query, "job_id") or first(query, "id")
        job = get_library_import_job(job_id)
        if not job:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown import job")
            return
        self.send_json({"job": job})

    def handle_library_import_folder(self, payload: dict[str, Any]) -> None:
        folder_path = Path(str(payload.get("folder_path") or "")).expanduser()
        if not str(folder_path):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Folder path is required")
            return
        try:
            folder_path = folder_path.resolve()
        except OSError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, f"Could not resolve folder path: {exc}")
            return
        if not folder_path.exists() or not folder_path.is_dir():
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Folder path is not a readable directory")
            return
        copy_mode = str(payload.get("copy_mode") or "copy")
        if copy_mode not in {"copy", "link"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "copy_mode must be copy or link")
            return
        dry_run = bool(payload.get("dry_run"))
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = safe_slug(folder_path.name or "library-folder", 60)
        inventory_path = ROOT / "reports" / "imports" / f"folder-inventory-{slug}-{timestamp}.json"
        report_path = ROOT / "reports" / "imports" / f"folder-import-{slug}-{'dry-run' if dry_run else 'import'}-{timestamp}.json"
        try:
            build_inventory_from_folder(folder_path, output_path=inventory_path, parse_pdfs=False)
            storage = Storage(self.configured_db_path)
            try:
                result = import_library_inventory(
                    inventory_path,
                    copy_mode=copy_mode,
                    preserve_folders=True,
                    dedupe_by=("doi", "arxiv", "path"),
                    dry_run=dry_run,
                    storage=storage,
                    report_path=report_path,
                    library_item_name="filename",
                )
                snapshot = library_snapshot(storage)
            finally:
                storage.close()
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self.send_json({"import_result": summarize_import_result(result), "inventory_path": str(inventory_path), **snapshot})

    def handle_create_library_folder(self, payload: dict[str, Any]) -> None:
        name = str(payload.get("name") or "New Folder")
        parent_id = int(payload.get("parent_id") or 1)
        storage = Storage(self.configured_db_path)
        try:
            folder = storage.create_library_folder(parent_id=parent_id, name=name)
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json({"folder": library_folder_to_api(folder), **snapshot})

    def handle_rename_library_folder(self, payload: dict[str, Any]) -> None:
        folder_id = int(payload.get("folder_id") or 0)
        name = str(payload.get("name") or "")
        storage = Storage(self.configured_db_path)
        try:
            folder = storage.rename_library_folder(folder_id=folder_id, name=name)
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"folder": library_folder_to_api(folder), **snapshot})

    def handle_color_library_folder(self, payload: dict[str, Any]) -> None:
        folder_id = int(payload.get("folder_id") or 0)
        color = str(payload.get("color") or "")
        storage = Storage(self.configured_db_path)
        try:
            folder = storage.set_library_folder_color(folder_id=folder_id, color=color)
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"folder": library_folder_to_api(folder), **snapshot})

    def handle_add_library_item(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        folder_id = int(payload.get("folder_id") or 1)
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            target_folder = None
            if payload.get("unsorted"):
                target_folder = storage.ensure_library_folder(parent_id=1, name=LIBRARY_UNSORTED_FOLDER_NAME)
                folder_id = int(target_folder.get("id") or 1)
            paper = storage.get_paper(paper_id)
            if not paper:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
                return
            item = storage.add_library_item(paper_id=paper_id, folder_id=folder_id)
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json({
            "item": library_item_to_api(item, paper) if item else {},
            "folder": library_folder_to_api(target_folder) if target_folder else None,
            **snapshot,
        })

    def handle_rename_library_item(self, payload: dict[str, Any]) -> None:
        item_id = int(payload.get("item_id") or 0)
        name = str(payload.get("name") or "")
        storage = Storage(self.configured_db_path)
        try:
            item = storage.rename_library_item(item_id=item_id, name=name)
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"item_id": int(item.get("id") or item_id), **snapshot})

    def handle_move_library_entry(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        target_folder_id = int(payload.get("target_folder_id") or 1)
        storage = Storage(self.configured_db_path)
        try:
            special = ensure_library_special_folders(storage)
            unsorted_id = int(special["unsorted"].get("id") or 1)
            recycle_id = int(special["recycle"].get("id") or 1)
            moved: dict[str, Any] | None = None
            if entry_type == "item":
                item_id = int(payload.get("id") or 0)
                if target_folder_id == recycle_id:
                    moved = storage.move_library_item_to_trash(item_id=item_id, recycle_folder_id=recycle_id)
                else:
                    moved = storage.move_library_item(item_id=item_id, folder_id=target_folder_id)
            elif entry_type == "folder":
                folder_id = int(payload.get("id") or 0)
                folder = storage.get_library_folder(folder_id)
                if not folder:
                    raise ValueError("Folder not found")
                if folder_id in {1, unsorted_id, recycle_id} or folder.get("parent_id") is None:
                    raise ValueError("This folder cannot be moved")
                if target_folder_id == recycle_id:
                    moved = storage.move_library_folder_to_trash(folder_id=folder_id, recycle_folder_id=recycle_id)
                else:
                    moved = storage.move_library_folder(folder_id=folder_id, parent_id=target_folder_id)
            else:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "type must be item or folder")
                return
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"moved": dict(moved or {}), **snapshot})

    def handle_reorder_library_entry(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        entry_id = int(payload.get("id") or 0)
        parent_id = int(payload.get("parent_folder_id") or 1)
        target_id = int(payload.get("target_id") or 0)
        position = str(payload.get("position") or "before")
        storage = Storage(self.configured_db_path)
        try:
            reordered = storage.reorder_library_entry(
                entry_type=entry_type,
                entry_id=entry_id,
                parent_id=parent_id,
                target_id=target_id,
                position=position,
            )
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"reordered": dict(reordered or {}), **snapshot})

    def handle_delete_library_entry(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        entry_id = int(payload.get("id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            special = ensure_library_special_folders(storage)
            unsorted_id = int(special["unsorted"].get("id") or 1)
            recycle_id = int(special["recycle"].get("id") or 1)
            if entry_type == "item":
                item = storage.get_library_item(entry_id)
                if not item:
                    raise ValueError("Library item not found")
                folder_id = int(item.get("folder_id") or 1)
                paper_id = str(item.get("paper_id") or "")
                if folder_id == recycle_id:
                    storage.delete_library_item(item_id=entry_id)
                    if paper_id and storage.count_active_library_items_for_paper(paper_id=paper_id, recycle_folder_id=recycle_id) == 0:
                        storage.add_library_item(paper_id=paper_id, folder_id=unsorted_id)
                elif folder_id == unsorted_id:
                    storage.move_library_item_to_trash(item_id=entry_id, recycle_folder_id=recycle_id)
                else:
                    storage.delete_library_item(item_id=entry_id)
                    if paper_id and storage.count_active_library_items_for_paper(paper_id=paper_id, recycle_folder_id=recycle_id) == 0:
                        storage.add_library_item(paper_id=paper_id, folder_id=unsorted_id)
            elif entry_type == "folder":
                folder = storage.get_library_folder(entry_id)
                if not folder:
                    raise ValueError("Folder not found")
                if int(folder.get("id") or 0) in {1, unsorted_id, recycle_id} or folder.get("parent_id") is None:
                    raise ValueError("This folder cannot be deleted")
                if int(folder.get("parent_id") or 0) == recycle_id:
                    paper_ids = storage.library_paper_ids_in_folder_tree(folder_id=entry_id)
                    storage.delete_library_folder(folder_id=entry_id)
                    for paper_id in paper_ids:
                        if storage.count_active_library_items_for_paper(paper_id=paper_id, recycle_folder_id=recycle_id) == 0:
                            storage.add_library_item(paper_id=paper_id, folder_id=unsorted_id)
                else:
                    storage.move_library_folder_to_trash(folder_id=entry_id, recycle_folder_id=recycle_id)
            else:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "type must be item or folder")
                return
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json(snapshot)

    def handle_recover_library_entry(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        entry_id = int(payload.get("id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            special = ensure_library_special_folders(storage)
            unsorted_id = int(special["unsorted"].get("id") or 1)
            if entry_type == "item":
                recovered = storage.recover_library_item(item_id=entry_id, fallback_folder_id=unsorted_id)
            elif entry_type == "folder":
                recovered = storage.recover_library_folder(folder_id=entry_id, fallback_parent_id=1)
            else:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "type must be item or folder")
                return
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"recovered": dict(recovered or {}), **snapshot})

    def handle_remove_paper_from_library(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            storage.remove_library_paper(paper_id=paper_id)
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json(snapshot)

    def handle_paste_library_entry(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        entry_id = int(payload.get("id") or 0)
        target_folder_id = int(payload.get("target_folder_id") or 1)
        storage = Storage(self.configured_db_path)
        try:
            pasted: dict[str, Any] | None = None
            if entry_type == "item":
                pasted = storage.copy_library_item(item_id=entry_id, folder_id=target_folder_id)
            elif entry_type == "folder":
                pasted = storage.copy_library_folder(folder_id=entry_id, parent_id=target_folder_id)
            else:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "type must be item or folder")
                return
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"pasted": dict(pasted or {}), **snapshot})

    def handle_delete_pdf(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            paper = storage.get_paper(paper_id)
            if not paper:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
                return
            deleted = delete_pdf_files_for_paper(paper)
            storage.clear_download_status(paper_id)
            paper = storage.get_paper(paper_id)
        finally:
            storage.close()
        self.send_json({"deleted": deleted, "paper": paper_to_api(paper) if paper else None})

    def handle_delete_analysis(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            paper = storage.get_paper(paper_id)
            if not paper:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
                return
            deleted = delete_analysis_file_for_paper(paper)
            storage.clear_analysis_status(paper_id)
            paper = storage.get_paper(paper_id)
        finally:
            storage.close()
        self.send_json({"deleted": deleted, "paper": paper_to_api(paper) if paper else None})

    def handle_analysis(self, query: dict[str, list[str]]) -> None:
        paper_id = first(query, "paper_id")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            paper = storage.get_paper(paper_id)
        finally:
            storage.close()
        if not paper:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
            return
        analysis_path = paper.get("analysis_path") or ""
        if not analysis_path:
            self.send_error_json(HTTPStatus.NOT_FOUND, "No analysis note for this paper")
            return
        requested = Path(analysis_path).expanduser().resolve()
        if not is_allowed_file(requested, [DEFAULT_ANALYSIS_DIR.resolve()]):
            self.send_error_json(HTTPStatus.FORBIDDEN, "Analysis file is outside allowed folder")
            return
        if not requested.exists():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Analysis file not found")
            return
        self.send_json({"paper": paper_to_api(paper), "content": requested.read_text(encoding="utf-8")})

    def handle_open_pdf(self, payload: dict[str, Any]) -> None:
        raw_path = str(payload.get("path") or "")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        requested = Path(raw_path).expanduser().resolve()
        if not is_allowed_file(requested, allowed_pdf_roots()):
            self.send_error_json(HTTPStatus.FORBIDDEN, "PDF is outside allowed folder")
            return
        if not requested.exists() or requested.suffix.lower() != ".pdf":
            self.send_error_json(HTTPStatus.NOT_FOUND, "PDF not found")
            return
        subprocess.run(["open", "-a", "Preview", str(requested)], check=True)
        self.send_json({"status": "opened", "path": str(requested)})

    def handle_quick_look(self, payload: dict[str, Any]) -> None:
        raw_path = str(payload.get("path") or "")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        requested = Path(raw_path).expanduser().resolve()
        if not is_allowed_file(requested, allowed_pdf_roots()):
            self.send_error_json(HTTPStatus.FORBIDDEN, "PDF is outside allowed folder")
            return
        if not requested.exists() or requested.suffix.lower() != ".pdf":
            self.send_error_json(HTTPStatus.NOT_FOUND, "PDF not found")
            return
        open_single_quick_look(requested)
        activate_native_app_later()
        self.send_json({"status": "opened", "path": str(requested)})

    def handle_open_url(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "A valid http(s) URL is required")
            return
        webbrowser.open(url)
        self.send_json({"status": "opened", "url": url})

    def handle_reveal_path(self, payload: dict[str, Any]) -> None:
        raw_path = str(payload.get("path") or "")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        requested = Path(raw_path).expanduser().resolve()
        target = requested
        revealed = "file"
        if requested.exists():
            subprocess.run(["open", "-R", str(requested)], check=True)
        else:
            revealed = "nearest_parent"
            target = requested.parent
            while target != target.parent and not target.exists():
                target = target.parent
            if not target.exists():
                self.send_error_json(HTTPStatus.NOT_FOUND, "No existing parent folder found")
                return
            subprocess.run(["open", str(target)], check=True)
        self.send_json({"status": "opened", "path": str(requested), "opened_path": str(target), "revealed": revealed})

    def handle_journals(self) -> None:
        raw = read_config_json()
        self.send_json({"journals": raw.get("journals", []), "history": journal_history(raw)})

    def handle_journal_logo(self, query: dict[str, list[str]]) -> None:
        name = clean_journal_name(first(query, "name") or "")
        if not name:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Journal name is required")
            return
        cache_key = name.lower()
        if cache_key not in JOURNAL_LOGO_CACHE:
            raw = read_config_json()
            configured = next((item for item in raw.get("journals", []) if item.get("name", "").lower() == cache_key), {})
            configured_logo = str(configured.get("logo_url") or "")
            if is_icon_logo_candidate(configured_logo, configured_logo):
                configured_logo = ""
            JOURNAL_LOGO_CACHE[cache_key] = resolve_journal_logo_url(name) or configured_logo
        self.send_json({"name": name, "logo_url": JOURNAL_LOGO_CACHE.get(cache_key, "")})

    def handle_paper_figure(self, query: dict[str, list[str]]) -> None:
        paper_id = first(query, "paper_id")
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            paper = storage.get_paper(paper_id)
            if not paper:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
                return
            if not paper.get("image_url"):
                enriched = enrich_image_from_landing_page(dict(paper))
                image_url = enriched.get("image_url") or ""
                if image_url:
                    storage.update_image_url(paper_id, image_url)
                    paper = storage.get_paper(paper_id) or enriched
        finally:
            storage.close()
        self.send_json({"paper": paper_to_api(paper)})

    def handle_page_proxy(self, query: dict[str, list[str]]) -> None:
        url = first(query, "url") or ""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "A valid http(s) URL is required")
            return
        response = request_with_retries(
            "GET",
            url,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"},
            timeout=20,
        )
        content_type = response.headers.get("Content-Type", "text/html; charset=utf-8")
        if "text/html" in content_type.lower():
            data = prepare_internal_page_html(response.text, response.url).encode("utf-8")
            content_type = "text/html; charset=utf-8"
        else:
            data = response.content
        self.send_bytes(data, content_type=content_type)

    def handle_add_journal(self, payload: dict[str, Any]) -> None:
        name = clean_journal_name(str(payload.get("name") or ""))
        issns = [clean_journal_name(str(value)) for value in payload.get("issns") or []]
        issns = [value for value in issns if value]
        resolved: dict[str, Any] = {}
        if not name:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Journal name is required")
            return
        if not issns:
            preset = JOURNAL_PRESETS.get(name.lower())
            if preset:
                issns = list(preset["issns"])
        preset = JOURNAL_PRESETS.get(name.lower(), {})
        openalex_source_id = preset.get("openalex_source_id")
        if not issns and not openalex_source_id:
            resolved = resolve_journal_metadata(name)
            issns = list(resolved.get("issns") or [])
            openalex_source_id = resolved.get("openalex_source_id")
        elif not resolved:
            resolved = resolve_journal_metadata(name)
            if not openalex_source_id:
                openalex_source_id = resolved.get("openalex_source_id")
        if not issns:
            self.send_error_json(
                HTTPStatus.BAD_REQUEST,
                "Could not resolve this journal automatically. Please enter at least one ISSN.",
            )
            return

        raw = read_config_json()
        journals = raw.setdefault("journals", [])
        if any(item.get("name", "").lower() == name.lower() for item in journals):
            self.send_error_json(HTTPStatus.CONFLICT, "Journal already exists")
            return
        resolved_name = clean_journal_name(str(resolved.get("name") or name))
        if resolved_name.lower() != name.lower() and any(item.get("name", "").lower() == resolved_name.lower() for item in journals):
            self.send_error_json(HTTPStatus.CONFLICT, "Journal already exists")
            return
        journals.append(
            journal_entry := {
                "name": resolved_name,
                "issns": issns,
                "openalex_source_id": openalex_source_id,
                "section_policy": str(payload.get("section_policy") or preset.get("section_policy") or "science"),
                "skip_landing_enrichment": bool(payload.get("skip_landing_enrichment", preset.get("skip_landing_enrichment", True))),
                "logo_url": preset.get("logo_url") or resolved.get("logo_url") or resolve_journal_logo_url(resolved_name),
            }
        )
        remember_journal_history(raw, journal_entry)
        write_config_json(raw)
        self.refresh_journals()
        self.send_json({"journals": journals, "history": journal_history(raw)})

    def handle_remove_journal(self, payload: dict[str, Any]) -> None:
        name = clean_journal_name(str(payload.get("name") or ""))
        if not name:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Journal name is required")
            return
        raw = read_config_json()
        journals = raw.setdefault("journals", [])
        raw["journals"] = [item for item in journals if item.get("name", "").lower() != name.lower()]
        write_config_json(raw)
        self.refresh_journals()
        self.send_json({"journals": raw["journals"], "history": journal_history(raw)})

    def handle_file(self, query: dict[str, list[str]]) -> None:
        raw_path = first(query, "path")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        requested = Path(unquote(raw_path)).expanduser().resolve()
        if not is_allowed_file(requested, [*allowed_pdf_roots(), DEFAULT_ANALYSIS_DIR.resolve()]):
            self.send_error_json(HTTPStatus.FORBIDDEN, "File is outside allowed report/PDF folders")
            return
        if not requested.exists() or not requested.is_file():
            self.send_error_json(HTTPStatus.NOT_FOUND, "File not found")
            return
        content_type = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        data = requested.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_pdf_info(self, query: dict[str, list[str]]) -> None:
        raw_path = first(query, "path")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        requested = Path(unquote(raw_path)).expanduser().resolve()
        if not is_allowed_file(requested, allowed_pdf_roots()):
            self.send_error_json(HTTPStatus.FORBIDDEN, "PDF is outside allowed folder")
            return
        if not requested.exists() or requested.suffix.lower() != ".pdf":
            self.send_error_json(HTTPStatus.NOT_FOUND, "PDF not found")
            return
        try:
            page_count = len(PdfReader(str(requested)).pages)
        except Exception:
            page_count = 0
        self.send_json({"path": str(requested), "page_count": page_count})

    def handle_pdf_page(self, query: dict[str, list[str]]) -> None:
        requested = self.validated_pdf_path(query)
        if not requested:
            return
        page_number = max(1, int(first(query, "page") or 1))
        data = single_page_pdf_bytes(requested, page_number)
        if data is None:
            self.send_error_json(HTTPStatus.NOT_FOUND, "PDF page not found")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Disposition", "inline")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_pdf_thumb(self, query: dict[str, list[str]]) -> None:
        requested = self.validated_pdf_path(query)
        if not requested:
            return
        page_number = max(1, int(first(query, "page") or 1))
        size = max(120, min(1800, int(first(query, "size") or 240)))
        data, content_type = pdf_page_thumbnail(requested, page_number, size=size)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if size <= 360:
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def validated_pdf_path(self, query: dict[str, list[str]]) -> Path | None:
        raw_path = first(query, "path")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return None
        requested = Path(unquote(raw_path)).expanduser().resolve()
        if not is_allowed_file(requested, allowed_pdf_roots()):
            self.send_error_json(HTTPStatus.FORBIDDEN, "PDF is outside allowed folder")
            return None
        if not requested.exists() or requested.suffix.lower() != ".pdf":
            self.send_error_json(HTTPStatus.NOT_FOUND, "PDF not found")
            return None
        return requested

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def read_multipart_body(self) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("multipart/form-data is required")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        message = BytesParser(policy=email_policy).parsebytes(header + body)
        fields: dict[str, str] = {}
        files: dict[str, dict[str, Any]] = {}
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            filename = part.get_filename()
            content = part.get_payload(decode=True) or b""
            if filename:
                files[name] = {"filename": filename, "content": content}
            else:
                fields[name] = content.decode(part.get_content_charset() or "utf-8", errors="replace")
        return fields, files

    def send_text(self, text: str, *, content_type: str) -> None:
        data = text.encode("utf-8")
        self.send_bytes(data, content_type=content_type)

    def send_bytes(self, data: bytes, *, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def refresh_journals(self) -> None:
        config = load_config()
        self.configured_journals = configured_source_names(config)


def configured_source_names(config: AppConfig) -> list[str]:
    names = [journal.name for journal in config.journals]
    for preprint in PREPRINT_JOURNALS:
        if preprint not in names:
            names.append(preprint)
    return names


def fetch_missing_sources_for_date(
    *,
    config: AppConfig,
    storage: Storage,
    selected: str,
    selected_date: date,
    missing_sources: list[str],
) -> None:
    total = len(missing_sources)
    completed = 0
    journal_names = [source for source in missing_sources if source not in PREPRINT_JOURNALS]

    if journal_names:
        fetch_config = config_for_journals(config, journal_names)

        def update_journal_progress(journal: str, journal_completed: int, _journal_total: int) -> None:
            update_fetch_progress(selected, journal=journal, completed=completed + journal_completed, total=total)

        run_journal_monitor(
            config=fetch_config,
            storage=storage,
            start_date=selected_date,
            end_date=selected_date,
            enrich=True,
            progress_callback=update_journal_progress,
        )
        completed += len(journal_names)

    if ARXIV_JOURNAL_NAME in missing_sources:
        update_fetch_progress(selected, journal=ARXIV_JOURNAL_NAME, completed=completed, total=total)
        fetch_one_arxiv_preprint_source(
            storage=storage,
            start_date=selected_date,
            end_date=selected_date,
            categories=ARXIV_DEFAULT_CATEGORIES,
        )
        completed += 1
        update_fetch_progress(selected, journal=ARXIV_JOURNAL_NAME, completed=completed, total=total)


def prepare_internal_page_html(html: str, base_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for meta in soup.select("meta[http-equiv]"):
        http_equiv = str(meta.get("http-equiv") or "").lower()
        if http_equiv in {"content-security-policy", "x-frame-options"}:
            meta.decompose()
    if not soup.head:
        head = soup.new_tag("head")
        if soup.html:
            soup.html.insert(0, head)
        else:
            soup.insert(0, head)
    if soup.head and not soup.head.find("base"):
        base = soup.new_tag("base", href=base_url)
        soup.head.insert(0, base)
    if soup.body:
        script = soup.new_tag("script")
        script.string = """
(() => {
  const proxied = (url) => {
    const target = new URL("/api/page-proxy", window.location.href);
    target.searchParams.set("url", url);
    return target.href;
  };
  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("a[href]");
    if (!link) return;
    const href = link.href || "";
    if (!href || href.startsWith("mailto:") || href.startsWith("tel:")) return;
    event.preventDefault();
    window.location.href = proxied(href);
  }, true);
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form || String(form.method || "get").toLowerCase() !== "get") return;
    event.preventDefault();
    const target = new URL(form.action || window.location.href, window.location.href);
    new FormData(form).forEach((value, key) => target.searchParams.append(key, value));
    window.location.href = proxied(target.href);
  }, true);
})();
"""
        soup.body.append(script)
    return str(soup)


def paper_to_api(paper: dict[str, Any]) -> dict[str, Any]:
    section = paper.get("publisher_section") or "unknown"
    merged_pdf = existing_path_or_empty(paper.get("merged_pdf_path") or "")
    analysis_path = existing_path_or_empty(paper.get("analysis_path") or "")
    return {
        "paper_id": paper.get("paper_id") or "",
        "title": paper.get("title") or "",
        "journal": paper.get("journal") or "",
        "publication_date": paper.get("publication_date") or "",
        "doi": paper.get("doi") or "",
        "url": paper.get("url") or paper.get("landing_url") or "",
        "section": section,
        "section_color": section_color(section),
        "section_badge_background": section_badge_background(section),
        "abstract": paper.get("abstract") or "",
        "abstract_source": paper.get("abstract_source") or "",
        "download_status": paper.get("download_status") or "not_attempted",
        "download_message": paper.get("download_message") or "",
        "merged_pdf_path": merged_pdf,
        "merged_pdf_url": file_url(merged_pdf),
        "analysis_status": paper.get("analysis_status") or "not_started",
        "analysis_path": analysis_path,
        "analysis_url": file_url(analysis_path),
        "authors": author_summary(paper),
        "full_authors": full_author_names(paper),
        "fields": classify_fields(paper),
        "discipline": classify_discipline(paper),
        "image_url": paper.get("image_url") or "",
        "preprint_id": preprint_identifier(paper),
        "preprint_category": preprint_primary_category(paper),
        "preprint_categories": preprint_categories(paper),
        "citation_label": citation_label(paper),
        "citation_metrics": citation_metrics(paper),
        "google_scholar_url": google_scholar_url(paper),
        "bibtex": bibtex_entry(paper),
        "nature_reference": nature_reference(paper),
    }


def library_snapshot(storage: Storage) -> dict[str, Any]:
    ensure_library_special_folders(storage)
    workspace_tabs = library_workspace_tabs(storage)
    return {
        "root_id": 1,
        "folders": [library_folder_to_api(folder) for folder in storage.list_library_folders()],
        "items": [library_item_to_api(item, item) for item in storage.list_library_items()],
        "shortcut_tabs": library_shortcut_tabs(storage),
        "workspace_tabs": workspace_tabs,
    }


def summarize_import_result(result: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "dry_run",
        "copy_mode",
        "source_root",
        "total_files",
        "paper_candidates_seen",
        "created_papers",
        "updated_papers",
        "pdf_attachments_to_import",
        "created_resources",
        "reused_existing_files",
        "resources_or_attachments_to_import",
        "skipped",
        "skipped_system_metadata",
        "mac_aliases_found",
        "missing_source_files",
        "doi_duplicates",
        "arxiv_duplicates",
        "duplicate_paper_candidates",
        "report_path",
        "copy_target_root",
        "import_batch_id",
    ]
    summary = {key: result.get(key) for key in keys if key in result}
    summary["errors"] = result.get("errors") or []
    summary["warnings"] = (result.get("warnings") or [])[:20]
    summary["warning_count"] = len(result.get("warnings") or [])
    summary["missing_sources"] = result.get("missing_sources") or []
    summary["aliases"] = result.get("aliases") or []
    summary["duplicate_dois"] = result.get("duplicate_dois") or []
    summary["duplicate_arxiv_ids"] = result.get("duplicate_arxiv_ids") or []
    return summary


def library_shortcut_tabs(storage: Storage) -> list[dict[str, Any]]:
    raw = storage.get_setting("library_shortcut_tabs", "[]")
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        values = []
    result: list[dict[str, Any]] = []
    for index in range(LIBRARY_SHORTCUT_TAB_COUNT):
        item = values[index] if isinstance(values, list) and index < len(values) and isinstance(values[index], dict) else {}
        folder_id = int(item.get("folder_id") or 0)
        folder = storage.get_library_folder(folder_id) if folder_id else None
        result.append({
            "folder_id": int(folder.get("id") or 0) if folder else 0,
            "label": str(folder.get("name") or item.get("label") or "") if folder else "",
        })
    return result


def library_workspace_tabs(storage: Storage) -> list[dict[str, Any]]:
    raw = storage.get_setting("library_workspace_tabs", "[]")
    try:
        values = json.loads(raw)
    except json.JSONDecodeError:
        values = []
    result: list[dict[str, Any]] = []
    changed = False
    for index in range(LIBRARY_WORKSPACE_TAB_COUNT):
        item = values[index] if isinstance(values, list) and index < len(values) and isinstance(values[index], dict) else {}
        label = " ".join(str(item.get("label") or f"Space {index + 1}").split()) or f"Space {index + 1}"
        root_folder_id = int(item.get("root_folder_id") or 0)
        folder = storage.get_library_folder(root_folder_id) if root_folder_id else None
        if not folder:
            folder = storage.create_library_root_folder(name=label[:80])
            root_folder_id = int(folder.get("id") or 0)
            changed = True
        legacy_paper_ids = [str(paper_id) for paper_id in item.get("paper_ids", []) if paper_id] if isinstance(item.get("paper_ids"), list) else []
        for paper_id in legacy_paper_ids:
            if storage.get_paper(paper_id):
                storage.add_library_item(paper_id=paper_id, folder_id=root_folder_id)
                changed = True
        result.append({"label": str(folder.get("name") or label)[:80], "root_folder_id": root_folder_id})
    if changed:
        storage.set_setting("library_workspace_tabs", json.dumps(workspace_tabs_to_setting(result), ensure_ascii=False))
    return result


def workspace_tabs_to_setting(tabs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index in range(LIBRARY_WORKSPACE_TAB_COUNT):
        tab = tabs[index] if index < len(tabs) and isinstance(tabs[index], dict) else {}
        label = " ".join(str(tab.get("label") or f"Space {index + 1}").split()) or f"Space {index + 1}"
        root_folder_id = int(tab.get("root_folder_id") or 0)
        result.append({"label": label[:80], "root_folder_id": root_folder_id})
    return result


def ensure_library_special_folders(storage: Storage) -> dict[str, dict[str, Any]]:
    return {
        "unsorted": storage.ensure_library_folder(parent_id=1, name=LIBRARY_UNSORTED_FOLDER_NAME),
        "recycle": storage.ensure_library_folder(parent_id=1, name=LIBRARY_RECYCLE_FOLDER_NAME),
    }


def library_folder_to_api(folder: dict[str, Any]) -> dict[str, Any]:
    name = folder.get("name") or "New Folder"
    parent_id = int(folder["parent_id"]) if folder.get("parent_id") is not None else None
    is_recycle = parent_id == 1 and name == LIBRARY_RECYCLE_FOLDER_NAME
    is_unsorted = parent_id == 1 and name == LIBRARY_UNSORTED_FOLDER_NAME
    return {
        "id": int(folder.get("id") or 0),
        "name": name,
        "parent_id": parent_id,
        "color": folder.get("color") or "",
        "sort_order": int(folder.get("sort_order") or 0),
        "original_parent_id": int(folder["original_parent_id"]) if folder.get("original_parent_id") is not None else None,
        "trashed_at": folder.get("trashed_at") or "",
        "is_recycle": is_recycle,
        "is_unsorted": is_unsorted,
        "protected": parent_id is None or is_unsorted or is_recycle,
    }


def library_item_to_api(item: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(item.get("id") or 0),
        "folder_id": int(item.get("folder_id") or 1),
        "paper_id": paper.get("paper_id") or item.get("paper_id") or "",
        "display_name": item.get("display_name") or "",
        "sort_order": int(item.get("sort_order") or 0),
        "original_folder_id": int(item["original_folder_id"]) if item.get("original_folder_id") is not None else None,
        "trashed_at": item.get("trashed_at") or "",
        "paper": paper_to_api(paper),
    }


def my_publication_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row.get("id") or 0),
        "paper_id": row.get("paper_id") or "",
        "starred": bool(row.get("starred")),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "paper": paper_to_api(row),
    }


def publication_candidate_to_api(paper: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(paper)
    if "raw_json" not in candidate:
        candidate["raw_json"] = json.dumps(candidate.get("raw") or {}, ensure_ascii=False)
    return {
        "paper_id": candidate.get("paper_id") or "",
        "doi": candidate.get("doi") or "",
        "paper": paper_to_api(candidate),
        "raw": candidate.get("raw") or parse_raw_json(candidate),
    }


def paper_from_publication_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else candidate
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else paper.get("raw")
    if isinstance(raw, dict) and ("DOI" in raw or "container-title" in raw):
        journal = clean_text(first_crossref_text(raw.get("container-title"))) or clean_text(paper.get("journal") or "Unknown Journal")
        return normalize_crossref_item(raw, journal)
    publication_date = clean_text(paper.get("publication_date") or "")
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    title = clean_text(paper.get("title") or "(Untitled)")
    journal = clean_text(paper.get("journal") or "Unknown Journal")
    return {
        "paper_id": paper.get("paper_id") or paper_id_from_publication(doi, title, journal, publication_date),
        "doi": doi,
        "title": title,
        "journal": journal,
        "publication_date": publication_date,
        "abstract": clean_text(paper.get("abstract") or ""),
        "abstract_source": paper.get("abstract_source") or ("manual" if paper.get("abstract") else "missing"),
        "url": paper.get("url") or (f"https://doi.org/{doi}" if doi else ""),
        "landing_url": paper.get("landing_url") or paper.get("url") or (f"https://doi.org/{doi}" if doi else ""),
        "pdf_url": paper.get("pdf_url") or "",
        "source": paper.get("source") or "manual",
        "type": paper.get("type") or "journal-article",
        "type_crossref": paper.get("type_crossref") or paper.get("type") or "journal-article",
        "publisher_section": paper.get("publisher_section") or "",
        "section_allowed": None,
        "raw": raw if isinstance(raw, dict) else {},
    }


def search_crossref_publications(search_text: str, *, kind: str = "auto") -> list[dict[str, Any]]:
    query = clean_text(search_text)
    detected = "doi" if looks_like_doi(query) else "title"
    search_kind = kind if kind in {"doi", "title", "author"} else detected
    if search_kind == "doi":
        doi = normalize_publication_doi(query)
        response = request_with_retries("GET", f"https://api.crossref.org/works/{quote(doi, safe='')}", timeout=20)
        item = response.json().get("message", {})
        if not item:
            return []
        return [normalize_crossref_item(item, clean_text(first_crossref_text(item.get("container-title"))) or "Unknown Journal")]

    params: dict[str, Any] = {"rows": 12, "sort": "published", "order": "desc"}
    if search_kind == "author":
        params["query.author"] = query
    else:
        params["query.title"] = query
    response = request_with_retries("GET", "https://api.crossref.org/works", params=params, timeout=20)
    items = response.json().get("message", {}).get("items", [])
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        journal = clean_text(first_crossref_text(item.get("container-title"))) or "Unknown Journal"
        paper = normalize_crossref_item(item, journal)
        key = paper.get("doi") or paper.get("paper_id")
        if key in seen:
            continue
        seen.add(key)
        results.append(paper)
    return results


def first_crossref_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return clean_text(value[0])
    return clean_text(value)


def looks_like_doi(value: str) -> bool:
    return bool(re.search(r"\b10\.\d{4,9}/\S+", value, flags=re.I))


def normalize_publication_doi(value: str) -> str:
    doi = clean_text(value)
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    match = re.search(r"10\.\d{4,9}/\S+", doi, flags=re.I)
    doi = match.group(0) if match else doi
    return doi.strip().rstrip(".,;").lower()


def paper_id_from_publication(doi: str, title: str, journal: str, publication_date: str) -> str:
    if doi:
        return "doi_" + hashlib.sha1(doi.lower().encode("utf-8")).hexdigest()[:16]
    key = "|".join([clean_text(title).lower(), clean_text(journal).lower(), clean_text(publication_date)])
    return "p_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def citation_label(paper: dict[str, Any]) -> str:
    authors = full_author_names(paper) or author_summary(paper)
    lead = author_last_name(authors[0]) if authors else "Unknown"
    if len(authors) > 1:
        lead = f"{lead} et al."
    journal = paper.get("journal") or "Unknown Journal"
    preprint_id = preprint_identifier(paper)
    if preprint_id:
        journal = f"{journal}:{preprint_id}"
    volume = paper_volume(paper)
    page = paper_page(paper)
    year = publication_year(paper)
    source = journal
    if volume:
        source = f"{source} {volume}"
    if page:
        source = f"{source}, {page}"
    return f"{lead} {source} ({year})" if year else f"{lead} {source}"


def citation_metrics(paper: dict[str, Any]) -> dict[str, Any]:
    raw = parse_raw_json(paper)
    metrics: dict[str, Any] = {"source": "", "count": None, "by_year": []}
    if "cited_by_count" in raw or raw.get("counts_by_year"):
        metrics["source"] = "OpenAlex"
        metrics["count"] = int_or_none(raw.get("cited_by_count"))
        by_year = []
        for item in raw.get("counts_by_year") or []:
            if not isinstance(item, dict):
                continue
            year = int_or_none(item.get("year"))
            count = int_or_none(item.get("cited_by_count", item.get("works_count")))
            if year is None or count is None:
                continue
            by_year.append({"year": year, "count": count})
        metrics["by_year"] = sorted(by_year, key=lambda entry: entry["year"])
        return metrics
    crossref_count = int_or_none(raw.get("is-referenced-by-count"))
    if crossref_count is not None:
        metrics["source"] = "Crossref"
        metrics["count"] = crossref_count
    return metrics


def google_scholar_url(paper: dict[str, Any]) -> str:
    query = paper.get("doi") or paper.get("title") or ""
    return f"https://scholar.google.com/scholar?q={quote(query)}" if query else ""


def bibtex_entry(paper: dict[str, Any]) -> str:
    entry_type = "misc" if (paper.get("journal") or "").lower() == ARXIV_JOURNAL_NAME.lower() else "article"
    fields = {
        "title": paper.get("title") or "",
        "author": " and ".join(full_author_names(paper)),
        "journal": paper.get("journal") or "",
        "year": publication_year(paper),
        "volume": paper_volume(paper),
        "pages": paper_page(paper),
        "doi": paper.get("doi") or "",
        "url": paper.get("url") or paper.get("landing_url") or "",
    }
    preprint_id = preprint_identifier(paper)
    if preprint_id:
        fields["eprint"] = preprint_id
        fields["archivePrefix"] = "arXiv"
        fields["primaryClass"] = preprint_primary_category(paper)
    body = "\n".join(
        f"  {key} = {{{bibtex_escape(value)}}},"
        for key, value in fields.items()
        if value
    )
    return f"@{entry_type}{{{bibtex_key(paper)},\n{body}\n}}"


def nature_reference(paper: dict[str, Any]) -> dict[str, str]:
    title = clean_text(paper.get("title") or "")
    journal = clean_text(paper.get("journal") or "")
    return {
        "authors": nature_author_text(paper),
        "title": title,
        "journal": journal,
        "volume": paper_volume(paper),
        "pages": paper_page(paper),
        "year": publication_year(paper),
        "doi": clean_text(paper.get("doi") or ""),
    }


def nature_author_text(paper: dict[str, Any]) -> str:
    authors = full_author_names(paper)
    if not authors:
        return ""
    lead = nature_author_name(authors[0])
    if len(authors) > 1:
        return f"{lead} et al"
    return lead


def nature_author_name(name: str) -> str:
    clean = clean_author_name(name)
    if not clean:
        return ""
    if "," in clean:
        family, given = [part.strip() for part in clean.split(",", 1)]
        return f"{family}, {initials_from_given_names(given)}".strip()
    parts = clean.split()
    if len(parts) == 1:
        return parts[0]
    family = parts[-1]
    given = " ".join(parts[:-1])
    return f"{family}, {initials_from_given_names(given)}".strip()


def initials_from_given_names(value: str) -> str:
    initials: list[str] = []
    for token in re.split(r"[\s.-]+", value):
        token = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ]", "", token)
        if token:
            initials.append(f"{token[0].upper()}.")
    return " ".join(initials)


def full_author_names(paper: dict[str, Any]) -> list[str]:
    raw = parse_raw_json(paper)
    return authors_from_openalex(raw) or authors_from_crossref(raw) or authors_from_arxiv(raw)


def author_last_name(name: str) -> str:
    clean = clean_author_name(name)
    if not clean:
        return "Unknown"
    if "," in clean:
        return clean.split(",", 1)[0].strip() or clean
    return clean.split()[-1]


def publication_year(paper: dict[str, Any]) -> str:
    date_text = paper.get("publication_date") or ""
    if len(date_text) >= 4 and date_text[:4].isdigit():
        return date_text[:4]
    raw = parse_raw_json(paper)
    for key in ["published-print", "published-online", "issued", "created"]:
        parts = (raw.get(key) or {}).get("date-parts") or []
        if parts and parts[0]:
            return str(parts[0][0])
    return ""


def paper_volume(paper: dict[str, Any]) -> str:
    raw = parse_raw_json(paper)
    journal_issue = raw.get("journal-issue") or {}
    journal_volume = journal_issue.get("journal-volume") if isinstance(journal_issue, dict) else {}
    value = (
        raw.get("volume")
        or (raw.get("biblio") or {}).get("volume")
        or (journal_volume or {}).get("volume")
    )
    return clean_text(str(value or ""))


def paper_page(paper: dict[str, Any]) -> str:
    raw = parse_raw_json(paper)
    biblio = raw.get("biblio") or {}
    first_page = clean_text(str(biblio.get("first_page") or biblio.get("first-page") or ""))
    last_page = clean_text(str(biblio.get("last_page") or biblio.get("last-page") or ""))
    biblio_pages = f"{first_page}-{last_page}" if first_page and last_page and first_page != last_page else first_page
    value = raw.get("page") or raw.get("article-number") or biblio_pages
    return clean_text(str(value or ""))


def bibtex_key(paper: dict[str, Any]) -> str:
    authors = full_author_names(paper) or author_summary(paper)
    lead = author_last_name(authors[0]).lower() if authors else "paper"
    year = publication_year(paper) or "undated"
    title_word = next((part.lower() for part in re.findall(r"[A-Za-z0-9]+", paper.get("title") or "") if len(part) > 3), "paper")
    key = re.sub(r"[^a-z0-9]+", "", f"{lead}{year}{title_word}")
    return key or safe_slug(paper.get("paper_id") or "paper").replace("-", "")


def bibtex_escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def count_by_journal(papers: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in papers:
        journal = paper.get("journal") or "Unknown"
        counts[journal] = counts.get(journal, 0) + 1
    return counts


def author_summary(paper: dict[str, Any]) -> list[str]:
    raw = parse_raw_json(paper)
    names = authors_from_openalex(raw) or authors_from_crossref(raw) or authors_from_arxiv(raw)
    if len(names) <= 6:
        return names
    return names[:3] + ["…"] + names[-3:]


def authors_from_openalex(raw: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in raw.get("authorships") or []:
        if not isinstance(item, dict):
            continue
        author = item.get("author") or {}
        name = clean_author_name(str(author.get("display_name") or item.get("raw_author_name") or ""))
        if name:
            names.append(name)
    return dedup_names(names)


def authors_from_crossref(raw: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for item in raw.get("author") or []:
        if not isinstance(item, dict):
            continue
        literal = clean_author_name(str(item.get("name") or ""))
        given = clean_author_name(str(item.get("given") or ""))
        family = clean_author_name(str(item.get("family") or ""))
        name = literal or clean_author_name(" ".join(part for part in [given, family] if part))
        if name:
            names.append(name)
    return dedup_names(names)


def authors_from_arxiv(raw: dict[str, Any]) -> list[str]:
    return dedup_names([clean_author_name(str(name)) for name in raw.get("authors") or [] if name])


def preprint_identifier(paper: dict[str, Any]) -> str:
    if (paper.get("journal") or "").lower() != ARXIV_JOURNAL_NAME.lower():
        return ""
    raw = parse_raw_json(paper)
    return clean_text(raw.get("arxiv_id") or raw.get("versioned_arxiv_id") or "")


def preprint_categories(paper: dict[str, Any]) -> list[str]:
    if (paper.get("journal") or "").lower() != ARXIV_JOURNAL_NAME.lower():
        return []
    raw = parse_raw_json(paper)
    return [clean_text(category) for category in raw.get("categories") or [] if clean_text(category)]


def preprint_primary_category(paper: dict[str, Any]) -> str:
    if (paper.get("journal") or "").lower() != ARXIV_JOURNAL_NAME.lower():
        return ""
    raw = parse_raw_json(paper)
    primary = clean_text(raw.get("primary_category") or "")
    return primary or (preprint_categories(paper)[0] if preprint_categories(paper) else "")


def parse_raw_json(paper: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = json.loads(paper.get("raw_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def clean_author_name(value: str) -> str:
    value = " ".join(value.strip().split())
    return "" if value.lower() in {"none", "null"} else value


def dedup_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def start_fetch_progress(selected: str, journals: list[str]) -> None:
    with FETCH_PROGRESS_LOCK:
        FETCH_PROGRESS[selected] = {
            "active": True,
            "completed": 0,
            "total": len(journals),
            "percent": 0,
            "currentJournal": "",
        }


def try_start_fetch(selected: str) -> bool:
    with FETCH_PROGRESS_LOCK:
        if selected in ACTIVE_FETCH_DATES:
            return False
        ACTIVE_FETCH_DATES.add(selected)
        return True


def finish_active_fetch(selected: str) -> None:
    with FETCH_PROGRESS_LOCK:
        ACTIVE_FETCH_DATES.discard(selected)


def is_fetch_active(selected: str) -> bool:
    with FETCH_PROGRESS_LOCK:
        return selected in ACTIVE_FETCH_DATES


def update_fetch_progress(selected: str, *, journal: str, completed: int, total: int) -> None:
    percent = round((completed / total) * 100) if total else 100
    with FETCH_PROGRESS_LOCK:
        FETCH_PROGRESS[selected] = {
            "active": True,
            "completed": completed,
            "total": total,
            "percent": percent,
            "currentJournal": journal,
        }


def finish_fetch_progress(selected: str) -> None:
    with FETCH_PROGRESS_LOCK:
        progress = FETCH_PROGRESS.get(selected)
        if not progress:
            return
        total = int(progress.get("total") or 0)
        progress.update(
            {
                "active": False,
                "completed": total,
                "percent": 100,
                "currentJournal": progress.get("currentJournal") or "",
            }
        )


def get_fetch_progress(selected: str) -> dict[str, Any] | None:
    with FETCH_PROGRESS_LOCK:
        progress = FETCH_PROGRESS.get(selected)
        return dict(progress) if progress else None


def create_library_import_job(*, folder_path: Path, copy_mode: str, dry_run: bool) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with LIBRARY_IMPORT_JOBS_LOCK:
        LIBRARY_IMPORT_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "folder_path": str(folder_path),
            "copy_mode": copy_mode,
            "dry_run": dry_run,
            "started_at": now,
            "finished_at": "",
            "current": 0,
            "total": 0,
            "percent": 0,
            "logs": [{"time": now, "level": "info", "message": "Queued loader job"}],
            "result": None,
            "inventory_path": "",
            "error": "",
        }
    return job_id


def get_library_import_job(job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    with LIBRARY_IMPORT_JOBS_LOCK:
        job = LIBRARY_IMPORT_JOBS.get(job_id)
        if not job:
            return None
        result = job.get("result")
        if isinstance(result, dict) and result.get("report_path") and "missing_sources" not in result:
            report = load_import_report_summary(result.get("report_path"))
            if report:
                job["result"] = report
        snapshot = dict(job)
        snapshot["logs"] = list(job.get("logs") or [])[-300:]
        return snapshot


def update_library_import_job(job_id: str, **updates: Any) -> None:
    with LIBRARY_IMPORT_JOBS_LOCK:
        job = LIBRARY_IMPORT_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)


def log_library_import_job(job_id: str, message: str, *, level: str = "info") -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with LIBRARY_IMPORT_JOBS_LOCK:
        job = LIBRARY_IMPORT_JOBS.get(job_id)
        if not job:
            return
        logs = job.setdefault("logs", [])
        logs.append({"time": stamp, "level": level, "message": message})
        if len(logs) > 500:
            del logs[:-500]


def library_import_progress_callback(job_id: str):
    def progress(event: dict[str, Any]) -> None:
        current = event.get("current")
        total = event.get("total")
        percent = 0
        if isinstance(current, int) and isinstance(total, int) and total > 0:
            percent = max(0, min(100, round((current / total) * 100)))
        update_library_import_job(
            job_id,
            stage=event.get("stage") or "running",
            current=current or 0,
            total=total or 0,
            percent=percent,
        )
        message = clean_text(event.get("message"))
        if message:
            log_library_import_job(job_id, message)

    return progress


def run_library_import_job(*, job_id: str, folder_path: Path, copy_mode: str, dry_run: bool, db_path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = safe_slug(folder_path.name or "library-folder", 60)
    inventory_path = ROOT / "reports" / "imports" / f"folder-inventory-{slug}-{timestamp}.json"
    report_path = ROOT / "reports" / "imports" / f"folder-import-{slug}-{'dry-run' if dry_run else 'import'}-{timestamp}.json"
    progress = library_import_progress_callback(job_id)
    update_library_import_job(job_id, status="running", stage="scan", inventory_path=str(inventory_path))
    log_library_import_job(job_id, f"Source folder: {folder_path}")
    log_library_import_job(job_id, f"Mode: {'dry-run' if dry_run else 'import'} / {copy_mode}")
    try:
        build_inventory_from_folder(folder_path, output_path=inventory_path, parse_pdfs=False, progress_callback=progress)
        log_library_import_job(job_id, f"Inventory written: {inventory_path}")
        storage = Storage(db_path)
        try:
            result = import_library_inventory(
                inventory_path,
                copy_mode=copy_mode,
                preserve_folders=True,
                dedupe_by=("doi", "arxiv", "path"),
                dry_run=dry_run,
                storage=storage,
                report_path=report_path,
                library_item_name="filename",
                progress_callback=progress,
            )
        finally:
            storage.close()
        summary = summarize_import_result(result)
        level = "error" if summary.get("errors") else "info"
        log_library_import_job(job_id, f"Report written: {summary.get('report_path') or report_path}", level=level)
        log_library_import_job(
            job_id,
            (
                f"Done: {summary.get('created_papers', 0)} created, "
                f"{summary.get('updated_papers', 0)} updated, "
                f"{summary.get('resources_or_attachments_to_import', 0)} resources/attachments, "
                f"{summary.get('reused_existing_files', 0)} reused, "
                f"{summary.get('skipped', 0)} skipped"
            ),
            level=level,
        )
        update_library_import_job(
            job_id,
            status="failed" if summary.get("errors") else "completed",
            stage="complete",
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            percent=100,
            result=summary,
        )
    except Exception as exc:
        log_library_import_job(job_id, f"Loader failed: {exc}", level="error")
        update_library_import_job(
            job_id,
            status="failed",
            stage="failed",
            error=str(exc),
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )


def load_import_report_summary(report_path: Any) -> dict[str, Any] | None:
    try:
        path = Path(str(report_path or "")).expanduser().resolve()
        imports_root = (ROOT / "reports" / "imports").resolve()
        if not is_allowed_file(path, [imports_root]) or not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return summarize_import_result(data) if isinstance(data, dict) else None
    except Exception:
        return None


def missing_fetch_journals_for_date(storage: Storage, selected: str, journals: list[str]) -> list[str]:
    if not journals:
        return []
    placeholders = ", ".join(["?"] * len(journals))
    rows = storage.conn.execute(
        f"""
        SELECT journal, status, finished_at
        FROM fetch_runs
        WHERE monitor_type = 'journal'
          AND window_start <= ?
          AND window_end >= ?
          AND status IN ('success', 'empty', 'error')
          AND journal IN ({placeholders})
        ORDER BY finished_at DESC, id DESC
        """,
        (selected, selected, *journals),
    ).fetchall()
    selected_date = date.fromisoformat(selected)
    refresh_recent = selected_date >= today_jst() - timedelta(days=RECENT_FETCH_REFRESH_DAYS)
    now = datetime.now().astimezone()
    fetched: set[str] = set()
    for row in rows:
        journal = row["journal"]
        if journal in fetched:
            continue
        status = row["status"]
        if status == "error":
            if refresh_recent and fetch_run_is_fresh(row["finished_at"], now, ERROR_FETCH_RETRY_AFTER):
                fetched.add(journal)
            continue
        if not refresh_recent:
            fetched.add(journal)
            continue
        if fetch_run_is_fresh(row["finished_at"], now, RECENT_FETCH_REFRESH_AFTER):
            fetched.add(journal)
    return [journal for journal in journals if journal not in fetched]


def fetch_run_is_fresh(finished_at: str, now: datetime, max_age: timedelta) -> bool:
    try:
        finished = datetime.fromisoformat(finished_at)
    except (TypeError, ValueError):
        return False
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=now.tzinfo)
    return now - finished.astimezone(now.tzinfo) <= max_age


def config_for_journals(config: AppConfig, journal_names: list[str]) -> AppConfig:
    wanted = set(journal_names)
    return AppConfig(
        fetch_lookback_days=config.fetch_lookback_days,
        report_days=config.report_days,
        keep_unknown_sections=config.keep_unknown_sections,
        journals=[journal for journal in config.journals if journal.name in wanted],
        section_policies=config.section_policies,
    )


def read_config_json() -> dict[str, Any]:
    return json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def write_config_json(raw: dict[str, Any]) -> None:
    DEFAULT_CONFIG_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_journal_name(value: str) -> str:
    return " ".join(value.strip().split())


def resolve_journal_metadata(name: str) -> dict[str, Any]:
    try:
        response = request_with_retries(
            "GET",
            "https://api.openalex.org/sources",
            params={"search": name, "per-page": 1},
            timeout=12,
        )
        results = response.json().get("results") or []
    except Exception:
        return {}
    if not results:
        return {}
    source = results[0]
    source_id = clean_openalex_source_id(str(source.get("id") or ""))
    issns = [clean_journal_name(str(value)) for value in (source.get("issn") or []) if value]
    issn_l = clean_journal_name(str(source.get("issn_l") or ""))
    if issn_l and issn_l not in issns:
        issns.insert(0, issn_l)
    return {
        "name": clean_journal_name(str(source.get("display_name") or name)),
        "issns": issns,
        "openalex_source_id": source_id or None,
        "logo_url": resolve_journal_logo_url(
            clean_journal_name(str(source.get("display_name") or name)),
            clean_journal_name(str(source.get("homepage_url") or "")),
        ),
    }


def resolve_journal_logo_url(name: str, homepage_url: str = "") -> str:
    if name.lower().strip() == ARXIV_JOURNAL_NAME.lower():
        return ""
    known = KNOWN_JOURNAL_LOGOS.get(name.lower().strip())
    if known:
        return known
    for url in [homepage_url, journal_homepage_guess(name)]:
        if not url:
            continue
        try:
            response = request_with_retries("GET", url, timeout=12)
            soup = BeautifulSoup(response.text, "html.parser")
        except Exception:
            continue
        logo = extract_logo_url(soup, response.url, name)
        if logo:
            return logo
    return ""


def extract_logo_url(soup: BeautifulSoup, base_url: str, name: str) -> str:
    name_key = re.sub(r"[^a-z0-9]+", "", name.lower())
    selectors = [
        ".c-header__logo source",
        ".c-header__logo img",
        "picture[class*=logo i] source",
        "picture[class*=logo i] img",
        "img[alt*=logo i]",
        "img[class*=logo i]",
        "img[id*=logo i]",
        "svg[aria-label*=logo i]",
    ]
    for selector in selectors:
        for tag in soup.select(selector):
            value = (
                tag.get("srcset")
                or tag.get("src")
                or tag.get("href")
                or tag.get("content")
                or tag.get("data-src")
                or ""
            )
            if value and "," in str(value):
                value = str(value).split(",", 1)[0].strip().split(" ", 1)[0]
            marker = " ".join(
                [
                    str(value),
                    str(tag.get("alt") or ""),
                    str(tag.get("aria-label") or ""),
                    str(tag.get("class") or ""),
                    str(tag.get("id") or ""),
                ]
            ).lower()
            if is_icon_logo_candidate(str(value), marker):
                continue
            normalized_marker = re.sub(r"[^a-z0-9]+", "", marker)
            if value and ("logo" in marker or (name_key and name_key in normalized_marker)):
                return urljoin(base_url, str(value))
    return ""


def is_icon_logo_candidate(value: str, marker: str) -> bool:
    value = value.lower()
    marker = marker.lower()
    return any(token in value or token in marker for token in ["favicon", "apple-touch-icon", "mask-icon", "browserconfig", "og:image"])


def journal_homepage_guess(name: str) -> str:
    value = name.lower().strip()
    if value in KNOWN_JOURNAL_HOME_PAGES:
        return KNOWN_JOURNAL_HOME_PAGES[value]
    slug = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    if value == "nature":
        return "https://www.nature.com/nature/"
    if value.startswith("nature "):
        return f"https://www.nature.com/{slug.replace('-', '')}/"
    if value == "science":
        return "https://www.science.org/journal/science"
    if value.startswith("physical review"):
        return f"https://journals.aps.org/{slug.replace('-', '')}/"
    return ""


KNOWN_JOURNAL_HOME_PAGES = {
    "nature": "https://www.nature.com/nature/",
    "science": "https://www.science.org/journal/science",
    "nature physics": "https://www.nature.com/nphys/",
    "nature materials": "https://www.nature.com/nmat/",
    "nature nanotechnology": "https://www.nature.com/nnano/",
    "physical review letters": "https://journals.aps.org/prl/",
    "physical review x": "https://journals.aps.org/prx/",
    "arxiv": "https://arxiv.org/",
}


KNOWN_JOURNAL_LOGOS = {
    "nature": "https://media.springernature.com/full/nature-cms/uploads/product/nature/header-86f1267ea01eccd46b530284be10585e.svg",
    "science": "https://upload.wikimedia.org/wikipedia/commons/f/f9/Science_AAAS_logo.svg",
    "nature physics": "https://media.springernature.com/full/nature-cms/uploads/product/nphys/header-de20aedc63fc84540c5d069575af4aa2.svg",
    "nature materials": "https://media.springernature.com/full/nature-cms/uploads/product/nmat/header-80d384455b83ea3c6394c62ec2bf3e14.svg",
    "nature nanotechnology": "https://media.springernature.com/full/nature-cms/uploads/product/nnano/header-71cc5bc5501b853a90ee887ea8307d67.svg",
}


def journal_history(raw: dict[str, Any]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    history: list[dict[str, Any]] = []
    for item in [*raw.get("journals", []), *raw.get("journal_history", [])]:
        name = clean_journal_name(str(item.get("name") or ""))
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        history.append(
            {
                "name": name,
                "issns": list(item.get("issns") or []),
                "openalex_source_id": item.get("openalex_source_id"),
                "logo_url": item.get("logo_url") or "",
            }
        )
    return history


def remember_journal_history(raw: dict[str, Any], journal: dict[str, Any]) -> None:
    history = [item for item in raw.get("journal_history", []) if item.get("name", "").lower() != journal.get("name", "").lower()]
    history.insert(
        0,
        {
            "name": journal.get("name") or "",
            "issns": list(journal.get("issns") or []),
            "openalex_source_id": journal.get("openalex_source_id"),
            "logo_url": journal.get("logo_url") or "",
        },
    )
    raw["journal_history"] = history[:50]


def clean_openalex_source_id(value: str) -> str:
    value = value.rstrip("/")
    if not value:
        return ""
    return value.rsplit("/", 1)[-1]


JOURNAL_PRESETS = {
    "physical review letters": {
        "issns": ["1079-7114", "0031-9007"],
        "openalex_source_id": None,
        "section_policy": "science",
        "skip_landing_enrichment": True,
    },
    "prl": {
        "issns": ["1079-7114", "0031-9007"],
        "openalex_source_id": None,
        "section_policy": "science",
        "skip_landing_enrichment": True,
    },
}


def existing_path_or_empty(path: str) -> str:
    if not path:
        return ""
    requested = Path(path).expanduser()
    return path if requested.exists() else ""


def delete_pdf_files_for_paper(paper: dict[str, Any]) -> list[str]:
    paths = []
    for key in ("merged_pdf_path", "main_pdf_path"):
        if paper.get(key):
            paths.append(str(paper[key]))
    supplements = paper.get("supplement_pdf_paths")
    if supplements:
        try:
            paths.extend(str(path) for path in json.loads(supplements) if path)
        except (TypeError, json.JSONDecodeError):
            pass
    deleted = delete_allowed_files(paths, allowed_pdf_roots())
    for root in allowed_pdf_roots():
        cleanup_empty_parents(deleted, root)
    return deleted


def delete_analysis_file_for_paper(paper: dict[str, Any]) -> list[str]:
    return delete_allowed_files([str(paper.get("analysis_path") or "")], [DEFAULT_ANALYSIS_DIR.resolve()])


def delete_allowed_files(paths: list[str], roots: list[Path]) -> list[str]:
    deleted: list[str] = []
    for raw_path in dict.fromkeys(path for path in paths if path):
        requested = Path(raw_path).expanduser().resolve()
        if not is_allowed_file(requested, roots) or not requested.exists() or not requested.is_file():
            continue
        requested.unlink()
        deleted.append(str(requested))
    return deleted


def cleanup_empty_parents(deleted_paths: list[str], root: Path) -> None:
    for raw_path in deleted_paths:
        current = Path(raw_path).parent
        while is_relative_to(current, root) and current != root:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def file_url(path: str) -> str:
    if not path:
        return ""
    return "/files?path=" + quote(path)


def single_page_pdf_bytes(path: Path, page_number: int) -> bytes | None:
    try:
        reader = PdfReader(str(path))
        if not reader.pages:
            return None
        index = max(0, min(page_number - 1, len(reader.pages) - 1))
        writer = PdfWriter()
        writer.add_page(reader.pages[index])
        buffer = BytesIO()
        writer.write(buffer)
        return buffer.getvalue()
    except Exception:
        return None


def pdf_page_thumbnail(path: Path, page_number: int, *, size: int = 240) -> tuple[bytes, str]:
    persistent_cache = size <= 360
    cache_key = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}:{page_number}:{size}".encode("utf-8")).hexdigest()
    thumb_path = PDF_THUMB_CACHE_DIR / f"{cache_key}.png"
    if persistent_cache and thumb_path.exists():
        return thumb_path.read_bytes(), "image/png"
    data = single_page_pdf_bytes(path, page_number)
    if data:
        PDF_THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        page_pdf = PDF_THUMB_CACHE_DIR / f"{cache_key}.pdf"
        output_path = thumb_path if persistent_cache else PDF_THUMB_CACHE_DIR / f"{cache_key}.tmp.png"
        page_pdf.write_bytes(data)
        try:
            subprocess.run(
                ["sips", "-s", "format", "png", "-Z", str(size), str(page_pdf), "--out", str(output_path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=20,
            )
            if output_path.exists():
                image_data = output_path.read_bytes()
                return image_data, "image/png"
        except Exception:
            pass
        finally:
            try:
                page_pdf.unlink()
            except OSError:
                pass
            if not persistent_cache:
                try:
                    output_path.unlink()
                except OSError:
                    pass
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="156" viewBox="0 0 120 156">'
        '<rect x="10" y="8" width="100" height="140" rx="7" fill="#fff" stroke="#d0d5dd"/>'
        '<rect x="24" y="30" width="72" height="5" rx="2" fill="#e5e7eb"/>'
        '<rect x="24" y="46" width="62" height="5" rx="2" fill="#e5e7eb"/>'
        f'<text x="60" y="104" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, sans-serif" font-size="28" fill="#98a2b3">{page_number}</text>'
        '</svg>'
    )
    return svg.encode("utf-8"), "image/svg+xml"


def read_text_file(path: str) -> str:
    if not path:
        return ""
    requested = Path(path).expanduser().resolve()
    if not is_allowed_file(requested, [DEFAULT_ANALYSIS_DIR.resolve()]) or not requested.exists():
        return ""
    return requested.read_text(encoding="utf-8")


def is_allowed_file(path: Path, roots: list[Path]) -> bool:
    return any(is_relative_to(path, root) for root in roots)


def allowed_pdf_roots() -> list[Path]:
    return [DEFAULT_PDF_DIR.resolve(), DEFAULT_LIBRARY_IMPORT_DIR.resolve()]


PHYSICAL_INCLUDE_KEYWORDS = [
    "physics",
    "physical",
    "quantum",
    "photon",
    "photonic",
    "optical",
    "optics",
    "laser",
    "metasurface",
    "refractive",
    "radiative",
    "polariton",
    "plasmon",
    "crystal",
    "lattice",
    "material",
    "materials",
    "chemical",
    "chemistry",
    "molecule",
    "molecular",
    "ligand",
    "polymer",
    "perovskite",
    "semiconductor",
    "superconduct",
    "junction",
    "electron",
    "electronic",
    "spin",
    "valley",
    "topological",
    "phonon",
    "exciton",
    "magnetic",
    "conductance",
    "conductivity",
    "dielectric",
    "energy",
    "solar",
    "battery",
    "electrode",
    "catalyst",
    "catalysis",
    "nanophotonic",
    "nanostructure",
    "device",
    "thin film",
    "lithography",
    "spectroscopy",
    "harmonic",
    "resonator",
    "frequency comb",
]


NON_PHYSICAL_KEYWORDS = [
    "song",
    "music",
    "vocal",
    "brain",
    "neural",
    "synaptic",
    "hippocamp",
    "autism",
    "cancer",
    "cellular",
    "lipid",
    "gene",
    "genetic",
    "genome",
    "rna",
    "dna",
    "protein",
    "microglia",
    "stroke",
    "intestine",
    "fish",
    "cichlid",
    "sleep",
    "depression",
    "diabetes",
    "wildfire",
    "mountain",
    "ecosystem",
    "food",
    "fertilizer",
    "political",
    "government",
]


NON_PHYSICAL_TITLE_KEYWORDS = [
    "song",
    "synaptic",
    "brain",
    "neural",
    "autism",
    "cancer",
    "cellular",
    "lipid",
    "protein",
    "gene",
    "rna",
    "dna",
    "intestine",
    "fish",
    "sleep",
    "obesity",
    "antibiotic",
    "antimicrobial",
    "wildfire",
    "precipitation",
    "water storage",
]


FIELD_KEYWORDS = {
    "physics": [
        "physics",
        "quantum",
        "photon",
        "photonic",
        "optical",
        "optics",
        "laser",
        "polariton",
        "plasmon",
        "superconduct",
        "electron",
        "spin",
        "valley",
        "topological",
        "phonon",
        "magnon",
        "magnetic",
        "josephson",
        "frequency comb",
        "spectroscopy",
    ],
    "quantum_information": [
        "quantum information",
        "quantum computing",
        "quantum computer",
        "quantum processor",
        "quantum communication",
        "quantum network",
        "quantum internet",
        "quantum error",
        "quantum algorithm",
        "quantum simulation",
        "quantum cryptography",
        "quantum key distribution",
        "qubit",
        "qubits",
        "entanglement",
    ],
    "materials": [
        "material",
        "materials",
        "crystal",
        "lattice",
        "thin film",
        "semiconductor",
        "perovskite",
        "metasurface",
        "nanostructure",
        "nanophotonic",
        "polymer",
        "device",
        "electrode",
        "dielectric",
        "alloy",
    ],
    "chemistry": [
        "chemical",
        "chemistry",
        "molecule",
        "molecular",
        "ligand",
        "polymer",
        "catalyst",
        "catalysis",
        "reaction",
        "synthesis",
        "electrochemical",
        "battery",
    ],
}


JOURNAL_FIELD_HINTS = {
    "nature physics": ["physics"],
    "physical review letters": ["physics"],
    "nature photonics": ["physics"],
    "nature materials": ["materials"],
    "nature chemistry": ["chemistry"],
}


def classify_fields(paper: dict[str, Any]) -> list[str]:
    journal = (paper.get("journal") or "").lower()
    hinted = JOURNAL_FIELD_HINTS.get(journal)
    if hinted:
        return hinted
    title = (paper.get("title") or "").lower()
    if any(keyword in title for keyword in NON_PHYSICAL_TITLE_KEYWORDS):
        return ["other"]
    text = f"{title}\n{paper.get('abstract') or ''}\n{paper.get('publisher_section') or ''}".lower()
    if sum(1 for keyword in NON_PHYSICAL_KEYWORDS if keyword in text) >= 2:
        return ["other"]
    fields = [
        field
        for field, keywords in FIELD_KEYWORDS.items()
        if any(keyword in text for keyword in keywords)
    ]
    if journal == ARXIV_JOURNAL_NAME.lower():
        categories = preprint_categories(paper)
        if any(category.startswith("cond-mat") for category in categories):
            fields.insert(0, "physics")
        if "cond-mat.mtrl-sci" in categories:
            fields.append("materials")
        fields = list(dict.fromkeys(fields))
    return fields or ["other"]


def classify_discipline(paper: dict[str, Any]) -> str:
    return "other" if classify_fields(paper) == ["other"] else "physical"


def first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key) or []
    return values[0] if values else None


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Journal Monitor</title>
  <style>
    :root {
      --ink: #18212f;
      --muted: #667085;
      --line: #d9dee8;
      --panel: #ffffff;
      --paper: #f7f8fb;
      --accent: #0f6b6e;
      --accent-2: #a6423a;
      --warn: #a15c00;
      --ok: #1d7044;
      --shadow: 0 12px 28px rgba(17, 24, 39, 0.08);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
    }
    * { box-sizing: border-box; }
    body { margin: 0; height: 100vh; overflow: hidden; -webkit-user-select: text; user-select: text; }
    button, input, select { font: inherit; }
    button, input, select, textarea, .paper, .calendar, .sidebar, .library-view, .library-detail, .analysis-body {
      -webkit-user-select: text;
      user-select: text;
    }
    a { color: var(--accent); text-decoration: none; }
    a:hover { text-decoration: underline; }
    .app {
      --sidebar-width: 340px;
      display: grid;
      grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
      height: 100vh;
      overflow: hidden;
      position: relative;
    }
    .app::before {
      content: "";
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: 38px;
      background: #d9e8ff;
      z-index: 60;
      pointer-events: none;
    }
    .app.sidebar-collapsed { --sidebar-width: 0px; grid-template-columns: 0 minmax(0, 1fr); }
    .app.sidebar-collapsed .sidebar { padding: 0; border-right: 0; overflow: hidden; }
    .app.library-mode { --sidebar-width: 0px; grid-template-columns: minmax(0, 1fr); }
    .app.library-mode .sidebar,
    .app.library-mode .sidebar-edge {
      display: none;
    }
    .sidebar {
      border-right: 1px solid var(--line);
      background: #fff;
      padding: 22px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      height: 100vh;
      overflow-y: auto;
    }
    .brand {
      display: flex;
      align-items: baseline;
      justify-content: flex-start;
      gap: 12px;
      min-height: 32px;
    }
    .brand h1 { font-size: 22px; margin: 0; letter-spacing: 0; }
    .today { color: var(--muted); font-size: 13px; white-space: nowrap; }
    .sidebar-edge {
      position: fixed;
      left: var(--sidebar-width);
      top: 50%;
      transform: translate(-50%, -50%);
      z-index: 30;
      width: 14px;
      min-height: 46px;
      border: 0;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.62);
      color: #98a2b3;
      cursor: pointer;
      box-shadow: none;
      font-size: 10px;
      line-height: 1;
      opacity: 0.6;
    }
    .sidebar-edge:hover {
      color: var(--accent);
      background: #fff;
      box-shadow: 0 4px 12px rgba(17, 24, 39, 0.08);
      opacity: 1;
    }
    .app.sidebar-collapsed .sidebar-edge { left: 8px; }
    .monthbar { display: grid; grid-template-columns: 38px 1fr 38px; gap: 8px; align-items: center; }
    .monthbar strong { text-align: center; font-size: 16px; }
    .iconbtn, .smallbtn {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 7px;
      min-height: 36px;
      cursor: pointer;
    }
    .iconbtn:hover, .smallbtn:hover { border-color: var(--accent); color: var(--accent); }
    .calendar { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 6px; }
    .weekday { text-align: center; color: var(--muted); font-size: 12px; padding: 4px 0; }
    .day {
      position: relative;
      min-height: 48px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 7px;
      padding: 6px;
      text-align: left;
      cursor: pointer;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: 2px;
    }
    .day:hover { border-color: var(--accent); }
    .day.out { color: #a7adba; background: #f0f2f6; cursor: default; }
    .day.active { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
    .day.fetching { border-color: rgba(23, 100, 59, 0.42); background: #f7fbf8; }
    .day.no-match::after {
      content: "";
      position: absolute;
      left: 8px;
      right: 8px;
      top: 50%;
      border-top: 2px solid rgba(192, 57, 43, 0.86);
      transform: rotate(-35deg);
      transform-origin: center;
      pointer-events: none;
    }
    .daynum { font-weight: 650; font-size: 14px; }
    .count { color: var(--muted); font-size: 11px; }
    .fetching-dot {
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
      animation: fetchingPulse 1s ease-in-out infinite;
    }
    .fetch-progress {
      display: grid;
      gap: 10px;
      text-align: left;
    }
    .fetch-progress-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
    }
    .fetch-progress strong { color: var(--ink); font-weight: 600; }
    .fetch-progress-track {
      height: 8px;
      border-radius: 999px;
      background: rgba(23, 100, 59, 0.12);
      overflow: hidden;
    }
    .fetch-progress-bar {
      height: 100%;
      border-radius: inherit;
      background: var(--accent);
      transition: width 180ms ease;
    }
    .arxiv-countdown {
      border: 1px solid rgba(15, 107, 110, 0.24);
      border-radius: 7px;
      background: #f5fbfa;
      padding: 12px 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      color: var(--muted);
    }
    .arxiv-countdown-main { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
    .arxiv-countdown-main span { font-size: 13px; }
    .arxiv-countdown-main strong { color: var(--accent); font-size: 20px; font-weight: 760; white-space: nowrap; }
    .arxiv-countdown-detail { font-size: 12px; text-align: right; }
    @keyframes fetchingPulse {
      0%, 100% { opacity: 0.35; transform: scale(0.86); }
      50% { opacity: 1; transform: scale(1); }
    }
    .filters { display: flex; flex-direction: column; gap: 8px; }
    .filter-title { font-size: 13px; color: var(--muted); }
    .journal-toggle, .preprint-category-toggle {
      display: grid;
      grid-template-columns: 18px 1fr auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px 10px;
      background: #fff;
    }
    .preprint-filter-row { display: grid; grid-template-columns: minmax(0, 1fr) 32px; gap: 6px; align-items: stretch; }
    .preprint-filter-row .journal-toggle { min-width: 0; }
    .preprint-collapse-toggle {
      display: grid;
      place-items: center;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--muted);
      cursor: pointer;
      font-size: 12px;
      line-height: 1;
    }
    .preprint-collapse-toggle:hover { color: var(--ink); border-color: rgba(15, 107, 110, 0.34); }
    .preprint-category-list { display: flex; flex-direction: column; gap: 6px; padding-left: 14px; }
    .preprint-category-list[hidden] { display: none; }
    .preprint-category-toggle { padding: 7px 8px; }
    .journal-toggle input, .preprint-category-toggle input { width: 16px; height: 16px; }
    .journal-toggle span, .preprint-category-toggle span { font-size: 14px; min-width: 0; }
    .preprint-category-toggle span { font-size: 12px; line-height: 1.2; }
    .journal-toggle b, .preprint-category-toggle b { color: var(--muted); font-size: 12px; font-weight: 500; }
    .journal-setting-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px 10px;
      background: #fff;
    }
    .journal-setting-name { font-size: 14px; min-width: 0; }
    .main { padding: 50px 30px 24px; min-width: 0; height: 100vh; overflow: hidden; }
    .app.library-mode .main { padding-top: 52px; }
    .internal-browser {
      position: fixed;
      inset: 0;
      z-index: 80;
      display: none;
      grid-template-rows: auto minmax(0, 1fr);
      background: #fff;
    }
    .internal-browser.open { display: grid; }
    .internal-browser-bar {
      display: grid;
      grid-template-columns: auto auto minmax(0, 1fr);
      gap: 12px;
      align-items: center;
      min-height: 58px;
      border-bottom: 1px solid var(--line);
      padding: 10px 14px;
      background: #fff;
    }
    .internal-browser-title { min-width: 0; color: var(--muted); font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .internal-browser-title strong { display: block; color: var(--ink); font-size: 14px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .internal-browser iframe { width: 100%; height: 100%; border: 0; background: #fff; }
    .library-quicklook {
      position: fixed;
      top: 80px;
      left: 40px;
      z-index: 90;
      display: none;
      width: 760px;
      height: 640px;
      border: 1px solid rgba(16, 24, 40, 0.18);
      border-radius: 12px;
      overflow: hidden;
      background: #fff;
      box-shadow: 0 24px 70px rgba(15, 23, 42, 0.28);
      pointer-events: auto;
    }
    .library-quicklook.open { display: grid; grid-template-rows: auto minmax(0, 1fr); }
    .library-quicklook-title {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      min-height: 34px;
      padding: 8px 12px;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
      cursor: move;
      user-select: none;
      background: rgba(255, 255, 255, 0.92);
    }
    .library-quicklook-title span {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .library-quicklook-title button {
      width: 24px;
      min-height: 24px;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
    }
    .library-quicklook-title button:hover { background: #eef2f7; color: var(--ink); }
    .library-quicklook-body {
      display: grid;
      grid-template-columns: 112px minmax(0, 1fr);
      min-height: 0;
      background: #eef1f5;
    }
    .library-quicklook-thumbs {
      min-height: 0;
      overflow-y: auto;
      border-right: 1px solid var(--line);
      padding: 10px 8px;
      background: #f8fafc;
    }
    .library-page-thumb {
      width: 76px;
      min-height: 98px;
      display: grid;
      grid-template-rows: minmax(0, 1fr) auto;
      gap: 5px;
      margin: 0 auto 10px;
      border: 1px solid transparent;
      border-radius: 7px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      padding: 5px;
      text-align: center;
      font-size: 11px;
    }
    .library-page-thumb:hover { background: #eef2f7; }
    .library-page-thumb.active { border-color: var(--accent); background: #e8f3f4; color: var(--ink); }
    .library-page-thumb-preview {
      display: block;
      width: 100%;
      aspect-ratio: 0.76;
      position: relative;
      overflow: hidden;
      border: 1px solid #d0d5dd;
      border-radius: 4px;
      background: #fff;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
    }
    .library-page-thumb-preview img {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: cover;
      object-position: top center;
      background: #fff;
      pointer-events: none;
    }
    .library-page-thumb-placeholder {
      width: 100%;
      height: 100%;
      display: grid;
      align-content: start;
      gap: 5px;
      padding: 13px 10px;
      color: #98a2b3;
      font-size: 10px;
      background: linear-gradient(180deg, #fff 0%, #fff 76%, #f3f4f6 76%, #f3f4f6 100%);
    }
    .library-page-thumb-placeholder::before,
    .library-page-thumb-placeholder::after {
      content: "";
      height: 4px;
      border-radius: 999px;
      background: #e5e7eb;
    }
    .library-page-thumb-placeholder::after {
      width: 72%;
    }
    .library-quicklook-pages {
      min-width: 0;
      min-height: 0;
      overflow: auto;
      display: grid;
      padding: 18px;
      background: #68717c;
    }
    .library-pdf-frame {
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
      border-radius: 4px;
      background: #fff;
      box-shadow: 0 8px 22px rgba(15, 23, 42, 0.25);
    }
    .library-quicklook-placeholder {
      min-height: 100%;
      width: 100%;
      display: grid;
      place-items: center;
      padding: 18px;
      color: #eef2f7;
      text-align: center;
    }
    .library-quicklook-placeholder-card {
      width: 132px;
      min-height: 112px;
      display: grid;
      place-items: center;
      gap: 8px;
      border-radius: 10px;
      border: 1px solid rgba(255, 255, 255, 0.28);
      background: rgba(255, 255, 255, 0.12);
      box-shadow: 0 12px 30px rgba(15, 23, 42, 0.22);
      padding: 14px;
    }
    .library-quicklook-placeholder-icon { font-size: 42px; line-height: 1; }
    .library-quicklook-placeholder-title { max-width: 108px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
    .library-quicklook-resize {
      position: absolute;
      right: 0;
      bottom: 0;
      width: 18px;
      height: 18px;
      cursor: nwse-resize;
      background: linear-gradient(135deg, transparent 0 45%, rgba(102, 112, 133, 0.5) 46% 52%, transparent 53% 100%);
    }
    .workspace {
      --note-width: 460px;
      display: grid;
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas: "report";
      height: 100%;
      min-height: 0;
      transition: grid-template-columns 160ms ease;
    }
    .workspace.note-open {
      grid-template-columns: minmax(180px, 1fr) 14px 7px minmax(260px, var(--note-width));
      grid-template-areas: "report toggle resize note";
    }
    .workspace.note-open.report-collapsed {
      grid-template-columns: 14px minmax(260px, 1fr);
      grid-template-areas: "toggle note";
    }
    .report-column {
      grid-area: report;
      min-width: 0;
      height: 100%;
      min-height: 0;
      overflow: hidden;
      padding-right: 18px;
      display: grid;
      grid-template-rows: auto auto auto auto minmax(0, 1fr);
    }
    .app.library-mode .report-column {
      padding-right: 0;
    }
    .workspace.report-collapsed .report-column { display: none; }
    .workspace-toggle, .workspace-resizer { display: none; }
    .workspace.note-open .workspace-toggle {
      grid-area: toggle;
      position: relative;
      z-index: 3;
      display: flex;
      align-items: center;
      justify-content: center;
      align-self: stretch;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: #98a2b3;
      cursor: pointer;
      min-width: 14px;
      padding: 0;
      box-shadow: none;
      font-size: 10px;
      opacity: 0.55;
    }
    .workspace.note-open .workspace-toggle:hover {
      background: rgba(255, 255, 255, 0.8);
      color: var(--accent);
      opacity: 1;
    }
    .workspace.note-open .workspace-resizer {
      grid-area: resize;
      position: relative;
      z-index: 2;
      display: block;
      align-self: stretch;
      cursor: col-resize;
      border-left: 1px solid transparent;
      border-right: 1px solid transparent;
      background: linear-gradient(to right, transparent 0 2px, var(--line) 2px 3px, transparent 3px);
    }
    .workspace.note-open.report-collapsed .workspace-resizer { display: none; }
    body.resizing { cursor: col-resize; user-select: none; }
    .toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      margin-bottom: 18px;
      min-height: 34px;
      flex-wrap: wrap;
    }
    .toolbar h2 { display: none; }
    .app.library-mode .toolbar {
      min-height: 0;
      margin-bottom: 8px;
    }
    .view-switcher {
      display: flex;
      align-items: flex-end;
      gap: 2px;
      min-width: 0;
      height: 32px;
      position: fixed;
      top: 6px;
      left: 86px;
      z-index: 70;
    }
    .view-switcher.hidden { display: none; }
    .sidebar-view-switcher {
      display: none;
      align-items: flex-end;
      gap: 2px;
      min-width: 0;
      height: 32px;
      position: fixed;
      top: 6px;
      left: 86px;
      z-index: 70;
    }
    .sidebar-view-switcher.open { display: flex; }
    .view-switch {
      min-height: 32px;
      border: 0;
      border-radius: 14px 14px 0 0;
      background: transparent;
      color: #475467;
      cursor: pointer;
      font-size: 13px;
      font-weight: 560;
      letter-spacing: 0;
      line-height: 1;
      padding: 0 22px;
      position: relative;
      text-align: center;
      white-space: nowrap;
    }
    .view-switch:hover {
      background: rgba(255, 255, 255, .38);
      color: var(--ink);
    }
    .view-switch.active {
      color: var(--ink);
      background: var(--paper);
      box-shadow: none;
      position: relative;
      z-index: 1;
    }
    .view-switch.active::before,
    .view-switch.active::after {
      content: "";
      position: absolute;
      bottom: 0;
      width: 14px;
      height: 14px;
      pointer-events: none;
    }
    .view-switch.active::before {
      left: -14px;
      background: radial-gradient(circle at 0 0, transparent 14px, var(--paper) 15px);
    }
    .view-switch.active::after {
      right: -14px;
      background: radial-gradient(circle at 100% 0, transparent 14px, var(--paper) 15px);
    }
    .toolbar-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .toolbar-actions.hidden { display: none; }
    .toolbar-import {
      display: none;
      align-items: center;
      gap: 6px;
      flex-wrap: nowrap;
      min-width: 0;
    }
    .toolbar-import.open { display: flex; }
    .toolbar-import input {
      width: clamp(180px, 20vw, 300px);
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 10px;
      background: #fff;
    }
    .toolbar-import select {
      width: 64px;
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
    }
    .toolbar-import .smallbtn {
      min-height: 36px;
      padding: 0 8px;
      white-space: nowrap;
    }
    .toolbar-import-status {
      display: none;
      flex-basis: 100%;
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }
    .toolbar-import-status.open { display: block; }
    .toolbar-import-status.err { color: #b42318; }
    .toolbar-import-status.ok { color: #067647; }
    .toolbar-toggle {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      padding: 0 10px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      font-size: 13px;
      color: var(--ink);
    }
    .toolbar-toggle input { width: 15px; height: 15px; }
    .search {
      width: min(360px, 70vw);
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 12px;
      background: #fff;
    }
    .summary { color: var(--muted); font-size: 14px; margin: -8px 0 18px; }
    .summary:empty { display: none; }
    .report-tabs {
      display: none;
      gap: 8px;
      align-items: stretch;
      overflow-x: auto;
      padding-bottom: 8px;
      margin: -8px 0 14px;
    }
    .report-tabs.open { display: flex; }
    .journal-tab {
      flex: 0 0 auto;
      min-width: 132px;
      max-width: 260px;
      min-height: 46px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      cursor: pointer;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 8px 10px;
      text-align: left;
    }
    .journal-tab.active { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
    .journal-tab img { max-width: 180px; max-height: 24px; object-fit: contain; display: block; }
    .journal-tab-label { min-width: 0; font-size: 14px; font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .journal-tab-count { color: var(--muted); font-size: 12px; font-weight: 500; }
    .library-controls {
      display: none;
      gap: 6px;
      align-items: center;
      flex-wrap: wrap;
      margin: -8px 0 18px;
    }
    .library-controls.open { display: flex; }
    .library-controls input, .library-controls select {
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 10px;
      background: #fff;
    }
    .library-search-tools {
      margin-left: auto;
      display: none;
      align-items: center;
      gap: 6px;
      min-width: min(360px, 100%);
    }
    .library-search-tools.open { display: flex; }
    .library-search-wrap {
      position: relative;
      flex: 1 1 220px;
      min-width: 160px;
    }
    .library-search-wrap::before {
      content: "";
      position: absolute;
      left: 10px;
      top: 50%;
      width: 11px;
      height: 11px;
      border: 1.6px solid #667085;
      border-radius: 999px;
      transform: translateY(-58%);
      pointer-events: none;
    }
    .library-search-wrap::after {
      content: "";
      position: absolute;
      left: 20px;
      top: 22px;
      width: 7px;
      height: 1.6px;
      border-radius: 999px;
      background: #667085;
      transform: rotate(42deg);
      transform-origin: left center;
      pointer-events: none;
    }
    .library-search-wrap input {
      width: 100%;
      padding-left: 30px;
      padding-right: 34px;
    }
    .library-search-clear {
      position: absolute;
      right: 5px;
      top: 50%;
      transform: translateY(-50%);
      width: 24px;
      min-height: 24px;
      border: 0;
      border-radius: 999px;
      background: transparent;
      color: #667085;
      cursor: pointer;
      font-size: 16px;
      line-height: 1;
      display: none;
    }
    .library-search-clear.open { display: grid; place-items: center; }
    .library-search-clear:hover { background: #eef2f7; color: var(--ink); }
    .library-search-count {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }
    .library-tab {
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 0 13px;
      cursor: pointer;
      font-weight: 650;
    }
    #libraryTab,
    #myPublicationsTab {
      flex: 0 0 auto;
    }
    #libraryShortcutTabs {
      display: grid;
      grid-template-columns: repeat(5, 92px) repeat(3, 86px);
      grid-template-rows: 34px;
      align-items: center;
      column-gap: 6px;
      flex: 0 0 auto;
      min-width: 0;
    }
    .library-tab.active {
      border-color: var(--accent);
      color: var(--accent-strong);
      box-shadow: inset 0 0 0 1px var(--accent);
    }
    .library-tab.shortcut-tab {
      width: 100%;
      background: #fff8d7;
      border-color: #eadc99;
      min-height: 34px;
      padding: 0 7px;
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .shortcut-tab-0 { grid-column: 1; grid-row: 1; }
    .shortcut-tab-1 { grid-column: 2; grid-row: 1; }
    .shortcut-tab-2 { grid-column: 3; grid-row: 1; }
    .shortcut-tab-3 { grid-column: 4; grid-row: 1; }
    .shortcut-tab-4 { grid-column: 5; grid-row: 1; }
    .library-tab.workspace-tab {
      width: 100%;
      background: #eaf8df;
      border-color: #c4e3b1;
      min-height: 34px;
      padding: 0 7px;
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .workspace-tab-0 { grid-column: 6; grid-row: 1; }
    .workspace-tab-1 { grid-column: 7; grid-row: 1; }
    .workspace-tab-2 { grid-column: 8; grid-row: 1; }
    .loader-tool-tab {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
      min-height: 26px;
      border: 0;
      border-radius: 999px;
      background: #263238;
      color: #fff;
      padding: 0 13px;
      font-size: 11px;
      font-weight: 750;
      box-shadow: 0 1px 0 rgba(0, 0, 0, .18);
      cursor: pointer;
    }
    .loader-tool-tab.active {
      background: var(--accent);
      color: #fff;
      box-shadow: 0 0 0 2px rgba(56, 102, 255, .18);
    }
    .top-tools {
      position: fixed;
      top: 46px;
      right: 30px;
      z-index: 70;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .top-tools.hidden { display: none; }
    .top-tools-label {
      color: #475467;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: .06em;
      text-transform: uppercase;
      white-space: nowrap;
    }
    .workspace-tools {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
      margin-bottom: 10px;
      flex-wrap: wrap;
      grid-column: 1 / -1;
    }
    .workspace-tools input {
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 10px;
      background: #fff;
    }
    .library-tab.drag-over {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 1px var(--accent);
    }
    .my-publications-tools {
      display: none;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }
    .my-publications-tools.open { display: flex; }
    .my-publications-panel {
      min-width: 0;
      min-height: 0;
      height: 100%;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .my-publications-search {
      border-bottom: 1px solid var(--line);
      padding: 10px 12px;
      background: #fbfcfe;
    }
    .publication-search-status { color: var(--muted); font-size: 12px; }
    .publication-search-results {
      display: grid;
      gap: 8px;
      margin-top: 8px;
      max-height: 190px;
      overflow-y: auto;
    }
    .publication-search-result {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 8px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
    }
    .publication-search-result strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink); }
    .publication-search-result span { display: block; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .my-publications-table-wrap {
      min-height: 0;
      overflow: auto;
    }
    .my-publications-table {
      width: var(--my-publications-table-width, 100%);
      min-width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 13px;
    }
    .my-publications-table th {
      position: sticky;
      top: 0;
      z-index: 1;
      background: #fff;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      text-align: left;
      padding: 9px 8px;
      border-right: 1px solid #edf0f5;
    }
    .my-publications-table td {
      border-bottom: 1px solid #edf0f5;
      border-right: 1px solid #edf0f5;
      padding: 9px 8px;
      color: #344054;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .my-publications-table th:last-child,
    .my-publications-table td:last-child { border-right: 0; }
    .my-publications-head-cell {
      position: relative;
      min-height: 16px;
    }
    .my-publications-col-resizer {
      position: absolute;
      top: -9px;
      right: -8px;
      bottom: -9px;
      width: 9px;
      cursor: col-resize;
      z-index: 2;
    }
    .my-publications-col-resizer::after {
      content: "";
      position: absolute;
      top: 0;
      bottom: 0;
      left: 4px;
      width: 1px;
      background: transparent;
    }
    .my-publications-col-resizer:hover::after { background: var(--accent); }
    .my-publications-row {
      cursor: default;
    }
    .my-publications-row:hover { background: #f8fafc; }
    .my-publications-row.active { background: #e8f3f4; }
    .my-publications-id em { font-style: italic; }
    .my-publications-id strong { font-weight: 750; color: var(--ink); }
    .star-button {
      width: 28px;
      height: 28px;
      border: 0;
      background: transparent;
      color: #a0a7b4;
      cursor: pointer;
      font-size: 18px;
      line-height: 1;
    }
    .star-button.active { color: #d97706; }
    .workspace-status {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #fbfcfe;
      color: var(--muted);
      font-size: 12px;
    }
    .loader-panel {
      height: 100%;
      min-height: 0;
      display: grid;
      grid-template-rows: auto auto auto minmax(0, 1fr);
      gap: 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      padding: 14px;
      overflow: hidden;
    }
    .loader-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      padding-bottom: 10px;
    }
    .loader-head strong { font-size: 16px; color: var(--ink); }
    .loader-head-main {
      display: flex;
      align-items: baseline;
      gap: 12px;
      min-width: 0;
    }
    .loader-description {
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .loader-form {
      display: grid;
      grid-template-columns: minmax(280px, 1fr) 90px auto auto auto;
      gap: 8px;
      align-items: center;
    }
    .loader-form input,
    .loader-form select {
      min-height: 36px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 10px;
      background: #fff;
    }
    .loader-progress {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }
    .loader-progress-track {
      grid-column: 1 / -1;
      height: 8px;
      border-radius: 999px;
      background: #edf1f5;
      overflow: hidden;
    }
    .loader-progress-bar {
      height: 100%;
      width: 0%;
      background: var(--accent);
      transition: width 0.2s ease;
    }
    .loader-main {
      min-height: 0;
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, 360px);
      gap: 12px;
    }
    .loader-console {
      min-height: 0;
      overflow: auto;
      border: 1px solid #1f2937;
      border-radius: 8px;
      background: #111827;
      color: #e5e7eb;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.45;
      padding: 12px;
      white-space: pre-wrap;
      user-select: text;
    }
    .loader-line.error { color: #fecaca; }
    .loader-line.warn { color: #fde68a; }
    .loader-result {
      color: var(--muted);
      font-size: 12px;
    }
    .loader-side {
      min-height: 0;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      padding: 12px;
      color: #344054;
      font-size: 12px;
    }
    .loader-side h3 {
      margin: 0 0 8px;
      color: var(--ink);
      font-size: 14px;
      letter-spacing: 0;
    }
    .loader-metric {
      display: grid;
      grid-template-columns: 92px minmax(0, 1fr);
      gap: 8px;
      padding: 6px 0;
      border-bottom: 1px solid #edf0f5;
    }
    .loader-metric strong { color: var(--ink); }
    .loader-missing-tools {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      margin-top: 10px;
    }
    .loader-missing-tools select {
      min-width: 0;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      padding: 0 8px;
    }
    .loader-missing-path {
      margin-top: 8px;
      padding: 8px;
      border-radius: 7px;
      background: #fff;
      border: 1px solid var(--line);
      word-break: break-all;
      user-select: text;
      color: var(--muted);
    }
    .library-shell {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
      gap: 12px;
      align-items: stretch;
      height: 100%;
      max-height: 100%;
      min-height: 0;
      overflow: hidden;
      outline: none;
    }
    .library-columns {
      min-width: 0;
      min-height: 0;
      height: 100%;
      max-height: 100%;
      align-self: stretch;
      flex: 1 1 auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      display: flex;
      align-items: stretch;
      overflow-x: auto;
      overflow-y: hidden;
    }
    .library-search-results {
      min-width: 0;
      min-height: 0;
      height: 100%;
      max-height: 100%;
      align-self: stretch;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .library-search-results-body {
      min-height: 0;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 8px;
    }
    .library-search-path {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .library-search-results .library-row { height: 50px; }
    .library-search-results .library-name {
      display: grid;
      gap: 2px;
      line-height: 1.2;
    }
    .library-column {
      flex: 0 0 var(--library-column-width, 260px);
      min-width: 180px;
      height: 100%;
      max-height: 100%;
      min-height: 0;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      border-right: 1px solid #b9c1ce;
      overflow: hidden;
      background: #fff;
      position: relative;
    }
    .library-column:last-child { border-right: 0; }
    .library-column-resizer {
      position: absolute;
      top: 0;
      right: -4px;
      bottom: 0;
      z-index: 3;
      width: 8px;
      cursor: col-resize;
    }
    .library-column-resizer::after {
      content: "";
      position: absolute;
      top: 0;
      bottom: 0;
      left: 3px;
      width: 2px;
      background: #b9c1ce;
    }
    .library-column-resizer:hover::after,
    .library-column.resizing .library-column-resizer::after {
      background: var(--accent);
    }
    .library-pane {
      min-width: 0;
      min-height: 0;
      height: 100%;
      max-height: 100%;
      align-self: stretch;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
    }
    .library-pane-header {
      z-index: 1;
      min-height: 38px;
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }
    .library-column-body {
      min-height: 0;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 8px;
    }
    .library-row {
      width: 100%;
      height: 44px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 5px 8px;
      text-align: left;
      cursor: default;
      font-size: 13px;
    }
    .library-row:hover { background: #f8fafc; }
    .library-row.range-selected { background: #edf5ff; border-color: #cadcf5; }
    .library-row.active { background: #e8f3f4; border-color: #b7dadd; }
    .library-row.path-parent { background: #f3f4f6; border-color: #e5e7eb; }
    .library-row.drag-over { border-color: var(--accent); background: #eef9f8; }
    .library-row.drag-reorder-before { border-top-color: var(--accent); border-top-width: 2px; }
    .library-row.drag-reorder-after { border-bottom-color: var(--accent); border-bottom-width: 2px; }
    .library-row.special-folder { color: #667085; }
    .library-entry-icon {
      width: 20px;
      height: 18px;
      position: relative;
      display: inline-block;
      justify-self: center;
      flex: 0 0 auto;
    }
    .library-entry-icon.folder::before {
      content: "";
      position: absolute;
      left: 1px;
      top: 6px;
      width: 18px;
      height: 11px;
      border-radius: 3px 3px 2px 2px;
      background: linear-gradient(180deg, #62b4f9 0%, #2384dc 100%);
      box-shadow: inset 0 0 0 1px rgba(20, 89, 150, 0.24);
    }
    .library-entry-icon.folder::after {
      content: "";
      position: absolute;
      left: 2px;
      top: 3px;
      width: 9px;
      height: 5px;
      border-radius: 3px 3px 0 0;
      background: #78c3ff;
      box-shadow: inset 0 0 0 1px rgba(20, 89, 150, 0.16);
    }
    .library-entry-icon.document::before {
      content: "";
      position: absolute;
      left: 4px;
      top: 1px;
      width: 12px;
      height: 16px;
      border: 1px solid #aeb8c6;
      border-radius: 2px;
      background: linear-gradient(180deg, #ffffff 0%, #eef3f8 100%);
      box-shadow: 0 1px 1px rgba(15, 23, 42, 0.08);
    }
    .library-entry-icon.document::after {
      content: "";
      position: absolute;
      right: 4px;
      top: 1px;
      width: 5px;
      height: 5px;
      border-left: 1px solid #aeb8c6;
      border-bottom: 1px solid #aeb8c6;
      background: #dfe7f0;
      clip-path: polygon(0 0, 100% 100%, 0 100%);
    }
    .library-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .library-meta { color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .library-rename-input {
      width: 100%;
      min-width: 0;
      border: 1px solid var(--accent);
      border-radius: 5px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      padding: 3px 6px;
      outline: 0;
    }
    .library-detail {
      min-height: 0;
      overflow-y: auto;
      padding: 14px;
      color: #344054;
      font-size: 13px;
      line-height: 1.5;
    }
    .library-detail h3 { margin: 0 0 8px; color: var(--ink); font-size: 16px; line-height: 1.3; letter-spacing: 0; }
    .library-detail dl { display: grid; grid-template-columns: 74px minmax(0, 1fr); gap: 6px 10px; margin: 12px 0; }
    .library-detail dt { color: var(--muted); }
    .library-detail dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
    .library-detail-figure {
      margin: 10px 0 12px;
      border: 1px solid var(--line);
      border-radius: 7px;
      overflow: hidden;
      background: #f8fafc;
    }
    .library-detail-figure img {
      display: block;
      width: 100%;
      max-height: 220px;
      object-fit: contain;
      background: #fff;
    }
    .library-detail-abstract {
      margin: 12px 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fbfcfe;
    }
    .library-detail-abstract strong {
      display: block;
      margin-bottom: 6px;
      color: var(--ink);
    }
    .library-detail-abstract p {
      margin: 0;
      color: #344054;
    }
    .bibtex-box {
      margin-top: 12px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #f8fafc;
      color: #1f2937;
      font-size: 12px;
      white-space: pre-wrap;
      overflow: auto;
    }
    .library-reference-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-top: 12px;
    }
    .library-reference-head strong { color: var(--ink); }
    .nature-reference-box { white-space: normal; }
    .citation-panel {
      margin: 12px 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
    }
    .citation-summary {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
    }
    .citation-summary strong { color: var(--ink); }
    .citation-count {
      color: var(--accent-strong);
      font-size: 18px;
      font-weight: 700;
    }
    .citation-bars {
      display: flex;
      align-items: end;
      gap: 5px;
      height: 82px;
      margin-top: 10px;
      overflow-x: auto;
      padding-bottom: 2px;
    }
    .citation-bar-wrap {
      display: grid;
      grid-template-rows: 1fr auto;
      justify-items: center;
      gap: 4px;
      min-width: 22px;
      height: 80px;
      color: var(--muted);
      font-size: 10px;
    }
    .citation-bar {
      align-self: end;
      width: 13px;
      min-height: 2px;
      border-radius: 3px 3px 0 0;
      background: var(--accent);
    }
    .citation-empty { margin-top: 8px; color: var(--muted); font-size: 12px; }
    .library-detail-status { margin-top: 8px; min-height: 18px; color: var(--muted); }
    .library-detail-status.ok { color: #137333; }
    .library-detail-status.err { color: #b42318; }
    .library-context-menu {
      position: fixed;
      z-index: 50;
      display: none;
      min-width: 160px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: var(--shadow);
      padding: 6px;
    }
    .library-context-menu.open { display: block; }
    .library-context-menu button {
      width: 100%;
      min-height: 30px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      text-align: left;
      padding: 6px 8px;
      cursor: pointer;
    }
    .library-context-menu button:hover { background: #eef2f7; }
    .library-context-menu button[data-action="delete-entry"] { color: #b42318; }
    .library-context-menu button[data-action="delete-entry"]:hover { background: #fff1f0; }
    .library-color-input { position: fixed; opacity: 0; pointer-events: none; width: 1px; height: 1px; }
    .action.copied {
      border-color: rgba(29, 112, 68, 0.35);
      color: var(--ok);
      background: #f0f8f3;
    }
    .subject-controls { display: grid; grid-template-columns: 1fr; gap: 8px; }
    .subject-option {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 7px;
      min-height: 34px;
      padding: 7px 10px;
      text-align: left;
      cursor: pointer;
      font-size: 14px;
    }
    .subject-option.active { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); color: var(--accent); }
    .papers {
      min-height: 0;
      overflow-y: auto;
      display: grid;
      align-content: start;
      gap: 12px;
      padding-right: 2px;
    }
    .papers.library-view {
      display: block;
      height: 100%;
      overflow: hidden;
      padding-right: 0;
    }
    .paper {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
    }
    .paper-layout { display: grid; gap: 14px; }
    .paper.with-figure .paper-layout { grid-template-columns: minmax(150px, 220px) minmax(0, 1fr); align-items: start; }
    .paper-figure {
      margin: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #f8fafc;
      aspect-ratio: 4 / 3;
    }
    .paper-figure img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
    .paper-figure-placeholder {
      width: 100%;
      height: 100%;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 12px;
      background: #f8fafc;
    }
    .paper-head { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; }
    .paper-head > div:first-child { min-width: 0; }
    .paper h3 { margin: 0; font-size: 18px; line-height: 1.35; letter-spacing: 0; }
    .journal-group {
      margin: 10px 0 4px;
      color: var(--ink);
      font-size: 18px;
      font-weight: 750;
      display: flex;
      align-items: center;
      min-height: 34px;
    }
    .journal-group img { max-width: 240px; max-height: 34px; object-fit: contain; display: block; }
    .journal-group-text { font-size: 18px; font-weight: 750; }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border: 1px solid currentColor;
      border-radius: 7px;
      padding: 2px 8px;
      font-size: 12px;
      white-space: nowrap;
      flex: none;
    }
    .paper-badges {
      display: flex;
      flex: 0 0 auto;
      flex-wrap: wrap;
      justify-content: flex-end;
      align-items: flex-start;
      gap: 6px;
      max-width: 260px;
    }
    .field-badge {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border: 1px solid #cbd5e1;
      border-radius: 7px;
      padding: 2px 8px;
      background: #f8fafc;
      color: #475569;
      font-size: 12px;
      white-space: nowrap;
      flex: none;
    }
    .meta { display: flex; gap: 10px; flex-wrap: wrap; color: var(--muted); font-size: 13px; margin-top: 8px; }
    .journal-name { color: var(--ink); font-weight: 750; }
    .authors { color: #526071; }
    .abstract { color: #344054; line-height: 1.55; margin: 12px 0 0; font-size: 14px; }
    .actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 14px; }
    .action {
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 7px;
      min-height: 30px;
      padding: 0 8px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
    }
    .action.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    .action.secondary { background: var(--accent); border-color: var(--accent); color: #fff; }
    .action.danger { border-color: var(--accent-2); color: var(--accent-2); background: #fff7f6; }
    .action:disabled { opacity: 0.55; cursor: wait; }
    .manual-drop {
      border: 1px dashed var(--line);
      background: #fbfcfe;
      color: var(--muted);
      border-radius: 7px;
      min-height: 30px;
      padding: 0 8px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      font-size: 12px;
    }
    .manual-drop:hover, .manual-drop.dragging { border-color: var(--accent); color: var(--accent); background: #f0f9f9; }
    .manual-drop input { display: none; }
    .status {
      font-size: 12px;
      color: var(--muted);
      border-left: 3px solid var(--line);
      padding-left: 8px;
      min-height: 18px;
    }
    .status.ok { border-color: var(--ok); color: var(--ok); }
    .status.warn { border-color: var(--warn); color: var(--warn); }
    .status.err { border-color: var(--accent-2); color: var(--accent-2); }
    .empty {
      border: 1px dashed var(--line);
      border-radius: 8px;
      padding: 28px;
      color: var(--muted);
      background: #fff;
      text-align: center;
    }
    .analysis-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.28);
      display: none;
      z-index: 20;
    }
    .analysis-backdrop.open { display: none; }
    .analysis-panel {
      grid-area: note;
      position: relative;
      z-index: 1;
      min-width: 0;
      height: 100%;
      min-height: 0;
      overflow: auto;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 0;
      display: none;
    }
    .analysis-panel.open { display: block; }
    .analysis-header {
      position: sticky;
      top: 0;
      z-index: 2;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      background: #fff;
      border-bottom: 1px solid var(--line);
      padding: 16px 16px 10px;
      margin: 0 0 12px;
    }
    .analysis-close { min-width: 30px; min-height: 30px; border: 1px solid var(--line); border-radius: 7px; background: #fff; cursor: pointer; }
    .analysis-panel h2 { margin: 0 0 6px; font-size: 18px; letter-spacing: 0; }
    .analysis-meta { color: var(--muted); font-size: 13px; line-height: 1.45; margin-bottom: 12px; }
    .analysis-body { color: #273142; font-size: 14px; line-height: 1.65; padding: 0 16px 16px; }
    .analysis-body h1 { font-size: 20px; margin: 12px 0 8px; letter-spacing: 0; }
    .analysis-body h2 { font-size: 17px; margin: 16px 0 8px; letter-spacing: 0; }
    .analysis-body h3 { font-size: 15px; margin: 14px 0 6px; letter-spacing: 0; }
    .analysis-body p { margin: 8px 0; }
    .analysis-body ul { margin: 8px 0 8px 20px; padding: 0; }
    .analysis-body li { margin: 4px 0; }
    .analysis-body code {
      background: #eef2f7;
      border-radius: 4px;
      padding: 1px 4px;
      font-size: 0.92em;
    }
    @media (max-width: 480px) {
      .app { grid-template-columns: 1fr; }
      .app.sidebar-collapsed { grid-template-columns: 1fr; }
      .sidebar { border-right: 0; border-bottom: 1px solid var(--line); }
      .main { padding: 20px; height: auto; overflow: visible; }
      body, .app { height: auto; overflow: auto; }
      .sidebar { height: auto; overflow: visible; }
      .workspace, .workspace.note-open, .workspace.note-open.report-collapsed { grid-template-columns: 1fr; height: auto; }
      .workspace { grid-template-areas: "report"; }
      .workspace.note-open, .workspace.note-open.report-collapsed { grid-template-areas: "report" "note"; }
      .workspace-toggle, .workspace-resizer { display: none !important; }
      .report-column, .analysis-panel { height: auto; overflow: visible; display: block; }
      .papers, .papers.library-view { overflow: visible; display: grid; padding-right: 0; }
      .workspace.report-collapsed .report-column { display: block; }
      .paper.with-figure .paper-layout { grid-template-columns: 1fr; }
      .paper-head { flex-direction: column; }
      .paper-badges { justify-content: flex-start; max-width: 100%; }
      .library-shell { grid-template-columns: 1fr; }
      .loader-form { grid-template-columns: 1fr; }
      .loader-main { grid-template-columns: 1fr; }
      .library-quicklook { top: 24px; left: 4vw; width: 92vw; height: 70vh; }
      .library-quicklook-body { grid-template-columns: 78px minmax(0, 1fr); }
      .library-page-thumb { width: 58px; min-height: 78px; }
    }
  </style>
</head>
<body>
  <div class="app library-mode sidebar-collapsed">
    <aside class="sidebar">
      <div class="brand">
        <div class="sidebar-view-switcher" id="sidebarViewSwitcher">
          <button class="view-switch" id="sideLibraryMode" type="button">Library</button>
          <button class="view-switch" id="sideReportMode" type="button">Journal Monitor</button>
        </div>
      </div>
      <div class="monthbar">
        <button class="iconbtn" id="prevMonth" title="Previous month">‹</button>
        <strong id="monthLabel"></strong>
        <button class="iconbtn" id="nextMonth" title="Next month">›</button>
      </div>
      <div class="calendar" id="calendar"></div>
      <button class="smallbtn" id="jumpToday">Today</button>
      <div class="filters">
        <div class="filter-title">Journal Filter</div>
        <div id="journalFilters"></div>
      </div>
      <div class="filters">
        <div class="filter-title">Preprint Filter</div>
        <div id="preprintFilters"></div>
        <div class="preprint-category-list" id="preprintCategoryFilters"></div>
      </div>
      <div class="filters">
        <div class="filter-title">Field Filter</div>
        <div class="subject-controls" id="subjectFilters"></div>
      </div>
      <div class="filters">
        <div class="filter-title">Journal Settings</div>
        <div id="journalSettings"></div>
        <input class="search" id="journalName" placeholder="Journal name">
        <input class="search" id="journalIssns" placeholder="ISSNs, comma separated">
        <select class="search" id="journalHistory" title="Previously added journals"></select>
        <button class="smallbtn" id="addJournal">Add Journal</button>
      </div>
    </aside>
    <button class="sidebar-edge" id="toggleSidebar" title="Hide filters">&lsaquo;&lsaquo;</button>
    <main class="main">
      <div class="workspace" id="workspace">
        <section class="report-column">
          <div class="toolbar">
            <div class="view-switcher" id="primaryViewSwitcher">
              <button class="view-switch" id="libraryMode" type="button">Library</button>
              <button class="view-switch" id="reportMode" type="button">Journal Monitor</button>
            </div>
            <div class="top-tools hidden" id="topLibraryTools">
              <span class="top-tools-label">Tools:</span>
              <button class="loader-tool-tab" id="topLibraryLoader" type="button">Loader</button>
            </div>
            <h2 id="reportTitle"></h2>
            <div class="toolbar-actions" id="reportToolbarActions">
              <input class="search" id="searchBox" placeholder="Search title, abstract, DOI">
              <label class="toolbar-toggle"><input type="checkbox" id="figureToggle" checked> Figures</label>
            </div>
          </div>
          <div class="summary" id="summary"></div>
          <div class="report-tabs" id="reportTabs"></div>
          <div class="library-controls" id="libraryControls">
            <button class="library-tab active" id="libraryTab" type="button">Library</button>
            <button class="library-tab" id="myPublicationsTab" type="button">My Publications</button>
            <span id="libraryShortcutTabs"></span>
            <div class="library-search-tools" id="librarySearchTools">
              <div class="library-search-wrap">
                <input class="search" id="librarySearchBox" placeholder="Search Library" type="search">
                <button class="library-search-clear" id="clearLibrarySearch" type="button" title="Clear search">×</button>
              </div>
              <span class="library-search-count" id="librarySearchCount"></span>
            </div>
            <div class="my-publications-tools" id="myPublicationsTools">
              <input class="search" id="myPublicationName" placeholder="My name">
              <button class="smallbtn" id="findMyPublications" type="button">Find by Name</button>
              <input class="search" id="publicationSearchBox" placeholder="DOI or title">
              <button class="smallbtn" id="addMyPublication" type="button">Add</button>
              <select class="search" id="myPublicationSort" title="Sort publications">
                <option value="time">Time</option>
                <option value="highlight">Highlight</option>
              </select>
            </div>
          </div>
          <div class="papers" id="papers"></div>
        </section>
        <button class="workspace-toggle" id="toggleReportPanel" title="Hide list">&lsaquo;&lsaquo;</button>
        <div class="workspace-resizer" id="workspaceResizer" title="Drag to resize panels"></div>
        <div class="analysis-backdrop" id="analysisBackdrop"></div>
        <aside class="analysis-panel" id="analysisPanel" aria-hidden="true">
          <div class="analysis-header">
            <div>
              <h2>Analysis</h2>
              <div class="analysis-meta" id="analysisMeta"></div>
            </div>
            <button class="analysis-close" id="closeAnalysis" title="Close analysis">×</button>
          </div>
          <div class="analysis-body" id="analysisBody"></div>
        </aside>
        </div>
      <div class="internal-browser" id="internalBrowser" aria-hidden="true">
        <div class="internal-browser-bar">
          <button class="smallbtn" id="closeInternalBrowser" type="button">Back</button>
          <button class="smallbtn" id="openExternalBrowser" type="button">External Browser</button>
          <div class="internal-browser-title"><strong id="internalBrowserTitle">Publisher page</strong><span id="internalBrowserUrl"></span></div>
        </div>
        <iframe id="internalBrowserFrame" title="Publisher page" sandbox="allow-scripts allow-forms allow-modals allow-downloads"></iframe>
      </div>
      <div class="library-quicklook" id="libraryQuickLook" aria-hidden="true">
        <div class="library-quicklook-title" id="libraryQuickLookDragHandle">
          <span id="libraryQuickLookTitle"></span>
          <button id="closeLibraryQuickLook" type="button" title="Close preview">×</button>
        </div>
        <div class="library-quicklook-body">
          <div class="library-quicklook-thumbs" id="libraryQuickLookThumbs"></div>
          <div class="library-quicklook-pages" id="libraryQuickLookPages" tabindex="-1"></div>
        </div>
        <div class="library-quicklook-resize" id="libraryQuickLookResize" title="Resize preview"></div>
      </div>
    </main>
  </div>
  <script>
    const initialToday = localIsoDate(new Date());
    const PREPRINT_JOURNALS = new Set(["arXiv"]);
    const ARXIV_CATEGORIES = [
      ["cond-mat.dis-nn", "Disordered Systems"],
      ["cond-mat.mes-hall", "Mesoscale and Nanoscale Physics"],
      ["cond-mat.mtrl-sci", "Materials Science"],
      ["cond-mat.other", "Other Condensed Matter"],
      ["cond-mat.quant-gas", "Quantum Gases"],
      ["cond-mat.soft", "Soft Condensed Matter"],
      ["cond-mat.stat-mech", "Statistical Mechanics"],
      ["cond-mat.str-el", "Strongly Correlated Electrons"],
      ["cond-mat.supr-con", "Superconductivity"]
    ];
    const DEFAULT_ARXIV_CATEGORIES = ["cond-mat.mes-hall", "cond-mat.supr-con"];
    const FIELD_LABELS = {
      "physics": "Physics",
      "quantum_information": "Quantum Information",
      "materials": "Materials",
      "chemistry": "Chemistry",
      "all": "All Fields",
      "other": "Other Fields"
    };
    const MY_PUBLICATION_COLUMNS = [
      {key: "star", label: "", defaultWidth: 42, minWidth: 38, maxWidth: 90},
      {key: "number", label: "No", defaultWidth: 56, minWidth: 46, maxWidth: 120},
      {key: "date", label: "Date", defaultWidth: 120, minWidth: 92, maxWidth: 180},
      {key: "id", label: "ID", defaultWidth: 230, minWidth: 140, maxWidth: 520},
      {key: "title", label: "Title", defaultWidth: 560, minWidth: 260, maxWidth: 1200},
      {key: "delete", label: "", defaultWidth: 86, minWidth: 72, maxWidth: 140}
    ];
    const LIBRARY_SHORTCUT_TAB_COUNT = 5;
    const LIBRARY_WORKSPACE_TAB_COUNT = 3;
    const state = {
      selectedDate: initialToday,
      viewYear: Number(initialToday.slice(0, 4)),
      viewMonth: Number(initialToday.slice(5, 7)),
      journals: [],
      journalsConfig: [],
      journalHistory: [],
      selectedJournals: new Set(),
      selectedPreprintCategories: new Set(DEFAULT_ARXIV_CATEGORIES),
      preprintFiltersExpanded: false,
      selectedFields: new Set(["physics", "materials", "quantum_information"]),
      counts: {},
      papers: [],
      libraryFolders: [],
      libraryItems: [],
      libraryTab: "library",
      libraryShortcutTabs: [],
      libraryWorkspaceTabs: [],
      activeShortcutIndex: -1,
      activeWorkspaceIndex: -1,
      workspaceStatus: "",
      libraryImportPath: "",
      libraryImportCopyMode: "copy",
      libraryImportStatus: "",
      libraryImportBusy: false,
      libraryImportLastResult: null,
      libraryImportJobId: "",
      libraryImportJob: null,
      libraryImportPoller: null,
      libraryImportMissingIndex: 0,
      libraryRootId: 1,
      libraryCurrentFolderId: 1,
      libraryActiveFolderId: 1,
      librarySelection: {type: "folder", id: 1},
      libraryColumnSelections: {},
      libraryRangeAnchor: null,
      libraryRangeFolderId: 0,
      libraryRangeSelectionKeys: new Set(),
      libraryColumnsScrollLeft: 0,
      libraryColumnScrollTops: {},
      libraryColumnWidths: {},
      libraryClipboard: null,
      libraryDragPayload: null,
      libraryRevealColumnFolderId: 0,
      libraryRevealColumnDirection: "",
      libraryRenamingFolderId: 0,
      libraryRenamingItemId: 0,
      libraryQuickLookOpen: false,
      libraryQuickLookPath: "",
      libraryQuickLookUrl: "",
      libraryQuickLookPage: 1,
      libraryQuickLookPageCount: 0,
      libraryQuickLookManualFrame: false,
      libraryQuickLookFrameRect: null,
      myPublications: [],
      myPublicationSelectionId: 0,
      myPublicationSort: "time",
      myPublicationSearchResults: [],
      myPublicationSearchStatus: "",
      myPublicationName: "",
      myPublicationColumnWidths: {},
      mode: "library",
      activeReportJournal: "",
      noteWidth: 460,
      query: "",
      reportSequence: 0,
      reportCache: {},
      fetchingDates: new Set(),
      pendingFetchDates: new Set(),
      noMatchDates: new Set(),
      fetchProgress: {},
      progressPollers: {},
      fetchCompletionWatchers: new Set(),
      logoRequests: {},
      figureRequests: {},
      figureQueue: [],
      queuedFigureIds: new Set(),
      activeFigureHydrations: 0,
      maxFigureHydrations: 2,
      figureFailures: new Set(),
      internalBrowserUrl: "",
      showFigures: true,
      arxivCountdownTimer: null
    };

    const $ = (id) => document.getElementById(id);
    const fmtMonth = (year, month) => `${year}-${String(month).padStart(2, "0")}`;

    function localIsoDate(value) {
      const year = value.getFullYear();
      const month = String(value.getMonth() + 1).padStart(2, "0");
      const day = String(value.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function timeZoneParts(value, timeZone) {
      const parts = new Intl.DateTimeFormat("en-US", {
        timeZone,
        hourCycle: "h23",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      }).formatToParts(value);
      return Object.fromEntries(parts.filter((part) => part.type !== "literal").map((part) => [part.type, Number(part.value)]));
    }

    function timeZoneOffsetMs(value, timeZone) {
      const parts = timeZoneParts(value, timeZone);
      const localAsUtc = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
      return localAsUtc - value.getTime();
    }

    function zonedTimeToDate(year, month, day, hour, minute, timeZone) {
      const localAsUtc = Date.UTC(year, month - 1, day, hour, minute, 0);
      let instant = localAsUtc;
      for (let i = 0; i < 3; i += 1) {
        instant = localAsUtc - timeZoneOffsetMs(new Date(instant), timeZone);
      }
      return new Date(instant);
    }

    function addUtcDays(year, month, day, offset) {
      const value = new Date(Date.UTC(year, month - 1, day + offset, 12, 0, 0));
      return {year: value.getUTCFullYear(), month: value.getUTCMonth() + 1, day: value.getUTCDate()};
    }

    function nextArxivUpdateDate(now = new Date()) {
      const timeZone = "America/New_York";
      const today = timeZoneParts(now, timeZone);
      for (let offset = 0; offset < 8; offset += 1) {
        const candidateDay = addUtcDays(today.year, today.month, today.day, offset);
        const weekday = new Date(Date.UTC(candidateDay.year, candidateDay.month - 1, candidateDay.day)).getUTCDay();
        if (![0, 1, 2, 3, 4].includes(weekday)) continue;
        const candidate = zonedTimeToDate(candidateDay.year, candidateDay.month, candidateDay.day, 20, 0, timeZone);
        if (candidate.getTime() > now.getTime()) return candidate;
      }
      return zonedTimeToDate(today.year, today.month, today.day + 1, 20, 0, timeZone);
    }

    function nextArxivSubmissionCycleDate(now = new Date()) {
      const timeZone = "America/New_York";
      const today = timeZoneParts(now, timeZone);
      for (let offset = 0; offset < 8; offset += 1) {
        const candidateDay = addUtcDays(today.year, today.month, today.day, offset);
        const weekday = new Date(Date.UTC(candidateDay.year, candidateDay.month - 1, candidateDay.day)).getUTCDay();
        if (![1, 2, 3, 4, 5].includes(weekday)) continue;
        const candidate = zonedTimeToDate(candidateDay.year, candidateDay.month, candidateDay.day, 14, 0, timeZone);
        candidate.setSeconds(1, 0);
        if (candidate.getTime() > now.getTime()) return candidate;
      }
      const fallback = zonedTimeToDate(today.year, today.month, today.day + 1, 14, 0, timeZone);
      fallback.setSeconds(1, 0);
      return fallback;
    }

    function formatArxivCountdown(minutes) {
      const safeMinutes = Math.max(0, Math.ceil(minutes));
      const days = Math.floor(safeMinutes / 1440);
      const hours = Math.floor((safeMinutes % 1440) / 60);
      const mins = safeMinutes % 60;
      if (days) return `${days} d ${hours} h ${String(mins).padStart(2, "0")} min`;
      if (hours) return `${hours} h ${String(mins).padStart(2, "0")} min`;
      return `${mins} min`;
    }

    function statusClass(status) {
      if (["success", "partial", "created", "broad_reading"].some((x) => status.includes(x))) return "ok";
      if (["failed", "error"].some((x) => status.includes(x))) return "err";
      if (["skipped", "pending", "queued"].some((x) => status.includes(x))) return "warn";
      return "";
    }

    async function fetchJson(url, timeoutMs = 12000) {
      const controller = new AbortController();
      const timer = window.setTimeout(() => controller.abort(), timeoutMs);
      try {
        const res = await fetch(url, {signal: controller.signal});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText || "Request failed");
        return data;
      } catch (error) {
        if (error.name === "AbortError") throw new Error("Local data is busy. Try this date again in a moment.");
        throw error;
      } finally {
        window.clearTimeout(timer);
      }
    }

    async function loadMonth() {
      const data = await fetchJson(`/api/month?year=${state.viewYear}&month=${state.viewMonth}`);
      state.journals = data.journals;
      syncSelectedJournals();
      state.counts = data.counts;
      renderCalendar();
      renderFilters();
      renderSubjectFilters();
      await loadJournalSettings();
    }

    async function loadReport(options = {}) {
      const showLoading = options.showLoading !== false;
      const selectedDate = state.selectedDate;
      const sequence = ++state.reportSequence;
      const cached = state.reportCache[selectedDate];
      if (cached) {
        setPendingFetchDate(selectedDate, reportStillFetching(cached));
        updateCalendarCountFromReport(selectedDate, cached);
        applyReportData(selectedDate, cached, sequence);
      } else if (showLoading) {
        showReportLoading(selectedDate);
      }
      try {
        const data = await fetchJson(`/api/report?date=${selectedDate}&auto_fetch=0`);
        setPendingFetchDate(selectedDate, reportStillFetching(data));
        updateCalendarCountFromReport(selectedDate, data);
        state.reportCache[selectedDate] = data;
        applyReportData(selectedDate, data, sequence);
        if ((data.missingJournals || []).length) {
          refreshMissingDateInBackground(selectedDate);
        }
      } catch (error) {
        if (selectedDate !== state.selectedDate || sequence !== state.reportSequence) return;
        if (state.mode !== "library") setPrimaryView("report");
        $("summary").textContent = "Local data is busy";
        $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      }
    }

    function showReportLoading(selectedDate) {
      if (selectedDate !== state.selectedDate) return;
      stopArxivUpdateCountdown();
      $("reportTitle").textContent = `${selectedDate} Report`;
      $("summary").textContent = "Loading local data...";
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("papers").innerHTML = `<div class="empty">Loading papers for this date...</div>`;
    }

    function applyReportData(selectedDate, data, sequence) {
      if (selectedDate !== state.selectedDate || sequence !== state.reportSequence) return;
      state.journals = data.journals || state.journals;
      syncSelectedJournals();
      state.papers = data.papers || [];
      renderSubjectFilters();
      renderFilters();
      if (state.mode === "library") {
        loadLibrary();
        return;
      }
      renderReport();
      if ((data.missingJournals || []).length && !state.papers.length) {
        $("papers").innerHTML = `<div class="empty">Fetching papers for this date in the background. You can keep browsing other dates.</div>`;
      }
    }

    function reportIsActiveForDate(selectedDate) {
      return state.mode !== "library" && selectedDate === state.selectedDate;
    }

    function renderReportIfActive(selectedDate) {
      if (reportIsActiveForDate(selectedDate)) renderReport();
    }

    async function refreshMissingDateInBackground(selectedDate) {
      if (state.fetchingDates.has(selectedDate)) return;
      setPendingFetchDate(selectedDate, true);
      state.fetchingDates.add(selectedDate);
      state.fetchProgress[selectedDate] = state.fetchProgress[selectedDate] || {percent: 0, completed: 0, total: 0, active: true};
      startProgressPolling(selectedDate);
      renderCalendar();
      renderReportIfActive(selectedDate);
      try {
        const data = await fetchJson(`/api/report?date=${selectedDate}`, 20 * 60 * 1000);
        updateCalendarCountFromReport(selectedDate, data);
        state.reportCache[selectedDate] = data;
        if (data.fetchActive && (data.missingJournals || []).length) {
          await waitForDateFetchToFinish(selectedDate);
          const finalData = await fetchJson(`/api/report?date=${selectedDate}&auto_fetch=0`);
          setPendingFetchDate(selectedDate, false);
          updateCalendarCountFromReport(selectedDate, finalData);
          state.reportCache[selectedDate] = finalData;
          if (selectedDate === state.selectedDate) {
            const sequence = ++state.reportSequence;
            applyReportData(selectedDate, finalData, sequence);
          }
          return;
        }
        if ((data.missingJournals || []).length) {
          const retryData = await retryMissingSources(selectedDate, data);
          if (retryData) {
            updateCalendarCountFromReport(selectedDate, retryData);
            state.reportCache[selectedDate] = retryData;
            if (selectedDate === state.selectedDate) {
              const sequence = ++state.reportSequence;
              applyReportData(selectedDate, retryData, sequence);
            }
          }
          return;
        }
        setPendingFetchDate(selectedDate, false);
        if (data.fetched) await loadMonth();
        if (selectedDate === state.selectedDate) {
          const sequence = ++state.reportSequence;
          applyReportData(selectedDate, data, sequence);
        }
      } catch (error) {
        if (reportIsActiveForDate(selectedDate)) {
          $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
        }
      } finally {
        const progress = await refreshFetchProgress(selectedDate);
        if (progress && progress.active !== false) {
          setPendingFetchDate(selectedDate, true);
          state.fetchingDates.add(selectedDate);
          await startProgressPolling(selectedDate);
          watchFetchCompletion(selectedDate);
          renderCalendar();
          renderReportIfActive(selectedDate);
          return;
        }
        finishFetchUi(selectedDate);
      }
    }

    function setPendingFetchDate(selectedDate, value) {
      const before = state.pendingFetchDates.has(selectedDate);
      if (value) state.pendingFetchDates.add(selectedDate);
      else state.pendingFetchDates.delete(selectedDate);
      if (before !== state.pendingFetchDates.has(selectedDate)) renderCalendar();
    }

    function reportFetchIsPending(selectedDate) {
      return state.fetchingDates.has(selectedDate) || state.pendingFetchDates.has(selectedDate);
    }

    function reportStillFetching(data) {
      return Boolean(data.fetchActive || ((data.missingJournals || []).length && !data.fetched));
    }

    async function waitForDateFetchToFinish(selectedDate) {
      const deadline = Date.now() + 20 * 60 * 1000;
      while (Date.now() < deadline) {
        await sleep(700);
        const progress = await refreshFetchProgress(selectedDate);
        if (progress && progress.active === false) return;
      }
    }

    function sleep(ms) {
      return new Promise((resolve) => window.setTimeout(resolve, ms));
    }

    function finishFetchUi(selectedDate) {
      setPendingFetchDate(selectedDate, false);
      state.fetchingDates.delete(selectedDate);
      stopProgressPolling(selectedDate);
      renderCalendar();
      renderReportIfActive(selectedDate);
    }

    function watchFetchCompletion(selectedDate) {
      if (state.fetchCompletionWatchers.has(selectedDate)) return;
      state.fetchCompletionWatchers.add(selectedDate);
      (async () => {
        try {
          await waitForDateFetchToFinish(selectedDate);
          const finalData = await fetchJson(`/api/report?date=${selectedDate}&auto_fetch=0`);
          updateCalendarCountFromReport(selectedDate, finalData);
          state.reportCache[selectedDate] = finalData;
          if (selectedDate === state.selectedDate) {
            const sequence = ++state.reportSequence;
            applyReportData(selectedDate, finalData, sequence);
          }
        } catch (error) {
          if (selectedDate === state.selectedDate) {
            $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
          }
        } finally {
          state.fetchCompletionWatchers.delete(selectedDate);
          finishFetchUi(selectedDate);
        }
      })();
    }

    async function retryMissingSources(selectedDate, initialData) {
      let current = initialData;
      for (let attempt = 0; attempt < 2 && (current.missingJournals || []).length; attempt += 1) {
        setPendingFetchDate(selectedDate, true);
        state.fetchingDates.add(selectedDate);
        state.fetchProgress[selectedDate] = {
          active: true,
          completed: 0,
          total: (current.missingJournals || []).length,
          percent: 0,
          currentJournal: (current.missingJournals || [])[0] || ""
        };
        await startProgressPolling(selectedDate);
        renderReportIfActive(selectedDate);
        current = await fetchJson(`/api/report?date=${selectedDate}`, 20 * 60 * 1000);
        updateCalendarCountFromReport(selectedDate, current);
        state.reportCache[selectedDate] = current;
        if (current.fetchActive && (current.missingJournals || []).length) {
          await waitForDateFetchToFinish(selectedDate);
          current = await fetchJson(`/api/report?date=${selectedDate}&auto_fetch=0`);
        }
      }
      setPendingFetchDate(selectedDate, false);
      state.fetchingDates.delete(selectedDate);
      await refreshFetchProgress(selectedDate);
      stopProgressPolling(selectedDate);
      renderCalendar();
      return current;
    }

    function updateCalendarCountFromReport(selectedDate, data) {
      const sourceCounts = data.journalCounts || {};
      const counts = Object.keys(sourceCounts).length ? {...sourceCounts} : countPapersByJournal(data.papers || []);
      const missing = (data.missingJournals || []).length > 0;
      if (Object.keys(counts).length || !missing) {
        state.counts[selectedDate] = counts;
      }
      const total = Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
      if (total > 0) state.noMatchDates.delete(selectedDate);
      if (selectedDate.startsWith(fmtMonth(state.viewYear, state.viewMonth))) renderCalendar();
    }

    function countPapersByJournal(papers) {
      return papers.reduce((counts, paper) => {
        const journal = paper.journal || "Unknown";
        counts[journal] = (counts[journal] || 0) + 1;
        return counts;
      }, {});
    }

    async function startProgressPolling(selectedDate) {
      if (state.progressPollers[selectedDate]) return;
      await refreshFetchProgress(selectedDate);
      state.progressPollers[selectedDate] = window.setInterval(() => refreshFetchProgress(selectedDate), 350);
    }

    function stopProgressPolling(selectedDate) {
      const poller = state.progressPollers[selectedDate];
      if (!poller) return;
      window.clearInterval(poller);
      delete state.progressPollers[selectedDate];
    }

    async function refreshFetchProgress(selectedDate) {
      try {
        const res = await fetch(`/api/fetch-progress?date=${selectedDate}`);
        const data = await res.json();
        if (data.progress) {
          state.fetchProgress[selectedDate] = data.progress;
          if (state.fetchingDates.has(selectedDate)) renderReportIfActive(selectedDate);
        }
        return data.progress || null;
      } catch (error) {
        return null;
      }
    }

    async function loadLibrary() {
      state.mode = "library";
      state.libraryTab = "library";
      const res = await fetch("/api/library");
      const data = await res.json();
      applyLibrarySnapshot(data);
      state.libraryActiveFolderId = Number(state.libraryRootId || 1);
      state.libraryCurrentFolderId = Number(state.libraryRootId || 1);
      state.librarySelection = {type: "folder", id: Number(state.libraryRootId || 1)};
      clearLibraryRangeSelection();
      ensureLibraryColumnSelection(state.libraryRootId);
      setSidebarCollapsed(true);
      renderLibrary();
    }

    async function loadMyPublications() {
      state.mode = "library";
      state.libraryTab = "my-publications";
      setSidebarCollapsed(true);
      const res = await fetch("/api/my-publications");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not load My Publications");
      applyMyPublications(data);
      renderMyPublications();
    }

    function openLibraryLoader() {
      state.mode = "library";
      state.libraryTab = "loader";
      setSidebarCollapsed(true);
      renderLibraryLoader();
    }

    function renderActiveLibraryTab() {
      if (state.libraryTab === "loader") {
        renderLibraryLoader();
        return;
      }
      if (state.libraryTab === "my-publications") {
        renderMyPublications();
        return;
      }
      renderLibrary();
    }

    function applyMyPublications(data) {
      state.myPublications = Array.isArray(data.publications) ? data.publications : [];
      state.myPublicationName = data.myName || state.myPublicationName || "";
      if (!state.myPublicationSelectionId && state.myPublications.length) {
        state.myPublicationSelectionId = Number(sortedMyPublications()[0]?.id || 0);
      }
      if (state.myPublicationSelectionId && !myPublicationById(state.myPublicationSelectionId)) {
        state.myPublicationSelectionId = Number(sortedMyPublications()[0]?.id || 0);
      }
    }

    function myPublicationById(id) {
      return state.myPublications.find((item) => Number(item.id) === Number(id));
    }

    function sortedMyPublications() {
      const rows = [...state.myPublications];
      rows.sort((a, b) => {
        if (state.myPublicationSort === "highlight") {
          const starDelta = Number(Boolean(b.starred)) - Number(Boolean(a.starred));
          if (starDelta) return starDelta;
        }
        const dateDelta = String(b.paper?.publication_date || "").localeCompare(String(a.paper?.publication_date || ""));
        if (dateDelta) return dateDelta;
        return String(a.paper?.title || "").localeCompare(String(b.paper?.title || ""));
      });
      return rows;
    }

    function selectedMyPublicationPaper() {
      return myPublicationById(state.myPublicationSelectionId)?.paper || null;
    }

    function applyLibrarySnapshot(data) {
      state.libraryRootId = Number(data.root_id || 1);
      state.libraryFolders = data.folders || [];
      state.libraryItems = data.items || [];
      state.libraryShortcutTabs = Array.isArray(data.shortcut_tabs) ? data.shortcut_tabs : state.libraryShortcutTabs;
      state.libraryWorkspaceTabs = Array.isArray(data.workspace_tabs) ? data.workspace_tabs : state.libraryWorkspaceTabs;
      const displayRootId = libraryDisplayRootId();
      if (!libraryFolderById(state.libraryCurrentFolderId)) state.libraryCurrentFolderId = displayRootId;
      if (!libraryFolderById(state.libraryActiveFolderId)) state.libraryActiveFolderId = displayRootId;
      if (!librarySelectionExists(state.librarySelection)) {
        state.librarySelection = {type: "folder", id: state.libraryCurrentFolderId};
      }
      Object.keys(state.libraryColumnSelections).forEach((folderId) => {
        if (!libraryFolderById(folderId) || !librarySelectionExists(state.libraryColumnSelections[folderId])) {
          delete state.libraryColumnSelections[folderId];
        }
      });
      if (state.libraryClipboard && !librarySelectionExists(state.libraryClipboard)) state.libraryClipboard = null;
      pruneLibraryRangeSelection();
      ensureLibraryColumnSelection(displayRootId);
    }

    function libraryFolderById(id) {
      return state.libraryFolders.find((folder) => Number(folder.id) === Number(id));
    }

    function libraryDisplayRootId() {
      if (state.libraryTab?.startsWith("shortcut-")) {
        const index = Number(state.libraryTab.split("-")[1] || -1);
        const folderId = Number(state.libraryShortcutTabs[index]?.folder_id || 0);
        if (folderId && libraryFolderById(folderId)) return folderId;
      }
      if (state.libraryTab?.startsWith("workspace-")) {
        const index = Number(state.libraryTab.split("-")[1] || -1);
        const folderId = Number(state.libraryWorkspaceTabs[index]?.root_folder_id || 0);
        if (folderId && libraryFolderById(folderId)) return folderId;
      }
      return Number(state.libraryRootId || 1);
    }

    function libraryShortcutLabel(index) {
      const shortcut = state.libraryShortcutTabs[index] || {};
      return shortcut.label || `Shortcut ${index + 1}`;
    }

    function libraryWorkspaceTab(index) {
      return state.libraryWorkspaceTabs[index] || {label: `Space ${index + 1}`, root_folder_id: 0};
    }

    function libraryWorkspaceLabel(index) {
      return libraryWorkspaceTab(index).label || `Space ${index + 1}`;
    }

    function libraryUnsortedFolderId() {
      return Number(state.libraryFolders.find((folder) => folder.is_unsorted || folder.name === "unsorted")?.id || libraryDisplayRootId());
    }

    function libraryRecycleFolderId() {
      return Number(state.libraryFolders.find((folder) => folder.is_recycle || folder.name === "Recycle")?.id || 0);
    }

    function libraryItemById(id) {
      return state.libraryItems.find((item) => Number(item.id) === Number(id));
    }

    function librarySelectionExists(selection) {
      if (!selection) return false;
      if (selection.type === "folder") return Boolean(libraryFolderById(selection.id));
      if (selection.type === "item") return Boolean(libraryItemById(selection.id));
      return false;
    }

    function libraryChildFolders(parentId) {
      return state.libraryFolders
        .filter((folder) => Number(folder.parent_id || 0) === Number(parentId))
        .sort((a, b) => compareLibraryOrder(a, b, "name"));
    }

    function libraryFolderItemsRaw(folderId) {
      return state.libraryItems
        .filter((item) => Number(item.folder_id) === Number(folderId))
        .sort((a, b) => compareLibraryOrder(a, b, "display_name"));
    }

    function libraryFolderItems(folderId) {
      const query = state.query.trim().toLowerCase();
      return libraryFolderItemsRaw(folderId)
        .filter((item) => {
          if (!query) return true;
          const paper = item.paper || {};
          const haystack = `${item.display_name || ""} ${paper.citation_label || ""} ${paper.title || ""} ${paper.abstract || ""} ${paper.doi || ""} ${paper.journal || ""} ${(paper.authors || []).join(" ")}`.toLowerCase();
          return haystack.includes(query);
        });
    }

    function compareLibraryOrder(a, b, fallbackKey) {
      const specialDelta = libraryFolderSpecialRank(a) - libraryFolderSpecialRank(b);
      if (specialDelta) return specialDelta;
      const orderDelta = Number(a.sort_order || 0) - Number(b.sort_order || 0);
      if (orderDelta) return orderDelta;
      const left = fallbackKey === "display_name"
        ? (a.display_name || a.paper?.citation_label || a.paper?.title || "")
        : (a[fallbackKey] || "");
      const right = fallbackKey === "display_name"
        ? (b.display_name || b.paper?.citation_label || b.paper?.title || "")
        : (b[fallbackKey] || "");
      return String(left).localeCompare(String(right)) || (Number(a.id || 0) - Number(b.id || 0));
    }

    function libraryFolderSpecialRank(entry) {
      if (!entry || Number(entry.parent_id || 0) !== Number(state.libraryRootId || 1)) return 0;
      if (entry.is_unsorted || entry.name === "unsorted") return 10;
      if (entry.is_recycle || entry.name === "Recycle") return 11;
      return 0;
    }

    function libraryEntriesForFolder(folderId) {
      const query = state.query.trim().toLowerCase();
      const folders = libraryChildFolders(folderId)
        .filter((folder) => !query || (folder.name || "").toLowerCase().includes(query))
        .map((folder) => ({type: "folder", id: Number(folder.id)}));
      const items = libraryFolderItems(folderId)
        .map((item) => ({type: "item", id: Number(item.id)}));
      return folders.concat(items);
    }

    function librarySearchIsActive() {
      return Boolean(state.query.trim()) && !["loader", "my-publications"].includes(state.libraryTab || "");
    }

    function libraryItemSearchHaystack(item) {
      const paper = item.paper || {};
      return [
        item.display_name,
        paper.citation_label,
        paper.title,
        paper.abstract,
        paper.doi,
        paper.preprint_id,
        paper.journal,
        paper.publication_date,
        ...(Array.isArray(paper.authors) ? paper.authors : []),
        ...(Array.isArray(paper.full_authors) ? paper.full_authors : [])
      ].filter(Boolean).join(" ").toLowerCase();
    }

    function libraryFolderPath(folderId) {
      const displayRootId = libraryDisplayRootId();
      const parts = [];
      let current = libraryFolderById(folderId);
      let guard = 0;
      while (current && guard < 64) {
        guard += 1;
        parts.push(current.name || "Folder");
        if (Number(current.id) === Number(displayRootId) || current.parent_id === null) break;
        current = libraryFolderById(current.parent_id);
      }
      return parts.reverse().join(" / ");
    }

    function libraryDescendantFolderIds(rootId) {
      const ids = new Set([Number(rootId)]);
      const queue = [Number(rootId)];
      while (queue.length) {
        const parentId = queue.shift();
        libraryChildFolders(parentId).forEach((folder) => {
          const folderId = Number(folder.id);
          if (ids.has(folderId)) return;
          ids.add(folderId);
          queue.push(folderId);
        });
      }
      return ids;
    }

    function librarySearchResults() {
      const query = state.query.trim().toLowerCase();
      if (!query) return [];
      const displayRootId = libraryDisplayRootId();
      const folderIds = libraryDescendantFolderIds(displayRootId);
      const results = [];
      state.libraryFolders
        .filter((folder) => folderIds.has(Number(folder.id)) && Number(folder.id) !== Number(displayRootId))
        .forEach((folder) => {
          const path = libraryFolderPath(folder.id);
          const haystack = `${folder.name || ""} ${path}`.toLowerCase();
          if (haystack.includes(query)) {
            results.push({
              type: "folder",
              id: Number(folder.id),
              parentFolderId: Number(folder.parent_id || displayRootId),
              path
            });
          }
        });
      state.libraryItems
        .filter((item) => folderIds.has(Number(item.folder_id)))
        .forEach((item) => {
          const folderPath = libraryFolderPath(item.folder_id);
          const haystack = `${libraryItemSearchHaystack(item)} ${folderPath}`.toLowerCase();
          if (haystack.includes(query)) {
            results.push({
              type: "item",
              id: Number(item.id),
              parentFolderId: Number(item.folder_id || displayRootId),
              path: folderPath
            });
          }
        });
      return results.sort((a, b) => {
        const typeDelta = (a.type === "folder" ? 0 : 1) - (b.type === "folder" ? 0 : 1);
        if (typeDelta) return typeDelta;
        const left = a.type === "folder"
          ? (libraryFolderById(a.id)?.name || "")
          : (libraryItemById(a.id)?.display_name || libraryItemById(a.id)?.paper?.title || "");
        const right = b.type === "folder"
          ? (libraryFolderById(b.id)?.name || "")
          : (libraryItemById(b.id)?.display_name || libraryItemById(b.id)?.paper?.title || "");
        return String(left).localeCompare(String(right)) || Number(a.id) - Number(b.id);
      });
    }

    function libraryVisibleEntries() {
      return libraryEntriesForFolder(state.libraryActiveFolderId || libraryDisplayRootId());
    }

    function libraryEntryKey(entry) {
      return entry ? `${entry.type}:${Number(entry.id)}` : "";
    }

    function clearLibraryRangeSelection() {
      state.libraryRangeAnchor = null;
      state.libraryRangeFolderId = 0;
      state.libraryRangeSelectionKeys = new Set();
    }

    function pruneLibraryRangeSelection() {
      const folderId = Number(state.libraryRangeFolderId || 0);
      if (!folderId || !libraryFolderById(folderId)) {
        clearLibraryRangeSelection();
        return;
      }
      const validKeys = new Set(libraryEntriesForFolder(folderId).map(libraryEntryKey));
      state.libraryRangeSelectionKeys = new Set([...state.libraryRangeSelectionKeys].filter((key) => validKeys.has(key)));
      if (state.libraryRangeAnchor && !validKeys.has(libraryEntryKey(state.libraryRangeAnchor))) {
        state.libraryRangeAnchor = null;
      }
      if (state.libraryRangeSelectionKeys.size < 2) {
        state.libraryRangeSelectionKeys = new Set();
      }
    }

    function libraryEntryIsRangeSelected(folderId, entry) {
      return state.libraryRangeSelectionKeys.size > 1
        && Number(state.libraryRangeFolderId || 0) === Number(folderId)
        && state.libraryRangeSelectionKeys.has(libraryEntryKey(entry));
    }

    function libraryRangeSelectionEntries() {
      const folderId = Number(state.libraryRangeFolderId || 0);
      if (!folderId || state.libraryRangeSelectionKeys.size < 2) return [];
      return libraryEntriesForFolder(folderId).filter((entry) => state.libraryRangeSelectionKeys.has(libraryEntryKey(entry)));
    }

    function ensureLibraryColumnSelection(folderId) {
      const id = Number(folderId || libraryDisplayRootId());
      const selection = state.libraryColumnSelections[id];
      const entries = libraryEntriesForFolder(id);
      if (selection && entries.some((entry) => libraryEntryKey(entry) === libraryEntryKey(selection))) return selection;
      delete state.libraryColumnSelections[id];
      return null;
    }

    function setLibraryColumnSelection(folderId, entry, options = {}) {
      const parentId = Number(folderId || libraryDisplayRootId());
      const selection = {type: entry.type, id: Number(entry.id)};
      state.libraryColumnSelections[parentId] = selection;
      state.libraryActiveFolderId = parentId;
      state.librarySelection = selection;
      if (options.rangeKeys) {
        state.libraryRangeFolderId = parentId;
        state.libraryRangeSelectionKeys = new Set(options.rangeKeys);
        if (options.anchor) state.libraryRangeAnchor = options.anchor;
      } else {
        state.libraryRangeFolderId = parentId;
        state.libraryRangeAnchor = selection;
        state.libraryRangeSelectionKeys = new Set();
      }
      if (selection.type === "folder") {
        state.libraryCurrentFolderId = selection.id;
      } else {
        const item = libraryItemById(selection.id);
        state.libraryCurrentFolderId = Number(item?.folder_id || parentId);
      }
    }

    function setLibraryRangeSelection(folderId, entry) {
      const parentId = Number(folderId || libraryDisplayRootId());
      const entries = libraryEntriesForFolder(parentId);
      const target = {type: entry.type, id: Number(entry.id)};
      const targetKey = libraryEntryKey(target);
      const targetIndex = entries.findIndex((item) => libraryEntryKey(item) === targetKey);
      if (targetIndex < 0) {
        setLibraryColumnSelection(parentId, target);
        return;
      }
      const existingAnchor = Number(state.libraryRangeFolderId || 0) === parentId
        ? state.libraryRangeAnchor
        : null;
      const fallbackAnchor = selectedEntryInFolder(parentId) || target;
      const anchor = existingAnchor && entries.some((item) => libraryEntryKey(item) === libraryEntryKey(existingAnchor))
        ? existingAnchor
        : fallbackAnchor;
      const anchorIndex = entries.findIndex((item) => libraryEntryKey(item) === libraryEntryKey(anchor));
      if (anchorIndex < 0) {
        setLibraryColumnSelection(parentId, target);
        return;
      }
      const start = Math.min(anchorIndex, targetIndex);
      const end = Math.max(anchorIndex, targetIndex);
      const keys = entries.slice(start, end + 1).map(libraryEntryKey);
      setLibraryColumnSelection(parentId, target, {rangeKeys: keys, anchor});
    }

    function requestLibraryColumnReveal(folderId, direction = "nearest") {
      state.libraryRevealColumnFolderId = Number(folderId || state.libraryActiveFolderId || state.libraryRootId);
      state.libraryRevealColumnDirection = direction;
    }

    function parentFolderId(folderId) {
      const displayRootId = libraryDisplayRootId();
      if (Number(folderId) === displayRootId) return displayRootId;
      const folder = libraryFolderById(folderId);
      return Number(folder?.parent_id || displayRootId);
    }

    function selectedLibraryPathFolderIds() {
      const ids = new Set();
      const displayRootId = libraryDisplayRootId();
      let currentFolderId = 0;
      if (state.librarySelection?.type === "folder") {
        currentFolderId = Number(state.librarySelection.id || 0);
      } else if (state.librarySelection?.type === "item") {
        currentFolderId = Number(libraryItemById(state.librarySelection.id)?.folder_id || 0);
      }
      const selectedFolderId = state.librarySelection?.type === "folder" ? Number(state.librarySelection.id || 0) : 0;
      let guard = 0;
      while (currentFolderId && guard < 64) {
        guard += 1;
        if (currentFolderId === displayRootId) break;
        const parentId = parentFolderId(currentFolderId);
        if (!parentId || parentId === currentFolderId) break;
        if (currentFolderId !== selectedFolderId) ids.add(currentFolderId);
        currentFolderId = parentId;
      }
      return ids;
    }

    function selectedEntryInFolder(folderId) {
      return ensureLibraryColumnSelection(folderId);
    }

    async function createLibraryFolder(parentId) {
      const res = await fetch("/api/library/folders", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({parent_id: parentId || state.libraryActiveFolderId || state.libraryRootId, name: "New Folder"})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not create folder");
      applyLibrarySnapshot(data);
      const targetParentId = Number(data.folder?.parent_id || parentId || state.libraryActiveFolderId || state.libraryRootId);
      if (data.folder?.id) setLibraryColumnSelection(targetParentId, {type: "folder", id: Number(data.folder.id)});
      renderLibrary();
    }

    function beginLibraryEntryRename(type, id) {
      const entryId = Number(id || 0);
      if (!entryId) return;
      if (type === "folder") {
        if (entryId === Number(state.libraryRootId) || !libraryFolderById(entryId)) return;
        setLibraryColumnSelection(parentFolderId(entryId), {type: "folder", id: entryId});
        state.libraryRenamingFolderId = entryId;
        state.libraryRenamingItemId = 0;
      } else if (type === "item") {
        const item = libraryItemById(entryId);
        if (!item) return;
        setLibraryColumnSelection(Number(item.folder_id || state.libraryRootId), {type: "item", id: entryId});
        state.libraryRenamingFolderId = 0;
        state.libraryRenamingItemId = entryId;
      }
      renderLibrary();
    }

    function beginLibraryFolderRename(folderId) {
      beginLibraryEntryRename("folder", folderId);
    }

    function cancelLibraryEntryRename() {
      state.libraryRenamingFolderId = 0;
      state.libraryRenamingItemId = 0;
      renderLibrary();
    }

    function cancelLibraryFolderRename() {
      cancelLibraryEntryRename();
    }

    async function commitLibraryEntryRename(type, id, name) {
      const entryId = Number(id || 0);
      if (!entryId) return;
      if (type === "folder" && entryId === Number(state.libraryRootId)) return;
      const res = await fetch(type === "item" ? "/api/library/items/rename" : "/api/library/folders/rename", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(type === "item" ? {item_id: entryId, name} : {folder_id: entryId, name})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not rename entry");
      state.libraryRenamingFolderId = 0;
      state.libraryRenamingItemId = 0;
      applyLibrarySnapshot(data);
      const renamedItem = type === "item" ? libraryItemById(entryId) : null;
      const targetParentId = type === "item"
        ? Number(renamedItem?.folder_id || state.libraryRootId)
        : Number(data.folder?.parent_id || parentFolderId(entryId));
      setLibraryColumnSelection(targetParentId, {type, id: entryId});
      renderLibrary();
    }

    async function commitLibraryFolderRename(folderId, name) {
      await commitLibraryEntryRename("folder", folderId, name);
    }

    async function addPaperToLibrary(article, paperId) {
      const button = article.querySelector('[data-action="add-library"]');
      if (button) {
        button.disabled = true;
        button.textContent = "Adding...";
      }
      try {
        const res = await fetch("/api/library/items", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({paper_id: paperId, unsorted: true})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not add to library");
        applyLibrarySnapshot(data);
        if (button) button.textContent = "In Library";
      } catch (error) {
        if (button) {
          button.disabled = false;
          button.textContent = "Add to Library";
        }
        const status = article.querySelector('[data-role="status"]');
        if (status) {
          status.textContent = error.message;
          status.className = "status err";
        }
      }
    }

    async function moveLibraryEntry(type, id, targetFolderId) {
      const res = await fetch("/api/library/move", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({type, id, target_folder_id: targetFolderId})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not move library entry");
      applyLibrarySnapshot(data);
      setLibraryColumnSelection(Number(targetFolderId || state.libraryRootId), {type, id: Number(data.moved?.id || id)});
      renderLibrary();
    }

    async function reorderLibraryEntry(type, id, parentFolderId, targetId, position) {
      const res = await fetch("/api/library/reorder", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({type, id, parent_folder_id: parentFolderId, target_id: targetId, position})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not reorder library entry");
      applyLibrarySnapshot(data);
      setLibraryColumnSelection(Number(parentFolderId || state.libraryRootId), {type, id: Number(data.reordered?.id || id)});
      renderLibrary();
    }

    async function colorLibraryFolder(folderId, color) {
      const res = await fetch("/api/library/folders/color", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({folder_id: folderId, color})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not color folder");
      applyLibrarySnapshot(data);
      setLibraryColumnSelection(parentFolderId(folderId), {type: "folder", id: Number(data.folder?.id || folderId)});
      renderLibrary();
    }

    async function deleteLibraryEntry(type, id) {
      if (!type || !id) return;
      if (type === "folder" && libraryFolderById(id)?.protected) return;
      const parentId = type === "item"
        ? Number(libraryItemById(id)?.folder_id || state.libraryActiveFolderId || state.libraryRootId)
        : parentFolderId(id);
      const deletedEntry = {type, id: Number(id)};
      const entriesBeforeDelete = libraryEntriesForFolder(parentId);
      const res = await fetch("/api/library/delete", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({type, id})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not delete library entry");
      applyLibrarySnapshot(data);
      selectLibraryDeletionFallback(parentId, deletedEntry, entriesBeforeDelete);
      renderLibrary();
    }

    async function deleteSelectedLibraryEntries() {
      const selectedEntries = libraryRangeSelectionEntries()
        .filter((entry) => !(entry.type === "folder" && libraryFolderById(entry.id)?.protected));
      if (selectedEntries.length <= 1) {
        const selection = state.librarySelection;
        if (selection?.type && selection.id) await deleteLibraryEntry(selection.type, Number(selection.id));
        return;
      }
      const parentId = Number(state.libraryRangeFolderId || state.libraryActiveFolderId || state.libraryRootId);
      const entriesBeforeDelete = libraryEntriesForFolder(parentId);
      for (const entry of selectedEntries.slice().reverse()) {
        const stillExists = entry.type === "folder" ? libraryFolderById(entry.id) : libraryItemById(entry.id);
        if (!stillExists) continue;
        const res = await fetch("/api/library/delete", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({type: entry.type, id: entry.id})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not delete library entry");
        applyLibrarySnapshot(data);
      }
      clearLibraryRangeSelection();
      const lastDeleted = selectedEntries[selectedEntries.length - 1];
      selectLibraryDeletionFallback(parentId, lastDeleted, entriesBeforeDelete);
      renderLibrary();
    }

    function selectLibraryDeletionFallback(parentId, deletedEntry, entriesBeforeDelete) {
      const targetParentId = libraryFolderById(parentId) ? Number(parentId) : Number(state.libraryRootId);
      const deletedIndex = entriesBeforeDelete.findIndex((entry) => libraryEntryKey(entry) === libraryEntryKey(deletedEntry));
      const fallbackCandidates = [
        entriesBeforeDelete[deletedIndex + 1],
        entriesBeforeDelete[deletedIndex - 1]
      ].filter(Boolean);
      const nextSelection = fallbackCandidates.find((entry) => {
        if (entry.type === "folder") return Number(parentFolderId(entry.id)) === targetParentId;
        return Number(libraryItemById(entry.id)?.folder_id || 0) === targetParentId;
      });
      if (nextSelection) {
        setLibraryColumnSelection(targetParentId, nextSelection);
        return;
      }
      state.librarySelection = {type: "folder", id: targetParentId};
      state.libraryActiveFolderId = targetParentId;
      state.libraryCurrentFolderId = targetParentId;
    }

    async function recoverLibraryEntry(type, id) {
      if (!type || !id) return;
      const res = await fetch("/api/library/recover", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({type, id})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not recover library entry");
      applyLibrarySnapshot(data);
      const recoveredId = Number(data.recovered?.id || id);
      if (type === "item") {
        const item = libraryItemById(recoveredId);
        setLibraryColumnSelection(Number(item?.folder_id || libraryUnsortedFolderId()), {type: "item", id: recoveredId});
      } else {
        const folder = libraryFolderById(recoveredId);
        setLibraryColumnSelection(Number(folder?.parent_id || state.libraryRootId), {type: "folder", id: recoveredId});
      }
      renderLibrary();
    }

    async function pasteLibraryEntry(targetFolderId) {
      if (!state.libraryClipboard) return;
      const clipboard = state.libraryClipboard;
      const res = await fetch("/api/library/paste", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({type: clipboard.type, id: clipboard.id, target_folder_id: targetFolderId})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not paste library entry");
      applyLibrarySnapshot(data);
      const pastedId = Number(data.pasted?.id || 0);
      if (pastedId) {
        setLibraryColumnSelection(Number(targetFolderId || state.libraryRootId), {type: clipboard.type, id: pastedId});
      }
      renderLibrary();
    }

    async function removePaperFromLibrary(paper) {
      const paperId = paper?.paper_id;
      if (!paperId) return;
      const res = await fetch("/api/library/remove-paper", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({paper_id: paperId})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not remove paper from Library");
      const fallbackFolderId = Number(state.libraryActiveFolderId || libraryUnsortedFolderId() || state.libraryRootId);
      applyLibrarySnapshot(data);
      state.librarySelection = {type: "folder", id: libraryFolderById(fallbackFolderId) ? fallbackFolderId : state.libraryRootId};
      state.libraryActiveFolderId = state.librarySelection.id;
      state.libraryCurrentFolderId = state.librarySelection.id;
      renderLibrary();
    }

    function syncSelectedJournals() {
      const known = new Set(state.journals);
      state.selectedJournals = new Set([...state.selectedJournals].filter((journal) => known.has(journal)));
      if (!state.selectedJournals.size) state.journals.forEach((journal) => state.selectedJournals.add(journal));
    }

    function withPreprintJournals(journals) {
      const names = [...journals];
      PREPRINT_JOURNALS.forEach((journal) => {
        if (!names.includes(journal)) names.push(journal);
      });
      return names;
    }

    function renderCalendar() {
      if ($("todayLabel")) $("todayLabel").textContent = localIsoDate(new Date());
      $("monthLabel").textContent = fmtMonth(state.viewYear, state.viewMonth);
      const root = $("calendar");
      root.innerHTML = "";
      ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].forEach((day) => {
        const el = document.createElement("div");
        el.className = "weekday";
        el.textContent = day;
        root.appendChild(el);
      });

      const firstDay = new Date(state.viewYear, state.viewMonth - 1, 1);
      const startOffset = (firstDay.getDay() + 6) % 7;
      const days = new Date(state.viewYear, state.viewMonth, 0).getDate();
      for (let i = 0; i < startOffset; i++) {
        const blank = document.createElement("button");
        blank.className = "day out";
        blank.disabled = true;
        root.appendChild(blank);
      }
      for (let day = 1; day <= days; day++) {
        const iso = `${fmtMonth(state.viewYear, state.viewMonth)}-${String(day).padStart(2, "0")}`;
        const total = Object.values(state.counts[iso] || {}).reduce((sum, value) => sum + value, 0);
        const isFetching = state.fetchingDates.has(iso);
        const hasNoMatch = state.noMatchDates.has(iso);
        const button = document.createElement("button");
        button.className = `day${iso === state.selectedDate ? " active" : ""}${isFetching ? " fetching" : ""}${hasNoMatch ? " no-match" : ""}`;
        button.innerHTML = `<span class="daynum">${day}</span>${
          isFetching
            ? `<span class="fetching-dot" title="Fetching"></span>`
            : `<span class="count">${total || ""}</span>`
        }`;
        button.addEventListener("click", async () => {
          state.selectedDate = iso;
          state.activeReportJournal = "";
          renderCalendar();
          await loadReport();
        });
        root.appendChild(button);
      }
    }

    function renderFilters() {
      const counts = {};
      state.papers
        .filter((paper) => !isPreprintPaper(paper) && subjectMatches(paper))
        .forEach((paper) => counts[paper.journal] = (counts[paper.journal] || 0) + 1);
      const root = $("journalFilters");
      root.innerHTML = "";
      state.journals.filter((journal) => !PREPRINT_JOURNALS.has(journal)).forEach((journal) => {
        const label = document.createElement("label");
        label.className = "journal-toggle";
        label.innerHTML = `<input type="checkbox" ${state.selectedJournals.has(journal) ? "checked" : ""}>
          <span>${escapeHtml(journal)}</span><b>${counts[journal] || 0}</b>`;
        label.querySelector("input").addEventListener("change", (event) => {
          if (event.target.checked) state.selectedJournals.add(journal);
          else state.selectedJournals.delete(journal);
          state.noMatchDates = new Set();
          renderReport();
        });
        root.appendChild(label);
      });
      renderPreprintFilters();
    }

    function renderPreprintFilters() {
      const root = $("preprintFilters");
      const categoryRoot = $("preprintCategoryFilters");
      if (!root || !categoryRoot) return;
      const arxivPapers = state.papers.filter((paper) => isPreprintPaper(paper) && subjectMatches(paper));
      root.innerHTML = "";
      const row = document.createElement("div");
      row.className = "preprint-filter-row";
      const label = document.createElement("label");
      label.className = "journal-toggle";
      label.innerHTML = `<input type="checkbox" ${state.selectedJournals.has("arXiv") ? "checked" : ""}>
        <span>arXiv</span><b>${arxivPapers.length}</b>`;
      label.querySelector("input").addEventListener("change", (event) => {
        if (event.target.checked) state.selectedJournals.add("arXiv");
        else state.selectedJournals.delete("arXiv");
        state.noMatchDates = new Set();
        renderFilters();
        renderReport();
      });
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "preprint-collapse-toggle";
      toggle.textContent = state.preprintFiltersExpanded ? "▲" : "▼";
      toggle.title = state.preprintFiltersExpanded ? "Hide arXiv categories" : "Show arXiv categories";
      toggle.setAttribute("aria-label", toggle.title);
      toggle.setAttribute("aria-expanded", state.preprintFiltersExpanded ? "true" : "false");
      toggle.addEventListener("click", () => {
        state.preprintFiltersExpanded = !state.preprintFiltersExpanded;
        renderPreprintFilters();
      });
      row.appendChild(label);
      row.appendChild(toggle);
      root.appendChild(row);

      const counts = {};
      arxivPapers.forEach((paper) => {
        paperPreprintCategories(paper).forEach((category) => counts[category] = (counts[category] || 0) + 1);
      });
      categoryRoot.innerHTML = "";
      categoryRoot.hidden = !state.preprintFiltersExpanded;
      categoryRoot.setAttribute("aria-hidden", state.preprintFiltersExpanded ? "false" : "true");
      ARXIV_CATEGORIES.forEach(([code, title]) => {
        const categoryLabel = document.createElement("label");
        categoryLabel.className = "preprint-category-toggle";
        categoryLabel.innerHTML = `<input type="checkbox" ${state.selectedPreprintCategories.has(code) ? "checked" : ""}>
          <span>${escapeHtml(code)} · ${escapeHtml(title)}</span><b>${counts[code] || 0}</b>`;
        categoryLabel.querySelector("input").addEventListener("change", (event) => {
          if (event.target.checked) state.selectedPreprintCategories.add(code);
          else state.selectedPreprintCategories.delete(code);
          state.noMatchDates = new Set();
          renderFilters();
          renderReport();
        });
        categoryRoot.appendChild(categoryLabel);
      });
    }

    function renderSubjectFilters() {
      const options = [
        ["physics", FIELD_LABELS.physics],
        ["quantum_information", FIELD_LABELS.quantum_information],
        ["materials", FIELD_LABELS.materials],
        ["chemistry", FIELD_LABELS.chemistry],
        ["all", FIELD_LABELS.all],
        ["other", FIELD_LABELS.other]
      ];
      const root = $("subjectFilters");
      root.innerHTML = "";
      options.forEach(([value, label]) => {
        const count = state.papers.filter((paper) => paperMatchesField(paper, value)).length;
        const button = document.createElement("button");
        button.className = `subject-option${fieldIsActive(value) ? " active" : ""}`;
        button.textContent = `${label} (${count})`;
        button.addEventListener("click", () => {
          toggleFieldFilter(value);
          state.noMatchDates = new Set();
          renderSubjectFilters();
          renderFilters();
          renderReport();
        });
        root.appendChild(button);
      });
    }

    function fieldIsActive(value) {
      return state.selectedFields.has(value);
    }

    function toggleFieldFilter(value) {
      if (value === "all") {
        state.selectedFields = new Set(["all"]);
        return;
      }
      const next = new Set([...state.selectedFields].filter((field) => field !== "all"));
      if (next.has(value)) next.delete(value);
      else next.add(value);
      state.selectedFields = next.size ? next : new Set(["all"]);
    }

    async function loadJournalSettings() {
      const res = await fetch("/api/journals");
      const data = await res.json();
      state.journalsConfig = data.journals || [];
      state.journalHistory = data.history || [];
      renderJournalSettings();
      renderJournalHistory();
    }

    function renderJournalSettings() {
      const root = $("journalSettings");
      root.innerHTML = "";
      state.journalsConfig.forEach((journal) => {
        const row = document.createElement("div");
        row.className = "journal-setting-row";
        row.innerHTML = `<span class="journal-setting-name">${escapeHtml(journal.name)}</span><button class="action" type="button">Remove</button>`;
        row.querySelector("button").addEventListener("click", (event) => {
          event.stopPropagation();
          removeJournal(journal.name);
        });
        root.appendChild(row);
      });
    }

    function renderJournalHistory() {
      const select = $("journalHistory");
      if (!select) return;
      select.innerHTML = `<option value="">Previously added journals</option>` + state.journalHistory
        .map((journal) => `<option value="${escapeAttr(journal.name)}">${escapeHtml(journal.name)}</option>`)
        .join("");
    }

    async function addJournal() {
      const name = $("journalName").value.trim();
      const issns = $("journalIssns").value.split(",").map((value) => value.trim()).filter(Boolean);
      if (!name) return;
      const res = await fetch("/api/journals/add", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name, issns})
      });
      const data = await res.json();
      if (!res.ok) {
        $("papers").innerHTML = `<div class="empty">${escapeHtml(data.error || "Could not add journal.")}</div>` + $("papers").innerHTML;
        return;
      }
      $("journalName").value = "";
      $("journalIssns").value = "";
      state.reportCache = {};
      state.journalsConfig = data.journals || state.journalsConfig;
      state.journalHistory = data.history || state.journalHistory;
      state.journals = withPreprintJournals((data.journals || []).map((journal) => journal.name));
      syncSelectedJournals();
      renderJournalSettings();
      renderJournalHistory();
      await loadMonth();
      await loadReport();
    }

    async function removeJournal(name) {
      const res = await fetch("/api/journals/remove", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name})
      });
      const data = await res.json();
      if (!res.ok) {
        $("papers").innerHTML = `<div class="empty">${escapeHtml(data.error || "Could not remove journal.")}</div>` + $("papers").innerHTML;
        return;
      }
      state.reportCache = {};
      state.journalsConfig = data.journals || state.journalsConfig;
      state.journalHistory = data.history || state.journalHistory;
      state.journals = withPreprintJournals((data.journals || []).map((journal) => journal.name));
      syncSelectedJournals();
      renderJournalSettings();
      renderJournalHistory();
      await loadMonth();
      await loadReport();
    }

    function subjectMatches(paper) {
      if (state.selectedFields.has("all")) return true;
      return [...state.selectedFields].some((field) => paperMatchesField(paper, field));
    }

    function isPreprintPaper(paper) {
      return PREPRINT_JOURNALS.has(paper.journal);
    }

    function paperPreprintCategories(paper) {
      const categories = Array.isArray(paper.preprint_categories) ? paper.preprint_categories : [];
      if (categories.length) return categories;
      return paper.preprint_category ? [paper.preprint_category] : [];
    }

    function preprintCategoryMatches(paper) {
      if (!isPreprintPaper(paper)) return true;
      const categories = paperPreprintCategories(paper);
      if (!categories.length) return true;
      return categories.some((category) => state.selectedPreprintCategories.has(category));
    }

    function paperMatchesField(paper, value) {
      if (value === "all") return true;
      const fields = Array.isArray(paper.fields) && paper.fields.length ? paper.fields : [paper.discipline || "other"];
      return fields.includes(value);
    }

    function paperFieldValues(paper) {
      const fields = Array.isArray(paper.fields) && paper.fields.length ? paper.fields : [paper.discipline || "other"];
      return [...new Set(fields.filter((field) => field && field !== "all"))];
    }

    function renderReport() {
      state.mode = "report";
      closeLibraryQuickLook();
      stopArxivUpdateCountdown();
      updateToolbarLibraryImport();
      $("libraryControls").classList.remove("open");
      setPrimaryView("report");
      $("reportTitle").textContent = `${state.selectedDate} Report`;
      const query = state.query.trim().toLowerCase();
      const filtered = state.papers.filter((paper) => {
        const inJournal = state.selectedJournals.has(paper.journal);
        const haystack = `${paper.title} ${paper.abstract} ${paper.doi} ${paper.preprint_id || ""} ${paper.preprint_category || ""} ${paper.journal} ${(paper.authors || []).join(" ")}`.toLowerCase();
        return inJournal && preprintCategoryMatches(paper) && subjectMatches(paper) && (!query || haystack.includes(query));
      });
      const selectedFieldText = [...state.selectedFields]
        .map((field) => FIELD_LABELS[field] || field)
        .join(", ");
      $("summary").textContent = `${state.papers.length} total · ${filtered.length} shown · Fields: ${selectedFieldText || "All Fields"}`;
      const root = $("papers");
      root.classList.remove("library-view");
      root.style.height = "";
      root.style.minHeight = "";
      root.innerHTML = "";
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      const fetchPending = reportFetchIsPending(state.selectedDate);
      if (fetchPending) {
        root.innerHTML = fetchProgressMarkup(state.selectedDate);
      }
      const groups = groupedReportPapers(filtered);
      if (!groups.length && fetchPending) {
        return;
      }
      if (!groups.length) {
        markNoMatchDate(state.selectedDate, true);
        root.innerHTML = `<div class="empty">No matching papers for this date.</div>`;
        return;
      } else {
        markNoMatchDate(state.selectedDate, false);
      }
      const currentGroup = groups.find((group) => group.journal === state.activeReportJournal);
      const firstNonEmptyGroup = groups.find((group) => group.papers.length);
      if (!currentGroup || (!currentGroup.papers.length && firstNonEmptyGroup)) {
        state.activeReportJournal = firstNonEmptyGroup?.journal || groups[0]?.journal || "";
      }
      renderReportTabs(groups);
      const activeGroup = groups.find((group) => group.journal === state.activeReportJournal) || groups[0];
      renderArxivUpdateCountdown(root, activeGroup?.journal || "");
      const activePapers = activeGroup?.papers || [];
      activePapers.forEach((paper) => root.appendChild(renderPaper(paper)));
      if (!activePapers.length) {
        root.insertAdjacentHTML("beforeend", `<div class="empty">No papers in this source for this date.</div>`);
      }
    }

    function renderReportTabs(groups) {
      const root = $("reportTabs");
      root.innerHTML = "";
      if (!groups.length) {
        root.classList.remove("open");
        return;
      }
      root.classList.add("open");
      groups.forEach((group) => {
        const button = document.createElement("button");
        button.className = `journal-tab${group.journal === state.activeReportJournal ? " active" : ""}`;
        button.type = "button";
        button.title = group.journal;
        const logoUrl = journalLogoUrl(group.journal);
        button.innerHTML = `
          <span class="journal-tab-label">${logoUrl ? `<img src="${escapeAttr(logoUrl)}" alt="${escapeAttr(group.journal)} logo">` : escapeHtml(group.journal)}</span>
          <span class="journal-tab-count">${group.papers.length}</span>
        `;
        const logo = button.querySelector("img");
        if (logo) {
          logo.addEventListener("error", () => {
            button.querySelector(".journal-tab-label").textContent = group.journal;
          }, {once: true});
        } else {
          hydrateJournalLogo(group.journal, button.querySelector(".journal-tab-label"), "");
        }
        button.addEventListener("click", () => {
          state.activeReportJournal = group.journal;
          renderReport();
        });
        root.appendChild(button);
      });
    }

    function renderArxivUpdateCountdown(root, journal) {
      if (journal !== "arXiv") return;
      const banner = document.createElement("div");
      banner.className = "arxiv-countdown";
      banner.innerHTML = `
        <div class="arxiv-countdown-main">
          <span>Next arXiv update in</span>
          <strong data-role="arxiv-countdown-time">-- min</strong>
        </div>
        <div class="arxiv-countdown-detail">
          <div data-role="arxiv-countdown-detail"></div>
          <div data-role="arxiv-submit-detail"></div>
        </div>
      `;
      root.appendChild(banner);
      const refresh = () => {
        const nextUpdate = nextArxivUpdateDate(new Date());
        const nextSubmit = nextArxivSubmissionCycleDate(new Date());
        const minutes = Math.max(0, Math.ceil((nextUpdate.getTime() - Date.now()) / 60000));
        const detail = new Intl.DateTimeFormat("en-US", {
          weekday: "short",
          hour: "2-digit",
          minute: "2-digit",
          timeZoneName: "short"
        }).format(nextUpdate);
        const submitDetail = new Intl.DateTimeFormat("en-US", {
          weekday: "short",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          timeZoneName: "short"
        }).format(nextSubmit);
        banner.querySelector('[data-role="arxiv-countdown-time"]').textContent = formatArxivCountdown(minutes);
        banner.querySelector('[data-role="arxiv-countdown-detail"]').textContent = `Next announcement: ${detail}`;
        banner.querySelector('[data-role="arxiv-submit-detail"]').textContent = `Best submit: ${submitDetail}`;
      };
      refresh();
      state.arxivCountdownTimer = window.setInterval(refresh, 1000);
    }

    function stopArxivUpdateCountdown() {
      if (!state.arxivCountdownTimer) return;
      window.clearInterval(state.arxivCountdownTimer);
      state.arxivCountdownTimer = null;
    }

    function markNoMatchDate(iso, value) {
      const before = state.noMatchDates.has(iso);
      if (value) state.noMatchDates.add(iso);
      else state.noMatchDates.delete(iso);
      if (before !== state.noMatchDates.has(iso)) renderCalendar();
    }

    function journalLogoUrl(name) {
      const needle = String(name || "").toLowerCase();
      const journal = state.journalsConfig.find((item) => String(item.name || "").toLowerCase() === needle);
      return journal?.logo_url || "";
    }

    async function hydrateJournalLogo(name, target, fallbackClass = "journal-group-text") {
      if (!name || state.logoRequests[name]) return;
      state.logoRequests[name] = true;
      try {
        const res = await fetch(`/api/journal-logo?name=${encodeURIComponent(name)}`);
        const data = await res.json();
        if (!res.ok || !data.logo_url) return;
        const journal = state.journalsConfig.find((item) => String(item.name || "").toLowerCase() === String(name).toLowerCase());
        if (journal) journal.logo_url = data.logo_url;
        if (!document.body.contains(target)) return;
        target.innerHTML = `<img src="${escapeAttr(data.logo_url)}" alt="${escapeAttr(name)} logo">`;
        const logo = target.querySelector("img");
        if (logo) {
          logo.addEventListener("error", () => {
            target.innerHTML = fallbackClass
              ? `<span class="${fallbackClass}">${escapeHtml(name)}</span>`
              : escapeHtml(name);
          }, {once: true});
        }
      } finally {
        delete state.logoRequests[name];
      }
    }

    function groupedReportPapers(papers) {
      const order = new Map(state.journals.map((journal, index) => [journal, index]));
      const groups = new Map();
      [...papers]
        .sort((a, b) => {
          const journalDelta = (order.get(a.journal) ?? 9999) - (order.get(b.journal) ?? 9999)
            || String(a.journal || "").localeCompare(String(b.journal || ""));
          if (journalDelta) return journalDelta;
          return String(a.publication_date || "").localeCompare(String(b.publication_date || ""))
            || String(a.title || "").localeCompare(String(b.title || ""));
        })
        .forEach((paper) => {
          const journal = paper.journal || "Unknown Journal";
          if (!groups.has(journal)) groups.set(journal, []);
          groups.get(journal).push(paper);
        });
      return [...groups].map(([journal, groupPapers]) => ({journal, papers: groupPapers}));
    }

    function fetchProgressMarkup(selectedDate) {
      const progress = state.fetchProgress[selectedDate] || {};
      const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
      const completed = Number(progress.completed || 0);
      const total = Number(progress.total || 0);
      const detail = total ? `${completed} / ${total} sources completed` : "Preparing fetch";
      return `
        <div class="empty fetch-progress">
          <div class="fetch-progress-head">
            <strong>Fetching papers for this date in the background. You can keep browsing other dates.</strong>
            <span>${percent}%</span>
          </div>
          <div class="fetch-progress-track"><div class="fetch-progress-bar" style="width:${percent}%"></div></div>
          <div>${detail}</div>
        </div>
      `;
    }

    function renderLibraryLoader() {
      state.mode = "library";
      state.libraryTab = "loader";
      stopArxivUpdateCountdown();
      renderLibraryTabs();
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("reportTitle").textContent = "Library Loader";
      $("summary").textContent = "";
      const root = $("papers");
      root.classList.add("library-view");
      const job = state.libraryImportJob || {};
      const result = state.libraryImportLastResult || job.result || null;
      const percent = Number(job.percent || 0);
      const status = state.libraryImportStatus || (job.status ? `${job.status} · ${job.stage || ""}` : "Idle");
      root.innerHTML = `
        <div class="loader-panel">
          <div class="loader-head">
            <div class="loader-head-main">
              <strong>Folder Loader</strong>
              <span class="loader-description">Import a folder into Library with a live log. Source files are never moved or deleted.</span>
            </div>
            <button class="smallbtn" id="loaderBackToLibrary" type="button">Back to Library</button>
          </div>
          <div class="loader-form">
            <input id="libraryImportPath" type="text" value="${escapeAttr(state.libraryImportPath || "")}" placeholder="/path/to/folder">
            <select id="libraryImportCopyMode" title="Import mode">
              <option value="copy"${(state.libraryImportCopyMode || "copy") === "copy" ? " selected" : ""}>Copy</option>
              <option value="link"${state.libraryImportCopyMode === "link" ? " selected" : ""}>Link</option>
            </select>
            <button class="smallbtn" id="libraryChooseFolder" type="button"${state.libraryImportBusy ? " disabled" : ""}>Choose Folder</button>
            <button class="smallbtn" id="libraryDryRunImport" type="button"${state.libraryImportBusy ? " disabled" : ""}>Dry Run</button>
            <button class="smallbtn" id="libraryRunImport" type="button"${state.libraryImportBusy ? " disabled" : ""}>Import</button>
          </div>
          <div class="loader-progress">
            <span id="libraryImportStatus">${escapeHtml(status)}</span>
            <span>${percent ? `${percent}%` : ""}</span>
            <div class="loader-progress-track"><div class="loader-progress-bar" style="width:${percent}%"></div></div>
          </div>
          ${result ? `<div class="loader-result">${escapeHtml(loaderResultSummary(result))}</div>` : ""}
          <div class="loader-main">
            <div class="loader-console" id="libraryLoaderConsole">${loaderConsoleMarkup(job)}</div>
            <aside class="loader-side" id="libraryLoaderSide">${loaderSideMarkup(result)}</aside>
          </div>
        </div>
      `;
      wireLibraryImportTools();
      wireLoaderSide();
      $("loaderBackToLibrary")?.addEventListener("click", async () => {
        stopLibraryImportPolling();
        await loadLibrary();
      });
      const consoleEl = $("libraryLoaderConsole");
      if (consoleEl) consoleEl.scrollTop = consoleEl.scrollHeight;
    }

    function loaderResultSummary(result) {
      return [
        `${result.created_papers || 0} created`,
        `${result.updated_papers || 0} updated`,
        `${result.resources_or_attachments_to_import || 0} resources/attachments`,
        `${result.reused_existing_files || 0} reused`,
        `${result.skipped || 0} skipped`,
        `${result.missing_source_files || 0} missing`,
        result.report_path ? `Report: ${result.report_path}` : ""
      ].filter(Boolean).join(" · ");
    }

    function loaderConsoleMarkup(job) {
      const logs = Array.isArray(job.logs) ? job.logs : [];
      if (!logs.length) return escapeHtml("Ready. Choose a folder, then run Dry Run before Import.");
      return logs.map((entry) => {
        const level = entry.level || "info";
        const time = String(entry.time || "").split("T").pop() || "";
        return `<div class="loader-line ${escapeAttr(level)}">[${escapeHtml(time)}] ${escapeHtml(entry.message || "")}</div>`;
      }).join("");
    }

    function loaderSideMarkup(result) {
      if (!result) {
        return `
          <h3>Result Guide</h3>
          <p>Run Dry Run first. After a loader job finishes, this panel explains each number and lists missing files.</p>
          <div class="loader-metric"><strong>Created</strong><span>new paper records.</span></div>
          <div class="loader-metric"><strong>Updated</strong><span>existing paper records matched by DOI, arXiv, or source path.</span></div>
          <div class="loader-metric"><strong>Resources</strong><span>PDF attachments plus non-PDF resource files.</span></div>
          <div class="loader-metric"><strong>Skipped</strong><span>system metadata and macOS aliases; source files are not deleted.</span></div>
          <div class="loader-metric"><strong>Missing</strong><span>paths recorded in the scan but not readable during import.</span></div>
        `;
      }
      const missing = Array.isArray(result.missing_sources) ? result.missing_sources : [];
      const selectedIndex = Math.max(0, Math.min(Number(state.libraryImportMissingIndex || 0), Math.max(0, missing.length - 1)));
      const selected = missing[selectedIndex] || null;
      return `
        <h3>Result Guide</h3>
        <div class="loader-metric"><strong>${result.created_papers || 0} created</strong><span>New paper records made in Journal Monitor.</span></div>
        <div class="loader-metric"><strong>${result.updated_papers || 0} updated</strong><span>Already-known papers matched and refreshed instead of duplicated.</span></div>
        <div class="loader-metric"><strong>${result.resources_or_attachments_to_import || 0} resources</strong><span>Imported PDF attachments plus non-PDF resources. This includes ${result.pdf_attachments_to_import || 0} PDF files and ${result.created_resources || 0} non-PDF resources.</span></div>
        <div class="loader-metric"><strong>${result.reused_existing_files || 0} reused</strong><span>Already-copied files reused from Journal Monitor storage, so repeated imports do not copy them again.</span></div>
        <div class="loader-metric"><strong>${result.skipped || 0} skipped</strong><span>${result.skipped_system_metadata || 0} system metadata and ${result.mac_aliases_found || 0} macOS aliases. Normal papers are not deleted by this.</span></div>
        <div class="loader-metric"><strong>${result.missing_source_files || 0} missing</strong><span>Source paths that could not be read during import. These need checking in Finder.</span></div>
        <div class="loader-metric"><strong>${result.duplicate_paper_candidates || 0} duplicates</strong><span>${result.doi_duplicates || 0} DOI duplicates and ${result.arxiv_duplicates || 0} arXiv duplicates were merged into existing paper records.</span></div>
        <h3 style="margin-top:12px;">Missing Files</h3>
        ${missing.length ? `
          <div class="loader-missing-tools">
            <select id="loaderMissingSelect">
              ${missing.map((item, index) => `<option value="${index}"${index === selectedIndex ? " selected" : ""}>${escapeHtml(`${index + 1}. ${item.filename || item.relative_path || item.source_path || "missing file"}`)}</option>`).join("")}
            </select>
            <button class="smallbtn" id="loaderRevealMissing" type="button">Show in Finder</button>
          </div>
          <div class="loader-missing-path">${escapeHtml(selected?.source_path || "")}</div>
        ` : `<p>No missing files reported.</p>`}
      `;
    }

    function wireLoaderSide() {
      const select = $("loaderMissingSelect");
      select?.addEventListener("change", () => {
        state.libraryImportMissingIndex = Number(select.value || 0);
        renderLibraryLoader();
      });
      $("loaderRevealMissing")?.addEventListener("click", () => revealSelectedMissingFile().catch((error) => {
        state.libraryImportStatus = error.message || "Could not open Finder";
        renderLibraryLoader();
      }));
    }

    async function revealSelectedMissingFile() {
      const result = state.libraryImportLastResult || state.libraryImportJob?.result || {};
      const missing = Array.isArray(result.missing_sources) ? result.missing_sources : [];
      const item = missing[Number(state.libraryImportMissingIndex || 0)];
      const path = item?.source_path || "";
      if (!path) throw new Error("No missing file selected");
      const res = await fetch("/api/reveal-path", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({path})
      });
      const data = await parseJsonResponse(res);
      if (!res.ok) throw new Error(data.error || "Could not open Finder");
    }

    function renderLibrary() {
      state.mode = "library";
      if (!state.libraryTab?.startsWith("shortcut-") && !state.libraryTab?.startsWith("workspace-")) state.libraryTab = "library";
      stopArxivUpdateCountdown();
      renderLibraryTabs();
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("reportTitle").textContent = libraryViewTitle();
      const root = $("papers");
      captureLibraryColumnScrollTops();
      const previousColumnsScrollLeft = $("libraryColumns")?.scrollLeft ?? state.libraryColumnsScrollLeft;
      $("summary").textContent = "";
      root.classList.add("library-view");
      root.innerHTML = `
        <div class="library-shell" id="libraryShell" tabindex="0">
          ${workspaceToolsMarkup()}
          ${librarySearchIsActive()
            ? `<div class="library-search-results" id="librarySearchResults"></div>`
            : `<div class="library-columns" id="libraryColumns"></div>`}
          <aside class="library-pane">
            <div class="library-pane-header">Details</div>
            <div class="library-detail" id="libraryDetail"></div>
          </aside>
        </div>
        <div class="library-context-menu" id="libraryContextMenu">
          <button type="button" data-action="new-folder">New Folder</button>
          <button type="button" data-action="rename-entry">Rename</button>
          <button type="button" data-action="color-folder">Color</button>
          <button type="button" data-action="copy-entry">Copy</button>
          <button type="button" data-action="paste-entry">Paste</button>
          <button type="button" data-action="recover-entry">Recover</button>
          <button type="button" data-action="delete-entry">Delete</button>
          <input class="library-color-input" data-action="folder-color-picker" type="color" value="#4f46e5">
        </div>
      `;
      resizeLibraryViewport();
      if (librarySearchIsActive()) renderLibrarySearchResults();
      else renderLibraryColumns();
      renderLibraryDetail();
      wireLibraryInteractions();
      wireWorkspaceTools();
      updateToolbarLibraryImport();
      restoreLibraryColumnScrollTops();
      const columns = $("libraryColumns");
      if (columns) {
        columns.scrollLeft = Math.max(0, previousColumnsScrollLeft);
        state.libraryColumnsScrollLeft = columns.scrollLeft;
        if (state.libraryRevealColumnFolderId) {
          const folderId = state.libraryRevealColumnFolderId;
          const direction = state.libraryRevealColumnDirection || "nearest";
          state.libraryRevealColumnFolderId = 0;
          state.libraryRevealColumnDirection = "";
          revealLibraryColumns(folderId, direction);
        }
      }
      window.requestAnimationFrame(() => {
        if (librarySearchIsActive()) revealLibrarySearchSelection();
        else revealLibrarySelectionInColumn(state.libraryActiveFolderId);
      });
    }

    function libraryViewTitle() {
      if (state.libraryTab?.startsWith("shortcut-")) return libraryShortcutLabel(Number(state.libraryTab.split("-")[1] || 0));
      if (state.libraryTab?.startsWith("workspace-")) return libraryWorkspaceLabel(Number(state.libraryTab.split("-")[1] || 0));
      return "Library";
    }

    function activeWorkspaceIndex() {
      return state.libraryTab?.startsWith("workspace-") ? Number(state.libraryTab.split("-")[1] || 0) : -1;
    }

    function workspaceToolsMarkup() {
      const index = activeWorkspaceIndex();
      if (index < 0) return "";
      return `
        <div class="workspace-tools">
          <input class="search" id="workspaceNameInput" value="${escapeAttr(libraryWorkspaceLabel(index))}" placeholder="Space name">
          <button class="smallbtn" id="workspaceRenameButton" type="button">Rename</button>
          <input class="search" id="workspaceDoiInput" placeholder="DOI">
          <button class="smallbtn" id="workspaceAddDoiButton" type="button">Add DOI</button>
          <span class="workspace-status" id="workspaceStatus">${escapeHtml(state.workspaceStatus || "This space works like Library. Add papers by DOI into its root.")}</span>
        </div>
      `;
    }

    function updateToolbarLibraryImport() {
      const tools = $("toolbarLibraryImport");
      const statusEl = $("libraryImportStatus");
      if (!tools || !statusEl) return;
      const open = state.mode === "library" && state.libraryTab === "library";
      tools.classList.toggle("open", open);
      if (!open) {
        statusEl.classList.remove("open", "ok", "err");
        return;
      }
      const pathInput = $("libraryImportPath");
      const copyMode = $("libraryImportCopyMode");
      if (pathInput && document.activeElement !== pathInput) pathInput.value = state.libraryImportPath || "";
      if (copyMode) copyMode.value = state.libraryImportCopyMode || "copy";
      const result = state.libraryImportLastResult || null;
      const summary = result ? [
        `${result.created_papers || 0} create`,
        `${result.updated_papers || 0} update`,
        `${result.resources_or_attachments_to_import || 0} resources`,
        `${result.skipped || 0} skipped`,
        `${result.missing_source_files || 0} missing`,
        result.report_path ? `Report: ${result.report_path}` : ""
      ].filter(Boolean).join(" · ") : "";
      const status = state.libraryImportStatus || summary || "";
      const statusClass = result?.errors?.length ? " err" : (result ? " ok" : "");
      statusEl.textContent = status;
      statusEl.className = `toolbar-import-status${status ? " open" : ""}${statusClass}`;
      ["libraryDryRunImport", "libraryRunImport"].forEach((id) => {
        const button = $(id);
        if (button) button.disabled = state.libraryImportBusy;
      });
    }

    function wireLibraryImportTools() {
      const pathInput = $("libraryImportPath");
      const copyMode = $("libraryImportCopyMode");
      [pathInput, copyMode].forEach((element) => {
        element?.addEventListener("click", (event) => event.stopPropagation());
        element?.addEventListener("keydown", (event) => event.stopPropagation());
      });
      pathInput?.addEventListener("input", () => {
        state.libraryImportPath = pathInput.value;
      });
      copyMode?.addEventListener("change", () => {
        state.libraryImportCopyMode = copyMode.value;
      });
      $("libraryChooseFolder")?.addEventListener("click", chooseLibraryImportFolder);
      $("libraryDryRunImport")?.addEventListener("click", () => runLibraryFolderImport(true));
      $("libraryRunImport")?.addEventListener("click", () => runLibraryFolderImport(false));
    }

    async function chooseLibraryImportFolder() {
      await runLibraryMenuAction(async () => {
        state.libraryImportStatus = "Waiting for macOS folder permission...";
        renderLibraryLoader();
        const res = await fetch("/api/library/import-folder/choose", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not choose folder");
        state.libraryImportPath = data.path || "";
        state.libraryImportStatus = "Folder selected. Run Dry Run before importing.";
        state.libraryImportLastResult = null;
        renderLibraryLoader();
      });
    }

    async function runLibraryFolderImport(dryRun) {
      const path = ($("libraryImportPath")?.value || state.libraryImportPath || "").trim();
      const copyMode = $("libraryImportCopyMode")?.value || state.libraryImportCopyMode || "copy";
      if (!path) {
        state.libraryImportStatus = "Folder path is required.";
        state.libraryImportLastResult = {errors: ["Folder path is required"]};
        renderLibraryLoader();
        return;
      }
      stopLibraryImportPolling();
      state.libraryImportBusy = true;
      state.libraryImportPath = path;
      state.libraryImportCopyMode = copyMode;
      state.libraryImportStatus = dryRun ? "Starting dry-run loader..." : "Starting import loader...";
      state.libraryImportLastResult = null;
      state.libraryImportJob = {status: "starting", stage: "queued", logs: [{time: new Date().toISOString(), level: "info", message: state.libraryImportStatus}], percent: 0};
      renderLibraryLoader();
      try {
        const res = await fetch("/api/library/import-folder/start", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({folder_path: path, copy_mode: copyMode, dry_run: dryRun})
        });
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not start loader");
        state.libraryImportJobId = data.job_id || "";
        state.libraryImportJob = data.job || null;
        state.libraryImportStatus = "Loader running...";
        renderLibraryLoader();
        startLibraryImportPolling();
      } catch (error) {
        state.libraryImportStatus = error.message || "Import failed";
        state.libraryImportLastResult = {errors: [state.libraryImportStatus]};
        state.libraryImportBusy = false;
        renderLibraryLoader();
      }
    }

    function startLibraryImportPolling() {
      stopLibraryImportPolling();
      if (!state.libraryImportJobId) return;
      state.libraryImportPoller = window.setInterval(refreshLibraryImportJob, 500);
      refreshLibraryImportJob();
    }

    function stopLibraryImportPolling() {
      if (!state.libraryImportPoller) return;
      window.clearInterval(state.libraryImportPoller);
      state.libraryImportPoller = null;
    }

    async function refreshLibraryImportJob() {
      if (!state.libraryImportJobId) return;
      try {
        const res = await fetch(`/api/library/import-folder/progress?job_id=${encodeURIComponent(state.libraryImportJobId)}`);
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not read loader progress");
        const job = data.job || {};
        state.libraryImportJob = job;
        state.libraryImportStatus = `${job.status || "running"}${job.stage ? ` · ${job.stage}` : ""}`;
        if (job.result) state.libraryImportLastResult = job.result;
        if (["completed", "failed"].includes(job.status)) {
          state.libraryImportBusy = false;
          stopLibraryImportPolling();
          if (job.status === "completed" && !job.dry_run) {
            const libraryRes = await fetch("/api/library");
            const libraryData = await libraryRes.json();
            if (libraryRes.ok) applyLibrarySnapshot(libraryData);
          }
        }
        if (state.mode === "library" && state.libraryTab === "loader") renderLibraryLoader();
      } catch (error) {
        state.libraryImportStatus = error.message || "Could not read loader progress";
        state.libraryImportBusy = false;
        stopLibraryImportPolling();
        if (state.mode === "library" && state.libraryTab === "loader") renderLibraryLoader();
      }
    }

    async function parseJsonResponse(res) {
      const text = await res.text();
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch (error) {
        return {error: text};
      }
    }

    function renderLibraryTabs() {
      $("libraryControls").classList.add("open");
      setPrimaryView("library");
      $("libraryTab")?.classList.toggle("active", state.libraryTab === "library");
      $("myPublicationsTab")?.classList.toggle("active", state.libraryTab === "my-publications");
      $("topLibraryLoader")?.classList.toggle("active", state.libraryTab === "loader");
      renderLibraryShortcutTabs();
      $("myPublicationsTools")?.classList.toggle("open", state.libraryTab === "my-publications");
      const nameInput = $("myPublicationName");
      if (nameInput && document.activeElement !== nameInput) nameInput.value = state.myPublicationName || "";
      const sortSelect = $("myPublicationSort");
      if (sortSelect) sortSelect.value = state.myPublicationSort || "time";
      updateToolbarLibraryImport();
      updateLibrarySearchTools();
    }

    function updateLibrarySearchTools() {
      const tools = $("librarySearchTools");
      const input = $("librarySearchBox");
      const clear = $("clearLibrarySearch");
      const count = $("librarySearchCount");
      if (!tools || !input || !clear || !count) return;
      const open = state.mode === "library" && !["loader", "my-publications"].includes(state.libraryTab || "");
      tools.classList.toggle("open", open);
      if (document.activeElement !== input) input.value = state.query || "";
      clear.classList.toggle("open", Boolean(state.query));
      const results = open && state.query.trim() ? librarySearchResults().length : 0;
      count.textContent = state.query.trim() ? `${results} match${results === 1 ? "" : "es"}` : "";
    }

    function renderLibraryShortcutTabs() {
      const root = $("libraryShortcutTabs");
      if (!root) return;
      const shortcutTabs = Array.from({length: LIBRARY_SHORTCUT_TAB_COUNT}, (_, index) => {
        const assigned = Boolean(Number(state.libraryShortcutTabs[index]?.folder_id || 0));
        const label = libraryShortcutLabel(index);
        return `<button class="library-tab shortcut-tab shortcut-tab-${index}${state.libraryTab === `shortcut-${index}` ? " active" : ""}" type="button" data-shortcut-tab="${index}" title="${assigned ? "Folder shortcut" : "Drop a Library folder here"}">${escapeHtml(label)}</button>`;
      }).join("");
      const workspaceTabs = Array.from({length: LIBRARY_WORKSPACE_TAB_COUNT}, (_, index) => (
        `<button class="library-tab workspace-tab workspace-tab-${index}${state.libraryTab === `workspace-${index}` ? " active" : ""}" type="button" data-workspace-tab="${index}" title="${escapeAttr(libraryWorkspaceLabel(index))}">${escapeHtml(libraryWorkspaceLabel(index))}</button>`
      )).join("");
      root.innerHTML = shortcutTabs + workspaceTabs;
      root.querySelectorAll("[data-shortcut-tab]").forEach((button) => {
        button.addEventListener("click", () => openLibraryShortcutTab(Number(button.dataset.shortcutTab || 0)));
        button.addEventListener("dragover", (event) => {
          const payload = libraryDragPayload(event);
          if (payload?.type !== "folder") return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
          button.classList.add("drag-over");
        });
        button.addEventListener("dragleave", () => button.classList.remove("drag-over"));
        button.addEventListener("drop", async (event) => {
          const payload = libraryDragPayload(event);
          if (payload?.type !== "folder") return;
          event.preventDefault();
          button.classList.remove("drag-over");
          state.libraryDragPayload = null;
          await runLibraryMenuAction(() => assignLibraryShortcutTab(Number(button.dataset.shortcutTab || 0), Number(payload.id || 0)));
        });
      });
      root.querySelectorAll("[data-workspace-tab]").forEach((button) => {
        button.addEventListener("click", () => openLibraryWorkspaceTab(Number(button.dataset.workspaceTab || 0)));
      });
    }

    async function openLibraryShortcutTab(index) {
      if (!state.libraryFolders.length) {
        const res = await fetch("/api/library");
        const data = await res.json();
        applyLibrarySnapshot(data);
      }
      const folderId = Number(state.libraryShortcutTabs[index]?.folder_id || 0);
      if (!folderId || !libraryFolderById(folderId)) return;
      state.libraryTab = `shortcut-${index}`;
      state.libraryActiveFolderId = folderId;
      state.libraryCurrentFolderId = folderId;
      state.librarySelection = {type: "folder", id: folderId};
      ensureLibraryColumnSelection(folderId);
      renderLibrary();
    }

    async function assignLibraryShortcutTab(index, folderId) {
      const res = await fetch("/api/library/shortcut-tabs", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({index, folder_id: folderId})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not assign shortcut");
      applyLibrarySnapshot(data);
      await openLibraryShortcutTab(index);
    }

    async function openLibraryWorkspaceTab(index) {
      if (!state.libraryWorkspaceTabs.length) {
        const res = await fetch("/api/library");
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not load Library spaces");
        applyLibrarySnapshot(data);
      }
      const folderId = Number(state.libraryWorkspaceTabs[index]?.root_folder_id || 0);
      if (!folderId || !libraryFolderById(folderId)) return;
      state.libraryTab = `workspace-${index}`;
      state.activeWorkspaceIndex = index;
      state.libraryActiveFolderId = folderId;
      state.libraryCurrentFolderId = folderId;
      state.librarySelection = {type: "folder", id: folderId};
      ensureLibraryColumnSelection(folderId);
      renderLibrary();
    }

    async function renameLibraryWorkspace(index) {
      const label = $("workspaceNameInput")?.value || `Space ${index + 1}`;
      const res = await fetch("/api/library/workspace-tabs/rename", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({index, label})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not rename space");
      applyLibrarySnapshot(data);
      state.workspaceStatus = "Space renamed.";
      state.libraryTab = `workspace-${index}`;
      renderLibrary();
    }

    async function addLibraryWorkspaceDoi(index) {
      const doi = $("workspaceDoiInput")?.value || "";
      if (!doi.trim()) return;
      state.workspaceStatus = "Looking up DOI...";
      state.libraryTab = `workspace-${index}`;
      renderLibrary();
      try {
        const res = await fetch("/api/library/workspace-tabs/add-doi", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({index, doi})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not add DOI");
        applyLibrarySnapshot(data);
        const rootFolderId = Number(state.libraryWorkspaceTabs[index]?.root_folder_id || libraryDisplayRootId());
        const added = state.libraryItems.find((item) => String(item.paper_id || "") === String(data.paper_id || "") && Number(item.folder_id) === rootFolderId);
        if (added) {
          state.libraryActiveFolderId = rootFolderId;
          state.librarySelection = {type: "item", id: Number(added.id)};
          setLibraryColumnSelection(rootFolderId, state.librarySelection);
        }
        state.workspaceStatus = "Literature added.";
        state.libraryTab = `workspace-${index}`;
        renderLibrary();
      } catch (error) {
        state.workspaceStatus = error.message || "Could not add DOI";
        state.libraryTab = `workspace-${index}`;
        renderLibrary();
      }
    }

    function wireWorkspaceTools() {
      const index = activeWorkspaceIndex();
      if (index < 0) return;
      $("workspaceRenameButton")?.addEventListener("click", (event) => {
        event.stopPropagation();
        runLibraryMenuAction(() => renameLibraryWorkspace(index));
      });
      $("workspaceNameInput")?.addEventListener("click", (event) => event.stopPropagation());
      $("workspaceNameInput")?.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          runLibraryMenuAction(() => renameLibraryWorkspace(index));
        }
      });
      $("workspaceAddDoiButton")?.addEventListener("click", (event) => {
        event.stopPropagation();
        runLibraryMenuAction(() => addLibraryWorkspaceDoi(index));
      });
      $("workspaceDoiInput")?.addEventListener("click", (event) => event.stopPropagation());
      $("workspaceDoiInput")?.addEventListener("keydown", (event) => {
        event.stopPropagation();
        if (event.key === "Enter") {
          event.preventDefault();
          runLibraryMenuAction(() => addLibraryWorkspaceDoi(index));
        }
      });
    }

    function renderMyPublications() {
      state.mode = "library";
      state.libraryTab = "my-publications";
      stopArxivUpdateCountdown();
      renderLibraryTabs();
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("reportTitle").textContent = "Library";
      const rows = sortedMyPublications();
      const selected = myPublicationById(state.myPublicationSelectionId) || rows[0] || null;
      if (selected) state.myPublicationSelectionId = Number(selected.id);
      $("summary").textContent = `${state.myPublications.length} publications · Sort: ${state.myPublicationSort === "highlight" ? "Highlight" : "Time"}`;
      const root = $("papers");
      root.classList.add("library-view");
      root.innerHTML = `
        <div class="library-shell my-publications-shell" id="libraryShell" tabindex="0">
          <section class="my-publications-panel">
            <div class="my-publications-search">
              <div class="publication-search-status">${escapeHtml(state.myPublicationSearchStatus || "Use DOI, title, or your saved name to add publications.")}</div>
              <div class="publication-search-results" id="publicationSearchResults">${myPublicationSearchResultsMarkup()}</div>
            </div>
            <div class="my-publications-table-wrap">
              <table class="my-publications-table" style="--my-publications-table-width:${myPublicationTableWidth()}px">
                <colgroup>${myPublicationColgroupMarkup()}</colgroup>
                <thead>
                  <tr>${myPublicationHeaderMarkup()}</tr>
                </thead>
                <tbody>
                  ${rows.length ? rows.map((entry, index) => myPublicationRowMarkup(entry, index)).join("") : `<tr><td colspan="6"><div class="empty">No publications yet.</div></td></tr>`}
                </tbody>
              </table>
            </div>
          </section>
          <aside class="library-pane">
            <div class="library-pane-header">Details</div>
            <div class="library-detail" id="libraryDetail"></div>
          </aside>
        </div>
      `;
      resizeLibraryViewport();
      renderPublicationDetail();
      wireMyPublicationInteractions();
      window.requestAnimationFrame(() => revealMyPublicationSelection());
    }

    function myPublicationColumnWidth(key) {
      const column = MY_PUBLICATION_COLUMNS.find((item) => item.key === key);
      if (!column) return 120;
      const width = Number(state.myPublicationColumnWidths[key] || column.defaultWidth);
      return Math.max(column.minWidth, Math.min(column.maxWidth, width));
    }

    function myPublicationTableWidth() {
      return MY_PUBLICATION_COLUMNS.reduce((total, column) => total + myPublicationColumnWidth(column.key), 0);
    }

    function myPublicationColgroupMarkup() {
      return MY_PUBLICATION_COLUMNS
        .map((column) => `<col style="width:${myPublicationColumnWidth(column.key)}px">`)
        .join("");
    }

    function myPublicationHeaderMarkup() {
      return MY_PUBLICATION_COLUMNS.map((column) => `
        <th>
          <div class="my-publications-head-cell">
            ${escapeHtml(column.label)}
            <span class="my-publications-col-resizer" data-publication-col="${escapeAttr(column.key)}"></span>
          </div>
        </th>
      `).join("");
    }

    function myPublicationRowMarkup(entry, index) {
      const paper = entry.paper || {};
      const active = Number(entry.id) === Number(state.myPublicationSelectionId);
      return `
        <tr class="my-publications-row${active ? " active" : ""}" data-publication-id="${Number(entry.id)}">
          <td><button class="star-button${entry.starred ? " active" : ""}" type="button" data-action="toggle-publication-star" title="Highlight">${entry.starred ? "★" : "☆"}</button></td>
          <td>${index + 1}</td>
          <td>${escapeHtml(paper.publication_date || "")}</td>
          <td class="my-publications-id">${myPublicationIdMarkup(paper)}</td>
          <td>${escapeHtml(paper.title || "Untitled paper")}</td>
          <td><button class="action danger" type="button" data-action="delete-publication">Delete</button></td>
        </tr>
      `;
    }

    function myPublicationIdMarkup(paper) {
      const ref = paper?.nature_reference || {};
      if (paper?.preprint_id) {
        return `<em>${escapeHtml(paper.journal || "arXiv")}</em>:${escapeHtml(paper.preprint_id)}`;
      }
      const journal = ref.journal || paper?.journal || "";
      const volume = ref.volume || "";
      const pages = ref.pages || "";
      const parts = [];
      if (journal) parts.push(`<em>${escapeHtml(journal)}</em>`);
      if (volume) parts.push(`<strong>${escapeHtml(volume)}</strong>${pages ? `, ${escapeHtml(pages)}` : ""}`);
      else if (pages) parts.push(escapeHtml(pages));
      if (!parts.length && paper?.doi) parts.push(`doi:${escapeHtml(paper.doi)}`);
      return parts.join(" ") || escapeHtml(paper?.citation_label || "");
    }

    function myPublicationSearchResultsMarkup() {
      const results = state.myPublicationSearchResults || [];
      if (!results.length) return "";
      return results.map((candidate, index) => {
        const paper = candidate.paper || {};
        return `
          <div class="publication-search-result" data-search-index="${index}">
            <div>
              <strong>${escapeHtml(paper.title || "Untitled paper")}</strong>
              <span>${escapeHtml([paper.journal, paper.publication_date, paper.doi].filter(Boolean).join(" · "))}</span>
            </div>
            <button class="smallbtn" type="button" data-action="add-publication-result">Add</button>
          </div>
        `;
      }).join("");
    }

    function resizeLibraryViewport() {
      if (state.mode !== "library") return;
      const root = $("papers");
      const reportColumn = root?.closest(".report-column");
      if (!root || !reportColumn) return;
      const columnRect = reportColumn.getBoundingClientRect();
      const rootRect = root.getBoundingClientRect();
      const availableHeight = Math.max(280, Math.floor(columnRect.bottom - rootRect.top));
      root.style.height = `${availableHeight}px`;
      root.style.minHeight = `${availableHeight}px`;
      const shell = $("libraryShell");
      if (shell) {
        shell.style.height = `${availableHeight}px`;
        shell.style.minHeight = `${availableHeight}px`;
      }
    }

    function captureLibraryColumnScrollTops() {
      document.querySelectorAll("[data-library-column-folder]").forEach((column) => {
        const folderId = Number(column.dataset.libraryColumnFolder || 0);
        const body = column.querySelector(".library-column-body");
        if (folderId && body) state.libraryColumnScrollTops[folderId] = body.scrollTop;
      });
    }

    function restoreLibraryColumnScrollTops() {
      document.querySelectorAll("[data-library-column-folder]").forEach((column) => {
        const folderId = Number(column.dataset.libraryColumnFolder || 0);
        const body = column.querySelector(".library-column-body");
        if (!folderId || !body) return;
        body.scrollTop = state.libraryColumnScrollTops[folderId] || 0;
      });
    }

    function revealLibraryColumns(folderId, direction = "nearest") {
      const columns = $("libraryColumns");
      if (!columns) return;
      const allColumns = [...columns.querySelectorAll("[data-library-column-folder]")];
      const column = allColumns.find((item) => Number(item.dataset.libraryColumnFolder) === Number(folderId));
      if (!column) return;
      const columnIndex = allColumns.indexOf(column);
      const rightRevealColumn = allColumns[columnIndex + 1] || column;
      const revealColumn = direction === "right" ? rightRevealColumn : column;
      const padding = 12;
      const targetLeft = column.offsetLeft;
      const targetRight = column.offsetLeft + column.offsetWidth;
      const revealLeft = revealColumn.offsetLeft;
      const revealRight = revealColumn.offsetLeft + revealColumn.offsetWidth;
      const viewLeft = columns.scrollLeft;
      const viewRight = viewLeft + columns.clientWidth;
      let target = columns.scrollLeft;
      if (direction === "left") {
        if (targetLeft - padding < viewLeft) target = targetLeft - padding;
        else if (targetRight + padding > viewRight) target = targetRight + padding - columns.clientWidth;
      } else if (direction === "right") {
        if (revealRight + padding > viewRight) target = revealRight + padding - columns.clientWidth;
        else if (revealLeft - padding < viewLeft) target = revealLeft - padding;
      } else if (revealRight + padding > viewRight) {
        target = revealRight + padding - columns.clientWidth;
      } else if (revealLeft - padding < viewLeft) {
        target = revealLeft - padding;
      }
      const maxScroll = Math.max(0, columns.scrollWidth - columns.clientWidth);
      const nextScrollLeft = Math.max(0, Math.min(maxScroll, target));
      if (Math.abs(nextScrollLeft - columns.scrollLeft) < 1) return;
      columns.scrollLeft = nextScrollLeft;
      state.libraryColumnsScrollLeft = nextScrollLeft;
    }

    function revealLibrarySelectionInColumn(folderId) {
      const column = document.querySelector(`[data-library-column-folder="${Number(folderId || 0)}"]`);
      const body = column?.querySelector(".library-column-body");
      const row = column?.querySelector(".library-row.active");
      if (!body || !row) return;
      const bodyRect = body.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      const padding = 6;
      if (rowRect.bottom > bodyRect.bottom - padding) {
        body.scrollTop += rowRect.bottom - bodyRect.bottom + padding;
      } else if (rowRect.top < bodyRect.top + padding) {
        body.scrollTop -= bodyRect.top - rowRect.top + padding;
      }
      state.libraryColumnScrollTops[Number(folderId)] = body.scrollTop;
    }

    function revealLibrarySearchSelection() {
      const root = $("librarySearchResults");
      const body = root?.querySelector(".library-search-results-body");
      const row = root?.querySelector(".library-row.active");
      if (!body || !row) return;
      const bodyRect = body.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      const padding = 6;
      if (rowRect.bottom > bodyRect.bottom - padding) {
        body.scrollTop += rowRect.bottom - bodyRect.bottom + padding;
      } else if (rowRect.top < bodyRect.top + padding) {
        body.scrollTop -= bodyRect.top - rowRect.top + padding;
      }
    }

    function startLibraryColumnResize(event, folderId) {
      const column = event.currentTarget.closest(".library-column");
      if (!column || !folderId) return;
      event.preventDefault();
      event.stopPropagation();
      const startX = event.clientX;
      const startWidth = column.getBoundingClientRect().width;
      column.classList.add("resizing");
      document.body.classList.add("resizing");
      const move = (moveEvent) => {
        const width = Math.max(180, Math.min(520, Math.round(startWidth + moveEvent.clientX - startX)));
        state.libraryColumnWidths[folderId] = width;
        column.style.setProperty("--library-column-width", `${width}px`);
      };
      const stop = () => {
        column.classList.remove("resizing");
        document.body.classList.remove("resizing");
        $("libraryShell")?.focus({preventScroll: true});
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    }

    function renderLibraryColumns() {
      const root = $("libraryColumns");
      if (!root) return;
      const folderIds = libraryColumnFolderIds();
      const pathFolderIds = selectedLibraryPathFolderIds();
      root.innerHTML = folderIds.map((folderId) => libraryColumnMarkup(folderId, pathFolderIds)).join("");
    }

    function libraryColumnFolderIds() {
      const folderIds = [Number(libraryDisplayRootId() || 1)];
      let folderId = folderIds[0];
      const seen = new Set(folderIds);
      for (let depth = 0; depth < 24; depth += 1) {
        const selection = selectedEntryInFolder(folderId);
        if (!selection || selection.type !== "folder") break;
        const nextFolderId = Number(selection.id);
        if (seen.has(nextFolderId) || !libraryFolderById(nextFolderId)) break;
        folderIds.push(nextFolderId);
        seen.add(nextFolderId);
        folderId = nextFolderId;
      }
      return folderIds;
    }

    function libraryColumnMarkup(folderId, pathFolderIds = new Set()) {
      const folder = libraryFolderById(folderId) || {name: "Library"};
      const entries = libraryEntriesForFolder(folderId);
      const rows = entries.map((entry) => {
        const data = entry.type === "folder" ? libraryFolderById(entry.id) : libraryItemById(entry.id);
        return data ? libraryRowMarkup(entry.type, data, folderId, pathFolderIds) : "";
      }).join("");
      const width = Number(state.libraryColumnWidths[folderId] || 260);
      return `
        <section class="library-column" data-library-column-folder="${folderId}" data-library-drop-folder="${folderId}" style="--library-column-width:${Math.max(180, Math.min(520, width))}px">
          <div class="library-pane-header">${escapeHtml(folder.name || "Library")}</div>
          <div class="library-column-body">
            ${rows || `<div class="empty">Right-click to create a folder, or add papers from Report.</div>`}
          </div>
          <div class="library-column-resizer" data-library-resize-folder="${folderId}" title="Resize column"></div>
        </section>
      `;
    }

    function renderLibrarySearchResults() {
      const root = $("librarySearchResults");
      if (!root) return;
      const results = librarySearchResults();
      const visibleResults = results.slice(0, 400);
      const rows = visibleResults.map((result) => {
        const entry = result.type === "folder" ? libraryFolderById(result.id) : libraryItemById(result.id);
        return entry ? librarySearchResultRowMarkup(result.type, entry, result.parentFolderId, result.path) : "";
      }).join("");
      const trimmed = results.length > visibleResults.length
        ? `<div class="empty">${results.length - visibleResults.length} more matches hidden. Refine the search.</div>`
        : "";
      root.innerHTML = `
        <div class="library-pane-header">Search Results</div>
        <div class="library-search-results-body">
          ${rows || `<div class="empty">No Library matches for "${escapeHtml(state.query.trim())}".</div>`}
          ${trimmed}
        </div>
      `;
    }

    function librarySearchResultRowMarkup(type, entry, parentFolderId, path) {
      const id = Number(entry.id);
      const selected = libraryEntryKey(state.librarySelection) === libraryEntryKey({type, id});
      const paper = entry.paper || {};
      const name = type === "folder" ? entry.name : (entry.display_name || libraryPaperDisplayName(paper));
      const iconClass = type === "folder" ? "folder" : "document";
      const meta = type === "folder" ? "Folder" : (paper.journal || "Paper");
      return `
        <button class="library-row${selected ? " active" : ""}"
          type="button"
          draggable="false"
          data-library-type="${type}"
          data-library-id="${id}"
          data-library-parent-folder="${parentFolderId}"
          ${type === "folder" ? `data-library-drop-folder="${id}"` : ""}
          aria-selected="${selected ? "true" : "false"}">
          <span class="library-entry-icon ${iconClass}" aria-hidden="true"></span>
          <span class="library-name">
            ${escapeHtml(name)}
            <span class="library-search-path">${escapeHtml(path || "")}</span>
          </span>
          <span class="library-meta">${escapeHtml(meta)}</span>
        </button>
      `;
    }

    function libraryRowMarkup(type, entry, parentFolderId, pathFolderIds = new Set()) {
      const id = Number(entry.id);
      const selected = Number(parentFolderId) === Number(state.libraryActiveFolderId)
        && libraryEntryKey(state.librarySelection) === libraryEntryKey({type, id});
      const rangeSelected = libraryEntryIsRangeSelected(parentFolderId, {type, id});
      const paper = entry.paper || {};
      const name = type === "folder" ? entry.name : (entry.display_name || libraryPaperDisplayName(paper));
      const meta = type === "folder" ? libraryFolderItems(id).length : (paper.journal || "");
      const iconClass = type === "folder" ? "folder" : "document";
      const isSpecialFolder = type === "folder" && (entry.is_unsorted || entry.is_recycle);
      const isPathParent = type === "folder" && pathFolderIds.has(id) && !selected;
      const folderColor = type === "folder" ? libraryFolderTextColor(entry) : "";
      const renaming = (type === "folder" && Number(state.libraryRenamingFolderId || 0) === id)
        || (type === "item" && Number(state.libraryRenamingItemId || 0) === id);
      const rowTag = renaming ? "div" : "button";
      const draggable = !(type === "folder" && (entry.protected || id === state.libraryRootId));
      const rowAttrs = renaming
        ? ""
        : `type="button" draggable="${draggable ? "true" : "false"}"`;
      const nameMarkup = renaming
        ? `<input class="library-rename-input" data-library-rename-input data-library-rename-type="${type}" data-library-rename-id="${id}" value="${escapeAttr(name)}">`
        : escapeHtml(name);
      return `
        <${rowTag} class="library-row${rangeSelected ? " range-selected" : ""}${selected ? " active" : ""}${isPathParent ? " path-parent" : ""}${isSpecialFolder ? " special-folder" : ""}"
          ${rowAttrs}
          data-library-type="${type}"
          data-library-id="${id}"
          data-library-parent-folder="${parentFolderId}"
          ${type === "folder" ? `data-library-drop-folder="${id}"` : ""}
          aria-selected="${selected || rangeSelected ? "true" : "false"}">
          <span class="library-entry-icon ${iconClass}" aria-hidden="true"></span>
          <span class="library-name" ${folderColor ? `style="color:${escapeAttr(folderColor)}"` : ""}>${nameMarkup}</span>
          <span class="library-meta">${renaming ? "" : escapeHtml(String(meta || ""))}</span>
        </${rowTag}>
      `;
    }

    function libraryFolderTextColor(folder) {
      if (!folder) return "";
      if (folder.is_unsorted || folder.is_recycle) return "#667085";
      return isValidFolderColor(folder.color) ? folder.color : "";
    }

    function isValidFolderColor(color) {
      return /^#[0-9A-Fa-f]{6}$/.test(String(color || ""));
    }

    function libraryPaperDisplayName(paper) {
      const label = paper?.citation_label || paper?.title || "Untitled paper";
      return String(label).replace(/^(.+?) et al\.(\s+)/, "$1$2");
    }

    function libraryDetailFigureMarkup(paper) {
      if (!paper?.image_url) return "";
      return `
        <figure class="library-detail-figure">
          <img src="${escapeAttr(paper.image_url)}" alt="${escapeAttr(paper.title || "First figure")}" loading="lazy">
        </figure>
      `;
    }

    function libraryDetailAbstractMarkup(paper) {
      const abstract = String(paper?.abstract || "").trim();
      if (!abstract) return "";
      return `
        <section class="library-detail-abstract">
          <strong>Abstract</strong>
          <p>${escapeHtml(abstract)}</p>
        </section>
      `;
    }

    function hydrateLibraryDetailFigureIfNeeded(paper) {
      if (!paper?.paper_id || paper.image_url || state.figureFailures.has(paper.paper_id)) return;
      queuePaperFigureHydration(paper.paper_id);
    }

    function authorsMarkup(authors) {
      if (!Array.isArray(authors) || !authors.length) return "Authors unavailable";
      return authors.map((author) => {
        const escaped = escapeHtml(author);
        return authorMatchesMyName(author) ? `<strong>${escaped}</strong>` : escaped;
      }).join(", ");
    }

    function authorMatchesMyName(author) {
      const targets = authorNameSignatures(currentMyPublicationName());
      const candidates = authorNameSignatures(author || "");
      return targets.some((target) => candidates.some((candidate) => authorSignaturesMatch(target, candidate)));
    }

    function currentMyPublicationName() {
      const input = $("myPublicationName");
      return (input?.value || state.myPublicationName || "").trim();
    }

    function authorSignaturesMatch(target, candidate) {
      if (!target.family || !candidate.family || target.family !== candidate.family) return false;
      if (target.givenFull && candidate.givenFull && target.givenFull === candidate.givenFull) return true;
      if (target.initials && candidate.initials && target.initials === candidate.initials) return true;
      if (target.initials && candidate.initials && (target.initials.startsWith(candidate.initials) || candidate.initials.startsWith(target.initials))) return true;
      if (target.givenFull && candidate.initials) return target.initials === candidate.initials;
      if (target.initials && candidate.givenFull) return target.initials === candidate.initials;
      return !target.givenFull && !candidate.givenFull;
    }

    function authorNameSignatures(value) {
      const clean = String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .replace(/[.,-]/g, " ")
        .replace(/[^a-zA-Z\s]/g, "")
        .replace(/\s+/g, " ")
        .trim()
        .toLowerCase();
      const parts = clean.split(" ").filter(Boolean);
      if (!parts.length) return [];
      const variants = [];
      const addVariant = (family, given) => {
        const signature = {
          family,
          givenFull: given.join(""),
          initials: given.map((part) => part[0] || "").join("")
        };
        if (!variants.some((item) => item.family === signature.family && item.givenFull === signature.givenFull && item.initials === signature.initials)) {
          variants.push(signature);
        }
      };
      addVariant(parts[parts.length - 1], parts.slice(0, -1));
      if (parts.length > 1) addVariant(parts[0], parts.slice(1));
      return variants;
    }

    function renderLibraryDetail() {
      const root = $("libraryDetail");
      if (!root) return;
      const selection = state.librarySelection;
      if (!selection) {
        root.innerHTML = `<div class="empty">Select a folder or paper.</div>`;
        return;
      }
      if (selection.type === "folder") {
        const folder = libraryFolderById(selection.id);
        const folders = libraryChildFolders(selection.id).length;
        const items = libraryFolderItems(selection.id).length;
        root.innerHTML = `
          <h3>${escapeHtml(folder?.name || "Folder")}</h3>
          <dl>
            <dt>Type</dt><dd>Folder</dd>
            <dt>Contains</dt><dd>${folders} folders · ${items} papers</dd>
          </dl>
        `;
        return;
      }
      const item = libraryItemById(selection.id);
      const paper = item?.paper || {};
      const authors = Array.isArray(paper.full_authors) && paper.full_authors.length
        ? paper.full_authors
        : (Array.isArray(paper.authors) ? paper.authors : []);
      root.innerHTML = `
        <h3>${escapeHtml(paper.title || "Untitled paper")}</h3>
        ${libraryDetailFigureMarkup(paper)}
        <div class="actions">
          ${paper.merged_pdf_path ? `<button class="action primary" data-action="preview-library-pdf">Open in Preview</button>` : ""}
          ${!paper.merged_pdf_path ? `<button class="action primary" data-action="download-library-pdf">Download PDF</button>` : ""}
          ${paper.url ? `<button class="action" data-action="open-library-page">Open Page</button>` : ""}
          ${paper.google_scholar_url ? `<button class="action" data-action="open-google-scholar">Google Scholar</button>` : ""}
          <button class="action danger" data-action="remove-library-paper">Remove from Library</button>
        </div>
        <div class="library-detail-status" id="libraryDetailStatus"></div>
        <dl>
          <dt>Citation</dt><dd>${escapeHtml(paper.citation_label || "")}</dd>
          <dt>Authors</dt><dd>${authorsMarkup(authors)}</dd>
          <dt>Journal</dt><dd>${escapeHtml(paper.journal || "")}</dd>
          <dt>Date</dt><dd>${escapeHtml(paper.publication_date || "")}</dd>
          <dt>DOI</dt><dd>${escapeHtml(paper.doi || paper.preprint_id || "")}</dd>
          <dt>Fields</dt><dd>${paperFieldValues(paper).map((field) => escapeHtml(FIELD_LABELS[field] || field)).join(", ")}</dd>
          <dt>PDF</dt><dd>${escapeHtml(paper.merged_pdf_path || "No local PDF")}</dd>
        </dl>
        ${libraryDetailAbstractMarkup(paper)}
        ${citationMetricsMarkup(paper)}
        <div class="library-reference-head">
          <strong>BibTeX</strong>
          <button class="action" data-action="copy-bibtex" data-copy-button data-default-label="Copy Code">Copy Code</button>
        </div>
        <pre class="bibtex-box">${escapeHtml(paper.bibtex || "")}</pre>
        <div class="library-reference-head">
          <strong>Nature Reference</strong>
          <button class="action" data-action="copy-nature-reference" data-copy-button data-default-label="Copy Reference">Copy Reference</button>
        </div>
        <div class="bibtex-box nature-reference-box">${natureReferenceMarkup(paper)}</div>
      `;
      root.querySelector('[data-action="preview-library-pdf"]')?.addEventListener("click", () => openLibraryPdfInPreview(paper));
      root.querySelector('[data-action="download-library-pdf"]')?.addEventListener("click", () => downloadLibraryPdf(paper));
      root.querySelector('[data-action="open-library-page"]')?.addEventListener("click", () => openLibraryPageExternally(paper));
      root.querySelector('[data-action="open-google-scholar"]')?.addEventListener("click", () => openLibraryExternalUrl(paper.google_scholar_url, "Opening Google Scholar...", "Google Scholar opened"));
      root.querySelector('[data-action="remove-library-paper"]')?.addEventListener("click", async () => {
        const status = $("libraryDetailStatus");
        try {
          await removePaperFromLibrary(paper);
        } catch (error) {
          if (status) {
            status.textContent = error.message || "Could not remove paper from Library";
            status.className = "library-detail-status err";
          }
        }
      });
      root.querySelector('[data-action="copy-bibtex"]')?.addEventListener("click", (event) => copyLibraryBibtex(paper, event.currentTarget));
      root.querySelector('[data-action="copy-nature-reference"]')?.addEventListener("click", (event) => copyLibraryNatureReference(paper, event.currentTarget));
      hydrateLibraryDetailFigureIfNeeded(paper);
    }

    function renderPublicationDetail() {
      const root = $("libraryDetail");
      if (!root) return;
      const paper = selectedMyPublicationPaper();
      if (!paper) {
        root.innerHTML = `<div class="empty">Select a publication.</div>`;
        return;
      }
      const authors = Array.isArray(paper.full_authors) && paper.full_authors.length
        ? paper.full_authors
        : (Array.isArray(paper.authors) ? paper.authors : []);
      root.innerHTML = `
        <h3>${escapeHtml(paper.title || "Untitled paper")}</h3>
        ${libraryDetailFigureMarkup(paper)}
        <div class="actions">
          ${paper.merged_pdf_path ? `<button class="action primary" data-action="preview-library-pdf">Open in Preview</button>` : ""}
          ${!paper.merged_pdf_path ? `<button class="action primary" data-action="download-library-pdf">Download PDF</button>` : ""}
          ${paper.url ? `<button class="action" data-action="open-library-page">Open Page</button>` : ""}
          ${paper.google_scholar_url ? `<button class="action" data-action="open-google-scholar">Google Scholar</button>` : ""}
        </div>
        <div class="library-detail-status" id="libraryDetailStatus"></div>
        <dl>
          <dt>Citation</dt><dd>${escapeHtml(paper.citation_label || "")}</dd>
          <dt>Authors</dt><dd>${authorsMarkup(authors)}</dd>
          <dt>Journal</dt><dd>${escapeHtml(paper.journal || "")}</dd>
          <dt>Date</dt><dd>${escapeHtml(paper.publication_date || "")}</dd>
          <dt>DOI</dt><dd>${escapeHtml(paper.doi || paper.preprint_id || "")}</dd>
          <dt>Fields</dt><dd>${paperFieldValues(paper).map((field) => escapeHtml(FIELD_LABELS[field] || field)).join(", ")}</dd>
          <dt>PDF</dt><dd>${escapeHtml(paper.merged_pdf_path || "No local PDF")}</dd>
        </dl>
        ${libraryDetailAbstractMarkup(paper)}
        ${citationMetricsMarkup(paper)}
        <div class="library-reference-head">
          <strong>BibTeX</strong>
          <button class="action" data-action="copy-bibtex" data-copy-button data-default-label="Copy Code">Copy Code</button>
        </div>
        <pre class="bibtex-box">${escapeHtml(paper.bibtex || "")}</pre>
        <div class="library-reference-head">
          <strong>Nature Reference</strong>
          <button class="action" data-action="copy-nature-reference" data-copy-button data-default-label="Copy Reference">Copy Reference</button>
        </div>
        <div class="bibtex-box nature-reference-box">${natureReferenceMarkup(paper)}</div>
      `;
      root.querySelector('[data-action="preview-library-pdf"]')?.addEventListener("click", () => openLibraryPdfInPreview(paper));
      root.querySelector('[data-action="download-library-pdf"]')?.addEventListener("click", () => downloadLibraryPdf(paper));
      root.querySelector('[data-action="open-library-page"]')?.addEventListener("click", () => openLibraryPageExternally(paper));
      root.querySelector('[data-action="open-google-scholar"]')?.addEventListener("click", () => openLibraryExternalUrl(paper.google_scholar_url, "Opening Google Scholar...", "Google Scholar opened"));
      root.querySelector('[data-action="copy-bibtex"]')?.addEventListener("click", (event) => copyLibraryBibtex(paper, event.currentTarget));
      root.querySelector('[data-action="copy-nature-reference"]')?.addEventListener("click", (event) => copyLibraryNatureReference(paper, event.currentTarget));
      hydrateLibraryDetailFigureIfNeeded(paper);
    }

    function citationMetricsMarkup(paper) {
      const metrics = paper.citation_metrics || {};
      const source = metrics.source || "Citation data";
      const rawCount = metrics.count;
      const count = rawCount === null || rawCount === undefined || rawCount === ""
        ? null
        : (Number.isFinite(Number(rawCount)) ? Number(rawCount) : null);
      const years = Array.isArray(metrics.by_year) ? metrics.by_year.filter((entry) => Number.isFinite(Number(entry.year)) && Number.isFinite(Number(entry.count))) : [];
      const max = Math.max(1, ...years.map((entry) => Number(entry.count)));
      const bars = years.length
        ? `<div class="citation-bars" aria-label="Yearly citation histogram">
            ${years.map((entry) => {
              const year = Number(entry.year);
              const value = Number(entry.count);
              const height = Math.max(2, Math.round((value / max) * 62));
              return `<div class="citation-bar-wrap" title="${escapeAttr(`${year}: ${value}`)}">
                <span class="citation-bar" style="height:${height}px"></span>
                <span>${escapeHtml(String(year).slice(-2))}</span>
              </div>`;
            }).join("")}
          </div>`
        : `<div class="citation-empty">Yearly citation histogram unavailable.</div>`;
      return `
        <section class="citation-panel">
          <div class="citation-summary">
            <strong>${escapeHtml(source)} Citations</strong>
            <span class="citation-count">${count === null ? "--" : escapeHtml(count)}</span>
          </div>
          ${bars}
        </section>
      `;
    }

    function natureReferenceMarkup(paper) {
      const ref = paper.nature_reference || {};
      const authors = ref.authors || "";
      const title = ref.title || "";
      const journal = ref.journal || "";
      const volume = ref.volume || "";
      const pages = ref.pages || "";
      const year = ref.year || "";
      const doi = ref.doi || "";
      const parts = [];
      if (authors) parts.push(referenceSentenceMarkup(authors));
      if (title) parts.push(`${escapeHtml(title)}.`);
      if (journal) parts.push(`<em>${escapeHtml(journal)}</em>`);
      if (volume) parts.push(`<strong>${escapeHtml(volume)}</strong>${pages ? `, ${escapeHtml(pages)}` : ""}`);
      else if (pages) parts.push(escapeHtml(pages));
      else if (doi) parts.push(`https://doi.org/${escapeHtml(doi)}`);
      const body = parts.join(" ");
      const suffix = year ? ` (${escapeHtml(year)}).` : ".";
      return body ? `${body}${suffix}` : escapeHtml(paper.citation_label || "");
    }

    function referenceSentenceMarkup(value) {
      const clean = String(value || "").trim();
      if (!clean) return "";
      return `${escapeHtml(clean.replace(/[.。]+$/g, ""))}.`;
    }

    function natureReferenceText(paper) {
      const ref = paper.nature_reference || {};
      const authors = ref.authors || "";
      const title = ref.title || "";
      const journal = ref.journal || "";
      const volume = ref.volume || "";
      const pages = ref.pages || "";
      const year = ref.year || "";
      const doi = ref.doi || "";
      const parts = [];
      if (authors) parts.push(referenceSentenceText(authors));
      if (title) parts.push(`${title}.`);
      if (journal) parts.push(journal);
      if (volume) parts.push(`${volume}${pages ? `, ${pages}` : ""}`);
      else if (pages) parts.push(pages);
      else if (doi) parts.push(`https://doi.org/${doi}`);
      const body = parts.join(" ");
      const suffix = year ? ` (${year}).` : ".";
      return body ? `${body}${suffix}` : (paper.citation_label || "");
    }

    function natureReferenceHtml(paper) {
      return `<span style="font-family:&quot;Times New Roman&quot;, Times, serif; font-size:12pt;">${natureReferenceMarkup(paper)}</span>`;
    }

    function referenceSentenceText(value) {
      const clean = String(value || "").trim();
      if (!clean) return "";
      return `${clean.replace(/[.。]+$/g, "")}.`;
    }

    function wireMyPublicationInteractions() {
      const shell = $("libraryShell");
      if (!shell) return;
      shell.querySelectorAll(".my-publications-row").forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest(".star-button") || event.target.closest('[data-action="delete-publication"]')) return;
          selectMyPublication(Number(row.dataset.publicationId || 0));
        });
      });
      shell.querySelectorAll('[data-action="toggle-publication-star"]').forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          const row = button.closest(".my-publications-row");
          const publication = myPublicationById(Number(row?.dataset.publicationId || 0));
          if (!publication) return;
          await toggleMyPublicationStar(publication, !publication.starred);
        });
      });
      shell.querySelectorAll('[data-action="delete-publication"]').forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          const row = button.closest(".my-publications-row");
          const publicationId = Number(row?.dataset.publicationId || 0);
          if (publicationId) await deleteMyPublication(publicationId);
        });
      });
      shell.querySelectorAll('[data-action="add-publication-result"]').forEach((button) => {
        button.addEventListener("click", async () => {
          const index = Number(button.closest("[data-search-index]")?.dataset.searchIndex || -1);
          const candidate = state.myPublicationSearchResults[index];
          if (candidate) await addMyPublicationCandidate(candidate);
        });
      });
      shell.querySelectorAll("[data-publication-col]").forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => startMyPublicationColumnResize(event, handle.dataset.publicationCol));
      });
      shell.addEventListener("click", () => shell.focus({preventScroll: true}));
    }

    function startMyPublicationColumnResize(event, key) {
      const column = MY_PUBLICATION_COLUMNS.find((item) => item.key === key);
      if (!column) return;
      event.preventDefault();
      event.stopPropagation();
      const startX = event.clientX;
      const startWidth = myPublicationColumnWidth(key);
      document.body.classList.add("resizing");
      const move = (moveEvent) => {
        const nextWidth = Math.max(column.minWidth, Math.min(column.maxWidth, Math.round(startWidth + moveEvent.clientX - startX)));
        state.myPublicationColumnWidths[key] = nextWidth;
        const table = document.querySelector(".my-publications-table");
        const colIndex = MY_PUBLICATION_COLUMNS.findIndex((item) => item.key === key) + 1;
        const col = table?.querySelector(`colgroup col:nth-child(${colIndex})`);
        if (col) col.style.width = `${nextWidth}px`;
        if (table) table.style.setProperty("--my-publications-table-width", `${myPublicationTableWidth()}px`);
      };
      const stop = () => {
        document.body.classList.remove("resizing");
        $("libraryShell")?.focus({preventScroll: true});
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    }

    function selectMyPublication(id) {
      if (!myPublicationById(id)) return;
      state.myPublicationSelectionId = Number(id);
      renderMyPublications();
      refreshLibraryQuickLookForSelection();
    }

    function revealMyPublicationSelection() {
      const row = document.querySelector(`.my-publications-row[data-publication-id="${Number(state.myPublicationSelectionId || 0)}"]`);
      row?.scrollIntoView({block: "nearest"});
    }

    async function toggleMyPublicationStar(publication, starred) {
      const res = await fetch("/api/my-publications/star", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({publication_id: publication.id, starred})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not update highlight");
      applyMyPublications(data);
      state.myPublicationSelectionId = Number(data.publication?.id || publication.id);
      renderMyPublications();
    }

    async function deleteMyPublication(publicationId) {
      const res = await fetch("/api/my-publications/delete", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({publication_id: publicationId})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not delete publication");
      applyMyPublications(data);
      const rows = sortedMyPublications();
      if (!myPublicationById(state.myPublicationSelectionId)) {
        state.myPublicationSelectionId = Number(rows[0]?.id || 0);
      }
      state.myPublicationSearchStatus = "Publication deleted.";
      renderMyPublications();
      refreshLibraryQuickLookForSelection();
    }

    async function saveMyPublicationName() {
      const value = $("myPublicationName")?.value || "";
      const res = await fetch("/api/my-publications/name", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({name: value})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not save name");
      state.myPublicationName = data.myName || "";
      renderLibraryTabs();
      refreshLibraryDetailAuthors();
    }

    function refreshLibraryDetailAuthors() {
      if (state.libraryTab === "my-publications") renderPublicationDetail();
      else if (state.libraryTab?.startsWith("workspace-")) renderLibraryDetail();
      else if (state.mode === "library") renderLibraryDetail();
    }

    async function searchMyPublications(kind = "auto") {
      const query = kind === "author" ? ($("myPublicationName")?.value || state.myPublicationName || "") : ($("publicationSearchBox")?.value || "");
      const cleanQuery = query.trim();
      if (!cleanQuery) return;
      if (kind === "author") await saveMyPublicationName();
      state.myPublicationSearchStatus = "Searching publications...";
      state.myPublicationSearchResults = [];
      renderMyPublications();
      try {
        const res = await fetch(`/api/publication-search?q=${encodeURIComponent(cleanQuery)}&kind=${encodeURIComponent(kind)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Search failed");
        state.myPublicationSearchResults = data.results || [];
        state.myPublicationSearchStatus = state.myPublicationSearchResults.length
          ? `${state.myPublicationSearchResults.length} candidates found.`
          : "No publication candidates found.";
      } catch (error) {
        state.myPublicationSearchStatus = error.message || "Search failed";
      }
      renderMyPublications();
    }

    async function addMyPublicationCandidate(candidate) {
      state.myPublicationSearchStatus = "Adding publication...";
      renderMyPublications();
      const res = await fetch("/api/my-publications/add", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({paper: candidate})
      });
      const data = await res.json();
      if (!res.ok) {
        state.myPublicationSearchStatus = data.error || "Could not add publication";
        renderMyPublications();
        return;
      }
      applyMyPublications(data);
      state.myPublicationSelectionId = Number(data.publication?.id || state.myPublicationSelectionId || 0);
      state.myPublicationSearchResults = [];
      state.myPublicationSearchStatus = "Publication added.";
      renderMyPublications();
    }

    function handleMyPublicationKeydown(event, key) {
      const rows = sortedMyPublications();
      if (!rows.length) return true;
      if (key === " ") {
        const paper = selectedMyPublicationPaper();
        if (paper?.merged_pdf_path) quickLookLibraryPdf(paper, {toggle: true});
        else if (state.libraryQuickLookOpen) showLibraryQuickLookPlaceholder();
        return true;
      }
      if (!["ArrowUp", "ArrowDown"].includes(key)) return false;
      const currentIndex = rows.findIndex((entry) => Number(entry.id) === Number(state.myPublicationSelectionId));
      const fallback = key === "ArrowDown" ? 0 : rows.length - 1;
      const nextIndex = currentIndex < 0
        ? fallback
        : Math.max(0, Math.min(rows.length - 1, currentIndex + (key === "ArrowDown" ? 1 : -1)));
      state.myPublicationSelectionId = Number(rows[nextIndex].id);
      renderMyPublications();
      refreshLibraryQuickLookForSelection();
      return true;
    }

    function wireLibraryInteractions() {
      const shell = $("libraryShell");
      if (!shell) return;
      const renameInput = shell.querySelector("[data-library-rename-input]");
      if (renameInput) {
        window.setTimeout(() => {
          renameInput.focus({preventScroll: true});
          renameInput.select();
        }, 0);
        let finished = false;
        const finish = async (save) => {
          if (finished) return;
          finished = true;
          if (!save) {
            cancelLibraryEntryRename();
            return;
          }
          try {
            await commitLibraryEntryRename(renameInput.dataset.libraryRenameType, Number(renameInput.dataset.libraryRenameId), renameInput.value);
          } catch (error) {
            state.libraryRenamingFolderId = 0;
            state.libraryRenamingItemId = 0;
            renderLibrary();
          }
        };
        renameInput.addEventListener("keydown", (event) => {
          event.stopPropagation();
          if (event.key === "Enter") {
            event.preventDefault();
            finish(true);
          }
          if (event.key === "Escape") {
            event.preventDefault();
            finish(false);
          }
        });
        renameInput.addEventListener("click", (event) => event.stopPropagation());
        renameInput.addEventListener("blur", () => finish(true));
      }
      shell.querySelectorAll(".library-row").forEach((row) => {
        row.addEventListener("click", (event) => {
          if (event.target.closest("[data-library-rename-input]")) return;
          const type = row.dataset.libraryType;
          const id = Number(row.dataset.libraryId);
          const parentFolderId = Number(row.dataset.libraryParentFolder || state.libraryRootId);
          selectLibraryEntry(parentFolderId, type, id, {
            extendRange: event.shiftKey,
            revealChildColumn: type === "folder" && !event.shiftKey
          });
        });
        row.addEventListener("dblclick", () => {
          if (row.dataset.libraryType === "folder") focusLibraryFolder(Number(row.dataset.libraryId));
        });
        row.addEventListener("dragstart", (event) => {
          if (row.getAttribute("draggable") === "false") {
            event.preventDefault();
            return;
          }
          const payload = {
            type: row.dataset.libraryType,
            id: Number(row.dataset.libraryId),
            parent_folder_id: Number(row.dataset.libraryParentFolder || state.libraryRootId)
          };
          state.libraryDragPayload = payload;
          event.dataTransfer.setData("application/x-paper-monitor-library", JSON.stringify(payload));
          event.dataTransfer.setData("text/plain", row.querySelector(".library-name")?.textContent || "");
          event.dataTransfer.effectAllowed = "copyMove";
        });
        row.addEventListener("dragend", () => {
          state.libraryDragPayload = null;
        });
        row.addEventListener("dragover", (event) => {
          const payload = libraryDragPayload(event);
          if (!payload || !libraryDropIsReorder(payload, row, event)) return;
          event.preventDefault();
          event.stopPropagation();
          markLibraryReorderTarget(row, event);
        });
        row.addEventListener("dragleave", () => clearLibraryDragClasses(row));
        row.addEventListener("drop", async (event) => {
          const payload = libraryDragPayload(event);
          if (!payload || !libraryDropIsReorder(payload, row, event)) return;
          event.preventDefault();
          event.stopPropagation();
          const position = libraryDropIntent(row, event);
          clearLibraryDragClasses(row);
          await reorderLibraryEntry(payload.type, Number(payload.id), Number(payload.parent_folder_id), Number(row.dataset.libraryId), position);
        });
        row.addEventListener("contextmenu", (event) => {
          event.stopPropagation();
          const type = row.dataset.libraryType;
          const id = Number(row.dataset.libraryId);
          const parentFolderId = Number(row.dataset.libraryParentFolder || state.libraryRootId);
          setLibraryColumnSelection(parentFolderId, {type, id});
          renderLibraryDetail();
          refreshLibraryQuickLookForSelection();
          const parentId = row.dataset.libraryDropFolder || row.dataset.libraryParentFolder || state.libraryActiveFolderId;
          showLibraryContextMenu(event, parentId, type, id);
        });
      });
      shell.querySelectorAll("[data-library-drop-folder]").forEach((target) => {
        target.addEventListener("dragover", (event) => {
          if (!libraryDragPayload(event)) return;
          event.preventDefault();
          event.stopPropagation();
          target.classList.add("drag-over");
        });
        target.addEventListener("dragleave", () => target.classList.remove("drag-over"));
        target.addEventListener("drop", async (event) => {
          const payload = libraryDragPayload(event);
          if (!payload) return;
          event.preventDefault();
          event.stopPropagation();
          target.classList.remove("drag-over");
          const folderId = Number(target.dataset.libraryDropFolder || state.libraryActiveFolderId || state.libraryRootId);
          if (payload.type && payload.id) await moveLibraryEntry(payload.type, payload.id, folderId);
        });
      });
      shell.querySelectorAll("[data-library-column-folder]").forEach((column) => {
        const body = column.querySelector(".library-column-body");
        const folderId = Number(column.dataset.libraryColumnFolder || 0);
        body?.addEventListener("scroll", () => {
          if (folderId) state.libraryColumnScrollTops[folderId] = body.scrollTop;
        });
        column.addEventListener("click", (event) => {
          if (event.target.closest(".library-row")) return;
          state.libraryActiveFolderId = Number(column.dataset.libraryColumnFolder || state.libraryRootId);
          clearLibraryRangeSelection();
          renderLibrary();
        });
      });
      $("libraryColumns")?.addEventListener("scroll", (event) => {
        state.libraryColumnsScrollLeft = event.currentTarget.scrollLeft;
      });
      shell.querySelectorAll("[data-library-resize-folder]").forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => startLibraryColumnResize(event, Number(handle.dataset.libraryResizeFolder || 0)));
      });
      shell.addEventListener("contextmenu", (event) => {
        const column = event.target.closest?.("[data-library-column-folder]");
        const folderId = Number(column?.dataset.libraryColumnFolder || state.libraryActiveFolderId || state.libraryRootId);
        state.libraryActiveFolderId = folderId;
        showLibraryContextMenu(event, folderId);
      });
    }

    function libraryDragPayload(event) {
      const types = Array.prototype.slice.call(event.dataTransfer?.types || []);
      if (!types.includes("application/x-paper-monitor-library")) return state.libraryDragPayload || null;
      try {
        return JSON.parse(event.dataTransfer.getData("application/x-paper-monitor-library") || "null") || state.libraryDragPayload || null;
      } catch (error) {
        return state.libraryDragPayload || null;
      }
    }

    function libraryDropIsReorder(payload, row, event) {
      return Boolean(
        payload?.type
        && payload.type === row.dataset.libraryType
        && Number(payload.id || 0) !== Number(row.dataset.libraryId || 0)
        && Number(payload.parent_folder_id || 0) === Number(row.dataset.libraryParentFolder || 0)
        && libraryDropIntent(row, event) !== "inside"
      );
    }

    function libraryDropIntent(row, event) {
      const rect = row.getBoundingClientRect();
      const ratio = (event.clientY - rect.top) / Math.max(1, rect.height);
      if (row.dataset.libraryType === "folder" && ratio > 0.25 && ratio < 0.75) return "inside";
      return ratio >= 0.5 ? "after" : "before";
    }

    function markLibraryReorderTarget(row, event) {
      clearLibraryDragClasses(row);
      row.classList.add(libraryDropIntent(row, event) === "after" ? "drag-reorder-after" : "drag-reorder-before");
    }

    function clearLibraryDragClasses(row) {
      row.classList.remove("drag-over", "drag-reorder-before", "drag-reorder-after");
    }

    function selectLibraryEntry(parentFolderId, type, id, options = {}) {
      const entry = {type, id: Number(id)};
      if (options.extendRange) setLibraryRangeSelection(parentFolderId, entry);
      else setLibraryColumnSelection(parentFolderId, entry);
      if (options.revealChildColumn) requestLibraryColumnReveal(parentFolderId, "right");
      renderLibrary();
      refreshLibraryQuickLookForSelection();
    }

    function focusLibraryFolder(folderId) {
      if (!libraryFolderById(folderId)) return;
      const parentId = parentFolderId(folderId);
      setLibraryColumnSelection(parentId, {type: "folder", id: Number(folderId)});
      state.libraryActiveFolderId = Number(folderId);
      state.libraryCurrentFolderId = Number(folderId);
      renderLibrary();
      refreshLibraryQuickLookForSelection();
    }

    function selectedLibraryPaper() {
      if (state.libraryTab === "my-publications") return selectedMyPublicationPaper();
      if (state.librarySelection?.type !== "item") return null;
      return libraryItemById(state.librarySelection.id)?.paper || null;
    }

    async function openLibraryPdfInPreview(paper) {
      if (!paper?.merged_pdf_path) return;
      const status = $("libraryDetailStatus");
      if (status) {
        status.textContent = "Opening PDF in Preview...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/open-pdf", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({path: paper.merged_pdf_path})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "open failed");
        if (status) {
          status.textContent = "PDF opened in Preview";
          status.className = "library-detail-status ok";
        }
      } catch (error) {
        if (status) {
          status.textContent = error.message;
          status.className = "library-detail-status err";
        }
      }
    }

    async function downloadLibraryPdf(paper) {
      if (!paper?.paper_id) return;
      const status = $("libraryDetailStatus");
      const buttons = $("libraryDetail")?.querySelectorAll("button") || [];
      buttons.forEach((button) => button.disabled = true);
      if (status) {
        status.textContent = "Downloading PDF...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/download", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({paper_id: paper.paper_id})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "download failed");
        updatePaperState(paper.paper_id, data.paper);
        if (status) {
          status.textContent = "PDF downloaded";
          status.className = "library-detail-status ok";
        }
        if (state.libraryTab === "my-publications") renderMyPublications();
        else renderLibrary();
      } catch (error) {
        if (status) {
          status.textContent = error.message;
          status.className = "library-detail-status err";
        }
        buttons.forEach((button) => button.disabled = false);
      }
    }

    function closeLibraryQuickLook() {
      state.libraryQuickLookOpen = false;
      state.libraryQuickLookPath = "";
      state.libraryQuickLookUrl = "";
      state.libraryQuickLookPage = 1;
      state.libraryQuickLookPageCount = 0;
      const overlay = $("libraryQuickLook");
      const pages = $("libraryQuickLookPages");
      if (overlay) {
        overlay.classList.remove("open");
        overlay.setAttribute("aria-hidden", "true");
      }
      if (pages) pages.innerHTML = "";
      renderLibraryQuickLookThumbs(0);
    }

    function defaultLibraryQuickLookFrame() {
      const columns = $("libraryColumns");
      const rect = columns?.getBoundingClientRect();
      const fallback = {left: 32, top: 76, width: Math.min(780, window.innerWidth - 64), height: Math.min(680, window.innerHeight - 104)};
      if (!rect) return fallback;
      const width = Math.max(360, Math.min(820, rect.width - 24));
      const height = Math.max(360, Math.min(700, rect.height - 24, window.innerHeight - rect.top - 24));
      const columnWidth = Math.max(180, Number(state.libraryColumnWidths[state.libraryActiveFolderId] || 260));
      return {
        left: Math.round(rect.left + columnWidth + 12),
        top: Math.round(rect.top + Math.max(12, (rect.height - height) / 2)),
        width: Math.round(width),
        height: Math.round(height)
      };
    }

    function applyLibraryQuickLookFrame(frameRect = null) {
      const overlay = $("libraryQuickLook");
      if (!overlay) return;
      const rect = frameRect || state.libraryQuickLookFrameRect || defaultLibraryQuickLookFrame();
      const width = Math.max(320, Math.min(rect.width, Math.max(2200, window.innerWidth * 1.8)));
      const height = Math.max(300, Math.min(rect.height, Math.max(2000, window.innerHeight * 1.8)));
      const left = Math.max(80 - width, Math.min(rect.left, window.innerWidth - 80));
      const top = Math.max(36 - height, Math.min(rect.top, window.innerHeight - 36));
      state.libraryQuickLookFrameRect = {left, top, width, height};
      overlay.style.left = `${left}px`;
      overlay.style.top = `${top}px`;
      overlay.style.width = `${width}px`;
      overlay.style.height = `${height}px`;
    }

    function selectedLibraryQuickLookPlaceholder() {
      if (state.libraryTab === "my-publications") {
        const paper = selectedMyPublicationPaper();
        return {icon: "○", title: paper?.citation_label || paper?.title || "Publication", type: paper ? "No PDF" : "My Publications"};
      }
      const selection = state.librarySelection || {};
      if (selection.type === "folder") {
        const folder = libraryFolderById(selection.id);
        return {icon: "□", title: folder?.name || "Folder", type: "Folder"};
      }
      if (selection.type === "item") {
        const item = libraryItemById(selection.id);
        const paper = item?.paper || {};
        return {icon: "○", title: item?.display_name || paper.citation_label || paper.title || "Paper", type: "No PDF"};
      }
      return {icon: "□", title: "No Preview", type: "Library"};
    }

    function showLibraryQuickLookPlaceholder() {
      if (!state.libraryQuickLookOpen) return;
      const overlay = $("libraryQuickLook");
      const title = $("libraryQuickLookTitle");
      const pages = $("libraryQuickLookPages");
      if (!overlay || !pages) return;
      const placeholder = selectedLibraryQuickLookPlaceholder();
      state.libraryQuickLookPath = "";
      state.libraryQuickLookUrl = "";
      state.libraryQuickLookPage = 1;
      state.libraryQuickLookPageCount = 0;
      if (title) title.textContent = placeholder.type;
      renderLibraryQuickLookThumbs(0);
      pages.onscroll = null;
      pages.innerHTML = `
        <div class="library-quicklook-placeholder">
          <div class="library-quicklook-placeholder-card">
            <div class="library-quicklook-placeholder-icon">${escapeHtml(placeholder.icon)}</div>
            <div class="library-quicklook-placeholder-title">${escapeHtml(placeholder.title)}</div>
          </div>
        </div>
      `;
      overlay.classList.add("open");
      overlay.setAttribute("aria-hidden", "false");
      applyLibraryQuickLookFrame();
    }

    function setLibraryQuickLookPage(page) {
      const nextPage = Math.max(1, Math.min(Number(page || 1), state.libraryQuickLookPageCount || Number(page || 1)));
      updateLibraryQuickLookActivePage(nextPage);
      updateLibraryPdfFramePage(nextPage);
      $("libraryShell")?.focus({preventScroll: true});
    }

    function updateLibraryQuickLookActivePage(page) {
      state.libraryQuickLookPage = Math.max(1, Number(page || 1));
      $("libraryQuickLookThumbs")?.querySelectorAll("[data-page]").forEach((button) => {
        button.classList.toggle("active", Number(button.dataset.page || 0) === state.libraryQuickLookPage);
      });
      $("libraryQuickLookThumbs")?.querySelector(".library-page-thumb.active")?.scrollIntoView({block: "nearest"});
    }

    function libraryPdfFrameUrl(page = state.libraryQuickLookPage) {
      if (!state.libraryQuickLookUrl) return "";
      const safePage = Math.max(1, Number(page || 1));
      const [baseUrl] = state.libraryQuickLookUrl.split("#");
      const separator = baseUrl.includes("?") ? "&" : "?";
      return `${baseUrl}${separator}pm_page=${safePage}&pm_nonce=${Date.now()}#page=${safePage}&toolbar=0&navpanes=0&view=FitH`;
    }

    function updateLibraryPdfFramePage(page) {
      const frame = $("libraryQuickLookPages")?.querySelector(".library-pdf-frame");
      if (!frame) return;
      const nextUrl = libraryPdfFrameUrl(page);
      if (frame.getAttribute("src") === nextUrl) return;
      frame.src = nextUrl;
    }

    function libraryQuickLookImageUrl(page, size) {
      if (!state.libraryQuickLookPath) return "";
      const safePage = Math.max(1, Number(page || 1));
      return `/api/pdf-thumb?path=${encodeURIComponent(state.libraryQuickLookPath)}&page=${safePage}&size=${size}`;
    }

    function renderLibraryQuickLookThumbs(pageCount) {
      const root = $("libraryQuickLookThumbs");
      if (!root) return;
      const count = Math.max(0, Math.min(200, Number(pageCount || 0)));
      if (!count) {
        root.innerHTML = `<div class="empty">Pages</div>`;
        return;
      }
      root.innerHTML = Array.from({length: count}, (_, index) => {
        const page = index + 1;
        const preview = page <= 160
          ? `<img src="${escapeAttr(libraryQuickLookImageUrl(page, 240))}" alt="Page ${page}" loading="lazy">`
          : `<span class="library-page-thumb-placeholder"></span>`;
        return `
          <button class="library-page-thumb${page === state.libraryQuickLookPage ? " active" : ""}" type="button" data-page="${page}">
            <span class="library-page-thumb-preview">${preview}</span>
            <span>${page}</span>
          </button>
        `;
      }).join("");
      root.querySelectorAll("[data-page]").forEach((button) => {
        button.addEventListener("click", () => setLibraryQuickLookPage(Number(button.dataset.page || 1)));
      });
      root.querySelector(".library-page-thumb.active")?.scrollIntoView({block: "nearest"});
    }

    function renderLibraryQuickLookPages(pageCount) {
      const root = $("libraryQuickLookPages");
      if (!root) return;
      const count = Math.max(0, Math.min(200, Number(pageCount || 0)));
      if (!count) {
        root.innerHTML = `<div class="empty">Loading pages...</div>`;
        return;
      }
      const page = Math.max(1, Math.min(state.libraryQuickLookPage || 1, count));
      root.innerHTML = `<iframe class="library-pdf-frame" title="PDF preview" src="${escapeAttr(libraryPdfFrameUrl(page))}"></iframe>`;
      root.scrollTop = 0;
      root.onscroll = null;
    }

    function updateLibraryQuickLookPageFromScroll() {
      const root = $("libraryQuickLookPages");
      if (!root || !state.libraryQuickLookOpen) return;
      const pages = [...root.querySelectorAll("[data-preview-page]")];
      if (!pages.length) return;
      const anchor = root.scrollTop + 48;
      let current = Number(pages[0].dataset.previewPage || 1);
      pages.forEach((pageEl) => {
        if (pageEl.offsetTop <= anchor) current = Number(pageEl.dataset.previewPage || current);
      });
      if (current !== state.libraryQuickLookPage) updateLibraryQuickLookActivePage(current);
    }

    async function loadLibraryQuickLookInfo(path) {
      try {
        const res = await fetch(`/api/pdf-info?path=${encodeURIComponent(path)}`);
        const data = await res.json();
        if (!res.ok || path !== state.libraryQuickLookPath) return;
        state.libraryQuickLookPageCount = Number(data.page_count || 0);
        renderLibraryQuickLookThumbs(state.libraryQuickLookPageCount);
        renderLibraryQuickLookPages(state.libraryQuickLookPageCount);
      } catch (error) {
        state.libraryQuickLookPageCount = 0;
        renderLibraryQuickLookThumbs(0);
        renderLibraryQuickLookPages(0);
      }
    }

    function quickLookLibraryPdf(paper, options = {}) {
      if (!paper?.merged_pdf_path) return;
      if (options.toggle && state.libraryQuickLookOpen && paper.merged_pdf_path === state.libraryQuickLookPath) {
        closeLibraryQuickLook();
        return;
      }
      const status = $("libraryDetailStatus");
      if (status && !options.silent) {
        status.textContent = "Previewing PDF";
        status.className = "library-detail-status";
      }
      const overlay = $("libraryQuickLook");
      const title = $("libraryQuickLookTitle");
      const pages = $("libraryQuickLookPages");
      if (!overlay || !pages) return;
      const pdfUrl = paper.merged_pdf_url || `/files?path=${encodeURIComponent(paper.merged_pdf_path)}`;
      const isNewPdf = paper.merged_pdf_path !== state.libraryQuickLookPath;
      state.libraryQuickLookOpen = true;
      state.libraryQuickLookPath = paper.merged_pdf_path;
      state.libraryQuickLookUrl = pdfUrl;
      if (isNewPdf) {
        state.libraryQuickLookPage = 1;
        state.libraryQuickLookPageCount = 0;
        renderLibraryQuickLookThumbs(0);
        renderLibraryQuickLookPages(0);
        loadLibraryQuickLookInfo(paper.merged_pdf_path);
      }
      if (title) title.textContent = paper.citation_label || paper.title || "PDF Preview";
      overlay.classList.add("open");
      overlay.setAttribute("aria-hidden", "false");
      if (!state.libraryQuickLookManualFrame || !state.libraryQuickLookFrameRect) {
        applyLibraryQuickLookFrame(defaultLibraryQuickLookFrame());
      } else {
        applyLibraryQuickLookFrame();
      }
      $("libraryShell")?.focus({preventScroll: true});
      if (status && !options.silent) {
        status.textContent = "PDF preview open";
        status.className = "library-detail-status ok";
      }
    }

    function startLibraryQuickLookDrag(event) {
      const overlay = $("libraryQuickLook");
      if (!overlay || event.target.closest("button")) return;
      event.preventDefault();
      state.libraryQuickLookManualFrame = true;
      const rect = overlay.getBoundingClientRect();
      const startX = event.clientX;
      const startY = event.clientY;
      const startLeft = rect.left;
      const startTop = rect.top;
      const move = (moveEvent) => {
        applyLibraryQuickLookFrame({
          left: startLeft + moveEvent.clientX - startX,
          top: startTop + moveEvent.clientY - startY,
          width: rect.width,
          height: rect.height
        });
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        $("libraryShell")?.focus({preventScroll: true});
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    }

    function startLibraryQuickLookResize(event) {
      const overlay = $("libraryQuickLook");
      if (!overlay) return;
      event.preventDefault();
      event.stopPropagation();
      state.libraryQuickLookManualFrame = true;
      const rect = overlay.getBoundingClientRect();
      const startX = event.clientX;
      const startY = event.clientY;
      const move = (moveEvent) => {
        applyLibraryQuickLookFrame({
          left: rect.left,
          top: rect.top,
          width: rect.width + moveEvent.clientX - startX,
          height: rect.height + moveEvent.clientY - startY
        });
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        $("libraryShell")?.focus({preventScroll: true});
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    }

    function refreshLibraryQuickLookForSelection() {
      if (!state.libraryQuickLookOpen) return;
      const paper = selectedLibraryPaper();
      if (!paper?.merged_pdf_path) {
        showLibraryQuickLookPlaceholder();
        return;
      }
      if (paper.merged_pdf_path === state.libraryQuickLookPath) return;
      quickLookLibraryPdf(paper, {silent: true});
    }

    async function runLibraryMenuAction(action) {
      try {
        await action();
      } catch (error) {
        window.alert(error.message || "Library action failed");
      }
    }

    function libraryEntryIsCopyable(type, id) {
      if (!type || !id) return false;
      if (type === "item") return Boolean(libraryItemById(id));
      if (type === "folder") {
        const folder = libraryFolderById(id);
        return Boolean(folder && !folder.protected);
      }
      return false;
    }

    function copyLibraryEntryToClipboard(type, id) {
      if (!libraryEntryIsCopyable(type, id)) return false;
      state.libraryClipboard = {type, id: Number(id)};
      return true;
    }

    function libraryPasteTargetFolderId() {
      const selection = state.librarySelection;
      if (selection?.type === "folder") return Number(selection.id || state.libraryRootId);
      if (selection?.type === "item") return Number(libraryItemById(selection.id)?.folder_id || state.libraryActiveFolderId || state.libraryRootId);
      return Number(state.libraryActiveFolderId || state.libraryRootId);
    }

    function showLibraryContextMenu(event, parentId, entryType = "", entryId = 0) {
      event.preventDefault();
      const menu = $("libraryContextMenu");
      if (!menu) return;
      menu.dataset.parentId = parentId || state.libraryActiveFolderId || state.libraryRootId;
      menu.dataset.entryType = entryType || "";
      menu.dataset.entryId = entryId || "";
      menu.style.left = `${event.clientX}px`;
      menu.style.top = `${event.clientY}px`;
      menu.classList.add("open");
      menu.onclick = (clickEvent) => clickEvent.stopPropagation();
      const hasEntry = Boolean(entryType && entryId);
      const folder = entryType === "folder" ? libraryFolderById(entryId) : null;
      const item = entryType === "item" ? libraryItemById(entryId) : null;
      const recycleId = libraryRecycleFolderId();
      const isRoot = entryType === "folder" && Number(entryId) === Number(state.libraryRootId);
      const isProtectedFolder = Boolean(folder?.protected || isRoot);
      const isRecoverable = (entryType === "item" && Number(item?.folder_id || 0) === recycleId)
        || (entryType === "folder" && Number(folder?.parent_id || 0) === recycleId);
      const renameButton = menu.querySelector('[data-action="rename-entry"]');
      const colorButton = menu.querySelector('[data-action="color-folder"]');
      const colorPicker = menu.querySelector('[data-action="folder-color-picker"]');
      const deleteButton = menu.querySelector('[data-action="delete-entry"]');
      const copyButton = menu.querySelector('[data-action="copy-entry"]');
      const pasteButton = menu.querySelector('[data-action="paste-entry"]');
      const recoverButton = menu.querySelector('[data-action="recover-entry"]');
      if (renameButton) {
        renameButton.style.display = hasEntry && !isProtectedFolder ? "" : "none";
        renameButton.onclick = () => {
          hideLibraryContextMenu();
          beginLibraryEntryRename(menu.dataset.entryType, Number(menu.dataset.entryId || 0));
        };
      }
      if (colorButton && colorPicker) {
        const canColor = entryType === "folder" && hasEntry && !isProtectedFolder;
        colorButton.style.display = canColor ? "" : "none";
        colorPicker.value = isValidFolderColor(folder?.color) ? folder.color : "#4f46e5";
        colorButton.onclick = (clickEvent) => {
          clickEvent.stopPropagation();
          colorPicker.value = isValidFolderColor(folder?.color) ? folder.color : "#4f46e5";
          colorPicker.click();
        };
        colorPicker.onclick = (clickEvent) => clickEvent.stopPropagation();
        colorPicker.onchange = async () => {
          const folderId = Number(menu.dataset.entryId || 0);
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => colorLibraryFolder(folderId, colorPicker.value));
        };
      }
      if (deleteButton) {
        deleteButton.style.display = hasEntry && !isProtectedFolder ? "" : "none";
        deleteButton.onclick = async () => {
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => deleteLibraryEntry(menu.dataset.entryType, Number(menu.dataset.entryId || 0)));
        };
      }
      if (copyButton) {
        copyButton.style.display = hasEntry && !isProtectedFolder ? "" : "none";
        copyButton.onclick = () => {
          copyLibraryEntryToClipboard(menu.dataset.entryType, Number(menu.dataset.entryId || 0));
          hideLibraryContextMenu();
        };
      }
      if (recoverButton) {
        recoverButton.style.display = isRecoverable ? "" : "none";
        recoverButton.onclick = async () => {
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => recoverLibraryEntry(menu.dataset.entryType, Number(menu.dataset.entryId || 0)));
        };
      }
      if (pasteButton) {
        pasteButton.style.display = state.libraryClipboard ? "" : "none";
        pasteButton.onclick = async () => {
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => pasteLibraryEntry(Number(menu.dataset.parentId || state.libraryActiveFolderId || state.libraryRootId)));
        };
      }
      menu.querySelector('[data-action="new-folder"]').onclick = async () => {
        hideLibraryContextMenu();
        await runLibraryMenuAction(() => createLibraryFolder(Number(menu.dataset.parentId || state.libraryActiveFolderId || state.libraryRootId)));
      };
    }

    function hideLibraryContextMenu() {
      $("libraryContextMenu")?.classList.remove("open");
    }

    function handleLibraryKeydown(event) {
      if (state.mode !== "library") return false;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName)) return false;
      const keyAliases = {
        "Up": "ArrowUp",
        "Down": "ArrowDown",
        "Left": "ArrowLeft",
        "Right": "ArrowRight",
        "Spacebar": " "
      };
      const key = keyAliases[event.key] || event.key;
      if (state.libraryTab === "my-publications") {
        const handled = ["ArrowUp", "ArrowDown", " "].includes(key);
        if (!handled) return false;
        event.preventDefault();
        return handleMyPublicationKeydown(event, key);
      }
      if (event.metaKey && !event.altKey && !event.shiftKey && key.toLowerCase() === "c") {
        const selection = state.librarySelection;
        if (copyLibraryEntryToClipboard(selection?.type, Number(selection?.id || 0))) {
          event.preventDefault();
          return true;
        }
        return false;
      }
      if (event.metaKey && !event.altKey && !event.shiftKey && key.toLowerCase() === "v") {
        if (!state.libraryClipboard) return false;
        event.preventDefault();
        runLibraryMenuAction(() => pasteLibraryEntry(libraryPasteTargetFolderId()));
        return true;
      }
      const handled = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " ", "Enter", "Delete", "Backspace"].includes(key);
      if (!handled) return false;
      event.preventDefault();
      if (key === "Delete" || key === "Backspace") {
        runLibraryMenuAction(deleteSelectedLibraryEntries);
        return true;
      }
      if (key === " ") {
        const paper = selectedLibraryPaper();
        if (paper?.merged_pdf_path) quickLookLibraryPdf(paper, {toggle: true});
        return true;
      }
      if (key === "Enter") {
        if (state.librarySelection?.type) beginLibraryEntryRename(state.librarySelection.type, state.librarySelection.id);
        return true;
      }
      if (librarySearchIsActive() && ["ArrowUp", "ArrowDown"].includes(key)) {
        const results = librarySearchResults();
        if (!results.length) return true;
        const currentKey = libraryEntryKey(state.librarySelection);
        const currentIndex = results.findIndex((entry) => libraryEntryKey(entry) === currentKey);
        const fallback = key === "ArrowDown" ? 0 : results.length - 1;
        const nextIndex = currentIndex < 0
          ? fallback
          : Math.max(0, Math.min(results.length - 1, currentIndex + (key === "ArrowDown" ? 1 : -1)));
        const next = results[nextIndex];
        setLibraryColumnSelection(next.parentFolderId, next);
        renderLibrary();
        refreshLibraryQuickLookForSelection();
        return true;
      }
      if (key === "ArrowLeft") {
        const activeFolderId = Number(state.libraryActiveFolderId || state.libraryRootId);
        clearLibraryRangeSelection();
        if (activeFolderId !== Number(state.libraryRootId)) {
          const parentId = parentFolderId(activeFolderId);
          state.libraryActiveFolderId = parentId;
          state.libraryCurrentFolderId = activeFolderId;
          state.librarySelection = {type: "folder", id: activeFolderId};
          requestLibraryColumnReveal(parentId, "left");
        }
        renderLibrary();
        return true;
      }
      if (key === "ArrowRight") {
        const activeFolderId = Number(state.libraryActiveFolderId || state.libraryRootId);
        const selection = selectedEntryInFolder(activeFolderId);
        if (selection?.type === "folder") {
          clearLibraryRangeSelection();
          const childFolderId = Number(selection.id);
          const existing = selectedEntryInFolder(childFolderId);
          const firstEntry = libraryEntriesForFolder(childFolderId)[0];
          if (!existing && !firstEntry) return true;
          state.libraryActiveFolderId = childFolderId;
          state.libraryCurrentFolderId = childFolderId;
          setLibraryColumnSelection(childFolderId, existing || firstEntry);
          requestLibraryColumnReveal(childFolderId, "right");
          renderLibrary();
          refreshLibraryQuickLookForSelection();
        }
        return true;
      }
      const activeFolderId = Number(state.libraryActiveFolderId || state.libraryRootId);
      const entries = libraryEntriesForFolder(activeFolderId);
      if (!entries.length) return true;
      const currentSelection = selectedEntryInFolder(activeFolderId);
      const currentIndex = entries.findIndex((entry) => libraryEntryKey(entry) === libraryEntryKey(currentSelection));
      const fallback = key === "ArrowDown" ? 0 : entries.length - 1;
      const nextIndex = currentIndex < 0
        ? fallback
        : Math.max(0, Math.min(entries.length - 1, currentIndex + (key === "ArrowDown" ? 1 : -1)));
      if (event.shiftKey) setLibraryRangeSelection(activeFolderId, entries[nextIndex]);
      else setLibraryColumnSelection(activeFolderId, entries[nextIndex]);
      if (entries[nextIndex]?.type === "folder") requestLibraryColumnReveal(activeFolderId, "right");
      renderLibrary();
      refreshLibraryQuickLookForSelection();
      return true;
    }

    function updatePaperState(paperId, paper) {
      if (!paper) return;
      const reportIndex = state.papers.findIndex((item) => item.paper_id === paperId);
      if (reportIndex >= 0) state.papers[reportIndex] = paper;
      const cachedReport = state.reportCache[paper.publication_date];
      const cachedIndex = (cachedReport?.papers || []).findIndex((item) => item.paper_id === paperId);
      if (cachedIndex >= 0) cachedReport.papers[cachedIndex] = paper;
      state.libraryItems.forEach((item) => {
        if (item.paper_id === paperId || item.paper?.paper_id === paperId) item.paper = paper;
      });
      state.myPublications.forEach((item) => {
        if (item.paper_id === paperId || item.paper?.paper_id === paperId) item.paper = paper;
      });
    }

    function renderPaper(paper) {
      const article = document.createElement("article");
      const reserveFigure = state.showFigures && (paper.image_url || (paper.paper_id && !state.figureFailures.has(paper.paper_id)));
      article.className = `paper${reserveFigure ? " with-figure" : ""}`;
      article.dataset.paperId = paper.paper_id;
      const authorText = authorLine(paper);
      const identifierText = paper.doi || paper.preprint_id || "no DOI";
      const preprintCategoryText = paper.preprint_category || "";
      const fieldBadges = paperFieldValues(paper)
        .map((field) => `<span class="field-badge">${escapeHtml(FIELD_LABELS[field] || field)}</span>`)
        .join("");
      article.innerHTML = `
        <div class="paper-layout">
          ${reserveFigure ? reportFigureMarkup(paper) : ""}
          <div class="paper-main">
            <div class="paper-head">
              <div>
                <h3 style="color:${paper.section_color}">${escapeHtml(paper.title || "(Untitled)")}</h3>
                <div class="meta">
                  <span class="journal-name">${escapeHtml(paper.journal)}</span>
                  <span>${escapeHtml(paper.publication_date || "unknown date")}</span>
                  <span>${escapeHtml(identifierText)}</span>
                  ${preprintCategoryText ? `<span>${escapeHtml(preprintCategoryText)}</span>` : ""}
                  <span class="authors">${escapeHtml(authorText)}</span>
                </div>
              </div>
              <div class="paper-badges">
                <span class="badge" style="color:${paper.section_color};background:${paper.section_badge_background}">${escapeHtml(paper.section)}</span>
                ${fieldBadges}
              </div>
            </div>
            <p class="abstract">${escapeHtml(paper.abstract || "No abstract available.")}</p>
            <div class="actions">
              ${paper.url ? `<button class="action" data-action="open-page" title="Open publisher page inside Journal Monitor">↗ Open</button>` : ""}
              <button class="action" data-action="add-library" title="Add a shortcut to Library">Add to Library</button>
              <button class="action primary" data-action="download" title="Download merged PDF">↓ Download</button>
              <button class="action secondary" data-action="analyze" title="Queue a Codex analysis job">Queue Codex Analysis</button>
              ${paper.merged_pdf_path ? `<button class="action" data-action="open-pdf" title="Open merged PDF in Preview">PDF</button>` : ""}
              ${paper.merged_pdf_path ? `<button class="action danger" data-action="delete-pdf" title="Delete local PDF and reset download status">Delete PDF</button>` : ""}
              ${!paper.merged_pdf_path ? `<label class="manual-drop" data-role="manual-drop" title="Attach a local PDF"><input type="file" accept="application/pdf,.pdf">Drop PDF</label>` : ""}
              ${paper.analysis_path ? `<button class="action" data-action="view-analysis" title="Show analysis">Note</button>` : ""}
              ${paper.analysis_path ? `<button class="action danger" data-action="delete-analysis" title="Delete analysis note and reset analysis status">Delete Note</button>` : ""}
              <span class="status ${statusClass(paper.download_status)}" data-role="status">
                Download: ${escapeHtml(paper.download_status)}${paper.analysis_status ? ` · Analysis: ${escapeHtml(paper.analysis_status)}` : ""}
              </span>
            </div>
          </div>
        </div>
      `;
      const openPageButton = article.querySelector('[data-action="open-page"]');
      if (openPageButton) openPageButton.addEventListener("click", () => openInternalBrowser(paper.url, paper.title || "Publisher page"));
      article.querySelector('[data-action="add-library"]').addEventListener("click", () => addPaperToLibrary(article, paper.paper_id));
      article.querySelector('[data-action="download"]').addEventListener("click", () => runAction(article, paper.paper_id, "download"));
      article.querySelector('[data-action="analyze"]').addEventListener("click", () => runAction(article, paper.paper_id, "analyze"));
      const pdfButton = article.querySelector('[data-action="open-pdf"]');
      if (pdfButton) pdfButton.addEventListener("click", () => openPdf(article, paper));
      const analysisButton = article.querySelector('[data-action="view-analysis"]');
      if (analysisButton) analysisButton.addEventListener("click", () => viewAnalysis(article, paper.paper_id));
      const deletePdfButton = article.querySelector('[data-action="delete-pdf"]');
      if (deletePdfButton) deletePdfButton.addEventListener("click", () => deletePaperAsset(article, paper.paper_id, "delete-pdf"));
      const deleteAnalysisButton = article.querySelector('[data-action="delete-analysis"]');
      if (deleteAnalysisButton) deleteAnalysisButton.addEventListener("click", () => deletePaperAsset(article, paper.paper_id, "delete-analysis"));
      const dropZone = article.querySelector('[data-role="manual-drop"]');
      if (dropZone) wireManualPdfDrop(article, dropZone, paper.paper_id);
      const figureImage = article.querySelector(".paper-figure img");
      if (figureImage) {
        figureImage.addEventListener("error", () => {
          state.figureFailures.add(paper.paper_id);
          article.classList.remove("with-figure");
          article.querySelector(".paper-figure")?.remove();
        }, {once: true});
      } else if (reserveFigure && !paper.image_url) {
        queuePaperFigureHydration(paper.paper_id);
      }
      return article;
    }

    function reportFigureMarkup(paper) {
      if (paper.image_url) {
        return `<figure class="paper-figure"><img src="${escapeAttr(paper.image_url)}" alt="${escapeAttr(paper.title || "Paper figure")}" loading="lazy"></figure>`;
      }
      return `<figure class="paper-figure"><div class="paper-figure-placeholder"></div></figure>`;
    }

    function updateReportFigure(paper) {
      if (!state.showFigures || !paper?.paper_id || !paper.image_url) return;
      document.querySelectorAll(`.paper[data-paper-id="${CSS.escape(String(paper.paper_id))}"]`).forEach((article) => {
        article.classList.add("with-figure");
        const figure = article.querySelector(".paper-figure");
        const markup = `<img src="${escapeAttr(paper.image_url)}" alt="${escapeAttr(paper.title || "Paper figure")}" loading="lazy">`;
        if (figure) {
          figure.innerHTML = markup;
        } else {
          article.querySelector(".paper-layout")?.insertAdjacentHTML("afterbegin", `<figure class="paper-figure">${markup}</figure>`);
        }
        article.querySelector(".paper-figure img")?.addEventListener("error", () => {
          state.figureFailures.add(paper.paper_id);
          article.classList.remove("with-figure");
          article.querySelector(".paper-figure")?.remove();
        }, {once: true});
      });
    }

    function removeReportFigure(paperId) {
      if (!paperId) return;
      document.querySelectorAll(`.paper[data-paper-id="${CSS.escape(String(paperId))}"]`).forEach((article) => {
        article.classList.remove("with-figure");
        article.querySelector(".paper-figure")?.remove();
      });
    }

    function queuePaperFigureHydration(paperId) {
      if (!paperId || state.figureFailures.has(paperId) || state.figureRequests[paperId] || state.queuedFigureIds.has(paperId)) return;
      state.queuedFigureIds.add(paperId);
      state.figureQueue.push(paperId);
      drainFigureQueue();
    }

    function drainFigureQueue() {
      while ((state.showFigures || state.mode === "library") && state.activeFigureHydrations < state.maxFigureHydrations && state.figureQueue.length) {
        const paperId = state.figureQueue.shift();
        state.queuedFigureIds.delete(paperId);
        hydratePaperFigure(paperId);
      }
    }

    async function hydratePaperFigure(paperId) {
      if (state.figureRequests[paperId]) return;
      state.figureRequests[paperId] = true;
      state.activeFigureHydrations += 1;
      try {
        const res = await fetch(`/api/paper-figure?paper_id=${encodeURIComponent(paperId)}`);
        const data = await res.json();
        if (!res.ok || !data.paper?.image_url) {
          state.figureFailures.add(paperId);
          removeReportFigure(paperId);
          return;
        }
        updatePaperState(paperId, data.paper);
        if (state.mode === "library") renderActiveLibraryTab();
        else updateReportFigure(data.paper);
      } catch (error) {
        state.figureFailures.add(paperId);
        removeReportFigure(paperId);
      } finally {
        delete state.figureRequests[paperId];
        state.activeFigureHydrations = Math.max(0, state.activeFigureHydrations - 1);
        drainFigureQueue();
      }
    }

    function openInternalBrowser(url, title) {
      if (!url) return;
      state.internalBrowserUrl = url;
      $("internalBrowserTitle").textContent = title || "Publisher page";
      $("internalBrowserUrl").textContent = url;
      $("internalBrowserFrame").src = `/api/page-proxy?url=${encodeURIComponent(url)}`;
      $("internalBrowser").classList.add("open");
      $("internalBrowser").setAttribute("aria-hidden", "false");
    }

    function closeInternalBrowser() {
      state.internalBrowserUrl = "";
      $("internalBrowser").classList.remove("open");
      $("internalBrowser").setAttribute("aria-hidden", "true");
      $("internalBrowserFrame").src = "about:blank";
    }

    async function openExternalBrowser() {
      if (!state.internalBrowserUrl) return;
      await fetch("/api/open-url", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url: state.internalBrowserUrl})
      });
    }

    async function openLibraryPageExternally(paper) {
      if (!paper?.url) return;
      await openLibraryExternalUrl(paper.url, "Opening in external browser...", "Opened in external browser");
    }

    async function openLibraryExternalUrl(url, pendingText, successText) {
      if (!url) return;
      const status = $("libraryDetailStatus");
      if (status) {
        status.textContent = pendingText || "Opening in external browser...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/open-url", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({url})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "open failed");
        if (status) {
          status.textContent = successText || "Opened in external browser";
          status.className = "library-detail-status ok";
        }
      } catch (error) {
        if (status) {
          status.textContent = error.message;
          status.className = "library-detail-status err";
        }
      }
    }

    async function copyLibraryBibtex(paper, button = null) {
      const status = $("libraryDetailStatus");
      try {
        await copyTextToClipboard(paper?.bibtex || "");
        markCopyButtonCopied(button);
        if (status) {
          status.textContent = "BibTeX copied";
          status.className = "library-detail-status ok";
        }
      } catch (error) {
        if (status) {
          status.textContent = error.message || "Copy failed";
          status.className = "library-detail-status err";
        }
      }
    }

    async function copyLibraryNatureReference(paper, button = null) {
      const status = $("libraryDetailStatus");
      try {
        await copyHtmlToClipboard(natureReferenceHtml(paper), natureReferenceText(paper));
        markCopyButtonCopied(button);
        if (status) {
          status.textContent = "Reference copied";
          status.className = "library-detail-status ok";
        }
      } catch (error) {
        if (status) {
          status.textContent = error.message || "Copy failed";
          status.className = "library-detail-status err";
        }
      }
    }

    function markCopyButtonCopied(button) {
      if (!button) return;
      $("libraryDetail")?.querySelectorAll("[data-copy-button]").forEach((item) => {
        item.textContent = item.dataset.defaultLabel || "Copy";
        item.classList.remove("copied");
      });
      button.textContent = "Copied";
      button.classList.add("copied");
    }

    async function copyHtmlToClipboard(html, plainText) {
      if (navigator.clipboard?.write && window.ClipboardItem) {
        const item = new ClipboardItem({
          "text/html": new Blob([html], {type: "text/html"}),
          "text/plain": new Blob([plainText || ""], {type: "text/plain"})
        });
        await navigator.clipboard.write([item]);
        return;
      }
      if (document.queryCommandSupported?.("copy")) {
        const container = document.createElement("div");
        container.contentEditable = "true";
        container.style.position = "fixed";
        container.style.left = "-10000px";
        container.style.top = "0";
        container.innerHTML = html;
        document.body.appendChild(container);
        const selection = window.getSelection();
        const range = document.createRange();
        range.selectNodeContents(container);
        selection.removeAllRanges();
        selection.addRange(range);
        const ok = document.execCommand("copy");
        selection.removeAllRanges();
        container.remove();
        if (ok) return;
      }
      await copyTextToClipboard(plainText || "");
    }

    async function copyTextToClipboard(text) {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return;
      }
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.setAttribute("readonly", "");
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.select();
      const ok = document.execCommand("copy");
      textarea.remove();
      if (!ok) throw new Error("Copy failed");
    }

    function editableClipboardTarget(target) {
      const element = target?.closest?.("input, textarea, [contenteditable='true']");
      if (!element) return null;
      if (element.matches?.("input")) {
        const type = String(element.type || "text").toLowerCase();
        if (["button", "checkbox", "color", "file", "radio", "range", "submit"].includes(type)) return null;
      }
      if (element.disabled || element.readOnly) return null;
      return element;
    }

    function selectedTextForCopy() {
      return String(window.getSelection?.()?.toString() || "");
    }

    function handleSearchShortcut(event) {
      if (event.altKey || event.shiftKey) return false;
      const key = String(event.key || "").toLowerCase();
      const isCommandLike = event.metaKey || event.ctrlKey;
      if (!isCommandLike || key !== "f") return false;
      const target = state.mode === "library" && !["loader", "my-publications"].includes(state.libraryTab || "")
        ? $("librarySearchBox")
        : $("searchBox");
      if (!target) return false;
      event.preventDefault();
      target.focus({preventScroll: true});
      target.select?.();
      return true;
    }

    function handleTextClipboardShortcut(event) {
      if (event.altKey || event.shiftKey) return false;
      const key = String(event.key || "").toLowerCase();
      const isCommandLike = event.metaKey || event.ctrlKey;
      if (!isCommandLike) return false;
      if (key === "c") {
        const selected = selectedTextForCopy();
        if (!selected) return false;
        event.preventDefault();
        copyTextToClipboard(selected).catch(() => {});
        return true;
      }
      if (key === "v") {
        const target = editableClipboardTarget(event.target);
        if (!target || !event.ctrlKey) return false;
        event.preventDefault();
        pasteClipboardTextInto(target).catch(() => {});
        return true;
      }
      return false;
    }

    async function pasteClipboardTextInto(target) {
      if (!target) return;
      let text = "";
      if (navigator.clipboard?.readText) {
        text = await navigator.clipboard.readText();
      }
      if (!text) return;
      insertTextIntoEditable(target, text);
    }

    function insertTextIntoEditable(target, text) {
      target.focus?.({preventScroll: true});
      if (target.isContentEditable) {
        document.execCommand("insertText", false, text);
        target.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertText", data: text}));
        return;
      }
      const start = Number.isFinite(target.selectionStart) ? target.selectionStart : String(target.value || "").length;
      const end = Number.isFinite(target.selectionEnd) ? target.selectionEnd : start;
      const value = String(target.value || "");
      target.value = `${value.slice(0, start)}${text}${value.slice(end)}`;
      const cursor = start + text.length;
      target.setSelectionRange?.(cursor, cursor);
      target.dispatchEvent(new InputEvent("input", {bubbles: true, inputType: "insertFromPaste", data: text}));
      target.dispatchEvent(new Event("change", {bubbles: true}));
    }

    function authorLine(paper) {
      const authors = Array.isArray(paper.authors) ? paper.authors : [];
      if (!authors.length) return "Authors unavailable";
      return `Authors: ${authors.join(", ")}`;
    }

    function wireManualPdfDrop(article, dropZone, paperId) {
      const input = dropZone.querySelector("input");
      input.addEventListener("change", () => {
        if (input.files.length) uploadManualPdf(article, paperId, input.files[0]);
        input.value = "";
      });
      ["dragenter", "dragover"].forEach((eventName) => {
        dropZone.addEventListener(eventName, (event) => {
          event.preventDefault();
          dropZone.classList.add("dragging");
        });
      });
      ["dragleave", "drop"].forEach((eventName) => {
        dropZone.addEventListener(eventName, () => dropZone.classList.remove("dragging"));
      });
      dropZone.addEventListener("drop", (event) => {
        event.preventDefault();
        const file = [...event.dataTransfer.files].find((item) => item.type === "application/pdf" || item.name.toLowerCase().endsWith(".pdf"));
        if (file) uploadManualPdf(article, paperId, file);
      });
    }

    async function uploadManualPdf(article, paperId, file) {
      const buttons = article.querySelectorAll("button, .manual-drop");
      const status = article.querySelector('[data-role="status"]');
      buttons.forEach((button) => button.disabled = true);
      status.textContent = "Uploading manual PDF...";
      status.className = "status";
      const form = new FormData();
      form.append("paper_id", paperId);
      form.append("pdf", file);
      try {
        const res = await fetch("/api/manual-pdf", {method: "POST", body: form});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "upload failed");
        updatePaperState(paperId, data.paper);
        if (state.mode === "library") renderActiveLibraryTab();
        else renderReport();
      } catch (error) {
        status.textContent = error.message;
        status.className = "status err";
        buttons.forEach((button) => button.disabled = false);
      }
    }

    async function runAction(article, paperId, action) {
      const buttons = article.querySelectorAll("button");
      const status = article.querySelector('[data-role="status"]');
      buttons.forEach((button) => button.disabled = true);
      status.textContent = action === "download" ? "Downloading..." : "Queueing Codex analysis...";
      status.className = "status";
      try {
        const res = await fetch(`/api/${action}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({paper_id: paperId})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "request failed");
        updatePaperState(paperId, data.paper);
        if (state.mode === "library") renderActiveLibraryTab();
        else renderReport();
      } catch (error) {
        status.textContent = error.message;
        status.className = "status err";
        buttons.forEach((button) => button.disabled = false);
      }
    }

    async function deletePaperAsset(article, paperId, action) {
      const label = action === "delete-pdf" ? "PDF" : "analysis note";
      if (!window.confirm(`Delete this ${label}?`)) return;
      const controls = article.querySelectorAll("button, .manual-drop");
      const status = article.querySelector('[data-role="status"]');
      controls.forEach((control) => control.disabled = true);
      status.textContent = `Deleting ${label}...`;
      status.className = "status";
      try {
        const res = await fetch(`/api/${action}`, {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({paper_id: paperId})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "delete failed");
        updatePaperState(paperId, data.paper);
        if (action === "delete-analysis") closeAnalysis();
        if (state.mode === "library") renderActiveLibraryTab();
        else renderReport();
      } catch (error) {
        status.textContent = error.message;
        status.className = "status err";
        controls.forEach((control) => control.disabled = false);
      }
    }

    async function openPdf(article, paper) {
      const status = article.querySelector('[data-role="status"]');
      status.textContent = "Opening PDF in Preview...";
      status.className = "status";
      try {
        const res = await fetch("/api/open-pdf", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({path: paper.merged_pdf_path})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "open failed");
        status.textContent = "PDF opened in Preview";
        status.className = "status ok";
      } catch (error) {
        status.textContent = error.message;
        status.className = "status err";
      }
    }

    async function viewAnalysis(article, paperId) {
      const status = article.querySelector('[data-role="status"]');
      status.textContent = "Loading analysis...";
      status.className = "status";
      try {
        const res = await fetch(`/api/analysis?paper_id=${encodeURIComponent(paperId)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "analysis not found");
        showAnalysis(data.paper, data.content || "");
        status.textContent = "Analysis opened";
        status.className = "status ok";
      } catch (error) {
        status.textContent = error.message;
        status.className = "status err";
      }
    }

    function showAnalysis(paper, content) {
      $("analysisMeta").innerHTML = `
        <strong>${escapeHtml(paper?.title || "Analysis")}</strong><br>
        ${escapeHtml(paper?.journal || "")} ${escapeHtml(paper?.publication_date || "")}
      `;
      $("analysisBody").innerHTML = markdownToHtml(content || "The analysis file is empty.");
      $("analysisBackdrop").classList.add("open");
      $("workspace").classList.add("note-open");
      $("workspace").style.setProperty("--note-width", `${state.noteWidth}px`);
      $("analysisPanel").classList.add("open");
      $("analysisPanel").setAttribute("aria-hidden", "false");
      updateReportPanelToggle();
    }

    function closeAnalysis() {
      $("analysisBackdrop").classList.remove("open");
      $("workspace").classList.remove("note-open");
      $("workspace").classList.remove("report-collapsed");
      $("analysisPanel").classList.remove("open");
      $("analysisPanel").setAttribute("aria-hidden", "true");
      updateReportPanelToggle();
    }

    function updateSidebarToggle() {
      const collapsed = document.querySelector(".app").classList.contains("sidebar-collapsed");
      $("toggleSidebar").innerHTML = collapsed ? "&rsaquo;&rsaquo;" : "&lsaquo;&lsaquo;";
      $("toggleSidebar").title = collapsed ? "Show filters" : "Hide filters";
    }

    function setSidebarCollapsed(collapsed) {
      document.querySelector(".app").classList.toggle("sidebar-collapsed", Boolean(collapsed));
      updateSidebarToggle();
    }

    function updateReportPanelToggle() {
      const workspace = $("workspace");
      const collapsed = workspace.classList.contains("report-collapsed");
      $("toggleReportPanel").innerHTML = collapsed ? "&rsaquo;&rsaquo;" : "&lsaquo;&lsaquo;";
      $("toggleReportPanel").title = collapsed ? "Show list" : "Hide list";
    }

    function toggleReportPanel() {
      const workspace = $("workspace");
      if (!workspace.classList.contains("note-open")) return;
      workspace.classList.toggle("report-collapsed");
      updateReportPanelToggle();
    }

    function startWorkspaceResize(event) {
      const workspace = $("workspace");
      if (!workspace.classList.contains("note-open") || workspace.classList.contains("report-collapsed")) return;
      event.preventDefault();
      document.body.classList.add("resizing");
      const move = (moveEvent) => {
        const rect = workspace.getBoundingClientRect();
        const minWidth = 260;
        const maxWidth = Math.max(minWidth, rect.width - 240);
        const nextWidth = Math.max(minWidth, Math.min(maxWidth, rect.right - moveEvent.clientX));
        state.noteWidth = Math.round(nextWidth);
        workspace.style.setProperty("--note-width", `${state.noteWidth}px`);
      };
      const stop = () => {
        document.body.classList.remove("resizing");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    }

    function markdownToHtml(markdown) {
      const lines = String(markdown || "").split(/\\r?\\n/);
      const output = [];
      let inList = false;
      const closeList = () => {
        if (inList) {
          output.push("</ul>");
          inList = false;
        }
      };
      for (const rawLine of lines) {
        const line = rawLine.trim();
        if (!line) {
          closeList();
          continue;
        }
        if (line.startsWith("### ")) {
          closeList();
          output.push(`<h3>${inlineMarkdown(line.slice(4))}</h3>`);
        } else if (line.startsWith("## ")) {
          closeList();
          output.push(`<h2>${inlineMarkdown(line.slice(3))}</h2>`);
        } else if (line.startsWith("# ")) {
          closeList();
          output.push(`<h1>${inlineMarkdown(line.slice(2))}</h1>`);
        } else if (line.startsWith("- ")) {
          if (!inList) {
            output.push("<ul>");
            inList = true;
          }
          output.push(`<li>${inlineMarkdown(line.slice(2))}</li>`);
        } else {
          closeList();
          output.push(`<p>${inlineMarkdown(line)}</p>`);
        }
      }
      closeList();
      return output.join("");
    }

    function inlineMarkdown(value) {
      return escapeHtml(value)
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[ch]));
    }

    function escapeAttr(value) {
      return escapeHtml(value).replace(/`/g, "&#96;");
    }

    $("prevMonth").addEventListener("click", async () => {
      state.viewMonth -= 1;
      if (state.viewMonth < 1) { state.viewMonth = 12; state.viewYear -= 1; }
      await loadMonth();
    });
    $("nextMonth").addEventListener("click", async () => {
      state.viewMonth += 1;
      if (state.viewMonth > 12) { state.viewMonth = 1; state.viewYear += 1; }
      await loadMonth();
    });
    $("jumpToday").addEventListener("click", async () => {
      const now = new Date();
      state.selectedDate = localIsoDate(now);
      state.activeReportJournal = "";
      state.viewYear = Number(state.selectedDate.slice(0, 4));
      state.viewMonth = Number(state.selectedDate.slice(5, 7));
      await loadMonth();
      await loadReport();
    });
    async function openJournalMonitor() {
      state.mode = "report";
      await loadMonth();
      setSidebarCollapsed(false);
      await loadReport({showLoading: false});
    }

    function setPrimaryView(view) {
      document.querySelector(".app")?.classList.toggle("library-mode", view === "library");
      $("libraryMode")?.classList.toggle("active", view === "library");
      $("reportMode")?.classList.toggle("active", view === "report");
      $("sideLibraryMode")?.classList.toggle("active", view === "library");
      $("sideReportMode")?.classList.toggle("active", view === "report");
      $("primaryViewSwitcher")?.classList.toggle("hidden", view === "report");
      $("sidebarViewSwitcher")?.classList.toggle("open", view === "report");
      $("reportToolbarActions")?.classList.toggle("hidden", view !== "report");
      $("topLibraryTools")?.classList.toggle("hidden", view !== "library");
    }

    $("reportMode").addEventListener("click", () => openJournalMonitor().catch((error) => {
      $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    }));
    $("libraryMode").addEventListener("click", loadLibrary);
    $("sideReportMode").addEventListener("click", () => openJournalMonitor().catch((error) => {
      $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    }));
    $("sideLibraryMode").addEventListener("click", loadLibrary);
    $("topLibraryLoader").addEventListener("click", openLibraryLoader);
    $("libraryTab").addEventListener("click", () => {
      loadLibrary().catch((error) => {
        $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      });
    });
    $("myPublicationsTab").addEventListener("click", () => {
      loadMyPublications().catch((error) => {
        $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      });
    });
    wireLibraryImportTools();
    $("addMyPublication").addEventListener("click", () => searchMyPublications("auto"));
    $("findMyPublications").addEventListener("click", () => searchMyPublications("author"));
    $("publicationSearchBox").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        searchMyPublications("auto");
      }
    });
    $("myPublicationName").addEventListener("change", () => saveMyPublicationName().catch(() => {}));
    $("myPublicationName").addEventListener("input", (event) => {
      state.myPublicationName = event.target.value || "";
      refreshLibraryDetailAuthors();
    });
    $("myPublicationName").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveMyPublicationName().catch(() => {});
      }
    });
    $("myPublicationSort").addEventListener("change", (event) => {
      state.myPublicationSort = event.target.value === "highlight" ? "highlight" : "time";
      renderMyPublications();
    });
    $("toggleSidebar").addEventListener("click", () => {
      const collapsed = document.querySelector(".app").classList.contains("sidebar-collapsed");
      setSidebarCollapsed(!collapsed);
    });
    $("toggleReportPanel").addEventListener("click", toggleReportPanel);
    $("workspaceResizer").addEventListener("pointerdown", startWorkspaceResize);
    $("addJournal").addEventListener("click", addJournal);
    $("journalHistory").addEventListener("change", (event) => {
      const journal = state.journalHistory.find((item) => item.name === event.target.value);
      if (!journal) return;
      $("journalName").value = journal.name || "";
      $("journalIssns").value = (journal.issns || []).join(", ");
    });
    $("figureToggle").addEventListener("change", (event) => {
      state.showFigures = event.target.checked;
      if (!state.showFigures) {
        state.figureQueue = [];
        state.queuedFigureIds.clear();
      }
      if (state.mode === "library") renderActiveLibraryTab();
      else renderReport();
    });
    $("searchBox").addEventListener("input", (event) => {
      state.query = event.target.value;
      state.noMatchDates = new Set();
      if (state.mode === "library") renderActiveLibraryTab();
      else renderReport();
    });
    $("librarySearchBox").addEventListener("input", (event) => {
      state.query = event.target.value;
      clearLibraryRangeSelection();
      renderActiveLibraryTab();
    });
    $("clearLibrarySearch").addEventListener("click", () => {
      state.query = "";
      $("librarySearchBox").value = "";
      clearLibraryRangeSelection();
      renderActiveLibraryTab();
      $("librarySearchBox")?.focus({preventScroll: true});
    });
    $("closeAnalysis").addEventListener("click", closeAnalysis);
    $("analysisBackdrop").addEventListener("click", closeAnalysis);
    $("closeInternalBrowser").addEventListener("click", closeInternalBrowser);
    $("openExternalBrowser").addEventListener("click", openExternalBrowser);
    $("closeLibraryQuickLook").addEventListener("click", () => {
      closeLibraryQuickLook();
      $("libraryShell")?.focus({preventScroll: true});
    });
    $("libraryQuickLookDragHandle").addEventListener("pointerdown", startLibraryQuickLookDrag);
    $("libraryQuickLookResize").addEventListener("pointerdown", startLibraryQuickLookResize);
    window.addEventListener("keydown", (event) => {
      if (handleSearchShortcut(event)) return;
      if (handleTextClipboardShortcut(event)) return;
      if (handleLibraryKeydown(event)) return;
      if (event.key !== "Escape") return;
      if (state.libraryQuickLookOpen) {
        event.preventDefault();
        event.stopPropagation();
        closeLibraryQuickLook();
        return;
      }
      if ($("internalBrowser").classList.contains("open")) {
        event.preventDefault();
        event.stopPropagation();
        closeInternalBrowser();
        return;
      }
      hideLibraryContextMenu();
      closeAnalysis();
    }, true);
    window.addEventListener("click", hideLibraryContextMenu);
    window.addEventListener("resize", () => {
      if (state.mode === "library") resizeLibraryViewport();
    });
    window.addEventListener("dragover", (event) => {
      if (event.dataTransfer?.types?.includes("Files")) event.preventDefault();
    });
    window.addEventListener("drop", (event) => {
      if (event.dataTransfer?.types?.includes("Files")) event.preventDefault();
    });

    Promise.resolve().then(loadLibrary).catch((error) => {
      $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    });
    updateSidebarToggle();
    updateReportPanelToggle();
  </script>
</body>
</html>
"""
