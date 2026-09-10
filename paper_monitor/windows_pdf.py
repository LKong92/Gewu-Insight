"""Windows PDF thumbnails, rendered without macOS command-line tools.

PDFium is not thread safe, even for separate documents. All calls and object
cleanup are serialized; original PDFs are opened read-only and never rewritten.
"""
from io import BytesIO
from pathlib import Path
from threading import Lock
from functools import lru_cache
import math

_render_lock = Lock()


@lru_cache(maxsize=128)
def page_count(path: str, size: int, modified_ns: int) -> int:
    import pypdfium2 as pdfium
    with _render_lock:
        document = pdfium.PdfDocument(path)
        try:
            return len(document)
        finally:
            document.close()


@lru_cache(maxsize=64)
def page_sizes(path: str, size: int, modified_ns: int) -> tuple[tuple[float, float], ...]:
    """Stable page geometry allows continuous scrolling before pixels arrive."""
    import pypdfium2 as pdfium
    with _render_lock:
        document = pdfium.PdfDocument(path)
        try:
            result = tuple(document.get_page_size(index) for index in range(len(document)))
            if any(not all(math.isfinite(value) and value > 0 for value in pair) for pair in result):
                raise ValueError("Invalid PDF page dimensions")
            return result
        finally:
            document.close()


def page_text(path: Path, page_number: int) -> str:
    """Bounded, selectable text for the current page; never OCR or rewrite."""
    import pypdfium2 as pdfium
    with _render_lock:
        document = pdfium.PdfDocument(str(path))
        try:
            if not 1 <= page_number <= len(document):
                raise ValueError("PDF page not found")
            page = document[page_number - 1]
            try:
                text = page.get_textpage()
                try:
                    return text.get_text_range(0, min(text.count_chars(), 64000))
                finally:
                    text.close()
            finally:
                page.close()
        finally:
            document.close()


def render_page_png(path: Path, page_number: int, size: int = 240) -> bytes:
    import pypdfium2 as pdfium

    size = max(32, min(2048, int(size)))
    with _render_lock:
        document = pdfium.PdfDocument(str(path))
        try:
            if len(document) < 1:
                raise ValueError("The PDF has no pages")
            page = document[max(0, min(len(document) - 1, int(page_number) - 1))]
            try:
                longest = max(page.get_size())
                if not math.isfinite(longest) or longest <= 0:
                    raise ValueError("Invalid PDF page dimensions")
                bitmap = page.render(scale=size / longest)
                try:
                    with bitmap.to_pil() as image:
                        output = BytesIO()
                        image.save(output, format="PNG")
                        return output.getvalue()
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            document.close()
