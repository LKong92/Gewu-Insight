import copy
import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from paper_monitor import metadata_jobs as jobs, metadata_refresh as work, metadata_network as network, http
from paper_monitor.storage import Storage
from tests import test_metadata_refresh as fixtures
from tests.test_metadata_refresh import preprint, published, DOI, ARXIV, DOI_CORE, ui


class UnifiedMetadataTests(unittest.TestCase):
    setUp = fixtures.MetadataRefreshTests.setUp
    refresh = fixtures.MetadataRefreshTests.refresh

    def test_quick_refreshes_basic_fields_even_with_both_identifiers(self):
        work.save_doi(self.storage, self.pid, DOI)
        self.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: preprint(DOI)
        result = self.refresh(mode='quick')
        self.assertEqual(result['paper']['journal'], 'Synthetic Journal')
        self.mocks['publication_metrics_metadata_from_doi'].assert_called_once()
        self.mocks['pubmed_metadata_from_doi'].assert_not_called()
        self.assertEqual(result['metadata_refresh']['mode'], 'quick')

    def test_single_full_satisfies_batch_quick_and_full_but_quick_does_not_block_full(self):
        self.refresh(mode='quick')
        self.assertTrue(work.recently_completed(self.storage, self.pid, 'quick'))
        self.assertFalse(work.recently_completed(self.storage, self.pid, 'full'))
        self.refresh(mode='full')
        calls = self.mocks['fetch_arxiv_by_id'].call_count
        for mode in ('quick', 'full'):
            self.assertEqual(self.refresh(mode=mode, origin='batch', skip_days=3)['metadata_refresh']['status'], 'skipped_recent')
        self.assertEqual(calls, self.mocks['fetch_arxiv_by_id'].call_count)
        self.refresh(mode='full')  # Manual action can check again.
        self.assertEqual(calls + 1, self.mocks['fetch_arxiv_by_id'].call_count)

    def test_changing_identifier_invalidates_successful_cooldown(self):
        self.refresh()
        self.assertTrue(work.recently_completed(self.storage, self.pid, 'full'))
        work.save_doi(self.storage, self.pid, '10.1234/corrected')
        self.assertFalse(work.recently_completed(self.storage, self.pid, 'full'))

    def test_batch_refresh_keeps_all_file_rows_and_default_unchanged(self):
        self.storage.add_library_item(paper_id=self.pid)
        pdf = self.path.parent / 'synthetic.pdf'
        pdf.write_bytes(b'%PDF-1.4 synthetic fixture')
        resource = self.storage.create_paper_resource(paper_id=self.pid, stored_path=str(pdf), file_type='preprint', annotation_state='unannotated', file_source='arxiv')
        self.storage.set_preferred_paper_resource(self.pid, resource['id'])
        paper = self.storage.get_paper(self.pid)
        before = [tuple(r) for r in self.storage.conn.execute('SELECT * FROM resources')]
        job = jobs.create(self.storage)
        jobs.run_job(self.storage, job['job_id'])
        after = self.storage.get_paper(self.pid)
        self.assertEqual(before, [tuple(r) for r in self.storage.conn.execute('SELECT * FROM resources')])
        self.assertEqual(pdf.read_bytes(), b'%PDF-1.4 synthetic fixture')
        for field in ('preferred_resource_id', 'preferred_resource_manual', 'merged_pdf_path', 'main_pdf_path', 'storage_key'):
            self.assertEqual(paper.get(field), after.get(field), field)

    def test_expired_history_allows_a_new_batch_check(self):
        self.refresh()
        self.storage.conn.execute('UPDATE paper_metadata_refreshes SET finished_at=?', ((datetime.now().astimezone()-timedelta(days=4)).isoformat(),))
        self.storage.conn.commit()
        self.assertNotEqual(self.refresh(mode='full', skip_days=3)['metadata_refresh']['status'], 'skipped_recent')

    def test_partial_retry_reuses_successful_crossref_but_retries_failed_openalex(self):
        work.save_doi(self.storage, self.pid, DOI)
        self.mocks['publication_metrics_metadata_from_doi'].side_effect = DOI_CORE
        self.mocks['openalex_request'].side_effect = RuntimeError('offline')
        with patch.object(ui, 'publication_metadata_from_doi', return_value=published()) as crossref:
            first = self.refresh(mode='full', skip_days=3)
            self.assertEqual(first['metadata_refresh']['status'], 'partial')
            self.mocks['openalex_request'].side_effect = lambda *a, **k: SimpleNamespace(json=lambda: {})
            second = self.refresh(mode='full', skip_days=3)
            self.assertEqual(crossref.call_count, 1)
            self.assertIn('Crossref', second['metadata_refresh']['reused_sources'])
            self.assertEqual(self.mocks['openalex_request'].call_count, 2)
            self.assertNotIn('OpenAlex', second['metadata_refresh']['reused_sources'])

    def test_folder_scope_deduplicates_keys_excludes_recycle_and_reports_missing_ids(self):
        folder = self.storage.create_library_folder(parent_id=1, name='Scope')['id']
        child = self.storage.create_library_folder(parent_id=folder, name='Child')['id']
        self.storage.add_library_item(paper_id=self.pid, folder_id=folder)
        self.storage.add_library_item(paper_id=self.pid, folder_id=child)
        self.storage.add_library_item(paper_id=self.pid, folder_id=1)
        no_id = {'paper_id':'no-id', 'title':'A different unidentified document', 'journal':'Local'}
        self.storage.upsert_paper(no_id); self.storage.add_library_item(paper_id='no-id', folder_id=child)
        recycle = self.storage.ensure_library_folder(parent_id=1, name='Recycle')['id']
        self.storage.upsert_paper({'paper_id':'old', 'title':'Discarded example', 'journal':'Synthetic', 'doi':'10.1234/old'})
        self.storage.add_library_item(paper_id='old', folder_id=recycle)
        before = [tuple(r) for r in self.storage.conn.execute('SELECT * FROM library_items')]
        job = jobs.create(self.storage, folder_id=folder)
        self.assertEqual(job['total'], 2)
        jobs.run_job(self.storage, job['job_id'])
        done = jobs.get(self.storage, job['job_id'])
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['counts']['missing_identifier'], 1)
        self.assertEqual(before, [tuple(r) for r in self.storage.conn.execute('SELECT * FROM library_items')])
        self.assertEqual(self.mocks['fetch_arxiv_by_id'].call_count, 1)
        self.assertNotIn('old', jobs.candidates(self.storage))
        with self.assertRaises(ValueError): jobs.create(self.storage, folder_id=recycle)

    def test_unchanged_check_does_not_increment_updated_count(self):
        self.storage.add_library_item(paper_id=self.pid)
        self.refresh()
        job = jobs.create(self.storage, skip_days=0)
        jobs.run_job(self.storage, job['job_id'])
        done = jobs.get(self.storage, job['job_id'])
        self.assertEqual(done['counts']['unchanged'], 1)
        self.assertEqual(done['result']['metadata_refreshed'], 0)

    def test_paused_job_survives_restart_and_rechecks_only_remaining_scope(self):
        self.storage.add_library_item(paper_id=self.pid)
        self.storage.upsert_paper({'paper_id':'z-paper', 'title':'Second paper', 'journal':'Synthetic', 'doi':'10.1234/second'})
        self.storage.add_library_item(paper_id='z-paper')
        job = jobs.create(self.storage)
        def pause_after_one(current):
            if current['current'] == 1: jobs.control(self.storage, job['job_id'], 'pause')
        jobs.run_job(self.storage, job['job_id'], progress=pause_after_one)
        self.assertEqual(jobs.get(self.storage, job['job_id'])['status'], 'paused')
        self.assertEqual(jobs.get(self.storage, job['job_id'])['current'], 1)
        # The remaining paper moves outside the active scope while paused.
        self.storage.conn.execute('UPDATE library_items SET trashed_at="now" WHERE paper_id="z-paper"'); self.storage.conn.commit()
        jobs._INITIALIZED.discard(str(self.path.resolve()))
        store = Storage(self.path)
        try:
            self.assertEqual(jobs.get(store, job['job_id'])['current'], 1)
            jobs.control(store, job['job_id'], 'resume')
            jobs.run_job(store, job['job_id'])
            done = jobs.get(store, job['job_id'])
            self.assertEqual(done['status'], 'completed')
            self.assertEqual(done['counts']['removed'], 1)
        finally: store.close()
        self.assertEqual(self.mocks['fetch_arxiv_by_id'].call_count, 1)

    def test_interrupted_running_job_is_restored_paused_without_network(self):
        job = jobs.create(self.storage)
        job['status'] = 'running'; jobs._save(self.storage, job)
        jobs._INITIALIZED.discard(str(self.path.resolve()))
        self.assertEqual(jobs.listing(self.storage)[0]['status'], 'paused')
        self.mocks['fetch_arxiv_by_id'].assert_not_called()

    def test_loader_recovered_identifier_uses_selected_mode_once_and_persists_job(self):
        self.storage.add_library_item(paper_id=self.pid)
        result = {'metadata_refresh_candidates':[{'paper_id':self.pid}]}
        def recovered(*args, **kwargs):
            work.save_doi(self.storage, self.pid, DOI)
            return {self.pid}
        with patch.object(ui, 'recover_imported_pdf_identifiers', side_effect=recovered):
            ui.refresh_imported_doi_metadata(self.storage, result, mode='quick')
        self.assertEqual(self.mocks['publication_metrics_metadata_from_doi'].call_count, 1)
        self.mocks['pubmed_metadata_from_doi'].assert_not_called()
        self.assertTrue(jobs.get(self.storage, result['metadata_job_id']))
        self.assertEqual(work.marker(self.storage.get_paper(self.pid))['mode'], 'quick')

    def test_metadata_429_persists_source_pause_without_changing_ordinary_transport(self):
        network._NEXT.clear(); network._BLOCKED.clear()
        self.addCleanup(network._NEXT.clear); self.addCleanup(network._BLOCKED.clear)
        response = SimpleNamespace(url='https://api.crossref.org/works/test', status_code=429,
                                   headers={'Retry-After':'600'}, raise_for_status=lambda: None)
        with patch.object(http, 'request_with_local_proxy_fallback', return_value=response) as request:
            with network.scope(self.storage):
                with self.assertRaises(network.SourceCoolingDown): http.request_with_retries('GET', response.url, max_retries=1)
            network._BLOCKED.clear()  # Simulated restart: the saved pause still applies.
            with network.scope(self.storage):
                with self.assertRaises(network.SourceCoolingDown): http.request_with_retries('GET', response.url, max_retries=1)
            self.assertEqual(request.call_count, 1)
            response.status_code = 200
            self.assertIs(http.request_with_retries('GET', response.url), response)
            self.assertEqual(request.call_count, 2, 'Non-metadata traffic uses its original policy')

    def test_swallowed_provider_error_is_partial_and_not_cached_as_not_found(self):
        work.save_doi(self.storage, self.pid, DOI)
        def swallowed(*args, **kwargs):
            network.after_error('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi', RuntimeError('offline'))
            return {'pmid':'123', 'doi':DOI}
        self.mocks['pubmed_metadata_from_doi'].side_effect = swallowed
        first = self.refresh(mode='full', skip_days=3)
        self.assertEqual(first['metadata_refresh']['sources']['PubMed'], 'unavailable')
        self.assertEqual(first['metadata_refresh']['status'], 'partial')
        raw = ui.parse_raw_json(first['paper'])
        self.assertNotIn('PubMed', raw['metadata_source_cache'])
        self.mocks['pubmed_metadata_from_doi'].side_effect = lambda *a, **k: None
        self.refresh(mode='full', skip_days=3)
        self.assertEqual(self.mocks['pubmed_metadata_from_doi'].call_count, 2)

    def test_single_request_has_priority_over_a_waiting_batch_paper(self):
        for pid in ('batch-waiting', 'manual'):
            self.storage.upsert_paper({'paper_id':pid, 'title':pid, 'journal':'Synthetic', 'doi':'10.1234/'+pid})
        entered, release = threading.Event(), threading.Event()
        order = []
        def fake(storage, paper_id, **kwargs):
            order.append(paper_id)
            if paper_id == self.pid: entered.set(); release.wait(5)
            return {'paper':storage.get_paper(paper_id), 'metadata_refresh':{'status':'unchanged', 'message':'Checked', 'mode':'full', 'detailed':True}}
        def run(pid, origin):
            store = Storage(self.path)
            try: return work.refresh(store, pid, origin=origin)
            finally: store.close()
        with patch.object(work, '_refresh', side_effect=fake), ThreadPoolExecutor(3) as pool:
            first = pool.submit(run, self.pid, 'batch'); self.assertTrue(entered.wait(2))
            second = pool.submit(run, 'batch-waiting', 'batch')
            third = pool.submit(run, 'manual', 'single')
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with work._QUEUE:
                    if len(work._WAITING) >= 2: break
                time.sleep(.01)
            release.set()
            first.result(); second.result(); third.result()
        self.assertEqual(order, [self.pid, 'manual', 'batch-waiting'])


if __name__ == '__main__': unittest.main()
