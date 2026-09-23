"""Provider formats, isolated refresh writes and conservative identity review."""
import copy
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from paper_monitor import paper_identity as identity, ui_server as ui
from paper_monitor.storage import Storage


def publication(pid, doi='', raw=None, **fields):
    return dict(paper_id=pid, doi=doi, title='Synthetic coherent order in thin films',
                journal='Synthetic Journal', publication_date='2025-01-01',
                source='fixture', raw={'authors': ['Alice Researcher']} if raw is None else raw,
                **fields)


class AuthorIdentityReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite'
        self.s = Storage(self.path)
        self.addCleanup(self.s.close)
        self.author = self.s.add_author_monitor(dict(
            user_id='test-author', name='Test Author',
            url='https://scholar.google.com/citations?user=test-author'))['id']

    def test_all_provider_author_shapes_read_each_name(self):
        shapes = [
            {'authorships': [{'author': {'display_name': 'Alice Researcher'}},
                            {'raw_author_name': 'Bob Scientist'}]},
            {'author': [{'given': 'Alice', 'family': 'Researcher'},
                        {'given': 'Bob', 'family': 'Scientist'}]},
            {'authors': ['Alice Researcher', 'Bob Scientist']},
            {'authors': 'A Researcher, B Scientist et al.'},
            {'authors': [{'name': 'Alice Researcher'}, {'name': 'Bob Scientist'}]},
            {'creators': [{'givenName': 'Alice', 'familyName': 'Researcher'},
                          {'name': 'Bob Scientist'}]},
        ]
        for shape in shapes:
            for wrapper in ('', 'openalex', 'crossref', 'google_scholar', 'semantic_scholar', 'datacite'):
                with self.subTest(shape=shape, wrapper=wrapper):
                    raw = {wrapper: shape} if wrapper else shape
                    self.assertEqual(Storage._identity_authors({'raw': raw}), {'researcher', 'scientist'})
        self.assertEqual(Storage._identity_authors({'raw': {
            'authorships': [None, {'author': None}, 'invalid'],
            'authors': [None, {}, 123, 'et al.', '...']}}), set())
        self.assertEqual(Storage._identity_authors({'raw': {
            'authors': [{'name': 'Researcher, Alice'}]}}), {'researcher'})

    def legacy_pair(self, raw=None):
        self.s.upsert_paper(publication('article', '10.1234/work', raw=raw))
        self.s.upsert_paper(publication('old-record'))
        self.s.add_library_item(paper_id='article')
        self.s.conn.execute('DROP TRIGGER trg_papers_unique_changed_doi')
        self.s.conn.execute("UPDATE papers SET doi='10.1234/work' WHERE paper_id='old-record'")
        self.s.conn.commit()
        identity.ensure_schema(self.s.conn)

    def incoming_observation(self):
        current = self.s.get_paper('article')
        raw = Storage._paper_raw_dict(current)
        raw['google_scholar'] = {'publication_url':
            'https://scholar.google.com/citations?citation_for_view=test-author:new'}
        return raw

    def test_openalex_and_crossref_duplicate_can_reconcile_with_same_authors(self):
        self.legacy_pair({'authorships': [{'author': {'display_name': 'Alice Researcher'}}]})
        self.s.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id='old-record'",
                            (json.dumps({'author': [{'given': 'Alice', 'family': 'Researcher'}]}),))
        self.s.conn.commit()
        key = self.s.get_paper('article')['storage_key']
        old_key = self.s.get_paper('old-record')['storage_key']
        self.s.update_paper_raw_json('article', self.incoming_observation())
        self.assertEqual(self.s.paper_for_key(old_key)['storage_key'], key)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 1)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM library_items').fetchone()[0], 1)
        self.assertEqual(self.s.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_missing_authors_are_insufficient_evidence_not_metadata_conflict(self):
        self.legacy_pair({})
        before = self.s.get_paper('article')
        with self.assertRaises(identity.IdentityReviewRequired) as error:
            self.s.update_paper_raw_json('article', self.incoming_observation())
        self.assertEqual(error.exception.reasons, ['insufficient_same_work_evidence'])
        self.assertIn('not enough evidence', str(error.exception))
        self.assertIn(before['storage_key'], str(error.exception))
        self.assertEqual(self.s.get_paper('article'), before)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 2)

    def test_original_dataset_title_blocks_false_merge_after_bad_legacy_enrichment(self):
        self.legacy_pair({'authorships': [{'author': {'display_name': 'Alice Researcher'}}]})
        self.s.add_author_monitor_paper(author_monitor_id=self.author, paper_id='old-record',
            scholar_title='Raw data: Synthetic coherent order in thin films')
        self.assertFalse(identity.same_work_evidence(self.s, self.s.get_paper('article'), self.s.get_paper('old-record')))
        self.assertFalse(identity.same_work_evidence(self.s, self.s.get_paper('old-record'), self.s.get_paper('article')))
        with self.assertRaises(identity.IdentityReviewRequired) as error:
            self.s.update_paper_raw_json('article', self.incoming_observation())
        self.assertIn('dataset_article_conflict', error.exception.reasons)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 2)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM paper_aliases').fetchone()[0], 0)

    def test_dataset_cannot_be_enriched_into_article(self):
        dataset = publication('dataset', '10.1234/data')
        dataset['title'] = 'Raw data: Synthetic coherent order in thin films'
        self.s.upsert_paper(dataset)
        before = self.s.get_paper('dataset')
        with self.assertRaises(identity.IdentityReviewRequired):
            self.s.refresh_paper_metadata('dataset', publication('dataset', '10.1234/article'))
        self.assertEqual(self.s.get_paper('dataset'), before)
        self.assertTrue(self.s.upsert_paper(copy.deepcopy(dataset)))
        self.assertTrue(self.s.upsert_paper({'paper_id': 'dataset'}))
        self.assertEqual(self.s.get_paper('dataset')['title'], before['title'])

    def test_dataset_title_does_not_search_for_related_article_doi_or_arxiv(self):
        dataset = publication('dataset')
        dataset['title'] = 'Raw data: Synthetic coherent order in thin films'
        with patch.object(ui, 'search_crossref_publications') as crossref, \
                patch.object(ui, 'semantic_scholar_request') as semantic:
            self.assertIsNone(ui.resolve_google_scholar_candidate_to_doi(dataset))
            self.assertIsNone(ui.resolve_google_scholar_candidate_to_arxiv(dataset))
        crossref.assert_not_called()
        semantic.assert_not_called()
        self.assertEqual(identity.work_kind({'title': 'Ordinary preprint', 'url': 'https://zenodo.org/records/1'}, {}), '')

    def test_final_link_failure_rolls_back_observation_and_new_identifiers(self):
        self.s.upsert_paper(publication('article'))
        before = self.s.get_paper('article')
        candidate = publication('incoming', raw=self.incoming_observation())
        with patch.object(self.s, 'add_author_monitor_paper', side_effect=RuntimeError('write failed')):
            with self.assertRaisesRegex(RuntimeError, 'write failed'):
                ui.save_author_monitor_candidate(self.s, self.author, candidate,
                    ui.paper_from_publication_candidate(candidate),
                    is_scholar=True, provider='', unread=False)
        self.assertEqual(self.s.get_paper('article'), before)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM paper_identifiers').fetchone()[0], 0)
        self.assertFalse(self.s.conn.in_transaction)

    def test_raw_and_semantic_writes_honor_caller_rollback(self):
        self.s.upsert_paper(publication('article'))
        before = self.s.get_paper('article')
        self.s.conn.execute('BEGIN IMMEDIATE')
        self.s.update_paper_raw_json('article', {'authors': ['Bob Scientist']}, commit=False)
        self.s.update_semantic_scholar_enrichment('article', {'citationCount': 10}, commit=False)
        self.s.add_author_monitor_paper(author_monitor_id=self.author, paper_id='article', commit=False)
        self.s.conn.rollback()
        self.assertEqual(self.s.get_paper('article'), before)
        self.assertEqual(self.s.author_monitor_paper_count(self.author), 0)

    def test_refresh_continues_after_conflict_for_each_existing_provider(self):
        self.s.upsert_paper(publication('owner', '10.1234/owner'))
        before = self.s.get_paper('owner')
        bad = publication('incoming', '10.1234/owner', raw={'authors': ['Z Biologist']})
        bad.update(title='Unrelated ocean microbial communities', journal='Marine Biology')
        for provider in ('Google Scholar', 'OpenAlex', 'Semantic Scholar'):
            with self.subTest(provider=provider):
                if provider == 'Google Scholar':
                    author = self.author
                else:
                    profile = dict(source_type='researchgate', source_author_id=provider, user_id=provider,
                        name='Test Author', url='https://www.researchgate.net/profile/Test-'+provider.replace(' ', '-'),
                        openalex_author_id='A123456' if provider == 'OpenAlex' else '',
                        semantic_scholar_author_id='123456')
                    author = self.s.add_author_monitor(profile)['id']
                good = publication('good-'+provider, '10.1234/good-'+provider.replace(' ', '-'))
                candidates = [copy.deepcopy(bad), good]
                with ExitStack() as stack:
                    stack.enter_context(patch('requests.sessions.Session.request', side_effect=AssertionError('Unexpected provider request')))
                    fetch = stack.enter_context(patch.object(ui, 'fetch_google_scholar_profile_payload',
                        return_value={'profile': {}, 'candidates': candidates}))
                    oa_profile = stack.enter_context(patch.object(ui, 'fetch_openalex_author_profile', return_value={}))
                    oa_works = stack.enter_context(patch.object(ui, 'fetch_openalex_author_publications', return_value=candidates))
                    ss_profile = stack.enter_context(patch.object(ui, 'fetch_semantic_scholar_author_profile', return_value={}))
                    ss_works = stack.enter_context(patch.object(ui, 'fetch_semantic_scholar_author_publications', return_value=candidates))
                    result = ui.refresh_author_monitor_for_db(self.path, author, initial=True)
                self.assertEqual(result['status'], 'partial', result)
                self.assertEqual(result['added'], 1)
                self.assertEqual(result['identity_review_count'], 1)
                self.assertIn(bad['title'], result['message'])
                self.assertIn('titles and authors disagree', result['message'])
                self.assertEqual(self.s.get_author_monitor(author)['status'], 'partial')
                self.assertEqual(self.s.get_author_monitor(author)['message'], result['message'])
                self.assertTrue(self.s.get_paper(good['paper_id']))
                self.assertEqual(fetch.call_count, int(provider == 'Google Scholar'))
                self.assertEqual(oa_profile.call_count, int(provider == 'OpenAlex'))
                self.assertEqual(oa_works.call_count, int(provider == 'OpenAlex'))
                self.assertEqual(ss_profile.call_count, int(provider == 'Semantic Scholar'))
                self.assertEqual(ss_works.call_count, int(provider == 'Semantic Scholar'))
        self.assertEqual(self.s.get_paper('owner'), before)
        conflicts = self.s.list_pending_paper_identity_conflicts()
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]['occurrence_count'], 3)
        self.assertEqual(self.s.conn.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_late_identifier_collision_only_skips_one_scholar_publication(self):
        self.legacy_pair({})
        candidate = publication('article', '10.1234/work', raw=self.incoming_observation())
        good = publication('good', '10.1234/next')
        with patch.object(ui, 'fetch_google_scholar_profile_payload',
                          return_value={'profile': {}, 'candidates': [candidate, good]}):
            result = ui.refresh_author_monitor_for_db(self.path, self.author, initial=True)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['added'], 1)
        self.assertIn('not enough evidence', result['message'])
        self.assertEqual(self.s.author_monitor_paper_count(self.author), 1)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 3)
        self.assertEqual(len(self.s.list_pending_paper_identity_conflicts()), 1)

    def test_manual_default_disagreement_preserves_both_records_and_continues(self):
        self.legacy_pair()
        for index, pid in enumerate(('article', 'old-record')):
            self.s.conn.execute('UPDATE papers SET preferred_resource_manual=1,preferred_resource_id=? WHERE paper_id=?',
                                (100 + index, pid))
        self.s.conn.commit()
        before = {pid: self.s.get_paper(pid) for pid in ('article', 'old-record')}
        candidate = publication('article', '10.1234/work', raw=self.incoming_observation())
        with patch.object(ui, 'fetch_google_scholar_profile_payload', return_value={
                'profile': {}, 'candidates': [candidate, publication('good', '10.1234/next')]}):
            result = ui.refresh_author_monitor_for_db(self.path, self.author, initial=True)
        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['added'], 1)
        self.assertIn('Different manual Default files', result['message'])
        for pid, row in before.items():
            self.assertEqual(self.s.get_paper(pid), row)


if __name__ == '__main__':
    unittest.main()
