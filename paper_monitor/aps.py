from __future__ import annotations

from typing import Any


APS_JOURNAL_SLUGS = {
    "aps open science": "apsos",
    "apsos": "apsos",
    "physical review a": "pra",
    "pra": "pra",
    "physical review b": "prb",
    "prb": "prb",
    "physical review c": "prc",
    "prc": "prc",
    "physical review d": "prd",
    "prd": "prd",
    "physical review e": "pre",
    "pre": "pre",
    "physical review accelerators and beams": "prstab",
    "physical review special topics - accelerators and beams": "prstab",
    "physical review special topics—accelerators and beams": "prstab",
    "prab": "prstab",
    "physical review applied": "prapplied",
    "pr applied": "prapplied",
    "physical review fluids": "prfluids",
    "pr fluids": "prfluids",
    "physical review letters": "prl",
    "prl": "prl",
    "physical review materials": "prmaterials",
    "pr materials": "prmaterials",
    "physical review physics education research": "prstper",
    "prper": "prstper",
    "physical review research": "prresearch",
    "pr research": "prresearch",
    "physical review x": "prx",
    "prx": "prx",
    "prx energy": "prxenergy",
    "prx intelligence": "prxintelligence",
    "prx life": "prxlife",
    "prx quantum": "prxquantum",
    "reviews of modern physics": "rmp",
    "review of modern physics": "rmp",
    "rmp": "rmp",
}

APS_CANONICAL_NAMES_BY_SLUG = {
    "apsos": "APS Open Science",
    "pra": "Physical Review A",
    "prb": "Physical Review B",
    "prc": "Physical Review C",
    "prd": "Physical Review D",
    "pre": "Physical Review E",
    "prstab": "Physical Review Accelerators and Beams",
    "prapplied": "Physical Review Applied",
    "prfluids": "Physical Review Fluids",
    "prl": "Physical Review Letters",
    "prmaterials": "Physical Review Materials",
    "prstper": "Physical Review Physics Education Research",
    "prresearch": "Physical Review Research",
    "prx": "Physical Review X",
    "prxenergy": "PRX Energy",
    "prxintelligence": "PRX Intelligence",
    "prxlife": "PRX Life",
    "prxquantum": "PRX Quantum",
    "rmp": "Reviews of Modern Physics",
}

# Retain the historical public mapping used by SQLite migrations.
APS_MONITORED_JOURNALS = {
    name: APS_CANONICAL_NAMES_BY_SLUG[slug]
    for name, slug in APS_JOURNAL_SLUGS.items()
}


def is_aps_lifecycle_journal(journal_name: Any) -> bool:
    return str(journal_name or "").strip().casefold() in APS_MONITORED_JOURNALS


def aps_journal_slug(journal_name: Any) -> str:
    return APS_JOURNAL_SLUGS.get(str(journal_name or "").strip().casefold(), "")


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
