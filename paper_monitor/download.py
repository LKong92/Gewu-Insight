from __future__ import annotations

import mimetypes
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from .aps import aps_journal_slug as canonical_aps_journal_slug
from .config import DEFAULT_PDF_DIR
from .http import request_with_retries
from .pdf_utils import merge_pdfs
from .sources.openalex import openalex_request
from .sources.publisher import request_aps_page
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
    preserved_main_pdf_path = existing_science_main_only_pdf_path(paper) if force else None
    main_pdf_path: Path | None = preserved_main_pdf_path
    main_pdf_url = ""
    supplement_paths: list[Path] = []
    messages: list[str] = []

    if not main_pdf_path:
        for index, url in enumerate(candidates["main"]):
            path = target_dir / "main.pdf"
            if try_download_pdf(url, path, messages):
                main_pdf_path = path
                main_pdf_url = url
                break

    for index, url in enumerate(candidates["supplements"], start=1):
        path = target_dir / f"supplement_{index}.pdf"
        if try_download_pdf(url, path, messages):
            supplement_paths.append(path)

    for index, url in enumerate(candidates.get("supplement_documents") or [], start=1):
        source_path = try_download_word_supplement(
            url,
            target_dir / f"supplement_document_{index}",
            messages,
        )
        if not source_path:
            continue
        converted_path = target_dir / f"supplement_document_{index}.pdf"
        try:
            convert_word_document_to_pdf(source_path, converted_path)
            supplement_paths.append(converted_path)
        except Exception as exc:
            messages.append(f"{url}: Word supplement conversion failed: {exc}")
        finally:
            source_path.unlink(missing_ok=True)

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

    if preserved_main_pdf_path and not supplement_paths:
        status = "partial"
        message = "existing main PDF kept; no PDF supplement found"
        storage.update_download_status(
            paper_id,
            status=status,
            message=message,
            main_pdf_path=str(preserved_main_pdf_path),
            supplement_pdf_paths=[],
            merged_pdf_path=str(preserved_main_pdf_path),
        )
        return {
            "status": status,
            "message": message,
            "main_pdf_path": str(preserved_main_pdf_path),
            "main_pdf_url": "",
            "supplement_pdf_paths": [],
            "merged_pdf_path": str(preserved_main_pdf_path),
        }

    current_merged_path = str(paper.get("merged_pdf_path") or "")
    merged_path = unique_download_path(
        target_dir / f"{safe_slug(paper.get('title') or paper_id, 80)}_merged.pdf",
        # A forced refresh is a new version candidate.  Keep the current file
        # untouched until the resource layer has archived or de-duplicated it.
        current_path="" if force else current_merged_path,
    )
    working_merged_path = merged_path
    replacing_existing_pdf = merged_path.exists()
    if replacing_existing_pdf or (preserved_main_pdf_path and merged_path == preserved_main_pdf_path):
        working_merged_path = merged_path.with_name(f".{merged_path.stem}-download-merge.pdf")
        working_merged_path.unlink(missing_ok=True)
    downloaded_pdf_replaced = False
    try:
        merge_inputs = [main_pdf_path] + supplement_paths
        merge_pdfs(merge_inputs, working_merged_path)
        if working_merged_path != merged_path:
            working_merged_path.replace(merged_path)
        downloaded_pdf_replaced = True
        status = "success" if supplement_paths else "partial"
        message = "downloaded and merged; temporary PDFs removed" if supplement_paths else "main PDF saved as merged PDF; no PDF supplement found"
    except Exception as exc:
        if working_merged_path != merged_path:
            working_merged_path.unlink(missing_ok=True)
        if not replacing_existing_pdf and main_pdf_path != merged_path:
            shutil.copyfile(main_pdf_path, merged_path)
        status = "partial"
        if replacing_existing_pdf:
            message = f"existing PDF kept; refreshed PDF merge failed: {exc}"
        else:
            message = f"main PDF saved as merged PDF; supplement merge failed: {exc}"

    intermediate_paths = list(supplement_paths)
    if not preserved_main_pdf_path:
        intermediate_paths.insert(0, main_pdf_path)
    remove_intermediate_pdfs(intermediate_paths, keep=merged_path)

    storage.update_download_status(
        paper_id,
        status=status,
        message=message,
        main_pdf_path=str(merged_path),
        supplement_pdf_paths=[],
        merged_pdf_path=str(merged_path),
        pdf_url=main_pdf_url if downloaded_pdf_replaced else None,
    )
    return {
        "status": status,
        "message": message,
        "main_pdf_path": str(merged_path),
        "main_pdf_url": main_pdf_url,
        "supplement_pdf_paths": [],
        "merged_pdf_path": str(merged_path),
    }


