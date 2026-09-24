const assert = require('node:assert/strict');
const vm = require('node:vm');
const html = require('node:fs').readFileSync(0, 'utf8');
const source = 'function wireWindowDragRegion()' + html.split('function wireWindowDragRegion()')[1]
  .split('$("primaryViewSwitcher").addEventListener')[0];
const listeners = new Map(), messages = [], captures = new Set();
const region = {
  addEventListener: (type, fn) => listeners.set(type, fn),
  setPointerCapture: id => captures.add(id),
  releasePointerCapture(id) {
    captures.delete(id);
    // The native handoff must survive the resulting loss of WebKit capture.
    listeners.get('lostpointercapture')?.({pointerId: id});
  },
};
vm.runInNewContext(source + '\nwireWindowDragRegion();', {
  $: () => region, window: {webkit: {messageHandlers: {windowDrag: {
    postMessage: msg => messages.push(JSON.parse(JSON.stringify(msg))),
  }}}},
});
function fire(type, extra = {}) {
  listeners.get(type)({target: region, button: 0, buttons: 1, pointerId: 1,
    clientX: 900, clientY: 20, preventDefault() {}, stopPropagation() {}, ...extra});
}
// Clicks, slight hand movement and double-clicks never start a native drag.
fire('pointerdown'); fire('pointermove', {clientX: 901}); fire('pointerup');
fire('pointerdown'); fire('pointerup'); fire('dblclick');
assert.deepEqual(messages.splice(0), [{type: 'toggleFill', clientX: 900, clientY: 20}]);
assert.equal(captures.size, 0);
// Pass the ORIGINAL click location once, not the current moved location.
fire('pointerdown'); fire('pointermove', {clientX: 904});
fire('pointermove', {clientX: 950}); fire('pointerup');
assert.deepEqual(messages.splice(0), [{type: 'begin', clientX: 900, clientY: 20}]);
assert.equal(captures.size, 0);
// The OS may never send mouse-up. A later independent gesture still works.
fire('pointerdown'); fire('pointermove', {clientX: 910});
fire('pointerdown', {clientX: 1000}); fire('pointermove', {clientX: 1004});
assert.deepEqual(messages.splice(0), [
  {type: 'begin', clientX: 900, clientY: 20}, {type: 'begin', clientX: 1000, clientY: 20},
]);
// Tabs/search/children, secondary clicks, canceled or released pointers do not drag.
for (const extra of [{target: {}}, {button: 2}]) {
  fire('pointerdown', extra); fire('pointermove', {clientX: 910}); fire('dblclick', extra);
}
for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  fire('pointerdown'); fire(type); fire('pointermove', {clientX: 910});
}
assert.equal(messages.length, 0);
// macOS accessibility-generated drags can report buttons=0 for the entire
// down/move/up sequence. Preserve that existing workflow; native mouse-up
// validation and these explicit end/cancel events guard against stale drags.
fire('pointerdown', {buttons: 0}); fire('pointermove', {clientX: 920, buttons: 0});
fire('pointerup', {buttons: 0});
assert.deepEqual(messages.splice(0), [{type: 'begin', clientX: 900, clientY: 20}]);
// Unrelated pointer IDs cannot take ownership or end the pending drag.
fire('pointerdown'); fire('pointermove', {pointerId: 2, clientX: 920});
fire('pointerup', {pointerId: 2}); fire('pointermove', {clientX: 903});
assert.deepEqual(messages, [{type: 'begin', clientX: 900, clientY: 20}]);
console.log('Blank-only native handoff, click/double-click, cancellation and repeated gestures passed.');
