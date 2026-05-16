from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .config import DEFAULT_DB_PATH
from .time_utils import now_iso


SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS papers (
  paper_id TEXT PRIMARY KEY,
  doi TEXT,
  title TEXT NOT NULL,
  journal TEXT NOT NULL,
  publication_date TEXT,
  abstract TEXT,
  abstract_source TEXT,
  url TEXT,
  landing_url TEXT,
  pdf_url TEXT,
  source TEXT,
  source_count INTEGER NOT NULL DEFAULT 1,
  type TEXT,
  type_crossref TEXT,
  publisher_section TEXT,
  section_allowed INTEGER,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  raw_json TEXT,
  download_status TEXT NOT NULL DEFAULT 'not_attempted',
  download_message TEXT,
  main_pdf_path TEXT,
  supplement_pdf_paths TEXT,
  merged_pdf_path TEXT,
  downloaded_at TEXT,
  analysis_status TEXT NOT NULL DEFAULT 'not_started',
  analysis_path TEXT,
  analyzed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_journal_date ON papers(journal, publication_date);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_download_status ON papers(download_status);

CREATE TABLE IF NOT EXISTS fetch_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  monitor_type TEXT NOT NULL,
  source TEXT NOT NULL,
  journal TEXT,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  status TEXT NOT NULL,
  records_found INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def upsert_paper(self, paper: dict[str, Any]) -> None:
        existing = self.get_paper(paper["paper_id"])
        timestamp = now_iso()
        payload = dict(paper)
        payload.setdefault("first_seen_at", timestamp)
        payload["last_seen_at"] = timestamp
        payload["raw_json"] = json.dumps(payload.get("raw") or {}, ensure_ascii=False)
        payload["section_allowed"] = _bool_to_int(payload.get("section_allowed"))

        if existing:
            merged = dict(existing)
            for key in [
                "doi",
                "title",
                "journal",
                "publication_date",
                "abstract",
                "abstract_source",
                "url",
                "landing_url",
                "pdf_url",
                "source",
                "type",
                "type_crossref",
                "publisher_section",
                "section_allowed",
                "raw_json",
            ]:
                value = payload.get(key)
                if key == "section_allowed" and value is not None:
                    merged[key] = value
                    continue
                if value not in (None, "") and _is_blank_existing(key, merged.get(key)):
                    merged[key] = value
            merged["source_count"] = int(existing["source_count"] or 1) + 1
            merged["last_seen_at"] = timestamp
            self._update_paper(merged)
            return

        columns = [
            "paper_id",
            "doi",
            "title",
            "journal",
            "publication_date",
            "abstract",
            "abstract_source",
            "url",
            "landing_url",
            "pdf_url",
            "source",
            "type",
            "type_crossref",
            "publisher_section",
            "section_allowed",
            "first_seen_at",
            "last_seen_at",
            "raw_json",
        ]
        values = [payload.get(column) for column in columns]
        placeholders = ", ".join(["?"] * len(columns))
        self.conn.execute(
            f"INSERT INTO papers ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
        self.conn.commit()

    def _update_paper(self, paper: dict[str, Any]) -> None:
        columns = [
            "doi",
            "title",
            "journal",
            "publication_date",
            "abstract",
            "abstract_source",
            "url",
            "landing_url",
            "pdf_url",
            "source",
            "source_count",
            "type",
            "type_crossref",
            "publisher_section",
            "section_allowed",
            "last_seen_at",
            "raw_json",
        ]
        assignments = ", ".join([f"{column} = ?" for column in columns])
        values = [paper.get(column) for column in columns]
        values.append(paper["paper_id"])
        self.conn.execute(f"UPDATE papers SET {assignments} WHERE paper_id = ?", values)
        self.conn.commit()

    def record_fetch_run(
        self,
        *,
        monitor_type: str,
        source: str,
        journal: str | None,
        window_start: str,
        window_end: str,
        status: str,
        records_found: int,
        started_at: str,
        message: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO fetch_runs (
              monitor_type, source, journal, window_start, window_end, status,
              records_found, message, started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                monitor_type,
                source,
                journal,
                window_start,
                window_end,
                status,
                records_found,
                message,
                started_at,
                now_iso(),
            ),
        )
        self.conn.commit()

    def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM papers WHERE paper_id = ?", (paper_id,)).fetchone()
        return dict(row) if row else None

    def list_papers(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        journals: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = []
        params: list[Any] = []
        if start_date:
            clauses.append("publication_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("publication_date <= ?")
            params.append(end_date)
        journal_list = list(journals or [])
        if journal_list:
            placeholders = ", ".join(["?"] * len(journal_list))
            clauses.append(f"journal IN ({placeholders})")
            params.extend(journal_list)

        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT * FROM papers
            {where}
            ORDER BY publication_date DESC, journal ASC, title ASC
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def update_download_status(
        self,
        paper_id: str,
        *,
        status: str,
        message: str = "",
        main_pdf_path: str | None = None,
        supplement_pdf_paths: list[str] | None = None,
        merged_pdf_path: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE papers
            SET download_status = ?,
                download_message = ?,
                main_pdf_path = COALESCE(?, main_pdf_path),
                supplement_pdf_paths = COALESCE(?, supplement_pdf_paths),
                merged_pdf_path = COALESCE(?, merged_pdf_path),
                downloaded_at = ?
            WHERE paper_id = ?
            """,
            (
                status,
                message,
                main_pdf_path,
                json.dumps(supplement_pdf_paths, ensure_ascii=False) if supplement_pdf_paths is not None else None,
                merged_pdf_path,
                now_iso(),
                paper_id,
            ),
        )
        self.conn.commit()

    def update_analysis_status(self, paper_id: str, *, status: str, path: str | None, message: str = "") -> None:
        self.conn.execute(
            """
            UPDATE papers
            SET analysis_status = ?,
                analysis_path = COALESCE(?, analysis_path),
                analyzed_at = ?
            WHERE paper_id = ?
            """,
            (status if not message else f"{status}: {message}", path, now_iso(), paper_id),
        )
        self.conn.commit()

    def queue_analysis(self, paper_id: str, *, analysis_path: str, message: str = "") -> None:
        status = "queued_for_codex" if not message else f"queued_for_codex: {message}"
        self.conn.execute(
            """
            UPDATE papers
            SET analysis_status = ?,
                analysis_path = ?,
                analyzed_at = ?
            WHERE paper_id = ?
            """,
            (status, analysis_path, now_iso(), paper_id),
        )
        self.conn.commit()

    def clear_download_status(self, paper_id: str) -> None:
        self.conn.execute(
            """
            UPDATE papers
            SET download_status = 'not_attempted',
                download_message = '',
                main_pdf_path = NULL,
                supplement_pdf_paths = NULL,
                merged_pdf_path = NULL,
                downloaded_at = NULL
            WHERE paper_id = ?
            """,
            (paper_id,),
        )
        self.conn.commit()

    def clear_analysis_status(self, paper_id: str) -> None:
        self.conn.execute(
            """
            UPDATE papers
            SET analysis_status = 'not_started',
                analysis_path = NULL,
                analyzed_at = NULL
            WHERE paper_id = ?
            """,
            (paper_id,),
        )
        self.conn.commit()

    def update_section_status(
        self,
        paper_id: str,
        *,
        publisher_section: str,
        section_allowed: bool | None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE papers
            SET publisher_section = ?,
                section_allowed = ?
            WHERE paper_id = ?
            """,
            (publisher_section, _bool_to_int(section_allowed), paper_id),
        )
        self.conn.commit()


def _bool_to_int(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if bool(value) else 0


def _is_blank_existing(key: str, value: Any) -> bool:
    if value in (None, ""):
        return True
    if key == "title" and re.search(r"</?[A-Za-z][^>]*>", str(value)):
        return True
    if key == "abstract_source" and value in {"missing", "unavailable"}:
        return True
    if key == "publisher_section" and value in {"unknown", "non-research"}:
        return True
    return False
