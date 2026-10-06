"""Stop semantics with disposable SQLite, mocked lookups and no App gestures."""
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from paper_monitor import metadata_jobs as jobs, metadata_refresh as work, ui_server as ui
from paper_monitor.storage import Storage
from tests import test_metadata_refresh as fixtures
from tests.test_library_background_drop import js_function


class MetadataJobStopTests(unittest.TestCase):
    setUp = fixtures.MetadataRefreshTests.setUp

    def make_job(self):
        work.save_doi(self.storage, self.pid, fixtures.DOI)
        self.storage.add_library_item(paper_id=self.pid)
        self.storage.upsert_paper({'paper_id': 'z-second', 'title': 'Second synthetic document',
                                  'journal': 'Synthetic', 'doi': '10.1234/second'})
        self.storage.add_library_item(paper_id='z-second')
        return jobs.create(self.storage)

    def assert_stopped(self, job_id, current):
        job = jobs.get(self.storage, job_id)
        self.assertEqual(job['status'], 'stopped')
        self.assertEqual(job['current'], current)
        self.assertEqual(job['result']['processed'], current)
        self.assertTrue(job['finished_at'])
        self.assertEqual(json.loads(self.storage.get_setting('metadata_candidates:' + job_id)), [])
        return job

    def test_stop_idle_states_survives_restart_and_cannot_resume(self):
        for status in ('queued', 'paused', 'failed'):
            with self.subTest(status=status):
                job = self.make_job()
                job.update(status=status, stage=status)
                jobs._save(self.storage, job)
                jobs.control(self.storage, job['job_id'], 'stop')
                stopped = self.assert_stopped(job['job_id'], 0)
                jobs._INITIALIZED.discard(str(self.path.resolve()))
                store = Storage(self.path)
                try:
                    self.assertEqual(jobs.get(store, job['job_id']), stopped)
                    self.assertEqual(jobs.control(store, job['job_id'], 'stop'), stopped)
                    with self.assertRaisesRegex(ValueError, 'cannot be continued'):
                        jobs.control(store, job['job_id'], 'resume')
                    jobs.run_job(store, job['job_id'])
                finally:
                    store.close()
                self.assert_stopped(job['job_id'], 0)
        self.mocks['fetch_arxiv_by_id'].assert_not_called()
        self.assertEqual(len(jobs.listing(self.storage)), 3)
        self.assertNotEqual(jobs.create(self.storage)['job_id'], job['job_id'])

    def test_stop_during_lookup_commits_current_paper_but_never_starts_next(self):
        job = self.make_job()
        pdf = self.path.parent / 'kept.pdf'
        pdf.write_bytes(b'%PDF-1.4 retained fixture')
        resource = self.storage.create_paper_resource(paper_id=self.pid, stored_path=str(pdf), file_type='preprint')
        before = [tuple(r) for r in self.storage.conn.execute('SELECT * FROM library_items')]
        original = work.refresh

        def stop_during_lookup(storage, paper_id, **kwargs):
            control = Storage(self.path)
            try:
                stopping = jobs.control(control, job['job_id'], 'stop')
                self.assertEqual(stopping['status'], 'stopping')
            finally:
                control.close()
            return original(storage, paper_id, **kwargs)

        with patch.object(work, 'refresh', side_effect=stop_during_lookup) as refresh:
            jobs.run_job(self.storage, job['job_id'])
        self.assertEqual(refresh.call_count, 1)
        stopped = self.assert_stopped(job['job_id'], 1)
        self.assertEqual(stopped['result']['metadata_refreshed'], 1)
        self.assertEqual(stopped['percent'], 50)
        self.assertTrue(self.storage.get_paper(self.pid)['abstract'])
        self.assertEqual(before, [tuple(r) for r in self.storage.conn.execute('SELECT * FROM library_items')])
        self.assertEqual(pdf.read_bytes(), b'%PDF-1.4 retained fixture')
        self.assertIsNotNone(self.storage.conn.execute('SELECT id FROM resources WHERE id=?', (resource['id'],)).fetchone())

    def test_stop_on_last_paper_is_not_overwritten_by_completion(self):
        self.storage.add_library_item(paper_id=self.pid)
        job = jobs.create(self.storage)
        def last_lookup(*args, **kwargs):
            jobs.control(self.storage, job['job_id'], 'stop')
            return {'metadata_refresh': {'status': 'unchanged', 'message': 'Checked'}}
        with patch.object(work, 'refresh', side_effect=last_lookup):
            jobs.run_job(self.storage, job['job_id'])
        self.assertEqual(self.assert_stopped(job['job_id'], 1)['counts']['unchanged'], 1)

    def test_stop_wins_over_pending_pause_and_restart(self):
        job = self.make_job()
        job.update(status='running', stage='metadata')
        jobs._save(self.storage, job)
        self.assertEqual(jobs.control(self.storage, job['job_id'], 'pause')['status'], 'pausing')
        self.assertEqual(jobs.control(self.storage, job['job_id'], 'stop')['status'], 'stopping')
        jobs._INITIALIZED.discard(str(self.path.resolve()))
        self.assert_stopped(job['job_id'], 0)
        self.mocks['fetch_arxiv_by_id'].assert_not_called()

    def test_stop_between_papers_preserves_checkpoint_and_logs(self):
        job = self.make_job()
        def progress(current):
            if current['current'] == 1:
                jobs.control(self.storage, job['job_id'], 'stop')
        jobs.run_job(self.storage, job['job_id'], progress=progress)
        stopped = self.assert_stopped(job['job_id'], 1)
        self.assertEqual(len(stopped['logs']), 2)
        self.assertEqual(stopped['changed_count'], 1)

    def test_exception_while_stopping_does_not_make_job_resumable(self):
        job = self.make_job()
        def progress(current):
            jobs.control(self.storage, job['job_id'], 'stop')
            raise RuntimeError('Synthetic callback failure')
        jobs.run_job(self.storage, job['job_id'], progress=progress)
        self.assert_stopped(job['job_id'], 0)

    def test_loader_stop_ends_child_queue_even_during_last_lookup(self):
        self.storage.add_library_item(paper_id=self.pid)
        parent = ui.create_library_import_job(folder_path=self.path.parent, copy_mode='copy')
        self.addCleanup(ui.LIBRARY_IMPORT_JOBS.pop, parent, None)
        result = {'library_items_created': 1, 'metadata_refresh_candidates': [{'paper_id': self.pid}]}
        def stop_during_lookup(*args, **kwargs):
            ui.request_stop_library_import_job(parent, storage=self.storage)
            return {'metadata_refresh': {'status': 'updated', 'message': 'Saved', 'changed_fields': ['title']}}
        with patch.object(ui, 'recover_imported_pdf_identifiers', return_value=set()), \
             patch.object(work, 'refresh', side_effect=stop_during_lookup):
            with self.assertRaisesRegex(ui.ImportCancelled, 'remaining queue has ended'):
                ui.refresh_imported_doi_metadata(self.storage, result, job_id=parent)
        self.assert_stopped(result['metadata_job_id'], 1)
        self.assertEqual(result['library_items_created'], 1)
        self.assertEqual(result['doi_metadata_refreshed'], 1)
        self.assertTrue(ui.get_library_import_job(parent)['cancel_requested'])
        self.assertEqual(ui.get_library_import_job(parent)['current'], 1)

    def test_loader_stop_before_child_creation_never_starts_lookup(self):
        self.make_job()
        parent = ui.create_library_import_job(folder_path=self.path.parent, copy_mode='copy')
        self.addCleanup(ui.LIBRARY_IMPORT_JOBS.pop, parent, None)
        result = {'metadata_refresh_candidates': [{'paper_id': self.pid}]}
        ui.request_stop_library_import_job(parent, storage=self.storage)
        with patch.object(ui, 'recover_imported_pdf_identifiers', return_value=set()), \
             patch.object(work, 'refresh') as refresh:
            with self.assertRaises(ui.ImportCancelled):
                ui.refresh_imported_doi_metadata(self.storage, result, job_id=parent)
        refresh.assert_not_called()
        self.assert_stopped(result['metadata_job_id'], 0)

    def test_loader_retains_import_summary_when_metadata_stops(self):
        parent = ui.create_library_import_job(folder_path=self.path.parent, copy_mode='copy')
        self.addCleanup(ui.LIBRARY_IMPORT_JOBS.pop, parent, None)
        result = {'library_items_created': 2, 'created_resources': 2, 'doi_metadata_refreshed': 1}
        with patch.object(ui, 'build_inventory_from_folder'), \
             patch.object(ui, 'read_gewu_complete_export_manifest', return_value=None), \
             patch.object(ui, 'import_library_inventory', return_value=result), \
             patch.object(ui, 'refresh_imported_doi_metadata', side_effect=ui.ImportCancelled('Stopped')):
            ui.run_library_import_job(job_id=parent, db_path=self.path, folder_path=self.path.parent, copy_mode='copy',
                                      copy_plan={'copy_target_root': str(self.path.parent)})
        done = ui.get_library_import_job(parent)
        self.assertEqual(done['status'], 'cancelled')
        self.assertEqual(done['result']['library_items_created'], 2)
        self.assertEqual(done['result']['doi_metadata_refreshed'], 1)


