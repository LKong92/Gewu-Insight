"""Identity writes and reconciliation use synthetic records and temporary SQLite."""
import copy
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from paper_monitor import paper_identity as identity, ui_server as ui, ai_service, ai_store
from paper_monitor.storage import Storage


def paper(pid, doi=''):
    return dict(paper_id=pid, doi=doi, title='d-wave instability in a synthetic thin film',
                journal='Synthetic Journal', publication_date='2025', source='fixture',
                raw={'authors': ['A Researcher']})


class PaperIdentityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'test.sqlite'
        self.s = Storage(self.path)
        self.addCleanup(self.s.close)

    def author(self, name):
        return self.s.add_author_monitor(dict(user_id=name, name=name,
            url='https://scholar.google.com/citations?user='+name))['id']

    def test_same_doi_creation_reuses_identity_and_old_id(self):
        a, b = paper('one', '10.1234/work'), paper('two', 'https://doi.org/10.1234/WORK')
        self.assertTrue(self.s.upsert_paper(a))
        self.assertTrue(self.s.upsert_paper(b))
        self.assertEqual(b['paper_id'], 'one')
        self.assertEqual(self.s.get_paper('two')['paper_id'], 'one')
        self.s.add_library_item(paper_id='two')
        self.assertEqual(self.s.conn.execute('SELECT paper_id FROM library_items').fetchone()[0], 'one')
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 1)

    def test_key_and_alias_lookup_do_not_scan_unrelated_papers(self):
        self.s.upsert_paper(paper('owner'))
        key = self.s.get_paper('owner')['storage_key']
        identity.add_alias(self.s, 'gw_old_key', 'owner')
        self.s.conn.executemany('''INSERT INTO papers
            (paper_id,storage_key,title,journal,first_seen_at,last_seen_at)
            VALUES(?,?,'Unrelated fixture','Synthetic Journal','2025','2025')''',
            [(f'unrelated_{n}',f'gw_unrelated_{n}') for n in range(1000)])
        self.s.conn.commit()
        for requested in (key, 'gw_old_key', 'gw_absent'):
            steps = [0]
            def limit_work():
                steps[0] += 1
                return steps[0] > 500
            self.s.conn.set_progress_handler(limit_work, 1)
            try:
                result = self.s.paper_for_key(requested)
                self.assertEqual(result['paper_id'] if result else None,
                                 None if requested=='gw_absent' else 'owner')
            finally:
                self.s.conn.set_progress_handler(None, 0)

    def test_later_doi_completion_merges_author_links_and_keeps_other_authors(self):
        self.s.upsert_paper(paper('one', '10.1234/work'))
        self.s.upsert_paper(paper('two'))
        old_key = self.s.get_paper('two')['storage_key']
        a, b = self.author('Author A'), self.author('Author B')
        for aid, pid, unread in ((a,'one',False),(a,'two',True),(b,'two',False)):
            self.s.add_author_monitor_paper(author_monitor_id=aid, paper_id=pid, unread=unread)
        self.s.add_library_item(paper_id='one')
        result = self.s.refresh_paper_metadata('two', paper('two','10.1234/work'))
        self.assertEqual(result['paper_id'], 'one')
        self.assertEqual(self.s.paper_for_key(old_key)['paper_id'], 'one')
        self.assertEqual(len(self.s.list_author_monitor_papers(a)), 1)
        self.assertEqual(len(self.s.list_author_monitor_papers(b)), 1)
        self.assertEqual(self.s.conn.execute('SELECT is_unread FROM author_monitor_papers WHERE author_monitor_id=?',(a,)).fetchone()[0], 1)
        self.assertEqual(self.s.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        history = json.loads(self.s.conn.execute('SELECT snapshot_json FROM paper_identity_history').fetchone()[0])
        self.assertEqual(len(history['source_relationships']['author_monitor_papers']), 2)

    def test_known_doi_with_conflicting_identity_is_rejected_without_merge(self):
        self.s.upsert_paper(paper('one', '10.1234/work'))
        wrong = paper('two','10.1234/work')
        wrong.update(title='Completely unrelated ocean biology', journal='Marine Ecology', raw={'authors':['Z Someone']})
        self.assertFalse(self.s.upsert_paper(wrong))
        self.assertIsNone(self.s.get_paper('two'))
        self.assertEqual(len(self.s.list_pending_paper_identity_conflicts()), 1)

    def test_simultaneous_connections_cannot_create_duplicate_doi(self):
        def write(pid):
            s = Storage(self.path)
            try:
                value = paper(pid,'10.1234/work')
                s.upsert_paper(value)
                return value['paper_id']
            finally:
                s.close()
        with ThreadPoolExecutor(2) as pool:
            ids = list(pool.map(write, ('first','second')))
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 1)

    def test_unreviewed_foreign_key_rolls_back_entire_merge(self):
        self.s.upsert_paper(paper('one','10.1234/work'))
        self.s.upsert_paper(paper('two'))
        self.s.conn.execute('CREATE TABLE future_notes(paper_id TEXT REFERENCES papers(paper_id) ON DELETE CASCADE, note TEXT)')
        self.s.conn.execute("INSERT INTO future_notes VALUES('two','Keep this note')")
        self.s.conn.commit()
        with self.assertRaisesRegex(ValueError, 'Unreviewed paper relationship'):
            self.s.refresh_paper_metadata('two',paper('two','10.1234/work'))
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 2)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM paper_identity_history').fetchone()[0], 0)
        self.assertEqual(self.s.conn.execute('SELECT note FROM future_notes').fetchone()[0], 'Keep this note')

    def test_scholar_pagination_and_title_typography_do_not_duplicate(self):
        profile = dict(user_id='synthetic',name='Synthetic Author',url='https://scholar.google.com/citations?user=synthetic')
        author = self.s.add_author_monitor(profile)
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected network request')):
            for index, title in enumerate(('d-wave instability in a synthetic thin film','D ‐Wave instability in a synthetic thin film')):
                candidate = paper('ignored')
                candidate.pop('paper_id')
                candidate.update(title=title,source='google-scholar',url=f'https://scholar.google.com/citations?citation_for_view=synthetic:work&pagesize={50+index*50}&cstart={index*300}')
                payload = {'profile':profile,'candidates':[{'paper':candidate}]}
                with patch.object(ui,'fetch_google_scholar_profile_payload',return_value=payload):
                    ui.refresh_author_monitor_for_db(self.path,author['id'],initial=index==0)
        self.assertEqual(len(self.s.list_author_monitor_papers(author['id'])), 1)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0], 1)

    def legacy_duplicates(self):
        self.s.upsert_paper(paper('one'))
        self.s.upsert_paper(paper('two'))
        author = self.author('Synthetic Author')
        for pid in ('one','two'):
            self.s.add_author_monitor_paper(author_monitor_id=author,paper_id=pid)
        self.s.conn.execute('DROP TRIGGER trg_papers_unique_changed_doi')
        self.s.conn.execute("UPDATE papers SET doi='10.1234/work'")
        self.s.conn.commit()
        identity.ensure_schema(self.s.conn)
        return author

    def test_historical_plan_is_read_only_then_keeps_files_default_and_grants(self):
        author = self.legacy_duplicates()
        old_key = self.s.get_paper('two')['storage_key']
        self.s.add_my_publication(paper_id='one')
        self.s.add_library_item(paper_id='two')
        self.s.upsert_paper(paper('outside','10.1234/outside'))
        resources = []
        for pid, kind in (('one','preprint'),('two','other')):
            path = Path(self.tmp.name) / (pid+'.md')
            path.write_text('Original note '+pid)
            resources.append(self.s.create_paper_resource(paper_id=pid, stored_path=str(path),file_type=kind,
                file_source='user',annotation_state='unannotated',source_detail='Keep provenance',mime_type='text/markdown'))
        preferred = resources[0]['id']
        self.s.conn.execute('UPDATE papers SET preferred_resource_manual=1,preferred_resource_id=? WHERE paper_id=?',(preferred,'one'))
        self.s.conn.commit()
        before_resources = [dict(r) for r in self.s.conn.execute('SELECT * FROM resources')]
        grant = {'selection': {'kind':'papers','keys':[old_key]},'scopes':['papers:read']}
        before = self.s.conn.total_changes
        plan = identity.reconciliation_plan(self.s)
        self.assertEqual(self.s.conn.total_changes,before)
        self.assertFalse(plan['groups'][0]['blockers'])
        self.assertEqual(identity.apply_reconciliation(self.s,plan),['two'])
        after_resources = [dict(r) for r in self.s.conn.execute('SELECT * FROM resources')]
        self.assertEqual(after_resources,[{**r,'paper_id':'one'} for r in before_resources])
        for r in resources:
            self.assertEqual(Path(r['stored_path']).read_text(),'Original note '+Path(r['stored_path']).stem)
        self.assertEqual(self.s.get_paper('one')['preferred_resource_id'],preferred)
        self.assertEqual(len(self.s.list_author_monitor_papers(author)),1)
        self.assertEqual(ai_service.paper_for_key(self.s,grant,old_key)['paper_id'],'one')
        self.assertEqual(ai_service.paper_for_key(self.s,grant,self.s.get_paper('one')['storage_key'])['paper_id'],'one')
        with self.assertRaises(ai_store.APIError):
            ai_service.paper_for_key(self.s,grant,self.s.get_paper('outside')['storage_key'])

    def test_stale_plan_cannot_overwrite_new_edits(self):
        self.legacy_duplicates()
        plan = identity.reconciliation_plan(self.s)
        self.s.update_paper_raw_json('two',{'authors':['A Researcher'],'user_note':'Added after review'})
        with self.assertRaisesRegex(ValueError,'changed after planning'):
            identity.apply_reconciliation(self.s,plan)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],2)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM paper_identity_history').fetchone()[0],0)

    def test_legacy_feed_membership_survives_and_is_included_in_review(self):
        self.legacy_duplicates()
        self.s.conn.executescript('''
            CREATE TABLE journal_feeds(feed_key TEXT PRIMARY KEY);
            CREATE TABLE journal_feed_entries (
                feed_key TEXT NOT NULL REFERENCES journal_feeds(feed_key) ON DELETE CASCADE,
                paper_id TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
                publication_date TEXT NOT NULL, first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL, PRIMARY KEY(feed_key,paper_id));
            INSERT INTO journal_feeds VALUES('shared'),('source-only');
            INSERT INTO journal_feed_entries VALUES
                ('shared','one','2025','2025-02-01','2025-03-01'),
                ('shared','two','2025','2025-01-01','2025-04-01'),
                ('source-only','two','2025','2025-01-02','2025-03-02');
        ''')
        stale = identity.reconciliation_plan(self.s)
        self.s.conn.execute("UPDATE journal_feed_entries SET last_seen_at='2025-05-01' WHERE paper_id='two' AND feed_key='shared'")
        self.s.conn.commit()
        with self.assertRaisesRegex(ValueError, 'changed after planning'):
            identity.apply_reconciliation(self.s, stale)
        plan = identity.reconciliation_plan(self.s)
        self.assertEqual(identity.apply_reconciliation(self.s, plan), ['two'])
        rows = [tuple(r) for r in self.s.conn.execute('SELECT * FROM journal_feed_entries ORDER BY feed_key')]
        self.assertEqual(rows, [
            ('shared','one','2025','2025-01-01','2025-05-01'),
            ('source-only','one','2025','2025-01-02','2025-03-02')])
        self.assertEqual(self.s.conn.execute('PRAGMA foreign_key_check').fetchall(), [])
        snapshot = json.loads(self.s.conn.execute('SELECT snapshot_json FROM paper_identity_history').fetchone()[0])
        self.assertEqual(len(snapshot['source_relationships']['journal_feed_entries']), 2)

    def test_conflicting_defaults_and_legacy_paths_are_not_discarded(self):
        self.legacy_duplicates()
        for index, pid in enumerate(('one','two')):
            self.s.conn.execute('UPDATE papers SET preferred_resource_manual=1,preferred_resource_id=?,analysis_path=? WHERE paper_id=?',(100+index,'/synthetic/old-note-'+pid,pid))
        self.s.conn.commit()
        plan = identity.reconciliation_plan(self.s)
        self.assertIn('Different manual Default files need a choice',plan['groups'][0]['blockers'])
        self.assertIn('Legacy file paths must be registered before reconciliation',plan['groups'][0]['blockers'])
        self.assertEqual(identity.apply_reconciliation(self.s,plan),[])
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],2)

    def test_unverified_title_only_legacy_duplicates_remain_separate(self):
        self.legacy_duplicates()
        self.s.conn.execute("UPDATE papers SET raw_json='{}'")
        self.s.conn.commit()
        plan = identity.reconciliation_plan(self.s)
        self.assertIn('Same-work evidence is insufficient',plan['groups'][0]['blockers'])
        self.assertEqual(identity.apply_reconciliation(self.s,plan),[])

    def test_raw_preprint_identifier_completion_reuses_identity(self):
        a, b = paper('one'), paper('two')
        a['raw']['arxiv_id'] = '2609.12345'
        self.s.upsert_paper(a)
        self.s.upsert_paper(b)
        updated = self.s.update_paper_raw_json('two',{'authors':['A Researcher'],'arxiv_id':'2609.12345'})
        self.assertEqual(updated['paper_id'],'one')
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)

    def test_new_sql_duplicate_write_is_rejected(self):
        self.s.upsert_paper(paper('one','10.1234/work'))
        self.s.upsert_paper(paper('two'))
        with self.assertRaises(sqlite3.IntegrityError):
            self.s.conn.execute("UPDATE papers SET doi='10.1234/WORK' WHERE paper_id='two'")
        self.s.conn.rollback()
        self.assertFalse(self.s.get_paper('two')['doi'])

    def test_startup_upgrade_does_not_merge_historical_records(self):
        self.legacy_duplicates()
        self.s.conn.execute('PRAGMA user_version=18')
        self.s.conn.commit()
        other = Storage(self.path)
        try:
            self.assertEqual(other.conn.execute('SELECT count(*) FROM papers').fetchone()[0],2)
            self.assertEqual(other.conn.execute('SELECT count(*) FROM paper_identity_history').fetchone()[0],0)
            self.assertEqual(other.conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        finally:
            other.close()

    def test_all_monitor_provenance_and_publication_flags_survive(self):
        self.legacy_duplicates()
        run = self.s.start_fetch_run(monitor_type='journal',source='fixture',journal='Synthetic Journal',
            window_start='2025-01-01',window_end='2025-01-02',started_at='2025-01-01')
        publications = []
        for index, pid in enumerate(('one','two')):
            publications.append(self.s.add_my_publication(paper_id=pid))
            self.s.record_journal_monitor_paper(fetch_run_id=run,paper_id=pid,source='fixture')
            self.s.record_theme_result(paper_id=pid,group_key='group',group_name='Group',query='sample',
                score=index+1,hits=['first' if index==0 else 'second'],window_start='2025-01-01',window_end='2025-01-02')
            self.s.record_theme_candidate(paper_id=pid,source='fixture',window_start='2025-01-01',window_end='2025-01-02',query_plan_hash='one')
            self.s.mark_late_arrivals_seen([pid])
            self.s.conn.execute('INSERT INTO publication_identifier_tasks(publication_id,status) VALUES(?,?)',
                (publications[-1]['id'],'complete' if index==0 else 'pending'))
            self.s.conn.commit()
        self.s.conn.execute("UPDATE my_publications SET starred=1 WHERE paper_id='two'")
        self.s.conn.execute("UPDATE my_publications SET first_author=1 WHERE paper_id='one'")
        self.s.conn.commit()
        plan=identity.reconciliation_plan(self.s)
        identity.apply_reconciliation(self.s,plan)
        for table in ('journal_monitor_papers','theme_results','theme_candidates','paper_reads','my_publications'):
            self.assertEqual(self.s.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],1,table)
            self.assertEqual(self.s.conn.execute('SELECT paper_id FROM '+table).fetchone()[0],'one',table)
        self.assertEqual(json.loads(self.s.conn.execute('SELECT hits_json FROM theme_results').fetchone()[0]),['first','second'])
        flags=self.s.conn.execute('SELECT starred,first_author FROM my_publications').fetchone()
        self.assertEqual(tuple(flags),(1,1))
        self.assertEqual(self.s.conn.execute('SELECT status FROM publication_identifier_tasks').fetchone()[0],'pending')
        self.assertEqual(self.s.conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_enrichment_path_coalesces_late_identifier_and_keeps_notes(self):
        author = self.author('Synthetic Author')
        self.s.upsert_paper({**paper('one','10.1234/work'),'raw':{'authors':['A Researcher'],'saved_note':'Keep this'}})
        self.s.add_my_publication(paper_id='one')
        self.s.upsert_paper(paper('two'))
        self.s.add_author_monitor_paper(author_monitor_id=author,paper_id='two')
        job=ui.create_author_monitor_enrichment_job(author_monitor_id=author)
        enriched=paper('two','10.1234/work')
        with patch('requests.sessions.Session.request',side_effect=AssertionError('Unexpected network request')), \
                patch.object(ui,'resolve_google_scholar_candidate_to_identifier',return_value=enriched), \
                patch.object(ui,'publication_metrics_metadata_from_doi',return_value=enriched), \
                patch.object(ui,'refresh_pubmed_if_possible',side_effect=lambda s,p,**kw:p):
            ui.run_author_monitor_enrichment_job(job_id=job,db_path=self.path,author_monitor_id=author,force=True)
        self.assertEqual(len(self.s.list_author_monitor_papers(author)),1)
        self.assertEqual(self.s.get_paper('two')['paper_id'],'one')
        self.assertEqual(json.loads(self.s.get_paper('one')['raw_json'])['saved_note'],'Keep this')

    def test_cleared_identifier_cannot_keep_stale_ownership(self):
        original = paper('one')
        original['raw']['arxiv_id']='2609.12345'
        self.s.upsert_paper(original)
        # Simulate a manual edit made by an older running client.
        self.s.conn.execute("UPDATE papers SET raw_json=? WHERE paper_id='one'",
            (json.dumps({'manual_preprint_identifier_override':True,'manual_preprint_identifier':''}),))
        self.s.conn.commit()
        second=paper('two'); second['raw']['arxiv_id']='2609.12345'
        self.s.upsert_paper(second)
        third=copy.deepcopy(second); third['paper_id']='three'
        self.s.upsert_paper(third)
        self.assertEqual(third['paper_id'],'two')
        self.assertEqual(self.s.get_paper('one')['paper_id'],'one')

    def test_outer_import_transaction_can_roll_back_new_alias_and_record(self):
        self.s.conn.execute('BEGIN IMMEDIATE')
        a,b=paper('one','10.1234/work'),paper('two','10.1234/work')
        self.s.upsert_paper(a,commit=False)
        self.s.upsert_paper(b,commit=False)
        self.s.conn.rollback()
        for table in ('papers','paper_aliases','paper_identifiers'):
            self.assertEqual(self.s.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)

    def test_read_only_cli_plan_survives_schema_upgrade_and_requires_new_backup(self):
        self.legacy_duplicates()
        for table in ('paper_aliases','paper_identifiers','paper_identity_history'):
            self.s.conn.execute('DROP TABLE '+table)
        self.s.conn.execute('PRAGMA user_version=18')
        self.s.conn.commit()
        plan = Path(self.tmp.name)/'plan.json'
        backup = Path(self.tmp.name)/'backup.sqlite'
        script = Path(__file__).resolve().parents[1]/'scripts/reconcile_paper_identities.py'
        command = [sys.executable,str(script),'--db',str(self.path)]
        subprocess.run(command+['--plan',str(plan)],check=True,capture_output=True)
        self.assertEqual(self.s.conn.execute('PRAGMA user_version').fetchone()[0],18)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],2)
        subprocess.run(command+['--apply',str(plan),'--backup',str(backup)],check=True,capture_output=True)
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)
        old=sqlite3.connect(backup)
        try:
            self.assertEqual(old.execute('SELECT count(*) FROM papers').fetchone()[0],2)
        finally:
            old.close()
        self.assertEqual(backup.stat().st_mode & 0o777,0o600)
        retry=subprocess.run(command+['--apply',str(plan),'--backup',str(backup)],capture_output=True)
        self.assertNotEqual(retry.returncode,0)

    def test_active_download_defers_merge_without_interrupting_it(self):
        from paper_monitor.download import paper_download_lock
        self.s.upsert_paper(paper('one','10.1234/work'))
        self.s.upsert_paper(paper('two'))
        started, finish = threading.Event(), threading.Event()
        def downloading():
            with paper_download_lock(self.path,'two'):
                started.set()
                finish.wait(5)
        thread=threading.Thread(target=downloading)
        thread.start()
        try:
            self.assertTrue(started.wait(2))
            with self.assertRaisesRegex(ValueError,'download is still running'):
                self.s.refresh_paper_metadata('two',paper('two','10.1234/work'))
            self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],2)
        finally:
            finish.set();thread.join(3)
        self.s.refresh_paper_metadata('two',paper('two','10.1234/work'))
        self.assertEqual(self.s.conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)
