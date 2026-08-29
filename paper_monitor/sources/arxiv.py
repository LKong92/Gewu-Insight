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
DEFAULT_ARXIV_PRIMARY_SUBJECT = "physics"
DEFAULT_ARXIV_SECONDARY_SUBJECT = "cond-mat"
DEFAULT_ARXIV_SCOPE_IDS = ("physics/cond-mat",)


def _categories(*items: tuple[str, str]) -> list[dict[str, str]]:
    return [{"code": code, "label": label} for code, label in items]


ARXIV_SUBJECT_HIERARCHY = [
    {
        "code": "physics", "label": "Physics", "groups": [
            {"code": "astro-ph", "label": "Astrophysics", "categories": _categories(
                ("astro-ph.CO", "Cosmology and Nongalactic Astrophysics"), ("astro-ph.EP", "Earth and Planetary Astrophysics"),
                ("astro-ph.GA", "Astrophysics of Galaxies"), ("astro-ph.HE", "High Energy Astrophysical Phenomena"),
                ("astro-ph.IM", "Instrumentation and Methods for Astrophysics"), ("astro-ph.SR", "Solar and Stellar Astrophysics"),
            )},
            {"code": "cond-mat", "label": "Condensed Matter", "categories": _categories(
                ("cond-mat.dis-nn", "Disordered Systems and Neural Networks"), ("cond-mat.mes-hall", "Mesoscale and Nanoscale Physics"),
                ("cond-mat.mtrl-sci", "Materials Science"), ("cond-mat.other", "Other Condensed Matter"),
                ("cond-mat.quant-gas", "Quantum Gases"), ("cond-mat.soft", "Soft Condensed Matter"),
                ("cond-mat.stat-mech", "Statistical Mechanics"), ("cond-mat.str-el", "Strongly Correlated Electrons"),
                ("cond-mat.supr-con", "Superconductivity"),
            )},
            {"code": "gr-qc", "label": "General Relativity and Quantum Cosmology", "categories": _categories(("gr-qc", "General Relativity and Quantum Cosmology"))},
            {"code": "hep-ex", "label": "High Energy Physics - Experiment", "categories": _categories(("hep-ex", "High Energy Physics - Experiment"))},
            {"code": "hep-lat", "label": "High Energy Physics - Lattice", "categories": _categories(("hep-lat", "High Energy Physics - Lattice"))},
            {"code": "hep-ph", "label": "High Energy Physics - Phenomenology", "categories": _categories(("hep-ph", "High Energy Physics - Phenomenology"))},
            {"code": "hep-th", "label": "High Energy Physics - Theory", "categories": _categories(("hep-th", "High Energy Physics - Theory"))},
            {"code": "math-ph", "label": "Mathematical Physics", "categories": _categories(("math-ph", "Mathematical Physics"))},
            {"code": "nlin", "label": "Nonlinear Sciences", "categories": _categories(
                ("nlin.AO", "Adaptation and Self-Organizing Systems"), ("nlin.CD", "Chaotic Dynamics"),
                ("nlin.CG", "Cellular Automata and Lattice Gases"), ("nlin.PS", "Pattern Formation and Solitons"),
                ("nlin.SI", "Exactly Solvable and Integrable Systems"),
            )},
            {"code": "nucl-ex", "label": "Nuclear Experiment", "categories": _categories(("nucl-ex", "Nuclear Experiment"))},
            {"code": "nucl-th", "label": "Nuclear Theory", "categories": _categories(("nucl-th", "Nuclear Theory"))},
            {"code": "physics", "label": "Physics", "categories": _categories(
                ("physics.acc-ph", "Accelerator Physics"), ("physics.ao-ph", "Atmospheric and Oceanic Physics"),
                ("physics.app-ph", "Applied Physics"), ("physics.atm-clus", "Atomic and Molecular Clusters"),
                ("physics.atom-ph", "Atomic Physics"), ("physics.bio-ph", "Biological Physics"),
                ("physics.chem-ph", "Chemical Physics"), ("physics.class-ph", "Classical Physics"),
                ("physics.comp-ph", "Computational Physics"), ("physics.data-an", "Data Analysis, Statistics and Probability"),
                ("physics.flu-dyn", "Fluid Dynamics"), ("physics.gen-ph", "General Physics"),
                ("physics.geo-ph", "Geophysics"), ("physics.hist-ph", "History and Philosophy of Physics"),
                ("physics.ins-det", "Instrumentation and Detectors"), ("physics.med-ph", "Medical Physics"),
                ("physics.optics", "Optics"), ("physics.plasm-ph", "Plasma Physics"),
                ("physics.pop-ph", "Popular Physics"), ("physics.soc-ph", "Physics and Society"),
                ("physics.space-ph", "Space Physics"),
            )},
            {"code": "quant-ph", "label": "Quantum Physics", "categories": _categories(("quant-ph", "Quantum Physics"))},
        ],
    },
    {"code": "computer_science", "label": "Computer Science", "groups": [
        {"code": "cs", "label": "Computer Science", "categories": _categories(
            ("cs.AI", "Artificial Intelligence"), ("cs.AR", "Hardware Architecture"), ("cs.CC", "Computational Complexity"),
            ("cs.CE", "Computational Engineering, Finance, and Science"), ("cs.CG", "Computational Geometry"),
            ("cs.CL", "Computation and Language"), ("cs.CR", "Cryptography and Security"), ("cs.CV", "Computer Vision and Pattern Recognition"),
            ("cs.CY", "Computers and Society"), ("cs.DB", "Databases"), ("cs.DC", "Distributed, Parallel, and Cluster Computing"),
            ("cs.DL", "Digital Libraries"), ("cs.DM", "Discrete Mathematics"), ("cs.DS", "Data Structures and Algorithms"),
            ("cs.ET", "Emerging Technologies"), ("cs.FL", "Formal Languages and Automata Theory"), ("cs.GL", "General Literature"),
            ("cs.GR", "Graphics"), ("cs.GT", "Computer Science and Game Theory"), ("cs.HC", "Human-Computer Interaction"),
            ("cs.IR", "Information Retrieval"), ("cs.IT", "Information Theory"), ("cs.LG", "Machine Learning"),
            ("cs.LO", "Logic in Computer Science"), ("cs.MA", "Multiagent Systems"), ("cs.MM", "Multimedia"),
            ("cs.MS", "Mathematical Software"), ("cs.NA", "Numerical Analysis"), ("cs.NE", "Neural and Evolutionary Computing"),
            ("cs.NI", "Networking and Internet Architecture"), ("cs.OH", "Other Computer Science"), ("cs.OS", "Operating Systems"),
            ("cs.PF", "Performance"), ("cs.PL", "Programming Languages"), ("cs.RO", "Robotics"),
            ("cs.SC", "Symbolic Computation"), ("cs.SD", "Sound"), ("cs.SE", "Software Engineering"),
            ("cs.SI", "Social and Information Networks"), ("cs.SY", "Systems and Control"),
        )},
    ]},
    {"code": "economics", "label": "Economics", "groups": [
        {"code": "econ", "label": "Economics", "categories": _categories(("econ.EM", "Econometrics"), ("econ.GN", "General Economics"), ("econ.TH", "Theoretical Economics"))},
    ]},
    {"code": "eess", "label": "Electrical Engineering and Systems Science", "groups": [
        {"code": "eess", "label": "Electrical Engineering and Systems Science", "categories": _categories(
            ("eess.AS", "Audio and Speech Processing"), ("eess.IV", "Image and Video Processing"),
            ("eess.SP", "Signal Processing"), ("eess.SY", "Systems and Control"),
        )},
    ]},
    {"code": "mathematics", "label": "Mathematics", "groups": [
        {"code": "math", "label": "Mathematics", "categories": _categories(
            ("math.AC", "Commutative Algebra"), ("math.AG", "Algebraic Geometry"), ("math.AP", "Analysis of PDEs"),
            ("math.AT", "Algebraic Topology"), ("math.CA", "Classical Analysis and ODEs"), ("math.CO", "Combinatorics"),
            ("math.CT", "Category Theory"), ("math.CV", "Complex Variables"), ("math.DG", "Differential Geometry"),
            ("math.DS", "Dynamical Systems"), ("math.FA", "Functional Analysis"), ("math.GM", "General Mathematics"),
            ("math.GN", "General Topology"), ("math.GR", "Group Theory"), ("math.GT", "Geometric Topology"),
            ("math.HO", "History and Overview"), ("math.IT", "Information Theory"), ("math.KT", "K-Theory and Homology"),
            ("math.LO", "Logic"), ("math.MG", "Metric Geometry"), ("math.MP", "Mathematical Physics"),
            ("math.NA", "Numerical Analysis"), ("math.NT", "Number Theory"), ("math.OA", "Operator Algebras"),
            ("math.OC", "Optimization and Control"), ("math.PR", "Probability"), ("math.QA", "Quantum Algebra"),
            ("math.RA", "Rings and Algebras"), ("math.RT", "Representation Theory"), ("math.SG", "Symplectic Geometry"),
            ("math.SP", "Spectral Theory"), ("math.ST", "Statistics Theory"),
        )},
    ]},
    {"code": "q_bio", "label": "Quantitative Biology", "groups": [
        {"code": "q-bio", "label": "Quantitative Biology", "categories": _categories(
            ("q-bio.BM", "Biomolecules"), ("q-bio.CB", "Cell Behavior"), ("q-bio.GN", "Genomics"),
            ("q-bio.MN", "Molecular Networks"), ("q-bio.NC", "Neurons and Cognition"), ("q-bio.OT", "Other Quantitative Biology"),
            ("q-bio.PE", "Populations and Evolution"), ("q-bio.QM", "Quantitative Methods"),
            ("q-bio.SC", "Subcellular Processes"), ("q-bio.TO", "Tissues and Organs"),
        )},
    ]},
    {"code": "q_fin", "label": "Quantitative Finance", "groups": [
        {"code": "q-fin", "label": "Quantitative Finance", "categories": _categories(
            ("q-fin.CP", "Computational Finance"), ("q-fin.EC", "Economics"), ("q-fin.GN", "General Finance"),
            ("q-fin.MF", "Mathematical Finance"), ("q-fin.PM", "Portfolio Management"), ("q-fin.PR", "Pricing of Securities"),
            ("q-fin.RM", "Risk Management"), ("q-fin.ST", "Statistical Finance"), ("q-fin.TR", "Trading and Market Microstructure"),
        )},
    ]},
    {"code": "statistics", "label": "Statistics", "groups": [
        {"code": "stat", "label": "Statistics", "categories": _categories(
            ("stat.AP", "Applications"), ("stat.CO", "Computation"), ("stat.ME", "Methodology"),
            ("stat.ML", "Machine Learning"), ("stat.OT", "Other Statistics"), ("stat.TH", "Statistics Theory"),
        )},
    ]},
]


