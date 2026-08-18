from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "journals.json"
DEFAULT_DB_PATH = ROOT / "data" / "paper_monitor.sqlite"
DEFAULT_DAILY_REPORT_DIR = ROOT / "reports" / "daily"
DEFAULT_ANALYSIS_DIR = ROOT / "reports" / "analyses"
DEFAULT_PDF_DIR = ROOT / "data" / "pdfs"
DEFAULT_LIBRARY_IMPORT_DIR = ROOT / "data" / "library_imports"
DEFAULT_LIBRARY_DIR = ROOT / "data" / "Library"
DEFAULT_SPACES_DIR = ROOT / "data" / "Spaces"
DEFAULT_MY_PUBLICATIONS_DIR = ROOT / "data" / "My Publications"
DEFAULT_ASSOCIATED_FILES_DIR = ROOT / "data" / "Associated Files"
DEFAULT_AUTHOR_PHOTO_DIR = ROOT / "data" / "author_photos"


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


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> AppConfig:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    journals = [
        JournalConfig(
            name=item["name"],
            issns=list(item.get("issns", [])),
            openalex_source_id=item.get("openalex_source_id"),
            section_policy=item.get("section_policy", "nature"),
            skip_landing_enrichment=bool(item.get("skip_landing_enrichment", False)),
        )
        for item in raw["journals"]
    ]
    return AppConfig(
        fetch_lookback_days=int(raw.get("fetch_lookback_days", 14)),
        report_days=int(raw.get("report_days", 7)),
        keep_unknown_sections=bool(raw.get("keep_unknown_sections", True)),
        journals=journals,
        section_policies=raw.get("section_policies", {}),
    )
