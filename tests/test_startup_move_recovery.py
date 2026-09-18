"""Exercise startup recovery with disposable files and no UI/network workers."""
from contextlib import ExitStack
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.file_layout_journal import MoveJournal
from paper_monitor.storage import Storage
from tests import test_file_layout as fixtures


class StartupMoveRecoveryTests(unittest.TestCase):
    setUp = fixtures.FileLayoutTests.setUp
    tearDown = fixtures.FileLayoutTests.tearDown
    add_paper = fixtures.FileLayoutTests.add_paper
    fixture = fixtures.FileLayoutTests.fixture

    def launch(self, *, before_workers=None, documentation=False, error=None):
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {'GEWU_DOCUMENTATION_MODE': str(int(documentation))}))
            for name in ('configure_openalex_api_key', 'configure_semantic_scholar_api_key',
                         'prewarm_author_monitor_photo_cache', 'request_author_monitor_card_cache_build'):
                stack.enter_context(patch.object(ui, name))
            stack.enter_context(patch.object(ui, 'read_config_json', return_value={}))
            stack.enter_context(patch.object(ui, 'load_config', return_value={}))
            stack.enter_context(patch.object(ui, 'configured_source_names', return_value=[]))
            threads = stack.enter_context(patch.object(ui.threading, 'Thread'))
            if before_workers:
                threads.return_value.start.side_effect = before_workers
            workers = stack.enter_context(patch.object(ui.publication_jobs, 'start_workers'))
            server = stack.enter_context(patch.object(ui, 'FastLocalThreadingHTTPServer'))
            for module in ('file_layout_migration', 'resource_dedup_migration'):
                stack.enter_context(patch('paper_monitor.' + module + '.migrate',
                    side_effect=AssertionError('Startup must not run Library maintenance')))
            if error:
                with self.assertRaises(error):
                    ui.run_ui_server(db_path=self.db_path)
                threads.assert_not_called()
                workers.assert_not_called()
                server.assert_not_called()
            else:
                ui.run_ui_server(db_path=self.db_path)
                server.return_value.serve_forever.assert_called_once()
        self.assertFalse((self.db_path.parent / 'file-layout-backups').exists())
        self.assertFalse((self.db_path.parent / 'resource-dedup-backups').exists())

    def interrupted_move(self):
        _, resources, paths = self.fixture()
        source = paths[0]
        target = source.with_name('interrupted.pdf')
        journal = MoveJournal(self.storage, 'work')
        journal.move(source, target, resources[0]['id'])
        return journal, source, target, resources[0]['id']

    def test_no_journals_does_not_inspect_or_reorganize_paper_files(self):
        self.fixture()
        self.storage.update_paper_raw_json('work', {'file_layout': {'links_pending': True}})
        before = self.storage.get_paper('work')
        resources = [dict(r) for r in self.storage.conn.execute('SELECT * FROM resources ORDER BY id')]
        for empty_directory in (False, True):
            if empty_directory:
                (self.db_path.parent / 'file-layout-recovery').mkdir()
            with patch.object(Storage, 'get_paper_resource',
                              side_effect=AssertionError('No recovery lookup without a journal')):
                self.launch()
            self.assertEqual(self.storage.get_paper('work'), before)
            self.assertEqual([dict(r) for r in self.storage.conn.execute('SELECT * FROM resources ORDER BY id')], resources)
            self.assertTrue(all(Path(r['stored_path']).is_file() for r in resources))

    def test_uncommitted_move_is_restored_before_any_worker_starts(self):
        journal, source, target, rid = self.interrupted_move()
        content = target.read_bytes()
        def ready():
            self.assertEqual(source.read_bytes(), content)
            self.assertFalse(target.exists())
            self.assertFalse(journal.path.exists())
        self.launch(before_workers=ready)
        ready()
        self.assertEqual(self.storage.get_paper_resource(rid)['stored_path'], str(source))
        self.launch()  # Recovery is idempotent; it cannot become a maintenance job.
        ready()

    def test_committed_move_keeps_destination_and_clears_only_journal(self):
        journal, source, target, rid = self.interrupted_move()
        ui.update_paper_file_path_references(self.storage, 'work', source, target)
        content = target.read_bytes()
        def ready():
            self.assertEqual(target.read_bytes(), content)
            self.assertFalse(source.exists())
            self.assertFalse(journal.path.exists())
        self.launch(before_workers=ready)
        ready()
        self.assertEqual(self.storage.get_paper_resource(rid)['stored_path'], str(target))

    def test_interruption_between_link_and_unlink_retains_one_original(self):
        _, resources, paths = self.fixture()
        source = paths[0]
        target = source.with_name('interrupted.pdf')
        journal = MoveJournal(self.storage, 'work')
        with patch.object(Path, 'unlink', side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            journal.move(source, target, resources[0]['id'])
        self.assertTrue(os.path.samefile(source, target))
        content = source.read_bytes()
        self.launch()
        self.assertEqual(source.read_bytes(), content)
        self.assertFalse(target.exists())
        self.assertFalse(journal.path.exists())

    def test_external_collision_preserves_both_files_and_journal(self):
        journal, source, target, _ = self.interrupted_move()
        content = target.read_bytes()
        source.write_bytes(b'Unrelated external edit')
        self.launch(error=FileExistsError)
        self.assertEqual(source.read_bytes(), b'Unrelated external edit')
        self.assertEqual(target.read_bytes(), content)
        self.assertTrue(journal.path.exists())

    def test_documentation_and_mismatched_roots_leave_journals_untouched(self):
        journal, source, target, _ = self.interrupted_move()
        self.launch(documentation=True)
        with patch.object(ui, 'LIBRARY_LOCAL_COPY_ROOT', self.root / 'different-root' / 'Library'):
            self.launch()
        self.assertTrue(target.is_file())
        self.assertFalse(source.exists())
        self.assertTrue(journal.path.exists())