def arxiv_subject_group(primary_subject: str, secondary_subject: str) -> tuple[dict[str, Any], dict[str, Any]]:
    primary = next((item for item in ARXIV_SUBJECT_HIERARCHY if item["code"] == primary_subject), None)
    if primary is None:
        primary = next(item for item in ARXIV_SUBJECT_HIERARCHY if item["code"] == DEFAULT_ARXIV_PRIMARY_SUBJECT)
    group = next((item for item in primary["groups"] if item["code"] == secondary_subject), None)
    if group is None:
        preferred = DEFAULT_ARXIV_SECONDARY_SUBJECT if primary["code"] == DEFAULT_ARXIV_PRIMARY_SUBJECT else ""
        group = next((item for item in primary["groups"] if item["code"] == preferred), primary["groups"][0])
    return primary, group


def arxiv_scope_id(primary_subject: str, secondary_subject: str) -> str:
    return f"{primary_subject}/{secondary_subject}"


def arxiv_scope_groups() -> list[dict[str, Any]]:
    scopes: list[dict[str, Any]] = []
    for primary in ARXIV_SUBJECT_HIERARCHY:
        for group in primary["groups"]:
            scopes.append({
                "id": arxiv_scope_id(str(primary["code"]), str(group["code"])),
                "primary_code": str(primary["code"]),
                "primary_label": str(primary["label"]),
                "group_code": str(group["code"]),
                "group_label": str(group["label"]),
                "categories": copy.deepcopy(group["categories"]),
            })
    return scopes


