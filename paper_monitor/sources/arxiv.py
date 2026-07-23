from __future__ import annotations

import copy
import re
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone, tzinfo
import threading
from typing import Any
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from ..http import request_with_retries
from ..text import clean_text, normalize_doi, normalize_publication_title, safe_slug
from ..time_utils import local_timezone


ARXIV_JOURNAL_NAME = "arXiv"
ARXIV_CONDENSED_MATTER_CATEGORIES = [
    {"code": "cond-mat.dis-nn", "label": "Disordered Systems and Neural Networks"},
    {"code": "cond-mat.mes-hall", "label": "Mesoscale and Nanoscale Physics"},
    {"code": "cond-mat.mtrl-sci", "label": "Materials Science"},
    {"code": "cond-mat.other", "label": "Other Condensed Matter"},
    {"code": "cond-mat.quant-gas", "label": "Quantum Gases"},
    {"code": "cond-mat.soft", "label": "Soft Condensed Matter"},
    {"code": "cond-mat.stat-mech", "label": "Statistical Mechanics"},
    {"code": "cond-mat.str-el", "label": "Strongly Correlated Electrons"},
    {"code": "cond-mat.supr-con", "label": "Superconductivity"},
]
ARXIV_CONDENSED_MATTER_CODES = [item["code"] for item in ARXIV_CONDENSED_MATTER_CATEGORIES]
ARXIV_DISPLAY_DEFAULT_CATEGORIES = ["cond-mat.mes-hall", "cond-mat.supr-con"]
ARXIV_DEFAULT_CATEGORIES = ARXIV_CONDENSED_MATTER_CODES
ARXIV_API_TIMEOUT = 25
ARXIV_API_MAX_RETRIES = 2
ARXIV_REQUEST_INTERVAL = 3.2
ARXIV_REQUEST_LOCK = threading.Lock()
ARXIV_LAST_REQUEST_AT = 0.0
ARXIV_LATEST_LISTING_URL = "https://arxiv.org/list/cond-mat/new"
ARXIV_LATEST_LISTING_CACHE_SECONDS = 10 * 60
ARXIV_LATEST_LISTING_LOCK = threading.Lock()
ARXIV_LATEST_LISTING_CACHE: dict[str, Any] = {}

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}


def fetch_arxiv_condensed_matter(
    *,
    start_date: date,
    end_date: date,
    categories: list[str] | None = None,
    page_size: int = 200,
    max_pages: int = 3,
    force_latest: bool = False,
    require_latest_listing: bool = False,
) -> list[dict[str, Any]]:
    selected_categories = [code for code in (categories or ARXIV_DEFAULT_CATEGORIES) if code in ARXIV_CONDENSED_MATTER_CODES]
    listing_error: Exception | None = None
    try:
        listing = fetch_latest_arxiv_listing_for_window(
            start_date=start_date,
            end_date=end_date,
            categories=selected_categories or ARXIV_DEFAULT_CATEGORIES,
            force=force_latest,
        )
        if listing is not None:
            return enrich_arxiv_listing_metadata(listing)
    except Exception as exc:
        listing_error = exc
    if require_latest_listing:
        if listing_error:
            raise RuntimeError(f"arXiv latest listing check failed: {listing_error}") from listing_error
        raise RuntimeError("arXiv latest listing has not advanced to the expected announcement yet")

    papers: list[dict[str, Any]] = []
    query = arxiv_query(selected_categories or ARXIV_DEFAULT_CATEGORIES, start_date, end_date)
    try:
        for page in range(max_pages):
            wait_for_arxiv_rate_limit()
            response = request_with_retries(
                "GET",
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": query,
                    "start": page * page_size,
                    "max_results": page_size,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
                timeout=ARXIV_API_TIMEOUT,
                max_retries=ARXIV_API_MAX_RETRIES,
            )
            root = ET.fromstring(response.content)
            entries = root.findall("atom:entry", ATOM_NS)
            papers.extend(normalize_arxiv_entry(entry) for entry in entries)
            if len(entries) < page_size:
                break
            time.sleep(3)
    except Exception as api_error:
        if listing_error:
            raise RuntimeError(f"arXiv latest listing failed: {listing_error}; Export API failed: {api_error}") from api_error
        raise

    if not papers and listing_error:
        raise RuntimeError(f"arXiv latest listing failed and Export API returned no papers: {listing_error}")
    return papers


