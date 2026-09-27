"""Default ranking through real MCP HTTP writes, using disposable files only."""
import io
import json
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from paper_monitor import finder_alias, ui_server as ui
from paper_monitor.storage import Storage
from paper_monitor.ai_contract import WRITE_SCOPES
from tests import test_ai_writes as fixtures


class AIImportDefaultTests(unittest.TestCase):
    tearDown = fixtures.AIWriteTests.tearDown
    request = fixtures.AIWriteTests.request
    call = fixtures.AIWriteTests.call
    enable_writes = fixtures.AIWriteTests.enable_writes
    upload = fixtures.AIWriteTests.upload
    metadata = fixtures.AIWriteTests.metadata
    import_args = fixtures.AIWriteTests.import_args

    def setUp(self):
        fixtures.AIWriteTests.setUp(self)
        # Use the real managed-root relationship to the disposable SQLite file.
        # The generic access fixture deliberately uses paths outside that root.
        for name, folder in (('LIBRARY_LOCAL_COPY_ROOT', 'Library'), ('SPACES_LOCAL_COPY_ROOT', 'Spaces'),
                             ('MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'My Publications'),
                             ('ASSOCIATED_FILES_ROOT', 'Associated Files'), ('DEFAULT_PDF_DIR', 'pdfs')):
            active = patch.object(ui, name, self.path.parent / folder)
            active.start()
            self.patches.append(active)

    def start_preprint(self):
        self.writer_token = self.enable_writes(scopes=['papers:read', 'files:read', 'folders:read',
                                                      'analysis:write', *set(WRITE_SCOPES.values())])
        args = self.import_args(self.upload(self.writer_token))
        args['file_type'] = 'preprint'
        status, result, _ = self.call('import_paper', args, token=self.writer_token)
        self.assertEqual(status, 200, result)
        self.work_key = result['gewu_key']
        self.work_id = self.storage.paper_for_key(self.work_key)['paper_id']
        self.preprint_id = result['file']['file_id']
        return result

    def append(self, kind, index=1, content=None, name=None):
        if content is None:
            writer = PdfWriter()
            writer.add_blank_page(width=300 + index, height=400)
            output = io.BytesIO()
            writer.write(output)
            content = output.getvalue()
        upload = self.upload(self.writer_token, name=name or f'{kind}-{index}.pdf',
                             content=content, request=f'upload-version-{index}')
        args = dict(gewu_key=self.work_key, upload_id=upload['upload_id'],
                    file_type=kind, request_id=f'append-version-{index}')
        status, result, _ = self.call('add_paper_file', args, token=self.writer_token)
        self.assertEqual(status, 200, result)
        return result, args, content

    def assert_default(self, file_id):
        status, details, _ = self.call('get_paper', {'gewu_key': self.work_key}, token=self.writer_token)
        self.assertEqual(status, 200, details)
        self.assertEqual(details['default_file_id'], file_id)
        self.assertEqual([f['file_id'] for f in details['files'] if f['is_default']], [file_id])
        return self.storage.get_paper_resource(file_id)

    def test_append_publication_versions_ranks_automatically_and_survives_reopen(self):
        self.start_preprint()
        for index, kind in enumerate(('accepted_manuscript', 'published_version', 'corrected_published_version'), 1):
            result, _, content = self.append(kind, index)
            resource = self.assert_default(result['file']['file_id'])
            self.assertTrue(result['file']['is_default'])
            self.assertFalse(result['layout_pending'])
            self.assertEqual(Path(resource['stored_path']).parent.resolve(), ui.LIBRARY_LOCAL_COPY_ROOT.resolve())
            self.assertEqual(Path(resource['stored_path']).read_bytes(), content)
            with closing(Storage(self.path)) as reopened:
                paper = reopened.get_paper(self.work_id)
                self.assertFalse(paper['preferred_resource_manual'])
                self.assertIsNone(paper['preferred_resource_id'])
                self.assertEqual(paper['primary_resource_id'], resource['id'])
                self.assertEqual(reopened.resolve_default_paper_resource(self.work_id)['id'], resource['id'])
        preprint = self.storage.get_paper_resource(self.preprint_id)
        self.assertTrue(Path(preprint['stored_path']).resolve().is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()), preprint['stored_path'])
        self.assertEqual(Path(preprint['stored_path']).read_bytes(), self.pdf_bytes)

    def test_real_manual_preprint_choice_survives_append_and_reopen(self):
        self.start_preprint()
        ui.set_preferred_paper_file(self.storage, self.work_id, self.preprint_id)
        result, _, content = self.append('published_version')
        self.assert_default(self.preprint_id)
        self.assertFalse(result['file']['is_default'])
        resource = self.storage.get_paper_resource(result['file']['file_id'])
        self.assertTrue(Path(resource['stored_path']).is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()))
        self.assertEqual(Path(resource['stored_path']).read_bytes(), content)
        with closing(Storage(self.path)) as reopened:
            self.assertTrue(reopened.get_paper(self.work_id)['preferred_resource_manual'])
            self.assertEqual(reopened.resolve_default_paper_resource(self.work_id)['id'], self.preprint_id)
        ui.set_preferred_paper_file(self.storage, self.work_id, None)
        self.assert_default(resource['id'])

    def test_supplements_notes_and_unknown_attachments_do_not_take_default(self):
        self.start_preprint()
        for index, kind in enumerate(('supplementary_material', 'correction_notice', 'peer_review_file',
                                      'source_data', 'source_code', 'analysis', 'unknown', 'other'), 1):
            result, _, _ = self.append(kind, index)
            self.assertFalse(result['file']['is_default'])
            self.assert_default(self.preprint_id)

    def test_same_identity_import_updates_main_and_both_folder_aliases(self):
        self.start_preprint()
        space = self.call('create_space', {'name': 'Second context', 'request_id': 'second-context'},
                          token=self.writer_token)[1]
        writer = PdfWriter(); writer.add_blank_page(width=410, height=520)
        output = io.BytesIO(); writer.write(output)
        upload = self.upload(self.writer_token, name='published.pdf', content=output.getvalue(), request='upload-second-context')
        args = self.import_args(upload)
        args.update(folder_id=space['folder_id'], request_id='import-second-context')
        status, result, _ = self.call('import_paper', args, token=self.writer_token)
        self.assertEqual(status, 200, result)
        self.assertEqual(result['gewu_key'], self.work_key)
        self.assertTrue(result['reused_paper'])
        resource = self.assert_default(result['file']['file_id'])
        canonical = Path(resource['stored_path']).resolve()
        self.assertEqual(canonical.read_bytes(), output.getvalue())
        paper = self.storage.get_paper(self.work_id)
        members = [dict(r) for r in self.storage.conn.execute('SELECT * FROM library_items WHERE paper_id=?', (self.work_id,))]
        self.assertEqual(len(members), 2)
        for member in members:
            path = ui.library_item_local_pdf_path(self.storage, member, paper)
            self.assertIsNotNone(path)
            self.assertEqual(finder_alias.resolve(path), canonical)
        self.assertEqual(Path(self.storage.get_paper_resource(self.preprint_id)['stored_path']).read_bytes(), self.pdf_bytes)
        self.assertEqual(self.storage.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_duplicate_and_exact_retry_preserve_ids_and_classification(self):
        self.start_preprint()
        result, args, content = self.append('published_version')
        repeated = self.call('add_paper_file', args, token=self.writer_token)[1]
        self.assertTrue(repeated['reused_request'])
        self.assertEqual(repeated['file']['file_id'], result['file']['file_id'])
        # A different classification on identical bytes does not silently reclassify them.
        duplicate, _, _ = self.append('supplementary_material', 2, content)
        self.assertTrue(duplicate['reused_file'])
        self.assertEqual(duplicate['file']['file_id'], result['file']['file_id'])
        self.assertEqual(duplicate['file']['file_type'], 'published_version')
        self.assert_default(result['file']['file_id'])
        self.assertEqual(len(self.storage.list_paper_resources(self.work_id)), 2)

    def test_historical_attachment_provenance_is_not_a_manual_choice(self):
        self.start_preprint()
        result, _, _ = self.append('published_version')
        resource = self.storage.get_paper_resource(result['file']['file_id'])
        self.assertEqual(resource['added_via'], 'ai_import_attachment')
        self.assertFalse(resource['file_type_override'])
        self.assert_default(resource['id'])
        # Genuine unresolved identity conflicts remain excluded, even if called Published.
        self.storage.conn.execute("UPDATE resources SET added_via='inventory_conflict' WHERE id=?", (resource['id'],))
        self.storage.conn.commit()
        self.assert_default(self.preprint_id)

    def test_reconcile_old_import_layout_preserves_other_records_and_memberships(self):
        self.start_preprint()
        selector = Storage._select_default_paper_resource
        def old_selection(paper, resources):
            return selector(paper, [r for r in resources if r.get('added_via') != 'ai_import_attachment'])
        with patch.object(Storage, '_select_default_paper_resource', side_effect=old_selection):
            result, _, published_bytes = self.append('published_version')
            self.assert_default(self.preprint_id)
        others = [dict(r) for r in self.storage.conn.execute('SELECT * FROM papers WHERE paper_id<>?', (self.work_id,))]
        members = [dict(r) for r in self.storage.conn.execute('SELECT * FROM library_items')]
        ui.sync_all_pdf_aliases_for_paper(self.storage, self.work_id, preserve_canonical_name=True)
        resource = self.assert_default(result['file']['file_id'])
        self.assertEqual(Path(resource['stored_path']).parent.resolve(), ui.LIBRARY_LOCAL_COPY_ROOT.resolve())
        self.assertEqual(Path(resource['stored_path']).read_bytes(), published_bytes)
        preprint = self.storage.get_paper_resource(self.preprint_id)
        self.assertTrue(Path(preprint['stored_path']).resolve().is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()))
        self.assertEqual(Path(preprint['stored_path']).read_bytes(), self.pdf_bytes)
        self.assertEqual([dict(r) for r in self.storage.conn.execute('SELECT * FROM papers WHERE paper_id<>?', (self.work_id,))], others)
        self.assertEqual([dict(r) for r in self.storage.conn.execute('SELECT * FROM library_items')], members)
        self.assertFalse(self.storage.get_paper(self.work_id)['preferred_resource_manual'])

    def test_layout_failure_then_retry_preserves_all_bytes_and_saved_analysis(self):
        self.start_preprint()
        image, _, image_bytes = self.append('other', 10, b'fixture image bytes', 'figure.png')
        status, note, _ = self.call('save_analysis', {'gewu_key': self.work_key, 'title': 'Fixture reading',
            'markdown': '# Fixture\n\n![figure](figure.png)', 'request_id': 'fixture-reading'}, token=self.writer_token)
        self.assertEqual(status, 200, note)
        note_bytes = Path(self.storage.get_paper_resource(note['file']['file_id'])['stored_path']).read_bytes()
        analysis_before = [dict(r) for r in self.storage.conn.execute('SELECT * FROM ai_analyses')]
        with patch.object(ui, 'update_paper_file_path_references', side_effect=OSError('fixture move failure')):
            result, args, published_bytes = self.append('published_version')
        self.assertTrue(result['layout_pending'])
        self.assertEqual(Path(self.storage.get_paper_resource(self.preprint_id)['stored_path']).read_bytes(), self.pdf_bytes)
        repeated = self.call('add_paper_file', args, token=self.writer_token)[1]
        self.assertFalse(repeated['layout_pending'])
        resource = self.assert_default(result['file']['file_id'])
        self.assertEqual(Path(resource['stored_path']).read_bytes(), published_bytes)
        note_path = Path(self.storage.get_paper_resource(note['file']['file_id'])['stored_path'])
        image_path = Path(self.storage.get_paper_resource(image['file']['file_id'])['stored_path'])
        self.assertEqual(note_path.read_bytes(), note_bytes)
        self.assertEqual(image_path.read_bytes(), image_bytes)
        self.assertEqual(note_path.parent / 'figure.png', image_path)
        self.assertEqual(len(self.storage.list_paper_resources(self.work_id)), 4)
        self.assertEqual([dict(r) for r in self.storage.conn.execute('SELECT * FROM ai_analyses')], analysis_before)


if __name__ == '__main__':
    unittest.main()
