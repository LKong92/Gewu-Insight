from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = Path(os.environ.get("GEWU_DATA_ROOT") or (ROOT / "data")).expanduser().resolve()
DEFAULT_CONFIG_PATH = ROOT / "config" / "journals.json"
DEFAULT_DB_PATH = DATA_ROOT / "paper_monitor.sqlite"
DEFAULT_DAILY_REPORT_DIR = ROOT / "reports" / "daily"
DEFAULT_ANALYSIS_DIR = ROOT / "reports" / "analyses"
DEFAULT_PDF_DIR = DATA_ROOT / "pdfs"
DEFAULT_LIBRARY_IMPORT_DIR = DATA_ROOT / "library_imports"
DEFAULT_LIBRARY_DIR = DATA_ROOT / "Library"
DEFAULT_SPACES_DIR = DATA_ROOT / "Spaces"
DEFAULT_MY_PUBLICATIONS_DIR = DATA_ROOT / "My Publications"
DEFAULT_ASSOCIATED_FILES_DIR = DATA_ROOT / "Associated Files"
DEFAULT_AUTHOR_PHOTO_DIR = DATA_ROOT / "author_photos"


@dataclass(frozen=True)
class JournalConfig:
    name: str
    issns: list[str]
    openalex_source_id: str | None
    section_policy: str
    skip_landing_enrichment: bool


@dataclass(frozen=True)
class AppConfig:
    fetch_lookback_days: int
    report_days: int
    keep_unknown_sections: bool
    journals: list[JournalConfig]
    section_policies: dict[str, dict[str, list[str]]]


def journal_subscriptions_from_db(db_path: Path) -> list[dict[str, Any]] | None:
    path = Path(db_path)
    if not path.exists():
        return None
    connection = sqlite3.connect(str(path))
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'journal_subscriptions'"
        ).fetchone()
        if not table:
            return None
        total = int(connection.execute("SELECT COUNT(*) FROM journal_subscriptions").fetchone()[0])
        if not total:
            return None
        rows = connection.execute(
            """
            SELECT name, issns_json, openalex_source_id, section_policy,
                   skip_landing_enrichment
            FROM journal_subscriptions
            WHERE enabled = 1
            ORDER BY display_order, name COLLATE NOCASE
            """
        ).fetchall()
    finally:
        connection.close()
    journals: list[dict[str, Any]] = []
    for row in rows:
        try:
            issns = json.loads(row["issns_json"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            issns = []
        journals.append(
            {
                "name": str(row["name"] or ""),
                "issns": list(issns) if isinstance(issns, list) else [],
                "openalex_source_id": row["openalex_source_id"],
                "section_policy": str(row["section_policy"] or "science"),
                "skip_landing_enrichment": bool(row["skip_landing_enrichment"]),
            }
        )
    return journals


def load_config(
    path: Path = DEFAULT_CONFIG_PATH,
    *,
    db_path: Path | None = None,
) -> AppConfig:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    journal_rows = journal_subscriptions_from_db(db_path) if db_path is not None else None
    configured_journals = journal_rows if journal_rows is not None else raw["journals"]
    journals = [
        JournalConfig(
            name=item["name"],
            issns=list(item.get("issns", [])),
            openalex_source_id=item.get("openalex_source_id"),
            section_policy=item.get("section_policy", "nature"),
            skip_landing_enrichment=bool(item.get("skip_landing_enrichment", False)),
        )
        for item in configured_journals
    ]
    return AppConfig(
        fetch_lookback_days=int(raw.get("fetch_lookback_days", 14)),
        report_days=int(raw.get("report_days", 7)),
        keep_unknown_sections=bool(raw.get("keep_unknown_sections", True)),
        journals=journals,
        section_policies=raw.get("section_policies", {}),
    )
