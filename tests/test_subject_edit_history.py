from contextlib import ExitStack
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage
from paper_monitor.workflow_store import subject_window_preserved


class SubjectEditHistoryTests(TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'test.sqlite'
        self.storage = Storage(self.path); self.addCleanup(self.storage.close)
        self.key = 'HISTORY_TEST'
        ui.save_custom_theme_groups(self.storage,[{'key':self.key,'name':'History','queries':['old keyword'],'is_custom':True}])
        self.old = self.paper('old','Old keyword physics')
        self.new = self.paper('new','New keyword physics')
        for p in (self.old,self.new): self.storage.upsert_paper(p)
        for key,day in [(self.key,'2026-09-07'),(self.key,'2026-09-06'),('OTHER_TEST','2026-09-07')]:
            self.storage.record_theme_result(paper_id='old',group_key=key,group_name='History',query='old keyword',score=1,hits=['old keyword'],window_start=day,window_end=day)
        run=self.storage.start_fetch_run(monitor_type='theme',source='multi',journal='theme:'+self.key,window_start='2026-09-05',window_end='2026-09-05',started_at='2026-09-05T12:00:00+08:00')
        self.storage.finish_fetch_run(run,status='empty',records_found=0)

    def paper(self,id,title):
        return {'paper_id':id,'title':title,'publication_date':'2026-09-07','source':'arxiv','journal':'arXiv','type':'preprint','section_allowed':True}

    def edit(self,keywords='new keyword'):
        class Handler:
            configured_db_path=self.path
            def send_json(inner,data): inner.data=data
            def send_error_json(inner,status,message): raise AssertionError(message)
        handler=Handler()
        ui.PaperMonitorUiHandler.handle_update_theme_group(handler,{'key':self.key,'name':'Renamed Subject','keywords':keywords})

    def rows(self):
        return [tuple(row) for row in self.storage.conn.execute('SELECT * FROM theme_results ORDER BY id')]

    def run_fetch(self,*,trigger='manual',status='success',during=None,theme_groups=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(ui,'theme_source_fetchers',return_value=[]))
            def local(*args,**kwargs):
                if during: during()
                return [self.new],status,''
            stack.enter_context(patch.object(ui,'local_arxiv_theme_candidates',side_effect=local))
            stack.enter_context(patch.object(ui,'local_aps_rss_theme_candidates',return_value=([],'empty','')))
            return ui.run_theme_monitor(storage=self.storage,start_date=date(2026,9,7),end_date=date(2026,9,7),group_keys=[self.key],trigger=trigger,theme_groups=theme_groups)

    def test_edit_preserves_exact_history_and_zero_result_fetches_across_reopen(self):
        before=self.rows()
        runs=[tuple(r) for r in self.storage.conn.execute('SELECT * FROM fetch_runs')]
        self.edit()
        self.assertEqual(before,self.rows())
        self.assertEqual(runs,[tuple(r) for r in self.storage.conn.execute('SELECT * FROM fetch_runs')])
        self.assertEqual(self.storage.conn.execute('SELECT count(*) FROM papers').fetchone()[0],2)
        reopened=Storage(self.path)
        try:
            for day in ('2026-09-05','2026-09-06','2026-09-07'):
                self.assertTrue(subject_window_preserved(reopened,self.key,day,day))
            self.assertEqual(ui.load_theme_groups(reopened)[self.key]['queries'],['new keyword'])
        finally: reopened.close()

    def test_automatic_retry_and_local_arxiv_do_not_rematch_preserved_window(self):
        before=self.rows(); self.edit()
        self.run_fetch(trigger='automatic_retry')
        with patch.object(ui,'local_arxiv_theme_candidates',return_value=([self.new],'success','')):
            ui.match_local_arxiv_for_all_subjects(self.storage,date(2026,9,7))
        self.assertEqual(before,self.rows())
        self.assertNotIn(self.key,ui.missing_theme_group_keys_for_date(self.storage,'2026-09-07',[self.key]))

    def test_explicit_refresh_replaces_only_selected_subject_and_window(self):
        self.edit(); self.run_fetch()
        rows=self.storage.conn.execute('SELECT paper_id,group_key,window_start FROM theme_results').fetchall()
        self.assertEqual({tuple(r) for r in rows},{('new',self.key,'2026-09-07'),('old',self.key,'2026-09-06'),('old','OTHER_TEST','2026-09-07')})

    def test_failed_refresh_preserves_previous_results(self):
        self.edit(); before=self.rows()
        self.run_fetch(status='error')
        self.assertEqual(before,self.rows())

    def test_queued_fetch_uses_keywords_edited_after_its_configuration_was_captured(self):
        captured=ui.load_theme_groups(self.storage)
        self.edit()
        self.run_fetch(theme_groups=captured)
        rows=self.storage.conn.execute('SELECT paper_id FROM theme_results WHERE group_key=? AND window_start=?',(self.key,'2026-09-07')).fetchall()
        self.assertEqual([r[0] for r in rows],['new'])

    def test_edit_during_network_work_discards_old_job_results_and_fetch_record(self):
        before=self.rows()
        runs=self.storage.conn.execute('SELECT count(*) FROM fetch_runs').fetchone()[0]
        result=self.run_fetch(during=self.edit)
        self.assertEqual(before,self.rows())
        self.assertEqual(runs,self.storage.conn.execute('SELECT count(*) FROM fetch_runs').fetchone()[0])
        self.assertEqual(result['groups'][self.key]['status'],'superseded')
