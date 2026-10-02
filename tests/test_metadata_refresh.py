import copy
import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_monitor import metadata_refresh as work, ui_server as ui
from paper_monitor.storage import Storage

ARXIV = '2106.14849'
DOI = '10.1234/published'
DOI_CORE = ui.publication_metrics_metadata_from_doi


def preprint(doi=''):
    return {'paper_id': 'arxiv_' + ARXIV, 'title': 'A synthetic paper', 'journal': 'arXiv',
            'doi': doi, 'abstract': 'Preprint abstract', 'source': 'arxiv',
            'url': 'https://arxiv.org/abs/' + ARXIV,
            'raw': {'arxiv_id': ARXIV, 'authors': ['A Researcher']}}


def published(doi=DOI):
    return {'paper_id': 'doi_synthetic', 'doi': doi, 'title': 'A synthetic paper',
            'journal': 'Synthetic Journal', 'abstract': 'Published abstract',
            'publication_date': '2026-09-11', 'source': 'crossref',
            'url': 'https://doi.org/' + doi,
            'raw': {'DOI': doi, 'volume': '12', 'page': '123', 'author': [{'given': 'A', 'family': 'Researcher'}]}}


class MetadataRefreshTests(unittest.TestCase):
    def setUp(self):
        updates = patch.object(work.notice_discovery, 'fetch_updates', return_value=[])
        updates.start(); self.addCleanup(updates.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite'
        self.storage = Storage(self.path)
        self.addCleanup(self.storage.close)
        mocks = {
            'fetch_arxiv_by_id': preprint(), 'publication_metrics_metadata_from_doi': published(),
            'semantic_scholar_request': SimpleNamespace(json=lambda: {}),
            'openalex_request': SimpleNamespace(json=lambda: {'results': []}),
            'pubmed_metadata_from_doi': None, 'ads_api_token': '',
        }
        self.mocks = {}
        for name, result in mocks.items():
            p = patch.object(ui, name, side_effect=lambda *a, _r=result, **k: copy.deepcopy(_r))
            self.mocks[name] = p.start(); self.addCleanup(p.stop)
        p = patch.object(ui, 'request_with_retries', side_effect=AssertionError('Unexpected remote request'))
        p.start(); self.addCleanup(p.stop)
        self.storage.upsert_paper(preprint())
        self.pid = preprint()['paper_id']

    def refresh(self, **kwargs):
        return work.refresh(self.storage, self.pid, **kwargs)

    def test_preprint_published_doi_fills_full_metadata_keeps_key_and_placements(self):
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        self.storage.add_library_item(paper_id=self.pid)
        before = self.storage.get_paper(self.pid)
        placements = [tuple(r) for r in self.storage.conn.execute('SELECT * FROM library_items')]
        result = self.refresh()
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(result['paper']['journal'], 'Synthetic Journal')
        self.assertEqual(ui.arxiv_identifier_for_paper(result['paper']), ARXIV)
        for key in ('paper_id', 'storage_key', 'merged_pdf_path', 'preferred_resource_id', 'preferred_resource_manual'):
            self.assertEqual(result['paper'].get(key), before.get(key), key)
        self.assertEqual(placements, [tuple(r) for r in self.storage.conn.execute('SELECT * FROM library_items')])
        self.assertIn('doi', result['metadata_refresh']['changed_fields'])
        self.mocks['pubmed_metadata_from_doi'].assert_called_once_with(DOI, timeout=12, max_retries=1)

    def test_semantic_explicit_arxiv_link_promotes_doi(self):
        self.mocks['semantic_scholar_request'].side_effect = lambda *a, **k: SimpleNamespace(json=lambda: {'paperId': 's2', 'externalIds': {'ArXiv': ARXIV, 'DOI': DOI}})
        result = self.refresh()
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(result['paper']['journal'], 'Synthetic Journal')

    def test_doi_only_fills_arxiv_from_matching_semantic_record(self):
        self.storage.conn.execute('UPDATE papers SET doi=?, raw_json=?, journal=? WHERE paper_id=?', (DOI, '{}', 'Synthetic Journal', self.pid)); self.storage.conn.commit()
        self.mocks['semantic_scholar_request'].side_effect = lambda *a, **k: SimpleNamespace(json=lambda: {'paperId': 's2', 'externalIds': {'DOI': DOI, 'ArXiv': ARXIV}})
        result = self.refresh()
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(ui.preprint_identifier(result['paper']), ARXIV)

    def test_unrelated_semantic_response_cannot_change_identifiers_or_metrics(self):
        self.mocks['semantic_scholar_request'].side_effect = lambda *a, **k: SimpleNamespace(json=lambda: {'paperId': 'wrong', 'externalIds': {'ArXiv': '9999.99999', 'DOI': DOI}, 'citationCount': 10000})
        result = self.refresh()
        self.assertFalse(result['paper']['doi'])
        self.assertFalse(ui.parse_semantic_scholar_json(result['paper']))
        self.assertTrue(result['metadata_refresh']['conflicts'])

    def test_same_title_different_authors_without_explicit_link_does_not_fill_doi(self):
        self.mocks['openalex_request'].side_effect = lambda *a, **k: SimpleNamespace(json=lambda: {'results': [{'title': 'A synthetic paper', 'doi': DOI}]})
        self.assertFalse(self.refresh()['paper']['doi'])

    def test_openalex_explicit_location_is_used(self):
        self.mocks['openalex_request'].side_effect = lambda *a, **k: SimpleNamespace(json=lambda: {'results': [{'doi': DOI, 'locations': [{'landing_page_url': 'https://arxiv.org/abs/' + ARXIV}]}]})
        self.assertEqual(self.refresh()['paper']['doi'], DOI)

    def test_arxiv_in_references_is_not_an_identity_link(self):
        self.assertEqual(work.linked_arxiv({'reference': [{'URL': 'https://arxiv.org/abs/' + ARXIV}]}), set())
        self.assertEqual(work.linked_arxiv({'relation': {'has-preprint': [{'id-type': 'arxiv', 'id': ARXIV}]}}), {ARXIV})
        self.assertEqual(ui.arxiv_identifier_for_paper({'raw_json': json.dumps({'crossref': {'reference': [{'URL': 'https://arxiv.org/abs/' + ARXIV}]}})}), '')

    def test_manual_cleared_arxiv_stays_empty(self):
        ui.update_manual_preprint_identifier(self.storage, self.pid, '')
        work.save_doi(self.storage, self.pid, DOI)
        self.mocks['semantic_scholar_request'].side_effect = lambda *a, **k: SimpleNamespace(json=lambda: {'paperId': 's2', 'externalIds': {'DOI': DOI, 'ArXiv': ARXIV}})
        self.assertEqual(ui.arxiv_identifier_for_paper(self.refresh()['paper']), '')

    def test_manual_cleared_doi_is_not_restored(self):
        work.save_doi(self.storage, self.pid, DOI)
        work.save_doi(self.storage, self.pid, '')
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        self.assertFalse(self.refresh()['paper']['doi'])

    def test_verified_published_identity_reuses_existing_paper(self):
        self.storage.upsert_paper(published())
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        result = self.refresh()
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 1)
        self.assertFalse(result['metadata_refresh']['conflicts'])
        self.assertEqual(self.storage.get_paper(self.pid)['paper_id'], result['paper']['paper_id'])

    def test_another_doi_owner_with_conflicting_evidence_is_not_merged(self):
        other = published()
        other.update(title='An unrelated marine organism', raw={'authors':['Z Other']}, journal='Marine Ecology')
        self.storage.upsert_paper(other)
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        result = self.refresh()
        self.assertFalse(result['paper']['doi'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 2)
        self.assertTrue(result['metadata_refresh']['conflicts'])

    def test_partial_failure_retains_good_metadata_and_reports_source(self):
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        self.mocks['semantic_scholar_request'].side_effect = RuntimeError('offline')
        result = self.refresh()
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(result['metadata_refresh']['status'], 'partial')
        self.assertIn('unavailable', result['metadata_refresh']['sources'].values())

    def test_all_sources_unavailable_cannot_report_success(self):
        self.mocks['fetch_arxiv_by_id'].side_effect = RuntimeError('offline')
        self.mocks['semantic_scholar_request'].side_effect = RuntimeError('offline')
        self.mocks['openalex_request'].side_effect = RuntimeError('offline')
        result = self.refresh()
        self.assertEqual(result['metadata_refresh']['status'], 'partial')
        self.assertEqual(result['paper']['title'], 'A synthetic paper')

    def test_periodic_check_does_not_fetch_full_metadata_when_both_ids_known(self):
        work.save_doi(self.storage, self.pid, DOI)
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        self.refresh(detailed=False)
        self.mocks['publication_metrics_metadata_from_doi'].assert_not_called()
        self.mocks['semantic_scholar_request'].assert_not_called()
        self.mocks['pubmed_metadata_from_doi'].assert_not_called()

    def test_seven_day_checks_back_off_after_three_unchanged_attempts(self):
        result = self.refresh(detailed=False)
        now = datetime.fromisoformat(result['metadata_refresh']['checked_at'])
        self.assertFalse(work.is_due(result['paper'], now + timedelta(days=6)))
        self.assertTrue(work.is_due(result['paper'], now + timedelta(days=8)))
        self.refresh(detailed=False)
        result = self.refresh(detailed=False)
        self.assertFalse(work.is_due(result['paper'], now + timedelta(days=29)))

    def test_saved_candidates_deduplicate_and_exclude_recycle_descendants(self):
        self.storage.add_library_item(paper_id=self.pid)
        self.storage.add_my_publication(paper_id=self.pid)
        recycle = self.storage.create_library_folder(parent_id=1, name='Recycle')['id']
        child = self.storage.create_library_folder(parent_id=recycle, name='old')
        old = preprint(); old['paper_id'] = 'old'; old['raw']['arxiv_id'] = '2201.00001'; old['url'] = 'https://arxiv.org/abs/2201.00001'
        self.storage.upsert_paper(old); self.storage.add_library_item(paper_id='old', folder_id=child['id'])
        self.assertEqual([p['paper_id'] for p in work.saved_candidates(self.storage)], [self.pid])

    def test_concurrent_identifier_edit_prevents_stale_result(self):
        def during(*a, **k):
            ui.update_manual_preprint_identifier(self.storage, self.pid, '2201.00001')
            return preprint(DOI)
        self.mocks['fetch_arxiv_by_id'].side_effect = during
        with self.assertRaisesRegex(ValueError, 'Identifiers changed'):
            self.refresh()
        self.assertEqual(ui.arxiv_identifier_for_paper(self.storage.get_paper(self.pid)), '2201.00001')
        self.assertFalse(self.storage.get_paper(self.pid)['doi'])

    def test_duplicate_requests_share_one_network_run(self):
        entered = threading.Event(); release = threading.Event()
        def fetch(*a, **k): entered.set(); release.wait(3); return preprint()
        self.mocks['fetch_arxiv_by_id'].side_effect = fetch
        def run():
            store = Storage(self.path)
            try: return work.refresh(store, self.pid)
            finally: store.close()
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(run); self.assertTrue(entered.wait(2))
            second = pool.submit(run)
            # Ensure both callers have reached the shared Future.
            import time
            time.sleep(.08); release.set()
            self.assertEqual(first.result()['metadata_refresh'], second.result()['metadata_refresh'])
        self.assertEqual(self.mocks['fetch_arxiv_by_id'].call_count, 1)

    def test_exact_identifier_beats_high_citation_wrong_candidate(self):
        good = {'paperId': 'good', 'title': 'A synthetic paper', 'externalIds': {'DOI': DOI}}
        wrong = {'paperId': 'wrong', 'abstract': 'long', 'citationCount': 10000, 'externalIds': {'DOI': '10.1234/wrong'}}
        self.assertEqual(ui.best_semantic_scholar_candidate([wrong, good], doi=DOI)['paperId'], 'good')

    def test_arxiv_doi_transitions_to_retitled_publication_on_same_key(self):
        old = '10.48550/arxiv.' + ARXIV
        self.storage.conn.execute('UPDATE papers SET doi=?, url=? WHERE paper_id=?', (old, 'https://doi.org/' + old, self.pid))
        self.storage.conn.commit()
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        item = published(); item['title'] = 'Completely different published wording'
        self.mocks['publication_metrics_metadata_from_doi'].side_effect = lambda *a, **k: item
        result = self.refresh()
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(result['paper']['title'], item['title'])
        self.assertEqual(result['paper']['paper_id'], self.pid)

    def test_manual_doi_correction_retires_old_remote_url_not_files(self):
        old = '10.1234/incorrect'
        self.storage.conn.execute('UPDATE papers SET doi=?, url=?, pdf_url=? WHERE paper_id=?', (old, 'https://doi.org/' + old, 'https://example.org/doi/pdf/' + old, self.pid))
        self.storage.conn.commit()
        work.save_doi(self.storage, self.pid, DOI)
        result = self.refresh()
        self.assertEqual(result['paper']['journal'], 'Synthetic Journal')
        self.assertTrue(ui.parse_raw_json(result['paper'])['manual_identifier_history'])

    def test_user_folder_named_recycle_is_still_eligible(self):
        parent = self.storage.create_library_folder(parent_id=1, name='My Folder')['id']
        child = self.storage.create_library_folder(parent_id=parent, name='Recycle')['id']
        self.storage.add_library_item(paper_id=self.pid, folder_id=child)
        self.assertEqual([p['paper_id'] for p in work.saved_candidates(self.storage)], [self.pid])

    def test_crossref_preprint_relation_cross_fills_arxiv(self):
        self.storage.conn.execute('UPDATE papers SET doi=?, url=NULL, raw_json=? WHERE paper_id=?', (DOI, '{}', self.pid))
        self.storage.conn.commit()
        item = published(); item['raw']['relation'] = {'has-preprint': [{'id-type': 'doi', 'id': '10.48550/arXiv.' + ARXIV}]}
        self.mocks['publication_metrics_metadata_from_doi'].side_effect = lambda *a, **k: item
        self.assertEqual(ui.arxiv_identifier_for_paper(self.refresh()['paper']), ARXIV)

    def test_ads_explicit_arxiv_record_can_fill_doi(self):
        self.mocks['ads_api_token'].side_effect = lambda *a: 'synthetic-not-a-real-token'
        with patch.object(ui, 'fetch_ads_record_by_identifier', return_value={'doi': [DOI], 'identifier': ['arXiv:' + ARXIV]}):
            self.assertEqual(self.refresh()['paper']['doi'], DOI)

    def test_refresh_handler_accepts_arxiv_only_paper_without_doi_input(self):
        handler = object.__new__(ui.PaperMonitorUiHandler)
        handler.configured_db_path = self.path
        handler.send_json = lambda result: setattr(handler, 'result', result)
        handler.send_error_json = lambda *args: self.fail(str(args))
        handler.handle_refresh_library_metadata({'paper_id': self.pid, 'snapshot': False})
        self.assertEqual(handler.result['paper']['preprint_id'], ARXIV)
        self.assertIn('checked_at', handler.result['metadata_refresh'])

    def test_author_scheduler_does_not_refresh_saved_library_or_publication_papers(self):
        from paper_monitor import author_metadata_work as scheduler
        self.storage.add_library_item(paper_id=self.pid)
        self.storage.add_my_publication(paper_id=self.pid)
        now = datetime.now().astimezone()
        scheduler.save(self.storage, {'day': now.date().isoformat(), 'used': 79})
        with patch.dict(ui.AUTHOR_MONITOR_ENRICHMENT_JOBS, {}, clear=True), patch.object(ui, 'google_scholar_request_with_spacing', side_effect=AssertionError('No Scholar traffic')):
            scheduler.run_slice(self.path, now=now)
            self.assertEqual(scheduler.read(self.storage)['used'], 79)
            scheduler.run_slice(self.path, now=now + timedelta(minutes=10))
            self.assertEqual(self.mocks['fetch_arxiv_by_id'].call_count, 0)
            self.assertEqual(scheduler.snapshot(self.storage)['eligible'], 0)

    def test_raw_manual_metadata_survives_remote_payload(self):
        raw = ui.parse_raw_json(self.storage.get_paper(self.pid))
        raw['manual_metadata'] = {'title': 'My edited title'}
        self.storage.update_paper_raw_json(self.pid, raw)
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        result = self.refresh()
        self.assertEqual(ui.parse_raw_json(result['paper'])['manual_metadata'], {'title': 'My edited title'})

    def test_real_registered_files_and_manual_default_remain_byte_identical(self):
        from pypdf import PdfWriter
        pdf = Path(self.tmp.name) / 'synthetic.pdf'
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100); writer.write(str(pdf))
        resource = self.storage.create_paper_resource(paper_id=self.pid, stored_path=str(pdf), file_type='preprint', annotation_state='unannotated', file_source='arxiv')
        self.storage.set_preferred_paper_resource(self.pid, resource['id'])
        before = [tuple(r) for r in self.storage.conn.execute('SELECT * FROM resources')]
        data = pdf.read_bytes(); paper = self.storage.get_paper(self.pid)
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        result = self.refresh()
        self.assertEqual(before, [tuple(r) for r in self.storage.conn.execute('SELECT * FROM resources')])
        self.assertEqual(data, pdf.read_bytes())
        for field in ('preferred_resource_id','preferred_resource_manual','merged_pdf_path','main_pdf_path','storage_key'):
            self.assertEqual(paper.get(field), result['paper'].get(field), field)

    def test_doi_core_reports_partial_source_failure_without_repeating_crossref(self):
        self.mocks['publication_metrics_metadata_from_doi'].side_effect = DOI_CORE
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        self.mocks['openalex_request'].side_effect = RuntimeError('offline')
        with patch.object(ui, 'publication_metadata_from_doi', return_value=published()) as crossref:
            result = self.refresh()
        self.assertEqual(result['metadata_refresh']['sources']['OpenAlex'], 'unavailable')
        self.assertEqual(result['metadata_refresh']['status'], 'partial')
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(crossref.call_count, 1)


if __name__ == '__main__': unittest.main()
