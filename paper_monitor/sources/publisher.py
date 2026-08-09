from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..aps import APS_CANONICAL_NAMES_BY_SLUG, aps_journal_slug
from ..http import USER_AGENT
from .crossref import fetch_crossref_journal
from ..text import clean_text, make_paper_id, normalize_doi, normalize_publication_title

import requests


APS_ABSTRACT_REQUEST_INTERVAL_SECONDS = 5.0
APS_ABSTRACT_FAILURE_CACHE_SECONDS = 60 * 60
APS_ABSTRACT_BLOCK_COOLDOWN_SECONDS = 6 * 60 * 60
APS_RSS_CACHE_SECONDS = 60 * 60
APS_RSS_SUBJECT_CACHE_SECONDS = 24 * 60 * 60
APS_RSS_FAILURE_CACHE_SECONDS = 60 * 60
APS_RSS_REQUEST_INTERVAL_SECONDS = 0.25
_APS_ABSTRACT_REQUEST_LOCK = threading.Lock()
_APS_ABSTRACT_FETCH_LOCK = threading.Lock()
_APS_RSS_LOCK = threading.RLock()
_APS_ABSTRACT_LAST_REQUEST_AT = 0.0
_APS_ABSTRACT_BLOCKED_UNTIL = 0.0
_APS_RSS_LAST_REQUEST_AT = 0.0
_APS_RSS_BLOCKED_UNTIL = 0.0
_APS_ABSTRACT_CACHE: dict[str, tuple[float, str]] = {}
_APS_RSS_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_JOURNAL_FEED_LAST_REQUEST_AT: dict[str, float] = {}
_JOURNAL_FEED_BLOCKED_UNTIL: dict[str, float] = {}


@dataclass(frozen=True)
class JournalFeedDefinition:
    key: str
    publisher: str
    journal_name: str
    url: str
    parser: str = "standard"
    doi_prefixes: tuple[str, ...] = ()
    allowed_item_types: tuple[str, ...] = ()
    required_item_categories: tuple[str, ...] = ()
    include_abstract: bool = True
    source_name: str = "journal_feed"
    fallback_issns: tuple[str, ...] = ()


def aps_journal_feed_definitions() -> dict[str, JournalFeedDefinition]:
    return {
        f"aps:{slug}": JournalFeedDefinition(
            key=f"aps:{slug}",
            publisher="APS",
            journal_name=name,
            url=f"https://feeds.aps.org/rss/recent/{slug}.xml",
            parser="aps_rdf",
            doi_prefixes=("10.1103/",),
            source_name="aps_rss",
        )
        for slug, name in APS_CANONICAL_NAMES_BY_SLUG.items()
    }


