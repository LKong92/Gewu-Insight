"""Manual Paper Details DOI conflicts; only disposable databases/files."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import unittest

from paper_monitor import manual_doi as manual, metadata_refresh, paper_identity, ui_server as ui
from paper_monitor import finder_alias, folder_rename, desktop_files
from paper_monitor.file_layout import reconcile
from paper_monitor.storage import Storage
from tests import test_paper_resources as fixtures


DOI = '10.1234/manual-conflict'


class ManualDoiTests(unittest.TestCase):
    setUp = fixtures.PaperResourceStorageTests.setUp
    tearDown = fixtures.PaperResourceStorageTests.tearDown

    def fixture(self, other_pdf=True, associated=True):
        self.paths, self.files, self.items = {}, {}, {}
        for pid, doi, name in [('current', '', 'FeSe_Tip'), ('existing', DOI, 'Earlier')]:
            self.storage.upsert_paper(dict(paper_id=pid, doi=doi, title='Synthetic superconductivity paper',
                journal='Test Journal', source='fixture', raw={'authors': ['A Researcher']}))
            if pid == 'existing' and not other_pdf:
                continue
            folder = self.storage.create_library_folder(name=name, parent_id=1)
            item = self.storage.add_library_item(paper_id=pid, folder_id=folder['id'])
            item = self.storage.rename_library_item(item_id=item['id'], name=pid+'.pdf')
            self.items[pid] = item
            path = ui.local_copy_dir_for_library_folder(self.storage, folder['id']) / (pid+'.pdf')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'%PDF fixture '+pid.encode())
            external = self.root / (pid+'-original.pdf')
            external.write_bytes(path.read_bytes())
            resource = self.storage.create_paper_resource(paper_id=pid, stored_path=str(path),
                source_path=str(external), file_role='publication_version', file_type='published_version')
            self.storage.conn.execute('UPDATE papers SET main_pdf_path=?,merged_pdf_path=?,primary_resource_id=?,preferred_resource_id=?,preferred_resource_manual=1 WHERE paper_id=?',
                (str(path), str(path), resource['id'], resource['id'], pid))
            self.storage.conn.commit()
            self.paths[pid], self.files[pid] = path, resource
            if associated:
                extra = self.associated_root / name / 'supplement.pdf'
                extra.parent.mkdir(parents=True, exist_ok=True)
                extra.write_bytes(b'%PDF supplement '+pid.encode())
                self.storage.create_paper_resource(paper_id=pid, stored_path=str(extra), file_role='supplement')
                reconcile(self.storage, pid)
        self.storage.record_theme_result(paper_id='existing', group_key='sc', group_name='Superconductivity',
            query='superconductivity', score=5, hits=['sample'], window_start='2026-10-14', window_end='2026-10-14')
        run = self.storage.start_fetch_run(monitor_type='journal', source='fixture', journal='Test Journal',
            window_start='2026-10-14', window_end='2026-10-14', started_at='2026-10-14')
        self.storage.record_journal_monitor_paper(fetch_run_id=run, paper_id='existing', source='fixture')
        author = self.storage.add_author_monitor(dict(user_id='author', name='Author',
            url='https://scholar.google.com/citations?user=author'))['id']
        self.storage.add_author_monitor_paper(author_monitor_id=author, paper_id='existing', unread=True)
        self.storage.mark_late_arrivals_seen(['existing'])
        self.current = self.storage.get_paper('current')
        self.existing = self.storage.get_paper('existing')
        return self.review()

    def review(self):
        return manual.review(self.storage, 'current', DOI, item_id=self.items['current']['id'])

    def apply(self, review=None, action='merge'):
        review = review or self.review()
        return manual.resolve_conflict(self.storage, 'current', DOI, action=action,
            fingerprint=review['fingerprint'], item_id=review['item_id'])

    def db_state(self):
        return {table: [tuple(r) for r in self.storage.conn.execute('SELECT * FROM '+table)] for table in
            ('papers', 'resources', 'library_items', 'paper_aliases', 'paper_identifiers', 'paper_identity_history',
             'theme_results', 'journal_monitor_papers', 'author_monitor_papers', 'paper_reads')}

    def test_review_cancel_is_read_only_and_shows_both_sources(self):
        review = self.fixture(other_pdf=False)
        before = self.db_state()
        self.assertEqual(self.review(), review)
        self.assertEqual(before, self.db_state())
        self.assertIn('Subject Monitor', review['existing']['monitors'])
        self.assertEqual(review['current']['default_file'], 'current.pdf')
        self.assertEqual(review['main_location'], str(self.paths['current'].parent))

    def test_review_shows_pubmed_authors_without_changing_metadata_readers(self):
        self.fixture(other_pdf=False)
        self.storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?',
            (json.dumps({'pubmed': {'authors': ['A Researcher', 'B Scientist']}}), 'existing'))
        self.storage.conn.commit()
        self.assertEqual(self.review()['existing']['authors'], 'A Researcher, B Scientist')

    def test_merge_keeps_current_default_moves_all_other_bytes_and_retains_monitors(self):
        self.fixture()
        resources = [dict(r) for r in self.storage.conn.execute('SELECT * FROM resources')]
        original = {r['id']: Path(r['stored_path']).read_bytes() for r in resources}
        source_key, target_key = self.existing['storage_key'], self.current['storage_key']
        result = self.apply()
        self.assertEqual(result['warning'], '')
        paper = self.storage.get_paper('current')
        self.assertEqual(paper['doi'], DOI)
        self.assertEqual(paper['storage_key'], target_key)
        self.assertEqual(self.storage.paper_for_key(source_key)['paper_id'], 'current')
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 1)
        self.assertEqual(paper['main_pdf_path'], str(self.paths['current']))
        self.assertEqual(paper['preferred_resource_id'], self.files['current']['id'])
        files = self.storage.list_paper_resources('current')
        self.assertEqual(len(files), 4)
        for r in files:
            path = Path(r['stored_path'])
            self.assertEqual(path.read_bytes(), original[r['id']])
            if r['id'] != self.files['current']['id']:
                self.assertTrue(path.is_relative_to(self.associated_root / 'Library' / 'FeSe_Tip'))
                self.assertIn(target_key, str(path))
            self.assertEqual(r['is_default'], r['id'] == self.files['current']['id'])
        self.assertTrue(finder_alias.points_to(desktop_files.placement_path(self.paths['existing']), self.paths['current']))
        for pid in ('current', 'existing'):
            self.assertEqual((self.root / (pid+'-original.pdf')).read_bytes(), b'%PDF fixture '+pid.encode())
        for table in ('theme_results', 'journal_monitor_papers', 'author_monitor_papers', 'paper_reads'):
            rows = self.storage.conn.execute('SELECT * FROM '+table).fetchall()
            self.assertEqual(len(rows), 1, table)
            self.assertEqual(rows[0]['paper_id'], 'current', table)
        self.assertEqual(self.storage.conn.execute('SELECT window_start FROM theme_results').fetchone()[0], '2026-10-14')
        self.assertTrue(ui.annotate_papers_with_library_status(self.storage, [paper])[0]['in_library'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM library_items WHERE paper_id=?', ('current',)).fetchone()[0], 2)
        self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        reconcile(self.storage, 'current')
        self.assertEqual(self.storage.get_paper('current')['main_pdf_path'], str(self.paths['current']))

    def test_monitor_only_owner_has_no_files_but_becomes_saved(self):
        self.fixture(other_pdf=False)
        self.apply()
        self.assertEqual(len(self.storage.list_paper_resources('current')), 2)
        row = self.storage.conn.execute('SELECT paper_id FROM theme_results').fetchone()
        self.assertEqual(row[0], 'current')
        self.assertTrue(ui.annotate_papers_with_library_status(self.storage, [self.storage.get_paper(row[0])])[0]['in_library'])

    def test_selected_secondary_location_becomes_main_with_its_associated_tree(self):
        self.fixture()
        selected = self.storage.create_library_folder(name='Selected', parent_id=1)
        item = self.storage.add_library_item(paper_id='current', folder_id=selected['id'])
        reconcile(self.storage, 'current')
        self.items['current'] = item
        self.apply()
        canonical = Path(self.storage.get_paper('current')['main_pdf_path'])
        self.assertEqual(canonical.parent, self.library_root / 'Selected')
        self.assertEqual(canonical.name, 'current.pdf')
        self.assertTrue(finder_alias.points_to(desktop_files.placement_path(self.paths['current']), canonical))
        self.assertTrue(all(r['is_default'] or Path(r['stored_path']).is_relative_to(self.associated_root / 'Library' / 'Selected')
                            for r in self.storage.list_paper_resources('current')))

    def test_reassign_does_not_merge_move_or_mark_old_monitor_saved(self):
        self.fixture(other_pdf=False)
        self.storage.conn.execute('UPDATE papers SET url=?,semantic_scholar_json=? WHERE paper_id=?',
            ('https://doi.org/'+DOI, '{"citationCount":99}', 'existing'))
        self.storage.conn.commit()
        before = self.db_state()
        self.apply(action='reassign')
        current, other = self.storage.get_paper('current'), self.storage.get_paper('existing')
        self.assertEqual(current['doi'], DOI)
        self.assertFalse(other['doi'])
        self.assertEqual(other['storage_key'], self.existing['storage_key'])
        self.assertEqual(current['storage_key'], self.current['storage_key'])
        self.assertFalse(other['url'])
        self.assertFalse(other['semantic_scholar_json'])
        after = self.db_state()
        for table in ('resources', 'library_items', 'paper_aliases', 'theme_results', 'journal_monitor_papers', 'author_monitor_papers', 'paper_reads'):
            self.assertEqual(before[table], after[table], table)
        self.assertFalse(ui.annotate_papers_with_library_status(self.storage, [other])[0]['in_library'])
        self.assertEqual(self.storage.conn.execute("SELECT paper_id FROM paper_identifiers WHERE kind='doi' AND value=?", (DOI,)).fetchone()[0], 'current')
        with self.assertRaises(paper_identity.IdentityReviewRequired):
            self.storage.upsert_paper(dict(paper_id='existing', doi=DOI, title=other['title'], source='fixture', raw={}))
        self.assertFalse(self.storage.get_paper('existing')['doi'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 2)

    def test_reassign_failure_rolls_back_both_doi_edits(self):
        self.fixture()
        before = self.db_state()
        original = manual._set_doi
        def fail(storage, paper, doi, **kwargs):
            if paper['paper_id'] == 'current':
                raise OSError('synthetic second edit failure')
            original(storage, paper, doi, **kwargs)
        with patch.object(manual, '_set_doi', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                self.apply(action='reassign')
        self.assertEqual(before, self.db_state())

    def test_second_file_update_failure_restores_bytes_db_and_aliases(self):
        self.fixture()
        before = self.db_state()
        originals = {r['stored_path']: Path(r['stored_path']).read_bytes() for r in self.storage.list_paper_resources('existing')}
        original = ui.update_paper_file_path_references
        calls = []
        def fail(*args, **kwargs):
            calls.append(args[2])
            if len(calls) == 2:
                raise OSError('synthetic path failure')
            return original(*args, **kwargs)
        with patch.object(ui, 'update_paper_file_path_references', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'synthetic'):
                self.apply()
        self.assertEqual(before, self.db_state())
        for name, content in originals.items():
            self.assertEqual(Path(name).read_bytes(), content)
        self.assertFalse(list((self.db_path.parent / 'folder-rename-recovery').glob('*/operation.json')))

    def test_file_name_collision_keeps_both_files_without_overwrite(self):
        self.fixture()
        target = ui.existing_associated_work_dir(self.storage, 'current') / 'Versions' / 'existing.pdf'
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'Unregistered user file')
        self.apply()
        self.assertEqual(target.read_bytes(), b'Unregistered user file')
        moved = Path(self.storage.get_paper_resource(self.files['existing']['id'])['stored_path'])
        self.assertNotEqual(target, moved)
        self.assertEqual(moved.read_bytes(), b'%PDF fixture existing')

    def test_changed_records_or_files_reject_old_confirmation(self):
        review = self.fixture()
        self.paths['existing'].write_bytes(b'%PDF changed after review')
        before = self.db_state()
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.apply(review)
        self.assertEqual(before, self.db_state())

    def test_normal_save_and_automatic_identity_guards_unchanged(self):
        self.fixture()
        self.assertIsNone(manual.review(self.storage, 'current', '10.1234/unused'))
        saved = metadata_refresh.save_doi(self.storage, 'current', '10.1234/unused')
        self.assertEqual(saved['doi'], '10.1234/unused')
        with self.assertRaisesRegex(ValueError, 'already registered'):
            metadata_refresh.save_doi(self.storage, 'current', DOI)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 2)
        self.assertIn('Different manual Default files need a choice',
                      paper_identity.merge_blockers(self.storage, self.storage.get_paper('current'), self.existing))

    def test_interruption_before_commit_recovers_original_files_on_restart(self):
        self.fixture()
        review, before = self.review(), self.db_state()
        with patch.object(ui, 'update_paper_file_path_references', side_effect=SystemExit('interruption')):
            with self.assertRaises(SystemExit):
                self.apply(review)
        self.storage.close()  # SQLite rolls back the interrupted transaction.
        self.storage = Storage(self.db_path)
        folder_rename.recover(self.storage)
        self.assertEqual(before, self.db_state())
        self.assertEqual(self.paths['existing'].read_bytes(), b'%PDF fixture existing')

    def test_interruption_after_commit_keeps_merged_files_on_restart(self):
        self.fixture()
        with patch.object(folder_rename.RenameJournal, 'finish', side_effect=SystemExit('interruption')):
            with self.assertRaises(SystemExit):
                self.apply()
        self.storage.close()
        self.storage = Storage(self.db_path)
        folder_rename.recover(self.storage)
        self.assertEqual(self.storage.get_paper('existing')['paper_id'], 'current')
        self.assertEqual(len(self.storage.list_paper_resources('current')), 4)
        self.assertTrue(all(Path(r['stored_path']).is_file() for r in self.storage.list_paper_resources('current')))
        reconcile(self.storage, 'current')
        self.assertTrue(finder_alias.points_to(desktop_files.placement_path(self.paths['existing']), self.paths['current']))

    def test_new_unreviewed_relationship_aborts_without_losing_files(self):
        self.fixture()
        self.storage.conn.execute('CREATE TABLE future_links(paper_id TEXT REFERENCES papers(paper_id), value TEXT)')
        self.storage.conn.execute("INSERT INTO future_links VALUES('existing','keep')")
        self.storage.conn.commit()
        before = self.db_state()
        with self.assertRaisesRegex(ValueError, 'Unreviewed paper relationship'):
            self.apply()
        self.assertEqual(before, self.db_state())
        self.assertEqual(self.paths['existing'].read_bytes(), b'%PDF fixture existing')

    def test_external_linked_attachment_stays_in_place(self):
        self.fixture()
        external = self.root / 'linked.pdf'
        external.write_bytes(b'%PDF external linked bytes')
        resource = self.storage.create_paper_resource(paper_id='existing', stored_path='', source_path=str(external))
        self.apply()
        updated = self.storage.get_paper_resource(resource['id'])
        self.assertEqual(updated['paper_id'], 'current')
        self.assertEqual(updated['source_path'], str(external))
        self.assertEqual(external.read_bytes(), b'%PDF external linked bytes')

    def test_zotero_copy_receipts_follow_survivor_without_recopied_files(self):
        from paper_monitor.zotero_import import store
        self.fixture()
        store.initialize(self.storage)
        self.storage.conn.execute("INSERT INTO zotero_import_papers VALUES('zotero','ABC','existing')")
        self.storage.conn.execute("INSERT INTO zotero_import_files VALUES('zotero','FILE','digest','existing',?)",
                                  (self.files['existing']['id'],))
        self.storage.conn.commit()
        self.apply()
        for table in ('zotero_import_papers', 'zotero_import_files'):
            self.assertEqual(self.storage.conn.execute('SELECT paper_id FROM '+table).fetchone()[0], 'current')
        self.assertEqual(len(self.storage.list_paper_resources('current')), 4)

    def test_handler_review_and_confirmation_only_affect_manual_doi(self):
        self.fixture(other_pdf=False)
        handler = object.__new__(ui.PaperMonitorUiHandler)
        handler.configured_db_path = self.db_path
        handler.send_json = MagicMock()
        handler.send_error_json = MagicMock()
        payload = {'paper_id': 'current', 'kind': 'doi', 'identifier': DOI, 'item_id': self.items['current']['id']}
        handler.handle_update_preprint_identifier(payload)
        handler.send_error_json.assert_not_called()
        review = handler.send_json.call_args.args[0]['doi_conflict']
        self.assertEqual(handler.send_json.call_args.kwargs['status'], 409)
        self.assertFalse(self.storage.get_paper('current')['doi'])
        handler.handle_update_preprint_identifier({**payload, 'fingerprint': review['fingerprint'], 'conflict_action': 'merge'})
        handler.send_error_json.assert_not_called()
        result = handler.send_json.call_args.args[0]
        self.assertTrue(result['paper']['in_library'])
        self.assertEqual(result['merged_paper_id'], 'existing')
        self.assertEqual(len(result['library_items']), 1)
        self.assertEqual(len(result['paper_files']), 1)
        with patch.object(manual, 'review', side_effect=AssertionError('arXiv must not enter DOI review')):
            handler.handle_update_preprint_identifier({'paper_id': 'current', 'kind': 'arxiv', 'identifier': '2201.00001'})
        handler.send_error_json.assert_not_called()


if __name__ == '__main__':
    unittest.main()
