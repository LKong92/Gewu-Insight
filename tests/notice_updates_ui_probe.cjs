// Product event UI, real Chromium DOM, deterministic service responses.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {chromium} = require('playwright');
const source = fs.readFileSync(path.resolve(__dirname, '../paper_monitor/ui_server.py'), 'utf8');
const htmlStart = source.indexOf('INDEX_HTML =');
const cssStart = source.indexOf('<style>', htmlStart);
const css = source.slice(cssStart, source.indexOf('</style>', cssStart) + 8);
const layout = source.slice(source.indexOf('<div class="app library-mode">'), source.indexOf('<div class="papers" id="papers"></div>') + '<div class="papers" id="papers"></div>'.length)
  .replace('app library-mode', 'app report-mode') + '</section></div></main></div>';
const names = ['renderMonitorNoticeEvents', 'subjectMatches', 'paperMatchesField', 'rawPaperFieldValues', 'paperFieldValues', 'standaloneFieldCodes', 'canonicalFieldDefinitions', 'publicationNoticesMarkup', 'paperFileRoleLabel', 'escapeHtml', 'escapeAttr', 'refreshLibraryMetadataFromDoi'];
const functions = names.map(name => {
  const start = source.search(new RegExp('    (?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n    }', start) + 6);
}).join('\n');
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.GEWU_TEST_CHROME});
  try {
    const page = await browser.newPage(); const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setContent(css + layout + '<div hidden><div id="libraryDetail"></div><div id="files"></div></div>');
    await page.addScriptTag({content:`
      const $=id=>document.getElementById(id);
      const state={selectedJournals:new Set(['Nature']),selectedFields:new Set(['physics']),libraryLoaded:true,mode:'library',libraryTab:'library'};
      const DEFAULT_FIELD_SETTINGS={fields:[{code:'physics'},{code:'chemistry'},{code:'biology'}],standalone_fields:['physics','chemistry']}, FIELD_LABELS={};
      const paperMetadataRequests=new Map();
      const calls=[], applied=[], opened=[]; let fail=true, release;
      const event={fields:['physics'],id:17,doi:'10.5555/notice',title:'Retraction: <img src=x onerror="window.bad=true">',kind:'retraction_notice',journal:'Nature',publication_date:'2026-10-02'};
      const files=[{paper_id:'original',publication_notices:[event],files:[]}];
      function applyPaperFilesPayloads(values){applied.push(values);$('files').innerHTML=publicationNoticesMarkup(values[0]);}
      const upsertLibraryFolderLocal=()=>{},upsertLibraryItemLocal=()=>{},openWebsite=url=>opened.push(url);
      const metadataDetailContext=()=> 'original',savePaperDoi=async()=>{},updateMetadataRefreshButton=()=>{},updateMetadataRefreshActivity=()=>{},updateLibraryActivityStatus=()=>{};
      const applyMetadataResult=()=>{if(!applied.length)throw Error('Paper Files missing from refresh response');};
      async function fetch(url,options){calls.push({url,body:JSON.parse(options.body)});if(release===null)await new Promise(r=>release=r);return {ok:!fail,json:async()=>fail?{error:'Original DOI needs review'}:{paper:{paper_id:'original',storage_key:'gw_original'},paper_files:files,item:{paper_id:'original'},folder:{id:1}}};}
      ${functions}
      $('monitorSidebarSummary').innerHTML='<div class="monitor-sidebar-summary-title">Monitor Summary</div><div class="monitor-sidebar-summary-row"><span>Papers</span><span>25 total · 20 shown</span></div>';
      $('reportTabs').innerHTML='<button class="journal-tab active">Nature</button>';
      $('reportTabs').classList.add('open');
      $('papers').innerHTML='<article class="paper">Original article</article>';
      renderMonitorNoticeEvents([event,{...event,id:18,journal:'Other Journal'}]);
    `});
    const boxes = () => page.evaluate(() => {
      const rect = id => {const b=$(id).getBoundingClientRect();return {x:b.x,y:b.y,width:b.width,height:b.height,bottom:b.bottom,right:b.right};};
      return {notices:rect('monitorNoticeEvents'),summary:rect('monitorSidebarSummary'),tabs:rect('reportTabs'),papers:rect('papers'),sidebar:document.querySelector('.sidebar').getBoundingClientRect().right};
    });
    for (const width of [1440, 900]) {
      await page.setViewportSize({width,height:1000});
      assert.equal(await page.locator('.sidebar > #monitorSidebarSummary + #monitorNoticeEvents').count(),1, 'notices belong immediately below Monitor Summary in the sidebar');
      assert.equal(await page.locator('.report-column #monitorNoticeEvents').count(),0, 'notices cannot participate in the report grid');
      assert.equal(await page.locator('#monitorNoticeEvents details').getAttribute('open'), null);
      const collapsed = await boxes();
      assert.ok(collapsed.notices.y >= collapsed.summary.bottom && collapsed.notices.right <= collapsed.sidebar);
      assert.ok(collapsed.notices.right <= collapsed.tabs.x && collapsed.tabs.bottom <= collapsed.papers.y, 'no tab or article overlap: '+JSON.stringify(collapsed));
      await page.locator('#monitorNoticeEvents summary').click();
      const expanded = await boxes();
      assert.ok(expanded.notices.height > collapsed.notices.height);
      assert.deepEqual(expanded.tabs,collapsed.tabs, 'expansion cannot move journal tabs');
      assert.deepEqual(expanded.papers,collapsed.papers, 'expansion cannot shrink article scrolling');
      assert.equal(await page.evaluate(()=>getComputedStyle($('monitorNoticeEvents')).fontSize),await page.locator('.monitor-sidebar-summary-row').evaluate(el=>getComputedStyle(el).fontSize));
      assert.equal(await page.locator('#monitorNoticeEvents').evaluate(el=>el.scrollWidth<=el.clientWidth),true,'long titles wrap inside sidebar');
      await page.locator('#monitorNoticeEvents summary').click();
    }
    await page.evaluate(()=>{
      window.filterEvents=[event,{...event,id:18,fields:['chemistry']},{...event,id:19,fields:['biology']},{...event,id:20,fields:[]},{...event,id:21,journal:'Other Journal'}];
      renderMonitorNoticeEvents(window.filterEvents);
    });
    const ids=()=>page.locator('[data-notice-id]').evaluateAll(rows=>rows.map(row=>Number(row.dataset.noticeId)));
    assert.deepEqual(await ids(),[17],'notice list follows active Field and Journal filters');
    await page.evaluate(()=>{state.selectedFields=new Set(['physics','chemistry']);renderMonitorNoticeEvents(window.filterEvents);});
    assert.deepEqual(await ids(),[17,18],'multiple selected fields use the same OR rule as papers');
    assert.match(await page.locator('#monitorNoticeEvents summary').innerText(),/\(2\)/);
    await page.evaluate(()=>{state.selectedFields=new Set(['other']);renderMonitorNoticeEvents(window.filterEvents);});
    assert.deepEqual(await ids(),[19,20],'non-standalone and missing classifications follow Other Fields');
    await page.evaluate(()=>{state.selectedFields=new Set(['all']);renderMonitorNoticeEvents(window.filterEvents);});
    assert.deepEqual(await ids(),[17,18,19,20],'All Fields still respects journal selection');
    await page.evaluate(()=>{state.selectedFields=new Set(['physics']);renderMonitorNoticeEvents([window.filterEvents[1]]);});
    assert.equal(await page.locator('#monitorNoticeEvents').isVisible(),false,'no matching fields hides section');
    await page.evaluate(()=>renderMonitorNoticeEvents([]));
    assert.equal(await page.locator('#monitorNoticeEvents').isVisible(),false,'empty notice section hidden');
    await page.evaluate(()=>renderMonitorNoticeEvents([event]));
    await page.evaluate(()=>document.querySelector('.app').className='app theme-mode');
    assert.equal(await page.locator('#monitorNoticeEvents').isVisible(),false,'Journal notices hidden in Subject Monitor');
    await page.evaluate(()=>document.querySelector('.app').className='app report-mode');
    assert.match(await page.locator('summary').innerText(), /Publication updates \(1\)/);
    await page.locator('summary').click();
    assert.equal(await page.locator('[data-notice-id] img').count(), 0, 'publisher markup escaped');
    assert.equal(await page.locator('[data-paper-id]').count(), 0, 'events are not independent paper cards');
    await page.locator('[data-notice-open]').click();
    assert.deepEqual(await page.evaluate(()=>opened), ['https://doi.org/10.5555/notice']);
    await page.locator('[data-notice-add]').click();
    assert.match(await page.locator('[role=status]').innerText(), /needs review/);
    assert.equal(await page.locator('[data-notice-add]').isEnabled(), true, 'failed relation can be retried');
    await page.evaluate(()=>{fail=false;release=null;});
    await page.locator('[data-notice-add]').click();
    assert.equal(await page.locator('[data-notice-add]').isDisabled(), true);
    await page.evaluate(()=>release());
    await page.waitForFunction(()=>document.querySelector('[role=status]').textContent.includes('gw_original'));
    assert.deepEqual(await page.evaluate(()=>calls[1].body), {notice_id:17,snapshot:false});
    assert.match(await page.locator('#files').innerText(), /Retraction notice/);
    assert.equal(await page.locator('#files a').getAttribute('href'), 'https://doi.org/10.5555%2Fnotice');
    await page.evaluate(async()=>{applied.length=0;await refreshLibraryMetadataFromDoi({paper_id:'original',title:'Original article'});});
    assert.equal(await page.evaluate(()=>applied.length), 1, 'Refresh Info installs the new Paper Files snapshot');
    assert.deepEqual(await page.evaluate(()=>calls.at(-1).body), {paper_id:'original',snapshot:false});
    assert.deepEqual(errors, []);
    console.log('Notice UI: real product sidebar/layout at 1440/900 px, collapsed/expanded/empty and Subject states; Field/Journal filters and counts, event-only display, escaped evidence, exact notice action, retry, original Key and Refresh Info Paper Files update passed.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
