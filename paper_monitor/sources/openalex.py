from __future__ import annotations

import os
import re
import threading
import time
from datetime import date
from typing import Any
from urllib.parse import quote, urlparse

import requests

from ..aps import apply_aps_publication_status
from ..http import request_with_retries
from ..text import clean_markup_text, clean_text, journal_name_for_doi, make_paper_id, normalize_doi, normalize_publication_title


OPENALEX_API_KEY_SETTING = "openalex_api_key"
OPENALEX_RATE_STATUS_TTL_SECONDS = 300
OPENALEX_AUTHOR_EXCLUDED_SOURCE_NAMES = frozenset({"harvard dataverse"})
_OPENALEX_STATE_LOCK = threading.RLock()
_OPENALEX_RUNTIME_API_KEY = ""
_OPENALEX_RATE_STATUS: dict[str, Any] = {}


class OpenAlexDailyLimitError(RuntimeError):
    pass


def openalex_mailto_param() -> str | None:
    mailto = clean_text(os.getenv("OPENALEX_MAILTO", ""))
    if not mailto or mailto.lower() == "your_email@example.com" or "@" not in mailto:
        return None
    return mailto


def openalex_api_key_param() -> str | None:
    with _OPENALEX_STATE_LOCK:
        runtime_key = _OPENALEX_RUNTIME_API_KEY
    if runtime_key:
        return runtime_key
    api_key = clean_text(os.getenv("OPENALEX_API_KEY", ""))
    return api_key or None


def configure_openalex_api_key(api_key: str | None) -> None:
    global _OPENALEX_RUNTIME_API_KEY, _OPENALEX_RATE_STATUS
    normalized = clean_text(api_key or "")
    with _OPENALEX_STATE_LOCK:
        if normalized != _OPENALEX_RUNTIME_API_KEY:
            _OPENALEX_RATE_STATUS = {}
        _OPENALEX_RUNTIME_API_KEY = normalized


def openalex_rate_limit_snapshot() -> dict[str, Any]:
    with _OPENALEX_STATE_LOCK:
        snapshot = dict(_OPENALEX_RATE_STATUS)
    snapshot["configured"] = bool(openalex_api_key_param())
    snapshot["paused"] = bool(snapshot.get("paused"))
    return snapshot


def _normalize_openalex_rate_status(payload: Any) -> dict[str, Any]:
    outer = payload if isinstance(payload, dict) else {}
    rate = outer.get("rate_limit") if isinstance(outer.get("rate_limit"), dict) else outer

    def number(name: str) -> float | None:
        try:
            value = rate.get(name)
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    raw_costs = (
        rate.get("endpoint_costs_usd")
        if isinstance(rate.get("endpoint_costs_usd"), dict)
        else {}
    )
    endpoint_costs_usd: dict[str, float] = {}
    for name, value in raw_costs.items():
        try:
            endpoint_costs_usd[clean_text(name)] = float(value)
        except (TypeError, ValueError):
            continue
    return {
        "daily_budget_usd": number("daily_budget_usd"),
        "daily_used_usd": number("daily_used_usd"),
        "daily_remaining_usd": number("daily_remaining_usd"),
        "prepaid_balance_usd": number("prepaid_balance_usd"),
        "prepaid_remaining_usd": number("prepaid_remaining_usd"),
        "resets_at": clean_text(rate.get("resets_at") or ""),
        "resets_in_seconds": int(number("resets_in_seconds") or 0),
        "endpoint_costs_usd": endpoint_costs_usd,
        "checked_at_monotonic": time.monotonic(),
        "paused": (
            number("daily_remaining_usd") is not None
            and float(number("daily_remaining_usd") or 0) <= 0
        ),
    }


def refresh_openalex_rate_limit_status(
    api_key: str | None = None,
    *,
    timeout: int = 12,
    record: bool = True,
) -> dict[str, Any]:
    key = clean_text(api_key or openalex_api_key_param() or "")
    if not key:
        return {"configured": False, "status": "not_configured", "paused": False}
    response = request_with_retries(
        "GET",
        "https://api.openalex.org/rate-limit",
        params={"api_key": key},
        timeout=timeout,
        max_retries=1,
    )
    status = _normalize_openalex_rate_status(response.json())
    status.update({"configured": True, "status": "connected", "ok": True})
    if record:
        global _OPENALEX_RATE_STATUS
        with _OPENALEX_STATE_LOCK:
            _OPENALEX_RATE_STATUS = dict(status)
    return dict(status)


