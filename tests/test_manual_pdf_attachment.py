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

    def test_replacement_trashes_old_managed_pdf_after_new_copy_succeeds(self) -> None:
        self.add_paper("paper-replace")
        folder = self.storage.ensure_library_folder(parent_id=1, name="Reading")
        item = self.storage.add_library_item(paper_id="paper-replace", folder_id=int(folder["id"]))
        old_pdf = self.write_pdf("data/Library/Reading/Old.pdf")
        self.storage.update_download_status(
            "paper-replace",
            status="success",
            message="old PDF",
            main_pdf_path=str(old_pdf),
            supplement_pdf_paths=[],
            merged_pdf_path=str(old_pdf),
        )
        source = self.write_pdf("external/Replacement.pdf")
        trash_dir = self.root / "Finder Trash"
        trash_dir.mkdir()

        def fake_trash(path: Path) -> Path:
            destination = trash_dir / path.name
            path.rename(destination)
            return destination

        with patch.object(ui_server, "move_path_to_macos_trash", side_effect=fake_trash) as trash:
            target, paper = ui_server.attach_manual_pdf_to_paper(
                self.storage,
                paper_id="paper-replace",
                filename=source.name,
                context={"context": "library", "folder_id": folder["id"], "item_id": item["id"]},
                source_path=source,
                preserve_filename=True,
            )

        trash.assert_called_once_with(old_pdf.resolve())
        self.assertFalse(old_pdf.exists())
        self.assertTrue((trash_dir / old_pdf.name).exists())
        self.assertTrue(source.exists(), "The dragged external PDF must never be removed")
        self.assertEqual(target, self.library_root / "Reading" / "Replacement.pdf")
        self.assertEqual(paper["main_pdf_path"], str(target))
        self.assertEqual(paper["merged_pdf_path"], str(target))
        self.assertIn("manual PDF replaced", paper["download_message"])

    def test_replacement_never_deletes_external_old_pdf(self) -> None:
        self.add_paper("paper-external-old")
        folder = self.storage.ensure_library_folder(parent_id=1, name="Reading")
        item = self.storage.add_library_item(paper_id="paper-external-old", folder_id=int(folder["id"]))
        old_external = self.write_pdf("external/Old External.pdf")
        self.storage.update_download_status(
            "paper-external-old",
            status="success",
            message="old external PDF",
            main_pdf_path=str(old_external),
            supplement_pdf_paths=[],
            merged_pdf_path=str(old_external),
        )
        source = self.write_pdf("external/New External.pdf")

        with patch.object(ui_server, "move_path_to_macos_trash") as trash:
            target, paper = ui_server.attach_manual_pdf_to_paper(
                self.storage,
                paper_id="paper-external-old",
                filename=source.name,
                context={"context": "library", "folder_id": folder["id"], "item_id": item["id"]},
                source_path=source,
                preserve_filename=True,
            )

        trash.assert_not_called()
        self.assertTrue(old_external.exists())
        self.assertTrue(source.exists())
        self.assertEqual(paper["merged_pdf_path"], str(target))

    def test_invalid_replacement_keeps_existing_pdf_and_database_path(self) -> None:
        self.add_paper("paper-invalid-replacement")
        old_pdf = self.write_pdf("data/Library/Old.pdf")
        self.storage.update_download_status(
            "paper-invalid-replacement",
            status="success",
            message="old PDF",
            main_pdf_path=str(old_pdf),
            supplement_pdf_paths=[],
            merged_pdf_path=str(old_pdf),
        )
        invalid = self.root / "external" / "Invalid.pdf"
        invalid.parent.mkdir(parents=True, exist_ok=True)
        invalid.write_text("not a PDF", encoding="utf-8")

        with patch.object(ui_server, "move_path_to_macos_trash") as trash:
            with self.assertRaisesRegex(ValueError, "valid PDF"):
                ui_server.attach_manual_pdf_to_paper(
                    self.storage,
                    paper_id="paper-invalid-replacement",
                    filename=invalid.name,
                    context={"context": "library", "folder_id": 1},
                    source_path=invalid,
                    preserve_filename=True,
                )

        trash.assert_not_called()
        self.assertTrue(old_pdf.exists())
        paper = self.storage.get_paper("paper-invalid-replacement")
        self.assertEqual(paper["main_pdf_path"], str(old_pdf))
        self.assertEqual(paper["merged_pdf_path"], str(old_pdf))

    def test_shared_managed_old_pdf_is_not_trashed(self) -> None:
        self.add_paper("paper-shared-a")
        self.add_paper("paper-shared-b")
        old_pdf = self.write_pdf("data/pdfs/shared.pdf")
        for paper_id in ("paper-shared-a", "paper-shared-b"):
            self.storage.update_download_status(
                paper_id,
                status="success",
                message="shared PDF",
                main_pdf_path=str(old_pdf),
                supplement_pdf_paths=[],
                merged_pdf_path=str(old_pdf),
            )
        source = self.write_pdf("external/New.pdf")

        with patch.object(ui_server, "move_path_to_macos_trash") as trash:
            _, paper = ui_server.attach_manual_pdf_to_paper(
                self.storage,
                paper_id="paper-shared-a",
                filename=source.name,
                context={"context": "library", "folder_id": 1},
                source_path=source,
                preserve_filename=True,
            )

        trash.assert_not_called()
        self.assertTrue(old_pdf.exists())
        self.assertNotEqual(paper["merged_pdf_path"], str(old_pdf))
        self.assertEqual(self.storage.get_paper("paper-shared-b")["merged_pdf_path"], str(old_pdf))

    def test_existing_pdf_download_buttons_are_drop_replacement_targets(self) -> None:
        self.assertIn('data-pdf-replace="${paper.merged_pdf_path ? "1" : "0"}"', ui_server.INDEX_HTML)
        self.assertIn('data-pdf-replace="1"].drag-over::after', ui_server.INDEX_HTML)
        self.assertIn('replacing: Boolean(paper.merged_pdf_path)', ui_server.INDEX_HTML)

    def test_science_supplement_is_merged_after_main_and_temporary_source_is_not_stored(self) -> None:
        self.add_paper("paper-science")
        main = self.write_pdf("data/pdfs/paper-science/Main.pdf")
        supplement = self.write_pdf("native-temp/Science Supplement.pdf")
        self.storage.update_download_status(
            "paper-science",
            status="partial",
            message="main PDF saved as merged PDF; no PDF supplement found",
            main_pdf_path=str(main),
            supplement_pdf_paths=[],
            merged_pdf_path=str(main),
        )

        target, paper = ui_server.attach_publisher_supplement_pdf_to_paper(
            self.storage,
            paper_id="paper-science",
            context={"publisher_download_kind": "aaas-supplement-pdf"},
            source_path=supplement,
        )

        self.assertEqual(target, main.resolve())
        self.assertEqual(len(ui_server.PdfReader(str(target)).pages), 2)
        self.assertTrue(supplement.exists(), "The native wrapper owns and removes its temporary file")
        self.assertEqual(paper["download_status"], "success")
        self.assertEqual(paper["main_pdf_path"], str(target))
        self.assertEqual(paper["merged_pdf_path"], str(target))
        self.assertEqual(paper["supplement_pdf_paths"], "[]")
        self.assertIn("merged Science supplementary PDF", paper["download_message"])

    def test_docx_supplement_is_converted_then_merged(self) -> None:
        self.add_paper("paper-docx")
        main = self.write_pdf("data/pdfs/paper-docx/Main.pdf")
        supplement = self.root / "native-temp" / "Supplement.docx"
        supplement.parent.mkdir(parents=True, exist_ok=True)
        supplement.write_bytes(b"PK\x03\x04" + b"x" * 2048)
        self.storage.update_download_status(
            "paper-docx",
            status="partial",
            message="main PDF saved as merged PDF; no PDF supplement found",
            main_pdf_path=str(main),
            supplement_pdf_paths=[],
            merged_pdf_path=str(main),
        )

        def fake_conversion(_source: Path, target: Path) -> Path:
            writer = PdfWriter()
            writer.add_blank_page(width=200, height=200)
            with target.open("wb") as handle:
                writer.write(handle)
            return target

        with patch.object(
            ui_server,
            "convert_word_document_to_pdf",
            side_effect=fake_conversion,
        ):
            target, paper = ui_server.attach_publisher_supplement_pdf_to_paper(
                self.storage,
                paper_id="paper-docx",
                context={"publisher_download_kind": "publisher-supplement-file"},
                source_path=supplement,
            )

        self.assertEqual(len(ui_server.PdfReader(str(target)).pages), 2)
        self.assertTrue(supplement.exists())
        self.assertIn("publisher supplementary file", paper["download_message"])


if __name__ == "__main__":
    unittest.main()
