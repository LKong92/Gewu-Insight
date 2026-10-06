"""Loader navigation contracts without opening the user's App or clicking UI."""
import json
import shutil
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_monitor import metadata_jobs as jobs, ui_server as ui
from paper_monitor.importers.inventory import build_inventory_from_folder, import_library_inventory
from paper_monitor.storage import Storage
from tests import test_metadata_refresh as fixtures
from tests.test_library_background_drop import js_function


class LoaderLogTargetsTests(unittest.TestCase):
    setUp = fixtures.MetadataRefreshTests.setUp

    def test_new_metadata_logs_identify_each_paper_including_missing_id(self):
        self.storage.add_library_item(paper_id=self.pid)
        self.storage.upsert_paper({'paper_id': 'z-plain', 'title': 'Notes', 'journal': 'Local'})
        self.storage.add_library_item(paper_id='z-plain')
        job = jobs.create(self.storage)
        jobs.run_job(self.storage, job['job_id'])
        done = jobs.get(self.storage, job['job_id'])
        self.assertEqual([entry['paper_id'] for entry in done['logs']], [self.pid, 'z-plain'])
        self.assertIn('missing identifier', done['logs'][-1]['message'])

    def test_legacy_log_targets_use_queue_positions_without_mutating_checkpoint(self):
        job = jobs.create(self.storage, paper_ids=[self.pid, 'second'])
        job.update(status='paused', current=2, logs=[
            {'message': '1/2 · Same title · updated: Saved'},
            {'message': '2/2 · Same title · failed: Network'},
            {'message': '3/2 · Invalid position · failed: Error'},
            {'message': '1/500 · Another total · failed: Error'},
            {'message': 'Stop requested'},
        ])
        jobs._save(self.storage, job)
        raw = self.storage.get_setting(jobs.PREFIX + job['job_id'])
        for returned in (jobs.get(self.storage, job['job_id']), jobs.listing(self.storage)[0]):
            self.assertEqual([entry.get('paper_id') for entry in returned['logs']],
                             [self.pid, 'second', None, None, None])
        self.assertEqual(raw, self.storage.get_setting(jobs.PREFIX + job['job_id']))
        stopped = jobs.control(self.storage, job['job_id'], 'stop')
        self.assertEqual(stopped['logs'][0]['paper_id'], self.pid)
        self.assertEqual(json.loads(self.storage.get_setting('metadata_candidates:' + job['job_id'])), [])
        self.assertEqual(jobs.get(self.storage, job['job_id'])['logs'][1]['paper_id'], 'second')

    def test_loader_metadata_mirrors_last_paper_target(self):
        self.storage.add_library_item(paper_id=self.pid)
        parent = ui.create_library_import_job(folder_path=self.path.parent, copy_mode='copy')
        self.addCleanup(ui.LIBRARY_IMPORT_JOBS.pop, parent, None)
        result = {'metadata_refresh_candidates': [{'paper_id': self.pid}]}
        with patch.object(ui, 'recover_imported_pdf_identifiers', return_value=set()):
            ui.refresh_imported_doi_metadata(self.storage, result, job_id=parent)
        entries = [e for e in ui.get_library_import_job(parent)['logs'] if e.get('paper_id')]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['paper_id'], self.pid)

    def test_import_receipts_point_to_committed_placements_on_first_and_repeat_load(self):
        root = self.path.parent / 'source'
        root.mkdir()
        (root / 'Notes.rtf').write_text(r'{\rtf1 Synthetic note}')
        (root / 'Article.pdf').write_bytes(b'%PDF-1.4 synthetic unreadable fixture')
        inventory = self.path.parent / 'inventory.json'
        build_inventory_from_folder(root, output_path=inventory, parse_pdfs=False)
        for iteration in range(2):
            parent = ui.create_library_import_job(folder_path=root, copy_mode='copy')
            self.addCleanup(ui.LIBRARY_IMPORT_JOBS.pop, parent, None)
            progress = ui.library_import_progress_callback(parent)
            committed_targets = []
            def check_committed(event):
                progress(event)
                if not event.get('paper_id'):
                    return
                other = Storage(self.path)
                try:
                    row = other.conn.execute('SELECT paper_id FROM library_items WHERE id=?', (event['library_item_id'],)).fetchone()
                    committed_targets.append((row['paper_id'] if row else None, event['paper_id']))
                finally:
                    other.close()
            result = import_library_inventory(inventory, storage=self.storage, dry_run=False,
                preserve_folders=True, target_root=self.path.parent / 'copied', progress_callback=check_committed)
            self.assertEqual(result['errors'], [])
            entries = [e for e in ui.get_library_import_job(parent)['logs'] if e.get('paper_id')]
            self.assertEqual(len(entries), 2, iteration)
            self.assertTrue(all(e.get('library_item_id') for e in entries))
            self.assertEqual(len(committed_targets), 2)
            self.assertTrue(all(actual == expected for actual, expected in committed_targets))

    def test_locations_resolve_old_identity_before_loading_rows(self):
        item = self.storage.add_library_item(paper_id=self.pid)
        handler = SimpleNamespace(configured_db_path=self.path, send_json=Mock(), send_error_json=Mock())
        original = Storage.resolve_paper_id
        def resolve(store, paper_id):
            return self.pid if paper_id == 'former-id' else original(store, paper_id)
        with patch.object(Storage, 'resolve_paper_id', resolve):
            ui.PaperMonitorUiHandler.handle_library_paper_locations(handler, {'paper_id': ['former-id']})
        handler.send_error_json.assert_not_called()
        data = handler.send_json.call_args.args[0]
        self.assertEqual(data['paper_id'], self.pid)
        self.assertEqual(data['items'][0]['id'], item['id'])


