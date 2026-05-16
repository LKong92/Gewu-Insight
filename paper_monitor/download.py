from __future__ import annotations

import mimetypes
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

    target_dir = pdf_dir / paper_id
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

    merged_path = target_dir / f"{safe_slug(paper.get('title') or paper_id, 80)}_merged.pdf"
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

    if paper.get("pdf_url"):
        main.append(paper["pdf_url"])
    main.extend(doi_pdf_candidates(paper.get("doi") or ""))

    landing_url = paper.get("landing_url") or paper.get("url")
    if landing_url:
        try:
            response = request_with_retries("GET", landing_url)
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup.find_all("meta", attrs={"name": "citation_pdf_url"}):
                if tag.get("content"):
                    main.append(_absolute(landing_url, tag["content"]))
            for link in soup.find_all("a", href=True):
                href = _absolute(landing_url, link["href"])
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
    doi = doi.replace("https://doi.org/", "").strip()
    if not doi:
        return []
    candidates = []
    if doi.startswith("10.1038/"):
        article_id = doi.split("/", 1)[1]
        candidates.append(f"https://www.nature.com/articles/{article_id}.pdf")
    if doi.startswith("10.1126/"):
        candidates.append(f"https://www.science.org/doi/pdf/{doi}")
        candidates.append(f"https://www.science.org/doi/epdf/{doi}")
    candidates.append(f"https://doi.org/{doi}")
    return candidates


def try_download_pdf(url: str, path: Path, messages: list[str]) -> bool:
    try:
        response = request_with_retries("GET", url, stream=True)
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
        messages.append(f"{url}: {exc}")
        return False


def is_probable_supplement(marker: str) -> bool:
    if not any(token in marker for token in ["supplement", "supplementary", "appendix", "additional"]):
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
