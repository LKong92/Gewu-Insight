from __future__ import annotations

import mimetypes
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from .config import DEFAULT_PDF_DIR
from .http import request_with_retries
from .pdf_utils import merge_pdfs
from .storage import Storage
from .text import safe_slug


def download_paper(
    *,
    storage: Storage,
    paper_id: str,
    pdf_dir: Path = DEFAULT_PDF_DIR,
    target_dir: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    paper = storage.get_paper(paper_id)
    if not paper:
        raise ValueError(f"Unknown paper id: {paper_id}")

    if paper.get("download_status") in {"success", "partial"} and not force:
        return {
            "status": "skipped",
            "message": "already downloaded; use --force to retry",
            "merged_pdf_path": paper.get("merged_pdf_path"),
        }

    target_dir = target_dir if target_dir is not None else pdf_dir / paper_id
    target_dir.mkdir(parents=True, exist_ok=True)

    candidates = collect_pdf_candidates(paper)
    main_pdf_path: Path | None = None
    supplement_paths: list[Path] = []
    messages: list[str] = []

    for index, url in enumerate(candidates["main"]):
        path = target_dir / "main.pdf"
        if try_download_pdf(url, path, messages):
            main_pdf_path = path
            break

    for index, url in enumerate(candidates["supplements"], start=1):
        path = target_dir / f"supplement_{index}.pdf"
        if try_download_pdf(url, path, messages):
            supplement_paths.append(path)

    if not main_pdf_path:
        status = "failed"
        failure_detail = "; ".join(messages[-5:]) or "no downloadable main PDF found"
        if supplement_paths:
            message = (
                f"main PDF unavailable; downloaded {len(supplement_paths)} PDF supplement(s); "
                f"{failure_detail}"
            )
        else:
            message = failure_detail
        storage.update_download_status(paper_id, status=status, message=message)
        return {"status": status, "message": message}

    current_merged_path = str(paper.get("merged_pdf_path") or "")
    merged_path = unique_download_path(
        target_dir / f"{safe_slug(paper.get('title') or paper_id, 80)}_merged.pdf",
        current_path=current_merged_path,
    )
    try:
        merge_inputs = [main_pdf_path] + supplement_paths
        merge_pdfs(merge_inputs, merged_path)
        status = "success" if supplement_paths else "partial"
        message = "downloaded and merged; temporary PDFs removed" if supplement_paths else "main PDF saved as merged PDF; no PDF supplement found"
    except Exception as exc:
        shutil.copyfile(main_pdf_path, merged_path)
        status = "partial"
        message = f"main PDF saved as merged PDF; supplement merge failed: {exc}"

    remove_intermediate_pdfs([main_pdf_path] + supplement_paths, keep=merged_path)

    storage.update_download_status(
        paper_id,
        status=status,
        message=message,
        main_pdf_path=str(merged_path),
        supplement_pdf_paths=[],
        merged_pdf_path=str(merged_path),
    )
    return {
        "status": status,
        "message": message,
        "main_pdf_path": str(merged_path),
        "supplement_pdf_paths": [],
        "merged_pdf_path": str(merged_path),
    }


def unique_download_path(path: Path, *, current_path: str = "") -> Path:
    try:
        current_resolved = Path(current_path).expanduser().resolve() if current_path else None
    except OSError:
        current_resolved = None
    if not path.exists():
        return path
    try:
        if current_resolved and path.resolve() == current_resolved:
            return path
    except OSError:
        pass
    parent = path.parent
    stem = path.stem
    suffix = path.suffix
    for index in range(2, 1000):
        candidate = parent / f"{stem} {index}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError(str(path))


def remove_intermediate_pdfs(paths: list[Path], *, keep: Path) -> None:
    keep_resolved = keep.resolve()
    for path in paths:
        try:
            if path.exists() and path.resolve() != keep_resolved:
                path.unlink()
        except FileNotFoundError:
            pass


def collect_pdf_candidates(paper: dict[str, Any]) -> dict[str, list[str]]:
    main: list[str] = []
    supplements: list[str] = []
    doi = normalize_doi(paper.get("doi") or "")

    # AAAS currently places an anti-bot challenge in front of direct PDF
    # requests. Prefer verified open repository copies before trying the
    # publisher URLs, while retaining the publisher candidates as fallbacks.
    if doi.startswith("10.1126/"):
        main.extend(science_open_access_pdf_candidates(doi))
        supplements.extend(science_supplement_pdf_candidates(doi))
    if paper.get("pdf_url"):
        main.append(paper["pdf_url"])
    main.extend(journal_pdf_candidates(paper))
    main.extend(doi_pdf_candidates(doi))
    main.extend(crossref_pdf_candidates(doi))

    landing_url = paper.get("landing_url") or paper.get("url")
    if landing_url:
        try:
            response = request_with_retries("GET", landing_url)
            page_url = response.url or landing_url
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup.find_all("meta", attrs={"name": "citation_pdf_url"}):
                if tag.get("content"):
                    main.append(_absolute(page_url, tag["content"]))
            for link in soup.find_all("a", href=True):
                href = _absolute(page_url, link["href"])
                label = (link.get_text(" ", strip=True) or "").lower()
                marker = f"{href} {label}".lower()
                if is_probable_supplement(marker):
                    supplements.append(href)
                elif is_probable_non_article_pdf(marker):
                    continue
                elif is_probable_main_pdf_link(href, label):
                    main.append(href)
        except Exception:
            pass

    return {
        "main": dedup(main),
        "supplements": [url for url in dedup(supplements) if url not in main],
    }


def doi_pdf_candidates(doi: str) -> list[str]:
    doi = normalize_doi(doi)
    if not doi:
        return []
    candidates = []
    if doi.startswith("10.1038/"):
        article_id = doi.split("/", 1)[1]
        candidates.append(f"https://www.nature.com/articles/{article_id}.pdf")
    if doi.startswith("10.1126/"):
        candidates.append(f"https://www.science.org/doi/pdf/{doi}")
        candidates.append(f"https://www.science.org/doi/pdf/{doi}?download=true")
        candidates.append(f"https://www.science.org/doi/epdf/{doi}")
    candidates.append(f"https://doi.org/{doi}")
    return candidates


def journal_pdf_candidates(paper: dict[str, Any]) -> list[str]:
    doi = normalize_doi(paper.get("doi") or "")
    journal = str(paper.get("journal") or "").lower()
    if not doi:
        return []
    if doi.startswith("10.1103/"):
        aps_slug = aps_journal_slug(journal)
        candidates = [
            f"https://harvest.aps.org/v2/journals/articles/{doi}/fulltext",
        ]
        if aps_slug:
            candidates.append(f"https://journals.aps.org/{aps_slug}/pdf/{doi}")
        candidates.append(f"https://link.aps.org/pdf/{doi}")
        return candidates
    return []


def aps_journal_slug(journal: str) -> str:
    if "physical review letters" in journal:
        return "prl"
    if "physical review x" in journal:
        return "prx"
    if "physical review a" in journal:
        return "pra"
    if "physical review b" in journal:
        return "prb"
    if "physical review c" in journal:
        return "prc"
    if "physical review d" in journal:
        return "prd"
    if "physical review e" in journal:
        return "pre"
    if "reviews of modern physics" in journal:
        return "rmp"
    return ""


def crossref_pdf_candidates(doi: str) -> list[str]:
    doi = normalize_doi(doi)
    if not doi:
        return []
    try:
        response = request_with_retries(
            "GET",
            f"https://api.crossref.org/works/{quote(doi, safe='')}",
            headers={"Accept": "application/json"},
            timeout=12,
        )
        payload = response.json()
    except Exception:
        return []
    message = payload.get("message") or {}
    candidates: list[str] = []
    for link in message.get("link") or []:
        url = str(link.get("URL") or "")
        content_type = str(link.get("content-type") or "").lower()
        if url and ("pdf" in content_type or "/pdf/" in url.lower() or url.lower().endswith(".pdf")):
            candidates.append(url)
    primary = ((message.get("resource") or {}).get("primary") or {}).get("URL") or ""
    if primary:
        candidates.append(str(primary))
    return candidates


def science_open_access_pdf_candidates(doi: str) -> list[str]:
    doi = normalize_doi(doi)
    if not doi.startswith("10.1126/"):
        return []
    return dedup(
        europe_pmc_pdf_candidates(doi)
        + openalex_open_pdf_candidates(doi, published_only=True)
    )


def science_supplement_pdf_candidates(doi: str) -> list[str]:
    doi = normalize_doi(doi)
    if not doi.startswith("10.1126/"):
        return []
    article_id = doi.split("/", 1)[1]
    return [
        f"https://www.science.org/doi/suppl/{doi}/suppl_file/{article_id}_sm.pdf",
    ]


def europe_pmc_pdf_candidates(doi: str) -> list[str]:
    doi = normalize_doi(doi)
    if not doi:
        return []
    try:
        response = request_with_retries(
            "GET",
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            params={
                "query": f"DOI:{doi}",
                "format": "json",
                "pageSize": 3,
            },
            headers={"Accept": "application/json"},
            timeout=12,
            max_retries=1,
        )
        payload = response.json()
    except Exception:
        return []
    candidates: list[str] = []
    results = ((payload.get("resultList") or {}).get("result") or []) if isinstance(payload, dict) else []
    for result in results:
        if not isinstance(result, dict):
            continue
        result_doi = normalize_doi(result.get("doi") or "")
        pmcid = str(result.get("pmcid") or "").strip().upper()
        if (
            result_doi == doi
            and pmcid.startswith("PMC")
            and str(result.get("isOpenAccess") or "").upper() == "Y"
            and str(result.get("hasPDF") or "").upper() == "Y"
        ):
            candidates.append(f"https://europepmc.org/api/getPdf?pmcid={quote(pmcid, safe='')}")
    return dedup(candidates)


def openalex_open_pdf_candidates(
    doi: str,
    *,
    repositories_first: bool = False,
    published_only: bool = False,
) -> list[str]:
    doi = normalize_doi(doi)
    if not doi:
        return []
    work_id = quote(f"https://doi.org/{doi}", safe="")
    try:
        response = request_with_retries(
            "GET",
            f"https://api.openalex.org/works/{work_id}",
            params={"select": "best_oa_location,locations"},
            headers={"Accept": "application/json"},
            timeout=12,
            max_retries=1,
        )
        payload = response.json()
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    locations = [item for item in (payload.get("locations") or []) if isinstance(item, dict)]
    best = payload.get("best_oa_location")
    if isinstance(best, dict):
        locations.append(best)

    def location_rank(location: dict[str, Any]) -> int:
        source = location.get("source") if isinstance(location.get("source"), dict) else {}
        is_repository = str(source.get("type") or "").lower() == "repository"
        if repositories_first and is_repository:
            return 0
        if is_repository:
            return 1
        return 2

    candidates: list[str] = []
    for location in sorted(locations, key=location_rank):
        if location.get("is_oa") is not True:
            continue
        if published_only and str(location.get("version") or "") != "publishedVersion":
            continue
        pdf_url = str(location.get("pdf_url") or "").strip()
        if pdf_url:
            candidates.append(pdf_url)
    return dedup(candidates)


def normalize_doi(value: Any) -> str:
    doi = str(value or "").strip()
    doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    return doi.strip().lower()


def try_download_pdf(url: str, path: Path, messages: list[str]) -> bool:
    try:
        response = request_with_retries("GET", url, headers=pdf_request_headers(url), stream=True)
        content_type = response.headers.get("content-type", "").lower()
        guessed_type = mimetypes.guess_type(urlparse(response.url).path)[0] or ""
        if "pdf" not in content_type and "pdf" not in guessed_type and not response.url.lower().endswith(".pdf"):
            messages.append(f"not a PDF: {url}")
            return False
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if chunk:
                    handle.write(chunk)
        if path.stat().st_size < 1024:
            messages.append(f"too small to be a valid PDF: {url}")
            path.unlink(missing_ok=True)
            return False
        with path.open("rb") as handle:
            header = handle.read(1024)
        if b"%PDF-" not in header:
            messages.append(f"not a PDF payload: {url}")
            path.unlink(missing_ok=True)
            return False
        return True
    except Exception as exc:
        messages.append(f"{url}: {download_error_message(exc)}")
        return False


def download_error_message(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None and getattr(response, "status_code", None) == 403:
        headers = {key.lower(): value for key, value in response.headers.items()}
        if headers.get("cf-mitigated") == "challenge" or "cloudflare" in headers.get("server", "").lower():
            return "blocked by publisher anti-bot challenge (HTTP 403)"
        return "access forbidden by publisher (HTTP 403)"
    return str(exc)


def pdf_request_headers(url: str) -> dict[str, str]:
    headers = {
        "Accept": "application/pdf,application/octet-stream;q=0.9,text/html;q=0.8,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
    }
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path
    if "science.org" in host and "/doi/" in path:
        doi = path.split("/doi/", 1)[1]
        doi = re.sub(r"^(pdf|epdf|full|reader)/", "", doi)
        doi = doi.lstrip("/")
        if doi:
            headers["Referer"] = f"https://www.science.org/doi/{doi}"
    elif "aps.org" in host and "10.1103/" in url:
        doi = url.split("10.1103/", 1)[1].split("?", 1)[0]
        headers["Referer"] = f"https://link.aps.org/doi/10.1103/{doi}"
    elif "nature.com" in host and path.endswith(".pdf"):
        headers["Referer"] = f"https://www.nature.com{path[:-4]}"
    return headers


def is_probable_supplement(marker: str) -> bool:
    if not any(
        token in marker
        for token in [
            "supplement",
            "supplementary",
            "appendix",
            "additional",
            "peer review file",
            "peer-review file",
            "reporting summary",
        ]
    ):
        return False
    return marker.endswith(".pdf") or ".pdf" in marker or re.search(r"\bpdf\b", marker) is not None


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


def is_probable_main_pdf_link(href: str, label: str) -> bool:
    href_lower = href.lower()
    label_lower = label.lower()
    if is_probable_non_article_pdf(f"{href_lower} {label_lower}"):
        return False
    if href_lower.endswith(".pdf"):
        return True
    return "download pdf" in label_lower or label_lower == "pdf"


def dedup(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _absolute(base_url: str, href: str) -> str:
    from urllib.parse import urljoin

    return urljoin(base_url, href)
