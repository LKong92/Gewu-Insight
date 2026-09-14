import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

from paper_monitor import ui_server as ui, author_profile_retry as retry
from paper_monitor.storage import Storage
from tests.test_author_monitor import scholar_profile, paper


DNS_ERROR = "HTTPSConnectionPool: NameResolutionError: Failed to resolve 'scholar.google.com'"


class AuthorProfileRetryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'retry.sqlite'
        self.storage = Storage(self.path)
        self.addCleanup(self.storage.close)
        self.now = datetime(2026, 9, 15, 0, 30, tzinfo=timezone(timedelta(hours=8)))

    def author(self, name='A', *, status='error', message=DNS_ERROR, age=15):
        row = self.storage.add_author_monitor(scholar_profile(name, name))
        self.storage.update_author_monitor(row['id'], status=status, message=message,
            last_checked_at=(self.now - timedelta(minutes=age)).isoformat(),
            last_success_at=(self.now - timedelta(days=1)).isoformat())
        return self.storage.get_author_monitor(row['id'])

    def run_checks(self, *, retry_only=True):
        return ui.run_auto_author_monitor_once(self.path, self.now.date(), retry_only=retry_only, now=self.now)

    def test_legacy_network_error_retries_before_daily_start(self):
        a = self.author()
        self.author('B', status='success', message='No new publications.', age=90)
        self.author('C', status='idle', message='', age=90)
        with patch.object(ui, 'refresh_author_monitor_for_db', return_value={'status':'success'}) as refresh:
            self.run_checks()
        refresh.assert_called_once_with(self.path, a['id'], initial=False, force=False)

    def test_failed_today_is_retried_but_success_today_is_not(self):
        self.now = self.now.replace(hour=15)
        a = self.author()
        self.author('B', status='success', message='No new publications.')
        with patch.object(ui, 'refresh_author_monitor_for_db', return_value={'status':'success'}) as refresh:
            self.run_checks(retry_only=False)
        self.assertEqual([call.args[1] for call in refresh.call_args_list], [a['id']])

    def test_recent_failure_waits_before_retry(self):
        self.author(age=2)
        with patch.object(ui, 'refresh_author_monitor_for_db') as refresh:
            self.run_checks()
        refresh.assert_not_called()

    def test_retry_batch_is_bounded_and_preserves_scholar_spacing(self):
        for name in 'ABCDE': self.author(name)
        with patch.object(ui, 'refresh_author_monitor_for_db', return_value={'status':'success'}) as refresh, patch.object(ui.time, 'sleep') as sleep:
            self.run_checks()
        self.assertEqual(refresh.call_count, retry.BATCH_SIZE)
        self.assertEqual(sleep.call_count, retry.BATCH_SIZE - 1)
        for call in sleep.call_args_list:
            self.assertGreaterEqual(call.args[0], ui.AUTO_AUTHOR_MONITOR_STAGGER_MIN_SECONDS)

    def test_one_failed_probe_stops_other_authors_on_same_provider(self):
        for name in 'ABC': self.author(name)
        with patch.object(ui, 'refresh_author_monitor_for_db', return_value={'status':'error','network_retryable':True}) as refresh:
            self.run_checks()
        self.assertEqual(refresh.call_count, 1)

    def test_persistent_provider_backoff_increases_and_success_resets_it(self):
        a = self.author()
        for delay in [300,900,3600,3600]:
            retry.failed(self.storage, a, self.now)
            reopened = Storage(self.path)
            try: state = retry.read(reopened)
            finally: reopened.close()
            self.assertFalse(retry.due(state,a,self.now + timedelta(seconds=delay-1)))
            self.assertTrue(retry.due(state,a,self.now + timedelta(seconds=delay)))
        with patch.object(ui, 'refresh_author_monitor_for_db') as refresh: self.run_checks()
        refresh.assert_not_called()
        retry.succeeded(self.storage,a)
        self.assertTrue(retry.due(retry.read(self.storage),a,self.now))

    def test_backoff_also_protects_unchecked_daily_authors(self):
        a = self.author()
        self.author('B',status='idle',message='',age=24*60)
        retry.failed(self.storage,a,self.now)
        with patch.object(ui,'refresh_author_monitor_for_db') as refresh: self.run_checks(retry_only=False)
        refresh.assert_not_called()

    def test_global_and_per_author_access_cooldowns_still_win(self):
        a = self.author()
        pause = {'until':(self.now+timedelta(hours=24)).isoformat()}
        with patch.object(ui,'google_scholar_global_cooldown',return_value={'active':True,**pause}), patch.object(ui,'refresh_author_monitor_for_db') as refresh:
            self.run_checks()
        refresh.assert_not_called()
        with patch.object(ui,'author_monitor_cooldown_active',return_value=True), patch.object(ui,'refresh_author_monitor_for_db') as refresh:
            self.run_checks()
        refresh.assert_not_called()

    def test_identity_certificate_and_access_errors_do_not_auto_retry(self):
        for i,message in enumerate(['Existing papers and files were preserved: metadata conflicts',
                'CERTIFICATE_VERIFY_FAILED', 'HTTP 403 Forbidden', 'HTTP 429 Too Many Requests', 'recaptcha']):
            self.assertFalse(retry.network_failure(message))
            self.author(str(i),message=message)
        with patch.object(ui,'refresh_author_monitor_for_db') as refresh: self.run_checks()
        refresh.assert_not_called()

    def test_retry_state_tolerates_malformed_legacy_values(self):
        a = self.author()
        for entry in ['old', {'failures': 'unknown'}, {'failures': -100}]:
            self.storage.set_setting(retry.SETTING,json.dumps({'google_scholar':entry}))
            self.assertTrue(retry.due(retry.read(self.storage),a,self.now))
            retry.failed(self.storage,a,self.now)
            self.assertEqual(retry.read(self.storage)['google_scholar']['failures'],1)

    def test_new_transport_failure_is_durable_and_preserves_saved_collection(self):
        a=self.author(status='success',message='No new publications.')
        self.storage.upsert_paper(paper('kept','Existing paper','2026-09-01'))
        self.storage.add_author_monitor_paper(author_monitor_id=a['id'],paper_id='kept')
        original=dict(self.storage.get_paper('kept'))
        with patch.object(ui,'fetch_google_scholar_profile_payload',side_effect=requests.ConnectionError('offline')):
            result=ui.refresh_author_monitor_for_db(self.path,a['id'])
        saved=self.storage.get_author_monitor(a['id'])
        self.assertTrue(result['network_retryable'])
        self.assertTrue(retry.retryable(saved))
        self.assertEqual(saved['last_success_at'],a['last_success_at'])
        self.assertEqual(dict(self.storage.get_paper('kept')),original)
        self.assertEqual(self.storage.author_monitor_paper_count(a['id']),1)
        self.assertTrue(retry.read(self.storage)['google_scholar']['retry_at'])
        with patch.object(ui,'fetch_google_scholar_profile_payload',return_value={'candidates':[],'profile':scholar_profile('A','A')}):
            result=ui.refresh_author_monitor_for_db(self.path,a['id'])
        saved=self.storage.get_author_monitor(a['id'])
        self.assertEqual(result['status'],'success')
        self.assertFalse(retry.retryable(saved))
        self.assertEqual(retry.read(self.storage),{})
        self.assertEqual(self.storage.author_monitor_paper_count(a['id']),1)
        with patch.object(ui,'refresh_author_monitor_for_db') as refresh: self.run_checks()
        refresh.assert_not_called()

    def test_api_short_status_retains_original_error_in_details(self):
        a=self.author()
        api=ui.author_monitor_to_api(a)
        self.assertTrue(api['network_retryable'])
        self.assertEqual(api['error_detail'],DNS_ERROR)
        self.assertNotIn('HTTPSConnectionPool',api['message'])
        self.assertEqual(api['message'],'Google Scholar temporarily unavailable')


if __name__ == '__main__': unittest.main()
