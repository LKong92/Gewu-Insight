"""Capture-to-Library behavior with temporary SQLite/files and synthetic PDFs."""
import io
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from pypdf import PdfWriter
from paper_monitor import ui_server as ui
from paper_monitor.browser_capture import BrowserCaptureService, identifier, normalize_snapshot
from paper_monitor.storage import Storage


class BrowserCaptureImportCompatibilityTests(unittest.TestCase):
    def test_lazy_capture_import_with_pre_update_science_module_keeps_identifier_review(self):
        # Use a fresh interpreter: this test module otherwise imports capture
        # during collection, hiding the lazy-import failure seen in an open App.
        probe = textwrap.dedent('''
            import sys
            import tempfile
            from pathlib import Path
            from unittest.mock import patch
            from paper_monitor import ui_server, science_pdf
            from paper_monitor.storage import Storage

            for name in ('is_science_first_release_text', 'is_science_first_release_pdf'):
                delattr(science_pdf, name)
            sys.modules.pop('paper_monitor.science_version', None)
            assert 'paper_monitor.browser_capture' not in sys.modules
            from paper_monitor.browser_capture import BrowserCaptureService
            from paper_monitor.science_version import is_science_first_release_text
            assert is_science_first_release_text(
                'First release: 17 September 2026 science.org '
                '(Page numbers not final at time of first release) 1')

            service = BrowserCaptureService()
            with tempfile.TemporaryDirectory() as folder:
                db = Path(folder) / 'capture.sqlite'
                storage = Storage(db)
                try:
                    for kind, value, url in [
                        ('arxiv', '2609.24843', 'https://arxiv.org/pdf/2609.24843'),
                        ('doi', '10.1126/science.fixture', 'https://www.science.org/doi/10.1126/science.fixture'),
                    ]:
                        capture = service.begin(db, {'url': url})
                        first = service.review(capture, storage, {'resolve': False})
                        assert first['identifier'] == value
                        candidate = {'paper_id': kind + '-fixture', 'title': 'Synthetic article',
                                     'doi': value if kind == 'doi' else '',
                                     'raw': {'arxiv_id': value} if kind == 'arxiv' else {}}
                        with patch.object(service, 'resolve', return_value=candidate) as resolver:
                            reviewed = service.review(capture, storage, {})
                            resolver.assert_called_once_with(kind, value)
                        assert reviewed['can_save'] and reviewed['identifier'] == value
                        assert reviewed['paper']['title'] == 'Synthetic article'
                        service.cancel(db, capture.token)
                    for table in ('papers', 'resources', 'library_items'):
                        assert storage.conn.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] == 0
                finally:
                    storage.close()
        ''')
        result = subprocess.run([sys.executable, '-c', probe], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


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

    def test_uploaded_original_is_parsed_once_and_metadata_is_recomputed(self):
        from paper_monitor import pdf_utils
        first = self.begin()
        second = self.begin()
        for capture, title in ((first, 'First original document'), (second, 'Second original document')):
            content = self.pdf(title)
            with patch.object(pdf_utils, 'PdfReader', wraps=pdf_utils.PdfReader) as parse, patch.object(ui, 'PdfReader', side_effect=AssertionError('reparsed PDF')):
                self.service.upload(capture, content)
            self.assertEqual(parse.call_count, 1)
            self.assertEqual(capture.pdf_metadata_title, title)
            self.assertEqual(capture.path.read_bytes(), content)
        self.assertNotEqual(first.pdf_metadata_title, second.pdf_metadata_title)

    def test_reused_reader_preserves_identifier_and_first_page_title(self):
        from reportlab.pdfgen import canvas
        from paper_monitor.pdf_utils import validated_pdf_reader
        content = io.BytesIO()
        writer = canvas.Canvas(content)
        writer.setTitle('Quantum sensing using synthetic photons')
        writer.setFont('Helvetica-Bold', 18)
        writer.drawString(72, 740, 'Quantum sensing using synthetic photons')
        writer.setFont('Helvetica', 12)
        writer.drawString(72, 700, 'doi: 10.1234/fixture')
        writer.showPage()
        writer.setFont('Helvetica-Bold', 30)
        writer.drawString(72, 740, 'Supplementary document for another study')
        writer.save()
        path = self.root / 'evidence.pdf'
        path.write_bytes(content.getvalue())
        expected = ui.extract_identifier_from_pdf_or_title(path, {}, title_lookup=lambda _: {})
        first_page = {}
        reader = validated_pdf_reader(content.getvalue())
        titles = ui.pdf_layout_title_candidates(path, reader=reader, first_page_result=first_page)
        metadata, texts = ui.pdf_identifier_page_texts(path, reader=reader)
        self.assertEqual(ui.extract_identifier_from_pdf_or_title(path, {}, title_lookup=lambda _: {}, pdf_evidence=(metadata, texts, titles)), expected)
        self.assertEqual(expected['identifier'], '10.1234/fixture')
        self.assertEqual(first_page['titles'], ui.pdf_layout_title_candidates(path, page_limit=1))

    def test_science_first_release_uses_full_first_page_and_resets_on_reupload(self):
        from tests.test_science_download_integrity import FIRST_RELEASE, pdf_bytes
        doi = '10.1126/science.fixture'
        url = 'https://www.science.org/doi/pdf/' + doi
        capture = self.begin(doi=doi, pdf_urls=[url])
        found = {'kind': 'doi', 'identifier': doi}
        # The footer is beyond the short heading used by the capture card.
        self.upload(capture, found=found, content=pdf_bytes('Research article. ' * 40 + FIRST_RELEASE), source_url=url)
        self.assertNotIn('First release', capture.pdf_heading)
        capture.paper = {'doi': doi}
        self.assertEqual(self.service.suggested_file_type(capture)[0], 'accepted_manuscript')
        capture.paper = {'doi': '10.1126/science.other'}
        self.assertEqual(self.service.suggested_file_type(capture)[0], 'unknown')
        self.upload(capture, found=found, content=pdf_bytes('Final published article'), source_url=url)
        capture.paper = {'doi': doi}
        self.assertEqual(self.service.suggested_file_type(capture)[0], 'published_version')

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
        result = self.service.save(capture, self.storage, {'folder_id':folder['id'], 'folder_selection_explicit':True})
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
        self.assertEqual(self.storage.get_library_folder(result['folder_id'])['name'], 'unsorted')

    def test_custom_default_is_shared_but_existing_placement_and_explicit_choice_win(self):
        from paper_monitor.library_destination import save_default_add_folder
        inbox = self.storage.create_library_folder(parent_id=1, name='Inbox')
        space = self.storage.create_library_root_folder(name='Reading Space')
        save_default_add_folder(self.storage, inbox['id'])
        capture = self.begin()
        before = self.count('library_items')
        self.assertEqual(self.review(capture)['destination']['folder_id'], inbox['id'])
        self.assertEqual(self.count('library_items'), before)
        # Preference changes between Review and Save are resolved on Save.
        save_default_add_folder(self.storage, space['id'])
        saved = self.save(capture)
        self.assertEqual(saved['folder_id'], space['id'])
        save_default_add_folder(self.storage, inbox['id'])
        again = self.begin()
        self.upload(again)
        self.assertEqual(self.review(again)['destination']['folder_id'], space['id'])
        retained = self.save(again, include_pdf=True)
        self.assertEqual(retained['item_id'], saved['item_id'])
        self.assertEqual(retained['gewu_key'], saved['gewu_key'])
        self.assertEqual(self.count('library_items'), 1)
        explicit = self.begin()
        self.review(explicit)
        result = self.service.save(explicit, self.storage, {'folder_id':inbox['id'], 'folder_selection_explicit':True})
        self.assertEqual(result['folder_id'], inbox['id'])
        self.assertEqual(self.count('library_items'), 2)

    def test_custom_default_in_recycled_parent_falls_back_without_review_writes(self):
        from paper_monitor.library_destination import save_default_add_folder
        parent = self.storage.create_library_folder(parent_id=1, name='Reading')
        inbox = self.storage.create_library_folder(parent_id=parent['id'], name='Inbox')
        save_default_add_folder(self.storage, inbox['id'])
        capture = self.begin()
        self.assertEqual(self.review(capture)['destination']['folder_id'], inbox['id'])
        recycle = self.storage.ensure_library_folder(parent_id=1, name='Recycle')
        self.storage.move_library_folder_to_trash(folder_id=parent['id'], recycle_folder_id=recycle['id'])
        changes = self.storage.conn.total_changes
        destination = self.service.destination(capture, self.storage, '', self.service.folders(self.storage))
        self.assertEqual(destination['title'], 'Library / unsorted')
        self.assertEqual(self.storage.conn.total_changes, changes)
        result = self.save(capture)
        self.assertEqual(self.storage.get_library_folder(result['folder_id'])['name'], 'unsorted')

    def test_new_article_defaults_to_unsorted_without_writing_during_review(self):
        capture = self.begin()
        before = self.count('library_folders')
        review = self.review(capture)
        self.assertEqual(self.count('library_folders'), before)
        self.assertEqual(review['destination']['title'], 'Library / unsorted')
        result = self.save(capture)
        self.assertEqual(self.storage.get_library_folder(result['folder_id'])['name'], 'unsorted')
        self.assertEqual(self.storage.get_library_folder(result['folder_id'])['parent_id'], 1)
        self.assertEqual(self.count('library_items'), 1)

    def test_existing_nested_article_pdf_reuses_placement_on_save_and_retry(self):
        before = self.paper()
        unsorted = self.storage.ensure_library_folder(parent_id=1, name='unsorted')
        folder = self.storage.ensure_library_folder(parent_id=unsorted['id'], name='New Folder')
        item = self.storage.add_library_item(paper_id='first', folder_id=folder['id'])
        self.storage.rename_library_item(item_id=item['id'], name='My existing name')
        placements = [tuple(row) for row in self.storage.conn.execute('SELECT * FROM library_items')]
        for retry in (False, True):
            capture = self.begin()
            self.upload(capture)
            review = self.review(capture)
            self.assertEqual(review['destination']['item_id'], item['id'])
            result = self.save(capture, include_pdf=True)
            self.assertTrue(result['ok'])
            self.assertEqual(result['duplicate_file'], retry)
            self.assertEqual(result['folder_id'], folder['id'])
            self.assertEqual(result['item_id'], item['id'])
            self.assertEqual(result['gewu_key'], before['storage_key'])
            self.assertEqual([tuple(row) for row in self.storage.conn.execute('SELECT * FROM library_items')], placements)
        self.assertEqual(len(self.storage.list_paper_resources('first')), 1)

    def test_existing_placement_preference_is_scoped_to_the_identified_paper(self):
        self.paper()
        first_folder = self.storage.ensure_library_folder(parent_id=1, name='First')
        second_folder = self.storage.create_library_root_folder(name='Space')
        first = self.storage.add_library_item(paper_id='first', folder_id=first_folder['id'])
        second = self.storage.add_library_item(paper_id='first', folder_id=second_folder['id'])
        self.paper(key='other', doi='10.1234/other', title='Different paper')
        unrelated = self.storage.add_library_item(paper_id='other', folder_id=1)
        for preferred, expected in [(second['id'], second), (unrelated['id'], first), (999999, first)]:
            capture = self.begin(origin_library_item_id=preferred)
            self.assertEqual(self.review(capture)['destination']['item_id'], expected['id'])
            result = self.save(capture)
            self.assertEqual(result['item_id'], expected['id'])
        self.assertEqual(self.count('library_items'), 3)

    def test_only_confirmed_destination_adds_another_existing_article_placement(self):
        self.paper()
        folder = self.storage.ensure_library_folder(parent_id=1, name='Reading')
        item = self.storage.add_library_item(paper_id='first', folder_id=folder['id'])
        capture = self.begin(); self.review(capture)
        result = self.save(capture, folder_selection_explicit=True)
        self.assertEqual(result['folder_id'], 1)
        self.assertNotEqual(result['item_id'], item['id'])
        self.assertEqual(self.count('library_items'), 2)

    def test_recycle_placement_is_not_reused_and_stale_reviews_recheck_locations(self):
        self.paper()
        recycle = self.storage.ensure_library_folder(parent_id=1, name='Recycle')
        child = self.storage.ensure_library_folder(parent_id=recycle['id'], name='Discarded')
        self.storage.add_library_item(paper_id='first', folder_id=child['id'])
        capture = self.begin()
        self.assertFalse(self.review(capture)['destination']['reused'])
        folder = self.storage.ensure_library_folder(parent_id=1, name='Added while reviewing')
        item = self.storage.add_library_item(paper_id='first', folder_id=folder['id'])
        result = self.save(capture)
        self.assertEqual(result['item_id'], item['id'])
        self.assertEqual(result['folder_id'], folder['id'])
        self.assertEqual(self.count('library_items'), 2)

    def test_reviewed_placement_removed_before_save_is_not_a_dangling_target(self):
        self.paper()
        folder = self.storage.ensure_library_folder(parent_id=1, name='Reading')
        item = self.storage.add_library_item(paper_id='first', folder_id=folder['id'])
        capture = self.begin(); self.review(capture)
        self.storage.delete_library_item(item_id=item['id'])
        result = self.save(capture)
        self.assertTrue(result['ok'])
        self.assertEqual(self.storage.get_library_folder(result['folder_id'])['name'], 'unsorted')
        self.assertEqual(self.count('library_items'), 1)

    def test_open_website_origin_reuses_source_unless_page_identifies_another_article(self):
        origin = self.paper(url='https://example.org/source')
        capture = self.begin(doi='', origin_url=origin['url'])
        review = self.review(capture)
        self.assertEqual(review['paper']['paper_id'], 'first')
        self.assertTrue(review['paper']['existing'])
        self.assertEqual(review['origin']['gewu_key'], origin['storage_key'])
        self.assertEqual(self.review(capture, use_origin=True)['paper']['paper_id'], 'first')
        other = self.begin(doi='10.1234/second', origin_paper_id='first')
        self.assertNotEqual(self.review(other, use_origin=True)['paper']['paper_id'], 'first')

    def corrected_paper(self):
        paper = self.paper(doi='10.1109/iccv51701.2025.00828')
        self.storage.conn.execute('UPDATE papers SET raw_json=? WHERE paper_id=?',
            ('{"arxiv_id":"2025.00828","manual_preprint_identifier_override":true,"manual_preprint_identifier":"2503.19940"}', paper['paper_id']))
        self.storage.conn.commit()
        from paper_monitor import paper_identity
        paper = self.storage.get_paper(paper['paper_id'])
        paper_identity.register(self.storage, paper); self.storage.conn.commit()
        return paper

    def test_manual_arxiv_correction_reused_in_review_save_and_pdf_identity(self):
        paper = self.corrected_paper()
        folder = self.storage.ensure_library_folder(parent_id=1, name='AI')
        item = self.storage.add_library_item(paper_id=paper['paper_id'], folder_id=folder['id'])
        capture = self.service.begin(self.db, {'url':'https://arxiv.org/pdf/2503.19940v2','is_pdf':True})
        self.upload(capture, {'kind':'arxiv','identifier':'2503.19940'}, source_url=capture.snapshot['url'])
        review = self.review(capture)
        self.assertEqual(review['paper']['gewu_key'], paper['storage_key'])
        self.assertTrue(review['paper']['existing'])
        self.assertEqual(review['destination']['item_id'], item['id'])
        self.assertTrue(self.service.same_identity(self.storage, ('doi',paper['doi']), ('arxiv','2503.19940')))
        self.assertIsNone(self.service.existing(self.storage, 'arxiv','2025.00828'))
        result = self.save(capture, include_pdf=True)
        self.assertEqual(result['gewu_key'], paper['storage_key']); self.assertEqual(self.count('papers'), 1)
        self.assertEqual(result['folder_id'], folder['id'])
        file = self.storage.list_paper_resources(paper['paper_id'])[0]
        self.assertEqual(file['file_type'],'preprint')

    def test_cleared_arxiv_cannot_match_stale_source_or_old_paper_id(self):
        paper = self.corrected_paper()
        self.storage.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id=?", ('{"arxiv_id":"2503.19940","manual_preprint_identifier_override":true,"manual_preprint_identifier":""}', paper['paper_id']))
        self.storage.conn.commit()
        self.assertIsNone(self.service.existing(self.storage,'arxiv','2503.19940'))

    def test_manual_target_key_moves_review_to_existing_location_without_metadata_edits(self):
        target = self.paper(key='target',doi='10.1234/correct',title='A different target article')
        folder = self.storage.ensure_library_folder(parent_id=1,name='Target folder')
        self.storage.add_library_item(paper_id=target['paper_id'],folder_id=folder['id'])
        capture = self.begin()
        review = self.review(capture,target_key=target['storage_key'])
        self.assertTrue(review['target_conflict']); self.assertFalse(review['can_save'])
        self.assertEqual(review['destination']['folder_id'],folder['id'])
        with self.assertRaises(ValueError): self.save(capture)
        self.review(capture,target_key=target['storage_key'],confirm_target=True)
        before = self.storage.get_paper('target')
        result = self.save(capture)
        self.assertEqual(result['gewu_key'], target['storage_key'])
        after = self.storage.get_paper('target')
        for field in ('title','doi','storage_key','preferred_resource_id','preferred_resource_manual'):
            self.assertEqual(before.get(field),after.get(field),field)
        import json
        old_raw,new_raw=json.loads(before['raw_json']),json.loads(after['raw_json'])
        old_raw.pop('_paper_monitor_sources',None);new_raw.pop('_paper_monitor_sources',None)
        self.assertEqual(old_raw,new_raw)
        self.assertEqual(self.count('papers'),1)

    def test_invalid_key_revokes_previous_review_and_does_not_create_record(self):
        target = self.paper()
        capture = self.begin()
        self.review(capture)
        for key in ('gw_0000000000','bad key'):
            with self.assertRaises(ValueError): self.review(capture,target_key=key)
            with self.assertRaises(ValueError): self.save(capture)
        self.assertEqual(self.count('papers'),1)
        self.assertEqual(self.review(capture)['paper']['gewu_key'],target['storage_key'])

    def test_manual_key_alias_resolves_to_current_key(self):
        from paper_monitor import paper_identity
        target = self.paper()
        paper_identity.add_alias(self.storage, 'gw_abcdef0123', target['paper_id'])
        self.storage.conn.commit()
        capture = self.begin()
        review = self.review(capture, target_key='gw_abcdef0123')
        self.assertEqual(review['target_key'], target['storage_key'])
        self.assertTrue(review['can_save'])
        self.assertEqual(self.save(capture)['gewu_key'], target['storage_key'])

    def test_embedded_ieee_pdf_resolves_identity_and_published_type(self):
        target = self.corrected_paper()
        url = 'https://ieeexplore.ieee.org/stamppdf/getPDF.jsp?arnumber=11443405'
        capture = self.service.begin(self.db, {'url':'https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=11443405',
            'pdf_urls':[url], 'loaded_pdf_urls':[url], 'metadata':{}})
        self.assertIsNone(self.review(capture)['paper'])
        self.upload(capture, {'kind':'doi','identifier':target['doi']}, source_url=url)
        review = self.review(capture)
        self.assertEqual(review['paper']['gewu_key'], target['storage_key'])
        self.assertEqual(review['suggested_file_type'], 'published_version')
        self.assertTrue(review['can_save'])

    def test_target_identifier_changed_after_review_requires_fresh_review(self):
        target = self.paper()
        capture = self.begin(); self.review(capture)
        self.storage.conn.execute('UPDATE papers SET doi=? WHERE paper_id=?',('10.1234/new',target['paper_id']))
        self.storage.conn.commit()
        with self.assertRaisesRegex(ValueError,'identifiers changed'): self.save(capture)

    def test_arxiv_parser_rejects_publisher_doi_suffixes_and_arbitrary_urls(self):
        from paper_monitor.text import normalize_arxiv_identifier
        for value in ('10.1109/iccv51701.2025.00828','https://doi.org/10.1109/x.2025.00828','https://publisher.org/2503.19940','2025.00828','https://publisher.org/doi/10.1234/2503.19940'):
            self.assertEqual(normalize_arxiv_identifier(value),'',value)
        for value in ('2503.19940v2','arXiv:2503.19940','https://arxiv.org/pdf/2503.19940v2','https://doi.org/10.48550/arXiv.2503.19940'):
            self.assertEqual(normalize_arxiv_identifier(value),'2503.19940')
        self.assertEqual(normalize_arxiv_identifier('https://arxiv.org/abs/cond-mat/0101234v2'),'cond-mat/0101234')
        self.assertEqual(ui.arxiv_identifier_for_paper({'doi':'10.1109/x.2025.00828','url':'https://doi.org/10.1109/x.2025.00828'}),'')

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

    def test_first_unknown_browser_pdf_becomes_automatic_default_for_existing_library_item(self):
        before = self.paper()
        folder = self.storage.ensure_library_folder(parent_id=1, name='Already cataloged')
        item = self.storage.add_library_item(paper_id='first', folder_id=folder['id'])
        self.assertFalse(self.storage.list_paper_resources('first'))
        url = 'https://mdpi-res.com/article_deploy/fixture/article.pdf'
        capture = self.service.begin(self.db, {
            'url':url, 'is_pdf':True, 'origin_paper_id':'first',
            'metadata':{'doi':'10.1234/first', 'title':before['title']},
        })
        self.upload(capture, found={'kind':'doi','identifier':'10.1234/first'}, source_url=url)
        review = self.review(capture)
        self.assertTrue(review['paper']['existing'])
        self.assertEqual(review['suggested_file_type'], 'unknown')
        result = self.service.save(capture, self.storage, {'folder_id':folder['id'], 'include_pdf':True})
        self.assertTrue(result['ok'])
        self.assertEqual(result['gewu_key'], before['storage_key'])
        self.assertEqual(result['item_id'], item['id'])
        files = ui.paper_files_state_payload(self.storage, 'first')
        resource = files['files'][0]
        self.assertEqual(resource['file_type'], 'unknown')
        self.assertTrue(resource['is_default']); self.assertTrue(resource['is_primary'])
        self.assertFalse(files['preferred_resource_manual'])
        path = Path(resource['local_path'])
        self.assertEqual(path.parent.resolve(), (ui.LIBRARY_LOCAL_COPY_ROOT / 'Already cataloged').resolve())
        self.assertEqual(path.read_bytes(), capture.path.read_bytes())
        self.assertEqual(files['paper']['merged_pdf_path'], str(path))
        self.assertEqual(self.count('papers'), 1)
        self.assertEqual(self.count('library_items'), 1)
        self.assertEqual(self.count('resources'), 1)
        # Selection persists through reopening SQLite without setting a sticky manual preference.
        self.storage.close(); self.storage = Storage(self.db)
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], resource['id'])

    def test_first_unknown_default_does_not_steal_manual_choice_or_block_later_versions(self):
        self.paper()
        first = self.begin(); self.upload(first); self.review(first)
        self.assertTrue(self.save(first, include_pdf=True)['ok'])
        original = self.storage.resolve_default_paper_resource('first')
        self.assertIsNotNone(original)
        newer = self.begin(); self.upload(newer, content=self.pdf('Second unknown PDF')); self.review(newer)
        self.assertTrue(self.save(newer, include_pdf=True)['ok'])
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], original['id'])
        known = self.begin(); self.upload(known, content=self.pdf('Recognized preprint')); self.review(known)
        self.assertTrue(self.save(known, include_pdf=True, file_type='preprint')['ok'])
        preprint = self.storage.resolve_default_paper_resource('first')
        self.assertEqual(preprint['file_type'], 'preprint')
        self.assertEqual(self.storage.get_paper('first')['primary_resource_id'], preprint['id'])
        self.assertTrue(Path(self.storage.get_paper_resource(original['id'])['stored_path']).is_relative_to(ui.ASSOCIATED_FILES_ROOT))
        ui.set_preferred_paper_file(self.storage, 'first', original['id'])
        published = self.begin(); self.upload(published, content=self.pdf('Published paper')); self.review(published)
        self.assertTrue(self.save(published, include_pdf=True, file_type='published_version')['ok'])
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], original['id'])
        self.assertTrue(self.storage.get_paper('first')['preferred_resource_manual'])

    def test_first_unknown_promotion_failure_can_retry_without_duplicate_or_false_default(self):
        self.paper()
        capture = self.begin(); self.upload(capture); self.review(capture)
        self.storage.conn.execute("CREATE TRIGGER fail_primary BEFORE UPDATE OF primary_resource_id ON papers BEGIN SELECT RAISE(FAIL, 'fixture failure'); END")
        self.storage.conn.commit()
        failed = self.save(capture, include_pdf=True)
        self.assertFalse(failed['ok'])
        self.assertIsNone(self.storage.get_paper('first')['primary_resource_id'])
        first = self.storage.list_paper_resources('first')[0]
        self.assertEqual(Path(first['stored_path']).read_bytes(), capture.path.read_bytes())
        self.storage.conn.execute('DROP TRIGGER fail_primary'); self.storage.conn.commit()
        retried = self.save(capture, include_pdf=True)
        self.assertTrue(retried['ok']); self.assertTrue(retried['duplicate_file'])
        self.assertEqual(self.count('resources'), 1)
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], first['id'])
        self.assertEqual(self.storage.get_paper('first')['primary_resource_id'], first['id'])

    def test_resave_adopts_legacy_unknown_browser_pdf_without_adding_a_resource(self):
        before = self.paper()
        self.storage.add_library_item(paper_id='first', folder_id=1)
        content = self.pdf('A quantum sensing paper')
        original = ui.attach_file_to_paper(self.storage, paper_id='first', filename='old-capture.pdf',
            content=content, file_type='unknown', added_via='browser_capture')
        old_path = Path(original['stored_path'])
        self.assertTrue(old_path.resolve().is_relative_to(ui.ASSOCIATED_FILES_ROOT.resolve()))
        self.assertIsNone(self.storage.get_paper('first')['primary_resource_id'])
        capture = self.begin(); self.upload(capture, content=content); self.review(capture)
        result = self.save(capture, include_pdf=True)
        self.assertTrue(result['ok']); self.assertTrue(result['duplicate_file'])
        selected = self.storage.resolve_default_paper_resource('first')
        self.assertEqual(selected['id'], original['id'])
        self.assertEqual(result['gewu_key'], before['storage_key'])
        self.assertEqual(self.count('resources'), 1)
        self.assertFalse(old_path.exists())
        self.assertEqual(Path(selected['stored_path']).read_bytes(), content)
        self.assertFalse(self.storage.get_paper('first')['preferred_resource_manual'])

    def test_resave_repairs_only_unclassified_browser_copy_without_duplicates(self):
        self.paper(doi='10.1038/s41567-026-03429-7')
        old = self.publisher_capture(); self.review(old)
        before = self.save(old, include_pdf=True, file_type='unknown')
        resource = self.storage.list_paper_resources('first')[0]
        old_path = Path(resource['stored_path'])
        self.assertTrue(old_path.resolve().is_relative_to(ui.LIBRARY_LOCAL_COPY_ROOT.resolve()))
        again = self.publisher_capture(); self.review(again)
        after = self.save(again, include_pdf=True)
        self.assertTrue(after['duplicate_file'])
        self.assertEqual(before['gewu_key'], after['gewu_key'])
        self.assertEqual(before['item_id'], after['item_id'])
        files = self.storage.list_paper_resources('first')
        self.assertEqual(len(files), 1); self.assertEqual(files[0]['id'], resource['id'])
        self.assertEqual(files[0]['sha256'], resource['sha256'])
        self.assertTrue(files[0]['is_primary']); self.assertTrue(files[0]['is_default'])
        self.assertTrue(old_path.exists())

    def test_manual_unknown_and_existing_manual_default_are_preserved(self):
        self.paper(doi='10.1038/s41567-026-03429-7')
        capture = self.publisher_capture(); self.review(capture)
        self.save(capture, include_pdf=True, file_type='unknown', file_type_manual=True)
        first = self.storage.list_paper_resources('first')[0]
        self.assertTrue(first['file_type_override'])
        again = self.publisher_capture(); self.review(again); self.save(again, include_pdf=True)
        self.assertEqual(self.storage.get_paper_resource(first['id'])['file_type'], 'unknown')
        self.assertTrue(self.storage.get_paper('first')['main_pdf_path'])
        self.assertEqual(self.storage.resolve_default_paper_resource('first')['id'], first['id'])
        self.assertFalse(self.storage.get_paper('first')['preferred_resource_manual'])
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
            ('https://repository.example.edu/paper.pdf', 'institutional_repository'),
            ('https://files.example.net/paper.pdf', 'other'),
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
        result = self.service.save(capture, self.storage, {'folder_id':child['id'], 'folder_selection_explicit':True})
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
        with self.assertRaises(ValueError): self.service.save(capture,self.storage,{'folder_id':child['id'], 'folder_selection_explicit':True})
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
                self.assertTrue(file['is_default']); self.assertTrue(file['is_primary'])
                self.assertFalse(files['preferred_resource_manual'])
                self.assertTrue(Path(file['local_path']).resolve().is_relative_to(ui.LIBRARY_LOCAL_COPY_ROOT.resolve()))
                self.assertEqual(Path(file['local_path']).read_bytes(),content.getvalue())
                if resource_id is not None: self.assertEqual(file['id'],resource_id)
                resource_id=file['id']
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
