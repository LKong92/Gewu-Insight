import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_monitor import ui_server as ui, scholar_access, author_metadata_work as work
from paper_monitor.storage import Storage
from tests.test_author_monitor import paper, scholar_profile


class AuthorBackgroundTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite'
        self.storage = Storage(self.path)
        self.addCleanup(self.storage.close)
        self.old_jobs = dict(ui.AUTHOR_MONITOR_ENRICHMENT_JOBS)
        ui.AUTHOR_MONITOR_ENRICHMENT_JOBS.clear()
        self.addCleanup(lambda: (ui.AUTHOR_MONITOR_ENRICHMENT_JOBS.clear(), ui.AUTHOR_MONITOR_ENRICHMENT_JOBS.update(self.old_jobs)))
        self.spacing = patch.object(ui, 'GOOGLE_SCHOLAR_LAST_REQUEST_AT', 0)
        self.spacing.start(); self.addCleanup(self.spacing.stop)

    def add(self, count=3):
        a = self.storage.add_author_monitor(scholar_profile('test-a', 'A'))['id']
        b = self.storage.add_author_monitor(scholar_profile('test-b', 'B'))['id']
        for i in range(count):
            self.storage.upsert_paper(paper(f'p{i}', f'Paper {i}', '2026-09-10'))
            self.storage.add_author_monitor_paper(author_monitor_id=a if i % 2 == 0 else b, paper_id=f'p{i}')
        return a, b

    def test_persisted_cooldown_blocks_requests_after_reopen(self):
        first = ui.start_google_scholar_global_cooldown(self.storage)
        with scholar_access.database(self.path), patch.object(ui, 'request_with_retries') as request:
            for _ in range(2):
                with self.assertRaises(ui.GoogleScholarBlockedError):
                    ui.google_scholar_request_with_spacing('GET', 'https://scholar.google.com/citations')
            request.assert_not_called()
        again = ui.start_google_scholar_global_cooldown(self.storage)
        self.assertEqual(first['until'], again['until'], 'suppressed work must not extend a pause')

    def test_cooldown_is_rechecked_after_spacing(self):
        ui.GOOGLE_SCHOLAR_LAST_REQUEST_AT = 10
        with scholar_access.database(self.path), patch.object(ui.time, 'monotonic', return_value=10), patch.object(ui.time, 'sleep', side_effect=lambda _: ui.start_google_scholar_global_cooldown(self.storage)), patch.object(ui, 'request_with_retries') as request:
            with self.assertRaises(ui.GoogleScholarBlockedError):
                ui.google_scholar_request_with_spacing('GET', 'https://scholar.google.com/citations')
            request.assert_not_called()

    def test_restriction_stops_already_queued_requests_before_next_network_call(self):
        entered = threading.Event(); release = threading.Event()
        def network(*args, **kwargs):
            entered.set(); release.wait(2)
            return SimpleNamespace(text='unusual traffic recaptcha', url='https://scholar.google.com/sorry')
        def fetch():
            with scholar_access.database(self.path):
                try: ui.google_scholar_request_with_spacing('GET', 'https://scholar.google.com/citations')
                except ui.GoogleScholarBlockedError: return 'paused'
        with patch.object(ui, 'request_with_retries', side_effect=network) as request, ThreadPoolExecutor(2) as pool:
            first = pool.submit(fetch); self.assertTrue(entered.wait(2))
            second = pool.submit(fetch); release.set()
            self.assertEqual([first.result(), second.result()], ['paused', 'paused'])
            self.assertEqual(request.call_count, 1)
        self.assertTrue(ui.google_scholar_global_cooldown(self.storage)['active'])

    def test_http_429_starts_pause_without_network_retry(self):
        with scholar_access.database(self.path), patch.object(ui, 'request_with_retries', side_effect=RuntimeError('HTTP 429 Too Many Requests')) as request:
            with self.assertRaises(ui.GoogleScholarBlockedError): ui.google_scholar_request_with_spacing('GET', 'https://scholar.google.com/citations', max_retries=8)
            self.assertEqual(request.call_args.kwargs['max_retries'], 1)
        self.assertTrue(ui.google_scholar_global_cooldown(self.storage)['active'])

    def test_automatic_budget_and_rest_survive_worker_reentry(self):
        self.add(6)
        now = datetime.now().astimezone()
        with patch.object(work, 'BATCH_SIZE', 2), patch.object(work, 'DAILY_LIMIT', 3), patch.object(ui, 'resolve_google_scholar_candidate_to_identifier', return_value=None) as resolve, patch.object(ui.time, 'sleep'), patch.object(ui, 'google_scholar_request_with_spacing', side_effect=AssertionError('metadata must not contact Scholar')):
            work.run_slice(self.path, now=now)
            self.assertEqual(resolve.call_count, 2)
            self.assertEqual(work.read(self.storage)['used'], 2)
            work.run_slice(self.path, now=now)
            self.assertEqual(resolve.call_count, 2, 'restart respects the saved rest')
            work.run_slice(self.path, now=now + timedelta(minutes=10))
            self.assertEqual(resolve.call_count, 3)
            work.run_slice(self.path, now=now + timedelta(minutes=20))
            self.assertEqual(resolve.call_count, 3)
            state = work.read(self.storage)
            self.assertEqual(state['status'], 'daily_limit')
            self.assertEqual(state['eligible'], 3)
            self.assertEqual(state['waiting_retry'], 3)

    def test_zero_eligible_keeps_retry_reason_and_other_author_can_progress(self):
        a, b = self.add(2)
        p = self.storage.get_paper('p0')
        ui.record_author_monitor_enrichment_attempt(self.storage, 'p0', p, status='unresolved', message='No match')
        self.storage.add_author_monitor_paper(author_monitor_id=b, paper_id='p0')
        with patch.object(ui, 'resolve_google_scholar_candidate_to_identifier', return_value=None) as resolve:
            work.run_slice(self.path)
        self.assertEqual(resolve.call_count, 1)
        state = work.read(self.storage)
        self.assertEqual(state['waiting_retry'], 2)
        self.assertEqual(state['status'], 'waiting_retry')
        self.assertTrue(state['retry_at'])

    def test_reservation_survives_interruption_without_replenishing_quota(self):
        self.add(4)
        with patch.object(work, 'BATCH_SIZE', 2), patch.object(ui, 'run_author_monitor_enrichment_job', side_effect=RuntimeError('shutdown')):
            with self.assertRaises(RuntimeError): work.run_slice(self.path)
        self.assertEqual(work.read(self.storage)['used'], 2)
        self.assertEqual(work.snapshot(self.storage)['status'], 'error')
        ui.AUTHOR_MONITOR_ENRICHMENT_JOBS.clear()  # New process has no memory jobs.
        self.assertEqual(work.snapshot(self.storage)['status'], 'resting')
        with patch.object(ui, 'run_author_monitor_enrichment_job') as run:
            work.run_slice(self.path)
            run.assert_not_called()

    def test_time_slice_yields_between_papers(self):
        self.add(3)
        job = ui.create_author_monitor_enrichment_job(automatic=True)
        with patch.object(ui.time, 'monotonic', side_effect=[0, 121]), patch.object(ui.time, 'sleep'), patch.object(ui, 'resolve_google_scholar_candidate_to_identifier', return_value=None) as resolve:
            ui.run_author_monitor_enrichment_job(job_id=job, db_path=self.path, paper_ids=['p0','p1','p2'], time_budget_seconds=120)
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(ui.get_author_monitor_enrichment_job(job)['current'], 1)
        self.assertFalse(ui.author_monitor_enrichment_marker(self.storage.get_paper('p1')))

    def test_ready_card_cache_avoids_rebuilding_every_paper_on_scope_load(self):
        a, b = self.add(2)
        for row in self.storage.list_author_monitor_card_cache_candidates():
            card = ui.author_monitor_paper_to_api(row)
            self.storage.upsert_author_monitor_card_cache([(row['paper_id'], json.dumps(card), row['card_cache_revision'])])
        with patch.object(ui, 'author_monitor_paper_to_api', side_effect=AssertionError('do not rebuild ready cards')):
            result = ui.author_monitor_snapshot(self.storage, author_monitor_id=a)
        self.assertEqual([p['paper_id'] for p in result['papers']], ['p0'])
        self.assertEqual(result['selectedAuthorId'], a)

    def test_idle_daily_poll_preserves_last_completed_check(self):
        a, b = self.add(0)
        now = datetime.now().astimezone()
        for aid in [a,b]: self.storage.update_author_monitor(aid, last_checked_at=now.isoformat(), status='success')
        previous = {'run_date': now.date().isoformat(), 'checked': 2, 'new_papers': 4, 'finished_at': now.isoformat(), 'results': [{'status':'success'}]}
        self.storage.set_setting(ui.AUTO_AUTHOR_MONITOR_STATUS_SETTING, json.dumps(previous))
        with patch.object(ui, 'refresh_author_monitor_for_db', side_effect=AssertionError('already checked today')):
            result = ui.run_auto_author_monitor_once(self.path, now.date())
        self.assertEqual(result['checked'], 2); self.assertEqual(result['new_papers'], 4)
        self.assertEqual(result['finished_at'], previous['finished_at'])
        self.assertIn('last_scheduler_check_at', result)


if __name__ == '__main__': unittest.main()
