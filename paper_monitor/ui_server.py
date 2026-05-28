from __future__ import annotations

from email.parser import BytesParser
from email.policy import default as email_policy
import html
import hashlib
import atexit
from io import BytesIO
import json
import mimetypes
import os
import re
import shutil
import socket
import socketserver
import subprocess
import threading
import time
import uuid
import webbrowser
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from zoneinfo import ZoneInfo

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
from .importers.inventory import ImportCancelled, build_inventory_from_folder, build_inventory_from_paths, import_library_inventory
from .monitor import fetch_one_arxiv_preprint_source, run_journal_monitor
from .reporting import section_badge_background, section_color
from .sources.ads import fetch_ads_record_by_identifier, test_ads_token
from .sources.arxiv import ARXIV_DEFAULT_CATEGORIES, ARXIV_JOURNAL_NAME, fetch_arxiv_by_id, strip_arxiv_version
from .sources.crossref import normalize_crossref_item
from .sources.openalex import normalize_openalex_item, normalize_openalex_journal_name, search_openalex_author_publications
from .sources.publisher import enrich_from_landing_page, enrich_image_from_landing_page
from .storage import Storage
from .text import clean_text, journal_name_for_doi, normalize_publication_title, safe_slug
from .time_utils import now_iso, today_jst


class GoogleScholarBlockedError(RuntimeError):
    pass


FETCH_PROGRESS: dict[str, dict[str, Any]] = {}
FETCH_PROGRESS_LOCK = threading.Lock()
LIBRARY_IMPORT_JOBS: dict[str, dict[str, Any]] = {}
LIBRARY_IMPORT_JOBS_LOCK = threading.Lock()
MY_PUBLICATION_METRICS_JOBS: dict[str, dict[str, Any]] = {}
MY_PUBLICATION_METRICS_JOBS_LOCK = threading.Lock()
ACTIVE_FETCH_DATES: set[str] = set()
JOURNAL_LOGO_CACHE: dict[str, str] = {}
PREPRINT_JOURNALS = [ARXIV_JOURNAL_NAME]
LIBRARY_UNSORTED_FOLDER_NAME = "unsorted"
LIBRARY_RECYCLE_FOLDER_NAME = "Recycle"
LIBRARY_SHORTCUT_TAB_COUNT = 5
LIBRARY_WORKSPACE_TAB_COUNT = 3
LIBRARY_NAMING_RULE_SETTING = "library_naming_rule"
LIBRARY_NAMING_RULES = {"title", "citation"}
DEFAULT_LIBRARY_NAMING_RULE = "citation"
ADS_API_TOKEN_SETTING = "ads_api_token"
MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING = "my_publications_scholar_profile"
NCBI_EUTILS_TOOL = "PaperMonitor"
NCBI_EUTILS_EMAIL = "paper.monitor.local@example.com"
PDF_THUMB_CACHE_DIR = Path("/private/tmp/paper_monitor_pdf_thumbs")
ARXIV_ANNOUNCEMENT_BUFFER = timedelta(minutes=20)
INTERRUPTED_FETCH_RESUME_AFTER = timedelta(minutes=30)
LATE_ARRIVAL_LOOKBACK_DAYS = 3
DEFAULT_COMMENT_REPORT_DIR = ROOT / "reports" / "citation_comments"
PUBLICATION_EXPORT_DIR = ROOT / "reports" / "publication_exports"
COMMENT_REPORT_MAX_OPENALEX_PAGES = 10
COMMENT_REPORT_OPENALEX_PER_PAGE = 100
COMMENT_REPORT_LIST_LIMIT = 200
COMMENT_REPORT_CONTEXT_LIMIT = 100
COMMENT_REPORT_UNMATCHED_CONTEXT_LIMIT = 100
COMMENT_REPORT_HIGHLIGHT_LIMIT = 10
WEBKIT_NETWORK_CACHE_DIR = Path.home() / "Library" / "Caches" / "local.paper-monitor" / "WebKit" / "NetworkCache"
WEBKIT_CACHE_MAX_BYTES = 1024 * 1024 * 1024
WEBKIT_CACHE_TARGET_BYTES = 512 * 1024 * 1024
DEEP_SURVEY_DIR = ROOT / "deep_survey"
DEEP_SURVEY_APP_DIR = DEEP_SURVEY_DIR / "app"
DEEP_SURVEY_TEMPLATE_DIR = DEEP_SURVEY_DIR / "workspace-template"
DEEP_SURVEY_WORKSPACE_DIR = ROOT / "data" / "deep_survey_workspace"
DEEP_SURVEY_LOCK = threading.Lock()
DEEP_SURVEY_PROCESS: subprocess.Popen | None = None
DEEP_SURVEY_PORT: int | None = None


def find_free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def deep_survey_node_binary() -> str | None:
    candidates = [
        os.environ.get("DEEP_SURVEY_NODE"),
        "/Applications/Codex.app/Contents/Resources/node",
        shutil.which("node"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return str(candidate)
    return None


def ensure_deep_survey_workspace() -> None:
    DEEP_SURVEY_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    plugin_source = DEEP_SURVEY_TEMPLATE_DIR / "plugins" / "deep-literature-workflow"
    plugin_target = DEEP_SURVEY_WORKSPACE_DIR / "plugins" / "deep-literature-workflow"
    if plugin_source.exists() and not plugin_target.exists():
        plugin_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(plugin_source, plugin_target)


def wait_for_deep_survey_port(port: int, timeout: float = 4.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def ensure_deep_survey_server() -> dict[str, Any]:
    global DEEP_SURVEY_PROCESS, DEEP_SURVEY_PORT
    with DEEP_SURVEY_LOCK:
        if DEEP_SURVEY_PROCESS and DEEP_SURVEY_PROCESS.poll() is None and DEEP_SURVEY_PORT:
            return {
                "ok": True,
                "url": f"http://127.0.0.1:{DEEP_SURVEY_PORT}/",
                "port": DEEP_SURVEY_PORT,
                "workspace": str(DEEP_SURVEY_WORKSPACE_DIR),
            }

        server_path = DEEP_SURVEY_APP_DIR / "server.mjs"
        node_binary = deep_survey_node_binary()
        if not server_path.exists():
            return {"ok": False, "error": "Deep Survey server.mjs is missing."}
        if not node_binary:
            return {"ok": False, "error": "Node.js was not found. Install Codex.app or Node.js."}

        ensure_deep_survey_workspace()
        DEEP_SURVEY_PORT = find_free_local_port()
        env = os.environ.copy()
        env["CODEX_DLW_APP_PORT"] = str(DEEP_SURVEY_PORT)
        env["CODEX_DLW_WORKSPACE_ROOT"] = str(DEEP_SURVEY_WORKSPACE_DIR)
        env.setdefault("CODEX_DLW_SANDBOX", "danger-full-access")
        env.setdefault("CODEX_DLW_APPROVAL_POLICY", "never")
        env["PATH"] = ":".join([
            "/Applications/Codex.app/Contents/Resources",
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
            env.get("PATH", ""),
        ])
        log_dir = ROOT / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = open(log_dir / "deep_survey.log", "a", encoding="utf-8")
        DEEP_SURVEY_PROCESS = subprocess.Popen(
            [node_binary, str(server_path)],
            cwd=str(DEEP_SURVEY_APP_DIR),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        ready = wait_for_deep_survey_port(DEEP_SURVEY_PORT)
        if not ready and DEEP_SURVEY_PROCESS.poll() is not None:
            return {"ok": False, "error": "Deep Survey server exited during startup."}
        return {
            "ok": ready,
            "url": f"http://127.0.0.1:{DEEP_SURVEY_PORT}/",
            "port": DEEP_SURVEY_PORT,
            "workspace": str(DEEP_SURVEY_WORKSPACE_DIR),
            "error": None if ready else "Deep Survey server is still starting.",
        }


def stop_deep_survey_server() -> None:
    global DEEP_SURVEY_PROCESS
    if DEEP_SURVEY_PROCESS and DEEP_SURVEY_PROCESS.poll() is None:
        DEEP_SURVEY_PROCESS.terminate()


atexit.register(stop_deep_survey_server)


class FastLocalThreadingHTTPServer(ThreadingHTTPServer):
    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = port


def run_ui_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    db_path: Path = DEFAULT_DB_PATH,
    open_browser: bool = False,
) -> None:
    config = load_config()
    journals = configured_source_names(config)
    threading.Thread(target=trim_webkit_network_cache_if_needed, daemon=True).start()
    threading.Thread(target=clear_pdf_thumbnail_cache, daemon=True).start()

    class Handler(PaperMonitorUiHandler):
        configured_db_path = db_path
        configured_journals = journals

    server = FastLocalThreadingHTTPServer((host, port), Handler)
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
            if parsed.path == "/api/arxiv-daily-refresh":
                self.handle_arxiv_daily_refresh()
                return
            if parsed.path == "/api/deep-survey/status":
                self.handle_deep_survey_status()
                return
            if parsed.path == "/api/library/import-folder/progress":
                self.handle_library_import_folder_progress(parse_qs(parsed.query))
                return
            if parsed.path == "/api/paper":
                self.handle_paper(parse_qs(parsed.query))
                return
            if parsed.path == "/api/paper/semantic-influential":
                self.handle_paper_semantic_influential(parse_qs(parsed.query))
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
            if parsed.path == "/api/settings/library-naming":
                self.handle_get_library_naming_rule()
                return
            if parsed.path == "/api/settings/citation":
                self.handle_get_citation_settings()
                return
            if parsed.path == "/api/my-publications":
                self.handle_my_publications(parse_qs(parsed.query))
                return
            if parsed.path == "/api/my-publications/export":
                self.handle_export_my_publications(parse_qs(parsed.query))
                return
            if parsed.path == "/api/my-publications/refresh-metrics/progress":
                self.handle_my_publication_metrics_progress(parse_qs(parsed.query))
                return
            if parsed.path == "/api/publication-search":
                self.handle_publication_search(parse_qs(parsed.query))
                return
            if parsed.path == "/api/google-scholar-profiles":
                self.handle_google_scholar_profile_search(parse_qs(parsed.query))
                return
            if parsed.path == "/files":
                self.handle_file(parse_qs(parsed.query))
                return
            if parsed.path == "/api/native-file-preview":
                self.handle_native_file_preview(parse_qs(parsed.query))
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
            if parsed.path == "/api/papers/late-arrivals/seen":
                self.handle_mark_late_arrivals_seen(payload)
                return
            if parsed.path == "/api/open-pdf":
                self.handle_open_pdf(payload)
                return
            if parsed.path == "/api/open-native-file":
                self.handle_open_native_file(payload)
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
            if parsed.path == "/api/settings/library-naming":
                self.handle_set_library_naming_rule(payload)
                return
            if parsed.path == "/api/settings/citation":
                self.handle_set_citation_settings(payload)
                return
            if parsed.path == "/api/cache/clear-web":
                self.handle_clear_web_cache(payload)
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
            if parsed.path == "/api/library/delete-batch":
                self.handle_delete_library_entries(payload)
                return
            if parsed.path == "/api/library/delete-file":
                self.handle_delete_library_item_file(payload)
                return
            if parsed.path == "/api/library/special-folder/clear":
                self.handle_clear_library_special_folder(payload)
                return
            if parsed.path == "/api/library/recover":
                self.handle_recover_library_entry(payload)
                return
            if parsed.path == "/api/library/remove-item":
                self.handle_remove_library_item(payload)
                return
            if parsed.path == "/api/library/remove-paper":
                self.handle_remove_paper_from_library(payload)
                return
            if parsed.path == "/api/library/refresh-metadata":
                self.handle_refresh_library_metadata(payload)
                return
            if parsed.path == "/api/library/paste":
                self.handle_paste_library_entry(payload)
                return
            if parsed.path == "/api/library/paste-batch":
                self.handle_paste_library_entries(payload)
                return
            if parsed.path == "/api/my-publications/add":
                self.handle_add_my_publication(payload)
                return
            if parsed.path == "/api/my-publications/import-scholar":
                self.handle_import_google_scholar_publications(payload)
                return
            if parsed.path == "/api/my-publications/scholar-profile":
                self.handle_my_publication_scholar_profile(payload)
                return
            if parsed.path == "/api/my-publications/resolve-scholar":
                self.handle_resolve_google_scholar_publication(payload)
                return
            if parsed.path == "/api/my-publications/refresh-metrics":
                self.handle_refresh_my_publication_metrics(payload)
                return
            if parsed.path == "/api/my-publications/reimport":
                self.handle_reimport_my_publication(payload)
                return
            if parsed.path == "/api/my-publications/star":
                self.handle_star_my_publication(payload)
                return
            if parsed.path == "/api/my-publications/head":
                self.handle_my_publication_head(payload)
                return
            if parsed.path == "/api/my-publications/roles":
                self.handle_my_publication_roles(payload)
                return
            if parsed.path == "/api/my-publications/author-marks":
                self.handle_my_publication_author_marks(payload)
                return
            if parsed.path == "/api/my-publications/manual-metadata":
                self.handle_my_publication_manual_metadata(payload)
                return
            if parsed.path == "/api/my-publications/comments":
                self.handle_my_publication_comments(payload)
                return
            if parsed.path == "/api/my-publications/delete":
                self.handle_delete_my_publication(payload)
                return
            if parsed.path == "/api/my-publications/reorder":
                self.handle_reorder_my_publications(payload)
                return
            if parsed.path == "/api/my-publications/name":
                self.handle_set_my_publication_name(payload)
                return
            if parsed.path == "/api/library/shortcut-tabs":
                self.handle_set_library_shortcut_tabs(payload)
                return
            if parsed.path == "/api/library/shortcut-tabs/rename":
                self.handle_rename_library_shortcut_tab(payload)
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
            if parsed.path == "/api/library/import-folder/stop":
                self.handle_stop_library_import_folder(payload)
                return
            if parsed.path == "/api/library/import-folder/delete":
                self.handle_delete_library_import_folder_job(payload)
                return
            if parsed.path == "/api/library/import-paths":
                self.handle_library_import_paths(payload)
                return
            if parsed.path == "/api/library/import-folder":
                self.handle_library_import_folder(payload)
                return
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown route")
        except Exception as exc:
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, format: str, *args: Any) -> None:
        return

    def handle_deep_survey_status(self) -> None:
        self.send_json(ensure_deep_survey_server())

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
        force_fetch = first(query, "force_fetch") == "1"
        fetched = False
        missing_journals: list[str] = []
        storage = Storage(self.configured_db_path)
        try:
            selected_date = date.fromisoformat(selected)
            missing_journals = missing_fetch_journals_for_date(storage, selected, self.configured_journals)
            sources_to_fetch = manual_refresh_journals_for_date(selected, self.configured_journals) if force_fetch else missing_journals
            if (force_fetch or auto_fetch) and selected_date <= today_jst() and sources_to_fetch and try_start_fetch(selected):
                storage.close()
                fetch_storage = None
                try:
                    config = load_config()
                    fetch_storage = Storage(self.configured_db_path)
                    start_fetch_progress(selected, sources_to_fetch)
                    fetch_missing_sources_for_date(
                        config=config,
                        storage=fetch_storage,
                        selected=selected,
                        selected_date=selected_date,
                        missing_sources=sources_to_fetch,
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
            late_unread_ids = unread_late_arrival_paper_ids(storage, selected, self.configured_journals)
            late_arrivals = late_arrivals_for_seen_date(storage, selected, self.configured_journals)
        finally:
            storage.close()
        papers = [paper for paper in papers if paper.get("section_allowed") != 0]
        self.send_json(
            {
                "date": selected,
                "journals": self.configured_journals,
                "papers": [
                    paper_to_api(paper, late_arrival_unread=str(paper.get("paper_id") or "") in late_unread_ids)
                    for paper in papers
                ],
                "journalCounts": count_by_journal(papers),
                "lateArrivals": late_arrival_summaries(late_arrivals),
                "fetched": fetched,
                "forcedFetch": force_fetch,
                "missingJournals": missing_journals,
                "fetchActive": is_fetch_active(selected),
            }
        )

    def handle_fetch_progress(self, query: dict[str, list[str]]) -> None:
        selected = first(query, "date") or today_jst().isoformat()
        self.send_json({"date": selected, "progress": get_fetch_progress(selected)})

    def handle_arxiv_daily_refresh(self) -> None:
        selected_date = datetime.now().astimezone().date()
        selected = selected_date.isoformat()
        storage = Storage(self.configured_db_path)
        try:
            missing = missing_fetch_journals_for_date(storage, selected, [ARXIV_JOURNAL_NAME])
        finally:
            storage.close()
        if ARXIV_JOURNAL_NAME not in missing:
            self.send_json({"date": selected, "status": "skipped"})
            return
        if not try_start_fetch(selected):
            self.send_json({"date": selected, "status": "active"})
            return

        def refresh_arxiv() -> None:
            fetch_storage = Storage(self.configured_db_path)
            try:
                start_fetch_progress(selected, [ARXIV_JOURNAL_NAME])
                fetch_one_arxiv_preprint_source(
                    storage=fetch_storage,
                    start_date=selected_date,
                    end_date=selected_date,
                    categories=ARXIV_DEFAULT_CATEGORIES,
                )
            finally:
                finish_fetch_progress(selected)
                finish_active_fetch(selected)
                fetch_storage.close()

        threading.Thread(target=refresh_arxiv, daemon=True).start()
        self.send_json({"date": selected, "status": "started"})

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

    def handle_paper_semantic_influential(self, query: dict[str, list[str]]) -> None:
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
        try:
            citations = fetch_semantic_scholar_influential_citations(paper, limit=20)
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Semantic Scholar influential citations failed: {exc}")
            return
        self.send_json({"paper_id": paper_id, "citations": citations})

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
            scholar_profile = load_my_publications_scholar_profile(storage)
        finally:
            storage.close()
        self.send_json({"publications": publications, "myName": my_name, "scholarProfile": scholar_profile})

    def handle_publication_search(self, query: dict[str, list[str]]) -> None:
        search_text = (first(query, "q") or "").strip()
        kind = (first(query, "kind") or "auto").strip().lower()
        if not search_text:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "q is required")
            return
        try:
            results = search_publications(search_text, kind=kind)
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Publication lookup failed: {exc}")
            return
        self.send_json({"results": [publication_candidate_to_api(paper) for paper in results]})

    def handle_google_scholar_profile_search(self, query: dict[str, list[str]]) -> None:
        search_text = (first(query, "q") or "").strip()
        if not search_text:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "q is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            local_profiles = local_google_scholar_profiles(storage, search_text, limit=20)
        finally:
            storage.close()
        if local_profiles:
            self.send_json({"profiles": local_profiles})
            return
        try:
            profiles = search_google_scholar_profiles(search_text, limit=20)
        except GoogleScholarBlockedError as exc:
            self.send_error_json(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
            return
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Google Scholar profile lookup failed: {exc}")
            return
        self.send_json({"profiles": merge_google_scholar_profiles(local_profiles, profiles, search_text, limit=20)})

    def handle_add_my_publication(self, payload: dict[str, Any]) -> None:
        candidate = payload.get("paper")
        paper_id = str(payload.get("paper_id") or "")
        paper_ids = payload.get("paper_ids")
        storage = Storage(self.configured_db_path)
        try:
            paper: dict[str, Any] | None = None
            publication: dict[str, Any] = {}
            if isinstance(candidate, dict):
                normalized = paper_from_publication_candidate(candidate)
                storage.upsert_paper(normalized)
                paper = storage.get_paper(normalized["paper_id"])
                paper_id = normalized["paper_id"]
                if not paper_id or not paper:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "A publication candidate or paper_id is required")
                    return
                publication = storage.add_my_publication(paper_id=paper_id)
                sync_my_publication_existing_pubmed_marks(storage, paper_id=paper_id)
            elif isinstance(paper_ids, list):
                valid_ids = []
                for raw_id in paper_ids:
                    candidate_id = str(raw_id or "").strip()
                    if candidate_id and storage.get_paper(candidate_id):
                        valid_ids.append(candidate_id)
                if not valid_ids:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_ids must include at least one known paper")
                    return
                for candidate_id in valid_ids:
                    publication = storage.add_my_publication(paper_id=candidate_id)
                    sync_my_publication_existing_pubmed_marks(storage, paper_id=candidate_id)
            elif paper_id:
                paper = storage.get_paper(paper_id)
                if not paper_id or not paper:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "A publication candidate or paper_id is required")
                    return
                publication = storage.add_my_publication(paper_id=paper_id)
                sync_my_publication_existing_pubmed_marks(storage, paper_id=paper_id)
            else:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "A publication candidate or paper_id is required")
                return
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_import_google_scholar_publications(self, payload: dict[str, Any]) -> None:
        profile_url = str(payload.get("url") or "").strip()
        if not profile_url:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Google Scholar profile URL is required")
            return
        limit = max(1, min(300, int(payload.get("limit") or 200)))
        try:
            scholar_payload = fetch_google_scholar_profile_payload(profile_url, limit=limit)
            candidates = scholar_payload["candidates"]
        except GoogleScholarBlockedError as exc:
            self.send_error_json(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
            return
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Google Scholar import failed: {exc}")
            return
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        for candidate in candidates:
            title = ((candidate.get("paper") or {}).get("title") or candidate.get("title") or "")
            try:
                result = publication_candidate_to_api(paper_from_publication_candidate(candidate))
                result["match_status"] = "scholar"
                result["scholar_title"] = title
                results.append(result)
            except Exception as exc:
                if len(errors) < 5:
                    errors.append(f"{title or 'Untitled'}: {exc}")
        profile = save_my_publications_scholar_profile_for_db(
            self.configured_db_path,
            scholar_payload.get("profile") or {},
        )
        self.send_json(
            {
                "seen": len(candidates),
                "doi_matches": 0,
                "scholar_only": len(results),
                "errors": errors,
                "results": results,
                "profile": profile,
            }
        )

    def handle_my_publication_scholar_profile(self, payload: dict[str, Any]) -> None:
        profile = payload.get("profile")
        storage = Storage(self.configured_db_path)
        try:
            if not profile:
                storage.set_setting(MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING, "")
                saved_profile: dict[str, Any] = {}
            else:
                saved_profile = save_my_publications_scholar_profile(storage, profile)
        finally:
            storage.close()
        self.send_json({"profile": saved_profile})

    def handle_resolve_google_scholar_publication(self, payload: dict[str, Any]) -> None:
        candidate = payload.get("candidate")
        if not isinstance(candidate, dict):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "candidate is required")
            return
        try:
            resolved_candidate = resolve_google_scholar_candidate_to_identifier(candidate)
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Google Scholar identifier lookup failed: {exc}")
            return
        if not resolved_candidate:
            self.send_json({"candidate": None})
            return
        result = publication_candidate_to_api(resolved_candidate)
        result["match_status"] = "doi" if result.get("doi") else "arxiv"
        result["scholar_title"] = ((candidate.get("paper") or {}).get("title") or candidate.get("scholar_title") or "")
        self.send_json({"candidate": result})

    def handle_refresh_my_publication_metrics(self, payload: dict[str, Any]) -> None:
        active = active_my_publication_metrics_job()
        if active:
            self.send_json({"job_id": active["job_id"], "job": active})
            return
        job_id = create_my_publication_metrics_job()
        thread = threading.Thread(
            target=run_my_publication_metrics_job,
            kwargs={"job_id": job_id, "db_path": self.configured_db_path},
            daemon=True,
        )
        thread.start()
        self.send_json({"job_id": job_id, "job": get_my_publication_metrics_job(job_id)})

    def handle_my_publication_metrics_progress(self, query: dict[str, list[str]]) -> None:
        job_id = first(query, "job_id") or first(query, "id")
        job = get_my_publication_metrics_job(job_id)
        if not job:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown metrics job")
            return
        self.send_json({"job": job})

    def handle_reimport_my_publication(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        if not publication_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "publication_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.get_my_publication(publication_id=publication_id)
            if not publication:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Publication not found")
                return
            candidate = publication_to_reimport_candidate(publication)
            identifier_candidate = resolve_google_scholar_candidate_to_identifier(candidate)
            if not identifier_candidate:
                self.send_error_json(HTTPStatus.NOT_FOUND, "No DOI or arXiv match found for this publication")
                return
            normalized = paper_from_publication_candidate(identifier_candidate)
            storage.upsert_paper(normalized)
            replaced = storage.replace_my_publication_paper(publication_id=publication_id, paper_id=normalized["paper_id"])
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Reimport failed: {exc}")
            return
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(replaced), "publications": publications})

    def handle_star_my_publication(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.set_my_publication_starred(publication_id=publication_id, starred=bool(payload.get("starred")))
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_my_publication_head(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.set_my_publication_export_excluded(
                publication_id=publication_id,
                export_excluded=bool(payload.get("head")),
            )
            if not publication:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Publication not found")
                return
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_my_publication_roles(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.set_my_publication_roles(
                publication_id=publication_id,
                first_author=bool(payload.get("first_author")),
                corresponding_author=bool(payload.get("corresponding_author")),
                review_article=bool(payload.get("review_article")),
            )
            if not publication:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Publication not found")
                return
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_my_publication_author_marks(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        author_index = int(payload.get("author_index") or 0)
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.set_my_publication_author_mark(
                publication_id=publication_id,
                author_index=author_index,
                author_name=clean_text(payload.get("author_name") or ""),
                first_author=bool(payload.get("first_author")),
                co_first_author=bool(payload.get("co_first_author")),
                corresponding_author=bool(payload.get("corresponding_author")),
            )
            if not publication:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Publication not found")
                return
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_my_publication_manual_metadata(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.get_my_publication(publication_id=publication_id)
            if not publication:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Publication not found")
                return
            if not my_publication_allows_manual_metadata(publication):
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Manual metadata is only available for publications without DOI or arXiv ID")
                return
            raw = parse_raw_json(publication)
            authors = parse_manual_author_list(payload.get("authors") or "")
            raw["authors"] = authors
            raw["manual_metadata"] = True
            raw["source"] = raw.get("source") or publication.get("source") or "manual"
            for raw_key, payload_key in [
                ("volume", "volume"),
                ("issue", "issue"),
                ("page", "pages"),
                ("year", "publication_date"),
            ]:
                value = clean_text(payload.get(payload_key) or "")
                if value:
                    raw[raw_key] = value
                else:
                    raw.pop(raw_key, None)
            paper = dict(publication)
            paper.update({
                "title": clean_text(payload.get("title") or publication.get("title") or ""),
                "journal": clean_text(payload.get("journal") or publication.get("journal") or ""),
                "publication_date": clean_text(payload.get("publication_date") or publication.get("publication_date") or ""),
                "raw": raw,
            })
            updated = storage.refresh_paper_metadata(publication["paper_id"], merge_refreshed_metadata(publication, paper))
            publication = storage.get_my_publication(publication_id=publication_id) if updated else publication
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publication": my_publication_to_api(publication), "publications": publications})

    def handle_export_my_publications(self, query: dict[str, list[str]]) -> None:
        export_format = clean_text(first(query, "format") or "docx").lower()
        response_format = clean_text(first(query, "response") or "").lower()
        if export_format not in {"docx", "pdf", "tex", "overleaf"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "format must be docx, pdf, tex, or overleaf")
            return
        storage = Storage(self.configured_db_path)
        try:
            rows = [row for row in storage.list_my_publications() if not row.get("export_excluded")]
            my_name = storage.get_setting("my_publications_name", "")
        finally:
            storage.close()
        try:
            result_path = export_my_publication_list(rows, my_name=my_name, export_format=export_format)
        except Exception as exc:
            if response_format != "json":
                self.send_export_error_page(str(exc))
                return
            self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        if response_format == "json":
            try:
                open_result = open_publication_export_result(result_path, export_format)
            except Exception as exc:
                open_result = {"status": "failed", "error": str(exc)}
            self.send_json({
                "status": "exported",
                "format": export_format,
                "filename": result_path.name,
                "path": str(result_path),
                "folder": str(result_path.parent),
                "open": open_result,
            })
            return
        self.send_path_download(result_path)

    def handle_my_publication_comments(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        if not publication_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "publication_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            publication = storage.get_my_publication(publication_id=publication_id)
        finally:
            storage.close()
        if not publication:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Publication not found")
            return
        try:
            content, report_path, citing_count = build_my_publication_comments_report(publication)
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Comments report failed: {exc}")
            return
        self.send_json(
            {
                "paper": paper_to_api(publication),
                "content": content,
                "path": str(report_path),
                "citing_count": citing_count,
            }
        )

    def handle_delete_my_publication(self, payload: dict[str, Any]) -> None:
        publication_id = int(payload.get("publication_id") or 0)
        storage = Storage(self.configured_db_path)
        try:
            storage.delete_my_publication(publication_id=publication_id)
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"publications": publications})

    def handle_reorder_my_publications(self, payload: dict[str, Any]) -> None:
        publication_ids: list[int] = []
        for item in payload.get("publication_ids") or []:
            try:
                publication_id = int(item)
            except (TypeError, ValueError):
                continue
            if publication_id:
                publication_ids.append(publication_id)
        storage = Storage(self.configured_db_path)
        try:
            existing_order = [int(row["id"]) for row in storage.list_my_publications()]
            existing = set(existing_order)
            ordered = [publication_id for publication_id in publication_ids if publication_id in existing]
            ordered.extend(publication_id for publication_id in existing_order if publication_id not in ordered)
            storage.reorder_my_publications(ordered)
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

    def handle_mark_late_arrivals_seen(self, payload: dict[str, Any]) -> None:
        paper_ids = payload.get("paper_ids")
        if not isinstance(paper_ids, list):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_ids must be a list")
            return
        clean_ids = [str(paper_id) for paper_id in paper_ids if str(paper_id or "").strip()]
        storage = Storage(self.configured_db_path)
        try:
            storage.mark_late_arrivals_seen(clean_ids)
        finally:
            storage.close()
        self.send_json({"paper_ids": clean_ids})

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

    def handle_rename_library_shortcut_tab(self, payload: dict[str, Any]) -> None:
        index = int(payload.get("index") or 0)
        if index < 0 or index >= LIBRARY_SHORTCUT_TAB_COUNT:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "shortcut index is out of range")
            return
        label = " ".join(str(payload.get("label") or "").split()) or f"Shortcut {index + 1}"
        storage = Storage(self.configured_db_path)
        try:
            shortcuts = library_shortcut_tabs(storage)
            current = shortcuts[index] if index < len(shortcuts) else {}
            shortcuts[index] = {
                "folder_id": int(current.get("folder_id") or 0),
                "label": label[:80],
            }
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
        identifier = clean_text(str(payload.get("identifier") or payload.get("doi") or ""))
        doi = normalize_publication_doi(identifier)
        arxiv_id = normalize_arxiv_identifier(identifier)
        if not (doi and looks_like_doi(doi)) and not arxiv_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "DOI or arXiv ID is required")
            return
        try:
            if arxiv_id and not looks_like_doi(identifier):
                paper = publication_metrics_metadata_from_arxiv_id(arxiv_id)
            elif doi_is_likely_data_repository(doi):
                paper = publication_metrics_metadata_from_doi(doi, allow_data_repository=True)
            else:
                candidates = search_crossref_publications(doi, kind="doi")
                paper = paper_from_publication_candidate(candidates[0]) if candidates else None
        except Exception as exc:
            self.send_error_json(HTTPStatus.BAD_GATEWAY, f"Identifier lookup failed: {exc}")
            return
        if not paper:
            self.send_error_json(HTTPStatus.NOT_FOUND, "No publication found for this DOI or arXiv ID")
            return
        storage = Storage(self.configured_db_path)
        try:
            storage.upsert_paper(paper)
            paper_id = str(paper.get("paper_id") or "")
            stored_paper = storage.get_paper(paper_id)
            stored_paper = refresh_pubmed_if_possible(storage, stored_paper, doi=doi, timeout=8, max_retries=1) or stored_paper
            refreshed = refresh_semantic_scholar_if_possible(storage, stored_paper, timeout=8, max_retries=1)
            refresh_ads_if_possible(storage, refreshed or stored_paper or storage.get_paper(paper_id), timeout=8, max_retries=1)
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
        job_id = create_library_import_job(folder_path=folder_path, copy_mode=copy_mode)
        thread = threading.Thread(
            target=run_library_import_job,
            kwargs={
                "job_id": job_id,
                "folder_path": folder_path,
                "copy_mode": copy_mode,
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

    def handle_stop_library_import_folder(self, payload: dict[str, Any]) -> None:
        job_id = str(payload.get("job_id") or "")
        job = request_stop_library_import_job(job_id)
        if not job:
            self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown import job")
            return
        self.send_json({"job": job})

    def handle_delete_library_import_folder_job(self, payload: dict[str, Any]) -> None:
        job_id = str(payload.get("job_id") or "")
        storage = Storage(self.configured_db_path)
        try:
            result = delete_library_import_job_data(storage, job_id)
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"delete_result": result, **snapshot})

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
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = safe_slug(folder_path.name or "library-folder", 60)
        inventory_path = ROOT / "reports" / "imports" / f"folder-inventory-{slug}-{timestamp}.json"
        report_path = ROOT / "reports" / "imports" / f"folder-import-{slug}-import-{timestamp}.json"
        try:
            build_inventory_from_folder(folder_path, output_path=inventory_path, parse_pdfs=True)
            storage = Storage(self.configured_db_path)
            try:
                result = import_library_inventory(
                    inventory_path,
                    copy_mode=copy_mode,
                    preserve_folders=True,
                    dedupe_by=("doi", "arxiv", "path"),
                    dry_run=False,
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

    def handle_library_import_paths(self, payload: dict[str, Any]) -> None:
        raw_paths = payload.get("paths")
        if not isinstance(raw_paths, list) or not raw_paths:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paths must be a non-empty list")
            return
        copy_mode = str(payload.get("copy_mode") or "copy")
        if copy_mode not in {"copy", "link"}:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "copy_mode must be copy or link")
            return
        try:
            target_folder_id = int(payload.get("target_folder_id") or 1)
        except (TypeError, ValueError):
            self.send_error_json(HTTPStatus.BAD_REQUEST, "target_folder_id must be a Library folder id")
            return

        paths: list[Path] = []
        for raw_path in raw_paths:
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            try:
                path = Path(raw_path).expanduser().resolve()
            except OSError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, f"Could not resolve dropped path: {exc}")
                return
            if not path.exists():
                self.send_error_json(HTTPStatus.BAD_REQUEST, f"Dropped path does not exist: {path}")
                return
            paths.append(path)
        if not paths:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "No readable dropped paths")
            return

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = safe_slug(paths[0].name or "finder-drop", 60)
        inventory_path = ROOT / "reports" / "imports" / f"finder-drop-inventory-{slug}-{timestamp}.json"
        report_path = ROOT / "reports" / "imports" / f"finder-drop-import-{slug}-{timestamp}.json"
        try:
            build_inventory_from_paths(paths, output_path=inventory_path, parse_pdfs=True)
            storage = Storage(self.configured_db_path)
            try:
                if not storage.get_library_folder(target_folder_id):
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "Target Library folder does not exist")
                    return
                result = import_library_inventory(
                    inventory_path,
                    copy_mode=copy_mode,
                    preserve_folders=True,
                    dedupe_by=("doi", "arxiv", "path"),
                    dry_run=False,
                    storage=storage,
                    report_path=report_path,
                    library_item_name="filename",
                    library_root_folder_id=target_folder_id,
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
            if payload.get("refresh_metadata"):
                paper = refresh_paper_metadata_from_doi_if_possible(storage, paper, timeout=12, max_retries=1)
            item = storage.add_library_item(paper_id=paper_id, folder_id=folder_id)
            if item and not item.get("display_name"):
                naming_rule = library_naming_rule(storage)
                item = storage.rename_library_item(
                    item_id=int(item["id"]),
                    name=default_library_item_display_name(paper, rule=naming_rule),
                )
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json({
            "item": library_item_to_api(item, paper) if item else {},
            "folder": library_folder_to_api(target_folder) if target_folder else None,
            **snapshot,
        })

    def handle_get_library_naming_rule(self) -> None:
        storage = Storage(self.configured_db_path)
        try:
            rule = library_naming_rule(storage)
        finally:
            storage.close()
        self.send_json({"rule": rule})

    def handle_set_library_naming_rule(self, payload: dict[str, Any]) -> None:
        rule = str(payload.get("rule") or "").strip().lower()
        if rule not in LIBRARY_NAMING_RULES:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Naming rule must be title or citation")
            return
        storage = Storage(self.configured_db_path)
        try:
            storage.set_setting(LIBRARY_NAMING_RULE_SETTING, rule)
        finally:
            storage.close()
        self.send_json({"rule": rule})

    def handle_get_citation_settings(self) -> None:
        storage = Storage(self.configured_db_path)
        try:
            token = ads_api_token(storage)
        finally:
            storage.close()
        self.send_json({"ads": {"configured": bool(token), "status": "configured" if token else "not_configured"}})

    def handle_set_citation_settings(self, payload: dict[str, Any]) -> None:
        action = clean_text(str(payload.get("action") or "save")).lower()
        requested_token = clean_text(str(payload.get("ads_token") or ""))
        storage = Storage(self.configured_db_path)
        try:
            if action == "clear":
                storage.set_setting(ADS_API_TOKEN_SETTING, "")
                self.send_json({"ads": {"configured": False, "status": "cleared"}})
                return
            token = requested_token or ads_api_token(storage)
            if action == "test":
                if not token:
                    self.send_json({"ads": {"configured": False, "status": "not_configured", "ok": False}})
                    return
                try:
                    ok = test_ads_token(token)
                except Exception:
                    ok = False
                self.send_json({"ads": {"configured": bool(ads_api_token(storage)), "status": "connected" if ok else "invalid", "ok": ok}})
                return
            if requested_token:
                storage.set_setting(ADS_API_TOKEN_SETTING, requested_token)
                token = requested_token
            test_requested = bool(payload.get("test"))
            ok: bool | None = None
            if test_requested and token:
                try:
                    ok = test_ads_token(token)
                except Exception:
                    ok = False
            self.send_json({
                "ads": {
                    "configured": bool(token),
                    "status": "connected" if ok else ("invalid" if ok is False else ("configured" if token else "not_configured")),
                    "ok": ok,
                }
            })
        finally:
            storage.close()

    def handle_clear_web_cache(self, payload: dict[str, Any]) -> None:
        result = clear_webkit_network_cache()
        self.send_json(result)

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
            self.delete_library_entry_in_storage(storage, entry_type, entry_id)
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json(snapshot)

    def handle_delete_library_entries(self, payload: dict[str, Any]) -> None:
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "entries must be a non-empty list")
            return
        storage = Storage(self.configured_db_path)
        deleted: list[dict[str, Any]] = []
        try:
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Each entry must be an object")
                entry_type = str(entry.get("type") or "")
                entry_id = int(entry.get("id") or 0)
                self.delete_library_entry_in_storage(storage, entry_type, entry_id)
                deleted.append({"type": entry_type, "id": entry_id})
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"deleted": deleted, **snapshot})

    def delete_library_entry_in_storage(self, storage: Storage, entry_type: str, entry_id: int) -> None:
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
            return
        if entry_type == "folder":
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
            return
        raise ValueError("type must be item or folder")

    def handle_delete_library_item_file(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        entry_id = int(payload.get("id") or 0)
        item_id = int(payload.get("item_id") or 0)
        confirmed = bool(payload.get("confirmed"))
        if item_id and not entry_type:
            entry_type = "item"
            entry_id = item_id
        if entry_type not in {"item", "folder"} or not entry_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "type and id are required")
            return
        if not confirmed:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "confirmation is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            if entry_type == "item":
                item = storage.get_library_item(entry_id)
                if not item:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Library item not found")
                    return
                paper_ids = [str(item.get("paper_id") or "")]
            else:
                folder = storage.get_library_folder(entry_id)
                if not folder:
                    self.send_error_json(HTTPStatus.NOT_FOUND, "Folder not found")
                    return
                special = ensure_library_special_folders(storage)
                protected_ids = {
                    1,
                    int(special["unsorted"].get("id") or 0),
                    int(special["recycle"].get("id") or 0),
                }
                if int(folder.get("id") or 0) in protected_ids or folder.get("parent_id") is None:
                    self.send_error_json(HTTPStatus.BAD_REQUEST, "This folder cannot be deleted")
                    return
                paper_ids = storage.library_paper_ids_in_folder_tree(folder_id=entry_id)
            deleted = delete_library_paper_files(storage, paper_ids)
            if not deleted and entry_type == "item":
                self.send_error_json(HTTPStatus.NOT_FOUND, "No local files are available for this selection")
                return
            if entry_type == "item":
                storage.delete_library_item(item_id=entry_id)
            if entry_type == "folder":
                storage.delete_library_folder(folder_id=entry_id)
            snapshot = library_snapshot(storage)
        except IsADirectoryError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Refusing to delete a folder")
            return
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"deleted": deleted, **snapshot})

    def handle_clear_library_special_folder(self, payload: dict[str, Any]) -> None:
        folder_id = int(payload.get("folder_id") or 0)
        delete_files = bool(payload.get("delete_files"))
        confirmed = bool(payload.get("confirmed"))
        if not folder_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "folder_id is required")
            return
        if not confirmed:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "confirmation is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            special = ensure_library_special_folders(storage)
            allowed_ids = {
                int(special["unsorted"].get("id") or 0),
                int(special["recycle"].get("id") or 0),
            }
            folder = storage.get_library_folder(folder_id)
            if not folder or folder_id not in allowed_ids:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "Only unsorted and Recycle can be cleared")
                return
            paper_ids = storage.library_paper_ids_in_folder_tree(folder_id=folder_id)
            deleted_files = delete_library_paper_files(storage, paper_ids) if delete_files else []
            removed = clear_library_folder_contents(storage, folder_id=folder_id)
            snapshot = library_snapshot(storage)
        except IsADirectoryError:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "Refusing to delete a folder")
            return
        except PermissionError as exc:
            self.send_error_json(HTTPStatus.FORBIDDEN, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"deleted_files": deleted_files, "removed": removed, **snapshot})

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

    def handle_remove_library_item(self, payload: dict[str, Any]) -> None:
        item_id = int(payload.get("item_id") or payload.get("id") or 0)
        if not item_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "item_id is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            item = storage.get_library_item(item_id)
            if not item:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Library item not found")
                return
            storage.delete_library_item(item_id=item_id)
            snapshot = library_snapshot(storage)
        finally:
            storage.close()
        self.send_json(snapshot)

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

    def handle_refresh_library_metadata(self, payload: dict[str, Any]) -> None:
        paper_id = str(payload.get("paper_id") or "")
        identifier = clean_text(str(payload.get("identifier") or payload.get("doi") or ""))
        doi = normalize_publication_doi(identifier)
        arxiv_id = normalize_arxiv_identifier(identifier)
        if not paper_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "paper_id is required")
            return
        if not (doi and looks_like_doi(doi)) and not arxiv_id:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "A valid DOI or arXiv ID is required")
            return
        storage = Storage(self.configured_db_path)
        try:
            try:
                if arxiv_id and not looks_like_doi(identifier):
                    normalized = publication_metrics_metadata_from_arxiv_id(arxiv_id)
                    lookup_label = arxiv_id
                    lookup_kind = "arXiv ID"
                else:
                    normalized = publication_metrics_metadata_from_doi(
                        doi,
                        allow_data_repository=doi_is_likely_data_repository(doi),
                    )
                    lookup_label = doi
                    lookup_kind = "data DOI" if doi_is_likely_data_repository(doi) else "DOI"
            except Exception as exc:
                self.send_error_json(HTTPStatus.BAD_GATEWAY, f"{lookup_kind} metrics lookup failed: {exc}")
                return
            paper = None
            if normalized:
                paper = storage.refresh_paper_metadata(paper_id, merge_refreshed_metadata(storage.get_paper(paper_id), normalized))
            if not paper:
                paper = storage.get_paper(paper_id)
            if not paper:
                self.send_error_json(HTTPStatus.NOT_FOUND, "Paper not found")
                return
            pubmed_doi = normalize_publication_doi(doi or str(paper.get("doi") or ""))
            if pubmed_doi and looks_like_doi(pubmed_doi):
                paper = refresh_pubmed_if_possible(storage, paper, doi=pubmed_doi, timeout=12, max_retries=1) or paper
            semantic_lookup_paper = dict(paper)
            if doi and looks_like_doi(doi):
                semantic_lookup_paper["doi"] = doi
            if arxiv_id:
                raw = parse_raw_json(semantic_lookup_paper)
                raw["arxiv_id"] = arxiv_id
                semantic_lookup_paper["raw_json"] = json.dumps(raw, ensure_ascii=False)
            paper = refresh_semantic_scholar_if_possible(storage, semantic_lookup_paper, timeout=12, max_retries=1) or paper
            paper = refresh_ads_if_possible(storage, paper, timeout=12, max_retries=1) or paper
            if not normalized and not parse_semantic_scholar_json(paper):
                self.send_error_json(HTTPStatus.NOT_FOUND, f"No publication found for this {lookup_kind}: {lookup_label}")
                return
            snapshot = library_snapshot(storage)
            publications = [my_publication_to_api(row) for row in storage.list_my_publications()]
        finally:
            storage.close()
        self.send_json({"paper": paper_to_api(paper), "publications": publications, **snapshot})

    def handle_paste_library_entry(self, payload: dict[str, Any]) -> None:
        entry_type = str(payload.get("type") or "")
        entry_id = int(payload.get("id") or 0)
        target_folder_id = int(payload.get("target_folder_id") or 1)
        storage = Storage(self.configured_db_path)
        try:
            pasted = self.paste_library_entry_in_storage(storage, entry_type, entry_id, target_folder_id)
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"pasted": dict(pasted or {}), **snapshot})

    def handle_paste_library_entries(self, payload: dict[str, Any]) -> None:
        target_folder_id = int(payload.get("target_folder_id") or 1)
        entries = payload.get("entries")
        if not isinstance(entries, list) or not entries:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "entries must be a non-empty list")
            return
        storage = Storage(self.configured_db_path)
        pasted_entries: list[dict[str, Any]] = []
        try:
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Each entry must be an object")
                entry_type = str(entry.get("type") or "")
                entry_id = int(entry.get("id") or 0)
                pasted = self.paste_library_entry_in_storage(storage, entry_type, entry_id, target_folder_id)
                pasted_entries.append({"type": entry_type, "id": int(pasted.get("id") or 0), "source_id": entry_id})
            snapshot = library_snapshot(storage)
        except ValueError as exc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            return
        finally:
            storage.close()
        self.send_json({"pasted": pasted_entries, **snapshot})

    def paste_library_entry_in_storage(
        self,
        storage: Storage,
        entry_type: str,
        entry_id: int,
        target_folder_id: int,
    ) -> dict[str, Any]:
        if entry_type == "item":
            return storage.copy_library_item(item_id=entry_id, folder_id=target_folder_id)
        if entry_type == "folder":
            return storage.copy_library_folder(folder_id=entry_id, parent_id=target_folder_id)
        raise ValueError("type must be item or folder")

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

    def handle_open_native_file(self, payload: dict[str, Any]) -> None:
        raw_path = str(payload.get("path") or "")
        mode = str(payload.get("mode") or "open")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        requested = Path(raw_path).expanduser().resolve()
        if not requested.exists():
            self.send_error_json(HTTPStatus.NOT_FOUND, "Native file not found")
            return
        if mode == "folder":
            target = requested if requested.is_dir() else requested.parent
            subprocess.run(["open", str(target)], check=True)
            self.send_json({"status": "opened", "path": str(requested), "opened_path": str(target), "mode": "folder"})
            return
        if requested.is_dir():
            subprocess.run(["open", str(requested)], check=True)
        elif requested.suffix.lower() == ".pdf":
            subprocess.run(["open", "-a", "Preview", str(requested)], check=True)
        else:
            subprocess.run(["open", str(requested)], check=True)
        self.send_json({"status": "opened", "path": str(requested), "mode": "open"})

    def handle_open_url(self, payload: dict[str, Any]) -> None:
        url = str(payload.get("url") or "")
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "A valid http(s) URL is required")
            return
        if str(payload.get("app") or "").lower() == "safari":
            subprocess.run(["open", "-a", "Safari", url], check=True)
        else:
            webbrowser.open(url)
        self.send_json({"status": "opened", "url": url})

    def handle_reveal_path(self, payload: dict[str, Any]) -> None:
        raw_path = str(payload.get("path") or "")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        try:
            self.send_json(reveal_path_in_finder(Path(raw_path)))
        except FileNotFoundError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "No existing parent folder found")

    def send_export_error_page(self, message: str) -> None:
        html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Export failed</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#f7f8fb;color:#172033;font:15px -apple-system,BlinkMacSystemFont,sans-serif;}}
.card{{max-width:680px;margin:24px;padding:28px;border:1px solid #d8dee8;border-radius:12px;background:#fff;box-shadow:0 18px 50px rgba(15,23,42,.12);}}
h1{{margin:0 0 10px;font-size:22px;letter-spacing:0;}}
p{{color:#5f6b80;line-height:1.5;}}
pre{{white-space:pre-wrap;background:#f2f4f7;border-radius:8px;padding:12px;color:#344054;}}
button{{border:1px solid #cfd8e6;border-radius:8px;background:#fff;padding:9px 13px;font-weight:700;cursor:pointer;}}
</style></head><body><div class="card">
<h1>Publication List Export Failed</h1>
<p>The export did not finish. You can go back to Daiqo and try another format.</p>
<pre>{xml_escape(message)}</pre>
<button type="button" onclick="history.back()">Back</button>
</div></body></html>"""
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.INTERNAL_SERVER_ERROR)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

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

    def handle_native_file_preview(self, query: dict[str, list[str]]) -> None:
        raw_path = first(query, "path")
        if not raw_path:
            self.send_error_json(HTTPStatus.BAD_REQUEST, "path is required")
            return
        requested = Path(unquote(raw_path)).expanduser().resolve()
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

    def send_path_download(self, path: Path) -> None:
        data = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
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


def cache_file_entries(root: Path) -> tuple[int, list[tuple[float, int, Path]]]:
    if not root.exists():
        return 0, []
    total = 0
    entries: list[tuple[float, int, Path]] = []
    for path in root.rglob("*"):
        try:
            if path.is_symlink() or not path.is_file():
                continue
            stat = path.stat()
        except OSError:
            continue
        size = int(stat.st_size)
        total += size
        entries.append((float(stat.st_mtime), size, path))
    entries.sort(key=lambda item: item[0])
    return total, entries


def prune_empty_cache_dirs(root: Path) -> None:
    if not root.exists():
        return
    for path in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            path.rmdir()
        except OSError:
            pass


def trim_webkit_network_cache_if_needed() -> dict[str, Any]:
    before, entries = cache_file_entries(WEBKIT_NETWORK_CACHE_DIR)
    if before <= WEBKIT_CACHE_MAX_BYTES:
        return {
            "status": "skipped",
            "path": str(WEBKIT_NETWORK_CACHE_DIR),
            "before_bytes": before,
            "after_bytes": before,
            "removed_bytes": 0,
            "removed_files": 0,
            "errors": [],
        }
    return prune_cache_files(
        root=WEBKIT_NETWORK_CACHE_DIR,
        entries=entries,
        before=before,
        target_bytes=WEBKIT_CACHE_TARGET_BYTES,
    )


def clear_webkit_network_cache() -> dict[str, Any]:
    before, entries = cache_file_entries(WEBKIT_NETWORK_CACHE_DIR)
    return prune_cache_files(root=WEBKIT_NETWORK_CACHE_DIR, entries=entries, before=before, target_bytes=0)


def clear_pdf_thumbnail_cache() -> dict[str, Any]:
    before, entries = cache_file_entries(PDF_THUMB_CACHE_DIR)
    return prune_cache_files(root=PDF_THUMB_CACHE_DIR, entries=entries, before=before, target_bytes=0)


def prune_cache_files(
    *,
    root: Path,
    entries: list[tuple[float, int, Path]],
    before: int,
    target_bytes: int,
) -> dict[str, Any]:
    current = before
    removed_files = 0
    removed_bytes = 0
    errors: list[str] = []
    for _mtime, size, path in entries:
        if current <= target_bytes:
            break
        try:
            path.unlink()
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        current -= size
        removed_bytes += size
        removed_files += 1
    prune_empty_cache_dirs(root)
    after, _entries = cache_file_entries(root)
    return {
        "status": "trimmed" if removed_files else "skipped",
        "path": str(root),
        "before_bytes": before,
        "after_bytes": after,
        "removed_bytes": removed_bytes,
        "removed_files": removed_files,
        "errors": errors[:20],
    }


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
        journal_start_date = journal_fetch_start_date(selected_date)

        def update_journal_progress(journal: str, journal_completed: int, _journal_total: int) -> None:
            update_fetch_progress(selected, journal=journal, completed=completed + journal_completed, total=total)

        run_journal_monitor(
            config=fetch_config,
            storage=storage,
            start_date=journal_start_date,
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


def paper_to_api(paper: dict[str, Any], *, late_arrival_unread: bool = False) -> dict[str, Any]:
    section = paper.get("publisher_section") or "unknown"
    raw = parse_raw_json(paper)
    merged_pdf = existing_path_or_empty(paper.get("merged_pdf_path") or "")
    main_pdf = existing_path_or_empty(paper.get("main_pdf_path") or "")
    source_path = existing_path_or_empty(paper.get("source_path") or "")
    imported = raw.get("import") if isinstance(raw.get("import"), dict) else {}
    file_meta = raw.get("file") if isinstance(raw.get("file"), dict) else {}
    stored_import_path = existing_path_or_empty(imported.get("stored_path") or "")
    native_file_path = merged_pdf or main_pdf or stored_import_path or source_path
    analysis_path = existing_path_or_empty(paper.get("analysis_path") or "")
    storage_mode = paper_storage_mode(paper, merged_pdf=merged_pdf, main_pdf=main_pdf, source_path=source_path)
    return {
        "paper_id": paper.get("paper_id") or "",
        "title": paper.get("title") or "",
        "journal": display_journal_name(paper),
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
        "main_pdf_path": main_pdf,
        "source_path": source_path,
        "native_file_path": native_file_path,
        "storage_mode": storage_mode,
        "source": paper.get("source") or "",
        "import_batch_id": paper.get("import_batch_id") or "",
        "import_kind": paper.get("import_kind") or "",
        "import_as": paper.get("import_as") or "",
        "file_mime_type": file_meta.get("mime_type") or "",
        "file_extension": file_meta.get("extension") or Path(str(paper.get("original_filename") or "")).suffix.lower(),
        "file_size_bytes": int(paper.get("size_bytes") or 0),
        "original_relative_path": paper.get("original_relative_path") or "",
        "original_parent_relative_path": paper.get("original_parent_relative_path") or "",
        "original_filename": paper.get("original_filename") or "",
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
        "semantic_scholar": semantic_scholar_summary(paper),
        "pubmed": pubmed_summary(paper),
        "ads": ads_summary(paper),
        "google_scholar_url": google_scholar_url(paper),
        "late_arrival": paper_is_late_arrival(paper),
        "late_arrival_unread": bool(late_arrival_unread),
        "bibtex": bibtex_entry(paper),
        "nature_reference": nature_reference(paper),
        "manual_metadata": {
            "volume": _paper_volume_from_raw(raw),
            "issue": clean_text(str(raw.get("issue") or (raw.get("biblio") or {}).get("issue") or "")),
            "pages": _paper_page_from_raw(raw),
        },
        "full_detail": True,
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
        "existing_papers",
        "pdf_attachments_to_import",
        "created_resources",
        "reused_existing_files",
        "resources_or_attachments_to_import",
        "skipped",
        "skipped_system_metadata",
        "mac_aliases_found",
        "missing_source_files",
        "pdf_doi_extracted_count",
        "pdf_doi_missing_count",
        "doi_duplicates",
        "arxiv_duplicates",
        "duplicate_paper_candidates",
        "doi_metadata_refreshed",
        "identifier_metadata_refreshed",
        "report_path",
        "copy_target_root",
        "import_batch_id",
    ]
    summary = {key: result.get(key) for key in keys if key in result}
    summary["errors"] = result.get("errors") or []
    summary["warnings"] = (result.get("warnings") or [])[:20]
    summary["warning_count"] = len(result.get("warnings") or [])
    summary["missing_sources"] = result.get("missing_sources") or []
    summary["pdfs_without_doi"] = result.get("pdfs_without_doi") or []
    summary["aliases"] = result.get("aliases") or []
    summary["duplicate_dois"] = result.get("duplicate_dois") or []
    summary["duplicate_arxiv_ids"] = result.get("duplicate_arxiv_ids") or []
    return summary


def publication_metadata_from_doi(
    doi: str,
    *,
    timeout: int = 20,
    max_retries: int = 3,
    allow_data_repository: bool = False,
) -> dict[str, Any] | None:
    doi = normalize_publication_doi(doi)
    if not doi or not looks_like_doi(doi) or (doi_is_likely_data_repository(doi) and not allow_data_repository):
        return None
    candidates = search_crossref_publications(doi, kind="doi", timeout=timeout, max_retries=max_retries)
    if not candidates:
        return None
    normalized = paper_from_publication_candidate(candidates[0])
    return enrich_from_landing_page(dict(normalized), {}, True)


def publication_metadata_from_datacite_doi(
    doi: str,
    *,
    timeout: int = 20,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    doi = normalize_publication_doi(doi)
    if not doi or not looks_like_doi(doi):
        return None
    response = request_with_retries(
        "GET",
        f"https://api.datacite.org/dois/{quote(doi, safe='')}",
        timeout=timeout,
        max_retries=max_retries,
    )
    data = response.json().get("data") or {}
    attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
    if not attrs:
        return None
    titles = attrs.get("titles") if isinstance(attrs.get("titles"), list) else []
    title = normalize_publication_title(next((item.get("title") for item in titles if isinstance(item, dict) and item.get("title")), ""))
    descriptions = attrs.get("descriptions") if isinstance(attrs.get("descriptions"), list) else []
    abstract = clean_text(next((item.get("description") for item in descriptions if isinstance(item, dict) and item.get("description")), ""))
    year = clean_text(str(attrs.get("publicationYear") or ""))
    publisher = journal_name_for_doi(clean_text(attrs.get("publisher") or "DataCite"), doi)
    resource_type = attrs.get("types") if isinstance(attrs.get("types"), dict) else {}
    creators = attrs.get("creators") if isinstance(attrs.get("creators"), list) else []
    url = clean_text(attrs.get("url") or f"https://doi.org/{doi}")
    return {
        "paper_id": "doi_" + hashlib.sha1(doi.lower().encode("utf-8")).hexdigest()[:16],
        "doi": doi,
        "title": title or doi,
        "journal": publisher or "DataCite",
        "publication_date": year,
        "abstract": abstract,
        "abstract_source": "datacite" if abstract else "missing",
        "url": url,
        "landing_url": url,
        "pdf_url": "",
        "source": "datacite",
        "type": clean_text(resource_type.get("resourceTypeGeneral") or "dataset").lower(),
        "type_crossref": clean_text(resource_type.get("resourceTypeGeneral") or "dataset").lower(),
        "publisher_section": "dataset",
        "section_allowed": True,
        "raw": {"datacite": attrs, "creators": creators, "doi": doi},
    }


def publication_metrics_metadata_from_doi(
    doi: str,
    *,
    timeout: int = 20,
    max_retries: int = 3,
    allow_data_repository: bool = False,
) -> dict[str, Any] | None:
    doi = normalize_publication_doi(doi)
    if not doi or not looks_like_doi(doi) or (doi_is_likely_data_repository(doi) and not allow_data_repository):
        return None
    crossref_count: int | None = None
    crossref_journal = ""
    crossref_raw: dict[str, Any] = {}
    try:
        crossref = publication_metadata_from_doi(
            doi,
            timeout=timeout,
            max_retries=max_retries,
            allow_data_repository=allow_data_repository,
        )
        if isinstance(crossref, dict):
            crossref_journal = normalize_openalex_journal_name(crossref.get("journal") or "")
        crossref_raw = crossref.get("raw") if isinstance(crossref, dict) else {}
        if isinstance(crossref_raw, dict):
            crossref_count = int_or_none(crossref_raw.get("is-referenced-by-count"))
        else:
            crossref_raw = {}
    except Exception:
        crossref_count = None
        crossref_raw = {}
    try:
        response = request_with_retries(
            "GET",
            f"https://api.openalex.org/works/https://doi.org/{doi}",
            params={"mailto": "your_email@example.com"},
            timeout=timeout,
            max_retries=max_retries,
        )
        item = response.json()
        if isinstance(item, dict) and item.get("id"):
            source_journal = normalize_openalex_journal_name(((item.get("primary_location") or {}).get("source") or {}).get("display_name"))
            journal = crossref_journal or source_journal or "Unknown Journal"
            normalized = normalize_openalex_item(item, journal)
            raw = normalized.setdefault("raw", {})
            if isinstance(raw, dict):
                merge_crossref_bibliographic_raw(raw, crossref_raw)
                if crossref_count is not None:
                    raw["is-referenced-by-count"] = crossref_count
            return normalized
    except Exception:
        pass
    if allow_data_repository:
        try:
            datacite = publication_metadata_from_datacite_doi(doi, timeout=timeout, max_retries=max_retries)
            if datacite:
                return datacite
        except Exception:
            pass
    return publication_metadata_from_doi(
        doi,
        timeout=timeout,
        max_retries=max_retries,
        allow_data_repository=allow_data_repository,
    )


def publication_metrics_metadata_from_arxiv_id(
    arxiv_id: str,
    *,
    timeout: int = 20,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    normalized_id = normalize_arxiv_identifier(arxiv_id)
    if not normalized_id:
        return None
    paper = fetch_arxiv_by_id(normalized_id, timeout=timeout, max_retries=max_retries)
    if not paper:
        return None
    raw = paper.setdefault("raw", {})
    arxiv_doi = normalize_publication_doi(str(paper.get("doi") or ""))
    if doi_is_likely_published_version(arxiv_doi):
        published = publication_metrics_metadata_from_doi(arxiv_doi, timeout=timeout, max_retries=max_retries)
        if published:
            return attach_arxiv_preprint_metadata(published, paper)
    title = clean_text(paper.get("title") or "")
    if title:
        try:
            response = request_with_retries(
                "GET",
                "https://api.openalex.org/works",
                params={"search": title, "per-page": 1, "mailto": "your_email@example.com"},
                timeout=timeout,
                max_retries=max_retries,
            )
            for item in response.json().get("results") or []:
                if not isinstance(item, dict):
                    continue
                result_title = clean_text(item.get("title") or item.get("display_name") or "")
                if normalized_title_key(result_title) != normalized_title_key(title) and title_similarity(title, result_title) < 0.88:
                    continue
                if openalex_item_is_likely_data_repository(item):
                    continue
                raw["openalex_id"] = clean_text(item.get("id") or "")
                raw["id"] = clean_text(item.get("id") or "")
                raw["cited_by_count"] = item.get("cited_by_count")
                raw["counts_by_year"] = item.get("counts_by_year") or []
                raw["openalex"] = item
                if not paper.get("doi"):
                    paper["doi"] = normalize_publication_doi(clean_text(item.get("doi") or ""))
                doi = normalize_publication_doi(clean_text(item.get("doi") or ""))
                if doi_is_likely_published_version(doi):
                    published = publication_metrics_metadata_from_doi(doi, timeout=timeout, max_retries=max_retries)
                    if published:
                        return attach_arxiv_preprint_metadata(published, paper)
                break
        except Exception:
            pass
    return paper


def pubmed_metadata_from_doi(
    doi: str,
    *,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    doi = normalize_publication_doi(doi)
    if not doi or not looks_like_doi(doi):
        return None
    pmid = ""
    pmcid = ""
    try:
        response = request_with_retries(
            "GET",
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            params={
                "db": "pubmed",
                "term": f"{doi}[AID]",
                "retmode": "json",
                "retmax": "1",
                "tool": NCBI_EUTILS_TOOL,
                "email": NCBI_EUTILS_EMAIL,
            },
            timeout=timeout,
            max_retries=max_retries,
        )
        ids = ((response.json().get("esearchresult") or {}).get("idlist") or [])
        pmid = clean_text(str(ids[0] if ids else ""))
    except Exception:
        pmid = ""
    if not pmid:
        try:
            response = request_with_retries(
                "GET",
                "https://pmc.ncbi.nlm.nih.gov/tools/idconv/api/v1/articles/",
                params={"ids": doi, "format": "json", "tool": NCBI_EUTILS_TOOL, "email": NCBI_EUTILS_EMAIL},
                timeout=timeout,
                max_retries=max_retries,
            )
            records = response.json().get("records") or []
            record = records[0] if records and isinstance(records[0], dict) else {}
            pmid = clean_text(str(record.get("pmid") or ""))
            pmcid = clean_text(str(record.get("pmcid") or ""))
        except Exception:
            pmid = ""
    if not pmid:
        return None
    try:
        response = request_with_retries(
            "GET",
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            params={"db": "pubmed", "id": pmid, "retmode": "xml", "tool": NCBI_EUTILS_TOOL, "email": NCBI_EUTILS_EMAIL},
            timeout=timeout,
            max_retries=max_retries,
        )
        root = ET.fromstring(response.content)
    except Exception:
        return {"pmid": pmid, "pmcid": pmcid, "doi": doi}
    article = root.find(".//PubmedArticle")
    if article is None:
        return {"pmid": pmid, "pmcid": pmcid, "doi": doi}
    parsed = parse_pubmed_article(article)
    parsed["pmid"] = clean_text(parsed.get("pmid") or pmid)
    parsed["pmcid"] = clean_text(parsed.get("pmcid") or pmcid)
    parsed["doi"] = normalize_publication_doi(str(parsed.get("doi") or doi))
    return parsed


def refresh_pubmed_if_possible(
    storage: Storage,
    paper: dict[str, Any] | None,
    *,
    doi: str = "",
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    if not paper:
        return paper
    paper_id = clean_text(paper.get("paper_id") or "")
    normalized_doi = normalize_publication_doi(doi or str(paper.get("doi") or ""))
    if not paper_id or not normalized_doi or not looks_like_doi(normalized_doi):
        return paper
    try:
        pubmed = pubmed_metadata_from_doi(normalized_doi, timeout=timeout, max_retries=max_retries)
    except Exception:
        return paper
    if not pubmed:
        return paper
    raw = parse_raw_json(paper)
    raw["pubmed"] = pubmed
    if pubmed.get("pmid"):
        raw["pmid"] = pubmed.get("pmid")
    if pubmed.get("pmcid"):
        raw["pmcid"] = pubmed.get("pmcid")
    updated = storage.update_paper_raw_json(paper_id, raw) or paper
    sync_my_publication_pubmed_author_marks(storage, paper_id=paper_id, pubmed=pubmed)
    if not clean_text(updated.get("abstract") or "") and clean_text(pubmed.get("abstract") or ""):
        updated = storage.refresh_paper_metadata(
            paper_id,
            merge_refreshed_metadata(
                updated,
                {
                    "paper_id": paper_id,
                    "doi": updated.get("doi") or normalized_doi,
                    "title": updated.get("title") or pubmed.get("title") or "",
                    "journal": updated.get("journal") or pubmed.get("journal") or "",
                    "publication_date": updated.get("publication_date") or pubmed.get("publication_date") or "",
                    "abstract": clean_text(pubmed.get("abstract") or ""),
                    "abstract_source": "pubmed",
                    "source": updated.get("source") or "pubmed",
                    "raw": raw,
                },
            ),
        ) or updated
    return updated


def pubmed_author_entry_roles(item: dict[str, Any], *, index: int) -> dict[str, Any]:
    roles = item.get("roles") if isinstance(item.get("roles"), dict) else {}
    first_author = bool(roles.get("first_author"))
    co_first_author = bool(roles.get("co_first_author"))
    corresponding_author = bool(roles.get("corresponding_author"))
    notes = [clean_text(str(value)) for value in roles.get("notes") or [] if clean_text(str(value))]
    if first_author or co_first_author or corresponding_author or notes:
        return {
            "first_author": first_author,
            "co_first_author": co_first_author,
            "corresponding_author": corresponding_author,
            "notes": notes,
        }
    text = " ".join(clean_text(str(value)) for value in item.get("affiliations") or []).lower()
    equal = any(
        phrase in text
        for phrase in [
            "equal contribution",
            "contributed equally",
            "equally contributed",
            "co-first",
            "co first",
            "joint first",
            "shared first",
        ]
    )
    corresponding = pubmed_text_has_email(text) or any(
        phrase in text
        for phrase in [
            "corresponding author",
            "correspondence",
            "corresponding authors",
            "electronic address",
            "e-mail",
            "email:",
        ]
    )
    inferred_notes = []
    if index == 0 and not equal:
        inferred_notes.append("first author")
    if equal:
        inferred_notes.append("equal contribution")
    if corresponding:
        inferred_notes.append("corresponding author")
    return {
        "first_author": bool(index == 0 and not equal),
        "co_first_author": bool(equal),
        "corresponding_author": bool(corresponding),
        "notes": inferred_notes,
    }


def pubmed_author_marks(pubmed: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = pubmed.get("author_affiliations") if isinstance(pubmed.get("author_affiliations"), list) else []
    marks: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            continue
        roles = pubmed_author_entry_roles(item, index=index)
        first_author = bool(roles.get("first_author"))
        co_first_author = bool(roles.get("co_first_author"))
        corresponding_author = bool(roles.get("corresponding_author"))
        if not (first_author or co_first_author or corresponding_author):
            continue
        marks[str(index)] = {
            "name": clean_text(item.get("name") or ""),
            "first_author": first_author,
            "co_first_author": co_first_author,
            "corresponding_author": corresponding_author,
            "source": "pubmed_auto",
        }
    return marks


def sync_my_publication_pubmed_author_marks(storage: Storage, *, paper_id: str, pubmed: dict[str, Any]) -> None:
    marks = pubmed_author_marks(pubmed)
    if not marks:
        return
    rows = storage.conn.execute(
        "SELECT id, author_marks FROM my_publications WHERE paper_id = ?",
        (paper_id,),
    ).fetchall()
    if not rows:
        return
    aggregate_co_first = any(mark.get("co_first_author") for mark in marks.values())
    aggregate_corresponding = any(mark.get("corresponding_author") for mark in marks.values())
    timestamp = now_iso()
    for row in rows:
        try:
            existing_marks = json.loads(row["author_marks"] or "{}")
        except json.JSONDecodeError:
            existing_marks = {}
        if isinstance(existing_marks, dict) and existing_marks:
            continue
        storage.conn.execute(
            """
            UPDATE my_publications
            SET author_marks = ?,
                first_author = ?,
                corresponding_author = ?,
                starred = CASE WHEN ? OR ? THEN 1 ELSE starred END,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(marks, ensure_ascii=False),
                1 if aggregate_co_first else 0,
                1 if aggregate_corresponding else 0,
                1 if aggregate_co_first else 0,
                1 if aggregate_corresponding else 0,
                timestamp,
                int(row["id"]),
            ),
        )
    storage.conn.commit()


def sync_my_publication_existing_pubmed_marks(storage: Storage, *, paper_id: str) -> None:
    paper = storage.get_paper(paper_id)
    if not paper:
        return
    raw = parse_raw_json(paper)
    pubmed = raw.get("pubmed") if isinstance(raw.get("pubmed"), dict) else {}
    if pubmed:
        sync_my_publication_pubmed_author_marks(storage, paper_id=paper_id, pubmed=pubmed)


def pubmed_text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return clean_text(" ".join("".join(element.itertext()).split()))


def pubmed_first_text(root: ET.Element | None, path: str) -> str:
    if root is None:
        return ""
    return pubmed_text(root.find(path))


def parse_pubmed_article(article: ET.Element) -> dict[str, Any]:
    journal = article.find(".//Article/Journal")
    pub_date = journal.find("./JournalIssue/PubDate") if journal is not None else None
    article_ids = {
        clean_text(node.attrib.get("IdType") or "").lower(): pubmed_text(node)
        for node in article.findall(".//PubmedData/ArticleIdList/ArticleId")
    }
    abstract_parts = []
    for node in article.findall(".//Article/Abstract/AbstractText"):
        label = clean_text(node.attrib.get("Label") or "")
        text = pubmed_text(node)
        if text:
            abstract_parts.append(f"{label}: {text}" if label else text)
    authors = []
    affiliations = []
    author_affiliations = []
    for index, node in enumerate(article.findall(".//Article/AuthorList/Author")):
        collective = pubmed_first_text(node, "./CollectiveName")
        current_affiliations = []
        for aff in node.findall("./AffiliationInfo/Affiliation"):
            text = pubmed_text(aff)
            if text:
                affiliations.append(text)
                current_affiliations.append(text)
        roles = pubmed_author_roles(node, current_affiliations, index=index)
        if collective:
            authors.append(collective)
            author_affiliations.append({"name": collective, "affiliations": current_affiliations, "roles": roles})
            continue
        last = pubmed_first_text(node, "./LastName")
        fore = pubmed_first_text(node, "./ForeName")
        initials = pubmed_first_text(node, "./Initials")
        name = " ".join(part for part in [fore or initials, last] if part)
        if name:
            authors.append(name)
            author_affiliations.append({"name": name, "affiliations": current_affiliations, "roles": roles})
    mesh = []
    for node in article.findall(".//MeshHeadingList/MeshHeading"):
        descriptor = node.find("./DescriptorName")
        if descriptor is None:
            continue
        qualifiers = [pubmed_text(item) for item in node.findall("./QualifierName") if pubmed_text(item)]
        mesh.append(
            {
                "descriptor": pubmed_text(descriptor),
                "ui": clean_text(descriptor.attrib.get("UI") or ""),
                "major": clean_text(descriptor.attrib.get("MajorTopicYN") or "").upper() == "Y",
                "qualifiers": qualifiers,
            }
        )
    keywords = [pubmed_text(node) for node in article.findall(".//KeywordList/Keyword") if pubmed_text(node)]
    publication_types = [pubmed_text(node) for node in article.findall(".//PublicationTypeList/PublicationType") if pubmed_text(node)]
    return {
        "pmid": pubmed_first_text(article, ".//MedlineCitation/PMID"),
        "pmcid": clean_text(article_ids.get("pmc") or ""),
        "doi": normalize_publication_doi(str(article_ids.get("doi") or "")),
        "title": normalize_publication_title(pubmed_first_text(article, ".//Article/ArticleTitle")),
        "journal": pubmed_first_text(journal, "./Title") if journal is not None else "",
        "journal_iso_abbrev": pubmed_first_text(journal, "./ISOAbbreviation") if journal is not None else "",
        "issn": pubmed_first_text(journal, "./ISSN") if journal is not None else "",
        "publication_date": pubmed_publication_date(pub_date),
        "volume": pubmed_first_text(journal, "./JournalIssue/Volume") if journal is not None else "",
        "issue": pubmed_first_text(journal, "./JournalIssue/Issue") if journal is not None else "",
        "pages": pubmed_first_text(article, ".//Article/Pagination/MedlinePgn"),
        "abstract": clean_text("\n\n".join(abstract_parts)),
        "authors": authors,
        "affiliations": affiliations[:20],
        "author_affiliations": author_affiliations,
        "mesh": mesh,
        "keywords": keywords,
        "publication_types": publication_types,
        "nlm_unique_id": pubmed_first_text(article, ".//MedlineJournalInfo/NlmUniqueID"),
        "medline_ta": pubmed_first_text(article, ".//MedlineJournalInfo/MedlineTA"),
    }


def pubmed_author_roles(node: ET.Element, affiliations: list[str], *, index: int) -> dict[str, Any]:
    text = " ".join(affiliations).lower()
    equal = clean_text(node.attrib.get("EqualContrib") or "").upper() == "Y"
    equal = equal or any(
        phrase in text
        for phrase in [
            "equal contribution",
            "contributed equally",
            "equally contributed",
            "co-first",
            "co first",
            "joint first",
            "shared first",
        ]
    )
    corresponding = pubmed_text_has_email(text) or any(
        phrase in text
        for phrase in [
            "corresponding author",
            "correspondence",
            "corresponding authors",
            "electronic address",
            "e-mail",
            "email:",
        ]
    )
    notes = []
    if index == 0 and not equal:
        notes.append("first author")
    if equal:
        notes.append("equal contribution")
    if corresponding:
        notes.append("corresponding author")
    return {
        "first_author": bool(index == 0 and not equal),
        "co_first_author": bool(equal),
        "corresponding_author": bool(corresponding),
        "notes": notes,
    }


def pubmed_text_has_email(text: str) -> bool:
    value = clean_text(str(text or ""))
    if "@" not in value:
        return False
    return bool(re.search(r"[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}", value))


def pubmed_publication_date(pub_date: ET.Element | None) -> str:
    if pub_date is None:
        return ""
    year = pubmed_first_text(pub_date, "./Year")
    month = pubmed_first_text(pub_date, "./Month")
    day = pubmed_first_text(pub_date, "./Day")
    if not year:
        return pubmed_first_text(pub_date, "./MedlineDate")
    if month.isalpha():
        month = {
            "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
            "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
        }.get(month[:3].lower(), month)
    if month and month.isdigit():
        month = month.zfill(2)
    if day and day.isdigit():
        day = day.zfill(2)
    return "-".join(part for part in [year, month, day] if part)


def attach_arxiv_preprint_metadata(published: dict[str, Any], arxiv_paper: dict[str, Any]) -> dict[str, Any]:
    result = dict(published)
    raw = result.setdefault("raw", {})
    arxiv_raw = arxiv_paper.get("raw") if isinstance(arxiv_paper.get("raw"), dict) else {}
    arxiv_id = normalize_arxiv_identifier(str(arxiv_raw.get("arxiv_id") or arxiv_raw.get("versioned_arxiv_id") or arxiv_paper.get("paper_id") or ""))
    preprint = {
        "source": "arxiv",
        "arxiv_id": arxiv_id,
        "versioned_arxiv_id": clean_text(arxiv_raw.get("versioned_arxiv_id") or ""),
        "title": normalize_publication_title(arxiv_paper.get("title") or ""),
        "publication_date": clean_text(arxiv_paper.get("publication_date") or ""),
        "url": clean_text(arxiv_paper.get("url") or arxiv_paper.get("landing_url") or ""),
        "pdf_url": clean_text(arxiv_paper.get("pdf_url") or ""),
        "raw": arxiv_raw,
    }
    raw["preprint"] = {key: value for key, value in preprint.items() if value not in ("", {}, [])}
    if arxiv_id:
        raw["arxiv_id"] = arxiv_id
    if preprint.get("versioned_arxiv_id"):
        raw["versioned_arxiv_id"] = preprint["versioned_arxiv_id"]
    raw["published_doi"] = normalize_publication_doi(str(result.get("doi") or raw.get("DOI") or ""))
    return result


def semantic_scholar_enrichment_for_paper(
    paper: dict[str, Any],
    *,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    fields = (
        "paperId,corpusId,externalIds,url,title,abstract,venue,year,referenceCount,citationCount,"
        "influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,"
        "publicationTypes,publicationDate,journal,authors,tldr"
    )
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    arxiv_id = arxiv_identifier_for_paper(paper)
    refs: list[str] = []
    if arxiv_id and (paper.get("journal") or "").lower() == ARXIV_JOURNAL_NAME.lower():
        refs.append(f"ARXIV:{arxiv_id}")
    if doi and looks_like_doi(doi):
        refs.append(f"DOI:{doi}")
    if arxiv_id and f"ARXIV:{arxiv_id}" not in refs:
        refs.append(f"ARXIV:{arxiv_id}")
    for ref in refs:
        data = semantic_scholar_enrichment_by_ref(ref, fields=fields, timeout=timeout, max_retries=max_retries)
        if data:
            return data
    title = clean_text(paper.get("title") or "")
    if not title:
        return None
    response = request_with_retries(
        "GET",
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={"query": title, "limit": 1, "fields": fields},
        timeout=timeout,
        max_retries=max_retries,
    )
    for item in response.json().get("data") or []:
        if isinstance(item, dict) and item.get("paperId"):
            return item
    return None


def semantic_scholar_enrichment_by_ref(
    ref: str,
    *,
    fields: str,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    if not clean_text(ref):
        return None
    try:
        response = request_with_retries(
            "GET",
            f"https://api.semanticscholar.org/graph/v1/paper/{quote(ref, safe='')}",
            params={"fields": fields},
            timeout=timeout,
            max_retries=max_retries,
        )
        data = response.json()
        if isinstance(data, dict) and data.get("paperId"):
            return data
    except Exception:
        return None
    return None


def refresh_semantic_scholar_if_possible(
    storage: Storage,
    paper: dict[str, Any] | None,
    *,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    if not paper:
        return paper
    paper_id = clean_text(paper.get("paper_id") or "")
    if not paper_id:
        return paper
    try:
        enrichment = semantic_scholar_enrichment_for_paper(paper, timeout=timeout, max_retries=max_retries)
    except Exception:
        return paper
    if not enrichment:
        return paper
    updated = storage.update_semantic_scholar_enrichment(paper_id, enrichment) or paper
    if not clean_text(updated.get("abstract") or "") and clean_text(enrichment.get("abstract") or ""):
        updated = storage.refresh_paper_metadata(
            paper_id,
            merge_refreshed_metadata(
                updated,
                {
                    "paper_id": paper_id,
                    "title": updated.get("title") or enrichment.get("title") or "",
                    "journal": updated.get("journal") or enrichment.get("venue") or "",
                    "publication_date": updated.get("publication_date") or clean_text(str(enrichment.get("year") or "")),
                    "abstract": clean_text(enrichment.get("abstract") or ""),
                    "abstract_source": "semantic_scholar",
                    "raw": parse_raw_json(updated),
                },
            ),
        ) or updated
    return refresh_preprint_citation_version_if_possible(storage, updated, timeout=timeout, max_retries=max_retries) or updated


def refresh_preprint_citation_version_if_possible(
    storage: Storage,
    paper: dict[str, Any] | None,
    *,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    if not paper:
        return paper
    paper_id = clean_text(paper.get("paper_id") or "")
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    arxiv_id = arxiv_identifier_for_paper(paper)
    if not paper_id or not doi or not arxiv_id:
        return paper
    fields = (
        "paperId,corpusId,externalIds,url,title,abstract,venue,year,referenceCount,citationCount,"
        "influentialCitationCount,isOpenAccess,openAccessPdf,fieldsOfStudy,s2FieldsOfStudy,"
        "publicationTypes,publicationDate,journal,authors,tldr"
    )
    semantic = semantic_scholar_enrichment_by_ref(
        f"ARXIV:{arxiv_id}",
        fields=fields,
        timeout=timeout,
        max_retries=max_retries,
    )
    if not semantic:
        raw = ensure_raw_preprint_metadata(parse_raw_json(paper), arxiv_id)
        stored = storage.update_paper_raw_json(paper_id, raw)
        return stored or paper
    raw = parse_raw_json(paper)
    raw = ensure_raw_preprint_metadata(raw, arxiv_id)
    versions = raw.get("citation_versions") if isinstance(raw.get("citation_versions"), dict) else {}
    preprint = versions.get("preprint") if isinstance(versions.get("preprint"), dict) else {}
    semantic_sources = preprint.get("sources") if isinstance(preprint.get("sources"), dict) else {}
    semantic_sources["semantic_scholar"] = semantic
    preprint["sources"] = semantic_sources
    preprint["arxiv_id"] = arxiv_id
    versions["preprint"] = preprint
    raw["citation_versions"] = versions
    stored = storage.update_paper_raw_json(paper_id, raw)
    return stored or paper


def ensure_raw_preprint_metadata(raw: dict[str, Any], arxiv_id: str) -> dict[str, Any]:
    arxiv_id = normalize_arxiv_identifier(arxiv_id)
    if not arxiv_id:
        return raw
    raw = dict(raw or {})
    preprint = raw.get("preprint") if isinstance(raw.get("preprint"), dict) else {}
    preprint = dict(preprint)
    preprint.setdefault("source", "arxiv")
    preprint["arxiv_id"] = arxiv_id
    preprint.setdefault("url", f"https://arxiv.org/abs/{arxiv_id}")
    preprint.setdefault("pdf_url", f"https://arxiv.org/pdf/{arxiv_id}")
    raw["preprint"] = preprint
    raw["arxiv_id"] = arxiv_id
    return raw


def refresh_paper_metadata_from_doi_if_possible(
    storage: Storage,
    paper: dict[str, Any] | None,
    *,
    doi: str = "",
    timeout: int = 20,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    if not paper:
        return paper
    paper_id = clean_text(paper.get("paper_id") or "")
    normalized_doi = normalize_publication_doi(doi or str(paper.get("doi") or ""))
    if not paper_id or not normalized_doi or not looks_like_doi(normalized_doi):
        return paper
    try:
        normalized = publication_metrics_metadata_from_doi(
            normalized_doi,
            timeout=timeout,
            max_retries=max_retries,
            allow_data_repository=doi_is_likely_data_repository(normalized_doi),
        )
    except Exception:
        return paper
    if not normalized:
        return paper
    refreshed = storage.refresh_paper_metadata(paper_id, merge_refreshed_metadata(paper, normalized))
    refreshed = refreshed or paper
    return refresh_pubmed_if_possible(storage, refreshed, doi=normalized_doi, timeout=timeout, max_retries=max_retries) or refreshed


def refresh_paper_metadata_from_arxiv_if_possible(
    storage: Storage,
    paper: dict[str, Any] | None,
    *,
    arxiv_id: str = "",
    timeout: int = 20,
    max_retries: int = 3,
) -> dict[str, Any] | None:
    if not paper:
        return paper
    paper_id = clean_text(paper.get("paper_id") or "")
    normalized_id = normalize_arxiv_identifier(arxiv_id or arxiv_identifier_for_paper(paper))
    if not paper_id or not normalized_id:
        return paper
    try:
        normalized = publication_metrics_metadata_from_arxiv_id(normalized_id, timeout=timeout, max_retries=max_retries)
    except Exception:
        return paper
    if not normalized:
        return paper
    refreshed = storage.refresh_paper_metadata(paper_id, merge_refreshed_metadata(paper, normalized))
    refreshed = refreshed or paper
    published_doi = normalize_publication_doi(str(refreshed.get("doi") or ""))
    if published_doi and looks_like_doi(published_doi):
        refreshed = refresh_pubmed_if_possible(storage, refreshed, doi=published_doi, timeout=timeout, max_retries=max_retries) or refreshed
    return refreshed


def refresh_imported_doi_metadata(storage: Storage, result: dict[str, Any], *, job_id: str | None = None) -> int:
    batch_id = clean_text(result.get("import_batch_id") or "")
    if batch_id:
        rows = storage.conn.execute(
            """
            SELECT *
            FROM papers
            WHERE import_batch_id = ?
            ORDER BY original_relative_path ASC, title ASC
            """,
            (batch_id,),
        ).fetchall()
        papers = [dict(row) for row in rows]
    else:
        plans = list(result.get("papers_to_create") or []) + list(result.get("papers_to_update") or [])
        papers = [
            {"paper_id": plan.get("paper_id"), "doi": plan.get("doi"), "arxiv_id": plan.get("arxiv_id")}
            for plan in plans
            if isinstance(plan, dict)
        ]
    refreshed_count = 0
    seen: set[str] = set()
    eligible: list[dict[str, Any]] = []
    for paper in papers:
        paper_id = clean_text(paper.get("paper_id") or "")
        doi = normalize_publication_doi(str(paper.get("doi") or ""))
        arxiv_id = normalize_arxiv_identifier(str(paper.get("arxiv_id") or "")) or arxiv_identifier_for_paper(paper)
        if paper_id and (looks_like_doi(doi) or arxiv_id):
            eligible.append({"paper_id": paper_id, "doi": doi, "arxiv_id": arxiv_id})
    total = len(eligible)
    if job_id:
        if total:
            log_library_import_job(job_id, f"Refreshing Details metadata and citation metrics from DOI/arXiv for {total} imported papers")
        else:
            log_library_import_job(job_id, "No imported papers with DOI/arXiv ID were found for Details metadata refresh")
    current = 0
    for paper in eligible:
        if job_id and library_import_cancel_requested(job_id):
            raise ImportCancelled("Import stopped by user")
        paper_id = clean_text(paper.get("paper_id") or "")
        doi = normalize_publication_doi(str(paper.get("doi") or ""))
        arxiv_id = normalize_arxiv_identifier(str(paper.get("arxiv_id") or ""))
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        current += 1
        identifier = doi if looks_like_doi(doi) else arxiv_id
        identifier_kind = "DOI" if looks_like_doi(doi) else "arXiv"
        if job_id:
            percent = max(0, min(99, round((current / total) * 100))) if total else 0
            update_library_import_job(job_id, stage="metadata", current=current, total=total, percent=percent)
            log_library_import_job(job_id, f"Refreshing Details metadata and metrics from {identifier_kind} {current} / {total}: {identifier}")
        stored_paper = storage.get_paper(paper_id)
        before = dict(stored_paper or {})
        if looks_like_doi(doi):
            refreshed = refresh_paper_metadata_from_doi_if_possible(storage, stored_paper, doi=doi, timeout=12, max_retries=1)
        else:
            refreshed = refresh_paper_metadata_from_arxiv_if_possible(storage, stored_paper, arxiv_id=arxiv_id, timeout=12, max_retries=1)
        refreshed = refresh_semantic_scholar_if_possible(storage, refreshed, timeout=6, max_retries=1) or refreshed
        refreshed = refresh_ads_if_possible(storage, refreshed, timeout=6, max_retries=1) or refreshed
        if refreshed and refreshed != before:
            refreshed_count += 1
            if job_id:
                label = clean_text(refreshed.get("title") or identifier)
                log_library_import_job(job_id, f"Refreshed {identifier_kind} metadata: {label}")
    result["doi_metadata_refreshed"] = refreshed_count
    result["identifier_metadata_refreshed"] = refreshed_count
    return refreshed_count


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
    display_name = item.get("display_name") or ""
    if clean_text(display_name) == clean_text(paper.get("title") or ""):
        display_name = ""
    result = {
        "id": int(item.get("id") or 0),
        "folder_id": int(item.get("folder_id") or 1),
        "paper_id": paper.get("paper_id") or item.get("paper_id") or "",
        "paper": paper_to_library_summary_api(paper),
    }
    if display_name:
        result["display_name"] = display_name
    sort_order = int(item.get("sort_order") or 0)
    if sort_order:
        result["sort_order"] = sort_order
    if item.get("original_folder_id") is not None:
        result["original_folder_id"] = int(item["original_folder_id"])
    if item.get("trashed_at"):
        result["trashed_at"] = item.get("trashed_at") or ""
    return result


def paper_to_library_summary_api(paper: dict[str, Any]) -> dict[str, Any]:
    raw = parse_raw_json(paper)
    merged_pdf = existing_path_or_empty(paper.get("merged_pdf_path") or "")
    main_pdf = existing_path_or_empty(paper.get("main_pdf_path") or "")
    source_path = existing_path_or_empty(paper.get("source_path") or "")
    imported = raw.get("import") if isinstance(raw.get("import"), dict) else {}
    file_meta = raw.get("file") if isinstance(raw.get("file"), dict) else {}
    stored_import_path = existing_path_or_empty(imported.get("stored_path") or "")
    native_file_path = merged_pdf or main_pdf or stored_import_path or source_path
    storage_mode = paper_storage_mode(paper, merged_pdf=merged_pdf, main_pdf=main_pdf, source_path=source_path)
    summary = {
        "paper_id": paper.get("paper_id") or "",
        "title": paper.get("title") or "",
        "full_detail": False,
        "storage_mode": storage_mode,
        "source": paper.get("source") or "",
        "import_batch_id": paper.get("import_batch_id") or "",
        "import_kind": paper.get("import_kind") or "",
        "import_as": paper.get("import_as") or "",
        "file_mime_type": file_meta.get("mime_type") or "",
        "file_extension": file_meta.get("extension") or Path(str(paper.get("original_filename") or "")).suffix.lower(),
        "file_size_bytes": int(paper.get("size_bytes") or 0),
    }
    for key in ["journal", "publication_date", "doi"]:
        value = paper.get(key) or ""
        if value:
            summary[key] = value
    download_status = paper.get("download_status") or "not_attempted"
    if download_status != "not_attempted":
        summary["download_status"] = download_status
    analysis_status = paper.get("analysis_status") or "not_started"
    if analysis_status != "not_started":
        summary["analysis_status"] = analysis_status
    if merged_pdf:
        summary["merged_pdf_path"] = merged_pdf
    preprint_id = preprint_identifier(paper)
    if preprint_id:
        summary["preprint_id"] = preprint_id
    preprint_category = preprint_primary_category(paper)
    if preprint_category:
        summary["preprint_category"] = preprint_category
    if main_pdf and main_pdf != merged_pdf:
        summary["main_pdf_path"] = main_pdf
    if native_file_path:
        summary["native_file_path"] = native_file_path
    if source_path and not merged_pdf and not main_pdf:
        summary["source_path"] = source_path
    return summary


def library_naming_rule(storage: Storage) -> str:
    rule = storage.get_setting(LIBRARY_NAMING_RULE_SETTING, DEFAULT_LIBRARY_NAMING_RULE).strip().lower()
    return rule if rule in LIBRARY_NAMING_RULES else DEFAULT_LIBRARY_NAMING_RULE


def ads_api_token(storage: Storage) -> str:
    return clean_text(storage.get_setting(ADS_API_TOKEN_SETTING, ""))


def sanitize_google_scholar_profile(profile: Any) -> dict[str, Any]:
    if not isinstance(profile, dict):
        return {}
    interests = profile.get("interests")
    if not isinstance(interests, list):
        interests = []
    clean_interests = [clean_text(str(item)) for item in interests if clean_text(str(item))]
    sanitized = {
        "candidate_type": "scholar-profile",
        "name": clean_text(str(profile.get("name") or "")),
        "affiliation": clean_text(str(profile.get("affiliation") or "")),
        "email": clean_text(str(profile.get("email") or "")),
        "cited_by": clean_text(str(profile.get("cited_by") or "")),
        "interests": clean_interests[:20],
        "url": clean_text(str(profile.get("url") or "")),
        "user_id": clean_text(str(profile.get("user_id") or "")),
        "avatar_url": clean_text(str(profile.get("avatar_url") or "")),
    }
    return sanitized if sanitized["name"] or sanitized["url"] or sanitized["user_id"] or sanitized["avatar_url"] else {}


def load_my_publications_scholar_profile(storage: Storage) -> dict[str, Any]:
    raw = storage.get_setting(MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING, "")
    if not raw:
        return {}
    try:
        return sanitize_google_scholar_profile(json.loads(raw))
    except Exception:
        return {}


def save_my_publications_scholar_profile(storage: Storage, profile: Any) -> dict[str, Any]:
    sanitized = sanitize_google_scholar_profile(profile)
    storage.set_setting(
        MY_PUBLICATIONS_SCHOLAR_PROFILE_SETTING,
        json.dumps(sanitized, ensure_ascii=False) if sanitized else "",
    )
    return sanitized


def save_my_publications_scholar_profile_for_db(db_path: Path, profile: Any) -> dict[str, Any]:
    storage = Storage(db_path)
    try:
        return save_my_publications_scholar_profile(storage, profile)
    finally:
        storage.close()


def default_library_item_display_name(paper: dict[str, Any], *, rule: str = DEFAULT_LIBRARY_NAMING_RULE) -> str:
    if rule == "title":
        label = paper.get("title") or citation_label(paper) or "Untitled paper"
    else:
        label = citation_label(paper) or paper.get("title") or "Untitled paper"
    label = re.sub(r"^(.+?) et al\.(\s+)", r"\1\2", clean_text(label))
    return re.sub(r"\s+", "_", label).strip("_") or "Untitled_paper"


def my_publication_to_api(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row.get("id") or 0),
        "paper_id": row.get("paper_id") or "",
        "starred": bool(row.get("starred")),
        "first_author": bool(row.get("first_author")),
        "corresponding_author": bool(row.get("corresponding_author")),
        "review_article": bool(row.get("review_article")),
        "head": bool(row.get("export_excluded")),
        "author_marks": parse_my_publication_author_marks(row),
        "manual_metadata_editable": my_publication_allows_manual_metadata(row),
        "sort_order": int(row.get("sort_order") or 0),
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("updated_at") or "",
        "paper": paper_to_api(row),
    }


def parse_my_publication_author_marks(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = row.get("author_marks") or "{}"
    try:
        marks = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        marks = {}
    if not isinstance(marks, dict):
        return {}
    clean_marks: dict[str, dict[str, Any]] = {}
    for key, value in marks.items():
        if not isinstance(value, dict):
            continue
        clean_marks[str(key)] = {
            "name": clean_text(value.get("name") or ""),
            "first_author": bool(value.get("first_author")),
            "co_first_author": bool(value.get("co_first_author")),
            "corresponding_author": bool(value.get("corresponding_author")),
        }
    return clean_marks


def my_publication_allows_manual_metadata(row: dict[str, Any]) -> bool:
    doi = normalize_publication_doi(str(row.get("doi") or ""))
    return not doi and not preprint_identifier(row)


def parse_manual_author_list(value: Any) -> list[str]:
    text = clean_text(value)
    if not text:
        return []
    if re.search(r"[;\n；、，]", text):
        parts = re.split(r"\s*(?:[;\n；、，]+)\s*", text)
    else:
        parts = re.split(r"\s*,\s*", text)
    return dedup_names([clean_author_name(part) for part in parts if clean_author_name(part)])


def publication_candidate_to_api(paper: dict[str, Any]) -> dict[str, Any]:
    candidate = dict(paper)
    if "raw_json" not in candidate:
        candidate["raw_json"] = json.dumps(candidate.get("raw") or {}, ensure_ascii=False)
    raw = candidate.get("raw") or parse_raw_json(candidate)
    return {
        "paper_id": candidate.get("paper_id") or "",
        "doi": candidate.get("doi") or "",
        "paper": paper_to_api(candidate),
        "raw": raw,
        "arxiv_id": normalize_arxiv_identifier(str(raw.get("arxiv_id") or raw.get("versioned_arxiv_id") or "")) if isinstance(raw, dict) else "",
    }


def publication_to_reimport_candidate(publication: dict[str, Any]) -> dict[str, Any]:
    raw = parse_raw_json(publication)
    paper = {
        "title": publication.get("title") or "",
        "journal": publication.get("journal") or "",
        "publication_date": publication.get("publication_date") or raw.get("year") or "",
        "doi": publication.get("doi") or "",
        "url": publication.get("url") or publication.get("landing_url") or "",
        "landing_url": publication.get("landing_url") or publication.get("url") or "",
        "source": publication.get("source") or "manual",
        "raw": raw,
    }
    return {"paper": paper, "raw": raw}


def paper_from_publication_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else candidate
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else paper.get("raw")
    if isinstance(raw, dict) and ("DOI" in raw or "container-title" in raw):
        raw_doi = normalize_publication_doi(str(raw.get("DOI") or paper.get("doi") or ""))
        journal = clean_text(first_crossref_text(raw.get("container-title"))) or clean_text(paper.get("journal") or "Unknown Journal")
        journal = journal_name_for_doi(journal, raw_doi) or "Unknown Journal"
        return normalize_crossref_item(raw, journal)
    publication_date = clean_text(paper.get("publication_date") or "")
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    title = normalize_publication_title(paper.get("title") or "(Untitled)")
    journal = journal_name_for_doi(paper.get("journal") or "Unknown Journal", doi) or "Unknown Journal"
    arxiv_id = normalize_arxiv_identifier(str(raw.get("arxiv_id") or raw.get("versioned_arxiv_id") or "")) if isinstance(raw, dict) else ""
    return {
        "paper_id": paper.get("paper_id") or (f"arxiv_{safe_slug(arxiv_id, 90)}" if arxiv_id else paper_id_from_publication(doi, title, journal, publication_date)),
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


def search_crossref_publications(
    search_text: str,
    *,
    kind: str = "auto",
    rows: int = 12,
    timeout: int = 20,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    query = clean_text(search_text)
    detected = "doi" if looks_like_doi(query) else "title"
    search_kind = kind if kind in {"doi", "title", "author", "bibliographic"} else detected
    if search_kind == "doi":
        doi = normalize_publication_doi(query)
        response = request_with_retries(
            "GET",
            f"https://api.crossref.org/works/{quote(doi, safe='')}",
            timeout=timeout,
            max_retries=max_retries,
        )
        item = response.json().get("message", {})
        if not item:
            return []
        journal = journal_name_for_doi(clean_text(first_crossref_text(item.get("container-title"))) or "Unknown Journal", doi) or "Unknown Journal"
        return [normalize_crossref_item(item, journal)]

    params: dict[str, Any] = {"rows": max(1, min(50, int(rows or 12)))}
    if search_kind == "author":
        params["query.author"] = query
        params["sort"] = "published"
        params["order"] = "desc"
    elif search_kind == "bibliographic":
        params["query.bibliographic"] = query
    else:
        params["query.title"] = query
    response = request_with_retries(
        "GET",
        "https://api.crossref.org/works",
        params=params,
        timeout=timeout,
        max_retries=max_retries,
    )
    items = response.json().get("message", {}).get("items", [])
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        item_doi = normalize_publication_doi(str(item.get("DOI") or ""))
        journal = journal_name_for_doi(clean_text(first_crossref_text(item.get("container-title"))) or "Unknown Journal", item_doi) or "Unknown Journal"
        paper = normalize_crossref_item(item, journal)
        key = paper.get("doi") or paper.get("paper_id")
        if key in seen:
            continue
        seen.add(key)
        results.append(paper)
    return results


def parse_author_search_query(search_text: str) -> tuple[str, list[str]]:
    parts = [clean_text(part) for part in re.split(r"[;；]+", search_text) if clean_text(part)]
    if not parts:
        return "", []
    return parts[0], parts[1:]


def local_google_scholar_profiles(storage: Storage, search_text: str, *, limit: int = 20) -> list[dict[str, Any]]:
    author_name, affiliations = parse_author_search_query(search_text)
    if not author_name:
        return []
    profiles_by_user: dict[str, dict[str, Any]] = {}
    for paper in local_google_scholar_candidate_papers(storage):
        authors = full_author_names(paper) or author_summary(paper)
        matching_author = next((author for author in authors if author_matches_name(author, author_name)), "")
        if not matching_author:
            continue
        user_ids = google_scholar_user_ids_from_paper(paper)
        if not user_ids:
            continue
        for user_id in user_ids:
            profile = profiles_by_user.setdefault(
                user_id,
                {
                    "candidate_type": "scholar-profile",
                    "name": author_name or matching_author,
                    "affiliation": "",
                    "email": "",
                    "cited_by": "",
                    "interests": [],
                    "url": f"https://scholar.google.com/citations?user={quote(user_id)}&hl=en",
                    "user_id": user_id,
                    "source": "local",
                    "_papers": [],
                },
            )
            if matching_author and matching_author != author_name:
                profile.setdefault("_aliases", set()).add(matching_author)
            profile["_papers"].append(paper)
    profiles: list[dict[str, Any]] = []
    for profile in profiles_by_user.values():
        papers = profile.pop("_papers", [])
        aliases = profile.pop("_aliases", set())
        journals = dedup_names([clean_text(paper.get("journal") or "") for paper in papers if paper.get("journal")])[:2]
        context_parts = [f"Local Google Scholar imports · {len(papers)} publication{'s' if len(papers) != 1 else ''}"]
        if journals:
            context_parts.append(", ".join(journals))
        if affiliations:
            context_parts.append("; ".join(affiliations))
        if aliases:
            context_parts.append("aliases: " + ", ".join(sorted(aliases)[:3]))
        profile["affiliation"] = " · ".join(context_parts)
        profiles.append(profile)
    return sorted_google_scholar_profiles(profiles, author_name, affiliations)[:limit]


def local_google_scholar_candidate_papers(storage: Storage) -> list[dict[str, Any]]:
    rows = storage.conn.execute(
        """
        SELECT * FROM papers
        WHERE source = 'google-scholar'
           OR url LIKE '%scholar.google.%'
           OR landing_url LIKE '%scholar.google.%'
           OR raw_json LIKE '%scholar.google.%'
           OR raw_json LIKE '%google-scholar%'
        ORDER BY publication_date DESC, journal ASC, title ASC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def google_scholar_user_ids_from_paper(paper: dict[str, Any]) -> list[str]:
    raw = parse_raw_json(paper)
    values: list[Any] = [
        paper.get("url"),
        paper.get("landing_url"),
        paper.get("pdf_url"),
        raw,
    ]
    seen: set[str] = set()
    user_ids: list[str] = []
    for value in values:
        for user_id in google_scholar_user_ids_from_value(value):
            if user_id and user_id not in seen:
                seen.add(user_id)
                user_ids.append(user_id)
    return user_ids


def google_scholar_user_ids_from_value(value: Any) -> list[str]:
    if isinstance(value, dict):
        ids: list[str] = []
        for item in value.values():
            ids.extend(google_scholar_user_ids_from_value(item))
        return ids
    if isinstance(value, (list, tuple)):
        ids = []
        for item in value:
            ids.extend(google_scholar_user_ids_from_value(item))
        return ids
    if not isinstance(value, str):
        return []
    text = html.unescape(value)
    candidates = [text]
    candidates.extend(match.group(0) for match in re.finditer(r"https?://[^\s\"'<>]+", text))
    ids: list[str] = []
    for candidate in candidates:
        user_id = google_scholar_user_id(candidate)
        if user_id:
            ids.append(user_id)
    return dedup_names(ids)


def merge_google_scholar_profiles(
    local_profiles: list[dict[str, Any]],
    remote_profiles: list[dict[str, Any]],
    search_text: str,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    author_name, affiliations = parse_author_search_query(search_text)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for profile in [*local_profiles, *remote_profiles]:
        user_id = clean_text(profile.get("user_id") or "")
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        merged.append(profile)
    return sorted_google_scholar_profiles(merged, author_name, affiliations)[:limit]


def search_crossref_author_publications(
    author_name: str,
    affiliations: list[str],
    *,
    rows: int = 50,
    timeout: int = 20,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    if not affiliations:
        return search_crossref_publications(author_name, kind="author", rows=rows, timeout=timeout, max_retries=max_retries)
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for affiliation in affiliations:
        params = {
            "rows": max(1, min(50, int(rows or 50))),
            "query.author": author_name,
            "query.affiliation": affiliation,
            "sort": "published",
            "order": "desc",
        }
        response = request_with_retries(
            "GET",
            "https://api.crossref.org/works",
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        for item in response.json().get("message", {}).get("items", []):
            if not isinstance(item, dict) or not crossref_item_affiliation_matches(item, affiliations):
                continue
            journal = clean_text(first_crossref_text(item.get("container-title"))) or "Unknown Journal"
            paper = normalize_crossref_item(item, journal)
            key = paper.get("doi") or paper.get("paper_id")
            if not key or key in seen:
                continue
            seen.add(key)
            results.append(paper)
    return results


def crossref_item_affiliation_matches(item: dict[str, Any], affiliations: list[str]) -> bool:
    texts: list[str] = []
    for author in item.get("author") or []:
        if not isinstance(author, dict):
            continue
        for affiliation in author.get("affiliation") or []:
            if isinstance(affiliation, dict):
                texts.append(clean_text(affiliation.get("name") or ""))
            else:
                texts.append(clean_text(affiliation))
    haystack = " ".join(texts).lower()
    return bool(haystack) and any(affiliation_text_matches(haystack, affiliation) for affiliation in affiliations)


def affiliation_text_matches(haystack: str, affiliation: str) -> bool:
    tokens = [token for token in re.findall(r"[a-z0-9]+", clean_text(affiliation).lower()) if len(token) > 1]
    return bool(tokens) and all(token in haystack for token in tokens)


def search_publications(search_text: str, *, kind: str = "auto") -> list[dict[str, Any]]:
    query = clean_text(search_text)
    if not query:
        return []
    arxiv_id = normalize_arxiv_identifier(query)
    if arxiv_id and not looks_like_doi(query):
        paper = publication_metrics_metadata_from_arxiv_id(arxiv_id)
        return [paper] if paper else []
    doi = normalize_publication_doi(query)
    if looks_like_doi(doi) and doi_is_likely_data_repository(doi):
        paper = publication_metrics_metadata_from_doi(doi, allow_data_repository=True)
        return [paper] if paper else []
    search_kind = kind if kind in {"doi", "title", "author", "bibliographic"} else ("doi" if looks_like_doi(query) else "title")
    if search_kind != "author":
        return search_crossref_publications(query, kind=search_kind)

    author_name, affiliations = parse_author_search_query(query)
    if not author_name:
        return []
    results: list[dict[str, Any]] = []
    first_error: Exception | None = None
    lookups = [
        lambda: search_openalex_author_publications(
            author_name,
            affiliations=affiliations,
            max_authors=16,
            per_author=30,
        ),
        lambda: search_crossref_author_publications(author_name, affiliations, rows=50),
    ] if affiliations else [
        lambda: search_crossref_author_publications(author_name, affiliations, rows=50),
        lambda: search_openalex_author_publications(
            author_name,
            affiliations=affiliations,
            max_authors=6,
            per_author=20,
        ),
    ]
    for lookup in lookups:
        try:
            results.extend(lookup())
        except Exception as exc:
            if first_error is None:
                first_error = exc
    merged = dedup_publication_search_results(results)
    if merged or first_error is None:
        return merged
    raise first_error


def dedup_publication_search_results(results: list[dict[str, Any]], *, limit: int = 80) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for paper in results:
        key = publication_search_dedupe_key(paper)
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(paper)
        if len(merged) >= limit:
            break
    return merged


def publication_search_dedupe_key(paper: dict[str, Any]) -> str:
    doi = clean_text(paper.get("doi") or "").lower()
    if doi:
        return f"doi:{doi}"
    title = " ".join(sorted(title_tokens(paper.get("title") or "")))
    journal = clean_text(paper.get("journal") or "").lower()
    year = clean_text(paper.get("publication_date") or "")[:4]
    return f"title:{title}|journal:{journal}|year:{year}"


def search_google_scholar_profiles(search_text: str, *, limit: int = 20) -> list[dict[str, Any]]:
    author_name, affiliations = parse_author_search_query(search_text)
    queries = [
        f"{author_name} {' '.join(affiliations)} Google Scholar profile".strip(),
        f'"{author_name}" Google Scholar profile',
        f"{author_name} {' '.join(affiliations)}".strip(),
    ]
    if affiliations:
        queries.extend(f"{author_name} {affiliation} Google Scholar" for affiliation in affiliations if affiliation)
    queries.append(author_name)
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for query in queries:
        clean_query = clean_text(query)
        if not clean_query:
            continue
        for profile in fetch_google_scholar_profiles_from_search(clean_query, limit=limit):
            if not google_scholar_profile_matches_author(profile, author_name):
                continue
            user_id = clean_text(profile.get("user_id") or "")
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            profiles.append(profile)
            if len(profiles) >= limit:
                return sorted_google_scholar_profiles(profiles, author_name, affiliations)
    if profiles:
        return sorted_google_scholar_profiles(profiles, author_name, affiliations)
    saw_login_redirect = False
    for query in queries:
        clean_query = clean_text(query)
        if not clean_query:
            continue
        try:
            response = request_with_retries(
                "GET",
                "https://scholar.google.com/citations",
                params={"view_op": "search_authors", "mauthors": clean_query, "hl": "en"},
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://scholar.google.com/",
                },
                timeout=20,
                max_retries=1,
            )
        except RuntimeError as exc:
            if is_google_scholar_block_error(exc):
                raise GoogleScholarBlockedError(google_scholar_block_message()) from exc
            raise
        if "accounts.google." in urlparse(response.url).netloc.lower():
            saw_login_redirect = True
            continue
        if is_google_scholar_block_page(response.text, response.url):
            raise GoogleScholarBlockedError(google_scholar_block_message())
        soup = BeautifulSoup(response.text, "html.parser")
        for row in soup.select(".gsc_1usr"):
            profile = google_scholar_author_row_to_profile(row)
            if not google_scholar_profile_matches_author(profile, author_name):
                continue
            user_id = clean_text(profile.get("user_id") or "")
            if not user_id or user_id in seen:
                continue
            seen.add(user_id)
            profiles.append(profile)
            if len(profiles) >= limit:
                return sorted_google_scholar_profiles(profiles, author_name, affiliations)
    if saw_login_redirect and not profiles:
        raise GoogleScholarBlockedError(google_scholar_block_message())
    return sorted_google_scholar_profiles(profiles, author_name, affiliations)


def google_scholar_profile_matches_author(profile: dict[str, Any], author_name: str) -> bool:
    profile_name = clean_text(profile.get("name") or "")
    return not author_name or not profile_name or author_matches_name(profile_name, author_name)


def sorted_google_scholar_profiles(profiles: list[dict[str, Any]], author_name: str, affiliations: list[str]) -> list[dict[str, Any]]:
    return sorted(
        profiles,
        key=lambda profile: google_scholar_profile_match_score(profile, author_name, affiliations),
        reverse=True,
    )


def google_scholar_profile_match_score(profile: dict[str, Any], author_name: str, affiliations: list[str]) -> float:
    profile_name = clean_text(profile.get("name") or "").lower()
    author_tokens = [token for token in re.findall(r"[a-z0-9]+", clean_text(author_name).lower()) if token]
    score = 0.0
    if profile_name == clean_text(author_name).lower():
        score += 10.0
    if author_tokens:
        name_tokens = set(re.findall(r"[a-z0-9]+", profile_name))
        score += len(name_tokens & set(author_tokens))
        if author_tokens[-1] in name_tokens:
            score += 3.0
        if profile_name and author_tokens[0][:1] and re.search(rf"\b{re.escape(author_tokens[0][:1])}\b", profile_name):
            score += 1.5
    haystack = " ".join(
        [
            clean_text(profile.get("affiliation") or ""),
            clean_text(profile.get("email") or ""),
            " ".join(clean_text(item) for item in profile.get("interests") or []),
        ]
    ).lower()
    for affiliation in affiliations:
        if affiliation_text_matches(haystack, affiliation):
            score += 2.0
    return score


def fetch_google_scholar_profiles_from_search(search_text: str, *, limit: int = 20) -> list[dict[str, Any]]:
    try:
        response = request_with_retries(
            "GET",
            "https://scholar.google.com/scholar",
            params={"hl": "en", "q": search_text},
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://scholar.google.com/",
            },
            timeout=20,
            max_retries=1,
        )
    except RuntimeError as exc:
        if is_google_scholar_block_error(exc):
            raise GoogleScholarBlockedError(google_scholar_block_message()) from exc
        raise
    if is_google_scholar_block_page(response.text, response.url):
        raise GoogleScholarBlockedError(google_scholar_block_message())
    soup = BeautifulSoup(response.text, "html.parser")
    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in soup.select('a[href*="/citations?user="]'):
        profile = google_scholar_search_link_to_profile(link)
        user_id = clean_text(profile.get("user_id") or "")
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        profiles.append(profile)
        if len(profiles) >= limit:
            break
    return profiles


def google_scholar_search_link_to_profile(link: Any) -> dict[str, Any]:
    name = clean_text(link.get_text(" "))
    href = clean_text(link.get("href") or "")
    profile_url = urljoin("https://scholar.google.com", href)
    user_id = google_scholar_user_id(profile_url)
    result = link.find_parent(class_="gs_r")
    context = ""
    if result:
        context = clean_text(
            (result.select_one(".gs_a").get_text(" ") if result.select_one(".gs_a") else "")
            or (result.select_one(".gs_rs").get_text(" ") if result.select_one(".gs_rs") else "")
            or result.get_text(" ")
        )
    return {
        "candidate_type": "scholar-profile",
        "name": name,
        "affiliation": context,
        "email": "",
        "cited_by": "",
        "interests": [],
        "url": profile_url,
        "user_id": user_id,
    }


def google_scholar_author_row_to_profile(row: Any) -> dict[str, Any]:
    link = row.select_one(".gs_ai_name a")
    name = clean_text(link.get_text(" ") if link else row.select_one(".gs_ai_name").get_text(" ") if row.select_one(".gs_ai_name") else "")
    href = clean_text(link.get("href") if link else "")
    profile_url = urljoin("https://scholar.google.com", href) if href else ""
    user_id = google_scholar_user_id(profile_url)
    affiliation = clean_text(row.select_one(".gs_ai_aff").get_text(" ") if row.select_one(".gs_ai_aff") else "")
    email = clean_text(row.select_one(".gs_ai_eml").get_text(" ") if row.select_one(".gs_ai_eml") else "")
    cited_by = clean_text(row.select_one(".gs_ai_cby").get_text(" ") if row.select_one(".gs_ai_cby") else "")
    interests = [clean_text(item.get_text(" ")) for item in row.select(".gs_ai_one_int")]
    return {
        "candidate_type": "scholar-profile",
        "name": name,
        "affiliation": affiliation,
        "email": email,
        "cited_by": cited_by,
        "interests": [item for item in interests if item],
        "url": profile_url,
        "user_id": user_id,
    }


def fetch_google_scholar_profile_publications(profile_url: str, *, limit: int = 500) -> list[dict[str, Any]]:
    return fetch_google_scholar_profile_payload(profile_url, limit=limit)["candidates"]


def fetch_google_scholar_profile_payload(profile_url: str, *, limit: int = 500) -> dict[str, Any]:
    user_id = google_scholar_user_id(profile_url)
    if not user_id:
        raise ValueError("Paste a Google Scholar profile URL that contains a user id")
    page_size = 50
    candidates: list[dict[str, Any]] = []
    profile: dict[str, Any] = {
        "candidate_type": "scholar-profile",
        "name": "",
        "affiliation": "",
        "email": "",
        "cited_by": "",
        "interests": [],
        "url": f"https://scholar.google.com/citations?user={quote(user_id)}&hl=en",
        "user_id": user_id,
        "avatar_url": "",
    }
    seen: set[str] = set()
    for start in range(0, limit, page_size):
        if start:
            time.sleep(1.2)
        try:
            response = request_with_retries(
                "GET",
                "https://scholar.google.com/citations",
                params={"user": user_id, "hl": "en", "cstart": start, "pagesize": min(page_size, limit - start)},
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Referer": "https://scholar.google.com/",
                },
                timeout=20,
                max_retries=1,
            )
        except RuntimeError as exc:
            if is_google_scholar_block_error(exc):
                raise GoogleScholarBlockedError(google_scholar_block_message()) from exc
            raise
        html = response.text
        if is_google_scholar_block_page(html, response.url):
            raise GoogleScholarBlockedError(google_scholar_block_message())
        soup = BeautifulSoup(html, "html.parser")
        if start == 0:
            profile.update(google_scholar_profile_page_metadata(soup, response.url, user_id))
        rows = soup.select("tr.gsc_a_tr")
        if not rows:
            if start == 0:
                raise RuntimeError("No publication rows were found on this Scholar profile")
            break
        before = len(candidates)
        for row in rows:
            candidate = google_scholar_row_to_publication(row)
            if not candidate:
                continue
            paper = candidate["paper"]
            key = "|".join(
                [
                    clean_text(paper.get("title") or "").lower(),
                    clean_text(paper.get("journal") or "").lower(),
                    clean_text(paper.get("publication_date") or ""),
                ]
            )
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit or len(rows) < page_size or len(candidates) == before:
            break
    return {"profile": profile, "candidates": candidates}


def google_scholar_profile_page_metadata(soup: BeautifulSoup, page_url: str, user_id: str) -> dict[str, Any]:
    name = clean_text(soup.select_one("#gsc_prf_in").get_text(" ") if soup.select_one("#gsc_prf_in") else "")
    affiliation = clean_text(soup.select_one(".gsc_prf_il").get_text(" ") if soup.select_one(".gsc_prf_il") else "")
    email = ""
    cited_by = ""
    interests = [clean_text(item.get_text(" ")) for item in soup.select("#gsc_prf_int a, .gsc_prf_ila")]
    for line in [clean_text(item.get_text(" ")) for item in soup.select(".gsc_prf_il")]:
        if "@" in line or "verified email" in line.lower():
            email = line
        if "cited by" in line.lower():
            cited_by = line
    avatar_url = google_scholar_profile_avatar_url(soup, page_url)
    return {
        "candidate_type": "scholar-profile",
        "name": name,
        "affiliation": affiliation,
        "email": email,
        "cited_by": cited_by,
        "interests": [item for item in interests if item],
        "url": f"https://scholar.google.com/citations?user={quote(user_id)}&hl=en",
        "user_id": user_id,
        "avatar_url": avatar_url,
    }


def google_scholar_profile_avatar_url(soup: BeautifulSoup, page_url: str) -> str:
    for selector in ["#gsc_prf_pup-img", "#gsc_prf_pu img", ".gsc_prf_pu img", "img[src*='citations?view_op']"]:
        node = soup.select_one(selector)
        if not node:
            continue
        src = clean_text(node.get("src") or "")
        if src:
            return urljoin(page_url or "https://scholar.google.com", src)
        style = clean_text(node.get("style") or "")
        match = re.search(r"url\((['\"]?)(.*?)\1\)", style)
        if match:
            return urljoin(page_url or "https://scholar.google.com", clean_text(match.group(2)))
    return ""


def is_google_scholar_block_error(error: Exception) -> bool:
    text = str(error).lower()
    return "too many requests" in text or "sorry/index" in text or "google.com/sorry" in text


def is_google_scholar_block_page(html: str, url: str = "") -> bool:
    text = f"{url}\n{html[:5000]}".lower()
    return (
        "google.com/sorry" in text
        or "/sorry/index" in text
        or "unusual traffic" in text
        or "recaptcha" in text
    )


def google_scholar_block_message() -> str:
    return (
        "Google Scholar is temporarily blocking automated profile import. "
        "Wait a while before trying again, or open the Scholar profile in your browser first; "
        "the app will not keep retrying because that usually extends the block."
    )


def resolve_google_scholar_candidate_to_identifier(candidate: dict[str, Any]) -> dict[str, Any] | None:
    doi_candidate = resolve_google_scholar_candidate_to_doi(candidate)
    if doi_candidate:
        return doi_candidate
    return resolve_google_scholar_candidate_to_arxiv(candidate)


def resolve_google_scholar_candidate_to_doi(candidate: dict[str, Any]) -> dict[str, Any] | None:
    paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else candidate
    title = clean_text(paper.get("title") or "")
    year = clean_text(paper.get("publication_date") or "")
    if not title:
        return None
    queries = [scholar_bibliographic_query(candidate), title]
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, query in enumerate(query for query in queries if query):
        kind = "bibliographic" if index == 0 and query != title else "title"
        try:
            candidates = search_crossref_publications(query, kind=kind, rows=30, timeout=14, max_retries=2)
        except Exception:
            continue
        for result in candidates:
            key = clean_text(result.get("doi") or result.get("paper_id") or "")
            if not key or key in seen:
                continue
            if doi_is_likely_data_repository(result.get("doi") or ""):
                continue
            seen.add(key)
            results.append(result)
    if not results:
        return None
    scored: list[tuple[float, dict[str, Any]]] = []
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    scholar_journal = clean_text(paper.get("journal") or raw.get("venue") or "")
    scholar_journal_tokens = title_tokens(scholar_journal)
    for result in results:
        doi = clean_text(result.get("doi") or "")
        if not doi or doi_is_likely_data_repository(doi):
            continue
        result_title = clean_text(result.get("title") or "")
        score = title_similarity(title, result_title)
        result_journal_tokens = title_tokens(result.get("journal") or "")
        if scholar_journal_tokens and result_journal_tokens and scholar_journal_tokens & result_journal_tokens:
            score += 0.04
        result_year = publication_year(result)
        if year and result_year:
            if year[:4] == result_year[:4]:
                score += 0.04
            else:
                score -= 0.12
        scored.append((score, result))
    if not scored:
        return None
    score, result = max(scored, key=lambda item: item[0])
    return result if score >= 0.76 else None


def resolve_google_scholar_candidate_to_arxiv(candidate: dict[str, Any]) -> dict[str, Any] | None:
    paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else candidate
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else paper.get("raw") if isinstance(paper.get("raw"), dict) else {}
    title = clean_text(paper.get("title") or "")
    year = clean_text(paper.get("publication_date") or raw.get("year") or "")
    direct_candidates = [
        paper.get("url"),
        paper.get("landing_url"),
        paper.get("pdf_url"),
        raw.get("url"),
        raw.get("venue"),
        title,
    ]
    for value in direct_candidates:
        arxiv_id = normalize_arxiv_identifier(str(value or ""))
        if arxiv_id:
            return publication_metrics_metadata_from_arxiv_id(arxiv_id, timeout=14, max_retries=1)
    if not title:
        return None
    fields = "paperId,externalIds,title,year,venue,citationCount,url"
    try:
        response = request_with_retries(
            "GET",
            "https://api.semanticscholar.org/graph/v1/paper/search",
            params={"query": title, "limit": 5, "fields": fields},
            timeout=14,
            max_retries=1,
        )
    except Exception:
        return None
    scored: list[tuple[float, str]] = []
    for item in response.json().get("data") or []:
        if not isinstance(item, dict):
            continue
        external_ids = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
        arxiv_id = normalize_arxiv_identifier(str(external_ids.get("ArXiv") or external_ids.get("arXiv") or external_ids.get("ARXIV") or ""))
        if not arxiv_id:
            continue
        score = title_similarity(title, clean_text(item.get("title") or ""))
        item_year = clean_text(str(item.get("year") or ""))
        if year and item_year:
            if year[:4] == item_year[:4]:
                score += 0.04
            else:
                score -= 0.10
        scored.append((score, arxiv_id))
    if not scored:
        return None
    score, arxiv_id = max(scored, key=lambda item: item[0])
    if score < 0.78:
        return None
    return publication_metrics_metadata_from_arxiv_id(arxiv_id, timeout=14, max_retries=1)


def scholar_bibliographic_query(candidate: dict[str, Any]) -> str:
    paper = candidate.get("paper") if isinstance(candidate.get("paper"), dict) else candidate
    raw = candidate.get("raw") if isinstance(candidate.get("raw"), dict) else {}
    authors = raw.get("authors") if isinstance(raw.get("authors"), list) else []
    parts = [
        clean_text(paper.get("title") or ""),
        " ".join(clean_text(author) for author in authors[:3] if clean_text(author)),
        clean_text(raw.get("venue") or paper.get("journal") or ""),
        clean_text(paper.get("publication_date") or raw.get("year") or ""),
    ]
    return " ".join(part for part in parts if part)


def title_similarity(left: str, right: str) -> float:
    left_tokens = title_tokens(left)
    right_tokens = title_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    return (2 * overlap) / (len(left_tokens) + len(right_tokens))


def title_tokens(value: str) -> set[str]:
    stop_words = {"a", "an", "and", "for", "in", "of", "on", "the", "to", "with"}
    return {
        token
        for token in re.findall(r"[a-z0-9]+", clean_text(value).lower())
        if len(token) > 1 and token not in stop_words
    }


def google_scholar_user_id(profile_url: str) -> str:
    parsed = urlparse(profile_url)
    host = parsed.netloc.lower()
    if "scholar.google." not in host:
        return ""
    query = parse_qs(parsed.query)
    return clean_text((query.get("user") or [""])[0])


def google_scholar_row_to_publication(row: Any) -> dict[str, Any] | None:
    title_el = row.select_one("a.gsc_a_at")
    title = clean_text(title_el.get_text(" ") if title_el else "")
    if not title:
        return None
    detail_lines = [clean_text(item.get_text(" ")) for item in row.select(".gs_gray")]
    detail_lines = [line for line in detail_lines if line]
    year = clean_text(row.select_one(".gsc_a_y span").get_text(" ") if row.select_one(".gsc_a_y span") else "")
    venue = detail_lines[1] if len(detail_lines) > 1 else (detail_lines[0] if detail_lines else "")
    venue_parts = google_scholar_venue_parts(venue)
    journal = venue_parts.get("journal") or google_scholar_journal_from_venue(venue)
    href = clean_text(title_el.get("href") if title_el else "")
    url = urljoin("https://scholar.google.com", href) if href else ""
    paper = {
        "title": title,
        "journal": journal or "Unknown Journal",
        "publication_date": year,
        "url": url,
        "landing_url": url,
        "source": "google-scholar",
        "type": "scholar-profile-item",
        "type_crossref": "scholar-profile-item",
        "raw": {
            "source": "google-scholar",
            "authors": google_scholar_author_names(detail_lines[0] if detail_lines else ""),
            "venue": venue,
            "volume": venue_parts.get("volume") or "",
            "page": venue_parts.get("page") or "",
            "year": year,
            "url": url,
        },
    }
    paper["paper_id"] = paper_id_from_publication("", title, paper["journal"], year)
    return publication_candidate_to_api(paper)


def google_scholar_journal_from_venue(venue: str) -> str:
    text = clean_text(venue)
    if not text:
        return ""
    return re.split(r"\s{2,}|,\s*(?:vol\.?\s*)?\d|\s+\d+\s*(?:\(|,|$)", text, maxsplit=1, flags=re.I)[0].strip(" ,")


def google_scholar_venue_parts(venue: str) -> dict[str, str]:
    text = clean_text(venue)
    if not text:
        return {}
    match = re.match(
        r"^(?P<journal>.+?)\s+(?P<volume>\d+[A-Za-z]?)\s*(?:\([^)]*\))?\s*,\s*(?P<page>[A-Za-z]?\d+(?:[-–]\d+)?)",
        text,
    )
    if not match:
        return {"journal": google_scholar_journal_from_venue(text)}
    return {
        "journal": clean_text(match.group("journal")),
        "volume": clean_text(match.group("volume")),
        "page": clean_text(match.group("page")).replace("–", "-"),
    }


def google_scholar_author_names(value: str) -> list[str]:
    return [name for name in [clean_author_name(part) for part in re.split(r"\s*(?:,|，|、|;|；)\s*", value)] if name]


def first_crossref_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return clean_text(value[0])
    return clean_text(value)


def looks_like_doi(value: str) -> bool:
    return bool(re.search(r"\b10\.\d{4,9}/\S+", value, flags=re.I))


def doi_is_likely_data_repository(value: str) -> bool:
    doi = normalize_publication_doi(value)
    if not doi:
        return False
    repository_patterns = [
        r"^10\.5281/zenodo\b",
        r"^10\.5281/",
        r"^10\.6084/m9\.figshare\b",
        r"^10\.5061/dryad\b",
        r"^10\.17605/osf\.io\b",
        r"^10\.17632/",
    ]
    return any(re.search(pattern, doi, flags=re.I) for pattern in repository_patterns)


def doi_is_arxiv_preprint_doi(value: str) -> bool:
    doi = normalize_publication_doi(value)
    return bool(re.match(r"^10\.48550/arxiv[.:/]", doi, flags=re.I))


def doi_is_likely_published_version(value: str) -> bool:
    doi = normalize_publication_doi(value)
    return bool(
        doi
        and looks_like_doi(doi)
        and not doi_is_likely_data_repository(doi)
        and not doi_is_arxiv_preprint_doi(doi)
    )


def openalex_item_is_likely_data_repository(item: dict[str, Any]) -> bool:
    item_type = clean_text(item.get("type") or item.get("type_crossref") or "").lower()
    if item_type in {"dataset", "data-set", "data"}:
        return True
    doi = normalize_publication_doi(clean_text(item.get("doi") or ""))
    if doi_is_likely_data_repository(doi):
        return True
    primary = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
    source = primary.get("source") if isinstance(primary.get("source"), dict) else {}
    haystack = " ".join(
        clean_text(str(value)).lower()
        for value in [
            item.get("doi"),
            item.get("id"),
            item.get("landing_page_url"),
            primary.get("landing_page_url"),
            source.get("display_name"),
            source.get("host_organization_name"),
        ]
        if value
    )
    return any(name in haystack for name in ["zenodo", "figshare", "dryad", "osf.io", "mendeley data"])


def normalize_publication_doi(value: str) -> str:
    doi = clean_text(value)
    doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
    match = re.search(r"10\.\d{4,9}/\S+", doi, flags=re.I)
    doi = match.group(0) if match else doi
    return doi.strip().rstrip(".,;").lower()


def normalize_arxiv_identifier(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ""
    text = unquote(text).strip().strip("<>")
    text = re.sub(r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf|html)/", "", text, flags=re.I)
    text = re.sub(r"\.pdf(?:[?#].*)?$", "", text, flags=re.I)
    text = re.sub(r"^arxiv\s*:\s*", "", text, flags=re.I)
    text = text.strip().strip(".,;")
    old_style = re.search(r"\b([a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?\b", text, flags=re.I)
    if old_style:
        return strip_arxiv_version(old_style.group(1)).lower()
    new_style = re.search(r"\b(\d{4}\.\d{4,5})(?:v\d+)?\b", text, flags=re.I)
    return strip_arxiv_version(new_style.group(1)).lower() if new_style else ""


def looks_like_arxiv_identifier(value: str) -> bool:
    return bool(normalize_arxiv_identifier(value))


def arxiv_identifier_for_paper(paper: dict[str, Any]) -> str:
    raw = parse_raw_json(paper)
    preprint = raw.get("preprint") if isinstance(raw.get("preprint"), dict) else {}
    versions = raw.get("citation_versions") if isinstance(raw.get("citation_versions"), dict) else {}
    preprint_version = versions.get("preprint") if isinstance(versions.get("preprint"), dict) else {}
    candidates = [
        preprint.get("arxiv_id"),
        preprint.get("versioned_arxiv_id"),
        preprint_version.get("arxiv_id"),
        raw.get("arxiv_id"),
        raw.get("versioned_arxiv_id"),
        raw.get("eprint"),
        raw.get("arxiv"),
        paper.get("preprint_id"),
        paper.get("url"),
        paper.get("landing_url"),
        paper.get("pdf_url"),
    ]
    semantic = parse_semantic_scholar_json(paper)
    external_ids = semantic.get("externalIds") if isinstance(semantic.get("externalIds"), dict) else {}
    if isinstance(external_ids, dict):
        candidates.extend([external_ids.get("ArXiv"), external_ids.get("arXiv"), external_ids.get("ARXIV")])
    for candidate in candidates:
        identifier = normalize_arxiv_identifier(str(candidate or ""))
        if identifier:
            return identifier
    raw_identifier = arxiv_identifier_from_raw_values(raw)
    if raw_identifier:
        return raw_identifier
    if (paper.get("journal") or "").lower() == ARXIV_JOURNAL_NAME.lower():
        paper_id = clean_text(paper.get("paper_id") or "")
        if paper_id.startswith("arxiv_"):
            identifier = normalize_arxiv_identifier(paper_id.removeprefix("arxiv_").replace("_", "."))
            if identifier:
                return identifier
    return ""


def arxiv_identifier_from_raw_values(value: Any, *, depth: int = 0) -> str:
    if depth > 5:
        return ""
    if isinstance(value, str):
        return normalize_arxiv_identifier(value) if "arxiv" in value.lower() else ""
    if isinstance(value, dict):
        priority_keys = ["arxiv", "arxiv_id", "versioned_arxiv_id", "eprint", "externalIds", "ids", "url", "landing_page_url", "pdf_url"]
        for key in priority_keys:
            if key in value:
                identifier = arxiv_identifier_from_raw_values(value.get(key), depth=depth + 1)
                if identifier:
                    return identifier
        for item in value.values():
            identifier = arxiv_identifier_from_raw_values(item, depth=depth + 1)
            if identifier:
                return identifier
    if isinstance(value, list):
        for item in value:
            identifier = arxiv_identifier_from_raw_values(item, depth=depth + 1)
            if identifier:
                return identifier
    return ""


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
    journal = display_journal_name(paper) or "Unknown Journal"
    preprint_id = preprint_identifier(paper)
    if preprint_id and journal.lower() == ARXIV_JOURNAL_NAME.lower():
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


def display_journal_name(paper: dict[str, Any]) -> str:
    return journal_name_for_doi(paper.get("journal") or "", clean_text(paper.get("doi") or ""))


def citation_metrics(paper: dict[str, Any]) -> dict[str, Any]:
    raw = parse_raw_json(paper)
    semantic = parse_semantic_scholar_json(paper)
    sources: dict[str, Any] = {}
    published_sources: dict[str, Any] = {}
    preprint_sources: dict[str, Any] = {}
    openalex_by_year: list[dict[str, int]] = []
    openalex_count: int | None = None
    if "cited_by_count" in raw or raw.get("counts_by_year"):
        openalex_count = int_or_none(raw.get("cited_by_count"))
        for item in raw.get("counts_by_year") or []:
            if not isinstance(item, dict):
                continue
            year = int_or_none(item.get("year"))
            count = int_or_none(item.get("cited_by_count", item.get("works_count")))
            if year is None or count is None:
                continue
            openalex_by_year.append({"year": year, "count": count})
        sources["openalex"] = {
            "count": openalex_count,
            "by_year": sorted(openalex_by_year, key=lambda entry: entry["year"]),
        }
        published_sources["openalex"] = sources["openalex"]
    semantic_count = int_or_none(semantic.get("citationCount"))
    semantic_influential = int_or_none(semantic.get("influentialCitationCount"))
    if semantic:
        sources["semantic_scholar"] = {
            "count": semantic_count,
            "influential_count": semantic_influential,
            "paper_id": semantic.get("paperId") or "",
            "url": semantic.get("url") or "",
        }
        published_sources["semantic_scholar"] = sources["semantic_scholar"]
    crossref_count = int_or_none(raw.get("is-referenced-by-count"))
    if crossref_count is not None:
        sources["crossref"] = {"count": crossref_count}
        published_sources["crossref"] = sources["crossref"]
    ads_raw = raw.get("ads") if isinstance(raw.get("ads"), dict) else {}
    ads_count = int_or_none(ads_raw.get("citation_count"))
    if ads_raw:
        sources["ads"] = {
            "count": ads_count,
            "bibcode": ads_raw.get("bibcode") or "",
            "url": f"https://ui.adsabs.harvard.edu/abs/{quote(clean_text(ads_raw.get('bibcode') or ''), safe='')}/abstract" if clean_text(ads_raw.get("bibcode") or "") else "",
        }
        if ads_count is not None:
            published_sources["ads"] = sources["ads"]
    versions = raw.get("citation_versions") if isinstance(raw.get("citation_versions"), dict) else {}
    preprint = versions.get("preprint") if isinstance(versions.get("preprint"), dict) else {}
    preprint_source_raw = preprint.get("sources") if isinstance(preprint.get("sources"), dict) else {}
    preprint_semantic = preprint_source_raw.get("semantic_scholar") if isinstance(preprint_source_raw.get("semantic_scholar"), dict) else {}
    if preprint_semantic:
        preprint_sources["semantic_scholar"] = {
            "count": int_or_none(preprint_semantic.get("citationCount")),
            "influential_count": int_or_none(preprint_semantic.get("influentialCitationCount")),
            "paper_id": preprint_semantic.get("paperId") or "",
            "url": preprint_semantic.get("url") or "",
        }
    preprint_openalex = preprint_source_raw.get("openalex") if isinstance(preprint_source_raw.get("openalex"), dict) else {}
    if preprint_openalex:
        preprint_sources["openalex"] = {"count": int_or_none(preprint_openalex.get("cited_by_count"))}
    semantic_cluster_count = semantic_count
    semantic_preprint_merged = semantic_records_look_merged(semantic, preprint_semantic, preprint.get("arxiv_id") or raw.get("arxiv_id") or "")
    if preprint_semantic and not semantic_preprint_merged:
        preprint_semantic_count = int_or_none(preprint_semantic.get("citationCount"))
        if preprint_semantic_count is not None:
            semantic_cluster_count = max(semantic_cluster_count or 0, preprint_semantic_count)
    published_count = max(
        [
            value
            for value in [
                int_or_none(published_sources.get("openalex", {}).get("count")),
                int_or_none(published_sources.get("crossref", {}).get("count")),
                int_or_none(published_sources.get("ads", {}).get("count")),
            ]
            if value is not None
        ],
        default=None,
    )
    preprint_count = max(
        [
            value
            for value in [
                None if semantic_preprint_merged else int_or_none(preprint_sources.get("semantic_scholar", {}).get("count")),
                int_or_none(preprint_sources.get("openalex", {}).get("count")),
            ]
            if value is not None
        ],
        default=None,
    )
    if published_count is None and preprint_count is None and semantic_cluster_count is None:
        primary_count = None
    else:
        split_total = (published_count or 0) + (preprint_count or 0)
        primary_count = max(split_total, semantic_cluster_count or 0)
    primary_source = "Merged" if preprint_count is not None or semantic_cluster_count is not None else ""
    if not primary_source:
        for source_key, label in [("openalex", "OpenAlex"), ("semantic_scholar", "Semantic Scholar"), ("crossref", "Crossref"), ("ads", "ADS")]:
            value = sources.get(source_key, {}).get("count")
            if value is not None:
                primary_source = label
                break
    return {
        "source": primary_source,
        "count": primary_count,
        "by_year": sources.get("openalex", {}).get("by_year", []),
        "primary_source": primary_source,
        "sources": sources,
        "versions": {
            "published": {"count": published_count, "sources": published_sources},
            "preprint": {
                "count": preprint_count,
                "sources": preprint_sources,
                "arxiv_id": preprint.get("arxiv_id") or raw.get("arxiv_id") or "",
                "semantic_merged": semantic_preprint_merged,
            },
            "semantic_cluster": {"count": semantic_cluster_count, "merged_preprint": semantic_preprint_merged},
        },
    }


def semantic_records_look_merged(semantic: dict[str, Any], preprint_semantic: dict[str, Any], arxiv_id: str = "") -> bool:
    if not semantic or not preprint_semantic:
        return False
    if clean_text(semantic.get("paperId") or "") and clean_text(semantic.get("paperId") or "") == clean_text(preprint_semantic.get("paperId") or ""):
        return True
    if clean_text(str(semantic.get("corpusId") or "")) and clean_text(str(semantic.get("corpusId") or "")) == clean_text(str(preprint_semantic.get("corpusId") or "")):
        return True
    external_ids = semantic.get("externalIds") if isinstance(semantic.get("externalIds"), dict) else {}
    semantic_arxiv = normalize_arxiv_identifier(str(external_ids.get("ArXiv") or external_ids.get("arXiv") or external_ids.get("ARXIV") or ""))
    return bool(semantic_arxiv and arxiv_id and semantic_arxiv == normalize_arxiv_identifier(arxiv_id))


def semantic_scholar_summary(paper: dict[str, Any]) -> dict[str, Any]:
    raw = parse_semantic_scholar_json(paper)
    if not raw:
        return {}
    tldr = raw.get("tldr") if isinstance(raw.get("tldr"), dict) else {}
    journal = raw.get("journal") if isinstance(raw.get("journal"), dict) else {}
    external_ids = raw.get("externalIds") if isinstance(raw.get("externalIds"), dict) else {}
    open_access_pdf = raw.get("openAccessPdf") if isinstance(raw.get("openAccessPdf"), dict) else {}
    authors = raw.get("authors") if isinstance(raw.get("authors"), list) else []
    fields = raw.get("fieldsOfStudy") if isinstance(raw.get("fieldsOfStudy"), list) else []
    s2_fields = raw.get("s2FieldsOfStudy") if isinstance(raw.get("s2FieldsOfStudy"), list) else []
    return {
        "paper_id": raw.get("paperId") or "",
        "corpus_id": raw.get("corpusId") or "",
        "external_ids": {clean_text(str(key)): clean_text(str(value)) for key, value in external_ids.items() if clean_text(str(value))},
        "url": raw.get("url") or "",
        "citation_count": int_or_none(raw.get("citationCount")),
        "influential_citation_count": int_or_none(raw.get("influentialCitationCount")),
        "reference_count": int_or_none(raw.get("referenceCount")),
        "is_open_access": bool(raw.get("isOpenAccess")),
        "open_access_pdf_url": clean_text(open_access_pdf.get("url") or ""),
        "authors": [
            clean_text(item.get("name") or "")
            for item in authors
            if isinstance(item, dict) and clean_text(item.get("name") or "")
        ],
        "fields_of_study": [clean_text(str(value)) for value in fields if clean_text(str(value))],
        "s2_fields": [
            clean_text(item.get("category") or item.get("source") or "")
            for item in s2_fields
            if isinstance(item, dict) and clean_text(item.get("category") or item.get("source") or "")
        ],
        "publication_types": [clean_text(str(value)) for value in (raw.get("publicationTypes") or []) if clean_text(str(value))],
        "tldr": clean_text(tldr.get("text") or ""),
        "venue": clean_text(raw.get("venue") or ""),
        "year": clean_text(str(raw.get("year") or "")),
        "journal_name": clean_text(journal.get("name") or ""),
        "enriched_at": paper.get("semantic_scholar_enriched_at") or "",
    }


def pubmed_summary(paper: dict[str, Any]) -> dict[str, Any]:
    raw = parse_raw_json(paper)
    pubmed = raw.get("pubmed") if isinstance(raw.get("pubmed"), dict) else {}
    if not pubmed:
        return {}
    mesh_values: list[str] = []
    for item in pubmed.get("mesh") or []:
        if not isinstance(item, dict):
            continue
        descriptor = clean_text(item.get("descriptor") or "")
        if descriptor:
            mesh_values.append(descriptor)
    author_affiliations = []
    for index, item in enumerate(pubmed.get("author_affiliations") or []):
        if not isinstance(item, dict):
            continue
        affiliations = [clean_text(str(value)) for value in item.get("affiliations") or [] if clean_text(str(value))]
        roles = pubmed_author_entry_roles(item, index=index)
        author_affiliations.append({
            "name": clean_text(item.get("name") or ""),
            "affiliations": affiliations,
            "roles": {
                "first_author": bool(roles.get("first_author")),
                "co_first_author": bool(roles.get("co_first_author")),
                "corresponding_author": bool(roles.get("corresponding_author")),
                "notes": [clean_text(str(value)) for value in roles.get("notes") or [] if clean_text(str(value))],
            },
        })
    return {
        "pmid": clean_text(pubmed.get("pmid") or raw.get("pmid") or ""),
        "pmcid": clean_text(pubmed.get("pmcid") or raw.get("pmcid") or ""),
        "doi": normalize_publication_doi(str(pubmed.get("doi") or "")),
        "journal_iso_abbrev": clean_text(pubmed.get("journal_iso_abbrev") or ""),
        "issn": clean_text(pubmed.get("issn") or ""),
        "medline_ta": clean_text(pubmed.get("medline_ta") or ""),
        "nlm_unique_id": clean_text(pubmed.get("nlm_unique_id") or ""),
        "publication_types": [clean_text(str(value)) for value in pubmed.get("publication_types") or [] if clean_text(str(value))],
        "keywords": [clean_text(str(value)) for value in pubmed.get("keywords") or [] if clean_text(str(value))],
        "mesh": mesh_values,
        "author_affiliations": author_affiliations,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{quote(clean_text(pubmed.get('pmid') or raw.get('pmid') or ''), safe='')}/" if clean_text(pubmed.get("pmid") or raw.get("pmid") or "") else "",
        "pmc_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{quote(clean_text(pubmed.get('pmcid') or raw.get('pmcid') or ''), safe='')}/" if clean_text(pubmed.get("pmcid") or raw.get("pmcid") or "") else "",
    }


def ads_summary(paper: dict[str, Any]) -> dict[str, Any]:
    raw = parse_raw_json(paper)
    ads = raw.get("ads") if isinstance(raw.get("ads"), dict) else {}
    if not ads:
        return {}
    identifiers = [clean_text(str(value)) for value in ads.get("identifier") or [] if clean_text(str(value))]
    doi_values = [normalize_publication_doi(str(value)) for value in ads.get("doi") or [] if normalize_publication_doi(str(value))]
    titles = [clean_text(str(value)) for value in ads.get("title") or [] if clean_text(str(value))]
    authors = [clean_text(str(value)) for value in ads.get("author") or [] if clean_text(str(value))]
    properties = [clean_text(str(value)) for value in ads.get("property") or [] if clean_text(str(value))]
    links = ads.get("links_data") if isinstance(ads.get("links_data"), list) else []
    return {
        "bibcode": clean_text(ads.get("bibcode") or ""),
        "alternate_bibcode": [clean_text(str(value)) for value in ads.get("alternate_bibcode") or [] if clean_text(str(value))],
        "title": titles[0] if titles else "",
        "publication": clean_text(ads.get("pub") or ""),
        "year": clean_text(str(ads.get("year") or "")),
        "publication_date": clean_text(ads.get("pubdate") or ""),
        "doctype": clean_text(ads.get("doctype") or ""),
        "volume": clean_text(ads.get("volume") or ""),
        "page": clean_text((ads.get("page") or [""])[0] if isinstance(ads.get("page"), list) else ads.get("page") or ""),
        "citation_count": int_or_none(ads.get("citation_count")),
        "read_count": int_or_none(ads.get("read_count")),
        "reference_count": int_or_none(ads.get("reference_count")),
        "doi": doi_values[0] if doi_values else "",
        "identifiers": identifiers,
        "authors": authors,
        "properties": properties,
        "url": f"https://ui.adsabs.harvard.edu/abs/{quote(clean_text(ads.get('bibcode') or ''), safe='')}/abstract" if clean_text(ads.get("bibcode") or "") else "",
        "links": links,
    }


def ads_identifiers_for_paper(paper: dict[str, Any]) -> list[str]:
    identifiers: list[str] = []
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    if doi and looks_like_doi(doi):
        identifiers.append(doi)
    arxiv_id = arxiv_identifier_for_paper(paper)
    if arxiv_id:
        identifiers.extend([arxiv_id, f"arXiv:{arxiv_id}"])
    return list(dict.fromkeys(identifier for identifier in identifiers if identifier))


def refresh_ads_if_possible(
    storage: Storage,
    paper: dict[str, Any] | None,
    *,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    if not paper:
        return paper
    paper_id = clean_text(paper.get("paper_id") or "")
    token = ads_api_token(storage)
    if not paper_id or not token:
        return paper
    record: dict[str, Any] | None = None
    for identifier in ads_identifiers_for_paper(paper):
        try:
            record = fetch_ads_record_by_identifier(identifier, token, timeout=timeout, max_retries=max_retries)
        except Exception:
            record = None
        if record:
            break
    if not record:
        return paper
    raw = parse_raw_json(paper)
    raw["ads"] = record
    ads_dois = [normalize_publication_doi(str(value)) for value in record.get("doi") or [] if normalize_publication_doi(str(value))]
    published_ads_dois = [doi for doi in ads_dois if doi_is_likely_published_version(doi)]
    paper_doi = normalize_publication_doi(str(paper.get("doi") or ""))
    paper_has_published_doi = doi_is_likely_published_version(paper_doi)
    if published_ads_dois and not paper_has_published_doi:
        raw["published_doi"] = published_ads_dois[0]
    updated = storage.update_paper_raw_json(paper_id, raw) or paper
    if published_ads_dois and not paper_has_published_doi:
        try:
            published_doi = published_ads_dois[0]
            published = publication_metrics_metadata_from_doi(published_doi, timeout=timeout, max_retries=1)
            if published:
                merged = attach_arxiv_preprint_metadata(published, updated)
                refreshed = storage.refresh_paper_metadata(paper_id, merge_refreshed_metadata(updated, merged))
                if refreshed:
                    refreshed_raw = parse_raw_json(refreshed)
                    refreshed_raw["ads"] = record
                    updated = storage.update_paper_raw_json(paper_id, refreshed_raw) or refreshed
                    updated = refresh_pubmed_if_possible(storage, updated, doi=published_doi, timeout=timeout, max_retries=1) or updated
        except Exception:
            return updated
    return updated


def merge_refreshed_metadata(existing: dict[str, Any] | None, refreshed: dict[str, Any] | None) -> dict[str, Any]:
    existing = existing or {}
    merged = dict(refreshed or {})
    if clean_text(merged.get("title") or "") and merged.get("source") != "arxiv" and clean_text(merged.get("doi") or ""):
        merged["title"] = normalize_publication_title(merged.get("title") or "")
    if not clean_text(merged.get("abstract") or "") and clean_text(existing.get("abstract") or ""):
        merged["abstract"] = existing.get("abstract") or ""
        merged["abstract_source"] = existing.get("abstract_source") or "existing"
    elif (merged.get("abstract_source") in ("", None, "missing", "unavailable")) and clean_text(existing.get("abstract_source") or ""):
        merged["abstract_source"] = existing.get("abstract_source") or ""
    if not clean_text(merged.get("image_url") or "") and clean_text(existing.get("image_url") or ""):
        merged["image_url"] = existing.get("image_url") or ""
    existing_raw = parse_raw_json(existing)
    refreshed_raw = merged.get("raw") if isinstance(merged.get("raw"), dict) else {}
    for key in ["ads", "arxiv_id", "versioned_arxiv_id", "preprint", "published_doi", "citation_versions", "google_scholar", "crossref", "pubmed", "pmid", "pmcid"]:
        if key not in refreshed_raw and key in existing_raw:
            refreshed_raw[key] = existing_raw[key]
    for key in ["volume", "issue", "page", "article-number", "biblio", "journal-issue"]:
        if _empty_bibliographic_value(refreshed_raw.get(key)) and not _empty_bibliographic_value(existing_raw.get(key)):
            refreshed_raw[key] = existing_raw[key]
    merged["raw"] = refreshed_raw
    return merged


def merge_crossref_bibliographic_raw(raw: dict[str, Any], crossref_raw: dict[str, Any]) -> None:
    if not isinstance(raw, dict) or not isinstance(crossref_raw, dict) or not crossref_raw:
        return
    raw["crossref"] = crossref_raw
    for key in [
        "volume",
        "issue",
        "page",
        "article-number",
        "biblio",
        "journal-issue",
        "published-print",
        "published-online",
        "published",
        "issued",
        "container-title",
    ]:
        if _empty_bibliographic_value(raw.get(key)) and not _empty_bibliographic_value(crossref_raw.get(key)):
            raw[key] = crossref_raw[key]


def _empty_bibliographic_value(value: Any) -> bool:
    return value in (None, "", [], {})


def build_my_publication_comments_report(publication: dict[str, Any]) -> tuple[str, Path, int]:
    citing_papers = fetch_openalex_citing_papers(
        publication,
        max_pages=COMMENT_REPORT_MAX_OPENALEX_PAGES,
        per_page=COMMENT_REPORT_OPENALEX_PER_PAGE,
    )
    try:
        context_snippets = fetch_semantic_scholar_citation_contexts(publication, limit=COMMENT_REPORT_CONTEXT_LIMIT)
    except Exception:
        context_snippets = []
    content = my_publication_comments_markdown(publication, citing_papers, context_snippets)
    DEFAULT_COMMENT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    slug = safe_slug(citation_label(publication) or publication.get("title") or publication.get("paper_id") or "publication")
    report_path = DEFAULT_COMMENT_REPORT_DIR / f"{slug}_comments.md"
    report_path.write_text(content, encoding="utf-8")
    return content, report_path, len(citing_papers)


def fetch_openalex_citing_papers(
    paper: dict[str, Any],
    *,
    max_pages: int = 10,
    per_page: int = 100,
) -> list[dict[str, Any]]:
    work_id = openalex_work_id_for_paper(paper)
    if not work_id:
        raise RuntimeError("No OpenAlex work id found for this paper. DOI metadata may need to be refreshed first.")
    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = "*"
    for _ in range(max(1, int(max_pages))):
        response = request_with_retries(
            "GET",
            "https://api.openalex.org/works",
            params={
                "filter": f"cites:{work_id}",
                "per-page": max(1, min(200, int(per_page))),
                "cursor": cursor,
                "sort": "publication_date:desc",
                "mailto": "your_email@example.com",
            },
            timeout=30,
            max_retries=3,
        )
        data = response.json()
        results = data.get("results") or []
        for item in results:
            if not isinstance(item, dict):
                continue
            normalized = normalize_openalex_item(item, clean_text(((item.get("primary_location") or {}).get("source") or {}).get("display_name")) or "Unknown Journal")
            normalized["raw_json"] = json.dumps(item, ensure_ascii=False)
            key = normalized.get("doi") or normalized.get("paper_id") or clean_text(item.get("id"))
            if key and key not in seen:
                seen.add(key)
                papers.append(normalized)
        next_cursor = data.get("meta", {}).get("next_cursor")
        if not next_cursor or next_cursor == cursor or len(results) < per_page:
            break
        cursor = next_cursor
    return papers


def openalex_work_id_for_paper(paper: dict[str, Any]) -> str:
    raw = parse_raw_json(paper)
    raw_id = clean_text(raw.get("id") if isinstance(raw, dict) else "")
    if raw_id and "openalex.org/" in raw_id:
        return raw_id.rstrip("/").rsplit("/", 1)[-1]
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    if doi:
        try:
            response = request_with_retries(
                "GET",
                f"https://api.openalex.org/works/https://doi.org/{doi}",
                params={"mailto": "your_email@example.com"},
                timeout=20,
                max_retries=3,
            )
            data = response.json()
            work_id = clean_text(data.get("id"))
            if work_id:
                return work_id.rstrip("/").rsplit("/", 1)[-1]
        except Exception:
            pass
    title = clean_text(paper.get("title") or "")
    if title:
        response = request_with_retries(
            "GET",
            "https://api.openalex.org/works",
            params={"search": title, "per-page": 1, "mailto": "your_email@example.com"},
            timeout=20,
            max_retries=3,
        )
        for item in response.json().get("results") or []:
            if isinstance(item, dict) and clean_text(item.get("id")):
                return clean_text(item.get("id")).rstrip("/").rsplit("/", 1)[-1]
    return ""


def semantic_scholar_citation_ref(paper: dict[str, Any]) -> str:
    semantic = parse_semantic_scholar_json(paper)
    semantic_id = clean_text(semantic.get("paperId") or "")
    if semantic_id:
        return semantic_id
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    arxiv_id = arxiv_identifier_for_paper(paper)
    if doi:
        return f"DOI:{doi}"
    if arxiv_id:
        return f"ARXIV:{arxiv_id}"
    return ""


def fetch_semantic_scholar_citation_contexts(paper: dict[str, Any], *, limit: int = 12) -> list[dict[str, Any]]:
    paper_ref = semantic_scholar_citation_ref(paper)
    if not paper_ref:
        return []
    doi = normalize_publication_doi(str(paper.get("doi") or ""))
    response = request_with_retries(
        "GET",
        f"https://api.semanticscholar.org/graph/v1/paper/{quote(paper_ref, safe='')}/citations",
        params={
            "fields": "contexts,intents,isInfluential,citingPaper.title,citingPaper.year,citingPaper.venue,citingPaper.url,citingPaper.externalIds,citingPaper.authors,citingPaper.citationCount",
            "limit": 100,
        },
        timeout=30,
        max_retries=2,
    )
    snippets: list[dict[str, Any]] = []
    for item in response.json().get("data") or []:
        if not isinstance(item, dict):
            continue
        citing = item.get("citingPaper") or {}
        contexts = item.get("contexts") or []
        if not isinstance(contexts, list):
            continue
        title = clean_text(citing.get("title") or "")
        venue = clean_text(citing.get("venue") or "")
        year = clean_text(str(citing.get("year") or ""))
        url = clean_text(citing.get("url") or "")
        citing_authors = citing.get("authors") if isinstance(citing.get("authors"), list) else []
        citing_last_author = semantic_scholar_last_author(citing_authors)
        intents = item.get("intents") if isinstance(item.get("intents"), list) else []
        for context in contexts:
            text = trim_citation_context(clean_text(str(context or "")))
            if not text:
                continue
            snippets.append(
                {
                    "target_title": clean_text(paper.get("title") or ""),
                    "target_doi": doi,
                    "context": text,
                    "citing_title": title or "Untitled citing paper",
                    "citing_venue": venue,
                    "citing_year": year,
                    "citing_url": url,
                    "citing_last_author": citing_last_author,
                    "citing_citation_count": int_or_none(citing.get("citationCount")) or 0,
                    "intents": [clean_text(str(value)) for value in intents if clean_text(str(value))],
                    "is_influential": bool(item.get("isInfluential")),
                    "source": "Semantic Scholar citation contexts",
                }
            )
            if len(snippets) >= limit:
                return snippets
    return snippets


def fetch_semantic_scholar_influential_citations(paper: dict[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    paper_ref = semantic_scholar_citation_ref(paper)
    if not paper_ref:
        return []
    citations: list[dict[str, Any]] = []
    offset = 0
    fields = (
        "contexts,intents,isInfluential,"
        "citingPaper.paperId,citingPaper.title,citingPaper.year,citingPaper.venue,citingPaper.url,"
        "citingPaper.externalIds,citingPaper.authors,citingPaper.citationCount,citingPaper.influentialCitationCount"
    )
    while len(citations) < limit and offset < 1000:
        response = request_with_retries(
            "GET",
            f"https://api.semanticscholar.org/graph/v1/paper/{quote(paper_ref, safe='')}/citations",
            params={"fields": fields, "limit": 100, "offset": offset},
            timeout=30,
            max_retries=2,
        )
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(data, list) or not data:
            break
        for item in data:
            if not isinstance(item, dict) or not item.get("isInfluential"):
                continue
            citing = item.get("citingPaper") if isinstance(item.get("citingPaper"), dict) else {}
            contexts = [
                trim_citation_context(clean_text(str(context or "")))
                for context in (item.get("contexts") or [])
                if clean_text(str(context or ""))
            ]
            authors = citing.get("authors") if isinstance(citing.get("authors"), list) else []
            citations.append(
                {
                    "paper_id": clean_text(citing.get("paperId") or ""),
                    "title": clean_text(citing.get("title") or "Untitled citing paper"),
                    "venue": clean_text(citing.get("venue") or ""),
                    "year": clean_text(str(citing.get("year") or "")),
                    "url": clean_text(citing.get("url") or ""),
                    "authors": [
                        clean_text(author.get("name") or "")
                        for author in authors
                        if isinstance(author, dict) and clean_text(author.get("name") or "")
                    ],
                    "citation_count": int_or_none(citing.get("citationCount")) or 0,
                    "influential_citation_count": int_or_none(citing.get("influentialCitationCount")) or 0,
                    "intents": [
                        clean_text(str(value))
                        for value in (item.get("intents") or [])
                        if clean_text(str(value))
                    ],
                    "contexts": contexts[:5],
                }
            )
            if len(citations) >= limit:
                break
        next_offset = payload.get("next") if isinstance(payload, dict) else None
        if isinstance(next_offset, int) and next_offset > offset:
            offset = next_offset
        else:
            offset += len(data)
            if len(data) < 100:
                break
    citations.sort(key=lambda item: (int(item.get("citation_count") or 0), int(item.get("influential_citation_count") or 0)), reverse=True)
    return citations[:limit]


def semantic_scholar_last_author(authors: list[Any]) -> str:
    if not authors:
        return ""
    last = authors[-1]
    if isinstance(last, dict):
        return clean_text(last.get("name") or "")
    return clean_text(str(last))


def trim_citation_context(text: str, *, max_chars: int = 260) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rsplit(" ", 1)[0].rstrip(".,;:") + "..."


POSITIVE_COMMENT_TERMS = [
    ("important", 2),
    ("significant", 2),
    ("key", 2),
    ("central", 2),
    ("crucial", 2),
    ("notable", 2),
    ("elegant", 2),
    ("strong evidence", 3),
    ("direct evidence", 3),
    ("robust", 2),
    ("revealed", 2),
    ("demonstrated", 2),
    ("showed", 1),
    ("established", 3),
    ("enabled", 2),
    ("opened", 2),
]

STRONGEST_COMMENT_TERMS = [
    ("first", 3),
    ("seminal", 5),
    ("landmark", 5),
    ("pioneering", 5),
    ("breakthrough", 5),
    ("major advance", 5),
    ("compelling", 4),
    ("unambiguous", 4),
    ("definitive", 4),
    ("smoking gun", 5),
    ("paradigm", 4),
    ("widely", 2),
    ("opened", 3),
]

CRITICAL_COMMENT_TERMS = [
    ("however", 1),
    ("although", 1),
    ("but", 1),
    ("limitation", 4),
    ("limited", 2),
    ("unclear", 4),
    ("controvers", 4),
    ("debate", 3),
    ("challenge", 3),
    ("question", 3),
    ("not sufficient", 4),
    ("cannot", 3),
    ("failed", 4),
    ("lack", 3),
    ("ambiguous", 4),
    ("inconsistent", 4),
    ("discrep", 4),
    ("not reproduc", 5),
    ("alternative explanation", 5),
    ("caution", 4),
    ("artifact", 5),
    ("spurious", 5),
]


def citation_context_score(text: str, weighted_terms: list[tuple[str, int]]) -> int:
    haystack = clean_text(text).lower()
    return sum(weight for term, weight in weighted_terms if term in haystack)


def ranked_citation_contexts(
    snippets: list[dict[str, Any]],
    *,
    kind: str,
    limit: int = COMMENT_REPORT_HIGHLIGHT_LIMIT,
) -> list[dict[str, Any]]:
    ranked: list[tuple[int, int, int, dict[str, Any]]] = []
    seen: set[str] = set()
    for snippet in snippets:
        context = clean_text(snippet.get("context") or "")
        if not context:
            continue
        key = normalized_title_key(f"{snippet.get('citing_title') or ''} {context}")
        if key in seen:
            continue
        seen.add(key)
        intents = [clean_text(str(value)).lower() for value in snippet.get("intents") or [] if clean_text(str(value))]
        critical_score = citation_context_score(context, CRITICAL_COMMENT_TERMS)
        if kind in {"positive", "strongest"} and critical_score >= 3:
            continue
        if kind == "critical":
            score = critical_score
            min_score = 3
        elif kind == "strongest":
            score = citation_context_score(context, STRONGEST_COMMENT_TERMS) + citation_context_score(context, POSITIVE_COMMENT_TERMS)
            if snippet.get("is_influential"):
                score += 3
            if "result" in intents:
                score += 1
            min_score = 4
        else:
            score = citation_context_score(context, POSITIVE_COMMENT_TERMS)
            if snippet.get("is_influential"):
                score += 1
            if "result" in intents:
                score += 1
            min_score = 2
        if score < min_score:
            continue
        ranked.append((score, int_or_none(snippet.get("citing_citation_count")) or 0, int_or_none(snippet.get("citing_year")) or 0, snippet))
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return [snippet for *_prefix, snippet in ranked[:limit]]


def citation_context_identity(snippet: dict[str, Any]) -> str:
    return normalized_title_key(f"{snippet.get('citing_title') or ''} {snippet.get('context') or ''}")


def citation_context_highlight_markdown(snippets: list[dict[str, Any]]) -> list[str]:
    section_specs = [
        (
            "Most Positive Citation Comments",
            "positive",
            "positive",
            "No clearly positive citation-context sentences were found in the Semantic Scholar contexts fetched for this paper.",
        ),
        (
            "Strongest Praise / Impact Comments",
            "strongest",
            "strongest",
            "No clearly high-praise citation-context sentences were found in the Semantic Scholar contexts fetched for this paper.",
        ),
        (
            "Critical / Cautionary Comments",
            "critical",
            "critical",
            "No clearly critical citation-context sentences were found in the Semantic Scholar contexts fetched for this paper.",
        ),
    ]
    lines = ["## Citation Comment Highlights", ""]
    if not snippets:
        lines.extend([
            "Semantic Scholar did not return citation-context sentences for this paper, so no comment highlights can be ranked.",
            "",
        ])
        return lines
    assigned: dict[str, list[dict[str, Any]]] = {}
    used: set[str] = set()
    for label in ["strongest", "positive", "critical"]:
        assigned[label] = []
        for snippet in ranked_citation_contexts(snippets, kind=label):
            key = citation_context_identity(snippet)
            if not key or key in used:
                continue
            assigned[label].append(snippet)
            used.add(key)
            if len(assigned[label]) >= COMMENT_REPORT_HIGHLIGHT_LIMIT:
                break
    for heading, label, kind, empty_text in section_specs:
        lines.extend([f"### {heading}", ""])
        ranked = assigned.get(kind, [])
        if not ranked:
            lines.extend([empty_text, ""])
            continue
        for index, snippet in enumerate(ranked, start=1):
            lines.extend(citation_context_summary_item(snippet, index=index, label=label))
    return lines


def citation_context_summary_item(snippet: dict[str, Any], *, index: int, label: str) -> list[str]:
    title = clean_text(snippet.get("citing_title") or "Untitled citing paper")
    url = clean_text(snippet.get("citing_url") or "")
    title_text = f"[{title}]({url})" if url else title
    source = " ".join(
        part for part in [
            clean_text(snippet.get("citing_venue") or ""),
            clean_text(snippet.get("citing_year") or ""),
        ]
        if part
    ) or "Unknown source"
    citations = int_or_none(snippet.get("citing_citation_count"))
    lines = [
        f"**{index}. {title_text}**",
        "",
        f"- Last author: {clean_text(snippet.get('citing_last_author') or '') or 'Unavailable'}",
        f"- Source: {source}{f' · citing paper citations: {citations}' if citations is not None else ''}",
        "",
        f"> [{label}] {clean_text(snippet.get('context') or '')}",
        "",
    ]
    return lines


def my_publication_comments_markdown(
    publication: dict[str, Any],
    citing_papers: list[dict[str, Any]],
    context_snippets: list[dict[str, Any]],
) -> str:
    metrics = citation_metrics(publication)
    source_count = metrics.get("count")
    role = my_publication_role_text(publication)
    contexts_by_title = citation_contexts_by_title(context_snippets)
    top_examples = sorted(
        citing_papers,
        key=lambda row: int_or_none(parse_raw_json(row).get("cited_by_count")) or 0,
        reverse=True,
    )[:COMMENT_REPORT_LIST_LIMIT]
    lines = [
        f"# Citation Comments Report",
        "",
        f"## Target Paper",
        "",
        f"- Title: {clean_text(publication.get('title') or 'Untitled')}",
        f"- Journal: {clean_text(publication.get('journal') or 'Unknown Journal')}",
        f"- Date: {clean_text(publication.get('publication_date') or '')}",
        f"- DOI: {clean_text(publication.get('doi') or '') or 'Unavailable'}",
        f"- My role: {role}",
        "",
        "## Scope",
        "",
        (
            "This report lists papers that cite the target paper. When available, colored boxes show citation-context "
            "sentences returned by Semantic Scholar."
        ),
        (
            f"OpenAlex fetches up to {COMMENT_REPORT_MAX_OPENALEX_PAGES * COMMENT_REPORT_OPENALEX_PER_PAGE} citing papers; "
            f"this report lists up to {COMMENT_REPORT_LIST_LIMIT} citing papers sorted by citing-paper citation count. "
            f"Semantic Scholar citation contexts are fetched separately, up to {COMMENT_REPORT_CONTEXT_LIMIT} context sentences."
        ),
        "",
        "## Summary",
        "",
        f"- Citing papers fetched: {len(citing_papers)}",
        f"- Citation-context excerpts fetched: {len(context_snippets)}",
        f"- Citing papers listed below: {len(top_examples)}",
        f"- OpenAlex/Crossref citation count in stored metadata: {source_count if source_count is not None else 'Unavailable'}",
        "",
    ]
    lines.extend(citation_context_highlight_markdown(context_snippets))
    lines.extend(["## Citing Papers", ""])
    if not top_examples:
        lines.append("No citing papers were returned by OpenAlex.")
    for index, paper in enumerate(top_examples, start=1):
        title = clean_text(paper.get("title") or "Untitled")
        url = clean_text(paper.get("url") or paper.get("landing_url") or "")
        title_text = f"[{title}]({url})" if url else title
        contexts = contexts_by_title.get(normalized_title_key(title), [])
        lines.extend(
            [
                f"### {index}. {title_text}",
                "",
                f"- Last author: {last_author_name(paper)}",
                f"- Source: {clean_text(paper.get('journal') or 'Unknown Journal')} {clean_text(paper.get('publication_date') or '')}",
                "",
            ]
        )
        if contexts:
            for snippet in contexts[:3]:
                intent = primary_citation_intent(snippet)
                lines.append(f"> [{intent}] {clean_text(snippet.get('context') or '')}")
                lines.append("")
        else:
            lines.append("> [metadata] Semantic Scholar did not return a direct citation-context sentence for this citing paper.")
            lines.append("")
    remaining_contexts = [
        snippet for snippet in context_snippets
        if normalized_title_key(snippet.get("citing_title") or "") not in {normalized_title_key(paper.get("title") or "") for paper in top_examples}
    ]
    if remaining_contexts:
        lines.extend(["## Citation Contexts Without OpenAlex Match", ""])
        for index, snippet in enumerate(remaining_contexts[:COMMENT_REPORT_UNMATCHED_CONTEXT_LIMIT], start=1):
            title = clean_text(snippet.get("citing_title") or "Untitled citing paper")
            url = clean_text(snippet.get("citing_url") or "")
            title_text = f"[{title}]({url})" if url else title
            lines.extend([
                f"### {index}. {title_text}",
                "",
                f"- Last author: {clean_text(snippet.get('citing_last_author') or '') or 'Unavailable'}",
                f"- Source: {clean_text(snippet.get('citing_venue') or '')} {clean_text(snippet.get('citing_year') or '')}",
                "",
                f"> [{primary_citation_intent(snippet)}] {clean_text(snippet.get('context') or '')}",
                "",
            ])
        if len(remaining_contexts) > COMMENT_REPORT_UNMATCHED_CONTEXT_LIMIT:
            lines.append(f"... {len(remaining_contexts) - COMMENT_REPORT_UNMATCHED_CONTEXT_LIMIT} more unmatched citation contexts not shown.")
            lines.append("")
    return "\n".join(lines).strip() + "\n"


def citation_contexts_by_title(snippets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for snippet in snippets:
        key = normalized_title_key(snippet.get("citing_title") or "")
        if not key:
            continue
        grouped.setdefault(key, []).append(snippet)
    return grouped


def normalized_title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def primary_citation_intent(snippet: dict[str, Any]) -> str:
    intents = [clean_text(str(value)).lower() for value in snippet.get("intents") or [] if clean_text(str(value))]
    if not intents:
        return "context"
    if "methodology" in intents:
        return "methodology"
    if "background" in intents:
        return "background"
    if "result" in intents:
        return "result"
    return intents[0]


def last_author_name(paper: dict[str, Any]) -> str:
    authors = full_author_names(paper)
    return authors[-1] if authors else "Unavailable"


def my_publication_role_text(publication: dict[str, Any]) -> str:
    roles = []
    if publication.get("first_author"):
        roles.append("first / co-first marked")
    if publication.get("corresponding_author"):
        roles.append("corresponding / co-corresponding marked")
    return ", ".join(roles) if roles else "not manually marked"


def count_by_value(key: Any, rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for row in rows:
        value = key(row) if callable(key) else key
        label = clean_text(str(value or "Unknown"))
        counts[label] = counts.get(label, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def count_lines(items: list[tuple[str, int]], *, limit: int | None = None) -> list[str]:
    if not items:
        return ["- None"]
    visible = items[:limit] if limit else items
    lines = [f"- {label}: {count}" for label, count in visible]
    if limit and len(items) > limit:
        lines.append(f"- ... {len(items) - limit} more")
    return lines


def year_range(rows: list[dict[str, Any]]) -> str:
    years = sorted({publication_year(row) for row in rows if publication_year(row)})
    if not years:
        return "Unavailable"
    return years[0] if len(years) == 1 else f"{years[0]}-{years[-1]}"


def classify_citing_themes(rows: list[dict[str, Any]]) -> list[tuple[str, int]]:
    labels = {
        "Background / motivation": ["background", "review", "overview", "introduction", "recent", "progress"],
        "Experimental follow-up": ["experiment", "measurement", "observed", "spectroscopy", "transport", "device"],
        "Theory / modeling": ["theory", "model", "simulation", "calculation", "mechanism", "prediction"],
        "Materials / platform": ["material", "crystal", "film", "heterostructure", "superconductor", "semiconductor"],
        "Method / technique": ["method", "technique", "fabrication", "growth", "microscopy", "probe"],
    }
    counts = {label: 0 for label in labels}
    counts["General citation"] = 0
    for row in rows:
        text = f"{row.get('title') or ''} {row.get('abstract') or ''}".lower()
        matched = False
        for label, terms in labels.items():
            if any(term in text for term in terms):
                counts[label] += 1
                matched = True
        if not matched:
            counts["General citation"] += 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def citation_comment_sentence(target: dict[str, Any], citing: dict[str, Any]) -> str:
    target_terms = important_title_terms(target.get("title") or "")
    text = f"{citing.get('title') or ''} {citing.get('abstract') or ''}".lower()
    matched = [term for term in target_terms if term in text][:5]
    if matched:
        return "This citing paper appears related through: " + ", ".join(matched) + "."
    if citing.get("abstract"):
        return "This citing paper likely uses the target as background or related literature based on available metadata."
    return "Only limited metadata is available, so the citation intent cannot be inferred reliably."


def important_title_terms(title: str) -> list[str]:
    stop = {"the", "and", "for", "with", "from", "into", "onto", "that", "this", "these", "those", "using", "based"}
    return [
        token
        for token in re.findall(r"[a-zA-Z][a-zA-Z0-9+-]{3,}", clean_text(title).lower())
        if token not in stop
    ][:12]


def google_scholar_url(paper: dict[str, Any]) -> str:
    query = paper.get("doi") or arxiv_identifier_for_paper(paper) or paper.get("title") or ""
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
    journal = display_journal_name(paper)
    return {
        "authors": nature_author_text(paper),
        "title": title,
        "journal": journal,
        "volume": paper_volume(paper),
        "pages": paper_page(paper),
        "year": publication_year(paper),
        "doi": clean_text(paper.get("doi") or ""),
        "preprint_id": preprint_identifier(paper),
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
    return authors_from_openalex(raw) or authors_from_crossref(raw) or authors_from_arxiv(raw) or authors_from_datacite(raw) or authors_from_google_scholar(raw)


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
    value = _paper_volume_from_raw(raw)
    if not value and isinstance(raw.get("crossref"), dict):
        value = _paper_volume_from_raw(raw.get("crossref") or {})
    if not value:
        semantic_journal = parse_semantic_scholar_json(paper).get("journal") or {}
        if isinstance(semantic_journal, dict):
            value = clean_text(str(semantic_journal.get("volume") or ""))
    if not value:
        value, _page = aps_volume_page_from_doi(clean_text(str(paper.get("doi") or raw.get("doi") or raw.get("DOI") or "")))
    return clean_text(str(value or ""))


def paper_page(paper: dict[str, Any]) -> str:
    raw = parse_raw_json(paper)
    raw_page = _paper_page_from_raw(raw)
    crossref_raw = raw.get("crossref") if isinstance(raw.get("crossref"), dict) else {}
    crossref_page = _paper_page_from_raw(crossref_raw)
    if crossref_page and (not raw_page or raw_page == clean_text(str(raw.get("issue") or ""))):
        return crossref_page
    if raw_page:
        return raw_page
    semantic_journal = parse_semantic_scholar_json(paper).get("journal") or {}
    if isinstance(semantic_journal, dict):
        semantic_page = clean_text(str(semantic_journal.get("pages") or ""))
        if semantic_page:
            return semantic_page
    _volume, doi_page = aps_volume_page_from_doi(clean_text(str(paper.get("doi") or raw.get("doi") or raw.get("DOI") or "")))
    return doi_page


def _paper_volume_from_raw(raw: dict[str, Any]) -> str:
    journal_issue = raw.get("journal-issue") or {}
    journal_volume = journal_issue.get("journal-volume") if isinstance(journal_issue, dict) else {}
    value = (
        raw.get("volume")
        or (raw.get("biblio") or {}).get("volume")
        or (journal_volume or {}).get("volume")
    )
    return clean_text(str(value or ""))


def _paper_page_from_raw(raw: dict[str, Any]) -> str:
    biblio = raw.get("biblio") or {}
    first_page = clean_text(str(biblio.get("first_page") or biblio.get("first-page") or ""))
    last_page = clean_text(str(biblio.get("last_page") or biblio.get("last-page") or ""))
    biblio_pages = f"{first_page}-{last_page}" if first_page and last_page and first_page != last_page else first_page
    value = raw.get("page") or raw.get("article-number") or biblio_pages
    return clean_text(str(value or ""))


def aps_volume_page_from_doi(doi: str) -> tuple[str, str]:
    normalized = normalize_publication_doi(doi)
    match = re.search(
        r"^10\.1103/(?:physrev(?:[a-z]+)?|physrevlett|physrevx|physrevmaterials|revmodphys)\.(?P<volume>\d+)\.(?P<page>[A-Za-z]?\d[\w.-]*)$",
        normalized,
        flags=re.I,
    )
    if not match:
        return "", ""
    return clean_text(match.group("volume")), clean_text(match.group("page"))


def clear_publication_export_format(export_format: str) -> None:
    PUBLICATION_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    patterns = {
        "docx": ["publication_list_*.docx"],
        "tex": ["publication_list_*.tex"],
        "overleaf": ["publication_list_*_overleaf.zip"],
        "pdf": ["publication_list_*.pdf", "publication_list_*_pdf.tex", "publication_list_*_pdf.aux", "publication_list_*_pdf.log", "publication_list_*_pdf.out"],
    }.get(export_format, [])
    for pattern in patterns:
        for path in PUBLICATION_EXPORT_DIR.glob(pattern):
            if export_format == "tex" and path.name.endswith("_pdf.tex"):
                continue
            if path.is_file() or path.is_symlink():
                path.unlink(missing_ok=True)


def clear_publication_export_dir() -> None:
    PUBLICATION_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    for path in PUBLICATION_EXPORT_DIR.glob("publication_list_*"):
        if path.is_file() or path.is_symlink():
            path.unlink(missing_ok=True)


def open_publication_export_result(path: Path, export_format: str) -> dict[str, str]:
    requested = path.expanduser().resolve()
    if not requested.exists():
        raise FileNotFoundError(str(requested))
    result: dict[str, str] = {"status": "opened", "path": str(requested), "mode": "open"}
    if export_format == "overleaf":
        desktop_copy = copy_publication_export_to_desktop(requested)
        result.update({"status": "copied", "mode": "desktop-copy", "desktop_path": str(desktop_copy)})
        return result
    if requested.suffix.lower() == ".pdf":
        subprocess.run(["open", "-a", "Preview", str(requested)], check=True, capture_output=True, text=True)
    elif requested.suffix.lower() == ".tex":
        try:
            subprocess.run(["open", "-a", "TextEdit", str(requested)], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            subprocess.run(["open", str(requested)], check=True, capture_output=True, text=True)
    else:
        subprocess.run(["open", str(requested)], check=True, capture_output=True, text=True)
    return result


def copy_publication_export_to_desktop(path: Path) -> Path:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)
    for old_path in desktop.glob("publication_list_*_overleaf.zip"):
        if old_path.is_file() or old_path.is_symlink():
            old_path.unlink(missing_ok=True)
    target = desktop / path.name
    shutil.copy2(path, target)
    return target


def reveal_path_in_finder(path: Path) -> dict[str, str]:
    requested = path.expanduser().resolve()
    target = requested
    revealed = "file"
    if requested.exists():
        if requested.is_dir():
            revealed = "folder"
            open_finder_location(requested)
        else:
            try:
                reveal_finder_posix_file(requested)
            except subprocess.CalledProcessError:
                open_finder_absolute_path(requested.parent)
                revealed = "parent_folder"
                target = requested.parent
    else:
        revealed = "nearest_parent"
        target = requested.parent
        while target != target.parent and not target.exists():
            target = target.parent
        if not target.exists():
            raise FileNotFoundError(str(requested))
        open_finder_location(target)
    return {"status": "opened", "path": str(requested), "opened_path": str(target), "revealed": revealed}


def reveal_finder_posix_file(path: Path) -> None:
    run_finder_script(
        f"""
tell application "Finder"
    activate
    reveal POSIX file {applescript_string(str(path))}
end tell
"""
    )


def open_finder_posix_path(path: Path) -> None:
    run_finder_script(
        f"""
tell application "Finder"
    activate
    open POSIX file {applescript_string(str(path))}
end tell
"""
    )


def open_finder_location(path: Path) -> None:
    try:
        open_finder_posix_path(path)
    except subprocess.CalledProcessError:
        open_finder_absolute_path(path)


def open_finder_absolute_path(path: Path) -> None:
    try:
        subprocess.run(["open", str(path)], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        subprocess.run(["open", "-R", str(path)], check=True, capture_output=True, text=True)


def run_finder_script(script: str) -> None:
    args = ["osascript"]
    for line in script.splitlines():
        line = line.strip()
        if line:
            args.extend(["-e", line])
    subprocess.run(args, check=True, capture_output=True, text=True)


def applescript_string(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def export_my_publication_list(rows: list[dict[str, Any]], *, my_name: str, export_format: str) -> Path:
    clear_publication_export_format(export_format)
    stamp = re.sub(r"[^0-9]", "", now_iso())[:14]
    entries = [publication_export_entry(row, my_name=my_name) for row in rows]
    if export_format == "docx":
        path = PUBLICATION_EXPORT_DIR / f"publication_list_{stamp}.docx"
        write_publication_docx(path, entries)
        return path
    if export_format == "tex":
        path = PUBLICATION_EXPORT_DIR / f"publication_list_{stamp}.tex"
        write_publication_tex(path, entries, engine="xelatex")
        return path
    if export_format == "overleaf":
        path = PUBLICATION_EXPORT_DIR / f"publication_list_{stamp}_overleaf.zip"
        write_publication_overleaf_zip(path, entries)
        return path
    tex_path = PUBLICATION_EXPORT_DIR / f"publication_list_{stamp}_pdf.tex"
    engine = find_latex_engine()
    write_publication_tex(tex_path, entries, engine=Path(engine).name if engine else "xelatex")
    if not engine:
        raise RuntimeError(f"LaTeX is not installed. The source file was written to {tex_path}")
    latex_env = os.environ.copy()
    engine_dir = str(Path(engine).parent)
    latex_env["PATH"] = f"{engine_dir}:{latex_env.get('PATH', '')}" if engine_dir else latex_env.get("PATH", "")
    for _ in range(2):
        result = subprocess.run(
            [engine, "-interaction=nonstopmode", tex_path.name],
            cwd=tex_path.parent,
            capture_output=True,
            text=True,
            timeout=60,
            env=latex_env,
        )
        if result.returncode != 0:
            log_path = tex_path.with_suffix(".log")
            message = result.stderr.strip() or result.stdout[-800:].strip() or "LaTeX export failed"
            raise RuntimeError(f"{message}. Source file: {tex_path}. Log: {log_path}")
    pdf_path = tex_path.with_suffix(".pdf")
    if not pdf_path.exists():
        raise RuntimeError(f"LaTeX did not create a PDF. Source file: {tex_path}")
    cleanup_latex_export_auxiliary_files(tex_path)
    return pdf_path


def cleanup_latex_export_auxiliary_files(tex_path: Path) -> None:
    for suffix in (".aux", ".log", ".out", ".toc", ".tex"):
        tex_path.with_suffix(suffix).unlink(missing_ok=True)


def find_latex_engine() -> str:
    extra_dirs = [
        "/Library/TeX/texbin",
        "/usr/texbin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    for name in ("xelatex", "pdflatex"):
        found = shutil.which(name)
        if found:
            return found
        for folder in extra_dirs:
            candidate = Path(folder) / name
            if candidate.exists() and candidate.is_file():
                return str(candidate)
    return ""


def publication_export_entry(row: dict[str, Any], *, my_name: str) -> dict[str, Any]:
    authors = full_author_names(row) or author_summary(row)
    marks = parse_my_publication_author_marks(row)
    own_indexes = [index for index, name in enumerate(authors) if author_matches_name(name, my_name)]
    if not any(mark.get("co_first_author") for mark in marks.values()) and row.get("first_author"):
        for index in own_indexes:
            marks.setdefault(str(index), {"name": authors[index]})["co_first_author"] = True
    if not any(mark.get("corresponding_author") for mark in marks.values()) and row.get("corresponding_author"):
        for index in own_indexes:
            marks.setdefault(str(index), {"name": authors[index]})["corresponding_author"] = True
    return {
        "authors": authors,
        "marks": marks,
        "my_name": my_name,
        "title": clean_text(row.get("title") or ""),
        "journal": clean_text(row.get("journal") or ""),
        "volume": paper_volume(row),
        "pages": paper_page(row),
        "year": publication_year(row),
        "doi": clean_text(row.get("doi") or ""),
    }


def author_matches_name(author: str, target_name: str) -> bool:
    targets = author_name_signatures(target_name.split(";")[0] if target_name else "")
    candidates = author_name_signatures(author)
    return any(author_signatures_match(target, candidate) for target in targets for candidate in candidates)


CHINESE_PINYIN = {
    "丁": "ding", "中": "zhong", "二": "er", "井": "jing", "亮": "liang", "仁": "ren",
    "令": "ling", "作": "zuo", "侯": "hou", "儀": "yi", "元": "yuan", "光": "guang",
    "关": "guan", "军": "jun", "凡": "fan", "刘": "liu", "刚": "gang", "剑": "jian",
    "卉": "hui", "单": "shan", "吴": "wu", "哲": "zhe", "善": "shan", "嘉": "jia",
    "婧": "jing", "嫄": "yuan", "子": "zi", "孔": "kong", "孙": "sun", "宁": "ning",
    "宇": "yu", "尚": "shang", "崔": "cui", "平": "ping", "年": "nian", "广": "guang",
    "広": "guang", "建": "jian", "张": "zhang", "彭": "peng", "微": "wei", "户": "hu",
    "承": "cheng", "明": "ming", "朱": "zhu", "权": "quan", "李": "li", "村": "cun",
    "杨": "yang", "桂": "gui", "森": "sen", "正": "zheng", "治": "zhi", "洪": "hong",
    "海": "hai", "涛": "tao", "温": "wen", "焘": "tao", "猛": "meng", "王": "wang",
    "用": "yong", "益": "yi", "程": "cheng", "罡": "gang", "者": "zhe", "胡": "hu",
    "良": "liang", "芃": "peng", "苏": "su", "著": "zhu", "软": "ruan", "邴": "bing",
    "郭": "guo", "野": "ye", "金": "jin", "钟": "zhong", "钧": "jun", "铂": "bo",
    "铭": "ming", "锡": "xi", "飞": "fei", "马": "ma", "鹏": "peng", "黄": "huang",
    "洁": "jie", "鑫": "xin", "殷": "yin", "沈": "shen", "约": "yue", "拉": "la",
    "娜": "na",
}
CHINESE_COMPOUND_SURNAMES = {"欧阳": "ouyang", "司马": "sima", "诸葛": "zhuge", "上官": "shangguan"}
CHINESE_NAME_STOPWORDS = {"作者", "著者", "用户", "微软用户"}


def author_name_signatures(value: str) -> list[dict[str, str]]:
    clean = re.sub(r"[\u0300-\u036f]", "", clean_text(value))
    clean = re.sub(r"[.,-]", " ", clean)
    clean = re.sub(r"[^A-Za-z\s]", "", clean)
    parts = [part.lower() for part in clean.split() if part]
    variants: list[dict[str, str]] = []

    def add_variant(family: str, given: list[str]) -> None:
        family = clean_text(family).lower()
        given = [clean_text(part).lower() for part in given if clean_text(part)]
        if not family:
            return
        signature = {
            "family": family,
            "given_full": "".join(given),
            "initials": "".join(part[:1] for part in given),
        }
        if signature not in variants:
            variants.append(signature)

    if parts:
        add_variant(parts[-1], parts[:-1])
        if len(parts) > 1:
            add_variant(parts[0], parts[1:])
    add_chinese_author_signatures(value, add_variant)
    return variants


def add_chinese_author_signatures(value: str, add_variant: Any) -> None:
    for raw_name in re.findall(r"[\u4e00-\u9fff]{2,5}", value or ""):
        if raw_name in CHINESE_NAME_STOPWORDS:
            continue
        name = raw_name.removesuffix("著")
        if len(name) < 2 or name in CHINESE_NAME_STOPWORDS:
            continue
        surname = ""
        given_chars = ""
        for compound, pinyin in CHINESE_COMPOUND_SURNAMES.items():
            if name.startswith(compound) and len(name) > len(compound):
                surname = pinyin
                given_chars = name[len(compound):]
                break
        if not surname:
            surname = CHINESE_PINYIN.get(name[0], "")
            given_chars = name[1:]
        given = [CHINESE_PINYIN.get(char, "") for char in given_chars]
        if surname and given and all(given):
            add_variant(surname, given)


def author_signatures_match(target: dict[str, str], candidate: dict[str, str]) -> bool:
    if not target.get("family") or not candidate.get("family") or target["family"] != candidate["family"]:
        return False
    if target.get("given_full") and candidate.get("given_full") and target["given_full"] == candidate["given_full"]:
        return True
    if target.get("initials") and candidate.get("initials") and target["initials"] == candidate["initials"]:
        return True
    if target.get("initials") and candidate.get("initials") and (
        target["initials"].startswith(candidate["initials"]) or candidate["initials"].startswith(target["initials"])
    ):
        return True
    return not target.get("given_full") and not candidate.get("given_full")


def write_publication_docx(path: Path, entries: list[dict[str, Any]]) -> None:
    hyperlink_relationships: dict[str, str] = {}
    paragraphs: list[str] = [docx_paragraph([{"text": "Publication List", "bold": True}], style="Title", hyperlink_relationships=hyperlink_relationships)]
    legend_runs = publication_docx_legend_runs(entries)
    if legend_runs:
        paragraphs.append(docx_paragraph(legend_runs, style="Legend", align="right", hyperlink_relationships=hyperlink_relationships))
    for entry in entries:
        paragraphs.append(docx_paragraph(
            publication_docx_runs(entry),
            style="PublicationItem",
            num_id=1,
            justify=True,
            hyperlink_relationships=hyperlink_relationships,
        ))
    document_xml = DOCX_DOCUMENT_TEMPLATE.format(body="\n".join(paragraphs))
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", DOCX_CONTENT_TYPES)
        archive.writestr("_rels/.rels", DOCX_RELS)
        archive.writestr("word/_rels/document.xml.rels", docx_document_rels(hyperlink_relationships))
        archive.writestr("word/numbering.xml", DOCX_NUMBERING)
        archive.writestr("word/styles.xml", DOCX_STYLES)
        archive.writestr("word/document.xml", document_xml)


def publication_docx_runs(entry: dict[str, Any]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    runs.extend(publication_author_runs(entry, target="docx"))
    runs.extend([
        {"text": ". "},
        {"text": entry["title"]},
        {"text": ". "},
        {"text": entry["journal"], "italic": True},
    ])
    if entry["volume"]:
        runs.extend([{"text": " "}, {"text": entry["volume"], "bold": True}])
    if entry["pages"]:
        runs.append({"text": f", {entry['pages']}"})
    if entry["year"]:
        runs.append({"text": f" ({entry['year']})."})
    else:
        runs.append({"text": "."})
    if entry["doi"]:
        doi_url = f"https://doi.org/{entry['doi']}"
        runs.append({"text": f" {doi_url}", "hyperlink": doi_url})
    return runs


def publication_docx_legend_runs(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    parts = publication_symbol_legend_parts(entries, target="docx")
    runs: list[dict[str, Any]] = []
    for index, (symbol, label) in enumerate(parts):
        if index:
            runs.append({"text": "    "})
        runs.append({"text": symbol, "superscript": True})
        runs.append({"text": f" {label}"})
    return runs


def publication_author_runs(entry: dict[str, Any], *, target: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    authors = entry["authors"]
    for index, author in enumerate(authors):
        if index:
            runs.append({"text": ", "})
        mark = entry["marks"].get(str(index), {})
        runs.append({
            "text": nature_author_name(author),
            "bold": author_matches_name(author, entry["my_name"]),
        })
        symbols = publication_author_symbols(mark)
        if symbols:
            runs.append({"text": symbols, "superscript": True})
    return runs or [{"text": "Authors unavailable"}]


def publication_author_symbols(mark: dict[str, Any]) -> str:
    symbols = ""
    if mark.get("co_first_author"):
        symbols += "*"
    if mark.get("corresponding_author"):
        symbols += "†"
    return symbols


def publication_symbol_legend_parts(entries: list[dict[str, Any]], *, target: str) -> list[tuple[str, str]]:
    has_co_first = any(mark.get("co_first_author") for entry in entries for mark in entry["marks"].values())
    has_corresponding = any(mark.get("corresponding_author") for entry in entries for mark in entry["marks"].values())
    if target == "latex":
        parts = []
        if has_co_first:
            parts.append((r"\ensuremath{\ast}", "Equal contribution"))
        if has_corresponding:
            parts.append((r"\ensuremath{\dagger}", "Corresponding author"))
        return parts
    parts = []
    if has_co_first:
        parts.append(("*", "Equal contribution"))
    if has_corresponding:
        parts.append(("†", "Corresponding author"))
    return parts


def docx_paragraph(
    runs: list[dict[str, Any]],
    *,
    style: str = "",
    align: str = "",
    justify: bool = False,
    num_id: int | None = None,
    hyperlink_relationships: dict[str, str] | None = None,
) -> str:
    props = []
    if style:
        props.append(f'<w:pStyle w:val="{style}"/>')
    if num_id is not None:
        props.append(f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>')
    if justify:
        props.append('<w:jc w:val="both"/>')
    elif align:
        props.append(f'<w:jc w:val="{align}"/>')
    prop_xml = f"<w:pPr>{''.join(props)}</w:pPr>" if props else ""
    return f"<w:p>{prop_xml}{''.join(docx_run(run, hyperlink_relationships=hyperlink_relationships) for run in runs)}</w:p>"


def docx_run(run: dict[str, Any], *, hyperlink_relationships: dict[str, str] | None = None) -> str:
    run_xml = "".join(docx_run_segment(segment) for segment in docx_run_segments(run))
    url = clean_text(run.get("hyperlink") or "")
    if not url or hyperlink_relationships is None:
        return run_xml
    rel_id = docx_hyperlink_relationship_id(url, hyperlink_relationships)
    return f'<w:hyperlink r:id="{rel_id}" w:history="1">{run_xml}</w:hyperlink>'


DOCX_SUBSCRIPT_CHARS = {
    "₀": "0",
    "₁": "1",
    "₂": "2",
    "₃": "3",
    "₄": "4",
    "₅": "5",
    "₆": "6",
    "₇": "7",
    "₈": "8",
    "₉": "9",
    "₊": "+",
    "₋": "-",
    "₍": "(",
    "₎": ")",
    "ₓ": "x",
    "ᵧ": "y",
}


def docx_run_segments(run: dict[str, Any]) -> list[dict[str, Any]]:
    text = str(run.get("text") or "")
    if not text:
        return [run]
    segments: list[dict[str, Any]] = []
    current_text: list[str] = []
    current_subscript: bool | None = None

    def flush() -> None:
        nonlocal current_text, current_subscript
        if not current_text:
            return
        segment = dict(run)
        segment["text"] = "".join(current_text)
        if current_subscript:
            segment["subscript"] = True
            segment.setdefault("size", "24")
        segments.append(segment)
        current_text = []
        current_subscript = None

    for index, char in enumerate(text):
        subscript_char = DOCX_SUBSCRIPT_CHARS.get(char)
        is_subscript = subscript_char is not None
        if char in {"δ", "Δ"} and docx_delta_is_formula_subscript(text, index):
            subscript_char = "δ"
            is_subscript = True
        output_char = subscript_char if subscript_char is not None else char
        if current_subscript is not None and current_subscript != is_subscript:
            flush()
        current_subscript = is_subscript
        current_text.append(output_char)
    flush()
    return segments or [run]


def docx_delta_is_formula_subscript(text: str, index: int) -> bool:
    prev_char = text[index - 1] if index > 0 else ""
    next_char = text[index + 1] if index + 1 < len(text) else ""
    return prev_char in DOCX_SUBSCRIPT_CHARS or next_char in DOCX_SUBSCRIPT_CHARS


def docx_run_segment(run: dict[str, Any]) -> str:
    props = []
    text = str(run.get("text") or "")
    if docx_text_has_cjk(text):
        props.append('<w:rFonts w:eastAsia="KaiTi"/>')
    if run.get("bold"):
        props.append("<w:b/>")
    if run.get("italic"):
        props.append("<w:i/>")
    if run.get("superscript"):
        props.append('<w:vertAlign w:val="superscript"/>')
    if run.get("subscript"):
        props.append('<w:vertAlign w:val="subscript"/>')
    if run.get("size"):
        size = clean_text(str(run.get("size") or ""))
        if size.isdigit():
            props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    if run.get("hyperlink"):
        props.append('<w:color w:val="0563C1"/><w:u w:val="single"/>')
    prop_xml = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
    return f"<w:r>{prop_xml}<w:t xml:space=\"preserve\">{xml_escape(text)}</w:t></w:r>"


def docx_text_has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff\uf900-\ufaff]", text or ""))


def docx_hyperlink_relationship_id(url: str, hyperlink_relationships: dict[str, str]) -> str:
    existing = hyperlink_relationships.get(url)
    if existing:
        return existing
    rel_id = f"rId{len(hyperlink_relationships) + 3}"
    hyperlink_relationships[url] = rel_id
    return rel_id


def write_publication_tex(path: Path, entries: list[dict[str, Any]], *, engine: str = "xelatex") -> None:
    path.write_text(publication_tex_content(entries, engine=engine), encoding="utf-8")


def write_publication_overleaf_zip(path: Path, entries: list[dict[str, Any]]) -> None:
    readme = (
        "Paper Monitor publication list export\n\n"
        "Upload this zip to Overleaf as a new project. The main file is main.tex.\n"
        "The project includes latexmkrc to select XeLaTeX automatically.\n"
    )
    latexmkrc = "\n".join([
        "$pdf_mode = 5;",
        "$xelatex = 'xelatex -interaction=nonstopmode %O %S';",
        "",
    ])
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("main.tex", publication_tex_content(entries, engine="xelatex"))
        archive.writestr("latexmkrc", latexmkrc)
        archive.writestr("README.txt", readme)


def publication_tex_content(entries: list[dict[str, Any]], *, engine: str = "xelatex") -> str:
    lines = [
        r"% !TeX program = xelatex",
        r"% !TEX TS-program = xelatex",
        r"\documentclass[11pt]{article}",
        r"\usepackage[margin=1in]{geometry}",
        r"\usepackage{iftex}",
        r"\ifPDFTeX",
        r"  \usepackage[utf8]{inputenc}",
        r"  \usepackage[T1]{fontenc}",
        r"  \usepackage{mathptmx}",
        r"  \usepackage{CJKutf8}",
        r"\else",
        r"  \usepackage{fontspec}",
        r"  \setmainfont{Times New Roman}",
        r"  \usepackage{xeCJK}",
        r"  \setCJKmainfont{FandolKai-Regular.otf}",
        r"  \setCJKmonofont{FandolKai-Regular.otf}",
        r"\fi",
        r"\usepackage{enumitem}",
        r"\usepackage{xurl}",
        r"\usepackage[hidelinks]{hyperref}",
        r"\Urlmuskip=0mu plus 1mu",
        r"\setlist[enumerate]{leftmargin=*,label=\arabic*.,itemsep=0.45em}",
        r"\begin{document}",
        r"\ifPDFTeX\begin{CJK}{UTF8}{gkai}\fi",
        r"\section*{Publication List}",
        publication_tex_legend(entries),
        r"\begin{enumerate}",
    ]
    for entry in entries:
        lines.append(r"\item " + publication_tex_entry(entry))
    lines.extend([r"\end{enumerate}", r"\ifPDFTeX\end{CJK}\fi", r"\end{document}", ""])
    return "\n".join(lines)


def publication_tex_legend(entries: list[dict[str, Any]]) -> str:
    parts = publication_symbol_legend_parts(entries, target="latex")
    if not parts:
        return ""
    text = r"\quad ".join(symbol + r" " + latex_escape(label) for symbol, label in parts)
    return r"{\raggedleft\small " + text + r"\par}"


def publication_tex_entry(entry: dict[str, Any]) -> str:
    author_text = publication_tex_authors(entry)
    parts = [
        f"{author_text}.",
        f"{latex_escape(entry['title'])}.",
        r"\emph{" + latex_escape(entry["journal"]) + r"}",
    ]
    if entry["volume"]:
        parts.append(r"\textbf{" + latex_escape(entry["volume"]) + r"}" + (f", {latex_escape(entry['pages'])}" if entry["pages"] else ""))
    elif entry["pages"]:
        parts.append(latex_escape(entry["pages"]))
    if entry["year"]:
        parts.append(f"({latex_escape(entry['year'])}).")
    if entry["doi"]:
        parts.append(publication_tex_url(f"https://doi.org/{entry['doi']}"))
    return " ".join(part for part in parts if part)


def publication_tex_authors(entry: dict[str, Any]) -> str:
    authors = []
    for index, author in enumerate(entry["authors"]):
        mark = entry["marks"].get(str(index), {})
        text = latex_escape(nature_author_name(author))
        if author_matches_name(author, entry["my_name"]):
            text = r"\textbf{" + text + r"}"
        symbols = publication_author_latex_symbols(mark)
        if symbols:
            text += r"\textsuperscript{" + symbols + r"}"
        authors.append(text)
    return ", ".join(authors) or "Authors unavailable"


def publication_author_latex_symbols(mark: dict[str, Any]) -> str:
    symbols = []
    if mark.get("co_first_author"):
        symbols.append(r"\ast")
    if mark.get("corresponding_author"):
        symbols.append(r"\dagger")
    return r"\ensuremath{" + "".join(symbols) + r"}" if symbols else ""


def latex_escape(value: str) -> str:
    subscript_replacements = {
        "₀": r"$_0$",
        "₁": r"$_1$",
        "₂": r"$_2$",
        "₃": r"$_3$",
        "₄": r"$_4$",
        "₅": r"$_5$",
        "₆": r"$_6$",
        "₇": r"$_7$",
        "₈": r"$_8$",
        "₉": r"$_9$",
        "₊": r"$_+$",
        "₋": r"$_-$",
        "₍": r"$_($",
        "₎": r"$_)$",
        "ₓ": r"$_x$",
        "ᵧ": r"$_y$",
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "--",
        "—": "---",
        "−": r"$-$",
    }
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(subscript_replacements.get(char) or replacements.get(char, char) for char in str(value))


def publication_tex_url(url: str) -> str:
    return r"\url{" + latex_url_escape(url) + r"}"


def latex_url_escape(value: str) -> str:
    return str(value).replace("\\", "/").replace("%", r"\%").replace("{", r"\{").replace("}", r"\}")


def xml_escape(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
</Types>"""
DOCX_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
DOCX_DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
</Relationships>"""


def docx_document_rels(hyperlink_relationships: dict[str, str]) -> str:
    links = [
        f'<Relationship Id="{xml_escape(rel_id)}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="{xml_escape(url)}" TargetMode="External"/>'
        for url, rel_id in hyperlink_relationships.items()
    ]
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
  {links}
</Relationships>""".format(links="\n  ".join(links))


DOCX_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"/><w:sz w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Legend"><w:name w:val="Legend"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="160"/></w:pPr><w:rPr><w:sz w:val="20"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="PublicationItem"><w:name w:val="Publication Item"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:after="120"/><w:jc w:val="both"/></w:pPr></w:style>
</w:styles>"""
DOCX_NUMBERING = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:abstractNum w:abstractNumId="1">
    <w:multiLevelType w:val="singleLevel"/>
    <w:lvl w:ilvl="0">
      <w:start w:val="1"/>
      <w:numFmt w:val="decimal"/>
      <w:lvlText w:val="%1."/>
      <w:lvlJc w:val="left"/>
      <w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr>
    </w:lvl>
  </w:abstractNum>
  <w:num w:numId="1"><w:abstractNumId w:val="1"/></w:num>
</w:numbering>"""
DOCX_DOCUMENT_TEMPLATE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <w:body>
    {body}
    <w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr>
  </w:body>
</w:document>"""


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


def paper_first_seen_date(paper: dict[str, Any]) -> str:
    return str(paper.get("first_seen_at") or "")[:10]


def paper_is_late_arrival(paper: dict[str, Any]) -> bool:
    publication_date = str(paper.get("publication_date") or "")[:10]
    first_seen = paper_first_seen_date(paper)
    if not publication_date or not first_seen or first_seen <= publication_date:
        return False
    try:
        delta = date.fromisoformat(first_seen) - date.fromisoformat(publication_date)
    except ValueError:
        return False
    return timedelta(days=1) <= delta <= timedelta(days=LATE_ARRIVAL_LOOKBACK_DAYS)


def unread_late_arrival_paper_ids(storage: Storage, selected: str, journals: list[str]) -> set[str]:
    if not journals:
        return set()
    placeholders = ", ".join(["?"] * len(journals))
    rows = storage.conn.execute(
        f"""
        SELECT papers.paper_id
        FROM papers
        LEFT JOIN paper_reads ON paper_reads.paper_id = papers.paper_id
        WHERE papers.publication_date = ?
          AND length(papers.publication_date) = 10
          AND substr(papers.first_seen_at, 1, 10) > papers.publication_date
          AND julianday(substr(papers.first_seen_at, 1, 10)) - julianday(papers.publication_date) <= ?
          AND papers.source IN ('crossref', 'openalex', 'arxiv')
          AND papers.journal IN ({placeholders})
          AND (papers.section_allowed IS NULL OR papers.section_allowed != 0)
          AND paper_reads.late_arrival_seen_at IS NULL
        """,
        (selected, LATE_ARRIVAL_LOOKBACK_DAYS, *journals),
    ).fetchall()
    return {str(row["paper_id"]) for row in rows}


def late_arrivals_for_seen_date(storage: Storage, selected: str, journals: list[str]) -> list[dict[str, Any]]:
    if not journals:
        return []
    try:
        window_start = (date.fromisoformat(selected) - timedelta(days=LATE_ARRIVAL_LOOKBACK_DAYS)).isoformat()
    except ValueError:
        return []
    placeholders = ", ".join(["?"] * len(journals))
    rows = storage.conn.execute(
        f"""
        SELECT papers.*
        FROM papers
        LEFT JOIN paper_reads ON paper_reads.paper_id = papers.paper_id
        WHERE substr(papers.first_seen_at, 1, 10) = ?
          AND length(papers.publication_date) = 10
          AND papers.publication_date >= ?
          AND papers.publication_date < ?
          AND papers.source IN ('crossref', 'openalex', 'arxiv')
          AND papers.journal IN ({placeholders})
          AND (papers.section_allowed IS NULL OR papers.section_allowed != 0)
          AND paper_reads.late_arrival_seen_at IS NULL
        ORDER BY papers.publication_date DESC, papers.journal ASC, papers.title ASC
        """,
        (selected, window_start, selected, *journals),
    ).fetchall()
    return [dict(row) for row in rows]


def late_arrival_summaries(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for paper in papers:
        publication_date = str(paper.get("publication_date") or "")[:10]
        if not publication_date:
            continue
        summary = grouped.setdefault(
            publication_date,
            {"publication_date": publication_date, "count": 0, "journals": {}, "paper_ids": []},
        )
        summary["count"] += 1
        summary["paper_ids"].append(str(paper.get("paper_id") or ""))
        journal = paper.get("journal") or "Unknown Journal"
        summary["journals"][journal] = int(summary["journals"].get(journal, 0)) + 1
    return sorted(grouped.values(), key=lambda item: str(item["publication_date"]), reverse=True)


def author_summary(paper: dict[str, Any]) -> list[str]:
    raw = parse_raw_json(paper)
    names = authors_from_openalex(raw) or authors_from_crossref(raw) or authors_from_arxiv(raw) or authors_from_datacite(raw) or authors_from_google_scholar(raw)
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
    if clean_text(raw.get("source") or "").lower() != "arxiv" and not (raw.get("arxiv_id") or raw.get("versioned_arxiv_id")):
        return []
    return dedup_names([clean_author_name(str(name)) for name in raw.get("authors") or [] if name])


def authors_from_datacite(raw: dict[str, Any]) -> list[str]:
    datacite = raw.get("datacite") if isinstance(raw.get("datacite"), dict) else raw
    creators = raw.get("creators") or datacite.get("creators") or []
    names: list[str] = []
    for item in creators:
        if not isinstance(item, dict):
            continue
        name = clean_author_name(str(item.get("name") or ""))
        if not name:
            given = clean_author_name(str(item.get("givenName") or ""))
            family = clean_author_name(str(item.get("familyName") or ""))
            name = clean_author_name(" ".join(part for part in [given, family] if part))
        if name:
            names.append(name)
    return dedup_names(names)


def authors_from_google_scholar(raw: dict[str, Any]) -> list[str]:
    authors = raw.get("authors") or []
    if isinstance(authors, str):
        authors = re.split(r"\s*(?:,|，|、|;|；)\s*", authors)
    elif isinstance(authors, list):
        split_authors: list[str] = []
        for author in authors:
            split_authors.extend(re.split(r"\s*(?:，|、|;|；)\s*", str(author)))
        authors = split_authors
    return dedup_names([clean_author_name(str(name)) for name in authors if name])


def preprint_identifier(paper: dict[str, Any]) -> str:
    if (paper.get("journal") or "").lower() != ARXIV_JOURNAL_NAME.lower():
        raw = parse_raw_json(paper)
        preprint = raw.get("preprint") if isinstance(raw.get("preprint"), dict) else {}
        versions = raw.get("citation_versions") if isinstance(raw.get("citation_versions"), dict) else {}
        preprint_version = versions.get("preprint") if isinstance(versions.get("preprint"), dict) else {}
        return clean_text(preprint.get("arxiv_id") or preprint_version.get("arxiv_id") or raw.get("arxiv_id") or raw.get("versioned_arxiv_id") or "")
    raw = parse_raw_json(paper)
    return clean_text(raw.get("arxiv_id") or raw.get("versioned_arxiv_id") or "")


def preprint_categories(paper: dict[str, Any]) -> list[str]:
    if (paper.get("journal") or "").lower() != ARXIV_JOURNAL_NAME.lower():
        raw = parse_raw_json(paper)
        preprint = raw.get("preprint") if isinstance(raw.get("preprint"), dict) else {}
        preprint_raw = preprint.get("raw") if isinstance(preprint.get("raw"), dict) else {}
        return [clean_text(category) for category in preprint_raw.get("categories") or [] if clean_text(category)]
    raw = parse_raw_json(paper)
    return [clean_text(category) for category in raw.get("categories") or [] if clean_text(category)]


def preprint_primary_category(paper: dict[str, Any]) -> str:
    if (paper.get("journal") or "").lower() != ARXIV_JOURNAL_NAME.lower():
        raw = parse_raw_json(paper)
        preprint = raw.get("preprint") if isinstance(raw.get("preprint"), dict) else {}
        preprint_raw = preprint.get("raw") if isinstance(preprint.get("raw"), dict) else {}
        return clean_text(preprint_raw.get("primary_category") or "")
    raw = parse_raw_json(paper)
    primary = clean_text(raw.get("primary_category") or "")
    return primary or (preprint_categories(paper)[0] if preprint_categories(paper) else "")


def parse_raw_json(paper: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = json.loads(paper.get("raw_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def paper_storage_mode(paper: dict[str, Any], *, merged_pdf: str = "", main_pdf: str = "", source_path: str = "") -> str:
    copy_mode = clean_text(paper.get("import_copy_mode") or paper.get("copy_mode") or "").lower()
    if copy_mode in {"copy", "link"}:
        return copy_mode
    if source_path and source_path in {merged_pdf, main_pdf}:
        return "link"
    return "local"


def parse_semantic_scholar_json(paper: dict[str, Any]) -> dict[str, Any]:
    try:
        raw = json.loads(paper.get("semantic_scholar_json") or "{}")
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


def create_my_publication_metrics_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with MY_PUBLICATION_METRICS_JOBS_LOCK:
        MY_PUBLICATION_METRICS_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "started_at": now,
            "finished_at": "",
            "current": 0,
            "total": 0,
            "percent": 0,
            "refreshed": 0,
            "skipped": 0,
            "current_title": "",
            "errors": [],
            "publications": [],
        }
    return job_id


def get_my_publication_metrics_job(job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    with MY_PUBLICATION_METRICS_JOBS_LOCK:
        job = MY_PUBLICATION_METRICS_JOBS.get(job_id)
        return dict(job) if job else None


def active_my_publication_metrics_job() -> dict[str, Any] | None:
    with MY_PUBLICATION_METRICS_JOBS_LOCK:
        for job in reversed(list(MY_PUBLICATION_METRICS_JOBS.values())):
            if job.get("status") in {"queued", "running"}:
                return dict(job)
    return None


def update_my_publication_metrics_job(job_id: str, **updates: Any) -> None:
    with MY_PUBLICATION_METRICS_JOBS_LOCK:
        job = MY_PUBLICATION_METRICS_JOBS.get(job_id)
        if job:
            job.update(updates)


def run_my_publication_metrics_job(*, job_id: str, db_path: Path) -> None:
    storage = Storage(db_path)
    refreshed = 0
    skipped = 0
    errors: list[str] = []
    try:
        all_publications = storage.list_my_publications()
        publications = [
            publication
            for publication in all_publications
            if clean_text(publication.get("paper_id") or "")
            and (
                looks_like_doi(normalize_publication_doi(str(publication.get("doi") or "")))
                or arxiv_identifier_for_paper(publication)
            )
        ]
        total = len(publications)
        update_my_publication_metrics_job(job_id, status="running", stage="metrics", total=total)
        if not total:
            skipped = len(all_publications)
        for index, publication in enumerate(publications, start=1):
            doi = normalize_publication_doi(str(publication.get("doi") or ""))
            paper_id = clean_text(publication.get("paper_id") or "")
            title = clean_text(publication.get("title") or doi)
            update_my_publication_metrics_job(
                job_id,
                current=index,
                current_title=title,
                percent=max(1, min(99, round((index - 1) / max(1, total) * 100))),
            )
            try:
                arxiv_id = arxiv_identifier_for_paper(publication)
                if looks_like_doi(doi):
                    normalized = publication_metrics_metadata_from_doi(doi, timeout=10, max_retries=1)
                else:
                    normalized = publication_metrics_metadata_from_arxiv_id(arxiv_id, timeout=10, max_retries=1)
                updated = storage.refresh_paper_metadata(paper_id, merge_refreshed_metadata(publication, normalized)) if normalized else publication
                pubmed_doi = normalize_publication_doi(str((updated or {}).get("doi") or doi))
                pubmed_enriched = False
                if pubmed_doi and looks_like_doi(pubmed_doi):
                    before_pubmed = parse_raw_json(updated or {})
                    updated = refresh_pubmed_if_possible(storage, updated, doi=pubmed_doi, timeout=12, max_retries=1) or updated
                    after_pubmed = parse_raw_json(updated or {})
                    pubmed_enriched = bool(after_pubmed.get("pubmed")) and after_pubmed.get("pubmed") != before_pubmed.get("pubmed")
                    updated = storage.get_paper(paper_id) or updated
                enriched = refresh_semantic_scholar_if_possible(storage, updated, timeout=6, max_retries=1)
                ads_enriched = refresh_ads_if_possible(storage, enriched or updated, timeout=6, max_retries=1)
                final_paper = ads_enriched or enriched or updated
                final_raw = parse_raw_json(final_paper or {})
                final_pubmed_doi = normalize_publication_doi(
                    str((final_paper or {}).get("doi") or final_raw.get("published_doi") or final_raw.get("doi") or doi)
                )
                if final_pubmed_doi and looks_like_doi(final_pubmed_doi) and not final_raw.get("pubmed"):
                    final_paper = refresh_pubmed_if_possible(storage, final_paper, doi=final_pubmed_doi, timeout=12, max_retries=1) or final_paper
                    pubmed_enriched = bool(parse_raw_json(final_paper or {}).get("pubmed"))
                if normalized or pubmed_enriched or (enriched and enriched.get("semantic_scholar_json")) or (ads_enriched and ads_summary(ads_enriched)):
                    refreshed += 1
                else:
                    skipped += 1
            except Exception as exc:
                skipped += 1
                if len(errors) < 8:
                    errors.append(f"{title}: {exc}")
            update_my_publication_metrics_job(
                job_id,
                current=index,
                percent=max(1, min(99, round(index / max(1, total) * 100))),
                refreshed=refreshed,
                skipped=skipped,
                errors=list(errors),
            )
        api_rows = [my_publication_to_api(row) for row in storage.list_my_publications()]
        update_my_publication_metrics_job(
            job_id,
            status="completed",
            stage="completed",
            current=total,
            percent=100,
            refreshed=refreshed,
            skipped=skipped,
            errors=list(errors),
            publications=api_rows,
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    except Exception as exc:
        update_my_publication_metrics_job(
            job_id,
            status="failed",
            stage="failed",
            errors=[str(exc)],
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
    finally:
        storage.close()


def create_library_import_job(*, folder_path: Path, copy_mode: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    with LIBRARY_IMPORT_JOBS_LOCK:
        LIBRARY_IMPORT_JOBS[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "folder_path": str(folder_path),
            "copy_mode": copy_mode,
            "dry_run": False,
            "started_at": now,
            "finished_at": "",
            "current": 0,
            "total": 0,
            "percent": 0,
            "logs": [{"time": now, "level": "info", "message": "Queued loader job"}],
            "result": None,
            "inventory_path": "",
            "error": "",
            "cancel_requested": False,
            "scan_files": 0,
            "scan_dirs": 0,
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
        snapshot["logs"] = list(job.get("logs") or [])[-20000:]
        return snapshot


def update_library_import_job(job_id: str, **updates: Any) -> None:
    with LIBRARY_IMPORT_JOBS_LOCK:
        job = LIBRARY_IMPORT_JOBS.get(job_id)
        if not job:
            return
        job.update(updates)


def request_stop_library_import_job(job_id: str) -> dict[str, Any] | None:
    with LIBRARY_IMPORT_JOBS_LOCK:
        job = LIBRARY_IMPORT_JOBS.get(job_id)
        if not job:
            return None
        if job.get("status") not in {"completed", "failed", "cancelled", "deleted"}:
            job["cancel_requested"] = True
            job["status"] = "stopping"
            job["stage"] = "stopping"
        snapshot = dict(job)
        snapshot["logs"] = list(job.get("logs") or [])[-300:]
    log_library_import_job(job_id, "Stop requested. The loader will stop at the next safe checkpoint.", level="warn")
    return get_library_import_job(job_id)


def library_import_cancel_requested(job_id: str) -> bool:
    with LIBRARY_IMPORT_JOBS_LOCK:
        job = LIBRARY_IMPORT_JOBS.get(job_id)
        return bool(job and job.get("cancel_requested"))


def log_library_import_job(job_id: str, message: str, *, level: str = "info") -> None:
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    with LIBRARY_IMPORT_JOBS_LOCK:
        job = LIBRARY_IMPORT_JOBS.get(job_id)
        if not job:
            return
        logs = job.setdefault("logs", [])
        logs.append({"time": stamp, "level": level, "message": message})
        if len(logs) > 20000:
            del logs[:-20000]


def library_import_progress_callback(job_id: str):
    def progress(event: dict[str, Any]) -> None:
        if library_import_cancel_requested(job_id):
            raise ImportCancelled("Import stopped by user")
        current = event.get("current")
        total = event.get("total")
        percent = 0
        if isinstance(current, int) and isinstance(total, int) and total > 0:
            percent = max(0, min(100, round((current / total) * 100)))
        updates = {
            "stage": event.get("stage") or "running",
            "current": current or 0,
            "total": total or 0,
            "percent": percent,
        }
        if event.get("stage") == "scan":
            updates["scan_files"] = int(event.get("files_scanned") or 0)
            updates["scan_dirs"] = int(event.get("directories_scanned") or 0)
        update_library_import_job(job_id, **updates)
        message = clean_text(event.get("message"))
        if message:
            log_library_import_job(job_id, message)

    return progress


def run_library_import_job(*, job_id: str, folder_path: Path, copy_mode: str, db_path: Path) -> None:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = safe_slug(folder_path.name or "library-folder", 60)
    inventory_path = ROOT / "reports" / "imports" / f"folder-inventory-{slug}-{timestamp}.json"
    report_path = ROOT / "reports" / "imports" / f"folder-import-{slug}-import-{timestamp}.json"
    progress = library_import_progress_callback(job_id)
    update_library_import_job(job_id, status="running", stage="scan", inventory_path=str(inventory_path))
    log_library_import_job(job_id, f"Source folder: {folder_path}")
    log_library_import_job(job_id, f"Mode: import / {copy_mode}")
    try:
        build_inventory_from_folder(folder_path, output_path=inventory_path, parse_pdfs=True, progress_callback=progress)
        log_library_import_job(job_id, f"Inventory written: {inventory_path}")
        storage = Storage(db_path)
        try:
            result = import_library_inventory(
                inventory_path,
                copy_mode=copy_mode,
                preserve_folders=True,
                dedupe_by=("doi", "arxiv", "path"),
                dry_run=False,
                storage=storage,
                report_path=report_path,
                library_item_name="filename",
                progress_callback=progress,
            )
            refreshed = refresh_imported_doi_metadata(storage, result, job_id=job_id)
            if refreshed:
                log_library_import_job(job_id, f"Refreshed DOI/arXiv metadata for {refreshed} imported papers")
        finally:
            storage.close()
        summary = summarize_import_result(result)
        level = "error" if summary.get("errors") else "info"
        log_library_import_job(job_id, f"Report written: {summary.get('report_path') or report_path}", level=level)
        log_library_import_job(
            job_id,
            (
                f"Done: {summary.get('created_papers', 0)} created, "
                f"{summary.get('existing_papers', 0)} existing left unchanged, "
                f"{summary.get('updated_papers', 0)} updated, "
                f"{summary.get('pdf_doi_extracted_count', 0)} DOI found, "
                f"{summary.get('pdf_doi_missing_count', 0)} no DOI, "
                f"{summary.get('doi_metadata_refreshed', 0)} DOI/arXiv metadata refreshed, "
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
    except ImportCancelled as exc:
        log_library_import_job(job_id, str(exc) or "Import stopped by user", level="warn")
        update_library_import_job(
            job_id,
            status="cancelled",
            stage="cancelled",
            error=str(exc),
            finished_at=datetime.now().astimezone().isoformat(timespec="seconds"),
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


def delete_library_import_job_data(storage: Storage, job_id: str) -> dict[str, Any]:
    job = get_library_import_job(job_id)
    if not job:
        job = {
            "job_id": "",
            "status": "failed",
            "stage": "failed",
            "inventory_path": "",
            "result": {},
        }
    if job.get("status") not in {"completed", "failed", "cancelled", "deleted"}:
        raise ValueError("Stop the import before deleting it.")
    result = job.get("result") if isinstance(job.get("result"), dict) else {}
    batch_id = clean_text(result.get("import_batch_id"))
    batch = None
    if batch_id:
        batch = storage.conn.execute("SELECT * FROM inventory_import_batches WHERE id = ?", (batch_id,)).fetchone()
    if not batch:
        batch = storage.conn.execute(
            "SELECT * FROM inventory_import_batches ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        batch_id = clean_text(batch["id"] if batch else "")
    if not batch_id:
        deleted_paths = []
        for path_value in [job.get("inventory_path"), result.get("report_path")]:
            path_text = clean_text(path_value)
            if delete_import_path(path_text, ROOT / "reports" / "imports"):
                deleted_paths.append(path_text)
        with LIBRARY_IMPORT_JOBS_LOCK:
            live_job = LIBRARY_IMPORT_JOBS.get(job_id)
            if live_job:
                live_job["status"] = "deleted"
                live_job["stage"] = "deleted"
                live_job["result"] = None
                live_job["cancel_requested"] = True
        log_library_import_job(job_id, "Deleted loader scan files", level="warn")
        return {
            "batch_id": "",
            "deleted_papers": 0,
            "deleted_resources": 0,
            "deleted_folders": 0,
            "deleted_paths": deleted_paths,
        }

    started_at = clean_text(batch["started_at"] if batch else "")
    paper_count = storage.conn.execute(
        "SELECT COUNT(*) AS count FROM papers WHERE import_batch_id = ?",
        (batch_id,),
    ).fetchone()["count"]
    resource_count = storage.conn.execute(
        "SELECT COUNT(*) AS count FROM resources WHERE import_batch_id = ?",
        (batch_id,),
    ).fetchone()["count"]
    storage.conn.execute("DELETE FROM resources WHERE import_batch_id = ?", (batch_id,))
    storage.conn.execute("DELETE FROM papers WHERE import_batch_id = ?", (batch_id,))
    storage.conn.execute("DELETE FROM inventory_import_batches WHERE id = ?", (batch_id,))
    deleted_folders = cleanup_empty_import_folders(storage, started_at)
    storage.conn.commit()

    deleted_paths: list[str] = []
    copy_target = clean_text(result.get("copy_target_root")) or str(DEFAULT_LIBRARY_IMPORT_DIR / batch_id)
    if delete_import_path(copy_target, DEFAULT_LIBRARY_IMPORT_DIR):
        deleted_paths.append(copy_target)
    for path_value in [job.get("inventory_path"), result.get("report_path")]:
        if delete_import_path(clean_text(path_value), ROOT / "reports" / "imports"):
            deleted_paths.append(clean_text(path_value))

    with LIBRARY_IMPORT_JOBS_LOCK:
        live_job = LIBRARY_IMPORT_JOBS.get(job_id)
        if live_job:
            live_job["status"] = "deleted"
            live_job["stage"] = "deleted"
            live_job["result"] = None
            live_job["cancel_requested"] = True
    log_library_import_job(job_id, f"Deleted import batch {batch_id}", level="warn")
    return {
        "batch_id": batch_id,
        "deleted_papers": int(paper_count or 0),
        "deleted_resources": int(resource_count or 0),
        "deleted_folders": deleted_folders,
        "deleted_paths": deleted_paths,
    }


def cleanup_empty_import_folders(storage: Storage, started_at: str) -> int:
    if not started_at:
        return 0
    deleted = 0
    while True:
        rows = storage.conn.execute(
            """
            SELECT folder.id
            FROM library_folders AS folder
            LEFT JOIN library_folders AS child ON child.parent_id = folder.id
            LEFT JOIN library_items AS item ON item.folder_id = folder.id
            WHERE folder.id NOT IN (1)
              AND folder.created_at >= ?
              AND child.id IS NULL
              AND item.id IS NULL
            """,
            (started_at,),
        ).fetchall()
        if not rows:
            return deleted
        for row in rows:
            storage.conn.execute("DELETE FROM library_folders WHERE id = ?", (int(row["id"]),))
            deleted += 1


def delete_import_path(path_value: str, allowed_root: Path) -> bool:
    if not path_value:
        return False
    try:
        path = Path(path_value).expanduser().resolve()
        root = allowed_root.resolve()
    except OSError:
        return False
    if not is_allowed_file(path, [root]) or not path.exists():
        return False
    try:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        return True
    except OSError:
        return False


def missing_fetch_journals_for_date(storage: Storage, selected: str, journals: list[str]) -> list[str]:
    selected_date = date.fromisoformat(selected)
    if selected_date > today_jst():
        return []
    if not journals:
        return []
    placeholders = ", ".join(["?"] * len(journals))
    rows = storage.conn.execute(
        f"""
        SELECT journal, source, status, records_found, started_at, finished_at
        FROM fetch_runs
        WHERE monitor_type = 'journal'
          AND window_start <= ?
          AND window_end >= ?
          AND status IN ('success', 'empty', 'error', 'running')
          AND source IN ('journal', 'arxiv')
          AND journal IN ({placeholders})
        ORDER BY finished_at DESC, id DESC
        """,
        (selected, selected, *journals),
    ).fetchall()
    now = datetime.now().astimezone()
    arxiv_ready_at = arxiv_ready_time(selected_date).astimezone(now.tzinfo)
    fetched: set[str] = journals_with_papers_for_date(storage, selected, journals)
    for row in rows:
        journal = row["journal"]
        if journal in fetched:
            continue
        status = row["status"]
        if status == "running":
            if is_fetch_active(selected) and not running_fetch_is_stale(row["started_at"], row["finished_at"], now):
                fetched.add(journal)
            continue
        if journal == ARXIV_JOURNAL_NAME:
            if now < arxiv_ready_at:
                fetched.add(journal)
                continue
            if fetch_finished_before(row["finished_at"], now, arxiv_ready_at):
                continue
            fetched.add(journal)
            continue
        fetched.add(journal)
    missing = [journal for journal in journals if journal not in fetched]
    if ARXIV_JOURNAL_NAME in missing and now < arxiv_ready_at:
        missing.remove(ARXIV_JOURNAL_NAME)
    return missing


def manual_refresh_journals_for_date(selected: str, journals: list[str]) -> list[str]:
    selected_date = date.fromisoformat(selected)
    if selected_date > today_jst():
        return []
    return list(journals)


def journals_with_papers_for_date(storage: Storage, selected: str, journals: list[str]) -> set[str]:
    if not journals:
        return set()
    placeholders = ", ".join(["?"] * len(journals))
    rows = storage.conn.execute(
        f"""
        SELECT DISTINCT journal
        FROM papers
        WHERE publication_date = ?
          AND (section_allowed IS NULL OR section_allowed != 0)
          AND journal IN ({placeholders})
        """,
        (selected, *journals),
    ).fetchall()
    return {row["journal"] for row in rows}


def journal_fetch_start_date(selected_date: date) -> date:
    local_today = today_jst()
    if selected_date >= local_today:
        return selected_date - timedelta(days=1)
    return selected_date


def arxiv_ready_time(selected_date: date) -> datetime:
    eastern = ZoneInfo("America/New_York")
    local_tz = datetime.now().astimezone().tzinfo or ZoneInfo("UTC")
    announcement_date = selected_date - timedelta(days=1)
    announcement = datetime(
        announcement_date.year,
        announcement_date.month,
        announcement_date.day,
        20,
        0,
        tzinfo=eastern,
    )
    return announcement.astimezone(local_tz) + ARXIV_ANNOUNCEMENT_BUFFER


def parse_fetch_time(value: str, now: datetime) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=now.tzinfo)
    return parsed.astimezone(now.tzinfo)


def running_fetch_is_stale(started_at: str, finished_at: str, now: datetime) -> bool:
    started = parse_fetch_time(started_at, now) or parse_fetch_time(finished_at, now)
    if not started:
        return True
    return now - started > INTERRUPTED_FETCH_RESUME_AFTER


def fetch_finished_before(finished_at: str, now: datetime, threshold: datetime) -> bool:
    finished = parse_fetch_time(finished_at, now)
    return not finished or finished < threshold


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


def library_file_path_for_delete(paper: dict[str, Any]) -> Path | None:
    for key in ("merged_pdf_path", "main_pdf_path", "source_path"):
        raw_path = str(paper.get(key) or "")
        if not raw_path:
            continue
        path = Path(raw_path).expanduser().resolve()
        if path.exists() and path.is_file():
            return path
    return None


def delete_library_paper_files(storage: Storage, paper_ids: list[str]) -> list[str]:
    deleted: list[str] = []
    seen_paths: set[str] = set()
    cleared_paper_ids: set[str] = set()
    for paper_id in dict.fromkeys(str(paper_id or "") for paper_id in paper_ids if paper_id):
        paper = storage.get_paper(paper_id)
        if not paper:
            continue
        path = library_file_path_for_delete(paper)
        if not path:
            continue
        path_key = str(path)
        if path_key in seen_paths:
            cleared_paper_ids.add(paper_id)
            continue
        seen_paths.add(path_key)
        try:
            path.unlink()
            deleted.append(path_key)
        except FileNotFoundError:
            continue
        cleared_paper_ids.add(paper_id)
    for raw_path in deleted:
        path = Path(raw_path)
        if is_relative_to(path.parent, DEFAULT_LIBRARY_IMPORT_DIR.resolve()):
            cleanup_empty_parents([raw_path], DEFAULT_LIBRARY_IMPORT_DIR.resolve())
        elif is_relative_to(path.parent, DEFAULT_PDF_DIR.resolve()):
            cleanup_empty_parents([raw_path], DEFAULT_PDF_DIR.resolve())
    for paper_id in cleared_paper_ids:
        storage.clear_download_status(paper_id)
    return deleted


def clear_library_folder_contents(storage: Storage, *, folder_id: int) -> dict[str, int]:
    folder_id = int(folder_id)
    tree_sql = """
        WITH RECURSIVE folder_tree(id) AS (
          SELECT id FROM library_folders WHERE id = ?
          UNION ALL
          SELECT library_folders.id
          FROM library_folders
          JOIN folder_tree ON library_folders.parent_id = folder_tree.id
        )
    """
    exists = storage.conn.execute("SELECT 1 FROM library_folders WHERE id = ?", (folder_id,)).fetchone()
    if not exists:
        return {"items": 0, "folders": 0}
    item_count = int(
        storage.conn.execute(
            tree_sql
            + """
            SELECT COUNT(*) AS count
            FROM library_items
            WHERE folder_id IN (SELECT id FROM folder_tree)
            """,
            (folder_id,),
        ).fetchone()["count"]
        or 0
    )
    folder_count = int(
        storage.conn.execute(
            tree_sql
            + """
            SELECT COUNT(*) AS count
            FROM library_folders
            WHERE id != ? AND id IN (SELECT id FROM folder_tree)
            """,
            (folder_id, folder_id),
        ).fetchone()["count"]
        or 0
    )
    storage.conn.execute(
        tree_sql
        +
        """
        DELETE FROM library_items
        WHERE folder_id IN (SELECT id FROM folder_tree)
        """,
        (folder_id,),
    )
    storage.conn.execute(
        tree_sql
        +
        """
        DELETE FROM library_folders
        WHERE id != ? AND id IN (SELECT id FROM folder_tree)
        """,
        (folder_id, folder_id),
    )
    storage.conn.commit()
    return {"items": item_count, "folders": folder_count}


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
    cache_key = hashlib.sha256(f"{path}:{path.stat().st_mtime_ns}:{page_number}:{size}:{uuid.uuid4().hex}".encode("utf-8")).hexdigest()
    data = single_page_pdf_bytes(path, page_number)
    if data:
        PDF_THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        page_pdf = PDF_THUMB_CACHE_DIR / f"{cache_key}.pdf"
        output_path = PDF_THUMB_CACHE_DIR / f"{cache_key}.png"
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
    .app.library-mode {
      --sidebar-width: 0px;
      grid-template-columns: minmax(0, 1fr);
      background: #fff;
    }
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
      animation: fetchPanelPulse 1.8s ease-in-out infinite;
    }
    .fetch-progress-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
    }
    .fetch-progress strong { color: var(--ink); font-weight: 600; }
    .fetch-progress-percent {
      display: inline-block;
      min-width: 44px;
      text-align: right;
      color: var(--accent);
      font-weight: 700;
      transform-origin: center;
      animation: fetchPercentPulse 1.35s ease-in-out infinite;
    }
    .fetch-progress-track {
      position: relative;
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
    .fetch-progress-track::after {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(90deg, transparent, rgba(255,255,255,0.42), transparent);
      transform: translateX(-100%);
      animation: fetchTrackSweep 1.55s ease-in-out infinite;
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
    @keyframes fetchPanelPulse {
      0%, 100% { border-color: rgba(15, 107, 110, 0.15); }
      50% { border-color: rgba(15, 107, 110, 0.28); }
    }
    @keyframes fetchPercentPulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.08); }
    }
    @keyframes fetchTrackSweep {
      0% { transform: translateX(-100%); opacity: 0; }
      35% { opacity: 1; }
      100% { transform: translateX(100%); opacity: 0; }
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
    .app.library-mode .main {
      padding: 42px 12px 0 30px;
      background: #fff;
    }
    .app.deep-survey-mode {
      background: linear-gradient(to right, #f0f2f5 0 220px, #fbfcfd 220px);
    }
    .app.deep-survey-mode .main {
      position: relative;
      padding: 38px 0 0;
      background: linear-gradient(to right, #f0f2f5 0 220px, #fbfcfd 220px);
    }
    .app.deep-survey-mode .main::before {
      content: "";
      position: absolute;
      left: 0;
      top: 0;
      width: 220px;
      height: 38px;
      background: #f0f2f5;
      pointer-events: none;
    }
    .app.deep-survey-mode .main::after {
      content: "";
      position: absolute;
      left: 220px;
      top: 0;
      width: 1px;
      height: 38px;
      background: var(--line);
      pointer-events: none;
      z-index: 2;
    }
    .app.deep-survey-mode .workspace {
      height: calc(100vh - 38px);
      background: linear-gradient(to right, #f0f2f5 0 220px, #fbfcfd 220px);
    }
    .app.deep-survey-mode .report-column {
      height: 100%;
      padding-right: 0;
      grid-template-rows: auto minmax(0, 1fr);
      background: linear-gradient(to right, #f0f2f5 0 220px, #fbfcfd 220px);
    }
    .app.deep-survey-mode #summary,
    .app.deep-survey-mode #reportTabs,
    .app.deep-survey-mode #fetchProgressHost,
    .app.deep-survey-mode #libraryControls {
      display: none !important;
    }
    .app.deep-survey-mode .toolbar {
      height: 0;
      min-height: 0;
      margin-bottom: 0;
      padding: 0;
    }
    .app.deep-survey-mode #reportTitle,
    .app.deep-survey-mode #reportToolbarActions,
    .app.deep-survey-mode #librarySearchTools {
      display: none !important;
    }
    .internal-browser {
      position: fixed;
      inset: 0;
      z-index: 80;
      display: none;
      grid-template-rows: auto minmax(0, 1fr) auto;
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
    .library-quicklook.compact.open { grid-template-rows: auto minmax(0, 1fr); }
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
    .library-quicklook.compact .library-quicklook-body {
      display: block;
      background: #fff;
    }
    .library-quicklook-thumbs {
      min-height: 0;
      overflow-y: auto;
      border-right: 1px solid var(--line);
      padding: 10px 8px;
      background: #f8fafc;
    }
    .library-quicklook.compact .library-quicklook-thumbs { display: none; }
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
      padding: 0;
      background: #fff;
    }
    .library-pdf-frame {
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
      border-radius: 0;
      background: #fff;
      box-shadow: none;
    }
    .library-file-thumb-preview {
      display: grid;
      place-items: center;
      width: 100%;
      aspect-ratio: 0.76;
      border: 1px solid #d0d5dd;
      border-radius: 4px;
      background: #fff;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      overflow: hidden;
    }
    .library-file-preview {
      width: 100%;
      min-height: 100%;
      display: grid;
      place-items: center;
      background: #fff;
    }
    .library-file-preview.image {
      padding: 18px;
      background: #eef1f5;
    }
    .library-file-preview.image img {
      max-width: 100%;
      max-height: calc(100vh - 160px);
      object-fit: contain;
      background: #fff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.16);
    }
    .library-file-preview.text {
      display: block;
      place-items: initial;
      padding: 0;
      background: #fff;
    }
    .library-file-preview-text {
      min-height: 100%;
      margin: 0;
      padding: 18px 22px;
      color: #182230;
      background: #fff;
      font: 12px/1.55 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      white-space: pre-wrap;
      word-break: break-word;
    }
    .library-file-preview.media {
      padding: 18px;
      background: #101828;
    }
    .library-file-preview video,
    .library-file-preview audio {
      max-width: 100%;
      max-height: 100%;
    }
    .library-file-preview-card {
      width: min(440px, calc(100% - 36px));
      display: grid;
      gap: 12px;
      padding: 22px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
    }
    .library-file-preview-card strong {
      color: var(--ink);
      font-size: 15px;
      overflow-wrap: anywhere;
    }
    .library-file-preview-card span {
      color: var(--muted);
      font-size: 12px;
      overflow-wrap: anywhere;
    }
    .library-file-preview-card button {
      justify-self: start;
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
    .library-quicklook.compact .library-quicklook-pages {
      display: block;
      overflow: hidden;
      background: #fff;
    }
    .library-quicklook.compact .library-quicklook-placeholder {
      min-height: 0;
      padding: 13px 14px;
      color: var(--ink);
      text-align: left;
    }
    .library-quicklook.compact .library-quicklook-placeholder-card {
      width: 100%;
      min-height: 0;
      display: grid;
      grid-template-columns: auto minmax(0, 1fr);
      place-items: center start;
      gap: 10px;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
      padding: 0;
    }
    .library-quicklook.compact .library-quicklook-placeholder-icon {
      color: var(--muted);
      font-size: 22px;
    }
    .library-quicklook.compact .library-quicklook-placeholder-title {
      max-width: none;
      color: var(--ink);
      font-size: 13px;
      font-weight: 600;
    }
    .library-quicklook-resize {
      position: absolute;
      right: 0;
      bottom: 0;
      width: 18px;
      height: 18px;
      cursor: nwse-resize;
      background: linear-gradient(135deg, transparent 0 45%, rgba(102, 112, 133, 0.5) 46% 52%, transparent 53% 100%);
    }
    .library-quicklook.compact .library-quicklook-resize { display: none; }
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
      grid-template-rows: auto auto auto auto auto minmax(0, 1fr);
    }
    .app.library-mode .report-column {
      padding-right: 0;
      overflow: visible;
      background: #fff;
    }
    .app.library-mode:has(.my-publications-shell),
    .app.library-mode .main:has(.my-publications-shell),
    .app.library-mode .report-column:has(.my-publications-shell) {
      background: #f2f2f2;
    }
    .app.library-mode .workspace.note-open .report-column {
      overflow: hidden;
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
    .window-drag-region {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      height: 40px;
      z-index: 60;
      -webkit-user-select: none;
      user-select: none;
    }
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
    .toolbar-actions {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      position: relative;
      z-index: 70;
    }
    .toolbar-actions.hidden { display: none; }
    .app.library-mode #reportToolbarActions { display: none; }
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
    .fetch-progress-host {
      display: none;
      margin: -6px 0 12px;
    }
    .fetch-progress-host.open { display: block; }
    .report-tabs {
      display: none;
      gap: 8px;
      align-items: stretch;
      overflow-x: auto;
      overflow-y: hidden;
      padding: 0 2px 8px;
      margin: -8px -2px 14px;
      scrollbar-width: none;
      -ms-overflow-style: none;
      -webkit-mask-image: linear-gradient(90deg, #000 0, #000 100%);
      mask-image: linear-gradient(90deg, #000 0, #000 100%);
      transition: -webkit-mask-image 120ms ease, mask-image 120ms ease;
    }
    .report-tabs::-webkit-scrollbar { display: none; }
    .report-tabs.open { display: flex; }
    .report-tabs.has-overflow-right {
      -webkit-mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 34px), transparent 100%);
      mask-image: linear-gradient(90deg, #000 0, #000 calc(100% - 34px), transparent 100%);
    }
    .report-tabs.has-overflow-left {
      -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 34px, #000 100%);
      mask-image: linear-gradient(90deg, transparent 0, #000 34px, #000 100%);
    }
    .report-tabs.has-overflow-left.has-overflow-right {
      -webkit-mask-image: linear-gradient(90deg, transparent 0, #000 34px, #000 calc(100% - 34px), transparent 100%);
      mask-image: linear-gradient(90deg, transparent 0, #000 34px, #000 calc(100% - 34px), transparent 100%);
    }
    .journal-tab {
      position: relative;
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
    .late-arrivals {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px;
      padding: 10px 12px;
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      background: #eff6ff;
      color: #1e3a8a;
      font-size: 13px;
    }
    .late-arrivals strong { font-weight: 750; }
    .late-arrival-link {
      border: 0;
      background: transparent;
      color: #1d4ed8;
      font-weight: 700;
      padding: 0;
      cursor: pointer;
      text-decoration: underline;
    }
    .late-dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: #2563eb;
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18);
      flex: 0 0 auto;
    }
    .journal-tab .late-dot {
      position: absolute;
      top: 6px;
      right: 6px;
      width: 8px;
      height: 8px;
      box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.18);
    }
    .library-controls {
      display: none;
      gap: 6px;
      align-items: center;
      flex-wrap: nowrap;
      margin: -8px 0 10px;
      position: relative;
      z-index: 70;
      max-width: 100%;
    }
    .workspace.note-open .library-controls {
      overflow: hidden;
      z-index: 1;
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
      display: none;
      align-items: center;
      gap: 6px;
      position: fixed;
      top: 3px;
      right: 30px;
      z-index: 76;
      width: 292px;
      justify-content: flex-end;
      pointer-events: none;
    }
    .library-search-tools.open { display: flex; }
    .library-search-wrap {
      position: relative;
      width: 34px;
      min-width: 34px;
      transition: width 160ms ease;
      pointer-events: auto;
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
      min-height: 32px;
      padding-left: 30px;
      padding-right: 34px;
      opacity: 0;
      cursor: pointer;
      transition: opacity 120ms ease;
    }
    .library-search-tools:hover .library-search-wrap,
    .library-search-tools:focus-within .library-search-wrap,
    .library-search-tools.has-query .library-search-wrap {
      width: 292px;
    }
    .library-search-tools:hover .library-search-wrap input,
    .library-search-tools:focus-within .library-search-wrap input,
    .library-search-tools.has-query .library-search-wrap input {
      opacity: 1;
      cursor: text;
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
      display: none;
    }
    .library-search-tools.has-query:hover .library-search-count,
    .library-search-tools.has-query:focus-within .library-search-count { display: inline; }
    .library-tab {
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 0 13px;
      cursor: pointer;
      font-weight: 650;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }
    #libraryShortcutTabs {
      min-width: 0;
    }
    .library-tab-rail {
      --library-vertical-tab-length: 82px;
      --library-vertical-tab-thickness: 32px;
      width: 30px;
      min-width: 30px;
      min-height: 0;
      height: 100%;
      position: relative;
      background: transparent;
      padding: 0;
      overflow-x: visible;
      overflow-y: auto;
      scrollbar-width: none;
    }
    .library-tab-rail::after {
      display: none;
    }
    .library-tab-rail::-webkit-scrollbar {
      width: 0;
      height: 0;
    }
    .library-tab-rail-inner {
      position: relative;
      width: 30px;
      height: var(--library-rail-height, 900px);
    }
    .library-tab-rail .library-tab {
      position: absolute;
      left: 0;
      top: calc(var(--tab-top, 0px) + var(--library-vertical-tab-length));
      width: var(--library-vertical-tab-length);
      height: var(--library-vertical-tab-thickness);
      box-sizing: border-box;
      min-height: var(--library-vertical-tab-thickness);
      max-width: none;
      padding: 0 10px;
      justify-content: center;
      text-align: center;
      font-size: 12px;
      box-shadow: none;
      overflow: visible;
      transform: rotate(-90deg);
      transform-origin: left top;
      border-radius: 13px 13px 0 0;
      border: 0;
    }
    .library-tab-label {
      min-width: 0;
      flex: 1 1 auto;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .library-tab.active {
      border-color: var(--accent);
      color: var(--accent-strong);
      box-shadow: inset 0 0 0 1px var(--accent);
    }
    .library-tab-rail .library-tab.active {
      color: var(--ink);
      background: #fff;
      box-shadow: none;
      z-index: 2;
    }
    .library-tab-rail .library-tab.active::before,
    .library-tab-rail .library-tab.active::after {
      content: "";
      position: absolute;
      bottom: -1px;
      width: 18px;
      height: 18px;
      pointer-events: none;
    }
    .library-tab-rail .library-tab.active::before {
      left: -18px;
      background: radial-gradient(circle at 0 0, transparent 18px, #fff 19px);
    }
    .library-tab-rail .library-tab.active::after {
      right: -18px;
      background: radial-gradient(circle at 100% 0, transparent 18px, #fff 19px);
    }
    .library-tab.shortcut-tab {
      background: #fff8d7;
      border-color: #eadc99;
    }
    .library-tab.root-tab {
      background: #fff;
      color: var(--ink);
    }
    .library-tab.shortcut-tab.active {
      background: #fff2b8;
      border-color: #d7bd55;
    }
    .library-tab.workspace-tab {
      background: #eaf8df;
      border-color: #c4e3b1;
    }
    .library-tab.workspace-tab.active {
      background: #dcf1cf;
      border-color: #9dca82;
    }
    .library-tab-rail .library-tab.shortcut-tab.active,
    .library-tab-rail .library-tab.workspace-tab.active {
      background: #fff;
    }
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
      align-items: flex-start;
      gap: 4px 8px;
      flex-wrap: wrap;
      width: 100%;
      min-width: 0;
      margin-left: 0;
      justify-content: space-between;
    }
    .my-publications-tools.open { display: flex; }
    .my-publications-tool-note {
      flex: 1 0 100%;
      max-width: 100%;
      margin: 0 0 2px;
    }
    .my-publications-tools .search {
      min-height: 28px;
      border: 0;
      border-radius: 7px;
      background: #f2f2f2;
      box-shadow: inset 0 0 0 1px rgba(216, 216, 220, 0.78);
      color: var(--ink);
      font-size: 12px;
      padding: 0 8px;
      transition: background 0.16s ease, box-shadow 0.16s ease;
    }
    .my-publications-tools .search:focus {
      outline: 0;
      background: #fff;
      box-shadow: inset 0 0 0 1px rgba(15, 107, 110, 0.64), 0 0 0 3px rgba(15, 107, 110, 0.08);
    }
    .my-publications-tools .smallbtn {
      min-height: 28px;
      border: 0;
      border-radius: 7px;
      background: #d9d9d9;
      color: #2f3948;
      padding: 0 9px;
      font-size: 12px;
      font-weight: 650;
      line-height: 1;
      white-space: nowrap;
      box-shadow: none;
    }
    .my-publications-tools .smallbtn:hover {
      background: #d9d9d9;
      color: var(--accent);
      box-shadow: none;
    }
    .my-publications-tools #addMyPublication {
      background: #d9d9d9;
      color: var(--accent);
      box-shadow: none;
    }
    .my-publications-tool-left {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: nowrap;
      min-width: 0;
      flex: 0 0 calc(100% - 352px);
      overflow: visible;
      margin-left: -18px;
    }
    #myPublicationName { flex: 1 1 220px; min-width: 170px; }
    #publicationSearchBox { flex: 0 1 165px; width: 165px; min-width: 125px; }
    #myPublicationProfileStripHost {
      flex: 0 0 344px;
      min-width: 0;
      min-height: 28px;
      display: flex;
      align-items: center;
      justify-content: flex-end;
    }
    .publication-export-menu {
      position: relative;
      flex: 0 0 auto;
    }
    .publication-export-options {
      display: none;
      position: absolute;
      right: 0;
      top: calc(100% + 6px);
      min-width: 210px;
      padding: 5px;
      border: 0;
      border-radius: 0;
      background: #fff;
      box-shadow: 0 14px 34px rgba(15, 23, 42, 0.15);
      z-index: 120;
    }
    .publication-export-options.open { display: grid; gap: 3px; }
    .publication-export-options button {
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      padding: 8px 10px;
      text-align: left;
      cursor: pointer;
      font-weight: 650;
      white-space: nowrap;
    }
    .publication-export-options button:hover { background: #eef5f4; color: var(--accent-strong); }
    .my-publications-profile-strip {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 8px;
      flex: 1 1 auto;
      min-width: 0;
      max-width: 100%;
      min-height: 28px;
      margin-left: auto;
    }
    .my-publications-profile-statuses {
      display: flex;
      align-items: flex-start;
      justify-content: flex-end;
      gap: 6px;
      flex-wrap: nowrap;
      min-width: 0;
      max-height: 32px;
      overflow: hidden;
    }
    .my-publications-profile-status {
      position: relative;
      overflow: hidden;
      min-width: 0;
      max-width: 160px;
      border: 0;
      border-radius: 8px;
      background: #f2f2f2;
      color: var(--muted);
      padding: 4px 8px;
      font-size: 12px;
      line-height: 1.25;
      white-space: nowrap;
      overflow-wrap: anywhere;
      display: block;
      text-overflow: ellipsis;
    }
    .my-publications-profile-status.live {
      color: #3e6470;
      background: rgba(14, 116, 144, 0.035);
    }
    .my-publications-profile-status.live::after {
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background: linear-gradient(90deg, transparent 0%, rgba(14, 116, 144, 0.04) 28%, rgba(14, 116, 144, 0.16) 50%, rgba(14, 116, 144, 0.04) 72%, transparent 100%);
      background-size: 260% 100%;
      animation: statusFlow 2.8s ease-in-out infinite;
    }
    .my-publications-profile-avatar {
      width: 28px;
      height: 28px;
      border-radius: 50%;
      border: 0;
      background: #eef5f4;
      color: var(--accent-strong);
      font-weight: 800;
      display: grid;
      place-items: center;
      flex: 0 0 auto;
      overflow: hidden;
      padding: 0;
    }
    button.my-publications-profile-avatar {
      cursor: pointer;
    }
    button.my-publications-profile-avatar:hover {
      box-shadow: none;
    }
    .my-publications-profile-avatar img {
      width: 100%;
      height: 100%;
      display: block;
      object-fit: cover;
    }
    .my-publications-profile-clear {
      width: 22px;
      min-height: 22px;
      border: 0;
      border-radius: 50%;
      background: #d9d9d9;
      color: var(--muted);
      cursor: pointer;
      display: grid;
      place-items: center;
      padding: 0;
      font-size: 15px;
      line-height: 1;
      flex: 0 0 auto;
    }
    .my-publications-profile-clear:hover {
      color: var(--ink);
      background: #d9d9d9;
    }
    .workspace.note-open .my-publications-profile-strip {
      flex: 1 1 180px;
      max-width: 220px;
    }
    .workspace.note-open .my-publications-profile-status {
      min-width: 90px;
      max-width: 160px;
    }
    .workspace.note-open .my-publications-profile-avatar {
      width: 34px;
      height: 34px;
    }
    .workspace.note-open .my-publications-profile-clear { display: none; }
    .scholar-profile-input { width: min(320px, 45vw); }
    .my-publications-panel {
      min-width: 0;
      min-height: 0;
      height: 100%;
      border: 0;
      border-radius: 0;
      background: #f2f2f2;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
    }
    .my-publications-search {
      grid-row: 1;
      border-bottom: 1px solid #d8d8dc;
      padding: 5px 10px 6px;
      background: #f2f2f2;
    }
    .my-publications-search:has(.publication-search-results:empty) {
      display: none;
    }
    .publication-search-status {
      position: relative;
      overflow: hidden;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.25;
      min-height: 15px;
      border-radius: 7px;
      padding: 1px 4px;
      transition: color 240ms ease, background-color 240ms ease;
    }
    .publication-search-status.live {
      color: #3e6470;
      background: rgba(14, 116, 144, 0.035);
    }
    .publication-search-status.live::after {
      content: "";
      position: absolute;
      inset: 0;
      pointer-events: none;
      background: linear-gradient(90deg, transparent 0%, rgba(14, 116, 144, 0.03) 28%, rgba(14, 116, 144, 0.12) 50%, rgba(14, 116, 144, 0.03) 72%, transparent 100%);
      background-size: 260% 100%;
      animation: statusFlow 2.8s ease-in-out infinite;
      opacity: 0.82;
    }
    @keyframes statusFlow {
      0% { background-position: 120% 0; opacity: 0.42; }
      45% { opacity: 0.9; }
      100% { background-position: -120% 0; opacity: 0.42; }
    }
    .publication-search-results {
      display: grid;
      gap: 3px;
      margin-top: 4px;
      max-height: 190px;
      overflow-y: auto;
    }
    .publication-search-result {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: center;
      padding: 6px 8px;
      border: 0;
      border-radius: 7px;
      background: #fff;
    }
    .publication-search-result:hover { background: #f4f5f7; }
    .publication-search-result.placeholder {
      display: block;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .publication-search-result.added {
      background: #f7faf8;
      border-color: #c6e2d0;
    }
    .publication-search-result.resolving {
      border-color: #d6e4ff;
      background: #f8fbff;
    }
    .publication-search-result strong { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink); }
    .publication-search-result span { display: block; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .publication-search-actions {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      flex-wrap: wrap;
    }
    .my-publications-table-wrap {
      grid-row: 2;
      min-height: 0;
      overflow: auto;
      background: #fff;
      padding: 0 8px;
    }
    .my-publications-table {
      width: var(--my-publications-table-width, 100%);
      min-width: 100%;
      border-collapse: separate;
      border-spacing: 0 1px;
      table-layout: fixed;
      font-size: 12.5px;
      line-height: 1.15;
    }
    .my-publications-table th {
      position: sticky;
      top: 0;
      z-index: 3;
      background: #fff;
      border-bottom: 0;
      box-shadow: inset 0 -1px 0 #d8d8dc;
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      text-align: left;
      padding: 7px 8px;
      border-right: 0;
    }
    .my-publications-table th.sortable { color: #475467; }
    .my-publications-sort-button {
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-transform: inherit;
      letter-spacing: inherit;
      padding: 0;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      cursor: pointer;
    }
    .my-publications-sort-button:hover { color: var(--accent); }
    .my-publications-sort-indicator {
      color: var(--accent);
      font-size: 10px;
      min-width: 8px;
    }
    .my-publications-table td {
      border-top: 0;
      border-bottom: 0;
      border-right: 0;
      padding: 1px 8px;
      color: #344054;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      background: #fff;
      transition: none;
    }
    .my-publications-table td:first-child {
      border-right: 0;
      border-radius: 6px 0 0 6px;
    }
    .my-publications-table th:first-child {
      border-right: 0;
    }
    .my-publications-table td.my-publications-id {
      padding-left: 14px;
      padding-right: 10px;
    }
    .my-publications-table td:last-child { border-radius: 0 6px 6px 0; }
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
      -webkit-user-select: none;
      user-select: none;
    }
    .my-publications-row:nth-child(even):not(.active) td { background: #f3f3f3; }
    .my-publications-row.selected:not(.active) td {
      background: #d9ebff;
      color: var(--ink);
    }
    .my-publications-row.selected:not(.active) td:first-child {
      box-shadow: inset 3px 0 #6aa7ff;
    }
    .my-publications-row.review-article:not(.active) td { color: #7b8796; background: #fafafa; }
    .my-publications-row.review-article.selected:not(.active) td { background: #d9ebff; color: var(--ink); }
    .my-publications-row.review-article .my-publications-title-text { color: #8b95a5; font-weight: 400; }
    .my-publications-row.review-article .my-publications-id .journal-name { color: #687484; font-weight: 400; }
    .my-publications-row.review-article .my-publications-id strong { color: #687484; font-weight: 400; }
    .my-publications-row.head-excluded:not(.active) td:not(:last-child) {
      color: rgba(102, 112, 133, 0.36);
      background: #fafafa;
    }
    .my-publications-row.head-excluded .my-publications-title-text,
    .my-publications-row.head-excluded .my-publications-id .journal-name,
    .my-publications-row.head-excluded .my-publications-id strong {
      color: rgba(102, 112, 133, 0.42);
      font-weight: 400;
    }
    .my-publications-row.head-excluded .star-button { opacity: 0.38; }
    .my-publications-row:not(.review-article) .my-publications-title-text { font-weight: 400; color: var(--ink); }
    .my-publications-row.head-excluded .my-publications-title-text,
    .my-publications-row.head-excluded .my-publications-id .journal-name,
    .my-publications-row.head-excluded .my-publications-id strong {
      color: rgba(102, 112, 133, 0.42);
      font-weight: 400;
    }
    .my-publications-row.head-excluded.selected:not(.active) td {
      background: #d9ebff;
      color: var(--ink);
    }
    .my-publications-row.active td {
      background: var(--accent);
      color: #fff;
    }
    .my-publications-row.active td:first-child {
      box-shadow: none;
    }
    .my-publications-row.active .my-publications-title-text { font-weight: 400; }
    .my-publications-row.active .my-publications-title-text,
    .my-publications-row.active .my-publications-id .journal-name,
    .my-publications-row.active .my-publications-id strong {
      color: #fff;
    }
    .my-publications-row.active .star-button,
    .my-publications-row.active .action,
    .my-publications-row.active .my-publications-head-toggle {
      color: #fff;
      border-color: rgba(255, 255, 255, 0.42);
      background: rgba(255, 255, 255, 0.12);
    }
    .my-publications-row.dragging td {
      opacity: 0.68;
      background: #ffffff;
      box-shadow: 0 10px 24px rgba(15, 23, 42, 0.16);
      transition: transform 0.12s ease, opacity 0.12s ease, box-shadow 0.12s ease;
    }
    .my-publications-row.drag-over-before td {
      transform: translateY(24px);
      box-shadow: 0 -20px 0 rgba(15, 107, 110, 0.14), inset 0 3px 0 var(--accent);
      transition: transform 0.12s ease, box-shadow 0.12s ease;
    }
    .my-publications-row.drag-over-after td {
      transform: translateY(-24px);
      box-shadow: 0 20px 0 rgba(15, 107, 110, 0.14), inset 0 -3px 0 var(--accent);
      transition: transform 0.12s ease, box-shadow 0.12s ease;
    }
    .my-publications-title-cell {
      display: flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
    }
    .my-publications-title-cell .star-button { flex: 0 0 auto; }
    .my-publications-table .action {
      min-height: 22px;
      padding: 0 7px;
    }
    .my-publications-title-text {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .my-publications-head-toggle {
      width: 100%;
      min-height: 22px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: #344054;
      font-size: 12px;
      font-weight: 400;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0 7px;
      cursor: pointer;
    }
    .my-publications-head-toggle:hover {
      color: #344054;
      background: #fff;
    }
    .my-publications-head-toggle.active {
      border-color: var(--line);
      background: #fff;
      color: var(--accent);
    }
    .my-publications-id .journal-name { color: #526175; font-style: italic; font-weight: 500; }
    .my-publications-id strong { font-weight: 750; color: var(--ink); }
    .my-publications-stats {
      grid-row: 3;
      position: relative;
      display: grid;
      grid-template-columns: minmax(120px, 0.8fr) minmax(180px, 1.18fr) minmax(180px, 1.18fr) minmax(200px, 1.28fr);
      gap: 8px;
      border-top: 0;
      background: #f2f2f2;
      padding: 6px 0 1.5px;
      height: var(--my-publications-stats-height, 126px);
      min-height: 78px;
      overflow: hidden;
      z-index: 1;
    }
    .my-publications-table-wrap + .my-publications-stats {
      display: grid;
    }
    .my-publications-stats-resizer {
      position: absolute;
      top: -5px;
      left: 42%;
      right: 42%;
      height: 10px;
      border: 0;
      background: transparent;
      cursor: row-resize;
      z-index: 2;
    }
    .my-publications-stats-resizer::before {
      content: "";
      display: none;
      position: absolute;
      left: 0;
      right: 0;
      top: 4px;
      height: 2px;
      border-radius: 999px;
      background: #cbd5e1;
    }
    .my-publications-stat {
      min-width: 0;
      min-height: 0;
      border: 1px solid #e4e7ee;
      border-radius: 8px;
      background: #fff;
      padding: 6px 10px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    .my-publications-stat strong {
      display: block;
      flex: 0 0 auto;
      position: relative;
      color: var(--ink);
      font-size: 14px;
      line-height: 1.1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .my-publications-stat span {
      display: block;
      flex: 0 0 auto;
      color: var(--muted);
      font-size: 11px;
      margin-top: 3px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .my-publications-stat-list {
      display: grid;
      align-content: start;
      gap: 3px;
      margin-top: 6px;
      min-height: 0;
      flex: 1 1 auto;
      overflow: auto;
      padding-right: 2px;
    }
    .my-publications-stat-row {
      display: grid;
      grid-template-columns: minmax(66px, auto) minmax(0, 1fr);
      gap: 8px;
      align-items: baseline;
      position: relative;
      color: #344054;
      font-size: 11px;
      line-height: 1.25;
    }
    .my-publications-stat-row b {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 650;
      color: var(--ink);
    }
    .my-publications-stat-row em {
      font-style: normal;
      color: var(--accent);
      font-weight: 700;
      min-width: 0;
      text-align: right;
      overflow-wrap: anywhere;
    }
    .my-publications-stat-filter {
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      font-weight: inherit;
      padding: 0;
      text-align: left;
      cursor: pointer;
    }
    .my-publications-stat-row:has(.my-publications-stat-filter) {
      cursor: pointer;
    }
    .my-publications-stat-filter::after,
    .my-publications-stat-total::after {
      content: "";
      position: absolute;
      inset: 0;
    }
    .my-publications-stat-filter:hover { color: var(--accent); text-decoration: underline; }
    .my-publications-stat-filter.active { color: var(--accent); }
    .my-publications-stat-total {
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      font-weight: inherit;
      padding: 0;
      text-align: left;
      cursor: pointer;
    }
    .my-publications-stat-total:hover { color: var(--accent); text-decoration: underline; }
    .my-publications-stat-row.sources-row {
      grid-template-columns: minmax(66px, auto) minmax(0, 1fr);
      align-items: start;
    }
    .my-publications-stat-row.sources-row em {
      text-align: right;
      overflow: visible;
    }
    .my-publications-stat-row.first-solo-row {
      grid-template-columns: minmax(0, 1fr) auto;
    }
    .my-publications-stat-row.first-solo-row b {
      display: inline-flex;
      align-items: baseline;
      gap: 3px;
      white-space: nowrap;
      min-width: 0;
      font-size: 10px;
    }
    .my-publications-stat-row.first-solo-row .solo-inline {
      white-space: nowrap;
    }
    .my-publications-source-list {
      display: inline-block;
      line-height: 1.25;
      white-space: nowrap;
    }
    .my-publications-source-list-line {
      display: block;
      white-space: nowrap;
    }
    .publication-role-flags {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      flex-wrap: nowrap;
      overflow-x: auto;
      margin: 0;
      max-width: 100%;
    }
    .publication-role-flag {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fbfcfe;
      padding: 3px 4px;
      color: #344054;
      font-size: 10px;
      line-height: 1.2;
      white-space: nowrap;
    }
    .publication-role-flag input { margin: 0; }
    .publication-author-list {
      display: flex;
      flex-wrap: wrap;
      gap: 5px;
      align-items: center;
    }
    .publication-author-pill {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: #344054;
      padding: 3px 8px;
      font: inherit;
      cursor: pointer;
      max-width: 100%;
    }
    .publication-author-pill.mine { font-weight: 750; color: var(--ink); }
    .publication-author-pill.marked { border-color: rgba(13, 116, 116, 0.35); background: #eef8f7; }
    .publication-author-badge {
      margin-left: 4px;
      color: var(--accent-strong);
      font-size: 9px;
      font-weight: 800;
    }
    .publication-author-menu {
      position: fixed;
      z-index: 200;
      width: 310px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 16px 42px rgba(15, 23, 42, 0.18);
      padding: 10px;
      color: var(--ink);
    }
    .publication-author-menu strong {
      display: block;
      margin-bottom: 7px;
      font-size: 12px;
    }
    .publication-author-menu label {
      display: flex;
      gap: 7px;
      align-items: center;
      padding: 5px 0;
      font-size: 12px;
      color: #344054;
    }
    .publication-author-menu input { margin: 0; }
    .publication-author-menu-row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .publication-author-menu-affiliations {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid #edf0f5;
      color: #667085;
      font-size: 11px;
      line-height: 1.35;
      max-height: 150px;
      overflow: auto;
    }
    .publication-author-menu-affiliations b {
      display: block;
      margin-bottom: 4px;
      color: var(--ink);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .02em;
    }
    .publication-author-menu-affiliations p { margin: 0 0 6px; }
    .author-affiliation-hover {
      display: inline-block;
      text-decoration: underline dotted rgba(13, 116, 116, 0.45);
      text-underline-offset: 3px;
      cursor: help;
    }
    .author-affiliation-tooltip {
      display: none;
      position: fixed;
      z-index: 240;
      width: 320px;
      overflow: visible;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 14px 36px rgba(15, 23, 42, 0.18);
      padding: 9px 10px;
      color: #344054;
      font-size: 11px;
      line-height: 1.35;
      text-align: left;
      white-space: normal;
    }
    .author-affiliation-tooltip b {
      display: block;
      margin-bottom: 5px;
      color: var(--ink);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .02em;
    }
    .author-affiliation-tooltip p { margin: 0 0 6px; }
    .author-role-symbols {
      margin-left: 2px;
      color: var(--accent-strong);
      font-size: 10px;
      font-weight: 800;
      line-height: 0;
      vertical-align: super;
    }
    .star-button {
      width: 22px;
      height: 22px;
      border: 0;
      background: transparent;
      color: #a0a7b4;
      cursor: pointer;
      font-size: 15px;
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
    .loader-backdrop {
      z-index: 95;
      align-items: flex-start;
      justify-content: center;
      padding: 64px 28px 24px;
      background: transparent;
      pointer-events: none;
    }
    .loader-modal {
      width: min(1480px, calc(100vw - 56px));
      height: min(820px, calc(100vh - 88px));
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
      pointer-events: auto;
    }
    .loader-modal-body {
      min-height: 0;
      padding: 14px;
      display: grid;
    }
    .loader-modal .loader-panel {
      border: 0;
      border-radius: 0;
      padding: 0;
      grid-template-rows: auto auto auto minmax(0, 1fr);
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
      grid-template-columns: minmax(280px, 1fr) 90px auto auto 104px;
      grid-template-areas:
        "path mode choose run stop"
        "path mode choose run delete";
      gap: 8px;
      align-items: center;
    }
    .loader-form input { grid-area: path; }
    .loader-form select { grid-area: mode; }
    #libraryChooseFolder { grid-area: choose; }
    #libraryRunImport { grid-area: run; }
    #libraryStopImport { grid-area: stop; width: 104px; min-height: 30px; align-self: end; }
    #libraryDeleteImport { grid-area: delete; width: 104px; min-height: 30px; align-self: start; }
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
      grid-template-columns: minmax(0, 1fr) minmax(360px, 480px);
      gap: 12px;
    }
    .loader-console-wrap {
      position: relative;
      min-height: 0;
      overflow: hidden;
    }
    .loader-console {
      height: 100%;
      min-height: 0;
      overflow: auto;
      border: 1px solid #1f2937;
      border-radius: 8px;
      background: #111827;
      color: #e5e7eb;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px;
      line-height: 1.25;
      padding: 8px;
      white-space: normal;
      user-select: text;
    }
    .loader-line {
      display: grid;
      grid-template-columns: 56px 112px minmax(0, 1fr);
      gap: 6px;
      align-items: start;
      padding: 3px 5px;
      border-left: 3px solid transparent;
      border-radius: 5px;
      line-height: 1.22;
    }
    .loader-line + .loader-line { margin-top: 2px; }
    .loader-line.file-start { margin-top: 9px; }
    .loader-line.folder-enter { margin-top: 13px; margin-bottom: 5px; }
    .loader-line.enter { margin-top: 13px; margin-bottom: 5px; }
    .loader-line:first-child { margin-top: 0; }
    .loader-line.scan { color: #bfdbfe; border-left-color: #60a5fa; background: rgba(96, 165, 250, 0.08); }
    .loader-line.doi-ok { color: #bbf7d0; border-left-color: #22c55e; background: rgba(34, 197, 94, 0.10); }
    .loader-line.doi-missing { color: #fde68a; border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.12); }
    .loader-line.metadata { color: #ddd6fe; border-left-color: #a78bfa; background: rgba(167, 139, 250, 0.10); }
    .loader-line.import { color: #bae6fd; border-left-color: #38bdf8; background: rgba(56, 189, 248, 0.08); }
    .loader-line.enter { color: #fed7aa; border-left-color: #f97316; background: rgba(249, 115, 22, 0.10); }
    .loader-line.file { color: #d1d5db; border-left-color: #9ca3af; background: rgba(156, 163, 175, 0.08); }
    .loader-line.done { color: #ccfbf1; border-left-color: #14b8a6; background: rgba(20, 184, 166, 0.12); }
    .loader-line.error { color: #fecaca; border-left-color: #ef4444; background: rgba(239, 68, 68, 0.12); }
    .loader-line.warn { color: #fde68a; border-left-color: #f59e0b; background: rgba(245, 158, 11, 0.12); }
    .loader-badge {
      display: inline-flex;
      justify-content: center;
      min-width: 50px;
      padding: 1px 5px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.10);
      color: currentColor;
      font-size: 10px;
      font-weight: 700;
      line-height: 1.5;
      text-transform: uppercase;
    }
    .loader-time { color: #9ca3af; font-variant-numeric: tabular-nums; }
    .loader-message { min-width: 0; overflow-wrap: anywhere; }
    .loader-message {
      white-space: pre-wrap;
    }
    .loader-token-doi {
      color: #ffffff;
      font-weight: 700;
      background: rgba(255, 255, 255, 0.14);
      border-radius: 4px;
      padding: 0 3px;
    }
    .loader-jump-latest {
      position: absolute;
      right: 16px;
      bottom: 14px;
      width: 34px;
      height: 34px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.24);
      background: rgba(15, 23, 42, 0.86);
      color: #e5e7eb;
      box-shadow: 0 10px 22px rgba(0, 0, 0, 0.28);
      cursor: pointer;
      display: none;
      align-items: center;
      justify-content: center;
      font-size: 18px;
      line-height: 1;
      z-index: 4;
    }
    .loader-jump-latest.open { display: flex; }
    .loader-jump-latest:hover { border-color: #93c5fd; color: #bfdbfe; }
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
      grid-template-columns: 30px minmax(0, 1fr) 8px minmax(280px, var(--library-detail-width, 420px));
      grid-template-rows: minmax(0, 1fr) 26px;
      column-gap: 0;
      row-gap: 0;
      align-items: stretch;
      height: 100%;
      max-height: 100%;
      min-height: 0;
      margin-left: -30px;
      width: calc(100% + 30px);
      overflow: visible;
      outline: none;
      background: #fff;
      position: relative;
    }
    .library-shell::before {
      content: "";
      position: absolute;
      top: 0;
      bottom: 26px;
      left: 30px;
      width: 1px;
      background: #d8d8dc;
      pointer-events: none;
      z-index: 8;
    }
    .library-main-area {
      grid-column: 2;
      grid-row: 1;
      min-width: 0;
      min-height: 0;
      height: 100%;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
    }
    .library-main-area > .library-columns,
    .library-main-area > .library-search-results {
      grid-row: 2;
    }
    .library-shell > .library-pane {
      margin-left: 0;
    }
    .my-publications-shell {
      grid-template-columns: minmax(0, 1fr) minmax(260px, 340px);
      grid-template-rows: minmax(0, 1fr) 8px;
      column-gap: 11px;
      margin-left: -18px;
      width: calc(100% + 18px);
      overflow: hidden;
      background: #f2f2f2;
    }
    .my-publications-shell::before {
      display: none;
    }
    .my-publications-shell::after {
      display: none;
    }
    .my-publications-shell > .library-pane {
      margin-left: 0;
    }
    .my-publications-shell > .library-pane {
      grid-column: 2;
      border-left: 0;
      background: #f2f2f2;
      grid-template-rows: minmax(0, 1fr);
    }
    .my-publications-shell .library-pane-header {
      display: none;
    }
    .my-publications-shell .library-detail {
      background: #f2f2f2;
      padding-top: 4px;
      padding-bottom: 1px;
    }
    .my-publications-shell .library-detail > :last-child {
      margin-bottom: 0;
    }
    .my-publications-shell .library-detail .bibtex-box,
    .my-publications-shell .library-detail .citation-panel,
    .my-publications-shell .library-detail .library-detail-abstract,
    .my-publications-shell .library-detail .library-detail-authors,
    .my-publications-shell .library-detail .library-detail-doi input,
    .my-publications-shell .library-detail .library-detail-figure,
    .my-publications-shell .library-detail .library-detail-figure img,
    .my-publications-shell .library-detail .publication-manual-metadata,
    .my-publications-shell .library-detail .publication-manual-metadata input,
    .my-publications-shell .library-detail .publication-manual-metadata textarea,
    .my-publications-shell .library-detail .semantic-detail-row,
    .my-publications-shell .library-detail .semantic-influential-card {
      background: #f2f2f2;
    }
    .my-publications-shell .library-detail .action,
    .my-publications-shell .library-detail .action.danger,
    .my-publications-shell .library-detail .citation-source-cell,
    .my-publications-shell .library-detail .publication-author-pill,
    .my-publications-shell .library-detail .publication-role-flag {
      background: #d9d9d9;
      color: #2f3948;
      border: 0;
      box-shadow: none;
    }
    .my-publications-shell .library-detail .publication-author-pill.marked {
      background: #d9d9d9;
      border: 0;
      box-shadow: none;
    }
    .my-publications-shell .library-detail .citation-source-cell:hover {
      background: #d9d9d9;
    }
    .my-publications-shell .library-detail .action,
    .my-publications-shell .library-detail .action.danger,
    .my-publications-shell .library-detail .citation-source-cell,
    .my-publications-shell .library-detail .publication-author-pill {
      border: 0;
      box-shadow: none;
    }
    .my-publications-shell .library-detail .citation-source-cell.active {
      border: 0;
      box-shadow: none;
    }
    .library-columns {
      min-width: 0;
      min-height: 0;
      height: 100%;
      max-height: 100%;
      align-self: stretch;
      flex: 1 1 auto;
      border: 0;
      border-radius: 0;
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
      grid-template-rows: minmax(0, 1fr);
      border-right: 0;
      overflow: hidden;
      background: #fff;
      position: relative;
    }
    .library-column > .library-pane-header { display: none; }
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
      width: 1px;
      background: #d8d8dc;
    }
    .library-column-resizer:hover::after,
    .library-column.resizing .library-column-resizer::after {
      background: var(--accent);
    }
    .library-detail-divider {
      grid-column: 3;
      grid-row: 1;
      height: 100%;
      min-height: 0;
      position: relative;
      cursor: col-resize;
      background: #fff;
      z-index: 4;
    }
    .library-detail-divider::after {
      content: "";
      position: absolute;
      top: 0;
      bottom: 0;
      left: 3px;
      width: 1px;
      background: #d8d8dc;
    }
    .library-detail-divider:hover::after,
    .library-detail-divider.resizing::after {
      background: var(--accent);
    }
    .library-pane {
      min-width: 0;
      min-height: 0;
      height: 100%;
      max-height: 100%;
      align-self: stretch;
      border: 0;
      border-radius: 0;
      background: #fff;
      overflow: hidden;
      display: grid;
      grid-template-rows: minmax(0, 1fr);
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
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .library-pane-header-title { min-width: 0; }
    .library-pane-loader {
      flex: 0 0 auto;
      min-height: 24px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 0 8px;
      cursor: pointer;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: none;
    }
    .library-pane-loader:hover,
    .library-pane-loader.active {
      border-color: var(--accent);
      color: var(--accent);
      background: #f0f9f9;
    }
    .library-tab-context-menu {
      position: fixed;
      z-index: 120;
      min-width: 132px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: var(--shadow);
      padding: 5px;
      display: none;
    }
    .library-tab-context-menu.open { display: grid; }
    .library-tab-context-menu button {
      min-height: 30px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--ink);
      padding: 0 10px;
      text-align: left;
      cursor: pointer;
      font-size: 13px;
    }
    .library-tab-context-menu button:hover { background: #eef2f7; }
    .finder-drop-modal-backdrop {
      position: fixed;
      inset: 0;
      z-index: 300;
      background: rgba(15, 23, 42, 0.22);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .finder-drop-modal {
      width: min(440px, 100%);
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      box-shadow: 0 24px 70px rgba(15, 23, 42, 0.22);
      padding: 16px;
      color: var(--ink);
    }
    .finder-drop-modal h2 {
      margin: 0 0 8px;
      font-size: 16px;
      letter-spacing: 0;
    }
    .finder-drop-modal p {
      margin: 0 0 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .finder-drop-paths {
      max-height: 112px;
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfe;
      padding: 8px;
      color: #475467;
      font-size: 12px;
      line-height: 1.35;
      word-break: break-all;
    }
    .finder-drop-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      margin-top: 14px;
    }
    .finder-drop-actions button {
      min-height: 32px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fff;
      color: var(--ink);
      padding: 0 12px;
      cursor: pointer;
      font-size: 13px;
      font-weight: 700;
    }
    .finder-drop-actions button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: #fff;
    }
    .library-column-body {
      min-height: 0;
      overflow-y: auto;
      overscroll-behavior: contain;
      padding: 4px 8px;
      -webkit-user-select: none;
      user-select: none;
    }
    .library-row {
      width: 100%;
      height: 30px;
      border: 1px solid transparent;
      border-radius: 5px;
      background: transparent;
      color: var(--ink);
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr) 16px;
      gap: 6px;
      align-items: center;
      padding: 2px 8px;
      text-align: left;
      cursor: default;
      font-size: 13px;
      line-height: 1.15;
      -webkit-user-select: none;
      user-select: none;
    }
    .library-row + .library-row { margin-top: 1px; }
    .library-row:hover { background: #f2f2f3; }
    .library-row.range-selected { background: #d9ebff; border-color: #b9d7fb; }
    .library-row.range-selected .library-meta { color: #45637f; }
    .library-row.active:not(.range-selected) { background: #0b67d8; border-color: #0b67d8; color: #fff; }
    .library-row.path-parent { background: #dedede; border-color: #dedede; color: #1f2328; }
    .library-row.drag-over { border-color: var(--accent); background: #eef9f8; }
    .library-row.active:not(.range-selected) .library-meta { color: rgba(255, 255, 255, 0.86); }
    .library-row.path-parent .library-meta { color: #717171; }
    .library-shell.finder-drag-over .library-columns {
      border-color: var(--accent);
      box-shadow: inset 0 0 0 2px rgba(20, 184, 166, 0.18);
    }
    .library-row.drag-reorder-before { border-top-color: var(--accent); border-top-width: 2px; }
    .library-row.drag-reorder-after { border-bottom-color: var(--accent); border-bottom-width: 2px; }
    .library-row.special-folder { color: #667085; }
    .library-row.special-folder.active:not(.range-selected) { color: #fff; }
    .selection-marquee {
      position: fixed;
      z-index: 10000;
      pointer-events: none;
      border: 1px solid #0b67d8;
      background: rgba(11, 103, 216, 0.14);
      border-radius: 3px;
      box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.45) inset;
    }
    body.marquee-selecting,
    body.marquee-selecting * {
      -webkit-user-select: none !important;
      user-select: none !important;
      cursor: crosshair !important;
    }
    .library-row.special-folder.path-parent { color: #1f2328; }
    .library-entry-icon {
      width: 18px;
      height: 16px;
      position: relative;
      display: inline-block;
      justify-self: center;
      flex: 0 0 auto;
    }
    .library-entry-icon.native-file-drag-handle { cursor: grab; }
    .library-entry-icon.native-file-drag-handle:active { cursor: grabbing; }
    .library-entry-icon.folder::before {
      content: "";
      position: absolute;
      left: 1px;
      top: 6px;
      width: 17px;
      height: 10px;
      border-radius: 3px 3px 2px 2px;
      background: linear-gradient(180deg, #62b4f9 0%, #2384dc 100%);
      box-shadow: inset 0 0 0 1px rgba(20, 89, 150, 0.24);
    }
    .library-entry-icon.folder::after {
      content: "";
      position: absolute;
      left: 2px;
      top: 3px;
      width: 8px;
      height: 5px;
      border-radius: 3px 3px 0 0;
      background: #78c3ff;
      box-shadow: inset 0 0 0 1px rgba(20, 89, 150, 0.16);
    }
    .library-entry-icon.trash::before {
      content: "";
      position: absolute;
      left: 4px;
      top: 6px;
      width: 11px;
      height: 9px;
      border: 1.5px solid #667085;
      border-top: 0;
      border-radius: 0 0 3px 3px;
      background: linear-gradient(180deg, #f9fafb 0%, #e4e7ec 100%);
    }
    .library-entry-icon.trash::after {
      content: "";
      position: absolute;
      left: 3px;
      top: 3px;
      width: 13px;
      height: 3px;
      border-top: 1.5px solid #667085;
      border-radius: 2px;
      box-shadow: 4px -2px 0 -1px #667085;
    }
    .library-entry-icon.linked-document {
      width: 18px;
      height: 16px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 10px;
      line-height: 1;
      filter: saturate(0.82);
    }
    .library-entry-icon.linked-document::before {
      content: "🔗";
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
    .library-meta {
      color: #8a8a8a;
      font-size: 18px;
      line-height: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      justify-self: end;
    }
    .library-path-bar {
      grid-column: 2 / 5;
      grid-row: 2;
      min-width: 0;
      height: 26px;
      border-top: 1px solid #d8d8dc;
      background: #fff;
      color: #6e6e73;
      display: flex;
      align-items: flex-end;
      gap: 6px;
      padding: 0 10px 4px;
      font-size: 12px;
      line-height: 12px;
      white-space: nowrap;
      overflow: hidden;
      user-select: text;
    }
    .library-path-parts {
      min-width: 0;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      overflow: hidden;
    }
    .library-activity-status {
      margin-left: auto;
      max-width: min(360px, 42vw);
      min-height: 18px;
      display: inline-flex;
      align-items: center;
      justify-content: flex-end;
      gap: 6px;
      color: #667085;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      flex: 0 1 auto;
      user-select: none;
      border-radius: 999px;
      padding: 2px 10px;
      background: transparent;
      border: 1px solid transparent;
      transition: background 160ms ease, border-color 160ms ease, color 160ms ease, box-shadow 160ms ease;
    }
    .library-activity-status:empty {
      display: none;
    }
    .library-activity-status.live {
      color: var(--accent-strong);
      font-weight: 700;
      background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(224,245,241,0.72) 18%, rgba(219,243,239,0.95) 50%, rgba(224,245,241,0.72) 82%, rgba(255,255,255,0) 100%);
      border-color: rgba(15, 107, 110, 0.16);
      box-shadow: 0 0 0 1px rgba(15, 107, 110, 0.04);
      animation: libraryActivityGlow 1.45s ease-in-out infinite;
    }
    .library-activity-status.live::after {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 999px;
      background: var(--accent);
      box-shadow: 0 0 0 0 rgba(15, 107, 110, 0.35);
      animation: livePulse 1.1s infinite;
      flex: 0 0 auto;
    }
    .library-activity-status.ok {
      color: #14845f;
      background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(229,246,238,0.8) 20%, rgba(230,248,239,0.95) 50%, rgba(229,246,238,0.8) 80%, rgba(255,255,255,0) 100%);
      border-color: rgba(20, 132, 95, 0.12);
    }
    .library-activity-status.err {
      color: #b42318;
      background: linear-gradient(90deg, rgba(255,255,255,0) 0%, rgba(255,235,231,0.82) 20%, rgba(255,239,236,0.98) 50%, rgba(255,235,231,0.82) 80%, rgba(255,255,255,0) 100%);
      border-color: rgba(180, 35, 24, 0.12);
    }
    @keyframes livePulse {
      0%, 100% { transform: scale(0.78); opacity: 0.55; box-shadow: 0 0 0 0 rgba(15, 107, 110, 0.28); }
      50% { transform: scale(1); opacity: 1; box-shadow: 0 0 0 5px rgba(15, 107, 110, 0); }
    }
    @keyframes libraryActivityGlow {
      0%, 100% { filter: brightness(0.98); }
      50% { filter: brightness(1.06); }
    }
    .library-path-item {
      min-width: 0;
      display: inline-flex;
      align-items: center;
      gap: 5px;
      line-height: 12px;
    }
    .library-path-icon {
      transform: scale(0.7);
      transform-origin: center;
    }
    .library-path-part {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .library-path-separator {
      color: #a0a0a5;
      flex: 0 0 auto;
    }
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
      padding: 14px 12px;
      color: #344054;
      font-size: 13px;
      line-height: 1.5;
    }
    .library-detail h3 {
      margin: 0 0 10px;
      color: var(--ink);
      font-size: 17px;
      line-height: 1.25;
      letter-spacing: 0;
      max-width: 100%;
    }
    .library-detail dl {
      display: grid;
      grid-template-columns: minmax(76px, 0.22fr) minmax(0, 1fr);
      gap: 8px 18px;
      margin: 14px 0;
      max-width: 100%;
    }
    .library-detail dt { color: var(--muted); }
    .library-detail dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
    .library-detail-title {
      color: var(--ink);
      font-weight: 650;
      line-height: 1.35;
    }
    .library-detail-doi {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 6px;
    }
    .library-detail-doi input {
      min-width: 0;
      flex: 1 1 auto;
      min-height: 28px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 8px;
      font-size: 12px;
      background: #fff;
    }
    .library-detail-doi button {
      flex: 0 0 auto;
      min-height: 28px;
    }
    .library-file-line {
      display: block;
      margin-bottom: 4px;
    }
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
    .library-detail-abstract,
    .library-detail-authors {
      margin: 12px 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fbfcfe;
    }
    .library-detail-abstract strong,
    .library-detail-authors strong {
      display: block;
      margin-bottom: 6px;
      color: var(--ink);
    }
    .library-detail-abstract p {
      margin: 0;
      color: #344054;
    }
    .publication-manual-metadata {
      margin: 12px 0;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 7px;
      background: #fbfcfe;
    }
    .publication-manual-metadata strong {
      display: block;
      margin-bottom: 8px;
      color: var(--ink);
    }
    .publication-manual-metadata label {
      display: block;
      margin-bottom: 7px;
      color: #526071;
      font-size: 11px;
      font-weight: 700;
    }
    .publication-manual-metadata input,
    .publication-manual-metadata textarea {
      display: block;
      width: 100%;
      margin-top: 3px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 6px 8px;
      color: var(--ink);
      background: #fff;
      font: inherit;
      font-size: 12px;
      resize: vertical;
    }
    .publication-manual-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 7px;
    }
    .publication-manual-actions {
      display: flex;
      justify-content: flex-end;
      margin-top: 4px;
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
    .citation-comments-row {
      display: flex;
      justify-content: flex-start;
      margin-top: 8px;
    }
    .citation-comments-button.action,
    .my-publications-shell .library-detail .citation-comments-button.action {
      border: 0;
      background: var(--accent) !important;
      color: #fff !important;
      box-shadow: none;
    }
    .citation-comments-button.action:hover,
    .citation-comments-button.action:focus-visible,
    .my-publications-shell .library-detail .citation-comments-button.action:hover,
    .my-publications-shell .library-detail .citation-comments-button.action:focus-visible {
      background: var(--accent-strong) !important;
      color: #fff !important;
      box-shadow: none;
    }
    .citation-source-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 5px;
      margin-top: 10px;
    }
    .citation-source-cell {
      border: 1px solid #edf0f5;
      border-radius: 6px;
      padding: 5px 5px;
      background: #fbfcfe;
      min-width: 0;
      text-align: left;
      cursor: pointer;
    }
    .citation-source-cell:hover { border-color: #b9c7dd; background: #f6f9fe; }
    .citation-source-cell.active { border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }
    .citation-source-cell b {
      display: block;
      color: var(--ink);
      font-size: 10px;
      line-height: 1.12;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .citation-source-cell span { color: var(--accent-strong); font-weight: 750; font-size: 12px; }
    .citation-source-cell small { display: block; font-size: 9px; line-height: 1.15; color: var(--muted); }
    .semantic-panel,
    .ads-panel,
    .pubmed-panel {
      display: none;
      margin-top: 10px;
      border-top: 1px solid #edf0f5;
      padding-top: 9px;
      color: #344054;
      font-size: 12px;
      line-height: 1.45;
    }
    .pubmed-panel { display: block; }
    .citation-panel[data-active-citation-source="semantic_scholar"] .semantic-panel { display: block; }
    .citation-panel[data-active-citation-source="ads"] .ads-panel { display: block; }
    .semantic-panel strong,
    .ads-panel strong,
    .pubmed-panel strong { color: var(--ink); }
    .semantic-panel p,
    .ads-panel p,
    .pubmed-panel p { margin: 5px 0 0; }
    .semantic-detail-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      margin-top: 8px;
    }
    .semantic-detail-row {
      border: 1px solid #edf0f5;
      border-radius: 6px;
      background: #fbfcfe;
      padding: 6px 7px;
      min-width: 0;
    }
    .semantic-detail-row b {
      display: block;
      color: var(--muted);
      font-size: 10px;
      text-transform: uppercase;
      letter-spacing: .02em;
    }
    .semantic-detail-row span {
      display: block;
      margin-top: 2px;
      color: var(--ink);
      overflow-wrap: anywhere;
    }
    .semantic-influential-button {
      border: 0;
      background: transparent;
      color: var(--accent-strong);
      font: inherit;
      font-weight: 750;
      padding: 0;
      cursor: pointer;
      text-align: left;
    }
    .semantic-influential-button:hover { text-decoration: underline; }
    .semantic-influential-results {
      margin-top: 10px;
      display: grid;
      gap: 8px;
    }
    .semantic-influential-card {
      border: 1px solid #edf0f5;
      border-radius: 7px;
      background: #fbfcfe;
      padding: 8px;
    }
    .semantic-influential-card > strong {
      display: block;
      color: var(--ink);
      font-size: 12px;
      line-height: 1.3;
    }
    .semantic-influential-meta {
      margin-top: 3px;
      color: var(--muted);
      font-size: 11px;
    }
    .semantic-influential-context {
      margin: 7px 0 0;
      padding-left: 9px;
      border-left: 3px solid #d6e4ff;
      color: #344054;
    }
    .semantic-influential-context + .semantic-influential-context { margin-top: 5px; }
    .semantic-tags { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
    .semantic-tag {
      border: 1px solid #d6e4ff;
      border-radius: 999px;
      background: #f4f7ff;
      color: #315193;
      padding: 2px 7px;
      font-size: 11px;
    }
    a.semantic-tag:hover { text-decoration: none; border-color: #9bbcff; }
    .ads-panel .semantic-tag {
      border-color: #d8c6ff;
      background: #f7f3ff;
      color: #4c2d86;
    }
    .library-detail-status { margin-top: 8px; min-height: 18px; color: var(--muted); }
    .library-detail-status.ok { color: #137333; }
    .library-detail-status.err { color: #b42318; }
    .library-confirm-backdrop {
      position: fixed;
      inset: 0;
      z-index: 180;
      display: grid;
      place-items: center;
      background: rgba(31, 35, 40, 0.24);
    }
    .library-confirm-dialog {
      width: min(620px, calc(100vw - 44px));
      max-height: min(520px, calc(100vh - 80px));
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      border: 1px solid rgba(17, 24, 39, 0.16);
      border-radius: 10px;
      background: #f8f8f8;
      box-shadow: 0 22px 70px rgba(15, 23, 42, 0.24);
      overflow: hidden;
    }
    .library-confirm-dialog header {
      padding: 16px 18px 10px;
      font-size: 17px;
      font-weight: 760;
      color: var(--ink);
    }
    .library-confirm-body {
      padding: 0 18px 14px;
      color: #475467;
      font-size: 13px;
      line-height: 1.45;
      overflow: auto;
    }
    .library-confirm-paths {
      margin: 10px 0 0;
      padding: 10px;
      border: 1px solid rgba(15, 23, 42, 0.1);
      border-radius: 7px;
      background: #fff;
      color: #344054;
      font: 12px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
    .library-confirm-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      padding: 12px 18px 16px;
      border-top: 1px solid rgba(15, 23, 42, 0.09);
      background: #f2f2f2;
    }
    .library-confirm-actions button {
      min-height: 30px;
      border: 0;
      border-radius: 7px;
      background: #d9d9d9;
      color: #263241;
      padding: 0 13px;
      font-weight: 650;
      cursor: pointer;
    }
    .library-confirm-actions button.danger {
      background: #b42318;
      color: #fff;
    }
    .library-context-menu {
      position: fixed;
      z-index: 50;
      display: none;
      width: fit-content;
      min-width: 0;
      max-width: none;
      border: 1px solid rgba(0, 0, 0, 0.16);
      border-radius: 8px;
      background: rgba(229, 229, 229, 0.96);
      box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
      padding: 5px 6px;
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
    }
    .library-context-menu.open { display: inline-grid; }
    .library-context-menu button {
      width: auto;
      min-width: 100%;
      min-height: 24px;
      border: 0;
      border-radius: 5px;
      background: transparent;
      color: #1f2328;
      text-align: left;
      padding: 2px 12px;
      font-size: 12.5px;
      font-weight: 400;
      line-height: 1.15;
      white-space: nowrap;
      cursor: pointer;
    }
    .library-context-menu button:hover { background: rgba(0, 0, 0, 0.08); }
    .library-context-menu button[data-action="delete-entry"],
    .library-context-menu button[data-action="delete-file-entry"],
    .library-context-menu button[data-action="delete-special-original-files"],
    .library-context-menu button[data-action="remove-special-library"],
    .library-context-menu button[data-action="delete-my-publication"] { color: #1f2328; }
    .library-context-menu button[data-action="delete-entry"]:hover,
    .library-context-menu button[data-action="delete-file-entry"]:hover,
    .library-context-menu button[data-action="delete-special-original-files"]:hover,
    .library-context-menu button[data-action="remove-special-library"]:hover,
    .library-context-menu button[data-action="delete-my-publication"]:hover { background: rgba(0, 0, 0, 0.08); }
    .my-publication-context-menu {
      min-width: 0;
    }
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
      overflow: visible;
      padding-right: 0;
    }
    .app.deep-survey-mode #papers {
      display: none;
    }
    .papers.deep-survey-view {
      display: block;
      height: 100%;
      min-height: 0;
      overflow: hidden;
      padding-right: 0;
      background: linear-gradient(to right, #f0f2f5 0 220px, #fbfcfd 220px);
    }
    .deep-survey-host {
      display: none;
      height: 100%;
      min-height: 0;
      overflow: hidden;
      background: linear-gradient(to right, #f0f2f5 0 220px, #fbfcfd 220px);
    }
    .app.deep-survey-mode .deep-survey-host {
      display: block;
      grid-column: 1;
      grid-row: 1 / -1;
    }
    .deep-survey-frame {
      width: 100%;
      height: 100%;
      min-height: 0;
      border: 0;
      display: block;
      background: linear-gradient(to right, #f0f2f5 0 220px, #fbfcfd 220px);
    }
    .deep-survey-loading {
      min-height: 220px;
      display: grid;
      place-items: center;
      color: var(--muted);
      font-size: 14px;
    }
    .paper {
      position: relative;
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 16px;
      outline: 0;
      transition: border-color 120ms ease, box-shadow 120ms ease, background 120ms ease;
      cursor: pointer;
    }
    .paper.report-selected {
      border-color: rgba(15, 107, 110, 0.68);
      background: #f7fcfb;
      box-shadow: 0 0 0 2px rgba(15, 107, 110, 0.18), var(--shadow);
    }
    .paper.report-selected::after {
      content: "";
      position: absolute;
      inset: 7px;
      border: 1px solid rgba(15, 107, 110, 0.22);
      border-radius: 6px;
      pointer-events: none;
    }
    .paper.late-unread::before {
      content: "";
      position: absolute;
      top: 10px;
      left: 10px;
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: #2563eb;
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18);
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
    button.action.citation-comments-button,
    .my-publications-shell .library-detail button.action.citation-comments-button,
    button.action.citation-comments-button:hover,
    button.action.citation-comments-button:active,
    button.action.citation-comments-button:focus,
    button.action.citation-comments-button:focus-visible,
    .my-publications-shell .library-detail button.action.citation-comments-button:hover,
    .my-publications-shell .library-detail button.action.citation-comments-button:active,
    .my-publications-shell .library-detail button.action.citation-comments-button:focus,
    .my-publications-shell .library-detail button.action.citation-comments-button:focus-visible {
      border: 0 !important;
      background: #0f6b6e !important;
      background-color: #0f6b6e !important;
      background-image: none !important;
      color: #fff !important;
      -webkit-text-fill-color: #fff !important;
      box-shadow: none !important;
      text-shadow: none !important;
    }
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
      z-index: 90;
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
    .analysis-body h4 { font-size: 13px; margin: 12px 0 4px; letter-spacing: 0; }
    .analysis-body p { margin: 8px 0; }
    .analysis-body ul { margin: 8px 0 8px 20px; padding: 0; }
    .analysis-body li { margin: 4px 0; }
    .analysis-body a { color: var(--accent); font-weight: 650; text-decoration: none; }
    .analysis-body a:hover { text-decoration: underline; }
    .analysis-body blockquote.citation-context {
      margin: 8px 0 14px;
      padding: 10px 12px;
      border-left: 4px solid var(--accent);
      border-radius: 7px;
      background: #eef6ff;
      color: #1f3b57;
      font-size: 13px;
      line-height: 1.55;
    }
    .analysis-body blockquote.citation-context strong {
      display: inline-block;
      margin-right: 6px;
      color: #0f3d6e;
    }
    .analysis-body blockquote.context-background { border-left-color: #3866ff; background: #eef3ff; }
    .analysis-body blockquote.context-methodology { border-left-color: #0f6b6e; background: #eaf7f5; }
    .analysis-body blockquote.context-result { border-left-color: #9b5de5; background: #f4edff; }
    .analysis-body blockquote.context-metadata { border-left-color: #d97706; background: #fff6e6; }
    .analysis-body blockquote.context-positive { border-left-color: #0f766e; background: #edfafa; color: #174a43; }
    .analysis-body blockquote.context-strongest { border-left-color: #7c3aed; background: #f5f0ff; color: #3f2a6f; }
    .analysis-body blockquote.context-critical,
    .analysis-body blockquote.context-cautionary { border-left-color: #b45309; background: #fff7ed; color: #6f3a12; }
    .analysis-body.comments-report {
      padding: 0 18px 18px;
      background: linear-gradient(#ffffff, #fbfcfe);
    }
    .analysis-body.comments-report h1 {
      margin-top: 4px;
      padding-bottom: 8px;
      border-bottom: 1px solid #e5e7eb;
    }
    .analysis-body.comments-report h2 {
      margin: 20px 0 10px;
      padding: 8px 10px;
      border-radius: 7px;
      background: #f1f5f9;
      color: #1f2937;
    }
    .analysis-body.comments-report h3 {
      margin: 14px 0 8px;
      color: #0f6b6e;
      font-size: 14px;
    }
    .analysis-body.comments-report h4 {
      margin: 12px 0 0;
      padding: 8px 10px;
      border: 1px solid #e5e7eb;
      border-bottom: 0;
      border-radius: 7px 7px 0 0;
      background: #fff;
      color: var(--ink);
      line-height: 1.4;
    }
    .analysis-body.comments-report h4 + ul {
      margin: 0 0 0;
      padding: 8px 10px 8px 28px;
      border: 1px solid #e5e7eb;
      border-top: 0;
      background: #fff;
    }
    .analysis-body.comments-report h4 + ul + blockquote.citation-context {
      margin-top: 0;
      border-radius: 0 0 7px 7px;
    }
    .analysis-body code {
      background: #eef2f7;
      border-radius: 4px;
      padding: 1px 4px;
      font-size: 0.92em;
    }
    .settings-backdrop {
      position: fixed;
      inset: 0;
      z-index: 70;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(15, 23, 42, 0.28);
    }
    .settings-backdrop.open { display: flex; }
    .settings-modal {
      width: min(560px, calc(100vw - 40px));
      max-height: calc(100vh - 60px);
      overflow: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      box-shadow: 0 24px 70px rgba(15, 23, 42, 0.22);
    }
    .settings-modal-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 14px;
      padding: 16px 18px 12px;
      border-bottom: 1px solid var(--line);
    }
    .settings-modal-head h2 { margin: 0; font-size: 18px; letter-spacing: 0; }
    .settings-modal-head p { margin: 4px 0 0; color: var(--muted); font-size: 13px; line-height: 1.45; }
    .settings-modal-close { min-width: 30px; min-height: 30px; border: 1px solid var(--line); border-radius: 7px; background: #fff; cursor: pointer; }
    .settings-modal-body { padding: 16px 18px 18px; }
    .settings-backdrop.loader-backdrop {
      z-index: 95;
      align-items: flex-start;
      justify-content: center;
      padding: 64px 28px 18px;
      background: transparent;
      pointer-events: none;
    }
    .settings-backdrop.loader-backdrop.open {
      display: flex;
    }
    .settings-modal.loader-modal {
      width: min(1480px, calc(100vw - 56px));
      height: min(860px, calc(100vh - 76px));
      max-height: none;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      pointer-events: auto;
    }
    .settings-modal-body.loader-modal-body {
      min-height: 0;
      padding: 14px;
      display: grid;
      overflow: hidden;
    }
    .settings-modal.loader-modal .loader-main {
      grid-template-columns: minmax(0, 1fr) minmax(360px, 480px);
    }
    .app.loader-window-mode {
      display: block;
      height: 100vh;
      background: #f2f2f2;
      overflow: hidden;
    }
    .app.loader-window-mode::before {
      display: none;
    }
    body.loader-window-body .window-drag-region {
      display: none;
    }
    .app.loader-window-mode .sidebar,
    .app.loader-window-mode .sidebar-edge,
    .app.loader-window-mode .workspace,
    .app.loader-window-mode .internal-browser,
    .app.loader-window-mode .library-quicklook,
    .app.loader-window-mode #citationSettingsBackdrop {
      display: none !important;
    }
    .app.loader-window-mode .main {
      height: 100vh;
      padding: 0;
      background: #f2f2f2;
      overflow: hidden;
    }
    .app.loader-window-mode .settings-backdrop.loader-backdrop {
      position: fixed;
      inset: 0;
      z-index: 1;
      display: flex;
      align-items: stretch;
      justify-content: stretch;
      padding: 0;
      background: #f2f2f2;
      pointer-events: auto;
    }
    .app.loader-window-mode .settings-modal.loader-modal {
      width: 100%;
      height: 100%;
      border: 0;
      border-radius: 0;
      box-shadow: none;
      grid-template-rows: minmax(0, 1fr);
    }
    .app.loader-window-mode .settings-modal.loader-modal .settings-modal-head {
      display: none !important;
      height: 0 !important;
      min-height: 0 !important;
      padding: 0 !important;
      border: 0 !important;
      overflow: hidden !important;
      background: transparent !important;
    }
    .app.loader-window-mode .settings-modal.loader-modal .settings-modal-close {
      display: none;
    }
    .app.loader-window-mode .settings-modal-body.loader-modal-body {
      height: 100%;
      box-sizing: border-box;
      padding: 10px 12px 12px;
    }
    .app.loader-window-mode .loader-panel {
      gap: 8px;
      height: 100%;
      min-height: 0;
      grid-template-rows: auto auto auto minmax(0, 1fr);
    }
    .app.loader-window-mode .loader-form {
      gap: 6px;
    }
    .app.loader-window-mode .loader-progress-track {
      height: 6px;
    }
    .app.loader-window-mode .loader-main {
      grid-row: 3 / -1;
      min-height: 0;
      height: 100%;
    }
    .app.loader-window-mode .loader-panel:has(.loader-result) .loader-main {
      grid-row: 4 / -1;
    }
    .app.loader-window-mode .loader-console-wrap,
    .app.loader-window-mode .loader-side {
      height: 100%;
    }
    .citation-source-setting {
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      padding: 12px;
      background: #fbfcfe;
    }
    .citation-source-setting + .citation-source-setting { margin-top: 10px; }
    .citation-source-setting-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 8px;
    }
    .citation-source-setting-head strong { color: var(--ink); }
    .citation-source-setting-head span { color: var(--muted); font-size: 12px; }
    .citation-source-setting p { margin: 0 0 10px; color: var(--muted); font-size: 12px; line-height: 1.45; }
    .citation-token-row {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      align-items: center;
    }
    .citation-token-row input {
      flex: 1 1 300px;
      min-width: 220px;
      max-width: 100%;
    }
    .citation-token-row button {
      flex: 0 0 auto;
    }
    .citation-settings-status {
      margin-top: 8px;
      min-height: 18px;
      color: var(--muted);
      font-size: 12px;
    }
    .citation-settings-status.ok { color: #137333; }
    .citation-settings-status.err { color: #b42318; }
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
      .loader-form {
        grid-template-columns: 1fr;
        grid-template-areas: "path" "mode" "choose" "run" "stop" "delete";
      }
      .loader-main { grid-template-columns: 1fr; }
      .library-quicklook { top: 24px; left: 4vw; width: 92vw; height: 70vh; }
      .library-quicklook-body { grid-template-columns: 78px minmax(0, 1fr); }
      .library-page-thumb { width: 58px; min-height: 78px; }
    }
  </style>
</head>
<body>
  <div class="window-drag-region" id="windowDragRegion" aria-hidden="true"></div>
  <div class="app library-mode sidebar-collapsed">
    <aside class="sidebar">
      <div class="brand">
        <div class="sidebar-view-switcher" id="sidebarViewSwitcher">
          <button class="view-switch" id="sideLibraryMode" type="button">Library</button>
          <button class="view-switch" id="sideReportMode" type="button">Journal Monitor</button>
          <button class="view-switch" id="sideDeepSurveyMode" type="button">Deep Survey</button>
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
              <button class="view-switch active" id="libraryMode" type="button">Library</button>
              <button class="view-switch" id="myPublicationsMode" type="button">My Publications</button>
              <button class="view-switch" id="reportMode" type="button">Journal Monitor</button>
              <button class="view-switch" id="deepSurveyMode" type="button">Deep Survey</button>
            </div>
            <h2 id="reportTitle"></h2>
            <div class="toolbar-actions hidden" id="reportToolbarActions">
              <button class="smallbtn" id="refreshReport" type="button" title="Refresh papers for this date">Refresh</button>
              <input class="search" id="searchBox" placeholder="Search title, abstract, DOI">
              <label class="toolbar-toggle"><input type="checkbox" id="figureToggle" checked> Figures</label>
            </div>
            <div class="library-search-tools" id="librarySearchTools">
              <div class="library-search-wrap">
                <input class="search" id="librarySearchBox" placeholder="Search Library" type="search">
                <button class="library-search-clear" id="clearLibrarySearch" type="button" title="Clear search">×</button>
              </div>
              <span class="library-search-count" id="librarySearchCount"></span>
            </div>
          </div>
          <div class="summary" id="summary"></div>
          <div class="report-tabs" id="reportTabs"></div>
          <div class="fetch-progress-host" id="fetchProgressHost"></div>
          <div class="library-controls" id="libraryControls">
            <div class="my-publications-tools" id="myPublicationsTools">
              <div class="publication-search-status my-publications-tool-note" id="publicationSearchStatus">Use DOI/arXiv/title, or search by name with optional units: Name; Unit A; Unit B.</div>
              <div class="my-publications-tool-left">
                <input class="search" id="myPublicationName" placeholder="Name; affiliation A; affiliation B">
                <button class="smallbtn" id="findMyPublications" type="button">Find by Name</button>
                <button class="smallbtn" id="refreshMyPublicationMetrics" type="button" title="Refresh citation metrics and PubMed metadata" ${state.myPublicationMetricsRefreshing ? "disabled" : ""}>Refresh Metrics</button>
                <input class="search" id="publicationSearchBox" placeholder="DOI, arXiv, Zenodo, or title">
                <button class="smallbtn" id="addMyPublication" type="button">Add</button>
                <div class="publication-export-menu">
                  <button class="smallbtn" id="exportPublicationList" type="button">Export List</button>
                  <div class="publication-export-options" id="publicationExportOptions" aria-hidden="true">
                    <button type="button" data-action="export-publications" data-export-format="pdf">LaTeX PDF</button>
                    <button type="button" data-action="export-publications" data-export-format="tex">LaTeX .tex</button>
                    <button type="button" data-action="export-publications" data-export-format="overleaf">Overleaf Project .zip</button>
                    <button type="button" data-action="export-publications" data-export-format="docx">Word .docx</button>
                  </div>
                </div>
              </div>
              <div id="myPublicationProfileStripHost"></div>
            </div>
          </div>
          <div class="papers" id="papers"></div>
          <div class="deep-survey-host" id="deepSurveyHost" aria-hidden="true"></div>
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
      <div class="settings-backdrop" id="citationSettingsBackdrop" aria-hidden="true">
        <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="citationSettingsTitle">
          <div class="settings-modal-head">
            <div>
              <h2 id="citationSettingsTitle">Citation Settings</h2>
              <p>Manage optional citation and version-matching sources for paper details.</p>
            </div>
            <button class="settings-modal-close" id="closeCitationSettings" type="button" title="Close settings">×</button>
          </div>
          <div class="settings-modal-body">
            <div class="citation-source-setting">
              <div class="citation-source-setting-head"><strong>Built-in Sources</strong><span>Always available</span></div>
              <p>OpenAlex, Semantic Scholar, Crossref, arXiv, and DataCite continue to work without extra setup.</p>
            </div>
            <div class="citation-source-setting">
              <div class="citation-source-setting-head"><strong>NASA ADS</strong><span id="adsConfiguredLabel">Not configured</span></div>
              <p>Optional. Add an ADS API token to improve arXiv-published version matching and physics citation cross-checks.</p>
              <div class="citation-token-row">
                <input class="search" id="adsTokenInput" type="password" autocomplete="off" placeholder="ADS API token">
                <button class="smallbtn" id="saveAdsToken" type="button">Save</button>
                <button class="smallbtn" id="testAdsToken" type="button">Test</button>
                <button class="smallbtn" id="clearAdsToken" type="button">Clear</button>
              </div>
              <div class="citation-settings-status" id="citationSettingsStatus"></div>
            </div>
          </div>
        </section>
      </div>
      <div class="settings-backdrop loader-backdrop" id="libraryLoaderBackdrop" aria-hidden="true">
        <section class="settings-modal loader-modal" role="dialog" aria-modal="false" aria-labelledby="libraryLoaderTitle">
          <div class="settings-modal-head">
            <div>
              <h2 id="libraryLoaderTitle">Folder Loader</h2>
              <p>Import a folder into Library with a live log. Source files are never moved or deleted.</p>
            </div>
            <button class="settings-modal-close" id="closeLibraryLoader" type="button" title="Close loader">×</button>
          </div>
          <div class="settings-modal-body loader-modal-body" id="libraryLoaderModalBody"></div>
        </section>
      </div>
    </main>
  </div>
  <script>
    const initialToday = localIsoDate(new Date());
    const IS_STANDALONE_LOADER_WINDOW = new URLSearchParams(window.location.search).get("standalone") === "loader";
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
      {key: "number", label: "No", defaultWidth: 48, minWidth: 40, maxWidth: 90, sortable: false},
      {key: "title", label: "Title", defaultWidth: 515, minWidth: 300, maxWidth: 1000, sortable: true},
      {key: "citation", label: "Citation", defaultWidth: 238, minWidth: 180, maxWidth: 520, sortable: true},
      {key: "date", label: "Date", defaultWidth: 116, minWidth: 92, maxWidth: 150, sortable: true, defaultSortDir: "desc"},
      {key: "citations", label: "Cites", defaultWidth: 66, minWidth: 56, maxWidth: 110, sortable: true, defaultSortDir: "desc"}
    ];
    const LIBRARY_SHORTCUT_TAB_COUNT = 5;
    const LIBRARY_WORKSPACE_TAB_COUNT = 3;
    let librarySearchTimer = 0;
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
      libraryFoldersById: new Map(),
      libraryItemsById: new Map(),
      libraryChildFoldersByParent: new Map(),
      libraryItemsByFolder: new Map(),
      libraryLoaded: false,
      libraryLoadingPromise: null,
      libraryPaperDetailRequests: {},
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
      libraryImportMissingDoiIndex: 0,
      libraryImportFollowLatest: true,
      libraryLoaderOpen: false,
      libraryRootId: 1,
      libraryCurrentFolderId: 1,
      libraryActiveFolderId: 1,
      librarySelection: {type: "folder", id: 1},
      libraryColumnSelections: {},
      libraryRangeAnchor: null,
      libraryRangeFolderId: 0,
      libraryRangeSelectionKeys: new Set(),
      librarySearchCache: {key: "", results: []},
      librarySearchVersion: 0,
      libraryColumnsScrollLeft: 0,
      libraryColumnScrollTops: {},
      libraryColumnWidths: {},
      libraryDetailWidth: 340,
      libraryClipboard: null,
      libraryActivityText: "",
      libraryActivityLive: false,
      libraryActivityTimer: 0,
      libraryDragPayload: null,
      libraryRevealColumnFolderId: 0,
      libraryRevealColumnDirection: "",
      libraryRenamingFolderId: 0,
      libraryRenamingItemId: 0,
      libraryQuickLookOpen: false,
      libraryQuickLookKind: "",
      libraryQuickLookRenderToken: 0,
      libraryQuickLookPath: "",
      libraryQuickLookUrl: "",
      libraryQuickLookPage: 1,
      libraryQuickLookPageCount: 0,
      libraryQuickLookManualFrame: false,
      libraryQuickLookFrameRect: null,
      libraryQuickLookPdfHasFocus: false,
      myPublications: [],
      myPublicationSelectionId: 0,
      myPublicationSelectedIds: new Set(),
      myPublicationRangeAnchorId: 0,
      myPublicationSort: "manual",
      myPublicationSortDir: "asc",
      myPublicationSearchResults: [],
      myPublicationSearchStatus: "",
      myPublicationSearchScrollTop: 0,
      myPublicationsLoaded: false,
      myPublicationSearchToken: 0,
      myPublicationMetricsRefreshing: false,
      myPublicationMetricsJobId: "",
      myPublicationAuthorCache: {},
      myPublicationScholarProfile: null,
      myPublicationActivities: [],
      myPublicationStatsHeight: 126,
      myPublicationName: "",
      myPublicationColumnWidths: {},
      myPublicationRoleFilter: "",
      myPublicationJournalFilter: "",
      myPublicationKeyboardDetailToken: 0,
      myPublicationKeyboardDetailTimer: 0,
      mode: "library",
      activeReportJournal: "",
      reportSelectedPaperId: "",
      reportQuickLookPaperId: "",
      noteWidth: 460,
      query: "",
      reportSequence: 0,
      reportCache: {},
      monthCacheKey: "",
      monthLoaded: false,
      lateArrivals: [],
      markingLateArrivalIds: new Set(),
      fetchingDates: new Set(),
      pendingFetchDates: new Set(),
      noMatchDates: new Set(),
      fetchProgress: {},
      progressPollers: {},
      fetchSnapshotPolls: {},
      fetchSnapshotInflight: {},
      fetchCompletionWatchers: new Set(),
      deepSurveyUrl: "",
      deepSurveyLoadingPromise: null,
      logoRequests: {},
      figureRequests: {},
      figureQueue: [],
      queuedFigureIds: new Set(),
      activeFigureHydrations: 0,
      maxFigureHydrations: 2,
      figureFailures: new Set(),
      selectionMarquee: null,
      suppressClickOnce: false,
      suppressContextMenuOnce: false,
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

    function todayIsoDate() {
      return localIsoDate(new Date());
    }

    function isFutureDateIso(value) {
      return String(value || "") > todayIsoDate();
    }

    function updateReportRefreshButton() {
      const button = $("refreshReport");
      if (!button) return;
      const disabled = isFutureDateIso(state.selectedDate) || state.fetchingDates.has(state.selectedDate);
      button.disabled = disabled;
      button.title = isFutureDateIso(state.selectedDate)
        ? "Future dates cannot be refreshed"
        : "Refresh papers for this date";
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

    function currentMonthCacheKey() {
      return `${state.viewYear}-${String(state.viewMonth).padStart(2, "0")}`;
    }

    async function loadMonth(options = {}) {
      const cacheKey = currentMonthCacheKey();
      if (!options.force && state.monthLoaded && state.monthCacheKey === cacheKey) {
        renderCalendar();
        renderFilters();
        renderSubjectFilters();
        return;
      }
      const data = await fetchJson(`/api/month?year=${state.viewYear}&month=${state.viewMonth}`);
      state.journals = data.journals;
      syncSelectedJournals();
      state.counts = data.counts;
      state.monthCacheKey = cacheKey;
      state.monthLoaded = true;
      renderCalendar();
      renderFilters();
      renderSubjectFilters();
      await loadJournalSettings();
    }

    async function loadReport(options = {}) {
      const showLoading = options.showLoading !== false;
      const selectedDate = state.selectedDate;
      const sequence = ++state.reportSequence;
      updateReportRefreshButton();
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
        clearFetchProgressDisplay();
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
      clearFetchProgressDisplay();
      $("papers").innerHTML = `<div class="empty">Loading papers for this date...</div>`;
    }

    function applyReportData(selectedDate, data, sequence) {
      if (selectedDate !== state.selectedDate || sequence !== state.reportSequence) return;
      state.journals = data.journals || state.journals;
      syncSelectedJournals();
      state.papers = data.papers || [];
      state.lateArrivals = Array.isArray(data.lateArrivals) ? data.lateArrivals : [];
      renderSubjectFilters();
      renderFilters();
      if (state.mode === "library") {
        return;
      }
      renderReport();
      if ((data.missingJournals || []).length && !state.papers.length) {
        updateFetchProgressDisplay(selectedDate);
      }
    }

    function reportIsActiveForDate(selectedDate) {
      return state.mode !== "library" && selectedDate === state.selectedDate;
    }

    function renderReportIfActive(selectedDate) {
      if (reportIsActiveForDate(selectedDate)) renderReport();
    }

    async function refreshMissingDateInBackground(selectedDate, options = {}) {
      if (state.fetchingDates.has(selectedDate)) return;
      const forceFetch = Boolean(options.forceFetch);
      if (forceFetch) delete state.reportCache[selectedDate];
      setPendingFetchDate(selectedDate, true);
      state.fetchingDates.add(selectedDate);
      state.fetchProgress[selectedDate] = state.fetchProgress[selectedDate] || {percent: 0, completed: 0, total: 0, active: true};
      updateReportRefreshButton();
      await startProgressPolling(selectedDate);
      renderCalendar();
      renderReportIfActive(selectedDate);
      try {
        const forceParam = forceFetch ? "&force_fetch=1" : "";
        const data = await fetchJson(`/api/report?date=${selectedDate}${forceParam}`, 20 * 60 * 1000);
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
          setPendingFetchDate(selectedDate, false);
          if (selectedDate === state.selectedDate) {
            const sequence = ++state.reportSequence;
            applyReportData(selectedDate, data, sequence);
          }
          return;
        }
        setPendingFetchDate(selectedDate, false);
        if (data.fetched) await loadMonth({force: true});
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

    function refreshCurrentReportDate() {
      const selectedDate = state.selectedDate;
      if (isFutureDateIso(selectedDate) || state.fetchingDates.has(selectedDate)) return;
      state.noMatchDates.delete(selectedDate);
      state.fetchProgress[selectedDate] = {percent: 0, completed: 0, total: 0, active: true, currentJournal: ""};
      refreshMissingDateInBackground(selectedDate, {forceFetch: true});
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
      delete state.fetchSnapshotPolls[selectedDate];
      delete state.fetchSnapshotInflight[selectedDate];
      stopProgressPolling(selectedDate);
      renderCalendar();
      renderReportIfActive(selectedDate);
      updateReportRefreshButton();
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
          if (state.fetchingDates.has(selectedDate)) {
            updateFetchProgressDisplay(selectedDate);
            refreshReportSnapshotDuringFetch(selectedDate);
          }
        }
        return data.progress || null;
      } catch (error) {
        return null;
      }
    }

    function updateFetchProgressDisplay(selectedDate) {
      if (!reportIsActiveForDate(selectedDate)) return;
      const root = $("fetchProgressHost");
      root.classList.add("open");
      let panel = root.querySelector("[data-fetch-progress]");
      if (!panel) {
        root.innerHTML = fetchProgressMarkup(selectedDate);
        panel = root.querySelector("[data-fetch-progress]");
      }
      const progress = normalizedFetchProgress(selectedDate);
      panel.querySelector('[data-role="fetch-percent"]').textContent = `${progress.percent}%`;
      panel.querySelector('[data-role="fetch-bar"]').style.width = `${progress.percent}%`;
      panel.querySelector('[data-role="fetch-detail"]').textContent = progress.detail;
    }

    function clearFetchProgressDisplay() {
      const root = $("fetchProgressHost");
      if (!root) return;
      root.classList.remove("open");
      root.innerHTML = "";
    }

    async function refreshReportSnapshotDuringFetch(selectedDate) {
      if (selectedDate !== state.selectedDate || state.mode === "library") return;
      const now = Date.now();
      const last = state.fetchSnapshotPolls[selectedDate] || 0;
      if (state.fetchSnapshotInflight[selectedDate] || now - last < 1200) return;
      state.fetchSnapshotPolls[selectedDate] = now;
      state.fetchSnapshotInflight[selectedDate] = true;
      try {
        const data = await fetchJson(`/api/report?date=${selectedDate}&auto_fetch=0`);
        updateCalendarCountFromReport(selectedDate, data);
        state.reportCache[selectedDate] = data;
        if (selectedDate === state.selectedDate && state.mode !== "library") {
          const previousSignature = reportPaperListSignature(state.papers);
          const nextSignature = reportPaperListSignature(data.papers || []);
          if (nextSignature !== previousSignature) {
            applyReportData(selectedDate, data, state.reportSequence);
          } else {
            state.journals = data.journals || state.journals;
            state.papers = data.papers || state.papers;
            updateFetchProgressDisplay(selectedDate);
          }
        }
      } catch (error) {
        // Keep the progress UI alive; the completion watcher will surface persistent errors.
      } finally {
        delete state.fetchSnapshotInflight[selectedDate];
      }
    }

    function reportPaperListSignature(papers) {
      return (papers || [])
        .map((paper) => [
          paper.paper_id || "",
          paper.image_url || "",
          paper.download_status || "",
          paper.analysis_status || ""
        ].join(":"))
        .join("|");
    }

    function resetLibraryRootSelection() {
      state.libraryActiveFolderId = Number(state.libraryRootId || 1);
      state.libraryCurrentFolderId = Number(state.libraryRootId || 1);
      state.librarySelection = {type: "folder", id: Number(state.libraryRootId || 1)};
      clearLibraryRangeSelection();
      ensureLibraryColumnSelection(state.libraryRootId);
    }

    async function loadLibrary(options = {}) {
      state.mode = "library";
      state.libraryTab = "library";
      setSidebarCollapsed(true);
      if (!options.force && state.libraryLoaded) {
        resetLibraryRootSelection();
        renderLibrary();
        return;
      }
      if (!state.libraryLoadingPromise) {
        state.libraryLoadingPromise = fetch("/api/library")
          .then(async (res) => {
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Could not load Library");
            applyLibrarySnapshot(data);
          })
          .finally(() => {
            state.libraryLoadingPromise = null;
          });
      }
      await state.libraryLoadingPromise;
      resetLibraryRootSelection();
      renderLibrary();
    }

    async function loadMyPublications() {
      state.mode = "library";
      state.libraryTab = "my-publications";
      setSidebarCollapsed(true);
      renderMyPublications();
      if (state.myPublicationsLoaded) return;
      const res = await fetch("/api/my-publications");
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not load My Publications");
      applyMyPublications(data);
      renderMyPublications();
    }

    function openLibraryLoader() {
      state.libraryLoaderOpen = true;
      renderLibraryLoader();
    }

    function closeLibraryLoader() {
      if (IS_STANDALONE_LOADER_WINDOW) {
        window.webkit?.messageHandlers?.libraryLoaderWindow?.postMessage({type: "close"});
        return;
      }
      state.libraryLoaderOpen = false;
      $("libraryLoaderBackdrop")?.classList.remove("open");
      $("libraryLoaderBackdrop")?.setAttribute("aria-hidden", "true");
    }

    function renderActiveLibraryTab() {
      if (state.libraryTab === "my-publications") {
        renderMyPublications();
        return;
      }
      renderLibrary();
    }

    function applyMyPublications(data) {
      state.myPublications = Array.isArray(data.publications) ? data.publications : [];
      state.myPublicationsLoaded = true;
      state.myPublicationName = data.myName || state.myPublicationName || "";
      if (Object.prototype.hasOwnProperty.call(data || {}, "scholarProfile")) {
        state.myPublicationScholarProfile = data.scholarProfile && Object.keys(data.scholarProfile).length ? data.scholarProfile : null;
      }
      if (!state.myPublicationSelectionId && state.myPublications.length) {
        state.myPublicationSelectionId = Number(sortedMyPublications()[0]?.id || 0);
      }
      if (state.myPublicationSelectionId && !myPublicationById(state.myPublicationSelectionId)) {
        state.myPublicationSelectionId = Number(sortedMyPublications()[0]?.id || 0);
      }
      pruneMyPublicationSelection();
    }

    function myPublicationById(id) {
      return state.myPublications.find((item) => Number(item.id) === Number(id));
    }

    function sortedMyPublications() {
      const rows = [...state.myPublications];
      rows.sort((a, b) => {
        if (state.myPublicationSort === "manual") {
          const sortDelta = Number(a.sort_order || 0) - Number(b.sort_order || 0);
          if (sortDelta) return sortDelta;
          return Number(a.id || 0) - Number(b.id || 0);
        }
        const direction = state.myPublicationSortDir === "desc" ? -1 : 1;
        const value = (entry) => {
          const paper = entry.paper || {};
          if (state.myPublicationSort === "title") return String(paper.title || "").toLowerCase();
          if (state.myPublicationSort === "citation") return myPublicationCitationSortText(paper).toLowerCase();
          if (state.myPublicationSort === "date") return String(paper.publication_date || "");
          if (state.myPublicationSort === "citations") return Number(myPublicationMaxCitationCount(paper) || 0);
          return Number(entry.sort_order || 0);
        };
        const left = value(a);
        const right = value(b);
        let delta = 0;
        if (typeof left === "number" || typeof right === "number") delta = Number(left || 0) - Number(right || 0);
        else delta = String(left || "").localeCompare(String(right || ""));
        if (delta) return delta * direction;
        const dateDelta = String(a.paper?.publication_date || "").localeCompare(String(b.paper?.publication_date || ""));
        if (dateDelta) return dateDelta * direction;
        return String(a.paper?.title || "").localeCompare(String(b.paper?.title || ""));
      });
      return rows;
    }

    function myPublicationCitationSortText(paper) {
      const ref = paper?.nature_reference || {};
      return [
        ref.journal || paper?.journal || "",
        ref.volume || "",
        ref.pages || "",
        ref.year || paper?.publication_date || "",
        paper?.doi || "",
      ].join(" ");
    }

    function selectedMyPublicationPaper() {
      return myPublicationById(state.myPublicationSelectionId)?.paper || null;
    }

    function applyLibrarySnapshot(data) {
      state.libraryRootId = Number(data.root_id || 1);
      state.libraryFolders = data.folders || [];
      state.libraryItems = data.items || [];
      state.libraryFoldersById = new Map(state.libraryFolders.map((folder) => [Number(folder.id), folder]));
      state.libraryItemsById = new Map(state.libraryItems.map((item) => [Number(item.id), item]));
      state.libraryChildFoldersByParent = new Map();
      state.libraryFolders.forEach((folder) => {
        const parentId = Number(folder.parent_id || 0);
        if (!state.libraryChildFoldersByParent.has(parentId)) state.libraryChildFoldersByParent.set(parentId, []);
        state.libraryChildFoldersByParent.get(parentId).push(folder);
      });
      state.libraryChildFoldersByParent.forEach((folders) => folders.sort((a, b) => compareLibraryOrder(a, b, "name")));
      state.libraryItemsByFolder = new Map();
      state.libraryItems.forEach((item) => {
        const folderId = Number(item.folder_id || 0);
        if (!state.libraryItemsByFolder.has(folderId)) state.libraryItemsByFolder.set(folderId, []);
        state.libraryItemsByFolder.get(folderId).push(item);
      });
      state.libraryItemsByFolder.forEach((items) => items.sort((a, b) => compareLibraryOrder(a, b, "display_name")));
      state.libraryLoaded = true;
      clearLibrarySearchCache();
      state.librarySearchVersion += 1;
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
      pruneLibraryClipboard();
      pruneLibraryRangeSelection();
      ensureLibraryColumnSelection(displayRootId);
    }

    function libraryFolderById(id) {
      return state.libraryFoldersById.get(Number(id));
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
      return state.libraryItemsById.get(Number(id));
    }

    function librarySelectionExists(selection) {
      if (!selection) return false;
      if (selection.type === "folder") return Boolean(libraryFolderById(selection.id));
      if (selection.type === "item") return Boolean(libraryItemById(selection.id));
      return false;
    }

    function libraryChildFolders(parentId) {
      return state.libraryChildFoldersByParent.get(Number(parentId)) || [];
    }

    function libraryFolderItemsRaw(folderId) {
      return state.libraryItemsByFolder.get(Number(folderId)) || [];
    }

    function libraryFolderItems(folderId) {
      const query = state.query.trim();
      return libraryFolderItemsRaw(folderId)
        .filter((item) => {
          if (!query) return true;
          return librarySearchMatches(libraryItemSearchHaystack(item), query);
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
      const query = state.query.trim();
      const folders = libraryChildFolders(folderId)
        .filter((folder) => !query || librarySearchMatches(`${folder.name || ""} ${libraryFolderPath(folder.id)}`, query))
        .map((folder) => ({type: "folder", id: Number(folder.id)}));
      const items = libraryFolderItems(folderId)
        .map((item) => ({type: "item", id: Number(item.id)}));
      return folders.concat(items);
    }

    function librarySearchIsActive() {
      return Boolean(state.query.trim()) && !["loader", "my-publications"].includes(state.libraryTab || "");
    }

    function clearLibrarySearchCache() {
      state.librarySearchCache = {key: "", results: []};
    }

    function librarySearchCacheKey(query, displayRootId) {
      return [
        state.librarySearchVersion,
        Number(displayRootId || 0),
        librarySearchNormalize(query),
        state.libraryTab || ""
      ].join("|");
    }

    function libraryItemSearchHaystack(item) {
      const paper = item.paper || {};
      const doiValues = [
        paper.doi,
        paper.nature_reference?.doi,
        paper.url,
        paper.landing_url,
        paper.google_scholar_url
      ].filter(Boolean);
      return [
        item.display_name,
        paper.original_filename,
        paper.original_relative_path,
        paper.original_parent_relative_path,
        paper.source_path,
        paper.merged_pdf_path,
        paper.main_pdf_path,
        paper.pdf_url,
        paper.citation_label,
        paper.nature_reference?.authors,
        paper.nature_reference?.title,
        paper.nature_reference?.journal,
        paper.nature_reference?.volume,
        paper.nature_reference?.pages,
        paper.nature_reference?.year,
        paper.nature_reference?.doi,
        paper.title,
        paper.abstract,
        paper.doi,
        paper.preprint_id,
        paper.preprint_category,
        ...(Array.isArray(paper.preprint_categories) ? paper.preprint_categories : []),
        paper.journal,
        paper.publication_date,
        paper.bibtex,
        ...doiValues.map((value) => libraryDoiSearchKey(value)),
        ...(Array.isArray(paper.authors) ? paper.authors : []),
        ...(Array.isArray(paper.full_authors) ? paper.full_authors : [])
      ].filter(Boolean).join(" ").toLowerCase();
    }

    function librarySearchMatches(haystack, query) {
      const normalizedHaystack = librarySearchNormalize(haystack);
      const normalizedQuery = librarySearchNormalize(query);
      if (!normalizedQuery) return true;
      if (normalizedHaystack.includes(normalizedQuery)) return true;
      const compactQuery = libraryDoiSearchKey(query);
      if (compactQuery && libraryDoiSearchKey(haystack).includes(compactQuery)) return true;
      const queryTokens = librarySearchTokens(normalizedQuery).filter((token) => token.length > 1);
      if (!queryTokens.length) return normalizedHaystack.includes(normalizedQuery);
      const haystackTokens = librarySearchTokens(normalizedHaystack);
      if (!haystackTokens.length) return false;
      const longQueryTokens = queryTokens.filter((token) => token.length >= 4);
      const haystackTokenSet = new Set(haystackTokens.flatMap((token) => librarySearchTokenVariants(token)));
      let matched = 0;
      queryTokens.forEach((token) => {
        if (librarySearchTokenMatches(token, haystackTokens, haystackTokenSet, normalizedHaystack, longQueryTokens.length)) matched += 1;
      });
      const required = queryTokens.length <= 2 ? queryTokens.length : Math.max(2, Math.ceil(queryTokens.length * 0.66));
      return matched >= required;
    }

    function librarySearchNormalize(value) {
      return String(value || "")
        .normalize("NFD")
        .replace(/[\u0300-\u036f]/g, "")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, " ")
        .replace(/\s+/g, " ")
        .trim();
    }

    function libraryDoiSearchKey(value) {
      return String(value || "")
        .toLowerCase()
        .replace(/https?:\/\/(dx\.)?doi\.org\//g, "")
        .replace(/[^a-z0-9]/g, "");
    }

    function librarySearchTokens(value) {
      return librarySearchNormalize(value).split(" ").filter(Boolean);
    }

    function librarySearchTokenVariants(token) {
      const variants = new Set([token]);
      const suffixes = ["ations", "ation", "ments", "ment", "ities", "ity", "ions", "ion", "tion", "ing", "ed", "es", "s"];
      suffixes.forEach((suffix) => {
        if (token.length > suffix.length + 3 && token.endsWith(suffix)) {
          variants.add(token.slice(0, -suffix.length));
        }
      });
      return [...variants].filter((item) => item.length > 1);
    }

    function librarySearchTokenMatches(queryToken, haystackTokens, haystackTokenSet, normalizedHaystack, longQueryTokenCount = 0) {
      const queryVariants = librarySearchTokenVariants(queryToken);
      if (queryVariants.some((variant) => normalizedHaystack.includes(variant) || haystackTokenSet.has(variant))) return true;
      if (queryToken.length < 4 || longQueryTokenCount > 8) return false;
      const comparableTokens = haystackTokens.filter((token) => (
        token.length >= 4
        && Math.abs(token.length - queryToken.length) <= 3
        && token[0] === queryToken[0]
      )).slice(0, 80);
      return queryVariants.some((variant) => comparableTokens.some((token) => {
        if (token.length < 3) return false;
        if ((token.includes(variant) || variant.includes(token)) && Math.min(token.length, variant.length) >= 4) return true;
        const maxDistance = variant.length <= 4 ? 1 : (variant.length <= 8 ? 2 : 3);
        if (Math.abs(token.length - variant.length) > maxDistance) return false;
        return libraryEditDistanceWithin(variant, token, maxDistance);
      }));
    }

    function libraryEditDistanceWithin(left, right, limit) {
      if (left === right) return true;
      if (Math.abs(left.length - right.length) > limit) return false;
      let previous = Array.from({length: right.length + 1}, (_, index) => index);
      for (let i = 1; i <= left.length; i += 1) {
        const current = [i];
        let rowBest = current[0];
        for (let j = 1; j <= right.length; j += 1) {
          const cost = left[i - 1] === right[j - 1] ? 0 : 1;
          const value = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost);
          current[j] = value;
          if (value < rowBest) rowBest = value;
        }
        if (rowBest > limit) return false;
        previous = current;
      }
      return previous[right.length] <= limit;
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
      const query = state.query.trim();
      if (!query) return [];
      const displayRootId = libraryDisplayRootId();
      const cacheKey = librarySearchCacheKey(query, displayRootId);
      if (state.librarySearchCache.key === cacheKey) return state.librarySearchCache.results;
      const folderIds = libraryDescendantFolderIds(displayRootId);
      const results = [];
      state.libraryFolders
        .filter((folder) => folderIds.has(Number(folder.id)) && Number(folder.id) !== Number(displayRootId))
        .forEach((folder) => {
          const path = libraryFolderPath(folder.id);
          const haystack = `${folder.name || ""} ${path}`;
          if (librarySearchMatches(haystack, query)) {
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
          const haystack = `${libraryItemSearchHaystack(item)} ${folderPath}`;
          if (librarySearchMatches(haystack, query)) {
            results.push({
              type: "item",
              id: Number(item.id),
              parentFolderId: Number(item.folder_id || displayRootId),
              path: folderPath
            });
          }
        });
      results.sort((a, b) => {
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
      state.librarySearchCache = {key: cacheKey, results};
      return results;
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

    function selectedLibraryEntriesForAction() {
      const rangeEntries = libraryRangeSelectionEntries();
      if (rangeEntries.length > 1) return rangeEntries;
      const selection = state.librarySelection;
      return selection?.type && selection.id ? [{type: selection.type, id: Number(selection.id)}] : [];
    }

    function libraryEntryIsInActionSelection(parentFolderId, entry) {
      const target = {type: entry.type, id: Number(entry.id)};
      if (libraryEntryIsRangeSelected(parentFolderId, target)) return true;
      return libraryEntryKey(state.librarySelection) === libraryEntryKey(target);
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

    function selectLibraryColumnFolder(folderId) {
      const targetFolderId = Number(folderId || libraryDisplayRootId());
      if (!libraryFolderById(targetFolderId)) return;
      clearLibraryRangeSelection();
      state.libraryActiveFolderId = targetFolderId;
      state.libraryCurrentFolderId = targetFolderId;
      state.librarySelection = {type: "folder", id: targetFolderId};
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
      return withLibraryActivityStatus("Moving...", "Move complete.", async () => {
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
      });
    }

    async function reorderLibraryEntry(type, id, parentFolderId, targetId, position) {
      return withLibraryActivityStatus("Moving...", "Move complete.", async () => {
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
      });
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
      return withLibraryActivityStatus("Deleting...", "Delete complete.", async () => {
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
      });
    }

    async function removeLibraryItemFromCurrentCollection(itemId) {
      if (!itemId) return;
      const item = libraryItemById(itemId);
      if (!item) return;
      return withLibraryActivityStatus("Deleting...", "Delete complete.", async () => {
        const parentId = Number(item.folder_id || state.libraryActiveFolderId || state.libraryRootId);
        const deletedEntry = {type: "item", id: Number(itemId)};
        const entriesBeforeDelete = libraryEntriesForFolder(parentId);
        const res = await fetch("/api/library/remove-item", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({item_id: itemId})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not remove paper from current collection");
        applyLibrarySnapshot(data);
        selectLibraryDeletionFallback(parentId, deletedEntry, entriesBeforeDelete);
        renderLibrary();
      });
    }

    function libraryFilePathsForDelete(type, id) {
      if (type === "item") {
        const path = libraryNativeItemPath(libraryItemById(id));
        return path ? [path] : [];
      }
      if (type === "folder") {
        const folderIds = libraryDescendantFolderIds(id);
        const paths = state.libraryItems
          .filter((item) => folderIds.has(Number(item.folder_id || 0)))
          .map((item) => libraryNativeItemPath(item))
          .filter(Boolean);
        return [...new Set(paths)];
      }
      return [];
    }

    async function deleteLibraryEntryFiles(type, id) {
      const paths = libraryFilePathsForDelete(type, id);
      if (!paths.length && type !== "folder") return;
      const parentId = type === "folder"
        ? parentFolderId(id)
        : Number(libraryItemById(id)?.folder_id || state.libraryActiveFolderId || state.libraryRootId);
      const deletedEntry = {type, id: Number(id)};
      const entriesBeforeDelete = libraryEntriesForFolder(parentId);
      const entryLabel = type === "folder"
        ? `this Library folder${paths.length ? ` and ${paths.length} file${paths.length === 1 ? "" : "s"}` : ""}`
        : "the original file from disk";
      const preview = paths.length ? paths.slice(0, 8).join("\\n") : "No local files found in this folder.";
      const overflow = paths.length > 8 ? `\\n...and ${paths.length - 8} more` : "";
      const confirmed = await showLibraryConfirmDialog({
        title: `Delete ${entryLabel}?`,
        body: type === "folder"
          ? "This cannot be undone. The Library folder and these files will be removed."
          : "This cannot be undone. The original file will be deleted and this paper will be removed from the current collection.",
        paths: preview + overflow,
        confirmLabel: type === "folder" ? "Delete Folder" : "Delete File"
      });
      if (!confirmed) return;
      return withLibraryActivityStatus("Deleting files...", "Delete complete.", async () => {
        const res = await fetch("/api/library/delete-file", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({type, id, confirmed: true})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not delete files");
        applyLibrarySnapshot(data);
        selectLibraryDeletionFallback(parentId, deletedEntry, entriesBeforeDelete);
        renderLibrary();
      });
    }

    function libraryFolderContentCounts(folderId) {
      const folderIds = libraryDescendantFolderIds(folderId);
      const itemCount = state.libraryItems.filter((item) => folderIds.has(Number(item.folder_id || 0))).length;
      const folderCount = state.libraryFolders.filter((folder) => folderIds.has(Number(folder.parent_id || 0))).length;
      return {itemCount, folderCount};
    }

    async function clearLibrarySpecialFolder(folderId, {deleteFiles = false} = {}) {
      const folder = libraryFolderById(folderId);
      if (!folder || !(folder.is_unsorted || folder.is_recycle)) return;
      const paths = libraryFilePathsForDelete("folder", folderId);
      const counts = libraryFolderContentCounts(folderId);
      const totalEntries = counts.itemCount + counts.folderCount;
      if (!totalEntries) return;
      const folderName = folder.name || (folder.is_recycle ? "Recycle" : "unsorted");
      const preview = paths.length ? paths.slice(0, 8).join("\\n") : "No local files found in this folder.";
      const overflow = paths.length > 8 ? `\\n...and ${paths.length - 8} more` : "";
      const confirmed = await showLibraryConfirmDialog({
        title: deleteFiles ? `Delete all original files in ${folderName}?` : `Remove all from ${folderName}?`,
        body: deleteFiles
          ? `This cannot be undone. ${paths.length} local file${paths.length === 1 ? "" : "s"} will be deleted, and ${totalEntries} Library entr${totalEntries === 1 ? "y" : "ies"} will be removed.`
          : `This removes ${totalEntries} Library entr${totalEntries === 1 ? "y" : "ies"} from ${folderName}. Original files on disk are not deleted.`,
        paths: deleteFiles ? preview + overflow : "",
        confirmLabel: deleteFiles ? "Delete All Original Files" : "Remove All"
      });
      if (!confirmed) return;
      return withLibraryActivityStatus(deleteFiles ? "Deleting files..." : "Removing...", deleteFiles ? "Delete complete." : "Remove complete.", async () => {
        const res = await fetch("/api/library/special-folder/clear", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({folder_id: folderId, delete_files: deleteFiles, confirmed: true})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not clear folder");
        applyLibrarySnapshot(data);
        setLibraryColumnSelection(parentFolderId(folderId), {type: "folder", id: Number(folderId)});
        state.libraryActiveFolderId = Number(folderId);
        state.libraryCurrentFolderId = Number(folderId);
        renderLibrary();
      });
    }

    function showLibraryConfirmDialog({title, body, paths, confirmLabel = "Delete"} = {}) {
      return new Promise((resolve) => {
        document.querySelector(".library-confirm-backdrop")?.remove();
        const backdrop = document.createElement("div");
        backdrop.className = "library-confirm-backdrop";
        backdrop.innerHTML = `
          <section class="library-confirm-dialog" role="dialog" aria-modal="true">
            <header>${escapeHtml(title || "Confirm action")}</header>
            <div class="library-confirm-body">
              <div>${escapeHtml(body || "This action cannot be undone.")}</div>
              ${paths ? `<pre class="library-confirm-paths">${escapeHtml(paths)}</pre>` : ""}
            </div>
            <div class="library-confirm-actions">
              <button type="button" data-action="cancel">Cancel</button>
              <button class="danger" type="button" data-action="confirm">${escapeHtml(confirmLabel)}</button>
            </div>
          </section>
        `;
        let onKeydown = null;
        const finish = (value) => {
          if (onKeydown) window.removeEventListener("keydown", onKeydown, true);
          backdrop.remove();
          resolve(value);
        };
        backdrop.querySelector('[data-action="cancel"]')?.addEventListener("click", () => finish(false));
        backdrop.querySelector('[data-action="confirm"]')?.addEventListener("click", () => finish(true));
        backdrop.addEventListener("click", (event) => {
          if (event.target === backdrop) finish(false);
        });
        onKeydown = (event) => {
          if (event.key === "Escape") {
            finish(false);
          }
        };
        window.addEventListener("keydown", onKeydown, true);
        document.body.appendChild(backdrop);
        backdrop.querySelector('[data-action="cancel"]')?.focus({preventScroll: true});
      });
    }

    async function deleteSelectedLibraryEntries() {
      const selectedEntries = libraryRangeSelectionEntries()
        .filter((entry) => !(entry.type === "folder" && libraryFolderById(entry.id)?.protected));
      if (selectedEntries.length <= 1) {
        const selection = state.librarySelection;
        if (selection?.type && selection.id) await deleteLibraryEntry(selection.type, Number(selection.id));
        return;
      }
      return withLibraryActivityStatus(`Deleting ${selectedEntries.length} items...`, "Delete complete.", async () => {
        const parentId = Number(state.libraryRangeFolderId || state.libraryActiveFolderId || state.libraryRootId);
        const entriesBeforeDelete = libraryEntriesForFolder(parentId);
        const entriesToDelete = selectedEntries
          .slice()
          .reverse()
          .filter((entry) => entry.type === "folder" ? libraryFolderById(entry.id) : libraryItemById(entry.id));
        if (!entriesToDelete.length) return;
        const res = await fetch("/api/library/delete-batch", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({entries: entriesToDelete})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not delete library entries");
        applyLibrarySnapshot(data);
        clearLibraryRangeSelection();
        const lastDeleted = selectedEntries[selectedEntries.length - 1];
        selectLibraryDeletionFallback(parentId, lastDeleted, entriesBeforeDelete);
        renderLibrary();
      });
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
      const entries = libraryClipboardEntries();
      if (!entries.length) return;
      return withLibraryActivityStatus(`Pasting ${entries.length} item${entries.length === 1 ? "" : "s"}...`, "Paste complete.", async () => {
        let lastPasted = null;
        const res = await fetch("/api/library/paste-batch", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({entries, target_folder_id: targetFolderId})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not paste library entries");
        applyLibrarySnapshot(data);
        const pastedEntries = Array.isArray(data.pasted) ? data.pasted : [];
        const finalPasted = pastedEntries[pastedEntries.length - 1];
        if (finalPasted?.id) {
          lastPasted = {type: finalPasted.type, id: Number(finalPasted.id)};
        }
        if (lastPasted) {
          setLibraryColumnSelection(Number(targetFolderId || state.libraryRootId), lastPasted);
        }
        renderLibrary();
      });
    }

    async function refreshLibraryMetadataFromDoi(paper) {
      if (!paper?.paper_id) return;
      const input = $("libraryDetailDoiInput");
      const identifier = String(input?.value || "").trim();
      const status = $("libraryDetailStatus");
      const buttons = $("libraryDetail")?.querySelectorAll("button") || [];
      const activityId = `metadata:${paper.paper_id}`;
      if (!identifier) {
        if (status) {
          status.textContent = "Enter a DOI or arXiv ID first.";
          status.className = "library-detail-status err";
        }
        input?.focus({preventScroll: true});
        return;
      }
      buttons.forEach((button) => button.disabled = true);
      if (status) {
        status.textContent = "Refreshing metadata, metrics, and PubMed details from identifier...";
        status.className = "library-detail-status";
      }
      if (state.libraryTab === "my-publications") {
        setMyPublicationActivity(activityId, "Refreshing metadata...");
      }
      updateLibraryActivityStatus("Refreshing metadata...", {live: true, clear: false});
      try {
        const res = await fetch("/api/library/refresh-metadata", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({paper_id: paper.paper_id, identifier})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not refresh metadata");
        applyLibrarySnapshot(data);
        if (Array.isArray(data.publications)) applyMyPublications(data);
        updatePaperState(paper.paper_id, data.paper);
        state.figureFailures.delete(paper.paper_id);
        if (state.libraryTab === "my-publications") renderMyPublications();
        else renderLibrary();
        updateLibraryActivityStatus("Metadata refreshed.", {delay: 2600});
      } catch (error) {
        const message = error.message || "Could not refresh metadata";
        updateLibraryActivityStatus(`Metadata refresh failed: ${message}`, {delay: 4200});
        if (status) {
          status.textContent = message;
          status.className = "library-detail-status err";
        }
        buttons.forEach((button) => button.disabled = false);
      } finally {
        clearMyPublicationActivity(activityId);
      }
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
        const isFuture = isFutureDateIso(iso);
        const button = document.createElement("button");
        button.className = `day${iso === state.selectedDate ? " active" : ""}${isFetching ? " fetching" : ""}${hasNoMatch ? " no-match" : ""}${isFuture ? " future" : ""}`;
        button.disabled = isFuture;
        button.innerHTML = `<span class="daynum">${day}</span>${
          isFetching
            ? `<span class="fetching-dot" title="Fetching"></span>`
            : `<span class="count">${total || ""}</span>`
        }`;
        if (isFuture) {
          root.appendChild(button);
          continue;
        }
        button.addEventListener("click", async () => {
          state.selectedDate = iso;
          state.activeReportJournal = "";
          updateReportRefreshButton();
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
      await loadMonth({force: true});
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
      await loadMonth({force: true});
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
      const filtered = reportVisiblePapers();
      const selectedFieldText = [...state.selectedFields]
        .map((field) => FIELD_LABELS[field] || field)
        .join(", ");
      $("summary").textContent = `${state.papers.length} total · ${filtered.length} shown · Fields: ${selectedFieldText || "All Fields"}`;
      const root = $("papers");
      root.classList.remove("library-view", "deep-survey-view");
      root.style.height = "";
      root.style.minHeight = "";
      root.innerHTML = "";
      renderLateArrivalsBanner(root);
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      const fetchPending = reportFetchIsPending(state.selectedDate);
      if (fetchPending) {
        updateFetchProgressDisplay(state.selectedDate);
      } else {
        clearFetchProgressDisplay();
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
      ensureReportPaperSelection(activePapers);
      activePapers.forEach((paper) => root.appendChild(renderPaper(paper)));
      markVisibleLateArrivalsSeen(activePapers);
      if (!activePapers.length) {
        root.insertAdjacentHTML("beforeend", `<div class="empty">No papers in this source for this date.</div>`);
      }
    }

    function renderLateArrivalsBanner(root) {
      const summaries = state.lateArrivals || [];
      if (!summaries.length) return;
      const banner = document.createElement("div");
      banner.className = "late-arrivals";
      const total = summaries.reduce((sum, item) => sum + Number(item.count || 0), 0);
      const links = summaries.map((item) => {
        const journals = Object.entries(item.journals || {})
          .map(([journal, count]) => `${journal} ${count}`)
          .join(", ");
        return `<button class="late-arrival-link" type="button" data-late-date="${escapeAttr(item.publication_date)}">${escapeHtml(item.publication_date)}</button>${journals ? ` <span>${escapeHtml(journals)}</span>` : ""}`;
      }).join(" · ");
      banner.innerHTML = `<span class="late-dot" aria-hidden="true"></span><strong>${total} late arrival${total === 1 ? "" : "s"}</strong><span>newly fetched for earlier dates:</span>${links}`;
      banner.querySelectorAll("[data-late-date]").forEach((button) => {
        button.addEventListener("click", async () => {
          state.selectedDate = button.dataset.lateDate || state.selectedDate;
          state.activeReportJournal = "";
          updateReportRefreshButton();
          renderCalendar();
          await loadReport();
        });
      });
      root.appendChild(banner);
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
        button.dataset.journal = group.journal;
        const logoUrl = journalLogoUrl(group.journal);
        const hasUnreadLateArrival = group.papers.some((paper) => paper.late_arrival_unread);
        button.innerHTML = `
          <span class="journal-tab-label">${logoUrl ? `<img src="${escapeAttr(logoUrl)}" alt="${escapeAttr(group.journal)} logo">` : escapeHtml(group.journal)}</span>
          <span class="journal-tab-count">${group.papers.length}</span>
          ${hasUnreadLateArrival ? `<span class="late-dot" title="Unread late arrival"></span>` : ""}
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
      root.onscroll = () => updateReportTabsOverflow();
      window.requestAnimationFrame(() => {
        updateReportTabsOverflow();
        revealActiveReportTab();
      });
    }

    function updateReportTabsOverflow() {
      const root = $("reportTabs");
      if (!root || !root.classList.contains("open")) return;
      const maxScroll = Math.max(0, root.scrollWidth - root.clientWidth);
      const left = root.scrollLeft > 2;
      const right = root.scrollLeft < maxScroll - 2;
      root.classList.toggle("has-overflow-left", left);
      root.classList.toggle("has-overflow-right", right);
    }

    function revealActiveReportTab(options = {}) {
      const root = $("reportTabs");
      const active = root?.querySelector(".journal-tab.active");
      if (!root || !active) return;
      const rootRect = root.getBoundingClientRect();
      const activeRect = active.getBoundingClientRect();
      const gutter = 28;
      let delta = 0;
      if (activeRect.left < rootRect.left + gutter) {
        delta = activeRect.left - rootRect.left - gutter;
      } else if (activeRect.right > rootRect.right - gutter) {
        delta = activeRect.right - rootRect.right + gutter;
      }
      if (delta) {
        root.scrollBy({left: delta, behavior: options.smooth ? "smooth" : "auto"});
        window.setTimeout(updateReportTabsOverflow, options.smooth ? 180 : 0);
      } else {
        updateReportTabsOverflow();
      }
    }

    function activeReportPapers() {
      const groups = groupedReportPapers(reportVisiblePapers());
      if (!groups.length) return [];
      const group = groups.find((item) => item.journal === state.activeReportJournal) || groups[0];
      return group?.papers || [];
    }

    function ensureReportPaperSelection(papers) {
      if (!papers.length) {
        state.reportSelectedPaperId = "";
        return;
      }
      if (!state.reportSelectedPaperId || !papers.some((paper) => paper.paper_id === state.reportSelectedPaperId)) {
        state.reportSelectedPaperId = papers[0].paper_id || "";
      }
    }

    function selectedReportPaper() {
      const papers = activeReportPapers();
      ensureReportPaperSelection(papers);
      return papers.find((paper) => paper.paper_id === state.reportSelectedPaperId) || papers[0] || null;
    }

    function updateReportPaperSelectionDom(options = {}) {
      const selectedId = String(state.reportSelectedPaperId || "");
      document.querySelectorAll("#papers .paper[data-paper-id]").forEach((article) => {
        const selected = article.dataset.paperId === selectedId;
        article.classList.toggle("report-selected", selected);
        article.setAttribute("aria-selected", selected ? "true" : "false");
      });
      if (options.scroll && selectedId) {
        const selected = document.querySelector(`#papers .paper[data-paper-id="${CSS.escape(selectedId)}"]`);
        selected?.scrollIntoView({block: "nearest"});
      }
    }

    function selectReportPaper(paperId, options = {}) {
      if (!paperId) return;
      state.reportSelectedPaperId = paperId;
      updateReportPaperSelectionDom(options);
    }

    function switchReportJournalTab(delta) {
      const groups = groupedReportPapers(reportVisiblePapers()).filter((group) => group.papers.length);
      if (!groups.length) return true;
      const currentIndex = groups.findIndex((group) => group.journal === state.activeReportJournal);
      const baseIndex = currentIndex >= 0 ? currentIndex : 0;
      const nextIndex = (baseIndex + delta + groups.length) % groups.length;
      state.activeReportJournal = groups[nextIndex].journal;
      state.reportSelectedPaperId = groups[nextIndex].papers[0]?.paper_id || "";
      renderReport();
      revealActiveReportTab({smooth: true});
      updateReportPaperSelectionDom({scroll: true});
      return true;
    }

    function openSelectedReportPaperQuickLook() {
      const paper = selectedReportPaper();
      if (!paper) return;
      if (paper.merged_pdf_path || paper.main_pdf_path) {
        const previewPaper = paper.merged_pdf_path
          ? paper
          : {...paper, merged_pdf_path: paper.main_pdf_path, merged_pdf_url: paper.main_pdf_url || ""};
        quickLookLibraryPdf(previewPaper, {toggle: true, silent: true});
        state.reportQuickLookPaperId = paper.paper_id || "";
        return;
      }
      if (state.libraryQuickLookOpen && state.libraryQuickLookKind === "placeholder" && state.reportQuickLookPaperId === paper.paper_id) {
        closeLibraryQuickLook();
        return;
      }
      state.reportQuickLookPaperId = paper.paper_id || "";
      showLibraryQuickLookPlaceholder({open: true});
    }

    function reportKeyboardTargetIsEditable(target) {
      if (!target?.closest) return false;
      return Boolean(target.closest("input, textarea, select, button, a, [contenteditable='true']"));
    }

    function handleReportKeydown(event) {
      if (state.mode !== "report") return false;
      const keyAliases = {
        "Up": "ArrowUp",
        "Down": "ArrowDown",
        "Left": "ArrowLeft",
        "Right": "ArrowRight",
        "Spacebar": " "
      };
      const key = keyAliases[event.key] || event.key;
      if (key === " " && state.libraryQuickLookOpen) {
        event.preventDefault();
        event.stopPropagation();
        closeLibraryQuickLook();
        return true;
      }
      if (reportKeyboardTargetIsEditable(event.target)) return false;
      if (event.metaKey || event.ctrlKey || event.altKey) return false;
      if (key === "ArrowLeft" || key === "ArrowRight") {
        event.preventDefault();
        event.stopPropagation();
        return switchReportJournalTab(key === "ArrowRight" ? 1 : -1);
      }
      if (key === "ArrowUp" || key === "ArrowDown") {
        const papers = activeReportPapers();
        if (!papers.length) return false;
        event.preventDefault();
        event.stopPropagation();
        ensureReportPaperSelection(papers);
        const currentIndex = papers.findIndex((paper) => paper.paper_id === state.reportSelectedPaperId);
        const fallback = key === "ArrowDown" ? 0 : papers.length - 1;
        const nextIndex = currentIndex < 0
          ? fallback
          : Math.max(0, Math.min(papers.length - 1, currentIndex + (key === "ArrowDown" ? 1 : -1)));
        selectReportPaper(papers[nextIndex].paper_id, {scroll: true});
        return true;
      }
      if (key === " ") {
        event.preventDefault();
        event.stopPropagation();
        openSelectedReportPaperQuickLook();
        return true;
      }
      return false;
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
      const progress = normalizedFetchProgress(selectedDate);
      return `
        <div class="empty fetch-progress" data-fetch-progress="${escapeAttr(selectedDate)}">
          <div class="fetch-progress-head">
            <strong>Fetching recent papers in the background. You can keep browsing other dates.</strong>
            <span class="fetch-progress-percent" data-role="fetch-percent">${progress.percent}%</span>
          </div>
          <div class="fetch-progress-track"><div class="fetch-progress-bar" data-role="fetch-bar" style="width:${progress.percent}%"></div></div>
          <div data-role="fetch-detail">${escapeHtml(progress.detail)}</div>
        </div>
      `;
    }

    function normalizedFetchProgress(selectedDate) {
      const progress = state.fetchProgress[selectedDate] || {};
      const percent = Math.max(0, Math.min(100, Number(progress.percent || 0)));
      const completed = Number(progress.completed || 0);
      const total = Number(progress.total || 0);
      const detail = total ? `${completed} / ${total} sources completed` : "Preparing fetch";
      return {percent, completed, total, detail};
    }

    function renderLibraryLoader() {
      const backdrop = $("libraryLoaderBackdrop");
      const root = $("libraryLoaderModalBody");
      if (!backdrop || !root) return;
      if (!state.libraryLoaderOpen) {
        backdrop.classList.remove("open");
        backdrop.setAttribute("aria-hidden", "true");
        return;
      }
      backdrop.classList.add("open");
      backdrop.setAttribute("aria-hidden", "false");
      const job = state.libraryImportJob || {};
      const result = state.libraryImportLastResult || job.result || null;
      const percent = Number(job.percent || 0);
      const status = state.libraryImportStatus || loaderStatusText(job);
      const previousConsole = $("libraryLoaderConsole");
      const consoleWasAtBottom = isLoaderConsoleAtBottom(previousConsole);
      const previousConsoleScrollTop = previousConsole?.scrollTop || 0;
      root.innerHTML = `
        <div class="loader-panel">
          <div class="loader-form">
            <input id="libraryImportPath" type="text" value="${escapeAttr(state.libraryImportPath || "")}" placeholder="/path/to/folder">
            <select id="libraryImportCopyMode" title="Import mode">
              <option value="copy"${(state.libraryImportCopyMode || "copy") === "copy" ? " selected" : ""}>Copy</option>
              <option value="link"${state.libraryImportCopyMode === "link" ? " selected" : ""}>Link</option>
            </select>
            <button class="smallbtn" id="libraryChooseFolder" type="button"${state.libraryImportBusy ? " disabled" : ""}>Choose Folder</button>
            <button class="smallbtn" id="libraryRunImport" type="button"${state.libraryImportBusy ? " disabled" : ""}>Import</button>
            <button class="smallbtn" id="libraryStopImport" type="button"${state.libraryImportBusy ? "" : " disabled"}>Stop Import</button>
            <button class="smallbtn danger" id="libraryDeleteImport" type="button"${state.libraryImportBusy ? " disabled" : ""}>Delete Import</button>
          </div>
          <div class="loader-progress">
            <span id="libraryImportStatus">${escapeHtml(status)}</span>
            <span>${percent ? `${percent}%` : ""}</span>
            <div class="loader-progress-track"><div class="loader-progress-bar" style="width:${percent}%"></div></div>
          </div>
          ${result ? `<div class="loader-result">${escapeHtml(loaderResultSummary(result))}</div>` : ""}
          <div class="loader-main">
            <div class="loader-console-wrap">
              <div class="loader-console" id="libraryLoaderConsole">${loaderConsoleMarkup(job)}</div>
              <button class="loader-jump-latest${state.libraryImportFollowLatest ? "" : " open"}" id="loaderJumpLatest" type="button" title="Jump to latest">↓</button>
            </div>
            <aside class="loader-side" id="libraryLoaderSide">${loaderSideMarkup(result)}</aside>
          </div>
        </div>
      `;
      wireLibraryImportTools();
      wireLoaderSide();
      resumeLibraryImportPollingIfNeeded();
      const consoleEl = $("libraryLoaderConsole");
      if (consoleEl) {
        consoleEl.scrollTop = state.libraryImportFollowLatest || consoleWasAtBottom ? consoleEl.scrollHeight : previousConsoleScrollTop;
        wireLoaderConsoleScroll(consoleEl);
      }
      $("loaderJumpLatest")?.addEventListener("click", jumpLoaderConsoleToLatest);
    }

    function loaderStatusText(job) {
      if (!job?.status) return "Idle";
      const base = `${job.status}${job.stage ? ` · ${job.stage}` : ""}`;
      if (job.stage === "scan") {
        return `${base} · ${job.scan_files || 0} files · ${job.scan_dirs || 0} folders`;
      }
      return base;
    }

    function isLoaderConsoleAtBottom(consoleEl) {
      if (!consoleEl) return true;
      return consoleEl.scrollHeight - consoleEl.scrollTop - consoleEl.clientHeight < 20;
    }

    function wireLoaderConsoleScroll(consoleEl) {
      consoleEl.addEventListener("scroll", () => {
        const atBottom = isLoaderConsoleAtBottom(consoleEl);
        state.libraryImportFollowLatest = atBottom;
        $("loaderJumpLatest")?.classList.toggle("open", !atBottom);
      }, {passive: true});
      $("loaderJumpLatest")?.classList.toggle("open", !state.libraryImportFollowLatest);
    }

    function jumpLoaderConsoleToLatest() {
      const consoleEl = $("libraryLoaderConsole");
      state.libraryImportFollowLatest = true;
      if (consoleEl) consoleEl.scrollTop = consoleEl.scrollHeight;
      $("loaderJumpLatest")?.classList.remove("open");
    }

    function loaderResultSummary(result) {
      return [
        `${result.created_papers || 0} created`,
        `${result.existing_papers || 0} existing`,
        `${result.updated_papers || 0} updated`,
        `${result.resources_or_attachments_to_import || 0} resources/attachments`,
        `${result.reused_existing_files || 0} reused`,
        `${result.pdf_doi_extracted_count || 0} DOI found`,
        `${result.pdf_doi_missing_count || 0} no DOI`,
        `${result.skipped || 0} skipped`,
        `${result.missing_source_files || 0} missing`,
        result.report_path ? `Report: ${result.report_path}` : ""
      ].filter(Boolean).join(" · ");
    }

    function loaderConsoleMarkup(job) {
      const logs = Array.isArray(job.logs) ? job.logs : [];
      if (!logs.length) return escapeHtml("Ready. Choose a folder, then run Import.");
      return logs.map((entry) => {
        const message = entry.message || "";
        const kind = loaderLogKind(entry);
        const groupClass = loaderLogGroupClass(message);
        const label = loaderLogLabel(kind);
        const time = String(entry.time || "").split("T").pop() || "";
        return `
          <div class="loader-line ${escapeAttr(kind)} ${escapeAttr(groupClass)}">
            <span class="loader-badge">${escapeHtml(label)}</span>
            <span class="loader-time">${escapeHtml(time)}</span>
            <span class="loader-message">${loaderLogMessageMarkup(message)}</span>
          </div>
        `;
      }).join("");
    }

    function loaderLogGroupClass(message) {
      const text = String(message || "");
      if (text.startsWith("Entering ")) return "folder-enter";
      if (text.startsWith("Reading first PDF page")) return "file-start";
      return "";
    }

    function loaderLogKind(entry) {
      const level = String(entry.level || "info");
      const message = String(entry.message || "");
      if (level === "error" || /failed|error/i.test(message)) return "error";
      if (level === "warn" || /warning/i.test(message)) return "warn";
      if (message.startsWith("DOI extracted:")) return "doi-ok";
      if (message.startsWith("No DOI extracted")) return "doi-missing";
      if (message.startsWith("Refreshing Details metadata")) return "metadata";
      if (message.startsWith("Stop requested") || message.includes("stopped by user")) return "warn";
      if (message.startsWith("Deleted import batch")) return "warn";
      if (message.startsWith("Importing") || message.startsWith("Imported/checkpoint")) return "import";
      if (message.startsWith("Entering ")) return "enter";
      if (message.startsWith("Reading first PDF page") || message.startsWith("Scanning folder") || message.startsWith("Scanned ")) return "scan";
      if (message.startsWith("Inventory written") || message.startsWith("Report written") || message.startsWith("Source folder") || message.startsWith("Mode:")) return "file";
      if (message.startsWith("Done:") || message.startsWith("Import complete") || message.startsWith("Refreshed DOI metadata for") || message.startsWith("Refreshed DOI/arXiv metadata for")) return "done";
      return "info";
    }

    function loaderLogLabel(kind) {
      return {
        "doi-ok": "DOI",
        "doi-missing": "NO DOI",
        metadata: "META",
        import: "IMPORT",
        enter: "ENTER",
        scan: "SCAN",
        file: "FILE",
        done: "DONE",
        error: "ERROR",
        warn: "WARN",
        info: "INFO"
      }[kind] || "INFO";
    }

    function loaderLogMessageMarkup(message) {
      const escaped = escapeHtml(message || "");
      return escaped.replace(/(10\.\d{4,9}\/[^\s<]+)/gi, '<span class="loader-token-doi">$1</span>');
    }

    function loaderSideMarkup(result) {
      if (!result) {
        return `
          <h3>Result Guide</h3>
          <p>After an import finishes, this panel explains each number and lists files that need attention.</p>
          <div class="loader-metric"><strong>Created</strong><span>new Library item records for papers and other files.</span></div>
          <div class="loader-metric"><strong>Existing</strong><span>records already in Library are left unchanged during repeated imports.</span></div>
          <div class="loader-metric"><strong>Updated</strong><span>records refreshed by explicit metadata actions, not by repeated folder loading.</span></div>
          <div class="loader-metric"><strong>DOI found</strong><span>PDF files where the loader extracted a DOI from the first page or filename.</span></div>
          <div class="loader-metric"><strong>No DOI</strong><span>PDF files that did not expose a DOI during the loader scan.</span></div>
          <div class="loader-metric"><strong>Resources</strong><span>PDF attachments plus non-PDF resource files.</span></div>
          <div class="loader-metric"><strong>Skipped</strong><span>system metadata and macOS aliases; source files are not deleted.</span></div>
          <div class="loader-metric"><strong>Missing</strong><span>paths recorded in the scan but not readable during import.</span></div>
        `;
      }
      const missing = Array.isArray(result.missing_sources) ? result.missing_sources : [];
      const selectedIndex = Math.max(0, Math.min(Number(state.libraryImportMissingIndex || 0), Math.max(0, missing.length - 1)));
      const selected = missing[selectedIndex] || null;
      const missingDoi = Array.isArray(result.pdfs_without_doi) ? result.pdfs_without_doi : [];
      const doiIndex = Math.max(0, Math.min(Number(state.libraryImportMissingDoiIndex || 0), Math.max(0, missingDoi.length - 1)));
      const selectedDoi = missingDoi[doiIndex] || null;
      return `
        <h3>Result Guide</h3>
        <div class="loader-metric"><strong>${result.created_papers || 0} created</strong><span>New Library item records made for papers and other files.</span></div>
        <div class="loader-metric"><strong>${result.existing_papers || 0} existing</strong><span>Already-known files matched by DOI, arXiv, or source path and were left unchanged.</span></div>
        <div class="loader-metric"><strong>${result.updated_papers || 0} updated</strong><span>Records refreshed by explicit metadata actions, not by repeated folder loading.</span></div>
        <div class="loader-metric"><strong>${result.pdf_doi_extracted_count || 0} DOI found</strong><span>PDF files where the loader found a DOI from the first page or filename.</span></div>
        <div class="loader-metric"><strong>${result.pdf_doi_missing_count || 0} no DOI</strong><span>PDF files imported by path identity because no DOI was extracted.</span></div>
        <div class="loader-metric"><strong>${result.resources_or_attachments_to_import || 0} resources</strong><span>Imported PDF attachments plus non-PDF resources. This includes ${result.pdf_attachments_to_import || 0} PDF files and ${result.created_resources || 0} non-PDF resources.</span></div>
        <div class="loader-metric"><strong>${result.reused_existing_files || 0} reused</strong><span>Already-copied files reused from Journal Monitor storage, so repeated imports do not copy them again.</span></div>
        <div class="loader-metric"><strong>${result.skipped || 0} skipped</strong><span>${result.skipped_system_metadata || 0} system metadata and ${result.mac_aliases_found || 0} macOS aliases. Normal papers are not deleted by this.</span></div>
        <div class="loader-metric"><strong>${result.missing_source_files || 0} missing</strong><span>Source paths that could not be read during import. These need checking in Finder.</span></div>
        <div class="loader-metric"><strong>${result.duplicate_paper_candidates || 0} duplicates</strong><span>${result.doi_duplicates || 0} DOI duplicates and ${result.arxiv_duplicates || 0} arXiv duplicates were merged into existing paper records.</span></div>
        <h3 style="margin-top:12px;">PDFs Without DOI</h3>
        ${missingDoi.length ? `
          <div class="loader-missing-tools">
            <select id="loaderMissingDoiSelect">
              ${missingDoi.map((item, index) => `<option value="${index}"${index === doiIndex ? " selected" : ""}>${escapeHtml(`${index + 1}. ${item.filename || item.relative_path || item.source_path || "PDF without DOI"}`)}</option>`).join("")}
            </select>
            <button class="smallbtn" id="loaderRevealMissingDoi" type="button">Show in Finder</button>
          </div>
          <div class="loader-missing-path">${escapeHtml(selectedDoi?.source_path || "")}</div>
          ${selectedDoi?.parse_status ? `<div class="loader-missing-path">Parse: ${escapeHtml(selectedDoi.parse_status)}${selectedDoi.parse_error ? ` · ${escapeHtml(selectedDoi.parse_error)}` : ""}</div>` : ""}
        ` : `<p>All scanned PDF paper candidates had a DOI.</p>`}
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
      const doiSelect = $("loaderMissingDoiSelect");
      doiSelect?.addEventListener("change", () => {
        state.libraryImportMissingDoiIndex = Number(doiSelect.value || 0);
        renderLibraryLoader();
      });
      $("loaderRevealMissing")?.addEventListener("click", () => revealSelectedMissingFile().catch((error) => {
        state.libraryImportStatus = error.message || "Could not open Finder";
        renderLibraryLoader();
      }));
      $("loaderRevealMissingDoi")?.addEventListener("click", () => revealSelectedMissingDoiFile().catch((error) => {
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

    async function revealSelectedMissingDoiFile() {
      const result = state.libraryImportLastResult || state.libraryImportJob?.result || {};
      const missing = Array.isArray(result.pdfs_without_doi) ? result.pdfs_without_doi : [];
      const item = missing[Number(state.libraryImportMissingDoiIndex || 0)];
      const path = item?.source_path || "";
      if (!path) throw new Error("No PDF without DOI selected");
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
      clearFetchProgressDisplay();
      renderLibraryTabs();
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("reportTitle").textContent = libraryViewTitle();
      const root = $("papers");
      captureLibraryColumnScrollTops();
      const previousColumnsScrollLeft = $("libraryColumns")?.scrollLeft ?? state.libraryColumnsScrollLeft;
      $("summary").textContent = "";
      root.classList.remove("deep-survey-view");
      root.classList.add("library-view");
      root.innerHTML = `
        <div class="library-shell" id="libraryShell" tabindex="0" style="--library-detail-width:${Math.max(280, Math.min(620, Number(state.libraryDetailWidth || 420)))}px">
          <aside class="library-tab-rail" id="libraryShortcutTabs" aria-label="Library shortcuts and spaces"></aside>
          <div class="library-main-area">
            ${workspaceToolsMarkup()}
            ${librarySearchIsActive()
              ? `<div class="library-search-results" id="librarySearchResults"></div>`
              : `<div class="library-columns" id="libraryColumns"></div>`}
          </div>
          <div class="library-detail-divider" id="libraryDetailDivider" title="Resize details"></div>
          <aside class="library-pane">
            ${libraryPaneHeaderMarkup()}
            <div class="library-detail" id="libraryDetail"></div>
          </aside>
          <div class="library-path-bar" id="libraryPathBar" title="${escapeAttr(librarySelectionPathText())}">
            <span class="library-path-parts">${librarySelectionPathMarkup()}</span>
            <span class="${libraryActivityStatusClass()}" id="libraryActivityStatus">${escapeHtml(libraryActivityStatusText())}</span>
          </div>
        </div>
        <div class="library-tab-context-menu" id="libraryTabContextMenu">
          <button type="button" data-action="rename-tab">Rename</button>
        </div>
        <div class="library-context-menu" id="libraryContextMenu">
          <button type="button" data-action="new-folder">New Folder</button>
          <button type="button" data-action="rename-entry">Rename</button>
          <button type="button" data-action="copy-entry">Copy</button>
          <button type="button" data-action="add-to-my-publications">Add to My Publications</button>
          <button type="button" data-action="open-native-entry">Open Native File</button>
          <button type="button" data-action="reveal-native-entry">Open in Finder</button>
          <button type="button" data-action="color-folder">Color</button>
          <button type="button" data-action="paste-entry">Paste</button>
          <button type="button" data-action="recover-entry">Recover</button>
          <button type="button" data-action="delete-special-original-files">Delete All Original Files</button>
          <button type="button" data-action="remove-special-library">Remove All from Library</button>
          <button type="button" data-action="delete-entry">Remove from current collection</button>
          <button type="button" data-action="delete-file-entry">Delete File...</button>
          <input class="library-color-input" data-action="folder-color-picker" type="color" value="#4f46e5">
        </div>
      `;
      renderLibraryShortcutTabs();
      wireLibraryPaneTools();
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

    function librarySelectionPathParts() {
      const displayRootId = Number(libraryDisplayRootId() || state.libraryRootId || 1);
      const folderParts = [];
      const seen = new Set();
      let folderId = displayRootId;
      let leafName = "";
      const selection = state.librarySelection || {};
      if (selection.type === "item") {
        const item = libraryItemById(selection.id);
        folderId = Number(item?.folder_id || state.libraryActiveFolderId || displayRootId);
        leafName = item?.display_name || libraryPaperDisplayName(item?.paper || {}) || "Untitled";
      } else if (selection.type === "folder") {
        folderId = Number(selection.id || displayRootId);
      } else {
        folderId = Number(state.libraryActiveFolderId || displayRootId);
      }
      let current = folderId;
      while (current && !seen.has(current)) {
        seen.add(current);
        const folder = libraryFolderById(current);
        if (!folder) break;
        folderParts.unshift({type: "folder", name: folder.name || "Library", iconClass: libraryEntryIconClass("folder", folder)});
        if (current === displayRootId) break;
        current = Number(folder.parent_id || displayRootId);
      }
      if (!folderParts.length) {
        const displayRoot = libraryFolderById(displayRootId);
        folderParts.push({type: "folder", name: displayRoot?.name || "Library", iconClass: libraryEntryIconClass("folder", displayRoot || {})});
      }
      if (leafName) folderParts.push({type: "document", name: leafName, iconClass: "document"});
      return folderParts;
    }

    function librarySelectionPathText() {
      return librarySelectionPathParts().map((part) => part.name).join(" > ");
    }

    function librarySelectionPathMarkup() {
      return librarySelectionPathParts()
        .map((part, index) => `
          ${index ? `<span class="library-path-separator">›</span>` : ""}
          <span class="library-path-item">
            <span class="library-entry-icon ${escapeAttr(part.iconClass || (part.type === "folder" ? "folder" : "document"))} library-path-icon" aria-hidden="true"></span>
            <span class="library-path-part">${escapeHtml(part.name)}</span>
          </span>
        `)
        .join("");
    }

    function libraryActivityStatusText() {
      return state.libraryActivityText || "";
    }

    function libraryActivityStatusClass() {
      const base = "library-activity-status";
      if (!state.libraryActivityText) return base;
      if (state.libraryActivityLive) return `${base} live`;
      if (/failed|could not|error/i.test(state.libraryActivityText)) return `${base} err`;
      return `${base} ok`;
    }

    function updateLibraryActivityStatus(text = "", options = {}) {
      if (state.libraryActivityTimer) {
        window.clearTimeout(state.libraryActivityTimer);
        state.libraryActivityTimer = 0;
      }
      state.libraryActivityText = text;
      state.libraryActivityLive = Boolean(options.live);
      const status = $("libraryActivityStatus");
      if (status) {
        status.textContent = libraryActivityStatusText();
        status.className = libraryActivityStatusClass();
      }
      if (text && !options.live && options.clear !== false) {
        state.libraryActivityTimer = window.setTimeout(() => {
          state.libraryActivityText = "";
          state.libraryActivityLive = false;
          const current = $("libraryActivityStatus");
          if (current) {
            current.textContent = "";
            current.className = libraryActivityStatusClass();
          }
        }, Number(options.delay || 1800));
      }
    }

    async function withLibraryActivityStatus(liveText, doneText, action) {
      updateLibraryActivityStatus(liveText, {live: true, clear: false});
      try {
        const result = await action();
        updateLibraryActivityStatus(doneText, {live: false});
        return result;
      } catch (error) {
        updateLibraryActivityStatus(`Library action failed: ${error.message || "Unknown error"}`, {live: false});
        throw error;
      }
    }

    function libraryPaneHeaderMarkup(options = {}) {
      return "";
    }

    function wireLibraryPaneTools() {
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
          <input class="search" id="workspaceDoiInput" placeholder="DOI or arXiv ID">
          <button class="smallbtn" id="workspaceAddDoiButton" type="button">Add Paper</button>
          <span class="workspace-status" id="workspaceStatus">${escapeHtml(state.workspaceStatus || "This space works like Library. Add papers by DOI or arXiv ID into its root.")}</span>
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
        `${result.existing_papers || 0} existing`,
        `${result.updated_papers || 0} update`,
        `${result.pdf_doi_extracted_count || 0} DOI`,
        `${result.pdf_doi_missing_count || 0} no DOI`,
        `${result.resources_or_attachments_to_import || 0} resources`,
        `${result.skipped || 0} skipped`,
        `${result.missing_source_files || 0} missing`,
        result.report_path ? `Report: ${result.report_path}` : ""
      ].filter(Boolean).join(" · ") : "";
      const status = state.libraryImportStatus || summary || "";
      const statusClass = result?.errors?.length ? " err" : (result ? " ok" : "");
      statusEl.textContent = status;
      statusEl.className = `toolbar-import-status${status ? " open" : ""}${statusClass}`;
      const runButton = $("libraryRunImport");
      const stopButton = $("libraryStopImport");
      const deleteButton = $("libraryDeleteImport");
      if (runButton) runButton.disabled = state.libraryImportBusy;
      if (stopButton) stopButton.disabled = !state.libraryImportBusy;
      if (deleteButton) deleteButton.disabled = state.libraryImportBusy;
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
      $("libraryRunImport")?.addEventListener("click", runLibraryFolderImport);
      $("libraryStopImport")?.addEventListener("click", stopLibraryFolderImport);
      $("libraryDeleteImport")?.addEventListener("click", deleteLibraryFolderImport);
    }

    async function chooseLibraryImportFolder() {
      await runLibraryMenuAction(async () => {
        state.libraryImportStatus = "Waiting for macOS folder permission...";
        renderLibraryLoader();
        const res = await fetch("/api/library/import-folder/choose", {method: "POST", headers: {"Content-Type": "application/json"}, body: "{}"});
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not choose folder");
        state.libraryImportPath = data.path || "";
        state.libraryImportStatus = "Folder selected. Ready to import.";
        state.libraryImportLastResult = null;
        renderLibraryLoader();
      });
    }

    async function runLibraryFolderImport() {
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
      state.libraryImportStatus = "Starting import loader...";
      state.libraryImportLastResult = null;
      state.libraryImportJob = {status: "starting", stage: "queued", logs: [{time: new Date().toISOString(), level: "info", message: state.libraryImportStatus}], percent: 0};
      renderLibraryLoader();
      try {
        const res = await fetch("/api/library/import-folder/start", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({folder_path: path, copy_mode: copyMode})
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

    async function stopLibraryFolderImport() {
      if (!state.libraryImportJobId || !state.libraryImportBusy) return;
      state.libraryImportStatus = "Stopping import at the next safe checkpoint...";
      renderLibraryLoader();
      try {
        const res = await fetch("/api/library/import-folder/stop", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({job_id: state.libraryImportJobId})
        });
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not stop import");
        state.libraryImportJob = data.job || state.libraryImportJob;
        startLibraryImportPolling();
      } catch (error) {
        state.libraryImportStatus = error.message || "Could not stop import";
        renderLibraryLoader();
      }
    }

    async function deleteLibraryFolderImport() {
      if (state.libraryImportBusy) return;
      state.libraryImportStatus = "Deleting import batch...";
      appendLibraryImportLog("Deleting import batch and copied local files...", "warn");
      renderLibraryLoader();
      try {
        const res = await fetch("/api/library/import-folder/delete", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({job_id: state.libraryImportJobId})
        });
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not delete import");
        applyLibrarySnapshot(data);
        const deleted = data.delete_result || {};
        state.libraryImportBusy = false;
        state.libraryImportJobId = "";
        if (!state.libraryImportJob) {
          state.libraryImportJob = {status: "deleted", stage: "deleted", logs: [], percent: 100};
        }
        state.libraryImportJob.status = "deleted";
        state.libraryImportJob.stage = "deleted";
        state.libraryImportJob.percent = 100;
        state.libraryImportLastResult = null;
        state.libraryImportStatus = `Deleted import: ${deleted.deleted_papers || 0} papers, ${deleted.deleted_resources || 0} resources, ${deleted.deleted_folders || 0} folders`;
        appendLibraryImportLog(state.libraryImportStatus, "warn");
        if (Array.isArray(deleted.deleted_paths) && deleted.deleted_paths.length) {
          appendLibraryImportLog(`Deleted local paths: ${deleted.deleted_paths.join(", ")}`, "warn");
        }
        renderLibraryLoader();
      } catch (error) {
        state.libraryImportStatus = error.message || "Could not delete import";
        appendLibraryImportLog(state.libraryImportStatus, "error");
        renderLibraryLoader();
      }
    }

    function appendLibraryImportLog(message, level = "info") {
      if (!state.libraryImportJob) {
        state.libraryImportJob = {
          status: state.libraryImportStatus || "running",
          stage: "local",
          logs: [],
          percent: 0
        };
      }
      const logs = Array.isArray(state.libraryImportJob.logs) ? state.libraryImportJob.logs : [];
      logs.push({time: new Date().toISOString(), level, message});
      if (logs.length > 500) logs.splice(0, logs.length - 500);
      state.libraryImportJob.logs = logs;
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

    function resumeLibraryImportPollingIfNeeded() {
      if (!state.libraryImportJobId || state.libraryImportPoller) return;
      const status = state.libraryImportJob?.status || "";
      if (["completed", "failed", "cancelled", "deleted"].includes(status)) return;
      startLibraryImportPolling();
    }

    async function refreshLibraryImportJob() {
      if (!state.libraryImportJobId) return;
      try {
        const res = await fetch(`/api/library/import-folder/progress?job_id=${encodeURIComponent(state.libraryImportJobId)}`);
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not read loader progress");
        const job = data.job || {};
        state.libraryImportJob = job;
        state.libraryImportStatus = loaderStatusText(job);
        if (job.result) state.libraryImportLastResult = job.result;
        if (["completed", "failed", "cancelled", "deleted"].includes(job.status)) {
          state.libraryImportBusy = false;
          stopLibraryImportPolling();
          if (job.status === "completed") {
            const libraryRes = await fetch("/api/library");
            const libraryData = await libraryRes.json();
            if (libraryRes.ok) applyLibrarySnapshot(libraryData);
          }
        }
        if (state.libraryLoaderOpen) renderLibraryLoader();
      } catch (error) {
        state.libraryImportStatus = error.message || "Could not read loader progress";
        state.libraryImportBusy = false;
        stopLibraryImportPolling();
        if (state.libraryLoaderOpen) renderLibraryLoader();
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

    async function handleNativeFinderDrop(paths) {
      const droppedPaths = Array.isArray(paths)
        ? paths.filter((path) => typeof path === "string" && path.trim())
        : [];
      if (!droppedPaths.length) return;
      if (state.mode !== "library") {
        renderLibrary();
      }
      if (state.libraryTab === "my-publications" || state.libraryTab === "loader") {
        state.libraryTab = "library";
        renderLibrary();
      }
      const targetFolderId = libraryPasteTargetFolderId();
      const targetFolder = libraryFolderById(targetFolderId) || libraryFolderById(state.libraryRootId);
      const choice = await promptFinderDropMode(droppedPaths, targetFolder?.name || "Library");
      if (!choice) return;
      await importFinderDropPaths(droppedPaths, choice, targetFolderId);
    }

    function promptFinderDropMode(paths, targetName) {
      return new Promise((resolve) => {
        document.querySelector(".finder-drop-modal-backdrop")?.remove();
        const backdrop = document.createElement("div");
        backdrop.className = "finder-drop-modal-backdrop";
        const count = paths.length;
        const pathPreview = paths.slice(0, 5).map((path) => `<div>${escapeHtml(path)}</div>`).join("");
        const more = count > 5 ? `<div>...and ${count - 5} more</div>` : "";
        backdrop.innerHTML = `
          <div class="finder-drop-modal" role="dialog" aria-modal="true" aria-labelledby="finderDropTitle">
            <h2 id="finderDropTitle">Import into ${escapeHtml(targetName)}</h2>
            <p>Choose whether Daiqo should copy the original files into Library storage, or keep links to the files in their current Finder location.</p>
            <div class="finder-drop-paths">${pathPreview}${more}</div>
            <div class="finder-drop-actions">
              <button type="button" data-mode="cancel">Cancel</button>
              <button type="button" data-mode="link">Import Links</button>
              <button type="button" class="primary" data-mode="copy">Copy Originals</button>
            </div>
          </div>
        `;
        document.body.appendChild(backdrop);
        const finish = (mode) => {
          backdrop.remove();
          window.removeEventListener("keydown", onKeyDown);
          resolve(mode === "copy" || mode === "link" ? mode : "");
        };
        const onKeyDown = (event) => {
          if (event.key === "Escape") finish("");
        };
        backdrop.addEventListener("click", (event) => {
          if (event.target === backdrop) finish("");
        });
        backdrop.querySelectorAll("[data-mode]").forEach((button) => {
          button.addEventListener("click", () => finish(button.dataset.mode || ""));
        });
        window.addEventListener("keydown", onKeyDown);
        backdrop.querySelector(".primary")?.focus({preventScroll: true});
      });
    }

    async function importFinderDropPaths(paths, copyMode, targetFolderId) {
      stopLibraryImportPolling();
      state.libraryImportBusy = true;
      state.libraryImportCopyMode = copyMode;
      state.libraryImportStatus = `Importing ${paths.length} dropped item${paths.length === 1 ? "" : "s"} into Library...`;
      state.libraryImportLastResult = null;
      appendLibraryImportLog(state.libraryImportStatus, "info");
      updateToolbarLibraryImport();
      try {
        const res = await fetch("/api/library/import-paths", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({paths, copy_mode: copyMode, target_folder_id: targetFolderId})
        });
        const data = await parseJsonResponse(res);
        if (!res.ok) throw new Error(data.error || "Could not import dropped files");
        applyLibrarySnapshot(data);
        state.libraryImportBusy = false;
        state.libraryImportLastResult = data.import_result || null;
        const result = state.libraryImportLastResult || {};
        state.libraryImportStatus = result.errors?.length
          ? result.errors[0]
          : `Imported ${result.created_papers || 0} new items, left ${result.existing_papers || 0} existing unchanged, added ${result.created_resources || 0} non-PDF resources.`;
        appendLibraryImportLog(state.libraryImportStatus, result.errors?.length ? "error" : "done");
        state.libraryTab = "library";
        focusLibraryFolder(targetFolderId);
      } catch (error) {
        state.libraryImportBusy = false;
        state.libraryImportStatus = error.message || "Could not import dropped files";
        state.libraryImportLastResult = {errors: [state.libraryImportStatus]};
        appendLibraryImportLog(state.libraryImportStatus, "error");
        updateToolbarLibraryImport();
      }
    }

    function renderLibraryTabs() {
      $("libraryControls").classList.toggle("open", state.libraryTab === "my-publications");
      setPrimaryView(state.libraryTab === "my-publications" ? "my-publications" : "library");
      renderLibraryShortcutTabs();
      $("myPublicationsTools")?.classList.toggle("open", state.libraryTab === "my-publications");
      const nameInput = $("myPublicationName");
      if (nameInput && document.activeElement !== nameInput) nameInput.value = state.myPublicationName || "";
      updateMyPublicationScholarProfileStrip();
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
      tools.classList.toggle("has-query", Boolean(state.query));
      if (document.activeElement !== input) input.value = state.query || "";
      clear.classList.toggle("open", Boolean(state.query));
      const results = open && state.query.trim() ? librarySearchResults().length : 0;
      count.textContent = state.query.trim() ? `${results} match${results === 1 ? "" : "es"}` : "";
    }

    function commitLibrarySearch(value) {
      window.clearTimeout(librarySearchTimer);
      librarySearchTimer = 0;
      if (state.mode !== "library" || ["loader", "my-publications"].includes(state.libraryTab || "")) return;
      const nextQuery = String(value || "");
      if (state.query === nextQuery) {
        updateLibrarySearchTools();
        return;
      }
      state.query = nextQuery;
      clearLibraryRangeSelection();
      renderActiveLibraryTab();
    }

    function scheduleLibrarySearch(value) {
      window.clearTimeout(librarySearchTimer);
      librarySearchTimer = window.setTimeout(() => commitLibrarySearch(value), 450);
    }

    function renderLibraryShortcutTabs() {
      const root = $("libraryShortcutTabs");
      if (!root) return;
      const rootTab = `<button class="library-tab root-tab${state.libraryTab === "library" ? " active" : ""}" style="--tab-top:0px" type="button" data-root-tab="library" title="Library"><span class="library-tab-label">Library</span></button>`;
      const shortcutTabs = Array.from({length: LIBRARY_SHORTCUT_TAB_COUNT}, (_, index) => {
        const assigned = Boolean(Number(state.libraryShortcutTabs[index]?.folder_id || 0));
        const label = libraryShortcutLabel(index);
        return `<button class="library-tab shortcut-tab${state.libraryTab === `shortcut-${index}` ? " active" : ""}" style="--tab-top:${(index + 1) * 92}px" type="button" data-shortcut-tab="${index}" title="${assigned ? "Folder shortcut" : "Drop a Library folder here"}"><span class="library-tab-label">${escapeHtml(label)}</span></button>`;
      }).join("");
      const workspaceTabs = Array.from({length: LIBRARY_WORKSPACE_TAB_COUNT}, (_, index) => (
        `<button class="library-tab workspace-tab${state.libraryTab === `workspace-${index}` ? " active" : ""}" style="--tab-top:${(LIBRARY_SHORTCUT_TAB_COUNT + 1 + index) * 92 + 14}px" type="button" data-workspace-tab="${index}" title="${escapeAttr(libraryWorkspaceLabel(index))}"><span class="library-tab-label">${escapeHtml(libraryWorkspaceLabel(index))}</span></button>`
      )).join("");
      const railHeight = (LIBRARY_SHORTCUT_TAB_COUNT + LIBRARY_WORKSPACE_TAB_COUNT + 1) * 92 + 14;
      root.innerHTML = `
        <div class="library-tab-rail-inner" style="--library-rail-height:${railHeight}px">
          ${rootTab}
          ${shortcutTabs}
          ${workspaceTabs}
        </div>
      `;
      root.querySelector("[data-root-tab]")?.addEventListener("click", () => {
        loadLibrary().catch((error) => {
          $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
        });
      });
      root.querySelectorAll("[data-shortcut-tab]").forEach((button) => {
        button.addEventListener("click", () => openLibraryShortcutTab(Number(button.dataset.shortcutTab || 0)));
        button.addEventListener("contextmenu", (event) => {
          event.preventDefault();
          event.stopPropagation();
          showLibraryTabContextMenu(event, "shortcut", Number(button.dataset.shortcutTab || 0));
        });
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
        button.addEventListener("contextmenu", (event) => {
          event.preventDefault();
          event.stopPropagation();
          showLibraryTabContextMenu(event, "workspace", Number(button.dataset.workspaceTab || 0));
        });
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

    async function renameLibraryShortcutTab(index) {
      const current = libraryShortcutLabel(index);
      const label = window.prompt("Rename shortcut", current);
      if (label === null) return;
      const res = await fetch("/api/library/shortcut-tabs/rename", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({index, label})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not rename shortcut");
      applyLibrarySnapshot(data);
      if (state.libraryTab === `shortcut-${index}`) state.libraryTab = `shortcut-${index}`;
      renderLibrary();
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

    async function renameLibraryWorkspace(index, labelOverride = null) {
      const label = labelOverride === null ? ($("workspaceNameInput")?.value || `Space ${index + 1}`) : labelOverride;
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

    async function renameLibraryWorkspaceFromTab(index) {
      const current = libraryWorkspaceLabel(index);
      const label = window.prompt("Rename space", current);
      if (label === null) return;
      await renameLibraryWorkspace(index, label);
    }

    async function addLibraryWorkspaceDoi(index) {
      const identifier = $("workspaceDoiInput")?.value || "";
      if (!identifier.trim()) return;
      state.workspaceStatus = "Looking up identifier...";
      state.libraryTab = `workspace-${index}`;
      renderLibrary();
      try {
        const res = await fetch("/api/library/workspace-tabs/add-doi", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({index, identifier})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not add paper");
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

    function renderMyPublications(options = {}) {
      const existingResults = $("publicationSearchResults");
      const previousSearchScrollTop = existingResults ? existingResults.scrollTop : Number(state.myPublicationSearchScrollTop || 0);
      const existingTableWrap = document.querySelector(".my-publications-table-wrap");
      const previousTableScrollTop = existingTableWrap ? existingTableWrap.scrollTop : 0;
      const existingDetail = $("libraryDetail");
      const previousDetailScrollTop = existingDetail ? existingDetail.scrollTop : 0;
      const previousStatsScrollTops = Array.from(document.querySelectorAll(".my-publications-stat-list"))
        .map((element) => element.scrollTop || 0);
      state.mode = "library";
      state.libraryTab = "my-publications";
      clearScheduledMyPublicationDetailRender();
      stopArxivUpdateCountdown();
      clearFetchProgressDisplay();
      renderLibraryTabs();
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("reportTitle").textContent = "Library";
      const allRows = sortedMyPublications();
      const rows = myPublicationFilteredRows(allRows);
      const selected = myPublicationById(state.myPublicationSelectionId) || rows[0] || null;
      const visibleSelected = selected && rows.some((entry) => Number(entry.id) === Number(selected.id));
      if (visibleSelected) state.myPublicationSelectionId = Number(selected.id);
      else if (rows[0]) state.myPublicationSelectionId = Number(rows[0].id);
      else state.myPublicationSelectionId = 0;
      pruneMyPublicationSelection();
      $("summary").textContent = "";
      const root = $("papers");
      root.classList.remove("deep-survey-view");
      root.classList.add("library-view");
      root.innerHTML = `
        <div class="library-shell my-publications-shell" id="libraryShell" tabindex="0">
          <section class="my-publications-panel">
            <div class="my-publications-search">
              <div class="publication-search-results" id="publicationSearchResults">${myPublicationSearchResultsMarkup()}</div>
            </div>
            <div class="my-publications-table-wrap">
              <table class="my-publications-table" style="--my-publications-table-width:${myPublicationTableWidth()}px">
                <colgroup>${myPublicationColgroupMarkup()}</colgroup>
                <thead>
                  <tr>${myPublicationHeaderMarkup()}</tr>
                </thead>
                <tbody>
                  ${rows.length ? rows.map((entry, index) => myPublicationRowMarkup(entry, index)).join("") : `<tr><td colspan="${MY_PUBLICATION_COLUMNS.length}"><div class="empty">${allRows.length ? "No matching publications." : "No publications yet."}</div></td></tr>`}
                </tbody>
              </table>
            </div>
            ${myPublicationStatsMarkup(allRows)}
          </section>
          <aside class="library-pane">
            ${libraryPaneHeaderMarkup({hideLoader: true})}
            <div class="library-detail" id="libraryDetail"></div>
          </aside>
        </div>
        <div class="library-context-menu my-publication-context-menu" id="myPublicationContextMenu">
          <button type="button" data-action="toggle-my-publication-head">Hide</button>
          <button type="button" data-action="delete-my-publication">Delete</button>
        </div>
      `;
      resizeLibraryViewport();
      wireLibraryPaneTools();
      renderPublicationDetail();
      wireMyPublicationInteractions();
      const restoredResults = $("publicationSearchResults");
      if (restoredResults) restoredResults.scrollTop = previousSearchScrollTop;
      const restoredTableWrap = document.querySelector(".my-publications-table-wrap");
      if (restoredTableWrap) {
        restoredTableWrap.scrollTop = Number.isFinite(Number(options.tableScrollTop))
          ? Number(options.tableScrollTop)
          : previousTableScrollTop;
      }
      const restoredDetail = $("libraryDetail");
      if (restoredDetail) {
        restoredDetail.scrollTop = Number.isFinite(Number(options.detailScrollTop))
          ? Number(options.detailScrollTop)
          : previousDetailScrollTop;
      }
      document.querySelectorAll(".my-publications-stat-list").forEach((element, index) => {
        element.scrollTop = Number(previousStatsScrollTops[index] || 0);
      });
      updateMyPublicationSearchStatusText();
      window.requestAnimationFrame(() => resizeLibraryViewport());
      if (options.revealSelection) window.requestAnimationFrame(() => revealMyPublicationSelection());
    }

    function updateMyPublicationSearchStatusText() {
      const status = document.querySelector(".publication-search-status");
      if (status) {
        status.textContent = myPublicationSearchStatusText();
        status.className = `${myPublicationSearchStatusClass()} my-publications-tool-note`;
      }
      updateMyPublicationScholarProfileStrip();
    }

    function myPublicationSearchStatusText() {
      return state.myPublicationSearchStatus || "Use DOI/arXiv/title, or search by name with optional units: Name; Unit A; Unit B.";
    }

    function myPublicationSearchStatusClass() {
      return `publication-search-status${myPublicationSearchStatusIsLive() ? " live" : ""}`;
    }

    function myPublicationSearchStatusIsLive(text = state.myPublicationSearchStatus) {
      if (state.myPublicationMetricsRefreshing) return true;
      return /(adding|building|checking|deleting|fetching|importing|matching|refreshing|reimporting|resolving|retrying|searching|starting|stopping|updating)/i.test(String(text || ""));
    }

    function myPublicationScholarProfileMarkup() {
      const profile = state.myPublicationScholarProfile || {};
      const profileUrl = scholarProfileExternalUrl(profile);
      const hasSavedProfile = Boolean(profile.name || profile.avatar_url || profileUrl || profile.user_id);
      const chips = myPublicationProfileStatusChips(profile);
      if (!hasSavedProfile && !chips.length) return "";
      const avatarUrl = profile.avatar_url || "";
      const initials = scholarProfileInitials(profile.name || "") || "GS";
      const avatarMarkup = avatarUrl
        ? `<img src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(profile.name || "Google Scholar profile")}" onerror="this.remove(); this.parentElement.textContent='${escapeAttr(initials)}';">`
        : `${escapeHtml(initials)}`;
      return `
        <div class="my-publications-profile-strip" id="myPublicationProfileStrip">
          <div class="my-publications-profile-statuses">
            ${chips.map((chip) => `<div class="my-publications-profile-status${chip.live ? " live" : ""}" title="${escapeHtml(chip.text)}">${escapeHtml(chip.text)}</div>`).join("")}
          </div>
          ${profileUrl
            ? `<button class="my-publications-profile-avatar" type="button" data-action="open-scholar-profile" title="Open Google Scholar profile" aria-label="Open Google Scholar profile">${avatarMarkup}</button>`
            : `<div class="my-publications-profile-avatar" aria-label="${escapeHtml(profile.name || "Google Scholar profile")}">${avatarMarkup}</div>`}
          ${hasSavedProfile ? `<button class="my-publications-profile-clear" type="button" data-action="clear-scholar-profile" title="Forget saved Google Scholar profile">×</button>` : ""}
        </div>
      `;
    }

    function myPublicationProfileStatusChips(profile = {}) {
      const chips = [];
      const statusText = state.myPublicationSearchStatus || "";
      if (myPublicationSearchStatusIsLive(statusText)) chips.push({id: "search", text: statusText, live: true});
      (state.myPublicationActivities || []).forEach((activity) => {
        if (activity?.text) chips.push({id: activity.id || "", text: activity.text, live: activity.live !== false});
      });
      const profileUrl = scholarProfileExternalUrl(profile);
      if (!chips.length && (profile.name || profile.avatar_url || profileUrl || profile.user_id)) {
        chips.push({id: "profile", text: `Using ${profile.name || "Google Scholar profile"}`, live: false});
      }
      return chips.slice(0, 4);
    }

    function setMyPublicationActivity(id, text, options = {}) {
      if (!id || !text) return;
      const next = (state.myPublicationActivities || []).filter((activity) => activity.id !== id);
      next.push({id, text, live: options.live !== false});
      state.myPublicationActivities = next.slice(-4);
      updateMyPublicationScholarProfileStrip();
    }

    function clearMyPublicationActivity(id) {
      state.myPublicationActivities = (state.myPublicationActivities || []).filter((activity) => activity.id !== id);
      updateMyPublicationScholarProfileStrip();
    }

    function updateMyPublicationScholarProfileStrip() {
      const host = $("myPublicationProfileStripHost");
      if (!host) return;
      host.innerHTML = myPublicationScholarProfileMarkup();
    }

    async function clearMyPublicationScholarProfile() {
      const previous = state.myPublicationScholarProfile;
      state.myPublicationScholarProfile = null;
      state.myPublicationSearchStatus = "Google Scholar profile forgotten.";
      updateMyPublicationScholarProfileStrip();
      try {
        const res = await fetch("/api/my-publications/scholar-profile", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({profile: null})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not forget Google Scholar profile");
      } catch (error) {
        state.myPublicationScholarProfile = previous;
        state.myPublicationSearchStatus = error.message || "Could not forget Google Scholar profile";
      }
      updateMyPublicationSearchStatusText();
    }

    function scholarProfileExternalUrl(profile = {}) {
      const url = String(profile?.url || "").trim();
      if (/^https?:\/\//i.test(url)) return url;
      const userId = String(profile?.user_id || "").trim();
      return userId ? `https://scholar.google.com/citations?user=${encodeURIComponent(userId)}&hl=en` : "";
    }

    async function openMyPublicationScholarProfile() {
      const url = scholarProfileExternalUrl(state.myPublicationScholarProfile || {});
      if (!url) return;
      try {
        await fetch("/api/open-url", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({url})
        });
      } catch (error) {
        state.myPublicationSearchStatus = error.message || "Could not open Google Scholar profile";
        updateMyPublicationSearchStatusText();
      }
    }

    function scholarProfileInitials(name) {
      const parts = String(name || "").trim().split(/\s+/).filter(Boolean);
      if (!parts.length) return "GS";
      if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
      return `${parts[0][0] || ""}${parts[parts.length - 1][0] || ""}`.toUpperCase();
    }

    function myPublicationSortLabel(key) {
      const column = MY_PUBLICATION_COLUMNS.find((item) => item.key === key);
      return column?.label || "Manual";
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
        <th class="${column.sortable ? "sortable" : ""}" ${column.sortable ? `data-publication-sort="${escapeAttr(column.key)}"` : ""}>
          <div class="my-publications-head-cell">
            ${column.sortable ? `
              <button class="my-publications-sort-button" type="button" data-publication-sort="${escapeAttr(column.key)}">
                <span>${escapeHtml(column.label)}</span>
                <span class="my-publications-sort-indicator">${state.myPublicationSort === column.key ? (state.myPublicationSortDir === "desc" ? "↓" : "↑") : ""}</span>
              </button>
            ` : escapeHtml(column.label)}
            <span class="my-publications-col-resizer" data-publication-col="${escapeAttr(column.key)}"></span>
          </div>
        </th>
      `).join("");
    }

    function myPublicationRowMarkup(entry, index) {
      const paper = entry.paper || {};
      const multiSelected = (state.myPublicationSelectedIds || new Set()).size > 1;
      const active = !multiSelected && Number(entry.id) === Number(state.myPublicationSelectionId);
      const selected = (state.myPublicationSelectedIds || new Set()).has(Number(entry.id));
      return `
        <tr class="my-publications-row${selected ? " selected" : ""}${active ? " active" : ""}${entry.review_article ? " review-article" : ""}${entry.head ? " head-excluded" : ""}" data-publication-id="${Number(entry.id)}" draggable="true" aria-selected="${selected || active ? "true" : "false"}">
          <td>${index + 1}</td>
          <td>
            <div class="my-publications-title-cell">
              <button class="star-button${entry.starred ? " active" : ""}" type="button" data-action="toggle-publication-star" title="Highlight">${entry.starred ? "★" : "☆"}</button>
              <span class="my-publications-title-text">${escapeHtml(paper.title || "Untitled paper")}</span>
            </div>
          </td>
          <td class="my-publications-id">${myPublicationIdMarkup(paper)}</td>
          <td>${escapeHtml(paper.publication_date || "")}</td>
          <td>${myPublicationCitationCountMarkup(paper)}</td>
        </tr>
      `;
    }

    function myPublicationFilteredRows(rows) {
      return myPublicationJournalFilteredRows(myPublicationRoleFilteredRows(rows));
    }

    function myPublicationRoleFilteredRows(rows) {
      const key = state.myPublicationRoleFilter || "";
      if (!key) return rows;
      return rows.filter((entry) => myPublicationMatchesRoleFilter(entry, key));
    }

    function myPublicationJournalFilteredRows(rows) {
      const journal = state.myPublicationJournalFilter || "";
      if (!journal) return rows;
      return rows.filter((entry) => String(entry.paper?.journal || "") === journal);
    }

    function visibleMyPublicationRows() {
      return myPublicationFilteredRows(sortedMyPublications());
    }

    function visibleMyPublicationIds() {
      return visibleMyPublicationRows().map((entry) => Number(entry.id));
    }

    function pruneMyPublicationSelection() {
      const visibleIds = new Set(visibleMyPublicationIds());
      state.myPublicationSelectedIds = new Set(
        [...(state.myPublicationSelectedIds || new Set())]
          .map((id) => Number(id))
          .filter((id) => visibleIds.has(id) && myPublicationById(id))
      );
      if (state.myPublicationSelectionId && (!visibleIds.has(Number(state.myPublicationSelectionId)) || !myPublicationById(state.myPublicationSelectionId))) {
        state.myPublicationSelectionId = Number([...state.myPublicationSelectedIds][0] || visibleMyPublicationRows()[0]?.id || 0);
      }
      if (state.myPublicationSelectionId && !state.myPublicationSelectedIds.size) {
        state.myPublicationSelectedIds = new Set([Number(state.myPublicationSelectionId)]);
      }
      if (state.myPublicationRangeAnchorId && !visibleIds.has(Number(state.myPublicationRangeAnchorId))) {
        state.myPublicationRangeAnchorId = Number(state.myPublicationSelectionId || [...state.myPublicationSelectedIds][0] || 0);
      }
    }

    function selectedMyPublicationIdsForAction() {
      pruneMyPublicationSelection();
      const selected = [...(state.myPublicationSelectedIds || new Set())]
        .map((id) => Number(id))
        .filter((id) => myPublicationById(id));
      if (selected.length) return selected;
      return state.myPublicationSelectionId && myPublicationById(state.myPublicationSelectionId)
        ? [Number(state.myPublicationSelectionId)]
        : [];
    }

    function setMyPublicationSingleSelection(id) {
      const publicationId = Number(id || 0);
      if (!myPublicationById(publicationId)) return;
      state.myPublicationSelectionId = publicationId;
      state.myPublicationSelectedIds = new Set([publicationId]);
      state.myPublicationRangeAnchorId = publicationId;
    }

    function setMyPublicationRangeSelection(id) {
      const rows = visibleMyPublicationRows();
      const targetId = Number(id || 0);
      const targetIndex = rows.findIndex((entry) => Number(entry.id) === targetId);
      if (targetIndex < 0) {
        setMyPublicationSingleSelection(targetId);
        return;
      }
      const anchorId = Number(state.myPublicationRangeAnchorId || state.myPublicationSelectionId || targetId);
      let anchorIndex = rows.findIndex((entry) => Number(entry.id) === anchorId);
      if (anchorIndex < 0) anchorIndex = targetIndex;
      const start = Math.min(anchorIndex, targetIndex);
      const end = Math.max(anchorIndex, targetIndex);
      state.myPublicationSelectedIds = new Set(rows.slice(start, end + 1).map((entry) => Number(entry.id)));
      state.myPublicationSelectionId = targetId;
      state.myPublicationRangeAnchorId = Number(rows[anchorIndex]?.id || targetId);
    }

    function toggleMyPublicationSelection(id) {
      const publicationId = Number(id || 0);
      if (!myPublicationById(publicationId)) return;
      const next = new Set(state.myPublicationSelectedIds || []);
      if (next.has(publicationId) && next.size > 1) {
        next.delete(publicationId);
        if (Number(state.myPublicationSelectionId) === publicationId) {
          state.myPublicationSelectionId = Number([...next][0] || 0);
        }
      } else {
        next.add(publicationId);
        state.myPublicationSelectionId = publicationId;
      }
      state.myPublicationSelectedIds = next;
      state.myPublicationRangeAnchorId = publicationId;
    }

    function myPublicationMatchesRoleFilter(entry, key) {
      if (key === "listed-first") return myPublicationIsListedFirstAuthor(entry);
      if (key === "solo-first") return myPublicationIsListedFirstAuthor(entry) && !entry.first_author;
      if (key === "co-first") return Boolean(entry.first_author);
      if (key === "solo-and-co-first") return (myPublicationIsListedFirstAuthor(entry) && !entry.first_author) || Boolean(entry.first_author);
      if (key === "corresponding") return Boolean(entry.corresponding_author);
      return true;
    }

    function myPublicationRoleFilterLabel(key) {
      return {
        "listed-first": "First as listed",
        "solo-first": "Solo first",
        "co-first": "Co-first",
        "solo-and-co-first": "Solo first or Co-first",
        "corresponding": "Corresponding"
      }[key] || "";
    }

    function myPublicationFilterLabel() {
      const labels = [];
      const roleLabel = myPublicationRoleFilterLabel(state.myPublicationRoleFilter);
      if (roleLabel) labels.push(roleLabel);
      if (state.myPublicationJournalFilter) labels.push(`Journal: ${state.myPublicationJournalFilter}`);
      return labels.join(" · ");
    }

    function myPublicationStatsMarkup(rows) {
      const total = rows.length;
      const doiRows = rows.filter((entry) => String(entry.paper?.doi || "").trim());
      const withDoi = doiRows.length;
      const citationCounts = rows
        .map((entry) => myPublicationMaxCitationCount(entry.paper))
        .filter((value) => Number.isFinite(value));
      const totalCites = citationCounts.reduce((sum, value) => sum + value, 0);
      const doiCitationTotal = doiRows.reduce((sum, entry) => {
        const value = myPublicationMaxCitationCount(entry.paper);
        return sum + (Number.isFinite(value) ? Number(value) : 0);
      }, 0);
      const hIndex = myPublicationHIndex(citationCounts);
      const i10Index = citationCounts.filter((value) => value >= 10).length;
      const journalCounts = countMyPublicationJournals(rows);
      const journals = new Set(journalCounts.map((entry) => entry.name));
      const listedFirstRows = rows.filter((entry) => myPublicationIsListedFirstAuthor(entry));
      const soleFirstRows = listedFirstRows.filter((entry) => !entry.first_author);
      const firstAuthorRows = rows.filter((entry) => entry.first_author);
      const soloAndCoFirstRows = rows.filter((entry) => (myPublicationIsListedFirstAuthor(entry) && !entry.first_author) || entry.first_author);
      const correspondingAuthorRows = rows.filter((entry) => entry.corresponding_author);
      return `
        <div class="my-publications-stats" style="--my-publications-stats-height:${Number(state.myPublicationStatsHeight || 126)}px">
          <button class="my-publications-stats-resizer" type="button" data-action="resize-publication-stats" title="Resize statistics panel"></button>
          <div class="my-publications-stat">
            <strong><button class="my-publications-stat-total" type="button" data-action="publication-clear-filters">${total} Publications</button></strong>
            <span>${withDoi} with DOI</span>
            <div class="my-publications-stat-list">
              <div class="my-publications-stat-row"><b>H-index</b><em>${hIndex}</em></div>
              <div class="my-publications-stat-row"><b>i10-index</b><em>${i10Index}</em></div>
            </div>
          </div>
          <div class="my-publications-stat">
            <strong>${journals.size || 0} Journals</strong>
            <span>Journal counts</span>
            <div class="my-publications-stat-list">${myPublicationJournalStatsRows(journalCounts)}</div>
          </div>
          <div class="my-publications-stat">
            <strong>${totalCites || "--"} Cites</strong>
            <span>${citationCounts.length} papers with cites</span>
            <div class="my-publications-stat-list">
              <div class="my-publications-stat-row"><b>Rule</b><em>Max per paper</em></div>
              <div class="my-publications-stat-row sources-row"><b>Sources</b><em><span class="my-publications-source-list"><span class="my-publications-source-list-line">OpenAlex / Semantic</span><span class="my-publications-source-list-line">Crossref / ADS / PubMed</span></span></em></div>
              <div class="my-publications-stat-row"><b>Average</b><em>${withDoi ? Math.round(doiCitationTotal / withDoi) : "--"}</em></div>
            </div>
          </div>
          <div class="my-publications-stat">
            <strong>${listedFirstRows.length} (${soleFirstRows.length}) / ${firstAuthorRows.length} / ${soloAndCoFirstRows.length} / ${correspondingAuthorRows.length} Major Papers</strong>
            <span>First listed (solo) / co-1st / union / corr.</span>
            <div class="my-publications-stat-list">
              ${myPublicationFirstSoloRoleFilterRow(listedFirstRows.length, soleFirstRows.length)}
              ${myPublicationRoleFilterRow("Co-first", "co-first", firstAuthorRows.length)}
              ${myPublicationRoleFilterRow("Solo first and Co-first", "solo-and-co-first", soloAndCoFirstRows.length)}
              ${myPublicationRoleFilterRow("Corresponding", "corresponding", correspondingAuthorRows.length)}
            </div>
          </div>
        </div>
      `;
    }

    function myPublicationStatsRows(items) {
      if (!items.length) return `<div class="my-publications-stat-row"><b>None</b><em>0</em></div>`;
      return items
        .map((entry) => `<div class="my-publications-stat-row"><b>${escapeHtml(entry.name)}</b><em>${escapeHtml(entry.count)}</em></div>`)
        .join("");
    }

    function myPublicationJournalStatsRows(items) {
      if (!items.length) return `<div class="my-publications-stat-row"><b>None</b><em>0</em></div>`;
      return items
        .map((entry) => {
          const active = state.myPublicationJournalFilter === entry.name;
          return `<div class="my-publications-stat-row"><b><button class="my-publications-stat-filter${active ? " active" : ""}" type="button" data-action="publication-journal-filter" data-journal-filter="${escapeAttr(entry.name)}" title="${escapeAttr(entry.name)}">${escapeHtml(entry.name)}</button></b><em>${escapeHtml(entry.count)}</em></div>`;
        })
        .join("");
    }

    function myPublicationRoleStatsRows(label, rows) {
      const items = countMyPublicationJournals(rows);
      if (!items.length) return `<div class="my-publications-stat-row"><b>${escapeHtml(label)}</b><em>--</em></div>`;
      return items
        .map((entry) => `<div class="my-publications-stat-row"><b>${escapeHtml(label)} · ${escapeHtml(entry.name)}</b><em>${escapeHtml(entry.count)}</em></div>`)
        .join("");
    }

    function myPublicationRoleFilterRow(label, key, count) {
      const active = state.myPublicationRoleFilter === key;
      return `<div class="my-publications-stat-row"><b><button class="my-publications-stat-filter${active ? " active" : ""}" type="button" data-action="publication-role-filter" data-role-filter="${escapeAttr(key)}">${escapeHtml(label)}</button></b><em>${escapeHtml(count)}</em></div>`;
    }

    function myPublicationFirstSoloRoleFilterRow(firstCount, soloCount) {
      const firstActive = state.myPublicationRoleFilter === "listed-first";
      const soloActive = state.myPublicationRoleFilter === "solo-first";
      return `
        <div class="my-publications-stat-row first-solo-row">
          <b>
            <button class="my-publications-stat-filter${firstActive ? " active" : ""}" type="button" data-action="publication-role-filter" data-role-filter="listed-first">First as listed</button>
            <span class="solo-inline">(<button class="my-publications-stat-filter${soloActive ? " active" : ""}" type="button" data-action="publication-role-filter" data-role-filter="solo-first">Solo first</button>)</span>
          </b>
          <em>${escapeHtml(firstCount)} (${escapeHtml(soloCount)})</em>
        </div>
      `;
    }

    function myPublicationHIndex(counts) {
      const sorted = counts
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value))
        .sort((a, b) => b - a);
      let index = 0;
      while (index < sorted.length && sorted[index] >= index + 1) index += 1;
      return index;
    }

    function countMyPublicationJournals(rows) {
      const counts = new Map();
      rows.forEach((entry) => {
        const journal = entry.paper?.journal || "";
        if (!journal) return;
        counts.set(journal, (counts.get(journal) || 0) + 1);
      });
      return [...counts.entries()]
        .map(([name, count]) => ({name, count}))
        .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    }

    function myPublicationAuthorList(entry) {
      const paper = entry?.paper || {};
      if (Array.isArray(paper.full_authors) && paper.full_authors.length) return paper.full_authors;
      if (Array.isArray(paper.authors) && paper.authors.length) return paper.authors;
      return [];
    }

    function myPublicationIsListedFirstAuthor(entry) {
      const name = currentMyPublicationName();
      if (!name) return false;
      const authors = myPublicationAuthorList(entry);
      return Boolean(authors.length && authorMatchesMyName(authors[0]));
    }

    function myPublicationCitationCountMarkup(paper) {
      const value = myPublicationMaxCitationCount(paper);
      if (value === null || value === undefined || value === "") return "";
      return escapeHtml(value);
    }

    function myPublicationMaxCitationCount(paper) {
      const metrics = paper?.citation_metrics || {};
      if (Number.isFinite(Number(metrics.count))) return Number(metrics.count);
      const sources = metrics.sources || {};
      const values = [
        sources.openalex?.count,
        sources.semantic_scholar?.count,
        sources.crossref?.count
      ]
        .map((value) => Number(value))
        .filter((value) => Number.isFinite(value));
      return values.length ? Math.max(...values) : null;
    }

    function myPublicationIdMarkup(paper) {
      const ref = paper?.nature_reference || {};
      if (paper?.preprint_id && String(paper?.journal || "").toLowerCase() === "arxiv") {
        return `<em>${escapeHtml(paper.journal || "arXiv")}</em>:${escapeHtml(paper.preprint_id)}`;
      }
      const journal = ref.journal || paper?.journal || "";
      const volume = ref.volume || "";
      const pages = ref.pages || "";
      const parts = [];
      if (journal) parts.push(`<em class="journal-name">${escapeHtml(journal)}</em>`);
      if (volume) parts.push(`<strong>${escapeHtml(volume)}</strong>${pages ? `, ${escapeHtml(pages)}` : ""}`);
      else if (pages) parts.push(escapeHtml(pages));
      if (!parts.length && paper?.doi) parts.push(`doi:${escapeHtml(paper.doi)}`);
      return parts.join(" ") || escapeHtml(paper?.citation_label || "");
    }

    function myPublicationSearchResultsMarkup() {
      const results = state.myPublicationSearchResults || [];
      if (!results.length) {
        const status = state.myPublicationSearchStatus || "";
        if (/importing|matching|searching|resolving|loading/i.test(status)) {
          return `<div class="publication-search-result placeholder">Working on the lookup. Results will appear here when the profile or title matches come back.</div>`;
        }
        if (/no |0 |failed|blocked|error/i.test(status)) {
          return `<div class="publication-search-result placeholder">${escapeHtml(status)}</div>`;
        }
        return "";
      }
      return myPublicationSearchResultViewItems(results).map(({candidate, index}) => {
        if (candidate.candidate_type === "scholar-profile") {
          const meta = [
            candidate.affiliation || "",
            candidate.email || "",
            candidate.cited_by || "",
            Array.isArray(candidate.interests) ? candidate.interests.slice(0, 3).join(", ") : "",
          ].filter(Boolean).join(" · ");
          return `
            <div class="publication-search-result" data-search-index="${index}">
              <div>
                <strong>${escapeHtml(candidate.name || "Unnamed Scholar profile")}</strong>
                <span>${escapeHtml(meta || candidate.url || "")}</span>
              </div>
              <div class="publication-search-actions">
                <button class="smallbtn" type="button" data-action="use-scholar-profile">Use Profile</button>
              </div>
            </div>
          `;
        }
        const paper = candidate.paper || {};
        const added = myPublicationCandidateAlreadyAdded(candidate);
        const matchLabel = candidate.match_status === "doi"
          ? "DOI match"
          : (candidate.match_status === "arxiv" ? "arXiv match" : (candidate.match_status === "resolving" ? "Resolving identifier" : (candidate.match_status === "scholar" ? "Scholar-only" : "")));
        const meta = [matchLabel, paper.journal, paper.publication_date, paper.doi].filter(Boolean).join(" · ");
        const resolving = candidate.match_status === "resolving";
        const canRetry = candidate.match_status === "scholar";
        return `
          <div class="publication-search-result${added ? " added" : ""}${candidate.match_status === "resolving" ? " resolving" : ""}" data-search-index="${index}">
            <div>
              <strong>${escapeHtml(paper.title || "Untitled paper")}</strong>
              <span>${escapeHtml(meta)}</span>
            </div>
            <div class="publication-search-actions">
              ${canRetry ? `<button class="smallbtn" type="button" data-action="retry-scholar-doi">Retry ID</button>` : ""}
              <button class="smallbtn" type="button" data-action="add-publication-result" ${added || resolving ? "disabled" : ""}>${added ? "Added" : "Add"}</button>
            </div>
          </div>
        `;
      }).join("");
    }

    function myPublicationSearchResultViewItems(results) {
      return (results || [])
        .map((candidate, index) => ({candidate, index, added: myPublicationCandidateAlreadyAdded(candidate)}))
        .sort((a, b) => {
          const aProfile = a.candidate?.candidate_type === "scholar-profile";
          const bProfile = b.candidate?.candidate_type === "scholar-profile";
          if (aProfile !== bProfile) return aProfile ? -1 : 1;
          return Number(a.added) - Number(b.added) || a.index - b.index;
        });
    }

    function myPublicationCandidateAlreadyAdded(candidate) {
      const paper = candidate?.paper || candidate || {};
      const candidateDoi = String(paper.doi || "").trim().toLowerCase();
      const candidatePaperId = String(paper.paper_id || "").trim();
      const candidateTitle = String(paper.title || "").trim().toLowerCase();
      const candidateYear = String(paper.publication_date || "").slice(0, 4);
      return state.myPublications.some((entry) => {
        const existing = entry.paper || {};
        if (candidatePaperId && String(existing.paper_id || "") === candidatePaperId) return true;
        if (candidateDoi && String(existing.doi || "").trim().toLowerCase() === candidateDoi) return true;
        return Boolean(candidateTitle)
          && String(existing.title || "").trim().toLowerCase() === candidateTitle
          && String(existing.publication_date || "").slice(0, 4) === candidateYear;
      });
    }

    function sortMyPublicationSearchResultsByAdded() {
      state.myPublicationSearchResults = (state.myPublicationSearchResults || [])
        .map((candidate, index) => ({candidate, index, added: myPublicationCandidateAlreadyAdded(candidate)}))
        .sort((a, b) => Number(a.added) - Number(b.added) || a.index - b.index)
        .map((item) => item.candidate);
    }

    function resizeLibraryViewport() {
      if (state.mode !== "library") return;
      const root = $("papers");
      const reportColumn = root?.closest(".report-column");
      if (!root || !reportColumn) return;
      const columnRect = reportColumn.getBoundingClientRect();
      const rootRect = root.getBoundingClientRect();
      const viewportBottom = window.innerHeight;
      const availableHeight = Math.max(280, Math.floor(viewportBottom - rootRect.top));
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

    function updateLibrarySearchActiveRow() {
      const root = $("librarySearchResults");
      if (!root) return;
      const selectedKey = libraryEntryKey(state.librarySelection);
      root.querySelectorAll(".library-row").forEach((row) => {
        const rowKey = libraryEntryKey({type: row.dataset.libraryType, id: Number(row.dataset.libraryId || 0)});
        row.classList.toggle("active", rowKey === selectedKey);
      });
    }

    function selectLibrarySearchEntry(parentFolderId, type, id) {
      const entry = {type, id: Number(id)};
      setLibraryColumnSelection(parentFolderId, entry);
      renderLibraryDetail();
      updateLibrarySearchActiveRow();
      revealLibrarySearchSelection();
      refreshLibraryQuickLookForSelection();
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

    function startLibraryDetailResize(event) {
      const shell = $("libraryShell");
      const pane = shell?.querySelector(".library-pane");
      const divider = $("libraryDetailDivider");
      if (!shell || !pane || !divider) return;
      event.preventDefault();
      event.stopPropagation();
      const startX = event.clientX;
      const startWidth = pane.getBoundingClientRect().width;
      divider.classList.add("resizing");
      document.body.classList.add("resizing");
      const move = (moveEvent) => {
        const shellWidth = shell.getBoundingClientRect().width;
        const maxWidth = Math.max(320, Math.min(720, Math.round(shellWidth * 0.56)));
        const width = Math.max(280, Math.min(maxWidth, Math.round(startWidth - (moveEvent.clientX - startX))));
        state.libraryDetailWidth = width;
        shell.style.setProperty("--library-detail-width", `${width}px`);
      };
      const stop = () => {
        divider.classList.remove("resizing");
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
      const header = results.length > visibleResults.length
        ? `Search Results · Showing ${visibleResults.length} of ${results.length}`
        : `Search Results${results.length ? ` · ${results.length}` : ""}`;
      root.innerHTML = `
        <div class="library-pane-header">${escapeHtml(header)}</div>
        <div class="library-search-results-body">
          ${rows || `<div class="empty">No Library matches for "${escapeHtml(state.query.trim())}".</div>`}
        </div>
      `;
    }

    function librarySearchResultRowMarkup(type, entry, parentFolderId, path) {
      const id = Number(entry.id);
      const selected = libraryEntryKey(state.librarySelection) === libraryEntryKey({type, id});
      const paper = entry.paper || {};
      const name = type === "folder" ? entry.name : (entry.display_name || libraryPaperDisplayName(paper));
      const iconClass = libraryEntryIconClass(type, entry);
      const meta = type === "folder" ? "Folder" : (paper.journal || "Paper");
      const nativeDragAttrs = libraryNativeDragHandleAttrs(type, entry, name);
      return `
        <button class="library-row${selected ? " active" : ""}"
          type="button"
          draggable="false"
          data-library-type="${type}"
          data-library-id="${id}"
          data-library-parent-folder="${parentFolderId}"
          ${type === "folder" ? `data-library-drop-folder="${id}"` : ""}
          aria-selected="${selected ? "true" : "false"}">
          <span class="library-entry-icon ${iconClass}${nativeDragAttrs ? " native-file-drag-handle" : ""}" ${nativeDragAttrs} aria-hidden="true"></span>
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
      const meta = type === "folder" ? "›" : "";
      const iconClass = libraryEntryIconClass(type, entry);
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
      const nativeDragAttrs = libraryNativeDragHandleAttrs(type, entry, name);
      return `
        <${rowTag} class="library-row${rangeSelected ? " range-selected" : ""}${selected && !rangeSelected ? " active" : ""}${isPathParent ? " path-parent" : ""}${isSpecialFolder ? " special-folder" : ""}"
          ${rowAttrs}
          data-library-type="${type}"
          data-library-id="${id}"
          data-library-parent-folder="${parentFolderId}"
          ${type === "folder" ? `data-library-drop-folder="${id}"` : ""}
          aria-selected="${selected || rangeSelected ? "true" : "false"}">
          <span class="library-entry-icon ${iconClass}${nativeDragAttrs ? " native-file-drag-handle" : ""}" ${nativeDragAttrs} aria-hidden="true"></span>
          <span class="library-name" ${folderColor ? `style="color:${escapeAttr(folderColor)}"` : ""}>${nameMarkup}</span>
          <span class="library-meta">${renaming ? "" : escapeHtml(String(meta || ""))}</span>
        </${rowTag}>
      `;
    }

    function libraryNativeDragHandleAttrs(type, entry, fallbackName) {
      if (type !== "item") return "";
      const path = libraryNativeItemPath(entry);
      if (!path) return "";
      const fileName = sanitizeDragFileName(entry?.paper?.original_filename || fileNameFromPath(path) || fallbackName || "file");
      return `data-native-file-drag-handle draggable="false" data-native-drag-path="${escapeAttr(path)}" data-native-drag-name="${escapeAttr(fileName)}" title="Drag file to Finder"`;
    }

    function libraryEntryIconClass(type, entry) {
      if (type === "folder") return (entry?.is_unsorted || entry?.is_recycle) ? "trash" : "folder";
      return entry?.paper?.storage_mode === "link" ? "linked-document" : "document";
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

    function libraryPaperIsPdfLike(paper) {
      const kind = String(paper?.import_kind || "").toLowerCase();
      const extension = String(paper?.file_extension || "").toLowerCase().replace(/^\./, "");
      const importedFile = Boolean(paper?.import_batch_id || (kind && kind !== "pdf"));
      const hasIdentifier = Boolean(paper?.doi || paper?.preprint_id || String(paper?.paper_id || "").startsWith("arxiv_"));
      const journalMonitorRecord = !importedFile && Boolean(paper?.journal || paper?.publication_date || paper?.url || paper?.source);
      if (paper?.merged_pdf_path || paper?.main_pdf_path || kind === "pdf") return true;
      if (kind && kind !== "pdf") return false;
      if (importedFile && extension && extension !== "pdf") return false;
      return Boolean(hasIdentifier || journalMonitorRecord);
    }

    function fileSizeLabel(bytes) {
      const value = Number(bytes || 0);
      if (!Number.isFinite(value) || value <= 0) return "";
      const units = ["B", "KB", "MB", "GB", "TB"];
      let size = value;
      let index = 0;
      while (size >= 1024 && index < units.length - 1) {
        size /= 1024;
        index += 1;
      }
      return index === 0 ? `${value} ${units[index]}` : `${size.toFixed(size >= 10 ? 1 : 2)} ${units[index]}`;
    }

    function importedFileFormatLabel(paper) {
      const extension = String(paper?.file_extension || "").trim();
      const kind = String(paper?.import_kind || "").trim();
      const mime = String(paper?.file_mime_type || "").trim();
      return [extension, kind, mime].filter(Boolean).join(" · ") || "file";
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
      return `
        <section class="library-detail-abstract">
          <strong>Abstract</strong>
          <p>${escapeHtml(abstract || "No abstract available.")}</p>
        </section>
      `;
    }

    function publicationAuthorsSectionMarkup(publication, authors, paper = null) {
      return `
        <section class="library-detail-authors">
          <strong>Authors</strong>
          <div>${publicationAuthorsMarkup(publication, authors, paper)}</div>
        </section>
      `;
    }

    function libraryDetailDoiMarkup(paper) {
      const value = paper?.doi || paper?.preprint_id || "";
      return `
        <div class="library-detail-doi">
          <input id="libraryDetailDoiInput" type="text" value="${escapeAttr(value)}" placeholder="Enter DOI or arXiv ID">
          <button class="action" type="button" data-action="refresh-library-metadata" title="Refresh metadata from DOI or arXiv ID">Refresh</button>
        </div>
      `;
    }

    function libraryDetailFilesMarkup(paper) {
      const lines = [];
      if (paper?.merged_pdf_path) lines.push(`<span class="library-file-line">PDF: ${escapeHtml(paper.merged_pdf_path)}</span>`);
      else if (paper?.native_file_path || paper?.source_path) lines.push(`<span class="library-file-line">File: ${escapeHtml(paper.native_file_path || paper.source_path)}</span>`);
      else lines.push(`<span class="library-file-line">${libraryPaperIsPdfLike(paper) ? "PDF" : "File"}: No local file</span>`);
      if (paper?.pdf_url) lines.push(`<span class="library-file-line">Source PDF: ${escapeHtml(paper.pdf_url)}</span>`);
      return lines.join("");
    }

    function libraryDetailMetadataMarkup(paper, authors, publication = null, options = {}) {
      const preprintId = paper.preprint_id || "";
      const preprintUrl = preprintId ? `https://arxiv.org/abs/${encodeURI(preprintId.replace(/^arxiv:/i, "").trim())}` : "";
      const authorMarkup = publication ? publicationAuthorsMarkup(publication, authors, paper) : authorsMarkup(authors, paper);
      return `
        <dl>
          <dt>Title</dt><dd class="library-detail-title">${escapeHtml(paper.title || "Untitled paper")}</dd>
          ${options.hideAuthors ? "" : `<dt>Authors</dt><dd>${authorMarkup}</dd>`}
          <dt>Journal</dt><dd>${escapeHtml(paper.journal || "")}</dd>
          <dt>Date</dt><dd>${escapeHtml(paper.publication_date || "")}</dd>
          <dt>Identifier</dt><dd>${libraryDetailDoiMarkup(paper)}</dd>
          ${preprintId && paper.doi ? `<dt>Preprint</dt><dd><span>arXiv:${escapeHtml(preprintId)}</span> <button class="action" type="button" data-action="open-preprint-page" data-preprint-url="${escapeAttr(preprintUrl)}">Open</button></dd>` : ""}
          <dt>Citation</dt><dd>${escapeHtml(paper.citation_label || "")}</dd>
          <dt>Fields</dt><dd>${paperFieldValues(paper).map((field) => escapeHtml(FIELD_LABELS[field] || field)).join(", ")}</dd>
          ${options.hideFiles ? "" : `<dt>Files</dt><dd>${libraryDetailFilesMarkup(paper)}</dd>`}
        </dl>
      `;
    }

    function libraryNonPdfDetailMarkup(paper) {
      const path = paperNativePath(paper);
      const size = fileSizeLabel(paper?.file_size_bytes);
      return `
        <h3>${escapeHtml(paper?.title || paper?.original_filename || "Imported file")}</h3>
        <div class="actions">
          ${path ? `<button class="action primary" data-action="open-native-paper-file">Open File</button>` : ""}
        </div>
        <div class="library-detail-status" id="libraryDetailStatus"></div>
        <dl>
          <dt>Path</dt><dd>${escapeHtml(path || "No local file path")}</dd>
          <dt>Format</dt><dd>${escapeHtml(importedFileFormatLabel(paper))}</dd>
          <dt>Size</dt><dd>${escapeHtml(size || "--")}</dd>
        </dl>
      `;
    }

    function manualPublicationMetadataMarkup(publication, paper, authors) {
      if (!publication?.manual_metadata_editable) return "";
      const ref = paper?.nature_reference || {};
      const manual = paper?.manual_metadata || {};
      const volume = manual.volume || ref.volume || "";
      const issue = manual.issue || "";
      const pages = manual.pages || ref.pages || "";
      const authorText = Array.isArray(authors) ? authors.join("; ") : "";
      return `
        <section class="publication-manual-metadata">
          <strong>Manual Metadata</strong>
          <label>Title<input type="text" data-manual-metadata-field="title" value="${escapeAttr(paper.title || "")}"></label>
          <label>Authors<textarea data-manual-metadata-field="authors" rows="2">${escapeHtml(authorText)}</textarea></label>
          <div class="publication-manual-grid">
            <label>Journal<input type="text" data-manual-metadata-field="journal" value="${escapeAttr(paper.journal || "")}"></label>
            <label>Date<input type="text" data-manual-metadata-field="publication_date" value="${escapeAttr(paper.publication_date || "")}"></label>
            <label>Volume<input type="text" data-manual-metadata-field="volume" value="${escapeAttr(volume)}"></label>
            <label>Issue<input type="text" data-manual-metadata-field="issue" value="${escapeAttr(issue)}"></label>
            <label>Pages<input type="text" data-manual-metadata-field="pages" value="${escapeAttr(pages)}"></label>
          </div>
          <div class="publication-manual-actions">
            <button class="action" type="button" data-action="save-manual-publication-metadata">Save Metadata</button>
          </div>
        </section>
      `;
    }

    function hydrateLibraryDetailFigureIfNeeded(paper) {
      if (!paper?.paper_id || paper.image_url || state.figureFailures.has(paper.paper_id)) return;
      queuePaperFigureHydration(paper.paper_id);
    }

    function authorsMarkup(authors, paper = null) {
      if (!Array.isArray(authors) || !authors.length) return "Authors unavailable";
      return authors.map((author, index) => {
        const escaped = escapeHtml(author);
        const symbols = publicationAuthorRoleSymbols(paper, index, author);
        const suffix = symbols.text ? `<sup class="author-role-symbols" title="${escapeAttr(symbols.title)}">${escapeHtml(symbols.text)}</sup>` : "";
        const label = authorMatchesMyName(author) ? `<strong>${escaped}</strong>${suffix}` : `${escaped}${suffix}`;
        const affiliations = publicationAuthorAffiliations(paper, index, author);
        if (!affiliations.length) return label;
        return `
          <span class="author-affiliation-hover" tabindex="0" data-author-affiliations="${escapeAttr(JSON.stringify(affiliations))}">
            ${label}
          </span>
        `;
      }).join(", ");
    }

    function publicationAuthorRoleSymbols(paper, index, authorName) {
      const entry = publicationAuthorPubmedEntry(paper, index, authorName);
      const roles = entry?.roles || {};
      const parts = [];
      const labels = [];
      if (roles.co_first_author) {
        parts.push("*");
        labels.push("Equal contribution");
      }
      if (roles.corresponding_author) {
        parts.push("†");
        labels.push("Corresponding author");
      }
      return {text: parts.join(""), title: labels.join("; ")};
    }

    function publicationAuthorsMarkup(publication, authors, paper = null) {
      if (!Array.isArray(authors) || !authors.length) return "Authors unavailable";
      const marks = publication.author_marks || {};
      return `<span class="publication-author-list">${authors.map((author, index) => {
        const mark = marks[String(index)] || {};
        const badges = [
          mark.first_author ? "1st" : "",
          mark.co_first_author ? "co-1st" : "",
          mark.corresponding_author ? "corr." : ""
        ].filter(Boolean);
        const mine = authorMatchesMyName(author);
        const affiliations = publicationAuthorAffiliations(paper, index, author);
        return `<button class="publication-author-pill${mine ? " mine" : ""}${badges.length ? " marked" : ""}" type="button" data-action="edit-publication-author" data-author-index="${index}" data-author-name="${escapeAttr(author)}" data-author-affiliations="${escapeAttr(JSON.stringify(affiliations))}">${escapeHtml(author)}${badges.map((badge) => `<span class="publication-author-badge">${escapeHtml(badge)}</span>`).join("")}</button>`;
      }).join("")}</span>`;
    }

    function publicationAuthorAffiliations(paper, index, authorName) {
      const entry = publicationAuthorPubmedEntry(paper, index, authorName);
      return Array.isArray(entry?.affiliations) ? entry.affiliations.filter(Boolean) : [];
    }

    function publicationAuthorPubmedEntry(paper, index, authorName) {
      const values = Array.isArray(paper?.pubmed?.author_affiliations) ? paper.pubmed.author_affiliations : [];
      const byIndex = values[Number(index) || 0];
      if (byIndex) return byIndex;
      const target = String(authorName || "").trim().toLowerCase();
      return values.find((item) => String(item?.name || "").trim().toLowerCase() === target) || null;
    }

    function authorMatchesMyName(author) {
      const targets = authorNameSignatures(currentMyPublicationName());
      const candidates = authorNameSignatures(author || "");
      return targets.some((target) => candidates.some((candidate) => authorSignaturesMatch(target, candidate)));
    }

    function currentMyPublicationName() {
      const input = $("myPublicationName");
      return (input?.value || state.myPublicationName || "").split(/[;；]/)[0].trim();
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
      if (parts.length) {
        addVariant(parts[parts.length - 1], parts.slice(0, -1));
        if (parts.length > 1) addVariant(parts[0], parts.slice(1));
      }
      addChineseAuthorSignatures(value, addVariant);
      return variants;
    }

    const CHINESE_PINYIN = {
      "丁": "ding", "中": "zhong", "二": "er", "井": "jing", "亮": "liang", "仁": "ren",
      "令": "ling", "作": "zuo", "侯": "hou", "儀": "yi", "元": "yuan", "光": "guang",
      "关": "guan", "军": "jun", "凡": "fan", "刘": "liu", "刚": "gang", "剑": "jian",
      "卉": "hui", "单": "shan", "吴": "wu", "哲": "zhe", "善": "shan", "嘉": "jia",
      "婧": "jing", "嫄": "yuan", "子": "zi", "孔": "kong", "孙": "sun", "宁": "ning",
      "宇": "yu", "尚": "shang", "崔": "cui", "平": "ping", "年": "nian", "广": "guang",
      "広": "guang", "建": "jian", "张": "zhang", "彭": "peng", "微": "wei", "户": "hu",
      "承": "cheng", "明": "ming", "朱": "zhu", "权": "quan", "李": "li", "村": "cun",
      "杨": "yang", "桂": "gui", "森": "sen", "正": "zheng", "治": "zhi", "洪": "hong",
      "海": "hai", "涛": "tao", "温": "wen", "焘": "tao", "猛": "meng", "王": "wang",
      "用": "yong", "益": "yi", "程": "cheng", "罡": "gang", "者": "zhe", "胡": "hu",
      "良": "liang", "芃": "peng", "苏": "su", "著": "zhu", "软": "ruan", "邴": "bing",
      "郭": "guo", "野": "ye", "金": "jin", "钟": "zhong", "钧": "jun", "铂": "bo",
      "铭": "ming", "锡": "xi", "飞": "fei", "马": "ma", "鹏": "peng", "黄": "huang",
      "洁": "jie", "鑫": "xin", "殷": "yin", "沈": "shen", "约": "yue", "拉": "la",
      "娜": "na"
    };
    const CHINESE_COMPOUND_SURNAMES = {"欧阳": "ouyang", "司马": "sima", "诸葛": "zhuge", "上官": "shangguan"};
    const CHINESE_NAME_STOPWORDS = new Set(["作者", "著者", "用户", "微软用户"]);

    function addChineseAuthorSignatures(value, addVariant) {
      const matches = String(value || "").match(/[\u4e00-\u9fff]{2,5}/g) || [];
      matches.forEach((rawName) => {
        if (CHINESE_NAME_STOPWORDS.has(rawName)) return;
        const name = rawName.replace(/著$/u, "");
        if (name.length < 2 || CHINESE_NAME_STOPWORDS.has(name)) return;
        let family = "";
        let givenChars = "";
        for (const [compound, pinyin] of Object.entries(CHINESE_COMPOUND_SURNAMES)) {
          if (name.startsWith(compound) && name.length > compound.length) {
            family = pinyin;
            givenChars = name.slice(compound.length);
            break;
          }
        }
        if (!family) {
          family = CHINESE_PINYIN[name[0]] || "";
          givenChars = name.slice(1);
        }
        const given = Array.from(givenChars).map((char) => CHINESE_PINYIN[char] || "");
        if (family && given.length && given.every(Boolean)) addVariant(family, given);
      });
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
            <dt>Contains</dt><dd>${folders} folders · ${items} items</dd>
          </dl>
          <div class="library-detail-status" id="libraryDetailStatus"></div>
        `;
        return;
      }
      const item = libraryItemById(selection.id);
      const paper = item?.paper || {};
      if (paper.paper_id && !libraryPaperIsPdfLike(paper)) {
        root.innerHTML = libraryNonPdfDetailMarkup(paper);
        root.querySelector('[data-action="open-native-paper-file"]')?.addEventListener("click", () => openNativePaperFile(paper, {
          missingMessage: "No local file path is available for this item."
        }));
        if (!paper.full_detail) loadLibraryItemPaperDetail(item);
        return;
      }
      if (paper.paper_id && !paper.full_detail) {
        root.innerHTML = `
          <h3>${escapeHtml(paper.title || "Untitled paper")}</h3>
          <div class="library-detail-status">Loading details...</div>
          ${libraryDetailMetadataMarkup(paper, [])}
        `;
        loadLibraryItemPaperDetail(item);
        return;
      }
      const authors = Array.isArray(paper.full_authors) && paper.full_authors.length
        ? paper.full_authors
        : (Array.isArray(paper.authors) ? paper.authors : []);
      const isPdfLike = libraryPaperIsPdfLike(paper);
      if (!isPdfLike) {
        root.innerHTML = libraryNonPdfDetailMarkup(paper);
        root.querySelector('[data-action="open-native-paper-file"]')?.addEventListener("click", () => openNativePaperFile(paper, {
          missingMessage: "No local file path is available for this item."
        }));
        return;
      }
      root.innerHTML = `
        <h3>${escapeHtml(paper.title || "Untitled paper")}</h3>
        ${libraryDetailFigureMarkup(paper)}
        <div class="actions">
          ${paper.merged_pdf_path ? `<button class="action primary" data-action="preview-library-pdf">Open in Preview</button>` : ""}
          ${!paper.merged_pdf_path && isPdfLike ? `<button class="action primary" data-action="download-library-pdf">Download PDF</button>` : ""}
          ${!paper.merged_pdf_path && !isPdfLike && paper.source_path ? `<button class="action primary" data-action="open-native-paper-file">Open File</button>` : ""}
          ${paper.merged_pdf_path ? `<button class="action" data-action="refresh-library-pdf">Download</button>` : ""}
          ${paper.url ? `<button class="action" data-action="open-library-page">Open Page</button>` : ""}
          ${paper.google_scholar_url ? `<button class="action" data-action="open-google-scholar">Google Scholar</button>` : ""}
          <button class="action danger" data-action="remove-library-paper">Remove from current collection</button>
        </div>
        <div class="library-detail-status" id="libraryDetailStatus"></div>
        ${libraryDetailMetadataMarkup(paper, authors)}
        ${citationMetricsMarkup(paper)}
        ${libraryDetailAbstractMarkup(paper)}
        ${pubmedMarkup(paper.pubmed || {})}
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
      root.querySelector('[data-action="open-native-paper-file"]')?.addEventListener("click", () => openNativePaperFile(paper, {
        missingMessage: "No local file path is available for this item."
      }));
      root.querySelector('[data-action="refresh-library-pdf"]')?.addEventListener("click", () => downloadLibraryPdf(paper, {force: true}));
      root.querySelector('[data-action="refresh-library-metadata"]')?.addEventListener("click", () => refreshLibraryMetadataFromDoi(paper));
      root.querySelector("#libraryDetailDoiInput")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") refreshLibraryMetadataFromDoi(paper);
      });
      root.querySelector('[data-action="open-library-page"]')?.addEventListener("click", () => openLibraryPageExternally(paper));
      root.querySelector('[data-action="open-preprint-page"]')?.addEventListener("click", (event) => {
        const url = event.currentTarget?.dataset?.preprintUrl || "";
        openLibraryExternalUrl(url, "Opening preprint...", "Preprint opened");
      });
      root.querySelector('[data-action="open-google-scholar"]')?.addEventListener("click", () => openLibraryExternalUrl(paper.google_scholar_url, "Opening Google Scholar...", "Google Scholar opened"));
      root.querySelector('[data-action="remove-library-paper"]')?.addEventListener("click", async () => {
        const status = $("libraryDetailStatus");
        try {
          await removeLibraryItemFromCurrentCollection(item?.id);
        } catch (error) {
          if (status) {
            status.textContent = error.message || "Could not remove paper from current collection";
            status.className = "library-detail-status err";
          }
        }
      });
      wireCitationSourceSelector(root);
      wireSemanticInfluentialCitations(root);
      root.querySelector('[data-action="copy-bibtex"]')?.addEventListener("click", (event) => copyLibraryBibtex(paper, event.currentTarget));
      root.querySelector('[data-action="copy-nature-reference"]')?.addEventListener("click", (event) => copyLibraryNatureReference(paper, event.currentTarget));
      hydrateLibraryDetailFigureIfNeeded(paper);
    }

    async function loadLibraryItemPaperDetail(item) {
      if (!item?.paper_id || item.paper?.full_detail) return;
      if (state.libraryPaperDetailRequests[item.paper_id]) return state.libraryPaperDetailRequests[item.paper_id];
      state.libraryPaperDetailRequests[item.paper_id] = fetch(`/api/paper?paper_id=${encodeURIComponent(item.paper_id)}`)
        .then(async (res) => {
          const data = await res.json();
          if (!res.ok) throw new Error(data.error || "Could not load paper details");
          if (data.paper) {
            updatePaperState(item.paper_id, data.paper);
            if (
              state.mode === "library"
              && state.libraryTab !== "my-publications"
              && state.librarySelection?.type === "item"
              && Number(state.librarySelection.id) === Number(item.id)
            ) {
              renderLibraryDetail();
            }
          }
        })
        .catch((error) => {
          if (
            state.mode === "library"
            && state.libraryTab !== "my-publications"
            && state.librarySelection?.type === "item"
            && Number(state.librarySelection.id) === Number(item.id)
          ) {
            const status = $("libraryDetailStatus");
            if (status) {
              status.textContent = error.message || "Could not load paper details";
              status.className = "library-detail-status err";
            }
          }
        })
        .finally(() => {
          delete state.libraryPaperDetailRequests[item.paper_id];
        });
      return state.libraryPaperDetailRequests[item.paper_id];
    }

    function renderPublicationDetail() {
      const root = $("libraryDetail");
      if (!root) return;
      const publication = myPublicationById(state.myPublicationSelectionId);
      const paper = publication?.paper || null;
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
          ${paper.merged_pdf_path ? `<button class="action" data-action="refresh-library-pdf">Download</button>` : ""}
          ${paper.url ? `<button class="action" data-action="open-library-page">Open Page</button>` : ""}
          ${paper.google_scholar_url ? `<button class="action" data-action="open-google-scholar">Google Scholar</button>` : ""}
          <span class="publication-role-flags">
            <label class="publication-role-flag" title="Only check for co-first authors. Leave unchecked for solo first author."><input type="checkbox" data-action="toggle-first-author" ${publication.first_author ? "checked" : ""}> Co-1st</label>
            <label class="publication-role-flag" title="Corresponding or co-corresponding author"><input type="checkbox" data-action="toggle-corresponding-author" ${publication.corresponding_author ? "checked" : ""}> Co-corr.</label>
            <label class="publication-role-flag" title="Review or perspective article"><input type="checkbox" data-action="toggle-review-article" ${publication.review_article ? "checked" : ""}> Rev.</label>
          </span>
        </div>
        <div class="library-detail-status" id="libraryDetailStatus"></div>
        ${manualPublicationMetadataMarkup(publication, paper, authors)}
        ${libraryDetailMetadataMarkup(paper, authors, publication, {hideAuthors: true})}
        ${citationMetricsMarkup(paper, {commentsPublicationId: publication.id})}
        ${publicationAuthorsSectionMarkup(publication, authors, paper)}
        ${libraryDetailAbstractMarkup(paper)}
        ${pubmedMarkup(paper.pubmed || {})}
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
      root.querySelector('[data-action="refresh-library-pdf"]')?.addEventListener("click", () => downloadLibraryPdf(paper, {force: true}));
      root.querySelector('[data-action="refresh-library-metadata"]')?.addEventListener("click", () => refreshLibraryMetadataFromDoi(paper));
      root.querySelector("#libraryDetailDoiInput")?.addEventListener("keydown", (event) => {
        if (event.key === "Enter") refreshLibraryMetadataFromDoi(paper);
      });
      root.querySelector('[data-action="open-library-page"]')?.addEventListener("click", () => openLibraryPageExternally(paper));
      root.querySelector('[data-action="open-preprint-page"]')?.addEventListener("click", (event) => {
        const url = event.currentTarget?.dataset?.preprintUrl || "";
        openLibraryExternalUrl(url, "Opening preprint...", "Preprint opened");
      });
      root.querySelector('[data-action="open-google-scholar"]')?.addEventListener("click", () => openLibraryExternalUrl(paper.google_scholar_url, "Opening Google Scholar...", "Google Scholar opened"));
      root.querySelector('[data-action="publication-comments"]')?.addEventListener("click", () => openMyPublicationComments(publication.id));
      wireCitationSourceSelector(root);
      wireSemanticInfluentialCitations(root);
      root.querySelector('[data-action="copy-bibtex"]')?.addEventListener("click", (event) => copyLibraryBibtex(paper, event.currentTarget));
      root.querySelector('[data-action="copy-nature-reference"]')?.addEventListener("click", (event) => copyLibraryNatureReference(paper, event.currentTarget));
      root.querySelector('[data-action="toggle-first-author"]')?.addEventListener("change", () => updateSelectedMyPublicationRoles());
      root.querySelector('[data-action="toggle-corresponding-author"]')?.addEventListener("change", () => updateSelectedMyPublicationRoles());
      root.querySelector('[data-action="toggle-review-article"]')?.addEventListener("change", () => updateSelectedMyPublicationRoles());
      root.querySelector('[data-action="save-manual-publication-metadata"]')?.addEventListener("click", () => saveSelectedManualPublicationMetadata());
      root.querySelectorAll('[data-action="edit-publication-author"]').forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          openPublicationAuthorMenu(button, publication);
        });
      });
      hydrateLibraryDetailFigureIfNeeded(paper);
    }

    function citationMetricsMarkup(paper, options = {}) {
      const metrics = paper.citation_metrics || {};
      const source = metrics.source || "Citation data";
      const rawCount = metrics.count;
      const count = rawCount === null || rawCount === undefined || rawCount === ""
        ? null
        : (Number.isFinite(Number(rawCount)) ? Number(rawCount) : null);
      const sources = metrics.sources || {};
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
      const commentsButton = options.commentsPublicationId
        ? `<div class="citation-comments-row"><button class="action citation-comments-button" data-action="publication-comments" type="button">Comments</button></div>`
        : "";
      return `
        <section class="citation-panel" data-active-citation-source="${escapeAttr(citationSourceKeyFromLabel(source))}">
          <div class="citation-summary">
            <strong data-citation-title>Merged Citations</strong>
            <span class="citation-count" data-citation-count>${count === null ? "--" : escapeHtml(count)}</span>
          </div>
          <div class="citation-source-grid">
            ${citationSourceCell("openalex", "OpenAlex", sources.openalex?.count, citationSourceKeyFromLabel(source))}
            ${citationSourceCell("semantic_scholar", "Semantic", sources.semantic_scholar?.count, citationSourceKeyFromLabel(source), sources.semantic_scholar?.influential_count)}
            ${citationSourceCell("crossref", "Crossref", sources.crossref?.count, citationSourceKeyFromLabel(source))}
            ${paper.ads && Object.keys(paper.ads).length ? citationSourceCell("ads", "ADS", sources.ads?.count, citationSourceKeyFromLabel(source)) : ""}
          </div>
          ${bars}
          ${commentsButton}
          ${semanticScholarMarkup(paper.semantic_scholar || {}, paper)}
          ${adsMarkup(paper.ads || {})}
        </section>
      `;
    }

    function citationSourceCell(key, label, count, activeKey, extra = null) {
      const value = count === null || count === undefined || count === "" ? "--" : count;
      const suffix = extra === null || extra === undefined || extra === "" ? "" : ` · ${escapeHtml(extra)} influential`;
      return `<button class="citation-source-cell${key === activeKey ? " active" : ""}" type="button" data-citation-source="${escapeAttr(key)}" data-citation-label="${escapeAttr(label)}" data-citation-count="${escapeAttr(value)}"><b>${escapeHtml(label)}</b><span>${escapeHtml(value)}</span>${suffix ? `<small>${suffix}</small>` : ""}</button>`;
    }

    function citationSourceKeyFromLabel(label) {
      const normalized = String(label || "").toLowerCase();
      if (normalized.includes("semantic")) return "semantic_scholar";
      if (normalized.includes("crossref")) return "crossref";
      if (normalized.includes("ads")) return "ads";
      return "openalex";
    }

    function wireCitationSourceSelector(root) {
      root.querySelectorAll("[data-citation-source]").forEach((button) => {
        button.addEventListener("click", () => {
          const panel = button.closest(".citation-panel");
          if (!panel) return;
          panel.dataset.activeCitationSource = button.dataset.citationSource || "";
          panel.querySelectorAll("[data-citation-source]").forEach((cell) => cell.classList.toggle("active", cell === button));
          const label = button.dataset.citationLabel || "Citation data";
          const count = button.dataset.citationCount || "--";
          const title = panel.querySelector("[data-citation-title]");
          const counter = panel.querySelector("[data-citation-count]");
          if (title) title.textContent = `${label} Citations`;
          if (counter) counter.textContent = count;
        });
      });
    }

    function wireSemanticInfluentialCitations(root) {
      root.querySelectorAll('[data-action="load-semantic-influential"]').forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          const paperId = button.dataset.paperId || "";
          const panel = button.closest(".semantic-panel");
          const target = panel?.querySelector("[data-semantic-influential-results]");
          if (!paperId || !target) return;
          if (target.dataset.loaded === "1") {
            target.classList.toggle("collapsed");
            target.style.display = target.classList.contains("collapsed") ? "none" : "";
            return;
          }
          button.disabled = true;
          target.innerHTML = `<div class="citation-empty">Loading influential citing papers...</div>`;
          try {
            const res = await fetch(`/api/paper/semantic-influential?paper_id=${encodeURIComponent(paperId)}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "Could not load influential citations");
            target.dataset.loaded = "1";
            target.innerHTML = semanticInfluentialListMarkup(data.citations || []);
          } catch (error) {
            target.innerHTML = `<div class="citation-empty">${escapeHtml(error.message || "Could not load influential citations")}</div>`;
          } finally {
            button.disabled = false;
          }
        });
      });
    }

    function semanticInfluentialListMarkup(citations) {
      if (!Array.isArray(citations) || !citations.length) {
        return `<div class="citation-empty">Semantic Scholar did not return influential citing papers for this item.</div>`;
      }
      return citations.map((item, index) => {
        const authors = Array.isArray(item.authors) ? compactList(item.authors, 4) : "";
        const meta = [
          item.venue || "",
          item.year || "",
          authors ? `Authors: ${authors}` : "",
          Number.isFinite(Number(item.citation_count)) ? `${item.citation_count} cites` : "",
          Number.isFinite(Number(item.influential_citation_count)) ? `${item.influential_citation_count} influential` : "",
          Array.isArray(item.intents) && item.intents.length ? `Intent: ${item.intents.join(", ")}` : ""
        ].filter(Boolean).join(" · ");
        const contexts = Array.isArray(item.contexts) ? item.contexts : [];
        const title = item.url
          ? `<a href="${escapeAttr(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title || "Untitled citing paper")}</a>`
          : escapeHtml(item.title || "Untitled citing paper");
        return `
          <article class="semantic-influential-card">
            <strong>${index + 1}. ${title}</strong>
            ${meta ? `<div class="semantic-influential-meta">${escapeHtml(meta)}</div>` : ""}
            ${contexts.length
              ? contexts.map((context) => `<blockquote class="semantic-influential-context">${escapeHtml(context)}</blockquote>`).join("")
              : `<div class="semantic-influential-meta">No citation-context sentence returned for this influential citation.</div>`}
          </article>
        `;
      }).join("");
    }

    function semanticScholarMarkup(semantic, paper) {
      if (!semantic || !Object.keys(semantic).length) return "";
      const paperId = paper?.paper_id || "";
      const influentialCount = semantic.influential_citation_count ?? null;
      const fields = [
        ...(Array.isArray(semantic.fields_of_study) ? semantic.fields_of_study : []),
        ...(Array.isArray(semantic.s2_fields) ? semantic.s2_fields : [])
      ].filter(Boolean);
      const types = Array.isArray(semantic.publication_types) ? semantic.publication_types : [];
      const authors = Array.isArray(semantic.authors) ? semantic.authors : [];
      const externalIds = semantic.external_ids && typeof semantic.external_ids === "object" ? semantic.external_ids : {};
      const externalIdText = Object.entries(externalIds)
        .filter(([, value]) => value)
        .map(([key, value]) => `${key}: ${value}`)
        .join(" · ");
      const semanticRows = [
        ["Citations", semantic.citation_count ?? "--"],
        ["Influential", influentialCount !== null && influentialCount !== undefined && Number(influentialCount) > 0 && paperId
          ? `<button class="semantic-influential-button" type="button" data-action="load-semantic-influential" data-paper-id="${escapeAttr(paperId)}">${escapeHtml(influentialCount)} influential</button>`
          : escapeHtml(influentialCount ?? "--")],
        ["References", semantic.reference_count ?? "--"],
        ["Venue / Year", [semantic.venue || semantic.journal_name || "", semantic.year || ""].filter(Boolean).join(" · ") || "--"],
        ["Paper ID", semantic.paper_id || "--"],
        ["Corpus ID", semantic.corpus_id || "--"],
        ["Open Access", semantic.is_open_access ? "Yes" : "No"],
        ["External IDs", externalIdText || "--"],
        ["Authors", authors.length ? compactList(authors, 6) : "--"],
      ];
      return `
        <div class="semantic-panel">
          <strong>Semantic Scholar Details</strong>
          ${semantic.tldr ? `<p><b>TLDR</b> ${escapeHtml(semantic.tldr)}</p>` : ""}
          <div class="semantic-detail-grid">
            ${semanticRows.map(([label, value]) => `
              <div class="semantic-detail-row">
                <b>${escapeHtml(label)}</b>
                <span>${String(value).includes("<button") ? value : escapeHtml(value)}</span>
              </div>
            `).join("")}
          </div>
          <div class="semantic-influential-results" data-semantic-influential-results></div>
          <div class="semantic-tags">
            ${fields.map((field) => `<span class="semantic-tag">${escapeHtml(field)}</span>`).join("")}
            ${types.map((type) => `<span class="semantic-tag">${escapeHtml(type)}</span>`).join("")}
            ${semantic.url ? `<a class="semantic-tag" href="${escapeAttr(semantic.url)}" target="_blank" rel="noreferrer">Semantic Scholar</a>` : ""}
            ${semantic.open_access_pdf_url ? `<a class="semantic-tag" href="${escapeAttr(semantic.open_access_pdf_url)}" target="_blank" rel="noreferrer">Open PDF</a>` : ""}
          </div>
        </div>
      `;
    }

    function adsMarkup(ads) {
      if (!ads || !Object.keys(ads).length) return "";
      const identifiers = Array.isArray(ads.identifiers) ? ads.identifiers : [];
      const authors = Array.isArray(ads.authors) ? ads.authors : [];
      const properties = Array.isArray(ads.properties) ? ads.properties : [];
      const alternateBibcodes = Array.isArray(ads.alternate_bibcode) ? ads.alternate_bibcode : [];
      const adsRows = [
        ["Citations", ads.citation_count ?? "--"],
        ["Reads", ads.read_count ?? "--"],
        ["References", ads.reference_count ?? "--"],
        ["Publication / Year", [ads.publication || "", ads.year || ""].filter(Boolean).join(" · ") || "--"],
        ["Bibcode", ads.bibcode || "--"],
        ["Document Type", ads.doctype || "--"],
        ["Volume / Page", [ads.volume || "", ads.page || ""].filter(Boolean).join(" · ") || "--"],
        ["DOI", ads.doi || "--"],
        ["Identifiers", identifiers.length ? compactList(identifiers, 5) : "--"],
        ["Alt. Bibcodes", alternateBibcodes.length ? compactList(alternateBibcodes, 3) : "--"],
        ["Authors", authors.length ? compactList(authors, 6) : "--"],
      ];
      return `
        <div class="ads-panel">
          <strong>ADS Details</strong>
          ${ads.title ? `<p><b>Title</b> ${escapeHtml(ads.title)}</p>` : ""}
          <div class="semantic-detail-grid">
            ${adsRows.map(([label, value]) => `
              <div class="semantic-detail-row">
                <b>${escapeHtml(label)}</b>
                <span>${escapeHtml(value)}</span>
              </div>
            `).join("")}
          </div>
          <div class="semantic-tags">
            ${properties.map((property) => `<span class="semantic-tag">${escapeHtml(property)}</span>`).join("")}
            ${ads.url ? `<a class="semantic-tag" href="${escapeAttr(ads.url)}" target="_blank" rel="noreferrer">Open ADS</a>` : ""}
          </div>
        </div>
      `;
    }

    function pubmedMarkup(pubmed) {
      if (!pubmed || !Object.keys(pubmed).length) return "";
      const types = Array.isArray(pubmed.publication_types) ? pubmed.publication_types : [];
      const keywords = Array.isArray(pubmed.keywords) ? pubmed.keywords : [];
      const mesh = Array.isArray(pubmed.mesh) ? pubmed.mesh : [];
      const rows = [
        ["PMID", pubmed.pmid || "--"],
        ["PMCID", pubmed.pmcid || "--"],
        ["Journal", [pubmed.journal_iso_abbrev || "", pubmed.medline_ta || ""].filter(Boolean).join(" · ") || "--"],
        ["ISSN / NLM", [pubmed.issn || "", pubmed.nlm_unique_id || ""].filter(Boolean).join(" · ") || "--"],
        ["MeSH", mesh.length ? compactList(mesh, 8) : "--"],
        ["Keywords", keywords.length ? compactList(keywords, 8) : "--"],
        ["Types", types.length ? compactList(types, 6) : "--"],
      ];
      return `
        <div class="pubmed-panel">
          <strong>PubMed Details</strong>
          <div class="semantic-detail-grid">
            ${rows.map(([label, value]) => `
              <div class="semantic-detail-row">
                <b>${escapeHtml(label)}</b>
                <span>${escapeHtml(value)}</span>
              </div>
            `).join("")}
          </div>
          <div class="semantic-tags">
            ${pubmed.url ? `<a class="semantic-tag" href="${escapeAttr(pubmed.url)}" target="_blank" rel="noreferrer">Open PubMed</a>` : ""}
            ${pubmed.pmc_url ? `<a class="semantic-tag" href="${escapeAttr(pubmed.pmc_url)}" target="_blank" rel="noreferrer">Open PMC</a>` : ""}
          </div>
        </div>
      `;
    }

    function compactList(items, limit = 6) {
      const list = (Array.isArray(items) ? items : []).filter(Boolean);
      if (list.length <= limit) return list.join(", ");
      return `${list.slice(0, limit).join(", ")}, ... +${list.length - limit}`;
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
          if (state.suppressClickOnce) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          if (event.target.closest(".star-button")) return;
          selectMyPublication(Number(row.dataset.publicationId || 0), {
            extendRange: event.shiftKey,
            toggle: event.metaKey || event.ctrlKey
          });
        });
        row.addEventListener("contextmenu", (event) => {
          if (state.suppressContextMenuOnce) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          showMyPublicationContextMenu(event, Number(row.dataset.publicationId || 0));
        });
        row.addEventListener("dblclick", async (event) => {
          if (event.target.closest("button, input, select, textarea, a")) return;
          const publicationId = Number(row.dataset.publicationId || 0);
          const publication = myPublicationById(publicationId);
          if (!publication) return;
          selectMyPublication(publicationId);
          await openNativePaperFile(publication.paper, {
            missingMessage: "No local file path is available for this publication."
          });
        });
        row.addEventListener("dragstart", (event) => {
          if (state.selectionMarquee) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          event.dataTransfer?.setData("text/plain", row.dataset.publicationId || "");
          event.dataTransfer?.setData("application/x-my-publication-id", row.dataset.publicationId || "");
          row.classList.add("dragging");
        });
        row.addEventListener("dragover", (event) => {
          event.preventDefault();
          clearMyPublicationDragMarkers();
          row.classList.add(myPublicationDropPosition(row, event) === "after" ? "drag-over-after" : "drag-over-before");
        });
        row.addEventListener("dragleave", () => row.classList.remove("drag-over-before", "drag-over-after"));
        row.addEventListener("dragend", () => {
          row.classList.remove("dragging");
          clearMyPublicationDragMarkers();
        });
        row.addEventListener("drop", async (event) => {
          event.preventDefault();
          const position = myPublicationDropPosition(row, event);
          row.classList.remove("drag-over-before", "drag-over-after");
          const draggedId = Number(event.dataTransfer?.getData("application/x-my-publication-id") || event.dataTransfer?.getData("text/plain") || 0);
          const targetId = Number(row.dataset.publicationId || 0);
          if (draggedId && targetId && draggedId !== targetId) await reorderMyPublications(draggedId, targetId, position);
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
      shell.querySelectorAll('[data-action="add-publication-result"]').forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          const index = Number(button.closest("[data-search-index]")?.dataset.searchIndex || -1);
          const candidate = state.myPublicationSearchResults[index];
          if (candidate) await addMyPublicationCandidate(candidate);
        });
      });
      shell.querySelectorAll('[data-action="use-scholar-profile"]').forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          const index = Number(button.closest("[data-search-index]")?.dataset.searchIndex || -1);
          const profile = state.myPublicationSearchResults[index];
          const authorCacheKey = myPublicationAuthorCacheKey($("myPublicationName")?.value || state.myPublicationName || "");
          if (profile?.url) await importGoogleScholarProfile(profile.url, profile.name || "", authorCacheKey, profile);
        });
      });
      shell.querySelectorAll('[data-action="retry-scholar-doi"]').forEach((button) => {
        button.addEventListener("click", async (event) => {
          event.stopPropagation();
          const index = Number(button.closest("[data-search-index]")?.dataset.searchIndex || -1);
          if (index >= 0) await retryScholarDoiAtIndex(index);
        });
      });
      shell.querySelectorAll("[data-publication-col]").forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => startMyPublicationColumnResize(event, handle.dataset.publicationCol));
      });
      shell.querySelector('[data-action="resize-publication-stats"]')?.addEventListener("pointerdown", startMyPublicationStatsResize);
      shell.querySelectorAll('[data-action="publication-role-filter"]').forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          setMyPublicationRoleFilter(button.dataset.roleFilter || "");
        });
      });
      shell.querySelectorAll('[data-action="publication-journal-filter"]').forEach((button) => {
        button.addEventListener("click", (event) => {
          event.stopPropagation();
          setMyPublicationJournalFilter(button.dataset.journalFilter || "");
        });
      });
      shell.querySelector('[data-action="publication-clear-filters"]')?.addEventListener("click", (event) => {
        event.stopPropagation();
        clearMyPublicationFilters();
      });
      shell.querySelectorAll('.my-publications-sort-button[data-publication-sort]').forEach((button) => {
        button.addEventListener("click", (event) => {
          if (event.target.closest(".my-publications-col-resizer")) return;
          const key = button.dataset.publicationSort;
          if (key) sortMyPublicationsByColumn(key);
        });
      });
      const results = $("publicationSearchResults");
      results?.addEventListener("scroll", () => {
        state.myPublicationSearchScrollTop = results.scrollTop;
      });
      shell.querySelector(".my-publications-table-wrap")?.addEventListener("pointerdown", (event) => startDragSelection(event, "my-publications"));
      shell.addEventListener("click", (event) => {
        if (shouldPreserveInteractiveFocus(event.target)) return;
        shell.focus({preventScroll: true});
      });
    }

    function shouldPreserveInteractiveFocus(target) {
      return Boolean(target?.closest?.("input, textarea, select, button, a, [contenteditable='true'], .library-detail, .analysis-body, .bibtex-box, .publication-search-results"));
    }

    function setMyPublicationRoleFilter(filter) {
      state.myPublicationRoleFilter = filter || "";
      renderMyPublications({tableScrollTop: 0});
    }

    function setMyPublicationJournalFilter(filter) {
      state.myPublicationJournalFilter = filter || "";
      renderMyPublications({tableScrollTop: 0});
    }

    function clearMyPublicationFilters() {
      state.myPublicationRoleFilter = "";
      state.myPublicationJournalFilter = "";
      renderMyPublications({tableScrollTop: 0});
    }

    function togglePublicationExportMenu() {
      const menu = $("publicationExportOptions");
      if (!menu) return;
      const open = !menu.classList.contains("open");
      menu.classList.toggle("open", open);
      menu.setAttribute("aria-hidden", open ? "false" : "true");
    }

    function closePublicationExportMenu() {
      const menu = $("publicationExportOptions");
      menu?.classList.remove("open");
      menu?.setAttribute("aria-hidden", "true");
    }

    async function exportPublicationList(format) {
      closePublicationExportMenu();
      const requestedFormat = format || "docx";
      const status = $("publicationSearchStatus");
      if (status) {
        status.textContent = "Exporting publication list...";
        status.className = "publication-search-status live my-publications-tool-note";
      }
      if (format === "overleaf") {
        window.open("https://www.overleaf.com/project", "_blank", "noopener");
      }
      try {
        const target = `/api/my-publications/export?format=${encodeURIComponent(requestedFormat)}&response=json`;
        const res = await fetch(target);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Export failed");
        const openStatus = data.open?.status || "";
        const opened = openStatus === "opened" || openStatus === "copied";
        const targetPath = data.open?.desktop_path || data.path || "";
        state.myPublicationSearchStatus = openStatus === "copied"
          ? `Exported ${data.filename}. Zip copied to Desktop.`
          : (opened ? `Exported ${data.filename}. Opened.` : `Exported ${data.filename}. Could not open automatically.`);
        if (status) {
          status.textContent = `${state.myPublicationSearchStatus} Path: ${targetPath}`;
          status.className = `publication-search-status ${opened ? "ok" : "err"} my-publications-tool-note`;
        }
      } catch (error) {
        state.myPublicationSearchStatus = error.message || "Export failed";
        if (status) {
          status.textContent = state.myPublicationSearchStatus;
          status.className = "publication-search-status err my-publications-tool-note";
        }
      }
    }

    function startMyPublicationStatsResize(event) {
      event.preventDefault();
      event.stopPropagation();
      const stats = event.currentTarget.closest(".my-publications-stats");
      if (!stats) return;
      const startY = event.clientY;
      const startHeight = stats.getBoundingClientRect().height;
      const move = (moveEvent) => {
        const next = Math.max(86, Math.min(320, Math.round(startHeight + startY - moveEvent.clientY)));
        state.myPublicationStatsHeight = next;
        stats.style.setProperty("--my-publications-stats-height", `${next}px`);
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      };
      document.body.style.cursor = "row-resize";
      document.body.style.userSelect = "none";
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    }

    function myPublicationDropPosition(row, event) {
      const rect = row.getBoundingClientRect();
      return event.clientY >= rect.top + rect.height / 2 ? "after" : "before";
    }

    function clearMyPublicationDragMarkers() {
      document.querySelectorAll(".my-publications-row.drag-over-before, .my-publications-row.drag-over-after").forEach((row) => {
        row.classList.remove("drag-over-before", "drag-over-after");
      });
    }

    function rightDragSelectIsInteractiveTarget(target) {
      return Boolean(target?.closest?.("input, textarea, select, a, [contenteditable='true'], [data-library-rename-input], .star-button, .my-publications-col-resizer, .library-column-resizer, .library-detail, .publication-search-results"));
    }

    function marqueeRect(startX, startY, currentX, currentY) {
      const left = Math.min(startX, currentX);
      const top = Math.min(startY, currentY);
      const right = Math.max(startX, currentX);
      const bottom = Math.max(startY, currentY);
      return {left, top, right, bottom, width: right - left, height: bottom - top};
    }

    function rectsIntersect(a, b) {
      return a.left <= b.right && a.right >= b.left && a.top <= b.bottom && a.bottom >= b.top;
    }

    function showSelectionMarquee(rect) {
      let box = document.querySelector(".selection-marquee");
      if (!box) {
        box = document.createElement("div");
        box.className = "selection-marquee";
        document.body.appendChild(box);
      }
      box.style.left = `${rect.left}px`;
      box.style.top = `${rect.top}px`;
      box.style.width = `${rect.width}px`;
      box.style.height = `${rect.height}px`;
    }

    function clearSelectionMarquee() {
      document.querySelector(".selection-marquee")?.remove();
      document.body.classList.remove("marquee-selecting");
      state.selectionMarquee = null;
    }

    function updateLibraryMarqueeSelection(marquee, rect) {
      const folderId = Number(marquee.folderId || 0);
      const rows = [...document.querySelectorAll(`.library-row[data-library-parent-folder="${folderId}"]`)];
      const selectedEntries = [];
      rows.forEach((row) => {
        const rowRect = row.getBoundingClientRect();
        const selected = rectsIntersect(rect, rowRect);
        row.classList.toggle("range-selected", selected);
        row.classList.toggle("active", false);
        row.setAttribute("aria-selected", selected ? "true" : "false");
        if (selected) {
          selectedEntries.push({
            type: row.dataset.libraryType,
            id: Number(row.dataset.libraryId || 0)
          });
        }
      });
      if (!selectedEntries.length) return;
      const last = selectedEntries[selectedEntries.length - 1];
      state.libraryActiveFolderId = folderId;
      state.librarySelection = last;
      state.libraryColumnSelections[folderId] = last;
      state.libraryRangeFolderId = folderId;
      state.libraryRangeAnchor = selectedEntries[0];
      state.libraryRangeSelectionKeys = new Set(selectedEntries.map(libraryEntryKey));
    }

    function updateMyPublicationMarqueeSelection(rect) {
      const rows = [...document.querySelectorAll(".my-publications-row")];
      const selectedIds = [];
      rows.forEach((row) => {
        const rowRect = row.getBoundingClientRect();
        const selected = rectsIntersect(rect, rowRect);
        row.classList.toggle("selected", selected);
        row.classList.toggle("active", false);
        row.setAttribute("aria-selected", selected ? "true" : "false");
        if (selected) selectedIds.push(Number(row.dataset.publicationId || 0));
      });
      if (!selectedIds.length) return;
      state.myPublicationSelectedIds = new Set(selectedIds);
      state.myPublicationSelectionId = selectedIds[selectedIds.length - 1];
      state.myPublicationRangeAnchorId = selectedIds[0];
    }

    function startDragSelection(event, surface) {
      if (state.selectionMarquee) return;
      if (event.button !== 0 || rightDragSelectIsInteractiveTarget(event.target)) return;
      if (surface === "library" && event.target.closest(".library-row")) return;
      if (surface === "my-publications" && event.target.closest(".my-publications-row")) return;
      const column = surface === "library" ? event.target.closest("[data-library-column-folder]") : null;
      const tableWrap = surface === "my-publications" ? event.target.closest(".my-publications-table-wrap") : null;
      if (surface === "library" && !column) return;
      if (surface === "my-publications" && !tableWrap) return;
      state.selectionMarquee = {
        surface,
        folderId: Number(column?.dataset.libraryColumnFolder || 0),
        startX: event.clientX,
        startY: event.clientY,
        currentX: event.clientX,
        currentY: event.clientY,
        moved: false
      };
      const move = (moveEvent) => {
        const marquee = state.selectionMarquee;
        if (!marquee) return;
        marquee.currentX = moveEvent.clientX;
        marquee.currentY = moveEvent.clientY;
        const distance = Math.hypot(marquee.currentX - marquee.startX, marquee.currentY - marquee.startY);
        if (distance < 4 && !marquee.moved) return;
        marquee.moved = true;
        moveEvent.preventDefault();
        moveEvent.stopPropagation();
        document.body.classList.add("marquee-selecting");
        const rect = marqueeRect(marquee.startX, marquee.startY, marquee.currentX, marquee.currentY);
        showSelectionMarquee(rect);
        if (marquee.surface === "library") updateLibraryMarqueeSelection(marquee, rect);
        if (marquee.surface === "my-publications") updateMyPublicationMarqueeSelection(rect);
      };
      const stop = (upEvent) => {
        const marquee = state.selectionMarquee;
        window.removeEventListener("pointermove", move, true);
        window.removeEventListener("pointerup", stop, true);
        if (!marquee) return;
        const moved = marquee.moved;
        clearSelectionMarquee();
        if (!moved) return;
        upEvent.preventDefault();
        upEvent.stopPropagation();
        state.suppressClickOnce = true;
        window.setTimeout(() => { state.suppressClickOnce = false; }, 250);
        if (surface === "library") {
          renderLibraryDetail();
          refreshLibraryQuickLookForSelection();
        } else {
          renderPublicationDetail();
          refreshLibraryQuickLookForSelection();
        }
        $("libraryShell")?.focus({preventScroll: true});
      };
      window.addEventListener("pointermove", move, true);
      window.addEventListener("pointerup", stop, true);
    }

    function closeMyPublicationSearchResults() {
      if (!state.myPublicationSearchResults.length) return;
      state.myPublicationSearchResults = [];
      state.myPublicationSearchStatus = "";
      state.myPublicationSearchScrollTop = 0;
      state.myPublicationSearchToken += 1;
      renderMyPublications({tableScrollTop: 0});
    }

    function sortMyPublicationsByColumn(key) {
      const column = MY_PUBLICATION_COLUMNS.find((item) => item.key === key);
      if (!column?.sortable) return;
      if (state.myPublicationSort === key) {
        state.myPublicationSortDir = state.myPublicationSortDir === "desc" ? "asc" : "desc";
      } else {
        state.myPublicationSort = key;
        state.myPublicationSortDir = column.defaultSortDir || "asc";
      }
      renderMyPublications();
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

    function selectMyPublication(id, options = {}) {
      if (!myPublicationById(id)) return;
      clearScheduledMyPublicationDetailRender();
      if (options.extendRange) setMyPublicationRangeSelection(id);
      else if (options.toggle) toggleMyPublicationSelection(id);
      else setMyPublicationSingleSelection(id);
      updateMyPublicationActiveRow();
      renderPublicationDetail();
      refreshLibraryQuickLookForSelection();
    }

    function updateMyPublicationActiveRow() {
      const activeId = Number(state.myPublicationSelectionId || 0);
      const selectedIds = state.myPublicationSelectedIds || new Set();
      const multiSelected = selectedIds.size > 1;
      document.querySelectorAll(".my-publications-row").forEach((row) => {
        const id = Number(row.dataset.publicationId || 0);
        const active = !multiSelected && id === activeId;
        const selected = selectedIds.has(id);
        row.classList.toggle("active", active);
        row.classList.toggle("selected", selected);
        row.setAttribute("aria-selected", active || selected ? "true" : "false");
      });
    }

    function revealMyPublicationSelection(direction = "nearest") {
      const wrap = document.querySelector(".my-publications-table-wrap");
      const row = document.querySelector(`.my-publications-row[data-publication-id="${Number(state.myPublicationSelectionId || 0)}"]`);
      if (!wrap || !row) return;
      scrollMyPublicationRowIntoView(row, direction);
    }

    function scrollMyPublicationRowIntoView(row, direction = "nearest") {
      const wrap = document.querySelector(".my-publications-table-wrap");
      if (!wrap || !row) return;
      const wrapRect = wrap.getBoundingClientRect();
      const rowRect = row.getBoundingClientRect();
      const head = wrap.querySelector("thead");
      const headerHeight = Math.ceil(head?.getBoundingClientRect().height || 0);
      const padding = 7;
      const top = wrapRect.top + headerHeight + padding;
      const bottom = wrapRect.bottom - padding;
      if (direction === "down") {
        if (rowRect.bottom > bottom) wrap.scrollTop += rowRect.bottom - bottom;
      } else if (direction === "up") {
        if (rowRect.top < top) wrap.scrollTop -= top - rowRect.top;
      } else if (rowRect.bottom > bottom) {
        wrap.scrollTop += rowRect.bottom - bottom;
      } else if (rowRect.top < top) {
        wrap.scrollTop -= top - rowRect.top;
      }
    }

    function scrollMyPublicationKeyboardTarget(targetId, direction) {
      const row = document.querySelector(`.my-publications-row[data-publication-id="${Number(targetId || 0)}"]`);
      if (!row) return;
      scrollMyPublicationRowIntoView(row, direction);
    }

    function scheduleMyPublicationDetailRender(selectedId) {
      const token = ++state.myPublicationKeyboardDetailToken;
      if (state.myPublicationKeyboardDetailTimer) window.clearTimeout(state.myPublicationKeyboardDetailTimer);
      state.myPublicationKeyboardDetailTimer = window.setTimeout(() => {
        state.myPublicationKeyboardDetailTimer = 0;
        if (token !== state.myPublicationKeyboardDetailToken) return;
        if (Number(state.myPublicationSelectionId || 0) !== Number(selectedId || 0)) return;
        renderPublicationDetail();
        refreshLibraryQuickLookForSelection();
      }, 90);
    }

    function clearScheduledMyPublicationDetailRender() {
      state.myPublicationKeyboardDetailToken += 1;
      if (state.myPublicationKeyboardDetailTimer) {
        window.clearTimeout(state.myPublicationKeyboardDetailTimer);
        state.myPublicationKeyboardDetailTimer = 0;
      }
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

    async function toggleMyPublicationHead(publication, head) {
      const res = await fetch("/api/my-publications/head", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({publication_id: publication.id, head})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not update Hide");
      applyMyPublications(data);
      state.myPublicationSelectionId = Number(data.publication?.id || publication.id);
      renderMyPublications();
    }

    async function setMyPublicationHeadById(publicationId, head) {
      const res = await fetch("/api/my-publications/head", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({publication_id: publicationId, head})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not update Hide");
      applyMyPublications(data);
      return data.publication || null;
    }

    async function toggleSelectedMyPublicationsHead(publicationIds, head) {
      const ids = [...new Set((publicationIds || []).map((id) => Number(id)).filter(Boolean))];
      if (!ids.length) return;
      for (const id of ids) {
        if (myPublicationById(id)) await setMyPublicationHeadById(id, head);
      }
      state.myPublicationSelectedIds = new Set(ids.filter((id) => myPublicationById(id)));
      state.myPublicationSelectionId = Number(ids.find((id) => myPublicationById(id)) || state.myPublicationSelectionId || 0);
      state.myPublicationSearchStatus = `${head ? "Hidden" : "Shown"} ${ids.length} publication${ids.length === 1 ? "" : "s"}.`;
      renderMyPublications();
    }

    async function updateSelectedMyPublicationRoles() {
      const publication = myPublicationById(state.myPublicationSelectionId);
      const root = $("libraryDetail");
      if (!publication || !root) return;
      const status = $("libraryDetailStatus");
      const firstAuthor = Boolean(root.querySelector('[data-action="toggle-first-author"]')?.checked);
      const correspondingAuthor = Boolean(root.querySelector('[data-action="toggle-corresponding-author"]')?.checked);
      const reviewArticle = Boolean(root.querySelector('[data-action="toggle-review-article"]')?.checked);
      if (status) {
        status.textContent = "Saving publication flags...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/my-publications/roles", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            publication_id: publication.id,
            first_author: firstAuthor,
            corresponding_author: correspondingAuthor,
            review_article: reviewArticle
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not update publication flags");
        applyMyPublications(data);
        state.myPublicationSelectionId = Number(data.publication?.id || publication.id);
        renderMyPublications();
      } catch (error) {
        if (status) {
          status.textContent = error.message || "Could not update publication flags";
          status.className = "library-detail-status err";
        }
        renderPublicationDetail();
      }
    }

    async function saveSelectedManualPublicationMetadata() {
      const publication = myPublicationById(state.myPublicationSelectionId);
      const root = $("libraryDetail");
      if (!publication || !root || !publication.manual_metadata_editable) return;
      const status = $("libraryDetailStatus");
      const fieldValue = (name) => root.querySelector(`[data-manual-metadata-field="${name}"]`)?.value || "";
      if (status) {
        status.textContent = "Saving manual metadata...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/my-publications/manual-metadata", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            publication_id: publication.id,
            title: fieldValue("title"),
            authors: fieldValue("authors"),
            journal: fieldValue("journal"),
            publication_date: fieldValue("publication_date"),
            volume: fieldValue("volume"),
            issue: fieldValue("issue"),
            pages: fieldValue("pages")
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not save manual metadata");
        applyMyPublications(data);
        state.myPublicationSelectionId = Number(data.publication?.id || publication.id);
        renderMyPublications();
        const nextStatus = $("libraryDetailStatus");
        if (nextStatus) {
          nextStatus.textContent = "Manual metadata saved.";
          nextStatus.className = "library-detail-status ok";
        }
      } catch (error) {
        if (status) {
          status.textContent = error.message || "Could not save manual metadata";
          status.className = "library-detail-status err";
        }
      }
    }

    function openPublicationAuthorMenu(button, publication) {
      closePublicationAuthorMenu();
      const index = Number(button.dataset.authorIndex || 0);
      const authorName = button.dataset.authorName || "";
      let affiliations = [];
      try {
        affiliations = JSON.parse(button.dataset.authorAffiliations || "[]");
      } catch {
        affiliations = [];
      }
      affiliations = Array.isArray(affiliations) ? affiliations.filter(Boolean) : [];
      const mark = publication.author_marks?.[String(index)] || {};
      const rect = button.getBoundingClientRect();
      const menu = document.createElement("div");
      menu.className = "publication-author-menu";
      menu.id = "publicationAuthorMenu";
      menu.innerHTML = `
        <strong>${escapeHtml(authorName)}</strong>
        <div class="publication-author-menu-row">
          <label><input type="checkbox" data-author-menu-field="first_author" ${mark.first_author ? "checked" : ""}> First author</label>
          <label><input type="checkbox" data-author-menu-field="co_first_author" ${mark.co_first_author ? "checked" : ""}> Co-first author</label>
        </div>
        <label><input type="checkbox" data-author-menu-field="corresponding_author" ${mark.corresponding_author ? "checked" : ""}> Corresponding author</label>
        <div class="publication-author-menu-affiliations">
          <b>Affiliations</b>
          ${affiliations.length
            ? affiliations.map((affiliation) => `<p>${escapeHtml(affiliation)}</p>`).join("")
            : `<p>No PubMed affiliation found for this author.</p>`}
        </div>
      `;
      document.body.appendChild(menu);
      const top = Math.min(window.innerHeight - menu.offsetHeight - 12, rect.bottom + 6);
      const left = Math.min(window.innerWidth - menu.offsetWidth - 12, rect.left);
      menu.style.top = `${Math.max(12, top)}px`;
      menu.style.left = `${Math.max(12, left)}px`;
      menu.querySelectorAll("input").forEach((input) => {
        input.addEventListener("change", () => updateSelectedMyPublicationAuthorMark(publication, index, authorName, menu));
      });
    }

    function closePublicationAuthorMenu() {
      $("publicationAuthorMenu")?.remove();
    }

    function showAuthorAffiliationTooltip(anchor) {
      closeAuthorAffiliationTooltip();
      let affiliations = [];
      try {
        affiliations = JSON.parse(anchor?.dataset?.authorAffiliations || "[]");
      } catch {
        affiliations = [];
      }
      affiliations = Array.isArray(affiliations) ? affiliations.filter(Boolean) : [];
      if (!anchor || !affiliations.length) return;
      const detail = anchor.closest(".library-detail") || $("libraryDetail");
      const detailRect = detail?.getBoundingClientRect?.();
      const anchorRect = anchor.getBoundingClientRect();
      const tooltip = document.createElement("div");
      tooltip.className = "author-affiliation-tooltip";
      tooltip.id = "authorAffiliationTooltip";
      tooltip.setAttribute("role", "tooltip");
      tooltip.innerHTML = `
        <b>Affiliations</b>
        ${affiliations.map((affiliation) => `<p>${escapeHtml(affiliation)}</p>`).join("")}
      `;
      document.body.appendChild(tooltip);
      const margin = 8;
      const panelLeft = detailRect ? Math.max(margin, detailRect.left + margin) : margin;
      const panelRight = detailRect ? Math.min(window.innerWidth - margin, detailRect.right - margin) : window.innerWidth - margin;
      const panelTop = detailRect ? Math.max(margin, detailRect.top + margin) : margin;
      const panelBottom = detailRect ? Math.min(window.innerHeight - margin, detailRect.bottom - margin) : window.innerHeight - margin;
      const width = Math.max(180, Math.min(320, panelRight - panelLeft));
      tooltip.style.width = `${width}px`;
      tooltip.style.display = "block";
      const tooltipHeight = tooltip.offsetHeight;
      const preferredLeft = anchorRect.left;
      const left = Math.max(panelLeft, Math.min(preferredLeft, panelRight - width));
      const aboveTop = anchorRect.top - tooltipHeight - 7;
      const belowTop = anchorRect.bottom + 7;
      const top = aboveTop >= panelTop
        ? aboveTop
        : Math.max(panelTop, Math.min(belowTop, panelBottom - tooltipHeight));
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top}px`;
    }

    function closeAuthorAffiliationTooltip() {
      $("authorAffiliationTooltip")?.remove();
    }

    async function updateSelectedMyPublicationAuthorMark(publication, index, authorName, menu) {
      const status = $("libraryDetailStatus");
      const payload = {
        publication_id: publication.id,
        author_index: index,
        author_name: authorName,
        first_author: Boolean(menu.querySelector('[data-author-menu-field="first_author"]')?.checked),
        co_first_author: Boolean(menu.querySelector('[data-author-menu-field="co_first_author"]')?.checked),
        corresponding_author: Boolean(menu.querySelector('[data-author-menu-field="corresponding_author"]')?.checked)
      };
      if (status) {
        status.textContent = "Saving author marker...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/my-publications/author-marks", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not update author marker");
        closePublicationAuthorMenu();
        applyMyPublications(data);
        state.myPublicationSelectionId = Number(data.publication?.id || publication.id);
        renderMyPublications();
      } catch (error) {
        if (status) {
          status.textContent = error.message || "Could not update author marker";
          status.className = "library-detail-status err";
        }
      }
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
      const rows = visibleMyPublicationRows();
      if (!myPublicationById(state.myPublicationSelectionId)) {
        state.myPublicationSelectionId = Number(rows[0]?.id || 0);
      }
      state.myPublicationSearchStatus = "Publication deleted.";
      renderMyPublications();
      refreshLibraryQuickLookForSelection();
    }

    async function deleteMyPublications(publicationIds) {
      const ids = [...new Set((publicationIds || []).map((id) => Number(id)).filter(Boolean))];
      if (!ids.length) return;
      for (const id of ids) {
        if (!myPublicationById(id)) continue;
        const res = await fetch("/api/my-publications/delete", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({publication_id: id})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not delete publication");
        applyMyPublications(data);
      }
      state.myPublicationSelectedIds = new Set();
      const rows = visibleMyPublicationRows();
      state.myPublicationSelectionId = Number(rows[0]?.id || 0);
      if (state.myPublicationSelectionId) state.myPublicationSelectedIds = new Set([state.myPublicationSelectionId]);
      state.myPublicationRangeAnchorId = state.myPublicationSelectionId;
      state.myPublicationSearchStatus = `Deleted ${ids.length} publication${ids.length === 1 ? "" : "s"}.`;
      renderMyPublications();
      refreshLibraryQuickLookForSelection();
    }

    async function reimportMyPublication(publicationId) {
      state.myPublicationSearchStatus = "Reimporting this publication by DOI...";
      renderMyPublications();
      const res = await fetch("/api/my-publications/reimport", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({publication_id: publicationId})
      });
      const data = await res.json();
      if (!res.ok) {
        state.myPublicationSearchStatus = data.error || "Could not reimport this publication";
        renderMyPublications();
        return;
      }
      applyMyPublications(data);
      state.myPublicationSelectionId = Number(data.publication?.id || state.myPublicationSelectionId || 0);
      state.myPublicationSearchStatus = "Publication reimported by DOI.";
      renderMyPublications();
      refreshLibraryQuickLookForSelection();
    }

    async function openMyPublicationComments(publicationId) {
      const publication = myPublicationById(publicationId);
      if (!publication) return;
      state.myPublicationSelectionId = Number(publicationId);
      state.myPublicationSearchStatus = "Building citation comments report from citing-paper metadata...";
      renderMyPublications();
      try {
        const res = await fetch("/api/my-publications/comments", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({publication_id: publicationId})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not build comments report");
        state.myPublicationSearchStatus = `Comments report opened · ${Number(data.citing_count || 0)} citing papers fetched.`;
        renderMyPublications();
        showAnalysis(data.paper || publication.paper, data.content || "");
      } catch (error) {
        state.myPublicationSearchStatus = error.message || "Could not build comments report";
        renderMyPublications();
      }
    }

    async function refreshMyPublicationMetrics() {
      if (state.myPublicationMetricsRefreshing) return;
      const button = $("refreshMyPublicationMetrics");
      state.myPublicationMetricsRefreshing = true;
      state.myPublicationSearchStatus = "Refreshing citation metrics and PubMed metadata...";
      if (button) button.disabled = true;
      updateMyPublicationSearchStatusText();
      try {
        const res = await fetch("/api/my-publications/refresh-metrics", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not refresh metrics");
        const job = data.job || {};
        state.myPublicationMetricsJobId = data.job_id || job.job_id || "";
        state.myPublicationSearchStatus = myPublicationMetricsStatusText(job);
        updateMyPublicationSearchStatusText();
        await pollMyPublicationMetrics(state.myPublicationMetricsJobId);
      } catch (error) {
        state.myPublicationSearchStatus = error.message || "Could not refresh metrics";
        updateMyPublicationSearchStatusText();
      } finally {
        state.myPublicationMetricsRefreshing = false;
        state.myPublicationMetricsJobId = "";
        if (button) button.disabled = false;
        updateMyPublicationSearchStatusText();
      }
    }

    function myPublicationMetricsStatusText(job) {
      const status = job?.status || "";
      const current = Number(job?.current || 0);
      const total = Number(job?.total || 0);
      const refreshed = Number(job?.refreshed || 0);
      const skipped = Number(job?.skipped || 0);
      if (status === "completed") {
        return `Metrics refreshed for ${refreshed} publication${refreshed === 1 ? "" : "s"}${skipped ? ` · ${skipped} skipped` : ""}.`;
      }
      if (status === "failed") return `Metrics refresh failed${job?.errors?.length ? ` · ${job.errors[0]}` : ""}`;
      if (total) return `Refreshing metrics ${current} / ${total} · ${refreshed} updated${job?.current_title ? ` · ${job.current_title}` : ""}`;
      return "Refreshing citation metrics and PubMed metadata...";
    }

    async function pollMyPublicationMetrics(jobId) {
      if (!jobId) return;
      while (true) {
        await sleep(1000);
        const res = await fetch(`/api/my-publications/refresh-metrics/progress?job_id=${encodeURIComponent(jobId)}`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not refresh metrics");
        const job = data.job || {};
        state.myPublicationSearchStatus = myPublicationMetricsStatusText(job);
        if (["completed", "failed"].includes(job.status)) {
          if (job.status === "failed") throw new Error(state.myPublicationSearchStatus);
          const detailScrollTop = $("libraryDetail")?.scrollTop || 0;
          const tableScrollTop = document.querySelector(".my-publications-table-wrap")?.scrollTop || 0;
          if (Array.isArray(job.publications) && job.publications.length) {
            applyMyPublications({publications: job.publications});
            renderMyPublications({detailScrollTop, tableScrollTop});
          } else {
            updateMyPublicationSearchStatusText();
          }
          return;
        }
        updateMyPublicationSearchStatusText();
      }
    }

    async function reorderMyPublications(draggedId, targetId, position = "before") {
      const rows = sortedMyPublications();
      const ids = rows.map((entry) => Number(entry.id));
      const from = ids.indexOf(Number(draggedId));
      const to = ids.indexOf(Number(targetId));
      if (from < 0 || to < 0 || from === to) return;
      const [movedId] = ids.splice(from, 1);
      let insertIndex = ids.indexOf(Number(targetId));
      if (position === "after") insertIndex += 1;
      ids.splice(Math.max(0, Math.min(ids.length, insertIndex)), 0, movedId);
      state.myPublicationSort = "manual";
      state.myPublications = ids
        .map((id, index) => {
          const entry = myPublicationById(id);
          return entry ? {...entry, sort_order: index} : null;
        })
        .filter(Boolean);
      renderMyPublications();
      const res = await fetch("/api/my-publications/reorder", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({publication_ids: ids})
      });
      const data = await res.json();
      if (!res.ok) {
        state.myPublicationSearchStatus = data.error || "Could not reorder publications";
        renderMyPublications();
        return;
      }
      applyMyPublications(data);
      state.myPublicationSearchStatus = "Publication order updated.";
      renderMyPublications();
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

    function myPublicationAuthorCacheKey(value) {
      return String(value || "").trim().replace(/\s+/g, " ").toLowerCase();
    }

    function cacheMyPublicationAuthorResults(key) {
      if (!key) return;
      if (!Array.isArray(state.myPublicationSearchResults) || !state.myPublicationSearchResults.length) return;
      state.myPublicationAuthorCache[key] = {
        results: JSON.parse(JSON.stringify(state.myPublicationSearchResults || [])),
        status: state.myPublicationSearchStatus || "",
      };
    }

    function restoreMyPublicationAuthorResults(key) {
      const cached = key ? state.myPublicationAuthorCache[key] : null;
      if (!cached) return false;
      if (!Array.isArray(cached.results) || !cached.results.length) return false;
      state.myPublicationSearchToken += 1;
      state.myPublicationSearchResults = JSON.parse(JSON.stringify(cached.results || []));
      state.myPublicationSearchStatus = cached.status || `${state.myPublicationSearchResults.length} cached Scholar results.`;
      state.myPublicationSearchScrollTop = 0;
      renderMyPublications();
      return true;
    }

    async function searchMyPublications(kind = "auto") {
      const query = kind === "author" ? ($("myPublicationName")?.value || state.myPublicationName || "") : ($("publicationSearchBox")?.value || "");
      const cleanQuery = query.trim();
      if (!cleanQuery) return;
      if (kind === "author") await saveMyPublicationName();
      const authorCacheKey = kind === "author" ? myPublicationAuthorCacheKey(cleanQuery) : "";
      if (authorCacheKey && restoreMyPublicationAuthorResults(authorCacheKey)) return;
      state.myPublicationSearchToken += 1;
      state.myPublicationSearchStatus = kind === "author" ? "Matching Google Scholar profiles..." : "Searching publications...";
      state.myPublicationSearchResults = [];
      state.myPublicationSearchScrollTop = 0;
      renderMyPublications();
      try {
        const url = kind === "author"
          ? `/api/google-scholar-profiles?q=${encodeURIComponent(cleanQuery)}`
          : `/api/publication-search?q=${encodeURIComponent(cleanQuery)}&kind=${encodeURIComponent(kind)}`;
        const res = await fetch(url);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Search failed");
        state.myPublicationSearchResults = kind === "author" ? (data.profiles || []) : (data.results || []);
        state.myPublicationSearchStatus = state.myPublicationSearchResults.length
          ? (kind === "author"
            ? `${state.myPublicationSearchResults.length} Google Scholar profiles found. Choose the right profile.`
            : `${state.myPublicationSearchResults.length} candidates found.`)
          : (kind === "author" ? "No Google Scholar profiles found." : "No publication candidates found.");
        if (authorCacheKey) cacheMyPublicationAuthorResults(authorCacheKey);
      } catch (error) {
        state.myPublicationSearchStatus = error.message || "Search failed";
      }
      renderMyPublications();
    }

    async function addMyPublicationCandidate(candidate) {
      const results = $("publicationSearchResults");
      if (results) state.myPublicationSearchScrollTop = results.scrollTop;
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
      sortMyPublicationSearchResultsByAdded();
      state.myPublicationSearchStatus = "Publication added.";
      renderMyPublications();
    }

    async function importGoogleScholarProfile(profileUrl = "", profileName = "", authorCacheKey = "", profile = null) {
      const button = $("findMyPublications");
      const url = String(profileUrl || "").trim();
      if (!url) return;
      const searchToken = ++state.myPublicationSearchToken;
      state.myPublicationScholarProfile = {...(profile || {}), name: profileName || profile?.name || ""};
      state.myPublicationSearchStatus = `Importing Google Scholar titles${profileName ? ` for ${profileName}` : ""}...`;
      state.myPublicationSearchResults = [];
      state.myPublicationSearchScrollTop = 0;
      if (button) {
        button.disabled = true;
        button.textContent = "Searching...";
      }
      renderMyPublications();
      try {
        const res = await fetch("/api/my-publications/import-scholar", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({url})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Google Scholar import failed");
        if (searchToken !== state.myPublicationSearchToken) return;
        state.myPublicationScholarProfile = {...(state.myPublicationScholarProfile || {}), ...(data.profile || {})};
        state.myPublicationSearchResults = data.results || [];
        sortMyPublicationSearchResultsByAdded();
        const errorCount = Array.isArray(data.errors) ? data.errors.length : 0;
        state.myPublicationSearchStatus = state.myPublicationSearchResults.length
          ? `${state.myPublicationSearchResults.length} Scholar titles found. Resolving DOI/arXiv matches...`
          : `No Scholar titles found${errorCount ? ` · ${errorCount} errors` : ""}.`;
        if (authorCacheKey) cacheMyPublicationAuthorResults(authorCacheKey);
        renderMyPublications();
        if (state.myPublicationSearchResults.length) {
          resolveScholarSearchResults(searchToken, authorCacheKey);
        }
      } catch (error) {
        if (searchToken !== state.myPublicationSearchToken) return;
        state.myPublicationSearchStatus = error.message || "Google Scholar import failed";
      } finally {
        if (button) {
          button.disabled = false;
          button.textContent = "Find by Name";
        }
      }
      renderMyPublications();
    }

    async function resolveScholarSearchResults(searchToken, authorCacheKey = "") {
      const total = state.myPublicationSearchResults.length;
      for (let pass = 1; pass <= 3; pass += 1) {
        if (searchToken !== state.myPublicationSearchToken) return;
        const unresolved = scholarOnlyIndexes();
        if (!unresolved.length) break;
        if (pass > 1) {
          state.myPublicationSearchStatus = `${total} Scholar titles found · retrying ${unresolved.length} unresolved identifier lookup${unresolved.length === 1 ? "" : "s"}...`;
          renderMyPublications();
          await sleep(pass === 2 ? 1200 : 2200);
        }
        for (let attemptIndex = 0; attemptIndex < unresolved.length; attemptIndex += 1) {
          if (searchToken !== state.myPublicationSearchToken) return;
          const index = unresolved[attemptIndex];
          state.myPublicationSearchStatus = `${total} Scholar titles found. ${pass > 1 ? "Retrying" : "Resolving"} DOI/arXiv ${attemptIndex + 1} / ${unresolved.length}...`;
          await resolveScholarCandidateAtIndex(index, searchToken, authorCacheKey);
        }
      }
      updateScholarResolutionStatus("done");
      sortMyPublicationSearchResultsByAdded();
      if (authorCacheKey) cacheMyPublicationAuthorResults(authorCacheKey);
      renderMyPublications();
    }

    function scholarOnlyIndexes() {
      return state.myPublicationSearchResults
        .map((candidate, index) => candidate?.match_status === "scholar" ? index : -1)
        .filter((index) => index >= 0);
    }

    function scholarIdentifierMatchCount() {
      return state.myPublicationSearchResults.filter((candidate) => ["doi", "arxiv"].includes(candidate?.match_status)).length;
    }

    function updateScholarResolutionStatus(stage = "") {
      const total = state.myPublicationSearchResults.length;
      const matched = scholarIdentifierMatchCount();
      const unresolved = scholarOnlyIndexes().length;
      const prefix = `${total} Scholar titles found · ${matched} DOI/arXiv matches · ${unresolved} Scholar-only`;
      state.myPublicationSearchStatus = stage === "done" ? `${prefix}.` : prefix;
    }

    async function resolveScholarCandidateAtIndex(index, searchToken, authorCacheKey = "") {
      const candidate = state.myPublicationSearchResults[index];
      if (!candidate || candidate.match_status !== "scholar") return false;
      state.myPublicationSearchResults[index] = {...candidate, match_status: "resolving"};
      renderMyPublications();
      try {
        const res = await fetch("/api/my-publications/resolve-scholar", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({candidate})
        });
        const data = await res.json();
        if (searchToken !== state.myPublicationSearchToken) return false;
        if (res.ok && data.candidate) {
          state.myPublicationSearchResults[index] = data.candidate;
          updateScholarResolutionStatus();
          if (authorCacheKey) cacheMyPublicationAuthorResults(authorCacheKey);
          renderMyPublications();
          return true;
        }
      } catch (error) {
        if (searchToken !== state.myPublicationSearchToken) return false;
      }
      state.myPublicationSearchResults[index] = {...candidate, match_status: "scholar"};
      updateScholarResolutionStatus();
      if (authorCacheKey) cacheMyPublicationAuthorResults(authorCacheKey);
      renderMyPublications();
      return false;
    }

    async function retryScholarDoiAtIndex(index) {
      if (!state.myPublicationSearchResults[index]) return;
      const searchToken = ++state.myPublicationSearchToken;
      const authorCacheKey = myPublicationAuthorCacheKey($("myPublicationName")?.value || state.myPublicationName || "");
      state.myPublicationSearchStatus = "Retrying DOI/arXiv lookup for this Scholar title...";
      await resolveScholarCandidateAtIndex(index, searchToken, authorCacheKey);
      updateScholarResolutionStatus("done");
      if (authorCacheKey) cacheMyPublicationAuthorResults(authorCacheKey);
      renderMyPublications();
    }

    function handleMyPublicationKeydown(event, key) {
      const rows = visibleMyPublicationRows();
      if (!rows.length) return true;
      if (key === " ") {
        const paper = selectedMyPublicationPaper();
        if (paper?.merged_pdf_path) quickLookLibraryPdf(paper, {toggle: true});
        else quickLookLibraryFile(paper, {toggle: true, openPlaceholder: true});
        return true;
      }
      if (key === "Delete" || key === "Backspace") {
        const ids = selectedMyPublicationIdsForAction();
        if (ids.length) runLibraryMenuAction(() => deleteMyPublications(ids));
        return true;
      }
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(key)) return false;
      const currentIndex = rows.findIndex((entry) => Number(entry.id) === Number(state.myPublicationSelectionId));
      const movingDown = key === "ArrowDown" || key === "ArrowRight";
      const fallback = movingDown ? 0 : rows.length - 1;
      const nextIndex = currentIndex < 0
        ? fallback
        : Math.max(0, Math.min(rows.length - 1, currentIndex + (movingDown ? 1 : -1)));
      const nextId = Number(rows[nextIndex].id);
      if (event.shiftKey) setMyPublicationRangeSelection(nextId);
      else setMyPublicationSingleSelection(nextId);
      updateMyPublicationActiveRow();
      scrollMyPublicationKeyboardTarget(nextId, movingDown ? "down" : "up");
      scheduleMyPublicationDetailRender(nextId);
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
        row.querySelectorAll("[data-native-file-drag-handle]").forEach((handle) => {
          handle.addEventListener("mousedown", (event) => {
            event.stopPropagation();
            prepareNativeFileDrag(handle);
          });
          handle.addEventListener("dragstart", (event) => {
            event.preventDefault();
            event.stopPropagation();
          });
        });
        row.addEventListener("click", (event) => {
          if (state.suppressClickOnce) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          if (event.target.closest("[data-library-rename-input]")) return;
          const type = row.dataset.libraryType;
          const id = Number(row.dataset.libraryId);
          const parentFolderId = Number(row.dataset.libraryParentFolder || state.libraryRootId);
          if (librarySearchIsActive()) {
            selectLibrarySearchEntry(parentFolderId, type, id);
            return;
          }
          selectLibraryEntry(parentFolderId, type, id, {
            extendRange: event.shiftKey,
            revealChildColumn: type === "folder" && !event.shiftKey
          });
        });
        row.addEventListener("dblclick", () => {
          const id = Number(row.dataset.libraryId);
          if (row.dataset.libraryType === "folder") {
            focusLibraryFolder(id);
            return;
          }
          if (row.dataset.libraryType === "item") {
            openNativeLibraryEntry("item", id);
          }
        });
        row.addEventListener("dragstart", (event) => {
          if (state.selectionMarquee) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
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
          if (state.suppressContextMenuOnce) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          event.stopPropagation();
          const type = row.dataset.libraryType;
          const id = Number(row.dataset.libraryId);
          const parentFolderId = Number(row.dataset.libraryParentFolder || state.libraryRootId);
          if (!libraryEntryIsInActionSelection(parentFolderId, {type, id})) {
            setLibraryColumnSelection(parentFolderId, {type, id});
          }
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
        column.addEventListener("pointerdown", (event) => startDragSelection(event, "library"));
        body?.addEventListener("scroll", () => {
          if (folderId) state.libraryColumnScrollTops[folderId] = body.scrollTop;
        });
        column.addEventListener("click", (event) => {
          if (state.suppressClickOnce) {
            event.preventDefault();
            event.stopPropagation();
            return;
          }
          if (event.target.closest(".library-row")) return;
          selectLibraryColumnFolder(Number(column.dataset.libraryColumnFolder || state.libraryRootId));
          renderLibrary();
          refreshLibraryQuickLookForSelection();
        });
      });
      $("libraryColumns")?.addEventListener("scroll", (event) => {
        state.libraryColumnsScrollLeft = event.currentTarget.scrollLeft;
      });
      shell.querySelectorAll("[data-library-resize-folder]").forEach((handle) => {
        handle.addEventListener("pointerdown", (event) => startLibraryColumnResize(event, Number(handle.dataset.libraryResizeFolder || 0)));
      });
      $("libraryDetailDivider")?.addEventListener("pointerdown", startLibraryDetailResize);
      shell.addEventListener("contextmenu", (event) => {
        if (state.suppressContextMenuOnce) {
          event.preventDefault();
          event.stopPropagation();
          return;
        }
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

    function prepareNativeFileDrag(handle) {
      const path = handle?.dataset?.nativeDragPath || "";
      if (!path || !window.webkit?.messageHandlers?.nativeFileDrag) return;
      window.webkit.messageHandlers.nativeFileDrag.postMessage({
        path,
        name: handle.dataset.nativeDragName || fileNameFromPath(path) || "paper.pdf"
      });
    }

    function fileNameFromPath(path) {
      return String(path || "").split(/[\\/]/).filter(Boolean).pop() || "";
    }

    function sanitizeDragFileName(name) {
      return String(name || "").replace(/[\\r\\n:]/g, " ").trim() || "file";
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

    function paperNativePath(paper) {
      return paper.native_file_path || paper.merged_pdf_path || paper.main_pdf_path || paper.source_path || "";
    }

    function libraryNativeItemPath(item) {
      return paperNativePath(item?.paper || {});
    }

    function libraryNativeFolderPath(folderId) {
      const folderIds = libraryDescendantFolderIds(folderId);
      const items = state.libraryItems
        .filter((item) => folderIds.has(Number(item.folder_id || 0)))
        .sort((a, b) => compareLibraryOrder(a, b, "display_name"));
      const pdfItem = items.find((item) => item?.paper?.merged_pdf_path || item?.paper?.main_pdf_path);
      const sourceItem = items.find((item) => item?.paper?.source_path);
      return libraryNativeItemPath(pdfItem || sourceItem || null);
    }

    function libraryNativeTargetForEntry(entryType, entryId) {
      if (entryType === "item") {
        return {path: libraryNativeItemPath(libraryItemById(entryId)), mode: "open"};
      }
      if (entryType === "folder") {
        return {path: libraryNativeFolderPath(entryId), mode: "folder"};
      }
      return {path: "", mode: "open"};
    }

    async function openNativeLibraryEntry(entryType, entryId) {
      const target = libraryNativeTargetForEntry(entryType, entryId);
      await openNativeTarget(target, {
        missingMessage: entryType === "folder"
          ? "No native file was found inside this folder."
          : "No native file path is available for this item.",
        openingMessage: target.mode === "folder" ? "Opening native folder in Finder..." : "Opening native file...",
        openedMessage: target.mode === "folder" ? "Native folder opened in Finder" : "Native file opened"
      });
    }

    async function revealNativeLibraryEntry(entryType, entryId) {
      const target = libraryNativeTargetForEntry(entryType, entryId);
      const status = $("libraryDetailStatus");
      if (!target.path) {
        if (status) {
          status.textContent = entryType === "folder"
            ? "No native file was found inside this folder."
            : "No native file path is available for this item.";
          status.className = "library-detail-status err";
        }
        return;
      }
      if (status) {
        status.textContent = "Opening in Finder...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/reveal-path", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({path: target.path})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Failed to open Finder");
        if (status) status.textContent = "Opened in Finder";
      } catch (err) {
        if (status) {
          status.textContent = err.message || "Failed to open Finder";
          status.className = "library-detail-status err";
        }
      }
    }

    async function openNativePaperFile(paper, options = {}) {
      await openNativeTarget({path: paperNativePath(paper || {}), mode: "open"}, {
        missingMessage: options.missingMessage || "No local file path is available for this paper.",
        openingMessage: "Opening local file...",
        openedMessage: "Local file opened"
      });
    }

    function nativeFilePreviewUrl(path) {
      return `/api/native-file-preview?path=${encodeURIComponent(path)}`;
    }

    function libraryFileExtension(paper) {
      const explicit = String(paper?.file_extension || "").trim().replace(/^\./, "");
      if (explicit) return explicit.toLowerCase();
      const path = paperNativePath(paper || {});
      const name = path.split(/[\\/]/).pop() || "";
      const match = name.match(/\.([^.]+)$/);
      return match ? match[1].toLowerCase() : "";
    }

    function libraryFilePreviewKind(paper) {
      const mime = String(paper?.file_mime_type || "").toLowerCase();
      const ext = libraryFileExtension(paper);
      const textExtensions = new Set(["txt", "md", "markdown", "csv", "tsv", "json", "jsonl", "xml", "html", "htm", "css", "js", "ts", "py", "c", "cc", "cpp", "h", "hpp", "java", "m", "mm", "tex", "bib", "ris", "log", "ini", "yaml", "yml", "toml", "rtf"]);
      if (mime.startsWith("image/")) return "image";
      if (mime.startsWith("video/")) return "video";
      if (mime.startsWith("audio/")) return "audio";
      if (mime.startsWith("text/") || textExtensions.has(ext) || mime === "application/json" || mime.endsWith("+json") || mime.endsWith("+xml")) return "text";
      return "file";
    }

    function libraryFilePreviewTitle(paper) {
      return paper?.citation_label || paper?.title || paper?.original_filename || "File Preview";
    }

    function renderLibraryQuickLookFileThumb(paper) {
      const root = $("libraryQuickLookThumbs");
      if (!root) return;
      const ext = libraryFileExtension(paper) || "file";
      root.innerHTML = `
        <button class="library-page-thumb active" type="button">
          <span class="library-file-thumb-preview">${escapeHtml(ext.slice(0, 8))}</span>
          <span>File</span>
        </button>
      `;
    }

    function renderLibraryFilePreviewCard(root, paper, message = "") {
      const path = paperNativePath(paper || {});
      const size = fileSizeLabel(paper?.file_size_bytes);
      root.innerHTML = `
        <div class="library-file-preview">
          <div class="library-file-preview-card">
            <strong>${escapeHtml(libraryFilePreviewTitle(paper))}</strong>
            <span>${escapeHtml([importedFileFormatLabel(paper), size].filter(Boolean).join(" · "))}</span>
            ${message ? `<span>${escapeHtml(message)}</span>` : ""}
            <span>${escapeHtml(path)}</span>
            ${path ? `<button class="action" type="button" data-open-native-preview>Open File</button>` : ""}
          </div>
        </div>
      `;
      root.querySelector("[data-open-native-preview]")?.addEventListener("click", () => openNativePaperFile(paper));
    }

    async function renderLibraryQuickLookFilePreview(paper, token) {
      const root = $("libraryQuickLookPages");
      if (!root) return;
      const path = paperNativePath(paper || {});
      const url = nativeFilePreviewUrl(path);
      const kind = libraryFilePreviewKind(paper);
      root.onscroll = null;
      if (!path) {
        renderLibraryFilePreviewCard(root, paper, "No local file path is available.");
        return;
      }
      if (kind === "image") {
        root.innerHTML = `
          <div class="library-file-preview image">
            <img src="${escapeAttr(url)}" alt="${escapeAttr(libraryFilePreviewTitle(paper))}">
          </div>
        `;
        root.querySelector("img")?.addEventListener("error", () => renderLibraryFilePreviewCard(root, paper, "Preview could not be rendered."));
        return;
      }
      if (kind === "video") {
        root.innerHTML = `
          <div class="library-file-preview media">
            <video controls src="${escapeAttr(url)}"></video>
          </div>
        `;
        return;
      }
      if (kind === "audio") {
        root.innerHTML = `
          <div class="library-file-preview media">
            <audio controls src="${escapeAttr(url)}"></audio>
          </div>
        `;
        return;
      }
      if (kind === "text") {
        root.innerHTML = `<div class="library-file-preview text"><pre class="library-file-preview-text">Loading...</pre></div>`;
        try {
          const res = await fetch(url, {cache: "no-store"});
          const text = await res.text();
          if (token !== state.libraryQuickLookRenderToken || path !== state.libraryQuickLookPath) return;
          if (!res.ok) throw new Error(text || "Preview failed");
          const limit = 350000;
          const clipped = text.length > limit ? `${text.slice(0, limit)}\n\n[Preview truncated]` : text;
          root.innerHTML = `<div class="library-file-preview text"><pre class="library-file-preview-text">${escapeHtml(clipped)}</pre></div>`;
        } catch (error) {
          if (token === state.libraryQuickLookRenderToken) renderLibraryFilePreviewCard(root, paper, error.message || "Preview failed.");
        }
        return;
      }
      renderLibraryFilePreviewCard(root, paper, "This file type cannot be rendered inline yet.");
    }

    async function quickLookLibraryFile(paper, options = {}) {
      const path = paperNativePath(paper || {});
      const status = $("libraryDetailStatus");
      if (!path) {
        if (status && !options.silent) {
          status.textContent = options.missingMessage || "No local file path is available for this item.";
          status.className = "library-detail-status err";
        }
        if (options.openPlaceholder) showLibraryQuickLookPlaceholder({open: true});
        return;
      }
      if (options.toggle && state.libraryQuickLookOpen && state.libraryQuickLookKind === "file" && path === state.libraryQuickLookPath) {
        closeLibraryQuickLook();
        return;
      }
      if (status && !options.silent) {
        status.textContent = "Previewing file";
        status.className = "library-detail-status";
      }
      const overlay = $("libraryQuickLook");
      const title = $("libraryQuickLookTitle");
      const pages = $("libraryQuickLookPages");
      if (!overlay || !pages) return;
      const token = ++state.libraryQuickLookRenderToken;
      const isNewFile = path !== state.libraryQuickLookPath || state.libraryQuickLookKind !== "file";
      state.libraryQuickLookOpen = true;
      state.libraryQuickLookKind = "file";
      state.libraryQuickLookPath = path;
      state.libraryQuickLookUrl = nativeFilePreviewUrl(path);
      state.libraryQuickLookPage = 1;
      state.libraryQuickLookPageCount = 1;
      state.libraryQuickLookPdfHasFocus = false;
      if (title) title.textContent = libraryFilePreviewTitle(paper);
      renderLibraryQuickLookFileThumb(paper);
      overlay.classList.remove("compact");
      overlay.classList.add("open");
      overlay.setAttribute("aria-hidden", "false");
      if (!state.libraryQuickLookManualFrame || !state.libraryQuickLookFrameRect) {
        applyLibraryQuickLookFrame(defaultLibraryQuickLookFrame());
      } else {
        applyLibraryQuickLookFrame();
      }
      reclaimLibraryQuickLookFocus();
      if (isNewFile) await renderLibraryQuickLookFilePreview(paper, token);
      if (status && !options.silent) {
        status.textContent = "File preview open";
        status.className = "library-detail-status ok";
      }
    }

    async function openNativeTarget(target, messages = {}) {
      const status = $("libraryDetailStatus");
      if (!target.path) {
        if (status) {
          status.textContent = messages.missingMessage || "No native file path is available.";
          status.className = "library-detail-status err";
        }
        return;
      }
      if (status) {
        status.textContent = messages.openingMessage || "Opening native file...";
        status.className = "library-detail-status";
      }
      try {
        const res = await fetch("/api/open-native-file", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify(target)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "open failed");
        if (status) {
          status.textContent = messages.openedMessage || "Native file opened";
          status.className = "library-detail-status ok";
        }
      } catch (error) {
        if (status) {
          status.textContent = error.message;
          status.className = "library-detail-status err";
        }
      }
    }

    async function downloadLibraryPdf(paper, options = {}) {
      if (!paper?.paper_id) return;
      const status = $("libraryDetailStatus");
      const buttons = $("libraryDetail")?.querySelectorAll("button") || [];
      const activityId = `pdf:${paper.paper_id}`;
      buttons.forEach((button) => button.disabled = true);
      if (status) {
        status.textContent = options.force ? "Refreshing PDF..." : "Downloading PDF...";
        status.className = "library-detail-status";
      }
      if (state.libraryTab === "my-publications") {
        setMyPublicationActivity(activityId, options.force ? "Refreshing PDF..." : "Downloading PDF...");
      }
      updateLibraryActivityStatus(options.force ? "Refreshing PDF..." : "Downloading PDF...", {live: true, clear: false});
      try {
        const res = await fetch("/api/download", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({paper_id: paper.paper_id, force: Boolean(options.force)})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "download failed");
        updatePaperState(paper.paper_id, data.paper);
        if (status) {
          status.textContent = options.force ? "PDF refreshed" : "PDF downloaded";
          status.className = "library-detail-status ok";
        }
        if (state.libraryTab === "my-publications") renderMyPublications();
        else renderLibrary();
        updateLibraryActivityStatus(options.force ? "PDF refreshed." : "PDF downloaded.", {delay: 2600});
      } catch (error) {
        const message = error.message || "download failed";
        updateLibraryActivityStatus(`PDF download failed: ${message}`, {delay: 4200});
        if (status) {
          status.textContent = message;
          status.className = "library-detail-status err";
        }
        buttons.forEach((button) => button.disabled = false);
      } finally {
        clearMyPublicationActivity(activityId);
      }
    }

    function closeLibraryQuickLook() {
      state.libraryQuickLookOpen = false;
      state.libraryQuickLookKind = "";
      state.libraryQuickLookRenderToken += 1;
      state.libraryQuickLookPath = "";
      state.libraryQuickLookUrl = "";
      state.reportQuickLookPaperId = "";
      state.libraryQuickLookPage = 1;
      state.libraryQuickLookPageCount = 0;
      state.libraryQuickLookPdfHasFocus = false;
      const overlay = $("libraryQuickLook");
      const pages = $("libraryQuickLookPages");
      if (overlay) {
        overlay.classList.remove("open", "compact");
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

    function defaultLibraryQuickLookCompactFrame() {
      const title = $("libraryQuickLookTitle");
      const current = $("libraryQuickLook")?.getBoundingClientRect();
      const base = state.libraryQuickLookFrameRect || (current?.width ? current : defaultLibraryQuickLookFrame());
      const width = Math.max(240, Math.min(340, Math.round(window.innerWidth * 0.24)));
      const titleHeight = Math.max(34, Math.round(title?.getBoundingClientRect().height || 42));
      const height = titleHeight + 54;
      return {
        left: Math.round(Math.max(12, Math.min(base.left, window.innerWidth - width - 12))),
        top: Math.round(Math.max(50, Math.min(base.top, window.innerHeight - height - 12))),
        width,
        height
      };
    }

    function applyLibraryQuickLookFrame(frameRect = null, options = {}) {
      const overlay = $("libraryQuickLook");
      if (!overlay) return;
      const rect = frameRect || state.libraryQuickLookFrameRect || defaultLibraryQuickLookFrame();
      const minWidth = options.compact ? 220 : 320;
      const minHeight = options.compact ? 74 : 300;
      const width = Math.max(minWidth, Math.min(rect.width, Math.max(2200, window.innerWidth * 1.8)));
      const height = Math.max(minHeight, Math.min(rect.height, Math.max(2000, window.innerHeight * 1.8)));
      const left = Math.max(80 - width, Math.min(rect.left, window.innerWidth - 80));
      const top = Math.max(36 - height, Math.min(rect.top, window.innerHeight - 36));
      if (options.persist !== false) state.libraryQuickLookFrameRect = {left, top, width, height};
      overlay.style.left = `${left}px`;
      overlay.style.top = `${top}px`;
      overlay.style.width = `${width}px`;
      overlay.style.height = `${height}px`;
    }

    function selectedLibraryQuickLookPlaceholder() {
      if (state.mode === "report") {
        const paper = selectedReportPaper();
        return {icon: "○", title: paper?.citation_label || paper?.title || "Paper", type: paper ? "No PDF" : "Journal Monitor"};
      }
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

    function showLibraryQuickLookPlaceholder(options = {}) {
      if (!state.libraryQuickLookOpen && !options.open) return;
      const overlay = $("libraryQuickLook");
      const title = $("libraryQuickLookTitle");
      const pages = $("libraryQuickLookPages");
      if (!overlay || !pages) return;
      const placeholder = selectedLibraryQuickLookPlaceholder();
      state.libraryQuickLookOpen = true;
      state.libraryQuickLookKind = "placeholder";
      state.libraryQuickLookRenderToken += 1;
      state.libraryQuickLookPath = "";
      state.libraryQuickLookUrl = "";
      state.libraryQuickLookPage = 1;
      state.libraryQuickLookPageCount = 0;
      state.libraryQuickLookPdfHasFocus = false;
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
      overlay.classList.add("open", "compact");
      overlay.setAttribute("aria-hidden", "false");
      applyLibraryQuickLookFrame(defaultLibraryQuickLookCompactFrame(), {compact: true, persist: false});
      reclaimLibraryQuickLookFocus();
    }

    function setLibraryQuickLookPage(page) {
      const nextPage = Math.max(1, Math.min(Number(page || 1), state.libraryQuickLookPageCount || Number(page || 1)));
      updateLibraryQuickLookActivePage(nextPage);
      updateLibraryPdfFramePage(nextPage);
      reclaimLibraryQuickLookFocus();
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
      wireLibraryQuickLookPdfFrame(root.querySelector(".library-pdf-frame"));
      root.scrollTop = 0;
      root.onscroll = null;
    }

    function wireLibraryQuickLookPdfFrame(frame) {
      if (!frame) return;
      const markPdfFocus = () => { state.libraryQuickLookPdfHasFocus = true; };
      frame.addEventListener("focus", markPdfFocus);
      frame.addEventListener("pointerdown", markPdfFocus);
      frame.addEventListener("mousedown", markPdfFocus);
      frame.addEventListener("load", () => {
        try {
          frame.contentWindow?.addEventListener("keydown", handleLibraryQuickLookPdfKeydown, true);
        } catch (error) {
          // Built-in PDF viewers may hide their document; top-level focus recovery still handles accessible focus.
        }
      });
    }

    function handleLibraryQuickLookPdfKeydown(event) {
      const key = event.key === "Spacebar" ? " " : event.key;
      if (key === " " && state.mode === "report") {
        event.preventDefault();
        event.stopPropagation();
        closeLibraryQuickLook();
        return;
      }
      if (key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      reclaimLibraryQuickLookFocus();
    }

    function reclaimLibraryQuickLookFocus() {
      state.libraryQuickLookPdfHasFocus = false;
      window.focus();
      $("libraryShell")?.focus({preventScroll: true});
    }

    function libraryQuickLookShouldReclaimFocus() {
      if (!state.libraryQuickLookOpen) return false;
      const active = document.activeElement;
      return Boolean(state.libraryQuickLookPdfHasFocus || active?.classList?.contains("library-pdf-frame"));
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
      if (options.toggle && state.libraryQuickLookOpen && state.libraryQuickLookKind === "pdf" && paper.merged_pdf_path === state.libraryQuickLookPath) {
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
      const isNewPdf = paper.merged_pdf_path !== state.libraryQuickLookPath || state.libraryQuickLookKind !== "pdf";
      state.libraryQuickLookOpen = true;
      state.libraryQuickLookKind = "pdf";
      state.libraryQuickLookRenderToken += 1;
      state.libraryQuickLookPath = paper.merged_pdf_path;
      state.libraryQuickLookUrl = pdfUrl;
      state.libraryQuickLookPdfHasFocus = false;
      if (isNewPdf) {
        state.libraryQuickLookPage = 1;
        state.libraryQuickLookPageCount = 0;
        renderLibraryQuickLookThumbs(0);
        renderLibraryQuickLookPages(0);
        loadLibraryQuickLookInfo(paper.merged_pdf_path);
      }
      if (title) title.textContent = paper.citation_label || paper.title || "PDF Preview";
      overlay.classList.remove("compact");
      overlay.classList.add("open");
      overlay.setAttribute("aria-hidden", "false");
      if (!state.libraryQuickLookManualFrame || !state.libraryQuickLookFrameRect) {
        applyLibraryQuickLookFrame(defaultLibraryQuickLookFrame());
      } else {
        applyLibraryQuickLookFrame();
      }
      reclaimLibraryQuickLookFocus();
      if (status && !options.silent) {
        status.textContent = "PDF preview open";
        status.className = "library-detail-status ok";
      }
    }

    function startLibraryQuickLookDrag(event) {
      const overlay = $("libraryQuickLook");
      if (!overlay || event.target.closest("button")) return;
      event.preventDefault();
      const isCompact = overlay.classList.contains("compact");
      if (!isCompact) state.libraryQuickLookManualFrame = true;
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
        }, isCompact ? {compact: true, persist: false} : {});
      };
      const stop = () => {
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", stop);
        reclaimLibraryQuickLookFocus();
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
        reclaimLibraryQuickLookFocus();
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", stop);
    }

    function refreshLibraryQuickLookForSelection() {
      if (!state.libraryQuickLookOpen) return;
      const paper = selectedLibraryPaper();
      if (!paper) {
        showLibraryQuickLookPlaceholder();
        return;
      }
      if (paper.merged_pdf_path) {
        if (state.libraryQuickLookKind === "pdf" && paper.merged_pdf_path === state.libraryQuickLookPath) return;
        quickLookLibraryPdf(paper, {silent: true});
        return;
      }
      const path = paperNativePath(paper);
      if (path && !libraryPaperIsPdfLike(paper)) {
        if (state.libraryQuickLookKind === "file" && path === state.libraryQuickLookPath) return;
        quickLookLibraryFile(paper, {silent: true});
        return;
      }
      showLibraryQuickLookPlaceholder();
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

    function libraryClipboardEntries() {
      const clipboard = state.libraryClipboard;
      if (!clipboard) return [];
      const entries = Array.isArray(clipboard.entries)
        ? clipboard.entries
        : (clipboard.type && clipboard.id ? [{type: clipboard.type, id: Number(clipboard.id)}] : []);
      return entries
        .map((entry) => ({type: entry.type, id: Number(entry.id)}))
        .filter((entry) => libraryEntryIsCopyable(entry.type, entry.id));
    }

    function pruneLibraryClipboard() {
      const entries = libraryClipboardEntries();
      if (!entries.length) {
        state.libraryClipboard = null;
      } else if (entries.length === 1) {
        state.libraryClipboard = entries[0];
      } else {
        state.libraryClipboard = {entries};
      }
    }

    function copyLibraryEntryToClipboard(type, id) {
      const explicitEntry = {type, id: Number(id)};
      const actionEntries = selectedLibraryEntriesForAction();
      const useActionSelection = actionEntries.length > 1
        && actionEntries.some((entry) => libraryEntryKey(entry) === libraryEntryKey(explicitEntry));
      const entries = (useActionSelection ? actionEntries : [explicitEntry])
        .filter((entry) => libraryEntryIsCopyable(entry.type, entry.id));
      if (!entries.length) return false;
      state.libraryClipboard = entries.length === 1 ? entries[0] : {entries};
      updateLibraryActivityStatus(`Copied ${entries.length} item${entries.length === 1 ? "" : "s"}.`, {live: false});
      return true;
    }

    function libraryEntriesWithPapers(entries) {
      return (entries || [])
        .filter((entry) => entry?.type === "item")
        .map((entry) => libraryItemById(entry.id))
        .filter((item) => item?.paper?.paper_id);
    }

    async function addLibraryEntriesToMyPublications(entries) {
      const items = libraryEntriesWithPapers(entries);
      const paperIds = [...new Set(items.map((item) => item.paper.paper_id).filter(Boolean))];
      if (!paperIds.length) return;
      updateLibraryActivityStatus(`Adding ${paperIds.length} item${paperIds.length === 1 ? "" : "s"} to My Publications...`, {live: true});
      const res = await fetch("/api/my-publications/add", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({paper_ids: paperIds})
      });
      const data = await res.json();
      if (!res.ok) {
        updateLibraryActivityStatus(data.error || "Could not add to My Publications.", {live: false});
        throw new Error(data.error || "Could not add to My Publications");
      }
      applyMyPublications(data);
      state.myPublicationSelectionId = Number(data.publication?.id || state.myPublicationSelectionId || 0);
      updateLibraryActivityStatus(`Added ${paperIds.length} item${paperIds.length === 1 ? "" : "s"} to My Publications.`, {live: false});
    }

    function libraryPasteTargetFolderId() {
      const selection = state.librarySelection;
      if (selection?.type === "folder") return Number(selection.id || state.libraryRootId);
      if (selection?.type === "item") return Number(libraryItemById(selection.id)?.folder_id || state.libraryActiveFolderId || state.libraryRootId);
      return Number(state.libraryActiveFolderId || state.libraryRootId);
    }

    function showMyPublicationContextMenu(event, publicationId) {
      event.preventDefault();
      event.stopPropagation();
      hideLibraryContextMenu();
      hideLibraryTabContextMenu();
      const publication = myPublicationById(publicationId);
      const menu = $("myPublicationContextMenu");
      if (!publication || !menu) return;
      if (!(state.myPublicationSelectedIds || new Set()).has(Number(publicationId))) {
        selectMyPublication(publicationId);
      }
      const selectedIds = selectedMyPublicationIdsForAction();
      const selectedPublications = selectedIds.map(myPublicationById).filter(Boolean);
      menu.dataset.publicationId = String(publicationId);
      menu.style.left = `${event.clientX}px`;
      menu.style.top = `${event.clientY}px`;
      menu.classList.add("open");
      menu.onclick = (clickEvent) => clickEvent.stopPropagation();
      const headButton = menu.querySelector('[data-action="toggle-my-publication-head"]');
      const deleteButton = menu.querySelector('[data-action="delete-my-publication"]');
      if (headButton) {
        const shouldHide = selectedPublications.some((item) => !item.head);
        headButton.textContent = selectedPublications.length > 1
          ? `${shouldHide ? "Hide" : "Show"} ${selectedPublications.length} selected`
          : (publication.head ? "Show" : "Hide");
        headButton.onclick = async () => {
          const ids = selectedMyPublicationIdsForAction();
          hideMyPublicationContextMenu();
          if (ids.length) await runLibraryMenuAction(() => toggleSelectedMyPublicationsHead(ids, shouldHide));
        };
      }
      if (deleteButton) {
        deleteButton.textContent = selectedPublications.length > 1 ? `Delete ${selectedPublications.length} selected` : "Delete";
        deleteButton.onclick = async () => {
          const ids = selectedMyPublicationIdsForAction();
          hideMyPublicationContextMenu();
          if (ids.length) await runLibraryMenuAction(() => deleteMyPublications(ids));
        };
      }
    }

    function hideMyPublicationContextMenu() {
      $("myPublicationContextMenu")?.classList.remove("open");
    }

    function showLibraryContextMenu(event, parentId, entryType = "", entryId = 0) {
      event.preventDefault();
      hideMyPublicationContextMenu();
      hideLibraryTabContextMenu();
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
      const selectedEntries = selectedLibraryEntriesForAction();
      const contextEntrySelected = hasEntry && selectedEntries.some((entry) => libraryEntryKey(entry) === libraryEntryKey({type: entryType, id: entryId}));
      const actionEntries = contextEntrySelected ? selectedEntries : (hasEntry ? [{type: entryType, id: Number(entryId)}] : []);
      const multiCount = actionEntries.length;
      const allActionEntriesCopyable = actionEntries.length && actionEntries.every((entry) => libraryEntryIsCopyable(entry.type, entry.id));
      const hasProtectedActionFolder = actionEntries.some((entry) => entry.type === "folder" && (libraryFolderById(entry.id)?.protected || Number(entry.id) === Number(state.libraryRootId)));
      const recycleId = libraryRecycleFolderId();
      const isRoot = entryType === "folder" && Number(entryId) === Number(state.libraryRootId);
      const isProtectedFolder = Boolean(folder?.protected || isRoot);
      const isRecoverable = (entryType === "item" && Number(item?.folder_id || 0) === recycleId)
        || (entryType === "folder" && Number(folder?.parent_id || 0) === recycleId);
      const renameButton = menu.querySelector('[data-action="rename-entry"]');
      const colorButton = menu.querySelector('[data-action="color-folder"]');
      const colorPicker = menu.querySelector('[data-action="folder-color-picker"]');
      const deleteButton = menu.querySelector('[data-action="delete-entry"]');
      const deleteFileButton = menu.querySelector('[data-action="delete-file-entry"]');
      const deleteSpecialOriginalFilesButton = menu.querySelector('[data-action="delete-special-original-files"]');
      const removeSpecialLibraryButton = menu.querySelector('[data-action="remove-special-library"]');
      const copyButton = menu.querySelector('[data-action="copy-entry"]');
      const addToMyPublicationsButton = menu.querySelector('[data-action="add-to-my-publications"]');
      const pasteButton = menu.querySelector('[data-action="paste-entry"]');
      const recoverButton = menu.querySelector('[data-action="recover-entry"]');
      const openNativeButton = menu.querySelector('[data-action="open-native-entry"]');
      const revealNativeButton = menu.querySelector('[data-action="reveal-native-entry"]');
      const isClearableSpecialFolder = entryType === "folder" && hasEntry && Boolean(folder?.is_unsorted || folder?.is_recycle);
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
        deleteButton.style.display = hasEntry && !hasProtectedActionFolder ? "" : "none";
        deleteButton.textContent = multiCount > 1
          ? `Remove ${multiCount} selected`
          : (entryType === "item" ? "Remove from current collection" : "Remove Folder");
        deleteButton.onclick = async () => {
          const type = menu.dataset.entryType;
          const id = Number(menu.dataset.entryId || 0);
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => {
            if (contextEntrySelected && selectedLibraryEntriesForAction().length > 1) return deleteSelectedLibraryEntries();
            if (type === "item") return removeLibraryItemFromCurrentCollection(id);
            return deleteLibraryEntry(type, id);
          });
        };
      }
      if (deleteFileButton) {
        const canDeleteFile = entryType === "item" && hasEntry && Boolean(libraryNativeItemPath(item));
        const canDeleteFolder = entryType === "folder" && hasEntry && !isProtectedFolder;
        deleteFileButton.textContent = entryType === "folder" ? "Delete Folder..." : "Delete File...";
        deleteFileButton.style.display = canDeleteFile || canDeleteFolder ? "" : "none";
        deleteFileButton.onclick = async () => {
          const type = menu.dataset.entryType;
          const id = Number(menu.dataset.entryId || 0);
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => deleteLibraryEntryFiles(type, id));
        };
      }
      if (deleteSpecialOriginalFilesButton) {
        deleteSpecialOriginalFilesButton.style.display = isClearableSpecialFolder ? "" : "none";
        deleteSpecialOriginalFilesButton.onclick = async () => {
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => clearLibrarySpecialFolder(Number(menu.dataset.entryId || 0), {deleteFiles: true}));
        };
      }
      if (removeSpecialLibraryButton) {
        removeSpecialLibraryButton.style.display = isClearableSpecialFolder ? "" : "none";
        removeSpecialLibraryButton.onclick = async () => {
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => clearLibrarySpecialFolder(Number(menu.dataset.entryId || 0), {deleteFiles: false}));
        };
      }
      if (copyButton) {
        copyButton.style.display = hasEntry && allActionEntriesCopyable ? "" : "none";
        copyButton.textContent = multiCount > 1 ? `Copy ${multiCount} selected` : "Copy";
        copyButton.onclick = () => {
          copyLibraryEntryToClipboard(menu.dataset.entryType, Number(menu.dataset.entryId || 0));
          hideLibraryContextMenu();
        };
      }
      if (addToMyPublicationsButton) {
        const publicationItems = libraryEntriesWithPapers(actionEntries);
        addToMyPublicationsButton.style.display = publicationItems.length ? "" : "none";
        addToMyPublicationsButton.textContent = publicationItems.length > 1
          ? `Add ${publicationItems.length} selected to My Publications`
          : "Add to My Publications";
        addToMyPublicationsButton.onclick = async () => {
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => addLibraryEntriesToMyPublications(actionEntries));
        };
      }
      if (recoverButton) {
        recoverButton.style.display = isRecoverable ? "" : "none";
        recoverButton.onclick = async () => {
          hideLibraryContextMenu();
          await runLibraryMenuAction(() => recoverLibraryEntry(menu.dataset.entryType, Number(menu.dataset.entryId || 0)));
        };
      }
      if (openNativeButton) {
        openNativeButton.style.display = hasEntry ? "" : "none";
        openNativeButton.onclick = async () => {
          const type = menu.dataset.entryType;
          const id = Number(menu.dataset.entryId || 0);
          hideLibraryContextMenu();
          await openNativeLibraryEntry(type, id);
        };
      }
      if (revealNativeButton) {
        revealNativeButton.style.display = hasEntry ? "" : "none";
        revealNativeButton.onclick = async () => {
          const type = menu.dataset.entryType;
          const id = Number(menu.dataset.entryId || 0);
          hideLibraryContextMenu();
          await revealNativeLibraryEntry(type, id);
        };
      }
      if (pasteButton) {
        const pasteCount = libraryClipboardEntries().length;
        pasteButton.style.display = pasteCount ? "" : "none";
        pasteButton.textContent = pasteCount > 1 ? `Paste ${pasteCount} items` : "Paste";
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

    function showLibraryTabContextMenu(event, tabType, index) {
      hideLibraryContextMenu();
      hideMyPublicationContextMenu();
      const menu = $("libraryTabContextMenu");
      if (!menu) return;
      menu.dataset.tabType = tabType;
      menu.dataset.tabIndex = String(index);
      menu.style.left = `${event.clientX}px`;
      menu.style.top = `${event.clientY}px`;
      menu.classList.add("open");
      menu.onclick = (clickEvent) => clickEvent.stopPropagation();
      const renameButton = menu.querySelector('[data-action="rename-tab"]');
      if (renameButton) {
        renameButton.onclick = async () => {
          const type = menu.dataset.tabType || "";
          const tabIndex = Number(menu.dataset.tabIndex || 0);
          hideLibraryTabContextMenu();
          if (type === "shortcut") await runLibraryMenuAction(() => renameLibraryShortcutTab(tabIndex));
          if (type === "workspace") await runLibraryMenuAction(() => renameLibraryWorkspaceFromTab(tabIndex));
        };
      }
    }

    function hideLibraryTabContextMenu() {
      $("libraryTabContextMenu")?.classList.remove("open");
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
        const handled = ["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", " ", "Delete", "Backspace"].includes(key);
        if (!handled) return false;
        event.preventDefault();
        return handleMyPublicationKeydown(event, key);
      }
      if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && key.toLowerCase() === "c") {
        const selection = state.librarySelection;
        if (copyLibraryEntryToClipboard(selection?.type, Number(selection?.id || 0))) {
          event.preventDefault();
          return true;
        }
        return false;
      }
      if ((event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && key.toLowerCase() === "v") {
        if (!libraryClipboardEntries().length) return false;
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
        else quickLookLibraryFile(paper, {toggle: true, openPlaceholder: true});
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
        selectLibrarySearchEntry(next.parentFolderId, next.type, next.id);
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
        refreshLibraryQuickLookForSelection();
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
      const selected = paper.paper_id && paper.paper_id === state.reportSelectedPaperId;
      article.className = `paper${reserveFigure ? " with-figure" : ""}${paper.late_arrival_unread ? " late-unread" : ""}${selected ? " report-selected" : ""}`;
      article.dataset.paperId = paper.paper_id;
      article.tabIndex = -1;
      article.setAttribute("role", "option");
      article.setAttribute("aria-selected", selected ? "true" : "false");
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
              ${paper.url ? `<button class="action" data-action="open-page" title="Open publisher page in Safari">↗ Open</button>` : ""}
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
      if (openPageButton) openPageButton.addEventListener("click", () => openUrlExternally(paper.url));
      article.addEventListener("click", () => selectReportPaper(paper.paper_id));
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

    function markVisibleLateArrivalsSeen(papers) {
      const ids = (papers || [])
        .filter((paper) => paper?.late_arrival_unread && !state.markingLateArrivalIds.has(paper.paper_id))
        .map((paper) => paper.paper_id);
      if (!ids.length) return;
      ids.forEach((paperId) => state.markingLateArrivalIds.add(paperId));
      window.setTimeout(async () => {
        try {
          const res = await fetch("/api/papers/late-arrivals/seen", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({paper_ids: ids})
          });
          if (!res.ok) return;
          updateLateArrivalSeenState(ids);
          renderReportTabs(groupedReportPapers(reportVisiblePapers()));
          document.querySelectorAll(".paper.late-unread").forEach((article) => {
            if (ids.includes(article.dataset.paperId)) article.classList.remove("late-unread");
          });
        } finally {
          ids.forEach((paperId) => state.markingLateArrivalIds.delete(paperId));
        }
      }, 1400);
    }

    function updateLateArrivalSeenState(paperIds) {
      const seenIds = new Set(paperIds || []);
      state.papers.forEach((paper) => {
        if (seenIds.has(paper.paper_id)) paper.late_arrival_unread = false;
      });
      state.lateArrivals = (state.lateArrivals || [])
        .map((item) => {
          const remainingIds = (item.paper_ids || []).filter((paperId) => !seenIds.has(paperId));
          return {...item, paper_ids: remainingIds, count: remainingIds.length};
        })
        .filter((item) => Number(item.count || 0) > 0);
      Object.values(state.reportCache || {}).forEach((cached) => {
        (cached?.papers || []).forEach((paper) => {
          if (seenIds.has(paper.paper_id)) paper.late_arrival_unread = false;
        });
        if (Array.isArray(cached?.lateArrivals)) {
          cached.lateArrivals = cached.lateArrivals
            .map((item) => {
              const remainingIds = (item.paper_ids || []).filter((paperId) => !seenIds.has(paperId));
              return {...item, paper_ids: remainingIds, count: remainingIds.length};
            })
            .filter((item) => Number(item.count || 0) > 0);
        }
      });
    }

    function reportVisiblePapers() {
      const query = state.query.trim().toLowerCase();
      return state.papers.filter((paper) => {
        const inJournal = state.selectedJournals.has(paper.journal);
        const haystack = `${paper.title} ${paper.abstract} ${paper.doi} ${paper.preprint_id || ""} ${paper.preprint_category || ""} ${paper.journal} ${(paper.authors || []).join(" ")}`.toLowerCase();
        return inJournal && preprintCategoryMatches(paper) && subjectMatches(paper) && (!query || haystack.includes(query));
      });
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
      await openUrlExternally(state.internalBrowserUrl);
    }

    async function openUrlExternally(url) {
      if (!url) return;
      return fetch("/api/open-url", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({url, app: "Safari"})
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
        const res = await openUrlExternally(url);
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
      const isCommentsReport = /^#\s+Citation Comments Report\b/.test(String(content || "").trim());
      $("analysisMeta").innerHTML = `
        <strong>${escapeHtml(paper?.title || "Analysis")}</strong><br>
        ${escapeHtml(paper?.journal || "")} ${escapeHtml(paper?.publication_date || "")}
      `;
      $("analysisBody").innerHTML = markdownToHtml(content || "The analysis file is empty.");
      $("analysisBody").classList.toggle("comments-report", isCommentsReport);
      wireAnalysisLinks();
      $("analysisBackdrop").classList.add("open");
      $("workspace").classList.add("note-open");
      $("workspace").style.setProperty("--note-width", `${state.noteWidth}px`);
      $("analysisPanel").classList.add("open");
      $("analysisPanel").setAttribute("aria-hidden", "false");
      updateReportPanelToggle();
    }

    function wireAnalysisLinks() {
      $("analysisBody")?.querySelectorAll('a[data-open-external="safari"]').forEach((link) => {
        link.addEventListener("click", async (event) => {
          event.preventDefault();
          const url = link.getAttribute("href") || "";
          if (!url) return;
          await fetch("/api/open-url", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({url, app: "Safari"})
          });
        });
      });
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
        } else if (/^\*\*\d+\.\s+.+\*\*$/.test(line)) {
          closeList();
          output.push(`<h4>${inlineMarkdown(line.slice(2, -2))}</h4>`);
        } else if (line.startsWith("- ")) {
          if (!inList) {
            output.push("<ul>");
            inList = true;
          }
          output.push(`<li>${inlineMarkdown(line.slice(2))}</li>`);
        } else if (line.startsWith("> ")) {
          closeList();
          output.push(citationContextHtml(line.slice(2)));
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
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, `<a href="$2" data-open-external="safari">$1</a>`)
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");
    }

    function citationContextHtml(value) {
      const match = String(value || "").match(/^\[([^\]]+)\]\s*(.*)$/);
      const label = match ? match[1].trim() : "context";
      const text = match ? match[2].trim() : String(value || "");
      const slug = label.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "context";
      return `<blockquote class="citation-context context-${escapeAttr(slug)}"><strong>${escapeHtml(label)}</strong>${inlineMarkdown(text)}</blockquote>`;
    }

    async function openCitationSettings() {
      const backdrop = $("citationSettingsBackdrop");
      if (!backdrop) return;
      backdrop.classList.add("open");
      backdrop.setAttribute("aria-hidden", "false");
      $("citationSettingsStatus").textContent = "Loading citation settings...";
      $("citationSettingsStatus").className = "citation-settings-status";
      $("adsTokenInput").value = "";
      try {
        const res = await fetch("/api/settings/citation");
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not load citation settings");
        updateCitationSettingsUi(data.ads || {});
        $("citationSettingsStatus").textContent = data.ads?.configured ? "ADS token is saved locally." : "ADS is optional and currently disabled.";
        $("citationSettingsStatus").className = `citation-settings-status${data.ads?.configured ? " ok" : ""}`;
      } catch (error) {
        $("citationSettingsStatus").textContent = error.message || "Could not load citation settings";
        $("citationSettingsStatus").className = "citation-settings-status err";
      }
      $("adsTokenInput")?.focus({preventScroll: true});
    }

    function closeCitationSettings() {
      $("citationSettingsBackdrop")?.classList.remove("open");
      $("citationSettingsBackdrop")?.setAttribute("aria-hidden", "true");
      $("adsTokenInput").value = "";
    }

    function updateCitationSettingsUi(ads) {
      const configured = Boolean(ads?.configured);
      $("adsConfiguredLabel").textContent = configured ? "Configured" : "Not configured";
    }

    async function saveCitationAdsToken({test = false} = {}) {
      const token = $("adsTokenInput")?.value || "";
      if (!token.trim()) {
        $("citationSettingsStatus").textContent = "Paste an ADS token before saving.";
        $("citationSettingsStatus").className = "citation-settings-status err";
        return;
      }
      $("citationSettingsStatus").textContent = test ? "Saving and testing ADS token..." : "Saving ADS token locally...";
      $("citationSettingsStatus").className = "citation-settings-status";
      try {
        const res = await fetch("/api/settings/citation", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({ads_token: token, test})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not save ADS token");
        updateCitationSettingsUi(data.ads || {});
        $("adsTokenInput").value = "";
        const ok = data.ads?.ok;
        $("citationSettingsStatus").textContent = ok === false ? "ADS token saved, but the connection test failed." : (ok === true ? "ADS token saved and connected." : "ADS token saved locally.");
        $("citationSettingsStatus").className = `citation-settings-status${ok === false ? " err" : " ok"}`;
      } catch (error) {
        $("citationSettingsStatus").textContent = error.message || "Could not save ADS token";
        $("citationSettingsStatus").className = "citation-settings-status err";
      }
    }

    async function testCitationAdsToken() {
      const token = $("adsTokenInput")?.value || "";
      $("citationSettingsStatus").textContent = "Testing ADS connection...";
      $("citationSettingsStatus").className = "citation-settings-status";
      try {
        const res = await fetch("/api/settings/citation", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({action: "test", ads_token: token})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not test ADS token");
        updateCitationSettingsUi(data.ads || {});
        $("citationSettingsStatus").textContent = data.ads?.ok ? "ADS connection works." : "ADS token is missing or invalid.";
        $("citationSettingsStatus").className = `citation-settings-status${data.ads?.ok ? " ok" : " err"}`;
      } catch (error) {
        $("citationSettingsStatus").textContent = error.message || "Could not test ADS token";
        $("citationSettingsStatus").className = "citation-settings-status err";
      }
    }

    async function clearCitationAdsToken() {
      $("citationSettingsStatus").textContent = "Clearing ADS token...";
      $("citationSettingsStatus").className = "citation-settings-status";
      try {
        const res = await fetch("/api/settings/citation", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({action: "clear"})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not clear ADS token");
        updateCitationSettingsUi(data.ads || {});
        $("adsTokenInput").value = "";
        $("citationSettingsStatus").textContent = "ADS token cleared. ADS is disabled.";
        $("citationSettingsStatus").className = "citation-settings-status";
      } catch (error) {
        $("citationSettingsStatus").textContent = error.message || "Could not clear ADS token";
        $("citationSettingsStatus").className = "citation-settings-status err";
      }
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
      setSidebarCollapsed(false);
      await loadMonth();
      await loadReport({showLoading: false});
    }

    async function openDeepSurvey() {
      state.mode = "deep-survey";
      closeLibraryQuickLook();
      closeAnalysis();
      stopArxivUpdateCountdown();
      clearFetchProgressDisplay();
      setPrimaryView("deep-survey");
      $("summary").textContent = "";
      $("reportTabs").classList.remove("open");
      $("reportTabs").innerHTML = "";
      $("libraryControls").classList.remove("open");
      const root = $("papers");
      const host = $("deepSurveyHost");
      root.classList.remove("library-view", "deep-survey-view");
      root.style.height = "";
      root.style.minHeight = "";
      if (!host) return;
      host.setAttribute("aria-hidden", "false");
      if (!state.deepSurveyLoadingPromise) {
        const existingFrame = host.querySelector(".deep-survey-frame");
        if (!existingFrame) {
          host.innerHTML = `<div class="deep-survey-loading">Starting Deep Survey...</div>`;
        }
        state.deepSurveyLoadingPromise = (async () => {
          try {
            const data = await fetchJson("/api/deep-survey/status");
            if (!data.ok || !data.url) throw new Error(data.error || "Deep Survey could not start");
            if (existingFrame && state.deepSurveyUrl === data.url && existingFrame.getAttribute("src") === data.url) {
              return;
            }
            state.deepSurveyUrl = data.url;
            host.innerHTML = `<iframe class="deep-survey-frame" title="Deep Survey" src="${escapeAttr(data.url)}"></iframe>`;
          } catch (error) {
            state.deepSurveyUrl = "";
            host.innerHTML = `<div class="empty">${escapeHtml(error.message || "Deep Survey could not start")}</div>`;
          } finally {
            state.deepSurveyLoadingPromise = null;
          }
        })();
      }
      await state.deepSurveyLoadingPromise;
    }

    function setPrimaryView(view) {
      const isLibrarySurface = view === "library" || view === "my-publications" || view === "deep-survey";
      document.querySelector(".app")?.classList.toggle("library-mode", isLibrarySurface);
      document.querySelector(".app")?.classList.toggle("deep-survey-mode", view === "deep-survey");
      $("libraryMode")?.classList.toggle("active", view === "library");
      $("myPublicationsMode")?.classList.toggle("active", view === "my-publications");
      $("reportMode")?.classList.toggle("active", view === "report");
      $("deepSurveyMode")?.classList.toggle("active", view === "deep-survey");
      $("sideLibraryMode")?.classList.toggle("active", view === "library" || view === "my-publications");
      $("sideReportMode")?.classList.toggle("active", view === "report");
      $("sideDeepSurveyMode")?.classList.toggle("active", view === "deep-survey");
      $("deepSurveyHost")?.setAttribute("aria-hidden", view === "deep-survey" ? "false" : "true");
      $("primaryViewSwitcher")?.classList.remove("hidden");
      $("sidebarViewSwitcher")?.classList.remove("open");
      $("reportToolbarActions")?.classList.toggle("hidden", view !== "report");
      updateLibrarySearchTools();
      updateReportRefreshButton();
    }

    function wireWindowDragRegion() {
      const region = $("windowDragRegion");
      const handler = window.webkit?.messageHandlers?.windowDrag;
      if (!region || !handler) return;
      let dragging = false;
      const post = (type, event) => {
        handler.postMessage({type, screenX: event.screenX, screenY: event.screenY});
      };
      region.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        dragging = true;
        region.setPointerCapture?.(event.pointerId);
        post("begin", event);
        event.preventDefault();
      });
      region.addEventListener("pointermove", (event) => {
        if (!dragging) return;
        post("move", event);
        event.preventDefault();
      });
      const stop = (event) => {
        if (!dragging) return;
        dragging = false;
        post("end", event);
        region.releasePointerCapture?.(event.pointerId);
      };
      region.addEventListener("pointerup", stop);
      region.addEventListener("pointercancel", stop);
    }

    $("reportMode").addEventListener("click", () => openJournalMonitor().catch((error) => {
      $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    }));
    $("libraryMode").addEventListener("click", loadLibrary);
    $("myPublicationsMode").addEventListener("click", () => {
      loadMyPublications().catch((error) => {
        $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      });
    });
    $("deepSurveyMode").addEventListener("click", () => openDeepSurvey());
    $("sideReportMode").addEventListener("click", () => openJournalMonitor().catch((error) => {
      $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
    }));
    $("sideLibraryMode").addEventListener("click", loadLibrary);
    $("sideDeepSurveyMode").addEventListener("click", () => openDeepSurvey());
    wireLibraryImportTools();
    $("addMyPublication").addEventListener("click", () => searchMyPublications("auto"));
    $("findMyPublications").addEventListener("click", () => searchMyPublications("author"));
    $("refreshMyPublicationMetrics").addEventListener("click", () => refreshMyPublicationMetrics());
    $("exportPublicationList").addEventListener("click", (event) => {
      event.stopPropagation();
      togglePublicationExportMenu();
    });
    $("publicationExportOptions").querySelectorAll('[data-action="export-publications"]').forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        exportPublicationList(button.dataset.exportFormat || "docx");
      });
    });
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
    $("refreshReport").addEventListener("click", refreshCurrentReportDate);
    $("searchBox").addEventListener("input", (event) => {
      state.query = event.target.value;
      state.noMatchDates = new Set();
      if (state.mode === "library") renderActiveLibraryTab();
      else renderReport();
    });
    $("librarySearchBox").addEventListener("input", (event) => {
      scheduleLibrarySearch(event.target.value);
    });
    $("librarySearchBox").addEventListener("keydown", (event) => {
      if (event.key === "Enter") commitLibrarySearch(event.target.value);
    });
    $("clearLibrarySearch").addEventListener("click", () => {
      window.clearTimeout(librarySearchTimer);
      state.query = "";
      $("librarySearchBox").value = "";
      clearLibraryRangeSelection();
      renderActiveLibraryTab();
      $("librarySearchBox")?.focus({preventScroll: true});
    });
    $("closeAnalysis").addEventListener("click", closeAnalysis);
    $("analysisBackdrop").addEventListener("click", closeAnalysis);
    $("closeCitationSettings").addEventListener("click", closeCitationSettings);
    $("citationSettingsBackdrop").addEventListener("click", (event) => {
      if (event.target === $("citationSettingsBackdrop")) closeCitationSettings();
    });
    $("closeLibraryLoader").addEventListener("click", closeLibraryLoader);
    $("saveAdsToken").addEventListener("click", () => saveCitationAdsToken());
    $("testAdsToken").addEventListener("click", testCitationAdsToken);
    $("clearAdsToken").addEventListener("click", clearCitationAdsToken);
    $("adsTokenInput").addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        saveCitationAdsToken({test: true});
      }
    });
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
      if (handleReportKeydown(event)) return;
      if (event.key !== "Escape") return;
      closePublicationAuthorMenu();
      closePublicationExportMenu();
      closeAuthorAffiliationTooltip();
      if ($("citationSettingsBackdrop").classList.contains("open")) {
        event.preventDefault();
        event.stopPropagation();
        closeCitationSettings();
        return;
      }
      if ($("libraryLoaderBackdrop").classList.contains("open")) {
        event.preventDefault();
        event.stopPropagation();
        closeLibraryLoader();
        return;
      }
      if (state.libraryQuickLookOpen) {
        event.preventDefault();
        event.stopPropagation();
        if (libraryQuickLookShouldReclaimFocus()) {
          reclaimLibraryQuickLookFocus();
          return;
        }
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
      hideLibraryTabContextMenu();
      hideMyPublicationContextMenu();
      closeAnalysis();
    }, true);
    window.addEventListener("click", (event) => {
      if (event.target.closest?.('[data-action="open-scholar-profile"]')) {
        event.preventDefault();
        event.stopPropagation();
        openMyPublicationScholarProfile();
        return;
      }
      if (event.target.closest?.('[data-action="clear-scholar-profile"]')) {
        event.preventDefault();
        event.stopPropagation();
        clearMyPublicationScholarProfile();
        return;
      }
      hideLibraryContextMenu();
      hideLibraryTabContextMenu();
      hideMyPublicationContextMenu();
      closeAuthorAffiliationTooltip();
      if (!event.target.closest?.(".publication-author-menu, .publication-author-pill")) closePublicationAuthorMenu();
      if (!event.target.closest?.(".publication-export-menu")) closePublicationExportMenu();
      if (
        state.libraryTab === "my-publications"
        && state.myPublicationSearchResults.length
        && !event.target.closest(".my-publications-search")
        && !event.target.closest(".my-publications-tools")
      ) {
        closeMyPublicationSearchResults();
      }
    });
    window.addEventListener("resize", () => {
      if (state.mode === "library") resizeLibraryViewport();
      if (state.mode === "report") {
        revealActiveReportTab();
        updateReportTabsOverflow();
      }
      closeAuthorAffiliationTooltip();
    });
    window.addEventListener("scroll", closeAuthorAffiliationTooltip, true);
    document.addEventListener("pointerover", (event) => {
      const anchor = event.target.closest?.(".author-affiliation-hover");
      if (anchor) showAuthorAffiliationTooltip(anchor);
    });
    document.addEventListener("pointerout", (event) => {
      const anchor = event.target.closest?.(".author-affiliation-hover");
      const tooltip = event.target.closest?.("#authorAffiliationTooltip");
      if (anchor && (anchor.contains(event.relatedTarget) || event.relatedTarget?.closest?.("#authorAffiliationTooltip"))) return;
      if (tooltip && event.relatedTarget?.closest?.(".author-affiliation-hover, #authorAffiliationTooltip")) return;
      if (!anchor && !tooltip) return;
      closeAuthorAffiliationTooltip();
    });
    document.addEventListener("focusin", (event) => {
      const anchor = event.target.closest?.(".author-affiliation-hover");
      if (anchor) showAuthorAffiliationTooltip(anchor);
    });
    document.addEventListener("focusout", (event) => {
      const anchor = event.target.closest?.(".author-affiliation-hover");
      if (!anchor || anchor.contains(event.relatedTarget)) return;
      closeAuthorAffiliationTooltip();
    });
    window.addEventListener("dragover", (event) => {
      if (!event.dataTransfer?.types?.includes("Files")) return;
      event.preventDefault();
      if (state.mode === "library") $("libraryShell")?.classList.add("finder-drag-over");
    });
    window.addEventListener("dragleave", (event) => {
      if (event.clientX <= 0 || event.clientY <= 0 || event.clientX >= window.innerWidth || event.clientY >= window.innerHeight) {
        $("libraryShell")?.classList.remove("finder-drag-over");
      }
    });
    window.addEventListener("drop", (event) => {
      if (!event.dataTransfer?.types?.includes("Files")) return;
      event.preventDefault();
      $("libraryShell")?.classList.remove("finder-drag-over");
    });
    wireWindowDragRegion();
    document.addEventListener("daiqo-open-library-loader", openLibraryLoader);
    window.handleNativeFinderDrop = handleNativeFinderDrop;
    window.openCitationSettings = openCitationSettings;
    window.openLibraryLoader = openLibraryLoader;

    if (IS_STANDALONE_LOADER_WINDOW) {
      document.body.classList.add("loader-window-body");
      document.querySelector(".app")?.classList.add("loader-window-mode");
      state.libraryLoaderOpen = true;
      renderLibraryLoader();
    } else {
      Promise.resolve().then(loadLibrary).catch((error) => {
        $("papers").innerHTML = `<div class="empty">${escapeHtml(error.message)}</div>`;
      });
      window.setTimeout(() => {
        fetch("/api/arxiv-daily-refresh").catch(() => {});
      }, 1600);
      updateSidebarToggle();
      updateReportPanelToggle();
    }
  </script>
</body>
</html>
"""
