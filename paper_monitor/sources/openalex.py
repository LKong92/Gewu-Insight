from __future__ import annotations

import os
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
    max_authors: int = 6,
    per_author: int = 20,
    timeout: int = 20,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    query = clean_text(author_name)
    if not query:
        return []
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
    author_ids = [
        clean_text(item.get("id"))
        for item in author_response.json().get("results", [])
        if isinstance(item, dict) and item.get("id")
    ]
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
            paper = normalize_openalex_item(item, "Unknown Journal")
            key = paper.get("doi") or paper.get("paper_id")
            if not key or key in seen:
                continue
            seen.add(key)
            papers.append(paper)
    return papers


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

    return {
        "paper_id": paper_id,
        "doi": doi,
        "title": title,
        "journal": clean_text(source.get("display_name")) or journal_name,
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
