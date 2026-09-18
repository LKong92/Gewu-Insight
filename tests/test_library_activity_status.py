"""Independent activity indicators, using synthetic state without the running App."""
import shutil
import subprocess
import unittest

from tests.test_library_background_drop import ACTIVITY_DOM_STUB, js_function


@unittest.skipUnless(shutil.which("node"), "Node required")
class LibraryActivityStatusTests(unittest.TestCase):
    def test_concurrent_tasks_keep_separate_state_full_tooltips_and_stable_nodes(self):
        names = ["libraryActivityStatusItems", "libraryActivityStatusText", "libraryActivityStatusClass",
                 "renderLibraryActivityStatus", "updateLibraryActivityStatus", "metadataBatchActivityText",
                 "withLibraryActivityStatus", "downloadLibraryPdf"]
        script = "\n".join(js_function(name) for name in names)
        harness = ACTIVITY_DOM_STUB + r'''
const assert = require('node:assert/strict');
const timers = [];
const window = {setTimeout(fn){timers.push(fn);return timers.length;},clearTimeout(){}};
const paperMetadataRequests = new Map();
const state = {libraryActivities:[],libraryTab:'library',libraryTaskMode:'import',libraryImportBusy:true,
 libraryImportTargetPath:'Library / A very long folder name',libraryImportPath:'/synthetic/source',
 libraryImportNotice:{text:'Loading into Library / A very long folder name · 35% · import',live:true},
 libraryImportJob:{percent:35,stage:'import',current:35,total:100,message:'Importing example.rtf'},
 metadataRefreshJobs:[{job_id:'batch-1',status:'running',current:5000,total:10000,
 scope_label:'All Library and Space papers',metadata_mode:'full',current_paper:'Current paper'},
 {job_id:'batch-2',status:'paused',current:2,total:20,scope_label:'Other folder'}]};
function chip(id){return $('libraryActivityStatus').children.find(node=>node.dataset.activityId===id);}
function labels(){return $('libraryActivityStatus').children.map(node=>node.firstElementChild.textContent);}
function live(id){return chip(id).className.endsWith(' live');}
const downloads = new Map();
function requestPaperPdfDownload(payload){return new Promise((resolve,reject)=>downloads.set(payload.paper_id,{resolve,reject}));}
function libraryPdfContextPayload(id){return {paper_id:id};}
function updatePaperState(){} async function loadPaperFiles(){} function renderLibrary(){renderLibraryActivityStatus();}
function clearMyPublicationActivity(){} function setMyPublicationActivity(){} function renderMyPublications(){}
(async()=>{
 paperMetadataRequests.set('paper-1',{scope:'library',title:'A long title with <markup> & "quotes"'});
 paperMetadataRequests.set('author-paper',{scope:'author',title:'Other surface'});
 updateLibraryActivityStatus('Downloading PDF · Another paper',{activityId:'pdf:another',live:true});
 updateLibraryActivityStatus('Rename complete.');
 assert.equal(labels().length,6); // Two queues, import, single refresh, download, notice.
 assert.ok(live('batch:batch-1'));assert.ok(!live('batch:batch-2'));
 assert.ok(live('import'));assert.ok(live('metadata:paper-1'));assert.ok(live('pdf:another'));
 assert.ok(!live('notice'));assert.equal($('libraryImportDetails').hidden,false);
 assert.match(chip('batch:batch-1').title,/All Library and Space papers\nfull\nCurrent paper/);
 assert.match(chip('import').title,/synthetic\/source/);
 assert.match(chip('import').firstElementChild.textContent,/^Folder Loader · 35% · import/);
 assert.equal(chip('metadata:paper-1').title,'Refreshing info · A long title with <markup> & "quotes"');
 assert.equal(chip('metadata:paper-1').attributes['aria-label'],chip('metadata:paper-1').title);
 const queueNode=chip('batch:batch-1');state.metadataRefreshJobs[0].current=5001;renderLibraryActivityStatus();
 assert.equal(chip('batch:batch-1'),queueNode);assert.match(queueNode.title,/5001\/10000/);
 updateLibraryActivityStatus('Download failed · Another paper',{activityId:'pdf:another',failed:true});
 assert.ok(chip('pdf:another').className.endsWith(' err'));assert.ok(live('batch:batch-1'));
 const staleTimer=timers.at(-1);
 updateLibraryActivityStatus('Downloading again',{activityId:'pdf:another',live:true});
 staleTimer();assert.ok(live('pdf:another'));
 updateLibraryActivityStatus('',{activityId:'pdf:another'});
 assert.equal(chip('pdf:another'),undefined);assert.equal(chip('batch:batch-1'),queueNode);
 // Independent timers and completing one operation do not clear another.
 let finishA,finishB;
 const a=withLibraryActivityStatus('Moving A','Moved A',()=>new Promise(r=>finishA=r));
 const b=withLibraryActivityStatus('Moving B','Moved B',()=>new Promise(r=>finishB=r));
 finishA();await a;assert.ok(!live('operation:1'));assert.ok(live('operation:2'));
 timers.at(-1)();assert.equal(chip('operation:1'),undefined);assert.ok(live('operation:2'));
 finishB();await b;
 // Execute the actual download action with deferred, synthetic provider results.
 const downloadA=downloadLibraryPdf({paper_id:'a',title:'Full paper A'});
 const downloadB=downloadLibraryPdf({paper_id:'b',title:'Full paper B'});
 assert.ok(live('pdf:a'));assert.ok(live('pdf:b'));assert.match(chip('pdf:a').title,/Full paper A/);
 downloads.get('a').resolve({paper:{paper_id:'a'}});await downloadA;
 assert.ok(!live('pdf:a'));assert.ok(live('pdf:b'));assert.ok(live('import'));
 downloads.get('b').reject(Error('Synthetic failure'));await downloadB;
 assert.ok(chip('pdf:b').className.endsWith(' err'));assert.match(chip('pdf:b').title,/Full paper B/);
 assert.ok(live('batch:batch-1'));assert.equal(state.libraryImportBusy,true);
 // Remove a finished queue without replacing the remaining hovered indicators.
 state.metadataRefreshJobs[1].status='stopped';renderLibraryActivityStatus();
 assert.equal(chip('batch:batch-2'),undefined);assert.equal(chip('batch:batch-1'),queueNode);
 state.libraryImportNotice={text:'Loaded 100 items',live:false};state.libraryImportBusy=false;
 renderLibraryActivityStatus();assert.ok(!live('import'));assert.equal($('libraryImportDismiss').hidden,false);
 state.libraryImportNotice=null;renderLibraryActivityStatus();assert.equal(chip('import'),undefined);
 assert.ok(live('batch:batch-1'));assert.equal($('libraryImportDetails').hidden,false);
 console.log('Independent status, tooltips, polling, downloads and timer isolation passed.');
})().catch(error=>{console.error(error);process.exit(1)});
'''
        result = subprocess.run([shutil.which("node"), "-"], input=script + "\n" + harness,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
