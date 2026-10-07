from __future__ import annotations

import json
import os
import hashlib
import sys
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_development_root = (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
                     / "Gewu Insight" / "Development" / hashlib.sha256(str(ROOT).encode()).hexdigest()[:12])
WORKSPACE_ROOT = Path(os.environ.get("GEWU_WORKSPACE_ROOT") or
                      (_development_root if sys.platform == "win32" else ROOT)).expanduser().resolve()
DATA_ROOT = Path(os.environ.get("GEWU_DATA_ROOT") or (WORKSPACE_ROOT / "data")).expanduser().resolve()
_user_config = WORKSPACE_ROOT / "config" / "journals.json"
DEFAULT_CONFIG_PATH = _user_config if _user_config.is_file() else ROOT / "config" / "journals.json"
RUNTIME_ROOT = Path(os.environ.get("GEWU_RUNTIME_ROOT") or
                    (Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
                     / "Gewu Insight" / "Databases" / hashlib.sha256(os.path.normcase(str(WORKSPACE_ROOT)).encode()).hexdigest()[:32]))
DEFAULT_DB_PATH = DATA_ROOT / "paper_monitor.sqlite"
DEFAULT_DAILY_REPORT_DIR = WORKSPACE_ROOT / "reports" / "daily"
DEFAULT_ANALYSIS_DIR = WORKSPACE_ROOT / "reports" / "analyses"
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
