const test = require('node:test');
const assert = require('node:assert/strict');
const resources = require('../integrations/zotero/pdf-resources.js');

test('PDF resources are confined to Zotero renderer data, without arbitrary file/URL access', () => {
  assert.equal(resources.assetURL('standardFontDataUrl','FoxitSans.pfb'), 'resource://zotero/reader/pdf/web/standard_fonts/FoxitSans.pfb');
  assert.equal(resources.assetURL('cMapUrl','UniGB-UCS2-H.bcmap'), 'resource://zotero/reader/pdf/web/cmaps/UniGB-UCS2-H.bcmap');
  assert.equal(resources.assetURL('wasmUrl','openjpeg.wasm'), 'resource://zotero/reader/pdf/web/wasm/openjpeg.wasm');
  for (const name of ['../prefs.js','../../secret.ttf','a/b.ttf','a%2fb.ttf','https://example.org/a.ttf','/tmp/a.ttf','a.js','a.ttf?x=1','a.ttf#fragment','']) {
    assert.throws(() => resources.assetURL('standardFontDataUrl', name));
  }
  for (const kind of ['__proto__','constructor','prototype','file','https://example.org']) {
    assert.throws(() => resources.assetURL(kind, 'a.ttf'));
  }
});
