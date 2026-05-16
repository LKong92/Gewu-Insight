from __future__ import annotations

import re
import time
from datetime import date, datetime, time as datetime_time, timezone, tzinfo
from typing import Any
import xml.etree.ElementTree as ET

from ..http import request_with_retries
from ..text import clean_text, normalize_doi, safe_slug


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
ARXIV_DEFAULT_CATEGORIES = ["cond-mat.mes-hall", "cond-mat.supr-con"]

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
) -> list[dict[str, Any]]:
    papers: list[dict[str, Any]] = []
    selected_categories = [code for code in (categories or ARXIV_DEFAULT_CATEGORIES) if code in ARXIV_CONDENSED_MATTER_CODES]
    query = arxiv_query(selected_categories or ARXIV_DEFAULT_CATEGORIES, start_date, end_date)

    for page in range(max_pages):
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
            timeout=30,
        )
        root = ET.fromstring(response.content)
        entries = root.findall("atom:entry", ATOM_NS)
        papers.extend(normalize_arxiv_entry(entry) for entry in entries)
        if len(entries) < page_size:
            break
        time.sleep(3)

    return papers


def arxiv_query(categories: list[str], start_date: date, end_date: date) -> str:
    category_query = " OR ".join(f"cat:{code}" for code in categories)
    start_utc, end_utc = local_date_range_as_utc(start_date, end_date)
    submitted_range = f"submittedDate:[{start_utc:%Y%m%d%H%M} TO {end_utc:%Y%m%d%H%M}]"
    return f"({category_query}) AND {submitted_range}"


def local_date_range_as_utc(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    tz = local_timezone()
    start_local = datetime.combine(start_date, datetime_time.min, tzinfo=tz)
    end_local = datetime.combine(end_date, datetime_time(hour=23, minute=59), tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def local_timezone() -> tzinfo:
    return datetime.now().astimezone().tzinfo or timezone.utc


def normalize_arxiv_entry(entry: ET.Element) -> dict[str, Any]:
    versioned_arxiv_id = arxiv_id_from_url(atom_text(entry, "id"))
    arxiv_id = strip_arxiv_version(versioned_arxiv_id)
    title = atom_text(entry, "title") or "(Untitled)"
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
        "publication_date": local_date_part(published or updated),
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


def arxiv_pdf_url(entry: ET.Element, arxiv_id: str) -> str:
    for link in entry.findall("atom:link", ATOM_NS):
        title = clean_text(link.attrib.get("title")).lower()
        content_type = clean_text(link.attrib.get("type")).lower()
        href = clean_text(link.attrib.get("href"))
        if href and (title == "pdf" or "pdf" in content_type):
            return href
    return f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else ""
