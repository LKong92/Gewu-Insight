from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re

from pypdf import PdfReader


PDF_HEADER_PATTERN = re.compile(br"%PDF-[0-9]\.[0-9]")
PDF_HEADER_SCAN_BYTES = 1024
PDF_TRAILER_SCAN_BYTES = 4096


def _has_pdf_envelope(header: bytes, trailer: bytes) -> bool:
    return bool(PDF_HEADER_PATTERN.search(header)) and b"%%EOF" in trailer


def _reader_is_parseable(reader: PdfReader) -> bool:
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception:
            # A password-protected PDF can still be structurally valid even though
            # Gewu Insight cannot inspect its pages without the password.
            return True
        if reader.is_encrypted:
            return True
    try:
        len(reader.pages)
    except Exception:
        return False
    return True


def is_valid_pdf_bytes(content: bytes) -> bool:
    """Return whether bytes contain a complete, parseable PDF document."""

    if not content or not _has_pdf_envelope(
        content[:PDF_HEADER_SCAN_BYTES],
        content[-PDF_TRAILER_SCAN_BYTES:],
    ):
        return False
    try:
        return _reader_is_parseable(PdfReader(BytesIO(content), strict=False))
    except Exception:
        return False


def is_valid_pdf_file(path: Path) -> bool:
    """Return whether a local file contains a complete, parseable PDF document."""

    try:
        resolved = path.expanduser().resolve()
        size = resolved.stat().st_size
        if size <= 0:
            return False
        with resolved.open("rb") as handle:
            header = handle.read(PDF_HEADER_SCAN_BYTES)
            handle.seek(max(0, size - PDF_TRAILER_SCAN_BYTES))
            trailer = handle.read(PDF_TRAILER_SCAN_BYTES)
        if not _has_pdf_envelope(header, trailer):
            return False
        return _reader_is_parseable(PdfReader(str(resolved), strict=False))
    except Exception:
        return False


def merge_pdfs(input_paths: list[Path], output_path: Path) -> None:
    try:
        from pypdf import PdfWriter
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF merging. Install with: pip install -r requirements.txt") from exc

    writer = PdfWriter()
    for input_path in input_paths:
        with input_path.open("rb") as handle:
            writer.append(handle)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
