from __future__ import annotations

import unittest

from paper_monitor.ui_server import INDEX_HTML


ACTIVITY_DOM_STUB = r'''
class ActivityNode {
  constructor(){this.children=[];this.dataset={};this.attributes={};this.textContent='';this.title='';this.className='';this.hidden=false;}
  setAttribute(key,value){this.attributes[key]=value;}
  querySelectorAll(){return [];}
  get firstElementChild(){return this.children[0];}
  appendChild(node){this.insertBefore(node,null);}
  insertBefore(node,before){node.remove();const index=before?this.children.indexOf(before):this.children.length;this.children.splice(index,0,node);node.parent=this;}
  remove(){if(this.parent){const siblings=this.parent.children;siblings.splice(siblings.indexOf(this),1);this.parent=null;}}
}
const nodes=new Map();
function $(id){if(!nodes.has(id))nodes.set(id,new ActivityNode());return nodes.get(id);}
const document={createElement(){return new ActivityNode();}};
'''


def js_function(name: str) -> str:
    marker = f"function {name}"
    start = INDEX_HTML.rfind("\n", 0, INDEX_HTML.index(marker)) + 1
    candidates = [
        position
        for position in (
            INDEX_HTML.find("\n    function ", start + len(marker)),
            INDEX_HTML.find("\n    async function ", start + len(marker)),
        )
        if position >= 0
    ]
    return INDEX_HTML[start : min(candidates) if candidates else len(INDEX_HTML)]


class LibraryBackgroundDropUiTests(unittest.TestCase):
    def test_finder_drop_starts_background_import_without_opening_loader(self) -> None:
        drop_handler = js_function("handleNativeFinderDrop")

        self.assertIn("await runLibraryDroppedPathsImport(droppedPaths, targetFolderId, targetPath);", drop_handler)
        self.assertNotIn("openLibraryLoaderWindow", drop_handler)
        self.assertNotIn("saveLibraryImportDraft", drop_handler)

    def test_background_drop_always_skips_metadata(self) -> None:
        import_handler = js_function("runLibraryDroppedPathsImport")

        self.assertIn('metadata_mode: "skip"', import_handler)
        self.assertIn('state.libraryImportMetadataMode = "skip";', import_handler)
        self.assertNotIn("state.libraryLoaderOpen = true", import_handler)
        self.assertNotIn("renderLibraryLoader();", import_handler)

    def test_background_drop_reports_progress_in_library_status_bar(self) -> None:
        progress_handler = js_function("refreshLibraryImportJob")

        self.assertIn("function libraryDroppedImportActivityText", INDEX_HTML)
        self.assertIn("updateLibraryDroppedImportActivity(job);", progress_handler)
        self.assertIn("state.libraryImportNotice = {text: libraryDroppedImportActivityText(job)", INDEX_HTML)


if __name__ == "__main__":
    unittest.main()


