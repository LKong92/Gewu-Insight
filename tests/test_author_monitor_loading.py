"""Author cards must remain available while footer queue counting is pending."""
import shutil
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from paper_monitor import ui_server as ui
from paper_monitor.storage import Storage
from tests.test_author_monitor import paper, scholar_profile
from tests.test_author_monitor_status import function_source


class AuthorMonitorLoadingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'monitor.sqlite'
        self.storage = Storage(self.path)
        self.addCleanup(self.storage.close)
        self.author = self.storage.add_author_monitor(scholar_profile('one', 'One'))['id']
        self.other = self.storage.add_author_monitor(scholar_profile('two', 'Two'))['id']
        for pid, author in [('one', self.author), ('two', self.other)]:
            self.storage.upsert_paper(paper(pid, 'Title ' + pid, '2026-09-20'))
            self.storage.add_author_monitor_paper(author_monitor_id=author, paper_id=pid, unread=True)

    def test_cards_only_preserves_scoped_cards_and_index_readiness(self):
        for cached in (False, True):
            if cached:
                ui.rebuild_author_monitor_card_cache(self.path)
            for author in (self.author, self.other, 0, -1, 9999):
                with self.subTest(cached=cached, author=author):
                    with patch.object(ui.author_metadata_work, 'snapshot', return_value={'eligible': 123}) as counts:
                        full = ui.author_monitor_snapshot(self.storage, author_monitor_id=author)
                        counts.assert_called_once()
                    with patch.object(ui.author_metadata_work, 'snapshot', side_effect=AssertionError('Footer blocks cards')) as counts:
                        cards = ui.author_monitor_snapshot(
                            self.storage, author_monitor_id=author, include_metadata_work=False
                        )
                        counts.assert_not_called()
                    full.pop('metadataWork')
                    full.pop('checkedAt'); cards.pop('checkedAt')
                    self.assertEqual(cards, full)
            with patch.object(ui.author_metadata_work, 'snapshot', return_value={'eligible': 123}):
                full = ui.author_monitor_index_snapshot(self.storage)
            with patch.object(ui.author_metadata_work, 'snapshot', side_effect=AssertionError('Footer blocks index')):
                cards = ui.author_monitor_index_snapshot(self.storage, include_metadata_work=False)
            full.pop('metadataWork')
            full.pop('checkedAt'); cards.pop('checkedAt')
            self.assertEqual(cards, full)
            self.assertEqual(cards['indexReady'], cached)
            self.assertEqual(len(cards['papers']), 2 if cached else 0)

    def request(self, query):
        handler = SimpleNamespace(configured_db_path=self.path, send_json=Mock())
        ui.PaperMonitorUiHandler.handle_author_monitor(handler, query)
        return handler.send_json.call_args.args[0]

    def test_handler_keeps_default_response_and_summary_counts(self):
        ui.rebuild_author_monitor_card_cache(self.path)
        for query in ({}, {'index': ['1']}, {'summary': ['1'], 'cards_only': ['1']}):
            with self.subTest(query=query), patch.object(ui.author_metadata_work, 'snapshot', return_value={'eligible': 123}) as counts:
                result = self.request(query)
                self.assertEqual(result['metadataWork'], {'eligible': 123})
                counts.assert_called_once()

    def test_card_requests_finish_while_summary_counting_is_blocked(self):
        ui.rebuild_author_monitor_card_cache(self.path)
        entered, release = threading.Event(), threading.Event()

        def count(_storage):
            entered.set()
            if not release.wait(5):
                raise AssertionError('Summary was not released')
            return {'scope': 'all_authors', 'eligible': 123}

        with patch.object(ui.author_metadata_work, 'snapshot', side_effect=count) as counts, ThreadPoolExecutor(3) as pool:
            summary = pool.submit(self.request, {'summary': ['1']})
            try:
                self.assertTrue(entered.wait(2))
                selected = pool.submit(self.request, {'author_id': [str(self.author)], 'cards_only': ['1']})
                index = pool.submit(self.request, {'index': ['1'], 'cards_only': ['1']})
                self.assertEqual([p['paper_id'] for p in selected.result(timeout=2)['papers']], ['one'])
                self.assertEqual({p['paper_id'] for p in index.result(timeout=2)['papers']}, {'one', 'two'})
                self.assertFalse(summary.done())
                self.assertEqual(counts.call_count, 1)
            finally:
                release.set()
            self.assertEqual(summary.result(timeout=2)['metadataWork']['eligible'], 123)

    def test_ui_renders_before_summary_and_preserves_selection_when_index_arrives(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is needed to execute product UI functions')
        functions = [
            ('openAuthorMonitor', 'function openAuthorMonitorDialog', True),
            ('loadAuthorMonitorScope', 'function selectAuthorMonitorScope', True),
            ('fetchAuthorMonitorSnapshot', 'async function reconcileAddedAuthorMonitor', True),
            ('applyAuthorMonitorSnapshot', 'function applyAuthorMonitorIndex', False),
            ('applyAuthorMonitorIndex', 'function prefetchAuthorMonitorIndex', False),
            ('prefetchAuthorMonitorIndex', 'async function loadAuthorMonitorScope', False),
            ('refreshAuthorMonitorSummary', 'function startAuthorMonitorSummaryPolling', True),
            ('authorMonitorIdleActivity', 'function authorMonitorDisplayedActivity', False),
            ('authorMonitorIsBackgroundScholarJob', 'function syncAuthorMonitorBackgroundScholarStatus', False),
        ]
        source = '\n'.join(function_source(name, next_name, asynchronous=async_) for name, next_name, async_ in functions)
        harness = r'''
const assert=require('node:assert/strict');
const state={mode:'library',authorMonitorSelectedId:4,authorMonitorPapers:[],authorMonitors:[],
  authorMonitorLoadToken:0,authorMonitorMetadataWork:{},authorMonitorPaperCache:new Map(),
  authorMonitorSelectedPaperByAuthor:new Map(),authorMonitorLoaded:false};
const document={documentElement:{dataset:{}}};
const window={clearTimeout(){},setTimeout(){throw Error('Unexpected retry');}};
const AUTHOR_MONITOR_INDEX_MAX_RETRIES=40,AUTHOR_MONITOR_INDEX_RETRY_MS=350;
const requests=[],renders=[],elements=new Map();
const authors=[{id:4,name:'One',status:'ready',paper_count:1},{id:14,name:'Two',status:'ready',paper_count:1}];
const cards=[{paper_id:'one',title:'One',author_monitor_ids:[4]},{paper_id:'two',title:'Two',author_monitor_ids:[14]}];
let finishSummary,finishIndex;
const summaryReply=new Promise(resolve=>finishSummary=resolve);
const indexReply=new Promise(resolve=>finishIndex=resolve);
async function fetchAuthorMonitorReadSafeJson(url){
  requests.push(url);
  if(url.includes('summary=1')) return summaryReply;
  assert.ok(url.includes('cards_only=1'),url);
  if(url.includes('index=1')) return indexReply;
  assert.ok(url.includes('author_id=4'));
  return {authors,papers:[cards[0]],selectedAuthorId:4,paperScopeAuthorId:4};
}
function $(id){if(!elements.has(id))elements.set(id,{innerHTML:''});return elements.get(id);}
async function loadFieldSettings(){}
function closeLibraryQuickLook(){} function closeAnalysis(){} function stopArxivUpdateCountdown(){}
function setPrimaryView(){} function updateAuthorMonitorActivityStatus(){}
function syncAuthorMonitorActivityDisplay(){} function updateAuthorMonitorTopDot(){}
function syncAuthorMonitorBackgroundScholarStatus(){} function updateScholarCooldownControls(){}
function invalidateAuthorMonitorViewCache(){} function persistAuthorMonitorSelectedId(){}
function rememberCurrentAuthorMonitorPapers(){} function restoreCachedAuthorMonitorPapers(){return false;}
function authorMonitorScopeHasExpectedPapers(){return false;}
function initialAuthorMonitorSelectedId(){return 4;}
function monitorStatusMarkup(text){return text;}
function renderAuthorMonitor(){renders.push(state.authorMonitorPapers.map(p=>p.paper_id));}
function refreshAuthorMonitorInPlace(){renderAuthorMonitor();}
function authorMonitorVisiblePapers(){return state.authorMonitorPapers.filter(p=>p.author_monitor_ids.includes(state.authorMonitorSelectedId));}
function scheduleAuthorMonitorIdleEnrichment(){}
function pollAuthorMonitorInitialImport(){throw Error('No active import');}
function autoStatusTime(value){return value;}
''' + source + r'''
(async()=>{
  assert.equal(authorMonitorIdleActivity('secondary').text,'Author metadata · Checking status...');
  // A footer recount may already be running when the tab opens.
  const pendingSummary=refreshAuthorMonitorSummary();
  const opened=openAuthorMonitor();
  let timer;
  try {
    await Promise.race([opened,new Promise((_,reject)=>timer=setTimeout(()=>reject(Error('Cards waited for footer')),500))]);
  } finally {clearTimeout(timer);}
  assert.equal(state.authorMonitorSummaryLoading,true);
  assert.ok(renders.some(ids=>ids.includes('one')));
  assert.equal(state.authorMonitorSelectedPaperId,'one');
  assert.equal(state.authorMonitorLoading,false);
  assert.equal(requests.filter(url=>url.includes('summary=1')).length,1);
  assert.equal(requests.filter(url=>url.includes('index=1')).length,1);
  assert.ok(!('eligible' in state.authorMonitorMetadataWork));
  // Finish the footer, then the independently prefetched index.
  const work={scope:'all_authors',eligible:123,waiting_retry:4,status:'resting'};
  finishSummary({authors,metadataWork:work,indexReady:true});
  await pendingSummary;
  assert.equal(state.authorMonitorMetadataWork,work);
  assert.ok(authorMonitorIdleActivity('secondary').text.includes('123 ready'));
  const indexPromise=state.authorMonitorIndexLoadingPromise;
  finishIndex({authors,papers:cards,indexReady:true});
  await indexPromise;
  assert.equal(state.authorMonitorMetadataWork,work);
  assert.equal(state.authorMonitorSelectedId,4);
  assert.equal(state.authorMonitorSelectedPaperId,'one');
  assert.equal(state.authorMonitorPapers.length,2);
  assert.equal(state.authorMonitorIndexLoaded,true);
})().catch(error=>{console.error(error);process.exit(1);});
'''
        script = Path(self.tmp.name) / 'loading.js'
        script.write_text(harness)
        result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
