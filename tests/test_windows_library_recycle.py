"""Disposable Library selections, real SQLite commits and recovery file bytes."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from paper_monitor import ui_server as ui, windows_recycle as recovery
from paper_monitor.windows_library_recycle import delete_entries
from paper_monitor.storage import Storage


class LibraryRecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for key, name in [('LIBRARY_LOCAL_COPY_ROOT', 'Library'), ('MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'Publications'),
                          ('SPACES_LOCAL_COPY_ROOT', 'Spaces'), ('ASSOCIATED_FILES_ROOT', 'Associated'), ('DEFAULT_PDF_DIR', 'pdfs')]:
            self.enterContext(patch.object(ui, key, self.root / name))
        self.storage = Storage(self.root / 'data/paper_monitor.sqlite')
        self.addCleanup(self.storage.close)
        self.recycle_id = int(ui.ensure_library_special_folders(self.storage)['recycle']['id'])
        self.receipts = []
        self.enterContext(patch.object(recovery, 'recycle_file', side_effect=self.recycle))
        self.enterContext(patch.object(recovery, 'restore_shell_item', side_effect=self.restore))

    def restore(self, receipt, source):
        Path(receipt).replace(source)

    def recycle(self, source):
        target = self.root / 'Shell' / str(len(self.receipts)) / source.name
        target.parent.mkdir(parents=True)
        source.replace(target)
        self.receipts.append((target, source))
        return target

    def paper(self, name, folder=None, path=None):
        folder = self.recycle_id if folder is None else folder
        self.storage.upsert_paper({'paper_id': name, 'title': name, 'journal': 'Fixture', 'source': 'fixture', 'raw': {}})
        if path is None:
            path = ui.local_copy_dir_for_library_folder(self.storage, folder) / (name + '.txt')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(('研究 fixture ' + name).encode())
        self.storage.create_paper_resource(paper_id=name, stored_path=str(path), display_name=path.name,
            file_role='note', sha256='', content_sha256='', added_via='test')
        item = self.storage.add_library_item(paper_id=name, folder_id=folder)
        return {'type': 'item', 'id': item['id']}, path

    def snapshot(self):
        return {row[0]: self.storage.conn.execute('SELECT * FROM "' + row[0] + '"').fetchall()
                for row in self.storage.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    def assert_clean(self):
        self.assertEqual(recovery.recover_pending(self.storage), 0)
        self.assertEqual(self.storage.conn.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_selection_requires_confirmation_before_any_file_or_row_changes(self):
        one, path = self.paper('one')
        two, other = self.paper('two')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            delete_entries(self.storage, [one, two])
        self.assertEqual(before, self.snapshot())
        self.assertTrue(path.exists() and other.exists())
        self.assertFalse(self.receipts)

    def test_folder_and_overlapping_item_delete_once_with_all_attachments(self):
        folder = self.storage.create_library_folder(parent_id=self.recycle_id, name='Nested')
        child = self.storage.create_library_folder(parent_id=folder['id'], name='Child')
        one, path = self.paper('one', child['id'])
        two, other = self.paper('two', folder['id'])
        result = delete_entries(self.storage, [{'type': 'folder', 'id': folder['id']}, one], confirmed=True)
        self.assertEqual(result['removed'], {'items': 2, 'folders': 2})
        self.assertFalse(path.exists() or other.exists())
        self.assertEqual(len(self.receipts), 2)
        self.assertIsNone(self.storage.get_paper('one'))
        self.assertIsNone(self.storage.get_library_folder(child['id']))
        self.assert_clean()

    def test_second_file_failure_restores_first_and_all_rows(self):
        one, path = self.paper('one')
        two, other = self.paper('two')
        before = self.snapshot()
        def fail_second(source):
            if self.receipts:
                raise OSError('fixture second file locked')
            return self.recycle(source)
        with patch.object(recovery, 'recycle_file', side_effect=fail_second), self.assertRaisesRegex(OSError, 'second file'):
            delete_entries(self.storage, [one, two], confirmed=True)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(path.exists() and other.exists())
        self.assert_clean()

    def test_sql_failure_after_placement_deletes_rolls_back_whole_selection(self):
        one, path = self.paper('one')
        two, other = self.paper('two')
        self.storage.conn.execute("CREATE TRIGGER stop_delete BEFORE DELETE ON papers WHEN OLD.paper_id='two' BEGIN SELECT RAISE(ABORT, 'fixture rollback'); END")
        self.storage.conn.commit()
        before = self.snapshot()
        with self.assertRaisesRegex(sqlite3.IntegrityError, 'fixture rollback'):
            delete_entries(self.storage, [one, two], confirmed=True)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(path.exists() and other.exists())
        self.assert_clean()

    def test_outside_placement_and_publications_preserve_rows_and_bytes(self):
        one, path = self.paper('one')
        two, other = self.paper('two')
        self.storage.add_library_item(paper_id='one', folder_id=1)
        self.storage.add_my_publication(paper_id='two')
        result = delete_entries(self.storage, [one, two])
        self.assertEqual(result['cleanup']['cleaned_papers'], [])
        self.assertTrue(path.exists() and other.exists())
        self.assertIsNotNone(self.storage.get_paper('one'))
        self.assertIsNotNone(self.storage.get_paper('two'))
        self.assertFalse(self.receipts)

    def test_shared_bytes_from_another_paper_remain_at_the_original_path(self):
        one, path = self.paper('one')
        self.paper('outside', folder=1, path=path)
        result = delete_entries(self.storage, [one], confirmed=True)
        self.assertIsNone(self.storage.get_paper('one'))
        self.assertTrue(path.exists())
        self.assertEqual(result['cleanup']['retained_shared_files'], [str(path)])
        self.assertEqual(len(self.storage.list_paper_resources('outside')), 1)

    def test_shared_bytes_within_deletion_set_recycled_only_once(self):
        one, path = self.paper('one')
        two, _ = self.paper('two', path=path)
        delete_entries(self.storage, [one, two], confirmed=True)
        self.assertEqual(len(self.receipts), 1)
        self.assertFalse(path.exists())
        self.assert_clean()

    def test_external_original_never_recycled(self):
        external = self.root / 'external.txt'
        external.write_bytes(b'original')
        one, _ = self.paper('one', path=external)
        delete_entries(self.storage, [one], confirmed=True)
        self.assertEqual(external.read_bytes(), b'original')
        self.assertFalse(self.receipts)

    def test_clear_recycles_orphans_but_keeps_recycle_folder(self):
        one, path = self.paper('one')
        orphan = path.with_name('orphan.txt')
        orphan.write_bytes(b'orphan')
        result = delete_entries(self.storage, [{'type': 'folder', 'id': self.recycle_id}], confirmed=True, clear_folder_id=self.recycle_id)
        self.assertEqual(result['cleanup']['trashed_orphan_files'], [str(orphan)])
        self.assertFalse(orphan.exists() or path.exists())
        self.assertIsNotNone(self.storage.get_library_folder(self.recycle_id))
        self.assert_clean()

    def test_clear_orphan_failure_restores_metadata_and_files(self):
        one, path = self.paper('one')
        orphan = path.with_name('zz-orphan.txt')
        orphan.write_bytes(b'orphan')
        before = self.snapshot()
        def fail_orphan(source):
            if source == orphan:
                raise OSError('orphan locked')
            return self.recycle(source)
        with patch.object(recovery, 'recycle_file', side_effect=fail_orphan), self.assertRaisesRegex(OSError, 'orphan locked'):
            delete_entries(self.storage, [{'type': 'folder', 'id': self.recycle_id}], confirmed=True, clear_folder_id=self.recycle_id)
        self.assertEqual(before, self.snapshot())
        self.assertTrue(path.exists() and orphan.exists())
        self.assert_clean()

    def test_interruption_before_commit_restores_even_an_orphan(self):
        one, path = self.paper('one')
        removal = recovery.LibraryRemoval(self.storage)
        removal.recycle(path)
        for item in removal.removals:
            item.journal.close()
        # The orphan has no resource/paper identity: recovery uses the batch.
        self.assertEqual(recovery.recover_pending(self.storage), 1)
        self.assertTrue(path.exists())
        self.assertIsNotNone(self.storage.get_library_item(one['id']))
        self.assert_clean()

    def test_interruption_after_commit_keeps_shell_receipt_and_cleans_marker(self):
        one, path = self.paper('one')
        def interrupt(removal):
            for item in removal.removals:
                item.journal.close()
            raise OSError('simulated postcommit interruption')
        with patch.object(recovery.LibraryRemoval, 'finish', interrupt):
            result = delete_entries(self.storage, [one], confirmed=True)
        self.assertTrue(result['cleanup']['recovery_warning'])
        self.assertIsNone(self.storage.get_paper('one'))
        self.assertEqual(recovery.recover_pending(self.storage), 1)
        self.assertFalse(path.exists())
        self.assertTrue(self.receipts[0][0].exists())
        self.assert_clean()

    def test_normal_library_entry_still_uses_existing_move_workflow(self):
        one, path = self.paper('one', folder=1)
        self.assertIsNone(delete_entries(self.storage, [one]))
        self.assertTrue(path.exists())

    def test_recycle_root_cannot_be_deleted_as_an_ordinary_folder(self):
        with self.assertRaisesRegex(ValueError, 'cannot be deleted'):
            delete_entries(self.storage, [{'type': 'folder', 'id': self.recycle_id}], confirmed=True)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows handler routing')
    def test_bulk_and_clear_handlers_use_transactional_deletion(self):
        one, path = self.paper('one')
        two, other = self.paper('two')
        replies = []
        handler = object.__new__(ui.PaperMonitorUiHandler)
        handler.configured_db_path = self.storage.db_path
        handler.send_json = replies.append
        handler.send_error_json = lambda status, message: self.fail(str((status, message)))
        handler.handle_delete_library_entries({'entries': [one, two], 'confirmed': True, 'snapshot': False})
        self.assertEqual(len(replies[-1]['deleted']), 2)
        self.assertFalse(path.exists() or other.exists())
        three, third = self.paper('three')
        handler.handle_clear_library_special_folder({'folder_id': self.recycle_id, 'confirmed': True, 'snapshot': False})
        self.assertEqual(replies[-1]['removed']['items'], 1)
        self.assertFalse(third.exists())
        self.assert_clean()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows handler routing')
    def test_sql_failure_handler_returns_error_and_preserves_records(self):
        one, path = self.paper('one')
        self.storage.conn.execute("CREATE TRIGGER stop_delete BEFORE DELETE ON papers BEGIN SELECT RAISE(ABORT, 'fixture rollback'); END")
        self.storage.conn.commit()
        replies = []
        handler = object.__new__(ui.PaperMonitorUiHandler)
        handler.configured_db_path = self.storage.db_path
        handler.send_json = lambda data: self.fail('Must not return success')
        handler.send_error_json = lambda status, message: replies.append((status, message))
        handler.handle_delete_library_entry({**one, 'confirmed': True, 'snapshot': False})
        self.assertEqual(replies[0][0], 500)
        self.assertTrue(path.exists())
        self.assertIsNotNone(self.storage.get_library_item(one['id']))


@unittest.skipUnless(sys.platform == 'win32', 'Windows Shell integration')
class RealShellLibraryRecycleTests(LibraryRecycleTests):
    def setUp(self):
        self.shell_recycle, self.shell_restore = recovery.recycle_file, recovery.restore_shell_item
        super().setUp()
        self.addCleanup(self.restore_test_receipts)

    def restore_test_receipts(self):
        for receipt, source in self.receipts:
            if receipt.exists() and not source.exists():
                self.shell_restore(receipt, source)

    def recycle(self, source):
        receipt = self.shell_recycle(source)
        self.receipts.append((receipt, source))
        return receipt

    def restore(self, receipt, source):
        self.shell_restore(receipt, source)
