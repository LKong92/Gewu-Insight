// Real frontend download functions; deterministic native responses, no network.
const assert = require('node:assert/strict');
const vm = require('node:vm');
const {execFileSync} = require('node:child_process');
const {randomUUID} = require('node:crypto');
const source = execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c',
  'from paper_monitor.ui_server import INDEX_HTML as s; print(s[s.index("    const pendingNativePublisherDownloads ="):s.index("    async function downloadLibraryPdf(")])'], {encoding: 'utf8'});
const script = source;
assert.ok(script.includes('performPaperPdfDownload'));

async function exercise(fallback, mainFailure = false, options = {}) {
  const calls = [];
  const context = vm.createContext({console, updatePaperState() {},
    fetch: async () => ({ok: true, json: async () => ({browser_fallback: fallback,
      paper: {paper_id: 'fixture', marker: 'direct'},
      result: {status: 'failed', publisher_main_resource_id: options.existingMainId}})})});
  context.window = {crypto: {randomUUID}, setTimeout, clearTimeout, webkit: {messageHandlers: {publisherPdfDownload: {
    postMessage(payload) {
      calls.push(payload);
      const kind = payload.context.publisher_download_kind;
      const main = kind === 'aaas-published-pdf' || kind === 'publisher-main-pdf';
      const discovery = kind.endsWith('discovery');
      const data = main ? {publisher_main_resource_id: kind === 'aaas-published-pdf' || payload.context.publisher_download_name === 'nature' ? 42 : 0, paper: {paper_id: 'fixture', marker: 'native'}}
        : discovery ? {supplement_urls: options.empty ? [] : ['https://www.science.org/doi/suppl/fixture/sm.pdf', 'https://www.science.org/doi/suppl/fixture/sm-copy.pdf']}
        : {paper: {paper_id: 'fixture'}, result: {status: 'success'}};
      queueMicrotask(() => context.window.handleNativePublisherDownloadResult({token: payload.token,
        success: !(main && mainFailure) && !(discovery && options.discoveryFailure) && !(!main && !discovery && options.supplementFailure),
        data, error: main ? 'Main article unavailable' : 'Supplementary request timed out'}));
    }
  }}}};
  vm.runInContext(script, context);
  if (mainFailure) await assert.rejects(context.requestPaperPdfDownload({paper_id: 'fixture'}), /Main article unavailable/);
  else {
    const result = await context.requestPaperPdfDownload({paper_id: 'fixture'});
    assert.equal(result.paper.paper_id, 'fixture', 'Every completed flow retains the paper response');
    if (options.empty) assert.equal(result.paper.marker, fallback.kind.endsWith('discovery') ? 'direct' : 'native');
    if (options.discoveryFailure || options.supplementFailure) {
      assert.equal(result.paper.marker, fallback.kind.endsWith('discovery') ? 'direct' : 'native');
      assert.match(result.download_warning, /^Main PDF saved;/);
    }
  }
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
  const natureDiscovery = {kind: 'publisher-supplement-discovery', publisher: 'nature', url: 'https://www.nature.com/articles/fixture'};
  const natureMain = {kind: 'publisher-main-pdf', publisher: 'nature', url: natureDiscovery.url,
    target_url: `${natureDiscovery.url}.pdf`, followup: natureDiscovery};
  calls = await exercise(natureMain);
  assert.deepEqual(calls.map(v => v.context.publisher_download_kind), ['publisher-main-pdf', 'publisher-supplement-discovery', 'publisher-supplement-file', 'publisher-supplement-file']);
  assert.ok(calls.slice(1).every(v => v.context.publisher_main_resource_id === 42));
  calls = await exercise(natureDiscovery, false, {existingMainId: 71});
  assert.equal(calls.length, 3, 'Partial Nature result consumes discovered attachments');
  assert.ok(calls.every(v => v.context.publisher_main_resource_id === 71));
  calls = await exercise(natureMain, false, {empty: true});
  assert.equal(calls.length, 2, 'Nature without supplements keeps successful main response');
  calls = await exercise(natureDiscovery, false, {empty: true, existingMainId: 71});
  assert.equal(calls.length, 1);
  calls = await exercise(natureMain, true);
  assert.equal(calls.length, 1, 'Failed Nature main does not fetch supplements');
  for (const candidate of [main, natureMain, natureDiscovery]) {
    calls = await exercise(candidate, false, {discoveryFailure: true, existingMainId: 71});
    assert.equal(calls.length, candidate.followup ? 2 : 1, 'Discovery timeout retains the saved main');
    await exercise(candidate, false, {supplementFailure: true, existingMainId: 71});
  }
  await exercise(main, false, {empty: true});
  console.log('Science frontend probe: main → supplements, explicit resource targeting, failure stop, single discovery and generic publisher regression passed.');
})().catch(error => {console.error(error); process.exitCode = 1;});
