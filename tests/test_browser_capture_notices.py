"""Browser-only notice attachment regressions; all writes use temporary data."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import ExitStack

import test_browser_capture as fixture
from paper_monitor import publication_notices as notices, ui_server as ui
from paper_monitor.storage import Storage


class BrowserNoticeAttachmentTests(unittest.TestCase):
    setUp = fixture.BrowserCaptureTests.setUp
    clean = fixture.BrowserCaptureTests.clean
    paper = fixture.BrowserCaptureTests.paper
    begin = fixture.BrowserCaptureTests.begin
    review = fixture.BrowserCaptureTests.review
    save = fixture.BrowserCaptureTests.save
    pdf = fixture.BrowserCaptureTests.pdf
    upload = fixture.BrowserCaptureTests.upload
    count = fixture.BrowserCaptureTests.count

    def self_updated_article(self):
        paper = self.paper()
        raw = {'arxiv_id': '2212.02274', 'crossref': {'type': 'journal-article',
            'update-to': [{'type': 'correction', 'DOI': '10.1234/FIRST'}]}}
        # Seed the legacy state without changing the shared ingestion policy.
        self.storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?',
                                  (json.dumps(raw), paper['paper_id']))
        self.storage.conn.commit()
        return self.storage.get_paper(paper['paper_id'])

    def notice_capture(self, kind='correction', related='10.1234/first'):
        title = ('Retraction Note: ' if kind == 'retraction' else 'Author Correction: ') + 'Research'
        paper = {'paper_id': 'notice', 'title': title, 'doi': '10.1234/notice',
                 'raw': {'crossref': {'update-to': [{'type': kind, 'DOI': related}]}} if related else {}}
        capture = self.begin(doi=paper['doi'])
        self.upload(capture, title=title, found={'kind': 'doi', 'identifier': paper['doi']})
        capture.resolved['doi:' + paper['doi']] = paper
        return capture

    def test_existing_self_update_and_pending_notice_do_not_block_browser_attachment(self):
        original = self.self_updated_article()
        first = self.storage.add_library_item(paper_id='first', folder_id=1)
        space = self.storage.ensure_library_folder(parent_id=None, name='deepseek')
        second = self.storage.add_library_item(paper_id='first', folder_id=space['id'])
        old_notice = notices.record(self.storage, original, notices.describe(original), commit=True)
        pending = dict(self.storage.conn.execute('SELECT * FROM publication_notices WHERE id=?', (old_notice,)).fetchone())
        old_pdf = ui.attach_file_to_paper(self.storage, paper_id='first', filename='preprint.pdf',
            content=self.pdf('Preprint'), file_type='preprint', added_via='browser_capture')
        ui.set_preferred_paper_file(self.storage, 'first', old_pdf['id'])
        capture = self.begin(origin_paper_id='first', origin_library_item_id=second['id'])
        self.upload(capture, found={'kind': 'doi', 'identifier': original['doi']})
        reviewed = self.review(capture)
        self.assertTrue(reviewed['can_save'])
        result = self.save(capture, include_pdf=True, file_type='published_version')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['gewu_key'], original['storage_key'])
        self.assertEqual(result['item_id'], second['id'])
        self.assertEqual(self.count('papers'), 1)
        self.assertEqual(self.count('library_items'), 2)
        self.assertEqual(self.storage.get_library_item(first['id'])['paper_id'], 'first')
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], old_pdf['id'])
        saved = next(r for r in self.storage.list_paper_resources('first') if r['id'] != old_pdf['id'])
        self.assertEqual(saved['file_type'], 'published_version')
        self.assertEqual(Path(saved['stored_path']).read_bytes(), capture.path.read_bytes())
        self.assertEqual(dict(self.storage.conn.execute('SELECT * FROM publication_notices WHERE id=?', (old_notice,)).fetchone()), pending)
        after = self.storage.get_paper('first')
        self.assertEqual(json.loads(after['raw_json'])['crossref'], json.loads(original['raw_json'])['crossref'])
        # The exception is local to Browser, not a change to MCP/Monitor guards.
        self.assertIsNotNone(notices.describe_known(self.storage, after))
        with self.assertRaises(notices.NoticeReviewRequired): notices.guard(self.storage, after)

    def test_notice_review_shows_original_and_saves_only_notice_file(self):
        original = self.paper()
        capture = self.notice_capture(kind='retraction')
        reviewed = self.review(capture)
        self.assertTrue(reviewed['can_save'])
        self.assertEqual(reviewed['paper']['gewu_key'], original['storage_key'])
        self.assertEqual(reviewed['suggested_file_type'], 'retraction_notice')
        self.assertEqual(self.count('publication_notices'), 0)
        result = self.save(capture, include_pdf=True, file_type='published_version')
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.count('papers'), 1)
        resource = self.storage.list_paper_resources('first')[0]
        self.assertEqual(resource['file_type'], 'retraction_notice')
        self.assertIsNone(self.storage.resolve_default_paper_resource('first'))

        self.assertEqual(notices.for_paper(self.storage, 'first')[0]['file_ids'], [resource['id']])
        self.assertEqual(self.save(capture, include_pdf=True), result)

    def test_unresolved_notice_can_be_manually_attached_after_confirmation(self):
        original = self.self_updated_article()
        capture = self.notice_capture(related='')
        reviewed = self.review(capture)
        self.assertFalse(reviewed['can_save'])
        self.assertIn('Gewu Key', reviewed['warning'])
        self.assertEqual(self.count('publication_notices'), 0)
        self.assertFalse(self.review(capture, target_key=original['storage_key'])['can_save'])
        reviewed = self.review(capture, target_key=original['storage_key'], confirm_target=True)
        self.assertTrue(reviewed['can_save'])
        self.assertEqual(reviewed['suggested_file_type'], 'correction_notice')
        result = self.save(capture, include_pdf=True, file_type='correction_notice')
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['paper_id'], 'first')
        self.assertEqual(self.count('papers'), 1)
        event = notices.for_paper(self.storage, 'first')[0]
        self.assertEqual(event['relation']['related_dois'], [original['doi']])
        self.assertIsNone(self.storage.resolve_default_paper_resource('first'))

    def test_notice_can_resolve_new_original_without_creating_notice_identity(self):
        capture = self.notice_capture()
        parent = {'paper_id': 'parent', 'doi': '10.1234/first', 'title': 'Original research',
                  'journal': 'Fixture Journal', 'publication_date': '2023-09-15', 'source': 'crossref', 'raw': {}}
        with patch.object(self.service, 'resolve', return_value=parent) as resolver:
            reviewed = self.review(capture)
        resolver.assert_called_once_with('doi', parent['doi'])
        self.assertEqual(reviewed['paper']['paper_id'], 'parent')
        self.assertEqual(self.count('papers'), 0)
        self.assertEqual(self.count('publication_notices'), 0)
        result = self.save(capture, include_pdf=True)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['paper_id'], 'parent')
        self.assertEqual(self.count('papers'), 1)
        self.assertIsNone(self.storage.get_paper('notice'))

    def test_notice_target_changed_after_review_requires_review_again(self):
        self.paper()
        capture = self.notice_capture()
        self.review(capture)
        self.storage.conn.execute("UPDATE papers SET doi='10.1234/changed' WHERE paper_id='first'")
        self.storage.conn.commit()
        with self.assertRaisesRegex(ValueError, 'identifiers changed'): self.save(capture, include_pdf=True)
        self.assertEqual(self.count('resources'), 0)
        self.assertEqual(self.count('publication_notices'), 0)

    def test_reupload_does_not_reuse_previous_notice_target(self):
        original = self.paper()
        capture = self.notice_capture()
        self.review(capture)
        self.upload(capture, title=original['title'], found={'kind': 'doi', 'identifier': original['doi']})
        capture.snapshot['metadata']['doi'] = original['doi']
        reviewed = self.review(capture)
        self.assertTrue(reviewed['can_save'])
        self.assertTrue(self.save(capture, include_pdf=True, file_type='published_version')['ok'])
        self.assertEqual(self.storage.list_paper_resources('first')[0]['file_type'], 'published_version')
        self.assertEqual(self.count('publication_notices'), 0)

    def test_failed_or_wrong_parent_resolution_leaves_manual_key_path_without_writes(self):
        for answer in (None, {'paper_id': 'wrong', 'doi': '10.1234/wrong', 'title': 'Wrong article'}):
            with self.subTest(answer=answer):
                capture = self.notice_capture()
                with patch.object(self.service, 'resolve', return_value=answer):
                    reviewed = self.review(capture)
                self.assertFalse(reviewed['can_save'])
                self.assertIn('Gewu Key', reviewed['warning'])
                for table in ('papers', 'publication_notices', 'resources', 'library_items'):
                    self.assertEqual(self.count(table), 0)

    def test_explicit_notice_with_self_relation_is_not_treated_as_an_original(self):
        for extra in ({'title': 'Retraction Note: Research'}, {'type': 'correction'},
                      {'publication_notice': {'kind': 'correction_notice'}}):
            with self.subTest(extra=extra):
                paper = {'doi': '10.1234/notice', 'title': 'Research',
                         'raw': {'update-to': [{'type': 'correction', 'DOI': '10.1234/notice'}]}, **extra}
                self.assertIsNotNone(self.service._attachment_notice(self.storage, paper))

    def test_manual_retraction_pdf_attaches_to_existing_original_without_new_identity(self):
        original = self.paper()
        capture = self.begin(doi='10.1234/unknown-notice')
        self.upload(capture, title='Retraction Note: Research')
        reviewed = self.review(capture, target_key=original['storage_key'], confirm_target=True)
        self.assertTrue(reviewed['can_save'])
        self.assertEqual(reviewed['suggested_file_type'], 'retraction_notice')
        result = self.save(capture, include_pdf=True, file_type=reviewed['suggested_file_type'])
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.count('papers'), 1)
        self.assertEqual(self.storage.list_paper_resources('first')[0]['file_type'], 'retraction_notice')
        self.assertIsNone(self.storage.resolve_default_paper_resource('first'))


class BrowserSelfUpdateApiTests(unittest.TestCase):
    setUp = fixture.BrowserCaptureApiTests.setUp
    tearDown = fixture.BrowserCaptureApiTests.tearDown
    request = fixture.BrowserCaptureApiTests.request
    headers = fixture.BrowserCaptureApiTests.headers
    post = fixture.BrowserCaptureApiTests.post
    upload = fixture.BrowserCaptureApiTests.upload
    pdf = fixture.BrowserCaptureTests.pdf

    def test_browser_api_saves_self_updated_article_and_reuses_pdf(self):
        root = Path(self.temp.name)
        with ExitStack() as stack:
            for name in ('LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT',
                         'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'DEFAULT_PDF_DIR', 'ASSOCIATED_FILES_ROOT'):
                stack.enter_context(patch.object(ui, name, root / name))
            storage = Storage(root / 'api.sqlite')
            try:
                storage.upsert_paper({'paper_id': 'original', 'title': 'API original research',
                    'doi': '10.1234/api', 'journal': 'Fixture Journal', 'publication_date': '2023-09-15',
                    'source': 'fixture', 'raw': {}})
                storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?',
                    (json.dumps({'crossref': {'update-to': [{'type': 'correction', 'DOI': '10.1234/api'}]}}), 'original'))
                storage.conn.commit()
                original = storage.get_paper('original')
                notices.record(storage, original, notices.describe(original), commit=True)
                content = self.pdf('API original research')
                for duplicate in (False, True):
                    review = self.post('capture_begin', snapshot={'url': 'https://example.org/paper',
                        'metadata': {'doi': original['doi'], 'title': original['title']}})
                    self.assertEqual(self.upload(content, {'Content-Type': 'application/pdf',
                        'X-Gewu-Capture-Token': review['upload_token']}), 200)
                    reviewed = self.post('capture_review', token=review['token'], resolve=False)
                    self.assertTrue(reviewed['can_save'])
                    saved = self.post('capture_save', token=review['token'], include_pdf=True, file_type='published_version')
                    self.assertTrue(saved['ok'], saved)
                    self.assertEqual(saved['gewu_key'], original['storage_key'])
                    self.assertEqual(saved['duplicate_file'], duplicate)
                    self.assertEqual(saved['paper_files'][0]['files'][0]['file_type'], 'published_version')
                    self.post('capture_cancel', token=review['token'])
                self.assertEqual(len(storage.list_paper_resources('original')), 1)
                self.assertFalse(storage.conn.execute('PRAGMA foreign_key_check').fetchall())
            finally:
                storage.close()
