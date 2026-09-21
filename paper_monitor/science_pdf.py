"""Science main-document checks and exact-byte supplement deduplication."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

from pypdf import PdfReader, PdfWriter

from .pdf_utils import is_valid_pdf_file
from .resource_fingerprint import sha256_for_file


COMPONENTS_KEY = "/GewuScienceComponentSHA256"


def is_science_supplement_reference(value: str) -> bool:
    marker = unquote(str(value or "")).casefold()
    return bool(re.search(
        r"/suppl(?:/|_)|/supplement|(?:_|[-.])sm\.(?:pdf|docx?)(?:$|[?#\s\"';])"
        r"|supplementary|supporting[ _-]+(?:information|materials)"
        r"|mdar|reproducibility[ _-]+checklist|reporting[ _-]+(?:summary|checklist)",
        marker,
    ))


def science_main_pdf_rejection(path: Path, *, url: str = "", filename: str = "") -> str:
    if is_science_supplement_reference(url) or is_science_supplement_reference(filename):
        return "Science returned a supplementary file instead of the main article PDF"
    # Only inspect the cover heading, never a later Supplementary Materials
    # section or an ordinary reference to supporting information in the article.
    reader = PdfReader(str(path), strict=False)
    try:
        if reader.is_encrypted:
            reader.decrypt("")
        lines = (reader.pages[0].extract_text() or "").splitlines()
    except Exception:
        lines = []
    heading = "\n".join(line.strip() for line in lines[:12])[:800]
    if re.search(
        r"(?im)^\s*(?:supplementary (?:materials|information|material)"
        r"|supporting (?:information|materials))\s*(?:for\b|$)"
        r"|materials design analysis reporting|^\s*MDAR\s+(?:checklist|framework)",
        heading,
    ):
        return "Science returned a supplementary file instead of the main article PDF"
    return ""


def merge_science_pdfs(main: Path, supplements: list[Path], output: Path) -> int:
    """Append each exact downloaded component once; retain the manifest on retry.

    Hashes describe original input bytes, not text similarity. Existing PDFs and
    annotations are never edited in place by this helper.
    """
    reader = PdfReader(str(main), strict=False)
    if reader.is_encrypted:
        reader.decrypt("")
    metadata = dict(reader.metadata or {})
    try:
        recorded = json.loads(str(metadata.get(COMPONENTS_KEY) or "[]"))
    except (TypeError, ValueError):
        recorded = []
    seen = {value for value in recorded if isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)} if isinstance(recorded, list) else set()
    seen.add(sha256_for_file(main))
    accepted: list[Path] = []
    for path in supplements:
        digest = sha256_for_file(path)
        if digest not in seen:
            seen.add(digest)
            accepted.append(path)
    if not accepted:
        shutil.copyfile(main, output)
        return 0
    writer = PdfWriter()
    writer.append(reader)
    for path in accepted:
        writer.append(str(path))
    metadata[COMPONENTS_KEY] = json.dumps(sorted(seen))
    writer.add_metadata({str(key): str(value) for key, value in metadata.items() if value is not None})
    with output.open("wb") as handle:
        writer.write(handle)
    if not is_valid_pdf_file(output):
        raise ValueError("Science PDF merge did not produce a complete PDF")
    return len(accepted)
