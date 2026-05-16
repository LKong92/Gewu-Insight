from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as email_policy
import json
import mimetypes
import re
import subprocess
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from .analysis import queue_codex_analysis
from .config import AppConfig, DEFAULT_ANALYSIS_DIR, DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, DEFAULT_PDF_DIR, load_config
from .download import download_paper
from .http import request_with_retries
from .monitor import fetch_one_arxiv_preprint_source, run_journal_monitor
from .reporting import section_badge_background, section_color
from .sources.arxiv import ARXIV_DEFAULT_CATEGORIES, ARXIV_JOURNAL_NAME
from .sources.publisher import enrich_image_from_landing_page
from .storage import Storage
from .text import clean_text, safe_slug
from .time_utils import today_jst


FETCH_PROGRESS: dict[str, dict[str, Any]] = {}
FETCH_PROGRESS_LOCK = threading.Lock()
ACTIVE_FETCH_DATES: set[str] = set()
JOURNAL_LOGO_CACHE: dict[str, str] = {}
PREPRINT_JOURNALS = [ARXIV_JOURNAL_NAME]


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
    print(f"Paper Monitor UI: {url}")
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
            if parsed.path == "/api/paper":
                self.handle_paper(parse_qs(parsed.query))
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
            if parsed.path == "/api/open-url":
                self.handle_open_url(payload)
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
            if parsed.path == "/api/library/items":
                self.handle_add_library_item(payload)
                return
            if parsed.path == "/api/library/move":
                self.handle_move_library_entry(payload)
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

    def handle_add_library_item(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        folder_id = int(payload.get("folder_id") or 1)
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            paper = storage.get_paper(paper_id)
            if not paper:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
                return
            item = storage.add_library_item(paper_id=paper_id, folder_id=folder_id)
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json({"item": library_item_to_api(item, paper) if item else {}, **snapshot})

    def handle_move_library_entry(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        target_folder_id = int(payload.get("target_folder_id") or 1)
        storage = Storage(self.configured_db_path)
        try:
            if entry_type == "item":
                storage.move_library_item(item_id=int(payload.get("id") or 0), folder_id=target_folder_id)
            elif entry_type == "folder":
                storage.move_library_folder(folder_id=int(payload.get("id") or 0), parent_id=target_folder_id)
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
        if not is_allowed_file(requested, [DEFAULT_PDF_DIR.resolve()]):
            self.send_error_json(HTTPStatus.FORBIDDEN, "PDF is outside allowed folder")
            return
        if not requested.exists() or requested.suffix.lower() != ".pdf":
            self.send_error_json(HTTPStatus.NOT_FOUND, "PDF not found")
            return
        subprocess.run(["open", "-a", "Preview", str(requested)], check=True)
        self.send_json({"status": "opened", "path": str(requested)})

    def handle_open_url(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "A valid http(s) URL is required")
            return
        webbrowser.open(url)
        self.send_json({"status": "opened", "url": url})

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
        if not is_allowed_file(requested, [DEFAULT_PDF_DIR.resolve(), DEFAULT_ANALYSIS_DIR.resolve()]):
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
        "fields": classify_fields(paper),
        "discipline": classify_discipline(paper),
        "image_url": paper.get("image_url") or "",
        "preprint_id": preprint_identifier(paper),
        "preprint_category": preprint_primary_category(paper),
        "preprint_categories": preprint_categories(paper),
        "citation_label": citation_label(paper),
        "bibtex": bibtex_entry(paper),
    }


def library_snapshot(storage: Storage) -> dict[str, Any]:
    return {
        "root_id": 1,
        "folders": [library_folder_to_api(folder) for folder in storage.list_library_folders()],
        "items": [library_item_to_api(item, item) for item in storage.list_library_items()],
    }


def library_folder_to_api(folder: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(folder.get("id") or 0),
        "name": folder.get("name") or "New Folder",
        "parent_id": int(folder["parent_id"]) if folder.get("parent_id") is not None else None,
    }


def library_item_to_api(item: dict[str, Any], paper: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(item.get("id") or 0),
        "folder_id": int(item.get("folder_id") or 1),
        "paper_id": paper.get("paper_id") or item.get("paper_id") or "",
        "paper": paper_to_api(paper),
    }


def citation_label(paper: dict[str, Any]) -> str:
    authors = full_author_names(paper) or author_summary(paper)
    lead = author_last_name(authors[0]) if authors else "Unknown"
    if len(authors) > 1:
        lead = f"{lead} et al."
    journal = paper.get("journal") or "Unknown Journal"
    volume = paper_volume(paper)
    page = paper_page(paper)
    year = publication_year(paper)
    source = journal
    if volume:
        source = f"{source} {volume}"
    if page:
        source = f"{source}, {page}"
    return f"{lead} {source} ({year})" if year else f"{lead} {source}"


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
    value = raw.get("volume") or (raw.get("biblio") or {}).get("volume")
    return clean_text(str(value or ""))


def paper_page(paper: dict[str, Any]) -> str:
    raw = parse_raw_json(paper)
    value = raw.get("page") or raw.get("article-number") or (raw.get("biblio") or {}).get("first_page")
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


def missing_fetch_journals_for_date(storage: Storage, selected: str, journals: list[str]) -> list[str]:
    if not journals:
        return []
    placeholders = ", ".join(["?"] * len(journals))
    rows = storage.conn.execute(
        f"""
        SELECT DISTINCT journal
        FROM fetch_runs
        WHERE monitor_type = 'journal'
          AND window_start <= ?
          AND window_end >= ?
          AND status IN ('success', 'empty')
          AND journal IN ({placeholders})
        """,
        (selected, selected, *journals),
    ).fetchall()
    fetched = {row["journal"] for row in rows}
    return [journal for journal in journals if journal not in fetched]


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
    deleted = delete_allowed_files(paths, [DEFAULT_PDF_DIR.resolve()])
    cleanup_empty_parents(deleted, DEFAULT_PDF_DIR.resolve())
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


def read_text_file(path: str) -> str:
    if not path:
        return ""
    requested = Path(path).expanduser().resolve()
    if not is_allowed_file(requested, [DEFAULT_ANALYSIS_DIR.resolve()]) or not requested.exists():
        return ""
    return requested.read_text(encoding="utf-8")


def is_allowed_file(path: Path, roots: list[Path]) -> bool:
    return any(is_relative_to(path, root) for root in roots)


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
  <title>Paper Monitor</title>
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
    body { margin: 0; height: 100vh; overflow: hidden; }
    button, input, select { font: inherit; }
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
    .app.sidebar-collapsed { --sidebar-width: 0px; grid-template-columns: 0 minmax(0, 1fr); }
    .app.sidebar-collapsed .sidebar { padding: 0; border-right: 0; overflow: hidden; }
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
    .brand { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
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
    .preprint-category-list { display: flex; flex-direction: column; gap: 6px; padding-left: 14px; }
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
    .main { padding: 24px 30px 24px; min-width: 0; height: 100vh; overflow: hidden; }
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
    .report-column { grid-area: report; min-width: 0; height: 100%; min-height: 0; overflow-y: auto; padding-right: 18px; }
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
      flex-wrap: wrap;
    }
    .toolbar h2 { margin: 0; font-size: 24px; letter-spacing: 0; }
    .toolbar-actions { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
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
      gap: 8px;
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
    .library-shell {
      display: grid;
      grid-template-columns: minmax(180px, 240px) minmax(280px, 1fr) minmax(260px, 340px);
      gap: 12px;
      min-height: 560px;
      outline: none;
    }
    .library-pane {
      min-width: 0;
      min-height: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      overflow: auto;
    }
    .library-pane-header {
      position: sticky;
      top: 0;
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
    .library-tree, .library-list { padding: 8px; }
    .library-row {
      width: 100%;
      min-height: 32px;
      border: 1px solid transparent;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      display: grid;
      grid-template-columns: 20px minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 5px 8px;
      text-align: left;
      cursor: default;
      font-size: 13px;
    }
    .library-row:hover { background: #f8fafc; }
    .library-row.active { background: #e8f3f4; border-color: #b7dadd; }
    .library-row.current-folder { font-weight: 750; }
    .library-row.drag-over { border-color: var(--accent); background: #eef9f8; }
    .library-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .library-meta { color: var(--muted); font-size: 12px; }
    .library-indent { display: inline-block; }
    .library-detail {
      padding: 14px;
      color: #344054;
      font-size: 13px;
      line-height: 1.5;
    }
    .library-detail h3 { margin: 0 0 8px; color: var(--ink); font-size: 16px; line-height: 1.3; letter-spacing: 0; }
    .library-detail dl { display: grid; grid-template-columns: 74px minmax(0, 1fr); gap: 6px 10px; margin: 12px 0; }
    .library-detail dt { color: var(--muted); }
    .library-detail dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
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
    .papers { display: grid; gap: 12px; }
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
      .report-column, .analysis-panel { height: auto; overflow: visible; }
      .workspace.report-collapsed .report-column { display: block; }
      .paper.with-figure .paper-layout { grid-template-columns: 1fr; }
      .paper-head { flex-direction: column; }
      .paper-badges { justify-content: flex-start; max-width: 100%; }
      .library-shell { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <h1>Paper Monitor</h1>
        <div class="today" id="todayLabel"></div>
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
            <h2 id="reportTitle"></h2>
            <div class="toolbar-actions">
              <input class="search" id="searchBox" placeholder="Search title, abstract, DOI">
              <button class="smallbtn" id="reportMode">Report</button>
              <button class="smallbtn" id="libraryMode">Library</button>
              <label class="toolbar-toggle"><input type="checkbox" id="figureToggle" checked> Figures</label>
            </div>
          </div>
          <div class="summary" id="summary"></div>
          <div class="report-tabs" id="reportTabs"></div>
          <div class="library-controls" id="libraryControls">
            <button class="smallbtn" id="newLibraryFolder" type="button">New Folder</button>
            <button class="smallbtn" id="refreshLibrary" type="button">Refresh Library</button>
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
    const state = {
      selectedDate: initialToday,
      viewYear: Number(initialToday.slice(0, 4)),
      viewMonth: Number(initialToday.slice(5, 7)),
      journals: [],
      journalsConfig: [],
      journalHistory: [],
      selectedJournals: new Set(),
      selectedPreprintCategories: new Set(DEFAULT_ARXIV_CATEGORIES),
      selectedFields: new Set(["physics", "materials", "quantum_information"]),
      counts: {},
      papers: [],
      libraryFolders: [],
      libraryItems: [],
      libraryRootId: 1,
      libraryCurrentFolderId: 1,
      librarySelection: {type: "folder", id: 1},
      mode: "report",
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

    async function loadReport() {
      const selectedDate = state.selectedDate;
      const sequence = ++state.reportSequence;
      const cached = state.reportCache[selectedDate];
      if (cached) {
        setPendingFetchDate(selectedDate, reportStillFetching(cached));
        updateCalendarCountFromReport(selectedDate, cached);
        applyReportData(selectedDate, cached, sequence);
      } else {
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
      if (state.mode === "library") loadLibrary();
      else renderReport();
      if ((data.missingJournals || []).length && !state.papers.length) {
        $("papers").innerHTML = `<div class="empty">Fetching papers for this date in the background. You can keep browsing other dates.</div>`;
      }
    }

    async function refreshMissingDateInBackground(selectedDate) {
      if (state.fetchingDates.has(selectedDate)) return;
      setPendingFetchDate(selectedDate, true);
      state.fetchingDates.add(selectedDate);
      state.fetchProgress[selectedDate] = state.fetchProgress[selectedDate] || {percent: 0, completed: 0, total: 0, active: true};
      startProgressPolling(selectedDate);
      renderCalendar();
      if (selectedDate === state.selectedDate) renderReport();
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
        if (selectedDate === state.selectedDate) {
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
          if (selectedDate === state.selectedDate) renderReport();
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
      if (selectedDate === state.selectedDate) renderReport();
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
        if (selectedDate === state.selectedDate) renderReport();
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
          if (selectedDate === state.selectedDate && state.fetchingDates.has(selectedDate)) renderReport();
        }
        return data.progress || null;
      } catch (error) {
        return null;
      }
    }

    async function loadLibrary() {
      state.mode = "library";
      const res = await fetch("/api/library");
      const data = await res.json();
      applyLibrarySnapshot(data);
      renderLibrary();
    }

    function applyLibrarySnapshot(data) {
      state.libraryRootId = Number(data.root_id || 1);
      state.libraryFolders = data.folders || [];
      state.libraryItems = data.items || [];
      if (!libraryFolderById(state.libraryCurrentFolderId)) state.libraryCurrentFolderId = state.libraryRootId;
      if (!librarySelectionExists(state.librarySelection)) {
        state.librarySelection = {type: "folder", id: state.libraryCurrentFolderId};
      }
    }

    function libraryFolderById(id) {
      return state.libraryFolders.find((folder) => Number(folder.id) === Number(id));
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
        .sort((a, b) => (a.name || "").localeCompare(b.name || ""));
    }

    function libraryFolderItems(folderId) {
      const query = state.query.trim().toLowerCase();
      return state.libraryItems
        .filter((item) => Number(item.folder_id) === Number(folderId))
        .filter((item) => {
          if (!query) return true;
          const paper = item.paper || {};
          const haystack = `${paper.citation_label || ""} ${paper.title || ""} ${paper.abstract || ""} ${paper.doi || ""} ${paper.journal || ""} ${(paper.authors || []).join(" ")}`.toLowerCase();
          return haystack.includes(query);
        })
        .sort((a, b) => (a.paper?.citation_label || "").localeCompare(b.paper?.citation_label || ""));
    }

    function libraryVisibleEntries() {
      const query = state.query.trim().toLowerCase();
      const folders = libraryChildFolders(state.libraryCurrentFolderId)
        .filter((folder) => !query || (folder.name || "").toLowerCase().includes(query))
        .map((folder) => ({type: "folder", id: Number(folder.id)}));
      const items = libraryFolderItems(state.libraryCurrentFolderId)
        .map((item) => ({type: "item", id: Number(item.id)}));
      return folders.concat(items);
    }

    async function createLibraryFolder(parentId) {
      const res = await fetch("/api/library/folders", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({parent_id: parentId || state.libraryCurrentFolderId, name: "New Folder"})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not create folder");
      applyLibrarySnapshot(data);
      state.libraryCurrentFolderId = Number(data.folder?.parent_id || parentId || state.libraryCurrentFolderId);
      if (data.folder?.id) state.librarySelection = {type: "folder", id: Number(data.folder.id)};
      renderLibrary();
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
          body: JSON.stringify({paper_id: paperId, folder_id: state.libraryRootId || 1})
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
      state.libraryCurrentFolderId = Number(targetFolderId || state.libraryRootId);
      state.librarySelection = {type, id: Number(id)};
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
      $("todayLabel").textContent = localIsoDate(new Date());
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
      root.appendChild(label);

      const counts = {};
      arxivPapers.forEach((paper) => {
        paperPreprintCategories(paper).forEach((category) => counts[category] = (counts[category] || 0) + 1);
      });
      categoryRoot.innerHTML = "";
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
      stopArxivUpdateCountdown();
      $("libraryControls").classList.remove("open");
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

    function renderLibrary() {
      state.mode = "library";
      stopArxivUpdateCountdown();
      $("libraryControls").classList.add("open");
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("reportTitle").textContent = "Library";
      const root = $("papers");
      const folder = libraryFolderById(state.libraryCurrentFolderId) || libraryFolderById(state.libraryRootId) || {name: "Library"};
      const visible = libraryVisibleEntries();
      $("summary").textContent = `${state.libraryItems.length} shortcuts · ${visible.length} shown · Current folder: ${folder.name}`;
      root.innerHTML = `
        <div class="library-shell" id="libraryShell" tabindex="0">
          <section class="library-pane" data-library-drop-folder="${state.libraryRootId}">
            <div class="library-pane-header">Folders</div>
            <div class="library-tree" id="libraryTree"></div>
          </section>
          <section class="library-pane" data-library-drop-folder="${state.libraryCurrentFolderId}">
            <div class="library-pane-header">${escapeHtml(folder.name || "Library")}</div>
            <div class="library-list" id="libraryList"></div>
          </section>
          <aside class="library-pane">
            <div class="library-pane-header">Details</div>
            <div class="library-detail" id="libraryDetail"></div>
          </aside>
        </div>
        <div class="library-context-menu" id="libraryContextMenu">
          <button type="button" data-action="new-folder">New Folder</button>
        </div>
      `;
      renderLibraryTree();
      renderLibraryList();
      renderLibraryDetail();
      wireLibraryInteractions();
    }

    function renderLibraryTree() {
      const root = $("libraryTree");
      if (!root) return;
      root.innerHTML = renderLibraryFolderRows(state.libraryRootId, 0, true);
    }

    function renderLibraryFolderRows(folderId, depth, includeSelf) {
      const folder = libraryFolderById(folderId);
      let html = "";
      if (folder && includeSelf) html += libraryRowMarkup("folder", folder, depth, true);
      libraryChildFolders(folderId).forEach((child) => {
        html += libraryRowMarkup("folder", child, depth + (includeSelf ? 1 : 0), true);
        html += renderLibraryFolderRows(child.id, depth + (includeSelf ? 2 : 1), false);
      });
      return html;
    }

    function renderLibraryList() {
      const root = $("libraryList");
      if (!root) return;
      const folders = libraryChildFolders(state.libraryCurrentFolderId);
      const items = libraryFolderItems(state.libraryCurrentFolderId);
      const rows = folders.map((folder) => libraryRowMarkup("folder", folder, 0, false))
        .concat(items.map((item) => libraryRowMarkup("item", item, 0, false)));
      root.innerHTML = rows.join("") || `<div class="empty">Right-click to create a folder, or add papers from Report.</div>`;
    }

    function libraryRowMarkup(type, entry, depth, treeRow) {
      const id = Number(entry.id);
      const selected = state.librarySelection?.type === type && Number(state.librarySelection.id) === id;
      const current = type === "folder" && Number(state.libraryCurrentFolderId) === id;
      const paper = entry.paper || {};
      const name = type === "folder" ? entry.name : (paper.citation_label || paper.title || "Untitled paper");
      const meta = type === "folder" ? libraryFolderItems(id).length : (paper.journal || "");
      const icon = type === "folder" ? "▸" : "○";
      const indent = treeRow ? `<span class="library-indent" style="width:${depth * 14}px"></span>` : "";
      return `
        <button class="library-row${selected ? " active" : ""}${current ? " current-folder" : ""}"
          type="button"
          draggable="${id === state.libraryRootId && type === "folder" ? "false" : "true"}"
          data-library-type="${type}"
          data-library-id="${id}"
          ${type === "folder" ? `data-library-drop-folder="${id}"` : ""}>
          <span>${indent}${icon}</span>
          <span class="library-name">${escapeHtml(name)}</span>
          <span class="library-meta">${escapeHtml(String(meta || ""))}</span>
        </button>
      `;
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
      root.innerHTML = `
        <h3>${escapeHtml(paper.title || "Untitled paper")}</h3>
        <div class="actions">
          ${paper.merged_pdf_path ? `<button class="action primary" data-action="preview-library-pdf">Open in Preview</button>` : ""}
          ${paper.url ? `<button class="action" data-action="open-library-page">Open Page</button>` : ""}
        </div>
        <div class="library-detail-status" id="libraryDetailStatus"></div>
        <dl>
          <dt>Citation</dt><dd>${escapeHtml(paper.citation_label || "")}</dd>
          <dt>Journal</dt><dd>${escapeHtml(paper.journal || "")}</dd>
          <dt>Date</dt><dd>${escapeHtml(paper.publication_date || "")}</dd>
          <dt>DOI</dt><dd>${escapeHtml(paper.doi || paper.preprint_id || "")}</dd>
          <dt>Fields</dt><dd>${paperFieldValues(paper).map((field) => escapeHtml(FIELD_LABELS[field] || field)).join(", ")}</dd>
          <dt>PDF</dt><dd>${escapeHtml(paper.merged_pdf_path || "No local PDF")}</dd>
        </dl>
        <strong>BibTeX</strong>
        <pre class="bibtex-box">${escapeHtml(paper.bibtex || "")}</pre>
      `;
      root.querySelector('[data-action="preview-library-pdf"]')?.addEventListener("click", () => openLibraryPdfInPreview(paper));
      root.querySelector('[data-action="open-library-page"]')?.addEventListener("click", () => openInternalBrowser(paper.url, paper.title || "Publisher page"));
    }

    function wireLibraryInteractions() {
      const shell = $("libraryShell");
      if (!shell) return;
      shell.focus();
      shell.querySelectorAll(".library-row").forEach((row) => {
        row.addEventListener("click", () => {
          const type = row.dataset.libraryType;
          const id = Number(row.dataset.libraryId);
          selectLibraryEntry(type, id);
        });
        row.addEventListener("dblclick", () => {
          if (row.dataset.libraryType === "folder") openLibraryFolder(Number(row.dataset.libraryId));
        });
        row.addEventListener("dragstart", (event) => {
          event.dataTransfer.setData("application/x-paper-monitor-library", JSON.stringify({
            type: row.dataset.libraryType,
            id: Number(row.dataset.libraryId)
          }));
          event.dataTransfer.effectAllowed = "move";
        });
        row.addEventListener("contextmenu", (event) => {
          event.stopPropagation();
          showLibraryContextMenu(event, row.dataset.libraryDropFolder || state.libraryCurrentFolderId);
        });
      });
      shell.querySelectorAll("[data-library-drop-folder]").forEach((target) => {
        target.addEventListener("dragover", (event) => {
          if (!event.dataTransfer.types.includes("application/x-paper-monitor-library")) return;
          event.preventDefault();
          target.classList.add("drag-over");
        });
        target.addEventListener("dragleave", () => target.classList.remove("drag-over"));
        target.addEventListener("drop", async (event) => {
          if (!event.dataTransfer.types.includes("application/x-paper-monitor-library")) return;
          event.preventDefault();
          target.classList.remove("drag-over");
          const payload = JSON.parse(event.dataTransfer.getData("application/x-paper-monitor-library") || "{}");
          const folderId = Number(target.dataset.libraryDropFolder || state.libraryCurrentFolderId);
          if (payload.type && payload.id) await moveLibraryEntry(payload.type, payload.id, folderId);
        });
      });
      shell.addEventListener("contextmenu", (event) => showLibraryContextMenu(event, state.libraryCurrentFolderId));
    }

    function selectLibraryEntry(type, id) {
      state.librarySelection = {type, id: Number(id)};
      renderLibrary();
    }

    function openLibraryFolder(folderId) {
      if (!libraryFolderById(folderId)) return;
      state.libraryCurrentFolderId = Number(folderId);
      state.librarySelection = {type: "folder", id: Number(folderId)};
      renderLibrary();
    }

    function selectedLibraryPaper() {
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

    function showLibraryContextMenu(event, parentId) {
      event.preventDefault();
      const menu = $("libraryContextMenu");
      if (!menu) return;
      menu.dataset.parentId = parentId || state.libraryCurrentFolderId;
      menu.style.left = `${event.clientX}px`;
      menu.style.top = `${event.clientY}px`;
      menu.classList.add("open");
      menu.querySelector('[data-action="new-folder"]').onclick = async () => {
        hideLibraryContextMenu();
        await createLibraryFolder(Number(menu.dataset.parentId || state.libraryCurrentFolderId));
      };
    }

    function hideLibraryContextMenu() {
      $("libraryContextMenu")?.classList.remove("open");
    }

    function handleLibraryKeydown(event) {
      if (state.mode !== "library") return false;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName)) return false;
      const handled = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " "].includes(event.key);
      if (!handled) return false;
      event.preventDefault();
      if (event.key === " ") {
        const paper = selectedLibraryPaper();
        if (paper?.merged_pdf_path) openLibraryPdfInPreview(paper);
        return true;
      }
      if (event.key === "ArrowLeft") {
        const current = libraryFolderById(state.libraryCurrentFolderId);
        if (current?.parent_id) openLibraryFolder(Number(current.parent_id));
        return true;
      }
      if (event.key === "ArrowRight") {
        if (state.librarySelection?.type === "folder") openLibraryFolder(Number(state.librarySelection.id));
        return true;
      }
      const entries = libraryVisibleEntries();
      if (!entries.length) return true;
      const currentIndex = entries.findIndex((entry) => entry.type === state.librarySelection?.type && Number(entry.id) === Number(state.librarySelection?.id));
      const fallback = event.key === "ArrowDown" ? 0 : entries.length - 1;
      const nextIndex = currentIndex < 0
        ? fallback
        : Math.max(0, Math.min(entries.length - 1, currentIndex + (event.key === "ArrowDown" ? 1 : -1)));
      state.librarySelection = entries[nextIndex];
      renderLibrary();
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
    }

    function renderPaper(paper) {
      const article = document.createElement("article");
      const showFigure = state.showFigures && paper.image_url;
      article.className = `paper${showFigure ? " with-figure" : ""}`;
      article.dataset.paperId = paper.paper_id;
      const authorText = authorLine(paper);
      const identifierText = paper.doi || paper.preprint_id || "no DOI";
      const preprintCategoryText = paper.preprint_category || "";
      const fieldBadges = paperFieldValues(paper)
        .map((field) => `<span class="field-badge">${escapeHtml(FIELD_LABELS[field] || field)}</span>`)
        .join("");
      article.innerHTML = `
        <div class="paper-layout">
          ${showFigure ? `<figure class="paper-figure"><img src="${escapeAttr(paper.image_url)}" alt="${escapeAttr(paper.title || "Paper figure")}" loading="lazy"></figure>` : ""}
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
              ${paper.url ? `<button class="action" data-action="open-page" title="Open publisher page inside Paper Monitor">↗ Open</button>` : ""}
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
          article.classList.remove("with-figure");
          article.querySelector(".paper-figure")?.remove();
        }, {once: true});
      } else if (state.showFigures && paper.paper_id && !state.figureFailures.has(paper.paper_id)) {
        queuePaperFigureHydration(paper.paper_id);
      }
      return article;
    }

    function queuePaperFigureHydration(paperId) {
      if (!paperId || state.figureFailures.has(paperId) || state.figureRequests[paperId] || state.queuedFigureIds.has(paperId)) return;
      state.queuedFigureIds.add(paperId);
      state.figureQueue.push(paperId);
      drainFigureQueue();
    }

    function drainFigureQueue() {
      while (state.showFigures && state.activeFigureHydrations < state.maxFigureHydrations && state.figureQueue.length) {
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
          return;
        }
        updatePaperState(paperId, data.paper);
        if (state.mode === "library") renderLibrary();
        else renderReport();
      } catch (error) {
        state.figureFailures.add(paperId);
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
        if (state.mode === "library") renderLibrary();
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
        if (state.mode === "library") renderLibrary();
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
        if (state.mode === "library") renderLibrary();
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
    $("reportMode").addEventListener("click", renderReport);
    $("libraryMode").addEventListener("click", loadLibrary);
    $("refreshLibrary").addEventListener("click", loadLibrary);
    $("newLibraryFolder").addEventListener("click", () => createLibraryFolder(state.libraryCurrentFolderId));
    $("toggleSidebar").addEventListener("click", () => {
      document.querySelector(".app").classList.toggle("sidebar-collapsed");
      updateSidebarToggle();
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
      if (state.mode === "library") renderLibrary();
      else renderReport();
    });
    $("searchBox").addEventListener("input", (event) => {
      state.query = event.target.value;
      state.noMatchDates = new Set();
      if (state.mode === "library") renderLibrary();
      else renderReport();
    });
    $("closeAnalysis").addEventListener("click", closeAnalysis);
    $("analysisBackdrop").addEventListener("click", closeAnalysis);
    $("closeInternalBrowser").addEventListener("click", closeInternalBrowser);
    $("openExternalBrowser").addEventListener("click", openExternalBrowser);
    window.addEventListener("keydown", (event) => {
      if (handleLibraryKeydown(event)) return;
      if (event.key !== "Escape") return;
      if ($("internalBrowser").classList.contains("open")) {
        closeInternalBrowser();
        return;
      }
      hideLibraryContextMenu();
      closeAnalysis();
    });
    window.addEventListener("click", hideLibraryContextMenu);
    window.addEventListener("dragover", (event) => {
      if (event.dataTransfer?.types?.includes("Files")) event.preventDefault();
    });
    window.addEventListener("drop", (event) => {
      if (event.dataTransfer?.types?.includes("Files")) event.preventDefault();
    });

    Promise.resolve().then(loadMonth).then(loadReport).catch((error) => {
      $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    });
    updateSidebarToggle();
    updateReportPanelToggle();
  </script>
</body>
</html>
"""