def journal_feed_definitions() -> dict[str, JournalFeedDefinition]:
    """Return the curated official feeds used by Subject Monitor."""
    definitions = aps_journal_feed_definitions()
    research_item_types = (
        "research article",
        "research",
        "report",
        "reports",
        "research resource",
        "review",
        "review article",
    )
    definitions.update(
        {
            "aaas:science": JournalFeedDefinition(
                key="aaas:science",
                publisher="AAAS",
                journal_name="Science",
                url="https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=science",
                doi_prefixes=("10.1126/",),
                allowed_item_types=research_item_types,
                include_abstract=False,
            ),
            "aaas:science-advances": JournalFeedDefinition(
                key="aaas:science-advances",
                publisher="AAAS",
                journal_name="Science Advances",
                url="https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sciadv",
                doi_prefixes=("10.1126/",),
                allowed_item_types=research_item_types,
                include_abstract=False,
            ),
            "nature:nature-physics": JournalFeedDefinition(
                key="nature:nature-physics",
                publisher="Springer Nature",
                journal_name="Nature Physics",
                url="https://www.nature.com/nphys/journal/vaop/ncurrent/rss.rdf",
                doi_prefixes=("10.1038/",),
            ),
            "nature:communications-physics": JournalFeedDefinition(
                key="nature:communications-physics",
                publisher="Springer Nature",
                journal_name="Communications Physics",
                url="https://www.nature.com/commsphys.rss",
                doi_prefixes=("10.1038/",),
            ),
            "iop:new-journal-of-physics": JournalFeedDefinition(
                key="iop:new-journal-of-physics",
                publisher="IOP Publishing",
                journal_name="New Journal of Physics",
                url="https://iopscience.iop.org/journal/rss/1367-2630",
                doi_prefixes=("10.1088/",),
            ),
            "iop:reports-on-progress-in-physics": JournalFeedDefinition(
                key="iop:reports-on-progress-in-physics",
                publisher="IOP Publishing",
                journal_name="Reports on Progress in Physics",
                url="https://iopscience.iop.org/journal/rss/1361-6633",
                doi_prefixes=("10.1088/",),
            ),
            "nature:nature-reviews-physics": JournalFeedDefinition(
                key="nature:nature-reviews-physics",
                publisher="Springer Nature",
                journal_name="Nature Reviews Physics",
                url="https://www.nature.com/natrevphys.rss",
                doi_prefixes=("10.1038/",),
            ),
            "nature:npj-quantum-materials": JournalFeedDefinition(
                key="nature:npj-quantum-materials",
                publisher="Springer Nature",
                journal_name="npj Quantum Materials",
                url="https://www.nature.com/npjquantmats.rss",
                doi_prefixes=("10.1038/",),
            ),
            "iop:journal-of-physics-condensed-matter": JournalFeedDefinition(
                key="iop:journal-of-physics-condensed-matter",
                publisher="IOP Publishing",
                journal_name="Journal of Physics: Condensed Matter",
                url="https://iopscience.iop.org/journal/rss/1361-648X",
                doi_prefixes=("10.1088/",),
            ),
            "nature:npj-quantum-information": JournalFeedDefinition(
                key="nature:npj-quantum-information",
                publisher="Springer Nature",
                journal_name="npj Quantum Information",
                url="https://www.nature.com/npjqi.rss",
                doi_prefixes=("10.1038/",),
            ),
            "iop:quantum-science-and-technology": JournalFeedDefinition(
                key="iop:quantum-science-and-technology",
                publisher="IOP Publishing",
                journal_name="Quantum Science and Technology",
                url="https://iopscience.iop.org/journal/rss/2058-9565",
                doi_prefixes=("10.1088/",),
            ),
            "aip:applied-physics-letters": JournalFeedDefinition(
                key="aip:applied-physics-letters",
                publisher="AIP Publishing",
                journal_name="Applied Physics Letters",
                url="https://pubs.aip.org/rss/site_1000017/LatestOpenIssueArticles_1000011.xml",
                doi_prefixes=("10.1063/",),
            ),
            "nature:nature-materials": JournalFeedDefinition(
                key="nature:nature-materials",
                publisher="Springer Nature",
                journal_name="Nature Materials",
                url="https://www.nature.com/nmat/journal/vaop/ncurrent/rss.rdf",
                doi_prefixes=("10.1038/",),
            ),
            "nature:nature-nanotechnology": JournalFeedDefinition(
                key="nature:nature-nanotechnology",
                publisher="Springer Nature",
                journal_name="Nature Nanotechnology",
                url="https://www.nature.com/nnano/journal/vaop/ncurrent/rss.rdf",
                doi_prefixes=("10.1038/",),
            ),
            "iop:2d-materials": JournalFeedDefinition(
                key="iop:2d-materials",
                publisher="IOP Publishing",
                journal_name="2D Materials",
                url="https://iopscience.iop.org/journal/rss/2053-1583",
                doi_prefixes=("10.1088/",),
            ),
            "aip:avs-quantum-science": JournalFeedDefinition(
                key="aip:avs-quantum-science",
                publisher="AIP Publishing",
                journal_name="AVS Quantum Science",
                url="https://pubs.aip.org/rss/site_1000079/1000042.xml",
                doi_prefixes=("10.1116/",),
            ),
            "aip:journal-of-applied-physics": JournalFeedDefinition(
                key="aip:journal-of-applied-physics",
                publisher="AIP Publishing",
                journal_name="Journal of Applied Physics",
                url="https://pubs.aip.org/rss/site_1000029/LatestOpenIssueArticles_1000017.xml",
                doi_prefixes=("10.1063/",),
            ),
            "acs:nano-letters": JournalFeedDefinition(
                key="acs:nano-letters",
                publisher="American Chemical Society",
                journal_name="Nano Letters",
                url="https://pubs.acs.org/action/showFeed?type=axatoc&feed=rss&jc=nalefd",
                doi_prefixes=("10.1021/",),
                fallback_issns=("1530-6992",),
            ),
            "quantum:quantum": JournalFeedDefinition(
                key="quantum:quantum",
                publisher="Verein zur Foerderung des Open Access Publizierens in den Quantenwissenschaften",
                journal_name="Quantum",
                url="https://quantum-journal.org/feed/",
                doi_prefixes=("10.22331/",),
                required_item_categories=("paper",),
            ),
            "aip:review-of-scientific-instruments": JournalFeedDefinition(
                key="aip:review-of-scientific-instruments",
                publisher="AIP Publishing",
                journal_name="Review of Scientific Instruments",
                url="https://pubs.aip.org/aip/rsi",
                parser="aip_homepage",
                doi_prefixes=("10.1063/",),
                fallback_issns=("1089-7623",),
            ),
        }
    )
    return definitions


def enrich_aps_abstract_from_rss(paper: dict[str, Any], *, storage: Any = None) -> dict[str, Any]:
    if clean_text(paper.get("abstract") or ""):
        return paper
    journal = clean_text(paper.get("journal") or "").casefold()
    if not aps_journal_slug(journal):
        return paper
    if clean_text(paper.get("publisher_section") or "").casefold() != "published":
        return paper
    if paper.get("section_allowed") is False:
        return paper
    doi = clean_text(paper.get("doi") or "").lower()
    if not doi.startswith("10.1103/"):
        return paper

    abstract = aps_rss_abstracts(journal, storage=storage).get(doi, "")
    if abstract:
        paper["abstract"] = abstract
        paper["abstract_source"] = "aps_rss"
    return paper


