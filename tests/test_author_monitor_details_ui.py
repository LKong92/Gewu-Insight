"""Author details use the shared UI contract; all data/DOM here is synthetic."""
import re
import shutil
import subprocess
import unittest

from paper_monitor.ui_server import INDEX_HTML


def ui_function(name):
    match = re.search(r"    (?:async )?function " + name + r"\(", INDEX_HTML)
    body = INDEX_HTML[match.start():]
    end = re.search(r"\n    (?:async )?function ", body)
    return body[:end.start()] if end else body


class AuthorDetailsLayoutTests(unittest.TestCase):
    def test_no_redundant_header_or_forced_second_action_group(self):
        self.assertNotIn("author-monitor-detail-head", INDEX_HTML)
        detail = ui_function("renderAuthorMonitorPaperDetail")
        self.assertEqual(detail.count('class="actions author-detail-actions"'), 1)
        self.assertNotIn("Download Again", detail)
        self.assertIn("extractLibraryIdentifierFromFiles(paper)", detail)
        css = INDEX_HTML.split(".author-monitor-detail-body.library-detail > .actions .action {", 1)[1].split("}", 1)[0]
        self.assertIn("white-space: nowrap", css)
        self.assertIn("flex: 0 0 auto", css)
        group_css = INDEX_HTML.split(".actions.author-detail-actions {", 1)[1].split("}", 1)[0]
        self.assertIn("flex-wrap: wrap", group_css)
        # Discovery does not acquire Library-only bulk file-management controls.
        self.assertNotIn("paperFilesPanelMarkup", detail)
        self.assertNotIn("managePreprintFiles: true", detail)


