"""Real Shell tests use generated files and temporary SQLite only."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from paper_monitor import ui_server as ui, windows_recycle as recycle
from paper_monitor.storage import Storage


@unittest.skipUnless(sys.platform == "win32", "Windows Shell integration")
class WindowsRecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.storage = Storage(self.root / "data/paper_monitor.sqlite")
        self.storage.upsert_paper({"paper_id":"fixture", "title":"Disposable recovery fixture", "journal":"Fixture Journal", "source":"fixture", "raw":{}})
        self.path = self.root / "files" / "恢复 test #1.txt"
        self.path.parent.mkdir()
        self.path.write_bytes(b"Disposable file recovery check")
        self.resource = self.storage.create_paper_resource(paper_id="fixture", stored_path=str(self.path), display_name=self.path.name, file_role="note", sha256="", content_sha256="", added_via="test")
        self.roots = patch.object(ui, "local_copy_roots", return_value=[self.root])
        self.roots.start()

    def tearDown(self):
        self.roots.stop()
        self.storage.close()
        self.temporary.cleanup()

    def test_real_shell_database_failure_restores_file_and_resource(self):
        self.storage.conn.execute("CREATE TRIGGER fixture_abort BEFORE DELETE ON resources BEGIN SELECT RAISE(ABORT, 'fixture rollback'); END")
        self.storage.conn.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, "fixture rollback"):
            ui.delete_paper_resource(self.storage, "fixture", self.resource["id"])
        self.assertEqual(self.path.read_bytes(), b"Disposable file recovery check")
        self.assertIsNotNone(self.storage.get_paper_resource(self.resource["id"]))
        self.assertEqual(recycle.recover_pending(self.storage), 0)
        self.assertFalse(list((self.root / "data/.file-recovery").glob("*.backup")))

    def test_interrupted_deletion_recovers_from_sqlite_journal(self):
        removal = recycle.ResourceRemoval(self.storage, "fixture", self.resource["id"])
        receipt = removal.recycle(self.path)
        removal.journal.close()  # Simulate process exit before DB commit.
        self.assertFalse(self.path.exists())
        self.assertEqual(recycle.recover_pending(self.storage), 1)
        self.assertEqual(self.path.read_bytes(), b"Disposable file recovery check")
        self.assertFalse(receipt.exists())
        self.assertEqual(recycle.recover_pending(self.storage), 0)

    def test_recovery_never_overwrites_a_new_file_at_original_path(self):
        removal = recycle.ResourceRemoval(self.storage, "fixture", self.resource["id"])
        receipt = removal.recycle(self.path)
        removal.journal.close()
        self.path.write_bytes(b"new file")
        with self.assertRaisesRegex(OSError, "changed file"):
            recycle.recover_pending(self.storage)
        self.assertEqual(self.path.read_bytes(), b"new file")
        self.assertTrue(Path(removal.record["backup"]).is_file())
        self.path.unlink()  # Remove only the generated collision fixture.
        recycle.recover_pending(self.storage)
        self.assertFalse(receipt.exists())

    def test_committed_deletion_retains_real_recycle_item(self):
        receipts = []
        real_recycle = recycle.recycle_file
        def capture(path):
            receipt = real_recycle(path)
            receipts.append(receipt)
            return receipt
        with patch.object(recycle, "recycle_file", side_effect=capture):
            result = ui.delete_paper_resource(self.storage, "fixture", self.resource["id"])
        self.assertTrue(result["trashed"])
        self.assertIsNone(self.storage.get_paper_resource(self.resource["id"]))
        self.assertFalse(self.path.exists())
        self.assertTrue(receipts[0].exists())
        self.assertEqual(recycle.recover_pending(self.storage), 0)
        recycle.restore_shell_item(receipts[0], self.path)  # Clean only this test's Shell item.
        self.assertEqual(self.path.read_bytes(), b"Disposable file recovery check")