def fetch_arxiv_by_id(
    arxiv_id: str,
    *,
    timeout: int = ARXIV_API_TIMEOUT,
    max_retries: int = ARXIV_API_MAX_RETRIES,
) -> dict[str, Any] | None:
    arxiv_id = strip_arxiv_version(clean_text(arxiv_id))
    if not arxiv_id:
        return None
    wait_for_arxiv_rate_limit()
    response = request_with_retries(
        "GET",
        "https://export.arxiv.org/api/query",
        params={"id_list": arxiv_id, "max_results": 1},
        timeout=timeout,
        max_retries=max_retries,
    )
    root = ET.fromstring(response.content)
    entries = root.findall("atom:entry", ATOM_NS)
    if not entries:
        return None
    return normalize_arxiv_entry(entries[0])


def fetch_arxiv_by_ids(
    arxiv_ids: list[str],
    *,
    batch_size: int = 100,
    timeout: int = ARXIV_API_TIMEOUT,
    max_retries: int = 0,
) -> list[dict[str, Any]]:
    identifiers: list[str] = []
    for value in arxiv_ids:
        identifier = strip_arxiv_version(clean_text(value))
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)
    papers: list[dict[str, Any]] = []
    for offset in range(0, len(identifiers), max(1, int(batch_size or 100))):
        batch = identifiers[offset : offset + max(1, int(batch_size or 100))]
        wait_for_arxiv_rate_limit()
        response = request_with_retries(
            "GET",
            "https://export.arxiv.org/api/query",
            params={"id_list": ",".join(batch), "max_results": len(batch)},
            timeout=timeout,
            max_retries=max_retries,
        )
        root = ET.fromstring(response.content)
        papers.extend(normalize_arxiv_entry(entry) for entry in root.findall("atom:entry", ATOM_NS))
    return papers