@unittest.skipUnless(shutil.which("node"), "Node.js required for UI interaction tests")
class AuthorDetailsInteractionTests(unittest.TestCase):
    def run_js(self, names, assertions):
        script = "const assert = require('node:assert/strict');\n"
        script += "\n".join(ui_function(name) for name in names)
        script += "\n(async () => {\n" + assertions + "\n})().catch(error => {console.error(error); process.exit(1);});"
        result = subprocess.run(["node", "-"], input=script, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_shared_key_row_handles_absent_loading_and_updated_paper(self):
        self.run_js([
            "renderAuthorMonitorPaperDetail", "libraryDetailMetadataMarkup",
            "libraryDetailGewuKeyMarkup", "libraryIdentifierFromFilesButtonMarkup",
            "libraryDetailFilesMarkup", "escapeHtml", "escapeAttr", "updatePaperState",
        ], r'''
const root = {innerHTML: '', querySelector() {return null;}};
global.$ = () => root;
const paper = {paper_id: 'one', title: 'Shared paper', authors: ['A. Author'], full_detail: false};
global.state = {papers: [], themePapers: [], reportCache: {}, themePapersByDate: {},
 libraryItems: [], myPublications: [], authorMonitorPapers: [paper]};
global.selectedAuthorMonitorPaper = () => state.authorMonitorPapers[0];
global.invalidateAuthorMonitorViewCache = () => {};
global.publicationTitleMarkup = escapeHtml;
for (const name of ['libraryDetailFigureMarkup', 'libraryDetailDoiMarkup', 'citationMetricsMarkup',
 'libraryDetailAbstractMarkup', 'pubmedMarkup', 'natureReferenceMarkup']) global[name] = () => '';
for (const name of ['wirePreprintIdentifierControls', 'wireLibraryFileLocationLinks',
 'wireCitationSourceSelector', 'wireSemanticInfluentialCitations', 'hydrateLibraryDetailFigureIfNeeded']) global[name] = () => {};
global.authorsMarkup = authors => escapeHtml(authors.join(', '));
global.paperFieldValues = () => [];
global.libraryPaperIsPdfLike = () => true;
global.fileNameFromPath = path => path.split('/').pop();
renderAuthorMonitorPaperDetail();
assert.match(root.innerHTML, /<dt>Gewu Key<\/dt>/);
assert.match(root.innerHTML, /\(undefined\)/);
assert.match(root.innerHTML, /Loading paper details/);
// A compact API record already carries its assigned key, before loading details.
updatePaperState('one', {paper_id: 'one', storage_key: 'gw_existing', full_detail: false});
renderAuthorMonitorPaperDetail();
assert.match(root.innerHTML, /gw_existing/);
updatePaperState('one', {paper_id: 'one', storage_key: 'gw_existing', full_detail: true,
 merged_pdf_path: '/Library/Folder/paper.pdf', url: 'https://example.org/paper', google_scholar_url: 'https://example.org/scholar'});
renderAuthorMonitorPaperDetail();
assert.equal((root.innerHTML.match(/<dt>Gewu Key<\/dt>/g) || []).length, 1);
assert.match(root.innerHTML, /gw_existing/);
assert.match(root.innerHTML, /Get Identifier from Files/);
assert.match(root.innerHTML, /PDF: paper.pdf/);
assert.match(root.innerHTML, /title="\/Library\/Folder\/paper.pdf"/);
const actions = root.innerHTML.split('class="actions author-detail-actions"')[1].split('</div>')[0];
for (const label of ['Open in Preview', 'Download', 'Open Website', 'Google Scholar']) assert.ok(actions.includes(label));
// Add-to-Library updates reuse the same canonical key immediately.
updatePaperState('one', {paper_id: 'one', storage_key: 'gw_existing', full_detail: true,
 in_library: true, library_status_loaded: true, library_item_count: 1});
renderAuthorMonitorPaperDetail();
assert.match(root.innerHTML, /gw_existing/);
assert.equal(state.authorMonitorPapers.length, 1);
assert.equal(state.authorMonitorPapers[0].in_library, true);
updatePaperState('one', {paper_id: 'one', storage_key: '', full_detail: true});
renderAuthorMonitorPaperDetail();
assert.match(root.innerHTML, /\(undefined\)/);
assert.ok(!root.innerHTML.includes('gw_existing'));
assert.match(libraryDetailGewuKeyMarkup({storage_key: '  '}), /\(undefined\)/);
assert.ok(!libraryDetailGewuKeyMarkup({storage_key: '<script>'}).includes('<script>'));
''')

    def test_identifier_lookup_uses_active_details_and_preserves_library_workflows(self):
        self.run_js(["extractLibraryIdentifierFromFiles"], r'''
global.state = {mode: 'author', libraryTab: 'my-publications', figureFailures: new Set()};
const button = {disabled: false}, status = {textContent: ''}, calls = [];
const root = {querySelector: () => status, querySelectorAll: () => [button]};
global.$ = id => id === 'libraryDetailDoiInput' ? null : root;
global.updateAuthorMonitorActivityStatus = text => calls.push(['author-status', text]);
global.updateLibraryActivityStatus = text => calls.push(['library-status', text]);
global.setMyPublicationActivity = () => calls.push(['publication-start']);
global.clearMyPublicationActivity = () => calls.push(['publication-end']);
global.applyMyPublications = () => {};
global.updatePaperState = (id, data) => calls.push(['update', id, data.storage_key]);
for (const [name, label] of [['renderAuthorMonitorPaperDetail', 'author-render'],
 ['renderMyPublications', 'publication-render'], ['renderLibrary', 'library-render']]) global[name] = () => {calls.push([label]); button.disabled = false;};
let fail = false;
global.fetch = async (url, options) => {
 assert.equal(url, '/api/library/extract-identifier');
 assert.deepEqual(JSON.parse(options.body), {paper_id: 'one', snapshot: false});
 assert.equal(button.disabled, true);
 return {ok: !fail, json: async () => fail ? {error: 'No identifier found'} : {
  identifier: '10.1234/test', identifier_kind: 'doi', identifier_source: 'pdf',
  paper: {paper_id: 'one', storage_key: 'gw_existing'}}};
};
await extractLibraryIdentifierFromFiles({paper_id: 'one'});
assert.ok(calls.some(call => call[0] === 'author-render'));
assert.ok(!calls.some(call => call[0].startsWith('library') || call[0].startsWith('publication')));
assert.deepEqual(calls.find(call => call[0] === 'update'), ['update', 'one', 'gw_existing']);
calls.length = 0; fail = true;
await extractLibraryIdentifierFromFiles({paper_id: 'one'});
assert.equal(button.disabled, false);
assert.equal(status.textContent, 'No identifier found');
assert.equal(status.className, 'library-detail-status err');
assert.ok(!calls.some(call => call[0].endsWith('-render')));
fail = false;
for (const [tab, label] of [['library', 'library-render'], ['my-publications', 'publication-render']]) {
 calls.length = 0; state.mode = 'library'; state.libraryTab = tab;
 await extractLibraryIdentifierFromFiles({paper_id: 'one'});
 assert.ok(calls.some(call => call[0] === label));
 assert.ok(calls.some(call => call[0] === 'library-status'));
 assert.ok(!calls.some(call => call[0].startsWith('author')));
}
''')