@unittest.skipUnless(shutil.which('node'), 'Node required')
class LoaderNavigationFrontendTests(unittest.TestCase):
    def test_log_navigation_success_failure_selection_and_native_handoff(self):
        names = ['loaderConsoleMarkup', 'loaderLogGroupClass', 'loaderLogKind', 'loaderLogLabel',
                 'loaderLogMessageMarkup', 'wireLoaderLogNavigation', 'openLoaderLogPaper',
                 'revealLoaderPaper', 'finishLoaderPaperReveal', 'closeLibraryLoader']
        script = '\n'.join(js_function(name) for name in names)
        harness = r'''
const assert=require('node:assert/strict');
let state={libraryLoaderOpen:true,libraryImportBusy:true}, IS_STANDALONE_LOADER_WINDOW=false;
let calls=[], sent=[], renders=0, fail=false, selected=false, pending, release;
const window={webkit:{messageHandlers:{libraryLoaderWindow:{postMessage(p){sent.push(p)}}}},
  getSelection(){return {isCollapsed:!selected}},addEventListener(){},removeEventListener(){},setTimeout(fn){fn()}};
function $(id){return {classList:{remove(){}},setAttribute(){}}}
function renderLibraryLoader(){renders++}
function escapeHtml(v){return String(v).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;')}
const escapeAttr=escapeHtml;
async function navigateToPaperInLibrary(id,item){calls.push([id,item]);if(fail)throw Error('Paper unavailable');if(pending)await pending}
(async()=>{
 const html=loaderConsoleMarkup({logs:[{time:'T12:00',message:'1/2 · <script> · updated',paper_id:'key"1',library_item_id:7},{message:'Scanning folder'}]});
 assert.equal((html.match(/role="button"/g)||[]).length,1);assert.match(html,/key&quot;1/);assert.ok(!html.includes('<script>'));assert.match(html,/Show in Library/);
 let refreshDone=false;state.libraryRefreshPromise=Promise.resolve().then(()=>{refreshDone=true});
 await openLoaderLogPaper('key',7);assert.ok(refreshDone);assert.deepEqual(calls,[['key',7]]);assert.equal(state.libraryLoaderOpen,false);assert.equal(state.libraryImportBusy,true);assert.equal(state.libraryLoaderRevealBusy,false);
 state.libraryLoaderOpen=true;fail=true;await openLoaderLogPaper('missing');assert.equal(state.libraryLoaderOpen,true);assert.equal(state.libraryLoaderNavigationError,'Paper unavailable');assert.equal(state.libraryImportBusy,true);
 fail=false;pending=new Promise(r=>release=r);const first=openLoaderLogPaper('slow');await Promise.resolve();await openLoaderLogPaper('duplicate');release();await first;pending=null;assert.ok(!calls.some(c=>c[0]==='duplicate'));
 IS_STANDALONE_LOADER_WINDOW=true;state.libraryLoaderOpen=true;const count=calls.length;
 await openLoaderLogPaper('native',9);assert.equal(calls.length,count);assert.deepEqual(sent,[{type:'show-paper',paper_id:'native',library_item_id:9}]);assert.equal(state.libraryLoaderOpen,true);assert.equal(state.libraryLoaderRevealBusy,true);
 finishLoaderPaperReveal('Unavailable');assert.equal(state.libraryLoaderRevealBusy,false);assert.equal(state.libraryLoaderNavigationError,'Unavailable');
 const handlers={};const consoleEl={addEventListener(t,fn){handlers[t]=fn},contains(){return true}};wireLoaderLogNavigation(consoleEl);
 const row={dataset:{paperId:'clicked',libraryItemId:'12'}};const event={type:'click',target:{closest(){return row}},preventDefault(){},stopPropagation(){}};
 selected=true;handlers.click(event);assert.equal(sent.length,1);selected=false;handlers.click(event);assert.equal(sent.length,2);finishLoaderPaperReveal();
 handlers.keydown({...event,type:'keydown',key:'Tab'});assert.equal(sent.length,2);
 handlers.keydown({...event,type:'keydown',key:'Enter'});assert.equal(sent.length,3);assert.equal(state.libraryImportBusy,true);
 console.log('Loader log navigation contracts passed without App gestures.');
})().catch(e=>{console.error(e);process.exit(1)});
'''
        result = subprocess.run(['node','-'], input=script+'\n'+harness, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)


if __name__ == '__main__': unittest.main()
