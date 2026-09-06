"""Capture-to-Library behavior with temporary SQLite/files and synthetic PDFs."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def upload(self, capture, found=None, title='A quantum sensing paper', content=None):
        with patch.object(ui, 'extract_identifier_from_pdf_or_title', return_value=found or {}), patch.object(ui, 'pdf_layout_title_candidates', return_value=[title]):
            self.service.upload(capture, content or self.pdf(title))

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
        self.assertEqual(snapshot['pdf_urls'], ['https://example.org/paper.pdf'])
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
