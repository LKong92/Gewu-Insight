// Real frontend download functions; deterministic native responses, no network.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const source = execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c',
  'from paper_monitor.ui_server import INDEX_HTML as s; print(s[s.index("    const pendingNativePublisherDownloads ="):s.index("    async function downloadLibraryPdf(")])'], {encoding: 'utf8'});
const script = source;
assert.ok(script.includes('performPaperPdfDownload'));

async function exercise(fallback, mainFailure = false) {
  const calls = [];
  const context = vm.createContext({console, updatePaperState() {},
    fetch: async () => ({ok: true, json: async () => ({browser_fallback: fallback, result: {status: 'failed'}})})});
  context.window = {crypto: {randomUUID}, setTimeout, clearTimeout, webkit: {messageHandlers: {publisherPdfDownload: {
    postMessage(payload) {
      calls.push(payload);
      const kind = payload.context.publisher_download_kind;
      const main = kind === 'aaas-published-pdf' || kind === 'publisher-main-pdf';
      const discovery = kind.endsWith('discovery');
      const data = main ? {publisher_main_resource_id: kind === 'aaas-published-pdf' ? 42 : 0, paper: {paper_id: 'fixture'}}
        : discovery ? {supplement_urls: ['https://www.science.org/doi/suppl/fixture/sm.pdf', 'https://www.science.org/doi/suppl/fixture/sm-copy.pdf']}
        : {paper: {paper_id: 'fixture'}, result: {status: 'success'}};
      queueMicrotask(() => context.window.handleNativePublisherDownloadResult({token: payload.token,
        success: !(main && mainFailure), data, error: 'Main article unavailable'}));
    }
  }}}};
  vm.runInContext(script, context);
  if (mainFailure) await assert.rejects(context.requestPaperPdfDownload({paper_id: 'fixture'}), /Main article unavailable/);
  else await context.requestPaperPdfDownload({paper_id: 'fixture'});
  return calls;
}

(async () => {
  const discovery = {kind: 'aaas-supplement-discovery', url: 'https://www.science.org/doi/fixture'};
  const main = {kind: 'aaas-published-pdf', publisher: 'aaas', url: discovery.url,
    target_url: 'https://www.science.org/doi/pdf/fixture', followup: discovery};
  let calls = await exercise(main);
  assert.deepEqual(calls.map(v => v.context.publisher_download_kind), ['aaas-published-pdf', 'aaas-supplement-discovery', 'aaas-supplement-pdf', 'aaas-supplement-pdf']);
  assert.equal(calls[0].context.publisher_download_target_url, main.target_url);
  assert.ok(calls.slice(1).every(v => v.context.publisher_main_resource_id === 42));
  calls = await exercise(main, true);
  assert.equal(calls.length, 1, 'No supplements are fetched or merged when main failed');
  calls = await exercise(discovery);
  assert.equal(calls.filter(v => v.context.publisher_download_kind === 'aaas-supplement-discovery').length, 1);
  assert.equal(calls.length, 3, 'Existing main runs discovery only once');
  calls = await exercise({kind: 'publisher-main-pdf', publisher: 'acs', url: 'https://pubs.acs.org/doi/pdf/fixture',
    followup: {kind: 'publisher-supplement-discovery', publisher: 'acs', url: 'https://pubs.acs.org/doi/fixture'}});
  assert.equal(calls[2].context.publisher_download_kind, 'publisher-supplement-file');
  assert.equal(calls[2].context.publisher_download_name, 'acs');
  assert.equal(calls[2].context.publisher_main_resource_id, undefined);
  console.log('Science frontend probe: main → supplements, explicit resource targeting, failure stop, single discovery and generic publisher regression passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
