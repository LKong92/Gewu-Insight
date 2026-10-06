"""Explicit corrections use temporary SQLite and mocked source responses only."""
import copy
import json
import unittest
from pathlib import Path
import test_metadata_refresh as fixtures
from test_metadata_refresh import DOI, published, preprint
from paper_monitor import metadata_refresh as work, ui_server as ui


class IdentifierCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.MetadataRefreshTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.s = self.fixture.storage
        self.pid = 'synthetic_wrong_book'
        self.wrong = {'paper_id': self.pid, 'doi': '10.1234/wrong-book',
                      'title': 'Bookkeeping for marine creatures', 'journal': 'History of accounting',
                      'publication_date': '2013-01-01', 'abstract': 'Wrong abstract',
                      'source': 'crossref', 'url': 'https://doi.org/10.1234/wrong-book',
                      'raw': {'DOI': '10.1234/wrong-book', 'author': [{'family': 'Wrong', 'given': 'Z'}],
                              'volume': 'OLD', 'issue': 'OLD', 'counts_by_year': [{'year': 2013, 'cited_by_count': 99}],
                              'manual_metadata': {'user_note': 'keep'}, 'user_note': 'keep'}}
        self.s.upsert_paper(self.wrong)

    def correct(self):
        work.save_doi(self.s, self.pid, DOI)
        return work.refresh(self.s, self.pid)

    def test_wrong_bibliography_replaced_but_key_files_default_and_references_preserved(self):
        pdf = Path(self.fixture.tmp.name) / 'synthetic.pdf'
        pdf.write_bytes(b'%PDF-1.4\nsynthetic fixture only')
        res = self.s.create_paper_resource(paper_id=self.pid, stored_path=str(pdf), file_type='published', annotation_state='annotated', file_source='user_import')
        self.s.set_preferred_paper_resource(self.pid, res['id'])
        self.s.add_library_item(paper_id=self.pid)
        before = self.s.get_paper(self.pid)
        tables = {t: [tuple(r) for r in self.s.conn.execute('SELECT * FROM ' + t)] for t in ('resources', 'library_items')}
        result = self.correct(); paper = result['paper']; raw = ui.parse_raw_json(paper)
        self.assertEqual(paper['title'], published()['title'])
        self.assertEqual(ui.full_author_names(paper), ['A Researcher'])
        self.assertEqual(paper['doi'], DOI)
        self.assertFalse(raw.get('issue'))
        self.assertFalse(raw.get('counts_by_year'))
        self.assertEqual(raw['user_note'], 'keep')
        self.assertEqual(raw['manual_metadata'], {'user_note': 'keep'})
        self.assertEqual(raw['manual_identifier_metadata_history'][0]['metadata']['title'], self.wrong['title'])
        self.assertEqual(raw['manual_identifier_correction']['status'], 'applied')
        for field in ('paper_id', 'storage_key', 'preferred_resource_id', 'preferred_resource_manual', 'main_pdf_path', 'merged_pdf_path'):
            self.assertEqual(paper[field], before[field], field)
        for t, rows in tables.items():
            self.assertEqual(rows, [tuple(r) for r in self.s.conn.execute('SELECT * FROM ' + t)])
        self.assertEqual(pdf.read_bytes(), b'%PDF-1.4\nsynthetic fixture only')
        again = work.refresh(self.s, self.pid)
        self.assertEqual(len(ui.parse_raw_json(again['paper'])['manual_identifier_metadata_history']), 1)
        self.assertFalse(self.s.conn.execute('PRAGMA foreign_key_check').fetchall())

    def test_saved_by_previous_version_can_be_corrected_without_retyping(self):
        raw = copy.deepcopy(self.wrong['raw'])
        raw.update(manual_doi_identifier_override=True, manual_doi_identifier=DOI,
                   manual_doi_identifier_updated_at='2026-09-11T12:00:00+08:00')
        self.s.conn.execute('UPDATE papers SET doi=?,raw_json=? WHERE paper_id=?', (DOI, json.dumps(raw), self.pid))
        self.s.conn.commit()
        self.assertEqual(work.refresh(self.s, self.pid)['paper']['title'], published()['title'])

    def test_clear_then_retype_is_still_a_correction(self):
        work.save_doi(self.s, self.pid, '')
        self.assertEqual(self.correct()['paper']['title'], published()['title'])

    def test_matching_record_missing_keeps_old_information_and_pending_intent(self):
        self.fixture.mocks['publication_metrics_metadata_from_doi'].side_effect = lambda *a, **k: None
        result = self.correct()
        self.assertEqual(result['paper']['doi'], DOI)
        self.assertEqual(result['paper']['title'], self.wrong['title'])
        self.assertEqual(ui.parse_raw_json(result['paper'])['manual_identifier_correction']['status'], 'pending')
        self.assertIn('Identifier saved', ' '.join(result['metadata_refresh']['conflicts']))
        self.fixture.mocks['publication_metrics_metadata_from_doi'].side_effect = lambda *a, **k: published()
        self.assertEqual(work.refresh(self.s, self.pid)['paper']['title'], published()['title'])

    def test_wrong_returned_doi_is_not_accepted_as_manual_correction(self):
        self.fixture.mocks['publication_metrics_metadata_from_doi'].side_effect = lambda *a, **k: published('10.1234/not-requested')
        self.assertEqual(self.correct()['paper']['title'], self.wrong['title'])

    def test_manual_edit_does_not_merge_another_key(self):
        self.s.upsert_paper(published())
        before = self.s.get_paper(self.pid)
        with self.assertRaisesRegex(ValueError, 'another Gewu Key'):
            work.save_doi(self.s, self.pid, DOI)
        self.assertEqual(self.s.get_paper(self.pid), before)

    def test_old_semantic_and_source_ids_do_not_leak_into_corrected_record(self):
        self.s.update_semantic_scholar_enrichment(self.pid, {'externalIds': {'ArXiv': '1801.00001'}, 'citationCount': 999})
        result = self.correct()
        self.assertFalse(ui.parse_semantic_scholar_json(result['paper']))
        self.assertFalse(ui.arxiv_identifier_for_paper(result['paper']))
        self.fixture.mocks['fetch_arxiv_by_id'].assert_not_called()

    def test_arxiv_correction_and_collision_protection(self):
        ui.update_manual_preprint_identifier(self.s, self.pid, '1801.00001')
        ui.update_manual_preprint_identifier(self.s, self.pid, '2201.00001')
        record = preprint(); record['raw']['arxiv_id'] = '2201.00001'; record['title'] = 'Verified corrected preprint'
        self.fixture.mocks['fetch_arxiv_by_id'].side_effect = lambda *a, **k: copy.deepcopy(record)
        result = work.refresh(self.s, self.pid)
        self.assertEqual(result['paper']['title'], record['title'])
        self.assertFalse(result['paper']['doi'])
        self.assertEqual(ui.arxiv_identifier_for_paper(result['paper']), '2201.00001')
        with self.assertRaisesRegex(ValueError, 'another Gewu Key'):
            ui.update_manual_preprint_identifier(self.s, self.pid, '2106.14849')

    def test_later_refresh_still_rejects_unrelated_metadata(self):
        self.correct()
        other = published(); other.update(title='Totally unrelated marine biology', journal='Ocean Life', raw={'DOI': DOI, 'authors': ['Z Ocean']})
        self.fixture.mocks['publication_metrics_metadata_from_doi'].side_effect = lambda *a, **k: other
        self.assertEqual(work.refresh(self.s, self.pid)['paper']['title'], published()['title'])

    def test_old_manual_flag_alone_does_not_disable_automatic_conflict_protection(self):
        raw = self.wrong['raw'].copy()
        raw.update(manual_doi_identifier_override=True, manual_doi_identifier=self.wrong['doi'],
                   manual_doi_identifier_updated_at='2020-01-01T00:00:00+08:00',
                   metadata_refresh={'conflicts': ['Metadata disagrees with existing identity']})
        self.s.update_paper_raw_json(self.pid, raw)
        self.fixture.mocks['publication_metrics_metadata_from_doi'].side_effect = lambda *a, **k: published(self.wrong['doi'])
        self.assertEqual(work.refresh(self.s, self.pid)['paper']['title'], self.wrong['title'])

    def test_folder_quick_uses_the_same_correction_service(self):
        work.save_doi(self.s, self.pid, DOI)
        result = work.refresh(self.s, self.pid, mode='quick', origin='batch', skip_days=3)
        self.assertEqual(result['paper']['title'], published()['title'])
        self.assertEqual(result['metadata_refresh']['mode'], 'quick')

    def test_concurrent_identifier_edit_invalidates_old_result(self):
        def fetch(*a, **k):
            work.save_doi(self.s, self.pid, '10.1234/third')
            return published()
        self.fixture.mocks['publication_metrics_metadata_from_doi'].side_effect = fetch
        with self.assertRaisesRegex(ValueError, 'Identifiers changed'):
            self.correct()
        self.assertEqual(self.s.get_paper(self.pid)['doi'], '10.1234/third')
        self.assertEqual(self.s.get_paper(self.pid)['title'], self.wrong['title'])