def enrich_rmp_abstract_from_rss(paper: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible name for the original RMP-only helper."""
    return enrich_aps_abstract_from_rss(paper)


def aps_rss_abstracts(journal: str, *, storage: Any = None) -> dict[str, str]:
    slug = aps_journal_slug(journal)
    if not slug:
        return {}
    if storage is not None:
        sync_aps_rss_feeds(storage, journal_slugs=[slug])
        return storage.aps_rss_abstracts(slug)
    with _APS_RSS_LOCK:
        now = time.monotonic()
        cached_at, cached_abstracts = _APS_RSS_CACHE.get(slug, (0.0, {}))
        if cached_at and now - cached_at < APS_RSS_CACHE_SECONDS:
            return dict(cached_abstracts)
        try:
            response = requests.get(
                f"https://feeds.aps.org/rss/recent/{slug}.xml",
                headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml"},
                timeout=10,
                allow_redirects=True,
            )
            response.raise_for_status()
            abstracts = parse_aps_rss_abstracts(response.content)
        except (requests.RequestException, ET.ParseError):
            abstracts = {}
        _APS_RSS_CACHE[slug] = (time.monotonic(), abstracts)
        return dict(abstracts)


def parse_aps_rss_abstracts(payload: bytes | str) -> dict[str, str]:
    root = ET.fromstring(payload)
    rss = "{http://purl.org/rss/1.0/}"
    prism = "{http://prismstandard.org/namespaces/basic/2.0/}"
    abstracts: dict[str, str] = {}
    for item in root.findall(f"{rss}item"):
        doi = normalize_doi(item.findtext(f"{prism}doi") or "")
        abstract = aps_rss_item_abstract(item)
        if doi and abstract:
            abstracts[doi] = abstract
    return abstracts


def parse_aps_rss_entries(
    payload: bytes | str,
    *,
    journal_slug: str = "",
    journal_name: str = "",
) -> list[dict[str, Any]]:
    root = ET.fromstring(payload)
    rss = "{http://purl.org/rss/1.0/}"
    prism = "{http://prismstandard.org/namespaces/basic/2.0/}"
    content = "{http://purl.org/rss/1.0/modules/content/}"
    dc = "{http://purl.org/dc/elements/1.1/}"
    canonical_name = journal_name or APS_CANONICAL_NAMES_BY_SLUG.get(journal_slug, "")
    papers: list[dict[str, Any]] = []
    for item in root.findall(f"{rss}item"):
        doi_value = item.findtext(f"{prism}doi") or item.findtext(f"{dc}identifier") or ""
        doi = normalize_doi(re.sub(r"^doi:\s*", "", doi_value, flags=re.IGNORECASE))
        if not doi.startswith("10.1103/"):
            continue
        title = normalize_publication_title(
            clean_text(item.findtext(f"{dc}title") or item.findtext(f"{rss}title") or "")
        )
        if not title:
            continue
        publication_name = clean_text(item.findtext(f"{prism}publicationName") or canonical_name)
        publication_date = clean_text(
            item.findtext(f"{prism}publicationDate") or item.findtext(f"{dc}date") or ""
        )[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", publication_date):
            continue
        url = clean_text(
            item.findtext(f"{prism}url")
            or item.findtext(f"{rss}link")
            or f"https://doi.org/{doi}"
        )
        creator = clean_text(item.findtext(f"{dc}creator") or "")
        authors = aps_rss_author_names(creator)
        abstract = aps_rss_item_abstract(item)
        volume = clean_text(item.findtext(f"{prism}volume") or "")
        issue = clean_text(item.findtext(f"{prism}number") or "")
        page = clean_text(item.findtext(f"{prism}startingPage") or "")
        section = clean_text(item.findtext(f"{prism}section") or item.findtext(f"{dc}subject") or "")
        slug = journal_slug or aps_journal_slug(publication_name)
        raw = {
            "DOI": doi,
            "title": [title],
            "author": [{"name": author} for author in authors],
            "container-title": [publication_name],
            "published-online": {"date-parts": [[int(part) for part in publication_date.split("-")]]},
            "volume": volume,
            "issue": issue,
            "page": page,
            "article-number": page,
            "type": "journal-article",
            "aps_rss": {
                "journal_slug": slug,
                "creator": creator,
                "section": section,
                "publication_date": publication_date,
            },
            "_paper_monitor_sources": ["aps_rss"],
        }
        papers.append(
            {
                "paper_id": make_paper_id(doi, title, publication_name, publication_date),
                "doi": doi,
                "title": title,
                "journal": publication_name or canonical_name or "APS",
                "publication_date": publication_date,
                "abstract": abstract,
                "abstract_source": "aps_rss" if abstract else "missing",
                "url": url,
                "landing_url": url,
                "pdf_url": "",
                "source": "aps_rss",
                "type": "journal-article",
                "type_crossref": "journal-article",
                "publisher_section": "published",
                "section_allowed": True,
                "raw": raw,
            }
        )
    return papers


def parse_journal_feed_entries(
    payload: bytes | str,
    definition: JournalFeedDefinition,
) -> list[dict[str, Any]]:
    if definition.parser == "aps_rdf":
        return parse_aps_rss_entries(
            payload,
            journal_slug=definition.key.removeprefix("aps:"),
            journal_name=definition.journal_name,
        )
    if definition.parser not in {"standard", "aip_homepage"}:
        raise ValueError(f"Unsupported journal feed parser: {definition.parser}")
    return parse_standard_journal_feed_entries(payload, definition)


def parse_standard_journal_feed_entries(
    payload: bytes | str,
    definition: JournalFeedDefinition,
) -> list[dict[str, Any]]:
    """Parse common RSS 2.0, RSS 1.0/RDF, and Atom journal feeds."""
    root = parse_journal_feed_xml(payload)
    items = [node for node in root.iter() if xml_local_name(node.tag) in {"item", "entry"}]
    papers: list[dict[str, Any]] = []
    for item in items:
        item_type = clean_text(feed_element_text(item, {"type"})).casefold()
        if journal_feed_item_type_is_excluded(item_type):
            continue
        if definition.allowed_item_types and item_type not in {
            value.casefold() for value in definition.allowed_item_types
        }:
            continue
        categories = {
            clean_text(" ".join(node.itertext())).casefold()
            for node in item.iter()
            if xml_local_name(node.tag) == "category"
        }
        if definition.required_item_categories and not categories.intersection(
            value.casefold() for value in definition.required_item_categories
        ):
            continue
        title = normalize_publication_title(feed_element_text(item, {"title"}))
        if not title or journal_feed_title_is_excluded(title):
            continue
        link = feed_entry_link(item)
        doi = feed_entry_doi(item, link)
        if definition.doi_prefixes and not any(
            doi.startswith(prefix.casefold()) for prefix in definition.doi_prefixes
        ):
            continue
        publication_date = normalize_feed_publication_date(
            feed_element_text(item, {"publicationdate", "date", "pubdate", "published", "updated"})
        )
        if not publication_date:
            continue
        journal_name = clean_text(
            feed_element_text(item, {"publicationname", "source"}) or definition.journal_name
        )
        url = link or (f"https://doi.org/{doi}" if doi else "")
        authors = feed_entry_authors(item)
        abstract = feed_entry_abstract(item) if definition.include_abstract else ""
        raw = {
            "DOI": doi,
            "title": [title],
            "author": [{"name": author} for author in authors],
            "container-title": [journal_name],
            "published-online": {"date-parts": [[int(part) for part in publication_date.split("-")]]},
            "type": "journal-article",
            "journal_feed": {
                "feed_key": definition.key,
                "publisher": definition.publisher,
                "feed_url": definition.url,
                "publication_date": publication_date,
                "item_type": item_type,
            },
            "_paper_monitor_sources": [definition.source_name],
        }
        papers.append(
            {
                "paper_id": make_paper_id(doi, title, journal_name, publication_date),
                "doi": doi,
                "title": title,
                "journal": journal_name,
                "publication_date": publication_date,
                "abstract": abstract,
                "abstract_source": definition.source_name if abstract else "missing",
                "url": url,
                "landing_url": url,
                "pdf_url": "",
                "source": definition.source_name,
                "type": "journal-article",
                "type_crossref": "journal-article",
                "publisher_section": "published",
                "section_allowed": True,
                "raw": raw,
            }
        )
    return papers


def parse_journal_feed_xml(payload: bytes | str) -> ET.Element:
    """Parse publisher XML, repairing only invalid controls and bare ampersands."""
    try:
        return ET.fromstring(payload)
    except ET.ParseError:
        text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        text = re.sub(r"&(?!#\d+;|#x[0-9a-fA-F]+;|[A-Za-z][A-Za-z0-9]+;)", "&amp;", text)
        return ET.fromstring(text)


def journal_feed_title_is_excluded(title: str) -> bool:
    text = clean_text(title).casefold()
    prefixes = (
        "author correction:",
        "publisher correction:",
        "correction:",
        "erratum:",
        "retraction note:",
        "retraction:",
        "editorial:",
        "book review:",
        "issue masthead",
    )
    return text.startswith(prefixes)


def journal_feed_item_type_is_excluded(item_type: str) -> bool:
    text = clean_text(item_type).casefold()
    if not text:
        return False
    excluded_markers = (
        "correction",
        "editorial",
        "news",
        "book review",
        "announcement",
        "obituary",
        "retraction",
        "erratum",
        "addendum",
        "masthead",
        "cover",
    )
    return any(marker in text for marker in excluded_markers)


def xml_local_name(tag: Any) -> str:
    return str(tag or "").rsplit("}", 1)[-1].casefold()


def feed_element_text(element: ET.Element, local_names: set[str]) -> str:
    names = {name.casefold() for name in local_names}
    for node in element.iter():
        if node is element or xml_local_name(node.tag) not in names:
            continue
        text = clean_text(" ".join(node.itertext()))
        if text:
            return text
    return ""


def feed_entry_link(item: ET.Element) -> str:
    for node in item.iter():
        if xml_local_name(node.tag) != "link":
            continue
        href = clean_text(node.attrib.get("href") or "")
        rel = clean_text(node.attrib.get("rel") or "alternate").casefold()
        if href and rel in {"", "alternate"}:
            return href
        text = clean_text(" ".join(node.itertext()))
        if text:
            return text
    return ""


def feed_entry_doi(item: ET.Element, link: str = "") -> str:
    candidates = [
        feed_element_text(item, {"doi"}),
        feed_element_text(item, {"identifier"}),
        feed_element_text(item, {"guid"}),
        feed_element_text(item, {"id"}),
        link,
        feed_element_text(item, {"description"}),
        feed_element_text(item, {"encoded"}),
        feed_element_text(item, {"content"}),
    ]
    for value in candidates:
        doi = normalize_doi(value)
        if doi.startswith("10.") and "/" in doi:
            return doi
        match = re.search(r"10\.\d{4,9}/[^\s<>\"']+", value or "", flags=re.IGNORECASE)
        if match:
            return normalize_doi(match.group(0).rstrip(".,;:)\]"))
    return ""


def normalize_feed_publication_date(value: str) -> str:
    text = clean_text(value)
    match = re.search(r"(?<!\d)(\d{4})[-/](\d{2})[-/](\d{2})(?!\d)", text)
    if match:
        candidate = "-".join(match.groups())
        try:
            return datetime.fromisoformat(candidate).date().isoformat()
        except ValueError:
            return ""
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def feed_entry_authors(item: ET.Element) -> list[str]:
    authors: list[str] = []
    for node in item.iter():
        local_name = xml_local_name(node.tag)
        if local_name == "author":
            name = feed_element_text(node, {"name"}) or clean_text(" ".join(node.itertext()))
        elif local_name == "creator":
            name = clean_text(" ".join(node.itertext()))
        else:
            continue
        for candidate in aps_rss_author_names(name):
            if candidate not in authors:
                authors.append(candidate)
    return authors


def feed_entry_abstract(item: ET.Element) -> str:
    for local_name in ("encoded", "summary", "description", "content"):
        value = feed_element_text(item, {local_name})
        if not value:
            continue
        soup = BeautifulSoup(value, "html.parser")
        paragraphs = [clean_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
        candidates = [text for text in paragraphs if len(text) >= 40]
        abstract = max(candidates, key=len, default=clean_text(soup.get_text(" ", strip=True)))
        if len(abstract) >= 40:
            return abstract
    return ""


def aps_rss_item_abstract(item: ET.Element) -> str:
    rss = "{http://purl.org/rss/1.0/}"
    content = "{http://purl.org/rss/1.0/modules/content/}"
    encoded = item.findtext(f"{content}encoded") or ""
    description = item.findtext(f"{rss}description") or ""
    soup = BeautifulSoup(encoded or description, "html.parser")
    paragraphs = [clean_text(node.get_text(" ", strip=True)) for node in soup.find_all("p")]
    candidates = [
        text
        for text in paragraphs
        if len(text) >= 80
        and not text.casefold().startswith("author(s):")
        and not text.startswith("[")
    ]
    return max(candidates, key=len, default="")


def aps_rss_author_names(value: str) -> list[str]:
    creator = re.sub(r"^author\(s\):\s*", "", clean_text(value), flags=re.IGNORECASE)
    creator = creator.replace(", and ", ", ").replace(" and ", ", ")
    return list(dict.fromkeys(clean_text(name) for name in creator.split(",") if clean_text(name)))


def sync_aps_rss_feeds(
    storage: Any,
    *,
    journal_slugs: list[str] | None = None,
    force: bool = False,
    cache_seconds: int = APS_RSS_CACHE_SECONDS,
) -> dict[str, Any]:
    requested = journal_slugs or list(APS_CANONICAL_NAMES_BY_SLUG)
    feed_keys = [f"aps:{slug}" for slug in requested if slug in APS_CANONICAL_NAMES_BY_SLUG]
    summary = sync_journal_feeds(
        storage,
        feed_keys=feed_keys,
        force=force,
        cache_seconds=cache_seconds,
    )
    summary["feeds"] = {
        key.removeprefix("aps:"): value for key, value in summary["feeds"].items()
    }
    return summary


def sync_journal_feeds(
    storage: Any,
    *,
    feed_keys: list[str] | None = None,
    definitions: dict[str, JournalFeedDefinition] | None = None,
    force: bool = False,
    cache_seconds: int = APS_RSS_CACHE_SECONDS,
) -> dict[str, Any]:
    registry = definitions or journal_feed_definitions()
    requested = feed_keys or list(registry)
    targets = [registry[key] for key in requested if key in registry]
    summary: dict[str, Any] = {
        "status": "empty",
        "feeds": {},
        "entries": 0,
        "created": 0,
        "errors": [],
    }
    with _APS_RSS_LOCK:
        for definition in targets:
            publisher_key = definition.publisher.casefold()
            state = storage.get_journal_feed(definition.key)
            if not force and journal_feed_state_is_fresh(state, success_ttl_seconds=cache_seconds):
                count = int((state or {}).get("entry_count") or 0)
                summary["feeds"][definition.key] = {"status": "cached", "entries": count}
                summary["entries"] += count
                continue
            now = time.monotonic()
            blocked_until = _JOURNAL_FEED_BLOCKED_UNTIL.get(publisher_key, 0.0)
            if now < blocked_until:
                summary["feeds"][definition.key] = {"status": "cooldown", "entries": 0}
                continue
            last_request_at = _JOURNAL_FEED_LAST_REQUEST_AT.get(publisher_key, 0.0)
            wait_seconds = APS_RSS_REQUEST_INTERVAL_SECONDS - (now - last_request_at)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            headers = {"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml"}
            if definition.parser != "aip_homepage" and state and state.get("etag"):
                headers["If-None-Match"] = str(state["etag"])
            if definition.parser != "aip_homepage" and state and state.get("last_modified"):
                headers["If-Modified-Since"] = str(state["last_modified"])
            try:
                response = requests.get(
                    definition.url,
                    headers=headers,
                    timeout=10,
                    allow_redirects=True,
                )
                if definition.parser == "aip_homepage":
                    response.raise_for_status()
                    feed_url = aip_homepage_feed_url(response.content, definition.url)
                    time.sleep(APS_RSS_REQUEST_INTERVAL_SECONDS)
                    response = requests.get(
                        feed_url,
                        headers={"User-Agent": USER_AGENT, "Accept": "application/xml,text/xml"},
                        timeout=10,
                        allow_redirects=True,
                    )
                requested_at = time.monotonic()
                _JOURNAL_FEED_LAST_REQUEST_AT[publisher_key] = requested_at
                if response.status_code in {403, 429}:
                    _JOURNAL_FEED_BLOCKED_UNTIL[publisher_key] = (
                        requested_at + APS_ABSTRACT_BLOCK_COOLDOWN_SECONDS
                    )
                    response.raise_for_status()
                if response.status_code == 304:
                    count = int((state or {}).get("entry_count") or 0)
                    storage.record_journal_feed(
                        feed_key=definition.key,
                        publisher=definition.publisher,
                        journal_name=definition.journal_name,
                        feed_url=definition.url,
                        parser=definition.parser,
                        status="success",
                        entry_count=count,
                        success=True,
                    )
                    summary["feeds"][definition.key] = {"status": "not_modified", "entries": count}
                    summary["entries"] += count
                    continue
                response.raise_for_status()
                papers = parse_journal_feed_entries(response.content, definition)
                storage.record_journal_feed(
                    feed_key=definition.key,
                    publisher=definition.publisher,
                    journal_name=definition.journal_name,
                    feed_url=definition.url,
                    parser=definition.parser,
                    status="running",
                    entry_count=int((state or {}).get("entry_count") or 0),
                )
                created = 0
                for paper in papers:
                    created += int(
                        storage.merge_paper_missing_metadata(
                            paper,
                            source_name=definition.source_name,
                            commit=False,
                        )
                    )
                storage.record_journal_feed_entries(definition.key, papers)
                storage.record_journal_feed(
                    feed_key=definition.key,
                    publisher=definition.publisher,
                    journal_name=definition.journal_name,
                    feed_url=definition.url,
                    parser=definition.parser,
                    status="success",
                    entry_count=len(papers),
                    etag=clean_text(response.headers.get("ETag") or ""),
                    last_modified=clean_text(response.headers.get("Last-Modified") or ""),
                    success=True,
                )
                summary["feeds"][definition.key] = {
                    "status": "success",
                    "entries": len(papers),
                    "created": created,
                }
                summary["entries"] += len(papers)
                summary["created"] += created
            except (requests.RequestException, ET.ParseError, ValueError) as exc:
                message = clean_text(str(exc))[:500]
                if definition.fallback_issns:
                    try:
                        papers = journal_feed_crossref_fallback(definition)
                        storage.record_journal_feed(
                            feed_key=definition.key,
                            publisher=definition.publisher,
                            journal_name=definition.journal_name,
                            feed_url=definition.url,
                            parser=definition.parser,
                            status="running",
                            entry_count=int((state or {}).get("entry_count") or 0),
                            message=f"Official RSS unavailable; using Crossref: {message}",
                        )
                        created = 0
                        for paper in papers:
                            created += int(
                                storage.merge_paper_missing_metadata(
                                    paper,
                                    source_name=definition.source_name,
                                    commit=False,
                                )
                            )
                        storage.record_journal_feed_entries(definition.key, papers)
                        storage.record_journal_feed(
                            feed_key=definition.key,
                            publisher=definition.publisher,
                            journal_name=definition.journal_name,
                            feed_url=definition.url,
                            parser=definition.parser,
                            status="success",
                            entry_count=len(papers),
                            success=True,
                            message=f"Official RSS unavailable; using Crossref: {message}",
                        )
                        summary["feeds"][definition.key] = {
                            "status": "fallback",
                            "entries": len(papers),
                            "created": created,
                            "message": "Official RSS unavailable; using Crossref",
                        }
                        summary["entries"] += len(papers)
                        summary["created"] += created
                        continue
                    except requests.RequestException as fallback_exc:
                        fallback_message = clean_text(str(fallback_exc))[:500]
                        message = f"{message}; Crossref fallback failed: {fallback_message}"[:500]
                storage.record_journal_feed(
                    feed_key=definition.key,
                    publisher=definition.publisher,
                    journal_name=definition.journal_name,
                    feed_url=definition.url,
                    parser=definition.parser,
                    status="error",
                    entry_count=int((state or {}).get("entry_count") or 0),
                    message=message,
                )
                summary["feeds"][definition.key] = {
                    "status": "error",
                    "entries": 0,
                    "message": message,
                }
                summary["errors"].append(f"{definition.journal_name}: {message}")
    statuses = [str(item.get("status") or "") for item in summary["feeds"].values()]
    successful = [
        status for status in statuses if status in {"success", "cached", "not_modified", "fallback"}
    ]
    failed = [status for status in statuses if status in {"error", "cooldown"}]
    if successful and failed:
        summary["status"] = "partial"
    elif successful:
        summary["status"] = "success"
    elif failed:
        summary["status"] = "error"
    return summary


def aip_homepage_feed_url(payload: bytes | str, homepage_url: str) -> str:
    soup = BeautifulSoup(payload, "html.parser")
    candidates: list[tuple[str, str]] = []
    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href") or "")
        if "/rss/" not in href or not href.casefold().endswith(".xml"):
            continue
        candidates.append((clean_text(link.get_text(" ", strip=True)).casefold(), urljoin(homepage_url, href)))
    if not candidates:
        raise ValueError("Official AIP RSS link was not found on the journal homepage")
    for label, url in candidates:
        if "current" in label:
            return url
    return candidates[0][1]


def journal_feed_crossref_fallback(definition: JournalFeedDefinition) -> list[dict[str, Any]]:
    end_date = date.today()
    papers = fetch_crossref_journal(
        journal_name=definition.journal_name,
        issns=list(definition.fallback_issns),
        start_date=end_date - timedelta(days=90),
        end_date=end_date,
        rows=100,
        max_pages=2,
    )
    accepted: list[dict[str, Any]] = []
    for paper in papers:
        doi = normalize_doi(paper.get("doi") or "")
        title = clean_text(paper.get("title") or "")
        if definition.doi_prefixes and not any(
            doi.startswith(prefix.casefold()) for prefix in definition.doi_prefixes
        ):
            continue
        if not title or journal_feed_title_is_excluded(title):
            continue
        raw = paper.get("raw") if isinstance(paper.get("raw"), dict) else {}
        source_names = raw.get("_paper_monitor_sources")
        if not isinstance(source_names, list):
            source_names = []
        if definition.source_name not in source_names:
            source_names.append(definition.source_name)
        raw["_paper_monitor_sources"] = source_names
        raw["journal_feed"] = {
            "feed_key": definition.key,
            "publisher": definition.publisher,
            "feed_url": definition.url,
            "fallback": "crossref",
        }
        paper["raw"] = raw
        paper["source"] = definition.source_name
        accepted.append(paper)
    return accepted


def journal_feed_state_is_fresh(
    state: dict[str, Any] | None,
    *,
    success_ttl_seconds: int = APS_RSS_CACHE_SECONDS,
) -> bool:
    if not state:
        return False
    status = clean_text(state.get("status") or "")
    if status not in {"success", "error"}:
        return False
    timestamp = state.get("success_at") if status == "success" else state.get("checked_at")
    if not timestamp:
        return False
    try:
        checked = datetime.fromisoformat(str(timestamp))
        now = datetime.now().astimezone()
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=now.tzinfo)
        age = (now - checked.astimezone(now.tzinfo)).total_seconds()
    except (TypeError, ValueError):
        return False
    ttl = max(60, int(success_ttl_seconds)) if status == "success" else APS_RSS_FAILURE_CACHE_SECONDS
    return 0 <= age < ttl


def aps_rss_feed_state_is_fresh(
    state: dict[str, Any] | None,
    *,
    success_ttl_seconds: int = APS_RSS_CACHE_SECONDS,
) -> bool:
    return journal_feed_state_is_fresh(state, success_ttl_seconds=success_ttl_seconds)


def parse_rmp_rss_abstracts(payload: bytes | str) -> dict[str, str]:
    """Backward-compatible name for callers and older tests."""
    return parse_aps_rss_abstracts(payload)


def enrich_aps_abstract_from_page(paper: dict[str, Any]) -> dict[str, Any]:
    if clean_text(paper.get("abstract") or ""):
        return paper
    journal = clean_text(paper.get("journal") or "").casefold()
    slug = aps_journal_slug(journal)
    if not slug:
        return paper
    if clean_text(paper.get("publisher_section") or "").casefold() != "published":
        return paper
    if paper.get("section_allowed") is False:
        return paper
    doi = clean_text(paper.get("doi") or "").lower()
    if not doi.startswith("10.1103/"):
        return paper

    # Serialize the complete cache-check/fetch sequence so concurrent journal
    # refreshes cannot issue duplicate requests for the same DOI.
    with _APS_ABSTRACT_FETCH_LOCK:
        abstract = cached_aps_abstract(doi)
        if abstract is None:
            return paper
        if abstract:
            paper["abstract"] = abstract
            paper["abstract_source"] = "aps"
            return paper

        escaped_doi = quote(doi, safe="/")
        urls = [f"https://journals.aps.org/{slug}/abstract/{escaped_doi}"]
        for url in urls:
            response = request_aps_page(url)
            if response is None:
                cache_aps_abstract(doi, "")
                return paper
            if response.status_code == 404:
                continue
            if response.status_code >= 400:
                cache_aps_abstract(doi, "")
                return paper
            abstract = extract_aps_page_abstract(BeautifulSoup(response.text, "html.parser"))
            if abstract:
                cache_aps_abstract(doi, abstract)
                paper["abstract"] = abstract
                paper["abstract_source"] = "aps"
                return paper

        cache_aps_abstract(doi, "")
    return paper


def enrich_rmp_abstract_from_aps(paper: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible name for the original RMP-only helper."""
    return enrich_aps_abstract_from_page(paper)


def cached_aps_abstract(doi: str) -> str | None:
    cached = _APS_ABSTRACT_CACHE.get(doi)
    if cached is None:
        return ""
    cached_at, abstract = cached
    if abstract:
        return abstract
    if time.monotonic() - cached_at < APS_ABSTRACT_FAILURE_CACHE_SECONDS:
        return None
    _APS_ABSTRACT_CACHE.pop(doi, None)
    return ""


def cache_aps_abstract(doi: str, abstract: str) -> None:
    _APS_ABSTRACT_CACHE[doi] = (time.monotonic(), clean_text(abstract))


def request_aps_page(url: str) -> requests.Response | None:
    global _APS_ABSTRACT_BLOCKED_UNTIL, _APS_ABSTRACT_LAST_REQUEST_AT
    with _APS_ABSTRACT_REQUEST_LOCK:
        now = time.monotonic()
        if now < _APS_ABSTRACT_BLOCKED_UNTIL:
            return None
        wait_seconds = APS_ABSTRACT_REQUEST_INTERVAL_SECONDS - (now - _APS_ABSTRACT_LAST_REQUEST_AT)
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=10,
                allow_redirects=True,
            )
        except requests.RequestException:
            _APS_ABSTRACT_LAST_REQUEST_AT = time.monotonic()
            return None
        _APS_ABSTRACT_LAST_REQUEST_AT = time.monotonic()
        if response.status_code in {403, 429}:
            _APS_ABSTRACT_BLOCKED_UNTIL = _APS_ABSTRACT_LAST_REQUEST_AT + APS_ABSTRACT_BLOCK_COOLDOWN_SECONDS
            return None
        return response


