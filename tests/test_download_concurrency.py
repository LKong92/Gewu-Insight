"""Concurrent UI requests use isolated SQLite and generated PDFs, never Library data."""
from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from paper_monitor import download, ui_server
from tests import test_ai_access


class DownloadConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_ai_access.AIAccessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.storage = self.fixture.storage
        self.folder = self.storage.ensure_library_folder(parent_id=1, name="Downloads")
        for paper_id in ("download-a", "download-b"):
            self.storage.upsert_paper({"paper_id": paper_id, "title": paper_id,
                                       "journal": "Fixture", "source": "fixture"})
            self.storage.add_library_item(paper_id=paper_id, folder_id=self.folder["id"])

    def request_download(self, paper_id, **options):
        return self.fixture.request("/api/download", {"paper_id": paper_id, **options}, workspace=True)

    @staticmethod
    def candidates(paper):
        return {"main": [paper["paper_id"]], "supplements": []}

    @staticmethod
    def write_pdf(path, width):
        writer = PdfWriter()
        writer.add_blank_page(width=width, height=792)
        with Path(path).open("wb") as handle:
            writer.write(handle)

    def test_two_papers_in_one_folder_keep_their_own_bytes(self):
        written = threading.Barrier(2)
        paths = []

        def retrieve(url, path, messages):
            paths.append(Path(path))
            self.write_pdf(path, 610 if url == "download-a" else 720)
            written.wait(timeout=5)
            return True

        with patch.object(download, "collect_pdf_candidates", side_effect=self.candidates), \
                patch.object(download, "try_download_pdf", side_effect=retrieve), \
                ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.request_download, paper_id) for paper_id in ("download-a", "download-b")]
            results = [future.result(timeout=15) for future in futures]
        self.assertNotEqual(paths[0], paths[1], "Concurrent papers must not share main.pdf")
        for (status, response, _), width in zip(results, (610, 720)):
            self.assertEqual(status, 200, response)
            path = Path(response["paper"]["merged_pdf_path"])
            self.assertEqual(float(PdfReader(path).pages[0].mediabox.width), width)
        self.assertFalse(any(path.exists() for path in paths))

    def test_duplicate_request_waits_without_downloading_again_and_add_remains_independent(self):
        entered, release = threading.Event(), threading.Event()
        calls = []

        def retrieve(url, path, messages):
            calls.append(url)
            entered.set()
            self.assertTrue(release.wait(timeout=8))
            self.write_pdf(path, 610)
            return True

        with patch.object(download, "collect_pdf_candidates", side_effect=self.candidates), \
                patch.object(download, "try_download_pdf", side_effect=retrieve), \
                ThreadPoolExecutor(3) as pool:
            first = pool.submit(self.request_download, "download-a")
            self.assertTrue(entered.wait(timeout=5))
            second = pool.submit(self.request_download, "download-a")
            try:
                added = pool.submit(self.fixture.request, "/api/library/items",
                                    {"paper_id": "outside", "folder_id": self.folder["id"], "snapshot": False}, workspace=True)
                self.assertEqual(added.result(timeout=3)[0], 200)
                self.assertFalse(first.done(), "Adding B must not end A's download")
                time.sleep(0.15)
            finally:
                release.set()
            results = [first.result(timeout=10), second.result(timeout=10)]
        self.assertEqual(calls, ["download-a"])
        self.assertTrue(all(result[0] == 200 for result in results), results)
        self.assertEqual(results[0][1]["paper"]["merged_pdf_path"], results[1][1]["paper"]["merged_pdf_path"])
        files = self.storage.list_paper_resources("download-a", ensure_primary=False)
        self.assertEqual(len(files), 1)
        folder = ui_server.local_copy_dir_for_library_folder(self.storage, self.folder["id"])
        self.assertEqual(len([p for p in folder.rglob("*.pdf") if not p.is_symlink()]), 1)

    def test_concurrent_publish_with_identical_names_never_overwrites_bytes(self):
        root = self.fixture.root / "publish"
        root.mkdir()
        sources = [root / "staged-a.pdf", root / "staged-b.pdf"]
        for source, width in zip(sources, (610, 720)):
            self.write_pdf(source, width)
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(download.publish_new_download, source, root / "same-title.pdf") for source in sources]
            outputs = [future.result(timeout=5) for future in futures]
        self.assertNotEqual(outputs[0], outputs[1])
        self.assertEqual([float(PdfReader(path).pages[0].mediabox.width) for path in outputs], [610, 720])

    def test_download_rename_and_repeated_refresh_keep_one_file_and_one_resource(self):
        item = self.storage.conn.execute("SELECT id FROM library_items WHERE paper_id=?", ("download-a",)).fetchone()
        self.storage.rename_library_item(item_id=item["id"], name="Readable library name")
        def retrieve(url, path, messages):
            self.write_pdf(path, 610)
            return True

        with patch.object(download, "collect_pdf_candidates", side_effect=self.candidates), \
                patch.object(download, "try_download_pdf", side_effect=retrieve) as network:
            first_path = None
            first_id = None
            for force in (False, False, True, True, False):
                status, response, _ = self.request_download("download-a", force=force)
                self.assertEqual(status, 200, response)
                path = Path(response["paper"]["merged_pdf_path"])
                files = self.storage.list_paper_resources("download-a", ensure_primary=False)
                self.assertEqual(len(files), 1)
                self.assertEqual(Path(files[0]["stored_path"]).resolve(), path.resolve(), "Rename must update Paper Files before returning")
                self.assertTrue(files[0]["exists"])
                self.assertTrue(path.is_file())
                first_path = first_path or path
                first_id = first_id or files[0]["id"]
                self.assertEqual(path, first_path)
                self.assertEqual(files[0]["id"], first_id)
                folder = ui_server.local_copy_dir_for_library_folder(self.storage, self.folder["id"])
                self.assertEqual(len([p for p in folder.rglob("*.pdf") if not p.is_symlink()]), 1)
            self.assertEqual(network.call_count, 3, "Only initial download and explicit refresh use the network")

    def test_existing_valid_pdf_is_reused_even_if_old_status_was_reset(self):
        def retrieve(url, path, messages):
            self.write_pdf(path, 610)
            return True
        with patch.object(download, "collect_pdf_candidates", side_effect=self.candidates), \
                patch.object(download, "try_download_pdf", side_effect=retrieve) as network:
            self.assertEqual(self.request_download("download-a")[0], 200)
            self.storage.update_download_status("download-a", status="failed", message="Old overlapping request failed")
            status, response, _ = self.request_download("download-a")
        self.assertEqual(status, 200, response)
        self.assertEqual(response["result"]["status"], "skipped")
        self.assertEqual(network.call_count, 1)

    def test_missing_pdf_is_downloaded_again_despite_a_success_status(self):
        def retrieve(url, path, messages):
            self.write_pdf(path, 610)
            return True
        with patch.object(download, "collect_pdf_candidates", side_effect=self.candidates), \
                patch.object(download, "try_download_pdf", side_effect=retrieve) as network:
            status, response, _ = self.request_download("download-a")
            self.assertEqual(status, 200)
            Path(response["paper"]["merged_pdf_path"]).unlink()
            status, response, _ = self.request_download("download-a")
        self.assertEqual(status, 200, response)
        self.assertTrue(Path(response["paper"]["merged_pdf_path"]).is_file())
        self.assertEqual(network.call_count, 2)

    def test_rename_failure_restores_file_and_both_registration_paths(self):
        with patch.object(download, "collect_pdf_candidates", side_effect=self.candidates), \
                patch.object(download, "try_download_pdf", side_effect=lambda url, path, messages: (self.write_pdf(path, 610) or True)):
            self.assertEqual(self.request_download("download-a")[0], 200)
        before = self.storage.get_paper("download-a")
        resource = self.storage.list_paper_resources("download-a", ensure_primary=False)[0]
        item = dict(self.storage.conn.execute("SELECT * FROM library_items WHERE paper_id=?", ("download-a",)).fetchone())
        path = Path(before["merged_pdf_path"])
        self.storage.conn.execute("CREATE TRIGGER fixture_rename_failure BEFORE UPDATE OF stored_path ON resources BEGIN SELECT RAISE(ABORT, 'fixture rename failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fixture rename failure"):
            ui_server.rename_library_item_and_sync_files(self.storage, item_id=item["id"], name="Changed name")
        self.assertTrue(path.is_file())
        self.assertFalse(path.with_name("Changed name.pdf").exists())
        after = self.storage.get_paper("download-a")
        self.assertEqual(after["merged_pdf_path"], before["merged_pdf_path"])
        self.assertEqual(after["primary_resource_id"], before["primary_resource_id"])
        self.assertEqual(self.storage.get_paper_resource(resource["id"])["stored_path"], resource["stored_path"])
        self.assertEqual(self.storage.get_library_item(item["id"])["display_name"], item["display_name"])

    def test_resource_only_rename_keeps_custom_label_and_original_source(self):
        old = self.fixture.root / "note-before.pdf"
        new = self.fixture.root / "note-after.pdf"
        self.write_pdf(old, 610)
        resource = self.storage.create_paper_resource(paper_id="download-a", stored_path=str(old),
            source_path="/original/import-source.pdf", display_name="Custom attachment label", file_type="preprint")
        old.rename(new)
        ui_server.update_paper_file_path_references(self.storage, "download-a", old, new)
        current = self.storage.get_paper_resource(resource["id"])
        self.assertEqual(current["stored_path"], str(new))
        self.assertEqual(current["display_name"], "Custom attachment label")
        self.assertEqual(current["source_path"], "/original/import-source.pdf")
        self.assertEqual(current["file_type"], resource["file_type"])


if __name__ == "__main__":
    unittest.main()
