"""Capture-to-Library behavior with temporary SQLite/files and synthetic PDFs."""
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from pypdf import PdfWriter
from paper_monitor import ui_server as ui
from paper_monitor.browser_capture import BrowserCaptureService, identifier, normalize_snapshot
from paper_monitor.storage import Storage


class BrowserCaptureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / 'capture.sqlite'
        self.storage = Storage(self.db)
        self.service = BrowserCaptureService()
        self.patches = [patch.object(ui, name, self.root / name) for name in (
            'LIBRARY_LOCAL_COPY_ROOT', 'SPACES_LOCAL_COPY_ROOT', 'MY_PUBLICATIONS_LOCAL_COPY_ROOT', 'DEFAULT_PDF_DIR', 'ASSOCIATED_FILES_ROOT')]
        self.patches += [patch.object(self.service, 'resolve', return_value=None)]
        for p in self.patches: p.start()
        self.addCleanup(self.clean)

    def clean(self):
        for capture in list(self.service.captures.values()): self.service.cancel(self.db, capture.token)
        for p in reversed(self.patches): p.stop()
        self.storage.close()
        self.tmp.cleanup()

    def paper(self, key='first', doi='10.1234/first', title='A quantum sensing paper', **kwargs):
        p = dict(paper_id=key, title=title, doi=doi, journal='Fixture Journal', publication_date='2026-01-01', source='fixture', section_allowed=True, raw={}, **kwargs)
        self.storage.upsert_paper(p)
        return self.storage.get_paper(key)

    def begin(self, doi='10.1234/first', **kwargs):
        return self.service.begin(self.db, dict(url='https://example.org/article', metadata={'doi':doi,'title':'A quantum sensing paper'}, **kwargs))

    def review(self, capture, **kwargs):
        return self.service.review(capture, self.storage, kwargs)

    def save(self, capture, **kwargs):
        return self.service.save(capture, self.storage, dict(folder_id=1, **kwargs))

    def pdf(self, title='Synthetic PDF'):
        writer = PdfWriter(); writer.add_blank_page(width=200, height=200); writer.add_metadata({'/Title':title})
        stream = io.BytesIO(); writer.write(stream); return stream.getvalue()

    def upload(self, capture, found=None, title='A quantum sensing paper', content=None, source_url=''):
        with patch.object(ui, 'extract_identifier_from_pdf_or_title', return_value=found or {}), patch.object(ui, 'pdf_layout_title_candidates', return_value=[title]):
            self.service.upload(capture, content or self.pdf(title), source_url=source_url)

    def remote_capture(self, pdf_url, doi='10.1234/first'):
        capture = self.service.begin(self.db, {
            'url':'https://www.nature.com/articles/capture-fixture',
            'metadata':{'doi':doi,'title':'A quantum sensing paper'},
            'pdf_urls':[pdf_url],
        })
        self.upload(capture, source_url=pdf_url)
        return capture

    def count(self, table):
        return self.storage.conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]

    def test_review_cancel_never_creates_papers_placements_or_resources(self):
        capture = self.begin()
        review = self.review(capture)
        self.assertTrue(review['can_save'])
        for table in ('papers','library_items','resources'): self.assertEqual(self.count(table), 0)
        path = capture.path.parent
        self.service.cancel(self.db, capture.token)
        self.assertFalse(path.exists())
        self.assertEqual(self.count('papers'), 0)

    def test_new_article_key_and_nested_library_placement_are_persisted_only_on_save(self):
        folder = self.storage.ensure_library_folder(parent_id=1, name='Reading')
        capture = self.begin()
        review = self.review(capture)
        result = self.service.save(capture, self.storage, {'folder_id':folder['id']})
        self.assertTrue(result['ok'])
        self.assertEqual(result['gewu_key'], review['paper']['gewu_key'])
        self.assertEqual(result['folder_id'], folder['id'])
        self.assertEqual(self.count('papers'), 1)
        self.assertEqual(self.count('library_items'), 1)
        self.assertEqual(self.save(capture), result, 'Retry is idempotent even after a lost response')

    def test_existing_monitor_record_retains_key_and_bibliography(self):
        before = self.paper()
        capture = self.begin()
        self.assertTrue(self.review(capture)['paper']['existing'])
        result = self.save(capture)
        self.assertEqual(result['paper_id'], 'first')
        self.assertEqual(result['gewu_key'], before['storage_key'])
        self.assertEqual(self.count('papers'), 1)
        self.assertEqual(self.storage.get_paper('first')['title'], before['title'])
        self.assertEqual(self.storage.get_paper('first')['doi'], before['doi'])

    def test_open_website_origin_is_a_hint_not_automatic_attachment(self):
        origin = self.paper(url='https://example.org/source')
        capture = self.begin(doi='', origin_url=origin['url'])
        review = self.review(capture)
        self.assertIsNone(review['paper'])
        self.assertEqual(review['origin']['gewu_key'], origin['storage_key'])
        self.assertEqual(self.review(capture, use_origin=True)['paper']['paper_id'], 'first')
        other = self.begin(doi='10.1234/second', origin_paper_id='first')
        self.assertNotEqual(self.review(other, use_origin=True)['paper']['paper_id'], 'first')

    def test_pdf_page_mismatch_and_wrong_manual_identifier_block_save(self):
        self.paper()
        capture = self.begin()
        self.upload(capture, {'kind':'doi','identifier':'10.1234/other'})
        self.assertFalse(self.review(capture)['can_save'])
        with self.assertRaises(ValueError): self.save(capture, include_pdf=True)
        capture = self.begin()
        self.assertFalse(self.review(capture, identifier='10.1234/wrong')['can_save'])
        self.assertEqual(self.count('library_items'), 0)

    def test_manual_title_is_explicit_and_reuses_an_existing_exact_match(self):
        self.paper(doi='')
        capture = self.begin(doi='')
        self.assertFalse(self.review(capture)['can_save'])
        review = self.review(capture, manual=True, title='A quantum sensing paper')
        self.assertEqual(review['paper']['paper_id'], 'first')
        other = self.begin(doi='')
        review = self.review(other, manual=True, title='Another new work')
        self.assertFalse(review['paper']['existing'])
        self.assertTrue(self.save(other)['ok'])
        self.assertEqual(self.count('papers'), 2)

    def test_invalid_pdf_upload_cannot_create_file_or_article(self):
        capture = self.begin()
        with self.assertRaisesRegex(ValueError, 'readable PDF'): self.service.upload(capture, b'<html>Login</html>')
        self.assertFalse(capture.pdf_ready)
        self.assertFalse(capture.path.exists())
        self.review(capture)
        with self.assertRaises(ValueError): self.save(capture, include_pdf=True)
        self.assertEqual(self.count('papers'), 0)

    def test_pdf_metadata_title_takes_precedence_over_doi_heading(self):
        title = 'Altermagnetism in twisted van der Waals homostructures'
        self.paper(title=title)
        capture = self.begin(is_pdf=True)
        with patch.object(ui, 'extract_identifier_from_pdf_or_title', return_value={'kind':'doi','identifier':'10.1234/first'}), patch.object(ui, 'pdf_layout_title_candidates', return_value=['Https://doi.org/10.1234/first', 'Altermagnetism in twisted van der Waals']):
            self.service.upload(capture, self.pdf(title))
        self.assertEqual(capture.pdf_title, title)
        review = self.review(capture)
        self.assertEqual(review['warning'], '')
        self.assertTrue(review['can_save'])

    def test_pdf_layout_skips_url_when_metadata_title_is_unusable(self):
        capture = self.begin(is_pdf=True)
        title = 'A quantum sensing paper'
        with patch.object(ui, 'extract_identifier_from_pdf_or_title', return_value={}), patch.object(ui, 'pdf_layout_title_candidates', return_value=['Https://doi.org/10.1234/first', title]):
            self.service.upload(capture, self.pdf('untitled'))
        self.assertEqual(capture.pdf_title, title)

    def test_pdf_is_managed_deduplicated_and_manual_default_is_sticky(self):
        self.paper()
        capture = self.begin()
        content = self.pdf()
        self.upload(capture, content=content); self.review(capture)
        first = self.save(capture, include_pdf=True, file_type='preprint')
        self.assertTrue(first['pdf_saved'])
        resources = self.storage.list_paper_resources('first')
        self.assertEqual(len(resources), 1)
        resource = resources[0]
        self.assertEqual(resource['file_source'], 'user_import')
        self.assertFalse(resource['source_detail'])
        self.assertFalse(resource['source_url'])
        self.assertTrue(Path(resource['stored_path']).resolve().is_relative_to(self.root.resolve()), resource['stored_path'])
        self.assertEqual(Path(resource['stored_path']).read_bytes(), content)
        self.storage.conn.execute('UPDATE papers SET preferred_resource_id=?,preferred_resource_manual=1 WHERE paper_id=?', (resource['id'],'first'))
        self.storage.conn.commit()
        for title, expected_duplicate in [('Synthetic PDF',True), ('Different version',False)]:
            another = self.begin(); self.upload(another, content=self.pdf(title)); self.review(another)
            result = self.save(another, include_pdf=True, file_type='published_version')
            self.assertEqual(result['duplicate_file'], expected_duplicate)
            self.assertEqual(self.storage.get_paper('first')['preferred_resource_id'], resource['id'])
        self.assertEqual(len(self.storage.list_paper_resources('first')), 2)
        self.assertEqual(self.count('library_items'), 1)

    def test_attachment_failure_reports_partial_state_and_retry_reuses_record(self):
        capture = self.begin(); self.upload(capture); self.review(capture)
        with patch.object(ui, 'attach_file_to_paper', side_effect=OSError('disk full')):
            result = self.save(capture, include_pdf=True)
        self.assertFalse(result['ok']); self.assertTrue(result['metadata_saved'])
        self.assertEqual(self.count('papers'), 1)
        result = self.save(capture, include_pdf=True)
        self.assertTrue(result['ok']); self.assertTrue(result['pdf_saved'])
        self.assertEqual(self.count('papers'), 1)
        self.assertEqual(self.count('library_items'), 1)

    def test_known_arxiv_alias_reuses_canonical_published_key(self):
        self.storage.upsert_paper(dict(paper_id='published',doi='10.1234/pub',title='Published work',journal='',source='fixture',raw={'preprint':{'arxiv_id':'2601.01234'}}))
        capture = self.begin(doi='arxiv:2601.01234v2')
        self.assertEqual(self.review(capture)['paper']['paper_id'], 'published')
        self.assertEqual(self.save(capture)['paper_id'], 'published')

    def test_pdf_url_suffix_does_not_override_embedded_identifier(self):
        self.paper()
        capture = self.service.begin(self.db, {'url':'https://example.org/doi/pdf/10.1234/first.pdf','is_pdf':True})
        self.upload(capture, {'kind':'doi','identifier':'10.1234/first'})
        self.assertTrue(self.review(capture)['can_save'])
        self.assertEqual(self.save(capture)['paper_id'], 'first')

    def publisher_capture(self, *, content=None, source=True):
        doi = '10.1038/s41567-026-03429-7'
        url = 'https://www.nature.com/articles/s41567-026-03429-7.pdf'
        capture = self.service.begin(self.db, {'url':url, 'is_pdf':True})
        with patch.object(ui, 'extract_identifier_from_pdf_or_title', return_value={'kind':'doi','identifier':doi}):
            self.service.upload(capture, content or self.pdf('A quantum sensing paper'), 'article.pdf', source_url=url if source else '')
        return capture

    def test_publisher_main_pdf_gets_default_main_path_icon_and_preview_payload(self):
        paper = self.paper(doi='10.1038/s41567-026-03429-7')
        capture = self.publisher_capture()
        self.assertEqual(self.review(capture)['suggested_file_type'], 'published_version')
        result = self.save(capture, include_pdf=True)
        self.assertTrue(result['ok'])
        self.assertEqual(result['gewu_key'], paper['storage_key'])
        payload = ui.paper_files_state_payload(self.storage, 'first')
        file = payload['files'][0]
        self.assertEqual(file['file_type'], 'published_version')
        self.assertEqual(file['file_source'], 'publisher')
        self.assertEqual(file['source_detail'], 'www.nature.com')
        self.assertEqual(file['source_url'], capture.pdf_source_url)
        self.assertTrue(file['is_default']); self.assertTrue(file['is_primary'])
        path = Path(file['local_path'])
        self.assertTrue(path.resolve().is_relative_to(ui.LIBRARY_LOCAL_COPY_ROOT.resolve()), str(path))
        self.assertEqual(payload['paper']['main_pdf_path'], str(path))
        self.assertEqual(payload['paper']['merged_pdf_path'], str(path))
        self.assertEqual(path.read_bytes(), capture.path.read_bytes())

    def test_resave_repairs_only_unclassified_browser_copy_without_duplicates(self):
        self.paper(doi='10.1038/s41567-026-03429-7')
        old = self.publisher_capture(); self.review(old)
        before = self.save(old, include_pdf=True, file_type='unknown')
        resource = self.storage.list_paper_resources('first')[0]
        old_path = Path(resource['stored_path'])
        self.assertTrue(old_path.is_relative_to(ui.ASSOCIATED_FILES_ROOT))
        again = self.publisher_capture(); self.review(again)
        after = self.save(again, include_pdf=True)
        self.assertTrue(after['duplicate_file'])
        self.assertEqual(before['gewu_key'], after['gewu_key'])
        self.assertEqual(before['item_id'], after['item_id'])
        files = self.storage.list_paper_resources('first')
        self.assertEqual(len(files), 1); self.assertEqual(files[0]['id'], resource['id'])
        self.assertEqual(files[0]['sha256'], resource['sha256'])
        self.assertTrue(files[0]['is_primary']); self.assertTrue(files[0]['is_default'])
        self.assertFalse(old_path.exists())

    def test_manual_unknown_and_existing_manual_default_are_preserved(self):
        self.paper(doi='10.1038/s41567-026-03429-7')
        capture = self.publisher_capture(); self.review(capture)
        self.save(capture, include_pdf=True, file_type='unknown', file_type_manual=True)
        first = self.storage.list_paper_resources('first')[0]
        self.assertTrue(first['file_type_override'])
        again = self.publisher_capture(); self.review(again); self.save(again, include_pdf=True)
        self.assertEqual(self.storage.get_paper_resource(first['id'])['file_type'], 'unknown')
        self.assertFalse(self.storage.get_paper('first')['main_pdf_path'])
        self.storage.set_preferred_paper_resource('first', first['id'])
        newer = self.publisher_capture(content=self.pdf('Another version of the quantum sensing paper'))
        self.review(newer); self.save(newer, include_pdf=True)
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], first['id'])

    def test_supplement_and_correction_are_not_promoted_to_main(self):
        self.paper(doi='10.1038/s41567-026-03429-7')
        for title, expected in [('Supplementary information for a quantum sensing paper','supplementary_material'),
                                ('Peer review file for a quantum sensing paper','peer_review_file'),
                                ('Author Correction: A quantum sensing paper','correction_notice')]:
            with self.subTest(title=title):
                capture = self.publisher_capture(content=self.pdf(title))
                self.assertEqual(self.review(capture)['suggested_file_type'], expected)
                self.assertTrue(self.save(capture, include_pdf=True)['ok'])
        self.assertFalse(self.storage.get_paper('first')['main_pdf_path'])
        self.assertIsNone(self.storage.resolve_default_paper_resource('first'))
        self.assertTrue(all(Path(r['stored_path']).resolve().is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()) for r in self.storage.list_paper_resources('first')))

    def test_local_pdf_has_no_asserted_publisher_origin_and_unbound_url_is_rejected(self):
        self.paper(doi='10.1038/s41567-026-03429-7')
        capture = self.publisher_capture(source=False)
        self.assertEqual(self.review(capture)['suggested_file_type'], 'unknown')
        with self.assertRaisesRegex(ValueError, 'source is not part'):
            self.service.upload(capture, self.pdf(), source_url='https://www.nature.com/articles/other.pdf')
        self.assertTrue(self.save(capture, include_pdf=True)['ok'])
        resource = self.storage.list_paper_resources('first')[0]
        self.assertEqual(resource['file_source'], 'user_import')
        self.assertFalse(resource['source_detail'])
        self.assertFalse(resource['source_url'])

    def test_remote_file_source_uses_pdf_host_independently_of_page_and_file_type(self):
        cases = [
            ('https://journals.aps.org/prl/pdf/10.1103/fixture', 'publisher'),
            ('https://media.springernature.com/full/springer-static/image/fixture.pdf', 'publisher'),
            ('https://export.arxiv.org/pdf/2601.01234', 'preprint_server'),
            ('https://www.biorxiv.org/content/fixture.full.pdf', 'preprint_server'),
            ('https://www.medrxiv.org/content/fixture.full.pdf', 'preprint_server'),
            ('https://chemrxiv.org/engage/fixture.pdf', 'preprint_server'),
            ('https://assets-eu.researchsquare.com/files/fixture.pdf', 'preprint_server'),
        ]
        for index, (url, expected) in enumerate(cases):
            with self.subTest(url=url):
                key = 'source-' + str(index)
                doi = '10.1234/' + key
                self.paper(key=key, doi=doi)
                capture = self.remote_capture(url, doi)
                self.review(capture)
                result = self.save(capture, include_pdf=True, file_type='preprint', file_type_manual=True)
                self.assertTrue(result['ok'])
                resource = self.storage.list_paper_resources(key)[0]
                self.assertEqual(resource['file_type'], 'preprint')
                self.assertTrue(resource['file_type_override'])
                self.assertEqual(resource['file_source'], expected)
                self.assertEqual(resource['source_detail'], urlsplit(url).hostname)
                self.assertEqual(resource['source_url'], url)
                self.assertEqual(resource['added_via'], 'browser_capture')
                self.assertTrue(resource['is_default'])
                observation = self.storage.conn.execute(
                    "SELECT source_key FROM paper_source_observations WHERE paper_id=? AND source_kind='browser'", (key,)
                ).fetchone()
                self.assertEqual(observation['source_key'], capture.snapshot['url'])

    def test_unverified_remote_sources_are_blocked_even_with_an_edu_host(self):
        for url in ('https://repository.example.edu/paper.pdf', 'https://files.example.net/paper.pdf'):
            with self.subTest(url=url):
                capture = self.service.begin(self.db, {'url':url, 'is_pdf':True})
                self.assertEqual(capture.snapshot['pdf_urls'], [])
                with self.assertRaisesRegex(ValueError, 'source is not verified'):
                    self.service.upload(capture, self.pdf('A quantum sensing paper'), source_url=url)

    def test_signed_pdf_retains_host_but_never_persists_authorization_url(self):
        self.paper()
        capture = self.remote_capture('https://www.nature.com/article.pdf?token=synthetic-secret')
        self.review(capture)
        self.assertTrue(self.save(capture, include_pdf=True)['ok'])
        resource = self.storage.list_paper_resources('first')[0]
        self.assertEqual(resource['file_source'], 'publisher')
        self.assertEqual(resource['source_detail'], 'www.nature.com')
        self.assertFalse(resource['source_url'])
        self.assertNotIn('synthetic-secret', str(resource))

    def test_selecting_local_pdf_after_native_upload_clears_remote_origin(self):
        self.paper()
        capture = self.remote_capture('https://arxiv.org/pdf/2601.01234')
        self.upload(capture)
        self.review(capture)
        self.assertTrue(self.save(capture, include_pdf=True)['ok'])
        resource = self.storage.list_paper_resources('first')[0]
        self.assertEqual(resource['file_source'], 'user_import')
        self.assertFalse(resource['source_detail'])
        self.assertFalse(resource['source_url'])

    def test_duplicate_capture_preserves_original_source_manual_type_and_default(self):
        self.paper()
        first = self.remote_capture('https://arxiv.org/pdf/2601.01234')
        self.review(first); self.save(first, include_pdf=True, file_type='preprint')
        resource = self.storage.list_paper_resources('first')[0]
        edited = ui.update_paper_resource_role(
            self.storage, 'first', resource['id'], 'accepted_manuscript',
            file_source='institutional_repository', source_detail='repository.example.edu')
        self.storage.set_preferred_paper_resource('first', resource['id'])
        for capture in (self.begin(), self.remote_capture('https://www.nature.com/article.pdf')):
            if not capture.pdf_ready:
                self.upload(capture)
            self.review(capture)
            result = self.save(capture, include_pdf=True, file_type='published_version')
            self.assertTrue(result['duplicate_file'])
            after = self.storage.get_paper_resource(resource['id'])
            for field in ('sha256', 'file_type', 'file_type_override', 'file_source', 'source_detail', 'source_url', 'added_via'):
                self.assertEqual(after[field], edited[field], field)
            self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], resource['id'])
            self.assertTrue(self.storage.get_paper('first')['preferred_resource_manual'])
        self.assertEqual(len(self.storage.list_paper_resources('first')), 1)

    def test_remote_duplicate_does_not_assign_a_source_to_an_existing_local_file(self):
        self.paper()
        local = self.begin(); self.upload(local); self.review(local)
        self.save(local, include_pdf=True)
        original = self.storage.list_paper_resources('first')[0]
        remote = self.remote_capture('https://www.nature.com/article.pdf'); self.review(remote)
        result = self.save(remote, include_pdf=True)
        self.assertTrue(result['duplicate_file'])
        after = self.storage.get_paper_resource(original['id'])
        self.assertEqual(after['file_source'], 'user_import')
        self.assertFalse(after['source_detail'])
        self.assertFalse(after['source_url'])

    def test_remote_capture_retry_preserves_source_and_deduplicates_after_placement_failure(self):
        self.paper()
        capture = self.remote_capture('https://www.nature.com/article.pdf'); self.review(capture)
        with patch.object(ui, 'reconcile_paper_pdf_storage', side_effect=OSError('fixture placement failure')):
            result = self.save(capture, include_pdf=True, file_type='published_version')
        self.assertFalse(result['ok']); self.assertTrue(result['metadata_saved'])
        result = self.save(capture, include_pdf=True, file_type='published_version')
        self.assertTrue(result['ok']); self.assertTrue(result['duplicate_file'])
        resources = self.storage.list_paper_resources('first')
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]['file_source'], 'publisher')
        self.assertEqual(resources[0]['source_detail'], 'www.nature.com')
        self.assertEqual(resources[0]['source_url'], capture.pdf_source_url)

    def test_arxiv_pdf_alias_stays_preprint_even_for_a_published_article(self):
        self.storage.upsert_paper(dict(paper_id='first',doi='10.1234/pub',title='Published work',journal='',source='fixture',raw={'preprint':{'arxiv_id':'2601.01234'}}))
        url='https://arxiv.org/pdf/2601.01234v2'
        capture=self.service.begin(self.db,{'url':url,'is_pdf':True})
        with patch.object(ui,'extract_identifier_from_pdf_or_title',return_value={'kind':'arxiv','identifier':'2601.01234'}):
            self.service.upload(capture,self.pdf('Published work'),source_url=url)
        self.assertEqual(self.review(capture)['suggested_file_type'],'preprint')
        self.assertTrue(self.save(capture,include_pdf=True)['ok'])
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['file_type'],'preprint')
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['file_source'],'preprint_server')

    def test_other_preprint_servers_do_not_use_journal_metadata_as_file_type(self):
        cases = [
            ('https://www.biorxiv.org/content/10.1101/2026.01.01.123456v2.full.pdf', '10.1101/2026.01.01.123456'),
            ('https://www.medrxiv.org/content/10.1101/2026.01.02.123456v1.full.pdf', '10.1101/2026.01.02.123456'),
            ('https://chemrxiv.org/engage/api-gateway/chemrxiv/assets/orp/resource/item/fixture/original/paper.pdf', '10.26434/chemrxiv-2026-fixture'),
            ('https://www.researchsquare.com/article/rs-123456/v1.pdf', '10.21203/rs.3.rs-123456/v1'),
            ('https://assets-eu.researchsquare.com/files/rs-123457/v2/fixture.pdf', '10.21203/rs.3.rs-123457/v2'),
        ]
        for index, (url, doi) in enumerate(cases):
            with self.subTest(url=url):
                paper = self.paper(key='preprint-'+str(index), doi=doi)
                capture = self.service.begin(self.db, {'url':url, 'is_pdf':True})
                with patch.object(ui,'extract_identifier_from_pdf_or_title',return_value={'kind':'doi','identifier':doi}):
                    self.service.upload(capture,self.pdf('A quantum sensing paper'),source_url=url)
                review = self.review(capture)
                self.assertTrue(review['paper']['journal'])
                self.assertEqual(review['suggested_file_type'],'preprint')
                result = self.save(capture,include_pdf=True)
                self.assertEqual(result['gewu_key'],paper['storage_key'])
                self.assertEqual(self.storage.resolve_default_paper_resource(paper['paper_id'])['file_type'],'preprint')
                self.assertEqual(self.storage.resolve_default_paper_resource(paper['paper_id'])['file_source'],'preprint_server')

    def test_arxiv_source_classifies_preprint_when_text_identity_is_missing_or_published(self):
        url = 'https://arxiv.org/pdf/2109.15071'
        self.paper(doi='10.1109/tasc.2022.3147730')
        for found in ({}, {'kind':'doi','identifier':'10.1109/tasc.2022.3147730'}):
            with self.subTest(found=found):
                capture = self.service.begin(self.db, {'url':url,'is_pdf':True})
                with patch.object(ui,'extract_identifier_from_pdf_or_title',return_value=found):
                    self.service.upload(capture,self.pdf('A quantum sensing paper'),source_url=url)
                review = self.review(capture,manual=True,title='A quantum sensing paper')
                self.assertEqual(review['suggested_file_type'],'preprint')
                self.assertTrue(self.save(capture,include_pdf=True)['ok'])
        # The same local bytes selected while reading arXiv assert no origin.
        local = self.service.begin(self.db, {'url':url,'is_pdf':True})
        with patch.object(ui,'extract_identifier_from_pdf_or_title',return_value={}):
            self.service.upload(local,self.pdf('A quantum sensing paper'))
        self.assertEqual(self.review(local,manual=True,title='A quantum sensing paper')['suggested_file_type'],'unknown')

    def test_publisher_url_cannot_be_inferred_from_a_lookalike_host_or_preprint_site(self):
        self.paper(doi='10.1038/s41567-026-03429-7')
        for host in ('www.nature.com.example.org','www.biorxiv.org'):
            url='https://'+host+'/articles/s41567-026-03429-7.pdf'
            capture=self.service.begin(self.db,{'url':url,'is_pdf':True})
            if host == 'www.nature.com.example.org':
                with self.assertRaisesRegex(ValueError, 'source is not verified'):
                    self.service.upload(capture,self.pdf('A quantum sensing paper'),source_url=url)
                continue
            with patch.object(ui,'extract_identifier_from_pdf_or_title',return_value={'kind':'doi','identifier':'10.1038/s41567-026-03429-7'}):
                self.service.upload(capture,self.pdf('A quantum sensing paper'),source_url=url)
            self.assertEqual(self.review(capture)['suggested_file_type'],'unknown')

    def test_pdf_and_page_known_arxiv_doi_aliases_are_compatible(self):
        self.storage.upsert_paper(dict(paper_id='published',doi='10.1234/pub',title='Published work',journal='',source='fixture',raw={'preprint':{'arxiv_id':'2601.01234'}}))
        capture = self.begin(doi='10.1234/pub')
        self.upload(capture, {'kind':'arxiv','identifier':'2601.01234'})
        self.assertTrue(self.review(capture)['can_save'])
        self.assertEqual(self.save(capture)['paper_id'], 'published')

    def test_shared_picker_space_destination_is_accepted(self):
        space = self.storage.create_library_root_folder(name='Reading Space')
        child = self.storage.ensure_library_folder(parent_id=space['id'], name='Quantum')
        capture = self.begin()
        review = self.review(capture)
        self.assertIn({'id':child['id'], 'title':'Reading Space / Quantum'}, review['folders'])
        result = self.service.save(capture, self.storage, {'folder_id':child['id']})
        self.assertEqual(result['folder_id'], child['id'])
        self.assertEqual(self.storage.get_library_item(result['item_id'])['folder_id'], child['id'])

    def test_tokens_are_db_scoped_and_expire(self):
        capture = self.begin()
        self.assertIs(self.service.get(self.db, capture.upload_token, upload=True), capture)
        for db, token, upload in [(self.root/'other',capture.token,False),(self.db,capture.token,True),(self.db,'bad',False)]:
            with self.assertRaises(ValueError): self.service.get(db,token,upload=upload)
        capture.touched -= 2000
        with self.assertRaises(ValueError): self.service.get(self.db,capture.token)

    def test_unsafe_urls_and_recycle_destinations_are_rejected(self):
        for url in ('http://127.0.0.1/paper','file:///tmp/paper','https://a:b@example.org/'):
            with self.assertRaises(ValueError): normalize_snapshot({'url':url})
        snapshot = normalize_snapshot({'url':'https://example.org/?token=private', 'origin_url':'https://example.org/?token=private', 'pdf_urls':['http://localhost/private','https://example.org/paper.pdf'], 'snapshot_id':'binding'})
        self.assertEqual(snapshot['pdf_urls'], [])
        self.assertEqual(snapshot['snapshot_id'], 'binding')
        self.assertEqual(snapshot['origin_url'], '')
        folder = self.storage.ensure_library_folder(parent_id=1, name='Recycle')
        child = self.storage.ensure_library_folder(parent_id=folder['id'],name='Discarded')
        capture = self.begin(); self.review(capture)
        with self.assertRaises(ValueError): self.service.save(capture,self.storage,{'folder_id':child['id']})
        self.assertEqual(self.count('papers'),0)

    def test_concurrent_reviews_recheck_canonical_doi_before_save(self):
        capture = self.begin(); self.review(capture)
        existing = self.paper(key='other-ingestion')
        result = self.save(capture)
        self.assertEqual(result['gewu_key'], existing['storage_key'])
        self.assertEqual(self.count('papers'),1)

    def test_signed_capture_url_is_not_persisted(self):
        capture = self.service.begin(self.db, {'url':'https://example.org/?token=synthetic-secret', 'metadata':{'doi':'10.1234/test','title':'Private URL paper'}})
        self.review(capture); result = self.save(capture)
        paper = self.storage.get_paper(result['paper_id'])
        self.assertEqual(paper['url'],''); self.assertEqual(paper['landing_url'],'')
        self.assertNotIn('synthetic-secret',paper['raw_json'])

    def test_identifier_recognizes_doi_and_arxiv_versions(self):
        self.assertEqual(identifier('https://doi.org/10.1234/AB'), ('doi','10.1234/ab'))
        self.assertEqual(identifier('https://arxiv.org/pdf/2601.01234v2.pdf'), ('arxiv','2601.01234'))