def request_aps_abstract_page(url: str) -> requests.Response | None:
    """Backward-compatible name for the shared guarded APS page request."""
    return request_aps_page(url)


def extract_aps_page_abstract(soup: BeautifulSoup) -> str:
    for selector in (
        "section.abstract",
        "div.abstract",
        "[data-testid='abstract']",
        ".article__abstract",
        ".article-text.abstract",
    ):
        node = soup.select_one(selector)
        text = clean_text(node.get_text(" ", strip=True) if node else "")
        text = re.sub(r"^abstract\s*", "", text, flags=re.IGNORECASE)
        if len(text) >= 80:
            return text

    for heading in soup.find_all(re.compile(r"^h[1-6]$")):
        if clean_text(heading.get_text(" ", strip=True)).casefold() != "abstract":
            continue
        container = heading.find_parent(["section", "div"])
        text = clean_text(container.get_text(" ", strip=True) if container else "")
        text = re.sub(r"^abstract\s*", "", text, flags=re.IGNORECASE)
        if len(text) >= 80:
            return text

    return first_meta(
        soup,
        [
            {"name": "citation_abstract"},
            {"name": "dc.description"},
            {"name": "dc.Description"},
            {"property": "og:description"},
        ],
    )


def reset_aps_abstract_fetch_state() -> None:
    global _APS_ABSTRACT_BLOCKED_UNTIL, _APS_ABSTRACT_LAST_REQUEST_AT
    global _APS_RSS_BLOCKED_UNTIL, _APS_RSS_LAST_REQUEST_AT
    with _APS_ABSTRACT_REQUEST_LOCK:
        _APS_ABSTRACT_CACHE.clear()
        _APS_ABSTRACT_LAST_REQUEST_AT = 0.0
        _APS_ABSTRACT_BLOCKED_UNTIL = 0.0
    with _APS_RSS_LOCK:
        _APS_RSS_CACHE.clear()
        _JOURNAL_FEED_LAST_REQUEST_AT.clear()
        _JOURNAL_FEED_BLOCKED_UNTIL.clear()
        _APS_RSS_LAST_REQUEST_AT = 0.0
        _APS_RSS_BLOCKED_UNTIL = 0.0


