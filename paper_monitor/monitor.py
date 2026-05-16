from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Callable

from .config import AppConfig, JournalConfig
from .sources.crossref import fetch_crossref_journal
from .sources.openalex import fetch_openalex_journal
from .sources.publisher import enrich_from_landing_page, enrich_image_from_landing_page
from .storage import Storage
from .text import clean_text
from .time_utils import now_iso


def run_journal_monitor(
    *,
    config: AppConfig,
    storage: Storage,
    start_date: date,
    end_date: date,
    enrich: bool = True,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "window_start": start_date.isoformat(),
        "window_end": end_date.isoformat(),
        "journals": {},
        "source_attempts": 0,
        "source_errors": 0,
    }

    total_journals = len(config.journals)
    for completed_journals, journal in enumerate(config.journals, start=1):
        journal_summary = fetch_one_journal(
            config=config,
            storage=storage,
            journal=journal,
            start_date=start_date,
            end_date=end_date,
            enrich=enrich,
        )
        summary["journals"][journal.name] = journal_summary
        summary["source_attempts"] += journal_summary["source_attempts"]
        summary["source_errors"] += journal_summary["source_errors"]
        if progress_callback:
            progress_callback(journal.name, completed_journals, total_journals)

    return summary


def fetch_one_journal(
    *,
    config: AppConfig,
    storage: Storage,
    journal: JournalConfig,
    start_date: date,
    end_date: date,
    enrich: bool,
) -> dict[str, Any]:
    collected: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}

    crossref_result = _run_source(
        storage=storage,
        source="crossref",
        journal_name=journal.name,
        start_date=start_date,
        end_date=end_date,
        fetch=lambda: fetch_crossref_journal(
            journal_name=journal.name,
            issns=journal.issns,
            start_date=start_date,
            end_date=end_date,
        ),
    )
    crossref_items = crossref_result["papers"]
    source_counts["crossref"] = len(crossref_items)
    collected.extend(crossref_items)
    source_statuses = {"crossref": crossref_result["status"]}
    source_errors = 1 if crossref_result["status"] == "error" else 0
    source_attempts = 1

    if journal.openalex_source_id:
        openalex_result = _run_source(
            storage=storage,
            source="openalex",
            journal_name=journal.name,
            start_date=start_date,
            end_date=end_date,
            fetch=lambda: fetch_openalex_journal(
                journal_name=journal.name,
                source_id=journal.openalex_source_id or "",
                start_date=start_date,
                end_date=end_date,
            ),
        )
        openalex_items = openalex_result["papers"]
        source_counts["openalex"] = len(openalex_items)
        collected.extend(openalex_items)
        source_statuses["openalex"] = openalex_result["status"]
        source_errors += 1 if openalex_result["status"] == "error" else 0
        source_attempts += 1

    policy = config.section_policies.get(journal.section_policy, {})
    saved = 0
    blocked = 0
    for paper in dedup_by_id(collected):
        apply_fast_section_hints(paper, journal)
        if enrich and not journal.skip_landing_enrichment and paper.get("section_allowed") is not False:
            paper = enrich_from_landing_page(
                paper,
                section_policy=policy,
                keep_unknown=config.keep_unknown_sections,
            )
        elif paper.get("section_allowed") is None:
            paper["section_allowed"] = config.keep_unknown_sections
        if enrich and journal.skip_landing_enrichment and paper.get("section_allowed") is not False:
            paper = enrich_image_from_landing_page(paper)

        if paper.get("section_allowed") is False:
            blocked += 1

        storage.upsert_paper(paper)
        saved += 1

    return {
        "source_counts": source_counts,
        "source_statuses": source_statuses,
        "source_attempts": source_attempts,
        "source_errors": source_errors,
        "saved": saved,
        "blocked_by_section": blocked,
    }


def default_windows(today: date, lookback_days: int, report_days: int) -> tuple[date, date, date]:
    fetch_start = today - timedelta(days=max(lookback_days - 1, 0))
    report_start = today - timedelta(days=max(report_days - 1, 0))
    return fetch_start, report_start, today


