"""Discovery read acknowledgements use temporary SQLite and loopback HTTP only."""
import unittest
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage
from tests import test_ai_access


class MonitorUnreadSelectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_ai_access.AIAccessTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.s = self.fixture.storage
        self.fixture.server.RequestHandlerClass.configured_journals = ['Fixture Journal']
        journals = patch.object(self.fixture.server.RequestHandlerClass, 'refresh_journals')
        journals.start(); self.addCleanup(journals.stop)
        self.day = '2026-09-30'
        self.s.conn.execute("UPDATE papers SET source='crossref', publication_date=?, "
                            "first_seen_at='2026-10-01T08:00:00', section_allowed=1", (self.day,))
        self.s.conn.commit()
        ui.save_custom_theme_groups(self.s, [dict(key='READING', name='Reading', queries=['quantum'], is_custom=True)])
        for pid in ('one', 'two', 'outside'):
            self.s.record_theme_result(paper_id=pid, group_key='READING', group_name='Reading',
                query='quantum', score=1, hits=['quantum'], window_start=self.day, window_end=self.day)
        self.before = [tuple(row) for row in self.s.conn.execute('SELECT * FROM papers ORDER BY paper_id')]
        guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected network'))
        guard.start(); self.addCleanup(guard.stop)

    def report(self, subject=False):
        url = ('/api/theme-report' if subject else '/api/report') + '?date=' + self.day + '&auto_fetch=0&group=READING'
        status, result, _ = self.fixture.request(url, workspace=True)
        self.assertEqual(status, 200, result)
        return {p['paper_id']: p['late_arrival_unread'] for p in result['papers']}

    def test_viewing_reports_is_read_only_and_only_acknowledged_paper_persists(self):
        for subject in (False, True):
            self.assertEqual(self.report(subject), dict(one=True, two=True, outside=True))
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM paper_reads').fetchone()[0], 0)
        status, result, _ = self.fixture.request('/api/papers/late-arrivals/seen',
            {'paper_ids': ['two']}, workspace=True)
        self.assertEqual(status, 200, result)
        for subject in (False, True):
            self.assertEqual(self.report(subject), dict(one=True, two=False, outside=True))
        reopened = Storage(self.fixture.path)
        try:
            rows = [reopened.get_paper(pid) for pid in ('one', 'two', 'outside')]
            ui.annotate_late_arrival_read_status(reopened, rows)
            self.assertEqual([ui.theme_paper_to_api(p)['late_arrival_unread'] for p in rows], [True, False, True])
            self.assertEqual([r['paper_id'] for r in reopened.conn.execute('SELECT * FROM paper_reads')], ['two'])
        finally:
            reopened.close()
        self.assertEqual([tuple(row) for row in self.s.conn.execute('SELECT * FROM papers ORDER BY paper_id')], self.before)
        self.assertFalse(self.s.conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_search_and_cached_subject_report_share_read_records(self):
        self.s.mark_late_arrivals_seen(['one'])
        with patch.object(ui, 'run_theme_monitor', return_value={'saved': 3}):
            status, result, _ = self.fixture.request('/api/theme-search',
                {'from_date': self.day, 'until_date': self.day, 'group': 'READING'}, workspace=True)
        self.assertEqual(status, 200, result)
        self.assertEqual({p['paper_id']: p['late_arrival_unread'] for p in result['papers']},
                         self.report(True))

    def test_same_day_old_and_invalid_dates_do_not_acquire_unread_flags(self):
        rows = [dict(paper_id=str(i), publication_date=day, first_seen_at=seen)
                for i, (day, seen) in enumerate([
                    ('2026-10-01', '2026-10-01'), ('2001-01-01', '2026-10-01'),
                    ('invalid', '2026-10-01'), ('2026-09-30', '2026-10-01')])]
        ui.annotate_late_arrival_read_status(self.s, rows)
        self.assertEqual([r['late_arrival_unread'] for r in rows], [False, False, False, True])


if __name__ == '__main__':
    unittest.main()
