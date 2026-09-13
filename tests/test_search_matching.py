"""Parity and Library search regression checks using synthetic paper records."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from paper_monitor import search_matching, ui_server
from paper_monitor.storage import Storage


class SearchMatchingTests(unittest.TestCase):
    def test_frontend_backend_rules_and_rank_agree(self):
        samples = [
            ('Majorana zero modes', 'majorna', 1),
            ('Majorana zero modes', 'MAJORANA', 3),
            ('Majorana zero modes', 'zero majorana', 2),
            ('Superconducting materials', 'superconductivity', 1),
            ('Cooling particles', 'cooled particle', 2),
            ('Quantum coherent systems', 'quantum missing systems', 2),
            ('10.1002/ADVS.202516394', 'https://doi.org/10.1002/advs.202516394', 3),
            ('Électron scattering', 'electron', 3),
            ('量子计算研究', '量子计算', 3),
            ('Majorana zero modes', 'chemistry', 0),
        ]
        # Scores are compared across real JS and Python; representative behavior
        # assertions do not infer expectations from the implementation.
        for text, query, expected in samples:
            self.assertEqual(search_matching.scorer(query)(text), expected, (text, query))
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js required for parity')
        html = ui_server.INDEX_HTML
        source = html[html.index('    function librarySearchMatches('):html.index('    function libraryFolderPath(')]
        pairs = [(text, query) for text, query, _ in samples]
        pairs += [('Majorana quantum superconductivity', word) for word in
                  ['major', 'majoranna', 'majoran', 'quantom', 'quntum', 'superconducting', '', 'XYZ', '!!!']]
        script = source + '\nconsole.log(JSON.stringify(' + json.dumps(pairs) + '.map(([h,q])=>librarySearchScore(h,q))));'
        result = subprocess.run([node, '-'], input=script, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [search_matching.scorer(q)(h) for h,q in pairs])

    def test_remote_search_runs_only_latest_pending_query(self):
        node = shutil.which('node')
        if not node: self.skipTest('Node.js required')
        html = ui_server.INDEX_HTML
        source = html[html.index('    function requestRemoteLibrarySearch('):html.index('    function libraryVisibleEntries(')]
        script = r"""
const assert=require('node:assert/strict');
const pending=[],requests=[];
const state={query:'major',mode:'library',libraryItems:[],libraryRemoteSearchSequence:0};
const librarySearchNormalize=s=>s.trim().toLowerCase(),currentSurfaceSearchScope=()=> 'library';
const window={setTimeout:()=>1,clearTimeout:()=>{}},updateLibraryActivityStatus=()=>{},updateLibrarySearchTools=()=>{};
const rebuildLibraryIndexes=()=>{},resetRemoteLibrarySearch=()=>{},renderLibrary=()=>requests.push('render:'+state.libraryRemoteSearchQuery);
const fetch=url=>{requests.push(url);return new Promise(resolve=>pending.push(resolve));};
""" + source + r"""
(async()=>{
 const first=requestRemoteLibrarySearch(state.query);
 state.query='majorna';await requestRemoteLibrarySearch(state.query);
 state.query='majorana';await requestRemoteLibrarySearch(state.query);
 assert.equal(pending.length,1,'typing cannot overlap whole-Library scans');
 pending.shift()({ok:true,json:async()=>({results:[],total:0})});await first;
 assert.equal(pending.length,1,'latest query follows completion');
 assert.equal(requests.length,2);assert.ok(requests[1].includes('q=majorana'));
 pending.shift()({ok:true,json:async()=>({results:[],total:0})});
 await new Promise(r=>setTimeout(r,0));
 assert.equal(state.libraryRemoteSearchQuery,'majorana');assert.equal(requests.at(-1),'render:majorana');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        result=subprocess.run([node,'-'],input=script,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_remote_search_retains_typos_ranks_exact_and_excludes_recycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp)/'test.sqlite')
            try:
                folder = storage.create_library_folder(parent_id=1, name='Synthetic field')
                for pid, title in [('typo','A Majorna observation'),('exact','Z Majorana observation'),('other','Unrelated chemistry')]:
                    storage.upsert_paper({'paper_id':pid,'title':title,'journal':'Fixture','source':'fixture',
                        'raw':{'author':[{'given':'Synthetic','family':'Einstein'}],'arxiv_id':'2609.12345' if pid == 'exact' else ''}})
                    storage.add_library_item(paper_id=pid,folder_id=folder['id'])
                result = ui_server.library_file_search_snapshot(storage, 'majorana', limit=1)
                self.assertEqual(result['total'],2)
                self.assertEqual(result['results'][0]['item']['paper_id'],'exact')
                self.assertEqual(ui_server.library_file_search_snapshot(storage,'majorna')['total'],2)
                self.assertEqual(ui_server.library_file_search_snapshot(storage,'Einsten')['total'],3)
                self.assertEqual(ui_server.library_file_search_snapshot(storage,'2609.12345')['total'],1)
                storage.conn.execute("UPDATE library_folders SET trashed_at='fixture' WHERE id=?", (folder['id'],))
                storage.conn.commit()
                self.assertEqual(ui_server.library_file_search_snapshot(storage,'majorana')['total'],0)
            finally:
                storage.close()


if __name__ == '__main__': unittest.main()