def existing_science_main_only_pdf_path(paper: dict[str, Any]) -> Path | None:
    doi = normalize_doi(paper.get("doi") or "")
    if not doi.startswith("10.1126/"):
        return None
    message = str(paper.get("download_message") or "").lower()
    if "merged science supplementary pdf" in message or message.startswith("downloaded and merged"):
        return None
    for key in ("merged_pdf_path", "main_pdf_path"):
        raw = str(paper.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        try:
            if not path.exists() or not path.is_file() or path.stat().st_size < 1024:
                continue
            with path.open("rb") as handle:
                if b"%PDF-" not in handle.read(1024):
                    continue
            return path.resolve()
        except OSError:
            continue
    return None


def unique_download_path(path: Path, *, current_path: str = "") -> Path:
    try:
        current_resolved = Path(current_path).expanduser().resolve() if current_path else None
    except OSError:
        current_resolved = None
    # A forced refresh must replace the paper's current canonical file even
    # when an older collision suffix (for example ``merged 2.pdf``) is part of
    # that canonical name.  Otherwise every refresh creates another numbered
    # copy and leaves the database pointing at a moving filename.
    try:
        if (
            current_resolved
            and current_resolved.exists()
            and current_resolved.parent == path.parent.expanduser().resolve()
        ):
            return current_resolved
    except OSError:
        pass
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
    supplement_documents: list[str] = []
    doi = normalize_doi(paper.get("doi") or "")

    # AAAS currently places an anti-bot challenge in front of direct PDF
    # requests. Prefer verified open repository copies before trying the
    # publisher URLs, while retaining the publisher candidates as fallbacks.
    if doi.startswith("10.1126/"):
        main.extend(science_open_access_pdf_candidates(doi))
        supplements.extend(science_supplement_pdf_candidates(doi))
    doi_candidates = doi_pdf_candidates(doi)
    # Nature keeps some accepted-manuscript ``*_reference.pdf`` URLs alive
    # after the version of record is published.  A stale URL can therefore
    # remain perfectly downloadable and prevent the canonical article PDF
    # from ever being attempted.  Put the DOI-derived version-of-record URL
    # first; reference PDFs remain available only as final fallbacks.
    if doi.startswith("10.1038/") and doi_candidates:
        main.append(doi_candidates.pop(0))
    main.extend(journal_pdf_candidates(paper))
    if paper.get("pdf_url"):
        main.append(paper["pdf_url"])
    main.extend(doi_candidates)
    crossref_candidates = crossref_pdf_candidates(doi)
    main.extend(science_direct_pdf_candidates(crossref_candidates))
    main.extend(crossref_candidates)

    landing_url = paper.get("landing_url") or paper.get("url")
    if landing_url:
        try:
            if doi.startswith("10.1103/"):
                response = request_aps_page(landing_url)
                if response is None:
                    raise RuntimeError("APS page request paused by rate-limit protection")
            else:
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
                if is_probable_word_supplement(marker):
                    supplement_documents.append(href)
                elif is_probable_supplement(marker):
                    supplements.append(href)
                elif is_probable_non_article_pdf(marker):
                    continue
                elif is_probable_main_pdf_link(href, label):
                    main.append(href)
        except Exception:
            pass

    main = dedup(main)
    if doi.startswith("10.1038/"):
        main = [url for url in main if not is_nature_reference_pdf_url(url)] + [
            url for url in main if is_nature_reference_pdf_url(url)
        ]

    return {
        "main": main,
        "supplements": [url for url in dedup(supplements) if url not in main],
        "supplement_documents": dedup(supplement_documents),
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


def is_nature_reference_pdf_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    return "nature.com" in parsed.netloc.lower() and parsed.path.lower().endswith("_reference.pdf")


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
    if doi.startswith("10.1021/"):
        return [
            f"https://pubs.acs.org/doi/pdf/{doi}",
            f"https://pubs.acs.org/doi/epdf/{doi}",
        ]
    if doi.startswith("10.1002/"):
        candidates = [
            f"https://onlinelibrary.wiley.com/doi/pdfdirect/{doi}",
            f"https://onlinelibrary.wiley.com/doi/pdf/{doi}",
        ]
        if "advanced" in journal:
            candidates.insert(0, f"https://advanced.onlinelibrary.wiley.com/doi/pdf/{doi}")
        return candidates
    if doi.startswith("10.1088/0256-307x/"):
        return [
            f"https://cpl.iphy.ac.cn/en/article/pdf/preview/{doi}.pdf",
            f"https://iopscience.iop.org/article/{doi}/pdf",
        ]
    if doi.startswith("10.1088/1674-1056/"):
        return cpb_pdf_candidates(doi) + [
            f"https://iopscience.iop.org/article/{doi}/pdf",
        ]
    return []


def cpb_pdf_candidates(doi: str) -> list[str]:
    doi = normalize_doi(doi)
    if not doi.startswith("10.1088/1674-1056/"):
        return []
    search_sql = f"((( AND 2[Journal]) AND {doi}[DOI]) AND year[Order])"
    try:
        response = request_with_retries(
            "POST",
            "https://cpb.iphy.ac.cn/EN/article/advancedSearchResult.do",
            data={"searchSQL": search_sql, "language": "EN"},
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://cpb.iphy.ac.cn/EN/article/advancedSearch.do",
            },
            timeout=12,
            max_retries=1,
        )
    except Exception:
        return []
    if doi not in response.text.lower():
        return []
    article_ids = re.findall(
        r"""lsdy1\(\s*['"]PDF['"]\s*,\s*['"](\d+)['"]""",
        response.text,
        flags=re.IGNORECASE,
    )
    return dedup(
        [
            "https://cpb.iphy.ac.cn/EN/article/"
            f"downloadArticleFile.do?attachType=PDF&id={article_id}"
            for article_id in article_ids
        ]
    )


def science_direct_pdf_candidates(urls: list[str]) -> list[str]:
    candidates: list[str] = []
    for url in urls:
        match = re.search(r"/pii/([A-Z0-9]+)", str(url), flags=re.IGNORECASE)
        if not match:
            continue
        pii = match.group(1)
        candidates.append(
            "https://www.sciencedirect.com/science/article/pii/"
            f"{pii}/pdfft?isDTMRedir=true&download=true"
        )
    return dedup(candidates)


def publisher_browser_candidate(paper: dict[str, Any]) -> dict[str, str] | None:
    doi = normalize_doi(paper.get("doi") or "")
    journal = str(paper.get("journal") or "").lower()
    if not doi:
        return None
    if doi.startswith("10.1103/"):
        aps_slug = aps_journal_slug(journal)
        if not aps_slug:
            return None
        return {
            "publisher": "aps",
            "url": f"https://journals.aps.org/{aps_slug}/pdf/{doi}",
            "referer": f"https://journals.aps.org/{aps_slug}/abstract/{doi}",
        }
    if doi.startswith("10.1021/"):
        return {
            "publisher": "acs",
            "url": f"https://pubs.acs.org/doi/pdf/{doi}",
            "referer": f"https://pubs.acs.org/doi/{doi}",
        }
    if doi.startswith("10.1002/"):
        host = "advanced.onlinelibrary.wiley.com" if "advanced" in journal else "onlinelibrary.wiley.com"
        article_url = f"https://{host}/doi/{doi}"
        return {
            "publisher": "wiley",
            "url": article_url,
            "referer": article_url,
            "target_url": f"https://{host}/doi/pdfdirect/{doi}",
        }
    if doi.startswith("10.1088/0256-307x/"):
        return {
            "publisher": "cpl",
            "url": f"https://cpl.iphy.ac.cn/en/article/pdf/preview/{doi}.pdf",
            "referer": f"https://cpl.iphy.ac.cn/en/article/doi/{doi}",
        }
    if doi.startswith("10.1088/1674-1056/"):
        cpb_candidates = cpb_pdf_candidates(doi)
        return {
            "publisher": "cpb",
            "url": cpb_candidates[0] if cpb_candidates else f"https://iopscience.iop.org/article/{doi}/pdf",
            "referer": f"https://cpb.iphy.ac.cn/EN/{doi}",
        }
    if doi.startswith("10.1016/j.scib."):
        crossref_candidates = crossref_pdf_candidates(doi)
        direct_candidates = science_direct_pdf_candidates(crossref_candidates)
        if direct_candidates:
            pii_match = re.search(r"/pii/([A-Z0-9]+)", direct_candidates[0], flags=re.IGNORECASE)
            referer = (
                f"https://www.sciencedirect.com/science/article/pii/{pii_match.group(1)}"
                if pii_match
                else "https://www.sciencedirect.com/journal/science-bulletin"
            )
            return {
                "publisher": "elsevier",
                "url": referer,
                "referer": referer,
                "target_url": direct_candidates[0],
            }
        return None
    if doi.startswith("10.1093/nsr/") or "national science review" in journal:
        urls = [
            str(paper.get("pdf_url") or ""),
            *crossref_pdf_candidates(doi),
        ]
        for url in urls:
            parsed = urlparse(url)
            if parsed.netloc.lower().endswith("academic.oup.com"):
                return {
                    "publisher": "oup",
                    "url": url,
                    "referer": f"https://academic.oup.com/nsr/advance-article/doi/{doi}",
                }
        return {
            "publisher": "oup",
            "url": f"https://academic.oup.com/nsr/advance-article/doi/{doi}",
            "referer": "https://academic.oup.com/nsr/advance-articles",
        }
    return None


def aps_journal_slug(journal: str) -> str:
    return canonical_aps_journal_slug(journal)


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
        response = openalex_request(
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


def try_download_pdf(
    url: str,
    path: Path,
    messages: list[str],
    *,
    request_max_retries: int | None = None,
) -> bool:
    try:
        request_options: dict[str, Any] = {
            "headers": pdf_request_headers(url),
            "stream": True,
        }
        if request_max_retries is not None:
            request_options["max_retries"] = max(1, int(request_max_retries))
        response = request_with_retries("GET", url, **request_options)
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


def try_download_word_supplement(
    url: str,
    path_without_suffix: Path,
    messages: list[str],
) -> Path | None:
    try:
        response = request_with_retries(
            "GET",
            url,
            headers=pdf_request_headers(url),
            stream=True,
        )
        content = response.content
        content_type = response.headers.get("content-type", "").lower()
        if content.startswith(b"PK\x03\x04") or "officedocument.wordprocessingml" in content_type:
            suffix = ".docx"
        elif content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1") or "msword" in content_type:
            suffix = ".doc"
        else:
            messages.append(f"not a Word document payload: {url}")
            return None
        path = path_without_suffix.with_suffix(suffix)
        path.write_bytes(content)
        return path
    except Exception as exc:
        messages.append(f"{url}: {download_error_message(exc)}")
        return None


def convert_word_document_to_pdf(source_path: Path, target_path: Path) -> Path:
    source_path = source_path.expanduser().resolve()
    target_path = target_path.expanduser().resolve()
    if source_path.suffix.lower() not in {".doc", ".docx"}:
        raise ValueError("Only DOC and DOCX supplements can be converted")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.unlink(missing_ok=True)

    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            subprocess.run(
                [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(target_path.parent),
                    str(source_path),
                ],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=90,
            )
            generated = target_path.parent / f"{source_path.stem}.pdf"
            if generated.exists() and generated != target_path:
                generated.replace(target_path)
            if is_valid_pdf_file(target_path):
                return target_path
        except (OSError, subprocess.SubprocessError):
            target_path.unlink(missing_ok=True)

    text_path = target_path.with_name(f".{target_path.stem}-converted.txt")
    try:
        subprocess.run(
            [
                "/usr/bin/textutil",
                "-convert",
                "txt",
                "-output",
                str(text_path),
                str(source_path),
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        with target_path.open("wb") as output:
            subprocess.run(
                ["/usr/sbin/cupsfilter", "-m", "application/pdf", str(text_path)],
                check=True,
                stdout=output,
                stderr=subprocess.PIPE,
                timeout=60,
            )
    finally:
        text_path.unlink(missing_ok=True)
    if not is_valid_pdf_file(target_path):
        target_path.unlink(missing_ok=True)
        raise ValueError("Converted supplement is not a valid PDF")
    return target_path


def is_valid_pdf_file(path: Path) -> bool:
    try:
        if not path.exists() or path.stat().st_size < 1024:
            return False
        with path.open("rb") as handle:
            return b"%PDF-" in handle.read(1024)
    except OSError:
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
    elif host == "pubs.acs.org" and "/doi/" in path:
        doi = re.sub(r"^/(?:doi/)?(?:pdf/|epdf/)?", "", path, flags=re.IGNORECASE)
        if doi:
            headers["Referer"] = f"https://pubs.acs.org/doi/{doi}"
    elif host.endswith("onlinelibrary.wiley.com") and "/doi/" in path:
        doi = re.sub(r"^/doi/(?:pdfdirect/|pdf/)?", "", path, flags=re.IGNORECASE)
        if doi:
            headers["Referer"] = f"https://{host}/doi/{doi}"
    elif host == "iopscience.iop.org" and "/article/" in path:
        article_path = path[:-4] if path.endswith("/pdf") else path
        headers["Referer"] = f"https://iopscience.iop.org{article_path}"
    elif host == "cpl.iphy.ac.cn":
        headers["Referer"] = "https://cpl.iphy.ac.cn/en/"
    elif host == "cpb.iphy.ac.cn":
        headers["Referer"] = "https://cpb.iphy.ac.cn/EN/"
    elif host.endswith("sciencedirect.com") and "/pdfft" in path:
        headers["Referer"] = f"https://{host}{path.split('/pdfft', 1)[0]}"
    elif host.endswith("academic.oup.com"):
        headers["Referer"] = "https://academic.oup.com/nsr"
    return headers


def is_probable_supplement(marker: str) -> bool:
    if not any(
        token in marker
        for token in [
            "supplement",
            "supplementary",
            "supinfo",
            "suppinfo",
            "suppdata",
            "appendix",
            "additional",
            "peer review file",
            "peer-review file",
            "reporting summary",
        ]
    ):
        return False
    return marker.endswith(".pdf") or ".pdf" in marker or re.search(r"\bpdf\b", marker) is not None


def is_probable_word_supplement(marker: str) -> bool:
    if not any(
        token in marker
        for token in [
            "supplement",
            "supplementary",
            "supporting information",
            "supinfo",
            "suppinfo",
            "suppdata",
            "appendix",
            "additional",
        ]
    ):
        return False
    return (
        re.search(r"\.docx?(?:$|[?#\s])", marker, flags=re.IGNORECASE) is not None
        or re.search(r"\b(?:microsoft\s+)?word\b", marker, flags=re.IGNORECASE) is not None
    )


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
