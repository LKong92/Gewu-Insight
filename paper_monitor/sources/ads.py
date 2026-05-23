from __future__ import annotations

from typing import Any

from ..http import request_with_retries
from ..text import clean_text


ADS_SEARCH_URL = "https://api.adsabs.harvard.edu/v1/search/query"


def fetch_ads_record_by_identifier(
    identifier: str,
    token: str,
    *,
    timeout: int = 20,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    identifier = clean_text(identifier)
    token = clean_text(token)
    if not identifier or not token:
        return None
    fields = [
        "bibcode",
        "title",
        "doi",
        "identifier",
        "alternate_bibcode",
        "citation_count",
        "read_count",
        "reference_count",
        "property",
        "doctype",
        "pub",
        "year",
        "volume",
        "page",
        "author",
        "pubdate",
        "links_data",
    ]
    response = request_with_retries(
        "GET",
        ADS_SEARCH_URL,
        params={
            "q": f'identifier:"{identifier}"',
            "fl": ",".join(fields),
            "rows": 1,
            "sort": "date desc",
        },
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
        max_retries=max_retries,
    )
    docs = response.json().get("response", {}).get("docs") or []
    for doc in docs:
        if isinstance(doc, dict) and clean_text(doc.get("bibcode") or ""):
            return doc
    return None


def test_ads_token(token: str, *, timeout: int = 12) -> bool:
    token = clean_text(token)
    if not token:
        return False
    response = request_with_retries(
        "GET",
        ADS_SEARCH_URL,
        params={"q": "bibstem:ApJ", "fl": "bibcode", "rows": 1},
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
        max_retries=1,
    )
    return response.status_code == 200