def enrich_arxiv_listing_metadata(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Best-effort bulk enrichment without making the daily listing depend on API indexing."""
    identifiers = [
        strip_arxiv_version(str((paper.get("raw") or {}).get("arxiv_id") or ""))
        for paper in papers
    ]
    identifiers = [identifier for identifier in identifiers if identifier]
    if not identifiers:
        return [copy.deepcopy(paper) for paper in papers]
    try:
        details = fetch_arxiv_by_ids(identifiers)
    except Exception as exc:
        enriched = []
        for paper in papers:
            item = copy.deepcopy(paper)
            raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
            raw["metadata_detail_status"] = "pending"
            raw["metadata_detail_message"] = clean_text(str(exc))[:500]
            item["raw"] = raw
            enriched.append(item)
        return enriched

    detail_by_id = {
        strip_arxiv_version(str((paper.get("raw") or {}).get("arxiv_id") or "")): paper
        for paper in details
    }
    enriched: list[dict[str, Any]] = []
    for listing_paper in papers:
        listing = copy.deepcopy(listing_paper)
        raw = listing.get("raw") if isinstance(listing.get("raw"), dict) else {}
        identifier = strip_arxiv_version(str(raw.get("arxiv_id") or ""))
        detail = detail_by_id.get(identifier)
        if not detail:
            raw["metadata_detail_status"] = "pending"
            listing["raw"] = raw
            enriched.append(listing)
            continue
        merged = dict(listing)
        for key in ["doi", "title", "abstract", "abstract_source", "url", "landing_url", "pdf_url"]:
            value = detail.get(key)
            if value not in (None, ""):
                merged[key] = value
        detail_raw = detail.get("raw") if isinstance(detail.get("raw"), dict) else {}
        merged_raw = {**raw, **detail_raw}
        merged_raw["metadata_source"] = "arxiv_latest_listing+id_list"
        merged_raw["metadata_detail_status"] = "complete"
        # The listing date is the authoritative announcement date for the user's
        # local calendar, even if the API's submitted timestamp maps differently.
        merged["publication_date"] = listing.get("publication_date")
        merged["raw"] = merged_raw
        enriched.append(merged)
    return enriched


def search_arxiv_works(
    *,
    query: str,
    start_date: date,
    end_date: date,
    page_size: int = 50,
    max_pages: int = 1,
) -> list[dict[str, Any]]:
    query = clean_text(query)
    if not query:
        return []
    listing_error: Exception | None = None
    try:
        listing = fetch_latest_arxiv_listing_for_window(
            start_date=start_date,
            end_date=end_date,
            categories=ARXIV_DEFAULT_CATEGORIES,
        )
        if listing is not None:
            return filter_arxiv_listing_by_query(listing, query)
    except Exception as exc:
        listing_error = exc
    papers: list[dict[str, Any]] = []
    start_utc, end_utc = announcement_date_range_as_submitted_utc(start_date, end_date)
    submitted_range = f"submittedDate:[{start_utc:%Y%m%d%H%M} TO {end_utc:%Y%m%d%H%M}]"
    search_query = f"({arxiv_text_query(query)}) AND {submitted_range}"

    try:
        for page in range(max_pages):
            wait_for_arxiv_rate_limit()
            response = request_with_retries(
                "GET",
                "https://export.arxiv.org/api/query",
                params={
                    "search_query": search_query,
                    "start": page * page_size,
                    "max_results": page_size,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
                timeout=ARXIV_API_TIMEOUT,
                max_retries=ARXIV_API_MAX_RETRIES,
            )
            root = ET.fromstring(response.content)
            entries = root.findall("atom:entry", ATOM_NS)
            papers.extend(normalize_arxiv_entry(entry) for entry in entries)
            if len(entries) < page_size:
                break
            time.sleep(3)
    except Exception as api_error:
        if listing_error:
            raise RuntimeError(f"arXiv latest listing failed: {listing_error}; Export API failed: {api_error}") from api_error
        raise

    if not papers and listing_error:
        raise RuntimeError(f"arXiv latest listing failed and Export API returned no papers: {listing_error}")
    return papers


def fetch_latest_arxiv_listing_for_window(
    *,
    start_date: date,
    end_date: date,
    categories: list[str],
    local_tz: tzinfo | None = None,
    force: bool = False,
) -> list[dict[str, Any]] | None:
    listing_date, papers = fetch_latest_arxiv_listing(local_tz=local_tz, force=force)
    if listing_date is None:
        raise RuntimeError("arXiv latest listing did not include its listing date")
    target_tz = local_tz or local_timezone()
    announcement_utc = arxiv_announcement_at(listing_date - timedelta(days=1)).astimezone(timezone.utc)
    local_day = announcement_utc.astimezone(target_tz).date()
    if not (start_date <= local_day <= end_date):
        return None
    selected = set(categories)
    return [
        paper
        for paper in papers
        if selected.intersection((paper.get("raw") or {}).get("categories") or [])
    ]


def fetch_latest_arxiv_listing(
    *,
    local_tz: tzinfo | None = None,
    force: bool = False,
) -> tuple[date | None, list[dict[str, Any]]]:
    target_tz = local_tz or local_timezone()
    cache_key = str(getattr(target_tz, "key", target_tz))
    with ARXIV_LATEST_LISTING_LOCK:
        cached_at = float(ARXIV_LATEST_LISTING_CACHE.get("fetched_at") or 0.0)
        if (
            not force
            and ARXIV_LATEST_LISTING_CACHE.get("timezone") == cache_key
            and time.monotonic() - cached_at < ARXIV_LATEST_LISTING_CACHE_SECONDS
        ):
            return ARXIV_LATEST_LISTING_CACHE.get("listing_date"), [
                copy.deepcopy(paper) for paper in ARXIV_LATEST_LISTING_CACHE.get("papers") or []
            ]
        response = request_with_retries(
            "GET",
            ARXIV_LATEST_LISTING_URL,
            params={"skip": 0, "show": 2000},
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=ARXIV_API_TIMEOUT,
            max_retries=ARXIV_API_MAX_RETRIES,
        )
        listing_date, papers = parse_arxiv_latest_listing(response.text, local_tz=target_tz)
        ARXIV_LATEST_LISTING_CACHE.clear()
        ARXIV_LATEST_LISTING_CACHE.update(
            {
                "fetched_at": time.monotonic(),
                "timezone": cache_key,
                "listing_date": listing_date,
                "papers": papers,
            }
        )
        return listing_date, [copy.deepcopy(paper) for paper in papers]


def parse_arxiv_latest_listing(html: str, *, local_tz: tzinfo | None = None) -> tuple[date | None, list[dict[str, Any]]]:
    soup = BeautifulSoup(html, "html.parser")
    listing_date = arxiv_listing_date_from_soup(soup)
    if listing_date is None:
        return None, []
    target_tz = local_tz or local_timezone()
    announcement_utc = arxiv_announcement_at(listing_date - timedelta(days=1)).astimezone(timezone.utc)
    publication_date = announcement_utc.astimezone(target_tz).date().isoformat()
    papers: list[dict[str, Any]] = []
    article_lists = soup.select("dl#articles")
    if not article_lists:
        return listing_date, []
    for articles in article_lists:
        section = ""
        pending_id = ""
        for child in articles.children:
            tag_name = getattr(child, "name", None)
            if tag_name == "h3":
                heading = clean_text(child.get_text(" ", strip=True)).lower()
                if heading.startswith("new submissions"):
                    section = "new"
                elif heading.startswith(("cross-lists", "cross submissions")):
                    section = "cross"
                elif heading.startswith(("replacements", "replacement submissions")):
                    section = "replacement"
                else:
                    section = ""
                continue
            if tag_name == "dt":
                abstract_link = child.select_one('a[title="Abstract"]')
                pending_id = strip_arxiv_version(arxiv_id_from_url(str(abstract_link.get("href") or ""))) if abstract_link else ""
                continue
            if tag_name != "dd" or not pending_id:
                continue
            arxiv_id = pending_id
            pending_id = ""
            if section not in {"new", "cross"}:
                continue
            title_node = child.select_one(".list-title")
            author_node = child.select_one(".list-authors")
            subject_node = child.select_one(".list-subjects")
            primary_node = child.select_one(".list-subjects .primary-subject")
            abstract_node = child.select_one("p.mathjax")
            comment_node = child.select_one(".list-comments")
            journal_ref_node = child.select_one(".list-journal-ref")
            title = descriptor_text(title_node, "Title:") or "(Untitled)"
            subject_text = clean_text(subject_node.get_text(" ", strip=True) if subject_node else "")
            categories = re.findall(r"\(([A-Za-z-]+(?:\.[A-Za-z-]+)?)\)", subject_text)
            primary_text = clean_text(primary_node.get_text(" ", strip=True) if primary_node else "")
            primary_match = re.search(r"\(([A-Za-z-]+(?:\.[A-Za-z-]+)?)\)", primary_text)
            primary_category = primary_match.group(1) if primary_match else (categories[0] if categories else "")
            authors = [clean_text(link.get_text(" ", strip=True)) for link in (author_node.select("a") if author_node else [])]
            papers.append(
                {
                    "paper_id": "arxiv_" + safe_slug(arxiv_id, 90),
                    "doi": "",
                    "title": normalize_publication_title(title) or "(Untitled)",
                    "journal": ARXIV_JOURNAL_NAME,
                    "publication_date": publication_date,
                    "abstract": clean_text(abstract_node.get_text(" ", strip=True) if abstract_node else ""),
                    "abstract_source": "arxiv",
                    "url": f"https://arxiv.org/abs/{arxiv_id}",
                    "landing_url": f"https://arxiv.org/abs/{arxiv_id}",
                    "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}",
                    "source": "arxiv",
                    "type": "preprint",
                    "type_crossref": "",
                    "publisher_section": "preprint",
                    "section_allowed": True,
                    "raw": {
                        "arxiv_id": arxiv_id,
                        "versioned_arxiv_id": arxiv_id,
                        "authors": [author for author in authors if author],
                        "categories": categories,
                        "primary_category": primary_category,
                        "published": "",
                        "updated": "",
                        "announcement_at_utc": announcement_utc.isoformat(timespec="seconds"),
                        "journal_ref": descriptor_text(journal_ref_node, "Journal-ref:"),
                        "comment": descriptor_text(comment_node, "Comments:"),
                        "metadata_source": "arxiv_latest_listing",
                    },
                }
            )
    return listing_date, papers


def arxiv_listing_date_from_soup(soup: BeautifulSoup) -> date | None:
    for heading in soup.select("h3"):
        text = clean_text(heading.get_text(" ", strip=True))
        match = re.search(r"Showing new listings for [A-Za-z]+,\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text)
        if not match:
            continue
        month_lookup = {
            name: index
            for index, name in enumerate(
                [
                    "",
                    "January",
                    "February",
                    "March",
                    "April",
                    "May",
                    "June",
                    "July",
                    "August",
                    "September",
                    "October",
                    "November",
                    "December",
                ]
            )
        }
        month = month_lookup.get(match.group(2))
        if month:
            return date(int(match.group(3)), month, int(match.group(1)))
    return None


def descriptor_text(node: Any, descriptor: str) -> str:
    if not node:
        return ""
    text = clean_text(node.get_text(" ", strip=True))
    return clean_text(text[len(descriptor):]) if text.lower().startswith(descriptor.lower()) else text


def filter_arxiv_listing_by_query(papers: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    terms = [term.lower() for term in re.findall(r"[A-Za-z0-9_+.-]+", clean_text(query)) if term]
    if not terms:
        return copy.deepcopy(papers)
    matches: list[dict[str, Any]] = []
    for paper in papers:
        haystack = " ".join(
            [
                str(paper.get("title") or ""),
                str(paper.get("abstract") or ""),
                " ".join((paper.get("raw") or {}).get("categories") or []),
            ]
        ).lower()
        if all(term in haystack for term in terms[:8]):
            matches.append(copy.deepcopy(paper))
    return matches


def wait_for_arxiv_rate_limit() -> None:
    global ARXIV_LAST_REQUEST_AT
    with ARXIV_REQUEST_LOCK:
        now = time.monotonic()
        elapsed = now - ARXIV_LAST_REQUEST_AT
        if elapsed < ARXIV_REQUEST_INTERVAL:
            time.sleep(ARXIV_REQUEST_INTERVAL - elapsed)
        ARXIV_LAST_REQUEST_AT = time.monotonic()


def arxiv_query(categories: list[str], start_date: date, end_date: date) -> str:
    category_query = " OR ".join(f"cat:{code}" for code in categories)
    start_utc, end_utc = announcement_date_range_as_submitted_utc(start_date, end_date)
    submitted_range = f"submittedDate:[{start_utc:%Y%m%d%H%M} TO {end_utc:%Y%m%d%H%M}]"
    return f"({category_query}) AND {submitted_range}"


def arxiv_text_query(query: str) -> str:
    terms = [term for term in re.findall(r"[A-Za-z0-9_+.-]+", clean_text(query)) if term]
    if not terms:
        return "all:*"
    return " AND ".join(f"all:{term}" for term in terms[:8])


def announcement_date_range_as_submitted_utc(
    start_date: date,
    end_date: date,
    *,
    local_tz: tzinfo | None = None,
) -> tuple[datetime, datetime]:
    windows = [
        arxiv_submission_window_for_announcement_day(announcement_day)
        for announcement_day in local_arxiv_announcement_days(start_date, end_date, local_tz=local_tz)
    ]
    if not windows:
        # This only happens for local dates that cannot contain an arXiv announcement.
        # Return an empty one-minute range instead of accidentally querying a whole day.
        start_local = datetime.combine(start_date, datetime_time.min, tzinfo=local_tz or local_timezone())
        start_utc = start_local.astimezone(timezone.utc)
        return start_utc, start_utc
    return min(window[0] for window in windows), max(window[1] for window in windows)


def local_arxiv_announcement_days(
    start_date: date,
    end_date: date,
    *,
    local_tz: tzinfo | None = None,
) -> list[date]:
    eastern = ZoneInfo("America/New_York")
    target_tz = local_tz or local_timezone()
    days: list[date] = []
    current = start_date - timedelta(days=2)
    stop = end_date + timedelta(days=2)
    while current <= stop:
        if is_arxiv_announcement_day(current):
            announcement = datetime.combine(current, datetime_time(hour=20), tzinfo=eastern)
            local_day = announcement.astimezone(target_tz).date()
            if start_date <= local_day <= end_date:
                days.append(current)
        current += timedelta(days=1)
    return days


def arxiv_submission_window_for_announcement_day(announcement_day: date) -> tuple[datetime, datetime]:
    eastern = ZoneInfo("America/New_York")
    weekday = announcement_day.weekday()
    if weekday == 6:
        start_day = announcement_day - timedelta(days=3)
        end_day = announcement_day - timedelta(days=2)
    elif weekday == 0:
        start_day = announcement_day - timedelta(days=3)
        end_day = announcement_day
    else:
        start_day = announcement_day - timedelta(days=1)
        end_day = announcement_day
    start_local = datetime.combine(start_day, datetime_time(hour=14), tzinfo=eastern)
    end_local = datetime.combine(end_day, datetime_time(hour=14), tzinfo=eastern)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def is_arxiv_announcement_day(day: date) -> bool:
    # arXiv announces new submissions Sunday through Thursday at 20:00
    # America/New_York time.  The Sunday announcement is the batch shown on
    # Monday in Asian (and UTC) calendars, so it must not be treated as a
    # weekend gap here.
    return day.weekday() in {0, 1, 2, 3, 6}


def arxiv_announcement_at(announcement_day: date) -> datetime:
    return datetime.combine(
        announcement_day,
        datetime_time(hour=20),
        tzinfo=ZoneInfo("America/New_York"),
    )


def latest_ready_arxiv_announcement(now: datetime, *, buffer: timedelta = timedelta(0)) -> datetime:
    """Return the most recent scheduled announcement whose buffer has elapsed."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    eastern_now = now.astimezone(ZoneInfo("America/New_York"))
    for offset in range(8):
        candidate_day = eastern_now.date() - timedelta(days=offset)
        if not is_arxiv_announcement_day(candidate_day):
            continue
        candidate = arxiv_announcement_at(candidate_day)
        if candidate + buffer <= eastern_now:
            return candidate
    raise RuntimeError("Could not resolve the latest arXiv announcement")


def normalize_arxiv_entry(entry: ET.Element) -> dict[str, Any]:
    versioned_arxiv_id = arxiv_id_from_url(atom_text(entry, "id"))
    arxiv_id = strip_arxiv_version(versioned_arxiv_id)
    title = normalize_publication_title(atom_text(entry, "title")) or "(Untitled)"
    published = atom_text(entry, "published")
    updated = atom_text(entry, "updated")
    authors = [clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS)) for author in entry.findall("atom:author", ATOM_NS)]
    authors = [author for author in authors if author]
    categories = [
        clean_text(category.attrib.get("term"))
        for category in entry.findall("atom:category", ATOM_NS)
        if category.attrib.get("term")
    ]
    primary = entry.find("arxiv:primary_category", ATOM_NS)
    primary_category = clean_text(primary.attrib.get("term")) if primary is not None else (categories[0] if categories else "")
    abstract_url = atom_text(entry, "id") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "")
    pdf_url = arxiv_pdf_url(entry, arxiv_id)
    doi = normalize_doi(entry.findtext("arxiv:doi", default="", namespaces=ATOM_NS))
    paper_id = "arxiv_" + safe_slug(arxiv_id or title, 90)

    return {
        "paper_id": paper_id,
        "doi": doi,
        "title": title,
        "journal": ARXIV_JOURNAL_NAME,
        "publication_date": arxiv_announcement_local_date(published or updated),
        "abstract": atom_text(entry, "summary"),
        "abstract_source": "arxiv",
        "url": abstract_url,
        "landing_url": abstract_url,
        "pdf_url": pdf_url,
        "source": "arxiv",
        "type": "preprint",
        "type_crossref": "",
        "publisher_section": "preprint",
        "section_allowed": True,
        "raw": {
            "arxiv_id": arxiv_id,
            "versioned_arxiv_id": versioned_arxiv_id,
            "authors": authors,
            "categories": categories,
            "primary_category": primary_category,
            "published": published,
            "updated": updated,
            "announcement_at_utc": arxiv_announcement_utc(published or updated),
            "journal_ref": clean_text(entry.findtext("arxiv:journal_ref", default="", namespaces=ATOM_NS)),
            "comment": clean_text(entry.findtext("arxiv:comment", default="", namespaces=ATOM_NS)),
        },
    }


