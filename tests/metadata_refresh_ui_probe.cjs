const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {chromium} = require('playwright');
const source = fs.readFileSync(path.resolve(__dirname, '../paper_monitor/ui_server.py'), 'utf8');
const names = ['metadataBatchActivityText', 'metadataRefreshActivityText', 'updateMetadataRefreshActivity', 'libraryActivityStatusText', 'libraryActivityStatusClass', 'renderLibraryActivityStatus', 'updateLibraryActivityStatus', 'setMyPublicationActivity', 'clearMyPublicationActivity', 'myPublicationSearchStatusText', 'myPublicationSearchStatusIsLive', 'myPublicationStatusItems', 'myPublicationStatusClass', 'updateMyPublicationStatusBar', 'authorMonitorDisplayedActivity', 'authorMonitorActivityStatusClass', 'syncAuthorMonitorActivityDisplay', 'updateAuthorMonitorActivityStatus','metadataDetailContext','applyMetadataResult','savePaperDoi','refreshLibraryMetadataFromDoi','pollVisibleMetadataResult','metadataRefreshButtonMarkup','metadataRefreshTooltipMarkup','updateMetadataRefreshButton','showMetadataRefreshTooltip','closeMetadataRefreshTooltip','wireMetadataRefreshTooltipEvents','libraryIdentifierFromFilesButtonMarkup','escapeHtml','escapeAttr'];
const styleStart=source.indexOf('<style>',source.indexOf('INDEX_HTML ='));
const css=source.slice(styleStart+7,source.indexOf('</style>',styleStart));
const functions = names.map(name => { const start = source.search(new RegExp('    (?:async )?function '+name+'\\(')); assert.ok(start >= 0, name); return source.slice(start, source.indexOf('\n    }', start)+6); }).join('\n');
(async () => {
 const browser = await chromium.launch({headless:true, executablePath:process.env.GEWU_TEST_CHROME});
 try {
  const page = await browser.newPage(); const errors=[]; page.on('pageerror', e=>errors.push(e.message));
  await page.setContent('<button id="tab">Library</button><input id="outside" value="retained"><div id="libraryDetail"></div><div id="authorMonitorDetailBody"></div><div id="libraryActivityStatus"></div><div id="authorMonitorActivityStatus"></div><div id="authorMonitorSecondaryActivityStatus"></div><div id="publicationSearchStatus"></div><div id="myPublicationSecondaryStatus"></div>');
  await page.addScriptTag({content:`
  const $=id=>document.getElementById(id), paperMetadataRequests=new Map(); let metadataDetailPollBusy=false;
  const state={mode:'library',libraryTab:'library',libraryItems:[{paper_id:'p',paper:{paper_id:'p',doi:'',preprint_id:'2106.14849'}}],authorMonitorPapers:[],myPublications:[],myPublicationActivities:[]};
  let fixtureWork=null;const myPublicationWorkStatusItem=()=>fixtureWork;
  const authorMonitorIdleActivity=()=>({text:'Background checks scheduled',live:false});
  let renders=0, calls=[], release, deferred=true, fail=false; let releases=[];
  const updated={paper_id:'p',doi:'10.1234/published',preprint_id:'2106.14849',metadata_refresh:{checked_at:'2026-09-11T11:00:00+08:00',message:'Updated DOI.',sources:{Crossref:'found',OpenAlex:'unavailable','Publication metadata':'found','Semantic Scholar DOI':'unavailable',ADS:'found',arXiv:'found',PubMed:'found'}}};
  function updatePaperState(id,paper){const item=state.libraryItems.find(p=>p.paper_id===id);if(item)item.paper=paper;}
  function renderLibraryDetail(){closeMetadataRefreshTooltip();renders++;const p=state.libraryItems[0].paper;const root=$('libraryDetail');root.dataset.metadataPaperId='p';root.dataset.metadataCheckedAt=p.metadata_refresh?.checked_at||'';root.innerHTML='<div class="library-detail-status"></div>'+metadataRefreshButtonMarkup(p)+'<input id="libraryDetailDoiInput" value="'+(p.doi||'')+'"><input class="preprint-identifier-input" value="2106.14849">';}
  const renderPublicationDetail=renderLibraryDetail, renderAuthorMonitorPaperDetail=renderLibraryDetail;
  async function fetch(url, options){calls.push({url,body:options?JSON.parse(options.body):null});if(deferred)await new Promise(r=>{release=r;releases.push(r)});return {ok:!fail,json:async()=>fail?({error:'Source unavailable'}):({paper:{...updated,paper_id:options?JSON.parse(options.body).paper_id:"p"}})};}
  ${functions}
  wireMetadataRefreshTooltipEvents();
  renderLibraryDetail();
  `});
  await page.evaluate(()=>{window.pending=refreshLibraryMetadataFromDoi(state.libraryItems[0].paper);});
  await page.waitForFunction(()=>typeof release==='function');
  await page.evaluate(()=>refreshLibraryMetadataFromDoi(state.libraryItems[0].paper));
  assert.equal(await page.evaluate(()=>calls.length),1,'repeated clicks coalesce');
  assert.match(await page.locator('#libraryActivityStatus').innerText(),/Refreshing info/);
  assert.ok((await page.locator('#libraryActivityStatus').getAttribute('class')).includes('live'));
  assert.deepEqual(await page.evaluate(()=>calls[0].body),{paper_id:'p',snapshot:false},'arXiv-only whole-paper request');
  await page.evaluate(()=>{state.mode='browser';$('tab').focus();release();});
  await page.evaluate(()=>window.pending);
  assert.equal(await page.evaluate(()=>state.mode),'browser');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'tab');
  assert.equal(await page.evaluate(()=>renders),1,'no render after workspace switch');
  await page.evaluate(()=>{state.mode='library';renderLibraryDetail();$('libraryDetailDoiInput').value='unsaved DOI';$('libraryDetailDoiInput').focus();applyMetadataResult($('libraryDetail'),metadataDetailContext($('libraryDetail')),updated);});
  assert.equal(await page.locator('#libraryDetailDoiInput').inputValue(),'unsaved DOI');
  assert.equal(await page.evaluate(()=>document.activeElement.id),'libraryDetailDoiInput');
  await page.evaluate(()=>{$('outside').focus();applyMetadataResult($('libraryDetail'),metadataDetailContext($('libraryDetail')),updated);});
  assert.equal(await page.locator('#libraryDetailDoiInput').inputValue(),'unsaved DOI','blurred draft retained');
  await page.evaluate(()=>{renderLibraryDetail();$('tab').focus();applyMetadataResult($('libraryDetail'),metadataDetailContext($('libraryDetail')),updated);});
  assert.equal(await page.evaluate(()=>document.activeElement.id),'tab');
  await page.evaluate(()=>{applyMetadataResult($('libraryDetail'),metadataDetailContext($('libraryDetail')),{...updated,doi:'old',metadata_refresh:{checked_at:'2026-09-10T11:00:00+08:00'}});});
  assert.equal(await page.evaluate(()=>state.libraryItems[0].paper.doi),'10.1234/published','late older reply rejected');
  await page.evaluate(()=>{deferred=false;calls=[];$('libraryDetailDoiInput').value='10.1234/corrected';});
  await page.evaluate(()=>savePaperDoi(state.libraryItems[0].paper,$('libraryDetail')));
  assert.deepEqual(await page.evaluate(()=>calls[0].body),{paper_id:'p',kind:'doi',identifier:'10.1234/corrected'});
  assert.equal(await page.locator('.library-detail-status').innerText(),'','refresh report never occupies panel status, including with drafts');
  // Render the actual action templates for all three Details implementations.
  await page.addStyleTag({content:css});
  await page.addStyleTag({content:'body{display:block;padding:20px;background:white}#libraryDetail{height:620px;max-width:calc(100vw - 40px);border:1px solid #cbd2db}#authorMonitorDetailBody{display:none}'});
  for (const [name,kind] of [['renderLibraryDetail','library'],['renderPublicationDetail','publication'],['renderAuthorMonitorPaperDetail','author']]) {
   const start=source.indexOf('    function '+name+'(');
   const actionStart=source.indexOf('<div class="actions paper-detail-actions',start);
   const end=source.indexOf('<div class="library-detail-status"',actionStart);
   const template=source.slice(actionStart,end);
   await page.evaluate(({template,kind})=>{
    closeMetadataRefreshTooltip();
    const p={...updated,merged_pdf_path:'/synthetic/paper.pdf',url:'https://example.org/paper',google_scholar_url:'https://example.org/scholar'};
    const render=new Function('paper','publication','isPdfLike','return `'+template+'`');
    const root=$('libraryDetail');root.className='library-detail'+(kind==='author'?' author-monitor-detail-body':'');
    root.innerHTML='<h3>Synthetic paper</h3>'+render(p,{},true)+'<div class="library-detail-status"></div><dl><dt>DOI</dt><dd>10.1234/published</dd></dl>';
   },{template,kind});
   for (const width of [1440,960,520]) {
    await page.setViewportSize({width,height:800});
    await page.evaluate(()=>{$('libraryDetail').style.width='300px';});
    const button=page.locator('[data-action="refresh-library-metadata"]');
    assert.equal(await button.innerText(),'Refresh Info');
    assert.equal(await page.locator('[data-action="extract-library-identifier"]').innerText(),'Get DOI');
    const tops=await page.locator('.paper-detail-action-row .action').evaluateAll(els=>els.map(e=>Math.round(e.getBoundingClientRect().top)));
    assert.equal(tops.length,6);assert.equal(new Set(tops).size,2,kind+' uses two rows');
    assert.equal(await page.locator('#libraryDetail').evaluate(e=>e.scrollWidth<=e.clientWidth+1),true,'no horizontal overflow');
    assert.ok(!(await page.locator('#libraryDetail').innerText()).includes('Updated DOI.'),'no permanent report');
    await button.hover();
    const tooltip=page.locator('#metadataRefreshTooltip');await tooltip.waitFor({state:'visible'});
    assert.ok((await tooltip.innerText()).includes('Last checked:'));
    assert.ok((await tooltip.innerText()).includes('arXiv: found'));
    const b=await button.boundingBox(), t=await tooltip.boundingBox();
    assert.ok(t.y>=b.y+b.height+5,'tooltip always below');assert.ok(t.x+t.width<=width-7,'tooltip within viewport');
    if(kind==='library'&&width===520&&process.env.GEWU_TEST_ARTIFACT_DIR)await page.screenshot({path:path.join(process.env.GEWU_TEST_ARTIFACT_DIR,'two-rows-hover.png')});
    await page.mouse.move(1,1);await tooltip.waitFor({state:'detached'});
   }
  }
  // Busy and failed requests still report through the same hover surface.
  await page.evaluate(()=>{renderLibraryDetail();deferred=true;window.pending=refreshLibraryMetadataFromDoi(state.libraryItems[0].paper);});
  await page.waitForFunction(()=>paperMetadataRequests.has('p'));
  await page.locator('[data-action="refresh-library-metadata"]').hover();
  assert.ok((await page.locator('#metadataRefreshTooltip').innerText()).includes('Refreshing information'));
  await page.evaluate(()=>release());await page.evaluate(()=>window.pending);
  await page.evaluate(()=>{deferred=false;fail=true;});
  await page.evaluate(()=>refreshLibraryMetadataFromDoi(state.libraryItems[0].paper));
  await page.mouse.move(1,1);await page.locator('[data-action="refresh-library-metadata"]').hover();
  assert.ok((await page.locator('#metadataRefreshTooltip').innerText()).includes('Source unavailable'));
  assert.equal(await page.locator('.library-detail-status').innerText(),'');
  await page.keyboard.press('Escape');assert.equal(await page.locator('#metadataRefreshTooltip').count(),0);
  await page.evaluate(()=>{$('tab').focus();});
  await page.keyboard.press('Tab');await page.keyboard.press('Tab');
  assert.equal(await page.locator('#metadataRefreshTooltip').count(),1,'keyboard focus exposes report');
  await page.keyboard.press('Tab');assert.equal(await page.locator('#metadataRefreshTooltip').count(),0);
  // Two actual refresh requests finish independently; another download remains visible.
  await page.evaluate(()=>{
   fail=false;deferred=true;releases=[];state.mode='library';state.libraryTab='library';renderLibraryDetail();
   state.libraryItems.push({paper_id:'q',paper:{paper_id:'q',title:'Second paper'}});
   updateLibraryActivityStatus('Downloading another PDF…',{live:true,clear:false});
   window.first=refreshLibraryMetadataFromDoi(state.libraryItems[0].paper);
   $('libraryDetailDoiInput').value='';$('libraryDetailDoiInput').defaultValue='';$('libraryDetail').dataset.metadataPaperId='q';
   window.second=refreshLibraryMetadataFromDoi(state.libraryItems[1].paper);
  });
  await page.waitForFunction(()=>releases.length===2);
  assert.match(await page.locator('#libraryActivityStatus').innerText(),/2 papers.*Downloading another PDF/);
  await page.evaluate(()=>releases[0]());await page.evaluate(()=>window.first);
  assert.match(await page.locator('#libraryActivityStatus').innerText(),/Second paper.*Downloading another PDF/);
  await page.evaluate(()=>releases[1]());await page.evaluate(()=>window.second);
  assert.equal(await page.locator('#libraryActivityStatus').innerText(),'Downloading another PDF…','finishing refresh preserves active download');
  for (const scope of ['library','my-publications','author']) {
   const selector=scope==='author'?'#authorMonitorSecondaryActivityStatus':scope==='my-publications'?'#publicationSearchStatus':'#libraryActivityStatus';
   await page.evaluate(scope=>{
    state.libraryActivityLive=false;state.libraryActivityText='';
    state.mode=scope==='author'?'author':'library';state.libraryTab=scope==='my-publications'?'my-publications':'library';
    deferred=true;fail=false;renderLibraryDetail();window.pending=refreshLibraryMetadataFromDoi(state.libraryItems[0].paper);
   },scope);
   await page.waitForFunction(()=>paperMetadataRequests.has('p'));
   assert.match(await page.locator(selector).innerText(),/Refreshing info/);
   assert.ok((await page.locator(selector).getAttribute('class')).includes('live'));
   // Completion stays with the original workspace when the user switches away.
   await page.evaluate(()=>{state.mode='browser';$('tab').focus();release();});await page.evaluate(()=>window.pending);
   assert.match(await page.locator(selector).innerText(),/Info refreshed/);
   assert.equal(await page.evaluate(()=>document.activeElement.id),'tab');
   await page.evaluate(scope=>{state.mode=scope==='author'?'author':'library';state.libraryTab=scope==='my-publications'?'my-publications':'library';deferred=false;fail=true;},scope);
   await page.evaluate(()=>refreshLibraryMetadataFromDoi(state.libraryItems[0].paper));
   assert.match(await page.locator(selector).innerText(),/Info refresh failed/);
   await page.evaluate(()=>{fail=false;updated.metadata_refresh.status='partial';});
   await page.evaluate(()=>refreshLibraryMetadataFromDoi(state.libraryItems[0].paper));
   assert.match(await page.locator(selector).innerText(),/Info refresh partial/);
   await page.evaluate(()=>{delete updated.metadata_refresh.status;});
  }
  await page.evaluate(()=>{
   fixtureWork={id:'work',text:'Importing publications',live:true};state.myPublicationSearchStatus='Searching profiles';
   state.myPublicationActivities=[{id:'download',text:'Downloading PDF',live:true},{id:'metadata-refresh',text:'Refreshing info · Synthetic paper',live:true}];
   updateMyPublicationStatusBar();
  });
  assert.equal(await page.locator('#publicationSearchStatus').innerText(),'Importing publications');
  assert.match(await page.locator('#myPublicationSecondaryStatus').innerText(),/Refreshing info/,'explicit refresh remains visible beside background import');
  assert.deepEqual(errors,[]);
  console.log('Whole-paper arXiv-only refresh, repeat clicks, changed workspace, input/tab focus, blurred drafts, stale responses, DOI editing two-row action templates in Library/My Publications/Author Details at three widths, below-button hover/leave, busy/error feedback and keyboard tooltip; shared footer progress/completion/partial/error, independent concurrent requests and workspace switching passed.');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
