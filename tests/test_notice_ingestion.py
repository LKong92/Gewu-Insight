"""Monitor notices, transaction isolation and honest cache state on temporary data."""
import copy
import hashlib
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack
from datetime import date
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

import requests

from paper_monitor import monitor, paper_identity, publication_notices as notices, ui_server as ui
from paper_monitor.config import AppConfig, JournalConfig
from paper_monitor.sources import publisher
from paper_monitor.storage import Storage


DAY = date(2026, 9, 29)


def paper(name, title=None):
    return dict(paper_id=name, doi='10.1103/fixture-' + name,
                title=title or 'Synthetic quantum materials ' + name,
                journal='Physical Review A', publication_date=DAY.isoformat(),
                source='fixture', raw={'authors': ['Alice Researcher']})


def notice(name='notice', kind='correction_notice', parent=None):
    value = paper(name, 'Erratum: Synthetic quantum materials')
    value['raw']['publication_notice'] = dict(
        kind=kind, related_dois=[parent['doi']] if parent else [],
        evidence_url='https://example.org/' + name)
    return value


def feed(items):
    return ('''<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
      xmlns="http://purl.org/rss/1.0/"
      xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/">''' + ''.join(
        '<item><title>' + escape(p['title']) + '</title><prism:doi>' + p['doi'] +
        '</prism:doi><prism:publicationDate>' + p['publication_date'] +
        '</prism:publicationDate><link>https://doi.org/' + p['doi'] + '</link></item>'
        for p in items) + '</rdf:RDF>').encode()


