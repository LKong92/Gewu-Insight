from __future__ import annotations

import inspect
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

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

    def test_embedded_library_table_year_regex_keeps_js_word_boundaries(self) -> None:
        self.assertNotIn("\b", ui_server.INDEX_HTML)
        self.assertIn(r"\b(18|19|20|21)\d{2}\b", ui_server.INDEX_HTML)

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

    def test_journal_download_infers_existing_space_as_real_pdf_target(self) -> None:
        space = self.storage.create_library_root_folder(name="Wigner Crystal")
        self.storage.upsert_paper(
            {
                "paper_id": "space-download-paper",
                "doi": "10.1234/space-download",
                "title": "Space Download Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-07-17",
                "abstract": "",
                "source": "arxiv",
                "type": "article",
            }
        )
        self.storage.add_library_item(paper_id="space-download-paper", folder_id=int(space["id"]))

        target = ui_server.preferred_local_pdf_dir_for_paper(self.storage, "space-download-paper")

        self.assertIsNotNone(target)
        self.assertEqual(
            target.resolve(),
            (ui_server.SPACES_LOCAL_COPY_ROOT / "Wigner Crystal").resolve(),
        )
        handler = inspect.getsource(ui_server.PaperMonitorUiHandler.handle_download)
        self.assertIn("preferred_local_pdf_dir_for_paper(storage, paper_id)", handler)
        self.assertIn("reconcile_paper_pdf_storage(storage, paper_id, target_dir=target_dir)", handler)

    def test_reconcile_moves_cache_pdf_into_space_and_replaces_alias_path(self) -> None:
        space = self.storage.create_library_root_folder(name="Wigner Crystal")
        self.storage.upsert_paper(
            {
                "paper_id": "cached-space-paper",
                "doi": "10.1234/cached-space",
                "title": "Cached Space Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-07-17",
                "abstract": "",
                "source": "arxiv",
                "type": "article",
            }
        )
        self.storage.add_library_item(paper_id="cached-space-paper", folder_id=int(space["id"]))
        cached_dir = ui_server.DEFAULT_PDF_DIR / "cached-space-paper"
        cached_dir.mkdir(parents=True)
        cached_pdf = cached_dir / "cached-space-paper.pdf"
        cached_pdf.write_bytes(b"%PDF fixture")
        stale_dir = ui_server.SPACES_LOCAL_COPY_ROOT / "Wigner C"
        stale_dir.mkdir(parents=True)
        stale_alias = stale_dir / cached_pdf.name
        stale_alias.symlink_to(cached_pdf)
        self.storage.update_download_status(
            "cached-space-paper",
            status="success",
            main_pdf_path=str(stale_alias),
            merged_pdf_path=str(stale_alias),
            supplement_pdf_paths=[],
        )

        changed = ui_server.reconcile_paper_pdf_storage(self.storage, "cached-space-paper")
        paper = self.storage.get_paper("cached-space-paper") or {}
        stored_pdf = Path(paper["merged_pdf_path"])

        self.assertTrue(changed)
        self.assertFalse(cached_pdf.exists())
        self.assertFalse(stale_alias.is_symlink(), list(stale_dir.iterdir()) if stale_dir.exists() else [])
        self.assertFalse(stale_dir.exists(), list(stale_dir.iterdir()) if stale_dir.exists() else [])
        self.assertTrue(stored_pdf.exists())
        self.assertFalse(stored_pdf.is_symlink())
        self.assertEqual(stored_pdf.parent.resolve(), (ui_server.SPACES_LOCAL_COPY_ROOT / "Wigner Crystal").resolve())
        self.assertEqual(paper["main_pdf_path"], paper["merged_pdf_path"])

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
        self.assertEqual(
            Path(result["moved"]["paper"]["merged_pdf_path"]).resolve(),
            moved_path.resolve(),
        )

    def test_recover_moves_recycled_pdf_back_to_original_folder_and_returns_new_path(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Original")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "recover.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "recover-paper",
                "doi": "10.1234/recover",
                "title": "Recover Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "recover-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="recover-paper", folder_id=int(folder["id"]))
        ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        recycled_pdf = Path((self.storage.get_paper("recover-paper") or {})["merged_pdf_path"])
        self.assertTrue(recycled_pdf.exists())
        self.assertIn("Recycle", recycled_pdf.parts)

        recovered = ui_server.PaperMonitorUiHandler.recover_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        restored_pdf = Path((self.storage.get_paper("recover-paper") or {})["merged_pdf_path"])

        self.assertEqual(int(recovered["folder_id"]), int(folder["id"]))
        self.assertEqual(Path(recovered["paper"]["merged_pdf_path"]).resolve(), restored_pdf.resolve())
        self.assertEqual(restored_pdf.parent.resolve(), source_dir.resolve())
        self.assertTrue(restored_pdf.exists())
        self.assertFalse(recycled_pdf.exists())

    def test_my_publication_counts_as_remaining_reference_on_library_delete(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Library Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "publication.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "publication-paper",
                "doi": "10.1234/publication",
                "title": "Publication Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "publication-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="publication-paper", folder_id=int(folder["id"]))
        self.storage.add_my_publication(paper_id="publication-paper")

        result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        paper = self.storage.get_paper("publication-paper") or {}
        retained_pdf = Path(paper["merged_pdf_path"])
        recycle_id = int(ui_server.ensure_library_special_folders(self.storage)["recycle"]["id"])

        self.assertEqual(result["mode"], "removed")
        self.assertTrue(result["retained_by_my_publications"])
        self.assertEqual(result["moved"], {})
        self.assertEqual(Path(result["paper"]["merged_pdf_path"]).resolve(), retained_pdf.resolve())
        self.assertIsNone(self.storage.get_library_item(int(item["id"])))
        self.assertEqual(
            self.storage.conn.execute(
                "SELECT COUNT(*) FROM library_items WHERE paper_id = ? AND folder_id = ?",
                ("publication-paper", recycle_id),
            ).fetchone()[0],
            0,
        )
        self.assertEqual(retained_pdf.parent.resolve(), ui_server.MY_PUBLICATIONS_LOCAL_COPY_ROOT.resolve())
        self.assertTrue(retained_pdf.exists())

    def test_permanent_recycle_delete_moves_pdf_before_removing_database_records(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "permanent.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "permanent-paper",
                "doi": "10.1234/permanent",
                "title": "Permanent Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "permanent-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="permanent-paper", folder_id=int(folder["id"]))
        ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        recycled_item = self.storage.get_library_item(int(item["id"])) or {}
        recycled_pdf = Path((self.storage.get_paper("permanent-paper") or {})["merged_pdf_path"])
        system_trash = self.root / "System Trash"
        system_trash.mkdir()

        def fake_system_trash(path: Path) -> Path:
            target = system_trash / path.name
            path.replace(target)
            return target

        with patch.object(ui_server, "move_path_to_macos_trash", side_effect=fake_system_trash):
            result = ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
                None,
                self.storage,
                "item",
                int(recycled_item["id"]),
                confirmed=True,
            )

        self.assertEqual(result["mode"], "removed")
        self.assertEqual(result["cleanup"]["trashed_files"], [str(recycled_pdf.resolve())])
        self.assertFalse(recycled_pdf.exists())
        self.assertTrue((system_trash / recycled_pdf.name).exists())
        self.assertIsNone(self.storage.get_library_item(int(item["id"])))
        self.assertIsNone(self.storage.get_paper("permanent-paper"))

    def test_permanent_recycle_delete_keeps_records_when_macos_trash_fails(self) -> None:
        folder = self.storage.create_library_folder(parent_id=1, name="Only")
        source_dir = ui_server.local_copy_dir_for_library_folder(self.storage, int(folder["id"]))
        source_dir.mkdir(parents=True)
        source_pdf = source_dir / "protected.pdf"
        source_pdf.write_bytes(b"%PDF fixture")
        self.storage.upsert_paper(
            {
                "paper_id": "protected-paper",
                "doi": "10.1234/protected",
                "title": "Protected Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "protected-paper",
            status="success",
            main_pdf_path=str(source_pdf),
            merged_pdf_path=str(source_pdf),
            supplement_pdf_paths=[],
        )
        item = self.storage.add_library_item(paper_id="protected-paper", folder_id=int(folder["id"]))
        ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
            None,
            self.storage,
            "item",
            int(item["id"]),
        )
        recycled_pdf = Path((self.storage.get_paper("protected-paper") or {})["merged_pdf_path"])

        with patch.object(
            ui_server,
            "move_path_to_macos_trash",
            side_effect=PermissionError("Finder Trash permission denied"),
        ):
            with self.assertRaises(PermissionError):
                ui_server.PaperMonitorUiHandler.delete_library_entry_in_storage(
                    None,
                    self.storage,
                    "item",
                    int(item["id"]),
                    confirmed=True,
                )

        self.assertIsNotNone(self.storage.get_library_item(int(item["id"])))
        self.assertIsNotNone(self.storage.get_paper("protected-paper"))
        self.assertTrue(recycled_pdf.exists())

    def test_recycle_orphan_detection_does_not_include_referenced_files(self) -> None:
        special = ui_server.ensure_library_special_folders(self.storage)
        recycle_id = int(special["recycle"]["id"])
        recycle_dir = ui_server.local_copy_dir_for_library_folder(self.storage, recycle_id)
        recycle_dir.mkdir(parents=True, exist_ok=True)
        referenced = recycle_dir / "referenced.pdf"
        orphan = recycle_dir / "orphan.pdf"
        referenced.write_bytes(b"%PDF referenced")
        orphan.write_bytes(b"%PDF orphan")
        self.storage.upsert_paper(
            {
                "paper_id": "referenced-paper",
                "doi": "10.1234/referenced",
                "title": "Referenced Paper",
                "journal": "Fixture Journal",
                "publication_date": "2026-01-01",
                "abstract": "",
                "source": "test",
                "type": "article",
            }
        )
        self.storage.update_download_status(
            "referenced-paper",
            status="success",
            main_pdf_path=str(referenced),
            merged_pdf_path=str(referenced),
            supplement_pdf_paths=[],
        )

        paths = ui_server.library_recycle_orphan_paths(self.storage, recycle_id)

        self.assertEqual(paths, [orphan.resolve()])

    def test_macos_trash_uses_nsfilemanager_instead_of_writing_dot_trash_directly(self) -> None:
        source = self.root / "system-trash.pdf"
        source.write_bytes(b"%PDF fixture")
        destination = self.root / "Finder Trash" / source.name
        completed = CompletedProcess(args=[], returncode=0, stdout=f"{destination}\n", stderr="")

        with patch.object(ui_server.sys, "platform", "darwin"), patch.object(
            ui_server.subprocess,
            "run",
            return_value=completed,
        ) as run:
            result = ui_server.move_path_to_macos_trash(source)

        command = run.call_args.args[0]
        self.assertEqual(command[0:4], ["/usr/bin/osascript", "-l", "JavaScript", "-e"])
        self.assertIn("trashItemAtURLResultingItemURLError", command[4])
        self.assertEqual(command[5], str(source.resolve()))
        self.assertEqual(result, destination)
        self.assertTrue(source.exists())

    def test_macos_trash_accepts_false_error_after_source_was_moved(self) -> None:
        source = self.root / "false-error.pdf"
        source.write_bytes(b"%PDF fixture")
        original_path = source.resolve()

        def false_error_after_move(*args, **kwargs):
            source.unlink()
            return CompletedProcess(
                args=args[0],
                returncode=1,
                stdout="",
                stderr="execution error: macOS refused the Trash operation",
            )

        with patch.object(ui_server.sys, "platform", "darwin"), patch.object(
            ui_server.subprocess,
            "run",
            side_effect=false_error_after_move,
        ):
            result = ui_server.move_path_to_macos_trash(source)

        self.assertEqual(result, original_path)
        self.assertFalse(source.exists())

    def test_macos_trash_still_raises_when_source_remains(self) -> None:
        source = self.root / "real-error.pdf"
        source.write_bytes(b"%PDF fixture")
        completed = CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="execution error: permission denied",
        )

        with patch.object(ui_server.sys, "platform", "darwin"), patch.object(
            ui_server.subprocess,
            "run",
            return_value=completed,
        ):
            with self.assertRaises(PermissionError):
                ui_server.move_path_to_macos_trash(source)

        self.assertTrue(source.exists())

    def test_embedded_recycle_item_delete_uses_incremental_state_update(self) -> None:
        self.assertIn("function applyLocalLibraryDeleteResult(result)", ui_server.INDEX_HTML)
        self.assertIn("applyLocalLibraryDeleteResult(data.deleted);", ui_server.INDEX_HTML)
        self.assertIn('snapshot: false', ui_server.INDEX_HTML)
        self.assertIn("function updateLocalPaperReferences(paper)", ui_server.INDEX_HTML)
        self.assertIn("if (rawMoved?.paper) updateLocalPaperReferences(rawMoved.paper);", ui_server.INDEX_HTML)
        self.assertIn("else upsertLibraryFolderLocal(data.recovered);", ui_server.INDEX_HTML)


if __name__ == "__main__":
    unittest.main()
