/* Synthetic browser fixture; never connects to a user's Gewu database. */
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {chromium} = require('playwright');
const source = fs.readFileSync(path.join(__dirname, '../paper_monitor/ui_server.py'), 'utf8');
const start = source.indexOf('<style>', source.indexOf('INDEX_HTML ='));
const css = source.slice(start + 7, source.indexOf('</style>', start));
const names = ['savePaperIdentifier', 'metadataDetailContext', 'identifierSaveNotice'];
const functions = names.map(name => {
  const at = source.search(new RegExp('    (?:async )?function ' + name + '\\('));
  return source.slice(at, source.indexOf('\n    }', at) + 6);
}).join('\n');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.GEWU_TEST_CHROME});
  try {
    const page = await browser.newPage({viewport: {width: 1100, height: 850}}), errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.setContent('<div id="libraryDetail" data-metadata-paper-id="current"><input id="libraryDetailDoiInput"><div class="library-detail-status"></div></div>');
    await page.addStyleTag({content: css});
    await page.addScriptTag({path: path.join(__dirname, '../paper_monitor/manual_doi.js')});
    await page.addScriptTag({content: `
      let requests=[], deferred=false, release, fail=false, result;
      const current={paper_id:'current', storage_key:'gw_current', title:'Synthetic superconductivity paper', doi:''};
      const existing={paper_id:'existing', storage_key:'gw_existing', title:'Synthetic superconductivity paper', doi:'10.1234/synthetic'};
      const review={doi:existing.doi, current:{...current, authors:'A Researcher', journal:'Test Journal', file_count:1,
        default_file:'current.pdf', locations:['Library / FeSe_Tip']}, existing:{...existing, authors:'A Researcher',
        journal:'Test Journal', file_count:1, default_file:'existing.pdf', monitors:['Subject Monitor']},
        item_id:7, fingerprint:'review-version', main_location:'Library / FeSe_Tip'};
      const state={mode:'library',libraryTab:'library',librarySelection:{type:'item',id:7},
        libraryItems:[{id:7,paper_id:'current',paper:current}],paperFilesByPaperId:{},libraryPaperLocationsLoaded:new Set(),
        libraryLoadedFolderIds:new Set(),reportCache:{},themePapersByDate:{},myPublications:[],
        monitorPaperDomCache:{journal:null,subject:null}};
      const libraryItemById=id=>state.libraryItems.find(i=>i.id===id);
      const updatePaperState=()=>{}, rebuildLibraryIndexes=()=>{}, invalidateAuthorMonitorViewCache=()=>{},
        applyPaperFilesPayloads=()=>{},loadLibraryPaperLocations=()=>{};
      async function fetch(url, options){
        const body=JSON.parse(options.body);requests.push(body);
        if(!body.conflict_action)return {ok:false,json:async()=>({doi_conflict:review})};
        if(deferred)await new Promise(r=>release=r);
        if(fail)return {ok:false,json:async()=>({error:'These records or files changed. Cancel and review again.'})};
        const p={...current,doi:review.doi};
        return {ok:true,json:async()=>({paper:p,changed_papers:[p],merged_paper_id:body.conflict_action==='merge'?'existing':'',library_items:[{id:7,paper_id:'current',paper:p}]})};
      }
      ${functions}
      function begin(){
        const input=document.getElementById('libraryDetailDoiInput');input.defaultValue='';input.value=review.doi;
        requests=[];result=null;input.focus();
        window.pending=savePaperIdentifier(current,document.getElementById('libraryDetail'),'doi',{render:false,finishEditing:true})
          .then(p=>result=p).catch(e=>result={error:e.message});
      }
    `});
    await page.evaluate(() => begin());
    await page.locator('[role="dialog"]').waitFor();
    assert.equal(await page.locator('[data-confirm]').isEnabled(), false, 'explicit choice required');
    assert.equal(await page.locator('input[name="doi-resolution"]:checked').count(), 0);
    assert.match(await page.locator('[data-record="existing"]').innerText(), /Subject Monitor/);
    await page.locator('[data-cancel]').click();
    await page.evaluate(() => window.pending);
    assert.equal(await page.evaluate(() => requests.length), 1, 'cancel never sends a mutation');
    assert.equal(await page.locator('#libraryDetailDoiInput').inputValue(), '10.1234/synthetic');
    for (const action of ['merge', 'reassign']) {
      await page.evaluate(() => begin());
      await page.locator('input[value="'+action+'"]').check();
      await page.locator('[data-confirm]').click();
      await page.evaluate(() => window.pending);
      assert.equal(await page.locator('[role="dialog"]').count(), 0);
      assert.equal(await page.locator('#libraryDetailDoiInput').inputValue(), '10.1234/synthetic');
      assert.deepEqual(await page.evaluate(() => requests[1]), {kind:'doi',paper_id:'current',identifier:'10.1234/synthetic',
        item_id:7,fingerprint:'review-version',conflict_action:action});
      assert.equal(await page.evaluate(() => result.error), undefined, 'manual response integrates with Paper Details');
    }
    await page.evaluate(() => {fail=true;begin();});
    await page.locator('input[value="merge"]').check();
    await page.locator('[data-confirm]').click();
    await page.locator('.doi-status').filter({hasText:'changed'}).waitFor();
    assert.equal(await page.locator('[data-cancel]').isEnabled(), true);
    await page.locator('[data-cancel]').click();
    await page.evaluate(() => window.pending);
    await page.evaluate(() => {fail=false;deferred=true;begin();});
    await page.locator('input[value="merge"]').check();
    await page.locator('[data-confirm]').click();
    assert.equal(await page.locator('[data-cancel]').isEnabled(), false, 'cannot hide an in-flight write');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('[role="dialog"]').count(), 1);
    await page.evaluate(() => release());
    await page.evaluate(() => window.pending);
    await page.evaluate(() => {deferred=false;review.current.title='<img src=x onerror=alert(1)> '+ 'Long title '.repeat(25);begin();});
    assert.equal(await page.locator('.doi-review img').count(), 0, 'metadata is text');
    for (const width of [1100, 600, 420]) {
      await page.setViewportSize({width, height:850});
      assert.equal(await page.locator('.doi-review').evaluate(e=>e.scrollWidth<=e.clientWidth+1), true, 'no dialog overflow');
      assert.equal(await page.locator('.settings-modal-body').evaluate(e=>e.scrollWidth<=e.clientWidth+1), true, 'wrapping stays within body');
    }
    await page.setViewportSize({width:1100,height:850});
    await page.evaluate(() => {document.querySelector('[data-record="current"] h3').textContent='Synthetic superconductivity paper';});
    if (process.env.GEWU_TEST_ARTIFACT_DIR) await page.screenshot({path:path.join(process.env.GEWU_TEST_ARTIFACT_DIR,'manual-doi-review.png')});
    await page.locator('.settings-modal-close').click();
    await page.evaluate(() => window.pending);
    assert.deepEqual(errors, []);
    console.log('Manual DOI review: cancel, both confirmations, stale review, busy lock, escaping and responsive layout passed.');
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
