import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from paper_monitor.storage import Storage
from paper_monitor.ui_server import (
    INDEX_HTML,
    annotate_papers_with_library_status,
    paper_to_api,
    theme_paper_to_api,
)


def ui_function_block(start, end):
    return start + INDEX_HTML.split(start, 1)[1].split(end, 1)[0]


@unittest.skipUnless(shutil.which("node"), "Node.js is required for monitor state regression tests")
class MonitorPaperUpdateTests(unittest.TestCase):
    def run_javascript(self, assertions):
        # Build the two real API representations using an isolated database.
        with tempfile.TemporaryDirectory() as tmp:
            storage = Storage(Path(tmp) / "monitor.sqlite")
            try:
                storage.upsert_paper({
                    "paper_id": "subject-paper", "title": "Quantum sensor example",
                    "journal": "Example Journal", "publication_date": "2026-08-31",
                    "source": "crossref", "section_allowed": True,
                })
                for group in ("sensing", "computing"):
                    storage.record_theme_result(
                        paper_id="subject-paper", group_key=group, group_name=group,
                        query="quantum", score=3, hits=["quantum"],
                        window_start="2026-08-31", window_end="2026-08-31",
                    )
                before = storage.list_theme_papers(window_start="2026-08-31", window_end="2026-08-31", group_keys=["sensing", "computing"])
                monitor = theme_paper_to_api(annotate_papers_with_library_status(storage, before)[0])
                storage.add_library_item(paper_id="subject-paper", folder_id=1)
                updated = paper_to_api(annotate_papers_with_library_status(storage, [storage.get_paper("subject-paper")])[0])
                after = storage.list_theme_papers(window_start="2026-08-31", window_end="2026-08-31", group_keys=["sensing", "computing"])
                self.assertEqual(after[0]["theme_groups"], before[0]["theme_groups"])
                self.assertNotIn("theme_groups", updated)
                self.assertTrue(updated["in_library"])
            finally:
                storage.close()
        functions = "\n".join([
            ui_function_block("function updatePaperState", "function initialAuthorMonitorSelectedId"),
            ui_function_block("function applyPaperFilesPayloads", "function paperFileRoleLabel"),
            ui_function_block("async function addPaperToLibrary", "async function moveLibraryEntry"),
            ui_function_block("function setReportLibraryButtonShowState", "async function navigateToPaperInLibrary"),
            ui_function_block("async function downloadReportPaper", "async function deletePaperAsset"),
            ui_function_block("const pendingPaperPdfDownloads =", "async function downloadScienceSupplementaryPdfs"),
            ui_function_block("function themePaperMatchesGroup", "function selectThemeSubject"),
        ])
        setup = r'''
const assert = require("node:assert/strict");
const paperId = monitor.paper_id;
const state = {
  mode: "theme", activeThemeGroupKey: "sensing", selectedDate: "2026-08-31",
  reportSelectedPaperId: paperId, themeGroups: [{key: "sensing"}, {key: "computing"}],
  monitorPaperOperations: new Map(), papers: [], themePapers: [structuredClone(monitor)], reportCache: {},
  themePapersByDate: {}, libraryLoaded: false, libraryItems: [],
  myPublications: [], authorMonitorPapers: [], paperFilesByPaperId: {}, paperFileRequests: {}
};
// These aliases are created by applyThemeReportData and renderThemeMonitor.
state.papers = state.themePapers;
state.themePapersByDate["2026-08-31|ALL"] = state.themePapers;
function themeVisiblePapers() { return state.themePapers; }
function invalidateAuthorMonitorViewCache() {}
const classes = new Set();
const button = {
  dataset: {libraryState: "add"}, disabled: false, textContent: "Add to Library",
  classList: {contains: (x) => classes.has(x), add: (x) => classes.add(x), remove: (x) => classes.delete(x)},
  setAttribute() {}
};
const status = {textContent: "", className: ""};
const article = {querySelector: (selector) => selector.includes('add-library') ? button : status};
const viewport = {paperId, scrollTop: 310, anchorOffset: 12};
function captureMonitorViewport() { return viewport; }
let renderOptions;
let renderedGroups;
function renderCurrentPaperSurface() { throw new Error("Background action must not render a workspace"); }
function setMonitorPaperOperation(paperId, kind, operation) {
  const operations = state.monitorPaperOperations.get(paperId) || {};
  if (operation) operations[kind] = operation; else delete operations[kind];
  state.monitorPaperOperations.set(paperId, operations);
  renderedGroups = groupedThemePapers();
}
async function fetch(url, options) {
  assert.equal(url, "/api/library/items");
  assert.deepEqual(JSON.parse(options.body), {paper_id: paperId, folder_id: 1, snapshot: false});
  return {ok: true, json: async () => ({paper: updated})};
}
'''
        script = "const monitor = " + json.dumps(monitor) + ";\nconst updated = " + json.dumps(updated) + ";\n"
        script += setup + functions + "\n(async () => {\n" + assertions + "\n})().catch(error => {console.error(error); process.exitCode = 1;});"
        result = subprocess.run([shutil.which("node"), "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_to_library_keeps_subject_paper_visible_and_selected_immediately(self):
        self.run_javascript(r'''
await addPaperToLibrary(article, paperId, {folderId: 1});
assert.equal(status.textContent, "");
assert.equal(state.themePapers.length, 1);
assert.deepEqual(state.themePapers[0].theme_groups, monitor.theme_groups);
assert.deepEqual(state.themePapers[0].theme_hits, monitor.theme_hits);
assert.equal(state.themePapers[0].theme_score, monitor.theme_score);
assert.deepEqual(renderedGroups.map(group => group.papers.length), [1, 1]);
assert.equal(state.papers[0].in_library, true);
assert.equal(button.textContent, "Show in Library");
assert.equal(button.disabled, false);
assert.equal(state.selectedDate, "2026-08-31");
assert.equal(state.activeThemeGroupKey, "sensing");
assert.equal(state.reportSelectedPaperId, paperId);
assert.equal(state.monitorPaperOperations.get(paperId).library, undefined);
// A later generic image/download response must not discard the groups either.
updatePaperState(paperId, {paper_id: paperId, image_url: "local-figure", library_status_loaded: false});
assert.deepEqual(groupedThemePapers().map(group => group.papers.length), [1, 1]);
assert.equal(state.themePapers[0].in_library, true);
assert.equal(state.themePapersByDate["2026-08-31|ALL"][0].image_url, "local-figure");
''')

    def test_download_survives_navigation_and_duplicate_click_without_rendering(self):
        self.run_javascript(r'''
let complete, requests = 0;
fetch = async () => { requests++; return await new Promise(resolve => { complete = resolve; }); };
state.paperFilesByPaperId = {[paperId]: {files: []}};
state.paperFileRequests = {[paperId]: Promise.resolve({files: []})};
const first = downloadReportPaper(article, paperId);
assert.equal(state.monitorPaperOperations.get(paperId).download.busy, true);
state.mode = "browser";
await downloadReportPaper(article, paperId);
assert.equal(requests, 1);
complete({ok: true, json: async () => ({paper: {...updated, merged_pdf_path: "fixture.pdf"}})});
await first;
assert.equal(state.mode, "browser");
assert.equal(state.paperFilesByPaperId[paperId], undefined);
assert.equal(state.paperFileRequests[paperId], undefined);
assert.equal(state.papers[0].merged_pdf_path, "fixture.pdf");
assert.equal(state.monitorPaperOperations.get(paperId).download, undefined);
''')

    def test_add_replaces_recycled_file_cache_without_changing_monitor_selection(self):
        self.run_javascript(r'''
state.paperFilesByPaperId[paperId] = {files: [{id: 10, local_path: "Recycle/old.pdf"}]};
state.paperFileRequests[paperId] = Promise.resolve({files: []});
fetch = async () => ({ok: true, json: async () => ({paper: updated,
  paper_files: [{paper_id: paperId, paper: {...updated, merged_pdf_path: "Library/new.pdf"},
    files: [{id: 10, local_path: "Library/new.pdf"}]}]})});
await addPaperToLibrary(article, paperId, {folderId: 1});
assert.equal(state.paperFilesByPaperId[paperId].files[0].local_path, "Library/new.pdf");
assert.equal(state.paperFileRequests[paperId], undefined);
assert.equal(state.reportSelectedPaperId, paperId);
assert.equal(state.activeThemeGroupKey, "sensing");
assert.equal(state.mode, "theme");
''')

    def test_shared_download_request_keeps_distinct_papers_independent_and_allows_retry(self):
        self.run_javascript(r'''
const replies = new Map(); let requests = 0;
fetch = async (url, options) => {
  requests++;
  return await new Promise(resolve => replies.set(JSON.parse(options.body).paper_id, resolve));
};
const a = requestPaperPdfDownload({paper_id: "a"});
assert.equal(a, requestPaperPdfDownload({paper_id: "a", context: "library", force: true}));
const b = requestPaperPdfDownload({paper_id: "b"});
assert.equal(requests, 2);
replies.get("b")({ok: true, json: async () => ({result: {status: "partial"}})});
await b;
assert.equal(pendingPaperPdfDownloads.has("a"), true);
const failure = assert.rejects(a, /fixture failure/);
replies.get("a")({ok: false, json: async () => ({error: "fixture failure"})});
await failure;
assert.equal(pendingPaperPdfDownloads.has("a"), false);
const retry = requestPaperPdfDownload({paper_id: "a"});
replies.get("a")({ok: true, json: async () => ({result: {status: "partial"}})});
await retry;
assert.equal(requests, 3);
''')


    def test_updates_keep_each_cached_views_context_without_reverting_library_state(self):
        self.run_javascript(r'''
const cached = [{...structuredClone(monitor), theme_groups: [{key: "other"}], theme_score: 9, theme_hits: ["different match"]}];
state.themePapersByDate["2026-08-31|other"] = cached;
state.reportCache["2026-08-30"] = {papers: [{paper_id: paperId, journal: "Example Journal", report_context: "older-date"}]};
state.libraryItems = [{paper_id: paperId, paper: {paper_id: paperId, title: "Old title"}}];
state.myPublications = [{paper_id: paperId, paper: {paper_id: paperId}}];
state.authorMonitorPapers = [{paper_id: paperId, author_context: "profile"}];
updatePaperState(paperId, updated);
assert.deepEqual(cached[0].theme_groups, [{key: "other"}]);
assert.equal(cached[0].theme_score, 9);
assert.deepEqual(cached[0].theme_hits, ["different match"]);
assert.equal(cached[0].in_library, true);
assert.equal(state.reportCache["2026-08-30"].papers[0].in_library, true);
assert.equal(state.reportCache["2026-08-30"].papers[0].report_context, "older-date");
assert.equal(state.libraryItems[0].paper.title, updated.title);
assert.equal(state.myPublications[0].paper.in_library, true);
assert.equal(state.authorMonitorPapers[0].author_context, "profile");
// An explicit empty value remains authoritative; only omitted fields survive.
updatePaperState(paperId, {paper_id: paperId, theme_groups: [], theme_hits: [], theme_score: 0,
  in_library: false, library_item_count: 0, library_status_loaded: true});
assert.deepEqual(state.themePapers[0].theme_groups, []);
assert.equal(state.themePapers[0].theme_score, 0);
assert.equal(state.themePapers[0].in_library, false);
assert.equal(cached[0].in_library, false);
''')


if __name__ == "__main__":
    unittest.main()
