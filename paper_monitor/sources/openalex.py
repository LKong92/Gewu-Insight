from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from ..http import request_with_retries
from ..text import clean_markup_text, clean_text, make_paper_id, normalize_doi


def fetch_openalex_journal(
    *,
    journal_name: str,
    source_id: str,
    start_date: date,
    end_date: date,
    per_page: int = 100,
    max_pages: int = 10,
) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    cursor = "*"

    for _ in range(max_pages):
        params = {
            "filter": (
                f"primary_location.source.id:https://openalex.org/{source_id},"
                f"from_publication_date:{start_date.isoformat()},"
                f"to_publication_date:{end_date.isoformat()}"
            ),
            "per-page": per_page,
            "cursor": cursor,
            "sort": "publication_date:desc",
            "mailto": os.getenv("OPENALEX_MAILTO", "your_email@example.com"),
        }
        response = request_with_retries("GET", "https://api.openalex.org/works", params=params)
        data = response.json()
        results = data.get("results", [])
        papers.extend(normalize_openalex_item(item, journal_name) for item in results)
        next_cursor = data.get("meta", {}).get("next_cursor")
        if not next_cursor or next_cursor == cursor or len(results) < per_page:
            break
        cursor = next_cursor

    return papers


def search_openalex_author_publications(
    author_name: str,
    *,
    affiliations: list[str] | None = None,
    max_authors: int = 6,
    per_author: int = 20,
    timeout: int = 20,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    query = clean_text(author_name)
    if not query:
        return []
    affiliation_terms = [clean_text(value) for value in (affiliations or []) if clean_text(value)]
    author_response = request_with_retries(
        "GET",
        "https://api.openalex.org/authors",
        params={
            "search": query,
            "per-page": max(1, min(25, int(max_authors or 6))),
            "mailto": os.getenv("OPENALEX_MAILTO", "your_email@example.com"),
        },
        timeout=timeout,
        max_retries=max_retries,
    )
    author_ids: list[str] = []
    author_affiliation_matches_by_id: dict[str, bool] = {}
    for item in author_response.json().get("results", []):
        if not isinstance(item, dict) or not item.get("id"):
            continue
        author_id = clean_text(item.get("id"))
        author_ids.append(author_id)
        author_affiliation_matches_by_id[author_id] = (
            openalex_author_affiliation_matches(item, affiliation_terms) if affiliation_terms else True
        )
    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for author_id in author_ids:
        response = request_with_retries(
            "GET",
            "https://api.openalex.org/works",
            params={
                "filter": f"authorships.author.id:{author_id}",
                "per-page": max(1, min(50, int(per_author or 20))),
                "sort": "publication_date:desc",
                "mailto": os.getenv("OPENALEX_MAILTO", "your_email@example.com"),
            },
            timeout=timeout,
            max_retries=max_retries,
        )
        for item in response.json().get("results", []):
            if not isinstance(item, dict):
                continue
            if affiliation_terms and not (
                openalex_work_author_affiliation_matches(item, author_id, affiliation_terms)
                or author_affiliation_matches_by_id.get(author_id, False)
            ):
                continue
            paper = normalize_openalex_item(item, "Unknown Journal")
            key = paper.get("doi") or paper.get("paper_id")
            if not key or key in seen:
                continue
            seen.add(key)
            papers.append(paper)
    return papers


def openalex_author_affiliation_matches(author: dict[str, Any], affiliations: list[str]) -> bool:
    haystack = " ".join(openalex_affiliation_strings(author)).lower()
    return any(affiliation_matches(haystack, affiliation) for affiliation in affiliations)


def openalex_work_author_affiliation_matches(work: dict[str, Any], author_id: str, affiliations: list[str]) -> bool:
    author_key = clean_text(author_id).rstrip("/").rsplit("/", 1)[-1].lower()
    for authorship in work.get("authorships") or []:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        work_author_id = clean_text(author.get("id")).rstrip("/").rsplit("/", 1)[-1].lower()
        if work_author_id != author_key:
            continue
        haystack = " ".join(openalex_affiliation_strings(authorship)).lower()
        if any(affiliation_matches(haystack, affiliation) for affiliation in affiliations):
            return True
    return False


def openalex_affiliation_strings(value: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in ["display_name", "raw_affiliation_string"]:
        if value.get(key):
            texts.append(clean_text(value.get(key)))
    for raw_affiliation in value.get("raw_affiliation_strings") or []:
        texts.append(clean_text(raw_affiliation))
    for key in ["last_known_institutions", "institutions"]:
        for item in value.get(key) or []:
            if isinstance(item, dict):
                texts.extend(clean_text(item.get(field)) for field in ["display_name", "ror", "country_code"] if item.get(field))
    for item in value.get("affiliations") or []:
        if not isinstance(item, dict):
            continue
        if item.get("raw_affiliation_string"):
            texts.append(clean_text(item.get("raw_affiliation_string")))
        for raw_affiliation in item.get("raw_affiliation_strings") or []:
            texts.append(clean_text(raw_affiliation))
        for institution in item.get("institutions") or []:
            if isinstance(institution, dict):
                texts.extend(clean_text(institution.get(field)) for field in ["display_name", "ror", "country_code"] if institution.get(field))
        for institution in item.get("institution_ids") or []:
            texts.append(clean_text(institution))
    return [text for text in texts if text]


def affiliation_matches(haystack: str, affiliation: str) -> bool:
    tokens = [token for token in re.findall(r"[a-z0-9]+", clean_text(affiliation).lower()) if len(token) > 1]
    return bool(tokens) and all(token in haystack for token in tokens)


def normalize_openalex_item(item: dict[str, Any], journal_name: str) -> dict[str, Any]:
    primary_location = item.get("primary_location") or {}
    source = primary_location.get("source") or {}
    title = clean_markup_text(item.get("title")) or "(Untitled)"
    doi = normalize_doi(item.get("doi"))
    publication_date = clean_text(item.get("publication_date"))
    landing_url = clean_text(primary_location.get("landing_page_url"))
    pdf_url = clean_text(primary_location.get("pdf_url"))
    url = f"https://doi.org/{doi}" if doi else landing_url or pdf_url or clean_text(item.get("id"))
    abstract = clean_text(item.get("abstract")) or rebuild_abstract(item.get("abstract_inverted_index"))
    paper_id = make_paper_id(doi, title, journal_name, publication_date)
    preferred_journal = normalize_openalex_journal_name(journal_name)
    source_journal = normalize_openalex_journal_name(source.get("display_name"))
    journal = preferred_journal if preferred_journal and preferred_journal.lower() != "unknown journal" else source_journal or preferred_journal

    return {
        "paper_id": paper_id,
        "doi": doi,
        "title": title,
        "journal": journal or "Unknown Journal",
        "publication_date": publication_date,
        "abstract": abstract,
        "abstract_source": "metadata" if abstract else "missing",
        "url": url,
        "landing_url": landing_url or url,
        "pdf_url": pdf_url,
        "source": "openalex",
        "type": clean_text(item.get("type")),
        "type_crossref": clean_text(item.get("type_crossref")),
        "publisher_section": "",
        "section_allowed": None,
        "raw": item,
    }


PHYSICAL_REVIEW_JOURNAL_NAMES = {
    "physical review a": "Physical Review A",
    "physical review b": "Physical Review B",
    "physical review c": "Physical Review C",
    "physical review d": "Physical Review D",
    "physical review e": "Physical Review E",
    "physical review letters": "Physical Review Letters",
    "physical review x": "Physical Review X",
    "physical review applied": "Physical Review Applied",
    "physical review fluids": "Physical Review Fluids",
    "physical review materials": "Physical Review Materials",
    "physical review research": "Physical Review Research",
    "reviews of modern physics": "Reviews of Modern Physics",
}


def normalize_openalex_journal_name(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parts = [clean_text(part).strip(" .") for part in text.split("/") if clean_text(part).strip(" .")]
    if len(parts) > 1:
        normalized_parts = {journal_name_key(part) for part in parts}
        if len(normalized_parts) == 1:
            text = parts[-1]
    key = journal_name_key(text)
    if key in PHYSICAL_REVIEW_JOURNAL_NAMES:
        return PHYSICAL_REVIEW_JOURNAL_NAMES[key]
    return clean_text(text)


def journal_name_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean_text(value).lower()).strip()


def rebuild_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    if not inverted_index:
        return ""
    pos_to_word: dict[int, str] = {}
    for word, positions in inverted_index.items():
        for position in positions:
            pos_to_word[position] = word
    if not pos_to_word:
        return ""
    words = [pos_to_word.get(i, "") for i in range(max(pos_to_word) + 1)]
    return clean_text(" ".join(words))
