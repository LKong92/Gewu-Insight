"""Execute the real footer/job predicates; idle must never masquerade as work."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from paper_monitor import ui_server as ui


def function_source(name, next_name, *, asynchronous=False):
    start = ('async ' if asynchronous else '') + 'function ' + name
    return start + ui.INDEX_HTML.split(start, 1)[1].split('    ' + next_name, 1)[0]


class AuthorMonitorStatusTests(unittest.TestCase):
    def run_js(self, assertions):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is needed to execute product UI functions')
        source = '\n'.join([
            function_source('authorMonitorIsBackgroundScholarJob', 'function syncAuthorMonitorBackgroundScholarStatus'),
            function_source('syncAuthorMonitorBackgroundScholarStatus', 'function authorMonitorEnrichmentProgressText'),
            function_source('authorMonitorIdleActivity', 'function authorMonitorDisplayedActivity'),
            function_source('pollAuthorMonitorInitialImport', 'async function addAuthorMonitorProfile', asynchronous=True),
        ])
        harness = '''
const assert = require('node:assert/strict');
const state = {authorMonitors: [], authorMonitorSelectedId: 0, mode:'author'};
const calls=[];
const window={clearTimeout(){},setTimeout(){throw Error('Inactive status must not keep polling');}};
let selected=null;
function selectedAuthorMonitor(){return selected;}
function scholarGlobalCooldownActive(){return false;}
function autoStatusTime(value){return value;}
function updateAuthorMonitorActivityStatus(text,options){
  calls.push({text,options});
  state.authorMonitorSecondaryActivityKind=text ? options.kind : '';
  state.authorMonitorSecondaryActivityText=text;
  state.authorMonitorSecondaryActivityLive=Boolean(options.live);
}
function updateAuthorMonitorTopDot(){}
function refreshAuthorMonitorInPlace(){}
function scheduleAuthorMonitorIdleEnrichment(){throw Error('Inactive status must not start enrichment');}
async function fetchAuthorMonitorSnapshot(){return {authors:state.authorMonitors};}
function applyAuthorMonitorSnapshot(snapshot){state.authorMonitors=snapshot.authors;syncAuthorMonitorBackgroundScholarStatus();}
''' + source + '\n(async()=>{\n' + assertions + '\n})().catch(e=>{console.error(e);process.exit(1);});'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'status.js'
            path.write_text(harness)
            result = subprocess.run([node, str(path)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_queued_or_refreshing_authors_are_running(self):
        self.run_js('''
for (const status of ['idle','ready','success','partial','error','cooldown','']) {
  assert.equal(authorMonitorIsBackgroundScholarJob({status}),false,status);
}
assert.equal(authorMonitorIsBackgroundScholarJob(null),false);
for (const status of ['queued','refreshing']) {
  assert.equal(authorMonitorIsBackgroundScholarJob({status}),true,status);
}
''')

    def test_switching_authors_clears_stale_repair_job_and_retains_real_jobs(self):
        self.run_js('''
const repaired={id:4,name:'Stevan',status:'idle',message:'Previous identity issue repaired.',last_success_at:'September 11'};
const other={id:14,name:'JC Davis',status:'success',message:'No new publications.',last_success_at:'September 23'};
state.authorMonitors=[repaired,other];
for (const author of [other,repaired,null,other]) {
  selected=author;
  state.authorMonitorSecondaryActivityKind='scholar-background';
  state.authorMonitorSecondaryActivityText=repaired.message;
  state.authorMonitorSecondaryActivityLive=true;
  syncAuthorMonitorBackgroundScholarStatus();
  assert.equal(state.authorMonitorSecondaryActivityText,'');
  assert.equal(state.authorMonitorSecondaryActivityLive,false);
  assert.equal(authorMonitorIdleActivity().live,false);
  if(author===other) assert.ok(!authorMonitorIdleActivity().text.includes('repair'));
}
const queued={id:27,name:'New author',status:'queued',message:'Initial OpenAlex import queued...'};
state.authorMonitors.push(queued);
syncAuthorMonitorBackgroundScholarStatus();
assert.equal(state.authorMonitorSecondaryActivityLive,true);
assert.ok(state.authorMonitorSecondaryActivityText.includes('New author'));
queued.status='success';
syncAuthorMonitorBackgroundScholarStatus();
assert.equal(state.authorMonitorSecondaryActivityText,'');
''')

    def test_idle_polling_ends_without_failure_or_enrichment(self):
        self.run_js('''
for (const status of ['idle','ready']) {
  for (const selectedId of [4,14]) {
    state.authorMonitorSelectedId=selectedId;
    state.authorMonitors=[{id:4,name:'Stevan',status,message:'Waiting for the next scheduled check.'}];
    state.authorMonitorSecondaryActivityKind='scholar-background';
    state.authorMonitorSecondaryActivityLive=true;
    calls.length=0;
    await pollAuthorMonitorInitialImport(4);
    assert.equal(state.authorMonitorSecondaryActivityText,'');
    assert.equal(state.authorMonitorSecondaryActivityLive,false);
    assert.ok(calls.every(call=>!call.text));
  }
}
''')

    def test_all_polling_entry_points_share_the_same_predicate(self):
        self.assertNotIn('["idle", "queued", "refreshing"]', ui.INDEX_HTML)
        self.assertEqual(ui.INDEX_HTML.count('const pendingImport = state.authorMonitors.find(\n'), 3)
        for section in ui.INDEX_HTML.split('const pendingImport = state.authorMonitors.find(\n')[1:]:
            self.assertEqual(section.split(');', 1)[0].strip(), 'authorMonitorIsBackgroundScholarJob')


if __name__ == '__main__':
    unittest.main()