def enrich_from_landing_page(paper: dict[str, Any], section_policy: dict[str, list[str]], keep_unknown: bool) -> dict[str, Any]:
    url = paper.get("landing_url") or paper.get("url")
    if not url:
        paper["section_allowed"] = keep_unknown
        return paper

    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        if paper.get("section_allowed") is None:
            paper["section_allowed"] = keep_unknown
        paper["publisher_section"] = paper.get("publisher_section") or "unknown"
        paper["landing_fetch_error"] = str(exc)
        return paper

    soup = BeautifulSoup(response.text, "html.parser")
    section = extract_section(soup)
    abstract = extract_abstract(soup)
    pdf_url = extract_pdf_url(soup, url)
    supplement_urls = extract_supplement_urls(soup, url)
    image_url = extract_first_image_url(soup, url)

    if section:
        paper["publisher_section"] = section
        paper["section_allowed"] = classify_section(section, section_policy, keep_unknown)
    elif paper.get("section_allowed") is None:
        paper["publisher_section"] = paper.get("publisher_section") or "unknown"
        paper["section_allowed"] = keep_unknown

    if not paper.get("abstract") and abstract:
        paper["abstract"] = abstract
        paper["abstract_source"] = "landing_page"
    if pdf_url and not paper.get("pdf_url"):
        paper["pdf_url"] = pdf_url
    if supplement_urls:
        paper["supplement_urls"] = supplement_urls
    if image_url:
        paper["image_url"] = image_url
    return paper