def test_openalex_api_key(api_key: str) -> dict[str, Any]:
    key = clean_text(api_key)
    if not key:
        return {
            "configured": False,
            "status": "not_configured",
            "ok": False,
            "paused": False,
        }
    try:
        return refresh_openalex_rate_limit_status(key, record=False)
    except Exception:
        return {
            "configured": bool(openalex_api_key_param()),
            "status": "invalid",
            "ok": False,
            "paused": False,
        }


def _openalex_request_cost_usd(url: str, params: dict[str, Any]) -> float:
    path = urlparse(url).path.rstrip("/")
    if re.search(r"/(works|authors|sources|institutions|topics)/[^/]+$", path):
        return 0.0
    costs = openalex_rate_limit_snapshot().get("endpoint_costs_usd")
    costs = costs if isinstance(costs, dict) else {}
    if "semantic" in path:
        return float(costs.get("semantic") or 0.01)
    if clean_text(params.get("search") or ""):
        return float(costs.get("search") or 0.001)
    return float(costs.get("list") or 0.0001)


def _openalex_reserve_free_budget(url: str, params: dict[str, Any]) -> float:
    key = openalex_api_key_param()
    if not key:
        return 0.0
    cost = _openalex_request_cost_usd(url, params)
    if cost <= 0:
        return 0.0
    snapshot = openalex_rate_limit_snapshot()
    checked_at = float(snapshot.get("checked_at_monotonic") or 0)
    if not checked_at or time.monotonic() - checked_at > OPENALEX_RATE_STATUS_TTL_SECONDS:
        snapshot = refresh_openalex_rate_limit_status(key)
    remaining = snapshot.get("daily_remaining_usd")
    if snapshot.get("paused") or (
        remaining is not None and float(remaining) + 1e-12 < cost
    ):
        raise OpenAlexDailyLimitError(
            "OpenAlex free daily allowance is exhausted; waiting for the UTC reset"
        )
    if remaining is not None:
        global _OPENALEX_RATE_STATUS
        with _OPENALEX_STATE_LOCK:
            current = float(
                _OPENALEX_RATE_STATUS.get("daily_remaining_usd")
                if _OPENALEX_RATE_STATUS.get("daily_remaining_usd") is not None
                else remaining
            )
            if current + 1e-12 < cost:
                _OPENALEX_RATE_STATUS["paused"] = True
                raise OpenAlexDailyLimitError(
                    "OpenAlex free daily allowance is exhausted; waiting for the UTC reset"
                )
            _OPENALEX_RATE_STATUS["daily_remaining_usd"] = max(0.0, current - cost)
            _OPENALEX_RATE_STATUS["paused"] = current - cost <= 0
    return cost


def apply_openalex_auth(params: dict[str, Any]) -> dict[str, Any]:
    api_key = openalex_api_key_param()
    if api_key:
        params["api_key"] = api_key
    mailto = openalex_mailto_param()
    if mailto:
        params["mailto"] = mailto
    return params


def openalex_request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    stream: bool = False,
) -> requests.Response:
    request_params = dict(params or {})
    apply_openalex_auth(request_params)
    _openalex_reserve_free_budget(url, request_params)
    try:
        return request_with_retries(
            method,
            url,
            params=request_params or None,
            headers=headers,
            timeout=timeout,
            max_retries=max_retries,
            retry_on_429=False,
            stream=stream,
        )
    except RuntimeError as exc:
        if "HTTP 429" in str(exc):
            global _OPENALEX_RATE_STATUS
            with _OPENALEX_STATE_LOCK:
                _OPENALEX_RATE_STATUS["paused"] = True
                _OPENALEX_RATE_STATUS["status"] = "daily_limit_reached"
            raise OpenAlexDailyLimitError(
                "OpenAlex is rate limited; waiting for the UTC reset"
            ) from exc
        raise


