"""Subject notice routing through the real HTTP handler and temporary storage."""
import copy
import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from paper_monitor import paper_identity, publication_notices, ui_server as ui
from paper_monitor.storage import Storage
from paper_monitor.sources import crossref


DAY = date(2026, 9, 29)
GROUP = 'NOTICE_REGRESSION'


def paper(name):
    return dict(paper_id=name, doi='10.5555/subject-' + name,
                title='Synthetic vortex research ' + name, journal='Fixture Journal',
                publication_date=DAY.isoformat(), type='journal-article',
                source='crossref', abstract='Synthetic vortex research.', raw={})


def notice(name='notice', parent=None):
    result = paper(name)
    result['title'] = 'Correction: Synthetic vortex research'
    if parent:
        result['raw']['publication_notice'] = dict(kind='correction_notice',
            related_dois=[parent['doi']], evidence_url='https://example.org/notice')
    return result


class SubjectNoticeIngestionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'subject.sqlite'
        self.s = Storage(self.path)
        self.addCleanup(self.s.close)
        ui.save_custom_theme_groups(self.s, [dict(key=GROUP, name='Vortex', queries=['vortex'], is_custom=True)])
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch('requests.sessions.Session.request',
            side_effect=AssertionError('Unexpected external network request')))
        for name in ('local_arxiv_theme_candidates', 'local_aps_rss_theme_candidates'):
            self.stack.enter_context(patch.object(ui, name, return_value=([], 'empty', '')))
        self.stack.enter_context(patch.object(ui, 'THEME_SOURCE_MIN_INTERVAL_SECONDS', {}))

    def run_sources(self, sources, *, trigger='manual_search'):
        fetchers = [(name, values if callable(values) else lambda *args, values=values: copy.deepcopy(values))
                    for name, values in sources]
        with patch.object(ui, 'theme_source_fetchers', return_value=fetchers):
            return ui.run_theme_monitor(storage=self.s, start_date=DAY, end_date=DAY,
                group_keys=[GROUP], trigger=trigger)

    def results(self):
        return self.s.list_theme_papers(window_start=DAY.isoformat(),
            window_end=DAY.isoformat(), group_keys=[GROUP])

    def count(self, table):
        return self.s.conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def assert_integrity(self):
        self.assertFalse(self.s.conn.in_transaction)
        self.assertEqual(self.s.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def http_search(self, sources):
        path = self.path
        class Handler(ui.PaperMonitorUiHandler):
            configured_db_path = path
            configured_journals = []
            def log_message(self, *args):
                pass
        server = ui.FastLocalThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        fetchers = [(name, values if callable(values) else lambda *args, values=values: copy.deepcopy(values))
                    for name, values in sources]
        with patch.object(ui, 'theme_source_fetchers', return_value=fetchers):
            thread.start()
            try:
                conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                conn.request('POST', '/api/theme-search', json.dumps(dict(
                    from_date=DAY.isoformat(), until_date=DAY.isoformat(), group=GROUP)),
                    headers={'Content-Type': 'application/json', 'X-Gewu-Workspace': server.workspace_access.token})
                response = conn.getresponse()
                data = json.loads(response.read())
                conn.close()
                return response.status, data
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_http_notice_at_each_position_for_all_online_providers(self):
        for source in ('crossref', 'openalex', 'semantic_scholar', 'pubmed'):
            for position in range(3):
                with self.subTest(source=source, position=position):
                    items = [paper('first'), paper('last')]
                    items.insert(position, notice())
                    status, data = self.http_search([(source, items)])
                    self.assertEqual(status, 200, data)
                    self.assertEqual({p['paper_id'] for p in data['papers']}, {'first', 'last'})
                    self.assertEqual(data['summary']['notices'], 1)
                    self.assertEqual(data['summary']['groups'][GROUP]['status'], 'success')
                    self.assertEqual(self.count('publication_notices'), 1)
                    self.assertIsNone(self.s.get_paper('notice'))
                    self.assert_integrity()

    def test_notice_only_http_refresh_is_empty_and_idempotent(self):
        for source in ('crossref', 'openalex', 'semantic_scholar', 'pubmed'):
            with self.subTest(source=source):
                status, data = self.http_search([(source, [notice()])])
                self.assertEqual(status, 200, data)
                self.assertEqual(data['papers'], [])
                self.assertEqual(data['summary']['groups'][GROUP]['status'], 'empty')
                self.assertEqual(self.count('publication_notices'), 1)
                self.assertEqual(self.count('papers'), 0)
                self.assertEqual(self.count('theme_candidates'), 0)
                self.assert_integrity()

    def test_raw_crossref_json_uses_native_parser_and_http_response(self):
        for position in (0, 1, 2, 'all'):
            with self.subTest(position=position):
                values = [paper('first'), paper('last')]
                if position == 'all':
                    values = [notice('notice-a'), notice('notice-b')]
                else:
                    values.insert(position, notice())
                items = [dict(DOI=p['doi'], title=[p['title']],
                    **{'container-title': [p['journal']], 'type': 'journal-article',
                       'published-online': {'date-parts': [[2026, 9, 29]]},
                       'abstract': p['abstract']}) for p in values]
                response = SimpleNamespace(json=lambda: {'message': {'items': items}})
                with patch.object(crossref, 'request_with_retries', return_value=response):
                    status, data = self.http_search([('crossref', ui.search_theme_crossref)])
                self.assertEqual(status, 200, data)
                self.assertEqual(len(data['papers']), 0 if position == 'all' else 2)
                self.assertTrue(all(not p['title'].startswith('Correction:') for p in data['papers']))
                self.assert_integrity()

    def test_cross_source_unlabelled_duplicate_cannot_mask_notice_in_either_order(self):
        unlabelled = paper('notice')
        unlabelled['abstract'] = 'vortex ' * 100
        unlabelled['pdf_url'] = 'https://example.org/fixture.pdf'
        sources = [('openalex', [unlabelled, paper('ordinary')]), ('crossref', [notice()])]
        for values in (sources, list(reversed(sources))):
            result = self.run_sources(values)
            self.assertEqual(result['saved'], 1)
            self.assertEqual([p['paper_id'] for p in self.results()], ['ordinary'])
            self.assertIsNone(self.s.get_paper('notice'))
            self.assert_integrity()

    def test_same_batch_parent_is_linked_and_existing_files_are_preserved(self):
        original = paper('original')
        self.s.upsert_paper(original)
        path = Path(self.tmp.name) / 'original.pdf'
        content = b'%PDF-1.4\nSynthetic protected bytes\n%%EOF'
        path.write_bytes(content)
        resource = self.s.create_paper_resource(paper_id='original', stored_path=str(path),
            kind='pdf', file_type='published_version')
        self.s.set_preferred_paper_resource('original', resource['id'])
        before = self.s.get_paper_resource(resource['id'])
        new_parent = paper('new-parent')
        result = self.run_sources([('crossref', [notice('new-notice', new_parent),
            new_parent, notice('old-notice', original)])])
        self.assertEqual(result['notices'], 2)
        for parent in ('original', 'new-parent'):
            self.assertEqual(publication_notices.for_paper(self.s, parent)[0]['status'], 'linked')
        self.assertEqual(self.s.get_paper_resource(resource['id']), before)
        self.assertEqual(self.s.resolve_default_paper_resource('original')['id'], resource['id'])
        self.assertEqual(path.read_bytes(), content)
        self.assert_integrity()

    def test_rejected_identity_is_excluded_from_both_subject_indexes(self):
        self.s.upsert_paper(paper('owner'))
        rejected = dict(paper('owner'), doi='10.5555/conflicting-identifier',
                        title='Unrelated ocean microbes', journal='Other Journal',
                        url='https://doi.org/' + paper('owner')['doi'])
        self.assertTrue(self.s.paper_identity_conflict_reasons(self.s.get_paper('owner'), rejected))
        result = self.run_sources([('crossref', [paper('first'), rejected, paper('last')])])
        self.assertEqual(result['saved'], 2)
        self.assertEqual(result['groups'][GROUP]['status'], 'partial')
        self.assertEqual({p['paper_id'] for p in self.results()}, {'first', 'last'})
        self.assertEqual(self.count('theme_candidates'), 2)
        self.assert_integrity()

    def test_accepted_canonical_identity_replaces_provider_id(self):
        original = paper('original')
        self.s.upsert_paper(original)
        incoming = dict(original, paper_id='provider-id')
        result = self.run_sources([('crossref', [incoming, notice()])])
        self.assertEqual(result['saved'], 1)
        self.assertEqual([p['paper_id'] for p in self.results()], ['original'])
        self.assert_integrity()

    def test_notice_conflict_is_partial_and_retry_does_not_reuse_failed_cache(self):
        original, other = paper('original'), paper('other')
        self.s.upsert_paper(original)
        self.s.upsert_paper(other)
        with paper_identity.transaction(self.s):
            publication_notices.record_for_ingestion(self.s, notice(parent=original))
        before = dict(self.s.conn.execute('SELECT * FROM publication_notices').fetchone())
        result = self.run_sources([('crossref', [paper('first'), notice(parent=other), paper('last')])])
        self.assertEqual(result['saved'], 2)
        self.assertEqual(result['groups'][GROUP]['status'], 'partial')
        self.assertTrue(result['groups'][GROUP]['failed_tasks'])
        self.assertEqual(dict(self.s.conn.execute('SELECT * FROM publication_notices').fetchone()), before)
        retried = self.run_sources([('crossref', [paper('first'), notice(parent=original), paper('last')])], trigger='automatic')
        self.assertEqual(retried['queries'], 1)
        self.assertEqual(retried['groups'][GROUP]['status'], 'success')
        self.assert_integrity()

    def test_notice_write_error_rolls_back_event_and_retains_good_candidates(self):
        record = publication_notices.record_for_ingestion
        def fail(storage, value):
            record(storage, value)
            raise sqlite3.IntegrityError('Synthetic notice write failure')
        with patch.object(publication_notices, 'record_for_ingestion', side_effect=fail):
            result = self.run_sources([('crossref', [paper('first'), notice(), paper('last')])])
        self.assertEqual(result['saved'], 2)
        self.assertEqual(result['groups'][GROUP]['status'], 'partial')
        self.assertIn('Synthetic notice write failure', ' '.join(result['errors']))
        self.assertEqual(self.count('publication_notices'), 0)
        self.assert_integrity()

    def test_paper_write_error_rolls_back_only_failed_candidate_and_is_retryable(self):
        self.s.conn.execute("""CREATE TRIGGER fail_fixture BEFORE INSERT ON papers
            WHEN NEW.paper_id='broken' BEGIN SELECT RAISE(ABORT, 'Synthetic paper write failure'); END""")
        self.s.conn.commit()
        values = [paper('first'), paper('broken'), notice(), paper('last')]
        result = self.run_sources([('crossref', values)])
        self.assertEqual(result['saved'], 2)
        self.assertEqual(result['groups'][GROUP]['status'], 'partial')
        self.assertIn('Synthetic paper write failure', ' '.join(result['errors']))
        self.assertIsNone(self.s.get_paper('broken'))
        self.assertFalse(self.s.conn.execute('SELECT 1 FROM paper_identifiers WHERE paper_id=?', ('broken',)).fetchone())
        self.assert_integrity()
        self.s.conn.execute('DROP TRIGGER fail_fixture')
        self.s.conn.commit()
        retry = self.run_sources([('crossref', values)], trigger='automatic')
        self.assertEqual(retry['queries'], 1)
        self.assertEqual(retry['saved'], 3)
        self.assert_integrity()

    def test_legacy_notice_result_is_hidden_without_deleting_saved_data(self):
        legacy = notice()
        # Reproduce a pre-guard row in temporary storage only.
        with patch.object(publication_notices, 'guard'):
            self.s.upsert_paper(legacy)
        self.s.record_theme_result(paper_id='notice', group_key=GROUP, group_name='Vortex',
            query='vortex', score=1, hits=['vortex'], window_start=DAY.isoformat(), window_end=DAY.isoformat())
        before = self.s.get_paper('notice')
        self.assertEqual(self.results(), [])
        self.assertEqual(self.s.get_paper('notice'), before)
        self.assertEqual(self.count('theme_results'), 1)
        self.assert_integrity()

    def test_successful_cache_and_storage_reopen_keep_only_ordinary_subject_cards(self):
        self.run_sources([('crossref', [paper('first'), notice(), paper('last')])])
        cached = self.run_sources([('crossref', [])], trigger='automatic')
        self.assertEqual(cached['queries'], 0)
        self.assertEqual(cached['saved'], 2)
        reopened = Storage(self.path)
        try:
            values = reopened.list_theme_papers(window_start=DAY.isoformat(),
                window_end=DAY.isoformat(), group_keys=[GROUP])
            self.assertEqual({p['paper_id'] for p in values}, {'first', 'last'})
            self.assertEqual(reopened.conn.execute('SELECT count(*) FROM publication_notices').fetchone()[0], 1)
        finally:
            reopened.close()
        self.assert_integrity()


if __name__ == '__main__':
    unittest.main()