def enrich_image_from_landing_page(paper: dict[str, Any]) -> dict[str, Any]:
    if paper.get("image_url"):
        return paper
    url = paper.get("landing_url") or paper.get("url")
    if not url:
        return paper
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=8,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        paper["landing_fetch_error"] = str(exc)
        return paper
    soup = BeautifulSoup(response.text, "html.parser")
    image_url = ""
    if (paper.get("journal") or "").lower() == "arxiv":
        image_url = extract_arxiv_html_first_figure_url(soup, response.url or url)
    if not image_url:
        image_url = extract_first_image_url(soup, url)
    if image_url:
        paper["image_url"] = image_url
    return paper


def extract_arxiv_html_first_figure_url(abs_soup: BeautifulSoup, abs_url: str) -> str:
    html_url = extract_arxiv_html_url(abs_soup, abs_url)
    if not html_url:
        return ""
    try:
        response = requests.get(
            html_url,
            headers={"User-Agent": USER_AGENT},
            timeout=12,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception:
        return ""
    return extract_first_image_url(BeautifulSoup(response.text, "html.parser"), response.url or html_url)


def extract_arxiv_html_url(soup: BeautifulSoup, base_url: str) -> str:
    for link in soup.find_all("a", href=True):
        label = clean_text(link.get_text(" ", strip=True)).lower()
        title = clean_text(link.get("title")).lower()
        marker = f"{label} {title}"
        href = clean_text(link.get("href"))
        if href and "html" in marker and "experimental" in marker:
            return urljoin(base_url, href)
    return ""


def extract_section(soup: BeautifulSoup) -> str:
    section = first_meta(
        soup,
        [
            {"name": "citation_article_type"},
            {"name": "dc.type"},
            {"name": "dc.Type"},
            {"name": "prism.section"},
            {"property": "article:section"},
            {"property": "og:type"},
        ],
    )
    return normalize_section(section)


def extract_abstract(soup: BeautifulSoup) -> str:
    return first_meta(
        soup,
        [
            {"name": "dc.description"},
            {"name": "dc.Description"},
            {"name": "description"},
            {"property": "og:description"},
            {"name": "twitter:description"},
        ],
    )


def extract_pdf_url(soup: BeautifulSoup, base_url: str) -> str:
    meta_url = first_meta(soup, [{"name": "citation_pdf_url"}])
    if meta_url:
        return urljoin(base_url, meta_url)
    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href"))
        label = clean_text(link.get_text(" ", strip=True)).lower()
        marker = f"{href} {label}".lower()
        if is_probable_non_article_pdf(marker):
            continue
        if href.lower().endswith(".pdf") or "download pdf" in label or label == "pdf":
            return urljoin(base_url, href)
    return ""


def extract_supplement_urls(soup: BeautifulSoup, base_url: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = clean_text(link.get("href"))
        label = clean_text(link.get_text(" ", strip=True)).lower()
        marker = f"{href} {label}".lower()
        if not any(
            token in marker
            for token in [
                "supplement",
                "supplementary",
                "appendix",
                "additional file",
                "peer review file",
                "peer-review file",
                "reporting summary",
            ]
        ):
            continue
        absolute = urljoin(base_url, href)
        if absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)
    return urls


def extract_first_image_url(soup: BeautifulSoup, base_url: str) -> str:
    for selector in [
        "figure img",
        "article img",
        "[class*=figure] img",
        "[id*=figure] img",
    ]:
        for image in soup.select(selector):
            url = image_candidate_url(image)
            if url and not is_probable_non_figure_image(url, image):
                return urljoin(base_url, url)

    meta_url = first_meta(
        soup,
        [
            {"name": "citation_figure"},
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"name": "twitter:image:src"},
        ],
    )
    return urljoin(base_url, meta_url) if meta_url else ""


