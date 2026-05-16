from __future__ import annotations

from pathlib import Path


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
