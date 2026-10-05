// Generated DOM and in-memory API only; never accesses the user's browser data.
const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path');
const {chromium} = require('playwright');
const {execFileSync} = require('node:child_process');
const root = path.resolve(__dirname,'..'), read = p => fs.readFileSync(path.join(root,p),'utf8');
const workspaceHTML = JSON.parse(execFileSync(process.env.GEWU_TEST_PYTHON || 'python3', ['-c','import json; from paper_monitor.ui_server import INDEX_HTML; print(json.dumps(INDEX_HTML))'],{cwd:root,encoding:'utf8',maxBuffer:8*1024*1024,env:{...process.env,PYTHONDONTWRITEBYTECODE:'1'},stdio:['ignore','pipe','pipe']}));
const pickerFunctions = ['ensureLibrarySnapshotForAddMenu','closeLibraryAddMenus','libraryAddFolderCanTarget','libraryAddWorkspaceRoots','libraryAddWorkspaceForRoot','libraryAddChildFolders','libraryAddFolderHasChildren','libraryAddColumnTitle','libraryAddFolderPath','renderLibraryAddMenu','libraryAddMenuAnchor','positionLibraryAddMenu','openLibraryAddMenu','applyPaperFilesPayloads','navigateToPaperInLibrary','libraryWorkspaceIndexForFolder','libraryFolderPathIdsFromDisplayRoot','selectLibraryItemInColumns'];
function workspaceFunction(name) {
  const start=workspaceHTML.search(new RegExp('    (?:async )?function '+name+'\\('));
  assert.ok(start>=0,name);
  const source=workspaceHTML.slice(start), end=source.slice(1).search(/\n    (?:async )?function /);
  return source.slice(0,end+1);
}