def image_candidate_url(image: Any) -> str:
    for attr in ["src", "data-src", "data-original", "data-highres", "data-download-url"]:
        value = clean_text(image.get(attr))
        if value:
            return value
    srcset = clean_text(image.get("srcset") or image.get("data-srcset"))
    if srcset:
        candidates = [part.strip().split(" ", 1)[0] for part in srcset.split(",") if part.strip()]
        if candidates:
            return candidates[-1]
    return ""


def is_probable_non_figure_image(url: str, image: Any) -> bool:
    marker = " ".join(
        [
            url,
            clean_text(image.get("alt")),
            clean_text(image.get("class")),
            clean_text(image.get("id")),
        ]
    ).lower()
    if any(token in marker for token in ["logo", "icon", "avatar", "ad-", "advert", "spinner", "tracking", "pixel"]):
        return True
    try:
        width = int(str(image.get("width") or "0").strip() or 0)
        height = int(str(image.get("height") or "0").strip() or 0)
    except ValueError:
        width = height = 0
    return bool(width and height and (width < 120 or height < 90))


def first_meta(soup: BeautifulSoup, attrs_list: list[dict[str, str]]) -> str:
    for attrs in attrs_list:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            value = clean_text(tag.get("content"))
            if value:
                return value
    return ""


def normalize_section(section: str) -> str:
    section = clean_text(section).lower()
    section = section.replace("open access", "")
    section = re.sub(r"\s+", " ", section).strip()
    if "research article" in section:
        return "research article"
    if section in {"research", "report", "review", "analysis", "perspective", "letter"}:
        return section
    if "review" in section:
        return "review"
    if "analysis" in section:
        return "analysis"
    if "perspective" in section:
        return "perspective"
    if "article" in section:
        return "article"
    return section


def is_probable_non_article_pdf(marker: str) -> bool:
    non_article_tokens = [
        "peer review",
        "peer-review",
        "reporting summary",
        "source data",
        "supplement",
        "supplementary",
        "appendix",
        "additional",
    ]
    return any(token in marker for token in non_article_tokens)


def classify_section(section: str, policy: dict[str, list[str]], keep_unknown: bool) -> bool:
    normalized = normalize_section(section)
    if not normalized:
        return keep_unknown
    if any(blocked in normalized for blocked in policy.get("blocked", [])):
        return False
    allowed = policy.get("allowed", [])
    if not allowed:
        return True
    return normalized in allowed or any(item in normalized for item in allowed)
