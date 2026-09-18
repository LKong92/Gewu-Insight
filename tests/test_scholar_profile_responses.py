"""Offline profile fixtures: usable lists, access pages and bounded recovery."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from paper_monitor import ui_server as ui, author_profile_retry as retry
from tests import test_author_profile_retry as fixtures
from tests.test_author_monitor import paper


URL = 'https://scholar.google.com/citations?user=example'


def article(index=0, tag='tr', title=None):
    return (f'<{tag} class="gsc_a_tr"><td><a class="gsc_a_at" href="/citations?citation_for_view=example:{index}">'
            f'{title or "Paper " + str(index)}</a><div class="gs_gray">A Author</div>'
            '<div class="gs_gray">Nature 12, 1-2</div></td>'
            '<td class="gsc_a_c"><a>42</a></td><td class="gsc_a_y"><span>2026</span></td>'
            f'</{tag}>')


class ScholarResponseTests(unittest.TestCase):
    def fetch(self, *pages, limit=500):
        responses = [SimpleNamespace(text=p, url=URL) for p in pages]
        with patch.object(ui, 'google_scholar_request_with_spacing', side_effect=responses), patch.object(ui.time, 'sleep'):
            return ui.fetch_google_scholar_profile_payload(URL, limit=limit)

    def test_regular_and_non_table_rows_keep_titles_and_citations(self):
        for tag in ('tr', 'div'):
            result = self.fetch('<div id="gsc_prf_in">Author</div>' + article(tag=tag))
            self.assertEqual(len(result['candidates']), 1)
            self.assertEqual(result['candidates'][0]['paper']['title'], 'Paper 0')

    def test_late_challenge_is_not_misreported_as_missing_publications(self):
        html = '<style>' + (' ' * 6000) + '</style><form action="/sorry/index"><div class="g-recaptcha"></div></form>'
        with self.assertRaises(ui.GoogleScholarBlockedError): self.fetch(html)

    def test_paper_title_about_captcha_is_not_a_block(self):
        html = article(title='Learning reCAPTCHA and unusual traffic patterns')
        self.assertFalse(ui.is_google_scholar_block_page(html, URL))
        self.assertEqual(len(self.fetch(html)['candidates']), 1)

    def test_login_consent_and_unexpected_html_are_failures_not_empty_success(self):
        for html in ('<h1>Sign in</h1>', '<form>Before you continue to Google</form>',
                     '<div id="gsc_prf_in">Author</div>', '<tr class="gsc_a_tr"><td>New markup</td></tr>'):
            with self.assertRaises(retry.ProfileResponseError): self.fetch(html)

    def test_explicit_empty_profile_is_valid(self):
        result = self.fetch('<div id="gsc_prf_in">Author</div><table id="gsc_a_b"><tr id="gsc_a_nn"><td>No articles</td></tr></table>')
        self.assertEqual(result['candidates'], [])

    def test_bad_later_page_does_not_commit_incomplete_success(self):
        first = ''.join(article(i) for i in range(100))
        with self.assertRaises(retry.ProfileResponseError): self.fetch(first, '<html>Sign in</html>')
        with self.assertRaises(retry.ProfileResponseError): self.fetch(first, first)

    def test_rate_limit_status_does_not_depend_on_reason_phrase(self):
        for message in ('429 Client Error', 'HTTP 429', 'HTTP 403'):
            self.assertTrue(ui.is_google_scholar_block_error(RuntimeError(message)))


class ProfileRecoveryTests(unittest.TestCase):
    setUp = fixtures.AuthorProfileRetryTests.setUp
    author = fixtures.AuthorProfileRetryTests.author
    run_checks = fixtures.AuthorProfileRetryTests.run_checks
    def test_unreadable_response_preserves_records_and_last_success(self):
        author = self.author(status='success', message='No new publications.')
        self.storage.upsert_paper(paper('kept', 'Saved work', '2026-09-01'))
        self.storage.add_author_monitor_paper(author_monitor_id=author['id'], paper_id='kept')
        before = dict(self.storage.get_paper('kept'))
        with patch.object(ui, 'fetch_google_scholar_profile_payload', side_effect=retry.ProfileResponseError(retry.PROFILE_ERROR)):
            result = ui.refresh_author_monitor_for_db(self.path, author['id'])
        self.assertTrue(result['profile_retryable'])
        self.assertFalse(result['network_retryable'])
        saved = self.storage.get_author_monitor(author['id'])
        self.assertEqual(saved['last_success_at'], author['last_success_at'])
        self.assertEqual(before, dict(self.storage.get_paper('kept')))
        self.assertIn('saved papers retained', ui.author_monitor_to_api(saved)['message'])

    def test_legacy_row_errors_get_bounded_retry_not_a_false_no_papers_message(self):
        author = self.author(message='No publication rows were found on this Scholar profile')
        api = ui.author_monitor_to_api(author)
        self.assertTrue(api['profile_retryable'])
        self.assertFalse(api['network_retryable'])
        self.assertNotIn('No publication rows', api['message'])
        self.author('B', message=author['message'])
        with patch.object(ui, 'refresh_author_monitor_for_db', return_value={'status': 'error', 'profile_retryable': True}) as refresh:
            self.run_checks()
        self.assertEqual(refresh.call_count, 1)

    def test_three_profile_probes_back_off_until_next_daily_check(self):
        author = self.author(message=retry.PROFILE_ERROR)
        self.now = self.now.replace(hour=10)
        for _ in range(3):
            retry.failed(self.storage, author, self.now, profile_error=True)
            state = retry.read(self.storage)
            self.assertFalse(retry.provider_ready(state, author, self.now))
            self.now += timedelta(hours=1)
        self.assertFalse(retry.provider_ready(retry.read(self.storage), author, self.now.replace(hour=23)))
        tomorrow = (self.now + timedelta(days=1)).replace(hour=10)
        self.assertTrue(retry.provider_ready(retry.read(self.storage), author, tomorrow))
        retry.succeeded(self.storage, author)
        self.assertEqual(retry.read(self.storage), {})


if __name__ == '__main__': unittest.main()
