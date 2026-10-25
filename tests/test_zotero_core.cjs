const test = require('node:test');
const assert = require('node:assert/strict');
const core = require('../integrations/zotero/core.js');

test('workspace addresses remain on loopback, without credential-bearing paths', () => {
  assert.equal(core.origin('http://127.0.0.1:8765/'), 'http://127.0.0.1:8765');
  assert.equal(core.origin('http://[::1]:8876'), 'http://[::1]:8876');
  for (const url of ['https://example.org', 'http://127.0.0.1.evil.test:8765',
    'http://user:secret@localhost:8765', 'http://localhost:8765/?key=secret',
    'http://localhost:8765/#secret', 'file:///tmp/a', 'http://localhost:8765/api']) {
    assert.throws(() => core.origin(url));
  }
});

test('metadata keeps full names, partial dates, bibliography and per-workspace identity', () => {
  const paper = { paper_id: 'doi_abc', storage_key: 'gw_abc', title: 'A paper',
    doi: 'https://doi.org/10.1234/ABC', journal: 'Journal', publication_date: '2026',
    full_authors: ['王小明', 'The Collaboration', 'Jane Smith'],
    authors: ['J. Smith'], abstract: 'An abstract',
    manual_metadata: { volume: '2', issue: '3', pages: '4–5' } };
  const data = core.fields(paper, 'workspace-1');
  assert.equal(data.DOI, '10.1234/abc');
  assert.equal(data.url, 'https://doi.org/10.1234/abc');
  assert.equal(data.date, '2026');
  assert.equal(data.volume, '2');
  assert.equal(data.pages, '4–5');
  assert.deepEqual(data.creators.map(a => a.lastName), paper.full_authors);
  assert.ok(core.extraHas(data.extra, 'Gewu: workspace-1/gw_abc'));
  assert.ok(!core.extraHas(data.extra, 'Gewu: workspace-1/gw_ab'));
  assert.notEqual(core.marker('workspace-2', paper), core.marker('workspace-1', paper));
});

test('preprint identity is version-normalized and does not require fabricated metadata', () => {
  const data = core.fields({ paper_id: 'arxiv:2401.12345', title: 'Preprint',
    preprint_id: 'arXiv:2401.12345v3' }, 'workspace-1');
  assert.equal(data.itemType, 'preprint');
  assert.equal(core.fields({paper_id:'a',title:'Preprint',preprint_id:'2401.12345',doi:'10.48550/arXiv.2401.12345'},'w').itemType, 'preprint');
  assert.equal(data.date, '');
  assert.equal(data.DOI, '');
  assert.equal(data.url, 'https://arxiv.org/abs/2401.12345');
  assert.deepEqual(data.creators, []);
  assert.throws(() => core.fields({paper_id: 'p'}, 'w'));
  assert.equal(core.website('javascript:alert(1)'), '');
  assert.equal(core.website('https://user:secret@example.org'), '');
});

test('PDF copy follows the chosen Default and never silently substitutes another file', () => {
  const files = [
    {id: 1, exists: true, local_path: '/one.pdf'},
    {id: 2, exists: true, local_path: '/two.pdf'},
    {id: 3, exists: true, local_path: '/notes.md'}
  ];
  assert.equal(core.defaultPDF({default_resource_id: 2, files}).id, 2);
  assert.equal(core.defaultPDF({default_resource_id: 3, files}), null);
  assert.equal(core.defaultPDF({default_resource_id: 99, files}), null);
  assert.equal(core.defaultPDF({default_resource_id: 2, files: [{...files[1], exists:false}]}), null);
});

test('embedded websites cannot use privileged schemes, credentials or local network addresses', () => {
  assert.equal(core.browserURL('https://example.org/article'), 'https://example.org/article');
  for (const value of ['file:///tmp/a','javascript:alert(1)','https://user:pass@example.org',
    'http://127.1/','http://0x7f000001/','http://192.168.1.2/','http://172.16.2.4/',
    'http://localhost/','http://host.local/','http://[::1]/','http://10.2.3.4/']) {
    assert.throws(() => core.browserURL(value), value);
  }
});
