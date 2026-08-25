from __future__ import annotations

import os
from datetime import date
from typing import Any

from requests import RequestException

from ..http import request_with_retries
from ..aps import apply_aps_publication_status
from ..text import clean_markup_text, first_text, journal_name_for_doi, make_paper_id, normalize_doi, normalize_publication_title


def fetch_crossref_journal(
    *,
    journal_name: str,
    issns: list[str],
    start_date: date,
    end_date: date,
    rows: int = 100,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    successful_requests = 0
    issn_errors: list[RequestException] = []

    for issn in issns:
        try:
            cursor = "*"
            for _ in range(max_pages):
                params = {
                    "filter": ",".join(
                        [
                            f"from-pub-date:{start_date.isoformat()}",
                            f"until-pub-date:{end_date.isoformat()}",
                            "type:journal-article",
                        ]
                    ),
                    "rows": rows,
                    "cursor": cursor,
                    "select": ",".join(
                        [
                            "DOI",
                            "URL",
                            "title",
                            "container-title",
                            "author",
                            "published-print",
                            "published-online",
                            "published",
                            "issued",
                            "volume",
                            "issue",
                            "page",
                            "article-number",
                            "type",
                            "abstract",
                        ]
                    ),
                }
                mailto = os.getenv("CROSSREF_MAILTO")
                if mailto:
                    params["mailto"] = mailto
                response = request_with_retries(
                    "GET",
                    f"https://api.crossref.org/journals/{issn}/works",
                    params=params,
                )
                message = response.json().get("message", {})
                successful_requests += 1
                for item in message.get("items", []):
                    paper = normalize_crossref_item(item, journal_name)
                    key = paper["doi"] or paper["url"] or paper["paper_id"]
                    if key in seen:
                        continue
                    seen.add(key)
                    papers.append(paper)
                next_cursor = message.get("next-cursor")
                if not next_cursor or len(message.get("items", [])) < rows:
                    break
                cursor = next_cursor
        except RequestException as exc:
            issn_errors.append(exc)

    if not successful_requests and issn_errors:
        raise issn_errors[0]

    return papers


def fetch_crossref_topic(
    *,
    query: str,
    start_date: date,
    end_date: date,
    rows: int = 50,
    max_pages: int = 2,
    timeout: int = 12,
    max_retries: int = 1,
) -> list[dict[str, Any]]:
    cleaned_query = normalize_publication_title(clean_markup_text(query))
    if not cleaned_query:
        return []
    papers: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor = "*"
    for _ in range(max_pages):
        params = {
            "query.bibliographic": cleaned_query,
            "filter": ",".join(
                [
                    f"from-pub-date:{start_date.isoformat()}",
                    f"until-pub-date:{end_date.isoformat()}",
                    "type:journal-article",
                ]
            ),
            "rows": max(1, min(100, int(rows or 50))),
            "cursor": cursor,
            "select": ",".join(
                [
                    "DOI",
                    "URL",
                    "title",
                    "container-title",
                    "author",
                    "published-print",
                    "published-online",
                    "published",
                    "issued",
                    "volume",
                    "issue",
                    "page",
                    "article-number",
                    "type",
                    "abstract",
                ]
            ),
        }
        mailto = os.getenv("CROSSREF_MAILTO")
        if mailto:
            params["mailto"] = mailto
        response = request_with_retries(
            "GET",
            "https://api.crossref.org/works",
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        message = response.json().get("message", {})
        items = message.get("items", [])
        for item in items:
            doi = normalize_doi(item.get("DOI"))
            journal_name = first_text(item.get("container-title")) or journal_name_for_doi("Unknown Journal", doi) or "Unknown Journal"
            paper = normalize_crossref_item(item, journal_name)
            key = paper["doi"] or paper["url"] or paper["paper_id"]
            if key in seen:
                continue
            seen.add(key)
            papers.append(paper)
        next_cursor = message.get("next-cursor")
        if not next_cursor or len(items) < rows:
            break
        cursor = next_cursor
    return papers


def search_crossref_works(
    *,
    query: str,
    start_date: date,
    end_date: date,
    rows: int = 50,
    max_pages: int = 1,
    timeout: int = 10,
    max_retries: int = 1,
) -> list[dict[str, Any]]:
    return fetch_crossref_topic(
        query=query,
        start_date=start_date,
        end_date=end_date,
        rows=rows,
        max_pages=max_pages,
        timeout=timeout,
        max_retries=max_retries,
    )


def normalize_crossref_item(item: dict[str, Any], journal_name: str) -> dict[str, Any]:
    title = normalize_publication_title(clean_markup_text(first_text(item.get("title"))))
    doi = normalize_doi(item.get("DOI"))
    journal_name = journal_name_for_doi(journal_name, doi) or "Unknown Journal"
    publication_date = (
        _crossref_date(item.get("published-online"))
        or _crossref_date(item.get("published-print"))
        or _crossref_date(item.get("published"))
        or _crossref_date(item.get("issued"))
    )
    url = item.get("URL") or (f"https://doi.org/{doi}" if doi else "")
    paper_id = make_paper_id(doi, title, journal_name, publication_date)
    abstract = clean_abstract(item.get("abstract"))
    paper = {
        "paper_id": paper_id,
        "doi": doi,
        "title": title or "(Untitled)",
        "journal": journal_name,
        "publication_date": publication_date,
        "abstract": abstract,
        "abstract_source": "crossref" if abstract else "missing",
        "url": url,
        "landing_url": url,
        "pdf_url": "",
        "source": "crossref",
        "type": item.get("type", ""),
        "type_crossref": item.get("type", ""),
        "publisher_section": "",
        "section_allowed": None,
        "raw": item,
    }
    apply_aps_publication_status(paper)
    return paper


def clean_abstract(value: str | None) -> str:
    return clean_markup_text(value)


def _crossref_date(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    raw_parts = value.get("date-parts") or [[]]
    parts = raw_parts[0] if raw_parts and isinstance(raw_parts[0], list) else []
    if not parts:
        return ""
    try:
        parts = [int(part) for part in parts if part is not None]
    except (TypeError, ValueError):
        return ""
    if not parts:
        return ""
    if len(parts) == 1:
        return f"{parts[0]:04d}"
    if len(parts) == 2:
        return f"{parts[0]:04d}-{parts[1]:02d}"
    return f"{parts[0]:04d}-{parts[1]:02d}-{parts[2]:02d}"
