"""Publication lifecycle checks use synthetic HTTP payloads and temporary files."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from paper_monitor import notice_discovery as discovery, publication_notices as notices
from paper_monitor import metadata_refresh, ui_server as ui
from tests import test_ai_access, test_metadata_refresh

ORIGINAL = '10.5555/original'


def raw_notice(doi='10.5555/notice', kind='retraction', targets=(ORIGINAL,)):
    return {'DOI': doi, 'title': ['Publisher update'], 'container-title': ['Fixture Journal'],
            'published': {'date-parts': [[2026, 10, 2]]}, 'type': 'journal-article',
            'URL': 'https://doi.org/' + doi,
            'update-to': [{'DOI': parent, 'type': kind} for parent in targets]}


class NoticeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_ai_access.AIAccessTests()
        self.fixture.setUp(); self.addCleanup(self.fixture.tearDown)
        self.s = self.fixture.storage
        self.s.conn.execute('UPDATE papers SET doi=? WHERE paper_id="one"', (ORIGINAL,))
        self.s.conn.commit()
        self.parent = self.s.get_paper('one')
        self.file = self.s.get_paper_resource(self.fixture.pdf['id'])
        self.bytes = Path(self.file['stored_path']).read_bytes()
        guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Unmocked network'))
        guard.start(); self.addCleanup(guard.stop)

    def assert_preserved(self):
        parent = self.s.get_paper('one')
        for key in ('paper_id', 'storage_key', 'doi', 'title', 'primary_resource_id', 'preferred_resource_id'):
            self.assertEqual(parent[key], self.parent[key], key)
        self.assertEqual(self.s.get_paper_resource(self.file['id']), self.file)
        self.assertEqual(Path(self.file['stored_path']).read_bytes(), self.bytes)
        self.assertFalse(self.s.conn.execute('PRAGMA foreign_key_check').fetchall())

    def seed(self, raw=None):
        paper = discovery.normalized(raw or raw_notice())
        event = notices.record_for_ingestion(self.s, paper)
        self.s.conn.commit()
        return event

    def test_exact_reverse_lookup_rechecks_direction_and_skips_original(self):
        items = [raw_notice(), raw_notice('10.5555/unrelated', targets=('10.5555/elsewhere',)),
                 raw_notice(ORIGINAL, targets=(ORIGINAL,)),
                 {'DOI': '10.5555/article', 'title': ['Ordinary article'], 'is_retracted': True}]
        with patch.object(discovery, 'request_with_retries', return_value=SimpleNamespace(json=lambda: {'message': {'items': items, 'total-results': 4}})) as request:
            found = discovery.fetch_updates(ORIGINAL)
        self.assertEqual([p['doi'] for p in found], ['10.5555/notice'])
        self.assertEqual(request.call_args.kwargs['params']['filter'], 'updates:' + ORIGINAL)
        self.assertEqual(request.call_args.kwargs['max_retries'], 1)

    def test_incomplete_and_malformed_lookup_are_not_empty_success(self):
        for message in ({'items': [], 'total-results': 101}, {}, None):
            with self.subTest(message=message), patch.object(discovery, 'request_with_retries', return_value=SimpleNamespace(json=lambda: {'message': message})):
                with self.assertRaises(ValueError): discovery.fetch_updates(ORIGINAL)

    def test_refresh_retains_event_without_new_identity_and_repeats_idempotently(self):
        update = discovery.normalized(raw_notice())
        for expected in (1, 0):
            added, errors = discovery.retain_updates(self.s, self.parent, [update])
            self.assertEqual(len(added), expected); self.assertEqual(errors, [])
            self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 3)
            self.assertEqual(len(notices.for_paper(self.s, 'one')), 1)
            self.assert_preserved()

    def test_pending_relation_is_completed_after_original_is_available(self):
        self.s.conn.execute('UPDATE papers SET doi="" WHERE paper_id="one"'); self.s.conn.commit()
        event = self.seed()
        self.assertIsNone(self.s.conn.execute('SELECT paper_id FROM publication_notices WHERE id=?', (event,)).fetchone()[0])
        self.s.conn.execute('UPDATE papers SET doi=? WHERE paper_id="one"', (ORIGINAL,)); self.s.conn.commit()
        added, errors = discovery.retain_updates(self.s, self.parent, [discovery.normalized(raw_notice())])
        self.assertEqual(added, [event]); self.assertEqual(errors, [])
        self.assert_preserved()

    def test_multiple_targets_are_retained_for_review_without_guess(self):
        added, errors = discovery.retain_updates(self.s, self.parent, [discovery.normalized(raw_notice(targets=(ORIGINAL, '10.5555/other')))])
        self.assertFalse(added); self.assertTrue(errors)
        self.assertEqual(notices.for_paper(self.s, 'one'), [])
        self.assert_preserved()

    def test_conflicting_notice_does_not_prevent_next_valid_notice(self):
        self.seed()
        updates = [discovery.normalized(raw_notice(kind='correction')),
                   discovery.normalized(raw_notice('10.5555/second', kind='correction'))]
        added, errors = discovery.retain_updates(self.s, self.parent, updates)
        self.assertEqual(len(added), 1); self.assertEqual(len(errors), 1)
        self.assertEqual(notices.for_paper(self.s, 'one')[0]['kind'], 'retraction_notice')
        self.assert_preserved()

    def test_monitor_add_routes_to_original_key_and_paper_files(self):
        event = self.seed()
        for _ in range(2):
            with patch.object(ui, 'reconcile_paper_pdf_storage'), patch.object(ui, 'sync_alias_for_library_item'):
                status, data, _ = self.fixture.request('/api/library/items', {'notice_id': event, 'folder_id': 1, 'snapshot': False}, workspace=True)
            self.assertEqual(status, 200, data)
            self.assertEqual(data['paper']['storage_key'], self.parent['storage_key'])
            self.assertEqual(data['item']['paper_id'], 'one')
            self.assertEqual(data['paper_files'][0]['publication_notices'][0]['id'], event)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 3)
        self.assert_preserved()

    def test_monitor_unresolved_notice_lookup_links_exact_original(self):
        raw = raw_notice(); raw.pop('update-to'); raw['title'] = ['Retraction: Original work']
        event = self.seed(raw)
        with patch.object(discovery, 'fetch_record', return_value=discovery.normalized(raw_notice())) as fetch:
            parent, linked = discovery.resolve_for_library(self.s, event_id=event)
        self.assertEqual(parent['paper_id'], 'one'); self.assertEqual(linked, event)
        fetch.assert_called_once_with('10.5555/notice')
        self.assert_preserved()

    def test_missing_original_is_imported_as_metadata_only_not_notice_identity(self):
        event = self.seed(raw_notice(targets=('10.5555/new-original',)))
        original = discovery.normalized({'DOI': '10.5555/new-original', 'title': ['Verified original'], 'container-title': ['Fixture Journal']})
        with patch.object(discovery, 'fetch_record', return_value=original):
            parent, linked = discovery.resolve_for_library(self.s, event_id=event)
        self.assertEqual(parent['doi'], '10.5555/new-original'); self.assertTrue(parent['storage_key'])
        self.assertEqual(self.s.list_paper_resources(parent['paper_id'], ensure_primary=False), [])
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 4)
        self.assertEqual(linked, event); self.assert_preserved()

    def test_monitor_rows_have_no_independent_identity(self):
        event = self.seed()
        rows = discovery.for_monitor_date(self.s, '2026-10-02', ['Fixture Journal'], field_classifier=ui.classify_fields)
        self.assertEqual(rows[0]['id'], event)
        self.assertNotIn('storage_key', rows[0])
        self.assertEqual(rows[0]['paper_id'], 'one')  # the original, never the notice
        self.assertEqual(discovery.for_monitor_date(self.s, '2026-10-01', ['Fixture Journal'], field_classifier=ui.classify_fields), [])
        self.assertEqual(discovery.for_monitor_date(self.s, '2026-10-02', ['Other Journal'], field_classifier=ui.classify_fields), [])

    def test_monitor_fields_follow_linked_original_or_unresolved_evidence(self):
        self.s.conn.execute('UPDATE papers SET title=?,abstract=?,journal=? WHERE paper_id="one"',
                            ('Quantum entanglement', '', 'Fixture Journal'))
        self.s.conn.commit()
        linked = self.seed()
        raw = raw_notice('10.5555/unresolved', targets=('10.5555/missing',))
        raw['title'] = ['Correction: Polymer materials']
        unresolved = self.seed(raw)
        before = self.s.conn.total_changes
        rows = discovery.for_monitor_date(self.s, '2026-10-02', ['Fixture Journal'], field_classifier=ui.classify_fields)
        by_id = {row['id']: row for row in rows}
        self.assertEqual(by_id[linked]['fields'], ui.classify_fields(self.s.get_paper('one')))
        self.assertIn('quantum_information', by_id[linked]['fields'])
        self.assertEqual(by_id[unresolved]['fields'], ui.classify_fields(discovery.normalized(raw)))
        self.assertIn('materials', by_id[unresolved]['fields'])
        self.assertIsNone(by_id[unresolved]['paper_id'])
        self.assertEqual(self.s.conn.total_changes, before)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 3)

    def test_unresolved_add_is_an_actionable_error_with_no_identity(self):
        raw = raw_notice(targets=()); raw['title'] = ['Erratum: Unresolved work']
        event = self.seed(raw)
        with patch.object(discovery, 'fetch_record', return_value=discovery.normalized(raw)):
            status, result, _ = self.fixture.request('/api/library/items', {'notice_id':event}, workspace=True)
        self.assertEqual(status, 400, result)
        self.assertIn('original DOI', result['error'])
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 3)
        self.assert_preserved()


class RefreshNoticeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f = test_metadata_refresh.MetadataRefreshTests()
        self.f.setUp(); self.addCleanup(self.f.doCleanups)
        self.f.storage.conn.execute('UPDATE papers SET doi=? WHERE paper_id=?', (test_metadata_refresh.DOI, self.f.pid))
        self.f.storage.conn.commit()

    def test_full_quick_and_periodic_checks_retain_updates(self):
        update = discovery.normalized(raw_notice(targets=(test_metadata_refresh.DOI,)))
        for mode in ('full', 'quick', 'automatic'):
            with patch.object(discovery, 'fetch_updates', return_value=[update]) as fetch:
                result = self.f.refresh(mode=mode)
            fetch.assert_called_once_with(test_metadata_refresh.DOI)
            self.assertEqual(result['metadata_refresh']['sources']['Crossref publication updates'], 'found')
            self.assertEqual(len(notices.for_paper(self.f.storage, self.f.pid)), 1)
            self.assertEqual(self.f.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 1)

    def test_update_network_failure_is_partial_and_preserves_known_retraction(self):
        discovery.retain_updates(self.f.storage, self.f.storage.get_paper(self.f.pid), [discovery.normalized(raw_notice(targets=(test_metadata_refresh.DOI,)))])
        with patch.object(discovery, 'fetch_updates', side_effect=RuntimeError('offline')):
            result = self.f.refresh()
        self.assertEqual(result['metadata_refresh']['status'], 'partial')
        self.assertEqual(result['metadata_refresh']['sources']['Crossref publication updates'], 'unavailable')
        self.assertEqual(len(notices.for_paper(self.f.storage, self.f.pid)), 1)


if __name__ == '__main__':
    unittest.main()
