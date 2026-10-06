"""Product UI regressions: real JavaScript functions, isolated fake DOM/data."""
import re
import shutil
import subprocess
import unittest

from paper_monitor.ui_server import INDEX_HTML


def function(name):
    match = re.search(r"    (?:async )?function " + name + r"\(", INDEX_HTML)
    body = INDEX_HTML[match.start():]
    end = re.search(r"\n    (?:async )?function ", body)
    return body[:end.start()] if end else body


@unittest.skipUnless(shutil.which("node"), "Node.js required")
class PaperFilesInteractionTests(unittest.TestCase):
    def run_js(self, names, code):
        script = "const assert = require('node:assert/strict');\n" + "\n".join(function(name) for name in names)
        result = subprocess.run(["node", "-e", script + "\n(async () => {\n" + code + "\n})().catch(error => {console.error(error); process.exit(1);});"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_forced_refresh_supersedes_an_older_empty_read(self):
        self.run_js(["paperFilesSnapshot", "loadPaperFiles"], r'''
global.state = {mode:'report', paperFilesByPaperId:{}, paperFileRequests:{}};
const replies = [];
global.libraryItemById = () => null;
global.fetch = () => new Promise(resolve => replies.push(files => resolve({ok:true,json:async()=>({paper_id:'paper',files})})));
const older = loadPaperFiles('paper');
const newer = loadPaperFiles('paper', {force:true});
assert.equal(replies.length, 2);
replies[1]([{id:5}]); await newer;
replies[0]([]); await older;
assert.deepEqual(paperFilesSnapshot('paper').files, [{id:5}]);
''')

    def test_download_replaces_monitor_empty_cache_before_supplement_failure(self):
        self.run_js(["paperFilesSnapshot", "applyPaperFilesPayloads", "loadPaperFiles",
                     "applyPaperPdfDownloadResult", "requestPaperPdfDownload", "performPaperPdfDownload",
                     "downloadPublishedPdfInBackground", "downloadScienceSupplementaryPdfs"], r'''
global.state = {mode:'report', libraryTab:'library', librarySelection:{id:9},
 paperFilesByPaperId:{paper:{paper_id:'paper',files:[]}}, paperFileRequests:{}};
global.pendingNativePublisherDownloads = new Map();
global.pendingPaperPdfDownloads = new Map();
let updated = [], renders = 0, failSupplement = false, sequence = 0;
global.updatePaperState = (id,paper) => updated.push(paper);
global.libraryItemById = () => ({paper_id:'paper'});
global.renderLibraryNavigationContent = options => {assert.equal(options.preserveRows,true); renders++;};
const saved = {paper:{paper_id:'paper',merged_pdf_path:'/Publisher.pdf'},
 paper_files:[{paper_id:'paper',files:[{id:5,file_type:'published_version',is_default:true}]}]};
const fallback = {url:'https://www.science.org/pdf',kind:'aaas-published-pdf',
 followup:{url:'https://www.science.org/article',kind:'aaas-supplement-discovery'}};
let response = {result:{status:'success'}, ...saved};
global.fetch = async () => ({ok:true,json:async()=>response});
global.window = {crypto:{randomUUID:()=>String(++sequence)}, setTimeout:()=>1, clearTimeout(){},
 webkit:{messageHandlers:{publisherPdfDownload:{postMessage(message) {
   const pending = pendingNativePublisherDownloads.get(message.token);
   if (message.context.publisher_download_kind === 'aaas-published-pdf') pending.resolve(saved);
   else {
     assert.equal(paperFilesSnapshot('paper').files[0].id,5);
     if (failSupplement) pending.reject(Error('Supplement unavailable'));
     else pending.resolve({supplement_urls:[]});
   }
 }}}}};
// A direct download from Journal Monitor replaces its cached empty list.
await requestPaperPdfDownload({paper_id:'paper'});
assert.equal(paperFilesSnapshot('paper').files[0].id,5);
assert.equal(renders,0);
// Switching to Library during the native download updates the selected list.
state.mode='library'; state.paperFilesByPaperId.paper={files:[]};
response = {result:{status:'failed'},browser_fallback:fallback}; failSupplement=true;
await assert.rejects(requestPaperPdfDownload({paper_id:'paper'}),/Supplement unavailable/);
assert.equal(paperFilesSnapshot('paper').files[0].id,5);
assert.equal(updated.at(-1).merged_pdf_path,'/Publisher.pdf');
assert.equal(renders,1);
// A publisher with no supplements must retain its saved main-paper result.
failSupplement=false; fallback.followup.kind='publisher-supplement-discovery';
const result=await requestPaperPdfDownload({paper_id:'paper'});
assert.equal(result.paper.merged_pdf_path,'/Publisher.pdf');
assert.equal(result.paper_files[0].files[0].id,5);
''')

    def test_saved_files_replace_empty_cache_and_supersede_inflight_reads(self):
        self.run_js(["paperFilesSnapshot", "applyPaperFilesPayloads", "loadPaperFiles"], r'''
global.state = {mode:'browser', paperFilesByPaperId:{paper:{paper_id:'paper',files:[]}}, paperFileRequests:{}};
const updated = [], replies = [];
global.updatePaperState = (id,paper) => updated.push([id,paper]);
global.libraryItemById = () => null;
global.fetch = () => new Promise(resolve => replies.push(files => resolve({ok:true,json:async()=>({paper_id:'paper',files})})));
const pending = loadPaperFiles('paper',{force:true});
const saved = {paper_id:'paper',files:[{id:9,file_type:'unknown'}],paper:{paper_id:'paper',title:'Saved article'}};
applyPaperFilesPayloads([saved]);
replies.shift()([]);
assert.equal(await pending, saved);
assert.equal(await loadPaperFiles('paper'), saved);
assert.deepEqual(updated, [['paper',saved.paper]]);
// Completion of an older request cannot clear a newer request either.
const older = loadPaperFiles('paper',{force:true});
applyPaperFilesPayloads([saved]);
const newer = loadPaperFiles('paper',{force:true});
const active = state.paperFileRequests.paper;
replies.shift()([]); await older;
assert.equal(state.paperFileRequests.paper,active);
replies.shift()([{id:9},{id:10}]); await newer;
assert.equal(paperFilesSnapshot('paper').files.length,2);
assert.equal(state.paperFileRequests.paper,undefined);
''')

    def test_item_open_uses_default_then_legacy_primary_and_explicit_preview(self):
        self.run_js(["openNativeLibraryEntry", "openLibraryPaperResource", "libraryPaperResourceIsPdf"], r'''
global.state = {};
let files = [], opened = [], messages = [], fail = false;
global.libraryItemById = id => ({paper_id: 'paper', paper: {main_pdf_path: '/old.pdf'}});
global.loadPaperFiles = async () => {if (fail) throw Error('offline'); return {files};};
global.openLibraryPdfInPreview = paper => opened.push(['Preview', paper.merged_pdf_path]);
global.openNativePaperFile = paper => opened.push(['native', paper.native_file_path]);
global.updateLibraryActivityStatus = message => messages.push(message);
global.libraryNativeTargetForEntry = () => ({path: '/folder', mode: 'folder'});
global.openNativeTarget = target => opened.push(['folder', target.path]);
const primary = {id: 1, is_primary: true, exists: true, local_path: '/old.pdf', extension: '.pdf'};
const preferred = {id: 2, is_default: true, exists: true, local_path: '/chosen.pdf', extension: '.pdf'};
files = [primary, preferred];
await openNativeLibraryEntry('item', 7);
assert.deepEqual(opened.pop(), ['Preview', '/chosen.pdf']);
files = [{...primary, file_type: 'unknown'}];
await openNativeLibraryEntry('item', 7);
assert.deepEqual(opened.pop(), ['Preview', '/old.pdf']);
files = [primary, {...preferred, local_path: '/notes.txt', extension: 'txt'}];
await openNativeLibraryEntry('item', 7);
assert.deepEqual(opened.pop(), ['native', '/notes.txt']);
files = [{...preferred, exists: false}, {...primary, file_type: 'invalid_file'}];
await openNativeLibraryEntry('item', 7);
assert.equal(opened.length, 0);
files = []; await openNativeLibraryEntry('item', 7);
fail = true; await openNativeLibraryEntry('item', 7);
assert.equal(opened.length, 0); assert.equal(messages.length, 3);
await openNativeLibraryEntry('folder', 1);
assert.deepEqual(opened.pop(), ['folder', '/folder']);
''')

    def test_paper_selection_keeps_row_dom_alive_for_native_double_click(self):
        self.run_js(["renderLibraryColumns"], r'''
const classes = new Set();
const folder = {dataset: {libraryColumnFolder: '1'}};
let replaced = 0, appended = 0, removed = 0, ids = [1];
const root = {classList: {contains: key => classes.has(key), toggle(key,on) {on ? classes.add(key) : classes.delete(key);}},
 querySelectorAll: () => [folder], querySelector: () => ({remove() {removed++;}}),
 insertAdjacentHTML(position, markup) {assert.equal(position, 'beforeend'); appended++;},
 set innerHTML(value) {replaced++;}};
global.$ = id => id === 'libraryColumns' ? root : null;
global.activeLibraryNavigationToolContext = () => null;
global.state = {librarySelection: {type: 'item', id: 2}};
global.libraryColumnFolderIds = () => ids;
global.selectedLibraryPathFolderIds = () => new Set();
global.libraryTableViewActive = () => false;
global.libraryItemById = id => ({id});
global.libraryPaperResourcesColumnMarkup = () => '<section>Files</section>';
global.libraryColumnMarkup = () => '<section>Rows</section>';
assert.equal(renderLibraryColumns({preserveRows: true}), true);
assert.equal(replaced, 0); assert.equal(appended, 1);
// Asynchronous file loading between clicks must also leave the row intact.
assert.equal(renderLibraryColumns({preserveRows: true}), true);
assert.equal(replaced, 0);
ids = [2];
assert.equal(renderLibraryColumns({preserveRows: true}), false);
assert.equal(replaced, 1);
''')
        self.assertIn('renderLibraryNavigationContent({preserveRows: type === "item"})', function("selectLibraryEntry"))
        self.assertIn('renderLibraryNavigationContent({preserveRows: true})', function("loadPaperFiles"))

    def test_footer_toggles_only_annotation_and_source_without_opening_file(self):
        self.run_js(["wireLibraryPaperFilesDropTarget", "wireLibraryResourceInteractions"], r'''
const handlers = {}, toggleHandlers = {}, details = {hidden: true}, attrs = {}, icon = {};
const toggle = {addEventListener: (name, fn) => toggleHandlers[name] = fn,
 setAttribute: (key, value) => attrs[key] = value, querySelector: () => icon};
const card = {dataset: {libraryResourcePaperId: 'paper', libraryResourceId: '8'},
 addEventListener: (name, fn) => handlers[name] = fn,
 querySelector: selector => selector === '[data-library-resource-toggle]' ? toggle : details};
const shell = {dataset: {}, addEventListener() {},
 querySelectorAll: selector => selector === '.library-resource-card[data-library-resource-id]' ? [card] : []};
global.state = {expandedPaperResourceProperties: new Set()};
let selected = 0, opened = 0, stopped = 0;
global.setLibraryPaperResourceSelection = () => selected++;
global.libraryPaperResourceById = () => ({});
global.openLibraryPaperResource = () => opened++;
wireLibraryResourceInteractions(shell);
const event = {target: {closest: () => toggle}, stopPropagation() {stopped++;}, preventDefault() {}};
toggleHandlers.click(event);
assert.equal(details.hidden, false); assert.equal(attrs['aria-expanded'], 'true');
assert.ok(state.expandedPaperResourceProperties.has('paper:8'));
handlers.click(event); handlers.dblclick(event); toggleHandlers.dblclick(event);
assert.equal(opened, 0); assert.equal(selected, 0);
toggleHandlers.click(event);
assert.equal(details.hidden, true); assert.equal(attrs['aria-expanded'], 'false');
assert.equal(state.expandedPaperResourceProperties.size, 0);
handlers.dblclick({...event, target: {closest: () => null}});
assert.equal(opened, 1);
''')
        markup = function("libraryPaperResourcesColumnMarkup")
        self.assertIn('library-resource-extra-properties', markup)
        self.assertIn('${expanded ? "" : " hidden"}', markup)
        self.assertLess(markup.index('>File type</span>'), markup.index('library-resource-extra-properties'))
        self.assertIn('data-library-resource-toggle', markup)

    def test_delete_waits_for_success_and_blocks_duplicate_requests(self):
        self.run_js(["deleteSelectedLibraryPaperResource"], r'''
const file = {id: 2, display_name: 'Note', exists: true};
global.state = {libraryPaperResourceSelection: {paperId: 'paper', resourceId: 2}, deletingPaperResources: new Set()};
let resolve, fail = false, requests = 0, renders = 0, statuses = [], files = [file];
global.window = {confirm: () => true, requestAnimationFrame() {}};
global.updateLibraryActivityStatus = message => statuses.push(message);
global.orderedLibraryPaperResources = () => files;
global.deletePaperFile = async () => {requests++; await new Promise(r => resolve = r); if (fail) throw Error('denied'); files = []; return {deleted: {trashed: true}};};
global.renderLibraryNavigationContent = options => {assert.equal(options.preserveRows, true); renders++;};
const first = deleteSelectedLibraryPaperResource(file);
await deleteSelectedLibraryPaperResource(file);
assert.equal(requests, 1); assert.equal(renders, 0); assert.equal(files.length, 1);
assert.ok(statuses[0].includes('Moving'));
resolve(); await first;
assert.equal(renders, 1); assert.equal(files.length, 0); assert.equal(state.deletingPaperResources.size, 0);
files = [file]; fail = true; state.libraryPaperResourceSelection = {paperId: 'paper', resourceId: 2};
const second = deleteSelectedLibraryPaperResource(file); resolve(); await second;
assert.equal(renders, 1); assert.equal(files.length, 1); assert.equal(state.deletingPaperResources.size, 0);
''')
