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
        if "original_parent_id" not in library_folder_columns:
            self.conn.execute("ALTER TABLE library_folders ADD COLUMN original_parent_id INTEGER")
            self.conn.commit()
        if "trashed_at" not in library_folder_columns:
            self.conn.execute("ALTER TABLE library_folders ADD COLUMN trashed_at TEXT")
            self.conn.commit()

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
        parent_id = int(folder.get("parent_id") or 1)
        clean_name = " ".join(name.strip().split()) or str(folder.get("name") or "New Folder")
        clean_name = self._unique_library_folder_name(parent_id, clean_name, exclude_id=folder_id)
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

    def count_active_library_items_for_paper(self, *, paper_id: str, recycle_folder_id: int) -> int:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM library_items
            WHERE paper_id = ?
              AND folder_id != ?
              AND trashed_at IS NULL
            """,
            (str(paper_id), int(recycle_folder_id)),
        ).fetchone()
        return int(row["count"] or 0)

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
