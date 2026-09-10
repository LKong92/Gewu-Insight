// Exercise the real shared handlers without reading or changing the OS clipboard.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const source = fs.readFileSync(require('node:path').join(__dirname, '../paper_monitor/ui_server.py'), 'utf8');
function extract(name) {
  const start = source.indexOf('    function ' + name + '(');
  assert(start >= 0);
  const end = source.indexOf('\n    ', start + 4);
  // Functions end at their four-space closing brace; inner blocks are deeper.
  const close = source.indexOf('\n    }', end);
  return source.slice(start, close + 6);
}
const context = {window: {gewuPlatform: {os: 'windows'}}, selectedTextForCopy: () => '',
  pasteClipboardTextInto: () => { context.pastes++; return Promise.resolve(); }, pastes: 0,
  toggleLibraryContentViewFromMenu: () => { throw Error('Must not switch views from editable text'); }};
vm.createContext(context);
for (const name of ['editableClipboardTarget', 'handleTextClipboardShortcut', 'handleLibraryViewShortcut']) vm.runInContext(extract(name), context);
const target = {type: 'text', matches: () => true, closest: () => target};
function event(key, extra = {}) { return {key, ctrlKey: true, target, prevented: false,
  preventDefault() { this.prevented = true; }, ...extra}; }
for (const key of ['v', 'c']) {
  const e = event(key);
  assert.equal(context.handleTextClipboardShortcut(e), true); // Stop app shortcuts.
  assert.equal(e.prevented, false); // Preserve WebView's native editing gesture.
}
assert.equal(context.pastes, 0);
const plainPaste = event('v', {shiftKey: true});
assert.equal(context.handleLibraryViewShortcut(plainPaste), false);
assert.equal(plainPaste.prevented, false);
assert.equal(context.handleTextClipboardShortcut(event('v', {target: {closest: () => null}})), false);
context.window.gewuPlatform.os = 'macos';
const legacy = event('v');
assert.equal(context.handleTextClipboardShortcut(legacy), true);
assert.equal(legacy.prevented, true);
assert.equal(context.pastes, 1);
console.log('Clipboard regression: native Windows editing, content routing and macOS compatibility passed.');
