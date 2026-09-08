import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch, Mock
from types import SimpleNamespace
from requests.exceptions import SSLError, Timeout, ConnectionError

from paper_monitor import publication_jobs as jobs, ui_server as ui
from paper_monitor.storage import Storage
from paper_monitor.workflow_store import publication_work_snapshot
from paper_monitor.publication_errors import publication_error_message


def candidate(index,doi=''):
    return {'paper':{'paper_id':f'scholar_fixture_{index}','title':f'Distinct research article {index}','journal':'Example Journal','publication_date':'2026','doi':doi,'source':'google-scholar'},'raw':{'authors':['Alice Researcher'],'google_scholar':{'publication_url':f'https://scholar.google.com/citations?user=test&citation_for_view=test:{index}'}}}


class PublicationJobsTests(TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'test.sqlite'
        self.storage=Storage(self.path);self.addCleanup(self.storage.close)
        for function in ('sync_my_publication_alias','move_monitor_pdf_into_context_if_needed','sync_my_publication_existing_pubmed_marks'):
            patcher=patch.object(ui,function);patcher.start();self.addCleanup(patcher.stop)
        self.profile={'url':'https://scholar.google.com/citations?user=fixture','user_id':'fixture','name':'Alice Researcher'}

    def job(self):
        return dict(self.storage.conn.execute('SELECT * FROM publication_import_jobs').fetchone())

    def test_import_exceeds_300_and_5000_without_loading_candidate_ui(self):
        jobs.create_import(self.storage,self.profile)
        # Cursor starts beyond Author Monitor's previous fixed 5,000 ceiling.
        self.storage.conn.execute('UPDATE publication_import_jobs SET page_offset=5000');self.storage.conn.commit()
        offsets=[]
        def page(url,offset):
            offsets.append(offset)
            return {'candidates':[candidate(offset+i) for i in range(100)],'next_offset':offset+100,'finished':offset==5300}
        with patch.object(jobs,'fetch_profile_page',side_effect=page):
            for _ in range(4): self.assertTrue(jobs.run_import_step(self.storage))
        self.assertEqual(offsets,[5000,5100,5200,5300])
        self.assertEqual(self.job()['status'],'complete')
        self.assertEqual(self.job()['added'],400)
        self.assertEqual(publication_work_snapshot(self.storage)['identifiers']['pending'],400)
        self.assertEqual(len(self.storage.list_my_publications()),400)

    def test_restart_resumes_cursor_and_source_deduplication(self):
        jobs.create_import(self.storage,self.profile)
        page={'candidates':[candidate(1),candidate(2)],'next_offset':100,'finished':False}
        with patch.object(jobs,'fetch_profile_page',return_value=page):jobs.run_import_step(self.storage)
        reopened=Storage(self.path)
        try:
            with patch.object(jobs,'fetch_profile_page',return_value={'candidates':[candidate(2),candidate(3)],'next_offset':200,'finished':True}) as fetch:
                jobs.run_import_step(reopened)
            self.assertEqual(fetch.call_args.args[1],100)
            self.assertEqual(len(reopened.list_my_publications()),3)
        finally:reopened.close()
        self.assertEqual(self.job()['seen'],3)

    def test_existing_author_library_record_reuses_key_and_individual_add_queues_id(self):
        original=ui.paper_from_publication_candidate(candidate(1));original['paper_id']='canonical_existing'
        self.storage.upsert_paper(original)
        before=self.storage.get_paper('canonical_existing')
        publication,existing=jobs.add_candidate(self.storage,candidate(1))
        self.assertFalse(existing)
        self.assertEqual(publication['paper_id'],'canonical_existing')
        self.assertEqual(self.storage.get_paper('canonical_existing')['storage_key'],before['storage_key'])
        duplicate,existing=jobs.add_candidate(self.storage,candidate(1))
        self.assertTrue(existing);self.assertEqual(duplicate['id'],publication['id'])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM publication_identifier_tasks').fetchone()[0],1)

    def test_explicit_recheck_readds_removed_placements_and_deleted_papers(self):
        job=jobs.create_import(self.storage,self.profile)
        page={'candidates':[candidate(1),candidate(2)],'next_offset':2,'finished':True}
        with patch.object(jobs,'fetch_profile_page',return_value=page):
            jobs.run_import_step(self.storage)
            rows=self.storage.list_my_publications()
            for row in rows:self.storage.delete_my_publication(publication_id=row['id'])
            self.storage.conn.execute('DELETE FROM papers WHERE paper_id=?',(rows[0]['paper_id'],))
            self.storage.conn.commit()
            jobs.control_import(self.storage,job['id'],'check')
            jobs.run_import_step(self.storage)
        self.assertEqual(len(self.storage.list_my_publications()),2)
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],2)
        self.assertEqual(self.job()['seen'],2)
        self.assertEqual(self.job()['status'],'complete')

    def test_identifier_updates_existing_record_without_changing_key_or_file(self):
        publication,_=jobs.add_candidate(self.storage,candidate(1))
        key=self.storage.get_paper(publication['paper_id'])['storage_key']
        file=Path(self.tmp.name)/'paper.pdf';file.write_bytes(b'test file bytes')
        self.storage.conn.execute('UPDATE papers SET main_pdf_path=?,merged_pdf_path=? WHERE paper_id=?',(str(file),str(file),publication['paper_id']));self.storage.conn.commit()
        identified=ui.paper_from_publication_candidate(candidate(1,'10.1234/example'))
        with patch.object(ui,'resolve_google_scholar_candidate_to_identifier',return_value=identified):jobs.run_identifier_step(self.storage)
        updated=self.storage.get_paper(publication['paper_id'])
        self.assertEqual(updated['doi'],'10.1234/example');self.assertEqual(updated['storage_key'],key)
        self.assertEqual(updated['main_pdf_path'],str(file));self.assertEqual(file.read_bytes(),b'test file bytes')
        self.assertEqual(publication_work_snapshot(self.storage)['identifiers'],{'matched':1})

    def test_deleting_publication_during_resolve_does_not_resurrect_it(self):
        publication,_=jobs.add_candidate(self.storage,candidate(1))
        def resolve(_):
            self.storage.delete_my_publication(publication_id=publication['id'])
            return ui.paper_from_publication_candidate(candidate(1,'10.1234/example'))
        with patch.object(ui,'resolve_google_scholar_candidate_to_identifier',side_effect=resolve):jobs.run_identifier_step(self.storage)
        self.assertEqual(self.storage.list_my_publications(),[])
        self.assertEqual(publication_work_snapshot(self.storage)['identifiers'],{})

    def test_unmatched_stays_saved_and_can_be_retried(self):
        publication,_=jobs.add_candidate(self.storage,candidate(1))
        with patch.object(ui,'resolve_google_scholar_candidate_to_identifier',return_value=None):jobs.run_identifier_step(self.storage)
        self.assertEqual(len(self.storage.list_my_publications()),1)
        self.assertEqual(publication_work_snapshot(self.storage)['identifiers'],{'unresolved':1})
        jobs.retry_identifiers(self.storage,publication['id'])
        self.assertEqual(publication_work_snapshot(self.storage)['identifiers'],{'pending':1})

    def test_one_identity_failure_does_not_stop_later_articles(self):
        jobs.create_import(self.storage,self.profile)
        original=jobs.add_candidate
        def add(storage,item):
            if item['paper']['paper_id'].endswith('_1'):raise ValueError('Synthetic identity conflict')
            return original(storage,item)
        with patch.object(jobs,'fetch_profile_page',return_value={'candidates':[candidate(1),candidate(2)],'next_offset':2,'finished':True}),patch.object(jobs,'add_candidate',side_effect=add):
            jobs.run_import_step(self.storage)
        self.assertEqual(self.job()['status'],'partial');self.assertEqual(self.job()['rejected'],1)
        self.assertEqual(len(self.storage.list_my_publications()),1)
        jobs.control_import(self.storage,self.job()['id'],'resume')
        with patch.object(jobs,'fetch_profile_page',return_value={'candidates':[candidate(1),candidate(2)],'next_offset':2,'finished':True}):jobs.run_import_step(self.storage)
        self.assertEqual(self.job()['status'],'complete');self.assertEqual(self.job()['seen'],2)

    def test_pause_during_page_request_keeps_cursor_and_resume_is_idempotent(self):
        job=jobs.create_import(self.storage,self.profile)
        def page(*args):
            jobs.control_import(self.storage,job['id'],'pause')
            return {'candidates':[candidate(1)],'next_offset':1,'finished':True}
        with patch.object(jobs,'fetch_profile_page',side_effect=page):jobs.run_import_step(self.storage)
        self.assertEqual(self.job()['status'],'paused');self.assertEqual(self.job()['page_offset'],0)
        jobs.control_import(self.storage,job['id'],'resume')
        self.assertEqual(jobs.create_import(self.storage,self.profile)['id'],job['id'])

    def test_network_error_and_repeated_page_are_incomplete(self):
        jobs.create_import(self.storage,self.profile)
        with patch.object(jobs,'fetch_profile_page',side_effect=RuntimeError('network unavailable')):jobs.run_import_step(self.storage)
        self.assertEqual(self.job()['status'],'error');self.assertEqual(self.job()['page_offset'],0)
        jobs.control_import(self.storage,self.job()['id'],'resume')
        with patch.object(jobs,'fetch_profile_page',return_value={'candidates':[candidate(1)],'next_offset':100,'finished':False}):
            jobs.run_import_step(self.storage);jobs.run_import_step(self.storage)
        self.assertEqual(self.job()['status'],'error');self.assertIn('repeated',self.job()['message'])
        self.assertEqual(len(self.storage.list_my_publications()),1)

    def test_parser_obeys_source_end_and_rejects_block_page(self):
        html='<tbody id="gsc_a_b"><tr class="gsc_a_tr"><td><a class="gsc_a_at" href="/citations?citation_for_view=fixture:1">An article</a><div class="gs_gray">Alice</div><div class="gs_gray">Journal</div></td><td class="gsc_a_y"><span>2026</span></td></tr></tbody><button id="gsc_bpf_more" disabled>More</button>'
        with patch.object(ui,'google_scholar_request_with_spacing',return_value=SimpleNamespace(text=html,url=self.profile['url'])):
            result=jobs.fetch_profile_page(self.profile['url'],5000)
        self.assertTrue(result['finished']);self.assertEqual(result['next_offset'],5001)
        with patch.object(ui,'google_scholar_request_with_spacing',return_value=SimpleNamespace(text='recaptcha',url=self.profile['url'])):
            with self.assertRaises(ui.GoogleScholarBlockedError):jobs.fetch_profile_page(self.profile['url'],0)

    def test_v16_upgrade_adds_workflows_without_reseeding_or_changing_existing_papers(self):
        publication,_=jobs.add_candidate(self.storage,candidate(1))
        original=self.storage.get_paper(publication['paper_id'])
        self.storage.conn.executescript('DROP TABLE publication_import_items; DROP TABLE publication_identifier_tasks; DROP TABLE publication_import_jobs; DROP TABLE subject_preserved_windows; PRAGMA user_version=16;')
        with patch.object(Storage,'_seed_library_from_existing_papers',side_effect=AssertionError('must not reseed')),patch.object(Storage,'_backfill_paper_source_observations',side_effect=AssertionError('must not backfill')):
            upgraded=Storage(self.path)
        try:
            self.assertEqual(upgraded.get_paper(publication['paper_id']),original)
            self.assertEqual(upgraded.conn.execute('PRAGMA user_version').fetchone()[0],17)
            self.assertEqual(publication_work_snapshot(upgraded),{'imports':[],'identifiers':{}})
        finally:upgraded.close()

    def test_restart_recovers_inflight_work_but_respects_pause(self):
        job=jobs.create_import(self.storage,self.profile)
        publication,_=jobs.add_candidate(self.storage,candidate(1))
        self.storage.conn.execute("UPDATE publication_import_jobs SET status='running',page_offset=400")
        self.storage.conn.execute("UPDATE publication_identifier_tasks SET status='working'")
        self.storage.conn.commit()
        jobs.recover_interrupted_work(self.storage)
        self.assertEqual(self.job()['status'],'queued');self.assertEqual(self.job()['page_offset'],400)
        self.assertEqual(publication_work_snapshot(self.storage)['identifiers'],{'pending':1})
        jobs.control_import(self.storage,job['id'],'pause');jobs.recover_interrupted_work(self.storage)
        self.assertEqual(self.job()['status'],'paused')

    def test_connection_failure_keeps_saved_page_and_resumes_at_next_page(self):
        job = jobs.create_import(self.storage, self.profile)
        with patch.object(jobs, 'fetch_profile_page', return_value={'candidates': [candidate(1)], 'next_offset': 100, 'finished': False}):
            jobs.run_import_step(self.storage)
        failure = SSLError("HTTPSConnectionPool(host='scholar.google.com'): SSLEOFError _ssl.c:1129")
        with patch.object(jobs, 'fetch_profile_page', side_effect=failure), self.assertLogs('paper_monitor.publication_errors', level='WARNING') as logs:
            jobs.run_import_step(self.storage)
        self.assertIn('SSLError', '\n'.join(logs.output))
        snapshot = publication_work_snapshot(self.storage)['imports'][0]
        self.assertEqual(snapshot['page_offset'], 100)
        self.assertEqual(snapshot['added'], 1)
        self.assertIn('secure connection', snapshot['message'])
        self.assertIn('try again later', snapshot['message'])
        self.assertNotIn('HTTPSConnectionPool', snapshot['message'])
        jobs.control_import(self.storage, job['id'], 'resume')
        with patch.object(jobs, 'fetch_profile_page', return_value={'candidates': [candidate(2)], 'next_offset': 101, 'finished': True}) as fetch:
            jobs.run_import_step(self.storage)
        self.assertEqual(fetch.call_args.args[1], 100)
        self.assertEqual(self.job()['status'], 'complete')
        self.assertEqual(len(self.storage.list_my_publications()), 2)

    def test_legacy_errors_are_projected_safely_without_rewriting_job(self):
        jobs.create_import(self.storage, self.profile)
        for failure, reason in [
            (SSLError('SSLError: HTTPSConnectionPool _ssl.c:1129'), 'secure connection'),
            (Timeout('Read timed out: internal request details'), 'too long'),
            (ConnectionError('HTTPSConnectionPool: private request details'), 'connection'),
            (RuntimeError('Traceback /private/path implementation details'), 'could not finish'),
            (ValueError('Google Scholar is temporarily blocking automated profile import'), 'limiting access'),
        ]:
            with self.subTest(reason=reason):
                raw = str(failure)
                self.storage.conn.execute("UPDATE publication_import_jobs SET status='error',message=?", (raw,))
                self.storage.conn.commit()
                public = publication_work_snapshot(self.storage)['imports'][0]['message']
                self.assertIn(reason, public)
                self.assertIn('try again later', public)
                for technical in ('HTTPSConnectionPool', '_ssl.c', 'Traceback', '/private/', 'internal request'):
                    self.assertNotIn(technical, public)
                self.assertEqual(self.job()['message'], raw)
                friendly = publication_error_message(failure)
                self.assertEqual(publication_error_message(friendly), friendly)

    def test_lookup_endpoints_return_a_reason_without_internal_exception_details(self):
        handler = ui.PaperMonitorUiHandler.__new__(ui.PaperMonitorUiHandler)
        handler.configured_db_path = self.path
        for method, payload, fetch in [
            ('handle_publication_search', {'q': ['paper']}, 'search_publications'),
            ('handle_google_scholar_profile_search', {'q': [self.profile['url']]}, 'fetch_google_scholar_profile_payload'),
            ('handle_import_google_scholar_publications', {'url': self.profile['url']}, 'fetch_google_scholar_profile_payload'),
            ('handle_resolve_google_scholar_publication', {'candidate': candidate(1)}, 'resolve_google_scholar_candidate_to_identifier'),
        ]:
            with self.subTest(method=method):
                handler.send_error_json = Mock()
                with patch.object(ui, fetch, side_effect=SSLError('HTTPSConnectionPool _ssl.c:1129')), self.assertLogs('paper_monitor.publication_errors', level='WARNING'):
                    getattr(handler, method)(payload)
                status, message = handler.send_error_json.call_args.args
                self.assertEqual(status, 502)
                self.assertIn('secure connection', message)
                self.assertIn('try again later', message)
                self.assertNotIn('_ssl.c', message)
                self.assertNotIn('HTTPSConnectionPool', message)