class Response:
    def __init__(self, items=(), status=200):
        self.status_code = status
        self.content = feed(items)
        self.headers = {'ETag': 'fixture-etag', 'Last-Modified': 'fixture-date'}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class NoticeIngestionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'monitor.sqlite'
        self.s = Storage(self.path)
        self.addCleanup(self.s.close)
        stack = self.enterContext(ExitStack())
        stack.enter_context(patch('requests.sessions.Session.request',
                                 side_effect=AssertionError('Unexpected network request')))
        stack.enter_context(patch.object(publisher, 'APS_RSS_REQUEST_INTERVAL_SECONDS', 0))
        stack.enter_context(patch.object(publisher, '_APS_RSS_BLOCKED_UNTIL', 0))

    # Python 3.9 compatibility, also ensures patches end before Storage closes.
    def enterContext(self, context):
        value = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        return value

    def sync(self, items, *, parsed=False, force=True):
        with ExitStack() as stack:
            stack.enter_context(patch.object(publisher, 'get_with_local_proxy_fallback',
                                             return_value=Response(items)))
            if parsed:
                stack.enter_context(patch.object(publisher, 'parse_aps_rss_entries',
                                                 return_value=copy.deepcopy(items)))
            return publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra'], force=force)

    def count(self, table):
        return self.s.conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def assert_integrity(self):
        self.assertFalse(self.s.conn.in_transaction)
        self.assertEqual(self.s.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_rss_notice_at_every_position_does_not_stop_later_papers(self):
        for position in range(3):
            with self.subTest(position=position):
                items = [paper('first'), paper('last')]
                items.insert(position, notice())
                result = self.sync(items)
                self.assertEqual(result['status'], 'success', result)
                self.assertEqual(result['entries'], 2)
                self.assertEqual(result['notices'], 1)
                self.assertEqual(result['created'], 2 if position == 0 else 0)
                self.assertEqual(self.count('papers'), 2)
                self.assertEqual(self.count('aps_rss_entries'), 2)
                self.assertEqual(self.count('publication_notices'), 1)
                self.assert_integrity()

    def test_notice_only_feed_and_retry_have_no_paper_identity_or_rss_link(self):
        items = [notice(kind=kind, name=kind) for kind in notices.KINDS]
        for _ in range(2):
            result = self.sync(items, parsed=True)
            self.assertEqual(result['status'], 'success', result)
            self.assertEqual(result['notices'], len(notices.KINDS))
            self.assertEqual(result['entries'], 0)
            self.assertEqual(self.count('papers'), 0)
            self.assertEqual(self.count('paper_identifiers'), 0)
            self.assertEqual(self.count('aps_rss_entries'), 0)
            self.assertEqual(self.count('publication_notices'), len(notices.KINDS))
        self.assert_integrity()

    def test_linked_and_unlabelled_known_notice_preserve_original_and_default(self):
        original = paper('original')
        self.s.upsert_paper(original)
        path = self.path.parent / 'original.pdf'
        content = b'%PDF-1.4\nSynthetic resource bytes\n%%EOF'
        path.write_bytes(content)
        resource = self.s.create_paper_resource(paper_id='original', stored_path=str(path),
            file_type='published_version', kind='pdf', sha256=hashlib.sha256(content).hexdigest())
        self.s.set_preferred_paper_resource('original', resource['id'])
        before = self.s.get_paper('original')
        resource_before = self.s.get_paper_resource(resource['id'])
        event = notice(parent=original)
        self.assertEqual(self.sync([event], parsed=True)['notices'], 1)
        # Later provider observations sometimes omit the notice label/type.
        unlabelled = paper('notice', 'Synthetic updated publication')
        result = self.sync([unlabelled, paper('later')], parsed=True)
        self.assertEqual(result['status'], 'success', result)
        self.assertEqual(result['notices'], 1)
        self.assertEqual(self.count('publication_notices'), 1)
        self.assertEqual(notices.for_paper(self.s, 'original')[0]['status'], 'linked')
        self.assertIsNone(self.s.get_paper('notice'))
        self.assertEqual(self.s.get_paper('original'), before)
        self.assertEqual(self.s.get_paper_resource(resource['id']), resource_before)
        self.assertEqual(self.s.resolve_default_paper_resource('original')['id'], resource['id'])
        self.assertEqual(path.read_bytes(), content)
        self.assert_integrity()

    def seed_conflicting_notice(self):
        original, other = paper('original'), paper('other')
        self.s.upsert_paper(original)
        self.s.upsert_paper(other)
        with paper_identity.transaction(self.s):
            notices.record_for_ingestion(self.s, notice(parent=original))
        before = dict(self.s.conn.execute('SELECT * FROM publication_notices').fetchone())
        return notice(parent=other), before

    def test_notice_relation_conflict_is_partial_and_keeps_previous_evidence(self):
        bad, before = self.seed_conflicting_notice()
        result = self.sync([paper('first'), bad, paper('last')], parsed=True)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['entries'], 2)
        self.assertEqual(result['created'], 2)
        self.assertEqual(len(result['feeds']['pra']['entry_errors']), 1)
        self.assertIn('different article', result['errors'][0])
        self.assertEqual(dict(self.s.conn.execute('SELECT * FROM publication_notices').fetchone()), before)
        self.assert_integrity()

    def test_rss_link_write_failure_rolls_back_only_its_paper_and_identifiers(self):
        write = self.s.record_aps_rss_entries
        def fail_one(slug, items, **kwargs):
            write(slug, items, **kwargs)
            if items[0]['doi'] == paper('broken')['doi']:
                raise sqlite3.IntegrityError('Synthetic RSS index failure')
        with patch.object(self.s, 'record_aps_rss_entries', side_effect=fail_one):
            result = self.sync([paper('first'), paper('broken'), paper('last')], parsed=True)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['created'], 2)
        self.assertEqual(result['entries'], 2)
        self.assertIsNone(self.s.get_paper('broken'))
        self.assertEqual(self.count('aps_rss_entries'), 2)
        self.assertFalse(self.s.conn.execute('SELECT 1 FROM paper_identifiers WHERE paper_id=?', ('broken',)).fetchone())
        self.assert_integrity()

    def test_identity_rejection_does_not_link_a_different_existing_paper(self):
        owner = paper('owner')
        self.s.upsert_paper(owner)
        before = self.s.get_paper('owner')
        bad = paper('bad', 'Unrelated marine microbial communities')
        bad.update(doi=owner['doi'], journal='Marine Biology', raw={'authors': ['Bob Biologist']})
        result = self.sync([bad, paper('last')], parsed=True)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['entries'], 1)
        self.assertEqual(self.s.get_paper('owner'), before)
        self.assertEqual(self.count('aps_rss_entries'), 1)
        self.assert_integrity()

    def test_cached_transport_error_remains_error_and_preserves_old_rows(self):
        self.sync([paper('first')])
        with patch.object(publisher, 'get_with_local_proxy_fallback', side_effect=requests.Timeout('Synthetic timeout')) as request:
            first = publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra'], force=True)
            second = publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra'])
        self.assertEqual(request.call_count, 1)
        for result in (first, second):
            self.assertEqual(result['status'], 'error', result)
            self.assertIn('Synthetic timeout', result['errors'][0])
        self.assertTrue(second['feeds']['pra']['cached'])
        self.assertEqual(self.count('aps_rss_entries'), 1)

    def test_cached_partial_stays_partial_and_retry_requests_the_body(self):
        self.sync([paper('first')])
        bad, _ = self.seed_conflicting_notice()
        self.assertEqual(self.sync([bad, paper('last')], parsed=True)['status'], 'partial')
        with patch.object(publisher, 'get_with_local_proxy_fallback', return_value=Response([paper('last')])) as request:
            cached = publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra'])
            request.assert_not_called()
            self.assertEqual(cached['status'], 'partial', cached)
            self.assertTrue(cached['errors'])
            retried = publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra'], force=True)
            self.assertEqual(retried['status'], 'success', retried)
            headers = request.call_args.kwargs['headers']
            self.assertNotIn('If-None-Match', headers)
            self.assertNotIn('If-Modified-Since', headers)

    def test_304_is_valid_only_after_a_complete_success(self):
        for initial in ('error', 'partial', 'success'):
            with self.subTest(initial=initial):
                self.s.record_aps_rss_feed(journal_slug='pra', journal_name='Physical Review A',
                    status=initial, entry_count=0, etag='old', success=initial == 'success')
                with patch.object(publisher, 'get_with_local_proxy_fallback', return_value=Response(status=304)):
                    result = publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra'], force=True)
                self.assertEqual(result['status'], 'success' if initial == 'success' else 'error', result)

    def test_failed_feed_does_not_stop_the_next_feed(self):
        with patch.object(publisher, 'get_with_local_proxy_fallback',
                          side_effect=[requests.Timeout('Synthetic timeout'), Response([paper('last')])]):
            result = publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra', 'prb'], force=True)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['feeds']['pra']['status'], 'error')
        self.assertEqual(result['feeds']['prb']['status'], 'success')
        self.assertEqual(result['created'], 1)

    def author(self, provider):
        profile = dict(user_id=provider, name='Synthetic Author',
                       url='https://scholar.google.com/citations?user=' + provider)
        if provider != 'Google Scholar':
            profile.update(source_type='researchgate', source_author_id=provider,
                url='https://www.researchgate.net/profile/Synthetic-' + provider.replace(' ', '-'),
                openalex_author_id='A123456' if provider == 'OpenAlex' else '',
                semantic_scholar_author_id='123456')
        return self.s.add_author_monitor(profile)['id']

    def refresh(self, author, items):
        with ExitStack() as stack:
            stack.enter_context(patch.object(ui, 'fetch_google_scholar_profile_payload',
                return_value={'profile': {}, 'candidates': copy.deepcopy(items)}))
            for provider in ('openalex', 'semantic_scholar'):
                stack.enter_context(patch.object(ui, 'fetch_' + provider + '_author_profile', return_value={}))
                stack.enter_context(patch.object(ui, 'fetch_' + provider + '_author_publications',
                    return_value=copy.deepcopy(items)))
            return ui.refresh_author_monitor_for_db(self.path, author, initial=True)

    def test_all_author_providers_continue_after_notice_and_retry_without_duplicates(self):
        for provider in ('Google Scholar', 'OpenAlex', 'Semantic Scholar'):
            with self.subTest(provider=provider):
                author = self.author(provider)
                for run in range(2):
                    result = self.refresh(author, [paper('first'), notice(), paper('last')])
                    self.assertEqual(result['status'], 'success', result)
                    self.assertEqual(result['added'], 2 if run == 0 else 0)
                    self.assertEqual(result['publication_notice_count'], 1)
                    self.assertEqual(self.s.author_monitor_paper_count(author), 2)
                    self.assertEqual(self.count('papers'), 2)
                    self.assertEqual(self.count('publication_notices'), 1)
                    self.assertEqual(self.count('paper_identity_conflicts'), 0)
                    self.assert_integrity()

    def test_author_notice_conflict_remains_partial_and_preserves_saved_relation(self):
        bad, before = self.seed_conflicting_notice()
        result = self.refresh(self.author('Google Scholar'), [paper('first'), bad, paper('last')])
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['added'], 2)
        self.assertEqual(len(result['notice_reviews']), 1)
        self.assertEqual(result['identity_review_count'], 0)
        self.assertEqual(dict(self.s.conn.execute('SELECT * FROM publication_notices').fetchone()), before)
        self.assert_integrity()

    def test_author_link_failure_rolls_back_only_that_entry_and_keeps_accurate_count(self):
        write = Storage.add_author_monitor_paper
        def fail_one(storage, **kwargs):
            result = write(storage, **kwargs)
            if kwargs['paper_id'] == 'broken':
                raise sqlite3.IntegrityError('Synthetic author link failure')
            return result
        author = self.author('Google Scholar')
        with patch.object(Storage, 'add_author_monitor_paper', fail_one):
            result = self.refresh(author, [paper('first'), paper('broken'), paper('last')])
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['added'], 2)
        self.assertEqual(len(result['entry_errors']), 1)
        self.assertEqual(self.s.author_monitor_paper_count(author), 2)
        self.assertIsNone(self.s.get_paper('broken'))
        self.assert_integrity()

    def test_journal_primary_ingestion_still_skips_notice_and_saves_later_paper(self):
        journal = JournalConfig(name='Physical Review A', issns=[], openalex_source_id=None,
                                section_policy='fixture', skip_landing_enrichment=True)
        config = AppConfig(fetch_lookback_days=1, report_days=1, keep_unknown_sections=True,
                           journals=[journal], section_policies={})
        with patch.object(monitor, 'fetch_crossref_journal', return_value=[paper('first'), notice(), paper('last')]):
            result = monitor.fetch_one_journal(config=config, storage=self.s, journal=journal,
                                               start_date=DAY, end_date=DAY, enrich=False)
        self.assertEqual(result['saved'], 2)
        self.assertEqual(self.count('publication_notices'), 1)
        self.assertEqual(self.count('journal_monitor_papers'), 2)
        self.assert_integrity()

    def test_subject_adapter_reports_cached_failure_and_retains_additive_cache(self):
        for has_papers in (False, True):
            with self.subTest(has_papers=has_papers):
                if has_papers:
                    self.sync([paper('first')])
                with patch.object(publisher, 'get_with_local_proxy_fallback', side_effect=requests.Timeout('Synthetic timeout')):
                    publisher.sync_aps_rss_feeds(self.s, journal_slugs=['pra'], force=True)
                def one_feed(storage, **kwargs):
                    return publisher.sync_aps_rss_feeds(storage, journal_slugs=['pra'], **kwargs)
                with patch.object(ui, 'sync_aps_rss_feeds', side_effect=one_feed):
                    items, status, message = ui.local_aps_rss_theme_candidates(self.s,
                        start_date=DAY, end_date=DAY, refresh=True)
                self.assertEqual(status, 'success' if has_papers else 'not_available')
                self.assertEqual(len(items), int(has_papers))
                self.assertIn('Synthetic timeout', message)


if __name__ == '__main__':
    unittest.main()