def dedup_by_id(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for paper in papers:
        key = paper.get("paper_id") or paper.get("doi") or paper.get("url")
        if not key:
            continue
        if key not in merged:
            merged[key] = dict(paper)
            order.append(key)
            continue
        current = merged[key]
        for field in [
            "abstract",
            "abstract_source",
            "landing_url",
            "pdf_url",
            "url",
            "type",
            "type_crossref",
            "publisher_section",
            "section_allowed",
        ]:
            value = paper.get(field)
            if value not in (None, "") and current.get(field) in (None, ""):
                current[field] = value
        sources = [item for item in (current.get("source") or "").split("+") if item]
        if paper.get("source"):
            sources.append(paper["source"])
        current["source"] = "+".join(sorted(set(sources)))
    return [merged[key] for key in order]


def apply_fast_section_hints(paper: dict[str, Any], journal: JournalConfig) -> None:
    doi = (paper.get("doi") or "").lower()
    title = clean_text(paper.get("title")).lower()
    if journal.section_policy == "nature":
        if doi.startswith("10.1038/d"):
            paper["publisher_section"] = paper.get("publisher_section") or "news/comment"
            paper["section_allowed"] = False
        elif doi.startswith("10.1038/s") and paper.get("section_allowed") is None:
            paper["publisher_section"] = paper.get("publisher_section") or "article"
            paper["section_allowed"] = True
    elif journal.section_policy == "science":
        if is_science_non_research(title, doi):
            paper["publisher_section"] = paper.get("publisher_section") or "non-research"
            paper["section_allowed"] = False
        elif is_science_perspective(title, doi, clean_text(paper.get("abstract"))):
            paper["publisher_section"] = "perspective"
            paper["section_allowed"] = True
        elif not paper.get("publisher_section"):
            paper["publisher_section"] = "research article"
            if paper.get("section_allowed") is None:
                paper["section_allowed"] = True


def is_science_non_research(title: str, doi: str) -> bool:
    suffix = doi.rsplit(".", 1)[-1] if doi else ""
    if suffix.startswith(("aei", "aeg", "aef")):
        return True
    blocked_title_patterns = [
        r"\berratum\b",
        r"\bcorrection\b",
        r"^in science journals$",
        r"^in other journals$",
        r"<b>.*</b>",
        r"\bbook review\b",
        r"\bdecried as political\b",
        r"\bshocks marine biologists\b",
        r"\bleader calls\b",
        r"\bimperils\b",
        r"\bpoints to\b",
        r"\bshows promise\b",
        r"\bthe power of a\b",
        r"\bhow .+ might be\b",
    ]
    return any(re.search(pattern, title, flags=re.IGNORECASE) for pattern in blocked_title_patterns)


def is_science_perspective(title: str, doi: str, abstract: str) -> bool:
    suffix = doi.rsplit(".", 1)[-1] if doi else ""
    if suffix.startswith("aeh"):
        return True
    perspective_title_patterns = [
        r"^aging and the narrowing\b",
        r"^building\b",
        r"^delivering\b",
        r"^forecasting\b",
        r"^knowledge gaps\b",
        r"^safeguard\b",
        r"^the future of\b",
        r"^the vulnerability of\b",
        r"^aiding peace\b",
        r"^evolving nature-based\b",
        r"^improve genetic\b",
    ]
    if any(re.search(pattern, title, flags=re.IGNORECASE) for pattern in perspective_title_patterns):
        return True
    return 0 < len(abstract) < 260


def _run_source(
    *,
    storage: Storage,
    source: str,
    journal_name: str,
    start_date: date,
    end_date: date,
    fetch,
) -> dict[str, Any]:
    started_at = now_iso()
    try:
        papers = fetch()
        status = "success" if papers else "empty"
        storage.record_fetch_run(
            monitor_type="journal",
            source=source,
            journal=journal_name,
            window_start=start_date.isoformat(),
            window_end=end_date.isoformat(),
            status=status,
            records_found=len(papers),
            started_at=started_at,
            message="",
        )
        return {"papers": papers, "status": status, "message": ""}
    except Exception as exc:
        message = str(exc)
        storage.record_fetch_run(
            monitor_type="journal",
            source=source,
            journal=journal_name,
            window_start=start_date.isoformat(),
            window_end=end_date.isoformat(),
            status="error",
            records_found=0,
            started_at=started_at,
            message=message,
        )
        return {"papers": [], "status": "error", "message": message}
