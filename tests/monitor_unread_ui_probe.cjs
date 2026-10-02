// Real discovery renderers, click and keyboard handlers; synthetic papers only.
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const {chromium} = require('playwright');
const source = fs.readFileSync(path.resolve(__dirname, '../paper_monitor/ui_server.py'), 'utf8');
const names = ['renderReport', 'renderReportTabs', 'syncReportJournalTab', 'syncMonitorTabUnreadDot',
  'renderPaper', 'selectReportPaper', 'ensureReportPaperSelection', 'updateReportPaperSelectionDom',
  'activeReportPapers', 'activeMonitorKeyboardMode', 'handleReportKeydown', 'reportKeyboardTargetIsEditable',
  'markSelectedLateArrivalSeen', 'updateLateArrivalSeenState', 'groupedReportPapers',
  'renderThemeMonitor', 'renderThemeTabs', 'selectThemeSubject', 'switchThemeSubjectTab',
  'activeThemePapers', 'themePaperMatchesGroup', 'groupedThemePapers', 'themeVisiblePapers',
  'monitorPaperSignature', 'renderMonitorPaperList', 'clearMonitorPaperSurface',
  'stashCurrentMonitorPaperSurface', 'currentMonitorPaperList', 'syncCurrentMonitorPaperSignature', 'updatePaperState'];
