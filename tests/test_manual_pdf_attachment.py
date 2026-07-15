from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from paper_monitor import ui_server
from paper_monitor.storage import Storage


class ManualPdfAttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.storage = Storage(self.root / "paper_monitor.sqlite")
        self.library_root = self.root / "data" / "Library"
        self.spaces_root = self.root / "data" / "Spaces"
        self.publications_root = self.root / "data" / "My Publications"
        self.pdf_root = self.root / "data" / "pdfs"
        self.patches = [
            patch.object(ui_server, "LIBRARY_LOCAL_COPY_ROOT", self.library_root),
            patch.object(ui_server, "SPACES_LOCAL_COPY_ROOT", self.spaces_root),
            patch.object(ui_server, "MY_PUBLICATIONS_LOCAL_COPY_ROOT", self.publications_root),
            patch.object(ui_server, "DEFAULT_PDF_DIR", self.pdf_root),
        ]
        for active_patch in self.patches:
            active_patch.start()

    def tearDown(self) -> None:
        for active_patch in reversed(self.patches):
            active_patch.stop()
        self.storage.close()
        self.tmp.cleanup()

    def add_paper(self, paper_id: str) -> None:
        self.storage.upsert_paper(
            {
                "paper_id": paper_id,
                "doi": "",
                "title": f"Paper {paper_id}",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "source": "fixture",
                "section_allowed": True,
                "raw": {},
            }
        )

    def write_pdf(self, relative_path: str) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        with path.open("wb") as handle:
            writer.write(handle)
        return path

    def test_dropped_pdf_is_copied_into_current_library_folder(self) -> None:
        self.add_paper("paper-library")
        folder = self.storage.ensure_library_folder(parent_id=1, name="Reading")
        item = self.storage.add_library_item(paper_id="paper-library", folder_id=int(folder["id"]))
        source = self.write_pdf("external/My Copy.pdf")

        target, paper = ui_server.attach_manual_pdf_to_paper(
            self.storage,
            paper_id="paper-library",
            filename=source.name,
            context={"context": "library", "folder_id": folder["id"], "item_id": item["id"]},
            source_path=source,
            preserve_filename=True,
        )

        self.assertEqual(target, self.library_root / "Reading" / "My Copy.pdf")
        self.assertTrue(source.exists(), "The external source PDF must remain untouched")
        self.assertEqual(target.read_bytes(), source.read_bytes())
        self.assertEqual(paper["main_pdf_path"], str(target))
        self.assertEqual(paper["merged_pdf_path"], str(target))
        self.assertEqual(paper["download_status"], "success")

    def test_dropped_pdf_in_my_publications_uses_publications_root(self) -> None:
        self.add_paper("paper-publication")
        self.storage.add_my_publication(paper_id="paper-publication")
        source = self.write_pdf("external/Publication.pdf")

        target, paper = ui_server.attach_manual_pdf_to_paper(
            self.storage,
            paper_id="paper-publication",
            filename=source.name,
            context={"context": "my-publications"},
            source_path=source,
            preserve_filename=True,
        )

        self.assertEqual(target, self.publications_root / "Publication.pdf")
        self.assertTrue(source.exists())
        self.assertEqual(paper["merged_pdf_path"], str(target))

    def test_non_pdf_content_is_rejected_without_writing_a_copy(self) -> None:
        self.add_paper("paper-invalid")
        source = self.root / "external" / "Not Really.pdf"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text("not a PDF", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "valid PDF"):
            ui_server.attach_manual_pdf_to_paper(
                self.storage,
                paper_id="paper-invalid",
                filename=source.name,
                context={"context": "library", "folder_id": 1},
                source_path=source,
                preserve_filename=True,
            )

        self.assertFalse(self.library_root.exists())
        paper = self.storage.get_paper("paper-invalid")
        self.assertFalse(paper["merged_pdf_path"])


if __name__ == "__main__":
    unittest.main()
