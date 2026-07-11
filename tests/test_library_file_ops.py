from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from paper_monitor import ui_server
from paper_monitor.storage import Storage


class LibraryFileOperationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "paper_monitor.sqlite"
        self.storage = Storage(self.db_path)
        self.original_roots = {
            "LIBRARY_LOCAL_COPY_ROOT": ui_server.LIBRARY_LOCAL_COPY_ROOT,
            "MY_PUBLICATIONS_LOCAL_COPY_ROOT": ui_server.MY_PUBLICATIONS_LOCAL_COPY_ROOT,
            "SPACES_LOCAL_COPY_ROOT": ui_server.SPACES_LOCAL_COPY_ROOT,
            "DEFAULT_PDF_DIR": ui_server.DEFAULT_PDF_DIR,
        }
        ui_server.LIBRARY_LOCAL_COPY_ROOT = self.root / "Library"
        ui_server.MY_PUBLICATIONS_LOCAL_COPY_ROOT = self.root / "My Publications"
        ui_server.SPACES_LOCAL_COPY_ROOT = self.root / "Spaces"
        ui_server.DEFAULT_PDF_DIR = self.root / "pdfs"

    def tearDown(self) -> None:
        for name, value in self.original_roots.items():
            setattr(ui_server, name, value)
        self.storage.close()
        self.tmp.cleanup()

    def test_pdf_rename_filename_preserves_pdf_suffix_when_title_is_long(self) -> None:
        long_title = " ".join(["Very Long Electride Nonlinear Optical Response"] * 12)
        filename = ui_server.pdf_rename_filename_from_values(
            "{author}_{year}_{title}",
            {"author": "Dale", "year": "2026", "title": long_title, "journal": "", "doi": ""},
            ".pdf",
        )

        self.assertTrue(filename.endswith(".pdf"))
        self.assertLessEqual(len(filename), 120)

    def test_move_library_item_api_uses_updated_pdf_path(self) -> None:
        source_folder = self.storage.create_library_folder(parent_id=1, name="Source")
        target_folder = self.storage.create_library_folder(parent_id=1, name="Target")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(source_folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")

        self.storage.upsert_paper(
            {
                "paper_id": "fixture-paper",
                "doi": "10.1234/fixture",
                "title": "Fixture Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "fixture-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="fixture-paper", folder_id=int(source_folder["id"]))

        ui_server.move_or_alias_library_item_pdf(
            self.storage,
            item=item,
            target_folder_id=int(target_folder["id"]),
        )
        moved = self.storage.move_library_item(item_id=int(item["id"]), folder_id=int(target_folder["id"]))
        paper = self.storage.get_paper("fixture-paper") or {}
        api_item = ui_server.library_item_to_api(moved, paper)
        moved_path = Path(api_item["paper"]["merged_pdf_path"])

        self.assertFalse(source_pdf.exists())
        self.assertTrue(moved_path.exists())
        self.assertEqual(
            moved_path.parent.resolve(),
            ui_server.local_copy_dir_for_library_folder(self.storage, int(target_folder["id"])).resolve(),
        )

    def test_delete_hands_pdf_to_earliest_remaining_non_recycle_link(self) -> None:
        folder_a = self.storage.create_library_folder(parent_id=1, name="A")
        folder_b = self.storage.create_library_folder(parent_id=1, name="B")
        folder_c = self.storage.create_library_folder(parent_id=1, name="C")
        dir_a = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder_a["id"]))
        dir_b = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder_b["id"]))
        dir_c = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder_c["id"]))
        dir_a.mkdir(parents=True)
        source_pdf = dir_a / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")

        self.storage.upsert_paper(
            {
                "paper_id": "handoff-paper",
                "doi": "10.1234/handoff",
                "title": "Handoff Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "handoff-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item_a = self.storage.add_library_item(paper_id="handoff-paper", folder_id=int(folder_a["id"]))
        item_b = self.storage.copy_library_item(item_id=int(item_a["id"]), folder_id=int(folder_b["id"]))
        item_c = self.storage.copy_library_item(item_id=int(item_a["id"]), folder_id=int(folder_c["id"]))
        ui_server.sync_alias_for_library_item(self.storage, "handoff-paper", int(folder_b["id"]))
        ui_server.sync_alias_for_library_item(self.storage, "handoff-paper", int(folder_c["id"]))

        result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item_a["id"]),
        )
        paper = self.storage.get_paper("handoff-paper") or {}
        moved_path = Path(paper["merged_pdf_path"])

        self.assertEqual(result["mode"], "removed")
        self.assertEqual(int(result["moved"]["id"]), int(item_b["id"]))
        self.assertIsNone(self.storage.get_library_item(int(item_a["id"])))
        self.assertIsNotNone(self.storage.get_library_item(int(item_b["id"])))
        self.assertIsNotNone(self.storage.get_library_item(int(item_c["id"])))
        self.assertFalse(source_pdf.exists())
        self.assertEqual(moved_path.resolve(), (dir_b / "paper.pdf").resolve())
        self.assertTrue(moved_path.exists())
        self.assertFalse(moved_path.is_symlink())
        self.assertTrue((dir_c / "paper.pdf").is_symlink())

    def test_delete_moves_pdf_to_recycle_when_no_remaining_non_recycle_link(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "paper.pdf"
        source_pdf.write_bytes(b"%PDF fixture")

        self.storage.upsert_paper(
            {
                "paper_id": "solo-paper",
                "doi": "10.1234/solo",
                "title": "Solo Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "solo-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="solo-paper", folder_id=int(folder["id"]))

        result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        paper = self.storage.get_paper("solo-paper") or {}
        moved_path = Path(paper["merged_pdf_path"])

        self.assertEqual(result["mode"], "trashed")
        self.assertFalse(source_pdf.exists())
        self.assertTrue(moved_path.exists())
        self.assertIn("Recycle", moved_path.parts)


if __name__ == "__main__":
    unittest.main()
