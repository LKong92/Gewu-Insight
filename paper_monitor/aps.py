from __future__ import annotations

from typing import Any


APS_MONITORED_JOURNALS = {
    "physical review letters": "Physical Review Letters",
    "physical review x": "Physical Review X",
    "reviews of modern physics": "Reviews of Modern Physics",
}


def is_aps_lifecycle_journal(journal_name: Any) -> bool:
    return str(journal_name or "").strip().casefold() in APS_MONITORED_JOURNALS


def is_aps_version_of_record(raw: dict[str, Any] | None) -> bool:
    """Return whether APS metadata has been assigned a formal journal citation."""
    item = raw or {}
    volume = str(item.get("volume") or "").strip()
    issue = str(item.get("issue") or "").strip()
    article_number = str(item.get("article-number") or item.get("page") or "").strip()
    if volume or issue or article_number:
        return bool(volume and issue and article_number)

    # OpenAlex does not always expose APS's article number in first_page, but
    # volume and issue are only assigned after the accepted manuscript becomes
    # the published version of record.
    biblio = item.get("biblio") if isinstance(item.get("biblio"), dict) else {}
    openalex_volume = str(biblio.get("volume") or "").strip()
    openalex_issue = str(biblio.get("issue") or "").strip()
    return bool(openalex_volume and openalex_issue)


def apply_aps_publication_status(paper: dict[str, Any]) -> bool:
    """Classify monitored APS records as Accepted or formally published."""
    if not is_aps_lifecycle_journal(paper.get("journal")):
        return False
    formal = is_aps_version_of_record(paper.get("raw"))
    paper["publisher_section"] = "published" if formal else "accepted"
    paper["section_allowed"] = formal
    return formal
