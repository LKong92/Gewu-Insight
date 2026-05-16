from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as email_policy
import json
import mimetypes
import subprocess
import threading
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .analysis import queue_codex_analysis
from .config import AppConfig, DEFAULT_ANALYSIS_DIR, DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH, DEFAULT_PDF_DIR, load_config
from .download import download_paper
from .http import request_with_retries
from .monitor import run_journal_monitor
from .reporting import section_badge_background, section_color
from .storage import Storage
from .text import safe_slug
from .time_utils import today_jst


FETCH_PROGRESS: dict[str, dict[str, Any]] = {}
FETCH_PROGRESS_LOCK = threading.Lock()


def run_ui_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Path = DEFAULT_DB_PATH,
    open_browser: bool = False,
) -> None:
    config = load_config()
    journals = [journal.name for journal in config.journals]

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
            if parsed.path == "/api/journals/add":
                self.handle_add_journal(payload)
                return
            if parsed.path == "/api/journals/remove":
                self.handle_remove_journal(payload)
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
            if auto_fetch and selected_date <= today_jst() and missing_journals:
                storage.close()
                config = load_config()
                fetch_config = config_for_journals(config, missing_journals)
                fetch_storage = Storage(self.configured_db_path)
                start_fetch_progress(selected, missing_journals)
                try:
                    run_journal_monitor(
                        config=fetch_config,
                        storage=fetch_storage,
                        start_date=selected_date,
                        end_date=selected_date,
                        enrich=True,
                        progress_callback=lambda journal, completed, total: update_fetch_progress(
                            selected,
                            journal=journal,
                            completed=completed,
                            total=total,
                        ),
                    )
                    fetched = True
                finally:
                    finish_fetch_progress(selected)
                    fetch_storage.close()
                storage = Storage(self.configured_db_path)
                self.configured_journals = [journal.name for journal in config.journals]
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
        self.refresh_journals()
        from_date = first(query, "from_date") or ""
        until_date = first(query, "until_date") or ""
        journal = first(query, "journal") or ""
        storage = Storage(self.configured_db_path)
        try:
            papers = list_library_papers(storage, from_date=from_date, until_date=until_date, journal=journal)
        finally:
            storage.close()
        self.send_json(
            {
                "papers": [paper_to_api(paper) for paper in papers],
                "journals": self.configured_journals,
            }
        )

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

    def handle_journals(self) -> None:
        raw = read_config_json()
        self.send_json({"journals": raw.get("journals", [])})

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
            {
                "name": resolved_name,
                "issns": issns,
                "openalex_source_id": openalex_source_id,
                "section_policy": str(payload.get("section_policy") or preset.get("section_policy") or "science"),
                "skip_landing_enrichment": bool(payload.get("skip_landing_enrichment", preset.get("skip_landing_enrichment", True))),
            }
        )
        write_config_json(raw)
        self.refresh_journals()
        self.send_json({"journals": journals})

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
        self.send_json({"journals": raw["journals"]})

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
        self.configured_journals = [journal.name for journal in config.journals]


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
    }


