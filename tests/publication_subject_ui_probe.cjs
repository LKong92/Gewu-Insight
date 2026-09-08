// Product controls against generated data, an isolated browser and fake local APIs.
const assert = require('node:assert/strict');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const html = JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c', 'import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'], {cwd:root, encoding:'utf8', maxBuffer:8*1024*1024}));
function fn(name) {
  const start = html.search(new RegExp('    (?:async )?function ' + name + '\\('));
  assert.ok(start >= 0, name);
  const tail = html.slice(start), end = tail.slice(1).search(/\n    (?:async )?function /);
  return tail.slice(0, end + 1);
}
(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1050,height:850}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.setContent(`<style>${html.match(/<style>([\s\S]*?)<\/style>/)[1]}</style><style>body{display:block;min-width:0;padding:20px;background:#fff}#papers{height:120px;overflow:auto}.paper{height:400px}</style><section class="my-publications-panel" style="height:640px"><div class="my-publications-search"><div class="publication-search-results" id="publicationSearchResults"></div></div><div class="my-publications-table-wrap" id="publicationFixtureTable">Saved publications</div><div class="my-publications-stats">Publication summary</div></section><div class="my-publications-status-bar" id="fixtureStatusBar"></div><input id="publicationSearchBox" value="Deferred search"><div id="papers"><div class="paper">Preserved Subject paper</div></div><input id="themeGroupName" value="Renamed"><textarea id="themeGroupKeywords">new keyword</textarea><span id="themeGroupStatus"></span><button id="saveThemeGroup">Save</button>`);
    await page.evaluate(() => {
      window.$ = id => document.getElementById(id);
      window.state = {mode:'library',libraryTab:'my-publications',myPublicationSelectionId:9,myPublications:[{id:9,paper:{title:'Already present',doi:'10.1234/known',paper_id:'known'}}],myPublicationScholarProfile:{name:'Alice Researcher',user_id:'fixture',url:'https://scholar.google.com/citations?user=fixture'},myPublicationCandidateProfile:null,myPublicationSearchOpen:false,myPublicationSearchToken:1,myPublicationSearchResults:[],myPublicationAuthorCache:{},myPublicationWork:{imports:[],identifiers:{}},editingThemeGroupKey:'SUBJECT',selectedThemeGroups:new Set(['SUBJECT']),activeThemeGroupKey:'SUBJECT'};
      window.escapeHtml = value => String(value??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;'); window.escapeAttr = escapeHtml;
      window.scholarProfileExternalUrl = p => p.url || ''; window.myPublicationById = id => state.myPublications.find(p => p.id === id); window.publicationTitleMarkup = escapeHtml;
      window.requests = [];
      window.fetch = async (url, opts) => {
        const payload = JSON.parse(opts.body); requests.push({url,payload});
        return {ok:true,json:async () => url.includes('theme-groups') ? {groups:[{key:'SUBJECT',name:'Renamed'}],group:{key:'SUBJECT'}} : {work:{imports:[{id:1,name:payload.profile?.name || 'Alice Researcher',user_id:payload.profile?.user_id || 'fixture',status:'queued',seen:0,added:0,reused:0}],identifiers:{}}}};
      };
      window.renderMyPublications = () => {$('publicationSearchResults').innerHTML = myPublicationSearchResultsMarkup(); $('fixtureStatusBar').innerHTML = myPublicationStatusBarMarkup();};
      window.updateMyPublicationScholarProfileStrip = () => {};
      window.saveSelectedThemeGroups = () => {}; window.closeThemeGroupDialog = () => {}; window.renderThemeFilters = () => {}; window.renderThemeTabs = () => {}; window.groupedThemePapers = () => [];
      window.restoreMonitorViewport = v => {$('papers').scrollTop = v.scrollTop;};
      window.loadThemeMonth = () => {throw Error('Editing must not reload calendar');};
      window.loadThemeReportForDate = () => {throw Error('Editing must not reload cards');};
      window.setActiveThemeGroupKey = () => {throw Error('Editing must not switch subjects');};
    });
    const names = ['myPublicationSearchStatusText','myPublicationSearchStatusIsLive','myPublicationStatusItems','myPublicationStatusClass','myPublicationStatusBarMarkup','updateMyPublicationStatusBar','myPublicationWorkStatusItem','myPublicationImportForProfile','myPublicationWorkMarkup','myPublicationsVisible','renderMyPublicationsIfVisible','runMyPublicationWorkAction','myPublicationCandidateAlreadyAdded','myPublicationSearchResultViewItems','myPublicationSearchResultsMarkup','closeMyPublicationSearchResults','openMyPublicationProgress','handleMyPublicationPanelClick','pollMyPublicationWork','searchMyPublications','cacheMyPublicationAuthorResults','restoreMyPublicationAuthorResults','saveThemeGroup'];
    await page.addScriptTag({content:names.map(fn).join('\n') + '\nfunction scheduleMyPublicationWorkPoll() {}'});
    assert.doesNotMatch(fn('renderMyPublications'), /id="myPublicationWork"/);
    assert.equal((html.match(/closeMyPublicationSearchResults\(\);/g) || []).length, 1, 'Only the explicit panel handler closes results');
    await page.evaluate(() => document.addEventListener('click', handleMyPublicationPanelClick));
    await page.evaluate(() => renderMyPublications());
    assert.equal(await page.locator('[data-publication-work-action]').count(), 0, 'No extra toolbar in normal My Publications');
    assert.equal(await page.locator('.my-publications-search').isVisible(), false);
    await page.evaluate(() => {
      state.myPublicationSearchOpen=true; state.myPublicationSearchResults = [{candidate_type:'scholar-profile',name:'Another Author',user_id:'another',url:'https://scholar.google.com/citations?user=another'}]; renderMyPublications();
    });
    assert.equal(await page.locator('[data-action="use-scholar-profile"]').count(), 1);
    await page.locator('[data-profile-index="0"]').evaluate(el => runMyPublicationWorkAction(el));
    let req = await page.evaluate(() => requests.at(-1));
    assert.equal(req.payload.profile.user_id, 'another'); assert.equal(req.payload.action, 'add-all');
    assert.equal('limit' in req.payload, false); assert.equal('papers' in req.payload, false);
    assert.equal(await page.locator('[data-publication-work-action="pause"]').count(), 1);
    await page.locator('[data-publication-work-action="pause"]').evaluate(el => runMyPublicationWorkAction(el));
    assert.equal(await page.evaluate(() => requests.at(-1).payload.action), 'pause');
    await page.evaluate(() => {
      state.myPublicationPanelMode='search'; state.myPublicationCandidateProfile = {name:'Alice Researcher',user_id:'fixture',url:'https://scholar.google.com/citations?user=fixture'};
      state.myPublicationSearchResults = [{paper:{title:'Unadded article',paper_id:'new'}}];
      renderMyPublications(); cacheMyPublicationAuthorResults('alice');
    });
    assert.equal(await page.locator('[data-action="add-publication-result"]').textContent(), 'Add');
    assert.equal(await page.locator('.my-publications-search [data-publication-work-action="add-all"]').count(), 1);
    await page.locator('[data-publication-work-action="add-all"]').evaluate(el => runMyPublicationWorkAction(el));
    assert.equal(await page.evaluate(() => requests.at(-1).payload.profile.user_id), 'fixture');
    await page.locator('[data-action="close-publication-progress"]').click();
    assert.equal(await page.locator('[data-publication-work-action]').count(), 0, 'Background job does not create a toolbar after closing search');
    assert.match(await page.locator('#publicationSearchStatus').textContent(), /Importing: 0 read/);
    const requestCountBeforeDetails = await page.evaluate(() => requests.length);
    await page.locator('#myPublicationProgressDetails').click();
    assert.equal(await page.evaluate(() => requests.length), requestCountBeforeDetails, 'Opening progress does not query Scholar');
    await page.locator('#publicationFixtureTable').click();
    assert.equal(await page.locator('.my-publications-search').isVisible(), true, 'Clicking a publication does not dismiss progress');
    assert.equal(await page.locator('[data-publication-work-action="pause"]').count(), 1, 'Existing work stays accessible while a new profile search is loading or blocked');
    await page.evaluate(() => closeMyPublicationSearchResults());
    await page.evaluate(() => restoreMyPublicationAuthorResults('alice'));
    assert.equal(await page.evaluate(() => state.myPublicationCandidateProfile.user_id), 'fixture');
    await page.evaluate(() => {
      state.myPublicationPanelMode='progress'; state.myPublicationWork = {imports:[{id:1,user_id:'fixture',name:'Alice Researcher',status:'partial',seen:5400,added:5000,reused:398,rejected:2,message:'Two articles need identity review.'}],identifiers:{matched:4500,pending:300,working:1,unresolved:199,error:0}}; renderMyPublications();
    });
    assert.match(await page.locator('#myPublicationWork').textContent(), /5400 read/);
    assert.equal(await page.locator('[data-publication-work-action="resume"]').count(), 1);
    assert.match(await page.locator('#myPublicationWork').textContent(), /301 pending/);
    for (const width of [750,1050,1400]) {
      await page.setViewportSize({width,height:850});
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false);
      const boxes = await page.evaluate(() => {const table=$('publicationFixtureTable').getBoundingClientRect(), search=document.querySelector('.my-publications-search').getBoundingClientRect(); return {tableHeight:table.height,ordered:table.top>=search.bottom};});
      assert.ok(boxes.ordered); assert.ok(boxes.tableHeight > 100);
    }
    await page.screenshot({path:'/private/tmp/gewu-publication-workflows-ui.png'});
    await page.evaluate(() => {state.myPublicationPanelMode='search';state.myPublicationWork.imports[0].status='complete';state.myPublicationWork.identifiers={};renderMyPublications();});
    await page.locator('[data-publication-work-action="add-all"]').evaluate(el => runMyPublicationWorkAction(el));
    assert.equal(await page.evaluate(() => requests.at(-1).payload.action), 'check');
    await page.evaluate(() => {closeMyPublicationSearchResults();state.myPublicationPanelMode='search';state.myPublicationSearchOpen=true;state.myPublicationSearchResults=[{paper:{title:'Ordinary title search',paper_id:'title'}}];renderMyPublications();});
    assert.equal(await page.locator('[data-publication-work-action="add-all"]').count(), 0, 'Title search must not import an unrelated saved profile');
    await page.evaluate(() => {
      state.myPublicationWork = {imports:[{id:1,status:'complete',seen:559,added:554,reused:5}],identifiers:{matched:69,unresolved:1,pending:401,working:1}};
      closeMyPublicationSearchResults();
      state.myPublicationActivities=[{id:'other',text:'Refreshing metrics',live:true}];
      updateMyPublicationStatusBar();
    });
    assert.equal(await page.locator('.my-publications-search').isVisible(), false);
    assert.match(await page.locator('#publicationSearchStatus').textContent(), /DOI\/arXiv: 70\/472 processing/);
    assert.match(await page.locator('#publicationSearchStatus').getAttribute('class'), /live/);
    assert.match(await page.locator('#myPublicationSecondaryStatus').textContent(), /Refreshing metrics/);
    await page.evaluate(() => {state.myPublicationWork.identifiers={matched:471,unresolved:1};updateMyPublicationStatusBar();});
    assert.match(await page.locator('#publicationSearchStatus').textContent(), /472\/472 processed/);
    assert.doesNotMatch(await page.locator('#publicationSearchStatus').getAttribute('class'), /live/);
    await page.evaluate(() => {state.myPublicationWork.imports[0].status='error';updateMyPublicationStatusBar();});
    assert.match(await page.locator('#publicationSearchStatus').textContent(), /Import needs retry/);
    await page.evaluate(() => {state.myPublicationWork.imports[0].status='paused';updateMyPublicationStatusBar();});
    assert.match(await page.locator('#publicationSearchStatus').textContent(), /Import paused/);
    for (const width of [750,1050,1400]) {
      await page.setViewportSize({width,height:850});
      assert.ok(await page.locator('#myPublicationProgressDetails').isVisible());
      const bounds = await page.locator('#myPublicationProgressDetails').boundingBox();
      assert.ok(bounds.x + bounds.width <= width, 'Details remains accessible at narrow widths');
    }
    // Exercise the real polling path with unchanged paper counts: failed/unmatched
    // identifier progress must update the footer without reopening or rebuilding.
    await page.evaluate(async () => {
      const originalFetch=fetch, originalTimeout=window.setTimeout;
      const nextWork={imports:[{id:1,status:'complete',seen:559,added:554,reused:5}],identifiers:{matched:69,unresolved:1,pending:402}};
      window.fetch=async () => ({ok:true,json:async () => ({work:nextWork})});
      window.setTimeout=() => 0;
      window.applyMyPublications=data => {state.myPublicationWork=data.work;};
      try {
        await pollMyPublicationWork();
        const footer=$('publicationSearchStatus');
        nextWork.identifiers={matched:69,unresolved:2,pending:401};
        await pollMyPublicationWork();
        if ($('publicationSearchStatus') !== footer) throw Error('Counter-only updates must not rebuild the table');
        if (!footer.textContent.includes('71/472 processing')) throw Error('Closed-panel progress did not update');
        if (state.myPublicationSearchOpen) throw Error('Polling reopened the panel');
        window.fetch=async () => {throw Error('offline');};
        await pollMyPublicationWork();
        if (!footer.textContent.includes('Progress unavailable')) throw Error('Lost progress connection must be visible');
      } finally {window.fetch=originalFetch;window.setTimeout=originalTimeout;myPublicationWorkPollTimer=null;}
    });
    // A response that arrives after Close must not restore candidates or reopen the panel.
    await page.evaluate(() => {
      window.savedFetch = fetch;
      window.fetch = () => new Promise(resolve => {window.releaseSearch = resolve;});
      window.pendingSearch = searchMyPublications();
    });
    await page.locator('[data-action="close-publication-progress"]').click();
    await page.evaluate(async () => {
      releaseSearch({ok:true,json:async () => ({results:[{paper:{title:'Late result'}}]})});
      await pendingSearch; window.fetch = savedFetch;
    });
    assert.equal(await page.evaluate(() => state.myPublicationSearchResults.length), 0);
    assert.equal(await page.locator('.my-publications-search').isVisible(), false);
    await page.evaluate(() => {
      state.myPublicationWork={imports:[{id:1,name:'Hong Ding',user_id:'old',status:'complete',seen:559,added:554,reused:5,currently_saved:0}],identifiers:{}};
      state.myPublicationPanelMode='search';state.myPublicationSearchOpen=true;
      state.myPublicationCandidateProfile=null;state.myPublicationSearchResults=[];
      state.myPublicationSearchStatus='Gewu Insight has temporarily paused Google Scholar requests. Try again after 2026-09-09 23:57 (local time).';
      renderMyPublications();
    });
    assert.doesNotMatch(await page.locator('#publicationSearchResults').textContent(), /Hong Ding|554/);
    assert.match(await page.locator('.publication-panel-status').textContent(), /Try again after/);
    assert.doesNotMatch(await page.locator('#publicationSearchStatus').textContent(), /554 added/);
    assert.equal(await page.locator('#myPublicationProgressDetails').textContent(), 'History');
    await page.locator('#myPublicationProgressDetails').click();
    assert.equal(await page.locator('.publication-import-history').getAttribute('open'), '');
    assert.match(await page.locator('.publication-import-history').textContent(), /554 originally added.*0 currently in My Publications/);
    await page.locator('[data-action="close-publication-progress"]').click();
    await page.evaluate(async () => {state.mode='theme';$('papers').scrollTop=100;window.originalPaper=$('papers').firstElementChild;await saveThemeGroup();});
    assert.equal(await page.evaluate(() => $('papers').scrollTop), 100);
    assert.equal(await page.evaluate(() => $('papers').firstElementChild===originalPaper), true);
    assert.equal(await page.evaluate(() => state.activeThemeGroupKey), 'SUBJECT');
    assert.equal(await page.evaluate(() => requests.filter(r=>r.url.includes('theme')).length), 1);
    assert.deepEqual(errors, []);
    console.log('Publication/Subject UI checks passed: unchanged normal table, Add All only in search/add results, full-profile payloads, individual Add, pause/continue/recheck, three widths, and exact Subject DOM/scroll preservation.');
  } finally {await browser.close();}
})().catch(e => {console.error(e);process.exitCode=1;});
