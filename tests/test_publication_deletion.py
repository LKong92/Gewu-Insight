import shutil
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from paper_monitor import ui_server as ui, publication_jobs as jobs
from paper_monitor.publication_deletion import delete_publications
from paper_monitor.storage import Storage
from paper_monitor.workflow_store import publication_work_snapshot, PUBLICATION_REMOVED_BY_USER
from tests.test_publication_jobs import candidate


class PublicationDeletionTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.storage = Storage(self.root / 'test.sqlite'); self.addCleanup(self.storage.close)
        for name in ('LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'ASSOCIATED_FILES_ROOT', 'DEFAULT_LIBRARY_IMPORT_DIR', 'DEFAULT_PDF_DIR'):
            target = self.root / name; target.mkdir()
            patcher = patch.object(ui, name, target); patcher.start(); self.addCleanup(patcher.stop)
        self.trash = self.root / 'Trash'; self.trash.mkdir()
        def trash(path):
            target = self.trash / path.name
            shutil.move(str(path), target)
            return target
        if sys.platform == 'win32':
            from paper_monitor import windows_recycle
            patcher = patch.object(windows_recycle, 'recycle_file', side_effect=trash)
            restore = patch.object(windows_recycle, 'restore_shell_item', side_effect=lambda source, target: shutil.move(str(source), str(target)))
            restore.start(); self.addCleanup(restore.stop)
        else:
            patcher = patch.object(ui, 'move_path_to_macos_trash', side_effect=trash)
        self.move = patcher.start(); self.addCleanup(patcher.stop)

    def publication(self, number):
        paper_id = f'fixture_{number}'
        paper = ui.paper_from_publication_candidate(candidate(number, f'10.1234/delete{number}'))
        paper['paper_id'] = paper_id
        self.storage.upsert_paper(paper)
        return self.storage.add_my_publication(paper_id=paper_id)

    def file(self, publication, *, shared=None, external=False):
        path = shared or ((self.root if external else ui.MY_PUBLICATIONS_LOCAL_COPY_ROOT) / f"{publication['paper_id']}.pdf")
        path.write_bytes(b'fixture file')
        self.storage.conn.execute('UPDATE papers SET main_pdf_path=?,merged_pdf_path=? WHERE paper_id=?', (str(path), str(path), publication['paper_id']))
        self.storage.conn.commit()
        return path

    def test_last_placement_removes_paper_metadata_tasks_and_managed_files(self):
        publication = self.publication(1); path = self.file(publication)
        self.storage.conn.execute("INSERT INTO publication_identifier_tasks(publication_id,status) VALUES (?,'pending')", (publication['id'],))
        self.storage.conn.commit()
        result = delete_publications(self.storage, [publication['id']])
        self.assertEqual(result['deleted_paper_ids'], [publication['paper_id']])
        self.assertIsNone(self.storage.get_paper(publication['paper_id']))
        self.assertEqual(publication_work_snapshot(self.storage)['identifiers'], {})
        self.assertFalse(path.exists()); self.assertTrue((self.trash / path.name).exists())
        self.assertEqual(list(self.storage.conn.execute('PRAGMA foreign_key_check')), [])

    def test_library_space_and_recycle_references_preserve_key_and_file(self):
        for index, name in enumerate(('Library folder', 'Space root', 'Recycle'), 1):
            with self.subTest(name=name):
                publication = self.publication(index); path = self.file(publication)
                key = self.storage.get_paper(publication['paper_id'])['storage_key']
                folder = self.storage.create_library_root_folder(name=name)
                self.storage.add_library_item(paper_id=publication['paper_id'], folder_id=folder['id'])
                result = delete_publications(self.storage, [publication['id']])
                self.assertEqual(result['retained_paper_ids'], [publication['paper_id']])
                self.assertEqual(self.storage.get_paper(publication['paper_id'])['storage_key'], key)
                self.assertTrue(path.exists())
        self.move.assert_not_called()

    def test_external_original_and_bytes_shared_with_another_paper_are_preserved(self):
        first = self.publication(1); external = self.file(first, external=True)
        delete_publications(self.storage, [first['id']]); self.assertTrue(external.exists())
        second, third = self.publication(2), self.publication(3)
        shared = self.file(second); self.file(third, shared=shared)
        delete_publications(self.storage, [second['id']]); self.assertTrue(shared.exists())
        self.assertIsNotNone(self.storage.get_paper(third['paper_id']))
        self.move.assert_not_called()

    def test_shared_resource_source_preserves_bytes_and_bulk_last_owner_trashes_once(self):
        first, second = self.publication(1), self.publication(2)
        path = self.file(first)
        self.storage.conn.execute("INSERT INTO resources(paper_id,source_path,created_at,updated_at) VALUES (?,?,'2026-09-09','2026-09-09')", (second['paper_id'], str(path)))
        self.storage.conn.commit()
        result = delete_publications(self.storage, [first['id'], second['id']])
        self.assertEqual(len(result['deleted_paper_ids']), 2)
        self.assertEqual(result['trashed_file_count'], 1)
        self.move.assert_called_once()
        self.assertFalse(path.exists())

    def test_failed_sql_delete_restores_files_and_all_placements(self):
        first, second = self.publication(1), self.publication(2)
        path = self.file(first)
        self.storage.conn.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON papers WHEN OLD.paper_id='fixture_2' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        self.storage.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            delete_publications(self.storage, [first['id'], second['id']])
        self.assertEqual(len(self.storage.list_my_publications()), 2)
        self.assertTrue(path.exists()); self.assertEqual(path.read_bytes(), b'fixture file')

    def test_failed_trash_keeps_record_and_file(self):
        publication = self.publication(1); path = self.file(publication)
        self.move.side_effect = PermissionError('test refusal')
        with self.assertRaises(PermissionError): delete_publications(self.storage, [publication['id']])
        self.assertIsNotNone(self.storage.get_paper(publication['paper_id']))
        self.assertEqual(len(self.storage.list_my_publications()), 1); self.assertTrue(path.exists())

    def test_removed_checkpoint_does_not_resurrect_on_resume_but_explicit_recheck_can_readd(self):
        profile = {'url':'https://scholar.google.com/citations?user=fixture', 'name':'Test Author'}
        job = jobs.create_import(self.storage, profile)
        with patch.object(jobs, 'fetch_profile_page', return_value={'candidates':[candidate(1)], 'next_offset':1, 'finished':False}):
            jobs.run_import_step(self.storage)
        publication = self.storage.list_my_publications()[0]
        delete_publications(self.storage, [publication['id']])
        snapshot = publication_work_snapshot(self.storage)['imports'][0]
        self.assertEqual(snapshot['status'], 'paused'); self.assertEqual(snapshot['currently_saved'], 0)
        self.assertIsNone(self.storage.get_paper(publication['paper_id']))
        self.assertEqual(self.storage.conn.execute('SELECT error FROM publication_import_items').fetchone()[0], PUBLICATION_REMOVED_BY_USER)
        jobs.control_import(self.storage, job['id'], 'resume')
        with patch.object(jobs, 'fetch_profile_page', return_value={'candidates':[candidate(1),candidate(2)], 'next_offset':3, 'finished':True}):
            jobs.run_import_step(self.storage)
        self.assertEqual(len(self.storage.list_my_publications()), 1)
        jobs.control_import(self.storage, job['id'], 'check')
        with patch.object(jobs, 'fetch_profile_page', return_value={'candidates':[candidate(1),candidate(2)], 'next_offset':2, 'finished':True}):
            jobs.run_import_step(self.storage)
        self.assertEqual(len(self.storage.list_my_publications()), 2)

    def test_no_files_never_scans_shared_file_owners(self):
        publication = self.publication(1)
        with patch.object(ui, 'paper_pdf_paths', side_effect=AssertionError('No filesystem scan for metadata-only deletion')):
            delete_publications(self.storage, [publication['id']])

    def test_pause_message_reports_local_retry_time_without_claiming_ip_ban(self):
        message = ui.google_scholar_global_cooldown_message({'until':'2026-09-09T23:57:42+08:00'})
        self.assertIn('Gewu Insight', message); self.assertIn('Try again after', message)
        self.assertIn('local time', message); self.assertNotIn('IP', message)