class BrowserCaptureApiTests(unittest.TestCase):
    from tests.test_browser import BrowserApiTests as _Base
    setUp = _Base.setUp
    tearDown = _Base.tearDown
    request = _Base.request

    def headers(self):
        return {'Origin':f'http://127.0.0.1:{self.server.server_port}','X-Gewu-Browser':'1','Content-Type':'application/json'}

    def post(self, action, **payload):
        import json
        status, data = self.request('/api/browser',dict(action=action,**payload),self.headers())
        self.assertEqual(status,200,data[:500])
        return json.loads(data)

    def upload(self, data, headers):
        import http.client
        c = http.client.HTTPConnection('127.0.0.1',self.server.server_port)
        c.request('POST','/api/browser-capture-file',data,headers)
        response = c.getresponse(); status=response.status; response.read(); c.close(); return status

    def test_capture_api_review_native_upload_cancel_and_origin_boundary(self):
        review = self.post('capture_begin',snapshot={'url':'https://example.org/paper','metadata':{'doi':'10.1234/api','title':'API article'}})
        self.assertTrue(review['can_save'])
        writer=PdfWriter(); writer.add_blank_page(width=100,height=100); content=io.BytesIO(); writer.write(content)
        headers={'Content-Type':'application/pdf','X-Gewu-Capture-Token':review['upload_token']}
        self.assertEqual(self.upload(content.getvalue(),headers),200)
        self.assertEqual(self.upload(content.getvalue(),{**headers,'Origin':'https://example.org'}),403)
        self.assertEqual(self.upload(content.getvalue(),{**headers,'X-Gewu-Capture-Token':review['token']}),400)
        self.post('capture_cancel',token=review['token'])
        self.assertEqual(self.upload(content.getvalue(),headers),400)

    def test_capture_api_metadata_save_and_repeated_delivery_share_identity(self):
        review=self.post('capture_begin',snapshot={'url':'https://example.org/paper','metadata':{'doi':'10.1234/api','title':'API article'}})
        first=self.post('capture_save',token=review['token'],folder_id=1)
        self.assertEqual(self.post('capture_save',token=review['token'],folder_id=1),first)
        self.post('capture_cancel',token=review['token'])
        review=self.post('capture_begin',snapshot={'url':'https://example.org/paper','metadata':{'doi':'10.1234/api','title':'API article'}})
        self.assertTrue(review['paper']['existing'])
        self.assertEqual(self.post('capture_save',token=review['token'])['gewu_key'],first['gewu_key'])
        self.post('capture_cancel',token=review['token'])

    def test_capture_save_returns_files_for_unknown_pdf_and_duplicate_reuse(self):
        from contextlib import ExitStack
        root = Path(self.temp.name)
        with ExitStack() as stack:
            for name in ('LIBRARY_LOCAL_COPY_ROOT','SPACES_LOCAL_COPY_ROOT','MY_PUBLICATIONS_LOCAL_COPY_ROOT','DEFAULT_PDF_DIR','ASSOCIATED_FILES_ROOT'):
                stack.enter_context(patch.object(ui,name,root/name))
            writer=PdfWriter(); writer.add_blank_page(width=100,height=100)
            writer.add_metadata({'/Title':'API article'})
            content=io.BytesIO(); writer.write(content)
            resource_id = None
            for duplicate in (False,True):
                review=self.post('capture_begin',snapshot={'url':'https://example.org/paper','metadata':{'doi':'10.1234/api','title':'API article'}})
                self.assertEqual(self.upload(content.getvalue(),{'Content-Type':'application/pdf','X-Gewu-Capture-Token':review['upload_token']}),200)
                self.post('capture_review',token=review['token'],resolve=False)
                result=self.post('capture_save',token=review['token'],folder_id=1,include_pdf=True,file_type='unknown')
                self.assertTrue(result['ok']); self.assertTrue(result['pdf_saved'])
                self.assertEqual(result['duplicate_file'],duplicate)
                files=result['paper_files'][0]
                self.assertEqual(files['paper_id'],result['paper_id'])
                self.assertEqual(files['paper']['storage_key'],result['gewu_key'])
                self.assertEqual(len(files['files']),1)
                file=files['files'][0]
                self.assertTrue(file['exists']); self.assertEqual(file['file_type'],'unknown')
                self.assertEqual(Path(file['local_path']).read_bytes(),content.getvalue())
                if resource_id is not None: self.assertEqual(file['id'],resource_id)
                resource_id=file['id']
                self.post('capture_cancel',token=review['token'])

