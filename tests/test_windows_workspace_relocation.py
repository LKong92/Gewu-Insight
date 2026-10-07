"""Offline relocation acceptance with disposable databases and actual .lnk files."""
from pathlib import Path
from contextlib import contextmanager
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from paper_monitor import desktop_files as desktop
from paper_monitor.windows_workspace_relocation import relocate, workspace_lock


@contextmanager
def database(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


@unittest.skipUnless(sys.platform == "win32", "Windows filesystem integration")
class WorkspaceRelocationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "old 研究"
        self.target = self.root / "new 资料"
        self.paper = self.source / "data/Library/空 格/论文 #1.pdf"
        self.paper.parent.mkdir(parents=True)
        self.paper.write_bytes(b"synthetic annotated canonical file")
        self.external = self.root / "external.pdf"
        self.external.write_bytes(b"external original")
        self.internal_link = desktop.create_placement(self.paper, self.source / "data/Spaces/one/Paper.pdf")
        self.external_link = desktop.create_placement(self.external, self.source / "data/Spaces/two/External.pdf")
        self.db = self.source / "data/paper_monitor.sqlite"
        with database(self.db) as c:
            c.executescript('''CREATE TABLE papers(paper_id TEXT PRIMARY KEY, main_pdf_path TEXT, title TEXT);
                CREATE TABLE resources(id INTEGER PRIMARY KEY, paper_id TEXT REFERENCES papers(paper_id), stored_path TEXT, file_type TEXT, annotation_state TEXT);
                CREATE TABLE app_settings(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE library_items(id INTEGER PRIMARY KEY, paper_id TEXT, folder_id INTEGER);
                CREATE TABLE my_publications(paper_id TEXT PRIMARY KEY);''')
            c.execute("INSERT INTO papers VALUES(?,?,?)", ("gw_stable", str(self.paper), "unchanged"))
            c.execute("INSERT INTO resources VALUES(1,?,?,?,?)", ("gw_stable", str(self.paper), "published", "annotated"))
            c.execute("INSERT INTO app_settings VALUES('default_resource', '1')")
            c.executemany("INSERT INTO library_items VALUES(?,?,?)", [(1,"gw_stable",1),(2,"gw_stable",2)])
            c.execute("INSERT INTO my_publications VALUES('gw_stable')")
            c.executescript('''CREATE TABLE edit_revision(revision INTEGER);
                INSERT INTO edit_revision VALUES(5);
                CREATE TRIGGER paper_edit AFTER UPDATE ON papers
                BEGIN UPDATE edit_revision SET revision=revision+1; END;''')
        profile = self.source / "webview/browser/profile-fixture"
        profile.parent.mkdir(parents=True)
        profile.write_bytes(b"synthetic browser state")

    def test_copy_preserves_identity_default_associations_files_and_external_targets(self):
        result = relocate(self.source, self.target)
        self.assertEqual(result["path_cells_updated"], 2)
        self.assertEqual(result["shortcuts_retargeted"], 1)
        self.assertEqual(result["existing_foreign_key_violations"], 0)
        self.assertFalse(result["selection_changed"])
        with database(self.target / "data/paper_monitor.sqlite") as c:
            self.assertEqual(c.execute("SELECT paper_id FROM my_publications").fetchall(), [("gw_stable",)])
            self.assertEqual(c.execute("SELECT count(*) FROM library_items").fetchone()[0], 2)
            self.assertEqual(c.execute("SELECT value FROM app_settings").fetchone()[0], "1")
            new_file = Path(c.execute("SELECT stored_path FROM resources").fetchone()[0])
            self.assertEqual(new_file.read_bytes(), self.paper.read_bytes())
            self.assertTrue(new_file.is_relative_to(self.target))
            self.assertEqual(c.execute("SELECT revision FROM edit_revision").fetchone()[0], 5)
            c.execute("UPDATE papers SET title='real edit after relocation'")
            self.assertEqual(c.execute("SELECT revision FROM edit_revision").fetchone()[0], 6)
        self.assertEqual(desktop.managed_link_target(self.internal_link), self.paper)
        self.assertEqual(desktop.managed_link_target(self.target / self.internal_link.relative_to(self.source)), new_file)
        self.assertEqual(desktop.managed_link_target(self.target / self.external_link.relative_to(self.source)), self.external)
        with database(self.db) as c:
            self.assertEqual(c.execute("SELECT main_pdf_path FROM papers").fetchone()[0], str(self.paper))

    def test_existing_destination_is_never_overwritten(self):
        self.target.mkdir()
        sentinel = self.target / "keep.txt"
        sentinel.write_text("keep")
        with self.assertRaises(FileExistsError):
            relocate(self.source, self.target)
        self.assertEqual(sentinel.read_text(), "keep")

    def test_active_desktop_lock_blocks_copy(self):
        with workspace_lock(self.source):
            with self.assertRaises(OSError):
                relocate(self.source, self.target)
        self.assertFalse(self.target.exists())

    def test_preexisting_missing_file_is_reported_and_stays_missing(self):
        self.paper.unlink()
        result = relocate(self.source, self.target)
        self.assertTrue(result['preexisting_missing_files'])
        self.assertFalse((self.target / self.paper.relative_to(self.source)).exists())

    def test_historical_embedded_paths_are_not_blindly_rewritten(self):
        import json
        with database(self.db) as c:
            c.execute("INSERT INTO app_settings VALUES('unplanned', ?)", (json.dumps([str(self.paper)]),))
        relocate(self.source, self.target)
        with database(self.target / 'data/paper_monitor.sqlite') as c:
            self.assertEqual(json.loads(c.execute("SELECT value FROM app_settings WHERE key='unplanned'").fetchone()[0]), [str(self.paper)])

    def test_failed_copy_keeps_source_and_does_not_select_partial_destination(self):
        original = self.paper.read_bytes()
        with patch.object(shutil, "copy2", side_effect=OSError("synthetic disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                relocate(self.source, self.target)
        self.assertEqual(self.paper.read_bytes(), original)
        self.assertTrue(self.db.exists())
        self.assertFalse((self.target / "data/paper_monitor.sqlite").exists())
        with self.assertRaises(FileExistsError):
            relocate(self.source, self.target)

    def test_corrupt_copy_is_detected(self):
        copy2 = shutil.copy2
        def corrupt(source, target):
            result = copy2(source, target)
            if Path(target).suffix == ".pdf":
                Path(target).write_bytes(b"corrupt")
            return result
        with patch.object(shutil, "copy2", side_effect=corrupt):
            with self.assertRaisesRegex(ValueError, "content changed|hash mismatch"):
                relocate(self.source, self.target)
        self.assertEqual(self.paper.read_bytes(), b"synthetic annotated canonical file")


if __name__ == "__main__":
    unittest.main()
