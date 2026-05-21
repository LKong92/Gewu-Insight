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
  image_url TEXT,
  download_status TEXT NOT NULL DEFAULT 'not_attempted',
  download_message TEXT,
  main_pdf_path TEXT,
  supplement_pdf_paths TEXT,
  merged_pdf_path TEXT,
  downloaded_at TEXT,
  source_path TEXT,
  original_relative_path TEXT,
  original_parent_relative_path TEXT,
  original_filename TEXT,
  import_batch_id TEXT,
  import_kind TEXT,
  import_as TEXT,
  doi_source TEXT,
  parse_status TEXT,
  parse_error TEXT,
  size_bytes INTEGER,
  modified_at TEXT,
  page_count INTEGER,
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

CREATE TABLE IF NOT EXISTS library_folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  parent_id INTEGER REFERENCES library_folders(id) ON DELETE CASCADE,
  color TEXT,
  original_parent_id INTEGER,
  trashed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_library_folders_parent ON library_folders(parent_id, sort_order, name);

CREATE TABLE IF NOT EXISTS library_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  folder_id INTEGER NOT NULL REFERENCES library_folders(id) ON DELETE CASCADE,
  paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
  display_name TEXT,
  original_folder_id INTEGER,
  trashed_at TEXT,
  created_at TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(folder_id, paper_id)
);

CREATE INDEX IF NOT EXISTS idx_library_items_folder ON library_items(folder_id, sort_order, id);
CREATE INDEX IF NOT EXISTS idx_library_items_paper ON library_items(paper_id);

CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS my_publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
  starred INTEGER NOT NULL DEFAULT 0,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(paper_id)
);

CREATE INDEX IF NOT EXISTS idx_my_publications_starred ON my_publications(starred, sort_order, id);

CREATE TABLE IF NOT EXISTS inventory_import_batches (
  id TEXT PRIMARY KEY,
  inventory_path TEXT NOT NULL,
  source_root TEXT,
  copy_mode TEXT NOT NULL,
  preserve_folders INTEGER NOT NULL DEFAULT 0,
  dedupe_by TEXT,
  dry_run INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  report_path TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  created_papers INTEGER NOT NULL DEFAULT 0,
  updated_papers INTEGER NOT NULL DEFAULT 0,
  created_resources INTEGER NOT NULL DEFAULT 0,
  skipped INTEGER NOT NULL DEFAULT 0,
  errors_json TEXT,
  warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  paper_id TEXT REFERENCES papers(paper_id) ON DELETE CASCADE,
  source_path TEXT,
  stored_path TEXT,
  original_relative_path TEXT,
  original_parent_relative_path TEXT,
  original_filename TEXT,
  kind TEXT,
  mime_type TEXT,
  import_as TEXT,
  import_batch_id TEXT,
  size_bytes INTEGER,
  modified_at TEXT,
  parse_status TEXT,
  parse_error TEXT,
  page_count INTEGER,
  status TEXT NOT NULL DEFAULT 'imported',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source_path, size_bytes, kind)
);

