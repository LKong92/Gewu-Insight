#!/usr/bin/env python3
"""Merge a main article PDF with PDF supplements.

Inputs and output are expected to live in ~/Downloads for this skill, but the
script accepts absolute paths so an agent can pass exact filenames.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PDF_MAGIC = b"%PDF-"


def expand(path: str) -> Path:
    return Path(path).expanduser().resolve()


def require_pdf(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Missing file: {path}")
    if not path.is_file():
        raise SystemExit(f"Not a file: {path}")
    with path.open("rb") as handle:
        header = handle.read(5)
    if header != PDF_MAGIC:
        raise SystemExit(f"Not a PDF by magic header: {path}")


def merge_with_pypdf(inputs: list[Path], output: Path) -> bool:
    try:
        from pypdf import PdfWriter
    except Exception:
        return False

    writer = PdfWriter()
    for pdf in inputs:
        writer.append(str(pdf))
    with output.open("wb") as handle:
        writer.write(handle)
    return True


def merge_with_pdfunite(inputs: list[Path], output: Path) -> bool:
    pdfunite = subprocess.run(
        ["which", "pdfunite"],
        check=False,
        capture_output=True,
        text=True,
    )
    if pdfunite.returncode != 0:
        return False
    subprocess.run(
        [pdfunite.stdout.strip(), *map(str, inputs), str(output)],
        check=True,
    )
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge main PDF and PDF supplements.")
    parser.add_argument("--main", required=True, help="Path to the main article PDF")
    parser.add_argument(
        "--supplement",
        action="append",
        default=[],
        help="Path to a PDF supplement; repeat in merge order",
    )
    parser.add_argument("--output", required=True, help="Path for the combined PDF")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    main_pdf = expand(args.main)
    supplements = [expand(item) for item in args.supplement]
    output = expand(args.output)

    if not supplements:
        raise SystemExit("At least one --supplement PDF is required.")

    inputs = [main_pdf, *supplements]
    for pdf in inputs:
        require_pdf(pdf)

    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    if not merge_with_pypdf(inputs, output):
        if not merge_with_pdfunite(inputs, output):
            raise SystemExit("Could not merge PDFs: install pypdf or pdfunite.")

    require_pdf(output)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