const functions = names.map(name => {
  const start = source.search(new RegExp('    (?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n    }', start) + 6);
}).join('\n');
(async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.GEWU_TEST_CHROME});
  try {
    const page = await browser.newPage(); const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.setContent('<div id="reportTabs"></div><div id="papers" tabindex="0"></div>' +
      ['libraryControls','reportTitle','summary','monitorSidebarSummary','arxivCountdownHost'].map(id=>`<div id="${id}"></div>`).join(''));
    await page.addScriptTag({content: `
      const $=id=>document.getElementById(id), FIELD_LABELS={physics:'Physics'}, calls=[];
      const papers=['a','b','c'].map(paper_id=>({paper_id,title:paper_id,journal:'Fixture',fields:['physics'],late_arrival_unread:true,theme_groups:[{key:'A'},{key:'B'}]}));
      const state={mode:'report',papers,themePapers:structuredClone(papers),themePapersByDate:{day:structuredClone(papers)},
        reportCache:{day:{papers:structuredClone(papers),lateArrivals:[{paper_ids:['a','b','c'],count:3,journals:{Fixture:3}}]}},
        lateArrivals:[{paper_ids:['a','b','c'],count:3,journals:{Fixture:3}}], seenLateArrivalIds:new Set(), markingLateArrivalIds:new Set(),
        monitorPaperDomCache:{},figureFailures:new Set(),showFigures:false,reportSelectedPaperId:'',activeReportJournal:'Fixture',journals:['Fixture'],
        selectedFields:new Set(['physics']),selectedDate:'2026-09-30',logoUnavailableJournals:new Set(),
        primaryKeyboardLayer:'content',monitorKeyboardPanes:{report:'papers',theme:'papers'},monitorSelectedPaperIds:{},
        themeGroups:[{key:'A',name:'A'},{key:'B',name:'B'}],activeThemeGroupKey:'A',themeFetchingDates:new Set(),themeSearched:true,
        themeSummary:{},showThemeArxiv:true,themeQuery:'',authorMonitorPapers:[],libraryItems:[],myPublications:[]};
      let held=false, fail=false, rejected=false; const pending=[];
      async function fetch(url,options){calls.push({url,ids:JSON.parse(options.body).paper_ids});if(held)await new Promise(r=>pending.push(r));if(rejected)throw Error('offline');return {ok:!fail};}
      const noop=()=>{}, closeLibraryQuickLook=noop,stopArxivUpdateCountdown=noop,updateToolbarLibraryImport=noop,setPrimaryView=noop,
        renderMonitorSidebarSummary=noop,clearMonitorStatusDisplay=noop,clearFetchProgressDisplay=noop,markNoMatchDate=noop,
        renderArxivUpdateCountdown=noop,requestKatexForPapers=noop,updateReportTabsOverflow=noop,revealActiveReportTab=noop,
        syncPrimaryKeyboardLayer=noop,setMonitorKeyboardPane=noop,focusMonitorPaperSelection=noop,
        syncMonitorPaperActions=noop,themePaperMetaMarkup=()=>'',authorLineMarkup=()=>'',
        selectedThemeGroupParam=()=> 'ALL',restoreCachedThemePapers=noop,updateThemeFetchButton=noop,renderThemeFilters=noop,
        selectedThemeGroupLabel=()=> 'All',themeLastFetchLabel=()=>'',refreshSelectedReportPaperQuickLook=noop;
      const reportFetchIsPending=()=>false,journalLogoUrl=()=>'',paperFieldValues=p=>p.fields,
        inlineLatexMarkup=v=>v,publicationTitleMarkup=v=>v,escapeHtml=v=>String(v),escapeAttr=v=>String(v),
        themePaperIsArxiv=()=>false,librarySearchMatches=(text,q)=>String(text).includes(q);
      const reportVisiblePapers=()=>state.papers.filter(p=>p.paper_id!==state.hiddenId);
      const setActiveThemeGroupKey=key=>{state.activeThemeGroupKey=key;};
      ${functions}
      document.addEventListener('keydown',handleReportKeydown);
      renderReport();
    `});
    const settle=()=>page.waitForFunction(()=>state.markingLateArrivalIds.size===0);
    const ids=()=>page.evaluate(()=>calls.map(c=>c.ids));
    const click=async id=>{await page.locator('#papers [data-paper-id="'+id+'"] h3').click();await settle();};
    await page.locator('[data-journal="Fixture"]').click();
    await page.waitForTimeout(1600); // Old implementation acknowledged the whole journal after 1.4s.
    assert.deepEqual(await ids(),[], 'opening a journal and automatic first-card selection cannot mark it read');
    assert.equal(await page.locator('.paper.late-unread').count(),3);
    await page.evaluate(()=>{held=true;});
    await page.locator('[data-paper-id="b"] h3').click();
    await page.locator('[data-paper-id="b"] h3').click();
    assert.deepEqual(await ids(),[['b']], 'duplicate pending clicks must send one acknowledgement');
    await page.evaluate(()=>{held=false;pending.splice(0).forEach(r=>r());});await settle();
    assert.equal(await page.locator('.paper.late-unread').count(),2);
    assert.equal(await page.locator('[data-journal="Fixture"] .late-dot').count(),1);
    assert.deepEqual(await page.evaluate(()=>state.lateArrivals[0].journals),{Fixture:2});
    await page.locator('#papers').focus(); await page.keyboard.press('ArrowDown'); await settle();
    assert.deepEqual(await ids(),[['b'],['c']], 'ArrowDown acknowledges only the newly selected paper');
    await page.evaluate(()=>{state.hiddenId='a';renderReport();});
    assert.equal(await page.locator('.paper.late-unread').count(),0);
    assert.equal(await page.locator('[data-journal="Fixture"] .late-dot').count(),1,'filtered-out unread paper keeps the journal dot');
    // Generic metadata and download results must not acknowledge other papers.
    await page.evaluate(()=>{updatePaperState('a',{paper_id:'a',late_arrival_unread:false,title:'a'});state.hiddenId='';renderReport();});
    assert.equal(await page.locator('[data-paper-id="a"]').evaluate(e=>e.classList.contains('late-unread')),true);
    // Read records are shared across Journal and Subject and every cached array.
    assert.equal(await page.evaluate(()=>state.themePapersByDate.day.find(p=>p.paper_id==='b').late_arrival_unread),false);
    await page.evaluate(()=>{state.mode='theme';renderThemeMonitor();});
    await page.locator('[data-theme-key="B"]').click();
    await page.waitForTimeout(1600);
    assert.deepEqual(await ids(),[['b'],['c']],'changing subjects cannot acknowledge papers');
    await page.evaluate(()=>{fail=true;});await click('a');
    assert.equal(await page.locator('[data-paper-id="a"]').evaluate(e=>e.classList.contains('late-unread')),true,'HTTP failure keeps the unread flag');
    await page.evaluate(()=>{fail=false;rejected=true;});await click('a');
    assert.equal(await page.locator('[data-paper-id="a"]').evaluate(e=>e.classList.contains('late-unread')),true,'network failure remains retryable');
    await page.evaluate(()=>{rejected=false;});await click('a');
    assert.equal(await page.locator('#reportTabs .late-dot').count(),0,'both subjects lose the dot only after their last unread paper');
    assert.deepEqual(await page.evaluate(()=>state.reportCache.day.lateArrivals),[]);
    // A response started before acknowledgement cannot resurrect the blue dot.
    await page.evaluate(()=>{state.themePapers=state.themePapers.map(p=>({...p,late_arrival_unread:true}));renderThemeMonitor();});
    assert.equal(await page.locator('.paper.late-unread').count(),0);
    await page.evaluate(()=>{state.mode='report';state.papers=state.reportCache.day.papers;renderReport();});
    assert.equal(await page.locator('#reportTabs .late-dot').count(),0);
    assert.equal(await page.locator('.paper.late-unread').count(),0);
    // Switching views while an acknowledgement is pending must not repaint Journal tabs over Subject tabs.
    await page.evaluate(()=>{state.seenLateArrivalIds.clear();state.papers.forEach(p=>p.late_arrival_unread=true);state.themePapers.forEach(p=>p.late_arrival_unread=true);renderReport();held=true;});
    await page.locator('[data-paper-id="b"] h3').click();
    await page.evaluate(()=>{state.mode='theme';renderThemeMonitor();held=false;pending.splice(0).forEach(r=>r());});await settle();
    assert.equal(await page.locator('[data-theme-key]').count(),2);
    assert.equal(await page.locator('[data-journal]').count(),0);
    assert.equal(await page.locator('[data-paper-id="b"]').evaluate(e=>e.classList.contains('late-unread')),false);
    await page.locator('#papers').focus(); await page.keyboard.press('ArrowUp'); await settle();
    assert.deepEqual((await ids()).at(-1),['a'],'Subject ArrowUp acknowledges only the newly selected paper');
    assert.equal(await page.locator('[data-paper-id="c"]').evaluate(e=>e.classList.contains('late-unread')),true);
    assert.equal(await page.locator('#reportTabs .late-dot').count(),2);
    await page.keyboard.press('ArrowDown'); await page.keyboard.press('ArrowDown'); await settle();
    assert.deepEqual((await ids()).at(-1),['c']);
    assert.equal(await page.locator('#reportTabs .late-dot').count(),0);
    assert.deepEqual(errors,[]);
    console.log('PASS: real Journal/Subject render, mouse/keyboard selection, filtered unread aggregation, cache and metadata preservation, failed acknowledgement retry, stale replies and view-switch race.');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