def atom_text(entry: ET.Element, tag: str) -> str:
    return clean_text(entry.findtext(f"atom:{tag}", default="", namespaces=ATOM_NS))


def arxiv_id_from_url(value: str) -> str:
    value = clean_text(value)
    if "/abs/" in value:
        return value.rsplit("/abs/", 1)[-1]
    return value.rsplit("/", 1)[-1] if value else ""


def strip_arxiv_version(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", clean_text(arxiv_id))


def local_date_part(value: str) -> str:
    value = clean_text(value)
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(local_timezone()).date().isoformat()


def arxiv_announcement_local_date(value: str, *, local_tz: tzinfo | None = None) -> str:
    parsed = parse_arxiv_datetime(value)
    if not parsed:
        return clean_text(value)[:10]
    eastern = ZoneInfo("America/New_York")
    submitted = parsed.astimezone(eastern)
    announcement_day = arxiv_announcement_day_for_submission(submitted)
    announcement = datetime.combine(announcement_day, datetime_time(hour=20), tzinfo=eastern)
    return announcement.astimezone(local_tz or local_timezone()).date().isoformat()


def arxiv_announcement_utc(value: str) -> str:
    parsed = parse_arxiv_datetime(value)
    if not parsed:
        return ""
    submitted = parsed.astimezone(ZoneInfo("America/New_York"))
    announcement_day = arxiv_announcement_day_for_submission(submitted)
    return arxiv_announcement_at(announcement_day).astimezone(timezone.utc).isoformat(timespec="seconds")


def arxiv_local_date_from_raw(raw: dict[str, Any], *, local_tz: tzinfo | None = None) -> str:
    target_tz = local_tz or local_timezone()
    announcement = parse_arxiv_datetime(str(raw.get("announcement_at_utc") or ""))
    if announcement:
        return announcement.astimezone(target_tz).date().isoformat()
    submitted_value = str(raw.get("published") or raw.get("updated") or "")
    return arxiv_announcement_local_date(submitted_value, local_tz=target_tz) if submitted_value else ""


def arxiv_announcement_day_for_submission(submitted: datetime) -> date:
    submitted_day = submitted.date()
    before_cutoff = submitted.time() <= datetime_time(hour=14)
    weekday = submitted_day.weekday()
    if weekday in {0, 1, 2}:
        return submitted_day if before_cutoff else submitted_day + timedelta(days=1)
    if weekday == 3:
        return submitted_day if before_cutoff else submitted_day + timedelta(days=3)
    if weekday == 4:
        return submitted_day + timedelta(days=2) if before_cutoff else submitted_day + timedelta(days=3)
    if weekday == 5:
        return submitted_day + timedelta(days=2)
    return submitted_day + timedelta(days=1)


def parse_arxiv_datetime(value: str) -> datetime | None:
    value = clean_text(value)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def arxiv_pdf_url(entry: ET.Element, arxiv_id: str) -> str:
    for link in entry.findall("atom:link", ATOM_NS):
        title = clean_text(link.attrib.get("title")).lower()
        content_type = clean_text(link.attrib.get("type")).lower()
        href = clean_text(link.attrib.get("href"))
        if href and (title == "pdf" or "pdf" in content_type):
            return href
    return f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else ""