def normalize_arxiv_scope_ids(scope_ids: Any) -> list[str]:
    requested = scope_ids if isinstance(scope_ids, (list, tuple, set)) else []
    selected = {str(value).strip() for value in requested if str(value).strip()}
    return [scope["id"] for scope in arxiv_scope_groups() if scope["id"] in selected]


def arxiv_categories_for_scopes(scope_ids: Any) -> list[str]:
    selected = set(normalize_arxiv_scope_ids(scope_ids))
    categories: list[str] = []
    seen: set[str] = set()
    for scope in arxiv_scope_groups():
        if scope["id"] not in selected:
            continue
        for item in scope["categories"]:
            code = str(item["code"])
            if code not in seen:
                categories.append(code)
                seen.add(code)
    return categories


def arxiv_display_categories_for_scopes(scope_ids: Any) -> list[str]:
    selected = normalize_arxiv_scope_ids(scope_ids)
    categories = arxiv_categories_for_scopes(selected)
    if selected == list(DEFAULT_ARXIV_SCOPE_IDS):
        preferred = ["cond-mat.mes-hall", "cond-mat.str-el", "cond-mat.supr-con"]
        return [code for code in preferred if code in categories]
    return categories


def arxiv_categories_for_subject(primary_subject: str, secondary_subject: str) -> list[str]:
    _primary, group = arxiv_subject_group(primary_subject, secondary_subject)
    return [str(item["code"]) for item in group["categories"]]


