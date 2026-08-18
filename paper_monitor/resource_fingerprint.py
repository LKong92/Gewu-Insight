from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from pypdf import PdfReader


PDF_CONTENT_FINGERPRINT_VERSION = b"gewu-pdf-content-v1\0"


@dataclass(frozen=True)
class ResourceFingerprint:
    sha256: str
    content_sha256: str
    annotation_count: int
    size_bytes: int
    modified_at: str

    @property
    def is_annotated(self) -> bool:
        return self.annotation_count > 0


def sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_pdf_object(value: Any) -> Any:
    try:
        return value.get_object()
    except (AttributeError, KeyError, TypeError, ValueError):
        return value


def _digest_pdf_value(digest: Any, value: Any) -> None:
    text = str(value or "").encode("utf-8", errors="replace")
    digest.update(len(text).to_bytes(8, "big"))
    digest.update(text)


def _digest_page_xobjects(digest: Any, page: Any) -> None:
    resources = _resolved_pdf_object(page.get("/Resources")) or {}
    xobjects = _resolved_pdf_object(resources.get("/XObject")) if hasattr(resources, "get") else None
    if not hasattr(xobjects, "keys"):
        return
    for name in sorted(xobjects.keys(), key=str):
        obj = _resolved_pdf_object(xobjects[name])
        subtype = str(obj.get("/Subtype") or "") if hasattr(obj, "get") else ""
        if subtype not in {"/Image", "/Form"}:
            continue
        _digest_pdf_value(digest, name)
        _digest_pdf_value(digest, subtype)
        for key in ("/Width", "/Height", "/ColorSpace", "/BitsPerComponent", "/BBox", "/Matrix"):
            _digest_pdf_value(digest, obj.get(key) if hasattr(obj, "get") else "")
        try:
            payload = obj.get_data()
        except (AttributeError, OSError, TypeError, ValueError):
            payload = b""
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)


def pdf_content_fingerprint(path: Path) -> tuple[str, int]:
    """Return an advisory page-content hash that deliberately excludes PDF annotations.

    This is not an exact-file identity and must never be used by itself to delete or
    merge files. It is meant to relate a clean PDF to an annotated copy whose page
    content streams and embedded page images remain unchanged.
    """

    try:
        reader = PdfReader(str(path), strict=False)
        digest = hashlib.sha256(PDF_CONTENT_FINGERPRINT_VERSION)
        annotation_count = 0
        digest.update(len(reader.pages).to_bytes(8, "big"))
        for index, page in enumerate(reader.pages):
            digest.update(index.to_bytes(8, "big"))
            for key in ("/MediaBox", "/CropBox", "/Rotate"):
                _digest_pdf_value(digest, page.get(key))
            contents = page.get_contents()
            try:
                payload = contents.get_data() if contents is not None else b""
            except (AttributeError, OSError, TypeError, ValueError):
                payload = b""
            digest.update(len(payload).to_bytes(8, "big"))
            digest.update(payload)
            _digest_page_xobjects(digest, page)
            annotations = _resolved_pdf_object(page.get("/Annots"))
            if annotations is not None:
                try:
                    annotation_count += len(annotations)
                except TypeError:
                    annotation_count += 1
        return digest.hexdigest(), annotation_count
    except Exception:
        return "", 0


def fingerprint_file(path: Path) -> ResourceFingerprint:
    resolved = path.expanduser().resolve()
    stat = resolved.stat()
    content_sha256 = ""
    annotation_count = 0
    if resolved.suffix.lower() == ".pdf":
        content_sha256, annotation_count = pdf_content_fingerprint(resolved)
    return ResourceFingerprint(
        sha256=sha256_for_file(resolved),
        content_sha256=content_sha256,
        annotation_count=annotation_count,
        size_bytes=int(stat.st_size),
        modified_at=datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
    )
