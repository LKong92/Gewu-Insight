from __future__ import annotations

import hashlib
from html import unescape
import re
from typing import Any

from bs4 import BeautifulSoup


def clean_text(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def clean_markup_text(value: Any) -> str:
    text = unescape(clean_text(value))
    if "<" not in text or ">" not in text:
        return text

    soup = BeautifulSoup(text, "html.parser")
    for math in soup.find_all(lambda tag: tag.name and tag.name.lower().endswith("math")):
        math.replace_with(_mathml_text(math))
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+([,.;:!?%)\]}])", r"\1", text)
    text = re.sub(r"([({\[])\s+", r"\1", text)
    return clean_text(text)


def _mathml_text(math: Any) -> str:
    text = "".join(math.stripped_strings)
    return clean_text(unescape(text))


def first_text(value: Any) -> str:
    if isinstance(value, list) and value:
        return clean_text(value[0])
    return clean_text(value)


def safe_slug(value: str, max_len: int = 80) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", clean_text(value).lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug or "untitled")[:max_len].strip("-")


def sha1_short(value: str, length: int = 12) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def make_paper_id(doi: str | None, title: str | None, journal: str | None, publication_date: str | None) -> str:
    if doi:
        normalized = doi.lower().removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        return "doi_" + sha1_short(normalized, 16)
    key = "|".join([clean_text(title).lower(), clean_text(journal).lower(), clean_text(publication_date)])
    return "p_" + sha1_short(key, 16)


def normalize_doi(value: str | None) -> str:
    doi = clean_text(value)
    if not doi:
        return ""
    doi = doi.removeprefix("https://doi.org/")
    doi = doi.removeprefix("http://doi.org/")
    return doi.lower()