class LibraryImportProgressRuntimeTests(unittest.TestCase):
    def test_progress_state_transitions_and_persistent_results(self):
        import json
        import subprocess
        import tempfile
        from pathlib import Path
        names=['metadataBatchActivityText','metadataRefreshActivityText','libraryActivityStatusItems','libraryActivityStatusText','libraryActivityStatusClass','renderLibraryActivityStatus',
               'updateLibraryActivityStatus','libraryDroppedImportActivityText','updateLibraryDroppedImportActivity',
               'refreshLibraryImportJob','stopLibraryImportPolling','loaderStatusText','openLibraryLoader']
        script='\n'.join(js_function(name) for name in names)
        harness=ACTIVITY_DOM_STUB+r'''
const assert=require('node:assert/strict');
const paperMetadataRequests=new Map();
const timeouts=[]; let refreshes=0, stopped=0, nativeOpens=0, drafts=0, renders=0;
const window={clearTimeout(){},setTimeout(fn){timeouts.push(fn);return timeouts.length},clearInterval(){stopped++},
  webkit:{messageHandlers:{libraryLoaderWindow:{postMessage(){nativeOpens++}}}}};
const IS_STANDALONE_LOADER_WINDOW=false;
function loadPendingLibraryImportDraft(){drafts++}
function renderLibraryLoader(){renders++}
function focusDialogSurface(){}
async function parseJsonResponse(r){return r.json()}
async function refreshLibraryAfterImportCompletion(){refreshes++}
async function refreshLibraryAfterImportReady(){refreshes++}
let state,fetch;
function reset(){state={libraryImportJobId:'job-a',libraryImportBusy:true,libraryImportBackground:true,
 libraryImportPoller:1,libraryImportInFlight:false,libraryImportNextPollAt:0,libraryImportPollFailures:0,
 libraryImportTargetPath:'Fixture folder',libraryImportJob:{status:'running',percent:25}};refreshes=0;stopped=0;}
function response(status,job){return {ok:status===200,status,json:async()=>({job,error:'fixture'})}}
(async()=>{
 reset();fetch=async()=>response(200,{status:'failed',error:'Fixture disk failure',result:{library_items_created:3}});
 await refreshLibraryImportJob();assert.equal(refreshes,1);assert.equal(state.libraryImportBusy,false);
 assert.match(libraryActivityStatusText(),/Partial import: 3/);assert.equal($('libraryImportDetails').hidden,false);
 updateLibraryActivityStatus('Unrelated action finished');timeouts.forEach(fn=>fn());
 assert.match(libraryActivityStatusText(),/Partial import: 3/);assert.equal($('libraryImportDismiss').hidden,false);
 openLibraryLoader({currentJob:true});assert.equal(nativeOpens,0);assert.equal(drafts,0);assert.equal(state.libraryLoaderOpen,true);
 reset();fetch=async()=>{throw new Error('temporary network error')};
 await refreshLibraryImportJob();assert.equal(state.libraryImportBusy,true);assert.equal(stopped,0);
 assert.match(libraryActivityStatusText(),/reconnecting/);assert.ok(state.libraryImportNextPollAt>Date.now());
 state.libraryImportNextPollAt=0;fetch=async()=>response(200,{status:'running',percent:40});
 await refreshLibraryImportJob();assert.equal(state.libraryImportPollFailures,0);assert.match(libraryActivityStatusText(),/40%/);
 fetch=async()=>response(200,{status:'completed',result:{library_items_created:8,identity_conflicts:[{}]}});
 await refreshLibraryImportJob();assert.equal(refreshes,1);assert.equal(state.libraryImportBusy,false);
 assert.match(libraryActivityStatusText(),/files kept/);
 reset();fetch=async()=>response(404);await refreshLibraryImportJob();
 assert.match(libraryActivityStatusText(),/unavailable/);assert.equal(state.libraryImportJob.status,'unavailable');assert.equal(refreshes,1);
 reset();let release;fetch=()=>new Promise(resolve=>release=resolve);
 const pending=refreshLibraryImportJob();await refreshLibraryImportJob();assert.equal(state.libraryImportInFlight,true);
 state.libraryImportJobId='job-b';release(response(200,{status:'completed'}));await pending;
 assert.equal(state.libraryImportBusy,true);assert.equal(refreshes,0);assert.equal(state.libraryImportInFlight,false);
 reset();state.libraryImportBackground=false;fetch=async()=>response(200,{status:'cancelled',result:{library_items_created:2}});
 await refreshLibraryImportJob();assert.equal(refreshes,1);assert.equal(state.libraryImportBusy,false);
 console.log('Import progress state transitions passed.');
})().catch(error=>{console.error(error);process.exit(1)});
'''
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'progress.cjs';path.write_text(script+'\n'+harness)
            import shutil
            node=shutil.which('node')
            if not node: self.skipTest('Node.js is required for the frontend runtime check')
            result=subprocess.run([node,str(path)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
