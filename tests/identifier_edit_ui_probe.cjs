const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {chromium} = require('playwright');
const source = fs.readFileSync(path.resolve(__dirname, '../paper_monitor/ui_server.py'), 'utf8');
const names = ['metadataDetailContext','applyMetadataResult','savePaperIdentifier','savePaperDoi','identifierSaveNotice','wireDoiIdentifierControls','wirePreprintIdentifierControls'];
const functions = names.map(name => {
  const start = source.search(new RegExp('    (?:async )?function '+name+'\\('));
  assert.ok(start >= 0, name); return source.slice(start, source.indexOf('\n    }', start)+6);
}).join('\n');
const cssStart = source.indexOf('<style>', source.indexOf('INDEX_HTML ='));
const css = source.slice(cssStart+7,source.indexOf('</style>',cssStart));
(async()=>{
  const browser = await chromium.launch({headless:true, executablePath:process.env.GEWU_TEST_CHROME});
  try {
    const page=await browser.newPage(), errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.setContent('<button id="other">Other control</button><div id="libraryDetail"></div><div id="authorMonitorDetailBody"></div>');
    await page.addStyleTag({content:css+'body{display:block;background:white;padding:20px}.library-detail{display:block!important;width:350px;max-width:calc(100vw - 40px);padding:20px}'});
    await page.addScriptTag({content:`
      const $=id=>document.getElementById(id);
      const state={mode:'library',libraryTab:'library',libraryItems:[],authorMonitorPapers:[],myPublications:[]};
      let calls=[], deferred=false, release, renders=0, failure=false, server;
      const updateMetadataRefreshButton=()=>{}, closeMetadataRefreshTooltip=()=>{}, showMetadataRefreshTooltip=()=>{};
      function rootNow(){return $(state.mode==='author'?'authorMonitorDetailBody':'libraryDetail');}
      function updatePaperState(id,p){const row=state.libraryItems.find(x=>x.paper_id===id);if(row)row.paper=p;}
      function renderLibraryDetail(){
        renders++; const root=rootNow(), paper=state.libraryItems[0].paper;
        root.className='library-detail';root.dataset.metadataPaperId=paper.paper_id;
        root.innerHTML='<h3>Synthetic paper</h3><div class="library-detail-status"></div><dl><dt>DOI</dt><dd><div class="library-detail-doi"><input id="libraryDetailDoiInput"></div></dd><dt>arXiv</dt><dd class="library-preprint-identifier"><span class="preprint-identifier-main"><button class="preprint-identifier-value" data-action="edit-preprint-identifier"></button><input class="preprint-identifier-input"></span><span class="preprint-identifier-status"></span></dd></dl>';
        const doi=root.querySelector('#libraryDetailDoiInput'), arxiv=root.querySelector('.preprint-identifier-input');
        doi.value=doi.defaultValue=paper.doi;arxiv.value=arxiv.defaultValue=paper.preprint_id;
        root.querySelector('.preprint-identifier-value').textContent=paper.preprint_id;
        wirePreprintIdentifierControls(root,paper);
      }
      const renderPublicationDetail=renderLibraryDetail,renderAuthorMonitorPaperDetail=renderLibraryDetail;
      async function fetch(url,options){
        const body=JSON.parse(options.body);calls.push({url,body});
        if(deferred)await new Promise(r=>release=r);
        if(failure)return {ok:false,json:async()=>({error:'Invalid identifier'})};
        server={...server,[body.kind==='doi'?'doi':'preprint_id']:body.identifier.toLowerCase()};
        return {ok:true,json:async()=>({paper:{...server}})};
      }
      function reset(scope){
        $('libraryDetail').innerHTML='';$('authorMonitorDetailBody').innerHTML='';
        state.mode=scope==='author'?'author':'library';state.libraryTab=scope==='my-publications'?'my-publications':'library';
        server={paper_id:'p',doi:'10.1234/old',preprint_id:'1801.00001',title:'Synthetic paper'};
        state.libraryItems=[{paper_id:'p',paper:{...server}}];calls=[];deferred=false;failure=false;renderLibraryDetail();
      }
      ${functions}
      reset('library');
    `});
    for(const scope of ['library','my-publications','author']){
      await page.evaluate(scope=>reset(scope),scope);
      const root=scope==='author'?'#authorMonitorDetailBody':'#libraryDetail';
      const doi=page.locator(root+' #libraryDetailDoiInput');
      await doi.fill('10.1234/CORRECTED');await doi.press('Enter');
      await page.waitForFunction(()=>rootNow().querySelector('.library-detail-status').textContent==='Identifier updated');
      assert.equal(await doi.inputValue(),'10.1234/corrected');
      assert.equal(await page.evaluate(()=>document.activeElement.tagName),'BODY','Enter leaves edit focus');
      assert.equal(await page.locator(root+' .library-detail-status').evaluate(e=>getComputedStyle(e).color),'rgb(19, 115, 51)');
      const arxiv=page.locator(root+' .preprint-identifier-input');
      await page.locator(root+' [data-action="edit-preprint-identifier"]').click();
      await arxiv.fill('2201.00001');await arxiv.press('Enter');
      await page.waitForFunction(()=>server.preprint_id==='2201.00001');
      assert.equal(await page.locator(root+' .is-editing').count(),0);
      assert.equal(await page.locator(root+' .preprint-identifier-value').innerText(),'2201.00001');
      assert.equal(await page.locator(root+' .library-detail-status').innerText(),'Identifier updated');
      assert.equal(await page.evaluate(()=>document.activeElement.tagName),'BODY');
      await doi.fill('');await doi.press('Enter');await page.waitForFunction(()=>server.doi==='');
      await doi.fill('10.1234/old');await doi.press('Enter');await page.waitForFunction(()=>server.doi==='10.1234/old');
      const count=await page.evaluate(()=>calls.length);
      await doi.focus();await doi.press('Enter');
      assert.equal(await page.evaluate(()=>calls.length),count);
      assert.equal(await page.locator(root+' .library-detail-status').innerText(),'Identifier saved');
      await page.evaluate(()=>failure=true);await doi.fill('invalid');await doi.press('Enter');
      await page.waitForFunction(()=>rootNow().querySelector('.library-detail-status').classList.contains('err'));
      assert.equal(await doi.inputValue(),'invalid');assert.equal(await doi.evaluate(e=>e.readOnly),false);
      assert.equal(await page.evaluate(()=>document.activeElement.id),'libraryDetailDoiInput','failed save stays editable');
      await page.evaluate(()=>{failure=false;deferred=true;});await doi.fill('10.1234/delayed');await doi.press('Enter');await doi.press('Enter');
      assert.equal(await page.evaluate(()=>calls.filter(x=>x.body.identifier==='10.1234/delayed').length),1);
      await page.locator('#other').focus();await page.evaluate(()=>release());
      await page.waitForFunction(()=>server.doi==='10.1234/delayed');
      assert.equal(await page.evaluate(()=>document.activeElement.id),'other','late save preserves other focus');
    }
    // Retained DOI closure while another draft prevents render: A -> B -> A must save twice.
    await page.evaluate(()=>reset('library'));
    await page.locator('[data-action="edit-preprint-identifier"]').click();
    await page.locator('.preprint-identifier-input').fill('unsaved arxiv');
    await page.evaluate(()=>{const p=state.libraryItems[0].paper;window.oldPaper=p;const input=$('libraryDetailDoiInput');input.value='10.1234/new';return savePaperDoi(p,$('libraryDetail'));});
    await page.evaluate(()=>{$('libraryDetailDoiInput').value='10.1234/old';return savePaperDoi(window.oldPaper,$('libraryDetail'));});
    assert.equal(await page.evaluate(()=>calls.length),2,'revert to original DOI is persisted');
    assert.equal(await page.evaluate(()=>server.doi),'10.1234/old');
    await page.evaluate(()=>{reset('library');deferred=true;});
    await page.locator('#libraryDetailDoiInput').fill('10.1234/late');await page.locator('#libraryDetailDoiInput').press('Enter');
    await page.evaluate(()=>{$('libraryDetail').dataset.metadataPaperId='q';$('libraryDetail').innerHTML='<h3 id="new-paper">Other paper</h3><div class="library-detail-status"></div>';release();});
    await page.waitForFunction(()=>server.doi==='10.1234/late');
    assert.equal(await page.locator('#new-paper').innerText(),'Other paper');
    assert.equal(await page.locator('.library-detail-status').innerText(),'','no stale notice on another paper');
    for(const width of [1440,960,520]){
      await page.setViewportSize({width,height:800});await page.evaluate(()=>reset('library'));
      await page.locator('#libraryDetailDoiInput').fill('10.1234/correct');await page.locator('#libraryDetailDoiInput').press('Enter');
      await page.waitForFunction(()=>rootNow().querySelector('.library-detail-status').textContent==='Identifier updated');
      assert.equal(await page.locator('#libraryDetail').evaluate(e=>e.scrollWidth<=e.clientWidth+1),true);
      if(width===520&&process.env.GEWU_TEST_ARTIFACT_DIR)await page.screenshot({path:path.join(process.env.GEWU_TEST_ARTIFACT_DIR,'identifier-saved.png')});
    }
    assert.deepEqual(errors,[]);console.log('PASS: DOI/arXiv Enter, saved feedback, blur, clear/retype, revert, errors, pending/switch guards; three Details scopes and widths.');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
