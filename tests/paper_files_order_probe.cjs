// Execute the product renderers and key/delete handlers against synthetic files.
const assert = require('node:assert/strict'), vm = require('node:vm');
const html = require('node:fs').readFileSync(0, 'utf8');
const names = ['publicationNoticesMarkup', 'libraryPaperResourcesColumnMarkup', 'paperFilesPanelMarkup',
  'orderedLibraryPaperResources', 'moveLibraryPaperResourceSelection',
  'deleteSelectedLibraryPaperResource', 'handleLibraryPaperResourceKeydown'];
const code = names.map(name => {
  const start = html.search(new RegExp('    (?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  return html.slice(start, html.indexOf('\n    }', start) + 6);
}).join('\n');
let files = [], previewId = 0;
const state = {libraryPaperResourceSelection: {}, expandedPaperResourceProperties: new Set(),
  expandedPaperFiles: new Set(), deletingPaperResources: new Set(), libraryQuickLookOpen: false};
const context = {
  state, paperFilesSnapshot: () => ({files}),
  selectedLibraryPaperResource: () => files.find(f => f.id === state.libraryPaperResourceSelection.resourceId),
  setLibraryPaperResourceSelection: (paperId, resourceId) => {state.libraryPaperResourceSelection = {paperId, resourceId};},
  document: {querySelector: () => null}, window: {confirm: () => true, requestAnimationFrame: fn => fn()},
  quickLookLibraryPaperResource: f => {previewId = f.id;},
  deletePaperFile: async (paperId, id) => {files = files.filter(f => f.id !== id); return {deleted:{trashed:true}};},
  renderLibraryNavigationContent() {}, updateLibraryActivityStatus() {},
  escapeHtml: String, escapeAttr: String, paperFileRowMarkup: f => `<div data-id="${f.id}"></div>`,
};
for (const name of ['paperFileRoleLabel', 'paperFileRoleOptions', 'paperFileAnnotationLabel',
  'paperFileAnnotationOptions', 'paperFileSourceLabel', 'paperFileSourceOptions',
  'fileSizeLabel', 'libraryNativeFileDragAttrs', 'paperFilesStatusMarkup']) context[name] = () => '';
vm.createContext(context); vm.runInContext(code, context);
const select = id => context.setLibraryPaperResourceSelection('probe', id);
const visible = () => [...context.libraryPaperResourcesColumnMarkup({paper_id:'probe',display_name:'Probe'})
  .matchAll(/data-library-resource-id="(\d+)"/g)].map(m => Number(m[1]));
const event = {target:null,preventDefault(){},stopPropagation(){},stopImmediatePropagation(){}};
(async () => {
  let cases = 0;
  for (const count of [1,2,4]) for (let defaultIndex = -1; defaultIndex < count; defaultIndex++) {
    files = Array.from({length:count}, (_,i) => ({id:i+1,is_default:i===defaultIndex,exists:true}));
    const snapshot = JSON.stringify(files);
    const expected = files.filter(f => f.is_default).concat(files.filter(f => !f.is_default)).map(f => f.id);
    assert.deepEqual(visible(), expected, 'Default is first and the remaining order is stable');
    const panel = [...context.paperFilesPanelMarkup({paper_id:'probe'}).matchAll(/data-id="(\d+)"/g)].map(m => Number(m[1]));
    assert.deepEqual(panel, expected, 'My Publications Files also puts Default first');
    for (const quickLook of [false,true]) {
      state.libraryQuickLookOpen = quickLook;
      for (let index=0; index<count; index++) for (const [key,delta] of [['ArrowUp',-1],['ArrowDown',1]]) {
        select(expected[index]);
        assert.equal(context.handleLibraryPaperResourceKeydown(event,key),true);
        const next = expected[Math.max(0,Math.min(count-1,index+delta))];
        assert.equal(state.libraryPaperResourceSelection.resourceId,next);
        if (quickLook) assert.equal(previewId,next);
      }
    }
    assert.equal(JSON.stringify(files),snapshot,'Rendering/navigation never mutates the file snapshot');
    for (const id of expected) {
      files = JSON.parse(snapshot); select(id);
      await context.deleteSelectedLibraryPaperResource(files.find(f => f.id === id));
      const remaining = visible(), index = expected.indexOf(id);
      assert.equal(state.libraryPaperResourceSelection.resourceId,remaining[Math.min(index,remaining.length-1)] || 0);
    }
    cases++;
  }
  files = [{id:1},{id:2,is_default:true},{id:3}]; select(3);
  files = files.map(f => ({...f,is_default:f.id===3}));
  assert.deepEqual(visible(),[3,1,2]);
  context.handleLibraryPaperResourceKeydown(event,'ArrowDown');
  assert.equal(state.libraryPaperResourceSelection.resourceId,1,'A changed Default updates both orders');
  console.log(`${cases} ordering scenarios passed, including preview, deletion, and Default changes`);
})().catch(error => {console.error(error);process.exitCode=1;});