def fetch_openalex_journal(
    *,
    journal_name: str,
    source_id: str,
    start_date: date,
    end_date: date,
    per_page: int = 100,
    max_pages: int = 10,
    timeout: int = 30,
    max_retries: int = 3,
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
        }
        apply_openalex_auth(params)
        response = openalex_request(
            "GET",
            "https://api.openalex.org/works",
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        data = response.json()
        results = data.get("results", [])
        papers.extend(normalize_openalex_item(item, journal_name) for item in results)
        next_cursor = data.get("meta", {}).get("next_cursor")
        if not next_cursor or next_cursor == cursor or len(results) < per_page:
            break
        cursor = next_cursor

    return papers


def fetch_openalex_work_by_doi(
    doi: str,
    *,
    journal_name: str = "Unknown Journal",
    timeout: int = 10,
) -> dict[str, Any] | None:
    """Fetch one work through OpenAlex's zero-cost entity endpoint.

    This is intentionally an exact DOI lookup rather than a title search or a
    paginated list request.  It is used as a conservative metadata fallback
    before visiting a publisher page.
    """
    normalized_doi = normalize_doi(doi)
    if not normalized_doi:
        return None
    openalex_id = quote(f"https://doi.org/{normalized_doi}", safe="")
    response = openalex_request(
        "GET",
        f"https://api.openalex.org/works/{openalex_id}",
        timeout=timeout,
        # request_with_retries counts total attempts, so 1 means no retry.
        max_retries=1,
    )
    item = response.json()
    if not isinstance(item, dict) or not item.get("id"):
        return None
    return normalize_openalex_item(item, journal_name)


def search_openalex_works(
    *,
    query: str,
    start_date: date,
    end_date: date,
    per_page: int = 50,
    max_pages: int = 2,
    timeout: int = 10,
    max_retries: int = 1,
) -> list[dict[str, Any]]:
    cleaned_query = clean_text(query)
    if not cleaned_query:
        return []

    papers: list[dict[str, Any]] = []
    cursor = "*"
    for _ in range(max_pages):
        params = {
            "search": cleaned_query,
            "filter": f"from_publication_date:{start_date.isoformat()},to_publication_date:{end_date.isoformat()}",
            "per-page": max(1, min(100, int(per_page or 50))),
            "cursor": cursor,
            "sort": "publication_date:desc",
        }
        apply_openalex_auth(params)
        response = openalex_request(
            "GET",
            "https://api.openalex.org/works",
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        data = response.json()
        results = data.get("results", [])
        papers.extend(
            normalize_openalex_item(
                item,
                normalize_openalex_journal_name(((item.get("primary_location") or {}).get("source") or {}).get("display_name"))
                or "Unknown Journal",
            )
            for item in results
        )
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
    author_params = {
        "search": query,
        "per-page": max(1, min(25, int(max_authors or 6))),
    }
    apply_openalex_auth(author_params)
    author_response = openalex_request(
        "GET",
        "https://api.openalex.org/authors",
        params=author_params,
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
        params = {
            "filter": f"authorships.author.id:{author_id}",
            "per-page": max(1, min(50, int(per_author or 20))),
            "sort": "publication_date:desc",
        }
        apply_openalex_auth(params)
        response = openalex_request(
            "GET",
            "https://api.openalex.org/works",
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        for item in response.json().get("results", []):
            if not isinstance(item, dict):
                continue
            if openalex_author_work_is_excluded(item):
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


def normalize_openalex_author_id(value: Any) -> str:
    text = clean_text(value).rstrip("/")
    if not text:
        return ""
    author_id = text.rsplit("/", 1)[-1].upper()
    return author_id if re.fullmatch(r"A\d+", author_id) else ""


def openalex_author_profile(item: dict[str, Any]) -> dict[str, Any]:
    author_id = normalize_openalex_author_id(item.get("id"))
    institutions = item.get("last_known_institutions") or []
    affiliation = ""
    for institution in institutions:
        if isinstance(institution, dict) and clean_text(institution.get("display_name")):
            affiliation = clean_text(institution.get("display_name"))
            break
    if not affiliation:
        affiliations = openalex_affiliation_strings(item)
        affiliation = affiliations[0] if affiliations else ""
    orcid = clean_text(item.get("orcid")).rstrip("/").rsplit("/", 1)[-1]
    return {
        "openalex_author_id": author_id,
        "name": clean_text(item.get("display_name")),
        "affiliation": affiliation,
        "orcid": orcid if re.fullmatch(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]", orcid, re.I) else "",
        "works_count": int(item.get("works_count") or 0),
        "cited_by_count": int(item.get("cited_by_count") or 0),
    }


def search_openalex_authors(
    author_name: str,
    *,
    affiliations: list[str] | None = None,
    limit: int = 12,
    timeout: int = 20,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    query = clean_text(author_name)
    if not query:
        return []
    params: dict[str, Any] = {
        "search": query,
        "per-page": max(1, min(25, int(limit or 12))),
    }
    apply_openalex_auth(params)
    response = openalex_request(
        "GET",
        "https://api.openalex.org/authors",
        params=params,
        timeout=timeout,
        max_retries=max_retries,
    )
    affiliation_terms = [
        clean_text(value) for value in (affiliations or []) if clean_text(value)
    ]
    profiles: list[dict[str, Any]] = []
    for item in response.json().get("results", []):
        if not isinstance(item, dict):
            continue
        profile = openalex_author_profile(item)
        if not profile.get("openalex_author_id") or not profile.get("name"):
            continue
        if affiliation_terms and not openalex_author_affiliation_matches(item, affiliation_terms):
            continue
        profiles.append(profile)
    return profiles[: max(1, int(limit or 12))]


def fetch_openalex_author_profile(
    author_id: str,
    *,
    timeout: int = 20,
    max_retries: int = 3,
) -> dict[str, Any]:
    normalized_id = normalize_openalex_author_id(author_id)
    if not normalized_id:
        raise ValueError("A valid OpenAlex author ID is required")
    params: dict[str, Any] = {}
    apply_openalex_auth(params)
    response = openalex_request(
        "GET",
        f"https://api.openalex.org/authors/{normalized_id}",
        params=params or None,
        timeout=timeout,
        max_retries=max_retries,
    )
    item = response.json()
    if not isinstance(item, dict):
        raise ValueError("OpenAlex did not return an author profile")
    profile = openalex_author_profile(item)
    if not profile.get("openalex_author_id"):
        raise ValueError("OpenAlex did not return a valid author profile")
    return profile


def fetch_openalex_author_publications(
    author_id: str,
    *,
    limit: int = 5000,
    sort_by_date: bool = False,
    timeout: int = 30,
    max_retries: int = 3,
) -> list[dict[str, Any]]:
    normalized_id = normalize_openalex_author_id(author_id)
    if not normalized_id:
        raise ValueError("A valid OpenAlex author ID is required")
    remaining = max(1, int(limit or 1))
    cursor = "*"
    papers: list[dict[str, Any]] = []
    while remaining > 0:
        per_page = min(100, remaining)
        params: dict[str, Any] = {
            "filter": f"authorships.author.id:{normalized_id}",
            "per-page": per_page,
            "cursor": cursor,
            "sort": "publication_date:desc" if sort_by_date else "cited_by_count:desc",
        }
        apply_openalex_auth(params)
        response = openalex_request(
            "GET",
            "https://api.openalex.org/works",
            params=params,
            timeout=timeout,
            max_retries=max_retries,
        )
        data = response.json()
        results = data.get("results", []) if isinstance(data, dict) else []
        for item in results:
            if not isinstance(item, dict):
                continue
            if openalex_author_work_is_excluded(item):
                continue
            papers.append(normalize_openalex_item(item, "Unknown Journal"))
        remaining -= len(results)
        next_cursor = (data.get("meta") or {}).get("next_cursor") if isinstance(data, dict) else None
        if not results or len(results) < per_page or not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
    return papers


def openalex_author_work_is_excluded(item: dict[str, Any]) -> bool:
    """Return True for repository records that are not Author Monitor papers."""
    if not isinstance(item, dict):
        return False
    raw = item.get("raw") if isinstance(item.get("raw"), dict) else item
    source_names = [
        clean_text(item.get("journal")),
        clean_text(((raw.get("primary_location") or {}).get("source") or {}).get("display_name")),
        clean_text(((raw.get("best_oa_location") or {}).get("source") or {}).get("display_name")),
    ]
    for location in raw.get("locations") or []:
        if isinstance(location, dict):
            source_names.append(
                clean_text(((location.get("source") or {}).get("display_name")))
            )
    return any(
        source_name.lower() in OPENALEX_AUTHOR_EXCLUDED_SOURCE_NAMES
        for source_name in source_names
        if source_name
    )


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
    title = normalize_publication_title(clean_markup_text(item.get("title"))) or "(Untitled)"
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
    journal = journal_name_for_doi(journal, doi) or "Unknown Journal"

    paper = {
        "paper_id": paper_id,
        "doi": doi,
        "title": title,
        "journal": journal,
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
    apply_aps_publication_status(paper)
    return paper


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