CREATE INDEX IF NOT EXISTS idx_resources_paper ON resources(paper_id);
CREATE INDEX IF NOT EXISTS idx_resources_batch ON resources(import_batch_id);
CREATE INDEX IF NOT EXISTS idx_resources_source ON resources(source_path, size_bytes);
"""


class Storage:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=15000")
        self.conn.executescript(SCHEMA)
        self._ensure_schema_columns()
        self._ensure_library_root()
        self._seed_library_from_existing_papers()

    def _ensure_schema_columns(self) -> None:
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(papers)").fetchall()}
        if "image_url" not in columns:
            self.conn.execute("ALTER TABLE papers ADD COLUMN image_url TEXT")
            self.conn.commit()
        for column, column_type in {
            "source_path": "TEXT",
            "original_relative_path": "TEXT",
            "original_parent_relative_path": "TEXT",
            "original_filename": "TEXT",
            "import_batch_id": "TEXT",
            "import_kind": "TEXT",
            "import_as": "TEXT",
            "doi_source": "TEXT",
            "parse_status": "TEXT",
            "parse_error": "TEXT",
            "size_bytes": "INTEGER",
            "modified_at": "TEXT",
            "page_count": "INTEGER",
        }.items():
            if column not in columns:
                self.conn.execute(f"ALTER TABLE papers ADD COLUMN {column} {column_type}")
                self.conn.commit()
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_source_path ON papers(source_path, size_bytes)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_papers_import_batch ON papers(import_batch_id)")
        self.conn.commit()
        library_item_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(library_items)").fetchall()}
        if "display_name" not in library_item_columns:
            self.conn.execute("ALTER TABLE library_items ADD COLUMN display_name TEXT")
            self.conn.commit()
        if "original_folder_id" not in library_item_columns:
            self.conn.execute("ALTER TABLE library_items ADD COLUMN original_folder_id INTEGER")
            self.conn.commit()
        if "trashed_at" not in library_item_columns:
            self.conn.execute("ALTER TABLE library_items ADD COLUMN trashed_at TEXT")
            self.conn.commit()
        library_folder_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(library_folders)").fetchall()}
        if "color" not in library_folder_columns:
            self.conn.execute("ALTER TABLE library_folders ADD COLUMN color TEXT")
            self.conn.commit()
        if "original_parent_id" not in library_folder_columns:
            self.conn.execute("ALTER TABLE library_folders ADD COLUMN original_parent_id INTEGER")
            self.conn.commit()
        if "trashed_at" not in library_folder_columns:
            self.conn.execute("ALTER TABLE library_folders ADD COLUMN trashed_at TEXT")
            self.conn.commit()
        my_publication_columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(my_publications)").fetchall()}
        if "sort_order" not in my_publication_columns:
            self.conn.execute("ALTER TABLE my_publications ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()
            self._backfill_my_publication_sort_order()

    def _ensure_library_root(self) -> None:
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO library_folders (id, name, parent_id, created_at, updated_at, sort_order)
            VALUES (1, 'Library', NULL, ?, ?, 0)
            """,
            (timestamp, timestamp),
        )
        self.conn.commit()

    def _seed_library_from_existing_papers(self) -> None:
        existing = self.conn.execute("SELECT COUNT(*) AS count FROM library_items").fetchone()
        if int(existing["count"] or 0) > 0:
            return
        rows = self.conn.execute(
            """
            SELECT paper_id
            FROM papers
            WHERE (download_status IN ('success', 'partial') OR analysis_status != 'not_started')
              AND (section_allowed IS NULL OR section_allowed != 0)
            ORDER BY publication_date DESC, journal ASC, title ASC
            """
        ).fetchall()
        timestamp = now_iso()
        for index, row in enumerate(rows, start=1):
            self.conn.execute(
                """
                INSERT OR IGNORE INTO library_items (folder_id, paper_id, created_at, sort_order)
                VALUES (1, ?, ?, ?)
                """,
                (row["paper_id"], timestamp, index),
            )
        self.conn.commit()

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
                "image_url",
                "raw_json",
            ]:
                value = payload.get(key)
                if key == "publication_date" and payload.get("source") == "arxiv" and value not in (None, ""):
                    merged[key] = value
                    continue
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
            "image_url",
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
            "image_url",
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

    def update_image_url(self, paper_id: str, image_url: str) -> None:
        self.conn.execute(
            "UPDATE papers SET image_url = ? WHERE paper_id = ?",
            (image_url, paper_id),
        )
        self.conn.commit()

    def create_library_folder(self, *, parent_id: int = 1, name: str) -> dict[str, Any]:
        parent_id = int(parent_id or 1)
        clean_name = " ".join(name.strip().split()) or "New Folder"
        clean_name = self._unique_library_folder_name(parent_id, clean_name)
        sort_order = self._next_library_sort_order("library_folders", parent_id)
        timestamp = now_iso()
        cursor = self.conn.execute(
            """
            INSERT INTO library_folders (name, parent_id, created_at, updated_at, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (clean_name, parent_id, timestamp, timestamp, sort_order),
        )
        self.conn.commit()
        return self.get_library_folder(int(cursor.lastrowid)) or {}

    def create_library_root_folder(self, *, name: str) -> dict[str, Any]:
        clean_name = " ".join(name.strip().split()) or "Space"
        clean_name = self._unique_library_root_folder_name(clean_name)
        timestamp = now_iso()
        row = self.conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM library_folders WHERE parent_id IS NULL"
        ).fetchone()
        sort_order = int(row["next_order"] or 1)
        cursor = self.conn.execute(
            """
            INSERT INTO library_folders (name, parent_id, created_at, updated_at, sort_order)
            VALUES (?, NULL, ?, ?, ?)
            """,
            (clean_name, timestamp, timestamp, sort_order),
        )
        self.conn.commit()
        return self.get_library_folder(int(cursor.lastrowid)) or {}

    def get_library_folder(self, folder_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM library_folders WHERE id = ?", (int(folder_id),)).fetchone()
        return dict(row) if row else None

    def ensure_library_folder(self, *, parent_id: int = 1, name: str) -> dict[str, Any]:
        parent_id = int(parent_id or 1)
        clean_name = " ".join(name.strip().split()) or "New Folder"
        row = self.conn.execute(
            """
            SELECT *
            FROM library_folders
            WHERE parent_id = ? AND lower(name) = lower(?)
            ORDER BY sort_order, id
            LIMIT 1
            """,
            (parent_id, clean_name),
        ).fetchone()
        if row:
            return dict(row)
        return self.create_library_folder(parent_id=parent_id, name=clean_name)

    def rename_library_folder(self, *, folder_id: int, name: str) -> dict[str, Any]:
        folder_id = int(folder_id)
        if folder_id == 1:
            raise ValueError("Root folder cannot be renamed")
        folder = self.get_library_folder(folder_id)
        if not folder:
            raise ValueError("Folder not found")
        clean_name = " ".join(name.strip().split()) or str(folder.get("name") or "New Folder")
        if folder.get("parent_id") is None:
            clean_name = self._unique_library_root_folder_name(clean_name, exclude_id=folder_id)
        else:
            clean_name = self._unique_library_folder_name(int(folder.get("parent_id") or 1), clean_name, exclude_id=folder_id)
        self.conn.execute(
            """
            UPDATE library_folders
            SET name = ?, updated_at = ?
            WHERE id = ?
            """,
            (clean_name, now_iso(), folder_id),
        )
        self.conn.commit()
        return self.get_library_folder(folder_id) or {}

    def set_library_folder_color(self, *, folder_id: int, color: str) -> dict[str, Any]:
        folder_id = int(folder_id)
        if folder_id == 1:
            raise ValueError("Root folder cannot be colored")
        if not self.get_library_folder(folder_id):
            raise ValueError("Folder not found")
        clean_color = str(color or "").strip()
        if clean_color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", clean_color):
            raise ValueError("Folder color must be a hex color")
        self.conn.execute(
            """
            UPDATE library_folders
            SET color = ?, updated_at = ?
            WHERE id = ?
            """,
            (clean_color or None, now_iso(), folder_id),
        )
        self.conn.commit()
        return self.get_library_folder(folder_id) or {}

    def add_library_item(self, *, paper_id: str, folder_id: int = 1) -> dict[str, Any]:
        folder_id = int(folder_id or 1)
        sort_order = self._next_library_sort_order("library_items", folder_id)
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO library_items (folder_id, paper_id, created_at, sort_order)
            VALUES (?, ?, ?, ?)
            """,
            (folder_id, paper_id, timestamp, sort_order),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT *
            FROM library_items
            WHERE folder_id = ? AND paper_id = ?
            """,
            (folder_id, paper_id),
        ).fetchone()
        return dict(row) if row else {}

    def get_library_item(self, item_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM library_items WHERE id = ?", (int(item_id),)).fetchone()
        return dict(row) if row else None

    def rename_library_item(self, *, item_id: int, name: str) -> dict[str, Any]:
        item_id = int(item_id)
        if not self.get_library_item(item_id):
            raise ValueError("Library item not found")
        clean_name = " ".join(name.strip().split())
        self.conn.execute(
            "UPDATE library_items SET display_name = ? WHERE id = ?",
            (clean_name or None, item_id),
        )
        self.conn.commit()
        return self.get_library_item(item_id) or {}

    def delete_library_item(self, *, item_id: int) -> None:
        self.conn.execute("DELETE FROM library_items WHERE id = ?", (int(item_id),))
        self.conn.commit()

    def delete_library_folder(self, *, folder_id: int) -> None:
        folder_id = int(folder_id)
        if folder_id == 1:
            raise ValueError("Root folder cannot be deleted")
        if not self.get_library_folder(folder_id):
            raise ValueError("Folder not found")
        self.conn.execute("DELETE FROM library_folders WHERE id = ?", (folder_id,))
        self.conn.commit()

    def remove_library_paper(self, *, paper_id: str) -> None:
        self.conn.execute("DELETE FROM library_items WHERE paper_id = ?", (str(paper_id),))
        self.conn.commit()

    def get_setting(self, key: str, default: str = "") -> str:
        row = self.conn.execute("SELECT value FROM app_settings WHERE key = ?", (str(key),)).fetchone()
        return str(row["value"] or "") if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (str(key), str(value or ""), now_iso()),
        )
        self.conn.commit()

    def add_my_publication(self, *, paper_id: str) -> dict[str, Any]:
        timestamp = now_iso()
        sort_order = self.next_my_publication_sort_order()
        self.conn.execute(
            """
            INSERT INTO my_publications (paper_id, starred, sort_order, created_at, updated_at)
            VALUES (?, 0, ?, ?, ?)
            ON CONFLICT(paper_id) DO UPDATE SET updated_at = excluded.updated_at
            """,
            (str(paper_id), sort_order, timestamp, timestamp),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT my_publications.*, papers.*
            FROM my_publications
            JOIN papers ON papers.paper_id = my_publications.paper_id
            WHERE my_publications.paper_id = ?
            """,
            (str(paper_id),),
        ).fetchone()
        return dict(row) if row else {}

    def set_my_publication_starred(self, *, publication_id: int, starred: bool) -> dict[str, Any]:
        self.conn.execute(
            "UPDATE my_publications SET starred = ?, updated_at = ? WHERE id = ?",
            (1 if starred else 0, now_iso(), int(publication_id)),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT my_publications.*, papers.*
            FROM my_publications
            JOIN papers ON papers.paper_id = my_publications.paper_id
            WHERE my_publications.id = ?
            """,
            (int(publication_id),),
        ).fetchone()
        return dict(row) if row else {}

    def delete_my_publication(self, *, publication_id: int) -> None:
        self.conn.execute("DELETE FROM my_publications WHERE id = ?", (int(publication_id),))
        self.conn.commit()

    def reorder_my_publications(self, publication_ids: list[int]) -> None:
        timestamp = now_iso()
        for index, publication_id in enumerate(publication_ids):
            self.conn.execute(
                "UPDATE my_publications SET sort_order = ?, updated_at = ? WHERE id = ?",
                (index, timestamp, int(publication_id)),
            )
        self.conn.commit()

    def list_my_publications(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT my_publications.*, papers.*
            FROM my_publications
            JOIN papers ON papers.paper_id = my_publications.paper_id
            ORDER BY my_publications.sort_order ASC, my_publications.id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def next_my_publication_sort_order(self) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM my_publications").fetchone()
        return int(row["next_order"] or 0)

    def _backfill_my_publication_sort_order(self) -> None:
        rows = self.conn.execute(
            """
            SELECT my_publications.id
            FROM my_publications
            JOIN papers ON papers.paper_id = my_publications.paper_id
            ORDER BY papers.publication_date DESC, papers.title ASC, my_publications.id ASC
            """
        ).fetchall()
        for index, row in enumerate(rows):
            self.conn.execute("UPDATE my_publications SET sort_order = ? WHERE id = ?", (index, row["id"]))
        self.conn.commit()

    def count_active_library_items_for_paper(self, *, paper_id: str, recycle_folder_id: int) -> int:
        row = self.conn.execute(
            """
            WITH RECURSIVE recycle_tree(id) AS (
              SELECT id FROM library_folders WHERE id = ?
              UNION ALL
              SELECT library_folders.id
              FROM library_folders
              JOIN recycle_tree ON library_folders.parent_id = recycle_tree.id
            )
            SELECT COUNT(*) AS count
            FROM library_items
            WHERE paper_id = ?
              AND folder_id NOT IN (SELECT id FROM recycle_tree)
              AND trashed_at IS NULL
            """,
            (int(recycle_folder_id), str(paper_id)),
        ).fetchone()
        return int(row["count"] or 0)

    def library_paper_ids_in_folder_tree(self, *, folder_id: int) -> list[str]:
        rows = self.conn.execute(
            """
            WITH RECURSIVE folder_tree(id) AS (
              SELECT id FROM library_folders WHERE id = ?
              UNION ALL
              SELECT library_folders.id
              FROM library_folders
              JOIN folder_tree ON library_folders.parent_id = folder_tree.id
            )
            SELECT DISTINCT paper_id
            FROM library_items
            WHERE folder_id IN (SELECT id FROM folder_tree)
            """,
            (int(folder_id),),
        ).fetchall()
        return [str(row["paper_id"]) for row in rows if row["paper_id"]]

    def move_library_item_to_trash(self, *, item_id: int, recycle_folder_id: int) -> dict[str, Any]:
        source = self.get_library_item(item_id)
        if not source:
            raise ValueError("Library item not found")
        recycle_folder_id = int(recycle_folder_id)
        existing = self.conn.execute(
            """
            SELECT *
            FROM library_items
            WHERE folder_id = ? AND paper_id = ? AND id != ?
            """,
            (recycle_folder_id, source["paper_id"], int(item_id)),
        ).fetchone()
        if existing:
            self.delete_library_item(item_id=int(item_id))
            return dict(existing)
        sort_order = self._next_library_sort_order("library_items", recycle_folder_id)
        self.conn.execute(
            """
            UPDATE library_items
            SET folder_id = ?, original_folder_id = ?, trashed_at = ?, sort_order = ?
            WHERE id = ?
            """,
            (recycle_folder_id, int(source.get("folder_id") or 1), now_iso(), sort_order, int(item_id)),
        )
        self.conn.commit()
        return self.get_library_item(int(item_id)) or {}

    def recover_library_item(self, *, item_id: int, fallback_folder_id: int) -> dict[str, Any]:
        source = self.get_library_item(item_id)
        if not source:
            raise ValueError("Library item not found")
        target_folder_id = int(source.get("original_folder_id") or fallback_folder_id or 1)
        if not self.get_library_folder(target_folder_id):
            target_folder_id = int(fallback_folder_id or 1)
        existing = self.conn.execute(
            """
            SELECT *
            FROM library_items
            WHERE folder_id = ? AND paper_id = ? AND id != ?
            """,
            (target_folder_id, source["paper_id"], int(item_id)),
        ).fetchone()
        if existing:
            self.delete_library_item(item_id=int(item_id))
            return dict(existing)
        sort_order = self._next_library_sort_order("library_items", target_folder_id)
        self.conn.execute(
            """
            UPDATE library_items
            SET folder_id = ?, original_folder_id = NULL, trashed_at = NULL, sort_order = ?
            WHERE id = ?
            """,
            (target_folder_id, sort_order, int(item_id)),
        )
        self.conn.commit()
        return self.get_library_item(int(item_id)) or {}

    def move_library_folder_to_trash(self, *, folder_id: int, recycle_folder_id: int) -> dict[str, Any]:
        folder_id = int(folder_id)
        recycle_folder_id = int(recycle_folder_id)
        if folder_id == 1 or folder_id == recycle_folder_id:
            raise ValueError("This folder cannot be deleted")
        source = self.get_library_folder(folder_id)
        if not source:
            raise ValueError("Folder not found")
        if self._folder_is_descendant(recycle_folder_id, folder_id):
            raise ValueError("Folder cannot be moved inside itself")
        sort_order = self._next_library_sort_order("library_folders", recycle_folder_id)
        self.conn.execute(
            """
            UPDATE library_folders
            SET parent_id = ?, original_parent_id = ?, trashed_at = ?, sort_order = ?, updated_at = ?
            WHERE id = ?
            """,
            (recycle_folder_id, int(source.get("parent_id") or 1), now_iso(), sort_order, now_iso(), folder_id),
        )
        self.conn.commit()
        return self.get_library_folder(folder_id) or {}

    def recover_library_folder(self, *, folder_id: int, fallback_parent_id: int) -> dict[str, Any]:
        folder_id = int(folder_id)
        source = self.get_library_folder(folder_id)
        if not source:
            raise ValueError("Folder not found")
        parent_id = int(source.get("original_parent_id") or fallback_parent_id or 1)
        if parent_id == folder_id or self._folder_is_descendant(parent_id, folder_id) or not self.get_library_folder(parent_id):
            parent_id = int(fallback_parent_id or 1)
        sort_order = self._next_library_sort_order("library_folders", parent_id)
        self.conn.execute(
            """
            UPDATE library_folders
            SET parent_id = ?, original_parent_id = NULL, trashed_at = NULL, sort_order = ?, updated_at = ?
            WHERE id = ?
            """,
            (parent_id, sort_order, now_iso(), folder_id),
        )
        self.conn.commit()
        return self.get_library_folder(folder_id) or {}

    def copy_library_item(self, *, item_id: int, folder_id: int) -> dict[str, Any]:
        source = self.get_library_item(item_id)
        if not source:
            raise ValueError("Library item not found")
        folder_id = int(folder_id or 1)
        sort_order = self._next_library_sort_order("library_items", folder_id)
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO library_items (folder_id, paper_id, display_name, created_at, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (folder_id, source["paper_id"], source.get("display_name"), timestamp, sort_order),
        )
        self.conn.commit()
        row = self.conn.execute(
            """
            SELECT *
            FROM library_items
            WHERE folder_id = ? AND paper_id = ?
            """,
            (folder_id, source["paper_id"]),
        ).fetchone()
        return dict(row) if row else {}

    def copy_library_folder(self, *, folder_id: int, parent_id: int) -> dict[str, Any]:
        folder_id = int(folder_id)
        parent_id = int(parent_id or 1)
        source = self.get_library_folder(folder_id)
        if not source:
            raise ValueError("Folder not found")
        if folder_id == 1:
            raise ValueError("Root folder cannot be copied")
        if parent_id == folder_id or self._folder_is_descendant(parent_id, folder_id):
            raise ValueError("Folder cannot be copied inside itself")
        return self._copy_library_folder_tree(folder_id=folder_id, parent_id=parent_id)

    def _copy_library_folder_tree(self, *, folder_id: int, parent_id: int) -> dict[str, Any]:
        source = self.get_library_folder(folder_id)
        if not source:
            raise ValueError("Folder not found")
        copied = self.create_library_folder(parent_id=parent_id, name=str(source.get("name") or "New Folder"))
        copied_id = int(copied.get("id") or 0)
        item_rows = self.conn.execute(
            """
            SELECT *
            FROM library_items
            WHERE folder_id = ?
            ORDER BY sort_order, id
            """,
            (folder_id,),
        ).fetchall()
        for row in item_rows:
            sort_order = self._next_library_sort_order("library_items", copied_id)
            self.conn.execute(
                """
                INSERT OR IGNORE INTO library_items (folder_id, paper_id, display_name, created_at, sort_order)
                VALUES (?, ?, ?, ?, ?)
                """,
                (copied_id, row["paper_id"], row["display_name"], now_iso(), sort_order),
            )
        child_rows = self.conn.execute(
            """
            SELECT id
            FROM library_folders
            WHERE parent_id = ?
            ORDER BY sort_order, name
            """,
            (folder_id,),
        ).fetchall()
        for row in child_rows:
            self._copy_library_folder_tree(folder_id=int(row["id"]), parent_id=copied_id)
        self.conn.commit()
        return copied

    def move_library_item(self, *, item_id: int, folder_id: int) -> dict[str, Any]:
        folder_id = int(folder_id or 1)
        item_id = int(item_id)
        source = self.get_library_item(item_id)
        if not source:
            raise ValueError("Library item not found")
        existing = self.conn.execute(
            """
            SELECT *
            FROM library_items
            WHERE folder_id = ? AND paper_id = ? AND id != ?
            """,
            (folder_id, source["paper_id"], item_id),
        ).fetchone()
        if existing:
            self.conn.execute("DELETE FROM library_items WHERE id = ?", (item_id,))
            self.conn.commit()
            return dict(existing)
        sort_order = self._next_library_sort_order("library_items", folder_id)
        self.conn.execute(
            "UPDATE library_items SET folder_id = ?, original_folder_id = NULL, trashed_at = NULL, sort_order = ? WHERE id = ?",
            (folder_id, sort_order, item_id),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM library_items WHERE id = ?", (item_id,)).fetchone()
        return dict(row) if row else {}

    def move_library_folder(self, *, folder_id: int, parent_id: int) -> dict[str, Any]:
        folder_id = int(folder_id)
        parent_id = int(parent_id or 1)
        if folder_id == 1:
            raise ValueError("Root folder cannot be moved")
        if folder_id == parent_id or self._folder_is_descendant(parent_id, folder_id):
            raise ValueError("Folder cannot be moved inside itself")
        sort_order = self._next_library_sort_order("library_folders", parent_id)
        self.conn.execute(
            """
            UPDATE library_folders
            SET parent_id = ?, original_parent_id = NULL, trashed_at = NULL, sort_order = ?, updated_at = ?
            WHERE id = ?
            """,
            (parent_id, sort_order, now_iso(), folder_id),
        )
        self.conn.commit()
        return self.get_library_folder(folder_id) or {}

    def reorder_library_entry(
        self,
        *,
        entry_type: str,
        entry_id: int,
        parent_id: int,
        target_id: int,
        position: str,
    ) -> dict[str, Any]:
        entry_id = int(entry_id)
        parent_id = int(parent_id or 1)
        target_id = int(target_id)
        position = "after" if position == "after" else "before"
        if entry_type == "folder":
            table = "library_folders"
            parent_column = "parent_id"
            label_column = "name"
            if entry_id == 1:
                raise ValueError("Root folder cannot be reordered")
        elif entry_type == "item":
            table = "library_items"
            parent_column = "folder_id"
            label_column = "id"
        else:
            raise ValueError("type must be item or folder")
        source = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (entry_id,)).fetchone()
        target = self.conn.execute(f"SELECT * FROM {table} WHERE id = ?", (target_id,)).fetchone()
        if not source or not target:
            raise ValueError("Library entry not found")
        if int(source[parent_column] or 1) != parent_id or int(target[parent_column] or 1) != parent_id:
            raise ValueError("Entries must be in the same folder")
        rows = self.conn.execute(
            f"""
            SELECT id
            FROM {table}
            WHERE {parent_column} = ?
            ORDER BY sort_order, {label_column}, id
            """,
            (parent_id,),
        ).fetchall()
        ordered = [int(row["id"]) for row in rows if int(row["id"]) != entry_id]
        if target_id not in ordered:
            raise ValueError("Target entry not found")
        target_index = ordered.index(target_id)
        insert_index = target_index + (1 if position == "after" else 0)
        ordered.insert(insert_index, entry_id)
        for sort_order, row_id in enumerate(ordered, start=1):
            self.conn.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (sort_order, row_id))
        if entry_type == "folder":
            self.conn.execute("UPDATE library_folders SET updated_at = ? WHERE id = ?", (now_iso(), entry_id))
        self.conn.commit()
        if entry_type == "folder":
            return self.get_library_folder(entry_id) or {}
        return self.get_library_item(entry_id) or {}

    def list_library_folders(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM library_folders
            ORDER BY COALESCE(parent_id, 0), sort_order, name
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def list_library_items(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT library_items.*, papers.*
            FROM library_items
            JOIN papers ON papers.paper_id = library_items.paper_id
            ORDER BY library_items.folder_id, library_items.sort_order, papers.title
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def _next_library_sort_order(self, table: str, folder_id: int) -> int:
        parent_column = "parent_id" if table == "library_folders" else "folder_id"
        row = self.conn.execute(
            f"SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM {table} WHERE {parent_column} = ?",
            (int(folder_id),),
        ).fetchone()
        return int(row["next_order"] or 1)

    def _unique_library_folder_name(self, parent_id: int, base_name: str, *, exclude_id: int | None = None) -> str:
        rows = self.conn.execute(
            "SELECT id, name FROM library_folders WHERE parent_id = ?",
            (int(parent_id),),
        ).fetchall()
        existing = {str(row["name"]) for row in rows if int(row["id"]) != int(exclude_id or 0)}
        if base_name not in existing:
            return base_name
        index = 2
        while f"{base_name} {index}" in existing:
            index += 1
        return f"{base_name} {index}"

    def _unique_library_root_folder_name(self, base_name: str, *, exclude_id: int | None = None) -> str:
        rows = self.conn.execute("SELECT id, name FROM library_folders WHERE parent_id IS NULL").fetchall()
        existing = {str(row["name"]) for row in rows if int(row["id"]) != int(exclude_id or 0)}
        if base_name not in existing:
            return base_name
        index = 2
        while f"{base_name} {index}" in existing:
            index += 1
        return f"{base_name} {index}"

    def _folder_is_descendant(self, candidate_id: int, ancestor_id: int) -> bool:
        current = int(candidate_id)
        while current and current != 1:
            row = self.conn.execute("SELECT parent_id FROM library_folders WHERE id = ?", (current,)).fetchone()
            if not row:
                return False
            current = int(row["parent_id"] or 1)
            if current == int(ancestor_id):
                return True
        return False


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