def arxiv_display_categories_for_subject(primary_subject: str, secondary_subject: str) -> list[str]:
    categories = arxiv_categories_for_subject(primary_subject, secondary_subject)
    if secondary_subject == "cond-mat":
        preferred = ["cond-mat.mes-hall", "cond-mat.str-el", "cond-mat.supr-con"]
        return [code for code in preferred if code in categories]
    return categories


def arxiv_subject_hierarchy_payload() -> list[dict[str, Any]]:
    return copy.deepcopy(ARXIV_SUBJECT_HIERARCHY)


def arxiv_archive_for_categories(categories: list[str]) -> str:
    selected = [str(code) for code in categories if code]
    if not selected:
        return DEFAULT_ARXIV_SECONDARY_SUBJECT
    code = selected[0]
    prefix = code.split(".", 1)[0]
    archives = {group["code"] for primary in ARXIV_SUBJECT_HIERARCHY for group in primary["groups"]}
    return prefix if prefix in archives else code


ARXIV_CONDENSED_MATTER_CATEGORIES = arxiv_subject_group("physics", "cond-mat")[1]["categories"]
ARXIV_CONDENSED_MATTER_CODES = [item["code"] for item in ARXIV_CONDENSED_MATTER_CATEGORIES]
ARXIV_ALL_CATEGORY_CODES = {
    item["code"]
    for primary in ARXIV_SUBJECT_HIERARCHY
    for group in primary["groups"]
    for item in group["categories"]
}
ARXIV_DISPLAY_DEFAULT_CATEGORIES = arxiv_display_categories_for_subject("physics", "cond-mat")
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
    selected_categories = [code for code in (categories or ARXIV_DEFAULT_CATEGORIES) if code in ARXIV_ALL_CATEGORY_CODES]
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
    archive = arxiv_archive_for_categories(categories)
    listing_date, papers = fetch_latest_arxiv_listing(
        local_tz=local_tz,
        force=force,
        archive=archive,
    )
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
    archive: str = DEFAULT_ARXIV_SECONDARY_SUBJECT,
) -> tuple[date | None, list[dict[str, Any]]]:
    target_tz = local_tz or local_timezone()
    archive = clean_text(archive)
    if not re.fullmatch(r"[A-Za-z0-9.-]+", archive):
        raise ValueError("Invalid arXiv archive")
    cache_key = f"{getattr(target_tz, 'key', target_tz)}:{archive}"
    with ARXIV_LATEST_LISTING_LOCK:
        cached_entries = ARXIV_LATEST_LISTING_CACHE.setdefault("entries", {})
        cached = cached_entries.get(cache_key) or {}
        cached_at = float(cached.get("fetched_at") or 0.0)
        if (
            not force
            and cached_at > 0
            and time.monotonic() - cached_at < ARXIV_LATEST_LISTING_CACHE_SECONDS
        ):
            return cached.get("listing_date"), [
                copy.deepcopy(paper) for paper in cached.get("papers") or []
            ]
        response = request_with_retries(
            "GET",
            f"https://arxiv.org/list/{archive}/new",
            params={"skip": 0, "show": 2000},
            headers={"Accept": "text/html,application/xhtml+xml"},
            timeout=ARXIV_API_TIMEOUT,
            max_retries=ARXIV_API_MAX_RETRIES,
        )
        listing_date, papers = parse_arxiv_latest_listing(response.text, local_tz=target_tz)
        cached_entries[cache_key] = {
            "fetched_at": time.monotonic(),
            "listing_date": listing_date,
            "papers": papers,
        }
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