@unittest.skipUnless(shutil.which('node'), 'Node is required for pure frontend logic checks')
class MetadataStopFrontendTests(unittest.TestCase):
    def test_stop_controls_history_and_status_without_browser_clicks(self):
        names = ['renderLibraryLoader', 'metadataJobStatusText', 'metadataBatchActivityText',
                 'metadataJobHistoryMarkup', 'controlMetadataJob', 'pollMetadataJobs']
        source = '\n'.join(js_function(name) for name in names)
        harness = r'''
const assert = require('node:assert/strict');
const nodes = new Map();
function $(id) {
  if (['libraryLoaderConsole','libraryLoaderSide','loaderJumpLatest'].includes(id)) return null;
  if (!nodes.has(id)) nodes.set(id, {classList:{add(){},remove(){}},setAttribute(){},querySelector(){return null;}});
  return nodes.get(id);
}
function escapeHtml(s){return String(s)} function escapeAttr(s){return String(s)}
function isLoaderConsoleAtBottom(){return true} function libraryImportSourceLabel(){return ''}
function loaderStatusText(){return ''} function loaderMetadataModeHint(){return ''}
function loaderHistoryMarkup(){return ''} function loaderResultSummary(){return ''}
function loaderConsoleMarkup(){return ''} function loaderSideMarkup(){return ''}
function wireLibraryImportTools(){} function wireLoaderSide(){} function resumeLibraryImportPollingIfNeeded(){}
function renderLibraryActivityStatus(){} function signalLibraryRefresh(){}
let starts=0, stops=0, notices=[], visibleRefreshes=0;
function startLibraryImportPolling(){starts++} function stopLibraryImportPolling(){stops++}
function updateLibraryActivityStatus(s){notices.push(s)} function pollVisibleMetadataResult(){visibleRefreshes++}
async function parseJsonResponse(res){return res.json()}
let state, responseJob, posted, fetch;
function job(status){return {job_id:'a',status,current:1,total:3,scope_label:'Fixture',metadata_mode:'full',result:status==='stopped'?{processed:1}:null}}
function setup(status){
 const j=job(status); state={libraryLoaderOpen:true,libraryTaskMode:'metadata-refresh',libraryImportJobId:'a',
 libraryImportJob:j,libraryImportBusy:['running','queued','pausing','stopping'].includes(status),metadataRefreshJobs:[j]};
 renderLibraryLoader();
}
function button(id){const m=$('libraryLoaderModalBody').innerHTML.match(new RegExp('<button[^>]*id="'+id+'"([^>]*)>([^<]*)</button>'));assert.ok(m);return {disabled:m[1].includes('disabled'),text:m[2]};}
(async()=>{
 for(const s of ['running','queued']){setup(s);assert.equal(button('libraryPauseImport').disabled,false);assert.equal(button('libraryStopImport').disabled,false);}
 setup('paused');assert.deepEqual(button('libraryRunImport'),{disabled:false,text:'Continue'});assert.equal(button('libraryStopImport').disabled,false);assert.match(metadataBatchActivityText(),/paused/);
 setup('stopping');assert.deepEqual(button('libraryStopImport'),{disabled:true,text:'Stopping…'});assert.equal(button('libraryRunImport').disabled,true);
 setup('stopped');assert.deepEqual(button('libraryRunImport'),{disabled:false,text:'Start Refresh'});assert.equal(button('libraryStopImport').disabled,true);assert.equal(metadataBatchActivityText(),'');assert.match(metadataJobHistoryMarkup(),/stopped.*1\/3/);
 setup('paused');responseJob=job('stopped');
 fetch=async(url,options)=>{if(options){posted=JSON.parse(options.body);return {ok:true,json:async()=>({job:responseJob})}}return {ok:true,json:async()=>({jobs:[responseJob]})}};
 await controlMetadataJob('stop');
 assert.deepEqual(posted,{job_id:'a',action:'stop'});assert.equal(state.libraryImportBusy,false);assert.equal(stops,1);assert.equal(starts,0);assert.equal(state.libraryImportLastResult.processed,1);assert.equal(metadataBatchActivityText(),'');
 // A stop made in the other window must update an idle Details window too.
 await pollMetadataJobs();setup('paused');await pollMetadataJobs();
 assert.equal(state.libraryImportJob.status,'stopped');assert.equal(button('libraryRunImport').text,'Start Refresh');assert.equal(visibleRefreshes,1);assert.deepEqual(notices,['Refresh stopped']);
 state.libraryActivityLive=true;state.metadataRefreshJobs=[job('stopping')];await pollMetadataJobs();assert.equal(notices.length,1);
 console.log('Stop frontend state checks passed (no browser or UI gestures).');
})().catch(e=>{console.error(e);process.exit(1)});
'''
        result = subprocess.run(['node', '-'], input=source + '\n' + harness,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