(async () => {
  const browser = await chromium.launch({headless:true, ...(process.env.GEWU_TEST_CHROME ? {executablePath:process.env.GEWU_TEST_CHROME} : {})});
  try {
    const page = await browser.newPage();
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/*',route=>route.fulfill({body:'<html><head></head><body></body></html>',contentType:'text/html'}));
    await page.goto('http://127.0.0.1:8765');
    await page.setContent(`<meta name="citation_title" content="Quantum sensing with light"><meta name="citation_doi" content="10.1234/fixture"><meta name="citation_author" content="A. Scientist"><meta name="citation_pdf_url" content="https://example.org/main.pdf"><input type="password" value="never-collect-this"><a href="https://example.org/supp.pdf">Supplement</a><script type="application/ld+json">{broken</script>`);
    const found = await page.evaluate(read('scripts/GewuBrowserCaptureProbe.js'));
    assert.equal(found.metadata.title,'Quantum sensing with light'); assert.equal(found.metadata.doi,'10.1234/fixture');
    assert.deepEqual(found.metadata.authors,['A. Scientist']); assert.equal(found.pdf_urls.length,2);
    assert.ok(!JSON.stringify(found).includes('never-collect'));
    await page.setContent('<style>*{box-sizing:border-box}body{margin:0}</style><button id="browserMode">Browser</button>');
    await page.addStyleTag({content:read('paper_monitor/browser_ui.css')});
    await page.addStyleTag({content:':root{--accent:#1f4f7a;--line:#d9dee8;--muted:#667085;--ink:#18212f;--panel:#fff;--paper:#f7f8fb}'});
    await page.addStyleTag({content:workspaceHTML.match(/\.library-add-control \{[^}]+\}/)[0]+workspaceHTML.split('    .library-add-menu {')[1].split('    @keyframes actionBusySpin')[0].replace(/^/, '.library-add-menu {')});
    await page.evaluate(() => {
      window.commands=[]; window.calls=[];
      window.state={mode:'browser',libraryLoaded:true,libraryRootId:1,paperFilesByPaperId:{paper:{paper_id:'paper',files:[]}},paperFileRequests:{},libraryItems:[{id:202,paper_id:'paper',folder_id:21},{id:101,paper_id:'paper',folder_id:7}]};
      window.pickerFolders=[{id:1,name:'Library',parent_id:null},{id:4,name:'unsorted',parent_id:1,is_unsorted:true},{id:5,name:'Reading',parent_id:1},{id:6,name:'Quantum',parent_id:5},{id:7,name:'Experiments',parent_id:6},{id:8,name:'Recycle',parent_id:1,is_recycle:true},{id:9,name:'Discarded',parent_id:8},{id:20,name:'Project Space',parent_id:null},{id:21,name:'Space Papers',parent_id:20}];
      window.libraryFolderById=id=>state.libraryFolders?.find(f=>f.id===Number(id));
      window.libraryChildFolders=id=>(state.libraryFolders||[]).filter(f=>f.parent_id===Number(id));
      window.libraryFolderIsWithin=(id,root)=>{const seen=new Set();while(id&&!seen.has(id)){if(id===root)return true;seen.add(id);id=libraryFolderById(id)?.parent_id;}return false;};
      window.libraryRecycleFolderId=()=>8; window.libraryUnsortedFolderId=()=>4;
      window.rebuildLibraryIndexes=()=>{};
      window.compareLibraryOrder=(a,b)=>a.id-b.id;
      window.escapeHtml=window.escapeAttr=value=>String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
      window.$=id=>document.getElementById(id);
      window.librarySearchTimer=0;
      window.updatePaperState=(id,paper)=>{state.updatedPaper=paper;};
      window.libraryItemById=id=>state.libraryItems.find(item=>item.id===Number(id));
      window.firstLibraryItemForPaper=id=>state.libraryItems.find(item=>item.paper_id===id);
      window.refreshLibrarySnapshotForNavigation=async()=>{if(window.failNavigation) throw Error('Library unavailable. Try again.');};
      window.libraryDisplayRootId=()=>state.libraryTab==='workspace-0'?20:1;
      window.setLibraryColumnSelection=(parent,entry)=>{(state.columnSelections ||= {})[parent]=entry;};
      window.requestLibraryColumnReveal=id=>{state.revealedFolder=id;};
      window.setPrimaryView=view=>{gewuBrowser.setActive(view==='browser');};
      window.clearLibraryRangeSelection=()=>{};
      window.renderLibrary=()=>{};
      window.refreshLibraryQuickLookForSelection=()=>{};
      window.monitorSaves=[]; window.addPaperToLibrary=(article,id,options)=>monitorSaves.push({id,...options});

      window.webkit={messageHandlers:{browser:{postMessage(value){commands.push(value);}}}};
      window.review={token:'capture-token',upload_token:'upload-token',paper:{paper_id:'paper',title:'Quantum sensing with light',existing:false,gewu_key:'gw_1234567890',doi:'10.1234/fixture',journal:'Fixture Journal'},snapshot:{snapshot_id:'native-snapshot',url:'https://example.org/article',is_pdf:false,pdf_urls:['https://example.org/paper.pdf']},can_save:true,pdf_ready:false,pdf_name:'Article.pdf',identifier:'10.1234/fixture',destination:{folder_id:4,title:'Library / unsorted',reused:false},folders:[{id:1,title:'Library'},{id:4,title:'Library / unsorted'},{id:5,title:'Library / Reading'},{id:6,title:'Library / Reading / Quantum'},{id:7,title:'Library / Reading / Quantum / Experiments'},{id:20,title:'Project Space'},{id:21,title:'Project Space / Space Papers'}]};
      window.fetch=async (url,options) => {
        if(url==='/api/library/add-targets') return {ok:true,json:async()=>({root_id:1,folders:structuredClone(pickerFolders),workspace_tabs:[{root_folder_id:20,label:'Project Space'}]})};
        const payload=JSON.parse(options.body); calls.push(payload);
        if (payload.action==='capture_begin') {
          if(window.deferBegin) await new Promise(resolve=>{window.releaseBegin=resolve;});
          return {ok:true,json:async()=>structuredClone(review)};
        }
        if (payload.action==='capture_review') {
          if(payload.target_key==='gw_0000000000') return {ok:false,json:async()=>({error:'Gewu Key not found.'})};
          if(payload.target_key) return {ok:true,json:async()=>({...structuredClone(review),target_key:payload.target_key,paper:{...review.paper,paper_id:'target',existing:true,gewu_key:payload.target_key},destination:{folder_id:21,reused:true},pdf_ready:true,can_save:true})};
          return {ok:true,json:async()=>({...structuredClone(review),pdf_ready:true,can_save:true,suggested_file_type:'published_version',file_type_reason:'Publisher article PDF; the PDF DOI matches.'})};
        }
        if (payload.action==='capture_save') return {ok:true,json:async()=>({ok:true,paper_id:'paper',item_id:payload.folder_id===21?202:101,folder_id:payload.folder_id,gewu_key:'gw_1234567890',pdf_saved:payload.include_pdf,duplicate_file:window.duplicateFile||false,paper_files:[{paper_id:'paper',files:payload.include_pdf?[{id:9,file_type:'unknown',exists:true}]:[],paper:{paper_id:'paper',title:'Quantum sensing with light'}}]})};
        return {ok:true,json:async()=>({bookmarks:[],history:[],preferences:{},ok:true})};
      };
    });
    await page.addScriptTag({content:pickerFunctions.map(workspaceFunction).join('\n')});
    await page.addScriptTag({content:read('paper_monitor/browser_keyboard.js')});
    await page.addScriptTag({content:read('paper_monitor/browser_ui.js')});
    await page.evaluate(() => {gewuBrowser.setActive(true); gewuBrowserNativeEvent({event:'state',tab_id:'t1',url:'https://example.org/article',title:'Article',home:false,loading:false});});
    async function start() {
      await page.click('#browserSaveGewu');
      return page.evaluate(()=>commands.filter(c=>c.action==='capture').at(-1).request_id);
    }
    async function deliver(id) {await page.evaluate(id=>gewuBrowserNativeEvent({event:'capture-metadata',request_id:id,snapshot:review.snapshot}),id);}
    async function details() {
      if(await page.getAttribute('[data-capture="details"]','aria-expanded')==='false') await page.click('[data-capture="details"]');
    }
    let id=await start();
    await deliver('stale-request'); assert.equal(await page.locator('[data-capture="save"]').isDisabled(),true);
    await deliver(id); await page.waitForFunction(()=>!document.querySelector('[data-capture="save"]').disabled);
    assert.ok(await page.evaluate(()=>commands.filter(c=>c.action==='layout').at(-1).visible===false),'native view hidden behind dialog');
    assert.equal(await page.getAttribute('[data-capture="details"]','aria-expanded'),'false');
    assert.equal(await page.locator('[name="identifier"]').isVisible(),false);
    assert.equal(await page.locator('[name="file_type"]').isVisible(),true);
    assert.equal(await page.locator('[data-capture="folder"]').isVisible(),true);
    assert.match(await page.locator('.capture-status').innerText(),/Article only/,'no-PDF saves remain explicit when details are hidden');
    const backdrop=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=80;c.height=60;const x=c.getContext('2d');x.fillStyle='#6495ed';x.fillRect(0,0,80,60);return c.toDataURL('image/jpeg');});
    await page.evaluate(image=>gewuBrowserNativeEvent({event:'capture-backdrop',request_id:'stale',image}),backdrop);
    assert.equal(await page.locator('.capture-page-backdrop').getAttribute('src'),null);
    await page.evaluate(({request_id,image})=>gewuBrowserNativeEvent({event:'capture-backdrop',request_id,image}),{request_id:id,image:backdrop});
    assert.equal(await page.locator('.capture-page-backdrop').isVisible(),true);
    assert.equal(await page.locator('.capture-page-backdrop').evaluate(e=>getComputedStyle(e).filter),'blur(5px)');
    await details();
    await page.click('[data-capture="details"]'); await details();
    assert.equal(await page.inputValue('[name="identifier"]'),'10.1234/fixture','details preserve article identity');
    await page.click('[data-capture="details"]');
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').length),0,'review never saves');
    for(const [width,height] of [[1200,900],[980,640],[700,560]]) {
      await page.setViewportSize({width,height});
      const fit=await page.locator('.browser-capture-panel').evaluate(e=>({width:e.getBoundingClientRect().width,right:e.getBoundingClientRect().right,scroll:e.scrollWidth,client:e.clientWidth}));
      assert.ok(fit.right<=width); assert.ok(fit.scroll<=fit.client+1);
    }
    await page.setViewportSize({width:1200,height:900});
    await page.screenshot({path:'/private/tmp/gewu-capture-ui.png'});
    await page.click('[data-capture="folder"]');
    const menu=page.locator('.browser-capture-folder-menu.open');
    await menu.locator('[data-workspace-root-id="1"].library-add-folder-option').waitFor();
    assert.equal(await menu.locator('.library-add-column').count(),2);
    assert.equal(await menu.locator('[data-folder-id="8"]').count(),0,'Recycle stays excluded');
    assert.equal(await menu.locator('[data-folder-id="7"]').count(),0,'nested folders are not flattened');
    await menu.locator('button[data-folder-id="5"]').click();
    await menu.locator('button[data-folder-id="6"]').click();
    await menu.locator('button[data-folder-id="7"]').click();
    assert.equal(await menu.locator('.library-add-column').count(),4);
    assert.match(await menu.locator('.library-add-selected-path').innerText(),/My Library \/ Reading \/ Quantum \/ Experiments/);
    assert.equal(await page.inputValue('[name="folder_id"]'),'4','navigation alone does not change destination');
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').length),0);
    await page.screenshot({path:'/private/tmp/gewu-capture-picker.png'});
    await menu.locator('[data-action="confirm-library-add"]').click();
    assert.equal(await page.inputValue('[name="folder_id"]'),'7');
    assert.equal(await page.evaluate(()=>monitorSaves.length),0,'capture picker never calls Monitor ingestion');
    await page.click('[data-capture="folder"]');
    await menu.locator('button[data-folder-id="7"]').waitFor();
    await menu.locator('button[data-workspace-root-id="20"]').click();
    await menu.locator('button[data-folder-id="21"]').click();
    await menu.locator('[data-action="cancel-library-add"]').click();
    assert.equal(await page.inputValue('[name="folder_id"]'),'7','picker cancellation preserves destination');
    await page.click('[data-capture="folder"]');
    await menu.locator('button[data-folder-id="7"]').waitFor();
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.browser-capture-panel').count(),1,'Escape closes picker before capture');
    for (const [width,height] of [[980,640],[700,560]]) {
      await page.setViewportSize({width,height});
      await page.click('[data-capture="folder"]');
      await menu.locator('button[data-folder-id="7"]').waitFor();
      const bounds=await menu.evaluate(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom};});
      assert.ok(bounds.left>=0&&bounds.right<=width&&bounds.top>=0&&bounds.bottom<=height,'folder picker stays within viewport');
      await menu.locator('[data-action="cancel-library-add"]').click();
    }
    await page.setViewportSize({width:1200,height:900});

    await details();
    await page.screenshot({path:'/private/tmp/gewu-capture-details-expanded.png'});
    await details(); await page.click('[data-capture="download"]');
    assert.equal(await page.locator('[data-capture="save"]').isDisabled(),true);
    const transfer=await page.evaluate(()=>commands.filter(c=>c.action==='capture-download').at(-1));
    assert.equal(transfer.allow_download,true,'article link download requires an explicit click');
    assert.equal(transfer.snapshot_id,'native-snapshot'); assert.equal(transfer.upload_token,'upload-token');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-pdf',token:'capture-token',error:'Publisher unavailable.'}));
    assert.equal(await page.locator('[data-capture="save"]').isDisabled(),false,'metadata-only save stays available');
    await page.click('[data-capture="download"]');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-pdf',token:'capture-token',error:''}));
    await page.waitForFunction(()=>document.querySelector('[name="include_pdf"]').checked);
    await page.click('[data-capture="details"]');
    assert.equal(await page.locator('.capture-status').isVisible(),false,'ready PDF needs no instruction paragraph');
    assert.equal(await page.locator('[data-capture="save"]').isDisabled(),false);
    await details();
    assert.equal(await page.inputValue('[name="file_type"]'),'published_version','review selects the detected main PDF type');
    await page.selectOption('[name="file_type"]','preprint');
    assert.equal(await page.inputValue('[name="folder_id"]'),'7','selection survives review');
    await page.fill('[name="identifier"]','10.1234/changed'); assert.equal(await page.locator('[data-capture="save"]').isDisabled(),true);
    await page.fill('[name="identifier"]','10.1234/fixture'); await page.click('[data-capture="lookup"]');
    await page.waitForFunction(()=>!document.querySelector('[data-capture="save"]').disabled);
    assert.equal(await page.inputValue('[name="file_type"]'),'preprint','Identify preserves an explicit file type');
    await page.selectOption('[name="file_type"]','published_version'); await page.click('[data-capture="save"]');
    await page.waitForFunction(()=>!document.querySelector('.browser-capture-panel'));
    const saved=await page.evaluate(()=>calls.filter(c=>c.action==='capture_save'));
    assert.equal(saved.length,1); assert.equal(saved[0].folder_id,7); assert.equal(saved[0].include_pdf,true);
    assert.equal(saved[0].folder_selection_explicit,true);
    assert.equal(saved[0].file_type_manual,true);
    assert.equal(await page.evaluate(()=>state.libraryLoaded),false);
    assert.equal(await page.evaluate(()=>state.paperFilesByPaperId.paper.files.length),1,'saving replaces a cached empty Paper Files list');
    assert.equal(await page.evaluate(()=>state.updatedPaper.paper_id),'paper');
    assert.equal(await page.evaluate(()=>state.mode),'browser','save keeps the current webpage open');
    await page.locator('#browserMessageAction').filter({hasText:'Show in Library'}).waitFor();
    for (const [width,height] of [[700,560],[980,640],[1200,900]]) {
      await page.setViewportSize({width,height});
      const button=await page.locator('#browserMessageAction').boundingBox();
      assert.ok(button.x>=0&&button.x+button.width<=width,'Show in Library fits the window');
    }
    await page.screenshot({path:'/private/tmp/gewu-capture-save-success.png'});
    await page.evaluate(()=>{failNavigation=true;});
    await page.click('#browserMessageAction');
    await page.waitForFunction(()=>document.querySelector('#browserMessageText').textContent.includes('Library unavailable'));
    assert.equal(await page.locator('#browserMessageAction').isDisabled(),false,'navigation failure leaves a retryable jump');
    await page.evaluate(()=>{failNavigation=false;});
    await page.click('#browserMessageAction');
    await page.waitForFunction(()=>state.mode==='library');
    assert.equal(await page.evaluate(()=>state.libraryActiveFolderId),7,'jump uses the saved placement instead of the first occurrence');
    assert.equal(await page.evaluate(()=>state.librarySelection.id),101);
    assert.equal(await page.evaluate(()=>state.libraryTab),'library');
    await page.evaluate(()=>{state.mode='browser';gewuBrowser.setActive(true);duplicateFile=true;});
    id=await start(); await deliver(id);
    await page.waitForFunction(()=>!document.querySelector('[data-capture="save"]').disabled);
    await page.click('[data-capture="folder"]');
    await menu.locator('button[data-workspace-root-id="20"]').click();
    await menu.locator('button[data-folder-id="21"]').click();
    await menu.locator('[data-action="confirm-library-add"]').click();
    await details(); await page.click('[data-capture="download"]');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-pdf',token:'capture-token',error:''}));
    await page.waitForFunction(()=>document.querySelector('[name="include_pdf"]').checked);
    await page.click('[data-capture="save"]');
    await page.waitForFunction(()=>!document.querySelector('.browser-capture-panel'));
    assert.match(await page.locator('#browserMessageText').innerText(),/Existing PDF reused/);
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').at(-1).file_type),'published_version');
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').at(-1).file_type_manual),false);
    assert.equal(await page.evaluate(()=>state.paperFilesByPaperId.paper.files.length),1);
    await page.click('#browserMessageAction');
    await page.waitForFunction(()=>state.mode==='library');
    assert.equal(await page.evaluate(()=>state.libraryActiveFolderId),21);
    assert.equal(await page.evaluate(()=>state.libraryTab),'workspace-0');
    assert.equal(await page.evaluate(()=>state.librarySelection.id),202);
    await page.evaluate(()=>{state.mode='browser';gewuBrowser.setActive(true);});

    // An already placed paper defaults to its existing folder, including after
    // PDF identification; merely opening/cancelling the picker is not consent
    // to add another placement. The backend separately verifies this hint.
    await page.evaluate(()=>{
      review.paper.existing=true;review.destination={folder_id:7,item_id:101,reused:true};
      state.librarySelection={type:'item',id:101};
      review.snapshot.origin_library_item_id=101;
    });
    id=await start(); await deliver(id);
    await page.waitForFunction(()=>!document.querySelector('[data-capture="save"]').disabled);
    assert.equal(await page.inputValue('[name="folder_id"]'),'7');
    assert.match(await page.locator('[data-capture="folder"]').innerText(),/Experiments/);
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_begin').at(-1).snapshot.origin_library_item_id),101);
    await page.click('[data-capture="folder"]');
    await menu.locator('button[data-folder-id="7"]').waitFor();
    await menu.locator('[data-action="cancel-library-add"]').click();
    await details(); await page.click('[data-capture="download"]');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-pdf',token:'capture-token',error:''}));
    await page.waitForFunction(()=>document.querySelector('[name="include_pdf"]').checked);
    assert.equal(await page.inputValue('[name="folder_id"]'),'7');
    await page.click('[data-capture="save"]');
    await page.waitForFunction(()=>!document.querySelector('.browser-capture-panel'));
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').at(-1).folder_selection_explicit),false);
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').at(-1).folder_id),7);
    await page.evaluate(()=>{review.paper.existing=false;review.destination={folder_id:4,title:'Library / unsorted',reused:false};});

    await page.evaluate(()=>{state.browserCaptureDetailsExpanded=true;});
    id=await start(); await deliver(id);
    await page.waitForFunction(()=>!document.querySelector('[data-capture="save"]').disabled);
    assert.equal(await page.getAttribute('[data-capture="details"]','aria-expanded'),'true','saved preference controls new dialogs');
    await page.click('[data-capture="details"]'); await page.click('[data-capture="cancel"]');
    assert.equal(await page.evaluate(()=>state.browserCaptureDetailsExpanded),true,'one-dialog toggle does not change saved preference');
    await page.evaluate(()=>{state.browserCaptureDetailsExpanded=false;review.can_save=false;review.paper=null;review.conflict='The identifiers conflict. Review the article.';});
    id=await start();await deliver(id);
    await page.waitForFunction(()=>document.querySelector('.capture-status').textContent.includes('identifiers conflict'));
    assert.equal(await page.getAttribute('[data-capture="details"]','aria-expanded'),'true','blocked identity exposes repair controls');
    assert.equal(await page.locator('[data-capture="save"]').isDisabled(),true);
    await page.click('[data-capture="details"]');
    assert.equal(await page.locator('.capture-status.error').isVisible(),true,'a collapsed conflict remains visible');
    await page.click('[data-capture="cancel"]');
    await page.evaluate(()=>{review.can_save=true;review.paper={paper_id:'paper',title:'Quantum sensing with light',gewu_key:'gw_1234567890'};review.conflict='';});

    // Opening an inline PDF never grants permission to request it again.
    await page.evaluate(()=>{review.snapshot.is_pdf=true;});
    id=await start(); await deliver(id);
    await page.waitForFunction(()=>commands.filter(c=>c.action==='capture-download').at(-1).allow_download===false);
    assert.match(await page.locator('.capture-status').innerText(),/Reading the loaded PDF/);
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-progress',token:'capture-token',message:'Reading PDF information…'}));
    assert.match(await page.locator('.capture-status').innerText(),/Reading PDF information/);
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-progress',token:'old-token',message:'Stale progress'}));
    assert.doesNotMatch(await page.locator('.capture-status').innerText(),/Stale/);
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-pdf',token:'capture-token',error:'Loaded original unavailable. No new download was started.'}));
    await details();
    assert.equal(await page.locator('[data-capture="download"]').innerText(),'Use Loaded PDF');
    await page.click('[data-capture="download"]');
    assert.equal(await page.evaluate(()=>commands.filter(c=>c.action==='capture-download').at(-1).allow_download),false,'retry still must not redownload');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-pdf',token:'capture-token',error:'Not ready.'}));
    await page.click('[data-capture="redownload"]');
    assert.equal(await page.evaluate(()=>commands.filter(c=>c.action==='capture-download').at(-1).allow_download),true,'explicit download again grants network permission');
    await page.click('[data-capture="cancel"]');
    await page.evaluate(()=>{gewuBrowserNativeEvent({event:'capture-progress',token:'capture-token',message:'Late'});review.snapshot.is_pdf=false;});
    assert.equal(await page.locator('.browser-capture-panel').count(),0);
    id=await start();await deliver(id);await details();
    await page.fill('[name="target_key"]','gw_abcdef0123');
    assert.equal(await page.locator('[data-capture="save"]').isDisabled(),true);
    await page.press('[name="target_key"]','Enter');
    await page.waitForFunction(()=>document.querySelector('.capture-target-status').textContent==='Target updated');
    assert.match(await page.locator('.capture-identity').innerText(),/Existing article · gw_abcdef0123/);
    assert.match(await page.locator('[data-capture="folder"]').innerText(),/Project Space \/ Space Papers/);
    assert.notEqual(await page.evaluate(()=>document.activeElement.name),'target_key');
    await page.fill('[name="target_key"]','gw_0000000000');await page.press('[name="target_key"]','Enter');
    await page.waitForFunction(()=>document.querySelector('.capture-status').textContent.includes('Key not found'));
    assert.equal(await page.locator('[data-capture="save"]').isDisabled(),true);
    await page.click('[data-capture="automatic"]');
    await page.waitForFunction(()=>!document.querySelector('[data-capture="save"]').disabled);
    await page.click('[data-capture="cancel"]');
    await page.evaluate(()=>{review.snapshot.loaded_pdf_urls=['https://example.org/paper.pdf'];review.snapshot.origin_library_item_id=202;});
    id=await start();await deliver(id);
    await page.waitForFunction(()=>commands.filter(c=>c.action==='capture-download').at(-1)?.allow_download===false);
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_begin').at(-1).snapshot.origin_library_item_id),202);
    assert.equal(await page.evaluate(()=>commands.filter(c=>c.action==='capture-download').at(-1).url),'https://example.org/paper.pdf');
    await page.click('[data-capture="cancel"]');
    await page.evaluate(()=>{delete review.snapshot.loaded_pdf_urls;delete review.snapshot.origin_library_item_id;});

    await page.evaluate(()=>{deferBegin=true;});
    id=await start(); await deliver(id);
    await page.waitForFunction(()=>typeof releaseBegin==='function');
    await page.click('[data-capture="cancel"]'); await page.evaluate(()=>releaseBegin());
    await page.waitForFunction(()=>calls.filter(c=>c.action==='capture_cancel').length>=2);
    assert.equal(await page.locator('.browser-capture-panel').count(),0);
    await page.evaluate(async()=>{
      const article=document.createElement('article');article.innerHTML='<button data-action="add-library">Add to Library</button><div class="library-add-menu" data-role="library-add-menu"></div>';document.body.append(article);
      await openLibraryAddMenu(article,'monitor-paper',article.querySelector('button'));
    });
    const monitorMenu=page.locator('.library-add-menu.open');
    await monitorMenu.locator('button[data-folder-id="5"]').click();
    await monitorMenu.locator('[data-action="confirm-library-add"]').click();
    assert.deepEqual(await page.evaluate(()=>monitorSaves),[{id:'monitor-paper',folderId:5}],'Monitor Add to Library still saves directly');
    await page.evaluate(()=>{deferBegin=false;});
    id=await start(); await deliver(id);
    await page.waitForFunction(()=>!document.querySelector('[data-capture="save"]').disabled);
    for (const value of ['expression_of_concern','withdrawal_notice','addendum','retraction_notice']) {
      await page.selectOption('[name="file_type"]', value);
      assert.equal(await page.inputValue('[name="file_type"]'), value, 'notice types are selectable in Browser');
    }
    await details(); await page.click('[data-capture="download"]');
    await page.evaluate(()=>gewuBrowserNativeEvent({event:'capture-pdf',token:'capture-token',error:''}));
    await page.waitForFunction(()=>document.querySelector('[name="include_pdf"]').checked);
    await page.click('[data-capture="save"]');
    await page.waitForFunction(()=>!document.querySelector('.browser-capture-panel'));
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').at(-1).file_type),'retraction_notice');
    assert.equal(await page.evaluate(()=>calls.filter(c=>c.action==='capture_save').at(-1).file_type_manual),true);
    assert.deepEqual(errors,[]);
    console.log('Capture metadata, privacy, review/save/cancel, retry, stale events, cache refresh, exact Library/Space navigation and three viewport sizes passed.');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exit(1);});
