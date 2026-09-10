"""Real Shell tests use generated files and temporary SQLite only."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from paper_monitor import ui_server as ui, windows_recycle as recycle
from paper_monitor.storage import Storage
from paper_monitor.publication_deletion import delete_publications


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

    def test_publication_sql_failure_restores_managed_file(self):
        publication = self.storage.add_my_publication(paper_id='fixture')
        self.storage.conn.execute("CREATE TRIGGER publication_abort BEFORE DELETE ON papers BEGIN SELECT RAISE(ABORT, 'publication rollback'); END")
        self.storage.conn.commit()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'publication rollback'):
            delete_publications(self.storage, [publication['id']])
        self.assertEqual(self.path.read_bytes(), b'Disposable file recovery check')
        self.assertIsNotNone(self.storage.get_paper('fixture'))
        self.assertEqual(len(self.storage.list_my_publications()), 1)
        self.assertEqual(recycle.recover_pending(self.storage), 0)

    def test_publication_commit_recycles_file_and_preserves_shared_reference(self):
        publication = self.storage.add_my_publication(paper_id='fixture')
        self.storage.add_library_item(paper_id='fixture', folder_id=1)
        result = delete_publications(self.storage, [publication['id']])
        self.assertEqual(result['retained_paper_ids'], ['fixture'])
        self.assertTrue(self.path.exists())
        self.storage.conn.execute('DELETE FROM library_items WHERE paper_id=?', ('fixture',))
        self.storage.conn.commit()
        publication = self.storage.add_my_publication(paper_id='fixture')
        receipts = []
        original = recycle.recycle_file
        def capture(path):
            receipt = original(path); receipts.append(receipt); return receipt
        with patch.object(recycle, 'recycle_file', side_effect=capture):
            result = delete_publications(self.storage, [publication['id']])
        self.assertEqual(result['deleted_paper_ids'], ['fixture'])
        self.assertEqual(result['trashed_file_count'], 1)
        self.assertFalse(self.path.exists())
        self.assertEqual(recycle.recover_pending(self.storage), 0)
        recycle.restore_shell_item(receipts[0], self.path)

    def test_publication_interruption_recovers_using_canonical_paper(self):
        self.storage.add_my_publication(paper_id='fixture')
        removal = recycle.PublicationRemoval(self.storage)
        receipt = removal.recycle(self.path, 'fixture')
        for pending in removal.removals:
            pending.journal.close()
        self.assertFalse(self.path.exists())
        self.assertEqual(recycle.recover_pending(self.storage), 1)
        self.assertEqual(self.path.read_bytes(), b'Disposable file recovery check')
        self.assertFalse(receipt.exists())