def count_by_journal(papers: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for paper in papers:
        journal = paper.get("journal") or "Unknown"
        counts[journal] = counts.get(journal, 0) + 1
    return counts


def author_summary(paper: dict[str, Any]) -> list[str]:
    raw = parse_raw_json(paper)
    names = authors_from_openalex(raw) or authors_from_crossref(raw)
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


def list_library_papers(
    storage: Storage,
    *,
    from_date: str = "",
    until_date: str = "",
    journal: str = "",
) -> list[dict[str, Any]]:
    clauses = [
        "(download_status IN ('success', 'partial') OR analysis_status != 'not_started')",
        "(section_allowed IS NULL OR section_allowed != 0)",
    ]
    params: list[Any] = []
    if from_date:
        clauses.append("publication_date >= ?")
        params.append(from_date)
    if until_date:
        clauses.append("publication_date <= ?")
        params.append(until_date)
    if journal:
        clauses.append("journal = ?")
        params.append(journal)
    rows = storage.conn.execute(
        f"""
        SELECT *
        FROM papers
        WHERE {' AND '.join(clauses)}
        ORDER BY publication_date DESC, journal ASC, title ASC
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def start_fetch_progress(selected: str, journals: list[str]) -> None:
    with FETCH_PROGRESS_LOCK:
        FETCH_PROGRESS[selected] = {
            "active": True,
            "completed": 0,
            "total": len(journals),
            "percent": 0,
            "currentJournal": "",
        }


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
    }


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
    button, input { font: inherit; }
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
    @keyframes fetchingPulse {
      0%, 100% { opacity: 0.35; transform: scale(0.86); }
      50% { opacity: 1; transform: scale(1); }
    }
    .filters { display: flex; flex-direction: column; gap: 8px; }
    .filter-title { font-size: 13px; color: var(--muted); }
    .journal-toggle, .section-toggle {
      display: grid;
      grid-template-columns: 18px 1fr auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 8px 10px;
      background: #fff;
    }
    .journal-toggle input, .section-toggle input { width: 16px; height: 16px; }
    .journal-toggle span, .section-toggle span { font-size: 14px; min-width: 0; }
    .journal-toggle b, .section-toggle b { color: var(--muted); font-size: 12px; font-weight: 500; }
    .main { padding: 24px 30px 24px; min-width: 0; height: 100vh; overflow: hidden; }
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
    .search {
      width: min(360px, 70vw);
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 7px;
      padding: 0 12px;
      background: #fff;
    }
    .summary { color: var(--muted); font-size: 14px; margin: -8px 0 18px; }
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
    .paper-head { display: flex; gap: 12px; align-items: flex-start; justify-content: space-between; }
    .paper h3 { margin: 0; font-size: 18px; line-height: 1.35; letter-spacing: 0; }
    .journal-group {
      margin: 8px 0 4px;
      color: var(--ink);
      font-size: 18px;
      font-weight: 750;
    }
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
        <div class="filter-title">Section Filter</div>
        <div id="sectionFilters"></div>
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
              <button class="smallbtn" id="selectAll">All Journals</button>
            </div>
          </div>
          <div class="summary" id="summary"></div>
          <div class="library-controls" id="libraryControls">
            <input type="date" id="libraryFrom" title="From date">
            <input type="date" id="libraryUntil" title="Until date">
            <select id="libraryJournal" title="Journal"></select>
            <button class="smallbtn" id="refreshLibrary">Refresh Library</button>
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
    </main>
  </div>
  <script>
    const initialToday = localIsoDate(new Date());
    const state = {
      selectedDate: initialToday,
      viewYear: Number(initialToday.slice(0, 4)),
      viewMonth: Number(initialToday.slice(5, 7)),
      journals: [],
      journalsConfig: [],
      selectedJournals: new Set(),
      subjectFilter: "physics",
      selectedSections: new Set(),
      counts: {},
      papers: [],
      libraryPapers: [],
      mode: "report",
      libraryFrom: "",
      libraryUntil: "",
      libraryJournal: "",
      noteWidth: 460,
      query: "",
      reportSequence: 0,
      reportCache: {},
      fetchingDates: new Set(),
      fetchProgress: {},
      progressPollers: {}
    };

    const $ = (id) => document.getElementById(id);
    const fmtMonth = (year, month) => `${year}-${String(month).padStart(2, "0")}`;

    function localIsoDate(value) {
      const year = value.getFullYear();
      const month = String(value.getMonth() + 1).padStart(2, "0");
      const day = String(value.getDate()).padStart(2, "0");
      return `${year}-${month}-${day}`;
    }

    function statusClass(status) {
      if (["success", "partial", "created", "broad_reading"].some((x) => status.includes(x))) return "ok";
      if (["failed", "error"].some((x) => status.includes(x))) return "err";
      if (["skipped", "pending", "queued"].some((x) => status.includes(x))) return "warn";
      return "";
    }

    async function loadMonth() {
      const res = await fetch(`/api/month?year=${state.viewYear}&month=${state.viewMonth}`);
      const data = await res.json();
      state.journals = data.journals;
      syncSelectedJournals();
      state.counts = data.counts;
      renderCalendar();
      renderFilters();
      renderSubjectFilters();
      renderLibraryJournalOptions();
      await loadJournalSettings();
    }

    async function loadReport() {
      const selectedDate = state.selectedDate;
      const sequence = ++state.reportSequence;
      const cached = state.reportCache[selectedDate];
      if (cached) {
        applyReportData(selectedDate, cached, sequence);
      } else {
        showReportLoading(selectedDate);
      }
      const res = await fetch(`/api/report?date=${selectedDate}&auto_fetch=0`);
      const data = await res.json();
      state.reportCache[selectedDate] = data;
      applyReportData(selectedDate, data, sequence);
      if ((data.missingJournals || []).length) {
        refreshMissingDateInBackground(selectedDate);
      }
    }

    function showReportLoading(selectedDate) {
      if (selectedDate !== state.selectedDate) return;
      $("reportTitle").textContent = `${selectedDate} Report`;
      $("summary").textContent = "Loading local data...";
      $("papers").innerHTML = `<div class="empty">Loading papers for this date...</div>`;
    }

    function applyReportData(selectedDate, data, sequence) {
      if (selectedDate !== state.selectedDate || sequence !== state.reportSequence) return;
      state.journals = data.journals || state.journals;
      syncSelectedJournals();
      state.papers = data.papers || [];
      renderSubjectFilters();
      renderSectionFilters();
      renderFilters();
      if (state.mode === "library") loadLibrary();
      else renderReport();
      if ((data.missingJournals || []).length && !state.papers.length) {
        $("papers").innerHTML = `<div class="empty">Fetching papers for this date in the background. You can keep browsing other dates.</div>`;
      }
    }

    async function refreshMissingDateInBackground(selectedDate) {
      if (state.fetchingDates.has(selectedDate)) return;
      state.fetchingDates.add(selectedDate);
      state.fetchProgress[selectedDate] = state.fetchProgress[selectedDate] || {percent: 0, completed: 0, total: 0, active: true};
      startProgressPolling(selectedDate);
      renderCalendar();
      if (selectedDate === state.selectedDate) renderReport();
      try {
        const res = await fetch(`/api/report?date=${selectedDate}`);
        const data = await res.json();
        state.reportCache[selectedDate] = data;
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
        state.fetchingDates.delete(selectedDate);
        await refreshFetchProgress(selectedDate);
        stopProgressPolling(selectedDate);
        renderCalendar();
        if (selectedDate === state.selectedDate) renderReport();
      }
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
      } catch (error) {
        return;
      }
    }

    async function loadLibrary() {
      state.mode = "library";
      const params = new URLSearchParams();
      if (state.libraryFrom) params.set("from_date", state.libraryFrom);
      if (state.libraryUntil) params.set("until_date", state.libraryUntil);
      if (state.libraryJournal) params.set("journal", state.libraryJournal);
      const res = await fetch(`/api/library?${params.toString()}`);
      const data = await res.json();
      state.libraryPapers = data.papers || [];
      renderLibraryJournalOptions();
      renderLibrary();
    }

    function syncSelectedJournals() {
      const known = new Set(state.journals);
      state.selectedJournals = new Set([...state.selectedJournals].filter((journal) => known.has(journal)));
      if (!state.selectedJournals.size) state.journals.forEach((journal) => state.selectedJournals.add(journal));
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
        const button = document.createElement("button");
        button.className = `day${iso === state.selectedDate ? " active" : ""}${isFetching ? " fetching" : ""}`;
        button.innerHTML = `<span class="daynum">${day}</span>${
          isFetching
            ? `<span class="fetching-dot" title="Fetching"></span>`
            : `<span class="count">${total || ""}</span>`
        }`;
        button.addEventListener("click", async () => {
          state.selectedDate = iso;
          renderCalendar();
          await loadReport();
        });
        root.appendChild(button);
      }
    }

    function renderFilters() {
      const counts = {};
      state.papers
        .filter((paper) => subjectMatches(paper) && sectionMatches(paper))
        .forEach((paper) => counts[paper.journal] = (counts[paper.journal] || 0) + 1);
      const root = $("journalFilters");
      root.innerHTML = "";
      state.journals.forEach((journal) => {
        const label = document.createElement("label");
        label.className = "journal-toggle";
        label.innerHTML = `<input type="checkbox" ${state.selectedJournals.has(journal) ? "checked" : ""}>
          <span>${escapeHtml(journal)}</span><b>${counts[journal] || 0}</b>`;
        label.querySelector("input").addEventListener("change", (event) => {
          if (event.target.checked) state.selectedJournals.add(journal);
          else state.selectedJournals.delete(journal);
          renderSectionFilters();
          renderReport();
        });
        root.appendChild(label);
      });
    }

    function renderSubjectFilters() {
      const options = [
        ["physics", "Physics"],
        ["materials", "Materials"],
        ["chemistry", "Chemistry"],
        ["all", "All Fields"],
        ["other", "Other Fields"]
      ];
      const root = $("subjectFilters");
      root.innerHTML = "";
      options.forEach(([value, label]) => {
        const count = state.papers.filter((paper) => paperMatchesField(paper, value)).length;
        const button = document.createElement("button");
        button.className = `subject-option${state.subjectFilter === value ? " active" : ""}`;
        button.textContent = `${label} (${count})`;
        button.addEventListener("click", () => {
          state.subjectFilter = value;
          renderSubjectFilters();
          renderFilters();
          renderSectionFilters();
          renderReport();
        });
        root.appendChild(button);
      });
    }

    function renderLibraryJournalOptions() {
      const select = $("libraryJournal");
      if (!select) return;
      const current = state.libraryJournal;
      select.innerHTML = `<option value="">All journals</option>` + state.journals
        .map((journal) => `<option value="${escapeAttr(journal)}">${escapeHtml(journal)}</option>`)
        .join("");
      select.value = current;
    }

    async function loadJournalSettings() {
      const res = await fetch("/api/journals");
      const data = await res.json();
      state.journalsConfig = data.journals || [];
      renderJournalSettings();
    }

    function renderJournalSettings() {
      const root = $("journalSettings");
      root.innerHTML = "";
      state.journalsConfig.forEach((journal) => {
        const row = document.createElement("label");
        row.className = "journal-toggle";
        row.innerHTML = `<span></span><span>${escapeHtml(journal.name)}</span><button class="action" type="button">Remove</button>`;
        row.querySelector("button").addEventListener("click", () => removeJournal(journal.name));
        root.appendChild(row);
      });
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
      state.journals = (data.journals || []).map((journal) => journal.name);
      syncSelectedJournals();
      renderJournalSettings();
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
      state.journals = (data.journals || []).map((journal) => journal.name);
      syncSelectedJournals();
      renderJournalSettings();
      await loadMonth();
      await loadReport();
    }

    function subjectMatches(paper) {
      return paperMatchesField(paper, state.subjectFilter);
    }

    function paperMatchesField(paper, value) {
      if (value === "all") return true;
      const fields = Array.isArray(paper.fields) && paper.fields.length ? paper.fields : [paper.discipline || "other"];
      return fields.includes(value);
    }

    function renderSectionFilters() {
      const counts = {};
      state.papers
        .filter((paper) => subjectMatches(paper) && state.selectedJournals.has(paper.journal))
        .forEach((paper) => {
          const section = normalizedSection(paper.section);
          counts[section] = (counts[section] || 0) + 1;
        });
      const sections = Object.keys(counts).sort();
      if (!state.selectedSections.size) sections.forEach((section) => state.selectedSections.add(section));
      state.selectedSections = new Set([...state.selectedSections].filter((section) => sections.includes(section)));
      if (!state.selectedSections.size) sections.forEach((section) => state.selectedSections.add(section));

      const root = $("sectionFilters");
      root.innerHTML = "";
      sections.forEach((section) => {
        const label = document.createElement("label");
        label.className = "section-toggle";
        label.innerHTML = `<input type="checkbox" ${state.selectedSections.has(section) ? "checked" : ""}>
          <span>${escapeHtml(section)}</span><b>${counts[section] || 0}</b>`;
        label.querySelector("input").addEventListener("change", (event) => {
          if (event.target.checked) state.selectedSections.add(section);
          else state.selectedSections.delete(section);
          renderReport();
        });
        root.appendChild(label);
      });
    }

    function sectionMatches(paper) {
      return !state.selectedSections.size || state.selectedSections.has(normalizedSection(paper.section));
    }

    function normalizedSection(section) {
      const value = String(section || "unknown").trim().toLowerCase();
      if (value.includes("perspective")) return "perspective";
      if (value.includes("review")) return "review";
      if (value.includes("article") || value === "research" || value === "report") return "article";
      if (value.includes("analysis")) return "analysis";
      if (value.includes("letter")) return "letter";
      return value || "unknown";
    }

    function renderReport() {
      state.mode = "report";
      $("libraryControls").classList.remove("open");
      $("reportTitle").textContent = `${state.selectedDate} Report`;
      const query = state.query.trim().toLowerCase();
      const filtered = state.papers.filter((paper) => {
        const inJournal = state.selectedJournals.has(paper.journal);
        const haystack = `${paper.title} ${paper.abstract} ${paper.doi} ${paper.journal} ${(paper.authors || []).join(" ")}`.toLowerCase();
        return inJournal && subjectMatches(paper) && sectionMatches(paper) && (!query || haystack.includes(query));
      });
      const subjectText = {
        "physics": "Physics",
        "materials": "Materials",
        "chemistry": "Chemistry",
        "all": "All Fields",
        "other": "Other Fields"
      }[state.subjectFilter] || "All Fields";
      $("summary").textContent = `${state.papers.length} total · ${filtered.length} shown · Field: ${subjectText}`;
      const root = $("papers");
      root.innerHTML = "";
      if (state.fetchingDates.has(state.selectedDate)) {
        root.innerHTML = fetchProgressMarkup(state.selectedDate);
      }
      if (!filtered.length) {
        if (!state.fetchingDates.has(state.selectedDate)) {
          root.innerHTML = `<div class="empty">No matching papers for this date.</div>`;
        }
        return;
      }
      groupedReportPapers(filtered).forEach((group) => {
        const heading = document.createElement("h3");
        heading.className = "journal-group";
        heading.textContent = group.journal;
        root.appendChild(heading);
        group.papers.forEach((paper) => root.appendChild(renderPaper(paper)));
      });
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
      const detail = total ? `${completed} / ${total} journals completed` : "Preparing fetch";
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
      $("libraryControls").classList.add("open");
      $("reportTitle").textContent = "Library";
      const root = $("papers");
      root.innerHTML = "";
      const query = state.query.trim().toLowerCase();
      const filtered = state.libraryPapers.filter((paper) => {
        const haystack = `${paper.title} ${paper.abstract} ${paper.doi} ${paper.journal} ${(paper.authors || []).join(" ")}`.toLowerCase();
        return !query || haystack.includes(query);
      });
      $("summary").textContent = `${state.libraryPapers.length} downloaded/analyzed · ${filtered.length} shown`;
      if (!filtered.length) {
        root.innerHTML = `<div class="empty">No downloaded or analyzed papers for these filters.</div>`;
        return;
      }
      filtered.forEach((paper) => root.appendChild(renderPaper(paper)));
    }

    function updatePaperState(paperId, paper) {
      if (!paper) return;
      const reportIndex = state.papers.findIndex((item) => item.paper_id === paperId);
      if (reportIndex >= 0) state.papers[reportIndex] = paper;
      const cachedReport = state.reportCache[paper.publication_date];
      const cachedIndex = (cachedReport?.papers || []).findIndex((item) => item.paper_id === paperId);
      if (cachedIndex >= 0) cachedReport.papers[cachedIndex] = paper;
      const libraryIndex = state.libraryPapers.findIndex((item) => item.paper_id === paperId);
      if (libraryIndex >= 0) state.libraryPapers[libraryIndex] = paper;
    }

    function renderPaper(paper) {
      const article = document.createElement("article");
      article.className = "paper";
      article.dataset.paperId = paper.paper_id;
      const authorText = authorLine(paper);
      article.innerHTML = `
        <div class="paper-head">
          <div>
            <h3 style="color:${paper.section_color}">${escapeHtml(paper.title || "(Untitled)")}</h3>
            <div class="meta">
              <span class="journal-name">${escapeHtml(paper.journal)}</span>
              <span>${escapeHtml(paper.publication_date || "unknown date")}</span>
              <span>${escapeHtml(paper.doi || "no DOI")}</span>
              <span class="authors">${escapeHtml(authorText)}</span>
            </div>
          </div>
          <span class="badge" style="color:${paper.section_color};background:${paper.section_badge_background}">${escapeHtml(paper.section)}</span>
        </div>
        <p class="abstract">${escapeHtml(paper.abstract || "No abstract available.")}</p>
        <div class="actions">
          ${paper.url ? `<a class="action" href="${escapeAttr(paper.url)}" target="_blank" rel="noreferrer" title="Open publisher page">↗ Open</a>` : ""}
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
      `;
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
      return article;
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
      state.viewYear = Number(state.selectedDate.slice(0, 4));
      state.viewMonth = Number(state.selectedDate.slice(5, 7));
      await loadMonth();
      await loadReport();
    });
    $("selectAll").addEventListener("click", () => {
      const allSelected = state.journals.every((journal) => state.selectedJournals.has(journal));
      state.selectedJournals = new Set(allSelected ? [] : state.journals);
      renderFilters();
      renderSectionFilters();
      if (state.mode === "library") renderLibrary();
      else renderReport();
    });
    $("reportMode").addEventListener("click", renderReport);
    $("libraryMode").addEventListener("click", async () => {
      $("libraryFrom").value = state.libraryFrom;
      $("libraryUntil").value = state.libraryUntil;
      await loadLibrary();
    });
    $("refreshLibrary").addEventListener("click", loadLibrary);
    $("libraryFrom").addEventListener("change", (event) => {
      state.libraryFrom = event.target.value;
    });
    $("libraryUntil").addEventListener("change", (event) => {
      state.libraryUntil = event.target.value;
    });
    $("libraryJournal").addEventListener("change", (event) => {
      state.libraryJournal = event.target.value;
    });
    $("toggleSidebar").addEventListener("click", () => {
      document.querySelector(".app").classList.toggle("sidebar-collapsed");
      updateSidebarToggle();
    });
    $("toggleReportPanel").addEventListener("click", toggleReportPanel);
    $("workspaceResizer").addEventListener("pointerdown", startWorkspaceResize);
    $("addJournal").addEventListener("click", addJournal);
    $("searchBox").addEventListener("input", (event) => {
      state.query = event.target.value;
      if (state.mode === "library") renderLibrary();
      else renderReport();
    });
    $("closeAnalysis").addEventListener("click", closeAnalysis);
    $("analysisBackdrop").addEventListener("click", closeAnalysis);
    window.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeAnalysis();
    });
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
