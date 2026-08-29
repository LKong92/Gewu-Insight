from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link, Text

from paper_monitor.resource_fingerprint import fingerprint_file


class ResourceFingerprintTests(unittest.TestCase):
    def test_publisher_links_do_not_mark_a_fresh_pdf_as_annotated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "publisher-links.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.add_annotation(
                page_number=0,
                annotation=Link(
                    rect=(72, 700, 180, 724),
                    url="https://doi.org/10.1000/example",
                ),
            )
            with path.open("wb") as handle:
                writer.write(handle)

            fingerprint = fingerprint_file(path)

            self.assertEqual(fingerprint.annotation_count, 0)
            self.assertFalse(fingerprint.is_annotated)

    def test_publisher_links_do_not_hide_real_reader_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "publisher-link-and-note.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.add_annotation(
                page_number=0,
                annotation=Link(rect=(72, 700, 180, 724), url="https://arxiv.org/"),
            )
            writer.add_annotation(
                page_number=0,
                annotation=Text(rect=(72, 650, 96, 674), text="personal note"),
            )
            with path.open("wb") as handle:
                writer.write(handle)

            fingerprint = fingerprint_file(path)

            self.assertEqual(fingerprint.annotation_count, 1)
            self.assertTrue(fingerprint.is_annotated)

    def test_annotation_changes_exact_hash_but_not_page_content_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clean = root / "clean.pdf"
            annotated = root / "annotated.pdf"

            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            with clean.open("wb") as handle:
                writer.write(handle)

            annotated_writer = PdfWriter()
            annotated_writer.append_pages_from_reader(PdfReader(str(clean)))
            annotated_writer.add_annotation(
                page_number=0,
                annotation=Text(rect=(72, 700, 96, 724), text="personal note"),
            )
            with annotated.open("wb") as handle:
                annotated_writer.write(handle)

            clean_fingerprint = fingerprint_file(clean)
            annotated_fingerprint = fingerprint_file(annotated)

            self.assertNotEqual(clean_fingerprint.sha256, annotated_fingerprint.sha256)
            self.assertEqual(clean_fingerprint.content_sha256, annotated_fingerprint.content_sha256)
            self.assertEqual(clean_fingerprint.annotation_count, 0)
            self.assertGreater(annotated_fingerprint.annotation_count, 0)
            self.assertTrue(annotated_fingerprint.is_annotated)