@unittest.skipUnless(sys.platform == "darwin", "Requires macOS Cocoa/WebKit and xcrun")
class BrowserCaptureNativeTests(unittest.TestCase):
    def test_native_capture_lifecycle(self):
        import shutil
        import subprocess
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            bundle=Path(directory)/'Capture.app'/'Contents'
            (bundle/'MacOS').mkdir(parents=True); (bundle/'Resources').mkdir()
            shutil.copy(root/'scripts/GewuBrowserCaptureProbe.js',bundle/'Resources')
            executable=bundle/'MacOS'/'Capture'
            command=['xcrun','clang','-fobjc-arc','-mmacosx-version-min=14.0','-I',str(root/'scripts'),'-framework','Cocoa','-framework','WebKit','-framework','UniformTypeIdentifiers',str(root/'tests/browser_capture_native_probe.m'),*[str(root/'scripts'/name) for name in ('GewuBrowserAutoFill.m','GewuBrowserFavicons.m','GewuBrowserCapture.m')],'-o',str(executable)]
            compiled=subprocess.run(command,capture_output=True,text=True,timeout=60)
            self.assertEqual(compiled.returncode,0,compiled.stderr[-5000:])
            run=subprocess.run([str(executable)],capture_output=True,text=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)

if __name__ == '__main__': unittest.main()
